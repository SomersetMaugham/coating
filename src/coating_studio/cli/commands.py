"""Subcommand implementations of ``coating-cli``.

Each command is a plain function: it takes options and a ``RunControl`` and returns a ``CommandResult`` (or
raises ``CliError``).  Argument parsing, stdout, signal handling and exit codes live in ``cli/__init__.py``,
so the same functions can later back other front ends (docs/CLI_PLAN.md, section 8).
"""

from __future__ import annotations

import csv
import io
import math
import os
import secrets
from dataclasses import asdict, dataclass, field

import numpy as np

from coating_studio.cli.output import LOAD_ERRORS, MODEL_ERRORS, CliError, issue_dict, load_error, model_error
from coating_studio.core.solver import solve
from coating_studio.core.structure import SlabLayer
from coating_studio.core.units import power_to_db, si_unit, to_display
from coating_studio.examples import EXAMPLES
from coating_studio.limits import (
    FITTED_PREFIX, limit_issues, measured_range, mixture_range_issues, rozanov_required_mu_d, static_permeability,
    target_limits,
)
from coating_studio.materials.checks import Issue, check_material, is_builtin_demo
from coating_studio.materials.library import builtin_materials
from coating_studio.materials.models import MaterialCycleError, MixtureMaterial
from coating_studio.optimize.optimizer import (
    MAX_ENUMERATED_COMBOS, OptimizationError, apply_result, evaluate_terms, optimize, preflight,
)
from coating_studio.project import Project, available_params, describe_path, get_param, param_unit
from coating_studio.tolerance import run_tolerance, tolerance_frequencies, yield_intervals

POLS = ("TE", "TM", "avg")


@dataclass
class CommandResult:
    result: dict
    warnings: list = field(default_factory=list)
    stopped: bool = False
    input_info: dict | None = None
    text: str | None = None  # raw text for stdout instead of the envelope (CSV without --output)


def warning(code, message, **extra):
    return {"code": code, "level": "warning", "message": message, **extra}


# ---------------------------------------------------------------------------
# helpers

def load_project(path):
    try:
        p = Project.load(path)
    except LOAD_ERRORS as e:
        raise load_error(e, path) from None
    return p, {"path": str(path), "schema": getattr(p, "source_schema", None)}


def resolve_seed(seed):
    """CLI seed: negative = random (GUI convention); random seeds are drawn here so runs can be replayed."""
    if seed is not None and seed < 0:
        seed = None
    return secrets.randbelow(2 ** 31) if seed is None else int(seed)


def param_value(value_si, display_unit, project=None, path=None):
    d = {"value": value_si, "unit": si_unit(display_unit),
         "display_value": to_display(value_si, display_unit), "display_unit": display_unit}
    if project is not None and path is not None and path[0] == "material" and list(path[2:]) == ["fraction"]:
        m = project.materials.get(path[1])
        if isinstance(m, MixtureMaterial):
            from coating_studio.cli.spec import mixture_densities, vol_to_wt
            try:
                rho_i, rho_m = mixture_densities(project, m)
                d["value_wt"] = vol_to_wt(value_si, rho_i, rho_m)
            except (KeyError, MaterialCycleError):
                pass
    return d


def layer_label(project, uid):
    for i, ly in enumerate(project.structure.layers, start=1):
        if ly.uid == uid:
            return ly.name or str(i)
    return None


def check_output_path(path, force, input_path=None):
    if path is None:
        return
    if input_path is not None and os.path.abspath(path) == os.path.abspath(input_path):
        return  # --in-place handled by the caller
    if os.path.exists(path) and not force:
        raise CliError("file_exists", f"{path} exists (use --force to overwrite)", 3, {"path": str(path)})


def write_text(path, text):
    try:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    except OSError as e:
        raise CliError("file_unwritable", f"{path}: {e.strerror or e}", 3, {"path": str(path)}) from None


def save_project(project, path):
    try:
        project.save(path)
    except OSError as e:
        raise CliError("file_unwritable", f"{path}: {e.strerror or e}", 3, {"path": str(path)}) from None


