import numpy as np
import pytest

from coating_studio.core import ETA0, Backing, SheetLayer, SlabLayer, Structure
from coating_studio.core.constants import C0
from coating_studio.examples import EXAMPLES
from coating_studio.optimize import OptimizationError, apply_result, evaluate_terms, optimize
from coating_studio.project import (
    ContinuousVariable, MaterialChoice, OptimizationSettings, Project,
)
from coating_studio.tolerance import run_tolerance


def test_rediscovers_salisbury_solution():
    p = Project()
    sheet, spacer = SheetLayer(150.0), SlabLayer("Air", 3e-3)
    p.structure = Structure(layers=[sheet, spacer], backing=Backing("pec"))
    p.optimization = OptimizationSettings(
        f_min=10e9, f_max=10e9, n_f=1, pols=["TE"], maxiter=80, seed=3,
        variables=[ContinuousVariable(("layer", sheet.uid, "R"), 50.0, 2000.0),
                   ContinuousVariable(("layer", spacer.uid, "thickness"), 1e-3, 12e-3)])
    res = optimize(p)
    assert res.terms.worst_db < -40
    assert res.values[("layer", sheet.uid, "R")] == pytest.approx(ETA0, rel=0.02)
    assert res.values[("layer", spacer.uid, "thickness")] == pytest.approx(C0 / 10e9 / 4, rel=0.02)
    apply_result(p, res)
    assert evaluate_terms(p).worst_db < -40


def test_material_choice_enumeration_picks_best():
    p = Project()
    ly = SlabLayer("PTFE", 2e-3)
    p.structure = Structure(layers=[ly], backing=Backing("pec"))
    p.optimization = OptimizationSettings(
        f_min=8e9, f_max=12e9, n_f=11, maxiter=40, seed=1, polish=False,
        variables=[ContinuousVariable(("layer", ly.uid, "thickness"), 0.5e-3, 5e-3)],
        choices=[MaterialChoice(ly.uid, ["PTFE", "Carbonyl iron / epoxy", "PMI foam"])])
    res = optimize(p)
    assert res.choices[ly.uid] == "Carbonyl iron / epoxy"
    assert res.terms.worst_db < -8


def test_stop_request_returns_partial_result():
    p = EXAMPLES["jaumann2"][1]()
    p.optimization.maxiter = 500
    calls = []

    def progress(info):
        calls.append(info)
        return len(calls) >= 3

    res = optimize(p, progress=progress, throttle_s=0.0)
    assert res.stopped and res.terms is not None


def test_thickness_limit_penalty():
    p = EXAMPLES["dallenbach"][1]()
    s = p.optimization
    s.thickness_max = 1.0e-3
    s.maxiter = 40
    s.seed = 2
    res = optimize(p)
    assert res.terms.thickness <= 1.0e-3 * 1.0001


def test_validation_errors():
    p = Project()
    with pytest.raises(OptimizationError):
        optimize(p)


def test_tolerance_zero_spread_matches_nominal():
    p = EXAMPLES["salisbury"][1]()
    p.tolerance.thickness = p.tolerance.eps = p.tolerance.mu = p.tolerance.sheet = 0.0
    p.tolerance.n_samples = 5
    f = np.linspace(8e9, 12e9, 21)
    r = run_tolerance(p, f, band=(9e9, 11e9))
    np.testing.assert_allclose(r.median_db, r.nominal_db)
    assert r.n_samples == 5


def test_tolerance_spread_and_yield():
    p = EXAMPLES["salisbury"][1]()
    p.tolerance.n_samples = 100
    p.tolerance.target_db = -15
    f = np.linspace(8e9, 12e9, 41)
    r = run_tolerance(p, f, band=(9.5e9, 10.5e9))
    assert np.all(r.lower_db <= r.median_db + 1e-9) and np.all(r.median_db <= r.upper_db + 1e-9)
    assert 0.0 <= r.yield_fraction <= 1.0
    assert np.ptp(r.worst_db) > 0
