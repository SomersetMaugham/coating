"""Optimisation tab: settings, variables, run/stop, live convergence and results."""

from __future__ import annotations

import math

import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter,
    QMenu, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from coating_studio import lengths
from coating_studio.gui import spectral
from coating_studio.gui.fmt import fmt_num, param_label, rl_display, unit_label
from coating_studio.gui.icons import set_button_icon
from coating_studio.gui.theme import mpl_rc
from coating_studio.gui.widgets.inputs import SciSpinBox, muted
from coating_studio.gui.widgets.properties import default_lc_bounds
from coating_studio.gui.workers import OptimizationWorker, start_worker
from coating_studio.i18n import issue_text, tr
from coating_studio.optimize import MAX_ENUMERATED_COMBOS, OptimizationError, apply_result, preflight
from coating_studio.project import (
    BandTarget, ContinuousVariable, available_params, get_param, param_unit,
)

# IEEE Std 521 radar letter bands [GHz] (not waveguide bands: X is 8-12, WR-90 is 8.2-12.4)
IEEE_BANDS = (("L", 1, 2), ("S", 2, 4), ("C", 4, 8), ("X", 8, 12), ("Ku", 12, 18), ("K", 18, 27),
              ("Ka", 27, 40))


class OptimizationPanel(QWidget):
    openProjectRequested = Signal(object)
    statusMessage = Signal(str)
    runningChanged = Signal(bool)

    def __init__(self, doc, ctx, parent=None):
        super().__init__(parent)
        self.doc, self.ctx = doc, ctx
        self._loading = False
        self.thread = None
        self.worker = None
        self.result = None
        self.result_project = None
        self._history = []

        split = QSplitter(Qt.Horizontal, self)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(split)

        # ---------------- left: settings --------------------------------------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        left = QWidget()
        scroll.setWidget(left)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 8, 8)
        ll.setSpacing(10)

        # ---- spec targets: compact list + a 3-row editor for the selected target -------------
        g = QGroupBox(tr("Targets"))
        tl = QVBoxLayout(g)
        self.tbl_targets = QTableWidget(0, 2)
        self.tbl_targets.horizontalHeader().setVisible(False)
        self.tbl_targets.verticalHeader().setVisible(False)
        self.tbl_targets.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tbl_targets.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_targets.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_targets.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl_targets.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_targets.setMaximumHeight(104)
        self.tbl_targets.setToolTip(tr("Each row is one requirement; the optimiser minimises the worst "
                                       "margin (worst RL minus goal) over the enabled rows."))
        self.tbl_targets.itemSelectionChanged.connect(self._on_target_selected)
        self.tbl_targets.itemChanged.connect(self._on_target_toggled)
        tl.addWidget(self.tbl_targets)
        br = QHBoxLayout()
        self.btn_t_add = QPushButton(tr("Add"))
        set_button_icon(self.btn_t_add, "add")
        self.btn_t_dup = QPushButton(tr("Duplicate"))
        self.btn_t_del = QPushButton(tr("Remove"))
        self.btn_t_preset = QPushButton(tr("Band preset"))
        pm = QMenu(self)
        for band, lo, hi in IEEE_BANDS:
            pm.addAction(f"{band}  ({lo:g}–{hi:g} GHz)", lambda lo=lo, hi=hi: self._apply_preset(lo, hi))
        self.btn_t_preset.setMenu(pm)
        self.btn_t_add.clicked.connect(lambda: self._add_target(duplicate=False))
        self.btn_t_dup.clicked.connect(lambda: self._add_target(duplicate=True))
        self.btn_t_del.clicked.connect(self._remove_target)
        for b in (self.btn_t_add, self.btn_t_dup, self.btn_t_del):
            br.addWidget(b)
        br.addStretch(1)
        br.addWidget(self.btn_t_preset)
        tl.addLayout(br)
        ed = QGridLayout()
        ed.setHorizontalSpacing(6)
        self.f_min = SciSpinBox()
        self.f_max = SciSpinBox()
        self.band = spectral.SpectralInputs(self.f_min, self.f_max)  # start/end in the project's spectral unit
        self.n_f = QSpinBox()
        self.n_f.setRange(1, 2001)
        self.n_f.setSuffix(" " + tr("pts"))
        self.a_min = SciSpinBox(minimum=0.0, maximum=89.9, suffix="°")
        self.a_max = SciSpinBox(minimum=0.0, maximum=89.9, suffix="°")
        self.n_a = QSpinBox()
        self.n_a.setRange(1, 181)
        self.n_a.setSuffix(" " + tr("pts"))
        self.goal = SciSpinBox(minimum=-200, maximum=0, suffix="dB")
        self.pol_te = QCheckBox("TE")
        self.pol_tm = QCheckBox("TM")
        self.lbl_goal = QLabel()
        rows = ((tr("Frequency"), self.f_min, self.f_max, self.n_f),
                (tr("Angle"), self.a_min, self.a_max, self.n_a))
        for r, (lab, a, b, n) in enumerate(rows):
            label = QLabel(lab)
            if r == 0:
                self.lbl_band = label  # "Frequency" / "Wavelength" / "Wavenumber" (follows the spectral unit)
            ed.addWidget(label, r, 0, Qt.AlignRight)
            ed.addWidget(a, r, 1)
            ed.addWidget(QLabel("–"), r, 2)
            ed.addWidget(b, r, 3)
            ed.addWidget(n, r, 4)
        ed.addWidget(self.lbl_goal, 2, 0, Qt.AlignRight)
        ed.addWidget(self.goal, 2, 1)
        pr = QHBoxLayout()
        pr.addWidget(self.pol_te)
        pr.addWidget(self.pol_tm)
        pr.addStretch(1)
        ed.addLayout(pr, 2, 3, 1, 2)
        tl.addLayout(ed)
        ll.addWidget(g)
        self._target_idx = 0

        g = QGroupBox(tr("Objective (weighted, normalised terms)"))
        grid = QGridLayout(g)
        grid.addWidget(muted(tr("Term")), 0, 0)
        grid.addWidget(muted(tr("Weight")), 0, 1)
        grid.addWidget(muted(tr("Reference")), 0, 2)
        self.w_worst = SciSpinBox(minimum=0, maximum=1e6)
        self.w_mean = SciSpinBox(minimum=0, maximum=1e6)
        self.w_thick = SciSpinBox(minimum=0, maximum=1e6)
        self.w_mass = SciSpinBox(minimum=0, maximum=1e6)
        self.rl_ref = SciSpinBox(minimum=-200, maximum=-0.01, suffix="dB")
        self.t_ref = SciSpinBox()
        self.m_ref = SciSpinBox(minimum=1e-6, maximum=1e6, suffix="kg/m²")
        rows = [(tr("Worst-case RL in band"), self.w_worst, self.rl_ref),
                (tr("Mean reflectance |Γ|²"), self.w_mean, muted(tr("uses the RL reference"))),
                (tr("Total thickness"), self.w_thick, self.t_ref),
                (tr("Areal mass"), self.w_mass, self.m_ref)]
        for r, (lab, w, ref) in enumerate(rows, start=1):
            grid.addWidget(QLabel(lab), r, 0)
            grid.addWidget(w, r, 1)
            grid.addWidget(ref, r, 2)
        self.chk_tmax = QCheckBox(tr("Thickness limit"))
        self.t_max = SciSpinBox()
        # thickness reference and limit in the project's length unit; positive, and untouched values keep their metres
        self.t_inputs = spectral.LengthInputs(self.t_ref, self.t_max, minimum=1e-12)
        grid.addWidget(self.chk_tmax, 5, 0)
        grid.addWidget(self.t_max, 5, 1, 1, 2)
        self.lbl_rl_hint = muted("")
        grid.addWidget(self.lbl_rl_hint, 6, 0, 1, 3)
        ll.addWidget(g)

        g = QGroupBox(tr("Variables"))
        vl = QVBoxLayout(g)
        self.tbl = QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels([tr("Parameter"), tr("Current"), tr("Lower"), tr("Upper"), ""])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionMode(QAbstractItemView.NoSelection)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setMinimumSectionSize(28)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        for c in (2, 3):
            hh.setSectionResizeMode(c, QHeaderView.Fixed)
            self.tbl.setColumnWidth(c, 74)
        self.tbl.setTextElideMode(Qt.ElideMiddle)  # long names keep their "[unit]" suffix
        hh.setSectionResizeMode(4, QHeaderView.Fixed)
        self.tbl.setColumnWidth(4, 30)
        self.tbl.setWordWrap(False)
        self.tbl.setMinimumHeight(140)
        vl.addWidget(self.tbl)
        ar = QHBoxLayout()
        self.cb_add = QComboBox()
        self.cb_add.setMinimumContentsLength(24)
        self.btn_add = QPushButton(tr("Add"))
        set_button_icon(self.btn_add, "add")
        self.btn_add.clicked.connect(self._add_variable)
        ar.addWidget(self.cb_add, 1)
        ar.addWidget(self.btn_add)
        vl.addLayout(ar)
        self.lbl_choices = muted()
        vl.addWidget(self.lbl_choices)
        ll.addWidget(g)

        g = QGroupBox(tr("Algorithm"))
        f = QFormLayout(g)
        f.setLabelAlignment(Qt.AlignRight)
        self.maxiter = QSpinBox()
        self.maxiter.setRange(1, 100000)
        self.popsize = QSpinBox()
        self.popsize.setRange(4, 500)
        self.seed = QSpinBox()
        self.seed.setRange(-1, 2 ** 31 - 1)
        self.seed.setSpecialValueText(tr("random"))
        self.polish = QCheckBox(tr("Local refinement (L-BFGS-B)"))
        f.addRow(tr("Generations (max)"), self.maxiter)
        f.addRow(tr("Population factor"), self.popsize)
        f.addRow(tr("Random seed"), self.seed)
        f.addRow("", self.polish)
        f.addRow(muted(tr("Global search: differential evolution. Material choices with ≤ {n} "
                          "combinations are enumerated exhaustively.", n=MAX_ENUMERATED_COMBOS)))
        ll.addWidget(g)
        ll.addStretch(1)
        split.addWidget(scroll)

        # ---------------- right: run & results ------------------------------
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 8, 8, 8)
        bar = QHBoxLayout()
        self.btn_run = QPushButton(tr("Run optimisation"))
        set_button_icon(self.btn_run, "run", True)
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self.run)
        self.btn_stop = QPushButton(tr("Stop"))
        set_button_icon(self.btn_stop, "stop")
        self.btn_stop.clicked.connect(self.stop)
        self.btn_stop.setEnabled(False)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setFormat("")
        bar.addWidget(self.btn_run)
        bar.addWidget(self.btn_stop)
        bar.addWidget(self.progress, 1)
        rl.addLayout(bar)
        self.lbl_status = muted(tr("Ready."))
        rl.addWidget(self.lbl_status)
        self.fig = Figure(figsize=(5, 2.6), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.fig)
        rl.addWidget(self.canvas, 2)
        grp = QGroupBox(tr("Best design"))
        gl = QVBoxLayout(grp)
        self.tbl_res = QTableWidget(0, 2)
        self.tbl_res.setHorizontalHeaderLabels([tr("Item"), tr("Value")])
        self.tbl_res.verticalHeader().setVisible(False)
        self.tbl_res.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_res.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl_res.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        gl.addWidget(self.tbl_res)
        br = QHBoxLayout()
        self.btn_apply = QPushButton(tr("Apply to project"))
        set_button_icon(self.btn_apply, "apply")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._apply)
        self.btn_new = QPushButton(tr("Open as new project"))
        self.btn_new.setEnabled(False)
        self.btn_new.clicked.connect(self._open_new)
        br.addStretch(1)
        br.addWidget(self.btn_new)
        br.addWidget(self.btn_apply)
        gl.addLayout(br)
        rl.addWidget(grp, 2)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([520, 560])
        scroll.setMinimumWidth(460)

        for w in (self.f_min, self.f_max, self.a_min, self.a_max, self.goal, self.w_worst, self.w_mean,
                  self.w_thick, self.w_mass, self.rl_ref, self.t_ref, self.m_ref, self.t_max):
            w.valueEdited.connect(self._commit)
        for w in (self.n_f, self.n_a, self.maxiter, self.popsize, self.seed):
            w.valueChanged.connect(self._commit)
        for w in (self.pol_te, self.pol_tm, self.chk_tmax, self.polish):
            w.toggled.connect(self._commit)
        self.refresh()
        self._draw_history()
        # target edits are settings changes; keep the list and editor in step with the document
        self.doc.changed.connect(lambda kind: kind == "settings" and self._reload_targets())

    def _reload_targets(self):
        self._loading = True
        try:
            self._refresh_targets()
        finally:
            self._loading = False

    # -- sync with document --------------------------------------------------
    # -- targets -----------------------------------------------------------------
    def target_summary(self, t):
        pos = self.ctx.rl_positive
        band = spectral.fmt_range(t.f_min, t.f_max, spectral.unit_of(self.doc.project))
        ang = (f"{t.angle_min:g}°" if t.angle_max <= t.angle_min else f"{t.angle_min:g}–{t.angle_max:g}°")
        pols = "+".join(t.pols) if t.pols else "—"
        rel = "≥" if pos else "≤"
        return f"{band} · {ang} · {pols} · {rel} {rl_display(t.goal_db, pos):g} dB"

    def _selected_target(self):
        ts = self.doc.project.optimization.targets
        return ts[self._target_idx] if 0 <= self._target_idx < len(ts) else None

    def _refresh_targets(self):
        ts = self.doc.project.optimization.targets
        self._target_idx = min(max(self._target_idx, 0), len(ts) - 1) if ts else -1
        self.tbl_targets.blockSignals(True)
        try:
            self.tbl_targets.setRowCount(len(ts))
            for r, t in enumerate(ts):
                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
                chk.setCheckState(Qt.Checked if t.enabled else Qt.Unchecked)
                chk.setToolTip(tr("Include this target in the optimisation"))
                self.tbl_targets.setItem(r, 0, chk)
                it = QTableWidgetItem(self.target_summary(t))
                it.setToolTip(it.text())
                self.tbl_targets.setItem(r, 1, it)
            if self._target_idx >= 0:
                self.tbl_targets.selectRow(self._target_idx)
        finally:
            self.tbl_targets.blockSignals(False)
        self.btn_t_del.setEnabled(len(ts) > 1)
        t = self._selected_target()
        for w in (self.f_min, self.f_max, self.n_f, self.a_min, self.a_max, self.n_a, self.goal,
                  self.pol_te, self.pol_tm, self.btn_t_dup, self.btn_t_preset):
            w.setEnabled(t is not None)
        if t is None:
            return
        pos = self.ctx.rl_positive
        self.band.show(spectral.unit_of(self.doc.project), t.f_min, t.f_max)
        self.lbl_band.setText(spectral.quantity_name(spectral.unit_of(self.doc.project)))
        self.n_f.setValue(t.n_f)
        self.a_min.set_value(t.angle_min)
        self.a_max.set_value(t.angle_max)
        self.n_a.setValue(t.n_angle)
        self.pol_te.setChecked("TE" in t.pols)
        self.pol_tm.setChecked("TM" in t.pols)
        self.goal.setRange(*((0, 200) if pos else (-200, 0)))
        self.goal.set_value(rl_display(t.goal_db, pos))
        self.lbl_goal.setText(tr("Goal RL (≥)") if pos else tr("Goal RL (≤)"))

    def _on_target_selected(self):
        rows = self.tbl_targets.selectionModel().selectedRows()
        if rows and rows[0].row() != self._target_idx:
            self._target_idx = rows[0].row()
            self._loading = True
            try:
                self._refresh_targets()
            finally:
                self._loading = False

    def _on_target_toggled(self, item):
        if self._loading or item.column() != 0:
            return
        r, on = item.row(), item.checkState() == Qt.Checked
        self.doc.edit_settings(lambda p: setattr(p.optimization.targets[r], "enabled", on))

    def _add_target(self, duplicate):
        cur = self._selected_target()
        new = BandTarget.from_dict(cur.to_dict()) if duplicate and cur else \
            BandTarget(goal_db=self.doc.project.optimization.rl_ref_db)
        self._target_idx = len(self.doc.project.optimization.targets)
        self.doc.edit_settings(lambda p: p.optimization.targets.append(new))

    def _remove_target(self):
        ts = self.doc.project.optimization.targets
        if len(ts) <= 1 or self._selected_target() is None:
            return
        i = self._target_idx
        self.doc.edit_settings(lambda p: p.optimization.targets.pop(i))

    def _apply_preset(self, lo_ghz, hi_ghz):
        i = self._target_idx
        if self._selected_target() is None:
            return

        def mut(p):
            t = p.optimization.targets[i]
            t.f_min, t.f_max = lo_ghz * 1e9, hi_ghz * 1e9
        self.doc.edit_settings(mut)

    def refresh(self):
        s = self.doc.project.optimization
        self._loading = True
        try:
            self._refresh_targets()
            self.w_worst.set_value(s.w_worst)
            self.w_mean.set_value(s.w_mean)
            self.w_thick.set_value(s.w_thickness)
            self.w_mass.set_value(s.w_mass)
            pos = self.ctx.rl_positive
            self.rl_ref.setRange(*((0.01, 200) if pos else (-200, -0.01)))
            self.rl_ref.set_value(rl_display(s.rl_ref_db, pos))
            self.lbl_rl_hint.setText(
                tr("Each term is divided by its reference so weights are comparable; "
                   "RL is in dB (positive = good).") if pos else
                tr("Each term is divided by its reference so weights are comparable; "
                   "RL is in dB (negative = good)."))
            # the limit box shows 10 mm while no limit is set; enabling it keeps exactly that value
            self.t_inputs.show(lengths.unit_of(self.doc.project), s.thickness_ref, s.thickness_max or 10e-3)
            self.m_ref.set_value(s.mass_ref)
            self.chk_tmax.setChecked(s.thickness_max is not None)
            self.t_max.setEnabled(s.thickness_max is not None)
            self.maxiter.setValue(s.maxiter)
            self.popsize.setValue(s.popsize)
            self.seed.setValue(-1 if s.seed is None else s.seed)
            self.polish.setChecked(s.polish)
            self._refresh_variables()
        finally:
            self._loading = False
        if self.result is not None and self.result.terms is not None:
            self._show_result(self.result)  # e.g. the RL sign preference changed

    def _param_label(self, label):
        """Translated parameter label; a dispersion term's f0 takes the symbol of the spectral unit (λ₀, ν̃₀)."""
        return param_label(label, spectral.position_symbol(spectral.unit_of(self.doc.project)))

    def _refresh_variables(self):
        p = self.doc.project
        s = p.optimization
        self.tbl.setRowCount(0)
        for v in s.variables:
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            try:
                # thicknesses ("mm") follow the length unit, dispersion f0 and gamma ("GHz") the spectral unit
                unit = param_unit(p, v.path)
                label = self._param_label(self._label(v.path))
                cur = fmt_num(spectral.param_to_display(get_param(p, v.path), p, v.path, unit))
            except (KeyError, AttributeError, IndexError):
                unit, label, cur = "", tr("(missing) ") + " / ".join(map(str, v.path)), "—"
            except ValueError:  # an f0 <= 0 has no wavelength or wavenumber
                cur = "—"
            ul = unit_label(spectral.param_display_unit(p, v.path, unit))
            it = QTableWidgetItem(label + (f"  [{ul}]" if ul else ""))
            it.setToolTip(it.text())
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.tbl.setItem(r, 0, it)
            it = QTableWidgetItem(cur)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl.setItem(r, 1, it)
            kind = spectral.param_kind(v.path, unit)
            # an f0 shown as a wavelength runs opposite to the stored Hz: the Lower box holds the upper bound
            attrs = ("upper", "lower") if spectral.param_reversed(p, v.path, unit) else ("lower", "upper")
            for col, attr in zip((2, 3), attrs):
                try:
                    shown = spectral.param_to_display(getattr(v, attr), p, v.path, unit)
                except ValueError:
                    it = QTableWidgetItem("—")
                    it.setFlags(Qt.ItemIsEnabled)
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    it.setToolTip(tr("A bound of 0 Hz or below has no wavelength or wavenumber; switch the "
                                     "spectral axis to a frequency unit to edit it."))
                    self.tbl.removeCellWidget(r, col)
                    self.tbl.setItem(r, col, it)
                    continue
                sp = SciSpinBox(digits=5)
                if kind == "position" and spectral.spectral_kind(spectral.unit_of(p)) != "f":
                    sp.setRange(*spectral.INPUT_RANGE)  # wavelengths and wavenumbers are positive
                elif kind == "linewidth":
                    sp.setRange(0.0, spectral.INPUT_RANGE[1])
                sp.setFrame(False)
                sp.set_value(shown)
                sp.valueEdited.connect(lambda val, path=v.path, a=attr, u=unit: self._set_bound(path, a, u, val))
                self.tbl.setCellWidget(r, col, sp)
            btn = QPushButton("")
            set_button_icon(btn, "delete")
            btn.setFlat(True)
            btn.setToolTip(tr("Remove variable"))
            btn.clicked.connect(lambda _=False, path=v.path: self._remove_variable(path))
            self.tbl.setCellWidget(r, 4, btn)
        self.cb_add.clear()
        existing = {tuple(v.path) for v in s.variables}
        for path, label, unit in available_params(p):
            if tuple(path) in existing:
                continue
            ul = unit_label(spectral.param_display_unit(p, path, unit))
            self.cb_add.addItem(self._param_label(label) + (f"  [{ul}]" if ul else ""), path)
        self.btn_add.setEnabled(self.cb_add.count() > 0)
        if s.choices:
            parts = []
            for c in s.choices:
                try:
                    idx = p.structure.index_of(c.uid) + 1
                except KeyError:
                    continue
                parts.append(tr("Layer {i}: {n} candidates", i=idx, n=len(c.candidates)))
            n = math.prod(len(c.candidates) for c in s.choices)
            self.lbl_choices.setText(tr("Material choices: {parts} — {n} combinations",
                                        parts="; ".join(parts), n=n))
        else:
            self.lbl_choices.setText(tr("Material choices: none (enable per layer in the Properties panel)."))

    def _label(self, path):
        for p, label, _ in available_params(self.doc.project):
            if tuple(p) == tuple(path):
                return label
        return " / ".join(map(str, path))

    def _commit(self, *_):
        if self._loading:
            return
        self.t_max.setEnabled(self.chk_tmax.isChecked())
        pols = [p for p, b in (("TE", self.pol_te), ("TM", self.pol_tm)) if b.isChecked()]
        i = self._target_idx
        pos = self.ctx.rl_positive
        f_lo, f_hi = self.band.values()  # an untouched box keeps its stored Hz value
        t_ref, t_max = self.t_inputs.values()  # ... and an untouched thickness box its metres

        def mut(p):
            s = p.optimization
            if 0 <= i < len(s.targets):
                t = s.targets[i]
                t.f_min, t.f_max, t.n_f = f_lo, f_hi, self.n_f.value()
                t.angle_min, t.angle_max, t.n_angle = self.a_min.value(), self.a_max.value(), self.n_a.value()
                t.pols = pols
                t.goal_db = rl_display(self.goal.value(), pos)
            s.w_worst, s.w_mean = self.w_worst.value(), self.w_mean.value()
            s.w_thickness, s.w_mass = self.w_thick.value(), self.w_mass.value()
            s.rl_ref_db = rl_display(self.rl_ref.value(), self.ctx.rl_positive)
            s.thickness_ref = t_ref
            s.mass_ref = self.m_ref.value()
            s.thickness_max = t_max if self.chk_tmax.isChecked() else None
            s.maxiter, s.popsize = self.maxiter.value(), self.popsize.value()
            s.seed = None if self.seed.value() < 0 else self.seed.value()
            s.polish = self.polish.isChecked()
        self.doc.edit_settings(mut)

    def _set_bound(self, path, attr, unit, val):
        """``attr`` is the model bound the box edits (for a wavelength f0 the Lower box edits ``upper``)."""
        try:
            si = spectral.param_from_display(val, self.doc.project, path, unit)
        except ValueError:  # 0 in a box that needs a positive wavelength or wavenumber
            return

        def mut(p):
            for v in p.optimization.variables:
                if tuple(v.path) == tuple(path):
                    setattr(v, attr, si)
        self.doc.edit(tr("Change variable bound"), mut, merge_key=("bound",) + tuple(path) + (attr,))

    def _add_variable(self):
        path = self.cb_add.currentData()
        if path is None:
            return
        p = self.doc.project
        val = get_param(p, path)
        unit = param_unit(p, path)
        if unit == "frac":
            lo, hi = 0.0, min(1.0, max(val * 3, 0.3))
        elif path[-1] == "X":
            lo, hi = val - 500.0, val + 500.0
        elif path[0] == "layer" and path[-1] in ("L", "C"):
            lo, hi = default_lc_bounds(path[-1], val)  # ratio 100: searched on a log scale
        elif val > 0:
            lo, hi = val / 4, val * 4
        elif val == 0 and path[-1] == "thickness":
            lo, hi = lengths.zero_thickness_range(p)  # same as the properties panel's Opt. toggle
        elif val == 0:
            lo, hi = 0.0, 1.0
        else:
            lo, hi = val * 4, val / 4
        self.doc.edit(tr("Add optimisation variable"),
                      lambda pr: pr.optimization.variables.append(ContinuousVariable(tuple(path), lo, hi)))

    def _remove_variable(self, path):
        def mut(p):
            p.optimization.variables = [v for v in p.optimization.variables if tuple(v.path) != tuple(path)]
        self.doc.edit(tr("Remove optimisation variable"), mut)

    # -- running -----------------------------------------------------------------
    def is_running(self):
        return self.thread is not None

    def _preflight(self):
        p = self.doc.project
        try:
            error_issues, warning_issues = preflight(p, p.optimization)
        except (OptimizationError, KeyError) as e:
            QMessageBox.warning(self, tr("Cannot start optimisation"), str(e))
            return False

        def text(iss):
            # "Unknown material: X" already names the material
            msg = issue_text(iss, unit=spectral.unit_of(self.doc.project))
            return msg if iss.code == "unknown_material" else f"{iss.material}: {msg}"

        errors = [text(i) for i in error_issues]
        warnings = [text(i) for i in warning_issues]
        if errors:
            QMessageBox.critical(self, tr("Pre-flight check failed"), "\n".join(errors))
            return False
        if warnings:
            r = QMessageBox.warning(self, tr("Pre-flight check"),
                                    tr("The following warnings were found:") + "\n\n" + "\n".join(warnings)
                                    + "\n\n" + tr("Run anyway?"),
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            return r == QMessageBox.Yes
        return True

    def run(self):
        if self.is_running() or not self._preflight():
            return
        self._history = []
        self.result = None
        self.btn_apply.setEnabled(False)
        self.btn_new.setEnabled(False)
        self.tbl_res.setRowCount(0)
        self.progress.setRange(0, 0)
        self.progress.setFormat("")
        self.lbl_status.setText(tr("Starting…"))
        self.worker = OptimizationWorker(self.doc.project, None)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.thread = start_worker(self.worker, self)
        self.thread.finished.connect(self._on_thread_done)
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.runningChanged.emit(True)

    def stop(self):
        if self.worker is not None:
            self.worker.request_stop()
            self.lbl_status.setText(tr("Stopping…"))

    def shutdown(self):
        """Stop a running job and wait for it (used when the window closes)."""
        if self.worker is not None:
            self.worker.request_stop()
        if self.thread is not None:
            self.thread.wait(5000)

    def _on_progress(self, info):
        self._history = info.get("history", self._history)
        stage = tr("global search") if info["stage"] == "global" else tr("local refinement")
        combo = (tr(", combination {i}/{n}", i=info["combo"], n=info["n_combos"])
                 if info.get("n_combos", 1) > 1 else "")
        best = info.get("best")
        best_txt = fmt_num(best, 5) if best is not None and math.isfinite(best) else "—"
        self.lbl_status.setText(tr("{stage}{combo} · iteration {it} · evaluations {ev} · best objective {b}",
                                   stage=stage, combo=combo, it=info["iteration"], ev=info["n_evals"], b=best_txt))
        n = info.get("n_combos", 1)
        if n > 1:
            self.progress.setRange(0, n)
            self.progress.setValue(info["combo"] - 1)
            self.progress.setFormat(f"{info['combo']}/{n}")
        elif info["stage"] == "global":
            total = max(1, int(self.doc.project.optimization.maxiter))
            self.progress.setRange(0, total)
            self.progress.setValue(min(int(info["iteration"]), total))
            self.progress.setFormat("%v/%m")
        else:  # local refinement has no fixed length
            self.progress.setRange(0, 0)
            self.progress.setFormat("")
        self._draw_history()

    def _on_finished(self, res):
        self.result = res
        self.result_project = None
        self._history = res.history
        self._draw_history()
        if res.terms is None:
            self.lbl_status.setText(tr("No valid design found."))
            return
        msg = tr("Stopped by user") if res.stopped else tr("Finished")
        self.lbl_status.setText(tr("{msg} · {ev} evaluations in {t} s", msg=msg, ev=res.n_evals,
                                   t=f"{res.elapsed:.1f}"))
        self._show_result(res)
        self.btn_apply.setEnabled(True)
        self.btn_new.setEnabled(True)
        self.statusMessage.emit(tr("Optimisation finished: worst-case RL {v} dB", v=self._rl(res.terms.worst_db)))

    def _on_failed(self, msg):
        self.lbl_status.setText(tr("Optimisation failed."))
        QMessageBox.critical(self, tr("Optimisation failed"), msg)

    def _on_thread_done(self):
        self.thread = None
        self.worker = None
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if self.result else 0)
        self.progress.setFormat("")
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.runningChanged.emit(False)

    # -- results -------------------------------------------------------------------
    def _rl(self, db):
        return f"{rl_display(db, self.ctx.rl_positive):.2f}"

    def _show_result(self, res):
        p = self.doc.project
        per = res.terms.per_target
        target_rows = []
        if len(per) > 1:
            enabled = p.optimization.enabled_targets()
            for n, (worst, margin) in enumerate(per, start=1):
                summary = self.target_summary(enabled[n - 1]) if n - 1 < len(enabled) else ""
                state = (tr("met (margin {m} dB)", m=f"{-margin:.2f}") if margin <= 0
                         else tr("missed by {m} dB", m=f"{margin:.2f}"))
                target_rows.append((tr("Target {n}: {s}", n=n, s=summary), f"{self._rl(worst)} dB · {state}"))
        rows = [(tr("Worst-case RL in band"), self._rl(res.terms.worst_db) + " dB"), *target_rows,
                (tr("Mean reflectance |Γ|²"), fmt_num(res.terms.mean_r, 4)),
                (tr("Total thickness"), lengths.fmt_length(res.terms.thickness, lengths.unit_of(p), 5)),
                (tr("Areal mass"), fmt_num(res.terms.mass, 4) + " kg/m²"),
                (tr("Objective"), fmt_num(res.terms.objective, 5))]
        for path, val in res.values.items():
            try:
                unit = param_unit(p, path)
            except KeyError:
                unit = ""
            ul = unit_label(spectral.param_display_unit(p, path, unit))
            try:
                shown = fmt_num(spectral.param_to_display(val, p, path, unit), 6)
            except ValueError:
                shown = "—"
            rows.append((self._param_label(self._label(path)), shown + (f" {ul}" if ul else "")))
        for uid, name in res.choices.items():
            try:
                idx = p.structure.index_of(uid) + 1
            except KeyError:
                continue
            rows.append((tr("Layer {i} material", i=idx), name))
        self.tbl_res.setRowCount(len(rows))
        for r, (a, b) in enumerate(rows):
            it = QTableWidgetItem(a)
            it.setToolTip(f"{a}: {b}")  # the item column is narrow; long target rows elide
            self.tbl_res.setItem(r, 0, it)
            it = QTableWidgetItem(b)
            it.setToolTip(f"{a}: {b}")
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tbl_res.setItem(r, 1, it)

    def _apply(self):
        if not self.result:
            return
        res = self.result
        self._pin_before()
        try:
            self.doc.edit(tr("Apply optimisation result"), lambda p: apply_result(p, res))
        except (KeyError, AttributeError) as e:
            QMessageBox.warning(self, tr("Cannot apply result"),
                                tr("The project changed since the run started: {e}", e=e))
            return
        self.statusMessage.emit(tr("Optimisation result applied (Undo restores the previous design)."))

    def _open_new(self):
        if not self.result:
            return
        q = self.doc.project.copy()
        try:
            apply_result(q, self.result)
        except (KeyError, AttributeError) as e:
            QMessageBox.warning(self, tr("Cannot apply result"), str(e))
            return
        q.name = tr("{name} (optimised)", name=q.name)
        self._pin_before()
        self.openProjectRequested.emit(q)

    def _pin_before(self):
        # Keep the design being replaced one click away for comparison (Frequency/Angle/Smith tabs).
        pin = getattr(self.ctx, "pin_before_optimisation", None)
        if pin is not None:
            pin()

    def _draw_history(self):
        c = self.ctx.colors
        with matplotlib.rc_context(mpl_rc(c)):
            self.fig.clear()
            self.fig.set_facecolor(c.base)
            ax = self.fig.add_subplot(111)
            if self._history:
                x = [h[0] for h in self._history] + [self._history[-1][0]]
                y = [h[1] for h in self._history] + [self._history[-1][1]]
                ax.step(x, y, where="post", color=c.series[0])
                ax.plot(x[-1], y[-1], "o", color=c.series[0])
            ax.set_xlabel(tr("Objective evaluations"))
            ax.set_ylabel(tr("Best objective"))
            ax.set_title(tr("Convergence"), fontsize=10, loc="left")
        self.canvas.draw_idle()

    def retheme(self):
        self._draw_history()
