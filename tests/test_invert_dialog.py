"""The filler inversion dialog: same numbers as the CLI, no invented inputs, no stale result."""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from coating_studio.cli import commands as C  # noqa: E402
from coating_studio.limits import inversion_provenance, mixture_range_issues  # noqa: E402
from coating_studio.materials.csvio import load_csv, to_csv_text  # noqa: E402
from coating_studio.materials.inversion import invert_filler, mix, provenance_note  # noqa: E402
from coating_studio.materials.models import (  # noqa: E402
    ConstantMaterial, DispersiveMaterial, MixtureMaterial, TabulatedMaterial, wt_to_vol,
)

F = np.linspace(2e9, 18e9, 81)
EM = (3 - 0.02j) * np.ones_like(F, dtype=complex)
MM = np.ones_like(F, dtype=complex)
EI = (30 - 5j) * np.ones_like(F, dtype=complex)
MI = 1 + 4 / (1 + 1j * F / 5e9)


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import matplotlib

    matplotlib.use("QtAgg")
    from PySide6.QtCore import QCoreApplication, QSettings
    from PySide6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path_factory.mktemp("cfg")))
    QCoreApplication.setOrganizationName("CoatingStudioTest")
    QCoreApplication.setApplicationName("CoatingStudioTest")
    yield QApplication.instance() or QApplication([])


def tabulated(name, eps, mu, f=F, note=""):
    return TabulatedMaterial(name, f, eps.real, -eps.imag, mu.real, -mu.imag, note=note)


def composite(phi=0.2, model="bruggeman", name="comp"):
    return tabulated(name, mix(EM, EI, phi, model), mix(MM, MI, phi, model))


@pytest.fixture
def window(app):
    from coating_studio.examples import EXAMPLES
    from coating_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.doc.set_project(EXAMPLES["salisbury"][1]())
    yield w
    w.doc._settings_dirty = False
    w.doc.undo_stack.setClean()
    w.close()


def dialog(window, material):
    from coating_studio.gui.dialogs.invert_filler import FillerInversionDialog

    return FillerInversionDialog(material, window)


def fill(d, model="bruggeman", fraction="0.2", rho="1800", matrix=("3", "0.02")):
    d.cb_model.setCurrentIndex(d.cb_model.findData(model))
    d.ed_fraction.setText(fraction)
    d.ed_rho_filler.setText(rho)
    d.ed_me_re.setText(matrix[0])
    d.ed_me_loss.setText(matrix[1])


def write(path, eps, mu):
    path.write_text(to_csv_text(F, eps, mu), encoding="utf-8")
    return str(path)


def codes(d):
    return [c for c, _ in d._report["flags"]]


def test_required_inputs_start_empty_and_nothing_is_computed_without_them(window):
    d = dialog(window, composite())
    assert d.cb_model.currentData() is None
    assert not d.ed_fraction.text() and not d.ed_rho_filler.text() and not d.ed_me_re.text() and not d.ed_me_loss.text()
    assert not d.btn_create.isEnabled()
    d.compute()
    assert d._report is None and not d.btn_create.isEnabled()
    fill(d, rho="")  # the filler density has no default
    d.compute()
    assert d._report is None and not d.btn_create.isEnabled()
    fill(d)  # nor has the mixing rule
    d.cb_model.setCurrentIndex(0)
    d.compute()
    assert d._report is None and not d.btn_create.isEnabled()


@pytest.mark.parametrize("model", ["maxwell_garnett", "bruggeman"])
def test_dialog_gives_the_numbers_of_the_cli(window, tmp_path, model):
    eps, mu = mix(EM, EI, 0.2, model), mix(MM, MI, 0.2, model)
    comp = write(tmp_path / "comp.csv", eps, mu)
    val = write(tmp_path / "val.csv", mix(EM, EI, 0.3, model), mix(MM, MI, 0.3, model))
    out = tmp_path / "out.csv"
    cli = C.cmd_invert_filler(comp, str(out), model, 1800.0, fraction=0.2, matrix_eps=(3.0, 0.02),
                              validate=[(val, 0.3)])
    d = dialog(window, load_csv(comp))
    fill(d, model)
    d.add_validation("val.csv", load_csv(val), "0.3")
    d.compute()
    r = d._report
    assert r["res"].ok and d.btn_create.isEnabled()
    for key, value in r["diag"].items():
        assert cli.result[key] == value, key
    assert cli.result["prediction"] == r["prediction"]
    assert (cli.result["validation"][0]["rms_eps"], cli.result["validation"][0]["rms_mu"]) == (
        r["validation"][0]["rms_eps"], r["validation"][0]["rms_mu"])
    assert [w["code"] for w in cli.warnings] == codes(d)
    written = load_csv(str(out))
    assert written.eps_re == pytest.approx(r["filler"].eps_re, rel=1e-7)
    assert written.mu_loss == pytest.approx(r["filler"].mu_loss, rel=1e-7, abs=1e-8)
    assert r["filler"].note == f"inverted: comp; model={model}; fraction=0.2; matrix=eps 3-0.02j"


