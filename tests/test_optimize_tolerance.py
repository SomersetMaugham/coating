import dataclasses
import json
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
    p.tolerance.eps_loss = p.tolerance.mu_loss = 0.0
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


# ---------------------------------------------------------------- independent loss tolerances
def _legacy_run(project, f, s, band):
    """The pre-loss-tolerance algorithm, frozen here to prove bit-identical legacy results."""
    from coating_studio.core.structure import SheetLayer as _Sh, SlabLayer as _Sl
    from coating_studio.tolerance import _draw
    rng = np.random.default_rng(s.seed)
    n = int(s.n_samples)
    pols = ("TE", "TM") if s.pol == "avg" else (s.pol,)

    def rl_db(perturb=None):
        res = solve(project.structure, project.materials, f, s.angle, pols=pols, perturb=perturb)
        return 10 * np.log10(np.maximum(res.quantity("R", "avg" if s.pol == "avg" else s.pol)[:, 0], 1e-30))

    factors = {}
    for ly in project.structure.layers:
        if isinstance(ly, _Sl):
            factors[ly.uid] = {k: np.maximum(_draw(rng, s.distribution, s.tolerance_for(ly.uid, k), n), 1e-6)
                               for k in ("thickness", "eps", "mu")}
        elif isinstance(ly, _Sh):
            factors[ly.uid] = {"sheet": np.maximum(_draw(rng, s.distribution, s.tolerance_for(ly.uid, "sheet"), n), 1e-6)}
    arr = np.array([rl_db({u: {k: a[i] for k, a in d.items()} for u, d in factors.items()}) for i in range(n)])
    mask = (f >= band[0]) & (f <= band[1])
    return arr, float(np.mean(arr[:, mask].max(axis=1) <= s.target_db))


def test_legacy_loss_mode_is_bit_identical():
    from coating_studio.project import ToleranceSettings
    p = EXAMPLES["dallenbach"][1]()
    p.tolerance = ToleranceSettings.from_dict({k: v for k, v in p.tolerance.to_dict().items()
                                               if k not in ("eps_loss", "mu_loss")})  # a schema-3 file
    assert p.tolerance.eps_loss is None and p.tolerance.mu_loss is None
    p.tolerance.n_samples = 40
    f = np.linspace(6e9, 14e9, 41)
    res = run_tolerance(p, f, band=(8e9, 12e9))
    arr, yld = _legacy_run(p, f, p.tolerance, (8e9, 12e9))
    assert np.array_equal(res.median_db, np.median(arr, axis=0)) and res.yield_fraction == yld


def test_solver_perturbs_real_and_loss_parts_separately():
    from coating_studio.core import Backing, SlabLayer as Sl, Structure as St
    from coating_studio.materials import ConstantMaterial
    m = {"Air": ConstantMaterial("Air"), "L": ConstantMaterial("L", 4.0, 0.8, 1.5, 0.3)}
    ly = Sl("L", 2e-3)
    st = St([ly], backing=Backing("pec"))
    f = np.linspace(2e9, 18e9, 33)

    def g(perturb=None, mat=None):
        return solve(st, mat or m, f, 0.0, pols=("TE",), perturb=perturb).pol["TE"].gamma

    def as_mat(er, el, mr, ml):
        return {"Air": m["Air"], "L": ConstantMaterial("L", er, el, mr, ml)}

    assert np.array_equal(g({ly.uid: {}}), g())  # no keys: unchanged
    assert np.allclose(g({ly.uid: {"eps_re": 1.1}}), g(mat=as_mat(4.4, 0.8, 1.5, 0.3)), atol=1e-14)
    assert np.allclose(g({ly.uid: {"eps_loss": 1.5}}), g(mat=as_mat(4.0, 1.2, 1.5, 0.3)), atol=1e-14)
    assert np.allclose(g({ly.uid: {"mu_re": 0.9, "mu_loss": 2.0}}), g(mat=as_mat(4.0, 0.8, 1.35, 0.6)), atol=1e-14)
    assert np.allclose(g({ly.uid: {"eps": 1.2}}), g(mat=as_mat(4.8, 0.96, 1.5, 0.3)), atol=1e-14)  # legacy key


def test_loss_tolerance_draws_and_overrides():
    from unittest import mock

    from coating_studio import tolerance as T
    p = EXAMPLES["dallenbach"][1]()
    uid = p.structure.layers[0].uid
    s = p.tolerance
    s.n_samples, s.thickness, s.eps, s.mu, s.eps_loss, s.mu_loss = 30, 0.0, 0.0, 0.0, 0.2, None
    seen = []
    real_solve = T.solve

    def spy(*a, perturb=None, **kw):
        if perturb:
            seen.append(dict(perturb[uid]))
        return real_solve(*a, perturb=perturb, **kw)

    with mock.patch.object(T, "solve", spy):
        T.run_tolerance(p, np.linspace(8e9, 12e9, 5))
    assert all(d["eps_re"] == 1.0 and d["mu"] == 1.0 and "mu_re" not in d for d in seen)  # mixed modes
    assert np.std([d["eps_loss"] for d in seen]) > 0.05  # only the loss part varies: tan d varies
    # per-layer override in both directions
    s.eps_loss, s.mu_loss = None, None
    s.per_layer = {uid: {"mu_loss": 0.3}}
    seen.clear()
    with mock.patch.object(T, "solve", spy):
        T.run_tolerance(p, np.linspace(8e9, 12e9, 5))
    assert all("eps" in d and "mu_loss" in d for d in seen)
    from coating_studio.project import ToleranceSettings
    t = ToleranceSettings.from_dict({**s.to_dict(), "per_layer": {uid: {"eps_loss": None, "eps": 0.02}}})
    assert t.per_layer == {uid: {"eps": 0.02}} and t.tolerance_for(uid, "eps_loss") is None


