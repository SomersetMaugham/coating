"""The Odelevskiy ratio N/pc from composites measured at several loadings (no Qt).

With y = e_h / (e_i - e_h) the Odelevskiy rule reads  e = e_h + e_h p / (u - B p),  u = N + y,  B = N / pc.
When the filler is a free table (one complex value per frequency, as ``invert-filler`` makes it), N is absorbed into
u: composites at any loading determine B alone.  Two (N, pc) with the same B give the same predictions wherever both
give a table; which N give one at all depends on the screening and passivity checks, because the screening
coordinate of the inversion is x = N / u.  So this module fits B and reports, per composite, the N that
``invert-filler`` accepts.  Design and numbers: docs/DEVELOPMENT_HISTORY.md 3.34, docs/CLI_PLAN.md 13.11.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from coating_studio.materials.inversion import invert_filler
from coating_studio.materials.models import Shape

B_MIN = 1e-4
N_GRID = 200  # log-spaced ratios in the profile
N_SHAPE_GRID = 400  # shape factors tested per composite
FLAT_FACTOR, FLAT_FLOOR = 1.1, 1e-4  # the flat interval: rms <= max(1.1 rms_min, rms_min + 1e-4)
SIGNAL_TOL = 1e-12
GN_ITERATIONS = 200  # hard data needs well over 60 damped steps at a few frequencies (seed 28 in the tests)
FIT_POOR = 0.10


def has_signal(e_h, e):
    """True when some composite differs from the matrix (a non-magnetic mu channel does not)."""
    e_h, e = np.asarray(e_h, dtype=complex), np.asarray(e, dtype=complex)
    return bool(np.any(np.abs(e - e_h) > SIGNAL_TOL * np.maximum(np.abs(e_h), 1.0)))


def _scales(e):
    return np.maximum(np.max(np.abs(e), axis=1), 1e-300)[:, None]  # max_f |e_k|, as ``inversion.rms_relative``


def solve_u(b, p, e_h, e):
    """u (per frequency) minimising sum_k |(e_h p_k / (u - b p_k) - (e_k - e_h)) / s_k|^2.

    Starts from the weighted linear solution of (u - b p_k) d_k = e_h p_k and takes damped Gauss-Newton steps, each
    accepted only where it lowers that frequency's residual."""
    p = np.asarray(p, dtype=float)[:, None]
    d = np.asarray(e, dtype=complex) - e_h
    w = 1.0 / _scales(e) ** 2
    num = np.sum(w * np.conj(d) * (e_h * p + b * p * d), axis=0)
    den = np.sum(w * np.abs(d) ** 2, axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        u = np.where(den > 0, num / np.where(den > 0, den, 1.0), b * p.max() + 1.0)

    def cost(u):
        with np.errstate(divide="ignore", invalid="ignore"):
            r = (e_h * p / (u - b * p) - d) * np.sqrt(w)
        return np.sum(np.abs(r) ** 2, axis=0), r  # a NaN trial is never "better" below

    c, r = cost(u)
    lam = np.full(u.shape, 1e-3)
    for _ in range(GN_ITERATIONS):
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            jac = -e_h * p / (u - b * p) ** 2 * np.sqrt(w)
            jj = np.sum(np.abs(jac) ** 2, axis=0)
            step = np.sum(np.conj(jac) * r, axis=0) / (jj * (1 + lam))
        trial = u - step
        c_new, r_new = cost(trial)
        better = c_new < c
        u = np.where(better, trial, u)
        c = np.where(better, c_new, c)
        r = np.where(better, r_new, r)
        lam = np.where(better, lam / 3, lam * 10)
        if np.all(~np.isfinite(step) | (np.abs(step) <= 1e-13 * np.maximum(np.abs(u), 1.0))):
            break
    return u, r


@dataclass
class ShapeFit:
    fractions: list
    channels_used: list
    n_over_pc: float
    rms: float
    rms_per: dict  # channel -> list of rms per composite (None for an unused channel)
    profile_b: np.ndarray
    profile_rms: np.ndarray
    flat_interval: tuple
    search_range: tuple
    u: dict = field(default_factory=dict)

    @property
    def at_bound(self):
        lo, hi = self.search_range
        span = np.log(hi / lo)
        return bool(np.log(self.n_over_pc / lo) < 1e-3 * span or np.log(hi / self.n_over_pc) < 1e-3 * span)


def _total(b, p, channels):
    """rms over every (channel, composite, frequency) normalised residual, and the residuals per channel."""
    res = {name: solve_u(b, p, e_h, e) for name, (e_h, e) in channels.items()}
    sq = sum(float(np.sum(np.abs(r) ** 2)) for _, r in res.values())
    n = sum(r.size for _, r in res.values())
    return float(np.sqrt(sq / n)) if np.isfinite(sq) else np.inf, res


def fit_shape(fractions, channels) -> ShapeFit:
    """Fit B = N/pc.  ``channels`` maps "eps"/"mu" to ``(e_h (F,), e (K, F))``; channels without signal are dropped.
    Raises ValueError for fewer than two distinct loadings or when no channel carries signal."""
    p = np.asarray(fractions, dtype=float)
    if p.ndim != 1 or p.size < 2:
        raise ValueError("at least two loadings are needed: one loading fits any N/pc")
    if np.any(p <= 0) or np.any(p >= 1):
        raise ValueError("loadings must lie between 0 and 1")
    if np.min(np.diff(np.sort(p))) <= 1e-9:
        raise ValueError("the loadings must differ")
    used = {k: (np.asarray(v[0], dtype=complex), np.asarray(v[1], dtype=complex)) for k, v in channels.items()
            if has_signal(*v)}
    if not used:
        raise ValueError("no composite differs from the matrix: there is nothing to fit")
    lo, hi = B_MIN, (1 - 1e-6) / p.max()  # N < 1 and pc > max p
    grid = np.geomspace(lo, hi, N_GRID)
    prof = np.array([_total(b, p, used)[0] for b in grid])
    i = int(np.argmin(prof))
    from scipy.optimize import minimize_scalar

    a, c = np.log(grid[max(i - 1, 0)]), np.log(grid[min(i + 1, N_GRID - 1)])
    r = minimize_scalar(lambda x: _total(np.exp(x), p, used)[0], bounds=(a, c), method="bounded",
                        options={"xatol": 1e-9})
    b = float(np.exp(r.x))
    rms, res = _total(b, p, used)
    if rms > prof[i]:  # the bracket search can only improve on the grid
        b, (rms, res) = float(grid[i]), _total(grid[i], p, used)
    rms_per = {}
    for name in channels:
        if name in res:
            rk = res[name][1]
            rms_per[name] = [float(np.sqrt(np.mean(np.abs(rk[k]) ** 2))) for k in range(p.size)]
        else:
            rms_per[name] = None
    return ShapeFit(list(map(float, p)), list(used), b, rms, rms_per, grid, prof,
                    flat_interval(grid, prof, b, rms), (lo, hi), {k: v[0] for k, v in res.items()})


def flat_interval(grid, prof, b, rms):
    """The connected stretch of the profile around the minimum where rms <= max(1.1 rms_min, rms_min + 1e-4); the
    ends are interpolated linearly in log B.  Not a confidence interval: the noise level is unknown."""
    lim = max(FLAT_FACTOR * rms, rms + FLAT_FLOOR)
    x, y = np.log(grid), np.asarray(prof)
    i = int(np.argmin(np.abs(x - np.log(b))))

    def end(step):
        j = i
        while 0 <= j + step < len(x) and y[j + step] <= lim:
            j += step
        if not 0 <= j + step < len(x):
            return float(np.exp(x[j]))  # flat up to the search bound
        k = j + step
        t = (lim - y[j]) / (y[k] - y[j]) if y[k] != y[j] else 0.0
        return float(np.exp(x[j] + t * (x[k] - x[j])))

    return min(end(-1), b), max(end(1), b)


def admissible_n(b, fractions, f, eps_k, mu_k, eps_m, mu_m, phi):
    """Shape factors N for which ``invert-filler`` accepts this composite with pc = N/B (pc <= 1, above every
    loading).  Returns ``(lo, hi, share)``: the smallest and largest accepted grid points and the accepted share of
    the grid, or ``None`` when none is accepted.  The grid excludes the open ends of (B max p, min(B, 1))."""
    top = max(fractions)
    lo, hi = b * top, min(b, 1.0)
    if not hi > lo:
        return None
    n = np.linspace(lo, hi, N_SHAPE_GRID + 2)[1:]
    if hi >= 1.0:
        n = n[:-1]  # N < 1
    ok = []
    for x in n:
        shape = Shape(float(x), min(float(x) / b, 1.0))
        if not shape.pc > top:
            continue
        if invert_filler(f, eps_k, mu_k, eps_m, mu_m, phi, "odelevskiy", False, shape).ok:
            ok.append(float(x))
    if not ok:
        return None
    return min(ok), max(ok), len(ok) / len(n)
