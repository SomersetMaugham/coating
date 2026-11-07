"""Engine helpers shared by the GUI and the CLI (moved out of gui/ so both give the same numbers)."""

import json

import numpy as np
import pytest

from coating_studio.core.structure import Backing, SlabLayer, Structure
from coating_studio.core.units import from_display, si_unit, to_display
from coating_studio.examples import EXAMPLES
from coating_studio.materials.checks import check_material
from coating_studio.materials.models import MixtureMaterial
from coating_studio.optimize import OptimizationError, preflight
from coating_studio.optimize.optimizer import validate_settings
from coating_studio.project import (
    SCHEMA_VERSION, MaterialChoice, NewerSchemaError, OptimizationSettings, Project, ProjectError,
    available_params, get_param,
)
from coating_studio.tolerance import tolerance_frequencies, yield_band, yield_intervals


def test_tolerance_frequencies_match_the_former_gui_grid():
    for log_f in (False, True):
        p = Project()
        p.sweep.log_f = log_f
        sw = p.sweep
        old = (np.geomspace(sw.f_min, sw.f_max, min(sw.n_f, 301)) if sw.log_f
               else np.linspace(sw.f_min, sw.f_max, min(sw.n_f, 301)))
        assert np.array_equal(tolerance_frequencies(p), old)


def test_yield_intervals_follow_targets_or_custom_band():
    p = EXAMPLES["dualband"][1]()
    assert yield_intervals(p) == p.optimization.frequency_intervals()
    p.tolerance.band_min, p.tolerance.band_max = 9e9, 11e9
    assert yield_intervals(p) == [(9e9, 11e9)]
    assert yield_band(p) == (9e9, 11e9)


def test_display_unit_round_trip_and_si_names():
    p = EXAMPLES["cara"][1]()
    for path, _label, unit in available_params(p):
        v = get_param(p, path)
        assert from_display(to_display(v, unit), unit) == pytest.approx(v, rel=1e-12)
    assert si_unit("mm") == "m" and si_unit("nH") == "H" and si_unit("pF") == "F"
    assert si_unit("GHz") == "Hz" and si_unit("g/cm3") == "kg/m3" and si_unit("frac") == "frac"


def test_newer_schema_is_a_project_error_with_details():
    d = Project().to_dict()
    d["schema"] = SCHEMA_VERSION + 1
    with pytest.raises(NewerSchemaError) as e:
        Project.from_dict(d)
    assert isinstance(e.value, ProjectError)
    assert (e.value.schema, e.value.supported) == (SCHEMA_VERSION + 1, SCHEMA_VERSION)


def test_source_schema_is_kept_but_not_saved():
    d = Project().to_dict()
    d["schema"] = 2
    p = Project.from_dict(d)
    assert p.source_schema == 2
    assert p.copy().source_schema == SCHEMA_VERSION
    assert "source_schema" not in json.dumps(p.to_dict())


def test_cyclic_mixture_is_reported_not_raised():
    p = Project()
    p.add_material(MixtureMaterial("A", "Epoxy", "B", 0.2))
    p.add_material(MixtureMaterial("B", "Epoxy", "A", 0.2))
    issues = check_material(p.materials["A"], np.array([10e9]), p.resolver)
    assert [(i.level, i.code) for i in issues] == [("error", "material_cycle")]


def test_choice_on_a_missing_layer_is_an_optimisation_error():
    p = EXAMPLES["dallenbach"][1]()
    p.optimization.choices = [MaterialChoice("no-such-uid", ["Epoxy"])]
    with pytest.raises(OptimizationError, match="no longer exists"):
        validate_settings(p, p.optimization)


def test_preflight_sorts_errors_and_warnings_and_drops_info():
    p = EXAMPLES["salisbury"][1]()
    errors, warnings = preflight(p)
    assert errors == [] and warnings == []  # demo-value notes are informational only
    p.structure.layers[1].material = "Ghost"  # unknown candidates are rejected earlier, by validate_settings
    errors, _ = preflight(p)
    assert [(i.code, i.args) for i in errors] == [("unknown_material", {"n": "Ghost"})]


def test_preflight_raises_on_invalid_settings():
    p = Project()
    p.structure = Structure(layers=[SlabLayer("Epoxy", 1e-3)], backing=Backing("pec"))
    p.optimization = OptimizationSettings()  # no variables
    with pytest.raises(OptimizationError):
        preflight(p)
