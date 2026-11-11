"""McLachlan GEM mixing rule: limits, analytic percolation laws, passivity and plumbing."""

import numpy as np
import pytest

from coating_studio.limits import static_permeability
from coating_studio.materials import ConstantMaterial, MixtureMaterial, material_from_dict
from coating_studio.materials.checks import check_material
from coating_studio.materials.models import GemParams, bruggeman, gem

RNG = np.random.default_rng(7)
EM = RNG.uniform(1, 10, 3000) - 1j * RNG.uniform(0, 5, 3000)
EI = RNG.uniform(1, 200, 3000) - 1j * RNG.uniform(0, 1e3, 3000)


@pytest.mark.parametrize("phi", [0.0, 0.05, 0.2, 1 / 3, 0.5, 0.9, 1.0])
def test_reduces_to_bruggeman(phi):
    ref = bruggeman(EM, EI, phi)
    assert np.max(np.abs(gem(EM, EI, phi, GemParams(1 / 3, 1.0)) - ref) / np.abs(ref)) < 1e-12


@pytest.mark.parametrize("t", [1.0, 1.5, 2.0, 3.0])
@pytest.mark.parametrize("phi", [0.02, 0.1, 0.25, 0.6])
def test_solves_the_equation_and_is_passive(t, phi):
    p = GemParams(0.12, t)
    e = gem(EM, EI, phi, p)
    a, b, x = EM ** (1 / t), EI ** (1 / t), e ** (1 / t)
    big_a = (1 - p.pc) / p.pc
    resid = (1 - phi) * (a - x) / (a + big_a * x) + phi * (b - x) / (b + big_a * x)
    assert np.max(np.abs(resid)) < 1e-10
    assert np.all(e.imag <= 1e-9 * np.abs(e))  # passive: eps'' >= 0
    assert np.all(e.real > 0) or t > 2  # (at t > 2 a strongly lossy result may have eps' < 0; it stays passive)


@pytest.mark.parametrize("t", [1.0, 2.0, 2.7])
def test_analytic_percolation_laws(t):
    """Insulating matrix: above pc, e = ei ((phi - pc)/(1 - pc))^t.  Perfectly conducting filler: below pc,
    e = em (pc/(pc - phi))^t.  Both follow from the GEM equation in the limits (McLachlan 1990)."""
    pc = 0.15
    p = GemParams(pc, t)
    for phi in (0.2, 0.4, 0.8):
        e = gem(np.array([1e-80]), np.array([2.0]), phi, p)[0]
        assert e.real == pytest.approx(2.0 * ((phi - pc) / (1 - pc)) ** t, rel=1e-5)
    for phi in (0.01, 0.07, 0.12):
        e = gem(np.array([3.0]), np.array([1e80]), phi, p)[0]
        assert e.real == pytest.approx(3.0 * (pc / (pc - phi)) ** t, rel=1e-5)


def test_continuous_through_the_threshold():
    """Unlike Odelevskiy (which raises at pc), GEM is defined at and across pc, and a conductive filler's loss rises
    there by orders of magnitude."""
    em, ei = np.array([3.0 - 0.05j]), np.array([20.0 - 5e4j])  # resin; carbon black with a large conduction loss
    phis = np.linspace(0.0, 0.4, 401)
    e = np.array([gem(em, ei, phi, GemParams(0.1, 2.0))[0] for phi in phis])
    assert np.all(np.isfinite(e))
    assert np.max(np.abs(np.diff(e))) < 0.05 * np.max(np.abs(e))  # no jump on a 0.001 grid
    below, above = -e[phis == 0.05][0].imag, -e[np.isclose(phis, 0.2)][0].imag
    assert above > 100 * below


def test_material_plumbing():
    mats = {"resin": ConstantMaterial("resin", 3.0, 0.05), "cb": ConstantMaterial("cb", 20.0, 5e3, 1.0, 0.0)}
    m = MixtureMaterial("cb mix", "resin", "cb", 0.12, "gem", percolation=0.08, exponent=2.0)
    d = m.to_dict()
    assert (d["model"], d["percolation"], d["exponent"]) == ("gem", 0.08, 2.0) and "shape_n" not in d
    assert material_from_dict(d).to_dict() == d
    assert m.percolation == 0.08 and m.exponent == 2.0 and m.shape is None
    eps, _ = m.eps_mu(np.array([1e9]), mats.__getitem__)
    assert eps[0] == pytest.approx(gem(np.array([3 - 0.05j]), np.array([20 - 5e3j]), 0.12, GemParams(0.08, 2.0))[0])
    assert check_material(m, [1e9], mats.__getitem__) == []
    assert static_permeability(m, mats.__getitem__) == (pytest.approx(1.0), False)
    assert [p.upper for p in m.params()] == [1.0]  # the fraction may cross the threshold
    for bad in ({"percolation": 0.1}, {"exponent": 2.0}, {"percolation": 1.0, "exponent": 2.0},
                {"percolation": 0.1, "exponent": 0.0}, {"percolation": 0.1, "exponent": 2.0, "shape_n": 0.2}):
        with pytest.raises(ValueError):
            MixtureMaterial("x", "resin", "cb", 0.1, "gem", **bad)
    with pytest.raises(ValueError, match="exponent"):
        MixtureMaterial("x", "resin", "cb", 0.1, "bruggeman", exponent=2.0)
    import copy

    assert copy.deepcopy(m).to_dict() == d


def test_gui_switch_to_gem_keeps_bruggeman_values(tmp_path):
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from coating_studio.examples import EXAMPLES
    from coating_studio.gui.dialogs.materials import MaterialManager
    from coating_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.doc.set_project(EXAMPLES["carbon"][1]())
    before = w.project.materials["Carbon / epoxy"].eps_mu(np.array([1e10]), w.project.resolver)[0]
    dlg = MaterialManager(w.doc, w, select="Carbon / epoxy")
    assert not dlg.m_form.isRowVisible(dlg.m_t)
    dlg.m_model.setCurrentIndex(dlg.m_model.findData("gem"))
    dlg._on_mix_model()
    m = w.project.materials["Carbon / epoxy"]
    assert (m.model, m.percolation, m.exponent) == ("gem", pytest.approx(1 / 3), 1.0)
    assert dlg.m_form.isRowVisible(dlg.m_t) and not dlg.m_form.isRowVisible(dlg.m_n)
    after = m.eps_mu(np.array([1e10]), w.project.resolver)[0]
    assert after == pytest.approx(before, rel=1e-12)  # the switch alone changes nothing
    dlg.m_pc.setValue(0.08)
    dlg.m_pc.valueEdited.emit(0.08)
    dlg.m_t.setValue(2.0)
    dlg.m_t.valueEdited.emit(2.0)
    m = w.project.materials["Carbon / epoxy"]
    assert (m.percolation, m.exponent) == (pytest.approx(0.08), pytest.approx(2.0))
    w.doc.undo_stack.setClean()
    dlg.close()
    w.close()
