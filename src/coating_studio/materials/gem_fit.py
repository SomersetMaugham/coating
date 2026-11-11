"""McLachlan GEM parameters (percolation threshold pc, exponent t) from composites measured at several loadings (no Qt).

The filler is unknown, one complex value per frequency (as ``invert-filler`` makes it).  For given (pc, t) each
composite fixes it in closed form: with x = e^(1/t), a = e_m^(1/t), A = (1 - pc)/pc and R = (1 - phi)(a - x)/(a + A x),

    b = e_i^(1/t) = x (phi - R A) / (phi + R).

At the right (pc, t) the loadings agree on b.  Per frequency the estimates are combined with weights
1 / (|db_k/de_k| s_k)^2 (s_k = max_f |e_k|, the normalisation of ``inversion.rms_relative``), which to first order
minimises the relative prediction error and gives a composite near the screening limit (phi + R -> 0, b -> infinity)
no weight; every composite is then predicted with the forward rule and the relative rms is the fit's cost.

Unlike Odelevskiy's N/pc (shape_fit), pc and t are not tied algebraically: noiseless data at any loadings give both.
With noise, pc is well determined when the loadings straddle it and t only weakly; loadings all on one side of pc
determine neither.  So the fit reports the flat region of the profile next to the optimum.  Numbers and design:
docs/DEVELOPMENT_HISTORY.md 3.53, docs/CLI_PLAN.md 13.13.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize

from coating_studio.materials.models import GemParams, gem

PC_GRID = np.geomspace(0.005, 0.6, 40)
T_GRID = np.linspace(1.0, 4.0, 31)
FLAT_FACTOR, FLAT_FLOOR = 1.1, 1e-4  # as shape_fit: rms <= max(1.1 rms_min, rms_min + 1e-4)
FIT_POOR = 0.10
T_WEAK = 1.5  # width of the flat t range that counts as "t is weakly determined"
N_STARTS = 5  # lowest grid points the local refinement starts from
SIGNAL_TOL = 1e-12


def has_signal(e_m, e):
    e_m, e = np.asarray(e_m, dtype=complex), np.asarray(e, dtype=complex)
    return bool(np.any(np.abs(e - e_m) > SIGNAL_TOL * np.maximum(np.abs(e_m), 1.0)))


def per_loading(e, e_m, phi, params):
    """(b, |db/de|) of one composite: the filler's 1/t power implied by it, and its sensitivity to the composite."""
    t = params.t
    big_a = (1.0 - params.pc) / params.pc
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        x = np.asarray(e, dtype=complex) ** (1.0 / t)
        a = np.asarray(e_m, dtype=complex) ** (1.0 / t)
        r = (1 - phi) * (a - x) / (a + big_a * x)
        b = x * (phi - r * big_a) / (phi + r)
        dbdx = (phi - r * big_a) / (phi + r) + x * phi * (1 - phi) * a * (1 + big_a) ** 2 / ((a + big_a * x) ** 2
                                                                                              * (phi + r) ** 2)
        dbde = np.abs(dbdx) * np.abs(x) / (t * np.abs(e))  # dx/de = x / (t e)
    return b, dbde


