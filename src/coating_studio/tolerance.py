"""Monte-Carlo manufacturing-tolerance analysis.

Each sample perturbs, per layer and independently, the thickness, eps and mu
(slabs) or the sheet impedance (sheets) by a relative error drawn from a
normal distribution (tolerance = 1 sigma) or a uniform one (+/- tolerance).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from coating_studio.core.solver import solve
from coating_studio.core.structure import SheetLayer, SlabLayer
from coating_studio.project import Project, ToleranceSettings


class _Stop(Exception):
    pass


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


def _draw(rng, dist, tol, n):
    if tol <= 0:
        return np.ones(n)
    if dist == "uniform":
        return 1.0 + rng.uniform(-tol, tol, n)
    return 1.0 + rng.normal(0.0, tol, n)


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
    factors = {}
    for ly in project.structure.layers:
        if isinstance(ly, SlabLayer):
            factors[ly.uid] = {k: np.maximum(_draw(rng, s.distribution, s.tolerance_for(ly.uid, k), n), 1e-6)
                               for k in ("thickness", "eps", "mu")}
        elif isinstance(ly, SheetLayer):
            factors[ly.uid] = {"sheet": np.maximum(_draw(rng, s.distribution,
                                                         s.tolerance_for(ly.uid, "sheet"), n), 1e-6)}
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
