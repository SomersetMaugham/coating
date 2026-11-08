"""Filler inversion: the analytic rules, the checks that refuse bad data, the CLI command and its provenance."""
import io
import json
import os

import numpy as np
import pytest

from coating_studio.cli import main
from coating_studio.core.structure import SlabLayer
from coating_studio.limits import _conductive, inversion_provenance, mixture_range_issues
from coating_studio.materials.csvio import load_csv, to_csv_text
from coating_studio.materials.inversion import (
    invert_filler, invert_rule, mix, prediction_checks, provenance_note, rms_relative, validation_errors,
)
from coating_studio.materials.models import ConstantMaterial, MixtureMaterial, TabulatedMaterial
from coating_studio.project import Project

F = np.linspace(1e9, 18e9, 171)
EM = (3 - 0.03j) * np.ones_like(F, dtype=complex)
MM = np.ones_like(F, dtype=complex)
EI = (30 - 5j) * np.ones_like(F, dtype=complex)
MI = 1 + 20 / (1 + 1j * F / 2e9)
MODELS = ("maxwell_garnett", "bruggeman")
CONDUCTIVE = 20 - 1j * 1e3 / (2 * np.pi * F * 8.854e-12)


def composite(phi, model="maxwell_garnett", ei=EI):
    return mix(EM, ei, phi, model), mix(MM, MI, phi, model)


def run(*argv):
    out = io.StringIO()
    code = main([str(a) for a in argv], stdout=out, stderr=io.StringIO())
    return code, json.loads(out.getvalue())


def write(tmp_path, name, eps, mu, f=F):
    p = tmp_path / name
    p.write_text(to_csv_text(f, eps, mu), encoding="utf-8")
    return p


def invert_args(comp, out, model="maxwell_garnett", phi=0.2):
    return ("invert-filler", comp, "-o", out, "--model", model, "--fraction", phi, "--density-filler", 7800,
            "--matrix-eps", 3, 0.03)


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("phi", [0.05, 0.2, 0.3])
def test_inversion_recovers_the_filler(model, phi):
    e, m = composite(phi, model)
    r = invert_filler(F, e, m, EM, MM, phi, model)
    assert r.ok and r.roundtrip_max < 1e-12
    assert np.max(np.abs(r.eps.value - EI) / np.abs(EI)) < 1e-10
    assert np.max(np.abs(r.mu.value - MI) / np.abs(MI)) < 1e-10


@pytest.mark.parametrize("model", MODELS)
def test_a_mixture_of_the_table_reproduces_the_composite(model):
    e, m = composite(0.2, model)
    r = invert_filler(F, e, m, EM, MM, 0.2, model)
    mats = {"m": ConstantMaterial("m", 3, 0.03), "f": r.to_tabulated("f", 7800.0)}
    got_e, got_m = MixtureMaterial("x", "m", "f", 0.2, model).eps_mu(F, mats.__getitem__)
    assert np.max(np.abs(got_e - e) / np.abs(e)) < 1e-12 and np.max(np.abs(got_m - m) / np.abs(m)) < 1e-12
    mid = (F[:-1] + F[1:]) / 2  # between the grid points, where the table interpolates
    between, _ = MixtureMaterial("x", "m", "f", 0.2, model).eps_mu(mid, mats.__getitem__)
    assert np.max(np.abs(between - mix(EM[0], EI[0], 0.2, model)) / np.abs(between)) < 1e-9


@pytest.mark.parametrize("model", MODELS)
def test_amplification_matches_a_numerical_derivative(model):
    e, em, phi = np.array([5 - 1j]), np.array([3 - 0.03j]), 0.2
    h = 1e-6
    fd = (invert_rule(e + h, em, phi, model)[0] - invert_rule(e - h, em, phi, model)[0]) / (2 * h)
    r = invert_filler(F[:1], e, np.ones(1), em, np.ones(1), phi, model)
    assert r.eps.amplification[0] == pytest.approx(abs(fd[0]) * abs(e[0]) / abs(r.eps.value[0]), rel=1e-7)


