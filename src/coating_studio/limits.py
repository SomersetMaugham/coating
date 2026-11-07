"""Physical limits and model-validity checks for absorber designs (no Qt).

Rozanov bound (K. N. Rozanov, IEEE Trans. Antennas Propag. 48(8), 2000): for a metal-backed (PEC) absorber at
normal incidence, ``|∫ ln|Γ(λ)| dλ| <= 2π² Σ μs,i·d_i`` (μs = static permeability, λ in the incident medium).
Requiring ``|Γ| <= Γ0`` over ``[λ1, λ2]`` gives the necessary condition
``Σ μs·d >= |ln Γ0|·(λ2 − λ1) / (2π²)``.  It is necessary, not sufficient: passing it does not mean the target
is reachable.  See docs/CLI_PLAN.md, section 13.4.
"""

from __future__ import annotations

import itertools
import math

import numpy as np

from coating_studio.core.constants import C0
from coating_studio.core.structure import SlabLayer
from coating_studio.materials.checks import Issue
from coating_studio.materials.models import (
    ConstantMaterial, DispersiveMaterial, MaterialCycleError, MixtureMaterial, TabulatedMaterial, bruggeman,
    maxwell_garnett,
)
from coating_studio.project import Project, set_param

FITTED_PREFIX = "fitted:"  # note prefix of materials made by ``coating-cli fit`` (extrapolated static mu)
MAX_CORNERS = 256  # material-variable corners evaluated for the best achievable static permeability

# Mixing-model validity intervals (closed): Bruggeman with a conductive inclusion near the percolation threshold
# (1/3 for spheres), Maxwell-Garnett beyond the dilute limit.  Warnings only.
BRUGGEMAN_CONDUCTIVE_RANGE = (0.25, 0.40)
MAXWELL_GARNETT_MAX = 0.30


def rozanov_required_mu_d(f_lo, f_hi, goal_db, n_inc=1.0):
    """Minimum Σ μs·d [m] for |Γ| <= 10^(goal_db/20) over f_lo..f_hi (normal incidence, PEC backing)."""
    gamma0 = 10 ** (goal_db / 20)
    if gamma0 >= 1:
        return 0.0
    dl = (C0 / f_lo - C0 / f_hi) / n_inc
    return abs(math.log(gamma0)) * dl / (2 * math.pi ** 2)


def static_permeability(mat, resolver, _seen=None):
    """(μs, extrapolated) of a material, from its model at f -> 0; μs is None when it cannot be known.

    Constant / dispersive models with a frequency-independent magnetic loss are not causal, so their real part
    underestimates μs (Kramers-Kronig): None.  Tabulated data is never extrapolated: None."""
    seen = _seen or set()
    if mat.name in seen:
        raise MaterialCycleError(f"material {mat.name!r} references itself")
    fitted = isinstance(mat.note, str) and mat.note.startswith(FITTED_PREFIX)
    if isinstance(mat, ConstantMaterial):
        return (mat.mu_re if mat.mu_loss == 0 else None), False
    if isinstance(mat, DispersiveMaterial):
        if mat.mu_loss != 0 or any(t["delta"] < 0 or t["f0"] <= 0 for t in mat.mu_terms):
            return None, fitted
        return mat.mu_inf + sum(t["delta"] for t in mat.mu_terms), fitted
    if isinstance(mat, MixtureMaterial):
        um, xm = static_permeability(resolver(mat.matrix), resolver, seen | {mat.name})
        ui, xi = static_permeability(resolver(mat.inclusion), resolver, seen | {mat.name})
        if um is None or ui is None:
            return None, xm or xi
        rule = maxwell_garnett if mat.model == "maxwell_garnett" else bruggeman
        return float(np.real(rule(np.array([um]), np.array([ui]), mat.fraction))[0]), xm or xi
    if isinstance(mat, TabulatedMaterial):
        return None, False
    return None, False


def _layer_mu(project, name):
    try:
        return static_permeability(project.materials[name], project.resolver)
    except (KeyError, MaterialCycleError):
        return None, False


