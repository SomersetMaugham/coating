"""Monte-Carlo manufacturing-tolerance analysis.

Each sample perturbs, per layer and independently, the thickness, eps and mu
(slabs) or the sheet impedance (sheets) by a relative error drawn from a
normal distribution (tolerance = 1 sigma) or a uniform one (+/- tolerance).
With a loss tolerance set (eps_loss / mu_loss), the real part and the loss part
of eps (mu) get their own errors, so the loss tangent varies as well; with
None the whole complex value is scaled by one factor (tan delta fixed).  The
real-part and loss errors are independent by default; ``loss_correlation`` (rho)
couples them, e.g. rho > 0 for a filler content that raises eps' and eps'' together.  A layer can
override rho through ``per_layer[uid]["loss_correlation"]``.

``material_params`` perturbs material parameters themselves (a mixture's volume fraction, a Debye/Lorentz term's
f0, ...), so a process error can move a relaxation or a resonance along the frequency axis, which a constant
factor on eps(f) cannot.  Each entry is one draw per sample for that material (a batch error): every layer and every
mixture that uses the material sees the same value, and the per-layer eps/mu factors still apply on top.  These
draws come after all per-layer draws, so files without entries give the same samples as before.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

import numpy as np
from scipy.special import ndtr, ndtri

from coating_studio.core.solver import solve
from coating_studio.core.structure import SheetLayer, SlabLayer
from coating_studio.project import Project, ToleranceSettings


class _Stop(Exception):
    pass


TOLERANCE_MAX_POINTS = 301  # frequency points of a tolerance run (GUI and CLI share this grid)


def tolerance_frequencies(project: Project):
    """Frequency grid of a tolerance run: the sweep grid, capped at TOLERANCE_MAX_POINTS points."""
    return project.sweep.freq_grid(min(project.sweep.n_f, TOLERANCE_MAX_POINTS))


def yield_intervals(project: Project):
    """Frequency intervals of the yield criterion: the custom band if set, otherwise the bands of the
    enabled optimisation targets (their union - not the envelope, which would include the gap
    between disjoint bands)."""
    s = project.tolerance
    if s.band_min and s.band_max and s.band_max > s.band_min:
        return [(s.band_min, s.band_max)]
    return project.optimization.frequency_intervals() or [(project.sweep.f_min, project.sweep.f_max)]


def yield_band(project: Project):
    """Envelope of ``yield_intervals`` (for display in the band fields)."""
    iv = yield_intervals(project)
    return min(a for a, _ in iv), max(b for _, b in iv)


@dataclass
class ToleranceResult:
    f: np.ndarray
    nominal_db: np.ndarray
    median_db: np.ndarray
    lower_db: np.ndarray
    upper_db: np.ndarray
    worst_db: np.ndarray  # per sample, worst in band
    yield_fraction: float  # samples whose in-band worst <= target
    n_samples: int
    stopped: bool = False
    # What the result was computed with, so plots and reports stay true after the settings change: a deep copy of
    # the tolerance settings (for a target row: its angle, polarisation and criterion) and the frequency intervals
    # the yield was judged on.  None on results built by hand (callers then fall back to the project's settings).
    settings: ToleranceSettings | None = None
    band: list | None = None
    # [{"path": [...], "n": samples whose drawn value was clipped to the parameter's bounds}] per material parameter;
    # a large n means the tolerance is wide for that parameter and the effective distribution is not the requested one
    clipped: list = field(default_factory=list)


def result_settings(r, project: Project) -> ToleranceSettings:
    """The settings ``r`` was computed with; the project's current ones for a result that does not record them."""
    return r.settings if getattr(r, "settings", None) is not None else project.tolerance


def result_band(r, project: Project):
    """The yield intervals of a ToleranceResult; the project's yield intervals if it does not record them."""
    return r.band if getattr(r, "band", None) is not None else yield_intervals(project)


def _snapshot(s: ToleranceSettings, **changes) -> ToleranceSettings:
    """Deep copy of ``s`` (per_layer included), with ``changes`` applied."""
    return ToleranceSettings.from_dict({**s.to_dict(), **changes})


