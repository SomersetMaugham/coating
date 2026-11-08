"""L and C from grid dimensions, against the formulas of Luukkonen et al. (IEEE TAP 2008) they come from."""
import io
import json
import math

import numpy as np
import pytest

from coating_studio.cli import main
from coating_studio.core import ETA0, SheetLayer
from coating_studio.core.constants import C0
from coating_studio.core.structure import infer_angle_preset
from coating_studio.examples import EXAMPLES
from coating_studio.fss import apply_to_sheet, grid_element
from coating_studio.project import Project

D, W, EPS = 5e-3, 0.5e-3, 2.2
F = np.array([1e9, 3.7e9, 10e9, 24e9])


def alpha(f, eps=EPS):
    return 2 * np.pi * f / C0 * np.sqrt(eps) * D / np.pi * np.log(1 / np.sin(np.pi * W / (2 * D)))


def test_mesh_inductance_gives_equation_6_at_every_frequency():
    el = grid_element("mesh", D, W, EPS)
    eta = ETA0 / np.sqrt(EPS)
    assert 1j * 2 * np.pi * F * el.L == pytest.approx(1j * eta / 2 * alpha(F), rel=1e-12)
    assert el.C is None and el.angle == {"L_TM": pytest.approx(-1 / (2 * EPS))}


def test_mesh_inductance_does_not_depend_on_the_permittivity():
    assert grid_element("mesh", D, W, 1.0).L == pytest.approx(grid_element("mesh", D, W, 9.0).L, rel=1e-14)


def test_patch_capacitance_gives_equation_8_at_every_frequency():
    el = grid_element("patch", D, W, EPS)
    eta = ETA0 / np.sqrt(EPS)
    assert 1 / (1j * 2 * np.pi * F * el.C) == pytest.approx(-1j * eta / (2 * alpha(F)), rel=1e-12)
    assert el.L is None and el.angle == {"C_TE": pytest.approx(-1 / (2 * EPS))}


def test_narrow_width_approximation():
    w = 1e-6
    exact = grid_element("mesh", D, w, 1.0).L
    assert exact == pytest.approx(4e-7 * D / 2 * math.log(2 * D / (math.pi * w)), rel=1e-6)


@pytest.mark.parametrize("args", [(D, D, 1.0), (D, 2 * D, 1.0), (D, 0.0, 1.0), (D, -W, 1.0), (0.0, W, 1.0),
                                  (D, W, 0.5), (D, W, float("nan")), (float("inf"), W, 1.0)])
@pytest.mark.parametrize("pattern", ["mesh", "patch"])
def test_bad_dimensions_are_refused(pattern, args):
    with pytest.raises(ValueError):
        grid_element(pattern, *args)


def test_unknown_pattern_is_refused():
    with pytest.raises(ValueError, match="pattern"):
        grid_element("strips", D, W, 1.0)


@pytest.mark.parametrize("pattern", ["mesh", "patch"])
def test_a_width_that_rounds_to_the_period_is_refused(pattern):
    with pytest.raises(ValueError, match="too close"):
        grid_element(pattern, 1.0, 1 - 1e-12, 1.0)


def test_limits_scale_with_the_lattice():
    el = grid_element("mesh", D, W, EPS)
    scale = C0 / (D * math.sqrt(EPS))
    assert el.limit_hz == pytest.approx(0.5 * scale) and el.caution_hz == pytest.approx(0.3 * scale)


@pytest.mark.parametrize("eps_r", [1.0, 1.5, 2.2, 4.0, 10.0, 100.0])
@pytest.mark.parametrize("sin_t", [0.0, 0.5, 0.999])
def test_the_limit_is_below_every_grating_lobe_on_a_substrate(eps_r, sin_t):
    limit = grid_element("mesh", D, W, (eps_r + 1) / 2).limit_hz
    assert limit <= C0 / (D * (math.sqrt(eps_r) + sin_t)) * (1 + 1e-12)
    assert limit <= C0 / (D * (1 + sin_t)) * (1 + 1e-12)


def test_width_ratio_warning_boundary():
    assert not grid_element("mesh", 1.0, 0.5, 1.0).wide and grid_element("mesh", 1.0, 0.500001, 1.0).wide


def _sheet(model="rlc"):
    s = SheetLayer(250.0, model=model, L=5e-9, C=0.05e-12)
    s.set_angle({"L_TE": 0.1, "L_TM": 0.2, "C_TE": 0.3, "C_TM": 0.4})
    return s


@pytest.mark.parametrize("model", ["rlc", "parallel_rlc"])
def test_by_default_the_sheet_becomes_a_pure_mesh(model):
    s, el = _sheet(model), grid_element("mesh", D, W, EPS)
    apply_to_sheet(s, el)
    assert (s.R, s.L, s.C) == (250.0, el.L, None)
    assert s.angle_dict() == {"L_TE": 0.0, "L_TM": el.angle["L_TM"], "C_TE": 0.0, "C_TM": 0.0}
    assert infer_angle_preset(s) == ("mesh", pytest.approx(EPS))


