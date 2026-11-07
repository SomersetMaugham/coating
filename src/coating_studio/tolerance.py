"""Monte-Carlo manufacturing-tolerance analysis.

Each sample perturbs, per layer and independently, the thickness, eps and mu
(slabs) or the sheet impedance (sheets) by a relative error drawn from a
normal distribution (tolerance = 1 sigma) or a uniform one (+/- tolerance).
With a loss tolerance set (eps_loss / mu_loss), the real part and the loss part
of eps (mu) get their own errors, so the loss tangent varies as well; with
None the whole complex value is scaled by one factor (tan delta fixed).  The
real-part and loss errors are independent by default; ``loss_correlation`` (rho)
couples them, e.g. rho > 0 for a filler content that raises eps' and eps'' together.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

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
    """Tolerance analysis at every (angle end x polarisation) corner of the enabled targets."""

    corners: list  # [(target index, target name, angle deg, pol, target dB, ToleranceResult)]
    joint_yield_fraction: float | None  # samples that meet every corner's criterion
    n_samples: int
    stopped: bool = False

    @property
    def worst(self):
        """Index into ``corners`` of the corner with the lowest yield."""
        return min(range(len(self.corners)), key=lambda i: self.corners[i][5].yield_fraction)


def _corner_progress(progress, k, n_req, n_corners):
    def cb(done, total):
        return progress(k * n_req + done, n_corners * n_req, k, n_corners)
    return cb


def target_corners(project: Project):
    """(target index, target, angle, pol) for the angle ends x polarisations of every enabled target."""
    out = []
    for ti, t in enumerate(project.optimization.enabled_targets()):
        for ang in sorted({t.angle_min, t.angle_max}):
            for pol in t.pols:
                out.append((ti, t, float(ang), pol))
    return out


def run_tolerance_corners(project: Project, f, target_db=None, progress=None, should_stop=None) -> CornerResult:
    """``run_tolerance`` at every target corner; each corner's yield band is its target's band and its criterion
    the target's goal (or ``target_db``).  The perturbation samples depend only on the seed and the layers (they
    are drawn before the solve loop), so every corner sees the same samples and the joint yield is exact.

    ``progress(done, total, corner_index, n_corners) -> bool`` may return True to stop; ``should_stop()`` is
    checked between corners."""
    plan = target_corners(project)
    if not plan:
        raise ValueError("no enabled target to take corners from")
    base = project.tolerance
    rows, passes, stopped = [], [], False
    n_req = int(base.n_samples)
    for k, (ti, t, ang, pol) in enumerate(plan):
        if k and should_stop is not None and should_stop():
            stopped = True
            break
        s = dataclasses.replace(base, angle=ang, pol=pol,
                                target_db=float(target_db) if target_db is not None else t.goal_db)
        cb = None if progress is None else _corner_progress(progress, k, n_req, len(plan))
        r = run_tolerance(project, f, settings=s, band=[(t.f_min, t.f_max)], progress=cb)
        rows.append((ti, t.name, ang, pol, s.target_db, r))
        passes.append(np.asarray(r.worst_db) <= s.target_db)
        if r.stopped:
            stopped = True
            break
    n = min(len(x) for x in passes)
    joint = float(np.mean(np.all([x[:n] for x in passes], axis=0))) if n else None
    return CornerResult(rows, joint, n, stopped or len(rows) < len(plan))


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
    rho = float(s.loss_correlation)
    if not -1.0 <= rho <= 1.0:
        raise ValueError(f"loss_correlation must be between -1 and 1, got {rho}")
    factors = {}
    for ly in project.structure.layers:
        if isinstance(ly, SlabLayer):
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
    arr = np.array(samples)
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
        worst_db=worst, yield_fraction=float(np.mean(worst <= s.target_db)), n_samples=len(samples),
        stopped=stopped)
