"""Fit a causal Debye/Lorentz model to measured eps/mu data."""

from __future__ import annotations

import matplotlib
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
)

from coating_studio.gui.icons import set_button_icon
from coating_studio.gui import spectral
from coating_studio.gui.theme import mpl_rc
from coating_studio.gui.widgets.inputs import muted
from coating_studio.i18n import tr
from coating_studio.materials.fitting import FitSpec, fit_dispersive


class FitDialog(QDialog):
    def __init__(self, material, ctx, parent=None):
        super().__init__(parent)
        self.src, self.ctx = material, ctx
        self.result_material = None
        self._fit = None
        self.setWindowTitle(tr("Fit dispersion model — {n}", n=material.name))
        self.resize(860, 560)

        self.ed_name = QLineEdit(tr("{n} (fit)", n=material.name))
        top = QFormLayout()
        top.addRow(tr("New material name"), self.ed_name)

        def side(title, allow_sigma):
            g = QGroupBox(title)
            f = QFormLayout(g)
            nd, nl, nh = QSpinBox(), QSpinBox(), QSpinBox()
            nd.setRange(0, 4)
            nl.setRange(0, 4)
            nh.setRange(0, 4)
            nh.setToolTip(tr("Broadened relaxations Δ/(1 + (jf/f₀)^α)^β, for polymer and composite data that one Debye "
                             "term does not fit."))
            cl = QCheckBox(tr("Constant loss term"))
            f.addRow(tr("Debye terms"), nd)
            f.addRow(tr("Lorentz terms"), nl)
            f.addRow(tr("Havriliak-Negami terms"), nh)
            sg = None
            if allow_sigma:
                sg = QCheckBox(tr("Conductivity σ"))
                f.addRow("", sg)
            f.addRow("", cl)
            return g, nd, nl, nh, cl, sg

        ge, self.e_nd, self.e_nl, self.e_nh, self.e_cl, self.e_sig = side(tr("Permittivity ε"), True)
        gm, self.m_nd, self.m_nl, self.m_nh, self.m_cl, _ = side(tr("Permeability μ"), False)
        self.e_nd.setValue(1)
        magnetic = np.any(np.abs(material.mu_re - 1) > 1e-6) or np.any(np.abs(material.mu_loss) > 1e-6)
        self.m_nd.setValue(1 if magnetic else 0)
        row = QHBoxLayout()
        row.addWidget(ge)
        row.addWidget(gm)

        self.btn_fit = QPushButton(tr("Fit"))
        set_button_icon(self.btn_fit, "fit", True)
        self.btn_fit.setObjectName("primary")
        self.btn_fit.clicked.connect(self.do_fit)
        self.lbl = muted(tr("Choose the number of terms and press Fit."))
        fr = QHBoxLayout()
        fr.addWidget(self.btn_fit)
        fr.addWidget(self.lbl, 1)

        self.fig = Figure(figsize=(6, 3), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.fig)

        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.button(QDialogButtonBox.Ok).setText(tr("Create material"))
        self.bb.button(QDialogButtonBox.Ok).setEnabled(False)
        self.bb.accepted.connect(self._accept)
        self.bb.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(row)
        lay.addLayout(fr)
        lay.addWidget(self.canvas, 1)
        lay.addWidget(self.bb)
        self._plot()

    def do_fit(self):
        m = self.src
        eps = m.eps_re - 1j * m.eps_loss
        mu = m.mu_re - 1j * m.mu_loss
        es = FitSpec(self.e_nd.value(), self.e_nl.value(), self.e_sig.isChecked(), self.e_cl.isChecked(),
                     n_hn=self.e_nh.value())
        ms = FitSpec(self.m_nd.value(), self.m_nl.value(), False, self.m_cl.isChecked(), n_hn=self.m_nh.value())
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._fit = fit_dispersive(self.ed_name.text().strip() or m.name, m.f, eps, mu, es, ms,
                                       density=m.density)
        except Exception as e:  # noqa: BLE001
            self.lbl.setText(tr("Fit failed: {e}", e=e))
            self._fit = None
        finally:
            QApplication.restoreOverrideCursor()
        if self._fit:
            self.lbl.setText(tr("RMS error: ε {e:.3%}, μ {m:.3%} (relative to max |value|)",
                                e=self._fit.rms_eps, m=self._fit.rms_mu))
        self.bb.button(QDialogButtonBox.Ok).setEnabled(self._fit is not None)
        self._plot()

    def _plot(self):
        c = self.ctx.colors
        m = self.src
        with matplotlib.rc_context(mpl_rc(c)):
            self.fig.clear()
            self.fig.set_facecolor(c.base)
            unit = spectral.unit_of(self.ctx.project)
            x = spectral.x_values(m.f, unit)
            f_dense = np.geomspace(m.f[0], m.f[-1], 400)
            fitted = self._fit.material.eps_mu(f_dense, None) if self._fit else None
            for k, (re, loss, sym) in enumerate(((m.eps_re, m.eps_loss, "ε"), (m.mu_re, m.mu_loss, "μ"))):
                ax = self.fig.add_subplot(1, 2, k + 1)
                ax.plot(x, re, "o", ms=3, color=c.series[0], label=f"{sym}′ " + tr("data"))
                ax.plot(x, loss, "s", ms=3, color=c.series[1], label=f"{sym}″ " + tr("data"))
                if fitted is not None:
                    v = np.broadcast_to(fitted[k], f_dense.shape)
                    xd = spectral.x_values(f_dense, unit)
                    ax.plot(xd, v.real, color=c.series[0], label=f"{sym}′ " + tr("fit"))
                    ax.plot(xd, -v.imag, color=c.series[1], ls="--", label=f"{sym}″ " + tr("fit"))
                ax.set_xscale("log" if m.f[-1] / m.f[0] > 20 else "linear")
                spectral.set_xlim(ax, x)
                ax.set_xlabel(spectral.axis_label(unit))
                ax.legend(fontsize=8)
        self.canvas.draw_idle()

    def _accept(self):
        if self._fit is None:
            return
        self.result_material = self._fit.material
        self.result_material.name = self.ed_name.text().strip() or self.result_material.name
        self.accept()


_ = QLabel
