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
from coating_studio.core.structure import SheetLayer, SlabLayer
from coating_studio.core.units import power_to_db, si_unit, to_display
from coating_studio.examples import EXAMPLES
from coating_studio.limits import (
    FITTED_PREFIX, limit_issues, measured_range, mixture_range_issues, sheet_proximity_issues, rozanov_required_mu_d, static_permeability,
    target_limits,
)
from coating_studio.materials.checks import Issue, check_material, is_builtin_demo
from coating_studio.materials.library import builtin_materials
from coating_studio.materials.models import INVERTED_PREFIX, ConstantMaterial, MaterialCycleError, MixtureMaterial
from coating_studio.optimize.optimizer import (
    MAX_ENUMERATED_COMBOS, OptimizationError, apply_result, evaluate_terms, optimize, preflight,
)
from coating_studio.project import Project, available_params, describe_path, get_param, param_unit
from coating_studio.tolerance import run_tolerance, run_tolerance_targets, tolerance_frequencies, yield_intervals

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
    return {"f_hz": [sw.f_min, sw.f_max], "n_f": sw.n_f, "log_f": sw.log_f,
            "uniform_wavelength": sw.wavelength_spaced(), "angle_deg": sw.angle,
            "angle_range_deg": [sw.angle_min, sw.angle_max], "n_angle": sw.n_angle, "f_at_hz": sw.f_at,
            "map_n_f": sw.map_n_f, "map_n_angle": sw.map_n_angle}


def used_materials(project, include_candidates=True):
    """Materials the design uses, with mixture constituents expanded (sorted)."""
    return project.used_materials(include_candidates)


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
        d.update(model=ly.model, R_ohm=ly.R, X_ohm=ly.X, C_f=ly.C,
                 L_h=None if ly.model == "parallel_rlc" and ly.L <= 0 else ly.L, angle=ly.angle_dict())
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
            if any(isinstance(ly, SheetLayer) and ly.has_angle for ly in p.structure.layers):
                # the sweep angle is often 0, where no angle coefficient can show a problem
                solve(p.structure, p.materials, [p.sweep.f_at], p.sweep.angle_grid())
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
    for iss in sheet_proximity_issues(p, p.sweep.f_max):
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
    grid = o.get("log_f")  # "log" / "linear" / "wavelength" (one of --log-f, --linear-f, --linear-wavelength)
    if grid is not None:
        sw.log_f, sw.uniform_wavelength = grid == "log", grid == "wavelength"


def _best(db, f, th, sweep):
    i = int(np.nanargmin(db))
    if sweep == "freq":
        return {"rl_db": db.flat[i], "f_hz": f[i]}
    if sweep == "angle":
        return {"rl_db": db.flat[i], "theta_deg": th[i]}
    fi, ti = np.unravel_index(i, db.shape)
    return {"rl_db": db[fi, ti], "f_hz": f[fi], "theta_deg": th[ti]}


def cmd_solve(path, sweep="freq", quantity_name="RL", pol="avg", targets=False, summary_only=False,
              layer_absorption=False, fmt="json", output=None, force=False, overrides=None, touchstone=None):
    p, inp = load_project(path)
    sw = p.sweep
    _apply_sweep_overrides(sw, overrides or {})
    ts_pol = None
    if touchstone is not None:
        if sweep != "freq":
            raise CliError("usage", "--touchstone needs the frequency sweep (--sweep freq)", 2)
        ts_pol = pol if pol != "avg" else ("TE" if abs(sw.angle) < 1e-12 else None)
        if ts_pol is None:
            raise CliError("usage", "--touchstone at oblique incidence needs --pol TE or TM (a file holds one "
                                    "polarisation)", 2)
        check_output_path(touchstone, force, input_path=path)
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

    ts_info = None
    if ts_pol is not None:
        from coating_studio.touchstone import design_s11, format_s1p
        tf, s11, ref, notes = design_s11(p, ts_pol, f=res.f, theta_deg=sw.angle)
        write_text(touchstone, format_s1p(tf, s11, ref, notes))
        ts_info = {"touchstone_path": str(touchstone), "touchstone_pol": ts_pol, "touchstone_ref_ohm": ref}

    if fmt == "csv":
        text = _solve_csv(res, sweep, quantity_name, pol)
        if output is None:
            return CommandResult({}, input_info=inp, text=text)
        check_output_path(output, force)
        write_text(output, text)
        return CommandResult({"output_path": str(output), "rows": text.count("\n") - 1, **(ts_info or {})},
                             input_info=inp)

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
    result.update(ts_info or {})
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
    d = {"objective": t.objective, "worst_db": t.worst_db, "margin_db": t.margin_db, "mean_r": t.mean_r,
         "thickness_m": t.thickness, "mass_kg_m2": t.mass, "thickness_max_m": thickness_max,
         "thickness_at_limit": at_limit}
    if math.isfinite(t.sample_yield):  # robust mode
        d.update(robust_margin_db=t.robust_margin_db, sample_yield=t.sample_yield)
    return d


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
                  samples=False, summary_only=False, fmt="json", output=None, force=False, corners=False,
                  angle_grid=False, n_angle=None):
    if n_angle is not None and not angle_grid:
        raise CliError("usage", "--n-angle needs --angle-grid", 2)
    if corners or angle_grid:
        for flag, given in (("--angle-deg", angle_deg is not None), ("--pol", pol is not None)):
            if given:  # each row uses its target's own angles and polarisations
                raise CliError("usage", f"{flag} cannot be combined with --corners / --angle-grid", 2)
        if n_angle is not None and n_angle < 2:
            raise CliError("usage", "--n-angle needs N >= 2", 2)
        return _tolerance_targets(path, control, "grid" if angle_grid else "corners", n_angle, seed, n_samples,
                                  target_db, samples, fmt, output, force)
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
              "worst_db": _stats(r.worst_db), "material_params_clipped": r.clipped}
    if not summary_only:
        result["data"] = {"f_hz": r.f, "nominal_db": r.nominal_db, "median_db": r.median_db,
                          "lower_db": r.lower_db, "upper_db": r.upper_db}
    if samples:
        result["samples_worst_db"] = r.worst_db
    result = _write_json_output(result, output, force, ("data", "samples_worst_db"))
    warnings = [warning("single_angle_yield",
                        f"yield evaluated at a single angle ({s.angle:g} deg, {s.pol}) only; "
                        "targets over an angle range need a check at every angle and polarisation")]
    warnings += _clipped_warnings(r.clipped, r.n_samples)
    if control.timed_out:
        warnings.append(warning("timeout", "stopped by --timeout"))
    return CommandResult(result, warnings=warnings, stopped=r.stopped, input_info=inp)


