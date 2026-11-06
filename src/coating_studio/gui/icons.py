"""Theme-aware line icons drawn from small inline SVGs (no external assets)."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_STROKE = 'fill="none" stroke="{c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'

_ICONS = {
    "new": '<path d="M6 3h8l4 4v14H6z" {s}/><path d="M14 3v4h4" {s}/><path d="M12 11v6M9 14h6" {s}/>',
    "open": '<path d="M3 7h6l2 2h10v10H3z" {s}/>',
    "save": '<path d="M5 3h12l3 3v15H5z" {s}/><path d="M8 3v5h8V3M8 21v-7h8v7" {s}/>',
    "undo": '<path d="M9 14 4 9l5-5" {s}/><path d="M4 9h11a5 5 0 0 1 0 10h-3" {s}/>',
    "redo": '<path d="M15 14l5-5-5-5" {s}/><path d="M20 9H9a5 5 0 0 0 0 10h3" {s}/>',
    "layer-add": '<rect x="3" y="5" width="12" height="14" rx="1" {s}/><path d="M19 9v6M16 12h6" {s}/>',
    "sheet-add": '<path d="M8 4v16" {s} stroke-dasharray="2 2"/><path d="M17 9v6M14 12h6" {s}/>',
    "duplicate": '<rect x="8" y="8" width="12" height="12" rx="1" {s}/><path d="M4 16V4h12" {s}/>',
    "delete": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" {s}/>',
    "up": '<path d="M12 19V5M6 11l6-6 6 6" {s}/>',
    "down": '<path d="M12 5v14M6 13l6 6 6-6" {s}/>',
    "slab": '<rect x="6" y="3" width="12" height="18" rx="1" fill="{c}" fill-opacity="0.25" stroke="{c}" stroke-width="1.5"/>',
    "sheet": '<path d="M12 3v18" stroke="{a}" stroke-width="3" stroke-linecap="round"/>',
    "run": '<path d="M7 4l13 8-13 8z" fill="{c}" stroke="none"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1.5" fill="{c}" stroke="none"/>',
    "export": '<path d="M12 3v12M7 8l5-5 5 5" {s}/><path d="M4 15v5h16v-5" {s}/>',
    "materials": '<circle cx="8" cy="9" r="4" {s}/><circle cx="16" cy="9" r="4" {s}/><circle cx="12" cy="16" r="4" {s}/>',
    "settings": '<circle cx="12" cy="12" r="3" {s}/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1" {s}/>',
    "apply": '<path d="M5 12l5 5 9-10" {s}/>',
    "optimize": '<path d="M3 20h18" {s}/><path d="M4 16c3-9 6-9 8-4s5 5 8-6" {s}/>',
    "tolerance": '<path d="M3 12c3 0 3-7 9-7s6 7 9 7" {s}/><path d="M3 15c3 0 3-4 9-4s6 4 9 4" {s} stroke-opacity="0.5"/>',
    "warning": '<path d="M12 3 2 20h20z" {s}/><path d="M12 10v4M12 17v.5" {s}/>',
    "error": '<circle cx="12" cy="12" r="9" {s}/><path d="M9 9l6 6M15 9l-6 6" {s}/>',
    "info": '<circle cx="12" cy="12" r="9" {s}/><path d="M12 11v6M12 7.5v.5" {s}/>',
    "add": '<path d="M12 5v14M5 12h14" {s}/>',
    "pin": '<path d="M9 3h6l-1 6 3 3H7l3-3z" {s}/><path d="M12 12v9" {s}/>',
    "refs": '<path d="M3 17c4-8 7-8 9-3s5 4 9-7" {s}/><path d="M3 20c4-6 7-6 9-2s5 3 9-5" {s} stroke-dasharray="3 2"/>',
    "import": '<path d="M12 15V3M7 10l5 5 5-5" {s}/><path d="M4 15v5h16v-5" {s}/>',
    "fit": '<path d="M3 19c4-12 8-12 18-14" {s}/><circle cx="6" cy="14" r="1" fill="{c}"/><circle cx="10" cy="9" r="1" fill="{c}"/><circle cx="15" cy="7" r="1" fill="{c}"/><circle cx="19" cy="5.5" r="1" fill="{c}"/>',
}

_color = "#1d2330"
_accent = "#d97706"
_cache = {}


def set_icon_colors(text_color: str, accent: str):
    global _color, _accent
    _color, _accent = text_color, accent
    _cache.clear()


def _svg(name, color):
    body = _ICONS[name].replace("{s}", _STROKE).replace("{c}", color).replace("{a}", _accent)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'.replace("{c}", color)


def _pixmap(name, color, size):
    r = QSvgRenderer(QByteArray(_svg(name, color).encode()))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


def icon(name: str, color: str | None = None) -> QIcon:
    col = color or _color
    key = (name, col)
    if key in _cache:
        return _cache[key]
    ic = QIcon()
    for size in (16, 24, 32, 48):
        ic.addPixmap(_pixmap(name, col, size), QIcon.Normal)
        ic.addPixmap(_pixmap(name, "#9aa0aa", size), QIcon.Disabled)
    _cache[key] = ic
    return ic


def set_button_icon(button, name: str, on_accent: bool = False):
    """Give a button a theme-aware icon that ``refresh_icons`` can redraw after a theme change."""
    button.setProperty("csIcon", name)
    button.setProperty("csIconOnAccent", on_accent)
    button.setIcon(icon(name, "#ffffff" if on_accent else None))


def refresh_icons(root):
    from PySide6.QtWidgets import QAbstractButton

    for b in root.findChildren(QAbstractButton):
        name = b.property("csIcon")
        if name:
            b.setIcon(icon(name, "#ffffff" if b.property("csIconOnAccent") else None))


APP_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#2563eb"/><stop offset="1" stop-color="#17a398"/></linearGradient></defs>
<rect x="2" y="2" width="60" height="60" rx="13" fill="url(#g)"/>
<rect x="40" y="12" width="10" height="40" rx="1.5" fill="#e5e7eb"/>
<rect x="31" y="12" width="7" height="40" fill="#ffffff" fill-opacity="0.55"/>
<rect x="24" y="12" width="5" height="40" fill="#ffffff" fill-opacity="0.35"/>
<path d="M6 32c3-7 6-7 9 0s6 7 9 0" fill="none" stroke="#ffffff" stroke-width="3" stroke-linecap="round"/>
</svg>"""


def app_icon() -> QIcon:
    ic = QIcon()
    r = QSvgRenderer(QByteArray(APP_ICON_SVG.encode()))
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        r.render(p, QRectF(0, 0, size, size))
        p.end()
        ic.addPixmap(pm)
    return ic
