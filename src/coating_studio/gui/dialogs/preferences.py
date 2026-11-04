"""Preferences: language, theme, reflection-loss sign convention."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QVBoxLayout

from coating_studio.gui.widgets.inputs import muted
from coating_studio.i18n import tr


class PreferencesDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("Preferences"))
        self.setMinimumWidth(460)
        form = QFormLayout()
        self.cb_lang = QComboBox()
        for key, label in (("system", tr("System default")), ("en", "English"), ("ko", "한국어")):
            self.cb_lang.addItem(label, key)
        self.cb_lang.setCurrentIndex(max(self.cb_lang.findData(settings.language), 0))
        self.cb_theme = QComboBox()
        for key, label in (("system", tr("System default")), ("light", tr("Light")), ("dark", tr("Dark"))):
            self.cb_theme.addItem(label, key)
        self.cb_theme.setCurrentIndex(max(self.cb_theme.findData(settings.theme), 0))
        self.cb_rl = QComboBox()
        self.cb_rl.addItem(tr("Negative dB: 20·log₁₀|Γ| (lower is better)"), False)
        self.cb_rl.addItem(tr("Positive dB: −20·log₁₀|Γ| (higher is better)"), True)
        self.cb_rl.setCurrentIndex(1 if settings.rl_positive else 0)
        form.addRow(tr("Language"), self.cb_lang)
        form.addRow("", muted(tr("A language change takes effect after restarting the application.")))
        form.addRow(tr("Theme"), self.cb_theme)
        form.addRow(tr("Reflection loss sign"), self.cb_rl)
        form.addRow("", muted(tr("Internally and in project files RL is always 20·log₁₀|Γ|; this only "
                                 "changes how values are displayed.")))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(bb)

    def values(self):
        return self.cb_lang.currentData(), self.cb_theme.currentData(), self.cb_rl.currentData()