def _clipped_warnings(clipped, n):
    """``tolerance_clipped`` warnings for material parameters whose draws hit their physical bounds."""
    return [warning("tolerance_clipped",
                    f"{c['n']} of {n} samples of {'/'.join(str(x) for x in c['path'][1:])} were clipped to the "
                    "parameter's physical bounds: the tolerance is wide for it, and the samples do not follow the "
                    "requested distribution", path=c["path"], n_clipped=c["n"]) for c in clipped if c["n"]]


def _write_json_output(result, output, force, bulky=()):
    """With ``--output``: write ``result`` to that file and return a short result for the envelope (``output_path``
    plus everything except the ``bulky`` keys); without it, return ``result`` unchanged."""
    if output is None:
        return result
    check_output_path(output, force)
    from coating_studio.cli.output import dumps
    write_text(output, dumps(result) + "\n")
    return {"output_path": str(output), **{k: v for k, v in result.items() if k not in bulky}}


_ANGLE_NOTES = {"corners": "corners only; angles inside each target's range are not sampled",
                "grid": "angle grid only; angles between the grid points are not sampled"}


def _tolerance_targets(path, control, mode, n_angle, seed, n_samples, target_db, samples, fmt, output, force):
    """Yield at every (angle x polarisation) row of every enabled target - the ends of its angle range ("corners")
    or its angle grid ("grid") - plus the joint yield (``tolerance.run_tolerance_targets``, shared with the GUI).
    ``--format csv`` exports the curves of the weakest row, as the GUI's data export does."""
    p, inp = load_project(path)
    s = p.tolerance
    s.seed = resolve_seed(seed if seed is not None else s.seed)
    if n_samples is not None:
        s.n_samples = int(n_samples)
    if not p.optimization.enabled_targets():
        raise CliError("invalid_optimization_settings",
                       f"--{'angle-grid' if mode == 'grid' else 'corners'} needs at least one enabled target", 4)
    try:
        cr = run_tolerance_targets(p, tolerance_frequencies(p), mode, n_angle=n_angle, target_db=target_db,
                                   progress=control.tolerance_callback(), should_stop=control.should_stop)
    except MODEL_ERRORS as e:
        raise model_error(e) from None
    if fmt == "csv":
        r = cr.corners[cr.worst][5]
        header = ["f [GHz]", "nominal [dB]", "median [dB]", "lower [dB]", "upper [dB]"]
        rows = [[f"{a / 1e9:.9g}", f"{b:.6g}", f"{c:.6g}", f"{d:.6g}", f"{e:.6g}"]
                for a, b, c, d, e in zip(r.f, r.nominal_db, r.median_db, r.lower_db, r.upper_db)]
        text = csv_text(header, rows)
        if output is None:
            return CommandResult({}, input_info=inp, text=text, stopped=cr.stopped)
        check_output_path(output, force)
        write_text(output, text)
        return CommandResult({"output_path": str(output), "rows": len(rows)}, input_info=inp, stopped=cr.stopped)
    rows = []
    for ti, name, ang, pol_, tdb, r in cr.corners:
        row = {"target": ti, "target_name": name, "angle_deg": ang, "pol": pol_, "target_db": tdb,
               "n_samples": r.n_samples, "yield_fraction": r.yield_fraction, "worst_db": _stats(r.worst_db)}
        if samples:
            row["samples_worst_db"] = r.worst_db
        rows.append(row)
    worst = rows[cr.worst]
    result = {"angle_mode": mode, "n_samples": cr.n_samples, "seed_used": s.seed, "target_db": target_db,
              "corners": rows, "joint_yield_fraction": cr.joint_yield_fraction,
              "min_corner": {k_: worst[k_] for k_ in ("target", "angle_deg", "pol")},
              "note": _ANGLE_NOTES[mode], "material_params_clipped": cr.clipped}
    if n_angle is not None:
        result["n_angle"] = n_angle
    result = _write_json_output(result, output, force, ("corners",))
    warnings = [warning("angle_grid_fallback",
                        f"target {ti + 1}: its angle range has fewer than 2 grid points (n_angle); "
                        "its two ends were evaluated instead") for ti in cr.fallback_targets]
    warnings += _clipped_warnings(cr.clipped, cr.n_samples)
    if control.timed_out:
        warnings.append(warning("timeout", "stopped by --timeout"))
    return CommandResult(result, warnings=warnings, stopped=cr.stopped, input_info=inp)


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


