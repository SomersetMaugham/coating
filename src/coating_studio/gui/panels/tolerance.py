"""Manufacturing-tolerance (Monte-Carlo) tab."""

from __future__ import annotations

import json
import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from coating_studio.core.structure import SheetLayer, SlabLayer
from coating_studio.gui import spectral
from coating_studio.gui.fmt import param_label, rl_display
from coating_studio.gui.icons import set_button_icon
from coating_studio.gui.plots.base import PlotView
from coating_studio.gui.widgets.inputs import SciSpinBox, muted
from coating_studio.gui.workers import ToleranceWorker, start_worker
from coating_studio.i18n import tr
from coating_studio.project import available_params
from coating_studio.report import corner_label, draw_tolerance_band, samples_text
from coating_studio.tolerance import (  # noqa: F401 (yield_band re-exported)
    CornerResult, result_band, result_settings, tolerance_frequencies, yield_band, yield_intervals,
)

_KEYS = ("thickness", "eps", "eps_loss", "mu", "mu_loss", "loss_correlation", "sheet")
_COEFF_KEYS = {"loss_correlation"}  # per-layer cells that hold a plain coefficient (-1..1), not a percentage
_LOSS_BASE = {"eps_loss": "eps", "mu_loss": "mu"}


def joint_yield_title(r, s):
    """Plot title of a multi-angle result (``s``: the settings of the run)."""
    if r.angle_mode == "grid":
        return tr("Joint yield {y:.1f}% over {n} angle-grid points ({s})",
                  y=100 * (r.joint_yield_fraction or 0.0), n=len(r.corners), s=samples_text(r, s))
    return tr("Joint yield {y:.1f}% over {n} corners ({s})",
              y=100 * (r.joint_yield_fraction or 0.0), n=len(r.corners), s=samples_text(r, s))


class TolerancePlot(PlotView):
    title = "tolerance_analysis"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.result = None
        self.controls.addStretch(1)

    def draw_plot(self, fig):
        ax = fig.add_subplot(111)
        r = self.result
        pos = self.ctx.rl_positive
        c = self.ctx.colors
        unit = spectral.unit_of(self.ctx.project)
        ax.set_xlabel(spectral.axis_label(unit))
        ax.set_ylabel(tr("Reflection loss [dB] (higher is better)") if pos
                      else tr("Reflection loss [dB] (lower is better)"))
        if r is None:
            ax.text(0.5, 0.5, tr("Run the analysis to see the spread of reflection loss."),
                    ha="center", va="center", transform=ax.transAxes, color=c.muted)
            return None
        project = self.ctx.project
        if isinstance(r, CornerResult):
            # Show the weakest row's spread; the title carries the joint yield over all rows.  The row records its
            # own band and criterion, so later target edits cannot misplace them.
            title = joint_yield_title(r, result_settings(r, project))
            r = r.corners[r.worst][5]
        else:
            title = None
        s = result_settings(r, project)  # the settings of the run, not the current ones
        draw_tolerance_band(ax, r, s.target_db, result_band(r, project), s.lower_pct, s.upper_pct,
                            {"spread": c.series[0], "nominal": c.series[1], "target": c.muted, "band": c.series[2]},
                            pos, project.sweep.log_f, unit)
        ax.legend(loc="best")
        ax.set_title(title or tr("Yield {y:.1f}% ({s})", y=100 * r.yield_fraction, s=samples_text(r, s)),
                     fontsize=10, loc="left", wrap=True)  # long joint-yield titles wrap instead of being clipped
        return None

    def format_cursor(self, ax, x, y):
        return tr("{x}, value = {v}", x=spectral.cursor_text(spectral.unit_of(self.ctx.project), x), v=f"{y:.4g}")

    def data_table(self):
        r = self.result
        if r is None:
            return None
        if isinstance(r, CornerResult):  # export the weakest corner
            r = r.corners[r.worst][5]
        pos = self.ctx.rl_positive
        nom, med = rl_display(r.nominal_db, pos), rl_display(r.median_db, pos)
        # A sign flip reverses the order of the percentile band; keep lower <= median <= upper.
        lo, hi = (rl_display(r.upper_db, pos), rl_display(r.lower_db, pos)) if pos else (r.lower_db, r.upper_db)
        unit = spectral.unit_of(self.ctx.project)
        return ([spectral.csv_header(unit), "nominal [dB]", "median [dB]", "lower [dB]", "upper [dB]"],
                [[f"{a:.10g}", f"{b:.6g}", f"{c:.6g}", f"{d:.6g}", f"{e:.6g}"]
                 for a, b, c, d, e in zip(spectral.x_values(r.f, unit), nom, med, lo, hi)])


