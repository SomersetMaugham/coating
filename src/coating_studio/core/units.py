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
