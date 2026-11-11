"""Warnings for patterned sheets close together (higher Floquet-mode coupling is not modelled)."""

import pytest

from coating_studio import diagnostics
from coating_studio.core import Backing, SheetLayer, SlabLayer, Structure
from coating_studio.core.constants import C0
from coating_studio.limits import SHEET_GAP_RATIO, sheet_proximity_issues
from coating_studio.materials import ConstantMaterial
from coating_studio.project import Project


def _rlc(name):
    return SheetLayer(50.0, name=name, model="rlc", L=5e-9, C=0.05e-12)


def _project(layers):
    p = Project()
    p.add_material(ConstantMaterial("Spacer", 4.0, 0.01))
    p.structure = Structure(layers=layers, backing=Backing("pec"))
    p.sweep.f_min, p.sweep.f_max = 2e9, 18e9
    return p


def test_close_sheets_warn_with_the_electrical_spacing():
    p = _project([_rlc("A"), SlabLayer("Spacer", 0.5e-3), SlabLayer("Spacer", 0.3e-3), _rlc("B"),
                  SlabLayer("Spacer", 3e-3)])
    (iss,) = sheet_proximity_issues(p, 18e9)
    assert (iss.level, iss.code, iss.args["a"], iss.args["b"]) == ("warning", "sheets_close", 1, 4)
    assert iss.args["d_mm"] == pytest.approx(0.8)
    assert iss.args["ratio"] == pytest.approx(0.8e-3 * 2.0 / (C0 / 18e9), rel=1e-6)  # n = sqrt(4) = 2


def test_same_plane_is_an_info_note_and_far_or_uniform_sheets_are_quiet():
    p = _project([_rlc("A"), _rlc("B"), SlabLayer("Spacer", 3e-3)])
    (iss,) = sheet_proximity_issues(p, 18e9)
    assert (iss.level, iss.code) == ("info", "sheets_same_plane")
    lam_in_spacer = C0 / 18e9 / 2.0
    far = _project([_rlc("A"), SlabLayer("Spacer", 1.01 * SHEET_GAP_RATIO * lam_in_spacer), _rlc("B")])
    assert sheet_proximity_issues(far, 18e9) == []
    near = _project([_rlc("A"), SlabLayer("Spacer", 0.99 * SHEET_GAP_RATIO * lam_in_spacer), _rlc("B")])
    assert [i.code for i in sheet_proximity_issues(near, 18e9)] == ["sheets_close"]
    uniform = _project([SheetLayer(377.0), SlabLayer("Spacer", 0.1e-3), SheetLayer(200.0)])
    assert sheet_proximity_issues(uniform, 18e9) == []
    broken = _project([_rlc("A"), SlabLayer("Missing", 0.1e-3), _rlc("B")])
    assert sheet_proximity_issues(broken, 18e9) == []  # the missing material is reported by its own check


def test_reported_by_diagnostics_and_cli_check(tmp_path):
    from coating_studio.cli.commands import cmd_check

    p = _project([_rlc("A"), SlabLayer("Spacer", 0.5e-3), _rlc("B"), SlabLayer("Spacer", 3e-3), _rlc("C")])
    problems, notes = diagnostics.collect(p, [10e9])
    assert any("Pattern sheets 1 and 3" in text for level, text in problems if level == "warning")
    path = tmp_path / "p.coat"
    p.save(path)
    codes = [i["code"] for i in cmd_check(str(path)).result["issues"]]
    assert codes.count("sheets_close") == 1
    same = _project([_rlc("A"), _rlc("B"), SlabLayer("Spacer", 3e-3)])
    _, notes = diagnostics.collect(same, [10e9])
    assert any("same plane" in n for n in notes)
