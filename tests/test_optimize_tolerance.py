import math

import numpy as np
import pytest

from coating_studio.core import ETA0, Backing, SheetLayer, SlabLayer, Structure, solve
from coating_studio.core.constants import C0
from coating_studio.examples import EXAMPLES
from coating_studio.optimize import OptimizationError, apply_result, evaluate_terms, optimize
from coating_studio.optimize.optimizer import validate_settings
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


# ---------------------------------------------------------------- multi-target optimisation
def _old_objective(p, s):
    """The schema-1 objective, written out independently."""
    from coating_studio.core import solve as _solve
    f = np.linspace(s.f_min, s.f_max, s.n_f) if s.f_max > s.f_min else np.array([s.f_min])
    th = np.linspace(s.angle_min, s.angle_max, s.n_angle) if s.n_angle > 1 else np.array([s.angle_min])
    res = _solve(p.structure, p.materials, f, th, pols=tuple(s.pols))
    r = np.stack([res.pol[k].R for k in s.pols])
    db = 10 * np.log10(np.maximum(r, 1e-30))
    j = s.w_worst * float(db.max()) / abs(s.rl_ref_db) + s.w_mean * float(r.mean()) / 10 ** (s.rl_ref_db / 10)
    return j + s.w_thickness * p.structure.total_thickness() / s.thickness_ref + s.w_mass * p.areal_mass() / s.mass_ref


def test_single_target_objective_is_bit_identical_to_schema1():
    from coating_studio.optimize.optimizer import Evaluator
    for key in ("salisbury", "jaumann2", "dallenbach", "carbon"):
        p = EXAMPLES[key][1]()
        s = p.optimization
        s.w_mean, s.w_thickness, s.w_mass = 0.3, 0.2, 0.1
        s.angle_max, s.n_angle = 40.0, 5
        assert Evaluator(p, s).terms().objective == _old_objective(p, s), key


def test_legacy_settings_migrate_to_one_target():
    from coating_studio.project import OptimizationSettings, SCHEMA_VERSION
    s = OptimizationSettings.from_dict({"f_min": 2e9, "f_max": 4e9, "n_f": 11, "pols": ["TE"], "rl_ref_db": -12})
    assert len(s.targets) == 1 and s.targets[0].goal_db == -12 and s.targets[0].pols == ["TE"]
    d = Project(optimization=s).to_dict()
    assert d["schema"] == SCHEMA_VERSION >= 2 and "f_min" not in d["optimization"]
    assert Project.from_dict(d).optimization == s
    p = EXAMPLES["salisbury"][1]()
    p.optimization = OptimizationSettings.from_dict({"targets": [], "variables": []})
    p.optimization.variables = EXAMPLES["salisbury"][1]().optimization.variables
    with pytest.raises(OptimizationError):  # an explicit empty v2 list is not migrated
        validate_settings(p, p.optimization)


def test_margins_grouping_and_disabled_targets():
    from coating_studio.optimize.optimizer import Evaluator, target_frequencies
    from coating_studio.project import BandTarget
    p = EXAMPLES["jaumann2"][1]()
    s = p.optimization
    s.targets = [BandTarget(8e9, 12e9, 21, 0, 0, 1, ["TE", "TM"], -20.0),
                 BandTarget(8e9, 12e9, 21, 0, 45, 4, ["TE", "TM"], -10.0),  # same f grid: one solve
                 BandTarget(30e9, 40e9, 5, goal_db=-30.0, enabled=False)]
    ev = Evaluator(p, s)
    assert len(ev.groups) == 1
    t = ev.terms()
    assert len(t.per_target) == 2  # the disabled target is ignored
    for (worst, margin), tg in zip(t.per_target, s.enabled_targets()):
        f, th = tg.grid()
        res = solve(p.structure, p.materials, f, th)
        want = 10 * np.log10(max(res.pol["TE"].R.max(), res.pol["TM"].R.max()))
        assert worst == pytest.approx(want, abs=1e-9) and margin == pytest.approx(want - tg.goal_db)
    assert t.margin_db == max(m for _, m in t.per_target)
    assert target_frequencies(s).max() <= 12e9  # pre-flight ignores the disabled target
    smooth = ev.terms(smooth=True)
    assert math.isfinite(smooth.objective)


def test_dual_band_salisbury_meets_both_goals():
    from coating_studio.project import BandTarget
    p = EXAMPLES["salisbury"][1]()
    s = p.optimization
    # the spacer is PMI foam; a lambda/4 design at f0 also absorbs at 3*f0
    s.targets = [BandTarget(3.0e9, 3.4e9, 9, goal_db=-15.0), BandTarget(9.0e9, 10.2e9, 13, goal_db=-15.0)]
    s.variables[1].lower, s.variables[1].upper = 5e-3, 40e-3
    s.maxiter, s.seed = 60, 1
    res = optimize(p, s)
    assert res.terms.margin_db <= 0, res.terms.per_target
    assert all(m <= 0 for _, m in res.terms.per_target)


def test_single_frequency_target_and_union_yield_band():
    from coating_studio.project import BandTarget
    f, th = BandTarget(10e9, 10e9, 7).grid()
    assert f.tolist() == [10e9] and th.tolist() == [0.0]
    p = EXAMPLES["salisbury"][1]()
    f = np.linspace(2e9, 18e9, 161)
    # two disjoint bands around the absorption peaks: the gap between them must not count
    p.tolerance.target_db, p.tolerance.n_samples = -10.0, 5
    res = run_tolerance(p, f, band=[(9e9, 11e9), (29e9, 31e9)])
    assert res.yield_fraction == 1.0
    envelope = run_tolerance(p, f, band=(9e9, 18e9))
    assert envelope.yield_fraction == 0.0
