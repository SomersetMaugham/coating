"""Display-unit adapters.  The engine works in SI; the UI shows engineering units.

Keeping every conversion here lets later optical modes (um, nm, n/kappa) plug in
without touching the engine.
"""

import numpy as np

GHZ = 1e9
MHZ = 1e6
MM = 1e-3
G_PER_CM3 = 1000.0  # 1 g/cm^3 = 1000 kg/m^3


# Display-unit id (as returned by project.param_unit / Material.params) -> SI scale and SI unit name.
DISPLAY_SCALE = {"mm": 1e-3, "GHz": 1e9, "ohm": 1.0, "S/m": 1.0, "frac": 1.0, "": 1.0, "g/cm3": 1000.0,
                 "nH": 1e-9, "pF": 1e-12}
SI_UNIT = {"mm": "m", "GHz": "Hz", "ohm": "ohm", "S/m": "S/m", "frac": "frac", "": "", "g/cm3": "kg/m3",
           "nH": "H", "pF": "F"}


def to_display(value, unit):
    """SI value -> value in the display unit ``unit``."""
    return value / DISPLAY_SCALE.get(unit, 1.0)


def from_display(value, unit):
    """Value in the display unit ``unit`` -> SI value."""
    return value * DISPLAY_SCALE.get(unit, 1.0)


def si_unit(unit):
    """SI unit name of a display-unit id."""
    return SI_UNIT.get(unit, unit)


def hz_to_ghz(f):
    return np.asarray(f) / GHZ if not np.isscalar(f) else f / GHZ


def ghz_to_hz(f):
    return np.asarray(f) * GHZ if not np.isscalar(f) else f * GHZ


def m_to_mm(x):
    return x / MM


def mm_to_m(x):
    return x * MM


def density_to_display(rho_si):
    """kg/m^3 -> g/cm^3."""
    return rho_si / G_PER_CM3


def density_from_display(rho_disp):
    """g/cm^3 -> kg/m^3."""
    return rho_disp * G_PER_CM3


def gamma_to_db(gamma_abs, positive=False):
    """|Gamma| -> dB.  Negative convention 20log10|G| (default) or positive -20log10|G|."""
    g = np.maximum(np.asarray(gamma_abs, dtype=float), 1e-15)
    db = 20.0 * np.log10(g)
    return -db if positive else db


def power_to_db(p, positive=False):
    """|Gamma|^2 (power ratio) -> dB."""
    p = np.maximum(np.asarray(p, dtype=float), 1e-30)
    db = 10.0 * np.log10(p)
    return -db if positive else db


def nk_from_eps_mu(eps, mu=1.0):
    """Complex refractive index n - j*kappa from eps, mu (future optical adapter)."""
    from coating_studio.core.csqrt import kz_sqrt

    n = kz_sqrt(np.asarray(eps, dtype=complex) * mu)
    return n.real, -n.imag


def fmt_num(x, digits=5):
    if x == 0:
        return "0"
    a = abs(x)
    if 1e-3 <= a < 1e5:
        s = f"{x:.{digits}g}"
    else:
        s = f"{x:.{max(digits - 2, 2)}e}"
    return s


# -- spectral axis (display only; the engine and the files keep frequencies in Hz) --------------------------
# unit id -> (kind, scale): "f" frequency x = f / scale; "wl" vacuum wavelength x = c / (f * scale);
# "wn" wavenumber x = f / (c * scale) with scale 100 for cm^-1.
SPECTRAL_UNITS = {"GHz": ("f", 1e9), "THz": ("f", 1e12), "um": ("wl", 1e-6), "nm": ("wl", 1e-9),
                  "cm-1": ("wn", 100.0)}
SPECTRAL_LABEL = {"GHz": "GHz", "THz": "THz", "um": "µm", "nm": "nm", "cm-1": "cm⁻¹"}
DEFAULT_SPECTRAL_UNIT = "GHz"


def spectral_kind(unit):
    """"f" (frequency), "wl" (vacuum wavelength) or "wn" (wavenumber); ValueError for an unknown unit."""
    try:
        return SPECTRAL_UNITS[unit][0]
    except KeyError:
        raise ValueError(f"unknown spectral unit {unit!r}") from None


def spectral_reversed(unit):
    """True when the display value falls as the frequency rises (wavelength units)."""
    return spectral_kind(unit) == "wl"


