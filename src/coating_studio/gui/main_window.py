"""Main application window."""

from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QFileDialog, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMenu, QMessageBox, QTabWidget, QToolBar, QToolButton,
)

from coating_studio import APP_NAME, __version__
from coating_studio.comparison import (
    BEFORE_OPTIMISATION, MAX_REFERENCES, free_slot, load_measured, snapshot_design,
)
from coating_studio.core.solver import SolverError, solve
from coating_studio.examples import EXAMPLES
from coating_studio.gui.dialogs.materials import MaterialManager
from coating_studio.gui.dialogs.preferences import PreferencesDialog
from coating_studio.gui.document import Document
from coating_studio.gui.fmt import fmt_num
from coating_studio.gui.icons import icon, refresh_icons, set_icon_colors
from coating_studio.gui.panels.optimization import OptimizationPanel
from coating_studio.gui.panels.tolerance import TolerancePanel
from coating_studio.gui.plots.views import (
    AbsorptionView, AngleView, FrequencyView, MapView, MaterialView, SmithView,
)
from coating_studio.gui.settings import AppSettings
from coating_studio.gui.theme import apply_qt_theme, resolve
from coating_studio.gui.widgets.layer_stack import LayerStackWidget
from coating_studio.gui.widgets.properties import PropertiesPanel
from coating_studio.gui.widgets.sweep_panel import SweepPanel
from coating_studio import diagnostics
from coating_studio.i18n import tr
from coating_studio.materials.csvio import CsvFormatError
from coating_studio.materials.models import MaterialCycleError, OutOfRangeError
from coating_studio.project import FILE_EXTENSION, Project, ProjectError, new_project_with_example_stack

