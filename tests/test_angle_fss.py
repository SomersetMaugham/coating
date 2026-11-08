"""Angle-dependent RLC sheets, checked against the grid-impedance formulas of Luukkonen et al. (IEEE TAP 2008)."""
import io
import json
import math

import numpy as np
import pytest

from coating_studio.cli import main
from coating_studio.core import ETA0, Backing, SheetLayer, SlabLayer, Structure, solve
from coating_studio.core.constants import C0
from coating_studio.core.solver import SolverError
from coating_studio.core.structure import angle_preset_coeffs, infer_angle_preset, layer_from_dict, parse_angle
from coating_studio.examples import EXAMPLES
from coating_studio.materials import ConstantMaterial, TabulatedMaterial
from coating_studio.project import SCHEMA_VERSION, Project
from coating_studio.report import build_report

D, W, EPS_EFF = 3e-3, 0.4e-3, 2.2
F = np.linspace(2e9, 18e9, 7)
ANGLES = [0.0, 25.0, 50.0, 70.0]
MATS = {"Air": ConstantMaterial("Air", 1.0, 0.0)}


def alpha(f):
    k_eff = 2 * np.pi * f / C0 * np.sqrt(EPS_EFF)
    return k_eff * D / np.pi * np.log(1 / np.sin(np.pi * W / (2 * D)))


ETA_EFF = ETA0 / np.sqrt(EPS_EFF)
L_MESH = float(ETA_EFF / 2 * alpha(1e9) / (2 * np.pi * 1e9))  # j eta_eff alpha / 2 = j w L, independent of f
C_PATCH = float(2 * alpha(1e9) / ETA_EFF / (2 * np.pi * 1e9))  # -j eta_eff / (2 alpha) = 1 / (j w C)


def sheet(model="rlc", L=L_MESH, C=None, R=1e-3, preset="mesh", eps_eff=EPS_EFF):
    s = SheetLayer(R, model=model, L=L, C=C)
    s.set_angle(angle_preset_coeffs(preset, eps_eff))
    return s


def closed_form(zs, theta, pol, n=1.0):
    c = np.cos(np.deg2rad(theta))
    z = ETA0 / (n * c) if pol == "TE" else ETA0 * c / n
    return -z / (2 * zs + z)


def gamma(s, f=F, angles=ANGLES, mats=MATS, medium="Air"):
    st = Structure([s], backing=Backing("halfspace", medium), incident=medium)
    return solve(st, mats, f, angles)


@pytest.mark.parametrize("pol", ["TE", "TM"])
def test_metal_mesh_follows_equations_5_and_6(pol):
    r = gamma(sheet())
    for j, th in enumerate(ANGLES):
        scale = 1 - np.sin(np.deg2rad(th)) ** 2 / (2 * EPS_EFF) if pol == "TM" else 1.0
        zg = 1j * ETA_EFF / 2 * alpha(F) * scale + 1e-3
        assert r.pol[pol].gamma[:, j] == pytest.approx(closed_form(zg, th, pol), rel=1e-12)


@pytest.mark.parametrize("pol", ["TE", "TM"])
def test_patch_array_follows_equations_8_and_9(pol):
    r = gamma(sheet(L=0.0, C=C_PATCH, preset="patch"))
    for j, th in enumerate(ANGLES):
        scale = 1 - np.sin(np.deg2rad(th)) ** 2 / (2 * EPS_EFF) if pol == "TE" else 1.0
        zg = -1j * ETA_EFF / (2 * alpha(F) * scale) + 1e-3
        assert r.pol[pol].gamma[:, j] == pytest.approx(closed_form(zg, th, pol), rel=1e-12)


@pytest.mark.parametrize("model", ["rlc", "parallel_rlc"])
def test_zero_coefficients_match_the_angle_independent_sheet_exactly(model):
    a = SheetLayer(120.0, model=model, L=3e-9, C=0.1e-12)
    b = SheetLayer(120.0, model=model, L=3e-9, C=0.1e-12)
    b.set_angle({"L_TM": 0.0})
    x = solve(Structure([a, SlabLayer("Air", 4e-3)], backing=Backing("pec")), MATS, F, ANGLES)
    y = solve(Structure([b, SlabLayer("Air", 4e-3)], backing=Backing("pec")), MATS, F, ANGLES)
    for pol in ("TE", "TM"):
        assert np.array_equal(x.pol[pol].gamma, y.pol[pol].gamma)


