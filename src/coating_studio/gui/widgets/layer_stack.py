"""Layer-stack editor: table + scaled cross-section + editing toolbar."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout, QWidget,
)

from coating_studio.core.structure import SheetLayer, SlabLayer
from coating_studio.gui.fmt import fmt_num
from coating_studio.gui.icons import icon
from coating_studio.gui.widgets.cross_section import CrossSectionWidget
from coating_studio.i18n import tr


class LayerStackWidget(QWidget):
    selectionChangedUid = Signal(object)  # uid or None

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.colors = None
        self._updating = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        self.toolbar = QToolBar()
        self.toolbar.setIconSize(QSize(18, 18))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.act_add_slab = self._act("layer-add", tr("Add slab layer"), self.add_slab, "Ctrl+L")
        self.act_add_sheet = self._act("sheet-add", tr("Add resistive sheet"), self.add_sheet, "Ctrl+Shift+L")
        self.toolbar.addSeparator()
        self.act_dup = self._act("duplicate", tr("Duplicate layer"), self.duplicate, "Ctrl+D")
        self.act_del = self._act("delete", tr("Delete layer"), self.delete, QKeySequence.Delete)
        self.toolbar.addSeparator()
        self.act_up = self._act("up", tr("Move towards front (incident side)"), lambda: self.move(-1), "Alt+Up")
        self.act_down = self._act("down", tr("Move towards back"), lambda: self.move(1), "Alt+Down")
        lay.addWidget(self.toolbar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", tr("Layer"), tr("Material / sheet"), tr("Thickness / R")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.setToolTip(tr("Front (incident side) at the top, backing at the bottom."))
        lay.addWidget(self.table, 1)

        self.section = CrossSectionWidget()
        self.section.layerClicked.connect(self.select_uid)
        lay.addWidget(self.section)
        self._update_actions()

    def _act(self, icon_name, text, slot, shortcut=None):
        a = QAction(icon(icon_name), text, self)
        a.setToolTip(text + (f" ({QKeySequence(shortcut).toString(QKeySequence.NativeText)})" if shortcut else ""))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        a.triggered.connect(slot)
        self.toolbar.addAction(a)
        self.addAction(a)
        return a

    # -- selection ---------------------------------------------------------
    def selected_uid(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.data(Qt.UserRole) if item else None

    def select_uid(self, uid):
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == uid:
                self.table.selectRow(r)
                return
        self.table.clearSelection()

    def _on_selection(self):
        if self._updating:
            return
        self._update_actions()
        uid = self.selected_uid()
        self.section.set_state(self.doc.project, self.colors, uid)
        self.selectionChangedUid.emit(uid)

    def _update_actions(self):
        uid = self.selected_uid()
        n = len(self.doc.project.structure.layers)
        idx = self.doc.project.structure.index_of(uid) if uid else -1
        for a in (self.act_dup, self.act_del):
            a.setEnabled(uid is not None)
        self.act_up.setEnabled(idx > 0)
        self.act_down.setEnabled(0 <= idx < n - 1)

    # -- refresh -----------------------------------------------------------
    def refresh(self, colors=None):
        if colors is not None:
            self.colors = colors
        keep = self.selected_uid()
        self._updating = True
        try:
            layers = self.doc.project.structure.layers
            self.table.setRowCount(len(layers))
            for r, ly in enumerate(layers):
                if isinstance(ly, SlabLayer):
                    kind = ly.name or tr("Slab")
                    what = ly.material
                    val = f"{fmt_num(ly.thickness * 1e3, 4)} mm"
                    missing = ly.material not in self.doc.project.materials
                else:
                    kind = ly.name or tr("Resistive sheet")
                    what = tr("Resistive sheet")
                    val = f"{fmt_num(ly.R, 4)}" + (f" {ly.X:+.4g}j" if ly.X else "") + " Ω/sq"
                    missing = False
                cells = [str(r + 1), kind, what, val]
                for c, text in enumerate(cells):
                    it = QTableWidgetItem(text)
                    if c == 0:
                        it.setData(Qt.UserRole, ly.uid)
                        it.setTextAlignment(Qt.AlignCenter)
                        it.setIcon(icon("sheet" if isinstance(ly, SheetLayer) else "slab"))
                    if c == 3:
                        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if missing and c == 2 and self.colors:
                        it.setForeground(QColor(self.colors.error))
                    self.table.setItem(r, c, it)
        finally:
            self._updating = False
        if keep and any(ly.uid == keep for ly in self.doc.project.structure.layers):
            self.select_uid(keep)
        self.section.set_state(self.doc.project, self.colors, self.selected_uid())
        self._update_actions()

    # -- editing -----------------------------------------------------------
    def _insert_index(self):
        uid = self.selected_uid()
        if uid is None:
            return 0
        return self.doc.project.structure.index_of(uid)

    def add_slab(self):
        p = self.doc.project
        mats = [m for m in p.materials if m != p.structure.incident]
        name = "PMI foam" if "PMI foam" in mats else (mats[0] if mats else p.structure.incident)
        ly = SlabLayer(name, 2e-3, name=tr("Layer"))
        idx = self._insert_index()
        self.doc.edit(tr("Add slab layer"), lambda pr: pr.structure.layers.insert(idx, ly))
        self.refresh()
        self.select_uid(ly.uid)

    def add_sheet(self):
        ly = SheetLayer(377.0, 0.0, name=tr("Resistive sheet"))
        idx = self._insert_index()
        self.doc.edit(tr("Add resistive sheet"), lambda pr: pr.structure.layers.insert(idx, ly))
        self.refresh()
        self.select_uid(ly.uid)

    def duplicate(self):
        uid = self.selected_uid()
        if uid is None:
            return
        src = self.doc.project.structure.layer_by_uid(uid)
        if isinstance(src, SlabLayer):
            ly = SlabLayer(src.material, src.thickness, name=src.name)
        else:
            ly = SheetLayer(src.R, src.X, name=src.name)
        idx = self.doc.project.structure.index_of(uid) + 1
        self.doc.edit(tr("Duplicate layer"), lambda pr: pr.structure.layers.insert(idx, ly))
        self.refresh()
        self.select_uid(ly.uid)

    def delete(self):
        uid = self.selected_uid()
        if uid is None:
            return
        idx = self.doc.project.structure.index_of(uid)
        self.doc.edit(tr("Delete layer"), lambda pr: pr.remove_layer(uid))
        self.refresh()
        layers = self.doc.project.structure.layers
        if layers:
            self.select_uid(layers[min(idx, len(layers) - 1)].uid)

    def move(self, delta):
        uid = self.selected_uid()
        if uid is None:
            return
        idx = self.doc.project.structure.index_of(uid)
        new = idx + delta
        if not 0 <= new < len(self.doc.project.structure.layers):
            return

        def mut(pr):
            ls = pr.structure.layers
            ls.insert(new, ls.pop(idx))
        self.doc.edit(tr("Reorder layers"), mut)
        self.refresh()
        self.select_uid(uid)


_ = QIcon
