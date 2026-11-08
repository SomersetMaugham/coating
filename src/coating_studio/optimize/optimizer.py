"""Absorber optimisation: continuous parameters + discrete material choices.

Objective (all terms dimensionless, normalised by user reference values)::

    J = w_worst * (max_i margin_i + RL_ref) / |RL_ref|      (RL in dB, negative is better)
      + w_mean  * (1/K) sum_i mean_i(|Gamma|^2) / 10^(goal_i/10)
      + w_thick * thickness / thickness_ref
      + w_mass  * areal_mass / mass_ref
      + penalty(thickness > thickness_max)

The spec is a list of K enabled targets (frequency band x angle range x polarisations, each with a
required level goal_i).  margin_i = worst_i - goal_i, where worst_i is the maximum of 20log10|Gamma|
over target i's grid; margin <= 0 means the target is met, and the optimiser minimises the worst
margin.  With one target whose goal equals RL_ref this is exactly the schema-1 objective
(w_worst * RL_worst / |RL_ref|, w_mean * mean|Gamma|^2 / 10^(RL_ref/10)).  Global search: SciPy differential evolution.  When the
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
from coating_studio.materials.checks import Issue, check_material
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
    worst_db: float  # worst RL of the binding target (the one with the largest margin)
    mean_r: float
    thickness: float  # m
    mass: float  # kg/m^2
    objective: float
    margin_db: float = math.nan  # largest worst-minus-goal over the targets (<= 0: all met)
    per_target: tuple = ()  # ((worst_db, margin_db), ...) for the enabled targets, in order

    def as_dict(self):
        return {"worst_db": self.worst_db, "mean_r": self.mean_r, "thickness": self.thickness,
                "mass": self.mass, "objective": self.objective, "margin_db": self.margin_db,
                "per_target": [list(t) for t in self.per_target]}


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
    """Grid of the first enabled target (kept for callers of the single-band API)."""
    targets = s.enabled_targets() or s.targets
    return targets[0].grid()


def target_frequencies(s: OptimizationSettings):
    """All frequencies the enabled targets evaluate (sorted, unique) - e.g. for material checks."""
    fs = [t.grid()[0] for t in s.enabled_targets()]
    return np.unique(np.concatenate(fs)) if fs else np.array([])


class _Group:
    """Enabled targets sharing one frequency grid are solved together (union of angles and pols)."""

    def __init__(self, f):
        self.f = f
        self.members = []  # (target index, target, angles)

    def finish(self):
        self.th = np.unique(np.concatenate([m[2] for m in self.members]))
        self.pols = tuple(p for p in ("TE", "TM") if any(p in m[1].pols for m in self.members))
        self.slices = [(i, t, np.searchsorted(self.th, th)) for i, t, th in self.members]


class Evaluator:
    """Evaluates the objective for a working copy of the project."""

    def __init__(self, project: Project, settings: OptimizationSettings):
        self.p = project.copy()
        self.s = settings
        self.targets = settings.enabled_targets()
        groups = {}
        for i, t in enumerate(self.targets):
            f, th = t.grid()
            g = groups.setdefault((t.f_min, t.f_max, len(f)), _Group(f))
            g.members.append((i, t, th))
        self.groups = list(groups.values())
        for g in self.groups:
            g.finish()
        # dB shift that turns each target's worst RL into "margin + RL_ref"; exactly 0 when the goal
        # equals the RL reference (schema-1 projects), so their objective is bit-for-bit unchanged.
        self.shift = [s_ if (s_ := settings.rl_ref_db - t.goal_db) != 0 else 0.0 for t in self.targets]
        self.n_evals = 0

    def _per_target_db(self):
        """[(dB array over the target's own grid, R array)] in target order."""
        out = [None] * len(self.targets)
        for g in self.groups:
            res = solve(self.p.structure, self.p.materials, g.f, g.th, pols=g.pols)
            for i, t, idx in g.slices:
                r = np.stack([res.pol[k].R[:, idx] for k in t.pols])
                out[i] = (10 * np.log10(np.maximum(r, 1e-30)), r)
        return out

    def terms(self, smooth=False) -> ObjectiveTerms:
        s = self.s
        self.n_evals += 1
        k = len(self.targets)
        try:
            data = self._per_target_db()
            true_worst = [float(db.max()) for db, _ in data]
            if smooth:
                # Smooth max per target; with several targets remove the grid-size bias
                # (SMOOTH*ln N) so a dense angle grid does not outweigh a single-angle target.
                sm = [float(SMOOTH_DB * logsumexp(db / SMOOTH_DB)) - (SMOOTH_DB * math.log(db.size) if k > 1 else 0.0)
                      for db, _ in data]
            else:
                sm = true_worst
            vals = [w + sh for w, sh in zip(sm, self.shift)]
            worst_term = vals[0] if k == 1 else (float(SMOOTH_DB * logsumexp(np.array(vals) / SMOOTH_DB))
                                                 if smooth else max(vals))
            means = [float(r.mean()) for _, r in data]
            mean_r = float(np.mean(means))
            mean_term = float(np.mean([m / 10 ** (t.goal_db / 10) for m, t in zip(means, self.targets)]))
            thick = self.p.structure.total_thickness()
            mass = self.p.areal_mass()
        except (SolverError, OutOfRangeError, MaterialCycleError, KeyError, FloatingPointError):
            return ObjectiveTerms(math.nan, math.nan, math.nan, math.nan, INVALID)
        margins = [w - t.goal_db for w, t in zip(true_worst, self.targets)]
        b = int(np.argmax(margins))
        worst = true_worst[b]
        per = tuple(zip(true_worst, margins))
        if not np.isfinite(worst_term):
            return ObjectiveTerms(worst, mean_r, thick, mass, INVALID, margins[b], per)
        j = 0.0
        if s.w_worst:
            j += s.w_worst * worst_term / max(abs(s.rl_ref_db), 1e-9)
        if s.w_mean:
            j += s.w_mean * mean_term
        if s.w_thickness:
            j += s.w_thickness * thick / max(s.thickness_ref, 1e-12)
        if s.w_mass:
            j += s.w_mass * mass / max(s.mass_ref, 1e-12)
        if s.thickness_max and thick > s.thickness_max:
            j += 10.0 + 100.0 * (thick / s.thickness_max - 1.0)
        return ObjectiveTerms(worst, mean_r, thick, mass, float(j), margins[b], per)


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
    targets = s.enabled_targets()
    if not targets:
        raise OptimizationError("no enabled optimisation target")
    for n, t in enumerate(s.targets, start=1):
        if not t.enabled:
            continue
        if t.f_max < t.f_min or t.f_min <= 0:
            raise OptimizationError(f"target {n}: invalid frequency band")
        if not (0 <= t.angle_min <= t.angle_max < 90):
            raise OptimizationError(f"target {n}: invalid angle range")
        if int(t.n_f) < 1 or int(t.n_angle) < 1:
            raise OptimizationError(f"target {n}: need at least one point")
        if not t.pols or any(p not in ("TE", "TM") for p in t.pols):
            raise OptimizationError(f"target {n}: select at least one polarisation")
        if not math.isfinite(t.goal_db):
            raise OptimizationError(f"target {n}: invalid goal")
    if s.w_worst == s.w_mean == s.w_thickness == s.w_mass == 0:
        raise OptimizationError("all objective weights are zero")
    for v in s.variables:
        if not v.upper > v.lower:
            raise OptimizationError(f"variable {v.path}: upper bound must exceed lower bound")
        try:
            get_param(project, v.path)
        except (KeyError, AttributeError, IndexError):
            raise OptimizationError(f"variable {v.path} no longer exists") from None
        if tuple(v.path[0::2]) == ("layer", "L") and v.lower <= 0 \
                and project.structure.layer_by_uid(v.path[1]).model == "parallel_rlc":
            # L -> 0+ shorts the sheet while L = 0 means no inductor: the range must not reach that jump
            raise OptimizationError(f"variable {v.path}: the lower bound of a parallel L must be above zero")
    for c in s.choices:
        if not c.candidates:
            raise OptimizationError("material choice without candidates")
        for name in c.candidates:
            if name not in project.materials:
                raise OptimizationError(f"unknown candidate material {name!r}")
        try:
            project.structure.layer_by_uid(c.uid)
        except KeyError:
            raise OptimizationError(f"choice layer {c.uid!r} no longer exists") from None


def preflight(project: Project, settings: OptimizationSettings | None = None):
    """Checks before an optimisation run: ``(errors, warnings)`` as lists of ``Issue``.

    Raises ``OptimizationError`` for invalid settings (``validate_settings``).  Errors are unknown
    materials and material-check errors on the enabled targets' frequencies; warnings are the
    material-check warnings.  Informational issues (e.g. built-in demo values) are left out."""
    s = settings or project.optimization
    validate_settings(project, s)
    f = target_frequencies(s)
    names = set(project.structure.referenced_materials())
    for c in s.choices:
        names |= set(c.candidates)
    errors, warnings = [], []
    for n in sorted(names):
        if n not in project.materials:
            errors.append(Issue("error", "unknown_material", n, {"n": n}))
            continue
        for iss in check_material(project.materials[n], f, project.resolver):
            if iss.level == "error":
                errors.append(iss)
            elif iss.level == "warning":
                warnings.append(iss)
    return errors, warnings


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
            iv = s.frequency_intervals()
            fc = math.sqrt(min(a for a, _ in iv) * max(b for _, b in iv))  # centre of the spec envelope
            ordered = [sorted(c, key=lambda n: _impedance_at(project, n, fc)) for c in candidate_lists]
            state["n_combos"] = 1
            state["combo"] = 1
            int_bounds = [(0, len(c) - 1) for c in ordered]

            def f_mixed(x):
                xc = x[:n_cont]
                combo = tuple(o[int(round(i))] for o, i in zip(ordered, x[n_cont:]))
                return f_cont(xc, combo)

            integrality = [False] * n_cont + [True] * len(ordered)
            # Seed the population with the current design (as the enumerated branch does), so restarting from a
            # previous best cannot end worse than it.  Only possible when every layer's current material is
            # one of its candidates.
            current = [project.structure.layer_by_uid(c.uid).material for c in s.choices]
            x0 = None
            if all(m in o for m, o in zip(current, ordered)):
                x0 = list(x_start) + [o.index(m) for m, o in zip(current, ordered)]
            differential_evolution(
                f_mixed, bounds + int_bounds, maxiter=int(s.maxiter), popsize=int(s.popsize),
                seed=rng_seed, polish=False, integrality=integrality, x0=x0, callback=de_callback,
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
