"""Human-readable design spec <-> Project (docs/CLI_PLAN.md, section 13.2).

The spec holds everything a Project holds, so ``spec`` -> edit -> ``build`` is the CLI's way of editing a design.
Units are fixed per field and named by key suffixes (``thickness_mm``, ``f_ghz``, ``angle_deg``, ``R_ohm``,
``L_nh``, ``C_pf``, ``_kg_m2``); material dicts use the ``.coat`` format (SI, no suffixes).  Layers are referred
to by name (when unique) or by 1-based index; uids never appear.
"""

from __future__ import annotations

import math
import os

from coating_studio.cli.output import CliError
from coating_studio.core.structure import SHEET_MODELS, parse_angle, Backing, SheetLayer, SlabLayer, Structure
from coating_studio.core.units import (
    DEFAULT_LENGTH_UNIT, DEFAULT_SPECTRAL_UNIT, DISPLAY_SCALE, LENGTH_UNITS, SPECTRAL_UNITS, from_display, to_display,
)
from coating_studio.limits import measured_range
from coating_studio.tolerance import material_param_info
from coating_studio.materials.csvio import CsvFormatError, load_csv
from coating_studio.materials.library import builtin_materials
from coating_studio.materials.models import MixtureMaterial, material_from_dict, vol_to_wt, wt_to_vol  # noqa: F401
from coating_studio.project import (
    BandTarget, ContinuousVariable, MaterialChoice, OptimizationSettings, Project, SweepSettings,
    ToleranceSettings, get_param, param_unit,
)

SPEC_VERSION = 1
_TOL_KEYS = ("thickness", "eps", "eps_loss", "mu", "mu_loss", "sheet")


def spec_error(path, message, **details):
    return CliError("invalid_spec", f"{path}: {message}", 3, {"path": path, **details})


# ---------------------------------------------------------------------------
# weight fraction (the conversions live in materials.models)


def mixture_densities(project, mix):
    return (project.materials[mix.inclusion].get_density(project.resolver),
            project.materials[mix.matrix].get_density(project.resolver))


# ---------------------------------------------------------------------------
# Project -> spec

def _layer_refs(project):
    names = [ly.name for ly in project.structure.layers]
    refs = {}
    for i, ly in enumerate(project.structure.layers, start=1):
        refs[ly.uid] = ly.name if ly.name and names.count(ly.name) == 1 else i
    return refs


def _f_pair(lo, hi):
    return [to_display(lo, "GHz"), to_display(hi, "GHz")]


