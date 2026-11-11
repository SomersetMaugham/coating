"""eps and mu of a sample from a measured two-port .s2p (the dialog of ``coating-cli extract-nrw``)."""

from __future__ import annotations

import os

import matplotlib
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from coating_studio.core.constants import C0
from coating_studio.gui import spectral
from coating_studio.gui.icons import set_button_icon
from coating_studio.gui.theme import mpl_rc
from coating_studio.gui.widgets.inputs import muted
from coating_studio.i18n import tr
from coating_studio.materials.extraction import RECIPROCITY, SMALL_S11, nrw
from coating_studio.materials.models import TabulatedMaterial
from coating_studio.touchstone import TouchstoneError, parse_s2p

NRW_PREFIX = "NRW extraction from"  # start of the provenance note of an extracted material


def _number(edit):
    """The value of a field, or None if it is empty or not a finite number."""
    try:
        value = float(edit.text().strip())
    except ValueError:
        return None
    return value if np.isfinite(value) else None


def warning_text(code, a):
    return {
        "half_wave_resonance": lambda: tr("|S11| < {s:g} at {n} frequencies: the sample is close to a multiple of half a "
                                          "wavelength there and the values are unreliable (shaded).", s=SMALL_S11,
                                          n=len(a["f_hz"])),
        "branch_suspect": lambda: tr("Phase branch {b} looks wrong; branch {s} fits the measured group delay better.",
                                     b=a["branch"], s=a["suggested_branch"]),
        "nonpassive": lambda: tr("The result shows gain (ε″ or μ″ < 0) at {n} frequencies.", n=len(a["f_hz"])),
        "nonreciprocal": lambda: tr("S21 and S12 differ by up to {r:.3g} (more than {lim:g}): check the calibration; "
                                    "their mean was used.", r=a["max_relative"], lim=RECIPROCITY),
    }[code]()


