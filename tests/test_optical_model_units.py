"""Dispersion-term f0 and gamma in the project's spectral display unit (display only: terms keep Hz)."""

import os

import pytest

from coating_studio import spectral
from coating_studio.core.constants import C0
from coating_studio.core.units import LINEWIDTH_UNIT, SPECTRAL_UNITS, from_linewidth, to_linewidth

F0 = 1080 * 100 * C0  # SiO2-like phonon resonance, 1080 cm^-1 = 32.4 THz = 9.26 um
GAMMA = 30 * 100 * C0  # 30 cm^-1


def _project(unit="nm"):
    from coating_studio.examples import EXAMPLES
    from coating_studio.materials.models import DispersiveMaterial, make_term

    p = EXAMPLES["dallenbach"][1]()
    p.add_material(DispersiveMaterial("Phonon", eps_inf=2.0, eps_terms=[
        make_term("debye", 1.0, 5e9), make_term("lorentz", 0.8, F0, GAMMA)]))
    p.structure.layers[0].material = "Phonon"
    p.sweep.spectral_unit = unit
    return p


def test_linewidth_units():
    assert set(LINEWIDTH_UNIT) == set(SPECTRAL_UNITS)
    assert to_linewidth(GAMMA, "cm-1") == pytest.approx(30.0, rel=1e-14)
    assert to_linewidth(2e12, "nm") == to_linewidth(2e12, "um") == to_linewidth(2e12, "THz") == 2.0
    assert to_linewidth(2e12, "GHz") == 2000.0
    assert to_linewidth(0.0, "nm") == 0.0 and from_linewidth(0.0, "cm-1") == 0.0
    for u in SPECTRAL_UNITS:
        assert from_linewidth(to_linewidth(GAMMA, u), u) == pytest.approx(GAMMA, rel=1e-14)
    with pytest.raises(ValueError):
        to_linewidth(-1.0, "THz")
    with pytest.raises(ValueError):
        from_linewidth(-1.0, "cm-1")
    with pytest.raises(ValueError):
        from_linewidth(float("inf"), "THz")


def test_param_helpers_map_only_term_f0_and_gamma():
    p = _project("nm")
    f0 = ("material", "Phonon", "eps_terms", 1, "f0")
    gamma = ("material", "Phonon", "eps_terms", 1, "gamma")
    assert spectral.param_kind(f0, "GHz") == "position" and spectral.param_kind(gamma, "GHz") == "linewidth"
    assert spectral.param_kind(("layer", "x", "thickness"), "mm") == "length"
    assert spectral.param_kind(("material", "Phonon", "eps_inf"), "") is None
    assert spectral.param_kind(("material", "M", "fraction"), "frac") is None
    assert spectral.param_display_unit(p, f0, "GHz") == "nm"
    assert spectral.param_display_unit(p, gamma, "GHz") == "THz"
    assert spectral.param_to_display(F0, p, f0, "GHz") == pytest.approx(C0 / F0 * 1e9)
    assert spectral.param_from_display(9259.259259259259, p, f0, "GHz") == pytest.approx(F0, rel=1e-12)
    assert spectral.param_reversed(p, f0, "GHz") and not spectral.param_reversed(p, gamma, "GHz")
    p.sweep.spectral_unit = "cm-1"
    assert spectral.param_to_display(F0, p, f0, "GHz") == pytest.approx(1080.0)
    assert spectral.param_to_display(GAMMA, p, gamma, "GHz") == pytest.approx(30.0)
    assert not spectral.param_reversed(p, f0, "GHz")
    p.sweep.spectral_unit = "GHz"  # the GHz project shows what it always did
    assert spectral.param_to_display(5e9, p, f0, "GHz") == 5.0
    assert spectral.param_from_display(5.0, p, gamma, "GHz") == 5e9
    p.sweep.length_unit = "um"
    assert spectral.param_display_unit(p, ("layer", "x", "thickness"), "mm") == "um"
    assert spectral.param_to_display(2e-3, p, ("layer", "x", "thickness"), "mm") == pytest.approx(2000.0)
    assert spectral.position_symbol("nm") == "λ₀" and spectral.position_symbol("cm-1") == "ν̃₀"
    assert spectral.position_symbol("THz") == "f₀"
    with pytest.raises(ValueError):  # an f0 of 0 Hz has no wavelength
        spectral.param_to_display(0.0, _project("nm"), f0, "GHz")


def test_cli_keeps_ghz_parameters():
    """The CLI contract is unchanged: term parameters are listed with the unit GHz."""
    from coating_studio.project import available_params, param_unit

    p = _project("nm")
    units = {path[-1]: unit for path, _, unit in available_params(p) if path[0] == "material"}
    assert units["f0"] == units["gamma"] == "GHz"
    assert param_unit(p, ("material", "Phonon", "eps_terms", 1, "f0")) == "GHz"


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    pytest.importorskip("PySide6")
    import matplotlib

    matplotlib.use("QtAgg")
    from PySide6.QtCore import QCoreApplication, QSettings
    from PySide6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path_factory.mktemp("cfg")))
    QCoreApplication.setOrganizationName("CoatingStudioTest")
    QCoreApplication.setApplicationName("CoatingStudioTest")
    yield QApplication.instance() or QApplication([])