def to_spectral(f, unit):
    """Frequency [Hz] (scalar or array, > 0) -> value in the spectral display unit."""
    from coating_studio.core.constants import C0

    kind, scale = spectral_kind(unit), SPECTRAL_UNITS[unit][1]
    a = np.asarray(f, dtype=float)
    if kind != "f" and np.any(a <= 0):
        raise ValueError("frequencies must be positive")
    if kind == "f":
        out = a / scale
    elif kind == "wl":
        out = C0 / (a * scale)
    else:
        out = a / (C0 * scale)
    return float(out) if np.ndim(f) == 0 else out


def from_spectral(x, unit):
    """Value in the spectral display unit (> 0) -> frequency [Hz]."""
    from coating_studio.core.constants import C0

    kind, scale = spectral_kind(unit), SPECTRAL_UNITS[unit][1]
    a = np.asarray(x, dtype=float)
    if np.any(a <= 0) or not np.all(np.isfinite(a)):
        raise ValueError("spectral values must be positive and finite")
    if kind == "f":
        out = a * scale
    elif kind == "wl":
        out = C0 / (a * scale)
    else:
        out = a * scale * C0
    return float(out) if np.ndim(x) == 0 else out


def spectral_bounds(f_lo, f_hi, unit):
    """(low, high) display values of the frequency interval [f_lo, f_hi] (swapped for wavelengths)."""
    a, b = to_spectral(f_lo, unit), to_spectral(f_hi, unit)
    return (min(a, b), max(a, b))


# A Lorentz damping rate gamma [Hz] is a frequency interval, not a spectral position: it scales linearly with the
# frequency (and wavenumber) units, but has no wavelength equivalent (c/gamma is meaningless and the width in
# wavelength, lambda0^2 gamma / c, would change whenever f0 changes).  Wavelength units show it in THz.
LINEWIDTH_UNIT = {"GHz": "GHz", "THz": "THz", "um": "THz", "nm": "THz", "cm-1": "cm-1"}


def to_linewidth(gamma, unit):
    """Damping rate [Hz] (>= 0) -> number in ``LINEWIDTH_UNIT[unit]``."""
    from coating_studio.core.constants import C0

    lw = LINEWIDTH_UNIT[unit]
    a = np.asarray(gamma, dtype=float)
    if np.any(a < 0):
        raise ValueError("damping rates must not be negative")
    out = a / (C0 * 100.0) if lw == "cm-1" else a / SPECTRAL_UNITS[lw][1]
    return float(out) if np.ndim(gamma) == 0 else out


def from_linewidth(x, unit):
    """Number in ``LINEWIDTH_UNIT[unit]`` (>= 0, finite) -> damping rate [Hz]."""
    from coating_studio.core.constants import C0

    lw = LINEWIDTH_UNIT[unit]
    a = np.asarray(x, dtype=float)
    if np.any(a < 0) or not np.all(np.isfinite(a)):
        raise ValueError("damping rates must be non-negative and finite")
    out = a * 100.0 * C0 if lw == "cm-1" else a * SPECTRAL_UNITS[lw][1]
    return float(out) if np.ndim(x) == 0 else out


# -- length (layer thickness) display unit (display only; layers and files keep metres) -------------------
LENGTH_UNITS = {"mm": 1e-3, "um": 1e-6, "nm": 1e-9}
LENGTH_LABEL = {"mm": "mm", "um": "µm", "nm": "nm"}
DEFAULT_LENGTH_UNIT = "mm"
# A new slab layer, and the optimisation range of a layer whose thickness is 0, in a size that suits the unit
# (a 2 mm default layer next to 100 nm films squeezed every film to the minimum width of the cross-section).
NEW_SLAB_THICKNESS = {"mm": 2e-3, "um": 1e-6, "nm": 100e-9}
ZERO_THICKNESS_RANGE = {"mm": (1e-4, 1e-2), "um": (1e-7, 1e-5), "nm": (1e-8, 1e-6)}


def length_scale(unit):
    """Metres per display unit; ValueError for an unknown unit."""
    try:
        return LENGTH_UNITS[unit]
    except KeyError:
        raise ValueError(f"unknown length unit {unit!r}") from None


def to_length(m, unit):
    """Metres -> display unit."""
    return m / length_scale(unit)


def from_length(x, unit):
    """Display unit -> metres."""
    return x * length_scale(unit)