@pytest.mark.parametrize("key,pol", [("L_TE", "TE"), ("L_TM", "TM"), ("C_TE", "TE"), ("C_TM", "TM")])
def test_a_coefficient_acts_only_on_its_polarisation(key, pol):
    base = SheetLayer(100.0, model="rlc", L=3e-9, C=0.1e-12)
    moved = SheetLayer(100.0, model="rlc", L=3e-9, C=0.1e-12)
    moved.set_angle({key: -0.3})
    other = "TM" if pol == "TE" else "TE"
    a, b = gamma(base), gamma(moved)
    assert np.array_equal(a.pol[other].gamma, b.pol[other].gamma)
    assert np.array_equal(a.pol[pol].gamma[:, 0], b.pol[pol].gamma[:, 0])  # no effect at normal incidence
    assert not np.allclose(a.pol[pol].gamma[:, 1:], b.pol[pol].gamma[:, 1:])


@pytest.mark.parametrize("n_f,n_a", [(7, 4), (5, 5), (1, 4), (6, 1)])
@pytest.mark.parametrize("model", ["rlc", "parallel_rlc"])
def test_every_grid_shape_gives_each_point_its_own_angle(model, n_f, n_a):
    s = SheetLayer(150.0, model=model, L=3e-9, C=0.1e-12)
    s.set_angle({"L_TM": -0.3, "C_TE": -0.2, "L_TE": 0.1, "C_TM": 0.05})
    f, th = np.linspace(3e9, 15e9, n_f), np.linspace(0, 60, n_a)
    st = Structure([s, SlabLayer("Air", 4e-3)], backing=Backing("pec"))
    grid = solve(st, MATS, f, th)
    for pol in ("TE", "TM"):
        assert grid.pol[pol].gamma.shape == (n_f, n_a)
        for i in range(n_f):
            for j in range(n_a):
                one = solve(st, MATS, [f[i]], th[j]).pol[pol].gamma[0, 0]
                assert grid.pol[pol].gamma[i, j] == pytest.approx(one, rel=1e-13)


def test_a_dispersive_incident_medium_sets_s2_at_each_frequency():
    f = np.array([4e9, 8e9, 12e9])
    n2 = np.array([2.0, 3.0, 4.0])
    med = TabulatedMaterial("Med", f, n2, np.zeros(3))
    s = SheetLayer(100.0, model="rlc", L=3e-9, C=None)
    s.set_angle({"L_TE": -0.1})
    th = 30.0
    r = gamma(s, f, [th], {"Med": med}, "Med")
    zs = 100.0 + 1j * 2 * np.pi * f * 3e-9 * (1 - 0.1 * n2 * np.sin(np.deg2rad(th)) ** 2)
    n = np.sqrt(n2)
    z = ETA0 / np.sqrt(n2 - n2 * np.sin(np.deg2rad(th)) ** 2)
    assert r.pol["TE"].gamma[:, 0] == pytest.approx(-z / (2 * zs + z), rel=1e-12) and n[0] > 1


def test_an_inactive_element_is_not_checked():
    assert gamma(sheet(L=0.0, C=C_PATCH, preset="patch")).pol["TE"].gamma.size
    assert gamma(sheet()).pol["TM"].gamma.size
    s = SheetLayer(100.0, model="rlc", L=0.0, C=1e-13)
    s.set_angle({"L_TM": -5.0})  # would be negative if L existed
    assert gamma(s).pol["TM"].gamma.size


@pytest.mark.parametrize("key", ["L_TM", "C_TE"])
def test_a_non_positive_element_is_refused(key):
    s = SheetLayer(100.0, model="rlc", L=3e-9, C=1e-13)
    s.set_angle({key: -2.0})
    with pytest.raises(SolverError, match="non-positive"):
        gamma(s)