@pytest.mark.parametrize("model", ["rlc", "parallel_rlc"])
def test_by_default_the_sheet_becomes_a_pure_patch(model):
    s, el = _sheet(model), grid_element("patch", D, W, EPS)
    apply_to_sheet(s, el)
    assert (s.R, s.L, s.C) == (250.0, 0.0, el.C)
    assert s.angle_dict() == {"L_TE": 0.0, "L_TM": 0.0, "C_TE": el.angle["C_TE"], "C_TM": 0.0}
    assert infer_angle_preset(s) == ("patch", pytest.approx(EPS))


def test_keeping_the_other_element_keeps_only_its_values():
    s, el = _sheet(), grid_element("mesh", D, W, EPS)
    apply_to_sheet(s, el, keep_other=True)
    assert (s.L, s.C) == (el.L, 0.05e-12)
    assert s.angle_dict() == {"L_TE": 0.0, "L_TM": el.angle["L_TM"], "C_TE": 0.3, "C_TM": 0.4}
    s, el = _sheet(), grid_element("patch", D, W, EPS)
    apply_to_sheet(s, el, keep_other=True)
    assert (s.L, s.C) == (5e-9, el.C)
    assert s.angle_dict() == {"L_TE": 0.1, "L_TM": 0.2, "C_TE": el.angle["C_TE"], "C_TM": 0.0}


def run(*argv):
    out = io.StringIO()
    code = main([str(a) for a in argv], stdout=out, stderr=io.StringIO())
    return code, json.loads(out.getvalue())


def test_cli_matches_the_engine():
    code, env = run("fss-grid", "--pattern", "patch", "--period-mm", 5, "--gap-mm", 0.5, "--eps-eff", 2.2)
    assert code == 0 and env["input"] is None
    r, el = env["result"], grid_element("patch", 5 * 1e-3, 0.5 * 1e-3, 2.2)
    assert (r["L_h"], r["C_f"], r["dense_limit_hz"], r["caution_limit_hz"]) == (None, el.C, el.limit_hz, el.caution_hz)
    assert (r["period_m"], r["width_m"], r["eps_eff"], r["angle"]) == (el.period, el.width, 2.2, el.angle)
    assert r["sheet"] == {"L_nh": 0.0, "C_pf": pytest.approx(el.C * 1e12), "angle": el.angle}
    assert r["assumptions"] and env["warnings"] == []


def test_cli_mesh_removes_the_capacitor_in_its_fragment():
    code, env = run("fss-grid", "--pattern", "mesh", "--period-mm", 5, "--strip-width-mm", 0.5, "--eps-eff", 1)
    assert code == 0
    assert env["result"]["sheet"]["C_pf"] is None and env["result"]["sheet"]["L_nh"] > 0
    assert env["result"]["C_f"] is None and env["result"]["L_h"] > 0


@pytest.mark.parametrize("argv", [["--pattern", "mesh", "--period-mm", 5, "--gap-mm", 0.5, "--eps-eff", 1],
                                  ["--pattern", "patch", "--period-mm", 5, "--strip-width-mm", 0.5, "--eps-eff", 1],
                                  ["--pattern", "mesh", "--period-mm", 5, "--strip-width-mm", 6, "--eps-eff", 1],
                                  ["--pattern", "mesh", "--period-mm", 5, "--strip-width-mm", 0.5, "--eps-eff", 0.5],
                                  ["--pattern", "mesh", "--period-mm", 5, "--eps-eff", 1],
                                  ["--pattern", "mesh", "--strip-width-mm", 0.5, "--eps-eff", 1],
                                  ["--pattern", "mesh", "--period-mm", 5, "--strip-width-mm", 0.5]])
def test_cli_refuses_wrong_or_missing_values(argv):
    code, env = run("fss-grid", *argv)
    assert code == 2 and env["error"]["code"] == "usage"


def test_cli_warns_about_a_wide_geometry():
    _, env = run("fss-grid", "--pattern", "patch", "--period-mm", 5, "--gap-mm", 4, "--eps-eff", 1)
    assert [w["code"] for w in env["warnings"]] == ["wide_geometry"]


def test_the_fragment_merges_into_a_design_spec(tmp_path):
    p = EXAMPLES["cara"][1]()
    src = tmp_path / "a.coat"
    p.save(src)
    spec = tmp_path / "a.json"
    run("spec", src, "-o", spec)
    d = json.loads(spec.read_text(encoding="utf-8"))
    d["variables"] = []
    _, env = run("fss-grid", "--pattern", "patch", "--period-mm", 5, "--gap-mm", 0.5, "--eps-eff", 2.2)
    d["layers"][0]["sheet"].update(env["result"]["sheet"])
    spec.write_text(json.dumps(d), encoding="utf-8")
    code, built = run("build", spec, "-o", tmp_path / "b.coat", "--force")
    assert code == 0, built
    s = Project.load(tmp_path / "b.coat").structure.layers[0]
    assert s.L == 0.0 and s.C == pytest.approx(env["result"]["C_f"]) and s.a_c_te == env["result"]["angle"]["C_TE"]