def project_to_spec(project: Project) -> dict:
    refs = _layer_refs(project)
    builtin = {m.name: m.to_dict() for m in builtin_materials()}
    materials, removed = [], [n for n in builtin if n not in project.materials]
    for m in project.materials.values():
        d = m.to_dict()
        if builtin.get(m.name) != d:
            materials.append(d)
    layers = []
    for ly in project.structure.layers:
        if isinstance(ly, SlabLayer):
            layers.append({"name": ly.name, "material": ly.material, "thickness_mm": to_display(ly.thickness, "mm")})
        elif ly.is_rlc:
            layers.append({"name": ly.name, "sheet": {"model": ly.model, "R_ohm": ly.R, "X_ohm": ly.X,
                                                      "L_nh": to_display(ly.L, "nH"),
                                                      "C_pf": None if ly.C is None else to_display(ly.C, "pF")}})
            if ly.has_angle:
                layers[-1]["sheet"]["angle"] = ly.angle_dict()
        else:
            layers.append({"name": ly.name, "sheet": {"model": "constant", "R_ohm": ly.R, "X_ohm": ly.X}})
    b = project.structure.backing
    backing = "pec" if b.kind == "pec" else {"kind": b.kind, "material": b.material}
    sw = project.sweep
    sweep = {"f_ghz": _f_pair(sw.f_min, sw.f_max), "n_f": sw.n_f, "log_f": sw.log_f, "angle_deg": sw.angle,
             "f_at_ghz": to_display(sw.f_at, "GHz"), "angle_range_deg": [sw.angle_min, sw.angle_max],
             "n_angle": sw.n_angle, "map_n_f": sw.map_n_f, "map_n_angle": sw.map_n_angle}
    if sw.spectral_unit != DEFAULT_SPECTRAL_UNIT:
        sweep["spectral_unit"] = sw.spectral_unit  # GUI display unit only; every number above stays in GHz
    if sw.wavelength_spaced():
        sweep["uniform_wavelength"] = True  # points even in vacuum wavelength (changes the results, unlike the units)
    if sw.length_unit != DEFAULT_LENGTH_UNIT:
        sweep["length_unit"] = sw.length_unit  # GUI display unit of thicknesses; the spec's numbers stay in mm
    s = project.optimization
    targets = [{"name": t.name, "f_ghz": _f_pair(t.f_min, t.f_max), "n_f": t.n_f,
                "angle_deg": [t.angle_min, t.angle_max], "n_angle": t.n_angle, "pols": list(t.pols),
                "goal_db": t.goal_db, "enabled": t.enabled} for t in s.targets]
    variables = []
    for v in s.variables:
        unit = param_unit(project, v.path)
        rng = [to_display(v.lower, unit), to_display(v.upper, unit)]
        if v.path[0] == "layer":
            variables.append({"layer": refs.get(v.path[1], v.path[1]), "param": v.path[2], "range": rng, "unit": unit})
        else:
            variables.append({"material": v.path[1], "param": list(v.path[2:]), "range": rng, "unit": unit})
    choices = [{"layer": refs.get(c.uid, c.uid), "candidates": list(c.candidates)} for c in s.choices]
    optimization = {"w_worst": s.w_worst, "w_mean": s.w_mean, "w_thickness": s.w_thickness, "w_mass": s.w_mass,
                    "rl_ref_db": s.rl_ref_db, "thickness_ref_mm": to_display(s.thickness_ref, "mm"),
                    "mass_ref_kg_m2": s.mass_ref,
                    "thickness_max_mm": None if s.thickness_max is None else to_display(s.thickness_max, "mm"),
                    "maxiter": s.maxiter, "popsize": s.popsize, "seed": s.seed, "polish": s.polish}
    if s.robust_samples:
        optimization.update(robust_samples=s.robust_samples, robust_quantile=s.robust_quantile)
    tol = project.tolerance
    tolerance = {k: getattr(tol, k) for k in ("n_samples", "distribution", *_TOL_KEYS, "loss_correlation",
                                              "target_db", "pol", "lower_pct", "upper_pct", "seed")}
    tolerance["band_ghz"] = (None if not (tol.band_min and tol.band_max)
                             else _f_pair(tol.band_min, tol.band_max))
    tolerance["angle_deg"] = tol.angle
    tolerance["per_layer"] = [{"layer": refs.get(uid, uid), **dict(d)} for uid, d in tol.per_layer.items()]
    if tol.material_params:
        tolerance["material_params"] = []
        for e in tol.material_params:
            item = {"material": e["path"][1], "param": list(e["path"][2:]), "tol": e["tol"]}
            if e.get("mode") == "absolute":  # in the parameter's display unit, as variables[] ranges are
                unit = param_unit(project, e["path"])
                item.update(tol=to_display(e["tol"], unit), mode="absolute", unit=unit)
            tolerance["material_params"].append(item)
    out = {"spec_version": SPEC_VERSION, "name": project.name, "notes": project.notes,
           "incident": project.structure.incident, "backing": backing}
    if removed:
        out["remove_builtin"] = removed
    out.update(materials=materials, layers=layers, sweep=sweep, targets=targets, variables=variables,
               choices=choices, optimization=optimization, tolerance=tolerance)
    return out


# ---------------------------------------------------------------------------
# spec -> Project

def _num(d, key, path, default=None, required=False):
    if key not in d or d[key] is None:
        if required:
            raise spec_error(f"{path}.{key}", "is required")
        return default
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise spec_error(f"{path}.{key}", f"must be a number, got {v!r}")
    return v


