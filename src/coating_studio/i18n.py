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
    "uniaxial_misuse": "A uniaxial material cannot be a mixture constituent or a component of another uniaxial material.",
    "percolation_exceeded": "The volume fraction {fraction:.3g} is at or above the percolation threshold {pc:.3g}, where the Odelevskiy rule has no meaning.",
    "rozanov_limit": "Target {target}: the design's mu_s x d is {design_mm:.3g} mm but at least {required_mm:.3g} mm "
                     "is needed (Rozanov bound, normal incidence).",
    "rozanov_infeasible": "Target {target}: even the optimisation ranges reach only {max_mm:.3g} mm of mu_s x d; "
                          "at least {required_mm:.3g} mm is needed (Rozanov bound, normal incidence).",
    "mixture_fraction_range": "Fraction {fraction_lo:.3g}-{fraction_hi:.3g} reaches {lo:.3g}-{hi:.3g}, where the "
                              "{model} model is unreliable.",
    "inverted_filler_model": "{inclusion} was inverted with the {extracted} rule, but this mixture uses {model}; "
                             "its values only mean something with the rule they came from.",
    "inverted_filler_fraction": "Fraction {fraction_lo:.3g}-{fraction_hi:.3g} leaves {lo:.3g}-{hi:.3g}, the range "
                                "around the loading {phi0:.3g} at which {inclusion} was inverted.",
    "inverted_filler_direct": "Effective values tied to a mixing rule, not a measured material; use them only as the "
                              "filler of a mixture.",
    "sweep_outside_data": "Frequencies {flo:.4g}-{fhi:.4g} GHz ({where}) lie outside the measured data "
                          "{lo:.4g}-{hi:.4g} GHz.",
}


# Issues whose arguments are frequencies [GHz] (the CLI contract); with another spectral display unit the GUI and the
# report show them through these templates.  (low, high) pairs swap for wavelengths.
_ISSUES_SPECTRAL = {
    "out_of_range": "Measured data covers {lo:.4g}-{hi:.4g} {u} but {flo:.4g}-{fhi:.4g} {u} is requested.",
    "eps_gain": "Passivity: eps'' < 0 (gain) near {f:.4g} {u}.",
    "mu_gain": "Passivity: mu'' < 0 (gain) near {f:.4g} {u}.",
    "sweep_outside_data": "Spectral range {flo:.4g}-{fhi:.4g} {u} ({where}) lies outside the measured data "
                          "{lo:.4g}-{hi:.4g} {u}.",
}
_SPECTRAL_PAIRS = (("lo", "hi"), ("flo", "fhi"))


def _spectral_args(args, unit):
    from coating_studio.core.units import SPECTRAL_LABEL, to_spectral

    out = dict(args, u=SPECTRAL_LABEL[unit])
    if "f" in args:
        out["f"] = to_spectral(args["f"] * 1e9, unit)
    for a, b in _SPECTRAL_PAIRS:
        if a in args and b in args:
            x, y = to_spectral(args[a] * 1e9, unit), to_spectral(args[b] * 1e9, unit)
            out[a], out[b] = min(x, y), max(x, y)
    return out


def issue_text(issue, lang: str | None = None, unit: str = "GHz") -> str:
    """Message of a ``materials.checks.Issue``.  ``unit``: spectral display unit for frequency arguments (the issue
    itself, and the CLI's ``issue_dict``, keep GHz)."""
    if unit != "GHz" and issue.code in _ISSUES_SPECTRAL:
        template = _ISSUES_SPECTRAL[issue.code]
        if (lang or _lang) == "ko":
            template = KO.get(template, template)
        try:
            return template.format(**_spectral_args(issue.args, unit))
        except (KeyError, ValueError, TypeError):
            return template
    template = _ISSUES_EN.get(issue.code, issue.code)
    if (lang or _lang) == "ko":
        template = KO.get(template, template)
    try:
        return template.format(**issue.args)
    except (KeyError, ValueError):
        return template
