"""Fit Debye / Lorentz / Havriliak-Negami dispersion models to measured eps(f), mu(f).

The resulting DispersiveMaterial is causal by construction (each term
satisfies Kramers-Kronig), so it can be evaluated outside the measured range.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from coating_studio.core.constants import EPS0
from coating_studio.materials.models import DispersiveMaterial, eval_terms


@dataclass
class FitSpec:
    n_debye: int = 1
    n_lorentz: int = 0
    fit_sigma: bool = False  # eps only
    fit_const_loss: bool = False
    n_hn: int = 0  # Havriliak-Negami terms (delta, f0, alpha, beta), after the Debye and Lorentz terms


@dataclass
class FitResult:
    material: DispersiveMaterial
    rms_eps: float  # rms residual relative to max |eps|
    rms_mu: float


def _fit_side(f, data, spec: FitSpec, allow_sigma: bool):
    """Return (inf, const_loss, sigma, terms, rel_rms)."""
    n_d, n_l, n_h = spec.n_debye, spec.n_lorentz, spec.n_hn
    use_sigma = spec.fit_sigma and allow_sigma
    scale = max(np.max(np.abs(data)), 1e-12)
    flo, fhi = float(f.min()), float(f.max())
    n_terms = n_d + n_l + n_h
    if n_terms == 0 and not use_sigma and not spec.fit_const_loss:
        val = complex(np.mean(data.real), np.mean(data.imag))
        resid = np.abs(data - val) / scale
        return val.real, max(-val.imag, 0.0), 0.0, [], float(np.sqrt(np.mean(resid ** 2)))
    centres = np.geomspace(flo, fhi, n_terms + 2)[1:-1] if n_terms else []

    # parameter vector: inf, [const_loss], [log10 sigma], per debye (delta, log f0),
    # per lorentz (delta, log f0, log gamma), per Havriliak-Negami (delta, log f0, alpha, beta)
    x0 = [float(np.min(data.real))]
    lb, ub = [-np.inf], [np.inf]
    if spec.fit_const_loss:
        x0.append(0.0); lb.append(0.0); ub.append(np.inf)
    if use_sigma:
        x0.append(-2.0); lb.append(-12.0); ub.append(8.0)
    span = max(float(np.ptp(data.real)), 0.1 * scale)
    for k in range(n_terms):
        x0 += [span / max(n_terms, 1), np.log10(centres[k])]
        lb += [0.0, np.log10(flo) - 3]
        ub += [np.inf, np.log10(fhi) + 3]
        if n_d <= k < n_d + n_l:  # Lorentz
            x0.append(np.log10(centres[k]))
            lb.append(np.log10(flo) - 4)
            ub.append(np.log10(fhi) + 3)
        elif k >= n_d + n_l:  # Havriliak-Negami: exponents in (0, 1], kept off 0 so the power stays well scaled
            x0 += [0.8, 0.8]
            lb += [0.05, 0.05]
            ub += [1.0, 1.0]

    def unpack(x):
        i = 0
        inf = x[i]; i += 1
        cl = 0.0
        if spec.fit_const_loss:
            cl = x[i]; i += 1
        sig = 0.0
        if use_sigma:
            sig = 10 ** x[i]; i += 1
        terms = []
        for k in range(n_terms):
            if k < n_d:
                terms.append({"type": "debye", "delta": x[i], "f0": 10 ** x[i + 1]}); i += 2
            elif k < n_d + n_l:
                terms.append({"type": "lorentz", "delta": x[i], "f0": 10 ** x[i + 1],
                              "gamma": 10 ** x[i + 2]}); i += 3
            else:
                terms.append({"type": "havriliak_negami", "delta": x[i], "f0": 10 ** x[i + 1],
                              "alpha": x[i + 2], "beta": x[i + 3]}); i += 4
        return inf, cl, sig, terms

    def model(x):
        inf, cl, sig, terms = unpack(x)
        val = complex(1, 0) * inf - 1j * cl + eval_terms(terms, f)
        if sig:
            val = val - 1j * sig / (2 * np.pi * f * EPS0)
        return val

    def resid(x):
        r = (model(x) - data) / scale
        return np.concatenate([r.real, r.imag])

    best = None
    starts = [np.array(x0, dtype=float)]
    rng = np.random.default_rng(0)
    for _ in range(6):
        jitter = np.array(x0, dtype=float)
        for j in range(len(jitter)):
            if np.isfinite(lb[j]) and np.isfinite(ub[j]):
                jitter[j] = rng.uniform(lb[j], ub[j])
            elif lb[j] == 0.0:
                jitter[j] = abs(jitter[j]) * rng.uniform(0.2, 3.0)
        starts.append(jitter)
    for s in starts:
        s = np.clip(s, np.array(lb) + 1e-12 * np.isfinite(lb), np.array(ub) - 1e-12 * np.isfinite(ub))
        try:
            sol = least_squares(resid, s, bounds=(lb, ub), x_scale="jac", max_nfev=4000)
        except ValueError:
            continue
        if best is None or sol.cost < best.cost:
            best = sol
    if best is None:
        raise ValueError(f"least squares failed from all {len(starts)} starting points")
    inf, cl, sig, terms = unpack(best.x)
    rms = float(np.sqrt(np.mean(np.abs(model(best.x) - data) ** 2)) / scale)
    return float(inf), float(cl), float(sig), [{k: float(v) if k != "type" else v for k, v in t.items()}
                                                 for t in terms], rms


def fit_dispersive(name, f, eps, mu, eps_spec: FitSpec, mu_spec: FitSpec | None = None,
                   density=1000.0) -> FitResult:
    f = np.asarray(f, dtype=float)
    eps = np.asarray(eps, dtype=complex)
    mu = np.asarray(mu, dtype=complex)
    e_inf, e_cl, e_sig, e_terms, e_rms = _fit_side(f, eps, eps_spec, allow_sigma=True)
    if mu_spec is None:
        m_inf, m_cl, m_terms, m_rms = 1.0, 0.0, [], 0.0
    else:
        m_inf, m_cl, _, m_terms, m_rms = _fit_side(f, mu, mu_spec, allow_sigma=False)
    mat = DispersiveMaterial(name, eps_inf=e_inf, eps_loss=e_cl, sigma=e_sig, eps_terms=e_terms,
                             mu_inf=m_inf, mu_loss=m_cl, mu_terms=m_terms, density=density,
                             note="fitted")
    return FitResult(mat, e_rms, m_rms)
