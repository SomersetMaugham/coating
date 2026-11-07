"""Material models.

Every material returns relative (eps, mu) as complex arrays over frequency
[Hz], with the engineering convention eps = eps' - j*eps'' (loss > 0).

Parameters are addressed by *keys*: tuples such as ("eps_inf",) or
("mu_terms", 0, "f0").  Keys let the optimiser and the UI read and write any
numeric parameter uniformly.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np

from coating_studio.core.constants import EPS0

DEFAULT_DENSITY = 1000.0  # kg/m^3


class OutOfRangeError(ValueError):
    """Tabulated data evaluated outside its measured frequency range."""

    def __init__(self, material, f_lo, f_hi, data_lo, data_hi):
        self.material = material
        self.f_lo, self.f_hi, self.data_lo, self.data_hi = f_lo, f_hi, data_lo, data_hi
        super().__init__(
            f"material {material!r}: requested {f_lo / 1e9:.6g}-{f_hi / 1e9:.6g} GHz "
            f"outside data range {data_lo / 1e9:.6g}-{data_hi / 1e9:.6g} GHz")


class MaterialCycleError(ValueError):
    pass


@dataclass
class ParamInfo:
    key: tuple
    label: str  # English label; the GUI translates
    unit: str  # display unit identifier: "", "GHz", "S/m", "g/cm3", "frac"
    lower: float | None = None  # hard physical lower bound (SI)
    upper: float | None = None


class Material:
    kind = "base"

    def __init__(self, name: str, density: float = DEFAULT_DENSITY, note: str = ""):
        self.name = name
        self.density = float(density)
        self.note = note

    # -- evaluation ---------------------------------------------------------
    def eps_mu(self, f, resolver):
        raise NotImplementedError

    def get_density(self, resolver) -> float:
        return self.density

    # -- parameters ---------------------------------------------------------
    def params(self) -> list[ParamInfo]:
        return []

    def get(self, key):
        obj = self
        for k in key[:-1]:
            obj = obj[k] if isinstance(k, int) else getattr(obj, k)
        last = key[-1]
        return obj[last] if isinstance(obj, dict) else getattr(obj, last)

    def set(self, key, value):
        obj = self
        for k in key[:-1]:
            obj = obj[k] if isinstance(k, int) else getattr(obj, k)
        last = key[-1]
        if isinstance(obj, dict):
            obj[last] = float(value)
        else:
            setattr(obj, last, float(value))

    # -- references ---------------------------------------------------------
    def references(self) -> set:
        return set()

    def rename_reference(self, old, new):
        pass

    # -- serialisation ------------------------------------------------------
    def _base_dict(self):
        return {"kind": self.kind, "name": self.name, "density": self.density, "note": self.note}

    def to_dict(self):
        return self._base_dict()

    def clone(self, name=None):
        m = copy.deepcopy(self)
        if name is not None:
            m.name = name
        return m


# ---------------------------------------------------------------------------
class ConstantMaterial(Material):
    """Frequency-independent complex eps and mu."""

    kind = "constant"

    def __init__(self, name, eps_re=1.0, eps_loss=0.0, mu_re=1.0, mu_loss=0.0, **kw):
        super().__init__(name, **kw)
        self.eps_re, self.eps_loss = float(eps_re), float(eps_loss)
        self.mu_re, self.mu_loss = float(mu_re), float(mu_loss)

    def eps_mu(self, f, resolver):
        f = np.asarray(f, dtype=float)
        eps = np.full(f.shape, complex(self.eps_re, -self.eps_loss))
        mu = np.full(f.shape, complex(self.mu_re, -self.mu_loss))
        return eps, mu

    def params(self):
        return [ParamInfo(("eps_re",), "eps'", ""),
                ParamInfo(("eps_loss",), "eps''", ""),
                ParamInfo(("mu_re",), "mu'", ""),
                ParamInfo(("mu_loss",), "mu''", "")]

    def to_dict(self):
        d = self._base_dict()
        d.update(eps_re=self.eps_re, eps_loss=self.eps_loss, mu_re=self.mu_re, mu_loss=self.mu_loss)
        return d


class PowerLawMaterial(Material):
    """Empirical power-law fit of eps and mu over frequency (f in GHz, values given at 1 GHz)::

        eps'(f) = eps_re / f**eps_a     eps''(f) = eps_loss / f**eps_b
        mu'(f)  = mu_re  / f**mu_a      mu''(f)  = mu_loss  / f**mu_b

    This is the form of the Michielssen et al. (1993) absorber material database.  It is a curve fit, not a
    causal model (the real and loss parts are not linked by Kramers-Kronig, and mu' grows without bound as
    f -> 0), so use it only inside the band it was fitted on; the static permeability is unknown."""

    kind = "power_law"

    def __init__(self, name, eps_re=1.0, eps_a=0.0, eps_loss=0.0, eps_b=0.0,
                 mu_re=1.0, mu_a=0.0, mu_loss=0.0, mu_b=0.0, **kw):
        super().__init__(name, **kw)
        self.eps_re, self.eps_a, self.eps_loss, self.eps_b = map(float, (eps_re, eps_a, eps_loss, eps_b))
        self.mu_re, self.mu_a, self.mu_loss, self.mu_b = map(float, (mu_re, mu_a, mu_loss, mu_b))

    def eps_mu(self, f, resolver):
        g = np.asarray(f, dtype=float) / 1e9  # GHz; the solver rejects f <= 0
        eps = self.eps_re * g ** -self.eps_a - 1j * self.eps_loss * g ** -self.eps_b
        mu = self.mu_re * g ** -self.mu_a - 1j * self.mu_loss * g ** -self.mu_b
        return eps, mu

    def params(self):
        return [ParamInfo(("eps_re",), "eps' (1 GHz)", ""), ParamInfo(("eps_a",), "eps' exponent a", ""),
                ParamInfo(("eps_loss",), "eps'' (1 GHz)", "", lower=0.0), ParamInfo(("eps_b",), "eps'' exponent b", ""),
                ParamInfo(("mu_re",), "mu' (1 GHz)", ""), ParamInfo(("mu_a",), "mu' exponent a", ""),
                ParamInfo(("mu_loss",), "mu'' (1 GHz)", "", lower=0.0), ParamInfo(("mu_b",), "mu'' exponent b", "")]

    def to_dict(self):
        d = self._base_dict()
        d.update(eps_re=self.eps_re, eps_a=self.eps_a, eps_loss=self.eps_loss, eps_b=self.eps_b,
                 mu_re=self.mu_re, mu_a=self.mu_a, mu_loss=self.mu_loss, mu_b=self.mu_b)
        return d


def loss_tangent(real, loss):
    """tan δ = loss / real part (ε″/ε′ or μ″/μ′).  Only defined for a positive real part."""
    if real <= 0:
        raise ValueError("loss tangent needs a positive real part")
    return loss / real


def loss_from_tangent(real, tan_delta):
    """Imaginary part (loss, > 0) from the real part and tan δ."""
    if real <= 0:
        raise ValueError("loss tangent needs a positive real part")
    return real * tan_delta


def eps_from_nk(n, k, mu=1.0 + 0j):
    """Permittivity of a medium with complex refractive index N = n - jk and permeability mu.

    N^2 = eps * mu, so eps = (n - jk)^2 / mu.  k > 0 is loss (same convention as eps'').
    """
    return (n - 1j * k) ** 2 / mu


def nk_from_eps_mu(eps, mu=1.0 + 0j):
    """(n, k) with N = n - jk = sqrt(eps * mu) on the passive branch (k >= 0, and n >= 0 if k = 0)."""
    N = np.sqrt(complex(eps) * complex(mu))
    if N.imag > 0 or (N.imag == 0 and N.real < 0):
        N = -N
    return N.real, -N.imag


# ---------------------------------------------------------------------------
def make_term(kind="debye", delta=1.0, f0=1e9, gamma=1e9):
    if kind not in ("debye", "lorentz"):
        raise ValueError(f"unknown term type {kind!r}")
    t = {"type": kind, "delta": float(delta), "f0": float(f0)}
    if kind == "lorentz":
        t["gamma"] = float(gamma)
    return t


def eval_terms(terms, f):
    """Sum of relaxation / resonance terms (complex, engineering convention).

    debye  : delta / (1 + j f/f0)
    lorentz: delta * f0^2 / (f0^2 - f^2 + j f gamma)
    For mu, a Debye term is the Snoek-type domain-wall/spin relaxation of ferrites.
    """
    f = np.asarray(f, dtype=float)
    out = np.zeros(f.shape, dtype=complex)
    for t in terms:
        if t["type"] == "debye":
            out = out + t["delta"] / (1.0 + 1j * f / t["f0"])
        else:
            f0 = t["f0"]
            out = out + t["delta"] * f0 * f0 / (f0 * f0 - f * f + 1j * f * t["gamma"])
    return out


class DispersiveMaterial(Material):
    """eps(f) = eps_inf - j eps_loss + sum(terms) - j sigma/(omega eps0)
    mu(f)  = mu_inf  - j mu_loss  + sum(terms)."""

    kind = "dispersive"

    def __init__(self, name, eps_inf=1.0, eps_loss=0.0, sigma=0.0, eps_terms=None,
                 mu_inf=1.0, mu_loss=0.0, mu_terms=None, **kw):
        super().__init__(name, **kw)
        self.eps_inf, self.eps_loss, self.sigma = float(eps_inf), float(eps_loss), float(sigma)
        self.mu_inf, self.mu_loss = float(mu_inf), float(mu_loss)
        self.eps_terms = [dict(t) for t in (eps_terms or [])]
        self.mu_terms = [dict(t) for t in (mu_terms or [])]

    def eps_mu(self, f, resolver):
        f = np.asarray(f, dtype=float)
        eps = complex(self.eps_inf, -self.eps_loss) + eval_terms(self.eps_terms, f)
        if self.sigma:
            eps = eps - 1j * self.sigma / (2 * np.pi * f * EPS0)
        mu = complex(self.mu_inf, -self.mu_loss) + eval_terms(self.mu_terms, f)
        return np.broadcast_to(eps, f.shape), np.broadcast_to(mu, f.shape)

    def params(self):
        out = [ParamInfo(("eps_inf",), "eps_inf", ""),
               ParamInfo(("eps_loss",), "eps'' (constant)", "", lower=0.0),
               ParamInfo(("sigma",), "sigma", "S/m", lower=0.0)]
        for prefix, terms in (("eps_terms", self.eps_terms), ("mu_terms", self.mu_terms)):
            if prefix == "mu_terms":
                out += [ParamInfo(("mu_inf",), "mu_inf", ""),
                        ParamInfo(("mu_loss",), "mu'' (constant)", "", lower=0.0)]
            sym = "eps" if prefix == "eps_terms" else "mu"
            for i, t in enumerate(terms):
                tag = f"{sym} {t['type']} #{i + 1}"
                out.append(ParamInfo((prefix, i, "delta"), f"{tag} delta", "", lower=0.0))
                out.append(ParamInfo((prefix, i, "f0"), f"{tag} f0", "GHz", lower=1.0))
                if t["type"] == "lorentz":
                    out.append(ParamInfo((prefix, i, "gamma"), f"{tag} gamma", "GHz", lower=0.0))
        return out

    def to_dict(self):
        d = self._base_dict()
        d.update(eps_inf=self.eps_inf, eps_loss=self.eps_loss, sigma=self.sigma,
                 eps_terms=[dict(t) for t in self.eps_terms],
                 mu_inf=self.mu_inf, mu_loss=self.mu_loss,
                 mu_terms=[dict(t) for t in self.mu_terms])
        return d


# ---------------------------------------------------------------------------
class TabulatedMaterial(Material):
    """Measured data, linearly interpolated.  Evaluation outside the data range raises."""

    kind = "tabulated"

    def __init__(self, name, f, eps_re, eps_loss, mu_re=None, mu_loss=None, source="", **kw):
        super().__init__(name, **kw)
        f = np.asarray(f, dtype=float)
        order = np.argsort(f)
        self.f = f[order]
        self.eps_re = np.asarray(eps_re, dtype=float)[order]
        self.eps_loss = np.asarray(eps_loss, dtype=float)[order]
        n = len(self.f)
        self.mu_re = np.ones(n) if mu_re is None else np.asarray(mu_re, dtype=float)[order]
        self.mu_loss = np.zeros(n) if mu_loss is None else np.asarray(mu_loss, dtype=float)[order]
        if n < 2:
            raise ValueError("tabulated material needs at least two frequency points")
        if np.any(np.diff(self.f) <= 0):
            raise ValueError("tabulated frequencies must be distinct")
        self.source = source

    @property
    def f_range(self):
        return float(self.f[0]), float(self.f[-1])

    def covers(self, f_lo, f_hi, rtol=1e-9):
        lo, hi = self.f_range
        return f_lo >= lo * (1 - rtol) and f_hi <= hi * (1 + rtol)

    def eps_mu(self, f, resolver):
        f = np.asarray(f, dtype=float)
        lo, hi = self.f_range
        if f.size and not self.covers(float(f.min()), float(f.max())):
            raise OutOfRangeError(self.name, float(f.min()), float(f.max()), lo, hi)
        fc = np.clip(f, lo, hi)
        eps = np.interp(fc, self.f, self.eps_re) - 1j * np.interp(fc, self.f, self.eps_loss)
        mu = np.interp(fc, self.f, self.mu_re) - 1j * np.interp(fc, self.f, self.mu_loss)
        return eps, mu

    def to_dict(self):
        d = self._base_dict()
        d.update(f=self.f.tolist(), eps_re=self.eps_re.tolist(), eps_loss=self.eps_loss.tolist(),
                 mu_re=self.mu_re.tolist(), mu_loss=self.mu_loss.tolist(), source=self.source)
        return d


# ---------------------------------------------------------------------------
class MixtureMaterial(Material):
    """Effective-medium mixture of an inclusion (volume fraction phi) in a matrix.

    model: 'maxwell_garnett' (dilute spherical inclusions) or 'bruggeman'
    (symmetric, valid up to and through percolation).  The same rule is
    applied to eps and mu.  Density is the volume-weighted average.
    """

    kind = "mixture"
    MODELS = ("maxwell_garnett", "bruggeman")

    def __init__(self, name, matrix, inclusion, fraction=0.1, model="maxwell_garnett", **kw):
        kw.pop("density", None)
        super().__init__(name, **kw)
        if model not in self.MODELS:
            raise ValueError(f"unknown mixing model {model!r}")
        self.matrix, self.inclusion = matrix, inclusion
        self.fraction = float(fraction)
        self.model = model
        self._busy = False

    def _guard(self):
        if self._busy:
            raise MaterialCycleError(f"material {self.name!r} references itself")

    def eps_mu(self, f, resolver):
        self._guard()
        self._busy = True
        try:
            em_m = resolver(self.matrix).eps_mu(f, resolver)
            em_i = resolver(self.inclusion).eps_mu(f, resolver)
        finally:
            self._busy = False
        phi = self.fraction
        rule = maxwell_garnett if self.model == "maxwell_garnett" else bruggeman
        return rule(em_m[0], em_i[0], phi), rule(em_m[1], em_i[1], phi)

    def get_density(self, resolver):
        self._guard()
        self._busy = True
        try:
            rm = resolver(self.matrix).get_density(resolver)
            ri = resolver(self.inclusion).get_density(resolver)
        finally:
            self._busy = False
        return self.fraction * ri + (1 - self.fraction) * rm

    def params(self):
        return [ParamInfo(("fraction",), "volume fraction", "frac", lower=0.0, upper=1.0)]

    def references(self):
        return {self.matrix, self.inclusion}

    def rename_reference(self, old, new):
        if self.matrix == old:
            self.matrix = new
        if self.inclusion == old:
            self.inclusion = new

    def to_dict(self):
        d = self._base_dict()
        d.pop("density")
        d.update(matrix=self.matrix, inclusion=self.inclusion, fraction=self.fraction, model=self.model)
        return d

    def __deepcopy__(self, memo):
        m = MixtureMaterial(self.name, self.matrix, self.inclusion, self.fraction, self.model,
                            note=self.note)
        return m


def maxwell_garnett(em, ei, phi):
    em = np.asarray(em, dtype=complex)
    ei = np.asarray(ei, dtype=complex)
    d = ei - em
    return em * (ei + 2 * em + 2 * phi * d) / (ei + 2 * em - phi * d)


def bruggeman(em, ei, phi):
    """Symmetric Bruggeman for spheres: 2e^2 - b e - ei em = 0, passive root."""
    em = np.asarray(em, dtype=complex)
    ei = np.asarray(ei, dtype=complex)
    b = (3 * phi - 1) * ei + (2 - 3 * phi) * em
    disc = np.sqrt(b * b + 8 * ei * em)
    r1 = (b + disc) / 4
    r2 = (b - disc) / 4
    # Physical root: Re > 0 and least gain (Im <= 0 in this convention).
    def score(r):
        return (r.real > 0).astype(float) * 2 + (r.imag <= 1e-12 * np.abs(r)).astype(float)
    s1, s2 = score(r1), score(r2)
    pick1 = (s1 > s2) | ((s1 == s2) & (r1.real >= r2.real))
    return np.where(pick1, r1, r2)


# ---------------------------------------------------------------------------
_KINDS = {c.kind: c for c in (ConstantMaterial, DispersiveMaterial, TabulatedMaterial, MixtureMaterial,
                                PowerLawMaterial)}


def material_from_dict(d) -> Material:
    d = dict(d)
    kind = d.pop("kind")
    try:
        cls = _KINDS[kind]
    except KeyError:
        raise ValueError(f"unknown material kind {kind!r}") from None
    name = d.pop("name")
    return cls(name, **d)
