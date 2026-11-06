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
    dlg.c_tde.setValue(0.05)  # tan d_eps keeps eps' and sets eps''; n, k follow
    m = w.project.materials[dlg.current]
    assert (m.eps_re, m.eps_loss) == pytest.approx((4.0, 0.2))
    assert dlg.c_k.value() > 0
    dlg.c_mr.setValue(2.0)
    dlg.c_tdm.setValue(0.1)
    m = w.project.materials[dlg.current]
    assert m.mu_loss == pytest.approx(0.2)
    dlg.c_k.setValue(0.0)  # n, k edit -> eps'' = 0 -> tan d_eps follows
    assert dlg.c_tde.value() == pytest.approx(0.0, abs=1e-12)
    dlg.c_er.setValue(-2.0)  # metal-like: tan d undefined, field disabled
    assert not dlg.c_tde.isEnabled()
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


def test_rl_sign_convention_everywhere(app):
    """Batch 2 / A: the positive-dB preference reaches every RL input, label and export."""
    from coating_studio.examples import EXAMPLES
    from coating_studio.gui.main_window import MainWindow
    from coating_studio.optimize.optimizer import ObjectiveTerms, OptimizationResult
    from coating_studio.tolerance import ToleranceResult

    w = MainWindow()
    w.show()
    w.doc.set_project(EXAMPLES["jaumann2"][1]())
    p = w.project
    p.optimization.rl_ref_db, p.tolerance.target_db = -20.0, -10.0
    w.p_opt.result = OptimizationResult(values={}, choices={}, terms=ObjectiveTerms(-23.5, 0.01, 0.01, 1.0, 0.5))
    w.set_rl_positive(False)
    assert w.p_opt.rl_ref.value() == -20 and w.p_tol.target.value() == -10
    assert w.p_opt.tbl_res.item(0, 1).text().startswith("-23.50")
    w.set_rl_positive(True)
    # switching the range must not write a clamped value back into the project
    assert p.optimization.rl_ref_db == -20.0 and p.tolerance.target_db == -10.0
    assert w.p_opt.rl_ref.value() == 20 and w.p_tol.target.value() == 10
    assert "≥" in w.p_tol.lbl_target.text() and "positive" in w.p_opt.lbl_rl_hint.text()
    assert w.p_opt.tbl_res.item(0, 1).text().startswith("23.50")
    assert w.v_freq.chk_target.text() == "10 dB line"
    # a user edit in the positive convention is stored as negative dB
    w.p_opt.rl_ref.setValue(25.0)  # like typing: valueChanged -> valueEdited
    w.p_tol.target.setValue(15.0)
    assert p.optimization.rl_ref_db == -25.0 and p.tolerance.target_db == -15.0
    # tolerance CSV keeps lower <= median <= upper in both conventions
    import numpy as np
    f = np.array([8e9, 9e9])
    w.p_tol.plot.result = ToleranceResult(f=f, nominal_db=np.array([-20., -25.]), median_db=np.array([-19., -24.]),
                                          lower_db=np.array([-30., -35.]), upper_db=np.array([-12., -15.]),
                                          worst_db=np.array([]), yield_fraction=0.5, n_samples=10)
    for pos in (False, True):
        w.set_rl_positive(pos)
        _, rows = w.p_tol.plot.data_table()
        for row in rows:
            lo, med, hi = float(row[3]), float(row[2]), float(row[4])
            assert lo <= med <= hi
        assert (float(rows[0][1]) > 0) == pos
    w.set_rl_positive(False)
    w.doc._settings_dirty = False
    w.doc.undo_stack.setClean()
    w.close()


def test_inline_sweep_controls(app):
    """Batch 2 / B: angle/frequency on the plot bars and the Analysis dock stay in step."""
    from coating_studio.examples import EXAMPLES
    from coating_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.show()
    w.doc.set_project(EXAMPLES["jaumann2"][1]())
    assert w.v_freq.sp_sweep.value() == w.project.sweep.angle
    assert w.v_angle.sp_sweep.value() == w.project.sweep.f_at / 1e9
    w.v_freq.sp_sweep.setValue(30.0)  # user edit on the plot bar
    assert w.project.sweep.angle == 30.0 and w.w_sweep.angle.value() == 30.0
    assert not w.doc.undo_stack.canUndo()  # sweep settings are not undoable, like in the dock
    w.w_sweep.f_at.setValue(12.5)  # user edit in the dock
    assert w.project.sweep.f_at == 12.5e9 and w.v_angle.sp_sweep.value() == 12.5
    w.v_angle.sp_sweep.setValue(7.3)
    assert abs(w.project.sweep.f_at - 7.3e9) < 1 and w.v_angle.sp_sweep.value() == 7.3
    assert w.v_freq.sp_sweep.maximumWidth() <= 120  # does not stretch across the plot bar
    w.recompute()
    for v in (w.v_freq, w.v_smith, w.v_abs):
        w.tabs.setCurrentWidget(v)
        _pump(app, 30)
        assert any("30°" in ax.get_title(loc="left") for ax in v.fig.axes), type(v).__name__
    w.doc._settings_dirty = False
    w.doc.undo_stack.setClean()
    w.close()


def test_diagnostics_dock_auto_visibility(app):
    """Batch 2 / C: the dock appears for problems, hides when clean, and obeys a manual choice."""
    import numpy as np

    from coating_studio.core import SlabLayer
    from coating_studio.examples import EXAMPLES
    from coating_studio.gui.main_window import MainWindow
    from coating_studio.materials import TabulatedMaterial

    w = MainWindow()
    w.show()
    w.doc.set_project(EXAMPLES["jaumann2"][1]())
    w.recompute()
    _pump(app, 20)
    assert not w.d_msgs.isVisible() and w.btn_diag.text() == "1 note"  # demo PMI foam only
    p = EXAMPLES["jaumann2"][1]()
    p.add_material(TabulatedMaterial("Narrow", np.array([1e9, 2e9]), [3, 3], [0.1, 0.1]))
    p.structure.layers.append(SlabLayer("Narrow", 1e-3))  # data stops at 2 GHz, sweep goes to 20
    w.doc.set_project(p)
    w.recompute()
    _pump(app, 20)
    assert w.d_msgs.isVisible() and "problem" in w.btn_diag.text()  # range error (+ solve error)
    w.doc.set_project(EXAMPLES["jaumann2"][1]())
    w.recompute()
    _pump(app, 20)
    assert not w.d_msgs.isVisible()  # back to clean: hidden again
    assert not w._msgs_user_pinned
    w.btn_diag.click()  # the user opens it by hand: it stays open
    w.recompute()
    _pump(app, 20)
    assert w.d_msgs.isVisible() and w._msgs_user_pinned
    w.doc._settings_dirty = False
    w.doc.undo_stack.setClean()
    w.close()