def test_a_channel_equal_to_the_matrix_is_lossless_and_not_ill_conditioned():
    e, _ = composite(0.02)
    r = invert_filler(F, e, MM, EM, MM, 0.02, "maxwell_garnett")  # mu = 1 everywhere: kappa would be 1/phi = 50
    assert np.array_equal(r.mu.value, np.ones_like(F, dtype=complex)) and r.gain_points == 0
    assert np.all(r.mu.amplification == 0) and r.amplification_stats()["mu"] == {"median": None, "max": None}


def test_data_beyond_the_screening_limit_is_refused():
    """Bruggeman data read with Maxwell-Garnett: no gain and a perfect round trip, yet Re beta > 1."""
    e, m = composite(0.3, "bruggeman", CONDUCTIVE)
    r = invert_filler(F, e, m, EM, MM, 0.3, "maxwell_garnett")
    assert r.outside_model_points == F.size and not r.ok


def test_gain_is_refused_and_clamped_only_where_the_real_part_stays_positive():
    e, m = composite(0.1)
    e = e.copy()
    e[10] = e[10].real + 0.15j  # noise large enough to flip the loss of a low-loss filler
    r = invert_filler(F, e, m, EM, MM, 0.1, "maxwell_garnett")
    assert r.gain_points == 1 and r.clampable_points == 1 and not r.ok
    c = invert_filler(F, e, m, EM, MM, 0.1, "maxwell_garnett", clamp_nonpassive=True)
    assert c.ok and c.clamped_points == 1 and c.eps.value[10].imag == 0 and c.eps.value[10].real > 0


def test_a_point_whose_real_part_flipped_is_never_clamped():
    """Inside the model (Re beta < 1) but Re < 0: clamping it would put a pole between the grid points of the table."""
    beta, phi = 0.9 + 0.9j, 0.1
    em = EM[:2]
    eff = em * (1 + 2 * phi * beta) / (1 - phi * beta)
    r = invert_filler(F[:2], eff, np.ones(2), em, np.ones(2), phi, "maxwell_garnett", clamp_nonpassive=True)
    assert np.all(r.eps.value.real < 0) and r.outside_model_points == 0
    assert r.gain_points == 2 and r.clamped_points == 0 and r.clampable_points == 0 and not r.ok


def test_another_bruggeman_root_is_refused():
    """No gain and inside the model, but the forward rule returns the other root of its quadratic."""
    eff = np.array([-0.0004576382630187988 - 2.113608007824406j])
    r = invert_filler(F[:1], eff, np.ones(1), EM[:1], np.ones(1), 0.5, "bruggeman")
    assert r.gain_points == 0 and r.outside_model_points == 0 and r.branch_points == 1 and not r.ok


@pytest.mark.parametrize("phi", [0.0, 1.0, -0.1, 1.5])
def test_fraction_must_be_inside_zero_and_one(phi):
    with pytest.raises(ValueError):
        invert_filler(F, *composite(0.2), EM, MM, phi, "bruggeman")


def test_cli_matches_the_engine_and_writes_a_usable_table(tmp_path):
    e, m = composite(0.2)
    comp = write(tmp_path, "comp.csv", e, m)
    e30, m30 = composite(0.3)
    val = write(tmp_path, "comp30.csv", e30, m30)
    out = tmp_path / "filler.csv"
    code, env = run(*invert_args(comp, out), "--validate", val, 0.3)
    assert code == 0, env
    res = env["result"]
    loaded = load_csv(out, density=res["material"]["density"])
    measured = load_csv(comp)
    eps, mu = measured.eps_mu(measured.f, None)
    direct = invert_filler(measured.f, eps, mu, EM, MM, 0.2, "maxwell_garnett")
    assert res["amplification"] == direct.amplification_stats() and res["roundtrip_max"] == direct.roundtrip_max
    assert res["prediction"] == prediction_checks(direct, eps, mu, EM, MM)
    assert np.allclose(loaded.eps_mu(F, None)[0], direct.eps.value, rtol=1e-8)
    table30 = load_csv(val)
    eval_e30, eval_m30 = table30.eps_mu(table30.f, None)
    assert res["validation"][0] == {"csv": str(val), "fraction": 0.3,
                                    **validation_errors(direct.to_tabulated("f", 1.0), ConstantMaterial("m", 3, 0.03),
                                                        table30.f, eval_e30, eval_m30, 0.3, "maxwell_garnett")}
    assert res["validation"][0]["rms_eps"] < 1e-6 and res["validation"][0]["rms_mu"] < 1e-6
    assert res["output_path"] == str(out) and os.path.isabs(res["material"]["csv"])
    assert os.path.samefile(res["material"]["csv"], out)
    assert {w["code"] for w in env["warnings"]} <= {"model_disagreement", "fraction_sensitive", "filler_ill_conditioned"}
    assert inversion_provenance(loaded) == ("maxwell_garnett", 0.2)


