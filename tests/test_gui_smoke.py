"""Offscreen GUI smoke test: build the window, exercise every view and a short optimisation."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


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
    a = QApplication.instance() or QApplication([])
    from coating_studio.gui.fonts import configure_matplotlib_fonts

    configure_matplotlib_fonts()
    yield a


def _pump(app, ms=50):
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


@pytest.mark.parametrize("lang", ["en", "ko"])
def test_main_window_all_tabs(app, lang):
    from coating_studio.examples import EXAMPLES
    from coating_studio.gui.main_window import MainWindow
    from coating_studio.i18n import set_language

    set_language(lang)
    w = MainWindow()
    w.show()
    for key in EXAMPLES:
        w.doc.set_project(EXAMPLES[key][1]())
        for i in range(w.tabs.count()):
            w.tabs.setCurrentIndex(i)
            _pump(app, 10)
        assert w.results.get("freq") is not None, w.result_error
    # editing + undo
    n = len(w.project.structure.layers)
    w.w_layers.add_sheet()
    assert len(w.project.structure.layers) == n + 1
    w.doc.undo_stack.undo()
    assert len(w.project.structure.layers) == n
    w.doc.undo_stack.redo()
    assert len(w.project.structure.layers) == n + 1
    w.doc._settings_dirty = False
    w.doc.undo_stack.setClean()
    w.close()
    set_language("en")


def test_review_fixes(app):
    """UI defects found in the practical-use review (ux-quick-fixes)."""
    from PySide6.QtWidgets import QPushButton

    from coating_studio.examples import EXAMPLES
    from coating_studio.gui.dialogs.materials import MaterialManager
    from coating_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.show()
    w.doc.set_project(EXAMPLES["dallenbach"][1]())
    w.v_mat.cb_mat.setCurrentText("PTFE")  # user looks at an unused material ...
    w.doc.set_project(EXAMPLES["jaumann2"][1]())
    assert w.v_mat.cb_mat.currentText() == "PMI foam"  # ... a new project shows one it uses
    w.recompute()
    texts = [w.w_msgs.item(i).text() for i in range(w.w_msgs.count())]
    assert any(t.startswith("PMI foam:") and "demonstration" in t for t in texts)
    assert "(" not in w.d_msgs.windowTitle()  # info notes are not counted as problems
    hdr = w.p_tol.tbl.horizontalHeader()
    fm = hdr.fontMetrics()
    for c in range(1, 5):
        label = w.p_tol.tbl.horizontalHeaderItem(c).text()
        assert hdr.sectionSize(c) >= fm.horizontalAdvance(label), label
    dlg = MaterialManager(w.doc, w)
    assert isinstance(dlg.btn_lib, QPushButton) and dlg.btn_lib.menu() is not None
    dlg.close()
    w.doc._settings_dirty = False
    w.doc.undo_stack.setClean()
    w.close()


def test_optimisation_runs_in_background(app):
    from coating_studio.examples import EXAMPLES
    from coating_studio.gui.main_window import MainWindow

    w = MainWindow()
    p = EXAMPLES["salisbury"][1]()
    p.optimization.maxiter = 15
    w.doc.set_project(p)
    w.p_opt.run()
    for _ in range(400):
        _pump(app, 25)
        if not w.p_opt.is_running():
            break
    assert not w.p_opt.is_running()
    assert w.p_opt.result is not None and w.p_opt.result.terms is not None
    w.p_opt._apply()
    assert w.doc.undo_stack.count() == 1
    w.doc._settings_dirty = False
    w.doc.undo_stack.setClean()
    w.close()


def test_material_manager_and_tolerance(app):
    from coating_studio.examples import EXAMPLES
    from coating_studio.gui.dialogs.materials import MaterialManager
    from coating_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.doc.set_project(EXAMPLES["carbon"][1]())
    dlg = MaterialManager(w.doc, w)
    for i in range(dlg.lst.count()):
        dlg.lst.setCurrentRow(i)
    dlg._new("dispersive")
    assert any(n.startswith("New dispersive") for n in w.project.materials)
    dlg._new("constant")
    dlg.c_n.setValue(1.38)  # user edit -> valueEdited -> eps = n^2
    dlg.c_k.setValue(0.01)
    m = w.project.materials[dlg.current]
    assert (m.eps_re, m.eps_loss) == pytest.approx((1.38 ** 2 - 0.01 ** 2, 2 * 1.38 * 0.01))
    dlg.c_er.setValue(4.0)  # editing eps refreshes n, k
    dlg.c_el.setValue(0.0)
    assert (dlg.c_n.value(), dlg.c_k.value()) == pytest.approx((2.0, 0.0))
    dlg.close()
    w.p_tol.n.setValue(20)
    w.p_tol.run()
    for _ in range(400):
        _pump(app, 25)
        if w.p_tol.thread is None:
            break
    assert w.p_tol.plot.result is not None
    w.doc._settings_dirty = False
    w.doc.undo_stack.setClean()
    w.close()
