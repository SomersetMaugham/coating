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


@dataclass
class NrwUncertainty:
    """Monte-Carlo spread of an NRW extraction: standard deviations per frequency (same shape as ``f``)."""

    f: np.ndarray
    eps_re: np.ndarray
    eps_loss: np.ndarray
    mu_re: np.ndarray
    mu_loss: np.ndarray
    n_samples: int


def nrw_uncertainty(f, s11, s21, thickness, cutoff_hz=None, branch=0, s12=None, offset1=0.0, offset2=0.0,
                    sigma_thickness=0.0, sigma_mag_db=0.0, sigma_phase_deg=0.0, n_samples=200, seed=0, method="nrw",
                    post=None, s22=None, holder_length=None, sigma_holder=0.0):
    """Standard deviations of eps', eps'', mu', mu'' from measurement errors, by Monte Carlo over ``nrw``.

    Error model (all 1 sigma, normal; 0 = that error is off):
    * ``sigma_thickness`` [m]: one thickness error per sample, the same at every frequency (a systematic error);
    * ``sigma_mag_db``, ``sigma_phase_deg``: an independent error on the magnitude (dB) and phase of each S-parameter at
      each frequency (random noise).  Calibration drift is smooth over frequency rather than independent, so treat
      this as a noise estimate, not a full calibration-uncertainty budget.
    The phase branch is held at ``branch``.  Near half-wave resonances the spread grows large: that is the point.
    ``method``: "nrw", "nonmagnetic" or "nonmagnetic_invariant" (the extraction that is repeated; the last needs
    ``s12``, ``s22`` and ``holder_length``, whose error ``sigma_holder`` [m] is drawn once per sample);
    ``post(eps, mu) -> (eps, mu)`` is applied to every sample (e.g. the coax air-gap correction), so the spread is that
    of the final values."""
    invariant = method == "nonmagnetic_invariant"
    extract = {"nrw": nrw, "nonmagnetic": nonmagnetic, "nonmagnetic_invariant": None}[method]
    if invariant and (s12 is None or s22 is None or holder_length is None):
        raise ValueError("the position-invariant method needs S12, S22 and the holder length")
    if sigma_holder < 0:
        raise ValueError("uncertainties must not be negative")
    f = np.asarray(f, dtype=float)
    if not all(x >= 0 for x in (sigma_thickness, sigma_mag_db, sigma_phase_deg)):
        raise ValueError("uncertainties must not be negative")
    if int(n_samples) < 2:
        raise ValueError("need at least two samples")
    rng = np.random.default_rng(seed)
    params = [np.asarray(s11, dtype=complex), np.asarray(s21, dtype=complex)]
    if s12 is not None:
        params.append(np.asarray(s12, dtype=complex))
    if invariant:
        params.append(np.asarray(s22, dtype=complex))
    out = []
    for _ in range(int(n_samples)):
        noisy = []
        for sp in params:
            mag = 10 ** (rng.normal(0.0, sigma_mag_db, f.shape) / 20) if sigma_mag_db else 1.0
            ph = np.exp(1j * np.radians(rng.normal(0.0, sigma_phase_deg, f.shape))) if sigma_phase_deg else 1.0
            noisy.append(sp * mag * ph)
        d = thickness + (rng.normal(0.0, sigma_thickness) if sigma_thickness else 0.0)
        if d <= 0:
            continue
        try:
            if invariant:
                lair = holder_length + (rng.normal(0.0, sigma_holder) if sigma_holder else 0.0)
                r = nonmagnetic_invariant(f, noisy[0], noisy[1], noisy[2], noisy[3], d, lair, cutoff_hz, branch)
            else:
                r = extract(f, noisy[0], noisy[1], d, cutoff_hz, branch, s12=noisy[2] if s12 is not None else None,
                            offset1=offset1, offset2=offset2)
        except ValueError:
            continue
        out.append(post(r.eps, r.mu) if post is not None else (r.eps, r.mu))
    if len(out) < 2:
        raise ValueError("too few samples gave a solution")
    eps = np.array([e for e, _ in out])
    mu = np.array([m for _, m in out])
    return NrwUncertainty(f, np.std(eps.real, axis=0, ddof=1), np.std(-eps.imag, axis=0, ddof=1),
                          np.std(mu.real, axis=0, ddof=1), np.std(-mu.imag, axis=0, ddof=1), len(out))