@dataclass
class CornerResult:
    """Tolerance analysis at several (target, angle, polarisation) points that share the same samples.

    ``angle_mode`` "corners": the two ends of each enabled target's angle range; "grid": the target's angle grid
    (``BandTarget.n_angle`` points, or the ``n_angle`` override).  ``fallback_targets``: indices of targets whose
    range has fewer than two grid points, evaluated at the two ends instead."""

    corners: list  # [(target index, target name, angle deg, pol, target dB, ToleranceResult)]
    joint_yield_fraction: float | None  # samples that meet every row's criterion
    n_samples: int
    stopped: bool = False
    angle_mode: str = "corners"
    fallback_targets: list = field(default_factory=list)
    settings: ToleranceSettings | None = None  # deep copy of the settings of the run (seed, tolerances, samples)
    clipped: list = field(default_factory=list)  # as ToleranceResult.clipped

    @property
    def worst(self):
        """Index into ``corners`` of the row with the lowest yield."""
        return min(range(len(self.corners)), key=lambda i: self.corners[i][5].yield_fraction)

    def per_target(self):
        """{target index: index into ``corners`` of that target's lowest-yield row}, in target order."""
        out = {}
        for i, row in enumerate(self.corners):
            j = out.get(row[0])
            if j is None or row[5].yield_fraction < self.corners[j][5].yield_fraction:
                out[row[0]] = i
        return out


ANGLE_MODES = ("corners", "grid")


def target_angles(t, mode="corners", n_angle=None):
    """(angles [deg], fell_back) of one target.  A target without an angle range has one angle.  "corners": both
    ends; "grid": ``n_angle`` (default ``t.n_angle``) evenly spaced angles, or both ends when that is below 2
    (the optimiser then looks at angle_min only, so the ends are the stricter choice)."""
    lo, hi = float(t.angle_min), float(t.angle_max)
    if not hi > lo:
        return [lo], False
    if mode == "corners":
        return [lo, hi], False
    if mode != "grid":
        raise ValueError(f"unknown angle mode {mode!r}")
    n = int(t.n_angle if n_angle is None else n_angle)
    if n < 2:
        return [lo, hi], True
    return [float(a) for a in np.linspace(lo, hi, n)], False


def target_rows(project: Project, mode="corners", n_angle=None):
    """([(target index, target, angle, pol)], fallback target indices) for the enabled targets."""
    rows, fallback = [], []
    for ti, t in enumerate(project.optimization.enabled_targets()):
        if not t.pols or any(q not in ("TE", "TM") for q in t.pols):
            raise ValueError(f"target {ti + 1}: polarisations must be TE and/or TM")
        angles, fell_back = target_angles(t, mode, n_angle)
        if fell_back:
            fallback.append(ti)
        rows += [(ti, t, ang, pol) for ang in angles for pol in t.pols]
    return rows, fallback


def target_corners(project: Project):
    """(target index, target, angle, pol) for the angle ends x polarisations of every enabled target."""
    return target_rows(project, "corners")[0]


