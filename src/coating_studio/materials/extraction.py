"""Permittivity and permeability of a sample from two-port S-parameters: Nicholson-Ross-Weir (NRW).

A flat sample of thickness ``d`` fills the cross-section of a transmission line: a coaxial line or free space (TEM,
no cutoff), or a rectangular waveguide in its TE10 mode (cutoff frequency ``fc``).  The S-parameters must be
referred to the empty line's wave impedance (as a TRL calibration does) with reference planes at the two sample faces;
``offset1``/``offset2`` move planes that sit in the empty line in front of / behind the sample onto its faces.
Engineering time convention e^{+j omega t}, as Touchstone files and the solver use: eps = eps' - j eps''.

    K = (S11^2 - S21^2 + 1) / (2 S11),   Gamma = K -/+ sqrt(K^2 - 1)  (|Gamma| <= 1)
    T = (S11 + S21 - Gamma) / (1 - (S11 + S21) Gamma)
    1/L = ln(1/T) / (j 2 pi d)                      (L: wavelength in the filled line; ln with the phase unwrapped)
    mu = (1/L) (1 + Gamma) / ((1 - Gamma) sqrt(1/lambda0^2 - 1/lambdac^2))
    eps = lambda0^2 / mu (1/lambdac^2 + 1/L^2)

(A. M. Nicholson, G. F. Ross, IEEE Trans. Instrum. Meas. 19, 377 (1970); W. B. Weir, Proc. IEEE 62, 33 (1974).)

Two known weaknesses are reported rather than hidden:

* the phase of T is only known up to 2 pi n.  It is unwrapped along frequency from ``branch`` at the lowest frequency
  (0 when the sample is shorter than half a wavelength there).  Weir's check compares the measured group delay
  -d(arg T)/d omega, which does not depend on n, with the delay the extracted eps*mu predicts for a non-dispersive
  sample, d (eps mu f/c^2) / sqrt(eps mu f^2/c^2 - 1/lambdac^2), which does.  The branch with the smallest mismatch
  is reported as ``suggested_branch``, preferring branches whose result is passive (a wrong branch often shows gain).
  Strongly dispersive samples (near a resonance) make the delay check approximate.
* for a low-loss sample, |S11| -> 0 where the sample is a multiple of half a wavelength thick, and the result is
  unstable around those frequencies.  They are flagged; the values are still returned.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from coating_studio.core.constants import C0

SMALL_S11 = 0.05  # |S11| below this: near a half-wavelength resonance, where NRW is ill-conditioned
RECIPROCITY = 0.05  # relative |S21 - S12| that flags a non-reciprocal (or badly calibrated) measurement


@dataclass
class NrwResult:
    f: np.ndarray
    eps: np.ndarray
    mu: np.ndarray
    gamma: np.ndarray  # interface reflection coefficient
    transmission: np.ndarray  # T = exp(-gamma_z d)
    branch: int
    suggested_branch: int = 0
    resonant: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))  # |S11| < SMALL_S11
    delay_mismatch: float = 0.0  # median relative difference: measured group delay vs the delay eps*mu predicts
    reciprocity_error: float = 0.0  # max |S21 - S12| / |S21|
    warnings: list = field(default_factory=list)  # (code, details) pairs


def nrw(f, s11, s21, thickness, cutoff_hz=None, branch=0, s12=None, offset1=0.0, offset2=0.0):
    """NRW extraction (see the module docstring).  ``f`` [Hz] ascending, S-parameters complex arrays, ``thickness``
    and offsets in metres, ``cutoff_hz`` None for TEM (coax, free space) or the TE10 cutoff of a waveguide.
    ``s12`` (optional) is averaged with ``s21``.  Returns an ``NrwResult``; raises ValueError on bad input."""
    f = np.asarray(f, dtype=float)
    s11 = np.asarray(s11, dtype=complex)
    s21 = np.asarray(s21, dtype=complex)
    if f.ndim != 1 or len(f) < 2 or s11.shape != f.shape or s21.shape != f.shape:
        raise ValueError("f, S11 and S21 must be 1-D arrays of the same length (at least two frequencies)")
    if np.any(np.diff(f) <= 0) or f[0] <= 0:
        raise ValueError("frequencies must be positive and ascending")
    d = float(thickness)
    if not d > 0:
        raise ValueError(f"the sample thickness must be positive, got {d:g} m")
    if offset1 < 0 or offset2 < 0:
        raise ValueError("offsets must not be negative")
    lam0 = C0 / f
    inv_lc2 = 0.0
    if cutoff_hz is not None:
        fc = float(cutoff_hz)
        if not fc > 0:
            raise ValueError(f"the cutoff frequency must be positive, got {fc:g} Hz")
        if np.any(f <= fc):
            raise ValueError(f"every frequency must be above the waveguide cutoff {fc / 1e9:.6g} GHz")
        inv_lc2 = (fc / C0) ** 2
    warnings = []
    recip = 0.0
    if s12 is not None:
        s12 = np.asarray(s12, dtype=complex)
        recip = float(np.max(np.abs(s21 - s12) / np.maximum(np.abs(s21), 1e-12)))
        if recip > RECIPROCITY:
            warnings.append(("nonreciprocal", {"max_relative": recip}))
        s21 = 0.5 * (s21 + s12)
    beta0 = 2 * np.pi * np.sqrt(1 / lam0 ** 2 - inv_lc2)  # empty line
    if offset1 or offset2:
        s11 = s11 * np.exp(2j * beta0 * offset1)
        s21 = s21 * np.exp(1j * beta0 * (offset1 + offset2))

    with np.errstate(divide="ignore", invalid="ignore"):
        k = (s11 ** 2 - s21 ** 2 + 1) / (2 * s11)
        root = np.sqrt(k * k - 1)
        g1, g2 = k + root, k - root
        gam = np.where(np.abs(g1) <= np.abs(g2), g1, g2)
        t = (s11 + s21 - gam) / (1 - (s11 + s21) * gam)
    if not np.all(np.isfinite(gam) & np.isfinite(t)) or np.any(t == 0):
        raise ValueError("the S-parameters give no finite solution (S11 = 0 exactly, or no transmission)")
    phase0 = np.unwrap(np.angle(t))
    root_g = np.sqrt(1 / lam0 ** 2 - inv_lc2)
    resonant = np.abs(s11) < SMALL_S11
    tau_meas = -np.gradient(phase0, 2 * np.pi * f)  # group delay through the sample; independent of the branch

    def solve_branch(n):
        phase = phase0 - 2 * np.pi * n
        inv_l = (-phase + 1j * np.log(np.abs(t))) / (2 * np.pi * d)  # = ln(1/T) / (j 2 pi d)
        mu_n = inv_l * (1 + gam) / ((1 - gam) * root_g)
        eps_n = lam0 ** 2 / mu_n * (inv_lc2 + inv_l ** 2)
        em = eps_n * mu_n
        tau_pred = d * np.real(em * f / C0 ** 2 / np.sqrt(em * f ** 2 / C0 ** 2 - inv_lc2 + 0j))
        ok = ~resonant & (np.abs(tau_pred) > 0)
        mis = float(np.median(np.abs(tau_meas[ok] - tau_pred[ok]) / np.abs(tau_pred[ok]))) if np.any(ok) else 0.0
        gain = float(np.mean((eps_n.imag > 1e-9 * np.abs(eps_n)) | (mu_n.imag > 1e-9 * np.abs(mu_n))))
        return eps_n, mu_n, mis, gain

    eps, mu, mismatch, _ = solve_branch(int(branch))
    # A wrong branch often gives gain (eps'' or mu'' < 0) somewhere; the delay check alone is misled by strong
    # dispersion.  So passive candidates come first, then the smallest delay mismatch.
    scores = {}
    # rough n from the group delay at the lowest frequency (exact for a non-dispersive TEM sample); search around it
    n_est = int(max(0, np.round((tau_meas[0] * 2 * np.pi * f[0] + phase0[0]) / (2 * np.pi))))
    for n in range(max(0, min(int(branch), n_est) - 3), max(int(branch), n_est) + 4):
        _, _, mis_n, gain_n = solve_branch(n)
        scores[n] = (gain_n > 0, mis_n)
    suggested = min(scores, key=scores.get)
    if np.any(resonant):
        warnings.append(("half_wave_resonance", {"f_hz": [float(x) for x in f[resonant]]}))
    if suggested != int(branch):
        warnings.append(("branch_suspect", {"median_relative": mismatch, "branch": int(branch),
                                            "suggested_branch": suggested}))
    passive = (eps.imag <= 1e-9 * np.abs(eps)) & (mu.imag <= 1e-9 * np.abs(mu))
    if not np.all(passive):
        warnings.append(("nonpassive", {"f_hz": [float(x) for x in f[~passive]]}))
    return NrwResult(f, eps, mu, gam, t, int(branch), suggested, resonant, mismatch, recip, warnings)
