"""Manufacturing-tolerance (Monte-Carlo) tab."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from coating_studio.core.structure import SheetLayer, SlabLayer
from coating_studio.gui.icons import set_button_icon
from coating_studio.gui.plots.base import PlotView
from coating_studio.gui.widgets.inputs import SciSpinBox, muted
from coating_studio.gui.workers import ToleranceWorker, start_worker
from coating_studio.i18n import tr

_KEYS = ("thickness", "eps", "mu", "sheet")


def yield_band(p):
    """Custom tolerance band if set, otherwise the optimisation target band."""
    s = p.tolerance
    if s.band_min and s.band_max and s.band_max > s.band_min:
        return s.band_min, s.band_max
    return p.optimization.f_min, p.optimization.f_max


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
        sgn = -1 if pos else 1
        c = self.ctx.colors
        s = self.ctx.project.tolerance
        ax.set_xlabel(tr("Frequency [GHz]"))
        ax.set_ylabel(tr("Reflection loss [dB] (higher is better)") if pos
                      else tr("Reflection loss [dB] (lower is better)"))
        if r is None:
            ax.text(0.5, 0.5, tr("Run the analysis to see the spread of reflection loss."),
                    ha="center", va="center", transform=ax.transAxes, color=c.muted)
            return None
        x = r.f / 1e9
        ax.fill_between(x, sgn * r.lower_db, sgn * r.upper_db, color=c.series[0], alpha=0.22,
                        label=tr("{a:g}–{b:g} percentile band", a=s.lower_pct, b=s.upper_pct))
        ax.plot(x, sgn * r.median_db, color=c.series[0], label=tr("Median"))
        ax.plot(x, sgn * r.nominal_db, color=c.series[1], ls="--", label=tr("Nominal design"))
        ax.axhline(sgn * s.target_db, color=c.muted, lw=1, ls=":", label=tr("Target"))
        lo, hi = yield_band(self.ctx.project)
        ax.axvspan(lo / 1e9, hi / 1e9, color=c.series[2], alpha=0.07)
        if self.ctx.project.sweep.log_f:
            ax.set_xscale("log")
        ax.set_xlim(x[0], x[-1])
        ax.legend(loc="best")
        ax.set_title(tr("Yield {y:.1f}% ({n} samples)", y=100 * r.yield_fraction, n=r.n_samples),
                     fontsize=10, loc="left")
        return None

    def format_cursor(self, ax, x, y):
        return tr("f = {f} GHz, value = {v}", f=f"{x:.5g}", v=f"{y:.4g}")

    def data_table(self):
        r = self.result
        if r is None:
            return None
        return (["f [GHz]", "nominal [dB]", "median [dB]", "lower [dB]", "upper [dB]"],
                [[f"{a / 1e9:.9g}", f"{b:.6g}", f"{c:.6g}", f"{d:.6g}", f"{e:.6g}"]
                 for a, b, c, d, e in zip(r.f, r.nominal_db, r.median_db, r.lower_db, r.upper_db)])


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
        for key, lab in (("thickness", tr("Thickness")), ("eps", tr("Permittivity ε")),
                         ("mu", tr("Permeability μ")), ("sheet", tr("Sheet impedance"))):
            sp = SciSpinBox(minimum=0, maximum=100, suffix="%")
            self.d[key] = sp
            f.addRow(lab, sp)
        ll.addWidget(g)

        g = QGroupBox(tr("Per-layer tolerances (%)"))
        gl = QVBoxLayout(g)
        self.tbl = QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels([tr("Layer"), tr("Thickness"), "ε", "μ", tr("Sheet")])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionMode(QAbstractItemView.NoSelection)
        th = self.tbl.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 5):
            th.setSectionResizeMode(c, QHeaderView.Fixed)
            self.tbl.setColumnWidth(c, 58)
        self.tbl.setMinimumHeight(120)
        gl.addWidget(self.tbl)
        gl.addWidget(muted(tr("Blank cells use the default tolerance.")))
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
        self.b_lo = SciSpinBox(minimum=1e-6, maximum=1e6, suffix="GHz")
        self.b_hi = SciSpinBox(minimum=1e-6, maximum=1e6, suffix="GHz")
        f.addRow(tr("Target RL (≤)"), self.target)
        f.addRow(tr("Incidence angle"), self.angle)
        f.addRow(tr("Polarisation"), self.pol)
        f.addRow("", self.chk_band)
        f.addRow(tr("Band from"), self.b_lo)
        f.addRow(tr("to"), self.b_hi)
        f.addRow(muted(tr("Yield = share of samples whose worst RL in the band meets the target "
                          "(target in the negative-dB convention). Without a custom band the "
                          "optimisation target band is used.")))
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
        split.addWidget(right)
        split.setSizes([440, 600])
        scroll.setMinimumWidth(400)

        self.n.valueChanged.connect(self._commit)
        self.seed.valueChanged.connect(self._commit)
        self.dist.currentIndexChanged.connect(self._commit)
        self.pol.currentIndexChanged.connect(self._commit)
        self.chk_band.toggled.connect(self._commit)
        for w in list(self.d.values()) + [self.target, self.angle, self.b_lo, self.b_hi]:
            w.valueEdited.connect(self._commit)
        self.tbl.itemChanged.connect(self._on_cell)
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
                sp.set_value(getattr(s, k) * 100)
            self.target.set_value(s.target_db)
            self.angle.set_value(s.angle)
            self.pol.setCurrentIndex({"avg": 0, "TE": 1, "TM": 2}.get(s.pol, 0))
            has_band = s.band_min is not None and s.band_max is not None
            self.chk_band.setChecked(has_band)
            lo, hi = yield_band(p)
            self.b_lo.set_value(lo / 1e9)
            self.b_hi.set_value(hi / 1e9)
            self.b_lo.setEnabled(has_band)
            self.b_hi.setEnabled(has_band)
            layers = p.structure.layers
            self.tbl.setRowCount(len(layers))
            for r, ly in enumerate(layers):
                name = ly.name or (tr("Sheet") if isinstance(ly, SheetLayer) else ly.material)
                it = QTableWidgetItem(f"{r + 1}. {name}")
                it.setFlags(Qt.ItemIsEnabled)
                it.setData(Qt.UserRole, ly.uid)
                self.tbl.setItem(r, 0, it)
                for c, key in enumerate(_KEYS, start=1):
                    applicable = (key == "sheet") == isinstance(ly, SheetLayer)
                    val = s.per_layer.get(ly.uid, {}).get(key)
                    cell = QTableWidgetItem("" if val is None or not applicable else f"{val * 100:g}")
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if not applicable:
                        cell.setFlags(Qt.NoItemFlags)
                        cell.setText("—")
                    self.tbl.setItem(r, c, cell)
        finally:
            self._loading = False

    def _commit(self, *_):
        if self._loading:
            return
        band = self.chk_band.isChecked()
        self.b_lo.setEnabled(band)
        self.b_hi.setEnabled(band)

        def mut(p):
            s = p.tolerance
            s.n_samples = self.n.value()
            s.distribution = self.dist.currentData()
            s.seed = None if self.seed.value() < 0 else self.seed.value()
            for k, sp in self.d.items():
                setattr(s, k, sp.value() / 100)
            s.target_db = self.target.value()
            s.angle = self.angle.value()
            s.pol = self.pol.currentData()
            if band and self.b_hi.value() > self.b_lo.value():
                s.band_min, s.band_max = self.b_lo.value() * 1e9, self.b_hi.value() * 1e9
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
                val = float(text) / 100
            except ValueError:
                self.refresh()
                return
            if val < 0:
                self.refresh()
                return
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
        sw = p.sweep
        f = np.geomspace(sw.f_min, sw.f_max, min(sw.n_f, 301)) if sw.log_f else \
            np.linspace(sw.f_min, sw.f_max, min(sw.n_f, 301))
        s = p.tolerance
        band = yield_band(p)
        self.worker = ToleranceWorker(p, f, band)
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

    def _on_finished(self, res):
        self.plot.result = res
        self.plot.mark_dirty()
        self.statusMessage.emit(tr("Tolerance analysis: yield {y:.1f}% of {n} samples",
                                   y=100 * res.yield_fraction, n=res.n_samples))

    def _on_failed(self, msg):
        QMessageBox.critical(self, tr("Tolerance analysis failed"), msg)

    def _on_done(self):
        self.thread = None
        self.worker = None
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def invalidate(self):
        """The design changed: the previous result no longer matches."""
        if self.plot.result is not None:
            self.plot.result = None
            self.plot.mark_dirty()


_ = (QLabel, SlabLayer)