def _pair(d, key, path, required=False):
    v = d.get(key)
    if v is None:
        if required:
            raise spec_error(f"{path}.{key}", "is required")
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v), float(v)
    if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v)):
        raise spec_error(f"{path}.{key}", f"must be a number or [lo, hi], got {v!r}")
    if v[1] < v[0]:
        raise spec_error(f"{path}.{key}", "upper must not be below lower")
    return float(v[0]), float(v[1])


_UNKNOWN_SUFFIXES = ("thickness_m", "f_hz", "L_h", "C_f", "thickness_um", "thickness_nm")


def _reject_alt_units(d, path):
    for k in d:
        if k in _UNKNOWN_SUFFIXES:
            raise spec_error(f"{path}.{k}", "unsupported unit; the spec uses mm, GHz, deg, ohm, nH and pF")


def _material(d, i, base_dir, project):
    path = f"materials[{i}]"
    if not isinstance(d, dict) or not d.get("name"):
        raise spec_error(path, "a material needs a name")
    if "csv" in d:
        csv_path = d["csv"] if os.path.isabs(d["csv"]) else os.path.join(base_dir, d["csv"])
        try:
            m = load_csv(csv_path, name=d["name"], density=float(d.get("density", 1000.0)))
        except FileNotFoundError:
            raise spec_error(f"{path}.csv", f"{csv_path}: no such file") from None
        except (CsvFormatError, ValueError, OSError) as e:
            raise spec_error(f"{path}.csv", str(e), csv_error=str(e)) from None
        if d.get("note"):
            m.note = d["note"]
        return m, []
    d = dict(d)
    warnings = []
    wt = d.pop("fraction_wt", None)
    if wt is not None:
        if d.get("kind") != "mixture":
            raise spec_error(f"{path}.fraction_wt", "only mixtures take a weight fraction")
        if "fraction" in d:
            raise spec_error(path, "give fraction or fraction_wt, not both")
        d["fraction"] = 0.0  # set once the constituents are known (below)
    try:
        m = material_from_dict(d)
    except (KeyError, TypeError, ValueError) as e:
        raise spec_error(path, f"invalid material: {e}") from None
    if wt is not None:
        m._fraction_wt = float(wt)
    return m, warnings


def _layer_index(ref, layers, path):
    if isinstance(ref, int) and not isinstance(ref, bool):
        if not 1 <= ref <= len(layers):
            raise spec_error(path, f"layer index {ref} out of range 1..{len(layers)}")
        return ref - 1
    matches = [i for i, ly in enumerate(layers) if ly.name == ref]
    if len(matches) != 1:
        raise spec_error(path, f"layer {ref!r} " + ("not found" if not matches else "is not unique; use its index"))
    return matches[0]