def csv_text(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def rl_db(res, pol):
    return power_to_db(res.quantity("R", pol))


def quantity(res, q, pol):
    return rl_db(res, pol) if q == "RL" else res.quantity(q, pol)


def target_rows(project, settings=None):
    """Per enabled target: worst RL and margin (margin = worst - goal; <= 0 means met)."""
    s = settings or project.optimization
    targets = s.enabled_targets()
    if not targets:
        return [], None
    terms = evaluate_terms(project, s)
    rows = []
    for i, (t, pt) in enumerate(zip(targets, terms.per_target)):
        worst, margin = pt
        rows.append({"index": i, "name": t.name, "goal_db": t.goal_db, "worst_rl_db": worst, "margin_db": margin})
    margins = [r["margin_db"] for r in rows if r["margin_db"] is not None and math.isfinite(r["margin_db"])]
    return rows, (max(margins) if len(margins) == len(rows) else None)


def first_failure(project, settings=None):
    """Re-run the first enabled target's solve to report why evaluations fail."""
    s = settings or project.optimization
    for t in s.enabled_targets():
        f, th = t.grid()
        try:
            solve(project.structure, project.materials, f, th, pols=tuple(t.pols))
        except MODEL_ERRORS as e:
            err = model_error(e)
            return {"code": err.code, "message": err.message, **({"details": err.details} if err.details else {})}
    return None


def optimisation_size(project, s=None):
    s = s or project.optimization
    n_cont = len(s.variables)
    n_combos = math.prod(len(c.candidates) for c in s.choices) if s.choices else 1
    if n_cont == 0:
        evals = n_combos
    elif n_combos <= MAX_ENUMERATED_COMBOS:
        evals = n_combos * (int(s.maxiter) + 1) * int(s.popsize) * n_cont
    else:
        n = n_cont + len(s.choices)
        evals = (int(s.maxiter) + 1) * int(s.popsize) * n
    if s.polish and n_cont:
        evals += 200 * (n_cont + 1)
    return {"n_vars": n_cont, "n_choices": len(s.choices), "n_combos": n_combos, "estimated_max_evals": evals}


def target_dict(t):
    return {"name": t.name, "f_hz": [t.f_min, t.f_max], "n_f": t.n_f, "angle_deg": [t.angle_min, t.angle_max],
            "n_angle": t.n_angle, "pols": list(t.pols), "goal_db": t.goal_db, "enabled": t.enabled}


def sweep_dict(sw):
    return {"f_hz": [sw.f_min, sw.f_max], "n_f": sw.n_f, "log_f": sw.log_f, "angle_deg": sw.angle,
            "angle_range_deg": [sw.angle_min, sw.angle_max], "n_angle": sw.n_angle, "f_at_hz": sw.f_at,
            "map_n_f": sw.map_n_f, "map_n_angle": sw.map_n_angle}


def used_materials(project, include_candidates=True):
    """Materials the design uses, with mixture constituents expanded (sorted)."""
    names = set(project.structure.referenced_materials())
    if include_candidates:
        for c in project.optimization.choices:
            names |= set(c.candidates)
    seen, stack = set(), list(names)
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        if n in project.materials:
            stack.extend(project.materials[n].references())
    return sorted(seen)


# ---------------------------------------------------------------------------
# examples

def cmd_examples_list():
    out = []
    for key, (name, builder) in EXAMPLES.items():
        p = builder()
        desc = p.notes or (builder.__doc__ or "").strip()
        out.append({"key": key, "name": name, "description": desc, "n_layers": len(p.structure.layers)})
    return CommandResult({"examples": out})


def cmd_examples_save(key, output, force=False):
    if key not in EXAMPLES:
        raise CliError("unknown_example", f"unknown example {key!r}", 3, {"known": list(EXAMPLES)})
    if not output:
        raise CliError("usage", "examples save needs -o PATH", 2)
    check_output_path(output, force)
    p = EXAMPLES[key][1]()
    save_project(p, output)
    return CommandResult({"key": key, "output_path": str(output), "n_layers": len(p.structure.layers)})


# ---------------------------------------------------------------------------
# info

def _layer_dict(i, ly):
    d = {"index": i, "uid": ly.uid, "kind": "slab" if isinstance(ly, SlabLayer) else "sheet", "name": ly.name}
    if isinstance(ly, SlabLayer):
        d.update(material=ly.material, thickness_m=ly.thickness)
    else:
        d.update(model=ly.model, R_ohm=ly.R, X_ohm=ly.X, L_h=ly.L, C_f=ly.C)
    return d


def cmd_info(path):
    p, inp = load_project(path)
    try:
        mass = p.areal_mass()
    except (KeyError, MaterialCycleError):
        mass = None
    s = p.optimization
    variables = []
    for v in s.variables:
        try:
            unit = param_unit(p, v.path)
        except (KeyError, AttributeError, IndexError):
            unit = ""
        variables.append({"path": list(v.path), "label": describe_path(p, v.path),
                          "lower": param_value(v.lower, unit, p, v.path), "upper": param_value(v.upper, unit, p, v.path)})
    params = []
    for path_, label, unit in available_params(p):
        params.append({"path": list(path_), "label": label, **param_value(get_param(p, path_), unit, p, path_)})
    result = {
        "name": p.name, "notes": p.notes, "incident": p.structure.incident,
        "backing": {"kind": p.structure.backing.kind, "material": p.structure.backing.material},
        "layers": [_layer_dict(i, ly) for i, ly in enumerate(p.structure.layers, start=1)],
        "materials": [{"name": m.name, "kind": m.kind, "users": p.material_users(m.name),
                       "used": bool(p.material_users(m.name))} for m in p.materials.values()],
        "total_thickness_m": p.structure.total_thickness(), "areal_mass_kg_m2": mass,
        "sweep": sweep_dict(p.sweep),
        "optimization": {
            "targets": [target_dict(t) for t in s.targets], "variables": variables,
            "choices": [{"uid": c.uid, "layer": layer_label(p, c.uid), "candidates": list(c.candidates)}
                        for c in s.choices],
            "weights": {"w_worst": s.w_worst, "w_mean": s.w_mean, "w_thickness": s.w_thickness, "w_mass": s.w_mass},
            "rl_ref_db": s.rl_ref_db, "thickness_ref_m": s.thickness_ref, "mass_ref_kg_m2": s.mass_ref,
            "thickness_max_m": s.thickness_max, "maxiter": s.maxiter, "popsize": s.popsize, "seed": s.seed,
            "polish": s.polish, **optimisation_size(p)},
        "tolerance": asdict(p.tolerance),
        "params": params,
    }
    return CommandResult(result, input_info=inp)


# ---------------------------------------------------------------------------
# check

def measured_range_issues(p):
    """``sweep_outside_data`` errors: sweep, targets or tolerance band beyond the measured data."""
    names = set(p.structure.referenced_materials())
    for c in p.optimization.choices:
        names |= set(c.candidates)
    rng = measured_range(p, names)
    if rng is None:
        return []
    lo, hi = rng
    spans = [("sweep", p.sweep.f_min, p.sweep.f_max)]
    spans += [(f"target {i + 1}", t.f_min, t.f_max) for i, t in enumerate(p.optimization.enabled_targets())]
    if p.tolerance.band_min and p.tolerance.band_max:
        spans.append(("tolerance band", p.tolerance.band_min, p.tolerance.band_max))
    return [Issue("error", "sweep_outside_data", "", {"where": w, "flo": a / 1e9, "fhi": b / 1e9,
                                                       "lo": lo / 1e9, "hi": hi / 1e9})
            for w, a, b in spans if a < lo - 1e-9 * hi or b > hi + 1e-9 * hi]


def cmd_check(path, no_opt=False):
    p, inp = load_project(path)
    issues, seen = [], set()

    def add(d):
        key = (d["code"], d["material"], d["target"], d["message"])
        if key not in seen:
            seen.add(key)
            issues.append(d)

    for n in sorted(set(p.structure.referenced_materials())):
        if n not in p.materials:
            add(issue_dict(Issue("error", "unknown_material", n, {"n": n})))
    # trial solve on the frequency sweep (the GUI's "Cannot compute" diagnostic)
    try:
        if not any(i["code"] == "unknown_material" for i in issues):
            solve(p.structure, p.materials, p.sweep.freq_grid(), p.sweep.angle)
    except MODEL_ERRORS as e:
        err = model_error(e)
        add({"level": "error", "code": err.code, "material": err.details.get("material", ""), "target": None,
             "args": err.details, "message": err.message})
    f = p.sweep.freq_grid(min(p.sweep.n_f, 200))
    for n in used_materials(p):
        if n in p.materials:
            for iss in check_material(p.materials[n], f, p.resolver):
                add(issue_dict(iss))
    s = p.optimization
    if (s.variables or s.choices) and not no_opt:
        try:
            errs, warns = preflight(p, s)
            for iss in errs + warns:
                add(issue_dict(iss))
        except (OptimizationError, KeyError) as e:
            add({"level": "error", "code": "invalid_optimization_settings", "material": "", "target": None,
                 "args": {}, "message": str(e)})
    used = used_materials(p)
    for iss in mixture_range_issues(p, float(np.sqrt(p.sweep.f_min * p.sweep.f_max)), names=set(used)):
        add(issue_dict(iss))
    for iss in measured_range_issues(p):
        add(issue_dict(iss))
    limits = target_limits(p)
    for ti, iss in limit_issues(limits):
        add(issue_dict(iss, target=ti))
    counts = {lvl: sum(1 for i in issues if i["level"] == lvl) for lvl in ("error", "warning", "info")}
    result = {"valid": counts["error"] == 0, "counts": counts, "issues": issues, "limits": limits,
              "optimization": optimisation_size(p)}
    if counts["error"]:
        raise CliError("validation_failed", f"{counts['error']} error(s) found", 4, result=result)
    return CommandResult(result, input_info=inp)


# ---------------------------------------------------------------------------
# solve

def _apply_sweep_overrides(sw, o):
    def ghz(key):
        return None if o.get(key) is None else float(o[key]) * 1e9
    for attr, key in (("f_min", "f_min_ghz"), ("f_max", "f_max_ghz"), ("f_at", "f_at_ghz")):
        if ghz(key) is not None:
            setattr(sw, attr, ghz(key))
    for attr, key in (("n_f", "n_f"), ("n_angle", "n_angle"), ("map_n_f", "map_n_f"), ("map_n_angle", "map_n_angle")):
        if o.get(key) is not None:
            setattr(sw, attr, int(o[key]))
    for attr, key in (("angle", "angle_deg"), ("angle_min", "angle_min_deg"), ("angle_max", "angle_max_deg")):
        if o.get(key) is not None:
            setattr(sw, attr, float(o[key]))
    if o.get("log_f") is not None:
        sw.log_f = bool(o["log_f"])


def _best(db, f, th, sweep):
    i = int(np.nanargmin(db))
    if sweep == "freq":
        return {"rl_db": db.flat[i], "f_hz": f[i]}
    if sweep == "angle":
        return {"rl_db": db.flat[i], "theta_deg": th[i]}
    fi, ti = np.unravel_index(i, db.shape)
    return {"rl_db": db[fi, ti], "f_hz": f[fi], "theta_deg": th[ti]}


def cmd_solve(path, sweep="freq", quantity_name="RL", pol="avg", targets=False, summary_only=False,
              layer_absorption=False, fmt="json", output=None, force=False, overrides=None):
    p, inp = load_project(path)
    sw = p.sweep
    _apply_sweep_overrides(sw, overrides or {})
    if sweep == "freq":
        f, th = sw.freq_grid(), np.array([sw.angle])
    elif sweep == "angle":
        f, th = np.array([sw.f_at]), sw.angle_grid()
    else:
        f, th = sw.freq_grid(sw.map_n_f), sw.angle_grid(sw.map_n_angle)
    try:
        res = solve(p.structure, p.materials, f, th)
    except MODEL_ERRORS as e:
        raise model_error(e) from None

    def cut(a):
        return a[:, 0] if sweep == "freq" else a[0, :] if sweep == "angle" else a

    if fmt == "csv":
        text = _solve_csv(res, sweep, quantity_name, pol)
        if output is None:
            return CommandResult({}, input_info=inp, text=text)
        check_output_path(output, force)
        write_text(output, text)
        return CommandResult({"output_path": str(output), "rows": text.count("\n") - 1}, input_info=inp)

    warnings = []
    try:
        mass = p.areal_mass()
    except (KeyError, MaterialCycleError):
        mass = None
    result = {"sweep": sweep, "summary": {
        "best": {q: _best(cut(rl_db(res, q)), res.f, res.theta, sweep) for q in POLS},
        "total_thickness_m": p.structure.total_thickness(), "areal_mass_kg_m2": mass}}
    if targets:
        if any(v is not None for v in (overrides or {}).values()):
            warnings.append(warning("targets_use_own_grid", "sweep overrides do not change the targets: each target "
                                    "is evaluated on its own band, angles and polarisations"))
        try:
            rows, max_margin = target_rows(p)
        except MODEL_ERRORS as e:
            rows, max_margin = None, None
            warnings.append(warning("targets_failed", f"target evaluation failed: {e}"))
        result["targets"], result["max_margin_db"] = rows, max_margin
    if not summary_only:
        data = {"f_hz": res.f if sweep != "angle" else res.f[0],
                "theta_deg": res.theta if sweep != "freq" else res.theta[0]}
        if sweep == "map":
            data["rl_db"] = {pol: rl_db(res, pol)}
        else:
            data["rl_db"] = {q: cut(rl_db(res, q)) for q in POLS}
            for name in ("R", "T", "A"):
                data[name] = {q: cut(res.quantity(name, q)) for q in POLS}
            if layer_absorption:
                data["layer_uids"] = list(res.layer_uids)
                data["A_layers"] = {q: [cut(a) for a in res.layer_absorption(q)] for q in POLS}
        result["data"] = data
    if output is not None:
        check_output_path(output, force)
        from coating_studio.cli.output import dumps
        write_text(output, dumps(result) + "\n")
        result = {"output_path": str(output), "sweep": sweep, "summary": result["summary"],
                  **({"targets": result["targets"], "max_margin_db": result["max_margin_db"]} if targets else {})}
    return CommandResult(result, warnings=warnings, input_info=inp)


def _solve_csv(res, sweep, q, pol):
    """Same columns and number formats as the GUI's data export (gui/plots/views.py ``data_table``)."""
    if sweep == "map":
        z = rl_db(res, pol)
        header = ["f [GHz] \\ theta [deg]"] + [f"{t:.6g}" for t in res.theta]
        rows = [[f"{fi / 1e9:.9g}"] + [f"{v:.6g}" for v in z[i]] for i, fi in enumerate(res.f)]
        return csv_text(header, rows)
    if sweep == "freq":
        cols = [quantity(res, q, p_)[:, 0] for p_ in POLS]
        header = ["f [GHz]"] + [f"{q} {p_}" for p_ in POLS]
        return csv_text(header, [[f"{a:.9g}" for a in row] for row in zip(res.f / 1e9, *cols)])
    cols = [quantity(res, q, p_)[0, :] for p_ in POLS]
    header = ["theta [deg]"] + [f"{q} {p_}" for p_ in POLS]
    return csv_text(header, [[f"{a:.9g}" for a in row] for row in zip(res.theta, *cols)])


# ---------------------------------------------------------------------------
# optimize

def _at_bound(v, value):
    span = v.upper - v.lower
    if value <= v.lower + 1e-3 * span:
        return "lower"
    if value >= v.upper - 1e-3 * span:
        return "upper"
    return None


def _terms_dict(t, thickness_max=None):
    if t is None:
        return None
    at_limit = thickness_max is not None and t.thickness >= thickness_max * (1 - 1e-3)
    return {"objective": t.objective, "worst_db": t.worst_db, "margin_db": t.margin_db, "mean_r": t.mean_r,
            "thickness_m": t.thickness, "mass_kg_m2": t.mass, "thickness_max_m": thickness_max,
            "thickness_at_limit": at_limit}


def cmd_optimize(path, control, output=None, in_place=False, force=False, seed=None, maxiter=None,
                 popsize=None, polish=None, strict=False, restarts=1):
    p, inp = load_project(path)
    if in_place:
        output = path
    s = p.optimization
    # One-off run options (and a randomly drawn seed) must not leak into the saved design: the next run would
    # silently repeat the same seed and inherit e.g. a large --popsize.
    saved_settings = {k: getattr(s, k) for k in ("maxiter", "popsize", "polish", "seed")}
    if maxiter is not None:
        s.maxiter = int(maxiter)
    if popsize is not None:
        s.popsize = int(popsize)
    if polish is not None:
        s.polish = bool(polish)
    s.seed = resolve_seed(seed if seed is not None else s.seed)
    check_output_path(output, force, input_path=path if in_place else None)
    try:
        errors, warns = preflight(p, s)
    except (OptimizationError, KeyError) as e:
        raise model_error(e if isinstance(e, OptimizationError) else OptimizationError(str(e))) from None
    warns = list(warns) + mixture_range_issues(p, float(np.sqrt(p.sweep.f_min * p.sweep.f_max)),
                                               names=set(used_materials(p)))
    warnings = [issue_dict(i) for i in warns]
    if errors:
        raise CliError("validation_failed", "pre-flight check failed", 4,
                       {"issues": [issue_dict(i) for i in errors]})
    if strict and warns:
        raise CliError("preflight_warnings", "pre-flight warnings with --strict", 4, {"issues": warnings})

    before = {tuple(v.path): get_param(p, v.path) for v in s.variables}
    before_choice = {c.uid: p.structure.layer_by_uid(c.uid).material for c in s.choices}
    runs, res, n_evals = [], None, 0
    for k in range(max(1, int(restarts))):
        if k and control.should_stop():
            break
        work = p.copy()
        work.optimization.seed = s.seed + k
        try:
            r = optimize(work, work.optimization, progress=control.optimize_callback({"restart": k + 1}),
                         throttle_s=0.0)
        except MODEL_ERRORS as e:
            raise model_error(e) from None
        n_evals += r.n_evals
        runs.append((work.optimization.seed, r))
        if r.terms is not None and (res is None or res.terms is None or r.terms.objective < res.terms.objective):
            res = r
        elif res is None:
            res = r
        if r.stopped:
            break
    if res.terms is None:
        raise CliError("no_valid_design", res.message, 4,
                       {"first_failure": first_failure(p, s), "n_evals": res.n_evals})
    apply_result(p, res)
    rows, max_margin = target_rows(p, s)
    values = []
    for v in s.variables:
        unit = param_unit(p, v.path)
        after = res.values[tuple(v.path)]
        values.append({"path": list(v.path), "label": describe_path(p, v.path),
                       "layer": layer_label(p, v.path[1]) if v.path[0] == "layer" else None,
                       "before": param_value(before[tuple(v.path)], unit, p, v.path),
                       "after": param_value(after, unit, p, v.path),
                       "at_bound": _at_bound(v, after)})
    choices = [{"uid": c.uid, "layer": layer_label(p, c.uid), "before": before_choice[c.uid],
                "after": res.choices.get(c.uid, before_choice[c.uid])} for c in s.choices]
    run_settings = {k: getattr(s, k) for k in saved_settings}
    if output is not None:
        for k, v in saved_settings.items():
            setattr(s, k, v)
        save_project(p, output)
        for k, v in run_settings.items():
            setattr(s, k, v)
    message = "stopped by timeout" if control.timed_out else res.message
    restart_rows = []
    for seed_k, r in runs:
        rr = {"seed": seed_k, "objective": None if r.terms is None else r.terms.objective,
              "max_margin_db": None if r.terms is None else r.terms.margin_db, "stopped": r.stopped}
        restart_rows.append(rr)
    best_seed = next(sd for sd, r in runs if r is res)
    result = {"message": message, "n_evals": n_evals, "best_seed": best_seed, "restarts": restart_rows,
              "run_settings": {"maxiter": s.maxiter, "popsize": s.popsize, "polish": s.polish},
              "elapsed_s": sum(r.elapsed for _, r in runs), "seed_used": s.seed,
              "targets": rows, "max_margin_db": max_margin, "terms": _terms_dict(res.terms, s.thickness_max),
              "values": values, "choices": choices, "history": [list(h) for h in res.history],
              "output_path": None if output is None else str(output)}
    if control.timed_out:
        warnings.append(warning("timeout", "stopped by --timeout"))
    stopped = res.stopped or any(r.stopped for _, r in runs) or (len(runs) < max(1, int(restarts)))
    return CommandResult(result, warnings=warnings, stopped=stopped, input_info=inp)


# ---------------------------------------------------------------------------
# tolerance

def _stats(a):
    a = np.asarray(a, dtype=float)
    return {"min": float(np.min(a)), "median": float(np.median(a)), "max": float(np.max(a))}


def cmd_tolerance(path, control, seed=None, n_samples=None, target_db=None, angle_deg=None, pol=None,
                  samples=False, summary_only=False, fmt="json", output=None, force=False, corners=False):
    if corners:
        return _tolerance_corners(path, control, seed, n_samples, target_db, samples)
    p, inp = load_project(path)
    s = p.tolerance
    s.seed = resolve_seed(seed if seed is not None else s.seed)
    if n_samples is not None:
        s.n_samples = int(n_samples)
    if target_db is not None:
        s.target_db = float(target_db)
    if angle_deg is not None:
        s.angle = float(angle_deg)
    if pol is not None:
        s.pol = pol
    f = tolerance_frequencies(p)
    band = yield_intervals(p)
    try:
        r = run_tolerance(p, f, band=band, progress=control.tolerance_callback())
    except MODEL_ERRORS as e:
        raise model_error(e) from None
    if fmt == "csv":
        header = ["f [GHz]", "nominal [dB]", "median [dB]", "lower [dB]", "upper [dB]"]
        rows = [[f"{a / 1e9:.9g}", f"{b:.6g}", f"{c:.6g}", f"{d:.6g}", f"{e:.6g}"]
                for a, b, c, d, e in zip(r.f, r.nominal_db, r.median_db, r.lower_db, r.upper_db)]
        text = csv_text(header, rows)
        if output is None:
            return CommandResult({}, input_info=inp, text=text, stopped=r.stopped)
        check_output_path(output, force)
        write_text(output, text)
        return CommandResult({"output_path": str(output), "rows": len(rows)}, input_info=inp, stopped=r.stopped)
    result = {"scope": {"angle_deg": s.angle, "pol": s.pol}, "n_samples": r.n_samples, "seed_used": s.seed,
              "yield_fraction": r.yield_fraction, "target_db": s.target_db, "lower_pct": s.lower_pct,
              "upper_pct": s.upper_pct, "yield_intervals_hz": [list(iv) for iv in band],
              "worst_db": _stats(r.worst_db)}
    if not summary_only:
        result["data"] = {"f_hz": r.f, "nominal_db": r.nominal_db, "median_db": r.median_db,
                          "lower_db": r.lower_db, "upper_db": r.upper_db}
    if samples:
        result["samples_worst_db"] = r.worst_db
    warnings = [warning("single_angle_yield",
                        f"yield evaluated at a single angle ({s.angle:g} deg, {s.pol}) only; "
                        "targets over an angle range need a check at every angle and polarisation")]
    if control.timed_out:
        warnings.append(warning("timeout", "stopped by --timeout"))
    return CommandResult(result, warnings=warnings, stopped=r.stopped, input_info=inp)


def _tolerance_corners(path, control, seed, n_samples, target_db, samples):
    """Yield at every (angle end x polarisation) corner of every enabled target, plus the joint yield.

    The perturbation samples depend only on the seed and the layers (they are drawn before the solve loop in
    ``run_tolerance``), so with one seed every corner sees the same samples and the joint yield is exact."""
    p, inp = load_project(path)
    s = p.tolerance
    s.seed = resolve_seed(seed if seed is not None else s.seed)
    if n_samples is not None:
        s.n_samples = int(n_samples)
    targets = p.optimization.enabled_targets()
    if not targets:
        raise CliError("invalid_optimization_settings", "--corners needs at least one enabled target", 4)
    f = tolerance_frequencies(p)
    plan = []
    for ti, t in enumerate(targets):
        for ang in sorted({t.angle_min, t.angle_max}):
            for pol_ in t.pols:
                plan.append((ti, t, ang, pol_))
    rows, passes, stopped = [], [], False
    for k, (ti, t, ang, pol_) in enumerate(plan):
        if k and control.should_stop():
            stopped = True
            break
        s.angle, s.pol = float(ang), pol_
        s.target_db = float(target_db) if target_db is not None else t.goal_db
        try:
            r = run_tolerance(p, f, band=[(t.f_min, t.f_max)],
                              progress=control.tolerance_callback({"corner": k + 1, "n_corners": len(plan)}))
        except MODEL_ERRORS as e:
            raise model_error(e) from None
        stopped = stopped or r.stopped
        row = {"target": ti, "target_name": t.name, "angle_deg": ang, "pol": pol_, "target_db": s.target_db,
               "n_samples": r.n_samples, "yield_fraction": r.yield_fraction, "worst_db": _stats(r.worst_db)}
        if samples:
            row["samples_worst_db"] = r.worst_db
        rows.append(row)
        passes.append(np.asarray(r.worst_db) <= s.target_db)
        if r.stopped:
            break
    n = min(len(x) for x in passes)
    joint = float(np.mean(np.all([x[:n] for x in passes], axis=0))) if n else None
    worst = min(rows, key=lambda r_: r_["yield_fraction"])
    result = {"n_samples": n, "seed_used": s.seed, "corners": rows, "joint_yield_fraction": joint,
              "min_corner": {k_: worst[k_] for k_ in ("target", "angle_deg", "pol")},
              "note": "corners only; angles inside each target's range are not sampled"}
    warnings = [warning("timeout", "stopped by --timeout")] if control.timed_out else []
    return CommandResult(result, warnings=warnings, stopped=stopped or len(rows) < len(plan), input_info=inp)


# ---------------------------------------------------------------------------
# materials, bound, fit

def cmd_materials(name=None, library=None):
    mats = builtin_materials()
    if library:
        from coating_studio.materials.library import load_library
        try:
            mats += load_library(library)
        except FileNotFoundError:
            raise CliError("file_not_found", f"{library}: no such file", 3, {"path": str(library)}) from None
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise CliError("invalid_value", f"{library}: {e}", 3, {"path": str(library)}) from None
    p = Project(materials=mats)
    out = []
    for m in mats:
        if name is not None and m.name != name:
            continue
        try:
            mu, _ext = static_permeability(m, p.resolver)
        except (KeyError, MaterialCycleError):
            mu = None
        out.append({"name": m.name, "kind": m.kind, "note": m.note, "is_demo": is_builtin_demo(m),
                    "dict": m.to_dict(),
                    "params": [{"path": list(pi.key), "label": pi.label, "unit": pi.unit} for pi in m.params()],
                    "static_mu": mu})
    if name is not None and not out:
        raise CliError("unknown_reference", f"no material {name!r}", 4, {"ref": name})
    return CommandResult({"materials": out})


def cmd_bound(f_lo_ghz, f_hi_ghz, goal_db, mu_s=1.0):
    if not (0 < f_lo_ghz < f_hi_ghz):
        raise CliError("usage", "--f-ghz needs 0 < LO < HI", 2)
    req = rozanov_required_mu_d(f_lo_ghz * 1e9, f_hi_ghz * 1e9, goal_db)
    return CommandResult({"f_hz": [f_lo_ghz * 1e9, f_hi_ghz * 1e9], "goal_db": goal_db, "required_mu_d_m": req,
                          "mu_s": mu_s, "min_thickness_m": req / mu_s,
                          "assumptions": ["normal incidence", "PEC backing", "air incident"]})


def cmd_fit(csv_path, name=None, eps_debye=1, eps_lorentz=0, sigma=False, eps_const_loss=False, mu_debye=0,
            mu_lorentz=0, mu_const_loss=False, density=1000.0):
    from coating_studio.materials.csvio import CsvFormatError, load_csv
    from coating_studio.materials.fitting import FitSpec, fit_dispersive
    try:
        tab = load_csv(csv_path, name=name or os.path.splitext(os.path.basename(csv_path))[0], density=density)
    except FileNotFoundError:
        raise CliError("file_not_found", f"{csv_path}: no such file", 3, {"path": str(csv_path)}) from None
    except (CsvFormatError, ValueError, OSError) as e:
        raise CliError("invalid_value", f"{csv_path}: {e}", 3, {"path": str(csv_path), "csv_error": str(e)}) from None
    f = tab.f
    eps, mu = tab.eps_mu(f, lambda n: None)
    mu_spec = FitSpec(n_debye=mu_debye, n_lorentz=mu_lorentz, fit_const_loss=mu_const_loss) \
        if (mu_debye or mu_lorentz or mu_const_loss) else None
    try:
        fr = fit_dispersive(tab.name, f, eps, mu,
                            FitSpec(n_debye=eps_debye, n_lorentz=eps_lorentz, fit_sigma=sigma,
                                    fit_const_loss=eps_const_loss), mu_spec, density=density)
    except (ValueError, RuntimeError) as e:
        raise CliError("invalid_value", f"fit failed: {e}", 4) from None
    pruned = 0
    for side, inf in (("eps_terms", fr.material.eps_inf), ("mu_terms", fr.material.mu_inf)):
        terms = getattr(fr.material, side)
        kept = [tm for tm in terms if abs(tm["delta"]) >= 1e-6 * max(1.0, abs(inf))]  # negligible fitted terms
        pruned += len(terms) - len(kept)
        setattr(fr.material, side, kept)
    fr.material.note = f"{FITTED_PREFIX} {os.path.basename(csv_path)}, {f[0] / 1e9:g}-{f[-1] / 1e9:g} GHz"
    warnings = []
    if pruned:
        warnings.append(warning("fit_terms_dropped", f"{pruned} fitted term(s) with negligible strength were dropped"))
    if mu_spec is None and np.any(np.abs(mu - 1) > 1e-6):
        warnings.append(warning("mu_not_fitted", "the data has mu != 1 but no mu terms were fitted (use --mu-debye)"))
    for side, rms in (("eps", fr.rms_eps), ("mu", fr.rms_mu)):
        if rms > 0.05:
            warnings.append(warning("fit_poor", f"{side} residual {rms:.3g} (relative); try more terms"))
    return CommandResult({"material": fr.material.to_dict(), "rms_eps": fr.rms_eps, "rms_mu": fr.rms_mu,
                          "data_range_hz": [f[0], f[-1]]}, warnings=warnings)


# ---------------------------------------------------------------------------
# build, spec, journal

def cmd_build(spec_path, output, force=False):
    import json as _json
    from coating_studio.cli.spec import SPEC_VERSION, spec_to_project
    try:
        with open(spec_path, encoding="utf-8") as fh:
            spec = _json.load(fh)
    except FileNotFoundError:
        raise CliError("file_not_found", f"{spec_path}: no such file", 3, {"path": str(spec_path)}) from None
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise CliError("invalid_spec", f"{spec_path}: not a JSON spec ({e})", 3, {"path": "$"}) from None
    check_output_path(output, force)
    p, warnings = spec_to_project(spec, base_dir=os.path.dirname(os.path.abspath(spec_path)))
    save_project(p, output)
    return CommandResult({"output_path": str(output), "n_layers": len(p.structure.layers),
                          "n_variables": len(p.optimization.variables), "n_targets": len(p.optimization.targets)},
                         warnings=warnings, input_info={"path": str(spec_path), "spec_version": SPEC_VERSION})


def cmd_spec(path, output=None, force=False):
    import json as _json
    from coating_studio.cli.spec import project_to_spec
    p, inp = load_project(path)
    sp = project_to_spec(p)
    if output is None:
        return CommandResult({"spec": sp}, input_info=inp)
    check_output_path(output, force)
    from coating_studio.cli.output import sanitize
    write_text(output, _json.dumps(sanitize(sp), indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    return CommandResult({"output_path": str(output)}, input_info=inp)


def cmd_journal(directory):
    from coating_studio.cli.journal import report
    result, warnings = report(directory)
    return CommandResult(result, warnings=warnings, input_info={"path": str(directory)})
