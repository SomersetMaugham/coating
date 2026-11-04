"""Scaled cross-section drawing of the layer stack."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from coating_studio.core.structure import SheetLayer, SlabLayer
from coating_studio.i18n import tr


class CrossSectionWidget(QWidget):
    layerClicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project = None
        self.colors = None
        self.selected_uid = None
        self._hit = []
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMouseTracking(True)

    def set_state(self, project, colors, selected_uid=None):
        self.project, self.colors, self.selected_uid = project, colors, selected_uid
        self.update()

    def mousePressEvent(self, e):
        for rect, uid in self._hit:
            if rect.contains(e.position()):
                self.layerClicked.emit(uid)
                return

    def _material_color(self, name, idx):
        palette = self.colors.series
        h = sum(ord(ch) for ch in name)
        c = QColor(palette[h % len(palette)])
        c.setAlpha(150)
        return c

    def paintEvent(self, _):
        if not self.project or not self.colors:
            return
        c = self.colors
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(c.base))
        layers = self.project.structure.layers
        margin_l, margin_r, top, bottom = 34, 14, 16, 24
        w = self.width() - margin_l - margin_r
        h = self.height() - top - bottom
        slabs = [ly for ly in layers if isinstance(ly, SlabLayer)]
        total = sum(ly.thickness for ly in slabs)
        backing_w = 18
        avail = max(w - backing_w - 6 * sum(isinstance(ly, SheetLayer) for ly in layers), 10)
        # thin layers get a minimum visual width so they remain clickable
        min_w = 8
        widths = []
        for ly in layers:
            if isinstance(ly, SlabLayer):
                widths.append(max(avail * (ly.thickness / total) if total else min_w, min_w))
            else:
                widths.append(6)
        scale = min(1.0, (w - backing_w) / max(sum(widths), 1))
        x = margin_l
        self._hit = []
        font = QFont(self.font())
        font.setPointSizeF(max(font.pointSizeF() - 1, 7))
        p.setFont(font)
        # incident wave arrow
        p.setPen(QPen(QColor(c.accent), 2))
        mid = top + h / 2
        p.drawLine(QPointF(6, mid), QPointF(margin_l - 6, mid))
        path = QPainterPath(QPointF(margin_l - 6, mid))
        path.lineTo(margin_l - 12, mid - 4)
        path.lineTo(margin_l - 12, mid + 4)
        path.closeSubpath()
        p.fillPath(path, QColor(c.accent))
        for idx, (ly, lw) in enumerate(zip(layers, widths)):
            lw *= scale
            rect = QRectF(x, top, lw, h)
            if isinstance(ly, SlabLayer):
                p.fillRect(rect, self._material_color(ly.material, idx))
                p.setPen(QPen(QColor(c.border), 1))
                p.drawRect(rect)
            else:
                p.fillRect(QRectF(x + lw / 2 - 1.5, top, 3, h), QColor(c.sheet))
            if ly.uid == self.selected_uid:
                p.setPen(QPen(QColor(c.accent), 2.5))
                p.setBrush(Qt.NoBrush)
                p.drawRect(rect.adjusted(1, 1, -1, -1))
            self._hit.append((rect, ly.uid))
            if lw > 22:
                p.setPen(QColor(c.text))
                p.drawText(rect.adjusted(2, 2, -2, -2), Qt.AlignHCenter | Qt.AlignTop, str(idx + 1))
            x += lw
        # backing
        brect = QRectF(x, top, backing_w, h)
        if self.project.structure.backing.kind == "pec":
            p.fillRect(brect, QColor(c.pec))
            p.save()
            p.setClipRect(brect)
            p.setPen(QPen(QColor(c.base), 1))
            step = 6
            for k in range(-int(h), int(backing_w) + int(h), step):
                p.drawLine(QPointF(x + k, top + h), QPointF(x + k + h, top))
            p.restore()
            label = tr("PEC")
        else:
            col = self._material_color(self.project.structure.backing.material or "", 0)
            col.setAlpha(60)
            p.fillRect(QRectF(x, top, self.width() - x - 2, h), col)
            label = tr("half-space")
        p.setPen(QColor(c.muted))
        p.drawText(QRectF(x - 40, top + h + 2, 120, bottom - 2), Qt.AlignLeft | Qt.AlignVCenter, label)
        p.drawText(QRectF(4, top + h + 2, 120, bottom - 2), Qt.AlignLeft | Qt.AlignVCenter,
                   tr("Total {t} mm", t=f"{total * 1e3:.4g}"))
        p.end()

    def sizeHint(self):
        from PySide6.QtCore import QSize

        return QSize(320, 170)


_ = math
