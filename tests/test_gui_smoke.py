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
    for c in range(1, w.p_tol.tbl.columnCount()):
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
    assert w.v_freq.chk_target.text() == "10 dB" and w.v_freq.chk_target.toolTip() == "10 dB line"
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


def test_reference_traces(app, tmp_path):
    """Pinned design references and measured curves on the Frequency, Angle and Smith tabs."""
    import numpy as np

    from coating_studio.comparison import MAX_REFERENCES, free_slot, snapshot_design
    from coating_studio.examples import EXAMPLES
    from coating_studio.gui.main_window import MainWindow
    from coating_studio.materials import TabulatedMaterial
    from coating_studio.optimize.optimizer import ObjectiveTerms, OptimizationResult

    def labels(view):
        w.tabs.setCurrentWidget(view)
        view.redraw()
        return [ln.get_label() for ax in view.fig.axes for ln in ax.get_lines()]

    w = MainWindow()
    w.show()
    w.doc.set_project(EXAMPLES["jaumann2"][1]())
    ref = w.pin_reference("A")
    assert ref is not None and ref.slot == 0
    w.doc.edit("thin", lambda p: setattr(p.structure.layers[1], "thickness", 4e-3))
    w.recompute()
    assert "A" in labels(w.v_freq) and "A" in labels(w.v_smith)  # normal incidence: one curve, no suffix
    assert any(lab.startswith("A (") for lab in labels(w.v_angle))  # oblique: polarisation named
    # the reference is re-solved under the current sweep, the live design is not affected
    key_before = ref._cache_key
    w.doc.edit("thinner", lambda p: setattr(p.structure.layers[3], "thickness", 3e-3))
    w.recompute()
    labels(w.v_freq)
    assert ref._cache_key == key_before  # model edit: no reference re-solve
    w.v_freq.sp_sweep.setValue(45.0)
    w.recompute()
    labs = labels(w.v_freq)
    assert "A (TE)" in labs and "A (TM)" in labs and ref._cache_key != key_before
    # export: one extra column per reference and polarisation
    header, _ = w.v_freq.data_table()
    assert "RL TE (A)" in header and "RL TM (A)" in header
    # legend stays when the live curves are hidden
    for b in w.v_freq.pol_boxes.values():
        b.setChecked(False)
    w.v_freq.redraw()
    assert w.v_freq.fig.axes[0].get_legend() is not None
    for pol, b in w.v_freq.pol_boxes.items():
        b.setChecked(pol != "avg")
    w.v_freq.sp_sweep.setValue(0.0)
    # hide / survive project switch
    w.set_reference_visible(ref, False)
    assert "A" not in labels(w.v_freq)
    w.set_reference_visible(ref, True)
    w.doc.set_project(EXAMPLES["dallenbach"][1]())
    w.recompute()
    assert "A" in labels(w.v_freq)
    # a reference that cannot be solved on the frequency sweep: amber warning, live curves still drawn
    p = EXAMPLES["dallenbach"][1]()
    p.add_material(TabulatedMaterial("Narrow", np.array([8e9, 12e9]), [4, 4], [0.2, 0.2]))
    p.structure.layers[0].material = "Narrow"
    bad = snapshot_design(p, "narrow", free_slot(w.references))
    w._add_reference(bad)
    labs = labels(w.v_freq)
    assert "TE" in labs and not w.v_freq.banner.isHidden()
    assert w.colors.warn in w.v_freq.banner.styleSheet()
    labels(w.v_angle)
    assert w.v_angle.banner.isHidden()  # 10 GHz is inside the data: fine on the angle tab
    w.remove_reference(bad)
    # measured curve: Frequency tab only, sign detected
    csv = tmp_path / "meas.csv"
    csv.write_text("f [GHz], RL [dB]\n2, 0.5\n10, 25\n18, 4\n", encoding="utf-8")
    meas = w.import_measured(str(csv))
    assert meas is not None and np.allclose(meas.rl_meas_db, [-0.5, -25, -4])
    assert "meas (measured)" in labels(w.v_freq)
    assert not any(lab.startswith("meas") for lab in labels(w.v_angle) + labels(w.v_smith))
    # positive-dB preference applies to references too
    w.set_rl_positive(True)
    w.v_freq.redraw()
    line = [ln for ln in w.v_freq.fig.axes[0].get_lines() if ln.get_label() == "meas (measured)"][0]
    assert line.get_ydata().max() == 25
    w.set_rl_positive(False)
    # optimiser apply pins "Before optimisation" (replacing an older one)
    w.p_opt.result = OptimizationResult(values={}, choices={}, terms=ObjectiveTerms(-20, 0.01, 0.002, 1, 0.5))
    w.p_opt._apply()
    w.p_opt._apply()
    assert [r.name for r in w.references].count("Before optimisation") == 1
    # slot cap: never blocks, colour slots are reused
    while w.pin_reference() is not None:
        pass
    assert len(w.references) == MAX_REFERENCES
    w.p_opt._apply()  # full: skipped with a status note, apply still works
    assert len(w.references) == MAX_REFERENCES
    gone = w.references[1]
    w.remove_reference(gone)
    assert w.pin_reference("again").slot == gone.slot
    assert w.a_refs.text() == f"References ({MAX_REFERENCES})"
    w.clear_references()
    assert w.a_refs.text() == "References"
    w.doc._settings_dirty = False
    w.doc.undo_stack.setClean()
    w.close()