class TolerancePanel(QWidget):
    statusMessage = Signal(str)

    def __init__(self, doc, ctx, parent=None):
        super().__init__(parent)
        self.doc, self.ctx = doc, ctx
        self._loading = False
        self.thread = None
        self.worker = None

        split = QSplitter(Qt.Horizontal, self)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(split)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        left = QWidget()
        scroll.setWidget(left)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 8, 8)

        g = QGroupBox(tr("Monte-Carlo settings"))
        f = QFormLayout(g)
        f.setLabelAlignment(Qt.AlignRight)
        self.n = QSpinBox()
        self.n.setRange(10, 100000)
        self.dist = QComboBox()
        self.dist.addItem(tr("Normal (value = 1σ)"), "normal")
        self.dist.addItem(tr("Uniform (± value)"), "uniform")
        self.seed = QSpinBox()
        self.seed.setRange(-1, 2 ** 31 - 1)
        self.seed.setSpecialValueText(tr("random"))
        f.addRow(tr("Samples"), self.n)
        f.addRow(tr("Distribution"), self.dist)
        f.addRow(tr("Random seed"), self.seed)
        ll.addWidget(g)

        g = QGroupBox(tr("Default tolerances (relative)"))
        f = QFormLayout(g)
        f.setLabelAlignment(Qt.AlignRight)
        self.d = {}
        self.follow = {}
        rows = (("thickness", tr("Thickness")), ("eps", tr("Permittivity ε′")), ("eps_loss", tr("Dielectric loss ε″")),
                ("mu", tr("Permeability μ′")), ("mu_loss", tr("Magnetic loss μ″")), ("sheet", tr("Sheet impedance")))
        for key, lab in rows:
            sp = SciSpinBox(minimum=0, maximum=100, suffix="%")
            self.d[key] = sp
            if key in _LOSS_BASE:
                # checked = the loss follows the real part (one factor on the complex value, tan δ fixed)
                chk = QCheckBox(tr("Follow ε′") if key == "eps_loss" else tr("Follow μ′"))
                chk.setToolTip(tr("Scale the loss with the same factor as the real part (fixed tan δ) "
                                  "instead of varying it independently."))
                self.follow[key] = chk
                row = QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.addWidget(sp, 1)
                row.addWidget(chk)
                f.addRow(lab, row)
            else:
                f.addRow(lab, sp)
        self.rho = QDoubleSpinBox()
        self.rho.setRange(-1.0, 1.0)
        self.rho.setDecimals(2)
        self.rho.setSingleStep(0.1)
        self.rho.setToolTip(tr("Correlation coefficient between each layer's real-part error and loss error (ε′ with ε″, "
                               "μ′ with μ″). 0 = independent; positive when both rise together, for example with "
                               "filler content. Used only where the loss does not follow the real part."))
        f.addRow(tr("Real/loss correlation ρ"), self.rho)
        f.addRow(muted(tr("ε″ and μ″ get their own errors (independent of ε′ and μ′ at ρ = 0), so the loss tangent "
                          "varies too. A relative tolerance has no effect where the nominal loss is zero.")))
        ll.addWidget(g)

        g = QGroupBox(tr("Per-layer tolerances (%)"))
        gl = QVBoxLayout(g)
        self.tbl = QTableWidget(0, 1 + len(_KEYS))
        self.tbl.setHorizontalHeaderLabels([tr("Layer"), tr("Thickness"), "ε′", "ε″", "μ′", "μ″", "ρ", tr("Sheet")])
        for c, tip in enumerate((tr("Thickness"), tr("Permittivity ε′"), tr("Dielectric loss ε″"),
                                 tr("Permeability μ′"), tr("Magnetic loss μ″"), tr("Real/loss correlation ρ"),
                                 tr("Sheet impedance")), start=1):
            self.tbl.horizontalHeaderItem(c).setToolTip(tip)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionMode(QAbstractItemView.NoSelection)
        th = self.tbl.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.Stretch)
        th.setMinimumSectionSize(32)
        for c in range(1, 1 + len(_KEYS)):  # fit the header text ("Thickness" was clipped at a fixed 58 px)
            th.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.tbl.setMinimumHeight(120)
        gl.addWidget(self.tbl)
        gl.addWidget(muted(tr("Blank cells use the default values. ρ is a coefficient from −1 to 1, not a "
                              "percentage, and overrides the default ρ for that layer.")))
        ll.addWidget(g)

        g = QGroupBox(tr("Material parameter tolerances"))
        gl = QVBoxLayout(g)
        self.mtbl = QTableWidget(0, 2)
        self.mtbl.setHorizontalHeaderLabels([tr("Parameter"), tr("Tolerance (%)")])
        self.mtbl.verticalHeader().setVisible(False)
        self.mtbl.setSelectionMode(QAbstractItemView.NoSelection)
        mh = self.mtbl.horizontalHeader()
        mh.setSectionResizeMode(0, QHeaderView.Stretch)
        mh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.mtbl.setMinimumHeight(120)
        gl.addWidget(self.mtbl)
        gl.addWidget(muted(tr("Blank cells leave the parameter at its value. A material parameter is drawn once per "
                              "sample for the material, so every layer that uses it moves together; shifting a "
                              "term's f₀ or a volume fraction moves the curve along the frequency axis. The layer "
                              "ε and μ tolerances still apply on top, so lower them when these already cover the "
                              "same error.")))
        ll.addWidget(g)

        g = QGroupBox(tr("Evaluation"))
        f = QFormLayout(g)
        f.setLabelAlignment(Qt.AlignRight)
        self.target = SciSpinBox(minimum=-200, maximum=0, suffix="dB")
        self.angle = SciSpinBox(minimum=0, maximum=89.9, suffix="°")
        self.pol = QComboBox()
        for pkey, lab in (("avg", tr("Average")), ("TE", "TE"), ("TM", "TM")):
            self.pol.addItem(lab, pkey)
        self.chk_band = QCheckBox(tr("Custom yield band"))
        self.b_lo = SciSpinBox()
        self.b_hi = SciSpinBox()
        self.band = spectral.SpectralInputs(self.b_lo, self.b_hi)  # in the project's spectral unit
        self.lbl_target = QLabel(tr("Target RL (≤)"))
        f.addRow(self.lbl_target, self.target)
        f.addRow(tr("Incidence angle"), self.angle)
        f.addRow(tr("Polarisation"), self.pol)
        f.addRow("", self.chk_band)
        self.angle_mode = QComboBox()  # view state only, not saved
        self.angle_mode.addItem(tr("Single angle (settings above)"), None)
        self.angle_mode.addItem(tr("Ends of each target's angle range"), "corners")
        self.angle_mode.addItem(tr("Each target's angle grid"), "grid")
        self.angle_mode.setToolTip(tr("The two target modes run the analysis for each enabled target against its own "
                                      "band and goal, for each of its polarisations, at the two ends of its angle "
                                      "range or at every angle of its grid (the angles the optimiser checks), and "
                                      "report the joint yield (samples that pass everywhere)."))
        f.addRow(tr("Band from"), self.b_lo)
        f.addRow(tr("to"), self.b_hi)
        f.addRow(muted(tr("Yield = share of samples whose worst RL in the band meets the target. "
                          "Without a custom band, the bands of the enabled optimisation targets are used.")))
        f.addRow(tr("Angles evaluated"), self.angle_mode)
        f.addRow(muted(tr("A single angle can overstate the yield of a target that spans several angles. The angle "
                          "grid also checks the angles inside the range; angles between its points are not sampled. "
                          "In both target modes the angle, polarisation, target and band above are not used.")))
        ll.addWidget(g)
        ll.addStretch(1)
        split.addWidget(scroll)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 4, 4, 4)
        bar = QHBoxLayout()
        self.btn_run = QPushButton(tr("Run analysis"))
        set_button_icon(self.btn_run, "run", True)
        self.btn_run.setObjectName("primary")
        self.btn_run.clicked.connect(self.run)
        self.btn_stop = QPushButton(tr("Stop"))
        set_button_icon(self.btn_stop, "stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop)
        self.progress = QProgressBar()
        bar.addWidget(self.btn_run)
        bar.addWidget(self.btn_stop)
        bar.addWidget(self.progress, 1)
        rl.addLayout(bar)
        self.plot = TolerancePlot(ctx)
        rl.addWidget(self.plot, 1)
        self.lbl_corners = QLabel()
        self.lbl_corners.setWordWrap(True)
        self.lbl_corners.setVisible(False)
        rl.addWidget(self.lbl_corners)
        split.addWidget(right)
        split.setSizes([480, 560])
        scroll.setMinimumWidth(440)  # room for the layer names next to the 7 per-layer columns

        self.n.valueChanged.connect(self._commit)
        self.seed.valueChanged.connect(self._commit)
        self.rho.valueChanged.connect(self._commit)
        self.dist.currentIndexChanged.connect(self._commit)
        self.pol.currentIndexChanged.connect(self._commit)
        self.chk_band.toggled.connect(self._commit)
        self._result_targets = None  # the enabled targets a shown multi-angle result was computed for
        self.angle_mode.currentIndexChanged.connect(self._on_corners_toggled)
        for w in list(self.d.values()) + [self.target, self.angle, self.b_lo, self.b_hi]:
            w.valueEdited.connect(self._commit)
        for chk in self.follow.values():
            chk.toggled.connect(self._commit)
        self.tbl.itemChanged.connect(self._on_cell)
        self.mtbl.itemChanged.connect(self._on_material_cell)
        self.refresh()

    # ------------------------------------------------------------------------
    def refresh(self):
        p = self.doc.project
        s = p.tolerance
        self._loading = True
        try:
            self.n.setValue(s.n_samples)
            self.dist.setCurrentIndex(0 if s.distribution == "normal" else 1)
            self.seed.setValue(-1 if s.seed is None else s.seed)
            for k, sp in self.d.items():
                val = getattr(s, k)
                if k in _LOSS_BASE:
                    follows = val is None
                    self.follow[k].setChecked(follows)
                    sp.setEnabled(not follows)
                    if follows:
                        val = getattr(s, _LOSS_BASE[k])  # shows the factor the loss follows
                sp.set_value(val * 100)
            self.rho.setValue(s.loss_correlation)
            self._update_rho_enabled()
            pos = self.ctx.rl_positive
            self.target.setRange(*((0, 200) if pos else (-200, 0)))
            self.target.set_value(rl_display(s.target_db, pos))
            self.lbl_target.setText(tr("Target RL (≥)") if pos else tr("Target RL (≤)"))
            self.angle.set_value(s.angle)
            self.pol.setCurrentIndex({"avg": 0, "TE": 1, "TM": 2}.get(s.pol, 0))
            has_band = s.band_min is not None and s.band_max is not None
            self.chk_band.setChecked(has_band)
            # shows the default band (the targets') until a custom one is set; enabling the custom band then keeps
            # exactly these Hz values (SpectralInputs writes back untouched boxes unchanged)
            self.band.show(spectral.unit_of(p), *yield_band(p))
            self.b_lo.setEnabled(has_band)
            self.b_hi.setEnabled(has_band)
            layers = p.structure.layers
            self.tbl.setRowCount(len(layers))
            for r, ly in enumerate(layers):
                name = ly.name or (tr("Sheet") if isinstance(ly, SheetLayer) else ly.material)
                it = QTableWidgetItem(f"{r + 1}. {name}")
                it.setToolTip(it.text())  # the name can be clipped when the panel is narrow
                it.setFlags(Qt.ItemIsEnabled)
                it.setData(Qt.UserRole, ly.uid)
                self.tbl.setItem(r, 0, it)
                for c, key in enumerate(_KEYS, start=1):
                    applicable = (key == "sheet") == isinstance(ly, SheetLayer)
                    val = s.per_layer.get(ly.uid, {}).get(key)
                    shown = val if key in _COEFF_KEYS else None if val is None else val * 100
                    cell = QTableWidgetItem("" if shown is None or not applicable else f"{shown:g}")
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if not applicable:
                        cell.setFlags(Qt.NoItemFlags)
                        cell.setText("—")
                    self.tbl.setItem(r, c, cell)
            self._refresh_material_table(p)
        finally:
            self._loading = False
        self._apply_corner_state()

    def _refresh_material_table(self, p):
        """One row per material parameter the optimiser could vary (materials in use and those they reference)."""
        rows = [(path, label) for path, label, _ in available_params(p) if path[0] == "material"]
        position = spectral.position_symbol(spectral.unit_of(p))
        self.mtbl.setRowCount(len(rows))
        for r, (path, label) in enumerate(rows):
            it = QTableWidgetItem(param_label(label, position))
            it.setToolTip(it.text())
            it.setFlags(Qt.ItemIsEnabled)
            it.setData(Qt.UserRole, list(path))
            self.mtbl.setItem(r, 0, it)
            tol = p.tolerance.material_tolerance(path)
            cell = QTableWidgetItem("" if tol is None else f"{tol * 100:g}")
            cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.mtbl.setItem(r, 1, cell)

    def _on_material_cell(self, item):
        if self._loading or item.column() != 1:
            return
        path = self.mtbl.item(item.row(), 0).data(Qt.UserRole)
        text = item.text().strip().replace("%", "")
        val = None
        if text:
            try:
                val = float(text) / 100
            except ValueError:
                val = None
            if val is None or not math.isfinite(val) or val < 0:
                self.refresh()
                return

        def mut(p):
            # an edited entry keeps its place: the list order is the draw order, so other entries keep their samples
            entries = p.tolerance.material_params
            i = next((i for i, e in enumerate(entries) if e["path"] == path), None)
            if val is None:
                if i is not None:
                    del entries[i]
            elif i is None:
                entries.append({"path": list(path), "tol": val})
            else:
                entries[i]["tol"] = val
        self.doc.edit(tr("Change material parameter tolerance"), mut)

    def _update_rho_enabled(self):
        """rho couples a loss error to its real-part error, so it needs at least one independent loss tolerance."""
        self.rho.setEnabled(not all(chk.isChecked() for chk in self.follow.values()))

    def _commit(self, *_):
        if self._loading:
            return
        band = self.chk_band.isChecked()
        self.b_lo.setEnabled(band)
        self.b_hi.setEnabled(band)
        self._apply_corner_state()
        for k, chk in self.follow.items():
            self.d[k].setEnabled(not chk.isChecked())
        self._update_rho_enabled()

        def mut(p):
            s = p.tolerance
            s.n_samples = self.n.value()
            s.distribution = self.dist.currentData()
            s.seed = None if self.seed.value() < 0 else self.seed.value()
            for k, sp in self.d.items():
                follows = k in _LOSS_BASE and self.follow[k].isChecked()
                setattr(s, k, None if follows else sp.value() / 100)
            s.loss_correlation = round(self.rho.value(), 2)
            s.target_db = rl_display(self.target.value(), self.ctx.rl_positive)
            s.angle = self.angle.value()
            s.pol = self.pol.currentData()
            f_lo, f_hi = self.band.values()
            if band and f_hi > f_lo:
                s.band_min, s.band_max = f_lo, f_hi
            elif not band:
                s.band_min = s.band_max = None
        self.doc.edit_settings(mut)
        self.plot.mark_dirty()

    def _on_cell(self, item):
        if self._loading or item.column() == 0:
            return
        uid = self.tbl.item(item.row(), 0).data(Qt.UserRole)
        key = _KEYS[item.column() - 1]
        text = item.text().strip().replace("%", "")
        if text:
            try:
                val = float(text)
            except ValueError:
                self.refresh()
                return
            ok = -1.0 <= val <= 1.0 if key in _COEFF_KEYS else val >= 0
            if not ok:
                self.refresh()
                return
            if key not in _COEFF_KEYS:
                val /= 100
        else:
            val = None

        def mut(p):
            d = p.tolerance.per_layer.setdefault(uid, {})
            if val is None:
                d.pop(key, None)
            else:
                d[key] = val
            if not d:
                p.tolerance.per_layer.pop(uid, None)
        self.doc.edit(tr("Change layer tolerance"), mut)

    # ------------------------------------------------------------------------
    def run(self):
        if self.thread is not None:
            return
        p = self.doc.project
        f = tolerance_frequencies(p)
        s = p.tolerance
        band = yield_intervals(p)
        mode = self.angle_mode.currentData()
        if mode and not p.optimization.enabled_targets():
            QMessageBox.information(self, tr("Tolerance analysis"),
                                    tr("Checking the target angles needs at least one enabled optimisation target."))
            return
        self._result_targets = _targets_key(p)
        self.worker = ToleranceWorker(p, f, band, angle_mode=mode)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.thread = start_worker(self.worker, self)
        self.thread.finished.connect(self._on_done)
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.setRange(0, s.n_samples)
        self.progress.setValue(0)

    def stop(self):
        if self.worker is not None:
            self.worker.request_stop()

    def shutdown(self):
        if self.worker is not None:
            self.worker.request_stop()
        if self.thread is not None:
            self.thread.wait(5000)

    def _on_progress(self, k, n):
        self.progress.setRange(0, n)
        self.progress.setValue(k)

    def _clipped_text(self, res):
        """A note on material-parameter draws clipped to their bounds, or ""."""
        hit = [c for c in getattr(res, "clipped", []) if c["n"]]
        if not hit:
            return ""
        items = "; ".join(f"{'/'.join(str(x) for x in c['path'][1:])}: {c['n']}" for c in hit)
        return tr("Samples clipped to physical bounds (the tolerance is wide for these parameters): {items}.",
                  items=items)

    def _on_finished(self, res):
        self.plot.result = res
        self.plot.mark_dirty()
        clipped = self._clipped_text(res)
        if isinstance(res, CornerResult):
            label = lambda i: corner_label(*res.corners[i][:4])  # noqa: E731
            lowest = [f"{label(i)}: {100 * res.corners[i][5].yield_fraction:.1f}%" for i in res.per_target().values()]
            text = tr("Weakest (plotted): {c}. Lowest yield per target: {rows}",
                      c=label(res.worst), rows=" · ".join(lowest))
            for ti in res.fallback_targets:
                text += " " + tr("Target {n}: fewer than 2 angle-grid points, so the two ends of its range were used.",
                                 n=ti + 1)
            self.lbl_corners.setText(text + (" " + clipped if clipped else ""))
            self.lbl_corners.setToolTip("\n".join(f"{label(i)}: {100 * row[5].yield_fraction:.1f}%"
                                                   for i, row in enumerate(res.corners)))
            self.lbl_corners.setVisible(True)
            if res.angle_mode == "grid":
                msg = tr("Tolerance analysis: joint yield {y:.1f}% over {n} angle-grid points",
                         y=100 * (res.joint_yield_fraction or 0.0), n=len(res.corners))
            else:
                msg = tr("Tolerance analysis: joint yield {y:.1f}% over {n} corners",
                         y=100 * (res.joint_yield_fraction or 0.0), n=len(res.corners))
            self.statusMessage.emit(msg)
            return
        self.lbl_corners.setText(clipped)
        self.lbl_corners.setToolTip("")
        self.lbl_corners.setVisible(bool(clipped))
        self.statusMessage.emit(tr("Tolerance analysis: yield {y:.1f}% of {n} samples",
                                   y=100 * res.yield_fraction, n=res.n_samples))

    def _on_failed(self, msg):
        QMessageBox.critical(self, tr("Tolerance analysis failed"), msg)

    def _on_done(self):
        self.thread = None
        self.worker = None
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def _apply_corner_state(self):
        # Per-target runs use each target's own angle, polarisation, band and goal.
        if self.angle_mode.currentData():
            for w in (self.target, self.angle, self.pol, self.chk_band, self.b_lo, self.b_hi):
                w.setEnabled(False)

    def _on_corners_toggled(self, *_):
        if self.angle_mode.currentData():
            self._apply_corner_state()
        else:
            for w in (self.target, self.angle, self.pol, self.chk_band):
                w.setEnabled(True)
            self.refresh()  # restores the band fields' own enabled state

    def invalidate(self):
        """The design changed: the previous result no longer matches."""
        if self.plot.result is not None:
            self.plot.result = None
            self.plot.mark_dirty()
            self.lbl_corners.setVisible(False)

    def settings_changed(self):
        """Drop a multi-angle result once the enabled targets differ from the ones it was computed for: its rows
        index those targets (drawing it against other targets plotted the wrong band or raised IndexError)."""
        if isinstance(self.plot.result, CornerResult) and _targets_key(self.doc.project) != self._result_targets:
            self.invalidate()


def _targets_key(project):
    return json.dumps([t.to_dict() for t in project.optimization.enabled_targets()], sort_keys=True)


_ = (QLabel, SlabLayer)