def test_weight_fraction_needs_a_matrix_density_and_is_converted(window):
    d = dialog(window, composite(wt_to_vol(0.4, 1800, 1100)))
    fill(d, fraction="0.4")
    d.cb_basis.setCurrentIndex(d.cb_basis.findData("weight"))
    assert d.ed_rho_matrix.isEnabled()
    d.compute()
    assert d._report is None
    d.ed_rho_matrix.setText("1100")
    d.compute()
    assert d._report["phi"] == pytest.approx(wt_to_vol(0.4, 1800, 1100))


def test_a_changed_input_invalidates_the_result_but_a_name_does_not(window):
    d = dialog(window, composite())
    fill(d)
    d.compute()
    assert d.btn_create.isEnabled()
    d.ed_name.setText("another name")
    assert d.btn_create.isEnabled() and d._report is not None
    for change in (lambda: d.ed_fraction.setText("0.21"), lambda: d.ed_rho_filler.setText("1900"),
                   lambda: d.ed_me_re.setText("3.1"), lambda: d.cb_model.setCurrentIndex(1),
                   lambda: d.cb_basis.setCurrentIndex(1), lambda: d.add_validation("v", composite(0.3), "0.3")):
        fill(d)
        d.cb_basis.setCurrentIndex(0)
        d.compute()
        assert d.btn_create.isEnabled()
        change()
        assert d._report is None and not d.btn_create.isEnabled()
        d._accept()
        assert d.result_filler is None  # the button is not the only guard


def test_blocked_data_cannot_be_created_and_the_clamp_needs_a_recompute(window):
    gain = tabulated("gain", EM * 1.2 + 0.05j, MM)
    d = dialog(window, gain)
    fill(d, "maxwell_garnett")
    assert not d.chk_clamp.isEnabled()
    d.compute()
    assert not d._report["res"].ok and not d.btn_create.isEnabled() and d.chk_clamp.isEnabled()
    d.chk_clamp.setChecked(True)
    assert d._report is None and d.chk_clamp.isEnabled()  # ticking it must not remove the way to recompute
    d.compute()
    assert d._report["res"].ok and d.btn_create.isEnabled() and "nonpassive_clamped" in codes(d)
    d.ed_fraction.setText("0.21")  # the permission belonged to the earlier result
    assert not d.chk_clamp.isChecked() and not d.chk_clamp.isEnabled()


def test_no_clamp_offered_when_no_point_qualifies(window):
    d = dialog(window, tabulated("cond", mix(EM, (10 - 200j) * np.ones_like(F, dtype=complex), 0.3, "bruggeman"), MM))
    fill(d, "maxwell_garnett", "0.3")
    d.compute()
    assert not d._report["res"].ok and d._report["res"].clampable_points == 0 and not d.chk_clamp.isEnabled()


def test_a_bad_validation_row_keeps_the_inversion(window):
    d = dialog(window, composite())
    fill(d)
    far = TabulatedMaterial("far", np.array([40e9, 41e9, 42e9]), np.ones(3) * 3, np.zeros(3))
    d.add_validation("far", far, "0.3")
    d.add_validation("noloading", composite(0.3), "")
    d.compute()
    assert d._report["res"].ok and d.btn_create.isEnabled()
    assert all("error" in v for v in d._report["validation"])
    assert "no_validation" in codes(d)  # rows that failed validated nothing


def test_matrix_that_does_not_cover_the_composite_is_refused(window):
    d = dialog(window, composite())
    fill(d)
    d.cb_source.setCurrentIndex(d.cb_source.findData(1))
    narrow = F[F < 10e9]
    d.set_matrix_csv(TabulatedMaterial("m", narrow, 3 * np.ones(narrow.size), 0.02 * np.ones(narrow.size)))
    d.compute()
    assert d._report is None and not d.btn_create.isEnabled()


def test_project_matrix_choices_exclude_what_cannot_be_a_matrix(window):
    p = window.doc.project
    comp = composite()
    note = provenance_note("x", "bruggeman", 0.2, "m")
    for m in (comp, tabulated("inverted", EM, MM, note=note), tabulated("measured matrix", EM, MM),
              ConstantMaterial("resin", 3.0, 0.02), DispersiveMaterial("fitted", eps_inf=3.0),
              MixtureMaterial("mix", "resin", "measured matrix", 0.1)):
        p.add_material(m)
    names = dialog(window, comp)._matrix_candidates()
    assert {"measured matrix", "resin", "fitted"} <= set(names)
    assert not {"comp", "inverted", "mix", "Spacer foam"} & set(names)
    from coating_studio.materials.checks import is_builtin_demo

    assert not [n for n in names if is_builtin_demo(p.materials[n])]


