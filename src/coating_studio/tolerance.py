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
    s = project.tolerance
    f = np.asarray(f, dtype=float)
    n = int(s.n_samples)
    need = {}
    for _ti, _t, ang, pol in plan:
        need.setdefault(ang, set()).add(pol)

    def rl_db(perturb=None):
        out = {}
        for ang, pset in need.items():
            pols = tuple(q for q in ("TE", "TM") if q in pset)
            res = solve(project.structure, project.materials, f, ang, pols=pols, perturb=perturb)
            for q in pols:
                out[ang, q] = 10 * np.log10(np.maximum(res.quantity("R", q)[:, 0], 1e-30))
        return out

    nominal = rl_db()
    factors = sample_factors(project, s, np.random.default_rng(s.seed), n)
    samples = {key: [] for key in nominal}
    stopped = False
    for k in range(n):
        if k and should_stop is not None and should_stop():
            stopped = True
            break
        perturb = {uid: {key: arr[k] for key, arr in d.items()} for uid, d in factors.items()}
        for key, db in rl_db(perturb).items():
            samples[key].append(db)
        if progress is not None and progress(k + 1, n):
            stopped = True
            break
    rows, passes = [], []
    for ti, t, ang, pol in plan:
        tdb = float(target_db) if target_db is not None else t.goal_db
        arr = np.array(samples[ang, pol]) if n else nominal[ang, pol][None, :]  # n_samples = 0: as run_tolerance
        r = _summarise(f, nominal[ang, pol], arr, [(t.f_min, t.f_max)], s, tdb, stopped)
        rows.append((ti, t.name, ang, pol, tdb, r))
        passes.append(np.asarray(r.worst_db) <= tdb)
    joint = float(np.mean(np.all(passes, axis=0)))
    return CornerResult(rows, joint, rows[0][5].n_samples, stopped, mode, fallback)


def run_tolerance_corners(project: Project, f, target_db=None, progress=None, should_stop=None) -> CornerResult:
    """``run_tolerance_targets`` at the angle ends of every enabled target (``progress(done, total)``)."""
    return run_tolerance_targets(project, f, "corners", target_db=target_db, progress=progress,
                                 should_stop=should_stop)


def _draw(rng, dist, tol, n):
    if tol <= 0:
        return np.ones(n)
    if dist == "uniform":
        return 1.0 + rng.uniform(-tol, tol, n)
    return 1.0 + rng.normal(0.0, tol, n)


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
            if ly.model == "rlc":
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
    s = settings or project.tolerance
    f = np.asarray(f, dtype=float)
    rng = np.random.default_rng(s.seed)
    n = int(s.n_samples)
    pols = ("TE", "TM") if s.pol == "avg" else (s.pol,)

    def rl_db(perturb=None):
        res = solve(project.structure, project.materials, f, s.angle, pols=pols, perturb=perturb)
        r = res.quantity("R", "avg" if s.pol == "avg" else s.pol)[:, 0]
        return 10 * np.log10(np.maximum(r, 1e-30))

    nominal = rl_db()
    factors = sample_factors(project, s, rng, n)
    samples = []
    stopped = False
    try:
        for k in range(n):
            perturb = {uid: {key: arr[k] for key, arr in d.items()} for uid, d in factors.items()}
            samples.append(rl_db(perturb))
            if progress is not None and progress(k + 1, n):
                raise _Stop
    except _Stop:
        stopped = True
    if not samples:
        samples = [nominal]
    return _summarise(f, nominal, np.array(samples), band, s, s.target_db, stopped)


def _summarise(f, nominal, arr, band, s, target_db, stopped):
    """ToleranceResult from the per-sample RL curves ``arr`` (samples x f).  ``band`` = (f_lo, f_hi), a list of
    them (a union), or None (all of ``f``); a band without any grid point falls back to all of ``f``."""
    if band is None:
        mask = np.ones(f.shape, dtype=bool)
    else:
        intervals = band if np.ndim(band) == 2 else [band]
        mask = np.zeros(f.shape, dtype=bool)
        for lo, hi in intervals:
            mask |= (f >= lo) & (f <= hi)
        if not mask.any():
            mask = np.ones(f.shape, dtype=bool)
    worst = arr[:, mask].max(axis=1)
    return ToleranceResult(
        f=f, nominal_db=nominal, median_db=np.median(arr, axis=0),
        lower_db=np.percentile(arr, s.lower_pct, axis=0), upper_db=np.percentile(arr, s.upper_pct, axis=0),
        worst_db=worst, yield_fraction=float(np.mean(worst <= target_db)), n_samples=len(arr),
        stopped=stopped)