def cmd_fss_grid(pattern, period_mm, strip_width_mm, gap_mm, eps_eff):
    """L or C of a dense mesh or patch array from its dimensions (docs/CLI_PLAN.md, section 13.10)."""
    from coating_studio.fss import grid_element
    width_mm = strip_width_mm if pattern == "mesh" else gap_mm
    if width_mm is None:
        raise CliError("usage", "a mesh takes --strip-width-mm and a patch array takes --gap-mm", 2)
    try:
        el = grid_element(pattern, period_mm * 1e-3, width_mm * 1e-3, eps_eff)
    except ValueError as e:
        raise CliError("usage", str(e), 2) from None
    sheet = {"L_nh": to_display(el.L, "nH") if el.L else 0.0, "C_pf": to_display(el.C, "pF") if el.C else None,
             "angle": el.angle}
    warnings = []
    if el.wide:
        warnings.append(warning("wide_geometry", f"width/period = {el.width_ratio:.3g}; the formula assumes much less"))
    return CommandResult({"pattern": pattern, "period_m": el.period, "width_m": el.width, "eps_eff": el.eps_eff,
                          "width_ratio": el.width_ratio, "L_h": el.L, "C_f": el.C, "angle": el.angle,
                          "caution_limit_hz": el.caution_hz, "dense_limit_hz": el.limit_hz, "sheet": sheet,
                          "assumptions": ["dense square lattice", "ideal conductors", "incidence in a principal plane",
                                          "width or gap much smaller than the period",
                                          "eps_eff = (eps_r + 1)/2 needs a dielectric thick compared with the period"]},
                         warnings=warnings)


def _read_measured(csv_path, name=None, density=1000.0):
    """Load a measured CSV; a missing or malformed file is an input error (exit 3)."""
    from coating_studio.materials.csvio import CsvFormatError, load_csv
    try:
        return load_csv(csv_path, name=name or os.path.splitext(os.path.basename(csv_path))[0], density=density)
    except FileNotFoundError:
        raise CliError("file_not_found", f"{csv_path}: no such file", 3, {"path": str(csv_path)}) from None
    except (CsvFormatError, ValueError, OSError) as e:
        raise CliError("invalid_value", f"{csv_path}: {e}", 3, {"path": str(csv_path), "csv_error": str(e)}) from None


