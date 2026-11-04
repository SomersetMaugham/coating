"""Matplotlib font set-up so Korean text renders on Windows, macOS and Linux."""

from __future__ import annotations

import sys

import matplotlib
from matplotlib import font_manager

_CANDIDATES = {
    "win32": ["Malgun Gothic", "맑은 고딕", "Gulim", "Segoe UI"],
    "darwin": ["Apple SD Gothic Neo", "AppleGothic", "Helvetica Neue"],
    "linux": ["Noto Sans CJK KR", "Noto Sans KR", "NanumGothic", "NanumBarunGothic",
              "UnDotum", "Source Han Sans KR", "DejaVu Sans"],
}


def configure_matplotlib_fonts() -> str | None:
    """Prepend the first available Korean-capable font; return its name (or None)."""
    plat = "win32" if sys.platform.startswith("win") else "darwin" if sys.platform == "darwin" else "linux"
    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = next((name for name in _CANDIDATES[plat] if name in available), None)
    fams = list(matplotlib.rcParams.get("font.sans-serif", []))
    if chosen:
        fams = [chosen] + [f for f in fams if f != chosen]
    if "DejaVu Sans" not in fams:
        fams.append("DejaVu Sans")
    matplotlib.rcParams["font.sans-serif"] = fams
    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["axes.unicode_minus"] = False
    return chosen
