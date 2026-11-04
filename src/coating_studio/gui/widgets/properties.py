"""Property editor for the selected layer and for the stack boundaries."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from coating_studio.core.structure import SlabLayer
from coating_studio.gui.fmt import fmt_num
from coating_studio.gui.widgets.inputs import SciSpinBox, muted
from coating_studio.i18n import tr
from coating_studio.project import ContinuousVariable, MaterialChoice


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
        form.addRow(tr("Thickness"), self.row_thick)
        self.sp_R, self.opt_R, self.row_R = self._num_row(1e-6, 1e9, "Ω/sq", "R")
        form.addRow(tr("Resistance R"), self.row_R)
        self.sp_X, self.opt_X, self.row_X = self._num_row(-1e9, 1e9, "Ω/sq", "X")
        form.addRow(tr("Reactance X"), self.row_X)
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
                for w, vis in ((self.row_material, slab), (self.row_thick, slab),
                               (self.row_R, not slab), (self.row_X, not slab)):
                    w.setVisible(vis)
                    self._form.labelForField(w).setVisible(vis)
                if slab:
                    self.cb_material.clear()
                    self.cb_material.addItems(names)
                    if ly.material not in names:
                        self.cb_material.addItem(ly.material)
                    self.cb_material.setCurrentText(ly.material)
                    self.sp_thick.set_value(ly.thickness * 1e3)
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
                    self.sp_R.set_value(ly.R)
                    self.sp_X.set_value(ly.X)
                    self.opt_R.setChecked(self._has_var("R"))
                    self.opt_X.setChecked(self._has_var("X"))
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

    def _on_value(self, attr, v):
        if self._loading or self.uid is None:
            return
        uid = self.uid
        value = v * 1e-3 if attr == "thickness" else v
        if attr == "R" and value <= 0:
            return
        label = {"thickness": tr("Change thickness"), "R": tr("Change sheet resistance"),
                 "X": tr("Change sheet reactance")}[attr]
        self.doc.edit(label, lambda p: setattr(p.structure.layer_by_uid(uid), attr, value),
                      merge_key=("layer", uid, attr))

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
                else:
                    lo, hi = (val / 4, val * 4) if val > 0 else ((1e-4, 1e-2) if attr == "thickness" else (10, 3000))
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
