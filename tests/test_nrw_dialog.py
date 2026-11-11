"""The NRW extraction dialog (material manager → New → Extract from S-parameters)."""

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from test_nrw import LOSSY, _s2p_text, slab_sparams  # noqa: E402  (the independent forward model)

from coating_studio.core.constants import C0  # noqa: E402
from coating_studio.materials import DispersiveMaterial  # noqa: E402


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


@pytest.fixture
def window(app):
    from coating_studio.examples import EXAMPLES
    from coating_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.doc.set_project(EXAMPLES["dallenbach"][1]())
    yield w
    w.doc.undo_stack.setClean()
    w.close()


def _write(tmp_path, f, eps, mu, d, fc=None, name="sample.s2p"):
    s11, s21 = slab_sparams(f, eps, mu, d, fc)
    path = tmp_path / name
    path.write_text(_s2p_text(f, s11, s21))
    return str(path)


def test_waveguide_extraction_creates_a_material(window, tmp_path):
    from coating_studio.gui.dialogs.nrw import NRW_PREFIX, NrwDialog

    f = np.linspace(8e9, 12e9, 41)
    eps, mu = LOSSY.eps_mu(f, None)
    path = _write(tmp_path, f, eps, mu, 3e-3, C0 / (2 * 22.86e-3))
    dlg = NrwDialog(window, window)
    ok = dlg.bb.button(dlg.bb.StandardButton.Ok)
    dlg.compute()
    assert "two-port" in dlg.lbl_status.text() and not ok.isEnabled()  # nothing is computed without a file
    assert dlg.load_file(path) and dlg.ed_name.text() == "sample" and "41" in dlg.lbl_file.text()
    dlg.compute()
    assert "thickness" in dlg.lbl_status.text() and not ok.isEnabled()  # no thickness is invented
    dlg.ed_thick.setText("3")
    dlg.cb_line.setCurrentIndex(dlg.cb_line.findData("waveguide"))
    assert dlg.form.isRowVisible(dlg.ed_a)
    dlg.ed_a.setText("22.86")
    dlg.compute()
    assert ok.isEnabled() and dlg.lbl_status.text() == "No warnings." and len(dlg.fig.axes) == 2
    dlg._accept()
    assert dlg.result_material is None and "density" in dlg.lbl_status.text()
    dlg.ed_rho.setText("2500")
    dlg.ed_thick.setText("3.1")
    dlg.ed_thick.textEdited.emit("3.1")  # an edit invalidates the result
    assert not ok.isEnabled()
    dlg.ed_thick.setText("3")
    dlg.compute()
    dlg._accept()
    m = dlg.result_material
    assert m.note.startswith(NRW_PREFIX) and "TE10 waveguide a = 22.86 mm" in m.note and m.density == 2500
    e2, m2 = m.eps_mu(f, None)
    assert np.max(np.abs(e2 - eps) / np.abs(eps)) < 1e-9 and np.max(np.abs(m2 - mu) / np.abs(mu)) < 1e-9


def test_suggested_branch_button(window, tmp_path):
    from coating_studio.gui.dialogs.nrw import NrwDialog

    f = np.linspace(8e9, 12e9, 161)
    mat = DispersiveMaterial("c", eps_inf=10.0, eps_loss=0.5, mu_inf=2.4, mu_loss=0.2)
    eps, mu = mat.eps_mu(f, None)
    dlg = NrwDialog(window, window)
    dlg.load_file(_write(tmp_path, f, eps, mu, 20e-3))
    dlg.ed_thick.setText("20")
    dlg.compute()
    assert dlg.btn_branch.isVisibleTo(dlg)
    assert "branch 3" in dlg.lbl_status.text() and dlg.btn_branch.text() == "Use branch 3"
    dlg.btn_branch.click()
    assert dlg.sp_branch.value() == 3 and dlg.lbl_status.text() == "No warnings."
    assert np.max(np.abs(dlg.result.eps - eps) / np.abs(eps)) < 1e-8


def test_manager_adds_the_material_as_one_undo_step(window, monkeypatch):
    import coating_studio.gui.dialogs.nrw as nrw_mod
    from coating_studio.gui.dialogs.materials import MaterialManager
    from coating_studio.materials.models import TabulatedMaterial

    made = TabulatedMaterial("PMI foam", [1e9, 2e9], [2, 2], [0.1, 0.1], density=900.0)  # a clashing name

    class Fake:
        def __init__(self, *a, **k):
            self.result_material = made

        def exec(self):
            return 1

    monkeypatch.setattr(nrw_mod, "NrwDialog", Fake)
    before = set(window.project.materials)
    dlg = MaterialManager(window.doc, window)
    dlg._extract_nrw()
    added = set(window.project.materials) - before
    assert added == {"PMI foam (2)"}
    window.doc.undo_stack.undo()
    assert set(window.project.materials) == before
    dlg.close()
