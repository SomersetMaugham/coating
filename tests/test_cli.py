"""coating-cli: output contract, GUI-identical numbers, error codes, cancellation (docs/CLI_PLAN.md, section 9)."""

import io
import json
import math
import signal
import subprocess
import sys
import textwrap

import numpy as np
import pytest

from coating_studio.cli import main
from coating_studio.cli.output import sanitize
from coating_studio.cli.progress import RunControl
from coating_studio.core.solver import solve
from coating_studio.core.structure import Backing, SlabLayer, Structure
from coating_studio.core.units import power_to_db
from coating_studio.examples import EXAMPLES
from coating_studio.materials.models import MixtureMaterial, TabulatedMaterial
from coating_studio.optimize import evaluate_terms, optimize
from coating_studio.project import SCHEMA_VERSION, Project
from coating_studio.tolerance import run_tolerance, tolerance_frequencies, yield_intervals


def run(*argv, control=None):
    out, err = io.StringIO(), io.StringIO()
    code = main([str(a) for a in argv], stdout=out, stderr=err, control=control)
    text = out.getvalue()
    env = json.loads(text) if text.lstrip().startswith("{") else None
    if env is not None:
        assert env["ok"] == (code in (0, 5)), (code, env)  # invariant of the envelope
        assert env["cli_schema"] == 1 and "command" in env
    return code, env, text, err.getvalue()


@pytest.fixture
def example(tmp_path):
    def make(key):
        path = tmp_path / f"{key}.coat"
        EXAMPLES[key][1]().save(path)
        return path
    return make


def save(project, tmp_path, name="p.coat"):
    path = tmp_path / name
    project.save(path)
    return path


# -- Qt boundary ---------------------------------------------------------------------------------------------

def test_cli_never_imports_qt_or_matplotlib(tmp_path):
    path = tmp_path / "sal.coat"
    script = textwrap.dedent(f"""
        import io, sys
        from coating_studio.cli import main
        p = {str(path)!r}
        for argv in (["examples", "save", "salisbury", "-o", p, "--force"], ["info", p], ["check", p],
                     ["solve", p, "--targets"], ["optimize", p, "--maxiter", "3", "--seed", "1"],
                     ["tolerance", p, "--n-samples", "5"], ["examples", "list"]):
            assert main(argv, stdout=io.StringIO(), stderr=io.StringIO()) == 0, argv
        bad = [m for m in sys.modules if m.startswith(("PySide6", "matplotlib"))]
        assert not bad, bad
    """)
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# -- same numbers as the engine / GUI ------------------------------------------------------------------------

@pytest.mark.parametrize("sweep", ["freq", "angle", "map"])
def test_solve_matches_the_engine_exactly(example, sweep):
    path = example("dualband")
    code, env, *_ = run("solve", path, "--sweep", sweep, "--pol", "TE")
    assert code == 0
    p = Project.load(path)
    sw = p.sweep
    if sweep == "freq":
        res = solve(p.structure, p.materials, sw.freq_grid(), sw.angle)
        assert env["result"]["data"]["rl_db"]["TM"] == power_to_db(res.quantity("R", "TM"))[:, 0].tolist()
    elif sweep == "angle":
        res = solve(p.structure, p.materials, [sw.f_at], sw.angle_grid())
        assert env["result"]["data"]["rl_db"]["avg"] == power_to_db(res.quantity("R", "avg"))[0, :].tolist()
    else:
        res = solve(p.structure, p.materials, sw.freq_grid(sw.map_n_f), sw.angle_grid(sw.map_n_angle))
        z = env["result"]["data"]["rl_db"]["TE"]
        assert (len(z), len(z[0])) == (sw.map_n_f, sw.map_n_angle)
        assert z == power_to_db(res.quantity("R", "TE")).tolist()


def test_salisbury_is_matched_at_its_design_frequency(example):
    code, env, *_ = run("solve", example("salisbury"), "--summary-only")
    best = env["result"]["summary"]["best"]["TE"]
    assert best["rl_db"] < -40 and best["f_hz"] == pytest.approx(10e9)