def slab_sparams(f, eps, mu, thickness, cutoff_hz=None):
    """Closed-form S11, S21 of a uniform slab filling a matched line, reference planes at its faces (the forward model
    the non-magnetic fit inverts): Gamma = (Z - Z0)/(Z + Z0), T = exp(-gamma d),
    S11 = Gamma (1 - T^2) / (1 - Gamma^2 T^2),  S21 = T (1 - Gamma^2) / (1 - Gamma^2 T^2).
    TEM: Z/Z0 = sqrt(mu/eps); TE10: Z/Z0 = mu gamma0 / gamma, gamma = j 2 pi sqrt(eps mu / lambda0^2 - 1/lambdac^2)."""
    f = np.asarray(f, dtype=float)
    lam0 = C0 / f
    inv_lc2 = 0.0 if cutoff_hz is None else (float(cutoff_hz) / C0) ** 2
    em = np.asarray(eps, dtype=complex) * np.asarray(mu, dtype=complex)
    # e^{+jwt}: gamma = j beta + alpha with Im(sqrt) <= 0 for a passive medium
    kz = np.sqrt(em / lam0 ** 2 - inv_lc2 + 0j)
    kz = np.where(kz.imag > 0, -kz, kz)
    gamma = 1j * 2 * np.pi * kz
    gamma0 = 1j * 2 * np.pi * np.sqrt(1 / lam0 ** 2 - inv_lc2 + 0j)
    z = np.asarray(mu, dtype=complex) * gamma0 / gamma
    g = (z - 1) / (z + 1)
    t = np.exp(-gamma * thickness)
    den = 1 - g ** 2 * t ** 2
    return g * (1 - t ** 2) / den, t * (1 - g ** 2) / den


def nonmagnetic(f, s11, s21, thickness, cutoff_hz=None, branch=0, s12=None, offset1=0.0, offset2=0.0):
    """eps of a non-magnetic sample (mu = 1) by a least-squares fit of S11 and S21 at each frequency.

    Two real unknowns against four real measurements, so the fit stays well posed where |S11| -> 0 and NRW is unstable
    (low-loss samples at half-wave thicknesses); this is the idea of the NIST iterative method (J. Baker-Jarvis et al.,
    IEEE Trans. Microw. Theory Tech. 38, 1096 (1990)), here with a plain complex least-squares fit.  The first
    frequency starts from the NRW value on ``branch``; each later one starts from the previous solution, which also
    carries the phase branch along.  Returns an ``NrwResult`` with mu = 1; its warnings come from the NRW start
    (branch) and a ``fit_poor`` entry where the fitted S-parameters miss the measured ones."""
    from scipy.optimize import least_squares

    f = np.asarray(f, dtype=float)
    start = nrw(f, s11, s21, thickness, cutoff_hz, branch, s12=s12, offset1=offset1, offset2=offset2)
    s11 = np.asarray(s11, dtype=complex)
    s21 = np.asarray(s21, dtype=complex)
    if s12 is not None:
        s21 = 0.5 * (s21 + np.asarray(s12, dtype=complex))
    lam0 = C0 / f
    inv_lc2 = 0.0 if cutoff_hz is None else (float(cutoff_hz) / C0) ** 2
    beta0 = 2 * np.pi * np.sqrt(1 / lam0 ** 2 - inv_lc2)
    if offset1 or offset2:
        s11 = s11 * np.exp(2j * beta0 * offset1)
        s21 = s21 * np.exp(1j * beta0 * (offset1 + offset2))
    eps = np.empty(f.shape, dtype=complex)
    resid = np.empty(f.shape)
    guess = complex(start.eps[0])
    for i, fi in enumerate(f):
        def res(x, fi=fi, i=i):
            a, b = slab_sparams(np.array([fi]), np.array([x[0] - 1j * x[1]]), np.array([1.0]), thickness, cutoff_hz)
            d = np.array([a[0] - s11[i], b[0] - s21[i]])
            return np.concatenate([d.real, d.imag])
        sol = least_squares(res, [guess.real, -guess.imag], x_scale="jac", xtol=1e-14, ftol=1e-14, gtol=1e-14)
        eps[i] = sol.x[0] - 1j * sol.x[1]
        resid[i] = float(np.sqrt(np.mean(sol.fun ** 2)))
        guess = eps[i]
    warnings = [w for w in start.warnings if w[0] in ("branch_suspect", "nonreciprocal")]
    bad = resid > 0.02
    if np.any(bad):
        warnings.append(("fit_poor", {"f_hz": [float(x) for x in f[bad]], "max_residual": float(resid.max())}))
    if np.any(eps.imag > 1e-9 * np.abs(eps)):
        warnings.append(("nonpassive", {"f_hz": [float(x) for x in f[eps.imag > 1e-9 * np.abs(eps)]]}))
    r = NrwResult(f, eps, np.ones(f.shape, dtype=complex), start.gamma, start.transmission, start.branch,
                  start.suggested_branch, start.resonant, start.delay_mismatch, start.reciprocity_error, warnings)
    r.fit_residual = resid
    return r


