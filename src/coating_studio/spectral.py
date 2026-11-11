"""The spectral axis in the project's display unit (``SweepSettings.spectral_unit``): GHz, THz, vacuum wavelength in
µm or nm, or wavenumber in cm⁻¹.  Plots, texts and exports of the GUI and the report go through here; the engine and
the files stay in Hz.  No Qt (the report uses it); the GUI's input boxes are in ``gui/spectral.py``.

Wavelength runs opposite to frequency, so the helpers keep axes ascending and intervals ordered.
"""

from __future__ import annotations

import numpy as np

from coating_studio.core.units import (
    LINEWIDTH_UNIT, SPECTRAL_LABEL, fmt_num, from_display, from_linewidth, from_spectral, spectral_bounds,
    spectral_kind, spectral_reversed, to_display, to_linewidth, to_spectral,
)
from coating_studio.i18n import tr

_SYMBOL = {"f": "f", "wl": "λ", "wn": "ν̃"}
_CSV_HEADER = {"GHz": "f [GHz]", "THz": "f [THz]", "um": "lambda [um]", "nm": "lambda [nm]", "cm-1": "nu [cm-1]"}
INPUT_RANGE = (1e-9, 1e15)  # display values; 2-18 GHz is about 1.7e7-1.5e8 nm, 200 nm about 1.5e6 GHz


def unit_of(project):
    return project.sweep.spectral_unit


def unit_label(unit):
    return SPECTRAL_LABEL[unit]


def axis_label(unit):
    """'Frequency [GHz]', 'Wavelength [nm]' or 'Wavenumber [cm⁻¹]'."""
    kind = spectral_kind(unit)
    if kind == "wl":
        return tr("Wavelength [{u}]", u=SPECTRAL_LABEL[unit])
    if kind == "wn":
        return tr("Wavenumber [{u}]", u=SPECTRAL_LABEL[unit])
    return tr("Frequency [{u}]", u=SPECTRAL_LABEL[unit])


def quantity_name(unit):
    """'Frequency', 'Wavelength' or 'Wavenumber' (translated): the label of an input in this unit."""
    return tr({"f": "Frequency", "wl": "Wavelength", "wn": "Wavenumber"}[spectral_kind(unit)])


def symbol(unit):
    return _SYMBOL[spectral_kind(unit)]


def csv_header(unit):
    """First-column header of a data export; csvio reads every one of these back (comparison curves)."""
    return _CSV_HEADER[unit]


def x_values(f, unit):
    """Frequencies [Hz] -> display values (same order as ``f``)."""
    return to_spectral(np.asarray(f, dtype=float), unit)


def fmt_value(f_hz, unit, digits=4):
    """'550 nm', '10 GHz'."""
    return f"{fmt_num(to_spectral(float(f_hz), unit), digits)} {SPECTRAL_LABEL[unit]}"


def fmt_point(f_hz, unit, digits=5):
    """'λ = 550 nm', 'f = 10 GHz'."""
    return f"{symbol(unit)} = {fmt_value(f_hz, unit, digits)}"


def fmt_range(f_lo, f_hi, unit, digits=4):
    """'8–12 GHz', '400–700 nm' (low to high in the display unit), or one value for a single frequency."""
    if not f_hi > f_lo:
        return fmt_value(f_lo, unit, digits)
    lo, hi = spectral_bounds(f_lo, f_hi, unit)
    return f"{fmt_num(lo, digits)}–{fmt_num(hi, digits)} {SPECTRAL_LABEL[unit]}"


def cursor_text(unit, x):
    """Cursor read-out of an axis position that is already in the display unit (no conversion)."""
    return f"{symbol(unit)} = {x:.5g} {SPECTRAL_LABEL[unit]}"


def span(f_lo, f_hi, unit):
    """Display interval (low, high) of [f_lo, f_hi], for masks and shaded bands."""
    return spectral_bounds(f_lo, f_hi, unit)


def set_xlim(ax, x):
    """Ascending x limits whatever the order of ``x`` (a wavelength sweep runs high to low)."""
    ax.set_xlim(min(x[0], x[-1]), max(x[0], x[-1]))


def ascending(x, *arrays):
    """``x`` and the arrays (first axis along x) reversed when ``x`` runs downwards, for meshes and stacks."""
    x = np.asarray(x)
    if len(x) > 1 and x[0] > x[-1]:
        return (x[::-1],) + tuple(np.asarray(a)[::-1] for a in arrays)
    return (x,) + tuple(np.asarray(a) for a in arrays)




# -- model parameters (optimiser paths, material editor) ----------------------------------------------------
# Debye/Lorentz f0 and gamma are stored in Hz and addressed with the unit "GHz" (the CLI contract); the GUI shows
# f0 as a spectral position in the project's unit and gamma as a damping rate (core.units.LINEWIDTH_UNIT).
_POSITION_SYMBOL = {"f": "f₀", "wl": "λ₀", "wn": "ν̃₀"}


def param_kind(path, unit):
    """"position" for a dispersion-term f0, "linewidth" for its gamma, "length" for a thickness, else None."""
    path = tuple(path)
    if unit == "mm":
        return "length"
    if unit == "GHz" and path and path[0] == "material" and path[-1] in ("f0", "gamma"):
        return "position" if path[-1] == "f0" else "linewidth"
    return None


def position_symbol(unit):
    """'f₀', 'λ₀' or 'ν̃₀': the resonance of a dispersion term in the spectral unit ``unit``."""
    return _POSITION_SYMBOL[spectral_kind(unit)]


def param_display_unit(project, path, unit):
    """Display unit id of the parameter at ``path`` whose own unit is ``unit`` (see ``param_kind``)."""
    kind = param_kind(path, unit)
    if kind == "length":
        return project.sweep.length_unit
    if kind == "position":
        return project.sweep.spectral_unit
    if kind == "linewidth":
        return LINEWIDTH_UNIT[project.sweep.spectral_unit]
    return unit


def param_reversed(project, path, unit):
    """True when the displayed number falls as the stored value rises (an f0 shown as a wavelength)."""
    return param_kind(path, unit) == "position" and spectral_reversed(project.sweep.spectral_unit)


def param_to_display(si, project, path, unit):
    """Stored value -> displayed number.  ValueError for an f0 <= 0 in a wavelength or wavenumber unit."""
    from coating_studio.core.units import to_length

    kind = param_kind(path, unit)
    if kind == "length":
        return to_length(si, project.sweep.length_unit)
    if kind == "position":
        return to_spectral(si, project.sweep.spectral_unit)
    if kind == "linewidth":
        return to_linewidth(si, project.sweep.spectral_unit)
    return to_display(si, unit)


def param_from_display(x, project, path, unit):
    """Displayed number -> stored value (inverse of ``param_to_display``)."""
    from coating_studio.core.units import from_length

    kind = param_kind(path, unit)
    if kind == "length":
        return from_length(x, project.sweep.length_unit)
    if kind == "position":
        return from_spectral(x, project.sweep.spectral_unit)
    if kind == "linewidth":
        return from_linewidth(x, project.sweep.spectral_unit)
    return from_display(x, unit)
