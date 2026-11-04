"""Project document: materials + layer stack + analysis / optimisation settings.

Saved as ``.coat`` (UTF-8 JSON with a schema version).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from coating_studio import __version__
from coating_studio.core.structure import Backing, SheetLayer, SlabLayer, Structure
from coating_studio.materials.library import builtin_materials
from coating_studio.materials.models import ConstantMaterial, Material, material_from_dict

SCHEMA_VERSION = 1
FILE_EXTENSION = ".coat"


class ProjectError(ValueError):
    pass


@dataclass
class SweepSettings:
    f_min: float = 2e9  # Hz
    f_max: float = 18e9
    n_f: int = 401
    log_f: bool = False
    angle: float = 0.0  # deg, for frequency plots
    angle_min: float = 0.0
    angle_max: float = 80.0
    n_angle: int = 81
    f_at: float = 10e9  # Hz, for angle plots
    map_n_f: int = 161
    map_n_angle: int = 61


@dataclass
class ContinuousVariable:
    """A numeric parameter to optimise.  path: ('layer', uid, attr) or ('material', name, *key)."""

    path: tuple
    lower: float
    upper: float

    def to_dict(self):
        return {"path": list(self.path), "lower": self.lower, "upper": self.upper}

    @classmethod
    def from_dict(cls, d):
        return cls(tuple(d["path"]), float(d["lower"]), float(d["upper"]))


@dataclass
class MaterialChoice:
    """Discrete variable: the material of slab layer ``uid`` is chosen from ``candidates``."""

    uid: str
    candidates: list

    def to_dict(self):
        return {"uid": self.uid, "candidates": list(self.candidates)}

    @classmethod
    def from_dict(cls, d):
        return cls(d["uid"], list(d["candidates"]))


@dataclass
class OptimizationSettings:
    f_min: float = 8e9
    f_max: float = 12e9
    n_f: int = 41
    angle_min: float = 0.0
    angle_max: float = 0.0
    n_angle: int = 1
    pols: list = field(default_factory=lambda: ["TE", "TM"])
    # weights of the normalised objective terms
    w_worst: float = 1.0
    w_mean: float = 0.0
    w_thickness: float = 0.0
    w_mass: float = 0.0
    # reference values used for normalisation
    rl_ref_db: float = -20.0
    thickness_ref: float = 5e-3  # m
    mass_ref: float = 5.0  # kg/m^2
    thickness_max: float | None = None  # m, hard limit (penalty)
    # algorithm
    maxiter: int = 150
    popsize: int = 15
    seed: int | None = None
    polish: bool = True
    variables: list = field(default_factory=list)
    choices: list = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        d["variables"] = [v.to_dict() for v in self.variables]
        d["choices"] = [c.to_dict() for c in self.choices]
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        variables = [ContinuousVariable.from_dict(v) for v in d.pop("variables", [])]
        choices = [MaterialChoice.from_dict(c) for c in d.pop("choices", [])]
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(variables=variables, choices=choices, **known)


@dataclass
class ToleranceSettings:
    n_samples: int = 200
    distribution: str = "normal"  # "normal": value is 1 sigma; "uniform": value is +/- half-width
    thickness: float = 0.05  # relative
    eps: float = 0.05
    mu: float = 0.05
    sheet: float = 0.05
    per_layer: dict = field(default_factory=dict)  # uid -> {"thickness","eps","mu","sheet"}
    target_db: float = -10.0
    angle: float = 0.0
    pol: str = "avg"
    lower_pct: float = 5.0
    upper_pct: float = 95.0
    seed: int | None = 1

    def tolerance_for(self, uid, key):
        return self.per_layer.get(uid, {}).get(key, getattr(self, key))

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class Project:
    def __init__(self, name="Untitled", materials=None, structure=None, sweep=None,
                 optimization=None, tolerance=None, notes=""):
        self.name = name
        self.materials: dict[str, Material] = {}
        for m in (materials if materials is not None else builtin_materials()):
            self.materials[m.name] = m
        if "Air" not in self.materials:
            self.materials = {"Air": ConstantMaterial("Air", 1.0, 0.0, density=1.2), **self.materials}
        self.structure = structure or Structure()
        self.sweep = sweep or SweepSettings()
        self.optimization = optimization or OptimizationSettings()
        self.tolerance = tolerance or ToleranceSettings()
        self.notes = notes

    # -- materials ---------------------------------------------------------
    def resolver(self, name):
        try:
            return self.materials[name]
        except KeyError:
            raise KeyError(name) from None

    def material_users(self, name) -> list[str]:
        users = []
        if self.structure.incident == name:
            users.append("incident")
        for i, ly in enumerate(self.structure.layers):
            if isinstance(ly, SlabLayer) and ly.material == name:
                users.append(f"layer {i + 1}")
        b = self.structure.backing
        if b.kind == "halfspace" and b.material == name:
            users.append("backing")
        for m in self.materials.values():
            if m.name != name and name in m.references():
                users.append(f"material {m.name}")
        for c in self.optimization.choices:
            if name in c.candidates:
                users.append("optimisation candidates")
                break
        return users

    def unique_material_name(self, base):
        if base not in self.materials:
            return base
        n = 2
        while f"{base} ({n})" in self.materials:
            n += 1
        return f"{base} ({n})"

    def add_material(self, mat: Material):
        if mat.name in self.materials:
            raise ProjectError(f"material {mat.name!r} already exists")
        self.materials[mat.name] = mat

    def remove_material(self, name):
        users = self.material_users(name)
        if users:
            raise ProjectError(f"material {name!r} is in use: {', '.join(users)}")
        del self.materials[name]

    def rename_material(self, old, new):
        if old == new:
            return
        if not new.strip():
            raise ProjectError("material name must not be empty")
        if new in self.materials:
            raise ProjectError(f"material {new!r} already exists")
        items = list(self.materials.items())
        self.materials = {}
        for k, m in items:
            if k == old:
                m.name = new
                k = new
            self.materials[k] = m
        for m in self.materials.values():
            m.rename_reference(old, new)
        s = self.structure
        if s.incident == old:
            s.incident = new
        for ly in s.layers:
            if isinstance(ly, SlabLayer) and ly.material == old:
                ly.material = new
        if s.backing.material == old:
            s.backing.material = new
        for v in self.optimization.variables:
            if v.path[0] == "material" and v.path[1] == old:
                v.path = ("material", new) + tuple(v.path[2:])
        for c in self.optimization.choices:
            c.candidates = [new if x == old else x for x in c.candidates]

    def replace_material(self, name, mat: Material):
        """Replace material ``name`` with ``mat`` (which may carry a new name)."""
        if mat.name != name:
            self.rename_material(name, mat.name)
        self.materials[mat.name] = mat

    # -- layers ------------------------------------------------------------
    def remove_layer(self, uid):
        idx = self.structure.index_of(uid)
        del self.structure.layers[idx]
        self.optimization.variables = [v for v in self.optimization.variables
                                       if not (v.path[0] == "layer" and v.path[1] == uid)]
        self.optimization.choices = [c for c in self.optimization.choices if c.uid != uid]
        self.tolerance.per_layer.pop(uid, None)

    def areal_mass(self, perturb=None) -> float:
        total = 0.0
        for ly in self.structure.layers:
            if isinstance(ly, SlabLayer):
                fac = (perturb or {}).get(ly.uid, {}).get("thickness", 1.0)
                total += ly.thickness * fac * self.materials[ly.material].get_density(self.resolver)
        return total

    # -- validation --------------------------------------------------------
    def validate(self) -> list[str]:
        problems = []
        for name in self.structure.referenced_materials():
            if name not in self.materials:
                problems.append(f"unknown material {name!r}")
        for m in self.materials.values():
            for ref in m.references():
                if ref not in self.materials:
                    problems.append(f"material {m.name!r} references unknown {ref!r}")
        return problems

    # -- serialisation -----------------------------------------------------
    def to_dict(self):
        return {
            "app": "Coating Studio",
            "app_version": __version__,
            "schema": SCHEMA_VERSION,
            "name": self.name,
            "notes": self.notes,
            "materials": [m.to_dict() for m in self.materials.values()],
            "structure": self.structure.to_dict(),
            "sweep": asdict(self.sweep),
            "optimization": self.optimization.to_dict(),
            "tolerance": self.tolerance.to_dict(),
        }

    def model_state(self):
        """The part of the document covered by undo/redo: materials and the layer stack."""
        return {"materials": [m.to_dict() for m in self.materials.values()],
                "structure": self.structure.to_dict(),
                "variables": [v.to_dict() for v in self.optimization.variables],
                "choices": [c.to_dict() for c in self.optimization.choices],
                "per_layer_tol": json.loads(json.dumps(self.tolerance.per_layer))}

    def restore_model_state(self, state):
        self.materials = {}
        for d in state["materials"]:
            m = material_from_dict(d)
            self.materials[m.name] = m
        self.structure = Structure.from_dict(state["structure"])
        self.optimization.variables = [ContinuousVariable.from_dict(v) for v in state["variables"]]
        self.optimization.choices = [MaterialChoice.from_dict(c) for c in state["choices"]]
        self.tolerance.per_layer = json.loads(json.dumps(state["per_layer_tol"]))

    @classmethod
    def from_dict(cls, d):
        schema = d.get("schema", 1)
        if schema > SCHEMA_VERSION:
            raise ProjectError(f"file schema {schema} is newer than supported ({SCHEMA_VERSION})")
        mats = [material_from_dict(m) for m in d.get("materials", [])]
        sweep = SweepSettings(**{k: v for k, v in d.get("sweep", {}).items()
                                 if k in SweepSettings.__dataclass_fields__})
        return cls(name=d.get("name", "Untitled"), materials=mats,
                   structure=Structure.from_dict(d.get("structure", {})),
                   sweep=sweep,
                   optimization=OptimizationSettings.from_dict(d.get("optimization", {})),
                   tolerance=ToleranceSettings.from_dict(d.get("tolerance", {})),
                   notes=d.get("notes", ""))

    def save(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except json.JSONDecodeError as e:
            raise ProjectError(f"not a valid project file: {e}") from None
        if data.get("app") != "Coating Studio":
            raise ProjectError("not a Coating Studio project file")
        return cls.from_dict(data)

    def copy(self):
        return Project.from_dict(json.loads(json.dumps(self.to_dict())))


# ---------------------------------------------------------------------------
# Parameter addressing (shared by the optimiser, tolerance analysis and the GUI)

def get_param(project: Project, path):
    path = tuple(path)
    if path[0] == "layer":
        return float(getattr(project.structure.layer_by_uid(path[1]), path[2]))
    if path[0] == "material":
        return float(project.materials[path[1]].get(tuple(path[2:])))
    raise KeyError(path)


def set_param(project: Project, path, value):
    path = tuple(path)
    if path[0] == "layer":
        setattr(project.structure.layer_by_uid(path[1]), path[2], float(value))
    elif path[0] == "material":
        project.materials[path[1]].set(tuple(path[2:]), value)
    else:
        raise KeyError(path)


def param_unit(project: Project, path) -> str:
    """Display-unit id of a parameter: 'mm', 'ohm', 'GHz', 'S/m', 'frac' or ''."""
    path = tuple(path)
    if path[0] == "layer":
        return {"thickness": "mm", "R": "ohm", "X": "ohm"}[path[2]]
    mat = project.materials[path[1]]
    for p in mat.params():
        if p.key == tuple(path[2:]):
            return p.unit
    return ""


def available_params(project: Project):
    """All optimisable continuous parameters: list of (path, english_label, unit)."""
    out = []
    for i, ly in enumerate(project.structure.layers):
        tag = f"L{i + 1} {ly.name}".strip()
        if isinstance(ly, SlabLayer):
            out.append((("layer", ly.uid, "thickness"), f"{tag}: thickness", "mm"))
        elif isinstance(ly, SheetLayer):
            out.append((("layer", ly.uid, "R"), f"{tag}: R", "ohm"))
            out.append((("layer", ly.uid, "X"), f"{tag}: X", "ohm"))
    used = project.structure.referenced_materials()
    for c in project.optimization.choices:
        used |= set(c.candidates)
    expanded = set()
    stack = list(used)
    while stack:
        n = stack.pop()
        if n in expanded or n not in project.materials:
            continue
        expanded.add(n)
        stack.extend(project.materials[n].references())
    for name, mat in project.materials.items():
        if name not in expanded or name == project.structure.incident:
            continue
        for p in mat.params():
            out.append((("material", name) + p.key, f"{name}: {p.label}", p.unit))
    return out


def describe_path(project: Project, path) -> str:
    path = tuple(path)
    for p, label, _ in available_params(project):
        if p == path:
            return label
    return " / ".join(str(x) for x in path)


def new_project_with_example_stack(name="Untitled"):
    p = Project(name=name)
    p.structure = Structure(layers=[SlabLayer("Carbonyl iron / epoxy", 1.7e-3, name="Absorber")],
                            backing=Backing("pec"))
    return p