def coax_gap_correction(eps, mu, r_conductor_in, r_sample_in, r_sample_out, r_conductor_out):
    """Remove the air gaps around a sample in a coaxial holder (quasi-static layered-coax model; J. Baker-Jarvis et
    al., NIST Technical Note 1355 (1993)).  Radii in any one unit: inner conductor R1 <= sample bore R2 < sample outer
    R3 <= outer conductor R4.  The gaps and the sample are radial layers:

        capacitances in series:  L3 / eps_m = L1 + L2 / eps_c   ->  eps_c = eps_m L2 / (L3 - eps_m L1)
        inductances add:         mu_m L3 = L1 + L2 mu_c         ->  mu_c = (mu_m L3 - L1) / L2

    with L1 = ln(R2/R1) + ln(R4/R3) (air), L2 = ln(R3/R2) (sample), L3 = ln(R4/R1).  Applied to the complex values, so
    the loss is corrected too.  The eps correction diverges as eps_m L1 -> L3: a large measured eps with a sizeable
    gap cannot be corrected reliably, and ValueError is raised where Re(L3 - eps_m L1) <= 0.1 L3."""
    r1, r2, r3, r4 = (float(x) for x in (r_conductor_in, r_sample_in, r_sample_out, r_conductor_out))
    if not (0 < r1 <= r2 < r3 <= r4):
        raise ValueError("radii must satisfy 0 < conductor_in <= sample_in < sample_out <= conductor_out")
    l1 = np.log(r2 / r1) + np.log(r4 / r3)
    l2 = np.log(r3 / r2)
    l3 = np.log(r4 / r1)
    eps = np.asarray(eps, dtype=complex)
    mu = np.asarray(mu, dtype=complex)
    den = l3 - eps * l1
    if np.any(den.real <= 0.1 * l3):
        raise ValueError("the gap is too large for this permittivity: the correction is ill-conditioned")
    return eps * l2 / den, (mu * l3 - l1) / l2


def _invariant_faces(f, s11, s21, s12, s22, gap, cutoff_hz):
    """(S11s, S21s): the sample's own S-parameters from the position-invariant combinations, with the empty line
    (total length ``gap``) removed.  S11s is known up to its sign: it is made continuous along frequency here, and the
    caller picks the overall sign."""
    lam0 = C0 / f
    inv_lc2 = 0.0 if cutoff_hz is None else (float(cutoff_hz) / C0) ** 2
    beta0 = 2 * np.pi * np.sqrt(1 / lam0 ** 2 - inv_lc2)
    e1 = (s11 * s22 - s21 * s12) * np.exp(2j * beta0 * gap)
    s21s = 0.5 * (s21 + s12) * np.exp(1j * beta0 * gap)
    s11s = np.sqrt(e1 + s21s ** 2)
    for k in range(1, s11s.size):  # continuity of the square root's sign
        if abs(s11s[k] - s11s[k - 1]) > abs(s11s[k] + s11s[k - 1]):
            s11s[k] = -s11s[k]
    return e1, s21s, s11s