def test_cli_reports_an_untested_prediction_and_a_bad_validation(tmp_path):
    e, m = composite(0.2)
    comp = write(tmp_path, "comp.csv", e, m)
    code, env = run(*invert_args(comp, tmp_path / "a.csv"))
    assert code == 0 and "no_validation" in {w["code"] for w in env["warnings"]}
    other = write(tmp_path, "other.csv", *composite(0.3, "bruggeman", (100 - 20j) * np.ones_like(F, dtype=complex)))
    code, env = run(*invert_args(comp, tmp_path / "b.csv"), "--validate", other, 0.3)
    assert code == 0 and "validation_poor" in {w["code"] for w in env["warnings"]}


def test_cli_refuses_nonphysical_data_and_writes_nothing(tmp_path):
    comp = write(tmp_path, "comp.csv", *composite(0.3, "bruggeman", CONDUCTIVE))
    out = tmp_path / "filler.csv"
    code, env = run(*invert_args(comp, out, phi=0.3), "--clamp-nonpassive")
    assert code == 4 and env["error"]["code"] == "inversion_nonphysical" and not out.exists()
    d = env["error"]["details"]
    assert d["outside_model_points"] == F.size and "amplification" in d and "clampable_points" in d


def test_cli_never_overwrites_an_input(tmp_path):
    comp = write(tmp_path, "comp.csv", *composite(0.2))
    before = comp.read_text(encoding="utf-8")
    code, env = run(*invert_args(comp, comp), "--force")
    assert code == 3 and env["error"]["code"] == "invalid_value" and comp.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("missing", ["--model", "--density-filler", "--fraction", "--matrix-eps"])
def test_nothing_about_the_sample_has_a_default(tmp_path, missing):
    comp = write(tmp_path, "comp.csv", *composite(0.2))
    argv = list(invert_args(comp, tmp_path / "f.csv"))
    i = argv.index(missing)
    del argv[i:i + (3 if missing == "--matrix-eps" else 2)]
    code, env = run(*argv)
    assert code == 2 and env["error"]["code"] == "usage"


def test_weight_fraction_uses_the_densities(tmp_path):
    from coating_studio.cli.spec import wt_to_vol
    phi = wt_to_vol(0.6, 7800.0, 1100.0)
    comp = write(tmp_path, "comp.csv", *composite(phi))
    code, env = run("invert-filler", comp, "-o", tmp_path / "f.csv", "--model", "maxwell_garnett", "--fraction-wt", 0.6,
                    "--density-filler", 7800, "--density-matrix", 1100, "--matrix-eps", 3, 0.03)
    assert code == 0 and env["result"]["fraction"] == phi
    code, env = run("invert-filler", comp, "-o", tmp_path / "g.csv", "--model", "maxwell_garnett", "--fraction-wt", 0.6,
                    "--density-filler", 7800, "--matrix-eps", 3, 0.03)
    assert code == 3 and "--density-matrix" in env["error"]["message"]


