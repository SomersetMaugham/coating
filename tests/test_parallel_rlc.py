"""Parallel-RLC sheets outside the solver: files, specs, the optimiser, tolerances and the report."""
import io
import json

import numpy as np
import pytest

from coating_studio.cli import main
from coating_studio.core import SheetLayer
from coating_studio.examples import EXAMPLES
from coating_studio.optimize.optimizer import OptimizationError, preflight
from coating_studio.project import SCHEMA_VERSION, ContinuousVariable, Project, available_params, get_param
from coating_studio.report import build_report
from coating_studio.tolerance import sample_factors


def run(*argv):
    out = io.StringIO()
    code = main([str(a) for a in argv], stdout=out, stderr=io.StringIO())
    return code, json.loads(out.getvalue())


def parallel_project(L=4e-9, C=0.08e-12):
    p = EXAMPLES["cara"][1]()
    sh = p.structure.layers[0]
    sh.model, sh.L, sh.C = "parallel_rlc", L, C
    p.optimization.variables = [v for v in p.optimization.variables if tuple(v.path[:2]) != ("layer", sh.uid)]
    return p, sh


def test_file_round_trip_and_schema():
    p, sh = parallel_project()
    q = Project.from_dict(json.loads(json.dumps(p.to_dict())))
    s2 = q.structure.layers[0]
    assert (s2.model, s2.L, s2.C) == ("parallel_rlc", 4e-9, 0.08e-12) and q.to_dict()["schema"] == SCHEMA_VERSION


def test_an_older_reader_refuses_the_model_rather_than_miscomputing():
    """Why the schema stays: the model name itself is rejected by a reader that does not know it."""
    p, _ = parallel_project()
    d = json.loads(json.dumps(p.to_dict()))
    d["structure"]["layers"][0]["model"] = "not_a_model"
    with pytest.raises(ValueError, match="unknown sheet model"):
        Project.from_dict(d)


def test_parameters_follow_the_elements_that_exist():
    p, sh = parallel_project()
    paths = [x[0] for x in available_params(p)]
    assert ("layer", sh.uid, "L") in paths and ("layer", sh.uid, "C") in paths and ("layer", sh.uid, "X") not in paths
    assert get_param(p, ("layer", sh.uid, "L")) == 4e-9
    sh.L = 0.0
    assert ("layer", sh.uid, "L") not in [x[0] for x in available_params(p)]
    with pytest.raises(KeyError):
        get_param(p, ("layer", sh.uid, "L"))


def test_series_l_stays_a_parameter_at_zero():
    sh = SheetLayer(100.0, model="rlc", L=0.0, C=None)
    assert sh.has_param("L")


def _with_l_variable(lower):
    p, sh = parallel_project()
    p.optimization.variables.append(ContinuousVariable(("layer", sh.uid, "L"), lower, 50e-9))
    return p


def test_optimiser_refuses_a_parallel_l_range_that_reaches_zero():
    with pytest.raises(OptimizationError, match="lower bound of a parallel L"):
        preflight(_with_l_variable(0.0))
    preflight(_with_l_variable(0.1e-9))


def test_series_l_range_may_still_start_at_zero():
    p = EXAMPLES["cara"][1]()
    sh = p.structure.layers[0]
    p.optimization.variables = [ContinuousVariable(("layer", sh.uid, "L"), 0.0, 50e-9)]
    preflight(p)


def test_tolerance_moves_r_l_and_c_separately():
    p, sh = parallel_project()
    p.tolerance.n_samples = 8
    factors = sample_factors(p, p.tolerance, np.random.default_rng(1), 8)[sh.uid]
    assert set(factors) == {"sheet_R", "sheet_L", "sheet_C"}


def test_spec_round_trip(tmp_path):
    p, sh = parallel_project()
    src = tmp_path / "a.coat"
    p.save(src)
    spec = tmp_path / "a.json"
    assert run("spec", src, "-o", spec)[0] == 0
    d = json.loads(spec.read_text(encoding="utf-8"))
    sheet = d["layers"][0]["sheet"]
    assert sheet["model"] == "parallel_rlc" and sheet["L_nh"] == pytest.approx(4.0) and sheet["C_pf"] == pytest.approx(0.08)
    out = tmp_path / "b.coat"
    code, env = run("build", spec, "-o", out)
    assert code == 0, env
    s2 = Project.load(out).structure.layers[0]
    assert s2.model == "parallel_rlc" and s2.L == pytest.approx(4e-9) and s2.C == pytest.approx(0.08e-12)


def test_spec_rejects_an_unknown_model_and_a_non_numeric_capacitor(tmp_path):
    p, _ = parallel_project()
    src = tmp_path / "a.coat"
    p.save(src)
    spec = tmp_path / "a.json"
    run("spec", src, "-o", spec)
    d = json.loads(spec.read_text(encoding="utf-8"))
    d["layers"][0]["sheet"]["model"] = "shunt"
    spec.write_text(json.dumps(d), encoding="utf-8")
    code, env = run("build", spec, "-o", tmp_path / "b.coat")
    assert code == 3 and "parallel_rlc" in env["error"]["message"]
    d["layers"][0]["sheet"]["model"] = "parallel_rlc"
    d["layers"][0]["sheet"]["C_pf"] = True
    spec.write_text(json.dumps(d), encoding="utf-8")
    code, env = run("build", spec, "-o", tmp_path / "c.coat")
    assert code == 3 and "must be a number" in env["error"]["message"]


def test_info_reports_a_missing_inductor_as_null(tmp_path):
    p, sh = parallel_project(L=0.0, C=None)
    src = tmp_path / "a.coat"
    p.save(src)
    code, env = run("info", src)
    assert code == 0
    assert env["result"]["layers"][0]["L_h"] is None and env["result"]["layers"][0]["C_f"] is None


def test_series_info_keeps_l_as_a_number(tmp_path):
    p = EXAMPLES["cara"][1]()
    p.structure.layers[0].L = 0.0
    src = tmp_path / "a.coat"
    p.save(src)
    assert run("info", src)[1]["result"]["layers"][0]["L_h"] == 0.0


def test_report_names_the_circuit_and_missing_elements():
    p, _ = parallel_project()
    html = build_report(p)
    assert "Parallel RLC: R = 250 Ω/sq, L = 4 nH, C = 0.08 pF" in html
    p, _ = parallel_project(L=0.0, C=None)
    html = build_report(p)
    assert "no inductor" in html and "no capacitor" in html