def cmd_fit(csv_path, name=None, eps_debye=1, eps_lorentz=0, sigma=False, eps_const_loss=False, mu_debye=0,
            mu_lorentz=0, mu_const_loss=False, density=1000.0, eps_hn=0, mu_hn=0):
    from coating_studio.materials.fitting import FitSpec, fit_dispersive
    tab = _read_measured(csv_path, name, density)
    f = tab.f
    eps, mu = tab.eps_mu(f, lambda n: None)
    mu_spec = FitSpec(n_debye=mu_debye, n_lorentz=mu_lorentz, fit_const_loss=mu_const_loss, n_hn=mu_hn) \
        if (mu_debye or mu_lorentz or mu_hn or mu_const_loss) else None
    try:
        fr = fit_dispersive(tab.name, f, eps, mu,
                            FitSpec(n_debye=eps_debye, n_lorentz=eps_lorentz, n_hn=eps_hn, fit_sigma=sigma,
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
    if isinstance(tab.note, str) and tab.note.startswith(INVERTED_PREFIX):
        fr.material.note = f"{fr.material.note}; {tab.note}"
        warnings.append(warning("fit_of_inverted", "this table holds effective filler values tied to a mixing rule; "
                                "a static permeability extrapolated from it is not a measured property"))
    if pruned:
        warnings.append(warning("fit_terms_dropped", f"{pruned} fitted term(s) with negligible strength were dropped"))
    if mu_spec is None and np.any(np.abs(mu - 1) > 1e-6):
        warnings.append(warning("mu_not_fitted", "the data has mu != 1 but no mu terms were fitted (use --mu-debye)"))
    for side, rms in (("eps", fr.rms_eps), ("mu", fr.rms_mu)):
        if rms > 0.05:
            warnings.append(warning("fit_poor", f"{side} residual {rms:.3g} (relative); try more terms"))
    return CommandResult({"material": fr.material.to_dict(), "rms_eps": fr.rms_eps, "rms_mu": fr.rms_mu,
                          "data_range_hz": [f[0], f[-1]]}, warnings=warnings)


def _inversion_warning(code, a):
    limit = a.get("limit", 0.0)
    return warning(code, {
        "filler_ill_conditioned": lambda: f"at {a['n']} point(s) measurement errors grow more than {limit:g}-fold in "
                                          "the filler values; trust predictions, not the values",
        "filler_negative_real": lambda: f"{a['n']} point(s) have Re <= 0",
        "nonpassive_clamped": lambda: f"loss set to 0 at {a['n']} point(s); the composite there is reproduced only to "
                                      f"{a['worst']:.3g}",
        "fraction_sensitive": lambda: f"a 10 % loading error moves predictions by more than {limit:.0%}",
        "model_disagreement": lambda: f"the other mixing rule predicts differently by more than {limit:.0%}",
        "no_validation": lambda: "no composite at another loading was given (--validate); predictions at other "
                                 "loadings are untested",
        "validation_poor": lambda: f"{a.get('label')}: prediction error above {limit:.0%}",
    }[code]())


def cmd_invert_filler(composite, output, model, density_filler, fraction=None, fraction_wt=None, density_matrix=None,
                      matrix_csv=None, matrix_eps=None, matrix_mu=None, name=None, clamp_nonpassive=False, validate=(),
                      force=False, shape_n=None, percolation=None, exponent=None):
    """Effective filler table from one measured composite (docs/CLI_PLAN.md, section 13.9)."""
    from coating_studio.cli.spec import wt_to_vol
    from coating_studio.materials.csvio import to_csv_text
    from coating_studio.materials.models import Shape, make_gem, make_shape
    from coating_studio.materials.inversion import (
        diagnostics, invert_filler, prediction_checks, provenance_note, validation_errors, warning_flags,
    )

    def bad(message, **details):
        return CliError("invalid_value", message, 3, details)

    def volume(value, what):
        try:
            v = float(value)
        except ValueError:
            raise bad(f"{what}: {value!r} is not a number") from None
        if not 0.0 < v < 1.0:
            raise bad(f"{what}: must be between 0 and 1, got {v:g}")
        return v if fraction_wt is None else wt_to_vol(v, density_filler, density_matrix)

    if density_filler <= 0:
        raise bad("--density-filler must be positive")
    if fraction_wt is not None and (density_matrix is None or density_matrix <= 0):
        raise bad("--fraction-wt needs a positive --density-matrix")
    if matrix_mu is not None and matrix_eps is None:
        raise bad("--matrix-mu goes with --matrix-eps; a matrix CSV carries its own mu")
    inputs = [composite] + ([matrix_csv] if matrix_csv else []) + [v[0] for v in validate]
    if any(os.path.abspath(output) == os.path.abspath(i) for i in inputs):
        raise bad(f"{output} is one of the input files; --force does not overwrite measurements", path=str(output))
    check_output_path(output, force)
    try:
        if model == "gem":
            if shape_n is not None:
                raise ValueError("the gem rule takes no shape factor")
            shape = make_gem(percolation, exponent)
        else:
            if exponent is not None:
                raise ValueError(f"the {model} rule takes no exponent")
            shape = make_shape(model, shape_n, percolation)
    except ValueError as e:
        raise bad(str(e)) from None
    phi = volume(fraction if fraction_wt is None else fraction_wt, "fraction")
    if isinstance(shape, Shape) and phi >= shape.pc:  # GEM is defined through its threshold
        raise bad(f"the volume fraction {phi:g} is at or above the percolation threshold {shape.pc:g}")
    checks = [(path, volume(value, f"--validate {path}")) for path, value in validate]

    comp = _read_measured(composite)
    if matrix_csv:
        matrix = _read_measured(matrix_csv, "matrix")
        label = os.path.basename(matrix_csv)
    else:
        matrix = ConstantMaterial("matrix", matrix_eps[0], matrix_eps[1], *(matrix_mu or (1.0, 0.0)))
        label = f"eps {matrix_eps[0]:g}-{matrix_eps[1]:g}j"
        if matrix_mu:
            label += f" mu {matrix_mu[0]:g}-{matrix_mu[1]:g}j"
    f = comp.f
    eps, mu = comp.eps_mu(f, None)
    try:
        eps_m, mu_m = matrix.eps_mu(f, None)
    except MODEL_ERRORS as e:
        raise model_error(e) from None
    res = invert_filler(f, eps, mu, eps_m, mu_m, phi, model, clamp_nonpassive, shape)
    diag = diagnostics(res)
    if not res.ok:
        raise CliError("inversion_nonphysical",
                       f"{res.gain_points} point(s) with gain, {res.outside_model_points} beyond what the {model} rule "
                       f"can represent, {res.branch_points} on another root: no usable filler table exists for this "
                       "data and rule. Do not invent values; try the other rule, or measure more loadings.",
                       4, {**diag, "clampable_points": res.clampable_points})

    note = provenance_note(os.path.basename(composite), model, phi, label, shape)
    display_name = name or os.path.splitext(os.path.basename(output))[0]
    filler = res.to_tabulated(display_name, density_filler, note=note, source=os.path.basename(output))
    prediction = prediction_checks(res, eps, mu, eps_m, mu_m)
    validation = []
    for path, phi_v in checks:
        tab = _read_measured(path)
        e_v, m_v = tab.eps_mu(tab.f, None)
        try:
            errors = validation_errors(filler, matrix, tab.f, e_v, m_v, phi_v, model, shape)
        except MODEL_ERRORS as e:
            raise model_error(e) from None
        validation.append({"csv": str(path), "fraction": phi_v, **errors})

    warnings = [_inversion_warning(code, args) for code, args in warning_flags(res, prediction, validation)]

    write_text(output, f"# {note}\n" + to_csv_text(f, res.eps.value, res.mu.value))
    material = {"name": display_name, "csv": os.path.abspath(output), "density": float(density_filler), "note": note}
    return CommandResult({"output_path": str(output), "material": material, **diag, "prediction": prediction,
                          "validation": validation}, warnings=warnings)


def _shape_warning(code, a):
    return warning(code, {
        "shape_at_bound": lambda: f"N/pc = {a['b']:.4g} lies at the edge of the searched range; the data may need a "
                                  "ratio outside it, or another rule",
        "shape_fit_poor": lambda: f"the best ratio reproduces the composites only to {a['rms']:.1%} rms (above "
                                  f"{a['limit']:.0%}); the rule may not describe this composite family",
        "shape_flat": lambda: f"the fit hardly changes over N/pc = {a['lo']:.4g}-{a['hi']:.4g}; the ratio is poorly "
                              "determined by these loadings",
        "shape_two_fractions": lambda: "two loadings fit one ratio with nothing left to test it; a third loading "
                                       "would show whether the rule holds",
        "shape_no_admissible_n": lambda: f"{a['label']}: no shape factor gives an accepted filler table at this "
                                         "ratio; invert-filler would fail on it",
    }[code]())


def _loadings_input(composites, matrix_csv, matrix_eps, matrix_mu, weight_fractions, density_filler, density_matrix,
                    what):
    """The shared input of fit-shape and fit-gem: (f, eps_m, mu_m, eps (loading x f), mu, fractions)."""
    from coating_studio.cli.spec import wt_to_vol

    def bad(message, **details):
        return CliError("invalid_value", message, 3, details)

    if len(composites) < 2:
        raise bad(f"{what} needs at least two --composite CSV FRACTION")
    if weight_fractions:
        if density_filler is None or density_filler <= 0 or density_matrix is None or density_matrix <= 0:
            raise bad("--weight-fractions needs a positive --density-filler and --density-matrix")
    elif density_filler is not None or density_matrix is not None:
        raise bad("--density-filler and --density-matrix go with --weight-fractions")
    if matrix_mu is not None and matrix_eps is None:
        raise bad("--matrix-mu goes with --matrix-eps; a matrix CSV carries its own mu")
    paths = [os.path.abspath(c[0]) for c in composites]
    if len(set(paths)) < len(paths):
        raise bad("the same CSV was given twice")
    fractions = []
    for path, value in composites:
        try:
            v = float(value)
        except ValueError:
            raise bad(f"--composite {path}: {value!r} is not a number") from None
        if not 0.0 < v < 1.0:
            raise bad(f"--composite {path}: the fraction must be between 0 and 1, got {v:g}")
        fractions.append(wt_to_vol(v, density_filler, density_matrix) if weight_fractions else v)
    if min(abs(a - b) for i, a in enumerate(fractions) for b in fractions[i + 1:]) <= 1e-9:
        raise bad("the loadings must differ", fractions=fractions)

    tabs = [_read_measured(path) for path, _ in composites]
    if matrix_csv:
        matrix = _read_measured(matrix_csv, "matrix")
        ranges = [t.f_range for t in tabs] + [matrix.f_range]
    else:
        matrix = ConstantMaterial("matrix", matrix_eps[0], matrix_eps[1], *(matrix_mu or (1.0, 0.0)))
        ranges = [t.f_range for t in tabs]
    lo, hi = max(r[0] for r in ranges), min(r[1] for r in ranges)
    f = tabs[0].f[(tabs[0].f >= lo * (1 - 1e-9)) & (tabs[0].f <= hi * (1 + 1e-9))]
    if f.size < 2:
        raise bad("fewer than two frequencies of the first composite lie where every input has data",
                  common_range_hz=[float(lo), float(hi)] if hi > lo else None)
    f = np.clip(f, lo, hi)  # the 1e-9 tolerance must not step outside a tabulated range
    try:
        eps_m, mu_m = matrix.eps_mu(f, None)
        data = [t.eps_mu(f, None) for t in tabs]
    except MODEL_ERRORS as e:
        raise model_error(e) from None
    eps = np.array([d[0] for d in data])
    mu = np.array([d[1] for d in data])
    return f, eps_m, mu_m, eps, mu, fractions


def cmd_fit_shape(composites, matrix_csv=None, matrix_eps=None, matrix_mu=None, weight_fractions=False,
                  density_filler=None, density_matrix=None):
    """The Odelevskiy ratio N/pc from composites at several loadings (docs/CLI_PLAN.md, section 13.11)."""
    from coating_studio.cli.spec import wt_to_vol
    from coating_studio.materials.shape_fit import FIT_POOR, admissible_n, fit_shape

    def bad(message, **details):
        return CliError("invalid_value", message, 3, details)

    f, eps_m, mu_m, eps, mu, fractions = _loadings_input(composites, matrix_csv, matrix_eps, matrix_mu, weight_fractions,
                                                         density_filler, density_matrix, "fit-shape")
    try:
        fit = fit_shape(fractions, {"eps": (eps_m, eps), "mu": (mu_m, mu)})
    except ValueError as e:
        raise bad(str(e)) from None
    b = fit.n_over_pc

    per, warns = [], []
    for k, (path, _) in enumerate(composites):
        adm = admissible_n(b, fractions, f, eps[k], mu[k], eps_m, mu_m, fractions[k])
        per.append({"csv": str(path), "fraction": fractions[k],
                    "rms_eps": None if fit.rms_per["eps"] is None else fit.rms_per["eps"][k],
                    "rms_mu": None if fit.rms_per["mu"] is None else fit.rms_per["mu"][k],
                    "shape_n_range": None if adm is None else [adm[0], adm[1]],
                    "percolation_range": None if adm is None else [min(adm[0] / b, 1.0), min(adm[1] / b, 1.0)],
                    "admissible_share": None if adm is None else adm[2]})
        if adm is None:
            warns.append(("shape_no_admissible_n", {"label": str(path)}))
    flo, fhi = fit.flat_interval
    if fit.at_bound:
        warns.insert(0, ("shape_at_bound", {"b": b}))
    if fit.rms > FIT_POOR:
        warns.insert(0, ("shape_fit_poor", {"rms": fit.rms, "limit": FIT_POOR}))
    if flo < 0.5 * b or fhi > 1.5 * b:
        warns.append(("shape_flat", {"lo": flo, "hi": fhi}))
    if len(composites) == 2:
        warns.append(("shape_two_fractions", {}))
    return CommandResult({
        "n_over_pc": b, "rms": fit.rms, "channels_used": fit.channels_used, "n_points": int(f.size),
        "data_range_hz": [float(f[0]), float(f[-1])], "search_range": list(fit.search_range),
        "flat_interval": [flo, fhi], "profile": {"n_over_pc": fit.profile_b.tolist(), "rms": fit.profile_rms.tolist()},
        "per_composite": per,
    }, warnings=[_shape_warning(c, a) for c, a in warns])


def cmd_extract_nrw(s2p_path, thickness_mm, output, force=False, cutoff_ghz=None, waveguide_a_mm=None, branch=0,
                    offset1_mm=0.0, offset2_mm=0.0, uncertainty_csv=None, thickness_sigma_mm=0.0, mag_sigma_db=0.0,
                    phase_sigma_deg=0.0, uncertainty_samples=200, seed=0, method="nrw", coax_gap=None,
                    holder_length_mm=None, holder_sigma_mm=0.0):
    """eps(f), mu(f) of a sample from a measured .s2p by Nicholson-Ross-Weir (docs/CLI_PLAN.md, section 13.12)."""
    from coating_studio.core.constants import C0
    from coating_studio.materials.csvio import to_csv_text
    from coating_studio.materials.extraction import (
        RECIPROCITY, SMALL_S11, coax_gap_correction, nonmagnetic, nonmagnetic_invariant, nrw, nrw_uncertainty,
    )
    from coating_studio.touchstone import TouchstoneError, parse_s2p

    try:
        with open(s2p_path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except FileNotFoundError:
        raise CliError("file_not_found", f"{s2p_path}: no such file", 3, {"path": str(s2p_path)}) from None
    try:
        f, s11, s21, s12, s22, ref = parse_s2p(text)
    except TouchstoneError as e:
        raise CliError("invalid_value", f"{s2p_path}: {e}", 3) from None
    if waveguide_a_mm is not None:
        if not waveguide_a_mm > 0:
            raise CliError("invalid_value", "--waveguide-a-mm must be positive", 3)
        cutoff_hz = C0 / (2 * waveguide_a_mm * 1e-3)
    else:
        cutoff_hz = None if cutoff_ghz is None else cutoff_ghz * 1e9
    for out_path in [output] + ([uncertainty_csv] if uncertainty_csv else []):
        if os.path.abspath(out_path) == os.path.abspath(s2p_path):
            raise CliError("invalid_value", f"{out_path} is the input file; --force does not overwrite measurements", 3,
                           {"path": str(out_path)})
    if uncertainty_csv and os.path.abspath(uncertainty_csv) == os.path.abspath(output):
        raise CliError("usage", "--uncertainty-csv must differ from --output", 2)
    sigmas = (thickness_sigma_mm, mag_sigma_db, phase_sigma_deg, holder_sigma_mm)
    if uncertainty_csv and not any(sigmas):
        raise CliError("usage", "--uncertainty-csv needs at least one of --thickness-sigma-mm, --mag-sigma-db, "
                       "--phase-sigma-deg (no error is assumed by default)", 2)
    if any(sigmas) and not uncertainty_csv:
        raise CliError("usage", "the sigma options go with --uncertainty-csv", 2)
    check_output_path(output, force)
    if uncertainty_csv:
        check_output_path(uncertainty_csv, force)
    if method not in ("nrw", "nonmagnetic", "nonmagnetic-invariant"):
        raise CliError("usage", f"unknown method {method!r}", 2)
    invariant = method == "nonmagnetic-invariant"
    if invariant:
        if holder_length_mm is None:
            raise CliError("usage", "--method nonmagnetic-invariant needs --holder-length-mm (the empty-line length "
                           "between the calibration planes, sample included)", 2)
        if offset1_mm or offset2_mm:
            raise CliError("usage", "the position-invariant method does not take --offset1-mm/--offset2-mm", 2)
    elif holder_length_mm is not None or holder_sigma_mm:
        raise CliError("usage", "--holder-length-mm and --holder-sigma-mm go with --method nonmagnetic-invariant", 2)
    post = None
    if coax_gap is not None:
        if cutoff_hz is not None:
            raise CliError("usage", "--coax-gap is for a coaxial holder, not a waveguide", 2)
        try:
            coax_gap_correction(1.0, 1.0, *coax_gap)  # checks the radii
        except ValueError as e:
            raise CliError("invalid_value", f"--coax-gap: {e}", 3) from None
        post = lambda e, m: coax_gap_correction(e, m, *coax_gap)  # noqa: E731
    try:
        if invariant:
            r = nonmagnetic_invariant(f, s11, s21, s12, s22, thickness_mm * 1e-3, holder_length_mm * 1e-3, cutoff_hz,
                                      branch)
        else:
            extract = nrw if method == "nrw" else nonmagnetic
            r = extract(f, s11, s21, thickness_mm * 1e-3, cutoff_hz, branch, s12=s12, offset1=offset1_mm * 1e-3,
                        offset2=offset2_mm * 1e-3)
    except ValueError as e:
        raise CliError("invalid_value", str(e), 4) from None
    eps_out, mu_out = r.eps, r.mu
    if post is not None:
        try:
            eps_out, mu_out = post(r.eps, r.mu)
        except ValueError as e:
            raise CliError("invalid_value", f"--coax-gap: {e}", 4) from None
    write_text(output, to_csv_text(r.f, eps_out, mu_out))
    unc = None
    if uncertainty_csv:
        try:
            u = nrw_uncertainty(f, s11, s21, thickness_mm * 1e-3, cutoff_hz, branch, s12=s12, offset1=offset1_mm * 1e-3,
                                offset2=offset2_mm * 1e-3, sigma_thickness=thickness_sigma_mm * 1e-3,
                                sigma_mag_db=mag_sigma_db, sigma_phase_deg=phase_sigma_deg,
                                n_samples=uncertainty_samples, seed=seed, method=method.replace("-", "_"), post=post,
                                s22=s22, holder_length=None if holder_length_mm is None else holder_length_mm * 1e-3,
                                sigma_holder=holder_sigma_mm * 1e-3)
        except ValueError as e:
            raise CliError("invalid_value", str(e), 4) from None
        rows = [[f"{a / 1e9:.9g}", f"{b:.6g}", f"{c:.6g}", f"{d:.6g}", f"{e:.6g}"]
                for a, b, c, d, e in zip(u.f, u.eps_re, u.eps_loss, u.mu_re, u.mu_loss)]
        write_text(uncertainty_csv, csv_text(["f [GHz]", "u(eps')", "u(eps'')", "u(mu')", "u(mu'')"], rows))
        rel = lambda sd, val: float(np.median(sd / np.maximum(np.abs(val), 1e-12)))  # noqa: E731
        unc = {"output_path": str(uncertainty_csv), "n_samples": u.n_samples, "seed": seed,
               "median_relative": {"eps_re": rel(u.eps_re, eps_out.real), "mu_re": rel(u.mu_re, mu_out.real)},
               "sigmas": {"thickness_mm": thickness_sigma_mm, "mag_db": mag_sigma_db, "phase_deg": phase_sigma_deg}}
    messages = {
        "half_wave_resonance": lambda a: (f"|S11| < {SMALL_S11:g} at {len(a['f_hz'])} frequencies: the sample is close to a "
                                          "multiple of half a wavelength there and the values are unreliable"),
        "branch_suspect": lambda a: (f"the phase branch {a['branch']} looks wrong; branch {a['suggested_branch']} fits the "
                                     "measured group delay better (rerun with --branch)"),
        "nonpassive": lambda a: f"the result shows gain (eps'' or mu'' < 0) at {len(a['f_hz'])} frequencies",
        "nonreciprocal": lambda a: (f"S21 and S12 differ by up to {a['max_relative']:.3g} (relative, more than "
                                    f"{RECIPROCITY:g}): check the calibration; their mean was used"),
        "fit_poor": lambda a: (f"the mu = 1 fit misses the measured S-parameters at {len(a['f_hz'])} frequencies "
                               f"(rms up to {a['max_residual']:.3g}): the sample may be magnetic; use --method nrw"),
        "asymmetric": lambda a: (f"|S11| and |S22| differ by up to {a['max_mag_diff']:.3g}: the sample is not symmetric "
                                 "(or the calibration differs at the two ports); the position-invariant fit assumes it is"),
    }
    warns = [warning(code, messages[code](args), **args) for code, args in r.warnings]
    return CommandResult({
        "output_path": str(output), "n_points": int(r.f.size), "data_range_hz": [float(r.f[0]), float(r.f[-1])],
        "line": "TEM" if cutoff_hz is None else "TE10 waveguide", "cutoff_hz": cutoff_hz, "method": method,
        "holder_length_m": None if holder_length_mm is None else holder_length_mm * 1e-3,
        "coax_gap_mm": None if coax_gap is None else list(coax_gap),
        "thickness_m": thickness_mm * 1e-3, "branch": r.branch, "suggested_branch": r.suggested_branch,
        "delay_mismatch": r.delay_mismatch, "reciprocity_error": r.reciprocity_error, "reference_ohm": ref,
        "resonant_points": int(np.count_nonzero(r.resonant)), "uncertainty": unc,
    }, warnings=warns, input_info={"path": str(s2p_path)})


def cmd_fit_gem(composites, matrix_csv=None, matrix_eps=None, matrix_mu=None, weight_fractions=False,
                density_filler=None, density_matrix=None):
    """McLachlan GEM pc and t from composites at several loadings (docs/CLI_PLAN.md, section 13.13)."""
    from coating_studio.materials.gem_fit import FIT_POOR, PC_GRID, T_GRID, T_WEAK, fit_gem, warning_flags

    f, eps_m, mu_m, eps, mu, fractions = _loadings_input(composites, matrix_csv, matrix_eps, matrix_mu, weight_fractions,
                                                         density_filler, density_matrix, "fit-gem")
    channels = {"eps": (eps_m, eps), "mu": (mu_m, mu)}
    try:
        fit = fit_gem(fractions, channels)
    except ValueError as e:
        raise CliError("invalid_value", str(e), 3) from None
    messages = {
        "gem_one_sided": lambda a: (f"every loading lies {a['side']} the fitted threshold {a['pc']:.3g}: pc and t are poorly "
                                    "determined from one side; measure loadings on both sides"),
        "gem_fit_poor": lambda a: (f"the best (pc, t) reproduces the composites only to {a['rms']:.1%} rms (above "
                                   f"{a['limit']:.0%}); GEM may not describe this composite family"),
        "gem_at_bound": lambda a: (f"the best grid point lies at the edge of pc {a['pc_range'][0]:g}-{a['pc_range'][1]:g}, "
                                   f"t {a['t_range'][0]:g}-{a['t_range'][1]:g}; the data may need values outside it"),
        "gem_two_fractions": lambda a: "only two loadings: no loading is left to test the fit; validate with a third",
        "gem_t_weak": lambda a: (f"the fit hardly changes over t = {a['t_lo']:.3g}-{a['t_hi']:.3g} (width {T_WEAK:g} or more): "
                                 "the exponent is poorly determined by these loadings"),
        "gem_channel_mismatch": lambda a: (f"eps alone gives pc = {a['pc_eps']:.3g}, mu alone {a['pc_mu']:.3g}: one GEM rule "
                                           "for both may not fit this filler"),
    }
    warns = [warning(code, messages[code](args), **args) for code, args in warning_flags(fit, fractions, channels)]
    per = [{"csv": str(path), **row} for (path, _), row in zip(composites, fit.per_composite)]
    return CommandResult({
        "percolation": fit.percolation, "exponent": fit.exponent, "rms": fit.rms, "rms_per": fit.rms_per,
        "channels_used": fit.channels_used, "n_points": int(f.size), "data_range_hz": [float(f[0]), float(f[-1])],
        "flat_region": {"percolation": list(fit.flat_pc), "exponent": list(fit.flat_t)},
        "search_range": {"percolation": [float(PC_GRID[0]), float(PC_GRID[-1])],
                         "exponent": [float(T_GRID[0]), float(T_GRID[-1])]},
        "per_composite": per, "fit_poor_limit": FIT_POOR,
    }, warnings=warns)


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