def spec_to_project(spec: dict, base_dir=".") -> tuple[Project, list]:
    """Build a Project from a spec; returns (project, warnings).  Raises CliError(invalid_spec)."""
    if not isinstance(spec, dict):
        raise spec_error("$", "the spec must be a JSON object")
    if spec.get("spec_version", SPEC_VERSION) != SPEC_VERSION:
        raise spec_error("spec_version", f"unsupported version {spec.get('spec_version')!r}")
    warnings = []
    p = Project(name=spec.get("name", "Untitled"), notes=spec.get("notes", ""))
    for n in spec.get("remove_builtin", []):
        p.materials.pop(n, None)
    wt_mixtures = []
    for i, d in enumerate(spec.get("materials", [])):
        m, w = _material(d, i, base_dir, p)
        warnings += w
        p.materials[m.name] = m
        if hasattr(m, "_fraction_wt"):
            wt_mixtures.append((i, m))
    for i, m in wt_mixtures:
        try:
            rho_i, rho_m = mixture_densities(p, m)
        except KeyError as e:
            raise spec_error(f"materials[{i}]", f"unknown constituent {e}") from None
        m.fraction = wt_to_vol(m._fraction_wt, rho_i, rho_m)
        warnings.append({"code": "fraction_wt_converted", "level": "info", "material": m.name,
                         "message": f"{m.name}: {m._fraction_wt:g} wt -> {m.fraction:.4g} vol "
                                    f"(densities {rho_i:g} / {rho_m:g} kg/m3)"})
        del m._fraction_wt

    layers = []
    for i, d in enumerate(spec.get("layers", [])):
        path = f"layers[{i}]"
        if not isinstance(d, dict):
            raise spec_error(path, "a layer must be an object")
        _reject_alt_units(d, path)
        name = d.get("name", "")
        if "sheet" in d:
            sh = d["sheet"]
            model = sh.get("model")
            if model not in SHEET_MODELS:
                raise spec_error(f"{path}.sheet.model", "must be 'constant', 'rlc' or 'parallel_rlc'")
            _reject_alt_units(sh, f"{path}.sheet")
            ly = SheetLayer(float(_num(sh, "R_ohm", f"{path}.sheet", required=True)),
                            float(_num(sh, "X_ohm", f"{path}.sheet", 0.0)), name=name, model=model)
            if ly.is_rlc:
                ly.L = from_display(float(_num(sh, "L_nh", f"{path}.sheet", 0.0)), "nH")
                c = _num(sh, "C_pf", f"{path}.sheet")
                ly.C = None if c is None else from_display(float(c), "pF")
                if sh.get("angle") is not None:
                    try:
                        ly.set_angle(parse_angle(sh["angle"]))
                    except ValueError as e:
                        raise spec_error(f"{path}.sheet.angle", str(e)) from None
            elif sh.get("angle") is not None:
                raise spec_error(f"{path}.sheet.angle", "only RLC sheets have an angle dependence")
        else:
            mat = d.get("material")
            if mat not in p.materials:
                raise spec_error(f"{path}.material", f"unknown material {mat!r}")
            ly = SlabLayer(mat, from_display(float(_num(d, "thickness_mm", path, required=True)), "mm"), name=name)
        layers.append(ly)
    b = spec.get("backing", "pec")
    if b == "pec" or b == {"kind": "pec"}:
        backing = Backing("pec")
    elif isinstance(b, dict) and b.get("kind") == "halfspace":
        if b.get("material") not in p.materials:
            raise spec_error("backing.material", f"unknown material {b.get('material')!r}")
        backing = Backing("halfspace", b["material"])
    else:
        raise spec_error("backing", "must be 'pec' or {\"kind\": \"halfspace\", \"material\": ...}")
    incident = spec.get("incident", "Air")
    if incident not in p.materials:
        raise spec_error("incident", f"unknown material {incident!r}")
    p.structure = Structure(incident=incident, layers=layers, backing=backing)

    sweep_given = "sweep" in spec
    sw = SweepSettings()
    if sweep_given:
        d = spec["sweep"]
        _reject_alt_units(d, "sweep")
        f = _pair(d, "f_ghz", "sweep")
        if f:
            sw.f_min, sw.f_max = from_display(f[0], "GHz"), from_display(f[1], "GHz")
        for key in ("n_f", "n_angle", "map_n_f", "map_n_angle"):
            if key in d:
                setattr(sw, key, int(_num(d, key, "sweep")))
        if "log_f" in d:
            sw.log_f = bool(d["log_f"])
        if "uniform_wavelength" in d:
            if not isinstance(d["uniform_wavelength"], bool):
                raise spec_error("sweep.uniform_wavelength", "must be true or false")
            sw.uniform_wavelength = d["uniform_wavelength"]
        sw.uniform_wavelength = sw.wavelength_spaced()  # with log_f the grid is logarithmic
        if "angle_deg" in d:
            sw.angle = float(_num(d, "angle_deg", "sweep"))
        if "f_at_ghz" in d:
            sw.f_at = from_display(float(_num(d, "f_at_ghz", "sweep")), "GHz")
        if "spectral_unit" in d:
            if d["spectral_unit"] not in SPECTRAL_UNITS:
                raise spec_error("sweep.spectral_unit", f"must be one of {', '.join(SPECTRAL_UNITS)}")
            sw.spectral_unit = d["spectral_unit"]
        if "length_unit" in d:
            if d["length_unit"] not in LENGTH_UNITS:
                raise spec_error("sweep.length_unit", f"must be one of {', '.join(LENGTH_UNITS)}")
            sw.length_unit = d["length_unit"]
        a = _pair(d, "angle_range_deg", "sweep")
        if a:
            sw.angle_min, sw.angle_max = a
    p.sweep = sw

    targets = []
    for i, d in enumerate(spec.get("targets", [])):
        path = f"targets[{i}]"
        _reject_alt_units(d, path)
        f = _pair(d, "f_ghz", path, required=True)
        a = _pair(d, "angle_deg", path) or (0.0, 0.0)
        n_angle = d.get("n_angle")
        if a[1] > a[0]:
            if n_angle is None or int(n_angle) < 2:
                raise spec_error(f"{path}.n_angle", "an angle range needs n_angle >= 2 (else only the lower angle "
                                                     "is evaluated)")
        else:
            n_angle = 1
        pols = d.get("pols", ["TE", "TM"])
        if not pols or any(q not in ("TE", "TM") for q in pols):
            raise spec_error(f"{path}.pols", "must be a non-empty list of 'TE' / 'TM'")
        targets.append(BandTarget(f_min=from_display(f[0], "GHz"), f_max=from_display(f[1], "GHz"),
                                  n_f=int(d.get("n_f", 41)), angle_min=a[0], angle_max=a[1], n_angle=int(n_angle),
                                  pols=list(pols), goal_db=float(_num(d, "goal_db", path, required=True)),
                                  enabled=bool(d.get("enabled", True)), name=d.get("name", "")))

    o = spec.get("optimization", {})
    s = OptimizationSettings(targets=targets)
    for key in ("w_worst", "w_mean", "w_thickness", "w_mass", "rl_ref_db", "mass_ref_kg_m2"):
        if key in o:
            setattr(s, key.replace("_kg_m2", ""), float(_num(o, key, "optimization")))
    if "thickness_ref_mm" in o:
        s.thickness_ref = from_display(float(_num(o, "thickness_ref_mm", "optimization")), "mm")
    if "thickness_max_mm" in o:
        tm = o["thickness_max_mm"]
        s.thickness_max = None if tm is None else from_display(float(tm), "mm")
    for key in ("maxiter", "popsize"):
        if key in o:
            setattr(s, key, int(_num(o, key, "optimization")))
    if "seed" in o:
        s.seed = None if o["seed"] is None else int(o["seed"])
    if "polish" in o:
        s.polish = bool(o["polish"])
    if "robust_samples" in o:
        k = o["robust_samples"]
        if isinstance(k, bool) or not isinstance(k, int) or not 0 <= k <= 1000:
            raise spec_error("optimization.robust_samples", "must be a whole number from 0 to 1000 (0 = off)")
        s.robust_samples = k
    if "robust_quantile" in o:
        q = o["robust_quantile"]
        if isinstance(q, bool) or not isinstance(q, (int, float)) or not 0 < q <= 1:
            raise spec_error("optimization.robust_quantile", "must be a number above 0 and at most 1")
        s.robust_quantile = float(q)
    p.optimization = s

    for i, d in enumerate(spec.get("variables", [])):
        path = f"variables[{i}]"
        rng = d.get("range")
        if not (isinstance(rng, list) and len(rng) == 2):
            raise spec_error(f"{path}.range", "must be [lo, hi]")
        if rng[1] <= rng[0]:
            raise spec_error(f"{path}.range", "upper must exceed lower")
        if "layer" in d:
            li = _layer_index(d["layer"], layers, f"{path}.layer")
            vpath = ("layer", layers[li].uid, d.get("param"))
        elif "material" in d:
            if d["material"] not in p.materials:
                raise spec_error(f"{path}.material", f"unknown material {d['material']!r}")
            key = d.get("param")
            key = [key] if isinstance(key, str) else list(key or [])
            vpath = ("material", d["material"], *key)
        else:
            raise spec_error(path, "needs 'layer' or 'material'")
        try:
            unit = param_unit(p, vpath)
            get_param(p, vpath)
        except (KeyError, AttributeError, IndexError, TypeError):
            raise spec_error(f"{path}.param", f"no parameter {list(vpath[2:])!r}") from None
        given = d.get("unit")
        lo, hi = float(rng[0]), float(rng[1])
        if given == "wt" and vpath[0] == "material" and list(vpath[2:]) == ["fraction"] \
                and isinstance(p.materials[vpath[1]], MixtureMaterial):
            rho_i, rho_m = mixture_densities(p, p.materials[vpath[1]])
            lo, hi = wt_to_vol(lo, rho_i, rho_m), wt_to_vol(hi, rho_i, rho_m)
        elif given != unit:
            raise spec_error(f"{path}.unit", f"this parameter is in {unit!r}, not {given!r}",
                             expected=unit, allowed=list(DISPLAY_SCALE))
        else:
            lo, hi = from_display(lo, unit), from_display(hi, unit)
        s.variables.append(ContinuousVariable(vpath, lo, hi))
    for i, d in enumerate(spec.get("choices", [])):
        path = f"choices[{i}]"
        li = _layer_index(d.get("layer"), layers, f"{path}.layer")
        if not isinstance(layers[li], SlabLayer):
            raise spec_error(f"{path}.layer", "material choices apply to slab layers")
        cands = list(d.get("candidates", []))
        for c in cands:
            if c not in p.materials:
                raise spec_error(f"{path}.candidates", f"unknown material {c!r}")
        s.choices.append(MaterialChoice(layers[li].uid, cands))

    t = spec.get("tolerance", {})
    tol = ToleranceSettings()
    for key in ("n_samples", "distribution", *_TOL_KEYS, "loss_correlation", "target_db", "pol", "lower_pct",
                "upper_pct", "seed"):
        if key in t:
            setattr(tol, key, t[key])
    if not isinstance(tol.loss_correlation, (int, float)) or not -1 <= tol.loss_correlation <= 1:
        raise spec_error("tolerance.loss_correlation", "must be a number between -1 and 1")
    if "angle_deg" in t:
        tol.angle = float(t["angle_deg"])
    band = _pair(t, "band_ghz", "tolerance")
    if band:
        tol.band_min, tol.band_max = from_display(band[0], "GHz"), from_display(band[1], "GHz")
    for i, d in enumerate(t.get("per_layer", [])):
        li = _layer_index(d.get("layer"), layers, f"tolerance.per_layer[{i}].layer")
        rho = d.get("loss_correlation", 0.0)
        if isinstance(rho, bool) or not isinstance(rho, (int, float)) or not -1 <= rho <= 1:
            raise spec_error(f"tolerance.per_layer[{i}].loss_correlation", "must be a number between -1 and 1")
        tol.per_layer[layers[li].uid] = {k: v for k, v in d.items() if k != "layer"}
    seen = set()
    for i, d in enumerate(t.get("material_params", [])):
        path = f"tolerance.material_params[{i}]"
        if not isinstance(d, dict) or d.get("material") not in p.materials:
            raise spec_error(f"{path}.material", f"unknown material {d.get('material') if isinstance(d, dict) else d!r}")
        key = d.get("param")
        key = [key] if isinstance(key, str) else list(key or [])
        mpath = ["material", d["material"], *key]
        try:
            material_param_info(p, mpath)
        except ValueError:
            raise spec_error(f"{path}.param", f"no parameter {key!r}") from None
        tv = d.get("tol")
        if isinstance(tv, bool) or not isinstance(tv, (int, float)) or not math.isfinite(tv) or tv < 0:
            raise spec_error(f"{path}.tol", "must be a non-negative number (relative, e.g. 0.05)")
        if tuple(mpath) in seen:
            raise spec_error(f"{path}.param", "listed twice")
        seen.add(tuple(mpath))
        mode = d.get("mode", "relative")
        if mode not in ("relative", "absolute"):
            raise spec_error(f"{path}.mode", "must be 'relative' or 'absolute'")
        entry = {"path": mpath, "tol": float(tv)}
        if mode == "relative":
            if "unit" in d:
                raise spec_error(f"{path}.unit", "a relative tolerance has no unit; omit 'unit' or use mode 'absolute'")
        else:
            unit = param_unit(p, mpath)
            given = d.get("unit")
            if given == "wt":
                raise spec_error(f"{path}.unit", "absolute tolerances in weight fraction are not supported (the conversion "
                                 "to volume fraction depends on the loading); give it as a volume fraction ('frac')")
            if given != unit:
                raise spec_error(f"{path}.unit", f"this parameter is in {unit!r}, not {given!r}", expected=unit)
            entry.update(tol=from_display(float(tv), unit), mode="absolute")
        tol.material_params.append(entry)
    p.tolerance = tol

    warnings += _check_measured_ranges(p, spec.get("sweep"))
    return p, warnings


