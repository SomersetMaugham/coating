"""Conversions between SI parameter values and display units used by the UI."""

from __future__ import annotations

from coating_studio.core.units import from_display, to_display  # noqa: F401 (re-exported)
from coating_studio.i18n import tr

_LABEL = {"mm": "mm", "GHz": "GHz", "ohm": "Ω/sq", "S/m": "S/m", "frac": "", "": "", "g/cm3": "g/cm³",
          "nH": "nH", "pF": "pF"}


def rl_display(db, positive):
    """RL in the user's display convention (internal RL is always 20·log10|Γ|, negative = good).

    The map is its own inverse, so it also converts a displayed value back to internal dB."""
    return -db if positive else db


def unit_label(unit):
    return _LABEL.get(unit, unit)


def fmt_num(x, digits=5):
    if x == 0:
        return "0"
    a = abs(x)
    if 1e-3 <= a < 1e5:
        s = f"{x:.{digits}g}"
    else:
        s = f"{x:.{max(digits - 2, 2)}e}"
    return s


def param_label(label: str) -> str:
    """Translate an engine parameter label such as 'L2 Spacer: thickness'."""
    if ": " in label:
        head, tail = label.split(": ", 1)
        return f"{head}: {translate_param_name(tail)}"
    return translate_param_name(label)


def translate_param_name(name: str) -> str:
    # dispersion term labels look like "mu debye #1 delta"
    parts = name.split(" ")
    if len(parts) == 4 and parts[1] in ("debye", "lorentz") and parts[2].startswith("#"):
        sym = "ε" if parts[0] == "eps" else "μ"
        kind = tr("Debye") if parts[1] == "debye" else tr("Lorentz")
        what = {"delta": "Δ", "f0": "f₀", "gamma": "γ"}[parts[3]]
        return f"{sym} {kind} {parts[2]} {what}"
    table = {
        "thickness": tr("thickness"), "R": "R", "X": "X",
        "eps'": "ε′", "eps''": "ε″", "mu'": "μ′", "mu''": "μ″",
        "eps_inf": "ε∞", "mu_inf": "μ∞", "eps'' (constant)": tr("ε″ (constant)"),
        "mu'' (constant)": tr("μ″ (constant)"), "sigma": "σ",
        "volume fraction": tr("volume fraction"),
    }
    return table.get(name, name)
