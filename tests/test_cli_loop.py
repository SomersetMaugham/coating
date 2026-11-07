"""Agent experiment loop: spec round trip, journal, Rozanov limits, corners, restarts, measured data
(docs/CLI_PLAN.md, section 13 and appendix B)."""

import io
import json
import math

import numpy as np
import pytest

from coating_studio.cli import main
from coating_studio.cli.progress import RunControl
from coating_studio.cli.spec import project_to_spec, spec_to_project, vol_to_wt, wt_to_vol
from coating_studio.core.structure import Backing, SlabLayer, Structure
from coating_studio.examples import EXAMPLES
from coating_studio.limits import (
    design_mu_d, max_achievable_mu_d, rozanov_required_mu_d, static_permeability, target_limits,
)
from coating_studio.materials.models import (
    ConstantMaterial, DispersiveMaterial, MixtureMaterial, TabulatedMaterial, make_term, maxwell_garnett,
)
from coating_studio.optimize import optimize
from coating_studio.project import BandTarget, ContinuousVariable, MaterialChoice, OptimizationSettings, Project
from coating_studio.tolerance import run_tolerance, tolerance_frequencies


def run(*argv, control=None):
    out, err = io.StringIO(), io.StringIO()
    code = main([str(a) for a in argv], stdout=out, stderr=err, control=control)
    env = json.loads(out.getvalue())
    assert env["ok"] == (code in (0, 5))
    return code, env


def _uid_free(p):
    s = json.dumps({k: v for k, v in p.to_dict().items() if k != "app_version"})
    for i, ly in enumerate(p.structure.layers):
        s = s.replace(ly.uid, f"#{i}")
    return json.loads(s)


