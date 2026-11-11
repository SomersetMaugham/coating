"""Conversions between SI parameter values and display units used by the UI."""

from __future__ import annotations

from coating_studio.core.units import (  # noqa: F401 (fmt_num, from_display, to_display re-exported)
    LENGTH_LABEL, SPECTRAL_LABEL, fmt_num, from_display, to_display,
)
from coating_studio.i18n import tr

# parameter units plus the display units a parameter can be shown in (thickness: mm/µm/nm; f0 and gamma: the
# spectral and linewidth units).  The length and spectral tables agree on their shared ids "um" and "nm".
_LABEL = {**SPECTRAL_LABEL, **LENGTH_LABEL, "ohm": "Ω/sq", "S/m": "S/m", "frac": "", "": "", "g/cm3": "g/cm³",
          "nH": "nH", "pF": "pF"}


def rl_display(db, positive):
    """RL in the user's display convention (internal RL is always 20·log10|Γ|, negative = good).

    The map is its own inverse, so it also converts a displayed value back to internal dB."""
    return -db if positive else db


def unit_label(unit):
    return _LABEL.get(unit, unit)


def param_label(label: str, position: str = "f₀") -> str:
    """Translate an engine parameter label such as 'L2 Spacer: thickness'.  ``position`` is the symbol of a
    dispersion term's f0 in the display unit (``spectral.position_symbol``: f₀, λ₀ or ν̃₀)."""
    if ": " in label:
        head, tail = label.split(": ", 1)
        return f"{head}: {translate_param_name(tail, position)}"
    return translate_param_name(label, position)


def translate_param_name(name: str, position: str = "f₀") -> str:
    # dispersion term labels look like "mu debye #1 delta"
    parts = name.split(" ")
    if len(parts) == 4 and parts[1] in ("debye", "lorentz", "havriliak_negami") and parts[2].startswith("#"):
        sym = "ε" if parts[0] == "eps" else "μ"
        kind = {"debye": tr("Debye"), "lorentz": tr("Lorentz"), "havriliak_negami": tr("Havriliak-Negami")}[parts[1]]
        what = {"delta": "Δ", "f0": position, "gamma": "γ", "alpha": "α", "beta": "β"}[parts[3]]
        return f"{sym} {kind} {parts[2]} {what}"
    table = {
        "thickness": tr("thickness"), "R": "R", "X": "X",
        "eps'": "ε′", "eps''": "ε″", "mu'": "μ′", "mu''": "μ″",
        "eps_inf": "ε∞", "mu_inf": "μ∞", "eps'' (constant)": tr("ε″ (constant)"),
        "mu'' (constant)": tr("μ″ (constant)"), "sigma": "σ",
        "volume fraction": tr("volume fraction"),
        "eps' (1 GHz)": "ε′ (1 GHz)", "eps'' (1 GHz)": "ε″ (1 GHz)", "mu' (1 GHz)": "μ′ (1 GHz)",
        "mu'' (1 GHz)": "μ″ (1 GHz)",
        "eps' exponent a": f"ε′ {tr('exponent')} a", "eps'' exponent b": f"ε″ {tr('exponent')} b",
        "mu' exponent a": f"μ′ {tr('exponent')} a", "mu'' exponent b": f"μ″ {tr('exponent')} b",
    }
    return table.get(name, name)
