"""Minimal runtime translation (English source strings -> Korean).

Pure Python so the engine (warnings) and the GUI share one catalogue and no
Qt build tools (lrelease) are needed on any platform.  The language is chosen
at start-up; changing it takes effect after a restart.
"""

from __future__ import annotations

import locale

from coating_studio.i18n_ko import KO

SUPPORTED = ("en", "ko")
_lang = "en"


def detect_system_language() -> str:
    try:
        from PySide6.QtCore import QLocale

        name = QLocale.system().name()
    except Exception:  # noqa: BLE001 - Qt may be unavailable in headless use
        name = (locale.getlocale()[0] or "")
    return "ko" if name.lower().startswith("ko") else "en"


def set_language(lang: str):
    global _lang
    _lang = lang if lang in SUPPORTED else "en"


def language() -> str:
    return _lang


def tr(text: str, **kwargs) -> str:
    """Translate ``text`` (English source) and apply str.format(**kwargs)."""
    out = KO.get(text, text) if _lang == "ko" else text
    return out.format(**kwargs) if kwargs else out


# ---------------------------------------------------------------------------
_ISSUES_EN = {
    "out_of_range": "Measured data covers {lo:.4g}-{hi:.4g} GHz but {flo:.4g}-{fhi:.4g} GHz is requested.",
    "missing_reference": "References a material that does not exist: {ref}.",
    "eps_gain": "Passivity: eps'' < 0 (gain) near {f:.4g} GHz.",
    "mu_gain": "Passivity: mu'' < 0 (gain) near {f:.4g} GHz.",
    "eps_inf_below_one": "eps_inf = {value:.3g} < 1 is unusual for a real dielectric.",
    "snoek": "Snoek limit: delta_mu x f0 = {product:.3g} GHz exceeds ~{limit:.3g} GHz (pure-iron bound); "
             "this permeability is probably not manufacturable.",
    "term_negative": "A dispersion term has a negative strength, frequency or damping.",
    "eps_huge": "eps' up to {value:.3g} is unusually large.",
    "demo_values": "Built-in demonstration values (representative, not a datasheet). "
                   "Use measured data for a real design.",
    "unknown_material": "Unknown material: {n}",
    "material_cycle": "This mixture references itself (directly or through other mixtures).",
    "rozanov_limit": "Target {target}: the design's mu_s x d is {design_mm:.3g} mm but at least {required_mm:.3g} mm "
                     "is needed (Rozanov bound, normal incidence).",
    "rozanov_infeasible": "Target {target}: even the optimisation ranges reach only {max_mm:.3g} mm of mu_s x d; "
                          "at least {required_mm:.3g} mm is needed (Rozanov bound, normal incidence).",
    "mixture_fraction_range": "Fraction {fraction_lo:.3g}-{fraction_hi:.3g} reaches {lo:.3g}-{hi:.3g}, where the "
                              "{model} model is unreliable.",
    "sweep_outside_data": "Frequencies {flo:.4g}-{fhi:.4g} GHz ({where}) lie outside the measured data "
                          "{lo:.4g}-{hi:.4g} GHz.",
}


def issue_text(issue, lang: str | None = None) -> str:
    template = _ISSUES_EN.get(issue.code, issue.code)
    if (lang or _lang) == "ko":
        template = KO.get(template, template)
    try:
        return template.format(**issue.args)
    except (KeyError, ValueError):
        return template