def run_tolerance_targets(project: Project, f, mode="corners", n_angle=None, target_db=None, progress=None,
                          should_stop=None) -> CornerResult:
    """Tolerance analysis at every (target, angle, polarisation) row of ``target_rows``.  Each row's yield band is its
    target's band and its criterion the target's goal (or ``target_db``).  The samples are drawn once, and every
    sample is solved once per distinct angle, so every row sees the same samples and the joint yield is exact.  Each
    row equals ``run_tolerance`` at that angle and polarisation bit for bit (same draws, same per-angle solve).

    ``progress(done, total) -> bool`` is called after each sample and may return True to stop; ``should_stop()``
    is checked before every sample after the first.  At least one sample is always solved."""
    plan, fallback = target_rows(project, mode, n_angle)
    if not plan:
        raise ValueError("no enabled target to take angles from")
    s = _snapshot(project.tolerance)
    f = np.asarray(f, dtype=float)
    n = int(s.n_samples)
    need = {}
    for _ti, _t, ang, pol in plan:
        need.setdefault(ang, set()).add(pol)

    def rl_db(perturb=None, materials=None):
        out = {}
        for ang, pset in need.items():
            pols = tuple(q for q in ("TE", "TM") if q in pset)
            res = solve(project.structure, materials or project.materials, f, ang, pols=pols, perturb=perturb)
            for q in pols:
                out[ang, q] = 10 * np.log10(np.maximum(res.quantity("R", q)[:, 0], 1e-30))
        return out

    nominal = rl_db()
    rng = np.random.default_rng(s.seed)
    factors = sample_factors(project, s, rng, n)
    mats = MaterialSampler(project, s, rng, n)
    samples = {key: [] for key in nominal}
    stopped = False
    for k in range(n):
        if k and should_stop is not None and should_stop():
            stopped = True
            break
        perturb = {uid: {key: arr[k] for key, arr in d.items()} for uid, d in factors.items()}
        for key, db in rl_db(perturb, mats.at(k)).items():
            samples[key].append(db)
        # a stop request after the last sample does not make a complete run "stopped"
        if progress is not None and progress(k + 1, n) and k + 1 < n:
            stopped = True
            break
    rows, passes = [], []
    for ti, t, ang, pol in plan:
        tdb = float(target_db) if target_db is not None else t.goal_db
        arr = np.array(samples[ang, pol]) if n else nominal[ang, pol][None, :]  # n_samples = 0: as run_tolerance
        r = _summarise(f, nominal[ang, pol], arr, [(t.f_min, t.f_max)], _snapshot(s, angle=ang, pol=pol, target_db=tdb),
                       tdb, stopped)
        rows.append((ti, t.name, ang, pol, tdb, r))
        passes.append(np.asarray(r.worst_db) <= tdb)
    joint = float(np.mean(np.all(passes, axis=0)))
    used = rows[0][5].n_samples if n else 0
    clipped = mats.clipped(used)
    for row in rows:
        row[5].clipped = clipped
    return CornerResult(rows, joint, rows[0][5].n_samples, stopped, mode, fallback, s, clipped)


def run_tolerance_corners(project: Project, f, target_db=None, progress=None, should_stop=None) -> CornerResult:
    """``run_tolerance_targets`` at the angle ends of every enabled target (``progress(done, total)``)."""
    return run_tolerance_targets(project, f, "corners", target_db=target_db, progress=progress,
                                 should_stop=should_stop)


def _draw_delta(rng, dist, tol, n):
    """Raw deviations: N(0, tol) or U(-tol, tol); zeros (and no draw) for tol <= 0."""
    if tol <= 0:
        return np.zeros(n)
    if dist == "uniform":
        return rng.uniform(-tol, tol, n)
    return rng.normal(0.0, tol, n)


def _draw(rng, dist, tol, n):
    """Relative factors 1 + deviation (the same arithmetic and draws as before ``_draw_delta`` existed)."""
    if tol <= 0:
        return np.ones(n)
    return 1.0 + _draw_delta(rng, dist, tol, n)


def material_param_info(project: Project, path):
    """ParamInfo of material parameter ``path`` (``("material", name, *key)``); ValueError if there is none."""
    path = tuple(path)
    mat = project.materials.get(path[1]) if len(path) >= 3 and path[0] == "material" else None
    info = next((p for p in mat.params() if p.key == path[2:]), None) if mat is not None else None
    if info is None:
        raise ValueError(f"tolerance: no material parameter {list(path)!r}")
    return info