def filler(fractions, e_m, e_k, params):
    """The filler e_i(f) the composites ``e_k`` (loading x frequency) imply for ``params`` (weighted, see above)."""
    s = np.maximum(np.max(np.abs(e_k), axis=1), 1e-300)
    num = np.zeros(e_k.shape[1], dtype=complex)
    den = np.zeros(e_k.shape[1])
    for phi, e, sk in zip(fractions, e_k, s):
        b, dbde = per_loading(e, e_m, phi, params)
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            w = 1.0 / (dbde * sk) ** 2
        ok = np.isfinite(b) & np.isfinite(w)
        num += np.where(ok, w * np.where(ok, b, 0), 0)
        den += np.where(ok, w, 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (num / den) ** params.t


def _channel_rms(fractions, e_m, e_k, params):
    """Relative rms of every composite predicted from the implied filler; per composite and overall."""
    ei = filler(fractions, e_m, e_k, params)
    if not np.all(np.isfinite(ei)):
        return np.inf, [np.inf] * len(fractions)
    per = []
    for phi, e in zip(fractions, e_k):
        pred = gem(e_m, ei, phi, params)
        per.append(float(np.sqrt(np.mean(np.abs(pred - e) ** 2)) / max(np.max(np.abs(e)), 1e-300)))
    return float(np.sqrt(np.mean(np.square(per)))), per


def _cost(fractions, channels, params):
    vals = [_channel_rms(fractions, e_m, e_k, params)[0] for e_m, e_k in channels]
    return float(np.sqrt(np.mean(np.square(vals))))


@dataclass
class GemFit:
    percolation: float
    exponent: float
    rms: float
    rms_per: dict  # channel -> rms (None for a channel without signal)
    per_composite: list  # [{"fraction", "rms_eps", "rms_mu"}]
    flat_pc: tuple
    flat_t: tuple
    at_bound: bool
    profile: np.ndarray  # rms on PC_GRID x T_GRID
    channels_used: list = field(default_factory=list)


def _flat_region(prof, i0, j0):
    """Grid points next to the optimum (4-connected) with rms <= max(1.1 min, min + 1e-4): their pc and t ranges."""
    lim = max(FLAT_FACTOR * prof[i0, j0], prof[i0, j0] + FLAT_FLOOR)
    seen = {(i0, j0)}
    stack = [(i0, j0)]
    while stack:
        i, j = stack.pop()
        for a, b in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if 0 <= a < prof.shape[0] and 0 <= b < prof.shape[1] and (a, b) not in seen and prof[a, b] <= lim:
                seen.add((a, b))
                stack.append((a, b))
    ii = [i for i, _ in seen]
    jj = [j for _, j in seen]
    return (float(PC_GRID[min(ii)]), float(PC_GRID[max(ii)])), (float(T_GRID[min(jj)]), float(T_GRID[max(jj)]))


def fit_gem(fractions, channels: dict) -> GemFit:
    """``channels``: {"eps"|"mu": (e_m (n_f,), e_k (n_loadings, n_f))}; channels without signal are ignored.
    The same (pc, t) holds for both, as a GEM mixture applies one rule to eps and mu."""
    fractions = [float(p) for p in fractions]
    used = {k: v for k, v in channels.items() if has_signal(*v)}
    if not used:
        raise ValueError("no composite differs from the matrix: nothing to fit")
    ch = [(np.asarray(em, dtype=complex), np.asarray(ek, dtype=complex)) for em, ek in used.values()]
    prof = np.array([[_cost(fractions, ch, GemParams(pc, t)) for t in T_GRID] for pc in PC_GRID])
    prof = np.where(np.isfinite(prof), prof, np.inf)
    i0, j0 = np.unravel_index(np.argmin(prof), prof.shape)
    if not np.isfinite(prof[i0, j0]):
        raise ValueError("no (pc, t) on the grid reproduces the composites")
    # The valley in (pc, t) is curved and nearly flat along t, so a box around the best grid point can miss the
    # optimum (seen: the grid's best was 4 t-steps from it).  Refine over the whole grid from the lowest grid points.
    bounds = [(float(np.log(PC_GRID[0])), float(np.log(PC_GRID[-1]))), (float(T_GRID[0]), float(T_GRID[-1]))]

    def obj(v):
        c = _cost(fractions, ch, GemParams(float(np.exp(v[0])), float(v[1])))
        return c if np.isfinite(c) else 1e300

    v, best = np.array([np.log(PC_GRID[i0]), T_GRID[j0]]), prof[i0, j0]
    for k in np.argsort(prof, axis=None)[:N_STARTS]:
        i, j = np.unravel_index(k, prof.shape)
        sol = minimize(obj, [np.log(PC_GRID[i]), T_GRID[j]], method="Nelder-Mead", bounds=bounds,
                       options={"xatol": 1e-10, "fatol": 1e-16, "maxiter": 2000})
        if sol.fun < best:
            v, best = sol.x, sol.fun
    pc, t = float(np.exp(v[0])), float(v[1])
    params = GemParams(pc, t)
    rms_per = {k: None for k in channels}
    per = [{"fraction": p, "rms_eps": None, "rms_mu": None} for p in fractions]
    for k, (em, ek) in zip(used, ch):
        total, rows = _channel_rms(fractions, em, ek, params)
        rms_per[k] = total
        for row, r in zip(per, rows):
            row[f"rms_{k}"] = r
    at_bound = i0 in (0, len(PC_GRID) - 1) or j0 in (0, len(T_GRID) - 1)
    flat_pc, flat_t = _flat_region(prof, i0, j0)
    # the region is made of grid points; the refined optimum can lie between them, so include it
    flat_pc = (min(flat_pc[0], pc), max(flat_pc[1], pc))
    flat_t = (min(flat_t[0], t), max(flat_t[1], t))
    return GemFit(pc, t, _cost(fractions, ch, params), rms_per, per, flat_pc, flat_t, at_bound, prof, list(used))


def warning_flags(fit: GemFit, fractions, channels: dict) -> list:
    """``[(code, args)]`` for a fit; ``channels`` as for ``fit_gem`` (used for the per-channel comparison)."""
    flags = []
    pc = fit.percolation
    if all(p < pc for p in fractions) or all(p > pc for p in fractions):
        flags.append(("gem_one_sided", {"pc": pc, "side": "below" if fractions[0] < pc else "above"}))
    if fit.rms > FIT_POOR:
        flags.append(("gem_fit_poor", {"rms": fit.rms, "limit": FIT_POOR}))
    if fit.at_bound:
        flags.append(("gem_at_bound", {"pc_range": [float(PC_GRID[0]), float(PC_GRID[-1])],
                                       "t_range": [float(T_GRID[0]), float(T_GRID[-1])]}))
    if len(fractions) == 2:
        flags.append(("gem_two_fractions", {}))
    if fit.flat_t[1] - fit.flat_t[0] >= T_WEAK:
        flags.append(("gem_t_weak", {"t_lo": fit.flat_t[0], "t_hi": fit.flat_t[1]}))
    if len(fit.channels_used) == 2:
        alone = {k: fit_gem(fractions, {k: channels[k]}) for k in fit.channels_used}
        e, m = alone["eps"], alone["mu"]
        step = PC_GRID[1] / PC_GRID[0]  # one grid cell of slack: the regions of noiseless data are single points
        if e.flat_pc[1] * step < m.flat_pc[0] / step or m.flat_pc[1] * step < e.flat_pc[0] / step:
            flags.append(("gem_channel_mismatch", {"pc_eps": e.percolation, "pc_mu": m.percolation}))
    return flags