def design_mu_d(project: Project):
    """(Σ μs·d of the current slabs [m] or None, extrapolated)."""
    total, ext = 0.0, False
    for ly in project.structure.layers:
        if isinstance(ly, SlabLayer):
            mu, x = _layer_mu(project, ly.material)
            if mu is None:
                return None, x
            total += mu * ly.thickness
            ext = ext or x
    return total, ext


def max_achievable_mu_d(project: Project):
    """(Largest Σ μs·d the optimisation can reach [m] or None, extrapolated).

    Per slab: the largest μs over its current material and its MaterialChoice candidates, with material
    variables at the corners of their ranges; thickness at its variable's upper bound (else the current
    value); with ``thickness_max`` the budget goes to the highest-μs layers first (after every layer's minimum)."""
    s = project.optimization
    mat_vars = [v for v in s.variables if v.path[0] == "material"]
    if len(mat_vars) > 8:
        return None, False
    choices = {c.uid: list(c.candidates) for c in s.choices}
    work = project.copy()
    best = {}  # uid -> (mu, extrapolated)
    ext_any = False
    corners = list(itertools.product(*[(v.lower, v.upper) for v in mat_vars])) or [()]
    for corner in corners[:MAX_CORNERS]:
        try:
            for v, val in zip(mat_vars, corner):
                set_param(work, v.path, val)
        except (KeyError, ValueError, AttributeError, IndexError):
            return None, False
        for ly in project.structure.layers:
            if not isinstance(ly, SlabLayer):
                continue
            for name in {ly.material, *choices.get(ly.uid, [])}:
                mu, x = _layer_mu(work, name)
                if mu is None:
                    return None, x
                ext_any = ext_any or x
                if ly.uid not in best or mu > best[ly.uid][0]:
                    best[ly.uid] = (mu, x)
    th_vars = {v.path[1]: v for v in s.variables if v.path[0] == "layer" and v.path[2] == "thickness"}
    slabs = [ly for ly in project.structure.layers if isinstance(ly, SlabLayer)]
    lo = {ly.uid: (th_vars[ly.uid].lower if ly.uid in th_vars else ly.thickness) for ly in slabs}
    hi = {ly.uid: (th_vars[ly.uid].upper if ly.uid in th_vars else ly.thickness) for ly in slabs}
    if s.thickness_max is None:
        return sum(best[u][0] * hi[u] for u in hi), ext_any
    budget = s.thickness_max - sum(lo.values())
    total = sum(best[u][0] * lo[u] for u in lo)
    for u in sorted(hi, key=lambda u: -best[u][0]):
        extra = max(0.0, min(hi[u] - lo[u], budget))
        total += best[u][0] * extra
        budget -= extra
    return total, ext_any


def _incident_index(project, f):
    try:
        eps, mu = project.materials[project.structure.incident].eps_mu(np.array([f]), project.resolver)
        return float(np.sqrt(np.real(eps[0] * mu[0])))
    except Exception:  # noqa: BLE001 - the solver reports incident-medium problems itself
        return 1.0


def target_limits(project: Project):
    """Rozanov verdict per enabled target: list of dicts (docs/CLI_PLAN.md, appendix B ``check.limits``)."""
    out = []
    pec = project.structure.backing.kind == "pec"
    design, d_ext = design_mu_d(project)
    best, b_ext = max_achievable_mu_d(project)
    for i, t in enumerate(project.optimization.enabled_targets()):
        n_inc = _incident_index(project, math.sqrt(t.f_min * t.f_max))
        req = rozanov_required_mu_d(t.f_min, t.f_max, t.goal_db, n_inc)
        row = {"target": i, "target_name": t.name, "required_mu_d_m": req, "design_mu_d_m": design,
               "max_achievable_mu_d_m": best, "status": "unknown", "note": "normal-incidence condition only"}
        if not pec:
            row["note"] = "the bound assumes a PEC backing"
        elif t.angle_min > 0:
            row["note"] = "target excludes normal incidence; the bound is derived for normal incidence"
        elif design is None:
            row["note"] = "static permeability unknown (tabulated data or constant magnetic loss)"
        elif design >= req:
            row["status"] = "ok"
        elif best is not None and best < req and not (b_ext or d_ext):
            row["status"] = "infeasible"
        else:
            row["status"] = "violated"
            if b_ext or d_ext:
                row["note"] += "; fitted model, extrapolated static permeability"
        out.append(row)
    return out


