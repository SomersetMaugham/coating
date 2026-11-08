"""Property editor for the selected layer and for the stack boundaries."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

import math

from coating_studio.core.structure import RLC_MODELS, SlabLayer
from coating_studio import lengths
from coating_studio.gui import spectral
from coating_studio.gui.fmt import fmt_num
from coating_studio.gui.widgets.inputs import SciSpinBox, muted
from coating_studio.i18n import tr
from coating_studio.project import ContinuousVariable, MaterialChoice


def default_lc_bounds(attr, value):
    """Optimisation bounds for L / C: a decade either side (ratio 100, so the optimiser searches on a
    log scale), or 0.1-50 nH for an inductance that is still zero."""
    if value > 0:
        return value / 10, value * 10
    return (0.1e-9, 50e-9) if attr == "L" else (0.005e-12, 0.5e-12)


def _drop_missing_vars(p, ly):
    """Remove optimisation variables for parameters the sheet no longer has (model / capacitor change)."""
    vs = p.optimization.variables
    vs[:] = [v for v in vs if not (v.path[0] == "layer" and v.path[1] == ly.uid and not ly.has_param(v.path[2]))]


class _OptToggle(QCheckBox):
    """'Optimise' checkbox bound to one continuous parameter path."""

    def __init__(self, parent=None):
        super().__init__(tr("Opt."), parent)
        self.setToolTip(tr("Include this value in the optimisation (bounds are set in the Optimisation panel)."))


class PropertiesPanel(QWidget):
    editMaterialsRequested = Signal(str)

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.uid = None
        self._loading = False

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)

        # ---- selected layer ------------------------------------------------
        self.grp_layer = QGroupBox(tr("Selected layer"))
        form = QFormLayout(self.grp_layer)
        form.setLabelAlignment(Qt.AlignRight)
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText(tr("optional"))
        self.ed_name.editingFinished.connect(self._on_name)
        form.addRow(tr("Name"), self.ed_name)

        self.cb_material = QComboBox()
        self.cb_material.activated.connect(self._on_material)
        self.btn_edit_mat = QPushButton(tr("Edit…"))
        self.btn_edit_mat.setToolTip(tr("Open the material manager"))
        self.btn_edit_mat.clicked.connect(lambda: self.editMaterialsRequested.emit(self.cb_material.currentText()))
        row = QHBoxLayout()
        row.addWidget(self.cb_material, 1)
        row.addWidget(self.btn_edit_mat)
        self.row_material = QWidget()
        self.row_material.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        form.addRow(tr("Material"), self.row_material)

        self.sp_thick, self.opt_thick, self.row_thick = self._num_row(0.0, 1e6, "mm", "thickness")
        self.thick = spectral.LengthInputs(self.sp_thick)  # in the project's length unit (mm, µm, nm)
        form.addRow(tr("Thickness"), self.row_thick)
        self.cb_model = QComboBox()
        self.cb_model.addItem(tr("Constant (R + jX)"), "constant")
        self.cb_model.addItem(tr("Series RLC"), "rlc")
        self.cb_model.addItem(tr("Parallel RLC"), "parallel_rlc")
        self.cb_model.setToolTip(tr("Series RLC: Zs = R + jωL + 1/(jωC), the equivalent circuit of a patterned "
                                    "(circuit-analog / FSS) layer. The circuit values are normal-incidence "
                                    "lumped values used for every angle and polarisation - valid for "
                                    "sub-wavelength unit cells.") + "\n"
                                 + tr("Parallel RLC: 1/Zs = 1/R + jωC + 1/(jωL); the sheet opens at resonance, as "
                                      "slot and aperture patterns do."))
        self.cb_model.activated.connect(self._on_model)
        form.addRow(tr("Model"), self.cb_model)
        self.row_model = self.cb_model
        self.sp_R, self.opt_R, self.row_R = self._num_row(1e-3, 1e9, "Ω/sq", "R")
        form.addRow(tr("Resistance R"), self.row_R)
        self.sp_X, self.opt_X, self.row_X = self._num_row(-1e9, 1e9, "Ω/sq", "X")
        form.addRow(tr("Reactance X"), self.row_X)
        self.sp_L, self.opt_L, self.row_L = self._num_row(0.0, 1e6, "nH", "L")
        self.sp_L.setToolTip(tr("In a parallel RLC sheet, 0 means no inductor."))
        form.addRow(tr("Inductance L"), self.row_L)
        self.chk_C = QCheckBox()  # no text: the row label says "Capacitance C" and the panel is narrow
        self.chk_C.setToolTip(tr("Capacitor on/off. Without a capacitor a series sheet is an inductive grid (R + jωL) "
                                 "and a parallel sheet has no capacitive branch."))
        self.chk_C.toggled.connect(self._on_capacitor)
        self.sp_C, self.opt_C, self.row_C = self._num_row(1e-9, 1e9, "pF", "C")
        self.row_C.layout().insertWidget(0, self.chk_C)
        form.addRow(tr("Capacitance C"), self.row_C)
        self.lbl_info = muted()
        form.addRow("", self.lbl_info)
        self._form = form
        lay.addWidget(self.grp_layer)

        # ---- candidate materials (discrete optimisation) -------------------
        self.grp_cand = QGroupBox(tr("Material candidates (optimisation)"))
        cl = QVBoxLayout(self.grp_cand)
        self.chk_cand = QCheckBox(tr("Let the optimiser choose this layer's material"))
        self.chk_cand.toggled.connect(self._on_cand_toggle)
        cl.addWidget(self.chk_cand)
        self.lst_cand = QListWidget()
        self.lst_cand.setMaximumHeight(150)
        self.lst_cand.itemChanged.connect(self._on_cand_items)
        cl.addWidget(self.lst_cand)
        lay.addWidget(self.grp_cand)

        self.lbl_empty = muted(tr("Select a layer to edit its properties."))
        lay.addWidget(self.lbl_empty)

        # ---- boundaries ----------------------------------------------------
        grp_b = QGroupBox(tr("Boundaries"))
        bf = QFormLayout(grp_b)
        bf.setLabelAlignment(Qt.AlignRight)
        self.cb_incident = QComboBox()
        self.cb_incident.setToolTip(tr("Lossless medium the wave arrives from"))
        self.cb_incident.activated.connect(self._on_incident)
        bf.addRow(tr("Incident medium"), self.cb_incident)
        self.cb_backing = QComboBox()
        self.cb_backing.addItem(tr("Metal plate (PEC)"), "pec")
        self.cb_backing.addItem(tr("Semi-infinite medium"), "halfspace")
        self.cb_backing.activated.connect(self._on_backing)
        bf.addRow(tr("Backing"), self.cb_backing)
        self.cb_back_mat = QComboBox()
        self.cb_back_mat.activated.connect(self._on_backing)
        bf.addRow(tr("Backing medium"), self.cb_back_mat)
        lay.addWidget(grp_b)
        lay.addStretch(1)
        self.set_layer(None)

    def _num_row(self, lo, hi, suffix, attr):
        sp = SciSpinBox(minimum=lo, maximum=hi, suffix=suffix)
        sp.valueEdited.connect(lambda v, a=attr: self._on_value(a, v))
        opt = _OptToggle()
        opt.toggled.connect(lambda on, a=attr: self._on_opt(a, on))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(sp, 1)
        row.addWidget(opt)
        w = QWidget()
        w.setLayout(row)
        return sp, opt, w

    # -- public ------------------------------------------------------------
    def set_layer(self, uid):
        self.uid = uid
        self.refresh()

    def refresh(self):
        p = self.doc.project
        self._loading = True
        try:
            names = list(p.materials)
            ly = None
            if self.uid is not None:
                try:
                    ly = p.structure.layer_by_uid(self.uid)
                except KeyError:
                    self.uid = None
            self.grp_layer.setVisible(ly is not None)
            self.lbl_empty.setVisible(ly is None)
            self.grp_cand.setVisible(isinstance(ly, SlabLayer))
            if ly is not None:
                self.ed_name.setText(ly.name)
                slab = isinstance(ly, SlabLayer)
                rlc = not slab and ly.is_rlc
                for w, vis in ((self.row_material, slab), (self.row_thick, slab), (self.row_model, not slab),
                               (self.row_R, not slab), (self.row_X, not slab and not rlc),
                               (self.row_L, rlc), (self.row_C, rlc)):
                    w.setVisible(vis)
                    self._form.labelForField(w).setVisible(vis)
                if slab:
                    self.cb_material.clear()
                    self.cb_material.addItems(names)
                    if ly.material not in names:
                        self.cb_material.addItem(ly.material)
                    self.cb_material.setCurrentText(ly.material)
                    self.thick.show(lengths.unit_of(p), ly.thickness)
                    self.opt_thick.setChecked(self._has_var("thickness"))
                    mat = p.materials.get(ly.material)
                    if mat is not None:
                        try:
                            rho = mat.get_density(p.resolver)
                            self.lbl_info.setText(tr("Density {rho} g/cm³ · areal mass {m} kg/m²",
                                                     rho=fmt_num(rho / 1000, 4),
                                                     m=fmt_num(rho * ly.thickness, 4)))
                        except Exception:  # noqa: BLE001
                            self.lbl_info.setText("")
                    else:
                        self.lbl_info.setText(tr("Material not found"))
                    choice = self._choice()
                    self.chk_cand.setChecked(choice is not None)
                    self.lst_cand.setEnabled(choice is not None)
                    self.lst_cand.clear()
                    chosen = set(choice.candidates) if choice else {ly.material}
                    for n in names:
                        if n == p.structure.incident:
                            continue
                        it = QListWidgetItem(n)
                        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                        it.setCheckState(Qt.Checked if n in chosen else Qt.Unchecked)
                        self.lst_cand.addItem(it)
                else:
                    self.cb_model.setCurrentIndex(max(0, self.cb_model.findData(ly.model)))
                    self.sp_R.set_value(ly.R)
                    self.sp_X.set_value(ly.X)
                    self.opt_R.setChecked(self._has_var("R"))
                    self.opt_X.setChecked(self._has_var("X"))
                    if rlc:
                        self.sp_L.set_value(ly.L * 1e9)
                        self.opt_L.setChecked(self._has_var("L"))
                        self.opt_L.setEnabled(ly.has_param("L"))
                        has_c = ly.C is not None
                        self.chk_C.setChecked(has_c)
                        self.sp_C.setEnabled(has_c)
                        self.opt_C.setEnabled(has_c)
                        self.sp_C.set_value((ly.C if has_c else 0.05e-12) * 1e12)
                        self.opt_C.setChecked(self._has_var("C"))
                        self.lbl_info.setText(self._rlc_info(ly, p))
                    else:
                        self.lbl_info.setText(tr("Free-space impedance is 376.7 Ω/sq."))
            self.cb_incident.clear()
            self.cb_incident.addItems(names)
            self.cb_incident.setCurrentText(p.structure.incident)
            b = p.structure.backing
            self.cb_backing.setCurrentIndex(0 if b.kind == "pec" else 1)
            self.cb_back_mat.clear()
            self.cb_back_mat.addItems(names)
            if b.material:
                self.cb_back_mat.setCurrentText(b.material)
            self.cb_back_mat.setEnabled(b.kind == "halfspace")
        finally:
            self._loading = False

    # -- helpers -----------------------------------------------------------
    def _path(self, attr):
        return ("layer", self.uid, attr)

    def _has_var(self, attr):
        return any(tuple(v.path) == self._path(attr) for v in self.doc.project.optimization.variables)

    def _choice(self):
        for c in self.doc.project.optimization.choices:
            if c.uid == self.uid:
                return c
        return None

    # -- slots -------------------------------------------------------------
    def _on_name(self):
        if self._loading or self.uid is None:
            return
        name = self.ed_name.text().strip()
        uid = self.uid
        self.doc.edit(tr("Rename layer"), lambda p: setattr(p.structure.layer_by_uid(uid), "name", name))

    def _on_material(self, _idx):
        if self._loading or self.uid is None:
            return
        name = self.cb_material.currentText()
        uid = self.uid
        self.doc.edit(tr("Change layer material"),
                      lambda p: setattr(p.structure.layer_by_uid(uid), "material", name))

    _DISPLAY = {"thickness": 1e-3, "L": 1e-9, "C": 1e-12}  # display unit -> SI

    @staticmethod
    def _rlc_info(ly, p):
        """f0 · Q · Zs at the angle-sweep frequency, plus a hint when f0 lies outside the sweep."""
        parts = []
        f0 = ly.resonance()
        if f0 is not None:
            q = ly.R * math.sqrt(ly.C / ly.L) if ly.model == "parallel_rlc" else math.sqrt(ly.L / ly.C) / ly.R
            parts.append(tr("f₀ = {f} GHz · Q = {q}", f=fmt_num(f0 / 1e9, 4), q=fmt_num(q, 3)))
        elif ly.model == "parallel_rlc" and ly.C is None and ly.L <= 0:
            parts.append(tr("Resistive, no reactive elements"))
        elif ly.C is None:
            parts.append(tr("Inductive grid (no resonance)"))
        else:
            parts.append(tr("Capacitive, no resonance"))
        zs = complex(ly.impedance_at([p.sweep.f_at])[0])
        parts.append(tr("Zs({x}) = {z} Ω/sq", x=spectral.fmt_value(p.sweep.f_at, p.sweep.spectral_unit),
                        z=f"{zs.real:.4g} {'+' if zs.imag >= 0 else '−'} {abs(zs.imag):.4g}j"))
        if f0 is not None and not (p.sweep.f_min <= f0 <= p.sweep.f_max):
            parts.append(tr("f₀ is outside the frequency sweep."))
        return "\n".join(parts)

    def _on_model(self, _index):
        if self._loading or self.uid is None:
            return
        uid, model = self.uid, self.cb_model.currentData()

        def mut(p):
            ly = p.structure.layer_by_uid(uid)
            if ly.model == model:
                return
            was_constant = ly.model == "constant"
            ly.model = model
            if was_constant and model in RLC_MODELS and ly.L == 0 and ly.C is None:
                ly.L, ly.C = 5e-9, 0.05e-12  # f0 ~ 10 GHz; R is kept
            _drop_missing_vars(p, ly)
        self.doc.edit(tr("Change sheet model"), mut)

    def _on_capacitor(self, on):
        if self._loading or self.uid is None:
            return
        uid, c = self.uid, self.sp_C.value() * 1e-12

        def mut(p):
            ly = p.structure.layer_by_uid(uid)
            ly.C = (c if c > 0 else 0.05e-12) if on else None
            _drop_missing_vars(p, ly)
        self.doc.edit(tr("Toggle sheet capacitor"), mut)

    def _on_value(self, attr, v):
        if self._loading or self.uid is None:
            return
        uid = self.uid
        value = self.thick.value() if attr == "thickness" else v * self._DISPLAY.get(attr, 1.0)
        if attr in ("R", "C") and value <= 0:
            return
        label = {"thickness": tr("Change thickness"), "R": tr("Change sheet resistance"),
                 "X": tr("Change sheet reactance"), "L": tr("Change sheet inductance"),
                 "C": tr("Change sheet capacitance")}[attr]

        def mut(p):
            ly = p.structure.layer_by_uid(uid)
            setattr(ly, attr, value)
            if attr == "L":  # a parallel sheet loses its L variable when L goes to 0 (no inductor)
                _drop_missing_vars(p, ly)
        self.doc.edit(label, mut, merge_key=("layer", uid, attr))

    def _on_opt(self, attr, on):
        if self._loading or self.uid is None:
            return
        path = self._path(attr)
        ly = self.doc.project.structure.layer_by_uid(self.uid)
        val = getattr(ly, attr)

        def mut(p):
            vs = p.optimization.variables
            vs[:] = [v for v in vs if tuple(v.path) != path]
            if on:
                if attr == "X":
                    lo, hi = val - 500.0, val + 500.0
                elif attr in ("L", "C"):
                    lo, hi = default_lc_bounds(attr, val)
                else:
                    lo, hi = ((val / 4, val * 4) if val > 0 else
                              (lengths.zero_thickness_range(p) if attr == "thickness" else (10, 3000)))
                vs.append(ContinuousVariable(path, lo, hi))
        self.doc.edit(tr("Toggle optimisation variable"), mut)

    def _on_cand_toggle(self, on):
        if self._loading or self.uid is None:
            return
        uid = self.uid
        ly = self.doc.project.structure.layer_by_uid(uid)

        def mut(p):
            p.optimization.choices = [c for c in p.optimization.choices if c.uid != uid]
            if on:
                p.optimization.choices.append(MaterialChoice(uid, [ly.material]))
        self.doc.edit(tr("Toggle material choice"), mut)
        self.lst_cand.setEnabled(on)

    def _on_cand_items(self, _item):
        if self._loading or self.uid is None or not self.chk_cand.isChecked():
            return
        names = [self.lst_cand.item(i).text() for i in range(self.lst_cand.count())
                 if self.lst_cand.item(i).checkState() == Qt.Checked]
        uid = self.uid

        def mut(p):
            for c in p.optimization.choices:
                if c.uid == uid:
                    c.candidates = names
        self.doc.edit(tr("Change material candidates"), mut)

    def _on_incident(self, _idx):
        if self._loading:
            return
        name = self.cb_incident.currentText()
        self.doc.edit(tr("Change incident medium"), lambda p: setattr(p.structure, "incident", name))

    def _on_backing(self, _idx):
        if self._loading:
            return
        kind = self.cb_backing.currentData()
        mat = self.cb_back_mat.currentText() if kind == "halfspace" else None

        def mut(p):
            p.structure.backing.kind = kind
            p.structure.backing.material = mat
        self.doc.edit(tr("Change backing"), mut)


_ = QLabel
