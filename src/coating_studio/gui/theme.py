"""Light / dark themes for Qt widgets and matching Matplotlib styles."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory


@dataclass(frozen=True)
class Colors:
    name: str
    window: str
    base: str
    alt_base: str
    text: str
    muted: str
    border: str
    accent: str
    accent_text: str
    grid: str
    series: tuple  # plot colour cycle
    ref_series: tuple  # pinned reference traces, one per slot
    warn: str
    error: str
    ok: str
    pec: str
    sheet: str


LIGHT = Colors(
    name="light", window="#f4f5f7", base="#ffffff", alt_base="#f7f8fa", text="#1d2330",
    muted="#5f6b7a", border="#d5d9e0", accent="#2563eb", accent_text="#ffffff", grid="#e3e6eb",
    series=("#2563eb", "#e4572e", "#17a398", "#9c6ade", "#f2a541", "#6b7280"),
    ref_series=("#7c3aed", "#db2777", "#65a30d", "#0891b2", "#a16207", "#475569"),
    warn="#b45309", error="#c0262d", ok="#15803d", pec="#8a94a6", sheet="#d97706")

DARK = Colors(
    name="dark", window="#1e2128", base="#16181d", alt_base="#1b1e24", text="#e6e9ef",
    muted="#9aa4b2", border="#343944", accent="#4f8cff", accent_text="#ffffff", grid="#2b2f38",
    series=("#5b9bff", "#ff7a59", "#2dd4bf", "#c4a1ff", "#fbbf24", "#9ca3af"),
    ref_series=("#c4b5fd", "#f472b6", "#a3e635", "#22d3ee", "#fcd34d", "#cbd5e1"),
    warn="#fbbf24", error="#f87171", ok="#4ade80", pec="#6b7385", sheet="#f59e0b")


def system_prefers_dark() -> bool:
    hints = QGuiApplication.styleHints()
    try:
        return hints.colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return QGuiApplication.palette().color(QPalette.Window).lightness() < 128


def resolve(mode: str) -> Colors:
    if mode == "dark":
        return DARK
    if mode == "light":
        return LIGHT
    return DARK if system_prefers_dark() else LIGHT


def _check_image(color: str) -> str:
    """Write a small check-mark SVG for checkbox indicators; return a stylesheet-safe path."""
    import pathlib
    import tempfile

    path = pathlib.Path(tempfile.gettempdir()) / f"coating_studio_check_{color.strip('#')}.svg"
    if not path.exists():
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 14 14">'
                        f'<path d="M3 7.2l2.6 2.6L11 4.4" fill="none" stroke="{color}" stroke-width="2" '
                        'stroke-linecap="round" stroke-linejoin="round"/></svg>', encoding="utf-8")
    return path.as_posix()


def apply_qt_theme(app: QApplication, c: Colors):
    app.setStyle(QStyleFactory.create("Fusion"))
    try:
        check = _check_image(c.accent_text)
    except OSError:
        check = ""
    pal = QPalette()
    col = QColor
    pal.setColor(QPalette.Window, col(c.window))
    pal.setColor(QPalette.WindowText, col(c.text))
    pal.setColor(QPalette.Base, col(c.base))
    pal.setColor(QPalette.AlternateBase, col(c.alt_base))
    pal.setColor(QPalette.ToolTipBase, col(c.base))
    pal.setColor(QPalette.ToolTipText, col(c.text))
    pal.setColor(QPalette.PlaceholderText, col(c.muted))
    pal.setColor(QPalette.Text, col(c.text))
    pal.setColor(QPalette.Button, col(c.window))
    pal.setColor(QPalette.ButtonText, col(c.text))
    pal.setColor(QPalette.BrightText, col("#ffffff"))
    pal.setColor(QPalette.Highlight, col(c.accent))
    pal.setColor(QPalette.HighlightedText, col(c.accent_text))
    pal.setColor(QPalette.Link, col(c.accent))
    pal.setColor(QPalette.Mid, col(c.border))
    pal.setColor(QPalette.Midlight, col(c.border))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, col(c.muted))
    app.setPalette(pal)
    app.setStyleSheet(f"""
        QToolTip {{ color: {c.text}; background: {c.base}; border: 1px solid {c.border}; padding: 4px; }}
        QDockWidget::title {{ padding: 6px 8px; background: {c.window}; font-weight: 600; }}
        QGroupBox {{ border: 1px solid {c.border}; border-radius: 6px; margin-top: 14px; padding-top: 6px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {c.muted};
                            font-weight: 600; }}
        QTabWidget::pane {{ border: 1px solid {c.border}; border-radius: 4px; top: -1px; }}
        QTabBar::tab {{ padding: 6px 14px; border: 1px solid transparent; border-bottom: none;
                        color: {c.muted}; }}
        QTabBar::tab:selected {{ color: {c.text}; background: {c.base}; border-color: {c.border};
                                 border-top-left-radius: 4px; border-top-right-radius: 4px; }}
        QTableView, QTreeView, QListView {{ gridline-color: {c.grid}; selection-background-color: {c.accent};
                                            border: 1px solid {c.border}; }}
        QHeaderView::section {{ background: {c.window}; color: {c.muted}; padding: 4px 6px; border: none;
                                border-bottom: 1px solid {c.border}; font-weight: 600; }}
        QPushButton#primary {{ background: {c.accent}; color: {c.accent_text}; border-radius: 4px;
                               padding: 6px 14px; font-weight: 600; border: none; }}
        QPushButton#primary:disabled {{ background: {c.border}; color: {c.muted}; }}
        QLabel#muted {{ color: {c.muted}; }}
        QLabel#banner {{ padding: 6px 10px; border-radius: 4px; }}
        QStatusBar {{ color: {c.muted}; }}
        QCheckBox::indicator, QAbstractItemView::indicator {{ width: 14px; height: 14px; border-radius: 3px;
                                                              border: 1px solid {c.muted}; background: {c.base}; }}
        QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {{
            background: {c.accent}; border-color: {c.accent}; image: url("{check}"); }}
        QCheckBox::indicator:disabled, QAbstractItemView::indicator:disabled {{ border-color: {c.border}; }}
        QCheckBox::indicator:checked:disabled {{ background: {c.border}; }}
    """)


def mpl_rc(c: Colors) -> dict:
    return {
        "figure.facecolor": c.base,
        "axes.facecolor": c.base,
        "axes.edgecolor": c.border,
        "axes.labelcolor": c.text,
        "axes.titlecolor": c.text,
        "axes.grid": True,
        "grid.color": c.grid,
        "grid.linewidth": 0.8,
        "xtick.color": c.muted,
        "ytick.color": c.muted,
        "xtick.labelcolor": c.text,
        "ytick.labelcolor": c.text,
        "text.color": c.text,
        "legend.facecolor": c.base,
        "legend.edgecolor": c.border,
        "legend.labelcolor": c.text,
        "legend.framealpha": 0.9,
        "axes.prop_cycle": __import__("cycler").cycler(color=list(c.series)),
        "lines.linewidth": 1.8,
        "savefig.facecolor": c.base,
    }