def test_optimisation_targets_editor(app):
    """Spec targets: list + editor, sign preference, results per target, mask, tolerance band."""
    from matplotlib.collections import LineCollection
    from PySide6.QtCore import Qt

    from coating_studio.examples import EXAMPLES
    from coating_studio.gui.main_window import MainWindow
    from coating_studio.gui.panels.tolerance import yield_intervals
    from coating_studio.optimize.optimizer import ObjectiveTerms, OptimizationResult

    w = MainWindow()
    w.show()
    w.doc.set_project(EXAMPLES["dualband"][1]())
    po, s = w.p_opt, w.project.optimization
    assert po.tbl_targets.rowCount() == 2 and "≤ -20 dB" in po.tbl_targets.item(0, 1).text()
    po.tbl_targets.selectRow(1)
    assert po.a_max.value() == 45 and po.goal.value() == -10
    w.set_rl_positive(True)
    assert po.goal.value() == 10 and "≥" in po.lbl_goal.text()
    po.goal.setValue(12.0)  # user edit in positive dB on the selected (second) target only
    assert s.targets[1].goal_db == -12.0 and s.targets[0].goal_db == -20.0
    assert "≥ 12 dB" in po.tbl_targets.item(1, 1).text()
    w.set_rl_positive(False)
    # add, duplicate, remove, enable/disable, preset
    po.btn_t_dup.click()
    assert len(s.targets) == 3 and s.targets[2] == s.targets[1] and s.targets[2] is not s.targets[1]
    assert po.tbl_targets.currentRow() == 2
    po.btn_t_preset.menu().actions()[3].trigger()  # X: 8-12 GHz
    assert (s.targets[2].f_min, s.targets[2].f_max) == (8e9, 12e9)
    po.btn_t_del.click()
    assert len(s.targets) == 2
    po.tbl_targets.item(1, 0).setCheckState(Qt.Unchecked)
    assert not s.targets[1].enabled
    assert yield_intervals(w.project) == [(8e9, 12e9)]  # tolerance follows the enabled targets
    po.tbl_targets.item(1, 0).setCheckState(Qt.Checked)
    assert yield_intervals(w.project) == [(8e9, 12e9), (12e9, 18e9)]
    assert w.p_tol.b_hi.value() == 18  # refreshed on the settings change
    # per-target result rows; row 0 is still the overall worst RL
    w.p_opt.result = OptimizationResult(values={}, choices={}, terms=ObjectiveTerms(
        -15.0, 0.01, 0.0145, 0.75, -0.2, 1.5, ((-21.0, -1.0), (-8.5, 1.5))))
    w.p_opt.refresh()
    texts = [w.p_opt.tbl_res.item(r, 0).text() for r in range(w.p_opt.tbl_res.rowCount())]
    assert texts[0] == "Worst-case RL in band" and texts[1].startswith("Target 1:") and texts[2].startswith("Target 2:")
    assert "missed by 1.50 dB" in w.p_opt.tbl_res.item(2, 1).text()
    # spec mask on the Frequency tab: both targets apply at 0°, only Ku at 30°
    def mask_segments():
        w.tabs.setCurrentWidget(w.v_freq)
        w.v_freq.redraw()
        return sum(len(c.get_segments()) for c in w.v_freq.fig.axes[0].collections if isinstance(c, LineCollection))
    w.recompute()
    assert mask_segments() == 2
    w.v_freq.sp_sweep.setValue(30.0)
    w.recompute()
    assert mask_segments() == 1
    w.v_freq.chk_mask.setChecked(False)
    assert mask_segments() == 0
    # the last target cannot be removed
    while len(s.targets) > 1:
        po.btn_t_del.click()
    assert not po.btn_t_del.isEnabled()
    w.doc._settings_dirty = False
    w.doc.undo_stack.setClean()
    w.close()