class NrwDialog(QDialog):
    """Every physical input is required and starts empty, so that nothing is invented.  The material can only be created
    while the inputs still match the computed result."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.project = ctx.project
        self.data = None  # (f, s11, s21, s12, ref) of the loaded file
        self.path = None
        self.result = None  # NrwResult for the current inputs
        self.result_material = None
        self.setWindowTitle(tr("Extract ε, μ from S-parameters"))
        self.resize(980, 640)

        box = QGroupBox(tr("Measurement"))
        form = QFormLayout(box)
        file_row = QHBoxLayout()
        self.lbl_file = muted(tr("No file chosen."))
        self.lbl_file.setWordWrap(True)
        b = QPushButton(tr("Open .s2p…"))
        set_button_icon(b, "import")
        b.clicked.connect(self._browse)
        file_row.addWidget(self.lbl_file, 1)
        file_row.addWidget(b)
        form.addRow(tr("Two-port file"), file_row)
        self.ed_thick = QLineEdit()
        self.cb_line = QComboBox()
        self.cb_line.addItem(tr("Coaxial line or free space (TEM)"), "tem")
        self.cb_line.addItem(tr("Rectangular waveguide (TE10)"), "waveguide")
        self.ed_a = QLineEdit()
        self.ed_off1, self.ed_off2 = QLineEdit("0"), QLineEdit("0")
        self.sp_branch = QSpinBox()
        self.sp_branch.setRange(0, 1000)
        self.sp_branch.setToolTip(tr("Phase branch n at the lowest frequency: 0 while the sample is thinner than half a "
                                     "wavelength there."))
        form.addRow(tr("Sample thickness [mm]"), self.ed_thick)
        form.addRow(tr("Line"), self.cb_line)
        form.addRow(tr("Waveguide broad wall a [mm]"), self.ed_a)
        form.addRow(tr("Empty line before the sample [mm]"), self.ed_off1)
        form.addRow(tr("Empty line after the sample [mm]"), self.ed_off2)
        form.addRow(tr("Phase branch"), self.sp_branch)
        self.form = form
        form.setRowVisible(self.ed_a, False)
        form.addRow(muted(tr("The S-parameters must be referred to the empty line (as a TRL calibration does). The offsets "
                             "move reference planes that sit in the empty line onto the sample faces.")))

        out = QGroupBox(tr("New material"))
        of = QFormLayout(out)
        self.ed_name = QLineEdit()
        self.ed_rho = QLineEdit()
        of.addRow(tr("Name"), self.ed_name)
        of.addRow(tr("Density [kg/m³]"), self.ed_rho)

        self.btn_compute = QPushButton(tr("Extract"))
        set_button_icon(self.btn_compute, "run", True)
        self.btn_compute.setObjectName("primary")
        self.btn_compute.clicked.connect(self.compute)
        self.btn_branch = QPushButton()
        self.btn_branch.setVisible(False)
        self.btn_branch.clicked.connect(self._use_suggested)
        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setObjectName("banner")
        self.lbl_status.setVisible(False)

        left = QVBoxLayout()
        left.addWidget(box)
        left.addWidget(out)
        row = QHBoxLayout()
        row.addWidget(self.btn_compute)
        row.addWidget(self.btn_branch)
        row.addStretch(1)
        left.addLayout(row)
        left.addWidget(self.lbl_status)
        left.addStretch(1)
        self.fig = Figure(figsize=(5, 4), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.fig)
        body = QHBoxLayout()
        body.addLayout(left, 0)
        body.addWidget(self.canvas, 1)
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.button(QDialogButtonBox.Ok).setText(tr("Create material"))
        self.bb.accepted.connect(self._accept)
        self.bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(body, 1)
        lay.addWidget(self.bb)

        self.cb_line.currentIndexChanged.connect(self._on_line)
        for w in (self.ed_thick, self.ed_a, self.ed_off1, self.ed_off2):
            w.textEdited.connect(self._invalidate)
        self.sp_branch.valueChanged.connect(self._invalidate)
        self._invalidate()

    # ------------------------------------------------------------------
    def _on_line(self, _index):
        self.form.setRowVisible(self.ed_a, self.cb_line.currentData() == "waveguide")
        self._invalidate()

    def _invalidate(self, *_):
        """Inputs changed: the shown result no longer applies."""
        self.result = None
        self.bb.button(QDialogButtonBox.Ok).setEnabled(False)
        self.btn_branch.setVisible(False)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Open two-port S-parameters"), "",
                                              tr("Touchstone two-port (*.s2p);;All files (*)"))
        if path:
            self.load_file(path)

    def load_file(self, path):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                self.data = parse_s2p(fh.read())
        except (OSError, TouchstoneError) as e:
            QMessageBox.critical(self, tr("Cannot read the file"), str(e))
            return False
        self.path = path
        f = self.data[0]
        unit = spectral.unit_of(self.project)
        self.lbl_file.setText(tr("{name}: {n} points, {range}, R = {r:g} Ω", name=os.path.basename(path), n=len(f),
                                 range=spectral.fmt_range(f[0], f[-1], unit, 5), r=self.data[5]))
        if not self.ed_name.text().strip():
            self.ed_name.setText(os.path.splitext(os.path.basename(path))[0])
        self._invalidate()
        return True

    def _inputs(self):
        """(thickness m, cutoff Hz or None, offset1 m, offset2 m) or an error message."""
        if self.data is None:
            return tr("Choose a two-port file.")
        d = _number(self.ed_thick)
        if d is None or d <= 0:
            return tr("Enter the sample thickness.")
        cutoff = None
        if self.cb_line.currentData() == "waveguide":
            a = _number(self.ed_a)
            if a is None or a <= 0:
                return tr("Enter the waveguide's broad wall a.")
            cutoff = C0 / (2 * a * 1e-3)
        o1, o2 = _number(self.ed_off1), _number(self.ed_off2)
        if o1 is None or o2 is None or o1 < 0 or o2 < 0:
            return tr("Offsets must be zero or positive.")
        return d * 1e-3, cutoff, o1 * 1e-3, o2 * 1e-3

    def compute(self):
        inp = self._inputs()
        if isinstance(inp, str):
            self._status(inp, "error")
            return
        d, cutoff, o1, o2 = inp
        f, s11, s21, s12, _s22, _ref = self.data
        try:
            r = nrw(f, s11, s21, d, cutoff, self.sp_branch.value(), s12=s12, offset1=o1, offset2=o2)
        except ValueError as e:
            self._status(str(e), "error")
            self._draw(None)
            return
        self.result = r
        msgs = [warning_text(code, a) for code, a in r.warnings]
        self._status("\n".join("• " + m for m in msgs) if msgs else tr("No warnings."), "warning" if msgs else "ok")
        if r.suggested_branch != r.branch:
            self.btn_branch.setText(tr("Use branch {n}", n=r.suggested_branch))
            self.btn_branch.setVisible(True)
        self.bb.button(QDialogButtonBox.Ok).setEnabled(True)
        self._draw(r)

    def _use_suggested(self):
        if self.result is not None:
            self.sp_branch.setValue(self.result.suggested_branch)
            self.compute()

    def _status(self, text, level):
        c = self.ctx.colors
        col = {"error": c.error, "warning": c.warn}.get(level, c.muted)
        self.lbl_status.setStyleSheet(f"color: {col}; border: 1px solid {col};")
        self.lbl_status.setText(text)
        self.lbl_status.setVisible(True)

    def _draw(self, r):
        c = self.ctx.colors
        with matplotlib.rc_context(mpl_rc(c)):
            self.fig.clear()
            self.fig.set_facecolor(c.base)
            if r is not None:
                unit = spectral.unit_of(self.project)
                x = spectral.x_values(r.f, unit)
                for k, (vals, sym) in enumerate(((r.eps, "ε"), (r.mu, "μ"))):
                    ax = self.fig.add_subplot(2, 1, k + 1)
                    ax.plot(x, vals.real, color=c.series[0], label=f"{sym}′")
                    ax.plot(x, -vals.imag, color=c.series[1], ls="--", label=f"{sym}″")
                    for xi in x[r.resonant]:
                        ax.axvline(xi, color=c.warn, alpha=0.15, lw=3)
                    spectral.set_xlim(ax, x)
                    ax.legend(loc="best", fontsize=8)
                ax.set_xlabel(spectral.axis_label(unit))
        self.canvas.draw_idle()

    def _accept(self):
        if self.result is None:
            return
        name = self.ed_name.text().strip()
        if not name:
            self._status(tr("Enter a name."), "error")
            return
        rho = _number(self.ed_rho)
        if rho is None or rho <= 0:
            self._status(tr("Enter the sample's density (it is needed for the areal mass)."), "error")
            return
        r = self.result
        line = "TEM" if self.cb_line.currentData() == "tem" else f"TE10 waveguide a = {self.ed_a.text().strip()} mm"
        note = (f"{NRW_PREFIX} {os.path.basename(self.path)}, d = {self.ed_thick.text().strip()} mm, {line}, "
                f"branch {r.branch}")
        if np.any(r.resonant):
            note += f"; {int(np.count_nonzero(r.resonant))} points near half-wave resonances"
        self.result_material = TabulatedMaterial(name, r.f, r.eps.real, -r.eps.imag, r.mu.real, -r.mu.imag,
                                                 source=os.path.basename(self.path), density=rho, note=note)
        self.accept()