class MaterialSampler:
    """Per-sample material mappings for ``ToleranceSettings.material_params``.

    The relative errors are drawn in the constructor (after ``sample_factors``, in list order, so a file without
    entries draws exactly as before).  ``at(k)`` applies sample k's errors to the project's *current* values - the
    optimiser's robust mode moves the nominal values between calls - each value clipped to the parameter's physical
    bounds (a volume fraction stays in 0..1, or below an Odelevskiy mixture's percolation threshold).  It returns the
    material mapping of sample k, or None when nothing is perturbed (the solver then uses the project's)."""

    def __init__(self, project: Project, s: ToleranceSettings, rng, n):
        self.project = project
        self.entries = []
        for e in s.material_params:
            tol = float(e["tol"])
            if not (np.isfinite(tol) and tol >= 0):
                raise ValueError(f"tolerance of {e['path']!r} must be a non-negative number, got {e['tol']!r}")
            path = tuple(e["path"])
            info = material_param_info(project, path)
            lo = -np.inf if info.lower is None else info.lower
            hi = np.inf if info.upper is None else info.upper
            mode = e.get("mode", "relative")
            if mode == "absolute":  # deviations in the parameter's SI unit, added to the current nominal value
                arr = _draw_delta(rng, s.distribution, tol, n)
            elif mode == "relative":
                arr = _draw(rng, s.distribution, tol, n)
            else:
                raise ValueError(f"tolerance mode of {e['path']!r} must be 'relative' or 'absolute', got {mode!r}")
            self.entries.append((path, mode, arr, lo, hi))

    def clipped(self, n):
        """[{"path", "n"}]: how many of the first ``n`` samples clip each parameter to its bounds (current values)."""
        out = []
        for path, mode, arr, lo, hi in self.entries:
            vals = self._values(path, mode, arr[:n])
            out.append({"path": list(path), "n": int(np.count_nonzero((vals < lo) | (vals > hi)))})
        return out

    def _values(self, path, mode, arr):
        nominal = float(self.project.materials[path[1]].get(path[2:]))
        return nominal + arr if mode == "absolute" else nominal * arr

    def at(self, k):
        if not self.entries:
            return None
        mats = self.project.materials
        copies = {name: mats[name].clone() for name in {p[1] for p, *_ in self.entries}}
        for path, mode, arr, lo, hi in self.entries:
            copies[path[1]].set(path[2:], np.clip(self._values(path, mode, arr[k]), lo, hi))
        return {**mats, **copies}


def _correlate(d_re, tol_re, d_loss, tol_loss, rho, dist):
    """Loss factors correlated with the real-part factors (correlation ``rho``), keeping their own distribution.

    Normal: z = rho*z_re + sqrt(1 - rho^2)*z_loss on the standardised draws, so the Pearson correlation is rho.
    Uniform: the same mixing through a Gaussian copula, so both marginals stay exactly uniform; the Pearson
    correlation is then (6/pi)*asin(rho/2), within 0.02 of rho."""
    w = np.sqrt(max(0.0, 1.0 - rho * rho))
    if dist == "uniform":
        eps = 1e-12
        z_re = ndtri(np.clip(((d_re - 1.0) / tol_re + 1.0) / 2.0, eps, 1 - eps))
        z_l = ndtri(np.clip(((d_loss - 1.0) / tol_loss + 1.0) / 2.0, eps, 1 - eps))
        return 1.0 + tol_loss * (2.0 * ndtr(rho * z_re + w * z_l) - 1.0)
    return 1.0 + tol_loss * (rho * (d_re - 1.0) / tol_re + w * (d_loss - 1.0) / tol_loss)


def sample_factors(project: Project, s: ToleranceSettings, rng, n):
    """Perturbation factors {layer uid: {key: array of n}} for ``n`` samples, drawn from ``rng``.

    The draw order is part of the reproducibility contract (same seed -> same samples as earlier versions)."""
    factors = {}
    for ly in project.structure.layers:
        if isinstance(ly, SlabLayer):
            rho = float(s.tolerance_for(ly.uid, "loss_correlation"))
            if not -1.0 <= rho <= 1.0:
                raise ValueError(f"loss_correlation must be between -1 and 1, got {rho}")
            # Same draws, in the same order, as before loss tolerances existed (bit-identical results
            # for files with eps_loss = mu_loss = None); independent loss draws come afterwards.
            raw = {k: _draw(rng, s.distribution, s.tolerance_for(ly.uid, k), n) for k in ("thickness", "eps", "mu")}
            fac = {k: np.maximum(v, 1e-6) for k, v in raw.items()}
            for part in ("eps", "mu"):
                tol_loss = s.tolerance_for(ly.uid, f"{part}_loss")
                if tol_loss is not None:
                    fac[f"{part}_re"] = fac.pop(part)
                    d_loss = _draw(rng, s.distribution, tol_loss, n)
                    tol_re = s.tolerance_for(ly.uid, part)
                    if rho and tol_loss > 0 and tol_re > 0:  # rho = 0 keeps the independent draws bit for bit
                        d_loss = _correlate(raw[part], tol_re, d_loss, tol_loss, rho, s.distribution)
                    fac[f"{part}_loss"] = np.maximum(d_loss, 1e-6)
            factors[ly.uid] = fac
        elif isinstance(ly, SheetLayer):
            tol = s.tolerance_for(ly.uid, "sheet")
            if ly.is_rlc:
                # R, L and C vary independently, so the resonance moves as it does for a real pattern
                # (scaling Zs as a whole would leave f0 = 1/(2*pi*sqrt(LC)) unchanged).
                factors[ly.uid] = {k: np.maximum(_draw(rng, s.distribution, tol, n), 1e-6)
                                   for k in ("sheet_R", "sheet_L", "sheet_C")}
            else:
                factors[ly.uid] = {"sheet": np.maximum(_draw(rng, s.distribution, tol, n), 1e-6)}
    return factors


