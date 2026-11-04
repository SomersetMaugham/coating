"""Absorber optimisation: continuous parameters + discrete material choices.

Objective (all terms dimensionless, normalised by user reference values)::

    J = w_worst * RL_worst / |RL_ref|          (RL in dB, negative is better)
      + w_mean  * mean(|Gamma|^2) / 10^(RL_ref/10)
      + w_thick * thickness / thickness_ref
      + w_mass  * areal_mass / mass_ref
      + penalty(thickness > thickness_max)

RL_worst is the maximum of 20log10|Gamma| over the frequency x angle x
polarisation grid.  Global search: SciPy differential evolution.  When the
number of material combinations is small (<= MAX_ENUMERATED_COMBOS) every
combination is optimised separately (no artificial ordering of materials);
otherwise candidates are ordered by wave impedance at the band centre and
treated as integer variables.  The optional local polish uses L-BFGS-B on a
LogSumExp-smoothed worst case; the reported value is always the true one.
"""

from __future__ import annotations

import itertools
import math
import time
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import differential_evolution, minimize
from scipy.special import logsumexp

from coating_studio.core.solver import SolverError, solve
from coating_studio.materials.models import MaterialCycleError, OutOfRangeError
from coating_studio.project import OptimizationSettings, Project, get_param, set_param

MAX_ENUMERATED_COMBOS = 64
INVALID = 1e6
SMOOTH_DB = 0.25  # LogSumExp temperature [dB] for the local polish


class OptimizationError(ValueError):
    pass


class _Stop(Exception):
    pass


@dataclass
class ObjectiveTerms:
    worst_db: float
    mean_r: float
    thickness: float  # m
    mass: float  # kg/m^2
    objective: float

    def as_dict(self):
        return {"worst_db": self.worst_db, "mean_r": self.mean_r, "thickness": self.thickness,
                "mass": self.mass, "objective": self.objective}


@dataclass
class OptimizationResult:
    values: dict  # path tuple -> value (SI)
    choices: dict  # layer uid -> material name
    terms: ObjectiveTerms | None
    history: list = field(default_factory=list)  # (n_evals, best objective)
    n_evals: int = 0
    stopped: bool = False
    elapsed: float = 0.0
    message: str = ""


def band_grid(s: OptimizationSettings):
    f = np.linspace(s.f_min, s.f_max, max(int(s.n_f), 1)) if s.f_max > s.f_min else np.array([s.f_min])
    if s.n_angle > 1 and s.angle_max > s.angle_min:
        th = np.linspace(s.angle_min, s.angle_max, int(s.n_angle))
    else:
        th = np.array([s.angle_min])
    return f, th


class Evaluator:
    """Evaluates the objective for a working copy of the project."""

    def __init__(self, project: Project, settings: OptimizationSettings):
        self.p = project.copy()
        self.s = settings
        self.f, self.th = band_grid(settings)
        self.pols = tuple(settings.pols) or ("TE", "TM")
        self.n_evals = 0

    def terms(self, smooth=False) -> ObjectiveTerms:
        s = self.s
        self.n_evals += 1
        try:
            res = solve(self.p.structure, self.p.materials, self.f, self.th, pols=self.pols)
            r = np.stack([res.pol[k].R for k in self.pols])
            db = 10 * np.log10(np.maximum(r, 1e-30))
            worst = float(SMOOTH_DB * logsumexp(db / SMOOTH_DB)) if smooth else float(db.max())
            mean_r = float(r.mean())
            thick = self.p.structure.total_thickness()
            mass = self.p.areal_mass()
        except (SolverError, OutOfRangeError, MaterialCycleError, KeyError, FloatingPointError):
            return ObjectiveTerms(math.nan, math.nan, math.nan, math.nan, INVALID)
        if not np.isfinite(worst):
            return ObjectiveTerms(worst, mean_r, thick, mass, INVALID)
        j = 0.0
        if s.w_worst:
            j += s.w_worst * worst / max(abs(s.rl_ref_db), 1e-9)
        if s.w_mean:
            j += s.w_mean * mean_r / 10 ** (s.rl_ref_db / 10)
        if s.w_thickness:
            j += s.w_thickness * thick / max(s.thickness_ref, 1e-12)
        if s.w_mass:
            j += s.w_mass * mass / max(s.mass_ref, 1e-12)
        if s.thickness_max and thick > s.thickness_max:
            j += 10.0 + 100.0 * (thick / s.thickness_max - 1.0)
        return ObjectiveTerms(worst, mean_r, thick, mass, float(j))


