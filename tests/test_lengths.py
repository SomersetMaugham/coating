"""Thickness display unit (mm / µm / nm): conversions, storage, CLI spec, report (no Qt)."""
import json

import pytest

from coating_studio import lengths
from coating_studio.core.units import DISPLAY_SCALE, LENGTH_UNITS, from_length, to_length
from coating_studio.examples import EXAMPLES
from coating_studio.project import SCHEMA_VERSION, Project


def test_conversions_and_texts():
    for unit in LENGTH_UNITS:
        assert from_length(to_length(1.7e-3, unit), unit) == pytest.approx(1.7e-3, rel=1e-15)
    assert to_length(99.64e-9, "nm") == pytest.approx(99.64)
    assert lengths.fmt_length(99.64e-9, "nm") == "99.64 nm"
    assert lengths.fmt_length(1.7e-3, "mm") == "1.7 mm"
    assert lengths.fmt_length(2.5e-6, "um") == "2.5 µm"
    with pytest.raises(ValueError):
        to_length(1.0, "m")


def test_display_unit_maps_only_thickness_parameters():
    p = EXAMPLES["salisbury"][1]()
    p.sweep.length_unit = "nm"
    assert lengths.display_unit(p, "mm") == "nm" and lengths.display_unit(p, "ohm") == "ohm"
    assert lengths.to_display_unit(100e-9, p, "mm") == pytest.approx(100)
    assert lengths.from_display_unit(100, p, "mm") == pytest.approx(100e-9)
    assert lengths.to_display_unit(5e-9, p, "nH") == pytest.approx(5)  # other units: core.units scale
    # the CLI's unit list is unchanged: only the GUI shows thicknesses in µm / nm
    assert "nm" not in DISPLAY_SCALE and "um" not in DISPLAY_SCALE


def test_project_keeps_the_unit_without_a_schema_bump():
    p = EXAMPLES["salisbury"][1]()
    assert p.sweep.length_unit == "mm"
    p.sweep.length_unit = "um"
    d = json.loads(json.dumps(p.to_dict()))
    assert d["schema"] == SCHEMA_VERSION == 6
    assert Project.from_dict(d).sweep.length_unit == "um"
    assert p.sweep.key() == EXAMPLES["salisbury"][1]().sweep.key()
    d["sweep"]["length_unit"] = "inch"
    assert Project.from_dict(d).sweep.length_unit == "mm"
    d["sweep"].pop("length_unit")
    assert Project.from_dict(d).sweep.length_unit == "mm"


def test_cli_spec_round_trips_the_unit_and_keeps_mm_numbers():
    from coating_studio.cli.output import CliError
    from coating_studio.cli.spec import project_to_spec, spec_to_project

    p = EXAMPLES["dallenbach"][1]()  # one slab layer
    p.sweep.length_unit = "nm"
    spec = project_to_spec(p)
    assert spec["sweep"]["length_unit"] == "nm"
    assert spec["layers"][0]["thickness_mm"] == pytest.approx(p.structure.layers[0].thickness * 1e3)
    assert spec_to_project(spec)[0].sweep.length_unit == "nm"
    spec["sweep"]["length_unit"] = "pm"
    with pytest.raises(CliError):
        spec_to_project(spec)
    spec["sweep"]["length_unit"] = "nm"
    spec["layers"][0]["thickness_nm"] = 100  # a wrong-unit key is named, not reported as a missing thickness_mm
    spec["layers"][0].pop("thickness_mm")
    with pytest.raises(CliError, match="unsupported unit"):
        spec_to_project(spec)


def test_report_shows_thicknesses_in_the_unit():
    from coating_studio.report import build_report

    p = EXAMPLES["dallenbach"][1]()
    p.sweep.length_unit = "um"
    html = build_report(p)
    assert lengths.fmt_length(p.structure.layers[0].thickness, "um") in html
    assert lengths.fmt_length(p.structure.total_thickness(), "um") in html