def test_rlc_sheet_editing(app):
    """Series-RLC sheets in the Properties panel, layer stack and optimiser."""
    from coating_studio.examples import EXAMPLES
    from coating_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.show()
    w.doc.set_project(EXAMPLES["cara"][1]())
    sheet = w.project.structure.layers[0]
    w.w_layers.select_uid(sheet.uid)
    w.w_props.set_layer(sheet.uid)
    pp = w.w_props
    assert pp.cb_model.currentData() == "rlc" and not pp.row_X.isVisibleTo(pp) and pp.row_L.isVisibleTo(pp)
    assert pp.sp_L.value() == pytest.approx(4.0) and pp.sp_C.value() == pytest.approx(0.08)
    assert "f₀ =" in pp.lbl_info.text() and "Q =" in pp.lbl_info.text()
    assert w.w_layers.table.item(0, 2).text().startswith("RLC · f₀") and "L 4 nH" in w.w_layers.table.item(0, 3).toolTip()
    pp.sp_L.setValue(5.0)  # user edit in nH
    assert sheet.L == pytest.approx(5e-9)
    # the info line follows the angle-sweep frequency (a settings change)
    w.w_sweep.f_at.setValue(12.0)
    assert "Zs(12 GHz)" in pp.lbl_info.text()
    # removing the capacitor drops its optimisation variable in the same undoable edit
    paths = lambda: [tuple(v.path) for v in w.project.optimization.variables]  # noqa: E731
    assert ("layer", sheet.uid, "C") in paths()
    pp.chk_C.setChecked(False)
    assert sheet.C is None and ("layer", sheet.uid, "C") not in paths() and "Inductive grid" in pp.lbl_info.text()
    w.doc.undo_stack.undo()
    sheet = w.project.structure.layers[0]
    assert sheet.C == pytest.approx(0.08e-12) and ("layer", sheet.uid, "C") in paths()
    # model switch to constant drops L and C variables; back to RLC keeps the values
    pp.set_layer(sheet.uid)
    pp.cb_model.setCurrentIndex(0)
    pp.cb_model.activated.emit(0)
    sheet = w.project.structure.layers[0]
    assert sheet.model == "constant" and not any(p[2] in ("L", "C") for p in paths() if p[1] == sheet.uid)
    assert pp.row_X.isVisibleTo(pp)
    # a new sheet switched to RLC starts at ~10 GHz; Opt. bounds span a decade each way (log search)
    w.w_layers.add_sheet()
    new = [ly for ly in w.project.structure.layers if ly.uid not in (sheet.uid,) and hasattr(ly, "model")][-1]
    pp.set_layer(new.uid)
    pp.cb_model.setCurrentIndex(1)
    pp.cb_model.activated.emit(1)
    new = w.project.structure.layer_by_uid(new.uid)
    assert (new.L, new.C) == (5e-9, 0.05e-12) and abs(new.resonance() / 1e9 - 10.07) < 0.01
    pp.set_layer(new.uid)
    pp.opt_L.setChecked(True)
    v = [v for v in w.project.optimization.variables if tuple(v.path) == ("layer", new.uid, "L")][0]
    assert v.upper / v.lower == pytest.approx(100)
    # duplicating keeps the model
    w.w_layers.select_uid(new.uid)
    w.w_layers.act_dup.trigger()
    dup = w.project.structure.layers[w.project.structure.index_of(new.uid) + 1]
    assert dup.model == "rlc" and dup.L == new.L and dup.C == new.C and dup.uid != new.uid
    w.recompute()
    assert w.results.get("freq") is not None, w.result_error
    w.doc._settings_dirty = False
    w.doc.undo_stack.setClean()
    w.close()


def test_loss_tolerance_panel(app):
    """Independent ε″/μ″ tolerances: default rows with Follow checkboxes and a 7-column table."""
    from coating_studio.examples import EXAMPLES
    from coating_studio.gui.main_window import MainWindow
    from coating_studio.project import Project

    w = MainWindow()
    w.show()
    w.doc.set_project(EXAMPLES["dallenbach"][1]())
    pt, s = w.p_tol, w.project.tolerance
    assert s.eps_loss == 0.10 and not pt.follow["eps_loss"].isChecked() and pt.d["eps_loss"].value() == 10
    pt.d["eps_loss"].setValue(20.0)  # user edit
    assert s.eps_loss == pytest.approx(0.20)
    pt.follow["eps_loss"].setChecked(True)  # follow eps': back to the correlated model
    assert s.eps_loss is None and not pt.d["eps_loss"].isEnabled()
    assert pt.d["eps_loss"].value() == pytest.approx(s.eps * 100)  # shows the factor it follows
    pt.follow["eps_loss"].setChecked(False)
    assert s.eps_loss == pytest.approx(s.eps) and pt.d["eps_loss"].isEnabled()
    # a schema-3 project (no loss keys) opens in the correlated mode with both boxes checked
    d = EXAMPLES["dallenbach"][1]().to_dict()
    d["tolerance"].pop("eps_loss")
    d["tolerance"].pop("mu_loss")
    w.doc.set_project(Project.from_dict(d))
    assert pt.follow["eps_loss"].isChecked() and pt.follow["mu_loss"].isChecked()
    # 7-column per-layer table; a loss cell overrides one layer
    assert pt.tbl.columnCount() == 7 and pt.tbl.horizontalHeaderItem(3).text() == "ε″"
    pt.tbl.item(0, 3).setText("25")
    uid = w.project.structure.layers[0].uid
    assert w.project.tolerance.per_layer[uid]["eps_loss"] == pytest.approx(0.25)
    w.doc._settings_dirty = False
    w.doc.undo_stack.setClean()
    w.close()