def test_a_non_finite_coefficient_is_refused():
    s = SheetLayer(100.0, model="rlc", L=3e-9, C=None)
    s.a_l_tm = float("nan")
    with pytest.raises(SolverError):
        gamma(s)


@pytest.mark.parametrize("model", ["rlc", "parallel_rlc"])
def test_energy_balance_at_oblique_incidence(model):
    lossy = ConstantMaterial("Lossy", 4.0, 0.8, 1.5, 0.3)
    s = SheetLayer(300.0, model=model, L=4e-9, C=0.06e-12)
    s.set_angle({"L_TM": -0.25, "C_TE": -0.25})
    res = solve(Structure([s, SlabLayer("Lossy", 2e-3)], backing=Backing("halfspace", "Air")),
                {**MATS, "Lossy": lossy}, np.linspace(1e9, 25e9, 40), [0, 30, 70])
    for pol in ("TE", "TM"):
        r = res.pol[pol]
        assert np.allclose(r.R + r.T + r.A_layers.sum(axis=0), 1.0, atol=1e-12)
        assert np.all(r.A_layers[0] > 0)


def test_parallel_sheet_is_still_three_shunts_at_oblique_incidence():
    R, L, C, f, th = 300.0, 4e-9, 0.06e-12, 7e9, 40.0
    w = 2 * np.pi * f
    s2 = np.sin(np.deg2rad(th)) ** 2
    one = SheetLayer(R, model="parallel_rlc", L=L, C=C)
    one.set_angle({"L_TM": -0.2, "C_TM": -0.3})
    three = [SheetLayer(R), SheetLayer(0.0, w * L * (1 - 0.2 * s2)), SheetLayer(0.0, -1 / (w * C * (1 - 0.3 * s2)))]
    a = solve(Structure([one, SlabLayer("Air", 5e-3)], backing=Backing("pec")), MATS, [f], [th], pols=("TM",))
    b = solve(Structure([*three, SlabLayer("Air", 5e-3)], backing=Backing("pec")), MATS, [f], [th], pols=("TM",))
    assert a.pol["TM"].gamma == pytest.approx(b.pol["TM"].gamma, rel=1e-12)


def test_a_tolerance_factor_combines_with_the_angle():
    s = SheetLayer(100.0, model="rlc", L=3e-9, C=None)
    s.set_angle({"L_TM": -0.25})
    th = 40.0
    r = solve(Structure([s], backing=Backing("halfspace", "Air")), MATS, F, [th], perturb={s.uid: {"sheet_L": 1.2}})
    zs = 100.0 + 1j * 2 * np.pi * F * 3e-9 * 1.2 * (1 - 0.25 * np.sin(np.deg2rad(th)) ** 2)
    assert r.pol["TM"].gamma[:, 0] == pytest.approx(closed_form(zs, th, "TM"), rel=1e-12)


def test_presets_round_trip():
    for preset, eps in (("mesh", 2.2), ("patch", 1.0), ("mesh", 1.0), ("patch", 37.5)):
        s = SheetLayer(10.0, model="rlc", L=1e-9, C=1e-13)
        s.set_angle(angle_preset_coeffs(preset, eps))
        got, e = infer_angle_preset(s)
        assert got == preset and e == pytest.approx(eps)


def test_other_coefficients_are_custom():
    s = SheetLayer(10.0, model="rlc", L=1e-9, C=1e-13)
    assert infer_angle_preset(s) == ("none", None)
    for d in ({"L_TE": -0.1}, {"L_TM": 0.1}, {"L_TM": -0.6}, {"L_TM": -0.2, "C_TE": -0.2}):
        s.set_angle(d)
        assert infer_angle_preset(s) == ("custom", None)


def _project():
    p = EXAMPLES["cara"][1]()
    sh = p.structure.layers[0]
    sh.set_angle({"L_TM": -0.25, "C_TE": -0.1})
    return p, sh


def test_file_round_trip_and_schema():
    p, sh = _project()
    d = json.loads(json.dumps(p.to_dict()))
    assert d["schema"] == SCHEMA_VERSION == 8
    assert d["structure"]["layers"][0]["angle"] == {"L_TE": 0.0, "L_TM": -0.25, "C_TE": -0.1, "C_TM": 0.0}
    assert Project.from_dict(d).structure.layers[0].angle_dict() == sh.angle_dict()


