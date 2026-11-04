"""Layer-stack data model.  Layers are ordered front (incident side) -> back."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


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


@dataclass
class SheetLayer:
    """Zero-thickness resistive sheet with complex sheet impedance R + jX [Ohm/sq]."""

    R: float
    X: float = 0.0
    name: str = ""
    uid: str = field(default_factory=new_uid)
    kind: str = "sheet"

    @property
    def impedance(self) -> complex:
        return complex(self.R, self.X)

    def to_dict(self):
        return {"kind": "sheet", "uid": self.uid, "name": self.name, "R": self.R, "X": self.X}


def layer_from_dict(d):
    if d["kind"] == "slab":
        return SlabLayer(material=d["material"], thickness=float(d["thickness"]),
                         name=d.get("name", ""), uid=d.get("uid") or new_uid())
    if d["kind"] == "sheet":
        return SheetLayer(R=float(d["R"]), X=float(d.get("X", 0.0)),
                          name=d.get("name", ""), uid=d.get("uid") or new_uid())
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