class _Space:
    """Maps optimiser vectors <-> parameter values (log scale for wide positive ranges)."""

    def __init__(self, variables):
        self.vars = variables
        self.log = [v.lower > 0 and v.upper / v.lower >= 100 for v in variables]

    def bounds(self):
        return [(math.log10(v.lower), math.log10(v.upper)) if lg else (v.lower, v.upper)
                for v, lg in zip(self.vars, self.log)]

    def decode(self, x):
        return [10 ** xi if lg else xi for xi, lg in zip(x, self.log)]

    def encode(self, values):
        return [math.log10(max(val, 1e-300)) if lg else val for val, lg in zip(values, self.log)]


def validate_settings(project: Project, s: OptimizationSettings):
    if not s.variables and not s.choices:
        raise OptimizationError("no optimisation variables selected")
    if s.f_max < s.f_min or s.f_min <= 0:
        raise OptimizationError("invalid frequency band")
    if not s.pols:
        raise OptimizationError("select at least one polarisation")
    if s.w_worst == s.w_mean == s.w_thickness == s.w_mass == 0:
        raise OptimizationError("all objective weights are zero")
    for v in s.variables:
        if not v.upper > v.lower:
            raise OptimizationError(f"variable {v.path}: upper bound must exceed lower bound")
        try:
            get_param(project, v.path)
        except (KeyError, AttributeError, IndexError):
            raise OptimizationError(f"variable {v.path} no longer exists") from None
    for c in s.choices:
        if not c.candidates:
            raise OptimizationError("material choice without candidates")
        for name in c.candidates:
            if name not in project.materials:
                raise OptimizationError(f"unknown candidate material {name!r}")
        project.structure.layer_by_uid(c.uid)


def _impedance_at(project, name, f):
    eps, mu = project.materials[name].eps_mu(np.array([f]), project.resolver)
    return abs(np.sqrt(mu[0] / eps[0]))