def test_schema_7_files_load_without_angle_and_constant_sheets_stay_unchanged():
    p = EXAMPLES["cara"][1]()
    d = json.loads(json.dumps(p.to_dict()))
    assert "angle" not in d["structure"]["layers"][0]
    d["schema"] = 7
    q = Project.from_dict(d)
    assert q.structure.layers[0].angle_dict() is None and q.source_schema == 7
    assert "angle" not in EXAMPLES["salisbury"][1]().to_dict()["structure"]["layers"][0]


@pytest.mark.parametrize("bad", [{"L_te": 0.1}, "x", {"L_TM": True}, {"L_TM": float("nan")}, {"L_TM": float("inf")}, {"C_TE": "a"}])
def test_malformed_coefficients_are_rejected(bad):
    with pytest.raises(ValueError):
        parse_angle(bad)
    with pytest.raises(ValueError):
        layer_from_dict({"kind": "sheet", "R": 1.0, "model": "rlc", "angle": bad})


def test_constant_sheet_has_no_angle():
    s = SheetLayer(100.0)
    s.set_angle({"L_TM": -0.2})
    assert not s.has_angle and s.angle_dict() is None and "angle" not in s.to_dict()


def run(*argv):
    out = io.StringIO()
    code = main([str(a) for a in argv], stdout=out, stderr=io.StringIO())
    return code, json.loads(out.getvalue())


def test_spec_and_info_round_trip(tmp_path):
    p, sh = _project()
    src = tmp_path / "a.coat"
    p.save(src)
    assert run("info", src)[1]["result"]["layers"][0]["angle"] == sh.angle_dict()
    spec = tmp_path / "a.json"
    assert run("spec", src, "-o", spec)[0] == 0
    code, env = run("build", spec, "-o", tmp_path / "b.coat")
    assert code == 0, env
    assert Project.load(tmp_path / "b.coat").structure.layers[0].angle_dict() == sh.angle_dict()


def test_info_is_null_without_an_angle_dependence(tmp_path):
    src = tmp_path / "a.coat"
    EXAMPLES["salisbury"][1]().save(src)
    assert run("info", src)[1]["result"]["layers"][0]["angle"] is None


def _bad_spec(tmp_path, angle, model=None):
    p, _ = _project()
    src = tmp_path / "a.coat"
    p.save(src)
    spec = tmp_path / "a.json"
    run("spec", src, "-o", spec)
    d = json.loads(spec.read_text(encoding="utf-8"))
    d["layers"][0]["sheet"]["angle"] = angle
    if model:
        d["layers"][0]["sheet"]["model"] = model
    spec.write_text(json.dumps(d), encoding="utf-8")
    return run("build", spec, "-o", tmp_path / "b.coat")


def test_spec_rejects_bad_angles(tmp_path):
    code, env = _bad_spec(tmp_path, {"L_te": 0.1})
    assert code == 3 and "unknown angle" in env["error"]["message"]
    code, env = _bad_spec(tmp_path, {"L_TM": -0.1}, "constant")
    assert code == 3 and "only RLC" in env["error"]["message"]


def test_check_finds_a_problem_that_only_appears_away_from_the_sweep_angle(tmp_path):
    p, sh = _project()
    sh.set_angle({"L_TM": -3.0})
    p.sweep.angle = 0.0
    src = tmp_path / "a.coat"
    p.save(src)
    code, env = run("check", src)
    assert env["result"]["valid"] is False
    assert any(i["code"] == "solver_error" and "non-positive" in i["message"] for i in env["result"]["issues"])


def test_report_lists_the_coefficients():
    p, _ = _project()
    assert "angle coefficients: L_TM -0.25, C_TE -0.1" in build_report(p)


def test_no_coefficient_is_an_optimisation_parameter():
    from coating_studio.project import available_params
    p, sh = _project()
    attrs = {x[0][2] for x in available_params(p) if x[0][:2] == ("layer", sh.uid)}
    assert not {a for a in attrs if a.startswith("a_")} and math.isfinite(sh.a_l_tm)