def _check_measured_ranges(p, sweep_spec):
    """Keep the sweep, targets and tolerance band inside the measured data of the materials in use.

    ``sweep_spec`` is the spec's sweep section (None if omitted).  Values the spec does not give are moved into
    the data range; values it gives explicitly must lie inside it (``invalid_spec`` names the field)."""
    names = set(p.structure.referenced_materials())
    for c in p.optimization.choices:
        names |= set(c.candidates)
    rng = measured_range(p, names)
    if rng is None:
        return []
    lo, hi = rng
    eps = 1e-9 * hi  # tolerate rounding at the data edges

    def outside(a, b):
        return a < lo - eps or b > hi + eps

    data = [lo / 1e9, hi / 1e9]
    for i, t in enumerate(p.optimization.targets):
        if t.enabled and outside(t.f_min, t.f_max):
            raise spec_error(f"targets[{i}].f_ghz", "outside the measured data range",
                             data_ghz=data, requested_ghz=[t.f_min / 1e9, t.f_max / 1e9])
    tol = p.tolerance
    if tol.band_min and tol.band_max and outside(tol.band_min, tol.band_max):
        raise spec_error("tolerance.band_ghz", "outside the measured data range", data_ghz=data)
    sw = p.sweep
    given = sweep_spec or {}
    before = (sw.f_min, sw.f_max)
    if "f_ghz" in given:
        if outside(sw.f_min, sw.f_max):
            raise spec_error("sweep.f_ghz", "outside the measured data range", data_ghz=data,
                             requested_ghz=[sw.f_min / 1e9, sw.f_max / 1e9])
    elif outside(sw.f_min, sw.f_max):
        sw.f_min, sw.f_max = max(sw.f_min, lo), min(sw.f_max, hi)
    if "f_at_ghz" in given:
        if not (sw.f_min - eps <= sw.f_at <= sw.f_max + eps):
            raise spec_error("sweep.f_at_ghz", "outside the sweep / measured data range", data_ghz=data,
                             sweep_ghz=[sw.f_min / 1e9, sw.f_max / 1e9], requested_ghz=sw.f_at / 1e9)
    elif not (sw.f_min <= sw.f_at <= sw.f_max):
        sw.f_at = min(max(sw.f_at, sw.f_min), sw.f_max)
    if (sw.f_min, sw.f_max) == before:
        return []
    return [{"code": "sweep_clamped", "level": "warning", "material": "",
             "message": f"sweep clamped to {sw.f_min / 1e9:g}-{sw.f_max / 1e9:g} GHz: the default "
                        f"{before[0] / 1e9:g}-{before[1] / 1e9:g} GHz sweep exceeds the measured data "
                        f"({lo / 1e9:g}-{hi / 1e9:g} GHz); give sweep.f_ghz to choose another range inside it"}]