def nonmagnetic_invariant(f, s11, s21, s12, s22, thickness, holder_length, cutoff_hz=None, branch=0):
    """eps (mu = 1) without knowing where the sample sits in the holder (NIST TN 1355, Baker-Jarvis et al.).

    With empty line of total length L_air - d around the sample, split L1 + L2 in any way,

        E1 = S11 S22 - S21 S12 = exp(-2 gamma0 (L_air - d)) (S11s^2 - S21s^2),
        E2 = (S21 + S12) / 2   = exp(-gamma0 (L_air - d)) S21s,

    where S11s, S21s are the sample's S-parameters at its faces (``slab_sparams``): only the holder length enters.
    The measured combinations are rotated back by the empty line, and at each frequency complex eps is fitted to them
    (absolute residuals, as ``nonmagnetic``).  The start is position-invariant too: S11s^2 = E1 + S21s^2 gives S11s
    up to a sign; NRW on both signs is run on the sample's own faces, and the sign whose mu is nearer 1 wins (the
    sample is assumed non-magnetic).  Later frequencies start from the previous solution.  The sample must be
    symmetric; ``asymmetric`` warns when |S11| and |S22| differ by more than 0.05 (with a lossless empty line they
    are equal wherever a symmetric sample sits)."""
    from scipy.optimize import least_squares

    f = np.asarray(f, dtype=float)
    d, lair = float(thickness), float(holder_length)
    if not lair >= d:
        raise ValueError(f"the holder length {lair * 1e3:g} mm is shorter than the sample {d * 1e3:g} mm")
    s11, s21, s12, s22 = (np.asarray(x, dtype=complex) for x in (s11, s21, s12, s22))
    if not all(x.shape == f.shape for x in (s11, s21, s12, s22)):
        raise ValueError("f and the four S-parameters must have the same length")
    e1, s21s, s11s = _invariant_faces(f, s11, s21, s12, s22, lair - d, cutoff_hz)
    recip = float(np.max(np.abs(s21 - s12) / np.maximum(np.abs(s21), 1e-12)))
    cands = [nrw(f, sign * s11s, s21s, d, cutoff_hz, branch) for sign in (1, -1)]
    start = min(cands, key=lambda r: float(np.median(np.abs(r.mu - 1))))
    eps = np.empty(f.shape, dtype=complex)
    resid = np.empty(f.shape)
    guess = complex(start.eps[0])
    for i, fi in enumerate(f):
        def res(x, fi=fi, i=i):
            a, b = slab_sparams(np.array([fi]), np.array([x[0] - 1j * x[1]]), np.array([1.0]), d, cutoff_hz)
            r = np.array([a[0] ** 2 - b[0] ** 2 - e1[i], b[0] - s21s[i]])
            return np.concatenate([r.real, r.imag])
        sol = least_squares(res, [guess.real, -guess.imag], x_scale="jac", xtol=1e-14, ftol=1e-14, gtol=1e-14)
        eps[i] = sol.x[0] - 1j * sol.x[1]
        resid[i] = float(np.sqrt(np.mean(sol.fun ** 2)))
        guess = eps[i]
    warnings = [w for w in start.warnings if w[0] == "branch_suspect"]
    if recip > RECIPROCITY:
        warnings.append(("nonreciprocal", {"max_relative": recip}))
    bad = resid > 0.02
    if np.any(bad):
        warnings.append(("fit_poor", {"f_hz": [float(x) for x in f[bad]], "max_residual": float(resid.max())}))
    asym = float(np.max(np.abs(np.abs(s11) - np.abs(s22))))
    if asym > 0.05:
        warnings.append(("asymmetric", {"max_mag_diff": asym}))
    if np.any(eps.imag > 1e-9 * np.abs(eps)):
        warnings.append(("nonpassive", {"f_hz": [float(x) for x in f[eps.imag > 1e-9 * np.abs(eps)]]}))
    ones = np.ones(f.shape, dtype=complex)
    g_fit, t_fit = slab_sparams(f, eps, ones, d, cutoff_hz)  # the fitted sample's S11s, S21s (for the record)
    r = NrwResult(f, eps, ones, g_fit, t_fit, start.branch, start.suggested_branch, np.abs(s11s) < SMALL_S11,
                  start.delay_mismatch, recip, warnings)
    r.fit_residual = resid
    return r