FILE_FILTER = "Coating Studio project (*.coat);;All files (*)"


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings | None = None):
        super().__init__()
        self.settings = settings or AppSettings()
        self.colors = resolve(self.settings.theme)
        self.rl_positive = self.settings.rl_positive
        self.doc = Document(new_project_with_example_stack(tr("Untitled")))
        self.results = {}
        self.result_error = None
        # Pinned reference traces (comparison curves).  They are saved with the project; a project opened
        # without saved curves keeps the ones on screen, so designs from different files can be compared.
        # Not undoable.
        self.references = []
        self._ref_counter = 0
        self.setWindowIcon(QApplication.windowIcon())
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowTabbedDocks)
        self.setDocumentMode(True)

        self._build_central()
        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_status()
        self._references_changed(user=False)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self.recompute)

        self.doc.changed.connect(self._on_doc_changed)
        self.doc.reset.connect(self._on_reset)
        self.doc.dirty_changed.connect(lambda _: self._update_title())
        self.doc.path_changed.connect(lambda _: self._update_title())

        self.resize(1440, 900)
        self._restore_window_state()
        self.apply_theme()
        self._on_reset()
        # Connected only now so that restoreState() and the first automatic show/hide above are not
        # mistaken for the user choosing to keep the dock open or closed.
        self.d_msgs.toggleViewAction().toggled.connect(self._on_msgs_dock_toggled)

    # =====================================================================
    # construction
    def _build_central(self):
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.ElideNone)
        self.v_freq = FrequencyView(self)
        self.v_angle = AngleView(self)
        self.v_map = MapView(self)
        self.v_smith = SmithView(self)
        self.v_abs = AbsorptionView(self)
        self.v_mat = MaterialView(self)
        self.p_opt = OptimizationPanel(self.doc, self)
        self.p_tol = TolerancePanel(self.doc, self)
        self.views = [self.v_freq, self.v_angle, self.v_map, self.v_smith, self.v_abs, self.v_mat,
                      self.p_tol.plot]
        for w, text in ((self.v_freq, tr("Frequency")), (self.v_angle, tr("Angle")),
                        (self.v_map, tr("Map")), (self.v_smith, tr("Smith chart")),
                        (self.v_abs, tr("Absorption")), (self.v_mat, tr("Material data")),
                        (self.p_opt, tr("Optimisation")), (self.p_tol, tr("Tolerance"))):
            self.tabs.addTab(w, text)
        self.tabs.setTabIcon(6, icon("optimize"))
        self.tabs.setTabIcon(7, icon("tolerance"))
        for v in self.views:
            v.cursorText.connect(self._on_cursor)
        self.p_opt.openProjectRequested.connect(self._open_project_object)
        self.p_opt.statusMessage.connect(lambda m: self.statusBar().showMessage(m, 8000))
        self.p_opt.runningChanged.connect(self._on_opt_running)
        self.p_tol.statusMessage.connect(lambda m: self.statusBar().showMessage(m, 8000))
        self.tabs.currentChanged.connect(self._update_export_actions)
        self.setCentralWidget(self.tabs)

    def _dock(self, title, widget, area, name):
        d = QDockWidget(title, self)
        d.setObjectName(name)
        d.setWidget(widget)
        d.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
                      | QDockWidget.DockWidgetClosable)
        self.addDockWidget(area, d)
        return d

    def _build_docks(self):
        self.w_layers = LayerStackWidget(self.doc)
        self.w_props = PropertiesPanel(self.doc)
        self.w_sweep = SweepPanel(self.doc)
        self.w_msgs = QListWidget()
        self.w_msgs.setAlternatingRowColors(True)
        self.d_layers = self._dock(tr("Layer stack"), self.w_layers, Qt.LeftDockWidgetArea, "dock_layers")
        self.d_props = self._dock(tr("Properties"), self.w_props, Qt.RightDockWidgetArea, "dock_props")
        self.d_sweep = self._dock(tr("Analysis settings"), self.w_sweep, Qt.RightDockWidgetArea, "dock_sweep")
        self.tabifyDockWidget(self.d_props, self.d_sweep)
        self.d_props.raise_()
        self.d_msgs = self._dock(tr("Diagnostics"), self.w_msgs, Qt.BottomDockWidgetArea, "dock_msgs")
        self.d_layers.setMinimumWidth(360)
        self.d_props.setMinimumWidth(320)
        self.resizeDocks([self.d_layers, self.d_props], [380, 340], Qt.Horizontal)
        self.resizeDocks([self.d_msgs], [110], Qt.Vertical)
        self.w_layers.selectionChangedUid.connect(self._on_layer_selected)
        self.w_props.editMaterialsRequested.connect(self.open_materials)

    def _action(self, text, slot, shortcut=None, icon_name=None, tip=None):
        a = QAction(text, self)
        if icon_name:
            a.setIcon(icon(icon_name))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setStatusTip(tip)
            a.setToolTip(tip)
        a.triggered.connect(slot)
        return a

    def _build_actions(self):
        self.a_new = self._action(tr("&New"), self.file_new, QKeySequence.New, "new", tr("New project"))
        self.a_open = self._action(tr("&Open…"), self.file_open, QKeySequence.Open, "open", tr("Open a project"))
        self.a_save = self._action(tr("&Save"), self.file_save, QKeySequence.Save, "save", tr("Save the project"))
        self.a_save_as = self._action(tr("Save &As…"), self.file_save_as, QKeySequence.SaveAs)
        self.a_export_fig = self._action(tr("Export &figure…"), self.export_figure, "Ctrl+E", "export",
                                         tr("Export the current plot (PNG/SVG/PDF)"))
        self.a_export_data = self._action(tr("Export &data (CSV)…"), self.export_data, "Ctrl+Shift+E")
        self.a_export_s1p = self._action(tr("Export &Touchstone (.s1p)…"), lambda: self.export_touchstone(), None,
                                         None, tr("Save the reflection coefficient S11 of the frequency sweep as a "
                                                  "Touchstone file for circuit and network-analyser tools"))
        self.a_export_report = self._action(tr("Export &report (HTML)…"), lambda: self.export_report(), None, None,
                                            tr("Save a one-page design report: targets and margins, layer stack, "
                                               "reflection plots, tolerance result and diagnostics"))
        self.a_quit = self._action(tr("&Quit"), self.close, QKeySequence.Quit)
        self.a_undo = self.doc.undo_stack.createUndoAction(self, tr("&Undo"))
        self.a_undo.setShortcut(QKeySequence.Undo)
        self.a_undo.setIcon(icon("undo"))
        self.a_redo = self.doc.undo_stack.createRedoAction(self, tr("&Redo"))
        self.a_redo.setShortcut(QKeySequence.Redo)
        self.a_redo.setIcon(icon("redo"))
        self.a_materials = self._action(tr("&Materials…"), lambda: self.open_materials(None), "Ctrl+M",
                                        "materials", tr("Open the material manager"))
        self.a_prefs = self._action(tr("&Preferences…"), self.open_preferences, QKeySequence.Preferences,
                                    "settings")
        self.a_run_opt = self._action(tr("Run &optimisation"), self.run_optimisation, "F5", "optimize",
                                      tr("Start the optimisation with the current settings"))
        self.a_stop_opt = self._action(tr("S&top optimisation"), lambda: self.p_opt.stop(), "Shift+F5", "stop")
        self.a_stop_opt.setEnabled(False)
        self.a_run_tol = self._action(tr("Run &tolerance analysis"), self.run_tolerance, "F6", "tolerance")
        self.a_pin = self._action(tr("&Pin reference"), lambda: self.pin_reference(), "Ctrl+Shift+P", "pin",
                                  tr("Pin the current design as a reference curve on the Frequency, Angle "
                                     "and Smith chart tabs"))
        self.a_import_meas = self._action(tr("Import measured curve…"), self.import_measured, None, "import",
                                          tr("Show a measured reflection-loss curve (CSV or Touchstone .s1p) on "
                                             "the Frequency tab"))
        self.a_clear_refs = self._action(tr("Remove all references"), self.clear_references)
        self.m_refs = QMenu(self)
        self.m_refs.aboutToShow.connect(self._fill_references_menu)
        self.a_refs = QAction(icon("refs"), tr("References"), self)
        self.a_refs.setMenu(self.m_refs)
        self.a_refs.setToolTip(tr("Show, hide, rename or remove reference curves"))
        self.a_about = self._action(tr("&About Coating Studio"), self.about)
        self.a_conventions = self._action(tr("Physics &conventions"), self.show_conventions, "F1")

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu(tr("&File"))
        m.addAction(self.a_new)
        m.addAction(self.a_open)
        self.m_examples = m.addMenu(tr("Open &example"))
        for key, (title, _) in EXAMPLES.items():
            self.m_examples.addAction(tr(title), lambda k=key: self.open_example(k))
        self.m_recent = m.addMenu(tr("Open &recent"))
        self.m_recent.aboutToShow.connect(self._fill_recent)
        m.addSeparator()
        m.addAction(self.a_save)
        m.addAction(self.a_save_as)
        m.addSeparator()
        m.addAction(self.a_export_fig)
        m.addAction(self.a_export_data)
        m.addAction(self.a_export_s1p)
        m.addAction(self.a_export_report)
        m.addSeparator()
        m.addAction(self.a_quit)

        m = mb.addMenu(tr("&Edit"))
        m.addAction(self.a_undo)
        m.addAction(self.a_redo)
        m.addSeparator()
        for a in (self.w_layers.act_add_slab, self.w_layers.act_add_sheet, self.w_layers.act_dup,
                  self.w_layers.act_del, self.w_layers.act_up, self.w_layers.act_down):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_materials)
        m.addAction(self.a_prefs)

        m = mb.addMenu(tr("&View"))
        for d in (self.d_layers, self.d_props, self.d_sweep, self.d_msgs):
            m.addAction(d.toggleViewAction())
        m.addSeparator()
        for i in range(self.tabs.count()):
            a = QAction(self.tabs.tabText(i), self)
            a.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
            a.triggered.connect(lambda _=False, i=i: self.tabs.setCurrentIndex(i))
            m.addAction(a)

        m = mb.addMenu(tr("&Analysis"))
        m.addAction(self.a_run_opt)
        m.addAction(self.a_stop_opt)
        m.addAction(self.a_run_tol)
        m.addSeparator()
        m.addAction(self.a_pin)
        m.addAction(self.a_import_meas)
        m.addAction(self.a_clear_refs)

        m = mb.addMenu(tr("&Help"))
        m.addAction(self.a_conventions)
        m.addAction(self.a_about)

    def _build_toolbar(self):
        tb = QToolBar(tr("Main toolbar"))
        tb.setObjectName("toolbar_main")
        tb.setIconSize(QSize(20, 20))
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        for a in (self.a_new, self.a_open, self.a_save):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.a_undo)
        tb.addAction(self.a_redo)
        tb.addSeparator()
        tb.addAction(self.w_layers.act_add_slab)
        tb.addAction(self.w_layers.act_add_sheet)
        tb.addAction(self.a_materials)
        tb.addSeparator()
        tb.addAction(self.a_run_opt)
        tb.addAction(self.a_export_fig)
        tb.addSeparator()
        tb.addAction(self.a_pin)
        tb.addAction(self.a_refs)
        btn = tb.widgetForAction(self.a_refs)
        btn.setPopupMode(QToolButton.InstantPopup)
        btn.setStyleSheet("QToolButton { padding-right: 14px; }")  # room for the menu arrow
        for a in (self.a_new, self.a_open, self.a_save, self.a_undo, self.a_redo):
            tb.widgetForAction(a).setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.addToolBar(tb)
        self.toolbar = tb

    def _build_status(self):
        sb = self.statusBar()
        self.lbl_cursor = QLabel()
        self.lbl_summary = QLabel()
        # Diagnostics summary; the dock opens by itself when there is a problem and hides when
        # there is none, unless the user has opened or closed it by hand (then it stays put).
        self.btn_diag = QToolButton()
        self.btn_diag.setAutoRaise(True)
        self.btn_diag.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_diag.setToolTip(tr("Show or hide the diagnostics panel"))
        self.btn_diag.clicked.connect(self._toggle_msgs_dock)
        self._diag_counts = (0, 0)
        self._msgs_user_pinned = False
        self._auto_msgs = False
        sb.addWidget(self.lbl_cursor, 1)
        sb.addPermanentWidget(self.btn_diag)  # permanent: showMessage() must not hide it
        sb.addPermanentWidget(self.lbl_summary)

    def _toggle_msgs_dock(self):
        self._msgs_user_pinned = True
        self.d_msgs.setVisible(not self.d_msgs.isVisible())

    def _on_msgs_dock_toggled(self, _checked):
        if not self._auto_msgs:  # View menu or the dock's close button
            self._msgs_user_pinned = True

    def _update_diag_button(self):
        n_issues, n_notes = self._diag_counts
        c = self.colors
        if n_issues:
            text = tr("1 problem") if n_issues == 1 else tr("{n} problems", n=n_issues)
            ic = icon("warning", c.warn)
        elif n_notes:
            text = tr("1 note") if n_notes == 1 else tr("{n} notes", n=n_notes)
            ic = icon("info", c.muted)
        else:
            text, ic = tr("No problems"), icon("apply", c.ok)
        self.btn_diag.setText(text)
        self.btn_diag.setIcon(ic)

    # =====================================================================
    # theme & title
    def apply_theme(self):
        app = QApplication.instance()
        apply_qt_theme(app, self.colors)
        set_icon_colors(self.colors.text, self.colors.sheet)
        self._reicon()
        refresh_icons(self)
        self.w_layers.refresh(self.colors)
        for v in self.views:
            v.mark_dirty()
        self.p_opt.retheme()
        if hasattr(self, "btn_diag"):
            self._update_diag_button()

    def _reicon(self):
        pairs = ((self.a_new, "new"), (self.a_open, "open"), (self.a_save, "save"), (self.a_undo, "undo"),
                 (self.a_redo, "redo"), (self.a_materials, "materials"), (self.a_prefs, "settings"),
                 (self.a_run_opt, "optimize"), (self.a_stop_opt, "stop"), (self.a_run_tol, "tolerance"),
                 (self.a_export_fig, "export"), (self.a_pin, "pin"), (self.a_refs, "refs"),
                 (self.a_import_meas, "import"), (self.w_layers.act_add_slab, "layer-add"),
                 (self.w_layers.act_add_sheet, "sheet-add"), (self.w_layers.act_dup, "duplicate"),
                 (self.w_layers.act_del, "delete"), (self.w_layers.act_up, "up"), (self.w_layers.act_down, "down"))
        for a, n in pairs:
            a.setIcon(icon(n))
        self.tabs.setTabIcon(6, icon("optimize"))
        self.tabs.setTabIcon(7, icon("tolerance"))

    def _update_title(self):
        star = "*" if self.doc.is_dirty else ""
        self.setWindowTitle(f"{self.doc.display_name}{star} — {APP_NAME}")
        self.setWindowModified(self.doc.is_dirty)

    # =====================================================================
    # document events
    @property
    def project(self):
        return self.doc.project

    def _on_reset(self):
        if self.project.references:  # a file with saved comparison curves shows those
            self.references = list(self.project.references)
            self._ref_counter = len(self.references)
        self.project.references = self.references
        self._references_changed(user=False)
        self.w_layers.refresh(self.colors)
        layers = self.project.structure.layers
        if layers:
            self.w_layers.select_uid(layers[0].uid)
        self.w_props.set_layer(self.w_layers.selected_uid())
        self._sync_sweep_editors()
        self.p_opt.refresh()
        self.p_tol.refresh()
        self.p_tol.invalidate()
        self.v_mat.sync_materials(reset=True)
        self._update_title()
        self.recompute()

    def _on_doc_changed(self, kind):
        if kind == "model":
            self.w_layers.refresh()
            self.w_props.set_layer(self.w_layers.selected_uid())
            self.p_opt.refresh()
            self.p_tol.refresh()
            self.p_tol.invalidate()
            self.v_mat.sync_materials()
        else:
            self.p_tol.refresh()  # its default yield band follows the optimisation targets
            self.w_props.refresh()  # RLC info shows Zs at the angle-sweep frequency
            self.p_tol.plot.mark_dirty()
            self._sync_sweep_editors()
            for v in (self.v_freq, self.v_angle, self.v_map):
                v.mark_dirty()  # target masks
        self._timer.start()

    def _sync_sweep_editors(self):
        """The dock and the plot bars edit the same sweep settings; keep them in step."""
        self.w_sweep.refresh()
        for v in self.views:
            if hasattr(v, "sync_controls"):
                v.sync_controls()

    def _on_layer_selected(self, uid):
        self.w_props.set_layer(uid)

    def _on_cursor(self, text):
        self.lbl_cursor.setText(text)

    def _on_opt_running(self, running):
        self.a_run_opt.setEnabled(not running)
        self.a_stop_opt.setEnabled(running)

    # =====================================================================
    # computation
    def _f_grid(self, n):
        return self.project.sweep.freq_grid(n)

    def recompute(self):
        p = self.project
        s = p.sweep
        self.results = {}
        self.result_error = None
        try:
            problems = p.validate()
            if problems:
                raise SolverError("; ".join(problems))
            self.results["freq"] = solve(p.structure, p.materials, self._f_grid(s.n_f), s.angle)
            self.results["angle"] = solve(p.structure, p.materials, [s.f_at], s.angle_grid())
            self.results["map"] = solve(p.structure, p.materials, self._f_grid(s.map_n_f),
                                        s.angle_grid(s.map_n_angle))
        except (SolverError, OutOfRangeError, MaterialCycleError, KeyError, ValueError) as e:
            self.results = {}
            self.result_error = tr("Cannot compute: {e}", e=e)
        for v in self.views:
            v.mark_dirty()
        self._update_summary()
        self._update_diagnostics()

    def _update_summary(self):
        p = self.project
        res = self.results.get("freq")
        thick = p.structure.total_thickness() * 1e3
        try:
            mass = p.areal_mass()
        except (KeyError, MaterialCycleError):
            mass = float("nan")
        parts = [tr("Thickness {t} mm", t=fmt_num(thick, 4)), tr("Areal mass {m} kg/m²", m=fmt_num(mass, 4))]
        if res is not None:
            r = res.quantity("R", "avg")[:, 0]
            db = 10 * np.log10(np.maximum(r, 1e-30))
            i = int(np.argmin(db))
            best = -db[i] if self.rl_positive else db[i]
            parts.insert(0, tr("Best RL {v} dB at {f} GHz", v=f"{best:.1f}", f=fmt_num(res.f[i] / 1e9, 4)))
        self.lbl_summary.setText("   ·   ".join(parts))

    def _update_diagnostics(self):
        p = self.project
        self.w_msgs.clear()
        s = p.sweep
        f = self._f_grid(min(s.n_f, 200))
        n_issues = 0
        if self.result_error:
            it = QListWidgetItem(icon("error"), self.result_error)
            self.w_msgs.addItem(it)
            n_issues += 1
        problems, notes = diagnostics.collect(p, f)
        for level, text in problems:
            self.w_msgs.addItem(QListWidgetItem(icon(level), text))
            n_issues += 1
        if not n_issues:
            self.w_msgs.addItem(QListWidgetItem(icon("info"), tr("No problems found in the materials used.")))
        for text in notes:  # informational only (e.g. built-in demo values); not counted as problems
            self.w_msgs.addItem(QListWidgetItem(icon("info"), text))
        self.d_msgs.setWindowTitle(tr("Diagnostics") + (f" ({n_issues})" if n_issues else ""))
        self._diag_counts = (n_issues, len(notes))
        self._update_diag_button()
        want = n_issues > 0
        if not self._msgs_user_pinned and self.d_msgs.isVisibleTo(self) != want:
            self._auto_msgs = True
            try:
                self.d_msgs.setVisible(want)
            finally:
                self._auto_msgs = False

    # =====================================================================
    # file handling
    def _confirm_discard(self):
        if not self.doc.is_dirty:
            return True
        r = QMessageBox.question(self, APP_NAME,
                                 tr("Save changes to “{n}”?", n=self.doc.display_name),
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if r == QMessageBox.Save:
            return self.file_save()
        return r == QMessageBox.Discard

    def _busy_guard(self):
        if self.p_opt.is_running():
            QMessageBox.information(self, APP_NAME, tr("Stop the running optimisation first."))
            return False
        return True

    def file_new(self):
        if self._busy_guard() and self._confirm_discard():
            self.doc.set_project(new_project_with_example_stack(tr("Untitled")))

    def file_open(self):
        if not (self._busy_guard() and self._confirm_discard()):
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("Open project"), self.settings.last_dir, FILE_FILTER)
        if path:
            self.load_path(path, confirm=False)

    def load_path(self, path, confirm=True):
        if confirm and not (self._busy_guard() and self._confirm_discard()):
            return False
        try:
            proj = Project.load(path)
        except (OSError, ProjectError, ValueError, KeyError, TypeError) as e:
            QMessageBox.critical(self, tr("Cannot open project"), f"{path}\n\n{e}")
            return False
        self.doc.set_project(proj, path)
        self.settings.add_recent(path)
        self.settings.last_dir = os.path.dirname(path)
        self.statusBar().showMessage(tr("Opened {p}", p=path), 5000)
        return True

    def file_save(self):
        if not self.doc.path:
            return self.file_save_as()
        return self._save_to(self.doc.path)

    def file_save_as(self):
        start = self.doc.path or os.path.join(self.settings.last_dir, self.project.name + FILE_EXTENSION)
        path, _ = QFileDialog.getSaveFileName(self, tr("Save project"), start, FILE_FILTER)
        if not path:
            return False
        if not path.lower().endswith(FILE_EXTENSION):
            path += FILE_EXTENSION
        return self._save_to(path)

    def _save_to(self, path):
        try:
            if not self.doc.path or os.path.abspath(path) != os.path.abspath(self.doc.path):
                self.project.name = os.path.splitext(os.path.basename(path))[0]
            self.doc.save(path)
        except OSError as e:
            QMessageBox.critical(self, tr("Cannot save project"), f"{path}\n\n{e}")
            return False
        self.settings.add_recent(path)
        self.settings.last_dir = os.path.dirname(path)
        self.statusBar().showMessage(tr("Saved {p}", p=path), 5000)
        return True

    def open_example(self, key):
        if not (self._busy_guard() and self._confirm_discard()):
            return
        title, builder = EXAMPLES[key]
        proj = builder()
        proj.name = tr(title)
        self.doc.set_project(proj)

    def _open_project_object(self, proj):
        if not self._confirm_discard():
            return
        proj.references = self.references  # the curves on screen, including the "Before optimisation" just pinned
        self.doc.set_project(proj)
        self.doc._settings_dirty = True
        self._update_title()

    def _fill_recent(self):
        self.m_recent.clear()
        files = self.settings.recent_files
        for path in files:
            a = self.m_recent.addAction(os.path.basename(path), lambda p=path: self.load_path(p))
            a.setToolTip(path)
            a.setEnabled(os.path.exists(path))
        if files:
            self.m_recent.addSeparator()
            self.m_recent.addAction(tr("Clear list"), self.settings.clear_recent)
        else:
            a = self.m_recent.addAction(tr("(no recent files)"))
            a.setEnabled(False)

    # =====================================================================
    # actions
    def _current_view(self):
        w = self.tabs.currentWidget()
        if w is self.p_tol:
            return self.p_tol.plot
        return w if w in self.views else None

    def _update_export_actions(self, *_):
        ok = self._current_view() is not None
        self.a_export_fig.setEnabled(ok)
        self.a_export_data.setEnabled(ok)

    def export_figure(self):
        v = self._current_view()
        if v:
            v.export_figure(self)

    def export_data(self):
        v = self._current_view()
        if v:
            v.export_data(self)

    def _export_path(self, title, suffix, file_filter):
        start = os.path.join(self.settings.last_dir, self.project.name + suffix)
        path, _ = QFileDialog.getSaveFileName(self, title, start, file_filter)
        if path and not path.lower().endswith(suffix):
            path += suffix
        return path

    def export_touchstone(self, path=None, pol=None):
        """S11 of the frequency sweep as .s1p.  One polarisation per file: asked for at oblique incidence."""
        from coating_studio.touchstone import write_design_s1p

        if pol is None:
            if abs(self.project.sweep.angle) < 1e-12:
                pol = "TE"  # TE = TM at normal incidence
            else:
                pol, ok = QInputDialog.getItem(
                    self, tr("Export Touchstone"),
                    tr("Polarisation at {a}° (a Touchstone file holds one):", a=f"{self.project.sweep.angle:g}"),
                    ["TE", "TM"], 0, False)
                if not ok:
                    return None
        if path is None:
            path = self._export_path(tr("Export Touchstone"), ".s1p", tr("Touchstone (*.s1p);;All files (*)"))
            if not path:
                return None
        try:
            n = write_design_s1p(path, self.project, pol)
        except (OSError, SolverError, OutOfRangeError, MaterialCycleError, KeyError, ValueError) as e:
            QMessageBox.critical(self, tr("Export failed"), str(e))
            return None
        self.settings.last_dir = os.path.dirname(path) or self.settings.last_dir
        self.statusBar().showMessage(tr("Saved {n} frequencies ({pol}) to {p}", n=n, pol=pol, p=path), 6000)
        return path

    def export_report(self, path=None):
        from coating_studio.report import write_report

        if path is None:
            path = self._export_path(tr("Export report"), ".html", tr("HTML (*.html);;All files (*)"))
            if not path:
                return None
        try:
            write_report(path, self.project, rl_positive=self.rl_positive, references=list(self.references),
                         tolerance=self.p_tol.plot.result, source=self.doc.path)
        except OSError as e:
            QMessageBox.critical(self, tr("Export failed"), str(e))
            return None
        self.settings.last_dir = os.path.dirname(path) or self.settings.last_dir
        self.statusBar().showMessage(tr("Saved {p}", p=path), 6000)
        return path

    def open_materials(self, select=None):
        dlg = MaterialManager(self.doc, self, select=select or None, parent=self)
        dlg.exec()

    def open_preferences(self):
        dlg = PreferencesDialog(self.settings, self)
        if not dlg.exec():
            return
        lang, theme, rl = dlg.values()
        old_lang = self.settings.language
        self.settings.language, self.settings.theme, self.settings.rl_positive = lang, theme, rl
        self.colors = resolve(theme)
        self.apply_theme()
        self.set_rl_positive(rl)
        if lang != old_lang:
            QMessageBox.information(self, APP_NAME, tr("The new language will be used after a restart."))

    # =====================================================================
    # reference traces
    def _add_reference(self, ref):
        self.references.append(ref)
        self._references_changed()

    def _set_references(self, refs):
        self.references[:] = refs  # in place: the project holds the same list and saves it

    def _references_changed(self, user=True):
        if user:
            self.doc.mark_dirty()  # comparison curves are saved with the file
        n = len(self.references)
        self.a_refs.setText(tr("References ({n})", n=n) if n else tr("References"))
        self.a_clear_refs.setEnabled(bool(n))
        for v in (self.v_freq, self.v_angle, self.v_smith):
            v.mark_dirty()

    def pin_reference(self, name=None):
        """Pin the current design; returns the new reference or None when all slots are taken."""
        slot = free_slot(self.references)
        if slot is None:
            self.statusBar().showMessage(
                tr("All {n} reference slots are in use; remove one first.", n=MAX_REFERENCES), 8000)
            return None
        if name is None:
            self._ref_counter += 1
            name = tr("Reference {n}", n=self._ref_counter)
        ref = snapshot_design(self.project, name, slot)
        self._add_reference(ref)
        self.statusBar().showMessage(tr("Pinned “{name}”. It follows the current sweep settings.", name=name), 6000)
        return ref

    def pin_before_optimisation(self):
        """Called by the optimiser just before a result replaces the design."""
        name = tr(BEFORE_OPTIMISATION)
        self._set_references([r for r in self.references if not (r.kind == "design" and r.name == name)])
        if self.pin_reference(name) is None:
            self._references_changed()
            self.statusBar().showMessage(
                tr("The design before optimisation was not pinned: all {n} reference slots are in use.",
                   n=MAX_REFERENCES), 8000)

    def import_measured(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, tr("Import measured curve"), "",
                                                  tr("Measured data (*.csv *.txt *.dat *.s1p);;All files (*)"))
            if not path:
                return None
        slot = free_slot(self.references)
        if slot is None:
            QMessageBox.information(self, tr("References"),
                                    tr("All {n} reference slots are in use; remove one first.", n=MAX_REFERENCES))
            return None
        try:
            ref, positive = load_measured(path)
        except (CsvFormatError, OSError, ValueError, UnicodeDecodeError) as e:
            QMessageBox.critical(self, tr("Import failed"), str(e))
            return None
        ref.slot = slot
        self._add_reference(ref)
        self.statusBar().showMessage(
            tr("Imported “{name}” (read as positive return loss).", name=ref.name) if positive else
            tr("Imported “{name}” (read as 20·log₁₀|Γ|, negative = good).", name=ref.name), 8000)
        return ref

    def remove_reference(self, ref):
        self._set_references([r for r in self.references if r is not ref])
        self._references_changed()

    def clear_references(self):
        self._set_references([])
        self._references_changed()

    def set_reference_visible(self, ref, visible):
        ref.visible = bool(visible)
        self._references_changed()

    def rename_reference(self, ref):
        name, ok = QInputDialog.getText(self, tr("Rename reference"), tr("Name"), text=ref.name)
        if ok and name.strip():
            ref.name = name.strip()
            self._references_changed()

    def _fill_references_menu(self):
        m = self.m_refs
        m.clear()
        if not self.references:
            a = m.addAction(tr("No references yet"))
            a.setEnabled(False)
        for ref in self.references:
            sub = m.addMenu(ref.name + ("" if ref.kind == "design" else "  " + tr("(measured)")))
            a = sub.addAction(tr("Show"))
            a.setCheckable(True)
            a.setChecked(ref.visible)
            a.toggled.connect(lambda on, r=ref: self.set_reference_visible(r, on))
            sub.addAction(tr("Rename…"), lambda r=ref: self.rename_reference(r))
            sub.addAction(tr("Remove"), lambda r=ref: self.remove_reference(r))
        m.addSeparator()
        m.addAction(self.a_pin)
        m.addAction(self.a_import_meas)
        m.addAction(self.a_clear_refs)

    def set_rl_positive(self, positive):
        """Switch the RL display convention everywhere (values stay negative dB internally)."""
        self.rl_positive = bool(positive)
        for v in self.views:
            if hasattr(v, "on_rl_sign_changed"):
                v.on_rl_sign_changed()
            v.mark_dirty()
        self.p_opt.refresh()
        self.p_tol.refresh()
        self._update_summary()

    def run_optimisation(self):
        self.tabs.setCurrentWidget(self.p_opt)
        self.p_opt.run()

    def run_tolerance(self):
        self.tabs.setCurrentWidget(self.p_tol)
        self.p_tol.run()

    def about(self):
        QMessageBox.about(self, tr("About Coating Studio"), tr(
            "<h3>Coating Studio {v}</h3>"
            "<p>Multilayer coating simulator and optimiser — v1 focuses on microwave and radar absorbers.</p>"
            "<p>Transmission-line (impedance) recursion for planar stacks, oblique TE/TM incidence, "
            "dispersive and measured materials, effective-medium mixtures, differential-evolution "
            "optimisation and Monte-Carlo tolerance analysis.</p>"
            "<p>MIT License.</p>", v=__version__))

    def show_conventions(self):
        QMessageBox.information(self, tr("Physics conventions"), tr(
            "<b>Time convention</b>: e<sup>+jωt</sup>; ε = ε′ − jε″, μ = μ′ − jμ″ (ε″, μ″ &gt; 0 are lossy).<br>"
            "<b>Reflection loss</b>: RL = 20·log₁₀|Γ| (negative dB; −10 dB ≈ 90% absorbed). "
            "The display sign can be changed in Preferences.<br>"
            "<b>Γ</b> is the reflection coefficient of the tangential electric field.<br>"
            "<b>Layer order</b>: the top row of the layer stack faces the incident wave.<br>"
            "<b>TE</b>: E perpendicular to the plane of incidence; <b>TM</b>: H perpendicular. "
            "Average = unpolarised power average.<br>"
            "<b>Resistive sheet</b>: shunt impedance Zs = R + jX in Ω/sq (free space ≈ 376.7 Ω/sq), or a "
            "series RLC circuit Zs = R + jωL + 1/(jωC) (inductive X &gt; 0). The RLC values are "
            "normal-incidence lumped values used for every angle and polarisation - valid for "
            "sub-wavelength unit cells below the grating-lobe onset.<br>"
            "<b>Units</b>: GHz, mm, degrees, S/m, g/cm³; the engine works in SI."))

    # =====================================================================
    # window state
    def _restore_window_state(self):
        q = QSettings()
        g = q.value("window/geometry")
        s = q.value("window/state")
        if g is not None:
            self.restoreGeometry(g)
        if s is not None:
            self.restoreState(s)

    def closeEvent(self, e):
        if self.p_opt.is_running():
            r = QMessageBox.question(self, APP_NAME, tr("An optimisation is running. Stop it and quit?"))
            if r != QMessageBox.Yes:
                e.ignore()
                return
        if not self._confirm_discard():
            e.ignore()
            return
        self.p_opt.shutdown()
        self.p_tol.shutdown()
        q = QSettings()
        q.setValue("window/geometry", self.saveGeometry())
        q.setValue("window/state", self.saveState())
        e.accept()
