"""Planar multilayer solver (oblique incidence, TE and TM).

Method: transmission-line (impedance) recursion expressed in reflection
coefficients.  Going from the backing towards the incident medium, only
factors exp(-2j*kz*d) with |.| <= 1 appear, so thick or very lossy layers can
never overflow.  Layer absorption is then recovered by a forward pass that
propagates the forward-wave amplitude V+ (again only decaying factors) and
differencing the time-averaged Poynting flux at each interface.

Conventions
-----------
* Time dependence exp(+j*omega*t); eps = eps' - j*eps'', mu = mu' - j*mu''.
* Waves travel as exp(-j*kz*z); kz is chosen with Im(kz) <= 0 (see csqrt).
* Wave impedances: TE  Z = omega*mu0*mu/kz ;  TM  Z = kz/(omega*eps0*eps).
* Gamma is the reflection coefficient of the tangential electric field,
  referred to the incident medium.  R = |Gamma|^2.
* Resistive sheets are shunt admittances 1/Zs (Zs = R + jX, Ohm/sq).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from coating_studio.core.constants import C0, EPS0, MU0
from coating_studio.core.csqrt import kz_sqrt
from coating_studio.core.structure import SheetLayer, SlabLayer, Structure


class SolverError(ValueError):
    pass


@dataclass
class PolarizationResult:
    gamma: np.ndarray  # complex, shape (Nf, Na)
    R: np.ndarray  # reflectance |Gamma|^2
    T: np.ndarray  # transmittance into the backing half-space (0 for PEC)
    A_layers: np.ndarray  # shape (N_layers, Nf, Na), absorbed fraction per layer
    z_in: np.ndarray  # input impedance normalised to the incident wave impedance

    @property
    def A(self):
        return self.A_layers.sum(axis=0) if self.A_layers.size else np.zeros_like(self.R)


@dataclass
class SolveResult:
    f: np.ndarray  # [Hz]
    theta: np.ndarray  # [deg]
    pol: dict = field(default_factory=dict)  # "TE"/"TM" -> PolarizationResult
    layer_uids: list = field(default_factory=list)

    def quantity(self, name: str, pol: str):
        """name in {'R','T','A'}; pol in {'TE','TM','avg'} (avg = unpolarised power average)."""
        if pol == "avg":
            vals = [getattr(p, name) for p in self.pol.values()]
            return sum(vals) / len(vals)
        return getattr(self.pol[pol], name)

    def layer_absorption(self, pol: str):
        if pol == "avg":
            vals = [p.A_layers for p in self.pol.values()]
            return sum(vals) / len(vals)
        return self.pol[pol].A_layers


def _convert(g, za, zb):
    """Re-reference reflection coefficient g (w.r.t. za) to zb, without forming Z."""
    a = za * (1.0 + g)
    b = zb * (1.0 - g)
    return (a - b) / (a + b)


def _shunt(g, z, zs):
    """Add a shunt sheet impedance zs at a plane where g is referred to z."""
    a = z * (1.0 + g)
    b = 1.0 - g
    num = a * zs - z * (a + b * zs)
    den = a * zs + z * (a + b * zs)
    return num / den


def _power(v, i):
    return 0.5 * np.real(v * np.conj(i))


def solve(structure: Structure, materials, f, theta_deg=0.0, pols=("TE", "TM"),
          perturb=None) -> SolveResult:
    """Solve the stack at frequencies ``f`` [Hz] and incidence angles ``theta_deg``.

    ``materials`` maps names to Material objects.  ``perturb`` optionally maps
    layer uid -> {"thickness","eps","mu","sheet": multiplicative factors}; slabs also accept
    "eps_re"/"eps_loss" and "mu_re"/"mu_loss" (real and loss parts separately); RLC sheets also accept
    "sheet_R", "sheet_L", "sheet_C" (default "sheet_R" = "sheet").
    (used by tolerance analysis).
    """
    f = np.atleast_1d(np.asarray(f, dtype=float))
    th = np.atleast_1d(np.asarray(theta_deg, dtype=float))
    if np.any(f <= 0):
        raise SolverError("frequencies must be positive")
    if np.any(th < 0) or np.any(th >= 90):
        raise SolverError("incidence angle must be in [0, 90) degrees")
    perturb = perturb or {}

    def resolve(name):
        try:
            return materials[name]
        except KeyError:
            raise SolverError(f"unknown material: {name!r}") from None

    cache = {}

    def eps_mu(name):
        if name not in cache:
            eps, mu = resolve(name).eps_mu(f, resolve)
            cache[name] = (np.broadcast_to(eps, f.shape)[:, None],
                           np.broadcast_to(mu, f.shape)[:, None])
        return cache[name]

    w = (2.0 * np.pi * f)[:, None]
    k0 = w / C0
    eps_i, mu_i = eps_mu(structure.incident)
    n2_i = eps_i * mu_i
    if np.any(np.abs(n2_i.imag) > 1e-9 * np.abs(n2_i)) or np.any(n2_i.real <= 0):
        raise SolverError("the incident medium must be lossless (real eps, mu > 0)")
    kx = k0 * np.sqrt(n2_i.real) * np.sin(np.deg2rad(th))[None, :]

    layers = structure.layers
    out = SolveResult(f=f, theta=th, layer_uids=[ly.uid for ly in layers])
    for pol in pols:
        if pol not in ("TE", "TM"):
            raise SolverError(f"unknown polarisation {pol!r}")

        def medium(eps, mu):
            kz = kz_sqrt(k0 * k0 * eps * mu - kx * kx)
            kz = np.where(kz == 0, 1e-30 + 0j, kz)
            z = (w * MU0 * mu / kz) if pol == "TE" else (kz / (w * EPS0 * eps))
            return kz, z

        _, z0 = medium(eps_i, mu_i)

        # ---- backward pass: backing -> front --------------------------------
        shape = np.broadcast_shapes(f[:, None].shape, th[None, :].shape)
        if structure.backing.kind == "pec":
            g = np.full(shape, -1.0 + 0j)
            zref = z0
        elif structure.backing.kind == "halfspace":
            if not structure.backing.material:
                raise SolverError("half-space backing needs a material")
            _, zsub = medium(*eps_mu(structure.backing.material))
            g = np.zeros(shape, dtype=complex)
            zref = zsub
        else:
            raise SolverError(f"unknown backing {structure.backing.kind!r}")

        store = [None] * len(layers)
        for idx in range(len(layers) - 1, -1, -1):
            ly = layers[idx]
            p = perturb.get(ly.uid, {})
            if isinstance(ly, SlabLayer):
                eps, mu = eps_mu(ly.material)
                # Real and loss parts can be perturbed separately ("eps_re"/"eps_loss"); without
                # those keys the whole complex value is scaled exactly as before.
                if "eps_re" in p or "eps_loss" in p:
                    base = p.get("eps", 1.0)
                    eps = eps.real * p.get("eps_re", base) + 1j * (eps.imag * p.get("eps_loss", base))
                else:
                    eps = eps * p.get("eps", 1.0)
                if "mu_re" in p or "mu_loss" in p:
                    base = p.get("mu", 1.0)
                    mu = mu.real * p.get("mu_re", base) + 1j * (mu.imag * p.get("mu_loss", base))
                else:
                    mu = mu * p.get("mu", 1.0)
                kz, zc = medium(eps, mu)
                d = ly.thickness * p.get("thickness", 1.0)
                if d < 0:
                    raise SolverError("negative thickness")
                gb = _convert(g, zref, zc)
                g = gb * np.exp(-2j * kz * d)
                zref = zc
                store[idx] = ("slab", zc, kz, d, gb)
            elif isinstance(ly, SheetLayer):
                if ly.model == "rlc":
                    if not ly.R > 0 or ly.L < 0 or (ly.C is not None and not ly.C > 0):
                        raise SolverError("RLC sheet needs R > 0, L >= 0 and C > 0")
                    # independent R / L / C factors so a tolerance can shift the resonance
                    zs = ly.impedance_at(f, p.get("sheet_R", p.get("sheet", 1.0)), p.get("sheet_L", 1.0),
                                         p.get("sheet_C", 1.0))[:, None]
                else:
                    zs = ly.impedance * p.get("sheet", 1.0)
                if np.any(np.abs(zs) < 1e-9):
                    raise SolverError("sheet impedance must be non-zero")
                g = _shunt(g, zref, zs)
                store[idx] = ("sheet", zs)
            else:
                raise SolverError(f"unknown layer type {type(ly).__name__}")
        gin = _convert(g, zref, z0)

        # ---- forward pass: recover fields and absorbed power ----------------
        p_inc = 0.5 * np.real(1.0 / z0)  # |V+|^2 = 1
        v = 1.0 + gin
        i = (1.0 - gin) / z0
        a_layers = np.zeros((len(layers),) + shape)
        for idx, item in enumerate(store):
            if item[0] == "sheet":
                zs = item[1]
                a_layers[idx] = 0.5 * np.abs(v) ** 2 * np.real(1.0 / zs) / p_inc
                i = i - v / zs
            else:
                _, zc, kz, d, gb = item
                p_front = _power(v, i)
                vp = 0.5 * (v + zc * i) * np.exp(-1j * kz * d)
                v = vp * (1.0 + gb)
                i = vp * (1.0 - gb) / zc
                a_layers[idx] = (p_front - _power(v, i)) / p_inc
        if structure.backing.kind == "halfspace":
            t = _power(v, i) / p_inc
        else:
            t = np.zeros(shape)
        with np.errstate(divide="ignore", invalid="ignore"):
            z_in = (1.0 + gin) / (1.0 - gin)
        out.pol[pol] = PolarizationResult(gamma=gin, R=np.abs(gin) ** 2, T=t,
                                          A_layers=a_layers, z_in=z_in)
    return out