def test_solve_targets_report_margin_as_worst_minus_goal(example):
    path = example("dualband")
    code, env, *_ = run("solve", path, "--targets", "--summary-only")
    p = Project.load(path)
    terms = evaluate_terms(p)
    rows = env["result"]["targets"]
    assert [[r["worst_rl_db"], r["margin_db"]] for r in rows] == [list(t) for t in terms.per_target]
    for r in rows:
        assert r["margin_db"] == pytest.approx(r["worst_rl_db"] - r["goal_db"])
    assert env["result"]["max_margin_db"] == max(r["margin_db"] for r in rows)


def test_tolerance_matches_run_tolerance_with_gui_grid_and_band(example):
    path = example("jaumann2")
    code, env, *_ = run("tolerance", path, "--seed", "4", "--n-samples", "40")
    p = Project.load(path)
    p.tolerance.seed, p.tolerance.n_samples = 4, 40
    r = run_tolerance(p, tolerance_frequencies(p), band=yield_intervals(p))
    assert env["result"]["yield_fraction"] == r.yield_fraction
    assert env["result"]["data"]["median_db"] == r.median_db.tolist()
    assert env["warnings"][0]["code"] == "single_angle_yield"


def test_optimize_matches_a_direct_run_and_saves_the_result(example, tmp_path):
    path = example("salisbury")
    out = tmp_path / "opt.coat"
    code, env, *_ = run("optimize", path, "-o", out, "--seed", "5", "--maxiter", "15")
    assert code == 0
    p = Project.load(path)
    p.optimization.seed, p.optimization.maxiter = 5, 15
    res = optimize(p, throttle_s=0.0)
    assert env["result"]["terms"]["objective"] == res.terms.objective
    assert env["result"]["seed_used"] == 5
    q = Project.load(out)
    for v in env["result"]["values"]:
        from coating_studio.project import get_param
        assert get_param(q, v["path"]) == v["after"]["value"]


def test_csv_uses_the_gui_columns_and_formats(example):
    path = example("salisbury")
    code, env, text, _ = run("solve", path, "--format", "csv", "--quantity", "T")
    assert env is None and code == 0
    lines = text.splitlines()
    assert lines[0] == "f [GHz],T TE,T TM,T avg"
    p = Project.load(path)
    res = solve(p.structure, p.materials, p.sweep.freq_grid(), p.sweep.angle)
    first = [f"{res.f[0] / 1e9:.9g}"] + [f"{res.quantity('T', q)[0, 0]:.9g}" for q in ("TE", "TM", "avg")]
    assert lines[1] == ",".join(first)
    code, _, text, _ = run("tolerance", path, "--format", "csv", "--n-samples", "5")
    assert text.splitlines()[0] == "f [GHz],nominal [dB],median [dB],lower [dB],upper [dB]"


# -- output contract -----------------------------------------------------------------------------------------

def test_sanitize_makes_strict_json():
    data = {"a": math.nan, "b": math.inf, "c": np.float64("nan"), "d": np.int64(3), "e": np.bool_(True),
            "f": (1, 2), "g": np.array([[1.0, np.nan], [np.inf, 2.0]])}
    out = sanitize(data)
    assert out == {"a": None, "b": None, "c": None, "d": 3, "e": True, "f": [1, 2], "g": [[1.0, None], [None, 2.0]]}
    json.dumps(out, allow_nan=False)


def test_every_command_writes_one_json_object(example):
    path = example("cara")
    for argv in (["examples", "list"], ["info", path], ["check", path], ["solve", path, "--summary-only"],
                 ["optimize", path, "--maxiter", "2"], ["tolerance", path, "--n-samples", "3"]):
        code, env, text, _ = run(*argv)
        assert env is not None and text.count("\n") == 1, argv


def test_info_reports_parameters_in_si_with_display_units(example):
    code, env, *_ = run("info", example("cara"))
    params = {tuple(p["path"][2:]) if p["path"][0] == "layer" else tuple(p["path"]): p for p in env["result"]["params"]}
    by_label = {p["label"].split(": ")[-1]: p for p in env["result"]["params"]}
    th = next(p for p in env["result"]["params"] if p["path"][-1] == "thickness")
    assert th["unit"] == "m" and th["display_unit"] == "mm"
    assert th["display_value"] == pytest.approx(th["value"] * 1e3)
    lp = next(p for p in env["result"]["params"] if p["path"][-1] == "L")
    assert lp["unit"] == "H" and lp["display_unit"] == "nH" and lp["display_value"] == pytest.approx(lp["value"] * 1e9)
    assert params and by_label
    assert env["input"]["schema"] == SCHEMA_VERSION