def limit_issues(rows):
    issues = []
    for r in rows:
        if r["status"] in ("violated", "infeasible"):
            code = "rozanov_limit" if r["status"] == "violated" else "rozanov_infeasible"
            issues.append((r["target"], Issue("warning", code, "", {
                "target": r["target_name"] or str(r["target"] + 1),
                "required_mm": r["required_mu_d_m"] * 1e3,
                "design_mm": (r["design_mu_d_m"] or 0.0) * 1e3,
                "max_mm": (r["max_achievable_mu_d_m"] or 0.0) * 1e3})))
    return issues


# ---------------------------------------------------------------------------
# mixing-model validity

def _conductive(mat, resolver, f):
    if isinstance(mat, DispersiveMaterial) and mat.sigma > 0:
        return True
    try:
        eps, _ = mat.eps_mu(np.array([f]), resolver)
    except Exception:  # noqa: BLE001
        return False
    e = complex(eps[0])
    return e.real > 0 and -e.imag / e.real > 1


def mixture_range_issues(project: Project, f_ref, names=None):
    """``mixture_fraction_range`` warnings for mixtures (restricted to ``names`` if given) whose fraction, or
    fraction variable range, enters an interval where the mixing model is unreliable."""
    ranges = {}
    for v in project.optimization.variables:
        if v.path[0] == "material" and tuple(v.path[2:]) == ("fraction",):
            ranges[v.path[1]] = (v.lower, v.upper)
    issues = []
    for m in project.materials.values():
        if not isinstance(m, MixtureMaterial) or (names is not None and m.name not in names):
            continue
        lo_v, hi_v = ranges.get(m.name, (m.fraction, m.fraction))
        lo_v, hi_v = min(lo_v, m.fraction), max(hi_v, m.fraction)
        if m.model == "bruggeman":
            try:
                inc = project.resolver(m.inclusion)
            except KeyError:
                continue
            if not _conductive(inc, project.resolver, f_ref):
                continue
            lo, hi = BRUGGEMAN_CONDUCTIVE_RANGE
            hit = hi_v >= lo and lo_v <= hi
        else:
            lo, hi = MAXWELL_GARNETT_MAX, 1.0
            hit = hi_v > lo
        if hit:
            issues.append(Issue("warning", "mixture_fraction_range", m.name,
                                {"model": m.model, "lo": lo, "hi": hi, "fraction_lo": lo_v, "fraction_hi": hi_v}))
    return issues


# ---------------------------------------------------------------------------
# measured-data ranges

def data_range(mat, resolver, _seen=None):
    """Frequency range [Hz] a material can be evaluated on (tabulated data, also inside mixtures); None = any."""
    seen = _seen or set()
    if mat.name in seen:
        return None
    if isinstance(mat, TabulatedMaterial):
        return float(mat.f[0]), float(mat.f[-1])
    if isinstance(mat, MixtureMaterial):
        rs = [data_range(resolver(n), resolver, seen | {mat.name}) for n in (mat.matrix, mat.inclusion)]
        rs = [r for r in rs if r is not None]
        if not rs:
            return None
        return max(r[0] for r in rs), min(r[1] for r in rs)
    return None


def measured_range(project: Project, names):
    """Intersection of the data ranges of ``names`` (and their constituents); None if none is tabulated."""
    rs = []
    for n in names:
        try:
            r = data_range(project.materials[n], project.resolver)
        except KeyError:
            continue
        if r is not None:
            rs.append(r)
    if not rs:
        return None
    return max(r[0] for r in rs), min(r[1] for r in rs)
