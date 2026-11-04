"""Input widgets: a spin box that accepts scientific notation, and small helpers."""

from __future__ import annotations

import math
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QDoubleSpinBox, QFrame, QLabel, QSizePolicy

from coating_studio.gui.fmt import fmt_num

_FLOAT = re.compile(r"^\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?\s*$")
_PARTIAL = re.compile(r"^\s*[-+]?(\d*\.?\d*)([eE][-+]?\d*)?\s*$")


class SciSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox with general-format display and exponent input.

    ``valueEdited`` fires only on user interaction (not on programmatic setValue).
    Stepping is multiplicative-friendly: one step is ~1% of the magnitude.
    """

    valueEdited = Signal(float)

    def __init__(self, parent=None, minimum=-1e300, maximum=1e300, digits=6, suffix=""):
        super().__init__(parent)
        self._digits = digits
        self.setDecimals(15)
        self.setRange(minimum, maximum)
        self.setKeyboardTracking(False)
        self.setAccelerated(True)
        if suffix:
            self.setSuffix(f" {suffix}")
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._programmatic = False
        self.valueChanged.connect(self._on_changed)

    def _on_changed(self, v):
        if not self._programmatic:
            self.valueEdited.emit(v)

    def set_value(self, v):
        self._programmatic = True
        try:
            self.setValue(v)
        finally:
            self._programmatic = False

    def textFromValue(self, v):
        return fmt_num(v, self._digits)

    def valueFromText(self, text):
        t = text.replace(self.suffix(), "").replace(",", ".").strip()
        try:
            return float(t)
        except ValueError:
            return self.value()

    def validate(self, text, pos):
        t = text.replace(self.suffix(), "").replace(",", ".")
        if _FLOAT.match(t):
            v = float(t)
            if self.minimum() <= v <= self.maximum():
                return QValidator.Acceptable, text, pos
            return QValidator.Intermediate, text, pos
        if _PARTIAL.match(t) or t.strip() == "":
            return QValidator.Intermediate, text, pos
        return QValidator.Invalid, text, pos

    def stepBy(self, steps):
        v = self.value()
        step = 10 ** math.floor(math.log10(abs(v))) / 10 if v else 0.1
        self.setValue(v + steps * step)


def hline():
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFrameShadow(QFrame.Sunken)
    return f


def muted(text=""):
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(True)
    return lab