def test_loss_tolerance_defaults_and_copy():
    from coating_studio.project import ToleranceSettings
    assert Project().tolerance.eps_loss == 0.10 and Project().tolerance.mu_loss == 0.10  # new projects
    for val in (None, 0.1):
        p = Project()
        p.tolerance.eps_loss = val
        assert p.copy().tolerance.eps_loss == val  # workers run on copies
    assert ToleranceSettings.from_dict({}).eps_loss is None  # old files keep the correlated model


# ---------------------------------------------------------------- real/loss error correlation (rho)
def _rho_project(dist="normal", rho=0.0, n=4000):
    p = EXAMPLES["dallenbach"][1]()
    s = p.tolerance
    s.n_samples, s.distribution, s.loss_correlation = n, dist, rho
    s.thickness, s.eps, s.mu, s.eps_loss, s.mu_loss = 0.03, 0.05, 0.04, 0.2, 0.3
    return p, p.structure.layers[0].uid


def test_rho_zero_keeps_the_independent_draws():
    """rho = 0 must reproduce the schema-4 draws exactly: thickness, eps, mu, then eps'', mu'' per layer."""
    from coating_studio.tolerance import _draw, sample_factors
    p, uid = _rho_project(n=50)
    s = p.tolerance
    got = sample_factors(p, s, np.random.default_rng(7), 50)[uid]
    rng = np.random.default_rng(7)
    want = {k: np.maximum(_draw(rng, s.distribution, getattr(s, k), 50), 1e-6) for k in ("thickness", "eps", "mu")}
    want["eps_re"], want["mu_re"] = want.pop("eps"), want.pop("mu")
    for k in ("eps_loss", "mu_loss"):
        want[k] = np.maximum(_draw(rng, s.distribution, getattr(s, k), 50), 1e-6)
    assert got.keys() == want.keys() and all(np.array_equal(got[k], want[k]) for k in want)


@pytest.mark.parametrize("rho", [-0.6, 0.5, 0.9])
def test_rho_normal_correlation_and_marginals(rho):
    from coating_studio.tolerance import sample_factors
    p, uid = _rho_project("normal", rho)
    fac = sample_factors(p, p.tolerance, np.random.default_rng(3), 4000)[uid]
    for part, tol_re, tol_loss in (("eps", 0.05, 0.2), ("mu", 0.04, 0.3)):
        re, loss = fac[f"{part}_re"], fac[f"{part}_loss"]
        assert abs(np.corrcoef(re, loss)[0, 1] - rho) < 0.04
        assert abs(np.std(loss) - tol_loss) < 0.015 and abs(np.mean(loss) - 1) < 0.015  # loss keeps its own sigma
        assert abs(np.std(re) - tol_re) < 0.004  # the real part is untouched
    full = sample_factors(p, dataclasses.replace(p.tolerance, loss_correlation=1.0), np.random.default_rng(3), 4000)[uid]
    assert np.allclose(full["eps_loss"] - 1, (full["eps_re"] - 1) * 0.2 / 0.05)  # rho = 1: fully coupled


def test_rho_uniform_stays_uniform():
    from coating_studio.tolerance import sample_factors
    p, uid = _rho_project("uniform", 0.8)
    fac = sample_factors(p, p.tolerance, np.random.default_rng(5), 4000)[uid]
    loss = fac["eps_loss"]
    assert loss.min() >= 0.8 and loss.max() <= 1.2  # still inside +/- 20 %
    assert np.histogram(loss, bins=4, range=(0.8, 1.2))[0].min() > 850  # flat (1000 expected per bin)
    assert abs(np.corrcoef(fac["eps_re"], loss)[0, 1] - 6 / np.pi * np.arcsin(0.4)) < 0.04


def test_rho_validation_old_files_and_spec():
    from coating_studio.cli.spec import project_to_spec, spec_to_project
    from coating_studio.project import ToleranceSettings
    from coating_studio.cli.output import CliError
    assert ToleranceSettings.from_dict({}).loss_correlation == 0.0  # schema <= 4 files: independent
    p, _ = _rho_project(rho=1.5, n=5)
    with pytest.raises(ValueError):
        run_tolerance(p, np.linspace(8e9, 12e9, 5))
    p.tolerance.loss_correlation = 0.4
    assert Project.from_dict(json.loads(json.dumps(p.to_dict()))).tolerance.loss_correlation == 0.4
    spec = project_to_spec(p)
    assert spec["tolerance"]["loss_correlation"] == 0.4
    assert spec_to_project(spec)[0].tolerance.loss_correlation == 0.4
    spec["tolerance"]["loss_correlation"] = -2
    with pytest.raises(CliError):
        spec_to_project(spec)


