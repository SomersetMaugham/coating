import json

import numpy as np
import pytest

from coating_studio.core import SheetLayer, SlabLayer
from coating_studio.examples import EXAMPLES
from coating_studio.materials import (
    ConstantMaterial, DispersiveMaterial, MixtureMaterial, OutOfRangeError, TabulatedMaterial,
    bruggeman, make_term, maxwell_garnett,
)
from coating_studio.materials.checks import check_material
from coating_studio.materials.csvio import CsvFormatError, parse_csv_text
from coating_studio.materials.fitting import FitSpec, fit_dispersive
from coating_studio.project import Project, available_params, get_param, set_param


def test_debye_lorentz_sign_convention_is_lossy():
    m = DispersiveMaterial("D", eps_inf=3, sigma=0.1, eps_terms=[make_term("debye", 5, 1e9)],
                           mu_terms=[make_term("lorentz", 2, 3e9, 1e9)])
    eps, mu = m.eps_mu(np.geomspace(1e7, 1e11, 50), None)
    assert np.all(eps.imag < 0) and np.all(mu.imag < 0)
    assert check_material(m, np.geomspace(1e7, 1e11, 5), None) == []


@pytest.mark.parametrize("rule", [maxwell_garnett, bruggeman])
def test_mixing_limits(rule):
    em, ei = np.array([3 - 0.1j]), np.array([20 - 5j])
    assert rule(em, ei, 0.0)[0] == pytest.approx(em[0])
    assert rule(em, ei, 1.0)[0] == pytest.approx(ei[0])
    mid = rule(em, ei, 0.3)[0]
    assert em[0].real < mid.real < ei[0].real and mid.imag <= 0


def test_mg_equals_bruggeman_dilute():
    em, ei = np.array([2.5 + 0j]), np.array([8 - 1j])
    a = maxwell_garnett(em, ei, 0.01)[0]
    b = bruggeman(em, ei, 0.01)[0]
    assert abs(a - b) / abs(a) < 2e-4


def test_mixture_material_and_density():
    p = Project()
    mix = p.materials["Carbon / epoxy"]
    eps, mu = mix.eps_mu(np.array([1e9, 1e10]), p.resolver)
    assert np.all(eps.imag < 0)
    rho = mix.get_density(p.resolver)
    assert rho == pytest.approx(0.30 * 1800 + 0.70 * 1200)


def test_tabulated_out_of_range_and_interp():
    t = TabulatedMaterial("T", [1e9, 2e9, 3e9], [2, 3, 4], [0.1, 0.2, 0.3])
    eps, mu = t.eps_mu(np.array([1.5e9]), None)
    assert eps[0] == pytest.approx(2.5 - 0.15j)
    with pytest.raises(OutOfRangeError):
        t.eps_mu(np.array([0.5e9]), None)


def test_csv_parse_units_and_errors():
    txt = "Frequency (MHz); eps'; eps''\n100;4;0.1\n200;3.9;0.12\n"
    f, er, el, mr, ml = parse_csv_text(txt)
    assert f[1] == pytest.approx(200e6) and np.all(mr == 1) and np.all(ml == 0)
    f, *_ = parse_csv_text("# comment\n1,2,0.1,1,0\n2,2,0.1,1,0\n")
    assert f[0] == pytest.approx(1e9)
    with pytest.raises(CsvFormatError):
        parse_csv_text("1,2\n3,4\n")


def test_fit_recovers_debye_parameters():
    true = DispersiveMaterial("T", eps_inf=4.0, eps_terms=[make_term("debye", 6.0, 3e9)],
                              mu_terms=[make_term("lorentz", 2.0, 5e9, 3e9)])
    f = np.geomspace(0.3e9, 30e9, 80)
    eps, mu = true.eps_mu(f, None)
    res = fit_dispersive("fit", f, eps, mu, FitSpec(1, 0), FitSpec(0, 1))
    m = res.material
    assert res.rms_eps < 1e-6 and res.rms_mu < 1e-6
    assert m.eps_inf == pytest.approx(4.0, rel=1e-4)
    assert m.eps_terms[0]["f0"] == pytest.approx(3e9, rel=1e-4)
    assert m.mu_terms[0]["gamma"] == pytest.approx(3e9, rel=1e-4)


def test_passivity_and_snoek_warnings():
    gain = ConstantMaterial("G", 3.0, -0.2)
    codes = {i.code for i in check_material(gain, [1e9], None)}
    assert "eps_gain" in codes
    fer = DispersiveMaterial("F", mu_terms=[make_term("debye", 1000.0, 1e9)])
    codes = {i.code for i in check_material(fer, [1e9], None)}
    assert "snoek" in codes


@pytest.mark.parametrize("key", list(EXAMPLES))
def test_project_roundtrip(tmp_path, key):
    p = EXAMPLES[key][1]()
    path = tmp_path / "x.coat"
    p.save(path)
    q = Project.load(path)
    assert json.dumps(q.to_dict(), sort_keys=True) == json.dumps(p.to_dict(), sort_keys=True)
    assert q.validate() == []


def test_rename_material_updates_references():
    p = EXAMPLES["carbon"][1]()
    p.rename_material("Epoxy", "Resin")
    assert p.materials["Carbon / epoxy"].matrix == "Resin"
    p.rename_material("Carbon / epoxy", "Mix")
    assert p.structure.layers[0].material == "Mix"
    assert any(v.path[:2] == ("material", "Mix") for v in p.optimization.variables)


def test_param_paths_and_undo_state():
    p = EXAMPLES["jaumann2"][1]()
    paths = [x[0] for x in available_params(p)]
    sheet = p.structure.layers[0]
    assert ("layer", sheet.uid, "R") in paths
    set_param(p, ("layer", sheet.uid, "R"), 555.0)
    assert get_param(p, ("layer", sheet.uid, "R")) == 555.0
    state = p.model_state()
    p.remove_layer(sheet.uid)
    assert len(p.structure.layers) == 3
    p.restore_model_state(state)
    assert isinstance(p.structure.layers[0], SheetLayer) and p.structure.layers[0].R == 555.0
    assert isinstance(p.structure.layers[1], SlabLayer)


def test_mixture_cycle_detected():
    p = Project()
    p.add_material(MixtureMaterial("M1", "Epoxy", "M2", 0.1))
    p.add_material(MixtureMaterial("M2", "Epoxy", "M1", 0.1))
    from coating_studio.materials import MaterialCycleError
    with pytest.raises(MaterialCycleError):
        p.materials["M1"].eps_mu(np.array([1e9]), p.resolver)


def test_refractive_index_conversion_round_trip():
    from coating_studio.materials import eps_from_nk, nk_from_eps_mu

    # MgF2 (lossless), a lossy dielectric, a metal (eps' < 0) and a magnetic medium
    for n, k, mu in [(1.38, 0.0, 1), (2.0, 0.3, 1), (0.13, 3.2, 1), (3.0, 0.5, 2.0 - 0.4j)]:
        eps = eps_from_nk(n, k, mu)
        assert np.sqrt(eps * mu) ** 2 == pytest.approx((n - 1j * k) ** 2)
        assert nk_from_eps_mu(eps, mu) == pytest.approx((n, k))
    eps = eps_from_nk(2.0, 0.3)
    assert eps.real == pytest.approx(4.0 - 0.09) and -eps.imag == pytest.approx(2 * 2.0 * 0.3)
    n, k = nk_from_eps_mu(-20 - 1j)  # Drude-like metal: large k, small positive n
    assert k > 4 and 0 < n < 1
