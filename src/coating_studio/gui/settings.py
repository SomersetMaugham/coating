"""Persistent application preferences (QSettings)."""

from __future__ import annotations

from PySide6.QtCore import QSettings

MAX_RECENT = 10


class AppSettings:
    def __init__(self):
        self.q = QSettings()

    def _get(self, key, default, typ=str):
        v = self.q.value(key, default)
        if typ is bool:
            return v in (True, "true", "1", 1)
        try:
            return typ(v)
        except (TypeError, ValueError):
            return default

    # language: "system" | "en" | "ko"
    @property
    def language(self):
        return self._get("ui/language", "system")

    @language.setter
    def language(self, v):
        self.q.setValue("ui/language", v)

    # theme: "system" | "light" | "dark"
    @property
    def theme(self):
        return self._get("ui/theme", "system")

    @theme.setter
    def theme(self, v):
        self.q.setValue("ui/theme", v)

    @property
    def rl_positive(self):
        """True: show reflection loss as positive dB (-20log10|G|)."""
        return self._get("ui/rl_positive", False, bool)

    @rl_positive.setter
    def rl_positive(self, v):
        self.q.setValue("ui/rl_positive", bool(v))

    @property
    def recent_files(self):
        v = self.q.value("files/recent", [])
        if isinstance(v, str):
            v = [v]
        return [x for x in (v or []) if x]

    def add_recent(self, path):
        items = [p for p in self.recent_files if p != path]
        items.insert(0, path)
        self.q.setValue("files/recent", items[:MAX_RECENT])

    def clear_recent(self):
        self.q.setValue("files/recent", [])

    @property
    def last_dir(self):
        return self._get("files/last_dir", "")

    @last_dir.setter
    def last_dir(self, v):
        self.q.setValue("files/last_dir", v)