def test_optimize_nan_terms_and_inf_progress_become_null(example):
    code, env, _, err = run("optimize", example("salisbury"), "--maxiter", "3", "--progress", "--progress-interval", "0")
    for line in err.splitlines():
        ev = json.loads(line)
        assert "history" not in ev and ev.get("stage") != "done"
    assert "NaN" not in err and "Infinity" not in err


# -- errors --------------------------------------------------------------------------------------------------

def test_file_errors_are_input_errors(tmp_path):
    cases = {}
    cases["missing"] = tmp_path / "nope.coat"
    (tmp_path / "dir.coat").mkdir()
    cases["dir"] = tmp_path / "dir.coat"
    (tmp_path / "text.coat").write_text("not json")
    cases["text"] = tmp_path / "text.coat"
    (tmp_path / "bin.coat").write_bytes(b"\xff\xfe\x00\x81")
    cases["bin"] = tmp_path / "bin.coat"
    (tmp_path / "list.coat").write_text("[1, 2]")
    cases["list"] = tmp_path / "list.coat"
    (tmp_path / "other.coat").write_text('{"app": "Other"}')
    cases["other"] = tmp_path / "other.coat"
    d = Project().to_dict()
    d["materials"] = [{"kind": "constant"}]  # no name
    (tmp_path / "broken.coat").write_text(json.dumps(d))
    cases["broken"] = tmp_path / "broken.coat"
    expected = {"missing": "file_not_found", "dir": "file_unreadable", "text": "invalid_project",
                "bin": "invalid_project", "list": "invalid_project", "other": "invalid_project",
                "broken": "invalid_project"}
    for key, path in cases.items():
        code, env, *_ = run("info", path)
        assert (code, env["error"]["code"]) == (3, expected[key]), key


def test_newer_schema(tmp_path):
    d = Project().to_dict()
    d["schema"] = SCHEMA_VERSION + 1
    path = tmp_path / "new.coat"
    path.write_text(json.dumps(d))
    code, env, *_ = run("solve", path)
    assert code == 3 and env["error"]["code"] == "newer_schema"
    assert env["error"]["details"] == {"schema": SCHEMA_VERSION + 1, "supported": SCHEMA_VERSION}


def test_out_of_range_tabulated_material(tmp_path):
    p = Project()
    f = np.linspace(4e9, 8e9, 5)
    p.add_material(TabulatedMaterial("Meas", f, np.full(5, 4.0), np.full(5, 0.2)))
    p.structure = Structure(layers=[SlabLayer("Meas", 2e-3)], backing=Backing("pec"))
    code, env, *_ = run("solve", save(p, tmp_path))
    assert code == 4 and env["error"]["code"] == "material_out_of_range"
    det = env["error"]["details"]
    assert det["data_lo_hz"] == 4e9 and det["data_hi_hz"] == 8e9 and det["req_lo_hz"] == p.sweep.f_min


def test_cyclic_mixture(tmp_path):
    p = Project()
    p.add_material(MixtureMaterial("A", "Epoxy", "B", 0.2))
    p.add_material(MixtureMaterial("B", "Epoxy", "A", 0.2))
    p.structure = Structure(layers=[SlabLayer("A", 2e-3)], backing=Backing("pec"))
    path = save(p, tmp_path)
    code, env, *_ = run("solve", path)
    assert code == 4 and env["error"]["code"] == "material_cycle"
    code, env, *_ = run("check", path)
    assert code == 4 and env["error"]["code"] == "validation_failed"
    assert "material_cycle" in {i["code"] for i in env["result"]["issues"]}