def test_matrix_csv_must_cover_the_composite(tmp_path):
    comp = write(tmp_path, "comp.csv", *composite(0.2))
    f = F[20:60]
    mat = write(tmp_path, "matrix.csv", EM[20:60], MM[20:60], f)
    code, env = run("invert-filler", comp, "-o", tmp_path / "f.csv", "--model", "bruggeman", "--fraction", 0.2,
                    "--density-filler", 7800, "--matrix-csv", mat)
    assert code == 4 and env["error"]["code"] == "material_out_of_range"


def _project_with_filler(tmp_path, model="bruggeman", phi0=0.2, fraction=0.2):
    comp = write(tmp_path, "comp.csv", *composite(phi0, model))
    out = tmp_path / "filler.csv"
    assert run(*invert_args(comp, out, model, phi0))[0] == 0
    p = Project()
    p.add_material(load_csv(out, name="F"))
    p.add_material(ConstantMaterial("Mtx", 3, 0.03))
    p.add_material(MixtureMaterial("Mix", "Mtx", "F", fraction, model))
    return p


def _codes(p, names=None):
    return {i.code for i in mixture_range_issues(p, 1e10, names=names)}


def test_no_warning_for_a_mixture_used_as_inverted(tmp_path):
    p = _project_with_filler(tmp_path)
    assert not {c for c in _codes(p) if c.startswith("inverted")}


def test_warning_for_another_mixing_rule(tmp_path):
    p = _project_with_filler(tmp_path, fraction=0.2)
    p.materials["Mix"].model = "maxwell_garnett"
    assert "inverted_filler_model" in _codes(p)


@pytest.mark.parametrize("fraction,hit", [(0.1, False), (0.3, False), (0.0999, True), (0.301, True)])
def test_warning_for_a_fraction_far_from_the_inverted_one(tmp_path, fraction, hit):
    p = _project_with_filler(tmp_path, fraction=fraction)
    assert ("inverted_filler_fraction" in _codes(p)) is hit


def test_upper_end_of_the_range_stops_at_one(tmp_path):
    p = _project_with_filler(tmp_path, phi0=0.8, fraction=0.3)
    hit = [i for i in mixture_range_issues(p, 1e10) if i.code == "inverted_filler_fraction"]
    assert len(hit) == 1 and hit[0].args["hi"] == 1.0 and hit[0].args["lo"] == pytest.approx(0.4)


def test_warning_for_an_inverted_table_used_directly(tmp_path):
    p = _project_with_filler(tmp_path)
    p.structure.layers.append(SlabLayer("F", 1e-3))
    assert "inverted_filler_direct" in _codes(p)
    assert "inverted_filler_direct" not in _codes(p, names={"Mix"})


def test_fit_keeps_the_provenance_and_warns(tmp_path):
    comp = write(tmp_path, "comp.csv", *composite(0.2))
    out = tmp_path / "filler.csv"
    run(*invert_args(comp, out))
    code, env = run("fit", out, "--mu-debye", 1)
    assert code == 0 and "fit_of_inverted" in {w["code"] for w in env["warnings"]}
    note = env["result"]["material"]["note"]
    assert note.startswith("fitted:") and "inverted:" in note
    fitted = TabulatedMaterial("x", [1e9, 2e9], [1, 1], [0, 0], note=note)
    assert inversion_provenance(fitted) == ("maxwell_garnett", 0.2)


def test_a_plain_csv_has_no_provenance(tmp_path):
    assert load_csv(write(tmp_path, "plain.csv", *composite(0.2))).note == ""


def test_negative_real_conductor_counts_as_conductive():
    assert _conductive(ConstantMaterial("metal", -50, 5), None, 1e9)
    assert not _conductive(ConstantMaterial("dielectric", 3, 0.1), None, 1e9)


def test_rms_is_relative_to_the_largest_measured_value():
    assert rms_relative([2, 0], [1, 0]) == pytest.approx(np.sqrt(0.5))


def test_provenance_note_is_one_line():
    note = provenance_note("a\nb.csv", "bruggeman", 0.2, "eps 3-0.03j")
    assert "\n" not in note and note.startswith("inverted: a b.csv; model=bruggeman; fraction=0.2;")
