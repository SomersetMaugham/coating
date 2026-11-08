"""Layer-stack data model.  Layers are ordered front (incident side) -> back."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

import numpy as np


def new_uid() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class SlabLayer:
    """Homogeneous slab of a material with finite thickness [m]."""

    material: str
    thickness: float
    name: str = ""
    uid: str = field(default_factory=new_uid)
    kind: str = "slab"

    def to_dict(self):
        return {"kind": "slab", "uid": self.uid, "name": self.name,
                "material": self.material, "thickness": self.thickness}


RLC_MODELS = ("rlc", "parallel_rlc")
SHEET_MODELS = ("constant",) + RLC_MODELS
ANGLE_KEYS = {"L_TE": "a_l_te", "L_TM": "a_l_tm", "C_TE": "a_c_te", "C_TM": "a_c_tm"}


def parse_angle(d) -> dict:
    """Validated angle coefficients ``{key: float}``.  Raises ValueError for anything else."""
    if not isinstance(d, dict):
        raise ValueError(f"angle must be an object, got {d!r}")
    unknown = sorted(set(d) - set(ANGLE_KEYS))
    if unknown:
        raise ValueError(f"unknown angle coefficient(s) {unknown}; expected {sorted(ANGLE_KEYS)}")
    for k, v in d.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"angle coefficient {k} must be a finite number, got {v!r}")
    return {k: float(v) for k, v in d.items()}


def angle_preset_coeffs(preset, eps_eff=1.0) -> dict:
    """Coefficients of a dense metal mesh or patch array (Luukkonen et al., IEEE TAP 56, 1624 (2008), eqs. 5 and 9)."""
    a = -1.0 / (2.0 * eps_eff)
    return {"mesh": {"L_TM": a}, "patch": {"C_TE": a}, "none": {}}[preset]


def infer_angle_preset(sheet):
    """``(preset, eps_eff)`` from the stored coefficients: the coefficients are the only saved form."""
    d = sheet.angle_dict()
    if d is None:
        return "none", None
    nonzero = {k: v for k, v in d.items() if v != 0}
    if len(nonzero) == 1:
        key, a = next(iter(nonzero.items()))
        if key in ("L_TM", "C_TE") and -0.5 - 1e-9 <= a < 0:
            return ("mesh" if key == "L_TM" else "patch"), max(1.0, -1.0 / (2.0 * a))
    return "custom", None


@dataclass
class SheetLayer:
    """Zero-thickness lossy sheet (a shunt admittance 1/Zs).

    model "constant": Zs = R + jX [Ohm/sq], frequency independent (resistive films).
    model "rlc": series RLC equivalent circuit Zs(f) = R + j(wL - 1/(wC)) with e^{+jwt}
    (inductive reactance > 0); ``C = None`` means no capacitor (inductive grid).  The circuit values
    are normal-incidence lumped values: the same Zs is used for every angle and polarisation, which is
    an approximation for real periodic patterns (valid for sub-wavelength unit cells).
    model "parallel_rlc": 1/Zs = 1/R + j(wC - 1/(wL)), the same kind of lumped values; the sheet opens (Zs = R) at
    resonance, as slot and aperture patterns do.  ``L = 0`` means no inductor and ``C = None`` no capacitor.

    RLC sheets may scale L and C per polarisation: X_pol(theta) = X (1 + a_pol s2), s2 = (kx/k0)^2, the form of the
    analytic results for dense meshes and patch arrays.  All coefficients 0 is the angle-independent model.
    """

    R: float
    X: float = 0.0
    name: str = ""
    uid: str = field(default_factory=new_uid)
    kind: str = "sheet"
    model: str = "constant"
    L: float = 0.0  # H, RLC models only
    C: float | None = None  # F, RLC models only; None = no capacitor
    a_l_te: float = 0.0  # angle coefficients, RLC models only
    a_l_tm: float = 0.0
    a_c_te: float = 0.0
    a_c_tm: float = 0.0

    @property
    def is_rlc(self) -> bool:
        return self.model in RLC_MODELS

    @property
    def has_angle(self) -> bool:
        return self.is_rlc and any(getattr(self, a) != 0 for a in ANGLE_KEYS.values())

    def angle_dict(self):
        """The four coefficients, or None when the sheet has no angle dependence."""
        return {k: getattr(self, a) for k, a in ANGLE_KEYS.items()} if self.has_angle else None

    def set_angle(self, coeffs):
        """Replace all four coefficients; keys left out become 0."""
        for k, a in ANGLE_KEYS.items():
            setattr(self, a, float(coeffs.get(k, 0.0)))

    def angle_scales(self, pol, s2):
        """Factors on L and C for polarisation ``pol`` at ``s2 = (kx/k0)^2``."""
        a_l, a_c = (self.a_l_te, self.a_c_te) if pol == "TE" else (self.a_l_tm, self.a_c_tm)
        return 1.0 + a_l * s2, 1.0 + a_c * s2

    @property
    def impedance(self) -> complex:
        """Constant-model impedance (kept for callers that predate the RLC model)."""
        return complex(self.R, self.X)

    def impedance_at(self, f, scale_r=1.0, scale_l=1.0, scale_c=1.0):
        """Sheet impedance at frequencies ``f`` [Hz] (array of the same shape, complex)."""
        f = np.asarray(f, dtype=float)
        if not self.is_rlc:
            return np.full(f.shape, complex(self.R, self.X))
        w = 2.0 * np.pi * f
        if self.model == "parallel_rlc":
            r = self.R * scale_r
            b = np.zeros(f.shape)  # susceptance; r / (1 + j r b) keeps Zs == R exactly when there is no L or C
            if self.L > 0:
                b = b - 1.0 / (w * self.L * scale_l)
            if self.C is not None:
                b = b + w * self.C * scale_c
            return r / (1.0 + 1j * r * b)
        x = w * (self.L * scale_l)
        if self.C is not None:
            x = x - 1.0 / (w * self.C * scale_c)
        return self.R * scale_r + 1j * x

    def resonance(self):
        """Resonance f0 [Hz], series or parallel, or None (no capacitor or no inductance)."""
        if not self.is_rlc or self.C is None or self.L <= 0:
            return None
        return 1.0 / (2.0 * np.pi * np.sqrt(self.L * self.C))

    def has_param(self, attr) -> bool:
        if attr == "R":
            return True
        if attr == "X":
            return not self.is_rlc
        if attr == "L":
            return self.model == "rlc" or (self.model == "parallel_rlc" and self.L > 0)
        if attr == "C":
            return self.is_rlc and self.C is not None
        return False

    def to_dict(self):
        d = {"kind": "sheet", "uid": self.uid, "name": self.name, "R": self.R, "X": self.X}
        if self.model != "constant":
            d.update(model=self.model, L=self.L, C=self.C)
            if self.has_angle:
                d["angle"] = self.angle_dict()
        return d


def layer_from_dict(d):
    if d["kind"] == "slab":
        return SlabLayer(material=d["material"], thickness=float(d["thickness"]),
                         name=d.get("name", ""), uid=d.get("uid") or new_uid())
    if d["kind"] == "sheet":
        model = d.get("model", "constant")
        if model not in SHEET_MODELS:
            raise ValueError(f"unknown sheet model: {model!r}")
        c = d.get("C")
        sheet = SheetLayer(R=float(d["R"]), X=float(d.get("X", 0.0)),
                           name=d.get("name", ""), uid=d.get("uid") or new_uid(), model=model,
                           L=float(d.get("L", 0.0)), C=None if c is None else float(c))
        if d.get("angle") is not None:
            sheet.set_angle(parse_angle(d["angle"]))
        return sheet
    raise ValueError(f"unknown layer kind: {d['kind']!r}")


@dataclass
class Backing:
    """'pec' (perfect electric conductor) or 'halfspace' (semi-infinite medium)."""

    kind: str = "pec"
    material: str | None = None

    def to_dict(self):
        return {"kind": self.kind, "material": self.material}

    @classmethod
    def from_dict(cls, d):
        return cls(kind=d.get("kind", "pec"), material=d.get("material"))


@dataclass
class Structure:
    layers: list = field(default_factory=list)
    incident: str = "Air"
    backing: Backing = field(default_factory=Backing)

    def layer_by_uid(self, uid):
        for layer in self.layers:
            if layer.uid == uid:
                return layer
        raise KeyError(uid)

    def index_of(self, uid) -> int:
        for i, layer in enumerate(self.layers):
            if layer.uid == uid:
                return i
        raise KeyError(uid)

    def total_thickness(self, perturb=None) -> float:
        total = 0.0
        for layer in self.layers:
            if isinstance(layer, SlabLayer):
                fac = (perturb or {}).get(layer.uid, {}).get("thickness", 1.0)
                total += layer.thickness * fac
        return total

    def referenced_materials(self) -> set:
        names = {self.incident}
        for layer in self.layers:
            if isinstance(layer, SlabLayer):
                names.add(layer.material)
        if self.backing.kind == "halfspace" and self.backing.material:
            names.add(self.backing.material)
        return names

    def to_dict(self):
        return {"incident": self.incident,
                "layers": [layer.to_dict() for layer in self.layers],
                "backing": self.backing.to_dict()}

    @classmethod
    def from_dict(cls, d):
        return cls(layers=[layer_from_dict(x) for x in d.get("layers", [])],
                   incident=d.get("incident", "Air"),
                   backing=Backing.from_dict(d.get("backing", {})))
