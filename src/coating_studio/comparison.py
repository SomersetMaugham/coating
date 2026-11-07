"""Reference traces for comparing designs: pinned design snapshots and measured curves.

No Qt here (see AGENTS.md); the GUI only draws what this module computes.

* A **design** reference stores a snapshot of a project's model (all materials, incident medium,
  layer stack, backing) and is re-solved under the *current* sweep settings, so a comparison never
  mixes different incidence angles or bands.  Results are cached per sweep key, so editing the live
  design costs nothing for the references.
* A **measured** reference is frozen data (frequency, RL in dB) that cannot be re-solved.

References are saved with the project (``.coat`` schema 5, ``references``): ``to_dict``/``from_dict``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np

from coating_studio.core.solver import solve
from coating_studio.core.structure import Structure
from coating_studio.materials.csvio import CsvFormatError, _abscissa, _blocks, _split_rows
from coating_studio.materials.models import material_from_dict

MAX_REFERENCES = 6
BEFORE_OPTIMISATION = "Before optimisation"  # English source text; the GUI translates it


@dataclass
class ReferenceTrace:
    name: str
    kind: str  # "design" | "measured"
    slot: int = 0  # colour slot 0..MAX_REFERENCES-1, kept when other references are removed
    visible: bool = True
    model: dict | None = None  # design: {"materials": [...], "structure": {...}}
    f_meas: np.ndarray | None = None  # measured: Hz, ascending
    rl_meas_db: np.ndarray | None = None  # measured: 20*log10|Gamma| (negative = good)
    _built: tuple | None = field(default=None, repr=False)
    _cache_key: tuple | None = field(default=None, repr=False)
    _cache: dict = field(default_factory=dict, repr=False)

    # -- design references ---------------------------------------------------------------
    def _objects(self):
        if self._built is None:
            mats = {}
            for d in self.model["materials"]:
                m = material_from_dict(d)
                mats[m.name] = m
            self._built = (Structure.from_dict(self.model["structure"]), mats)
        return self._built

    def results(self, sweep):
        """{"freq": SolveResult | Exception, "angle": SolveResult | Exception} under ``sweep``.

        Each grid is solved independently: a reference whose tabulated data does not cover the
        frequency sweep can still be valid on the angle sweep (and vice versa).
        """
        if self.kind != "design":
            return {}
        key = sweep.key()
        if key != self._cache_key:
            structure, mats = self._objects()
            out = {}
            for grid, f, th in (("freq", sweep.freq_grid(), sweep.angle),
                                ("angle", [sweep.f_at], sweep.angle_grid())):
                try:
                    out[grid] = solve(structure, mats, f, th)
                except Exception as e:  # noqa: BLE001 - reported per grid as a warning in the GUI
                    out[grid] = e
            self._cache_key, self._cache = key, out
        return self._cache

    def same_model(self, project) -> bool:
        return self.kind == "design" and self.model == _model_of(project)

    # -- saving ----------------------------------------------------------------------------
    def to_dict(self):
        d = {"name": self.name, "kind": self.kind, "slot": int(self.slot), "visible": bool(self.visible)}
        if self.kind == "design":
            d["model"] = self.model
        else:
            d["f_hz"] = [float(x) for x in self.f_meas]
            d["rl_db"] = [float(x) for x in self.rl_meas_db]
        return d

    @classmethod
    def from_dict(cls, d):
        kind = d.get("kind")
        common = dict(name=str(d["name"]), kind=kind, slot=int(d.get("slot", 0)), visible=bool(d.get("visible", True)))
        if kind == "design":
            model = d["model"]
            if not isinstance(model, dict) or "materials" not in model or "structure" not in model:
                raise ValueError(f"reference {d['name']!r}: design model needs materials and structure")
            return cls(model=json.loads(json.dumps(model)), **common)
        if kind == "measured":
            f = np.asarray(d["f_hz"], dtype=float)
            rl = np.asarray(d["rl_db"], dtype=float)
            if f.ndim != 1 or f.shape != rl.shape or len(f) < 2:
                raise ValueError(f"reference {d['name']!r}: f_hz and rl_db must be equal-length lists")
            return cls(f_meas=f, rl_meas_db=rl, **common)
        raise ValueError(f"unknown reference kind {kind!r}")


def _model_of(project):
    # All materials, not just the referenced ones: mixtures reference their matrix and inclusion
    # by name, and Structure.referenced_materials() does not follow those references.
    return json.loads(json.dumps({"materials": [m.to_dict() for m in project.materials.values()],
                                  "structure": project.structure.to_dict()}))


def snapshot_design(project, name, slot=0) -> ReferenceTrace:
    """Pin the current design.  The snapshot is a deep copy: later edits do not affect it."""
    return ReferenceTrace(name=name, kind="design", slot=slot, model=_model_of(project))


def free_slot(references) -> int | None:
    used = {r.slot for r in references}
    return next((i for i in range(MAX_REFERENCES) if i not in used), None)


# -- measured curves -------------------------------------------------------------------------
def parse_measured_text(text):
    """Return (f [Hz] ascending, rl_db internal convention, positive_input: bool).

    Layout: a frequency/wavelength column (units as for material CSVs) and one RL column in dB, or
    the app's own Frequency-tab export (``f [GHz], RL TE, RL TM, RL avg``; the average is used).
    Sign: a file with median > 0 and min >= -0.5 dB is read as positive return loss (-20·log10|Γ|,
    tolerating small calibration ripple below 0 dB) and negated; a file with values both below -1 dB
    and above +1 dB is rejected as ambiguous.
    """
    blocks = _blocks(_split_rows(text))
    if len(blocks) != 1:
        raise CsvFormatError("expected a single table")
    header, arr = blocks[0]
    if arr.shape[1] < 2:
        raise CsvFormatError("need a frequency column and an RL column")
    col = 1
    if header and arr.shape[1] >= 2:
        names = [h.strip().lower() for h in header]
        for i, h in enumerate(names):
            if i and "avg" in h:
                col = i
                break
        else:
            if arr.shape[1] != 2:
                raise CsvFormatError(f"expected 2 columns (frequency, RL), found {arr.shape[1]}")
    elif arr.shape[1] != 2:
        raise CsvFormatError(f"expected 2 columns (frequency, RL), found {arr.shape[1]}")
    to_f = _abscissa(header[0]) if header else (lambda v: v * 1e9)
    f = np.asarray(to_f(arr[:, 0]), dtype=float)
    rl = np.asarray(arr[:, col], dtype=float)
    ok = np.isfinite(f) & np.isfinite(rl)
    f, rl = f[ok], rl[ok]
    if len(f) < 2:
        raise CsvFormatError("need at least two data rows")
    if np.any(f <= 0):
        raise CsvFormatError("frequencies must be positive")
    order = np.argsort(f)
    f, rl = f[order], rl[order]
    if len(np.unique(f)) != len(f):
        raise CsvFormatError("duplicate frequencies")
    if np.min(rl) < -1.0 and np.max(rl) > 1.0:
        raise CsvFormatError("RL values are both below -1 dB and above +1 dB: cannot tell the sign "
                             "convention")
    positive = bool(np.median(rl) > 0 and np.min(rl) >= -0.5)
    return f, (-rl if positive else rl), positive


def load_measured(path, name=None) -> tuple[ReferenceTrace, bool]:
    """A measured curve from a CSV (see ``parse_measured_text``) or a Touchstone one-port file (.s1p)."""
    import os

    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    if path.lower().endswith(".s1p"):
        from coating_studio.touchstone import TouchstoneError, parse_s1p
        try:
            f, s11 = parse_s1p(text)
        except TouchstoneError as e:
            raise CsvFormatError(str(e)) from None
        rl, positive = 20 * np.log10(np.maximum(np.abs(s11), 1e-15)), False
    else:
        f, rl, positive = parse_measured_text(text)
    name = name or os.path.splitext(os.path.basename(path))[0]
    return ReferenceTrace(name=name, kind="measured", f_meas=f, rl_meas_db=rl), positive