def test_unit_labels_and_symbols(app):
    from coating_studio.gui.fmt import param_label, unit_label

    assert unit_label("um") == "µm" and unit_label("cm-1") == "cm⁻¹" and unit_label("THz") == "THz"
    assert unit_label("mm") == "mm" and unit_label("ohm") == "Ω/sq" and unit_label("frac") == ""
    assert param_label("Phonon: eps lorentz #2 f0") == "Phonon: ε Lorentz #2 f₀"
    assert param_label("Phonon: eps lorentz #2 f0", "λ₀") == "Phonon: ε Lorentz #2 λ₀"
    assert param_label("Phonon: eps lorentz #2 gamma", "λ₀") == "Phonon: ε Lorentz #2 γ"


def _close(w, *dialogs):
    w.doc._settings_dirty = False
    w.doc.undo_stack.setClean()
    for d in dialogs:
        d.close()
    w.close()


def test_terms_table_follows_the_spectral_unit(app):
    from coating_studio.gui.dialogs.materials import MaterialManager
    from coating_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.doc.set_project(_project("nm"))
    dlg = MaterialManager(w.doc, w, select="Phonon")
    tbl = dlg.d_eterms.tbl
    head = [tbl.horizontalHeaderItem(c).text() for c in range(4)]
    assert head[2:] == ["λ₀ [nm]", "γ [THz]"]
    assert "c/f₀" in tbl.horizontalHeaderItem(2).toolTip() and "THz" in tbl.horizontalHeaderItem(3).toolTip()
    assert tbl.cellWidget(1, 2).value() == pytest.approx(C0 / F0 * 1e9)
    assert tbl.cellWidget(1, 3).value() == pytest.approx(GAMMA / 1e12)
    assert tbl.cellWidget(0, 2).value() == pytest.approx(C0 / 5e9 * 1e9)  # the Debye term's f0 as well
    # an edit converts only its own box; the other values keep their Hz bit for bit
    tbl.cellWidget(1, 2).setValue(10000.0)
    terms = w.project.materials["Phonon"].eps_terms
    assert terms[1]["f0"] == pytest.approx(C0 / 10e-6, rel=1e-14)
    assert terms[1]["gamma"] == GAMMA and terms[0]["f0"] == 5e9
    tbl.cellWidget(1, 3).setValue(2.0)
    assert w.project.materials["Phonon"].eps_terms[1]["gamma"] == 2e12
    w.doc.undo_stack.undo()
    w.doc.undo_stack.undo()
    assert w.project.materials["Phonon"].eps_terms[1] == {"type": "lorentz", "delta": 0.8, "f0": F0, "gamma": GAMMA}
    # a unit change redraws the headers and the values
    w.doc.edit_settings(lambda pp: setattr(pp.sweep, "spectral_unit", "cm-1"))
    tbl = dlg.d_eterms.tbl
    assert [tbl.horizontalHeaderItem(c).text() for c in (2, 3)] == ["ν̃₀ [cm⁻¹]", "γ [cm⁻¹]"]
    assert tbl.horizontalHeaderItem(3).toolTip() == ""
    assert tbl.cellWidget(1, 2).value() == pytest.approx(1080.0)
    assert tbl.cellWidget(1, 3).value() == pytest.approx(30.0)
    # a new term in a cm-1 project still edits in cm-1 (the table keeps its unit)
    dlg.d_eterms._add("lorentz")
    tbl = dlg.d_eterms.tbl
    assert tbl.cellWidget(2, 2).value() == pytest.approx(1e9 / (100 * C0))
    tbl.cellWidget(2, 3).setValue(5.0)
    assert w.project.materials["Phonon"].eps_terms[2]["gamma"] == pytest.approx(5 * 100 * C0, rel=1e-14)
    # GHz shows what it always did
    w.doc.edit_settings(lambda pp: setattr(pp.sweep, "spectral_unit", "GHz"))
    tbl = dlg.d_eterms.tbl
    assert [tbl.horizontalHeaderItem(c).text() for c in (2, 3)] == ["f₀ [GHz]", "γ [GHz]"]
    assert tbl.cellWidget(0, 2).value() == 5.0
    tbl.cellWidget(0, 2).setValue(7.0)
    assert w.project.materials["Phonon"].eps_terms[0]["f0"] == 7e9
    _close(w, dlg)


