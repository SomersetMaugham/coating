"""Analysis (sweep) settings."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QSpinBox, QVBoxLayout, QWidget

from coating_studio.gui.widgets.inputs import SciSpinBox
from coating_studio.i18n import tr


class SweepPanel(QWidget):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self._loading = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        g1 = QGroupBox(tr("Frequency sweep"))
        f1 = QFormLayout(g1)
        f1.setLabelAlignment(Qt.AlignRight)
        self.f_min = SciSpinBox(minimum=1e-6, maximum=1e6, suffix="GHz")
        self.f_max = SciSpinBox(minimum=1e-6, maximum=1e6, suffix="GHz")
        self.n_f = QSpinBox()
        self.n_f.setRange(2, 20001)
        self.log_f = QCheckBox(tr("Logarithmic frequency axis"))
        self.angle = SciSpinBox(minimum=0.0, maximum=89.9, suffix="°")
        f1.addRow(tr("Start"), self.f_min)
        f1.addRow(tr("End"), self.f_max)
        f1.addRow(tr("Points"), self.n_f)
        f1.addRow("", self.log_f)
        f1.addRow(tr("Incidence angle"), self.angle)
        lay.addWidget(g1)

        g2 = QGroupBox(tr("Angle sweep"))
        f2 = QFormLayout(g2)
        f2.setLabelAlignment(Qt.AlignRight)
        self.a_min = SciSpinBox(minimum=0.0, maximum=89.9, suffix="°")
        self.a_max = SciSpinBox(minimum=0.0, maximum=89.9, suffix="°")
        self.n_a = QSpinBox()
        self.n_a.setRange(2, 2001)
        self.f_at = SciSpinBox(minimum=1e-6, maximum=1e6, suffix="GHz")
        f2.addRow(tr("From"), self.a_min)
        f2.addRow(tr("To"), self.a_max)
        f2.addRow(tr("Points"), self.n_a)
        f2.addRow(tr("Frequency"), self.f_at)
        lay.addWidget(g2)

        g3 = QGroupBox(tr("Frequency × angle map"))
        f3 = QFormLayout(g3)
        f3.setLabelAlignment(Qt.AlignRight)
        self.map_nf = QSpinBox()
        self.map_nf.setRange(10, 2001)
        self.map_na = QSpinBox()
        self.map_na.setRange(5, 721)
        f3.addRow(tr("Frequency points"), self.map_nf)
        f3.addRow(tr("Angle points"), self.map_na)
        lay.addWidget(g3)
        lay.addStretch(1)

        for w in (self.f_min, self.f_max, self.angle, self.a_min, self.a_max, self.f_at):
            w.valueEdited.connect(self._commit)
        for w in (self.n_f, self.n_a, self.map_nf, self.map_na):
            w.valueChanged.connect(self._commit)
        self.log_f.toggled.connect(self._commit)
        self.refresh()

    def refresh(self):
        s = self.doc.project.sweep
        self._loading = True
        try:
            self.f_min.set_value(s.f_min / 1e9)
            self.f_max.set_value(s.f_max / 1e9)
            self.n_f.setValue(s.n_f)
            self.log_f.setChecked(s.log_f)
            self.angle.set_value(s.angle)
            self.a_min.set_value(s.angle_min)
            self.a_max.set_value(s.angle_max)
            self.n_a.setValue(s.n_angle)
            self.f_at.set_value(s.f_at / 1e9)
            self.map_nf.setValue(s.map_n_f)
            self.map_na.setValue(s.map_n_angle)
        finally:
            self._loading = False

    def _commit(self, *_):
        if self._loading:
            return
        f_min, f_max = self.f_min.value() * 1e9, self.f_max.value() * 1e9
        a_min, a_max = self.a_min.value(), self.a_max.value()
        if f_max <= f_min or a_max <= a_min:
            return  # wait until the range is valid

        def mut(p):
            s = p.sweep
            s.f_min, s.f_max, s.n_f = f_min, f_max, self.n_f.value()
            s.log_f = self.log_f.isChecked()
            s.angle = self.angle.value()
            s.angle_min, s.angle_max, s.n_angle = a_min, a_max, self.n_a.value()
            s.f_at = self.f_at.value() * 1e9
            s.map_n_f, s.map_n_angle = self.map_nf.value(), self.map_na.value()
        self.doc.edit_settings(mut)
