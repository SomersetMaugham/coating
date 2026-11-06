"""Common plot container: themed Matplotlib canvas, toolbar, banner, cursor readout, export."""

from __future__ import annotations

import csv

import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from coating_studio.gui.theme import mpl_rc
from coating_studio.i18n import tr


class _Toolbar(NavigationToolbar2QT):
    # keep navigation tools; the app provides its own export actions
    toolitems = [t for t in NavigationToolbar2QT.toolitems if t[0] in ("Home", "Back", "Forward", "Pan", "Zoom")]

    def set_message(self, s):  # coordinates go to the status bar instead
        pass


class PlotView(QWidget):
    """Base class.  Subclasses implement ``draw_plot(fig)`` and ``data_table()``."""

    cursorText = Signal(str)
    title = "Plot"

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx  # MainWindow-provided context: results, colors, settings, project
        self.fig = Figure(figsize=(6, 4), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setFocusPolicy(Qt.ClickFocus)
        self.toolbar = _Toolbar(self.canvas, self)
        self.toolbar.setIconSize(self.toolbar.iconSize() * 0.8)
        self.controls = QHBoxLayout()
        self.controls.setContentsMargins(0, 0, 0, 0)
        self.controls.setSpacing(10)
        top = QHBoxLayout()
        top.setContentsMargins(6, 4, 6, 0)
        top.addLayout(self.controls, 1)
        top.addWidget(self.toolbar)
        self.banner = QLabel()
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addLayout(top)
        lay.addWidget(self.banner)
        lay.addWidget(self.canvas, 1)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self._dirty = True

    # -- drawing -------------------------------------------------------------
    def mark_dirty(self):
        self._dirty = True
        if self.isVisible():
            self.redraw()

    def showEvent(self, e):
        super().showEvent(e)
        if self._dirty:
            self.redraw()

    def redraw(self):
        self._dirty = False
        c = self.ctx.colors
        with matplotlib.rc_context(mpl_rc(c)):
            self.fig.clear()
            self.fig.set_facecolor(c.base)
            level = "error"
            try:
                msg = self.draw_plot(self.fig)
                if isinstance(msg, tuple):  # (message, "warn"): the plot is drawn, something is off
                    msg, level = msg
            except Exception as e:  # noqa: BLE001 - never let a plot crash the UI
                self.fig.clear()
                msg = tr("Cannot draw this plot: {err}", err=str(e))
            self.set_banner(msg, level)
        self.canvas.draw_idle()

    def set_banner(self, msg, level="error"):
        if not msg:
            self.banner.hide()
            return
        c = self.ctx.colors
        col = c.error if level == "error" else c.warn
        self.banner.setStyleSheet(f"color: {col}; border: 1px solid {col};")
        self.banner.setText(msg)
        self.banner.show()

    def draw_plot(self, fig):
        raise NotImplementedError

    def data_table(self):
        """Return (header list, rows list) for CSV export, or None."""
        return None

    def format_cursor(self, ax, x, y):
        return f"x = {x:.6g}, y = {y:.6g}"

    def _on_motion(self, ev):
        if ev.inaxes is None or ev.xdata is None:
            self.cursorText.emit("")
            return
        self.cursorText.emit(self.format_cursor(ev.inaxes, ev.xdata, ev.ydata))

    # -- export --------------------------------------------------------------
    def export_figure(self, parent=None):
        path, _ = QFileDialog.getSaveFileName(
            parent or self, tr("Export figure"), f"{self.title}.png",
            "PNG (*.png);;SVG (*.svg);;PDF (*.pdf)")
        if not path:
            return
        try:
            self.fig.savefig(path, dpi=200)
        except OSError as e:
            QMessageBox.critical(self, tr("Export failed"), str(e))

    def export_data(self, parent=None):
        table = self.data_table()
        if not table:
            QMessageBox.information(self, tr("Export data"), tr("This view has no data to export."))
            return
        path, _ = QFileDialog.getSaveFileName(parent or self, tr("Export data"), f"{self.title}.csv",
                                              "CSV (*.csv)")
        if not path:
            return
        header, rows = table
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(header)
                w.writerows(rows)
        except OSError as e:
            QMessageBox.critical(self, tr("Export failed"), str(e))