def run_tolerance(project: Project, f, settings: ToleranceSettings | None = None,
                  band=None, progress=None) -> ToleranceResult:
    """``band`` = (f_lo, f_hi) or a list of such intervals for the yield criterion (default: all of
    ``f``).  Several intervals are combined as a union, so the gap between disjoint target bands
    does not count against the yield."""
    s = _snapshot(settings or project.tolerance)
    f = np.asarray(f, dtype=float)
    rng = np.random.default_rng(s.seed)
    n = int(s.n_samples)
    pols = ("TE", "TM") if s.pol == "avg" else (s.pol,)

    def rl_db(perturb=None, materials=None):
        res = solve(project.structure, materials or project.materials, f, s.angle, pols=pols, perturb=perturb)
        r = res.quantity("R", "avg" if s.pol == "avg" else s.pol)[:, 0]
        return 10 * np.log10(np.maximum(r, 1e-30))

    nominal = rl_db()
    factors = sample_factors(project, s, rng, n)
    mats = MaterialSampler(project, s, rng, n)
    samples = []
    stopped = False
    try:
        for k in range(n):
            perturb = {uid: {key: arr[k] for key, arr in d.items()} for uid, d in factors.items()}
            samples.append(rl_db(perturb, mats.at(k)))
            if progress is not None and progress(k + 1, n) and k + 1 < n:  # not after the last sample
                raise _Stop
    except _Stop:
        stopped = True
    used = len(samples)
    if not samples:
        samples = [nominal]
    r = _summarise(f, nominal, np.array(samples), band, s, s.target_db, stopped)
    r.clipped = mats.clipped(used)
    return r


def _summarise(f, nominal, arr, band, s, target_db, stopped):
    """ToleranceResult from the per-sample RL curves ``arr`` (samples x f).  ``band`` = (f_lo, f_hi), a list of
    them (a union), or None (all of ``f``); a band without any grid point falls back to all of ``f``.  The result
    records ``s`` and the intervals actually used, always as a list of (lo, hi) pairs."""
    whole = [(float(f[0]), float(f[-1]))]
    if band is None:
        mask, used = np.ones(f.shape, dtype=bool), whole
    else:
        intervals = band if np.ndim(band) == 2 else [band]
        mask = np.zeros(f.shape, dtype=bool)
        for lo, hi in intervals:
            mask |= (f >= lo) & (f <= hi)
        used = [(float(lo), float(hi)) for lo, hi in intervals]
        if not mask.any():
            mask, used = np.ones(f.shape, dtype=bool), whole
    worst = arr[:, mask].max(axis=1)
    return ToleranceResult(
        f=f, nominal_db=nominal, median_db=np.median(arr, axis=0),
        lower_db=np.percentile(arr, s.lower_pct, axis=0), upper_db=np.percentile(arr, s.upper_pct, axis=0),
        worst_db=worst, yield_fraction=float(np.mean(worst <= target_db)), n_samples=len(arr),
        stopped=stopped, settings=s, band=used)