def test_optimisation_variables_follow_the_spectral_unit(app):
    from coating_studio.gui.main_window import MainWindow

    w = MainWindow()
    p = _project("nm")
    p.optimization.variables = []
    w.doc.set_project(p)
    p_opt = w.p_opt
    p_opt.refresh()
    f0_path = ("material", "Phonon", "eps_terms", 1, "f0")
    gamma_path = ("material", "Phonon", "eps_terms", 1, "gamma")
    texts = {tuple(p_opt.cb_add.itemData(k)): p_opt.cb_add.itemText(k) for k in range(p_opt.cb_add.count())}
    assert texts[f0_path] == "Phonon: ε Lorentz #2 λ₀  [nm]"
    assert texts[gamma_path] == "Phonon: ε Lorentz #2 γ  [THz]"
    for path in (f0_path, gamma_path):
        p_opt.cb_add.setCurrentIndex(next(k for k in range(p_opt.cb_add.count())
                                          if tuple(p_opt.cb_add.itemData(k)) == path))
        p_opt._add_variable()
    v = w.project.optimization.variables[0]
    assert tuple(v.path) == f0_path and (v.lower, v.upper) == (F0 / 4, F0 * 4)
    tbl = p_opt.tbl
    assert tbl.item(0, 0).text() == "Phonon: ε Lorentz #2 λ₀  [nm]"
    lam = C0 / F0 * 1e9
    assert float(tbl.item(0, 1).text()) == pytest.approx(lam, rel=1e-4)
    # Lower shows the short wavelength (the upper Hz bound) and edits that bound
    assert tbl.cellWidget(0, 2).value() == pytest.approx(lam / 4)
    assert tbl.cellWidget(0, 3).value() == pytest.approx(lam * 4)
    assert tbl.cellWidget(0, 2).minimum() > 0
    tbl.cellWidget(0, 2).setValue(5000.0)
    v = w.project.optimization.variables[0]
    assert v.upper == pytest.approx(C0 / 5e-6, rel=1e-14) and v.lower == F0 / 4
    tbl = p_opt.tbl
    tbl.cellWidget(0, 3).setValue(20000.0)
    v = w.project.optimization.variables[0]
    assert v.lower == pytest.approx(C0 / 20e-6, rel=1e-14) and v.upper == pytest.approx(C0 / 5e-6, rel=1e-14)
    # gamma: linear, THz, Lower is lower
    g = w.project.optimization.variables[1]
    tbl = p_opt.tbl
    assert tbl.item(1, 0).text().endswith("γ  [THz]")
    assert tbl.cellWidget(1, 2).value() == pytest.approx(g.lower / 1e12)
    assert tbl.cellWidget(1, 2).minimum() == 0.0
    # a unit change rebuilds the table (main window: the panel refreshes on a display-unit change)
    w.doc.edit_settings(lambda pp: setattr(pp.sweep, "spectral_unit", "cm-1"))
    tbl = p_opt.tbl
    assert tbl.item(0, 0).text() == "Phonon: ε Lorentz #2 ν̃₀  [cm⁻¹]"
    assert tbl.cellWidget(0, 2).value() == pytest.approx(C0 / 20e-6 / (100 * C0))  # not reversed
    assert tbl.item(1, 0).text().endswith("γ  [cm⁻¹]")
    # a bound of 0 Hz cannot be shown as a wavenumber: a dash instead of a crash
    w.doc.edit_settings(lambda pp: setattr(pp.optimization.variables[0], "lower", 0.0))
    p_opt.refresh()
    assert p_opt.tbl.item(0, 2).text() == "—" and p_opt.tbl.cellWidget(0, 2) is None
    w.doc.edit_settings(lambda pp: setattr(pp.sweep, "spectral_unit", "GHz"))
    tbl = p_opt.tbl
    assert tbl.item(0, 0).text() == "Phonon: ε Lorentz #2 f₀  [GHz]" and tbl.cellWidget(0, 2).value() == 0.0
    _close(w)


def test_result_table_uses_the_display_unit(app):
    from coating_studio.gui.main_window import MainWindow
    from coating_studio.optimize import optimize

    w = MainWindow()
    p = _project("nm")
    from coating_studio.project import ContinuousVariable

    path = ("material", "Phonon", "eps_terms", 1, "f0")
    p.optimization.variables = [ContinuousVariable(path, F0 / 2, F0 * 2)]
    p.optimization.maxiter, p.optimization.popsize, p.optimization.seed, p.optimization.polish = 2, 4, 1, False
    w.doc.set_project(p)
    res = optimize(p.copy())
    w.p_opt._show_result(res)
    rows = {w.p_opt.tbl_res.item(r, 0).text(): w.p_opt.tbl_res.item(r, 1).text()
            for r in range(w.p_opt.tbl_res.rowCount())}
    text = rows["Phonon: ε Lorentz #2 λ₀"]
    assert text.endswith(" nm") and float(text.split()[0]) == pytest.approx(C0 / res.values[path] * 1e9, rel=1e-5)
    _close(w)


def test_plot_fonts_fall_back_for_the_micro_sign():
    """Every µm axis drew '[⍰m]' on macOS: the Korean font has no µ and the generic family did not fall back."""
    import warnings

    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    from coating_studio.mplfonts import configure_matplotlib_fonts

    configure_matplotlib_fonts()
    fig = Figure()
    FigureCanvasAgg(fig)
    fig.text(0.1, 0.5, "Wavelength [µm] 파장 cm⁻¹ λ₀ ν̃₀")
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # "Glyph ... missing from font(s)"
        fig.canvas.draw()