def optimize(project: Project, settings: OptimizationSettings | None = None, progress=None,
             throttle_s=0.1) -> OptimizationResult:
    """Run the optimisation.  ``progress(info) -> bool`` may return True to stop.

    ``info`` keys: stage ('global'|'local'), combo, n_combos, iteration, best, n_evals,
    history (list of (n_evals, best)).
    """
    s = settings or project.optimization
    validate_settings(project, s)
    ev = Evaluator(project, s)
    space = _Space(s.variables)
    rng_seed = s.seed
    t0 = time.monotonic()
    history = []
    best = {"j": math.inf, "x": None, "combo": None}
    state = {"last_emit": 0.0, "stopped": False, "iteration": 0, "stage": "global",
             "combo": 0, "n_combos": 1}

    def emit(force=False):
        if progress is None:
            return
        now = time.monotonic()
        if not force and now - state["last_emit"] < throttle_s:
            return
        state["last_emit"] = now
        stop = progress({"stage": state["stage"], "combo": state["combo"],
                         "n_combos": state["n_combos"], "iteration": state["iteration"],
                         "best": best["j"], "n_evals": ev.n_evals, "history": list(history)})
        if stop:
            state["stopped"] = True
            raise _Stop

    def apply(xc, combo):
        for v, val in zip(s.variables, space.decode(xc)):
            set_param(ev.p, v.path, val)
        if combo is not None:
            for c, name in zip(s.choices, combo):
                ev.p.structure.layer_by_uid(c.uid).material = name

    def record(j, xc, combo):
        if j < best["j"]:
            best.update(j=j, x=list(xc), combo=combo)
            history.append((ev.n_evals, j))

    def f_cont(xc, combo, smooth=False):
        apply(xc, combo)
        j = ev.terms(smooth=smooth).objective
        if not smooth:
            record(j, xc, combo)
        return j

    n_cont = len(s.variables)
    candidate_lists = [list(c.candidates) for c in s.choices]
    n_combos = math.prod(len(c) for c in candidate_lists) if candidate_lists else 1
    x_start = space.encode([get_param(project, v.path) for v in s.variables])
    bounds = space.bounds()
    x_start = [min(max(x, lo), hi) for x, (lo, hi) in zip(x_start, bounds)]

    def de_callback(intermediate_result=None):
        state["iteration"] += 1
        emit()
        return False

    try:
        if n_combos <= MAX_ENUMERATED_COMBOS:
            combos = list(itertools.product(*candidate_lists)) if candidate_lists else [None]
            state["n_combos"] = len(combos)
            for ci, combo in enumerate(combos):
                state["combo"] = ci + 1
                state["iteration"] = 0
                if n_cont == 0:
                    f_cont([], combo)
                    emit()
                    continue
                differential_evolution(
                    lambda x, combo=combo: f_cont(x, combo), bounds, maxiter=int(s.maxiter),
                    popsize=int(s.popsize), seed=rng_seed, polish=False, init="sobol",
                    x0=x_start, callback=de_callback, tol=1e-6, atol=1e-9, updating="immediate")
        else:
            # Ordered integer encoding of materials (by wave impedance at the band centre).
            fc = math.sqrt(s.f_min * s.f_max)
            ordered = [sorted(c, key=lambda n: _impedance_at(project, n, fc)) for c in candidate_lists]
            state["n_combos"] = 1
            state["combo"] = 1
            int_bounds = [(0, len(c) - 1) for c in ordered]

            def f_mixed(x):
                xc = x[:n_cont]
                combo = tuple(o[int(round(i))] for o, i in zip(ordered, x[n_cont:]))
                return f_cont(xc, combo)

            integrality = [False] * n_cont + [True] * len(ordered)
            differential_evolution(
                f_mixed, bounds + int_bounds, maxiter=int(s.maxiter), popsize=int(s.popsize),
                seed=rng_seed, polish=False, integrality=integrality, callback=de_callback,
                tol=1e-6, atol=1e-9, updating="immediate")

        if s.polish and n_cont and best["x"] is not None and math.isfinite(best["j"]):
            state["stage"] = "local"
            state["iteration"] = 0
            combo = best["combo"]

            def lb_callback(intermediate_result=None):
                state["iteration"] += 1
                emit()

            sol = minimize(lambda x: f_cont(x, combo, smooth=True), best["x"], method="L-BFGS-B",
                           bounds=bounds, callback=lb_callback, options={"maxiter": 200})
            f_cont(sol.x, combo)  # records only if the true objective improved
    except _Stop:
        pass

    elapsed = time.monotonic() - t0
    if best["x"] is None and best["combo"] is None and not history:
        return OptimizationResult({}, {}, None, history, ev.n_evals, state["stopped"], elapsed,
                                  "no valid design found")
    apply(best["x"] or [], best["combo"])
    terms = ev.terms()
    values = {tuple(v.path): val for v, val in zip(s.variables, space.decode(best["x"] or []))}
    choices = ({c.uid: name for c, name in zip(s.choices, best["combo"])} if best["combo"] else {})
    state["stage"] = "done"
    if progress is not None:
        try:
            progress({"stage": "done", "combo": state["combo"], "n_combos": state["n_combos"],
                      "iteration": state["iteration"], "best": terms.objective,
                      "n_evals": ev.n_evals, "history": list(history)})
        except Exception:  # noqa: BLE001 - progress sinks must not break the result
            pass
    return OptimizationResult(values, choices, terms, history, ev.n_evals, state["stopped"], elapsed,
                              "stopped by user" if state["stopped"] else "converged")


def apply_result(project: Project, result: OptimizationResult):
    for path, val in result.values.items():
        set_param(project, path, val)
    for uid, name in result.choices.items():
        project.structure.layer_by_uid(uid).material = name


def evaluate_terms(project: Project, settings: OptimizationSettings | None = None) -> ObjectiveTerms:
    return Evaluator(project, settings or project.optimization).terms()
