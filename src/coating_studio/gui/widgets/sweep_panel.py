"""Analysis (sweep) settings."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QGroupBox, QLabel, QSpinBox, QVBoxLayout, QWidget

from coating_studio.core.units import LENGTH_LABEL, LENGTH_UNITS, SPECTRAL_UNITS
from coating_studio.gui.spectral import SpectralInputs, quantity_name, unit_label
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
        self.f_min = SciSpinBox(minimum=1e-6, maximum=1e6, suffix="")
        self.f_max = SciSpinBox(minimum=1e-6, maximum=1e6, suffix="")
        self.n_f = QSpinBox()
        self.n_f.setRange(2, 20001)
        self.spacing = QComboBox()  # (log_f, uniform_wavelength) of SweepSettings
        self.spacing.addItem(tr("Even in frequency"), "linear")
        self.spacing.addItem(tr("Even in wavelength"), "wavelength")
        self.spacing.addItem(tr("Logarithmic (log axis)"), "log")
        self.spacing.setToolTip(tr("How the sweep points are spread. Even in wavelength suits optical spectra; it is "
                                   "sparse at high frequencies ((f_max/f_min)² wider steps), so a narrow band there "
                                   "may fall between points. Logarithmic also draws a log axis."))
        self.angle = SciSpinBox(minimum=0.0, maximum=89.9, suffix="°")
        self.unit = QComboBox()
        for u in SPECTRAL_UNITS:
            self.unit.addItem(f"{quantity_name(u)} [{unit_label(u)}]", u)
        self.unit.setToolTip(tr("Unit of the spectral axis in plots, inputs and exports. Wavelengths are vacuum "
                                "wavelengths (c/f). Display only: the project keeps frequencies."))
        f1.addRow(tr("Spectral axis"), self.unit)
        self.length_unit = QComboBox()
        for u in LENGTH_UNITS:
            self.length_unit.addItem(LENGTH_LABEL[u], u)
        self.length_unit.setToolTip(tr("Unit of layer thicknesses in the layer stack, properties, optimisation and "
                                       "report. Display only: the project keeps metres."))
        f1.addRow(tr("Thickness unit"), self.length_unit)
        f1.addRow(tr("Start"), self.f_min)
        f1.addRow(tr("End"), self.f_max)
        f1.addRow(tr("Points"), self.n_f)
        f1.addRow(tr("Point spacing"), self.spacing)
        f1.addRow(tr("Incidence angle"), self.angle)
        lay.addWidget(g1)

        g2 = QGroupBox(tr("Angle sweep"))
        f2 = QFormLayout(g2)
        f2.setLabelAlignment(Qt.AlignRight)
        self.a_min = SciSpinBox(minimum=0.0, maximum=89.9, suffix="°")
        self.a_max = SciSpinBox(minimum=0.0, maximum=89.9, suffix="°")
        self.n_a = QSpinBox()
        self.n_a.setRange(2, 2001)
        self.f_at = SciSpinBox(minimum=1e-6, maximum=1e6, suffix="")
        f2.addRow(tr("From"), self.a_min)
        f2.addRow(tr("To"), self.a_max)
        f2.addRow(tr("Points"), self.n_a)
        self.lbl_at = QLabel(tr("Frequency"))  # "Wavelength" / "Wavenumber" in those units (refresh)
        f2.addRow(self.lbl_at, self.f_at)
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
        self.band = SpectralInputs(self.f_min, self.f_max)
        self.at = SpectralInputs(self.f_at)

        self.unit.currentIndexChanged.connect(self._commit)
        self.length_unit.currentIndexChanged.connect(self._commit)
        for w in (self.f_min, self.f_max, self.angle, self.a_min, self.a_max, self.f_at):
            w.valueEdited.connect(self._commit)
        for w in (self.n_f, self.n_a, self.map_nf, self.map_na):
            w.valueChanged.connect(self._commit)
        self.spacing.currentIndexChanged.connect(self._commit)
        self.refresh()

    def refresh(self):
        s = self.doc.project.sweep
        self._loading = True
        try:
            self.unit.setCurrentIndex(max(self.unit.findData(s.spectral_unit), 0))
            self.length_unit.setCurrentIndex(max(self.length_unit.findData(s.length_unit), 0))
            self.band.show(s.spectral_unit, s.f_min, s.f_max)
            self.n_f.setValue(s.n_f)
            mode = "log" if s.log_f else ("wavelength" if s.uniform_wavelength else "linear")
            self.spacing.setCurrentIndex(max(self.spacing.findData(mode), 0))
            self.angle.set_value(s.angle)
            self.a_min.set_value(s.angle_min)
            self.a_max.set_value(s.angle_max)
            self.n_a.setValue(s.n_angle)
            self.at.show(s.spectral_unit, s.f_at)
            self.lbl_at.setText(quantity_name(s.spectral_unit))
            self.map_nf.setValue(s.map_n_f)
            self.map_na.setValue(s.map_n_angle)
        finally:
            self._loading = False

    def _commit(self, *_):
        if self._loading:
            return
        f_min, f_max = self.band.values()  # only an edited box is converted; the other keeps its Hz value
        f_at = self.at.value()
        unit = self.unit.currentData()
        length_unit = self.length_unit.currentData()
        a_min, a_max = self.a_min.value(), self.a_max.value()
        if f_max <= f_min or a_max <= a_min:
            return  # wait until the range is valid

        def mut(p):
            s = p.sweep
            s.f_min, s.f_max, s.n_f = f_min, f_max, self.n_f.value()
            mode = self.spacing.currentData()
            s.log_f, s.uniform_wavelength = mode == "log", mode == "wavelength"
            s.angle = self.angle.value()
            s.angle_min, s.angle_max, s.n_angle = a_min, a_max, self.n_a.value()
            s.f_at = f_at
            s.spectral_unit = unit
            s.length_unit = length_unit
            s.map_n_f, s.map_n_angle = self.map_nf.value(), self.map_na.value()
        self.doc.edit_settings(mut)
