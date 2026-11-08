"""Project document: materials + layer stack + analysis / optimisation settings.

Saved as ``.coat`` (UTF-8 JSON with a schema version).
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import asdict, dataclass, field

import numpy as np

from coating_studio import __version__
from coating_studio.comparison import MAX_REFERENCES, ReferenceTrace
from coating_studio.core.structure import Backing, SheetLayer, SlabLayer, Structure
from coating_studio.core.units import DEFAULT_SPECTRAL_UNIT, SPECTRAL_UNITS
from coating_studio.materials.library import builtin_materials
from coating_studio.materials.models import ConstantMaterial, Material, material_from_dict

SCHEMA_VERSION = 6  # 6: per-layer real/loss correlation; 5: real/loss error correlation, saved comparison curves; 4: independent loss tolerances; 3: RLC sheets; 2: optimisation targets; 1: one band
FILE_EXTENSION = ".coat"


class ProjectError(ValueError):
    pass


class NewerSchemaError(ProjectError):
    """The file was written by a newer version (its schema is above SCHEMA_VERSION)."""

    def __init__(self, schema, supported=SCHEMA_VERSION):
        self.schema, self.supported = schema, supported
        super().__init__(f"file schema {schema} is newer than supported ({supported})")


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
    # Display unit of the spectral axis ("GHz", "THz", "um", "nm", "cm-1"; core.units.SPECTRAL_UNITS).  Display
    # only: the sweep stays in Hz, so it is not part of key() and needs no schema bump (older apps show GHz).
    spectral_unit: str = "GHz"

    # Grids shared by the live design and pinned references (one place, so they always match).
    def freq_grid(self, n=None):
        n = self.n_f if n is None else n
        return np.geomspace(self.f_min, self.f_max, n) if self.log_f else np.linspace(self.f_min, self.f_max, n)

    def angle_grid(self, n=None):
        return np.linspace(self.angle_min, self.angle_max, self.n_angle if n is None else n)

    def key(self):
        """Everything the frequency and angle sweeps depend on (cache key for reference solves)."""
        return (self.f_min, self.f_max, self.n_f, self.log_f, self.angle,
                self.f_at, self.angle_min, self.angle_max, self.n_angle)


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
class BandTarget:
    """One row of an optimisation spec mask: reflection loss must reach ``goal_db`` (internal sign,
    20·log10|Γ|, negative = good) over f_min..f_max × angle_min..angle_max for the given polarisations."""

    f_min: float = 8e9
    f_max: float = 12e9
    n_f: int = 41
    angle_min: float = 0.0
    angle_max: float = 0.0
    n_angle: int = 1
    pols: list = field(default_factory=lambda: ["TE", "TM"])
    goal_db: float = -20.0
    enabled: bool = True
    name: str = ""

    def grid(self):
        """(f [Hz], theta [deg]) evaluation grid of this target."""
        f = (np.linspace(self.f_min, self.f_max, max(int(self.n_f), 1)) if self.f_max > self.f_min
             else np.array([float(self.f_min)]))
        if self.n_angle > 1 and self.angle_max > self.angle_min:
            th = np.linspace(self.angle_min, self.angle_max, int(self.n_angle))
        else:
            th = np.array([float(self.angle_min)])
        return f, th

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        d = {k: v for k, v in dict(d).items() if k in cls.__dataclass_fields__}
        if "pols" in d:
            d["pols"] = list(d["pols"])
        return cls(**d)


# Schema-1 single-band fields; still accepted as keyword arguments and properties (first target).
_LEGACY_BAND = ("f_min", "f_max", "n_f", "angle_min", "angle_max", "n_angle", "pols")


@dataclass(init=False)
class OptimizationSettings:
    targets: list = field(default_factory=list)  # [BandTarget]; the objective uses the enabled ones
    # weights of the normalised objective terms
    w_worst: float = 1.0
    w_mean: float = 0.0
    w_thickness: float = 0.0
    w_mass: float = 0.0
    # reference values used for normalisation (rl_ref_db: dB scale against thickness / mass)
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

    def __init__(self, targets=None, **kw):
        legacy = {k: kw.pop(k) for k in _LEGACY_BAND if k in kw}
        for f in dataclasses.fields(self):
            if f.name == "targets":
                continue
            if f.name in kw:
                setattr(self, f.name, kw.pop(f.name))
            elif f.default_factory is not dataclasses.MISSING:
                setattr(self, f.name, f.default_factory())
            else:
                setattr(self, f.name, f.default)
        if kw:
            raise TypeError(f"unexpected optimisation settings: {sorted(kw)}")
        if targets is None:
            if "pols" in legacy:
                legacy["pols"] = list(legacy["pols"])
            # A schema-1 band: its required level is the RL reference, so the objective is unchanged.
            targets = [BandTarget(goal_db=self.rl_ref_db, **legacy)]
        elif legacy:
            raise TypeError("give either targets or the single-band fields, not both")
        self.targets = list(targets)

    def enabled_targets(self):
        return [t for t in self.targets if t.enabled]

    def frequency_intervals(self):
        """[(f_lo, f_hi)] of the enabled targets, in Hz."""
        return [(t.f_min, t.f_max) for t in self.enabled_targets()]

    def to_dict(self):
        d = asdict(self)
        d["variables"] = [v.to_dict() for v in self.variables]
        d["choices"] = [c.to_dict() for c in self.choices]
        d["targets"] = [t.to_dict() for t in self.targets]
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        variables = [ContinuousVariable.from_dict(v) for v in d.pop("variables", [])]
        choices = [MaterialChoice.from_dict(c) for c in d.pop("choices", [])]
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "targets"}
        if "targets" in d:  # schema 2 (an explicit empty list stays empty and fails validation)
            return cls(targets=[BandTarget.from_dict(t) for t in d["targets"]],
                       variables=variables, choices=choices, **known)
        legacy = {k: v for k, v in d.items() if k in _LEGACY_BAND}  # schema 1
        return cls(variables=variables, choices=choices, **known, **legacy)


def _band_property(name):
    def get(self):
        return getattr(self.targets[0], name)

    def set_(self, value):
        if not self.targets:
            self.targets.append(BandTarget(goal_db=self.rl_ref_db))
        setattr(self.targets[0], name, list(value) if name == "pols" else value)

    return property(get, set_, doc=f"Schema-1 compatibility: {name} of the first target.")


for _name in _LEGACY_BAND:
    setattr(OptimizationSettings, _name, _band_property(_name))


@dataclass
class ToleranceSettings:
    n_samples: int = 200
    distribution: str = "normal"  # "normal": value is 1 sigma; "uniform": value is +/- half-width
    thickness: float = 0.05  # relative
    eps: float = 0.05  # eps' (or the whole complex eps while eps_loss is None)
    mu: float = 0.05  # mu' (or the whole complex mu while mu_loss is None)
    sheet: float = 0.05
    # Relative tolerance of the loss parts eps'' / mu'', drawn independently of the real parts, so the
    # loss tangent varies too.  None = the loss follows the real part (one factor on the complex value,
    # tan delta fixed) - the behaviour of schema <= 3 files, which load with None.
    eps_loss: float | None = 0.10
    mu_loss: float | None = 0.10
    # Correlation coefficient rho (-1..1) between the real-part and loss errors of the same layer (eps' with
    # eps'', mu' with mu''); used only where a loss tolerance is set.  0 = independent (schema <= 4).
    loss_correlation: float = 0.0
    # uid -> {"thickness","eps","eps_loss","mu","mu_loss","sheet","loss_correlation"}; a missing key uses the
    # default above.  "loss_correlation" is a coefficient (-1..1, schema 6), the others are relative tolerances.
    per_layer: dict = field(default_factory=dict)
    target_db: float = -10.0
    band_min: float | None = None  # Hz; yield band (None -> whole sweep)
    band_max: float | None = None
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
        kw = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        # Files written before independent loss tolerances existed keep their old (correlated) model.
        kw.setdefault("eps_loss", None)
        kw.setdefault("mu_loss", None)
        # A stored None would stop tolerance_for() from falling back to the default.
        kw["per_layer"] = {uid: {k: v for k, v in vals.items() if v is not None}
                           for uid, vals in kw.get("per_layer", {}).items()}
        return cls(**kw)


def _references_from(items):
    """Saved comparison curves; at most MAX_REFERENCES, colour slots made unique."""
    refs = [ReferenceTrace.from_dict(x) for x in items][:MAX_REFERENCES]
    used = set()
    for r in refs:
        if r.slot in used or not 0 <= r.slot < MAX_REFERENCES:
            r.slot = next(i for i in range(MAX_REFERENCES) if i not in used)
        used.add(r.slot)
    return refs


class Project:
    def __init__(self, name="Untitled", materials=None, structure=None, sweep=None,
                 optimization=None, tolerance=None, notes="", references=None):
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
        # Comparison curves (comparison.ReferenceTrace) saved with the file; not part of undo (like settings).
        self.references: list = list(references or [])
        self.source_schema = SCHEMA_VERSION  # schema of the file this project was read from (not saved)

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

    def used_materials(self, include_candidates=True) -> list[str]:
        """Materials the design uses (incident medium, slabs, backing and optionally the optimisation
        candidates), with mixture constituents expanded; sorted.  Names not in ``materials`` are kept."""
        names = set(self.structure.referenced_materials())
        if include_candidates:
            for c in self.optimization.choices:
                names |= set(c.candidates)
        seen, stack = set(), list(names)
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            if n in self.materials:
                stack.extend(self.materials[n].references())
        return sorted(seen)

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
            "references": [r.to_dict() for r in self.references],
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
            raise NewerSchemaError(schema)
        mats = [material_from_dict(m) for m in d.get("materials", [])]
        sweep = SweepSettings(**{k: v for k, v in d.get("sweep", {}).items()
                                 if k in SweepSettings.__dataclass_fields__})
        if sweep.spectral_unit not in SPECTRAL_UNITS:  # a hand-edited or unknown value: show GHz rather than fail
            sweep.spectral_unit = DEFAULT_SPECTRAL_UNIT
        return cls(name=d.get("name", "Untitled"), materials=mats,
                   structure=Structure.from_dict(d.get("structure", {})),
                   sweep=sweep,
                   optimization=OptimizationSettings.from_dict(d.get("optimization", {})),
                   tolerance=ToleranceSettings.from_dict(d.get("tolerance", {})),
                   notes=d.get("notes", ""),
                   references=_references_from(d.get("references", [])))._with_source_schema(schema)

    def _with_source_schema(self, schema):
        self.source_schema = int(schema)
        return self

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

def _layer_attr(project, path):
    ly = project.structure.layer_by_uid(path[1])
    # A sheet only has the parameters of its model (X: constant; L, C: RLC; C only with a capacitor).
    if isinstance(ly, SheetLayer) and not ly.has_param(path[2]):
        raise KeyError(path)
    return ly


def get_param(project: Project, path):
    path = tuple(path)
    if path[0] == "layer":
        return float(getattr(_layer_attr(project, path), path[2]))
    if path[0] == "material":
        return float(project.materials[path[1]].get(tuple(path[2:])))
    raise KeyError(path)


def set_param(project: Project, path, value):
    path = tuple(path)
    if path[0] == "layer":
        setattr(_layer_attr(project, path), path[2], float(value))
    elif path[0] == "material":
        project.materials[path[1]].set(tuple(path[2:]), value)
    else:
        raise KeyError(path)


def param_unit(project: Project, path) -> str:
    """Display-unit id of a parameter: 'mm', 'ohm', 'nH', 'pF', 'GHz', 'S/m', 'frac' or ''."""
    path = tuple(path)
    if path[0] == "layer":
        return {"thickness": "mm", "R": "ohm", "X": "ohm", "L": "nH", "C": "pF"}[path[2]]
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
            for attr, unit in (("R", "ohm"), ("X", "ohm"), ("L", "nH"), ("C", "pF")):
                if ly.has_param(attr):
                    out.append((("layer", ly.uid, attr), f"{tag}: {attr}", unit))
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