def _close(a, b, path="$"):
    if isinstance(a, dict):
        assert set(a) == set(b), (path, set(a) ^ set(b))
        for k in a:
            _close(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _close(x, y, f"{path}[{i}]")
    elif isinstance(a, float) and isinstance(b, (int, float)) and not isinstance(b, bool):
        assert math.isclose(a, b, rel_tol=1e-12, abs_tol=0), (path, a, b)
    else:
        assert a == b, (path, a, b)


# -- spec ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("key", list(EXAMPLES))
def test_spec_round_trip_on_every_example(key):
    p = EXAMPLES[key][1]()
    p.tolerance.per_layer = {p.structure.layers[0].uid: {"thickness": 0.02}}
    spec = json.loads(json.dumps(project_to_spec(p)))
    q, _ = spec_to_project(spec)
    _close(_uid_free(p), _uid_free(q))


def test_build_and_spec_commands_round_trip(tmp_path):
    src = tmp_path / "dual.coat"
    EXAMPLES["dualband"][1]().save(src)
    code, env = run("spec", src, "-o", tmp_path / "dual.json")
    assert code == 0 and env["result"] == {"output_path": str(tmp_path / "dual.json")}
    code, env = run("build", tmp_path / "dual.json", "-o", tmp_path / "again.coat")
    assert code == 0 and env["input"]["spec_version"] == 1
    _close(_uid_free(Project.load(src)), _uid_free(Project.load(tmp_path / "again.coat")))
    code, env = run("spec", src)
    assert env["result"]["spec"]["targets"][1]["n_angle"] == 4


def _spec(**over):
    s = {"spec_version": 1,
         "materials": [{"name": "Mix", "kind": "mixture", "matrix": "Epoxy", "inclusion": "Carbon black",
                        "fraction": 0.1, "model": "bruggeman"}],
         "layers": [{"name": "A", "material": "Mix", "thickness_mm": 2.0}],
         "targets": [{"f_ghz": [8, 12], "angle_deg": 0, "goal_db": -15}]}
    s.update(over)
    return s


@pytest.mark.parametrize("change, path", [
    ({"targets": [{"f_ghz": [8, 12], "angle_deg": [0, 30], "goal_db": -15}]}, "targets[0].n_angle"),
    ({"layers": [{"name": "A", "material": "Nope", "thickness_mm": 1}]}, "layers[0].material"),
    ({"layers": [{"name": "A", "material": "Mix", "thickness_m": 0.001}]}, "layers[0].thickness_m"),
    ({"variables": [{"layer": "A", "param": "thickness", "range": [0.5, 3], "unit": "m"}]}, "variables[0].unit"),
    ({"variables": [{"layer": "B", "param": "thickness", "range": [0.5, 3], "unit": "mm"}]}, "variables[0].layer"),
    ({"layers": [{"name": "R", "sheet": {"R_ohm": 377}}]}, "layers[0].sheet.model"),
])
def test_invalid_specs_name_the_offending_field(tmp_path, change, path):
    sp = tmp_path / "s.json"
    sp.write_text(json.dumps(_spec(**change)))
    code, env = run("build", sp, "-o", tmp_path / "o.coat")
    assert code == 3 and env["error"]["code"] == "invalid_spec" and env["error"]["details"]["path"] == path


def test_param_accepts_a_string_for_one_level_material_paths_and_layer_indices(tmp_path):
    sp = tmp_path / "s.json"
    sp.write_text(json.dumps(_spec(variables=[{"material": "Mix", "param": "fraction", "range": [0.05, 0.2], "unit": "frac"},
                                              {"layer": 1, "param": "thickness", "range": [1, 3], "unit": "mm"}])))
    code, env = run("build", sp, "-o", tmp_path / "o.coat")
    assert code == 0
    p = Project.load(tmp_path / "o.coat")
    assert [tuple(v.path) for v in p.optimization.variables] == [
        ("material", "Mix", "fraction"), ("layer", p.structure.layers[0].uid, "thickness")]
    assert p.optimization.targets[0].n_angle == 1 and p.optimization.targets[0].angle_max == 0


def test_weight_fraction_conversion(tmp_path):
    mats = [{"name": "Rubber", "kind": "constant", "eps_re": 3.0, "density": 1150},
            {"name": "Iron", "kind": "constant", "eps_re": 20.0, "mu_re": 5.0, "density": 7860},
            {"name": "Mix", "kind": "mixture", "matrix": "Rubber", "inclusion": "Iron", "fraction_wt": 0.6,
             "model": "maxwell_garnett"}]
    sp = tmp_path / "s.json"
    sp.write_text(json.dumps(_spec(materials=mats, variables=[
        {"material": "Mix", "param": ["fraction"], "range": [0.5, 0.7], "unit": "wt"}])))
    code, env = run("build", sp, "-o", tmp_path / "o.coat")
    assert code == 0 and env["warnings"][0]["code"] == "fraction_wt_converted"
    p = Project.load(tmp_path / "o.coat")
    by_hand = (0.6 / 7860) / (0.6 / 7860 + 0.4 / 1150)
    assert p.materials["Mix"].fraction == pytest.approx(by_hand)
    v = p.optimization.variables[0]
    assert (v.lower, v.upper) == pytest.approx((wt_to_vol(0.5, 7860, 1150), wt_to_vol(0.7, 7860, 1150)))
    code, env = run("info", tmp_path / "o.coat")
    var = env["result"]["optimization"]["variables"][0]
    assert var["lower"]["value_wt"] == pytest.approx(0.5) and var["upper"]["value_wt"] == pytest.approx(0.7)
    assert vol_to_wt(wt_to_vol(0.42, 7860, 1150), 7860, 1150) == pytest.approx(0.42)


# -- measured data ---------------------------------------------------------------------------------------------

def _csv(tmp_path, lo=1e9, hi=8e9):
    p = Project()
    m = DispersiveMaterial("CI", eps_inf=14.0, eps_loss=0.3, mu_terms=[make_term("debye", delta=3.5, f0=2e9)])
    f = np.linspace(lo, hi, 71)
    eps, mu = m.eps_mu(f, p.resolver)
    path = tmp_path / "ci.csv"
    with open(path, "w") as fh:
        fh.write("f [GHz], eps', eps'', mu', mu''\n")
        for fi, e, u in zip(f, eps, mu):
            fh.write(f"{fi / 1e9:.6f}, {e.real:.8f}, {-e.imag:.8f}, {u.real:.8f}, {-u.imag:.8f}\n")
    return path


def test_measured_range_clamps_an_omitted_sweep_and_rejects_targets_outside(tmp_path):
    _csv(tmp_path)
    base = {"materials": [{"name": "Meas", "csv": "ci.csv"}], "layers": [{"material": "Meas", "thickness_mm": 1.2}],
            "targets": [{"f_ghz": [2, 6], "angle_deg": 0, "goal_db": -10}]}
    sp = tmp_path / "s.json"
    sp.write_text(json.dumps(base))
    code, env = run("build", sp, "-o", tmp_path / "o.coat")
    assert code == 0 and env["warnings"][0]["code"] == "sweep_clamped"
    p = Project.load(tmp_path / "o.coat")
    assert (p.sweep.f_min, p.sweep.f_max) == (2e9, 8e9)
    assert run("solve", tmp_path / "o.coat", "--summary-only")[0] == 0
    for change, path in (({"sweep": {"f_ghz": [2, 18]}}, "sweep.f_ghz"),
                         ({"targets": [{"f_ghz": [6, 10], "angle_deg": 0, "goal_db": -10}]}, "targets[0].f_ghz")):
        sp.write_text(json.dumps({**base, **change}))
        code, env = run("build", sp, "-o", tmp_path / "x.coat", "--force")
        assert code == 3 and env["error"]["details"]["path"] == path


def test_check_reports_sweep_outside_data(tmp_path):
    p = Project()
    p.add_material(TabulatedMaterial("Meas", np.linspace(4e9, 8e9, 5), np.full(5, 4.0), np.full(5, 0.2)))
    p.structure = Structure(layers=[SlabLayer("Meas", 2e-3)], backing=Backing("pec"))
    p.save(tmp_path / "m.coat")
    code, env = run("check", tmp_path / "m.coat")
    assert code == 4
    assert "sweep_outside_data" in {i["code"] for i in env["result"]["issues"]}


def test_fit_recovers_a_debye_material(tmp_path):
    code, env = run("fit", _csv(tmp_path), "--mu-debye", "1")
    assert code == 0 and env["result"]["rms_mu"] < 1e-3
    mat = env["result"]["material"]
    assert mat["mu_terms"][0]["delta"] == pytest.approx(3.5, rel=1e-3)
    assert mat["mu_terms"][0]["f0"] == pytest.approx(2e9, rel=1e-3)
    assert mat["note"].startswith("fitted:")
    code, env = run("fit", tmp_path / "ci.csv")
    assert {w["code"] for w in env["warnings"]} == {"mu_not_fitted"}


# -- Rozanov ---------------------------------------------------------------------------------------------------

def test_rozanov_required_value():
    assert rozanov_required_mu_d(8e9, 12e9, -20) * 1e3 == pytest.approx(1.4571, abs=1e-4)
    assert rozanov_required_mu_d(8e9, 12e9, -15) * 1e3 == pytest.approx(1.093, abs=1e-3)
    assert rozanov_required_mu_d(8e9, 12e9, -20, n_inc=2.0) == pytest.approx(rozanov_required_mu_d(8e9, 12e9, -20) / 2)


def test_static_permeability_by_material_kind():
    p = Project()
    r = p.resolver
    assert static_permeability(ConstantMaterial("a", 4, 0, 2.5, 0.0), r) == (2.5, False)
    assert static_permeability(ConstantMaterial("b", 4, 0, 2.5, 0.3), r)[0] is None  # constant mu'' -> unknown
    d = DispersiveMaterial("c", mu_inf=1.2, mu_terms=[make_term("debye", 3.0, 2e9), make_term("lorentz", 1.5, 5e9, 1e9)])
    assert static_permeability(d, r)[0] == pytest.approx(1.2 + 3.0 + 1.5)
    t = TabulatedMaterial("t", [1e9, 2e9], [4, 4], [0, 0], [3, 3], [0, 0])
    assert static_permeability(t, r)[0] is None
    p.add_material(ConstantMaterial("m1", 3, 0, 1.0, 0))
    p.add_material(ConstantMaterial("m2", 20, 0, 6.0, 0))
    mix = MixtureMaterial("mx", "m1", "m2", 0.3, "maxwell_garnett")
    assert static_permeability(mix, p.resolver)[0] == pytest.approx(float(np.real(maxwell_garnett(1.0, 6.0, 0.3))))
    fitted = DispersiveMaterial("f", mu_terms=[make_term("debye", 2.0, 1e9)], note="fitted: x.csv")
    assert static_permeability(fitted, r) == (3.0, True)


def _limit_project(thickness, angle=(0.0, 0.0), backing="pec", variables=(), choices=(), tmax=None):
    p = Project()
    ly = SlabLayer("Epoxy", thickness)
    p.structure = Structure(layers=[ly], backing=Backing(backing, "Epoxy" if backing == "halfspace" else None))
    t = BandTarget(f_min=8e9, f_max=12e9, angle_min=angle[0], angle_max=angle[1], n_angle=1 if angle[1] == 0 else 4,
                   goal_db=-20)
    p.optimization = OptimizationSettings(targets=[t], thickness_max=tmax)
    p.optimization.variables = [ContinuousVariable(("layer", ly.uid, "thickness"), lo, hi) for lo, hi in variables]
    p.optimization.choices = [MaterialChoice(ly.uid, list(c)) for c in choices]
    return p


def test_salisbury_passes_and_thin_layers_fail_the_bound():
    assert [r["status"] for r in target_limits(EXAMPLES["salisbury"][1]())] == ["ok"]
    assert target_limits(_limit_project(1e-3))[0]["status"] == "infeasible"  # 1 mm < 1.457 mm, no variables
    p = _limit_project(1e-3, variables=[(0.5e-3, 3e-3)])
    assert target_limits(p)[0]["status"] == "violated"  # reachable by making it thicker
    p = _limit_project(1e-3, variables=[(0.5e-3, 3e-3)], tmax=1.2e-3)
    assert target_limits(p)[0]["status"] == "infeasible"  # the thickness limit forbids it
    p = _limit_project(1e-3, choices=[("Epoxy", "Carbonyl iron / epoxy")])
    assert target_limits(p)[0]["status"] == "violated"  # mu_s = 4 candidate: 4 mm > 1.457 mm
    assert max_achievable_mu_d(p)[0] == pytest.approx(4e-3)
    assert design_mu_d(p)[0] == pytest.approx(1e-3)


def test_bound_applies_to_targets_including_normal_incidence_only():
    assert target_limits(_limit_project(1e-3, angle=(0, 30)))[0]["status"] == "infeasible"  # v6 rule
    assert target_limits(_limit_project(1e-3, angle=(30, 60)))[0]["status"] == "unknown"
    assert target_limits(_limit_project(1e-3, backing="halfspace"))[0]["status"] == "unknown"


def test_check_reports_limits_as_warnings_and_bound_command(tmp_path):
    _limit_project(1e-3).save(tmp_path / "thin.coat")
    code, env = run("check", tmp_path / "thin.coat")
    assert code == 0  # warnings only
    assert env["result"]["limits"][0]["status"] == "infeasible"
    assert any(i["code"] == "rozanov_infeasible" and i["target"] == 0 for i in env["result"]["issues"])
    code, env = run("bound", "--f-ghz", "8", "12", "--goal-db", "-20", "--mu-s", "4")
    assert env["result"]["min_thickness_m"] == pytest.approx(rozanov_required_mu_d(8e9, 12e9, -20) / 4)
    assert env["input"] is None


def test_mixture_fraction_range_warning(tmp_path):
    p = Project()
    p.add_material(MixtureMaterial("Mix", "Epoxy", "Carbon black", 0.10, "bruggeman"))
    p.structure = Structure(layers=[SlabLayer("Mix", 2e-3)], backing=Backing("pec"))
    p.save(tmp_path / "a.coat")
    codes = {i["code"] for i in run("check", tmp_path / "a.coat")[1]["result"]["issues"]}
    assert "mixture_fraction_range" not in codes  # the unused built-in Carbon / epoxy (0.30) is not reported
    p.optimization.variables = [ContinuousVariable(("material", "Mix", "fraction"), 0.05, 0.25)]
    p.save(tmp_path / "b.coat")
    issues = [i for i in run("check", tmp_path / "b.coat", "--no-opt")[1]["result"]["issues"]
              if i["code"] == "mixture_fraction_range"]
    assert issues and issues[0]["args"]["lo"] == 0.25 and issues[0]["args"]["hi"] == 0.40  # closed interval


# -- corners, restarts, materials -----------------------------------------------------------------------------

def test_corners_match_run_tolerance_and_joint_yield(tmp_path):
    p = EXAMPLES["dualband"][1]()
    p.save(tmp_path / "d.coat")
    code, env = run("tolerance", tmp_path / "d.coat", "--corners", "--seed", "3", "--n-samples", "30")
    assert code == 0
    corners = env["result"]["corners"]
    t1 = p.optimization.enabled_targets()[1]
    assert {(c["target"], c["angle_deg"], c["pol"]) for c in corners if c["target"] == 1} == \
        {(1, a, q) for a in (t1.angle_min, t1.angle_max) for q in t1.pols}
    c = next(c for c in corners if c["target"] == 1 and c["angle_deg"] == t1.angle_max and c["pol"] == "TE")
    p.tolerance.seed, p.tolerance.n_samples, p.tolerance.angle, p.tolerance.pol = 3, 30, t1.angle_max, "TE"
    p.tolerance.target_db = t1.goal_db
    r = run_tolerance(p, tolerance_frequencies(p), band=[(t1.f_min, t1.f_max)])
    assert c["yield_fraction"] == r.yield_fraction
    assert env["result"]["joint_yield_fraction"] <= min(x["yield_fraction"] for x in corners)


def test_restarts_keep_the_best_seed(tmp_path):
    EXAMPLES["salisbury"][1]().save(tmp_path / "s.coat")
    code, env = run("optimize", tmp_path / "s.coat", "--seed", "10", "--maxiter", "8", "--restarts", "3")
    rows = env["result"]["restarts"]
    assert [r["seed"] for r in rows] == [10, 11, 12]
    p = Project.load(tmp_path / "s.coat")
    p.optimization.maxiter, p.optimization.seed = 8, 11
    assert rows[1]["objective"] == optimize(p, throttle_s=0.0).terms.objective
    assert env["result"]["terms"]["objective"] == min(r["objective"] for r in rows)


def test_restarts_stop_early_when_asked(tmp_path):
    EXAMPLES["salisbury"][1]().save(tmp_path / "s.coat")
    ctl = RunControl(command="optimize")
    ctl.stop_event.set()
    code, env = run("optimize", tmp_path / "s.coat", "--restarts", "3", control=ctl)
    assert code == 5 and len(env["result"]["restarts"]) == 1


def test_materials_dicts_rebuild_the_builtins(tmp_path):
    code, env = run("materials")
    mats = env["result"]["materials"]
    epoxy = next(m for m in mats if m["name"] == "Epoxy")
    assert epoxy["is_demo"] and epoxy["static_mu"] == 1.0
    assert next(m for m in mats if m["name"] == "Air")["is_demo"] is False
    sp = tmp_path / "s.json"
    sp.write_text(json.dumps({"materials": [m["dict"] for m in mats], "layers": []}))
    run("build", sp, "-o", tmp_path / "o.coat")
    assert Project.load(tmp_path / "o.coat").to_dict()["materials"] == Project().to_dict()["materials"]


# -- journal ---------------------------------------------------------------------------------------------------

def test_journal_records_snapshots_and_compares_within_a_fingerprint(tmp_path):
    src = tmp_path / "s.coat"
    EXAMPLES["salisbury"][1]().save(src)
    j = tmp_path / "runs"
    run("solve", src, "--summary-only", "--journal", j, "--note", "baseline")
    run("optimize", src, "-o", tmp_path / "o.coat", "--maxiter", "10", "--seed", "1", "--journal", j, "--note", "opt")
    run("solve", src, "--summary-only", "--journal", j)  # same input -> same snapshot
    entries = [json.loads(line) for line in (j / "journal.jsonl").read_text().splitlines()]
    assert [e["seq"] for e in entries] == [1, 2, 3]
    assert entries[0]["summary"]["max_margin_db"] is not None  # margins recorded even without --targets
    assert entries[0]["snapshot"] == entries[2]["snapshot"]
    assert entries[1]["output_snapshot"] and entries[1]["seed_used"] == 1
    assert len(list((j / "snapshots").iterdir())) == 2
    code, env = run("journal", j)
    fp = env["result"]["fingerprints"]
    assert len(fp) == 1 and fp[0]["best"]["seq"] == 2 and env["warnings"] == []
    p = Project.load(src)
    p.optimization.targets[0].goal_db = -10
    p.save(tmp_path / "other.coat")
    run("solve", tmp_path / "other.coat", "--summary-only", "--journal", j)
    code, env = run("journal", j)
    assert len(env["result"]["fingerprints"]) == 2 and env["warnings"][0]["code"] == "targets_changed"