def create(window, comp, model="bruggeman", mixture=True):
    from coating_studio.gui.dialogs.materials import MaterialManager

    p = window.doc.project
    p.add_material(comp)
    p.add_material(ConstantMaterial("resin", 3.0, 0.02))
    manager = MaterialManager(window.doc, window)
    d = dialog(window, comp)
    fill(d, model, matrix=("", ""))
    d.cb_source.setCurrentIndex(d.cb_source.findData(2))
    d.cb_matrix.setCurrentText("resin")
    d.chk_mixture.setChecked(mixture)
    d.compute()
    d._accept()
    manager._add_inverted(d.result_filler, d.result_mixture)
    return d.result_filler.name, d


def test_create_is_one_undo_step_and_keeps_the_provenance(window):
    n_before = window.doc.undo_stack.count()
    filler, _ = create(window, composite())
    assert window.doc.undo_stack.count() == n_before + 1
    p = window.doc.project
    assert inversion_provenance(p.materials[filler]) == ("bruggeman", 0.2)
    assert p.materials[filler].density == 1800.0
    mixture = next(m for m in p.materials.values() if isinstance(m, MixtureMaterial) and m.inclusion == filler)
    assert (mixture.matrix, mixture.inclusion, mixture.fraction, mixture.model) == ("resin", filler, 0.2, "bruggeman")
    assert not [i for i in mixture_range_issues(p, 1e10) if i.code.startswith("inverted_filler")]
    window.doc.undo_stack.undo()
    assert filler not in window.doc.project.materials
    assert mixture.name not in window.doc.project.materials


def test_mixture_is_off_by_default_and_needs_a_project_matrix(window):
    d = dialog(window, composite())
    assert not d.chk_mixture.isEnabled() and not d.chk_mixture.isChecked()
    d.cb_source.setCurrentIndex(d.cb_source.findData(2))
    assert d.chk_mixture.isEnabled() and not d.chk_mixture.isChecked()
    d.chk_mixture.setChecked(True)
    d.cb_source.setCurrentIndex(d.cb_source.findData(0))
    assert not d.chk_mixture.isEnabled() and not d.chk_mixture.isChecked()


def test_filler_name_collision_gets_a_unique_name(window):
    window.doc.project.add_material(ConstantMaterial("comp filler", 2.0, 0.0))
    filler, _ = create(window, composite(), mixture=False)
    assert filler != "comp filler" and filler in window.doc.project.materials
    assert window.doc.project.materials["comp filler"].eps_re == 2.0


def test_an_inverted_table_is_not_offered_as_a_composite(window, monkeypatch):
    from coating_studio.gui.dialogs import materials as M

    table = tabulated("table", EM, MM, note=provenance_note("x", "bruggeman", 0.2, "m"))
    window.doc.project.add_material(table)
    manager = M.MaterialManager(window.doc, window, select="table")
    shown = []
    monkeypatch.setattr(M.QMessageBox, "information", staticmethod(lambda *a: shown.append(a[2])))
    monkeypatch.setattr(M, "FillerInversionDialog", lambda *a: pytest.fail("the dialog must not open"))
    manager._invert_filler()
    assert len(shown) == 1


def test_a_name_cannot_forge_the_provenance():
    note = provenance_note("a; model=bruggeman; fraction=0.9", "maxwell_garnett", 0.2, "b; model=x")

    class Stub:
        pass

    Stub.note = note
    assert inversion_provenance(Stub) == ("maxwell_garnett", 0.2)


def test_cli_warning_messages_are_the_contract():
    expected = {
        ("filler_ill_conditioned", ("n", 3), ("limit", 20.0)):
            "at 3 point(s) measurement errors grow more than 20-fold in the filler values; trust predictions, not the values",
        ("filler_negative_real", ("n", 2)): "2 point(s) have Re <= 0",
        ("nonpassive_clamped", ("n", 4), ("worst", 0.0125)):
            "loss set to 0 at 4 point(s); the composite there is reproduced only to 0.0125",
        ("fraction_sensitive", ("limit", 0.1)): "a 10 % loading error moves predictions by more than 10%",
        ("model_disagreement", ("limit", 0.1)): "the other mixing rule predicts differently by more than 10%",
        ("no_validation",): "no composite at another loading was given (--validate); predictions at other loadings are untested",
        ("validation_poor", ("label", "v.csv"), ("limit", 0.1)): "v.csv: prediction error above 10%",
    }
    for (code, *args), message in expected.items():
        w = C._inversion_warning(code, dict(args))
        assert (w["code"], w["message"]) == (code, message)


def test_inverting_on_the_dialog_grid_matches_the_core(window):
    comp = composite()
    d = dialog(window, comp)
    fill(d)
    d.compute()
    direct = invert_filler(comp.f, comp.eps_re - 1j * comp.eps_loss, comp.mu_re - 1j * comp.mu_loss, EM, MM, 0.2, "bruggeman")
    assert np.array_equal(d._report["res"].eps.value, direct.eps.value)
    assert np.array_equal(d._report["res"].mu.value, direct.mu.value)
