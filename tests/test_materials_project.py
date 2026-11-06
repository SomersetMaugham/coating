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


def test_csv_refractive_index_layouts():
    from coating_studio.core import C0

    # wavelength in nm with n, k -> eps = (n - jk)^2, frequency C0/lambda
    f, er, el, mr, ml = parse_csv_text("Wavelength (nm), n, k\n500, 1.5, 0.01\n600, 1.49, 0.02\n")
    assert f[0] == pytest.approx(C0 / 500e-9)
    assert (er[1], el[1]) == pytest.approx((1.49 ** 2 - 0.02 ** 2, 2 * 1.49 * 0.02))
    assert np.all(mr == 1) and np.all(ml == 0)
    # bare 'wl' heading means micrometres; n only means lossless
    f, er, el, *_ = parse_csv_text("wl\tn\n0.4\t1.47\n0.8\t1.45\n")
    assert f[1] == pytest.approx(C0 / 0.8e-6) and er[0] == pytest.approx(1.47 ** 2) and np.all(el == 0)
    # wavenumber (FTIR) axis
    f, *_ = parse_csv_text("Wavenumber (cm-1); eps'; eps''\n1000; 2; 0.5\n1200; 2; 0.4\n")
    assert f[0] == pytest.approx(C0 * 1e5)
    # micrometre wavelength with eps columns
    f, *_ = parse_csv_text("lambda [µm], eps', eps''\n8, 2, 0.1\n13, 2.2, 0.3\n")
    assert f[0] == pytest.approx(C0 / 8e-6)


def test_csv_refractiveindex_info_two_blocks():
    from coating_studio.core import C0

    txt = "wl,n\n0.4,1.50\n0.5,1.48\n0.6,1.47\n0.9,1.45\nwl,k\n0.45,0.0\n0.65,0.02\n"
    f, er, el, *_ = parse_csv_text(txt)
    # n points outside the k data (0.4, 0.9 um) are dropped, k is interpolated
    assert f == pytest.approx(C0 / np.array([0.5e-6, 0.6e-6]))
    k = np.array([0.005, 0.015])
    n = np.array([1.48, 1.47])
    assert er == pytest.approx(n ** 2 - k ** 2) and el == pytest.approx(2 * n * k)
    f, er, el, *_ = parse_csv_text("wl,n\n0.4,1.5\n0.5,1.48\n")  # n block only
    assert np.all(el == 0)
    with pytest.raises(CsvFormatError):
        parse_csv_text("wl,n\n0.4,1.5\n0.5,1.48\nwl,k\n2,0.1\n3,0.1\n")  # no overlap
    with pytest.raises(CsvFormatError):
        parse_csv_text("wl,n,k\n0.4,1.5,-0.1\n0.5,1.48,0\n")  # gain is not accepted


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


def test_builtin_demo_materials_are_flagged_until_edited():
    from coating_studio.materials.checks import is_builtin_demo
    from coating_studio.materials.library import builtin_materials

    mats = {m.name: m for m in builtin_materials()}
    f = np.array([1e9, 10e9])
    assert not is_builtin_demo(mats["Air"])  # vacuum is exact
    foam = mats["PMI foam"]
    assert is_builtin_demo(foam)
    assert [i.level for i in check_material(foam, f, mats.get)] == ["info"]
    foam.note = "my own note"  # a note change alone keeps the demo numbers
    assert is_builtin_demo(foam)
    foam.eps_re = 1.10  # edited numbers are the user's data
    assert not is_builtin_demo(foam) and check_material(foam, f, mats.get) == []
    renamed = mats["PTFE"].clone("PTFE (measured)")
    assert not is_builtin_demo(renamed)


def test_loss_tangent_helpers_and_csv():
    from coating_studio.materials import loss_from_tangent, loss_tangent

    assert loss_tangent(4.4, 0.088) == pytest.approx(0.02)
    assert loss_from_tangent(4.4, 0.02) == pytest.approx(0.088)
    with pytest.raises(ValueError):
        loss_tangent(-1.0, 0.1)
    plain = parse_csv_text("f [GHz], eps', eps'', mu', mu''\n1, 4, 0.08, 2, 0.4\n2, 4, 0.12, 1.5, 0.3\n")
    for hdr in ("f [GHz], eps', tan d, mu', tan d_mu", "f (GHz); ε'; tan δε; μ'; tan δμ",
                "f [GHz], eps', loss tangent, mu', mu''"):
        last = "0.4" if hdr.endswith("mu''") else "0.2"
        last2 = "0.3" if hdr.endswith("mu''") else "0.2"
        sep = ";" if ";" in hdr else ","
        txt = f"{hdr}\n1{sep}4{sep}0.02{sep}2{sep}{last}\n2{sep}4{sep}0.03{sep}1.5{sep}{last2}\n"
        got = parse_csv_text(txt)
        for a, b in zip(got, plain):
            assert np.allclose(a, b), hdr
    f, er, el, *_ = parse_csv_text("f [GHz], eps', tan d\n1, 4, 0.02\n2, 4, 0.03\n")
    assert np.allclose(el, [0.08, 0.12])
    with pytest.raises(CsvFormatError):  # negative tan d
        parse_csv_text("f [GHz], eps', tan d\n1, 4, -0.02\n2, 4, 0.03\n")
    with pytest.raises(CsvFormatError):  # tan d needs a positive real part
        parse_csv_text("f [GHz], eps', tan d\n1, -4, 0.02\n2, 4, 0.03\n")
    with pytest.raises(CsvFormatError):  # tan d in a real-part column
        parse_csv_text("f [GHz], tan d, eps''\n1, 0.02, 0.1\n2, 0.03, 0.1\n")


def test_rlc_sheet_file_format_and_parameters():
    from coating_studio.core import SheetLayer
    from coating_studio.project import SCHEMA_VERSION, available_params, get_param, set_param

    p = EXAMPLES["salisbury"][1]()
    d = p.to_dict()
    assert "model" not in d["structure"]["layers"][0]  # constant sheets serialise as before
    old = json.loads(json.dumps(d))
    old["schema"] = 2  # a schema-2 file loads unchanged (constant sheet)
    assert Project.from_dict(old).structure.layers[0].model == "constant"
    sh = p.structure.layers[0]
    sh.model, sh.L, sh.C = "rlc", 5e-9, 0.05e-12
    q = Project.from_dict(json.loads(json.dumps(p.to_dict())))
    s2 = q.structure.layers[0]
    assert (s2.model, s2.L, s2.C) == ("rlc", 5e-9, 0.05e-12) and q.to_dict()["schema"] == SCHEMA_VERSION == 3
    paths = [x[0] for x in available_params(q)]
    assert ("layer", sh.uid, "L") in paths and ("layer", sh.uid, "C") in paths
    assert ("layer", sh.uid, "X") not in paths
    assert get_param(q, ("layer", sh.uid, "L")) == 5e-9
    with pytest.raises(KeyError):
        get_param(q, ("layer", sh.uid, "X"))
    s2.C = None  # inductive grid: no C parameter (and no TypeError from float(None))
    with pytest.raises(KeyError):
        get_param(q, ("layer", sh.uid, "C"))
    with pytest.raises(KeyError):
        set_param(q, ("layer", sh.uid, "C"), 1e-13)
    with pytest.raises(ValueError):
        Project.from_dict({**q.to_dict(), "structure": {"layers": [{"kind": "sheet", "R": 1, "model": "x"}]}})
    assert SheetLayer(100.0).impedance_at(np.array([1e9, 2e9])).tolist() == [100 + 0j, 100 + 0j]
