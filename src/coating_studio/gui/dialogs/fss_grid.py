"""Compute the L or C of an RLC sheet from the dimensions of a metal mesh or patch array."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QVBoxLayout

from coating_studio import lengths, spectral
from coating_studio.core.units import LENGTH_LABEL, from_length, to_length
from coating_studio.fss import grid_element
from coating_studio.gui.fmt import fmt_num
from coating_studio.gui.widgets.inputs import SciSpinBox, muted
from coating_studio.i18n import tr


class FssGridDialog(QDialog):
    """``self.element`` is the result after a successful accept; nothing is changed here."""

    def __init__(self, project, sheet, parent=None):
        super().__init__(parent)
        self.project, self.sheet = project, sheet
        self.element = None
        self.setWindowTitle(tr("From grid dimensions"))
        self.unit = lengths.unit_of(project)
        suffix = f" {LENGTH_LABEL[self.unit]}"

        def length_box(metres):
            box = SciSpinBox(minimum=1e-12, maximum=1e12, suffix=suffix)
            box.set_value(to_length(metres, self.unit))
            box.setKeyboardTracking(True)  # the result follows the typing
            box.valueChanged.connect(self._update)
            return box

        self.cb_pattern = QComboBox()
        self.cb_pattern.addItem(tr("Metal mesh"), "mesh")
        self.cb_pattern.addItem(tr("Patch array"), "patch")
        self.cb_pattern.currentIndexChanged.connect(self._update)
        self.sp_period = length_box(5e-3)
        self.sp_width = length_box(0.5e-3)
        self.sp_eps = SciSpinBox(minimum=1.0, maximum=1e6)
        self.sp_eps.set_value(1.0)
        self.sp_eps.setKeyboardTracking(True)
        self.sp_eps.setToolTip(tr("Effective permittivity around the grid: (ε_r + 1)/2 on a substrate, ε_r when "
                                  "embedded, 1 in free space."))
        self.sp_eps.valueChanged.connect(self._update)
        self.chk_keep = QCheckBox(tr("Keep the other element"))
        self.chk_keep.setToolTip(tr("Off: a mesh removes C and a patch removes L, so the sheet is the one the formula "
                                    "describes."))
        self.chk_bounds = QCheckBox(tr("Reset its optimisation range around the new value"))
        self.chk_bounds.setChecked(True)
        self.lbl_result, self.lbl_warn = muted(), muted()
        self.lbl_result.setWordWrap(True)
        self.lbl_warn.setWordWrap(True)
        note = muted(tr("Dense square lattice of ideal conductors, incidence in a principal plane, width or gap much "
                        "smaller than the period. ε_eff = (ε_r + 1)/2 needs a dielectric thick compared with the "
                        "period. The dimensions are not saved."))
        note.setWordWrap(True)

        self.form = QFormLayout()
        self.form.addRow(tr("Pattern"), self.cb_pattern)
        self.form.addRow(tr("Period D"), self.sp_period)
        self.form.addRow(tr("Strip width w"), self.sp_width)
        self.form.addRow(tr("Effective ε"), self.sp_eps)
        self.form.addRow("", self.chk_keep)
        self.form.addRow("", self.chk_bounds)
        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.bb.accepted.connect(self._accept)
        self.bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(self.form)
        lay.addWidget(self.lbl_result)
        lay.addWidget(self.lbl_warn)
        lay.addWidget(note)
        lay.addWidget(self.bb)
        self.resize(460, 380)
        self._update()

    def _compute(self):
        """The result for the boxes as they stand, or None with the reason shown."""
        try:
            return grid_element(self.cb_pattern.currentData(), from_length(self.sp_period.value(), self.unit),
                                from_length(self.sp_width.value(), self.unit), self.sp_eps.value())
        except ValueError:
            return None

    def _max_frequency(self):
        p = self.project
        return max([p.sweep.f_max] + [t.f_max for t in p.optimization.enabled_targets()])

    def _out_of_range(self, element):
        """The optimisation variable the new value falls outside, or None."""
        attr, value = ("L", element.L) if element.pattern == "mesh" else ("C", element.C)
        path = ("layer", self.sheet.uid, attr)
        return next((v for v in self.project.optimization.variables
                     if tuple(v.path) == path and not v.lower <= value <= v.upper), None)

    def _update(self, *_):
        mesh = self.cb_pattern.currentData() == "mesh"
        self.form.labelForField(self.sp_width).setText(tr("Strip width w") if mesh else tr("Gap between patches w"))
        el = self._compute()
        self.bb.button(QDialogButtonBox.Ok).setEnabled(el is not None)
        self.chk_bounds.setVisible(el is not None and self._out_of_range(el) is not None)
        if el is None:
            self.lbl_result.setText(tr("The width must be positive and smaller than the period."))
            self.lbl_warn.setText("")
            return
        value = (f"L = {fmt_num(el.L * 1e9, 5)} nH" if mesh else f"C = {fmt_num(el.C * 1e12, 5)} pF")
        coeff = ", ".join(f"{k} {v:+.4g}" for k, v in el.angle.items())
        unit = self.project.sweep.spectral_unit
        lines = [f"{value} · {coeff}",
                 tr("R stays at {r} Ω/sq; the formula is for ideal conductors.", r=fmt_num(self.sheet.R, 5)),
                 tr("Valid well below {limit}; caution above {caution}.", limit=spectral.fmt_value(el.limit_hz, unit),
                    caution=spectral.fmt_value(el.caution_hz, unit))]
        self.lbl_result.setText("\n".join(lines))
        top, warn = self._max_frequency(), []
        if top >= el.limit_hz:
            warn.append(tr("The sweep or a target reaches {f}, above the validity limit (checked once, now).",
                           f=spectral.fmt_value(top, unit)))
        elif top >= el.caution_hz:
            warn.append(tr("The sweep or a target reaches {f}, in the caution range (checked once, now).",
                           f=spectral.fmt_value(top, unit)))
        if el.wide:
            warn.append(tr("The width is more than half of the period; the formula assumes it is much smaller."))
        self.lbl_warn.setText("\n".join(warn))

    def _accept(self):
        self.element = self._compute()
        if self.element is not None:
            self.accept()