def test_optimize_without_variables_and_with_a_missing_choice_layer(example, tmp_path):
    code, env, *_ = run("optimize", example("salisbury"), "--maxiter", "2")
    assert code == 0
    p = Project()
    p.structure = Structure(layers=[SlabLayer("Epoxy", 1e-3)], backing=Backing("pec"))
    code, env, *_ = run("optimize", save(p, tmp_path))
    assert code == 4 and env["error"]["code"] == "invalid_optimization_settings"
    from coating_studio.project import MaterialChoice
    p.optimization.choices = [MaterialChoice("ghost-uid", ["Epoxy"])]
    code, env, *_ = run("optimize", save(p, tmp_path, "q.coat"))
    assert code == 4 and env["error"]["code"] == "invalid_optimization_settings"


def test_usage_help_and_existing_output(example, tmp_path):
    code, env, *_ = run("solve", "--bogus")
    assert code == 2 and env["error"]["code"] == "usage"
    out = io.StringIO()
    assert main(["--help"], stdout=out, stderr=io.StringIO()) == 0
    path = example("salisbury")
    target = tmp_path / "exists.coat"
    target.write_text("x")
    code, env, *_ = run("optimize", path, "-o", target, "--maxiter", "2")
    assert code == 3 and env["error"]["code"] == "file_exists"
    code, env, *_ = run("examples", "save", "nope", "-o", tmp_path / "n.coat")
    assert code == 3 and env["error"]["code"] == "unknown_example"


# -- check -----------------------------------------------------------------------------------------------------

def test_check_default_project_without_variables_is_valid(tmp_path):
    p = Project()
    p.structure = Structure(layers=[SlabLayer("Carbon / epoxy", 2e-3)], backing=Backing("pec"))
    code, env, *_ = run("check", save(p, tmp_path))
    assert code == 0 and env["result"]["valid"]
    # constituents of the mixture are checked too (demo-value notes for Epoxy and Carbon black)
    mats = {i["material"] for i in env["result"]["issues"] if i["code"] == "demo_values"}
    assert {"Epoxy", "Carbon black"} <= mats


def test_check_reports_trial_solve_errors(tmp_path):
    p = Project()
    p.add_material(MixtureMaterial("Lossy air", "Air", "Carbon black", 0.1))
    p.structure = Structure(incident="Lossy air", layers=[SlabLayer("Epoxy", 1e-3)], backing=Backing("pec"))
    code, env, *_ = run("check", save(p, tmp_path))
    assert code == 4
    assert any(i["code"] == "solver_error" for i in env["result"]["issues"])
    keys = [(i["code"], i["material"], i["message"]) for i in env["result"]["issues"]]
    assert len(keys) == len(set(keys))


# -- cancellation ----------------------------------------------------------------------------------------------

def test_stop_event_returns_partial_results(example):
    path = example("dualband")
    ctl = RunControl(command="optimize")
    ctl.stop_event.set()
    code, env, *_ = run("optimize", path, control=ctl)
    assert code == 5 and env["stopped"] and env["result"]["terms"] is not None
    ctl = RunControl(command="tolerance")
    ctl.stop_event.set()
    code, env, *_ = run("tolerance", path, "--n-samples", "50", control=ctl)
    assert code == 5 and env["stopped"] and env["result"]["n_samples"] < 50


def test_timeout_stops_a_fast_optimisation(example):
    code, env, *_ = run("optimize", example("dualband"), "--timeout", "0.001", "--maxiter", "500")
    assert code == 5 and env["stopped"] and env["result"]["message"] == "stopped by timeout"


def test_tolerance_finishing_exactly_at_the_deadline_is_not_stopped(example):
    ctl = RunControl(command="tolerance")
    cb = ctl.tolerance_callback()
    ctl.stop_event.set()
    assert cb(10, 10) is False and cb(9, 10) is True


def test_signal_handlers_are_restored(example):
    before = signal.getsignal(signal.SIGINT)
    run("tolerance", example("salisbury"), "--n-samples", "3")
    assert signal.getsignal(signal.SIGINT) is before


def test_negative_seed_means_random_and_is_reported(example):
    path = example("salisbury")
    for cmd in (["optimize", path, "--maxiter", "2"], ["tolerance", path, "--n-samples", "3"]):
        code, env, *_ = run(*cmd, "--seed", "-1")
        assert code == 0 and isinstance(env["result"]["seed_used"], int) and env["result"]["seed_used"] >= 0
