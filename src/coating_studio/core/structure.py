"""Layer-stack data model.  Layers are ordered front (incident side) -> back."""

from __future__ import annotations

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


SHEET_MODELS = ("constant", "rlc")


@dataclass
class SheetLayer:
    """Zero-thickness lossy sheet (a shunt admittance 1/Zs).

    model "constant": Zs = R + jX [Ohm/sq], frequency independent (resistive films).
    model "rlc": series RLC equivalent circuit Zs(f) = R + j(wL - 1/(wC)) with e^{+jwt}
    (inductive reactance > 0); ``C = None`` means no capacitor (inductive grid).  The circuit values
    are normal-incidence lumped values: the same Zs is used for every angle and polarisation, which is
    an approximation for real periodic patterns (valid for sub-wavelength unit cells).
    """

    R: float
    X: float = 0.0
    name: str = ""
    uid: str = field(default_factory=new_uid)
    kind: str = "sheet"
    model: str = "constant"
    L: float = 0.0  # H, rlc only
    C: float | None = None  # F, rlc only; None = no capacitor

    @property
    def impedance(self) -> complex:
        """Constant-model impedance (kept for callers that predate the RLC model)."""
        return complex(self.R, self.X)

    def impedance_at(self, f, scale_r=1.0, scale_l=1.0, scale_c=1.0):
        """Sheet impedance at frequencies ``f`` [Hz] (array of the same shape, complex)."""
        f = np.asarray(f, dtype=float)
        if self.model != "rlc":
            return np.full(f.shape, complex(self.R, self.X))
        w = 2.0 * np.pi * f
        x = w * (self.L * scale_l)
        if self.C is not None:
            x = x - 1.0 / (w * self.C * scale_c)
        return self.R * scale_r + 1j * x

    def resonance(self):
        """Series resonance f0 [Hz], or None (no capacitor or no inductance)."""
        if self.model != "rlc" or self.C is None or self.L <= 0:
            return None
        return 1.0 / (2.0 * np.pi * np.sqrt(self.L * self.C))

    def has_param(self, attr) -> bool:
        if attr == "R":
            return True
        if attr == "X":
            return self.model != "rlc"
        if attr == "L":
            return self.model == "rlc"
        if attr == "C":
            return self.model == "rlc" and self.C is not None
        return False

    def to_dict(self):
        d = {"kind": "sheet", "uid": self.uid, "name": self.name, "R": self.R, "X": self.X}
        if self.model != "constant":
            d.update(model=self.model, L=self.L, C=self.C)
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
        return SheetLayer(R=float(d["R"]), X=float(d.get("X", 0.0)),
                          name=d.get("name", ""), uid=d.get("uid") or new_uid(), model=model,
                          L=float(d.get("L", 0.0)), C=None if c is None else float(c))
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