def _two_slab_project(n=4000):
    """Two lossy slabs with independent loss tolerances (per-layer rho tests)."""
    from coating_studio.core.structure import Backing, SlabLayer, Structure
    from coating_studio.materials.models import ConstantMaterial
    p = Project()
    p.add_material(ConstantMaterial("A", eps_re=4.0, eps_loss=0.8, mu_re=1.5, mu_loss=0.6))
    p.structure = Structure(layers=[SlabLayer("A", 2e-3), SlabLayer("A", 3e-3)], backing=Backing("pec"))
    s = p.tolerance
    s.n_samples, s.thickness, s.eps, s.mu, s.eps_loss, s.mu_loss = n, 0.03, 0.05, 0.04, 0.2, 0.3
    return p, [ly.uid for ly in p.structure.layers]


def test_per_layer_rho_overrides_the_default():
    from coating_studio.tolerance import sample_factors
    p, (u1, u2) = _two_slab_project()
    p.tolerance.loss_correlation = 0.0
    p.tolerance.per_layer = {u2: {"loss_correlation": 0.8}}
    fac = sample_factors(p, p.tolerance, np.random.default_rng(11), 4000)
    for part in ("eps", "mu"):
        assert abs(np.corrcoef(fac[u1][f"{part}_re"], fac[u1][f"{part}_loss"])[0, 1]) < 0.04  # default rho = 0
        assert abs(np.corrcoef(fac[u2][f"{part}_re"], fac[u2][f"{part}_loss"])[0, 1] - 0.8) < 0.04
    # an override equal to the default draws exactly what the default alone draws
    p.tolerance.loss_correlation = 0.5
    p.tolerance.per_layer = {}
    ref = sample_factors(p, p.tolerance, np.random.default_rng(2), 50)
    p.tolerance.per_layer = {u1: {"loss_correlation": 0.5}}
    got = sample_factors(p, p.tolerance, np.random.default_rng(2), 50)
    assert all(np.array_equal(got[u][k], ref[u][k]) for u in ref for k in ref[u])
    # a per-layer rho = 0 restores the independent draws of that layer only
    p.tolerance.per_layer = {u1: {"loss_correlation": 0.0}}
    got = sample_factors(p, p.tolerance, np.random.default_rng(2), 50)
    p.tolerance.loss_correlation, p.tolerance.per_layer = 0.0, {}
    indep = sample_factors(p, p.tolerance, np.random.default_rng(2), 50)
    assert all(np.array_equal(got[u1][k], indep[u1][k]) for k in indep[u1])
    assert all(np.array_equal(got[u2][k], ref[u2][k]) for k in ref[u2])


def test_per_layer_rho_validation_and_round_trip():
    from coating_studio.cli.output import CliError
    from coating_studio.cli.spec import project_to_spec, spec_to_project
    p, (u1, u2) = _two_slab_project(n=5)
    p.tolerance.per_layer = {u2: {"loss_correlation": -1.2}}
    with pytest.raises(ValueError):
        run_tolerance(p, np.linspace(8e9, 12e9, 5))
    p.tolerance.per_layer = {u2: {"loss_correlation": 0.7, "eps_loss": 0.25}}
    d = json.loads(json.dumps(p.to_dict()))
    assert d["schema"] == 6
    assert Project.from_dict(d).tolerance.per_layer == {u2: {"loss_correlation": 0.7, "eps_loss": 0.25}}
    spec = project_to_spec(p)
    assert len(spec["tolerance"]["per_layer"]) == 1
    assert spec["tolerance"]["per_layer"][0]["loss_correlation"] == 0.7
    q = spec_to_project(spec)[0]
    assert q.tolerance.tolerance_for(q.structure.layers[1].uid, "loss_correlation") == 0.7
    assert q.tolerance.tolerance_for(q.structure.layers[0].uid, "loss_correlation") == 0.0
    for bad in (2, "0.5", True):
        spec["tolerance"]["per_layer"][0]["loss_correlation"] = bad
        with pytest.raises(CliError):
            spec_to_project(spec)


def test_rho_changes_yield_only_when_set():
    p, _ = _rho_project(n=60)
    f = np.linspace(6e9, 14e9, 41)
    base = run_tolerance(p, f, band=(8e9, 12e9))
    p.tolerance.loss_correlation = 0.0
    assert np.array_equal(run_tolerance(p, f, band=(8e9, 12e9)).worst_db, base.worst_db)
    p.tolerance.loss_correlation = 0.9
    assert not np.array_equal(run_tolerance(p, f, band=(8e9, 12e9)).worst_db, base.worst_db)
