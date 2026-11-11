"""Robust (yield-oriented) optimisation: the worst-case term over fixed manufacturing samples."""

import math

import numpy as np
import pytest

from coating_studio.cli.output import CliError
from coating_studio.cli.spec import project_to_spec, spec_to_project
from coating_studio.core import solve
from coating_studio.examples import EXAMPLES
from coating_studio.optimize import OptimizationError, apply_result, evaluate_terms, optimize
from coating_studio.optimize.optimizer import Evaluator
from coating_studio.tolerance import MaterialSampler, sample_factors


def _project(k=8, q=0.75):
    p = EXAMPLES["jaumann2"][1]()
    o = p.optimization
    for t in o.targets:
        t.goal_db = -15.0
    o.rl_ref_db = -15.0
    o.robust_samples, o.robust_quantile = k, q
    p.tolerance.seed = 4
    p.tolerance.material_params = [{"path": ["material", "PMI foam", "eps_re"], "tol": 0.03}]
    return p


def test_off_by_default_and_nominal_terms_unchanged():
    p = _project(k=0)
    t = evaluate_terms(p)
    assert math.isnan(t.robust_margin_db) and math.isnan(t.sample_yield)
    q = _project(k=6)
    r = evaluate_terms(q)
    # the nominal parts of the terms do not depend on the robust mode
    assert (r.worst_db, r.margin_db, r.per_target, r.thickness) == (t.worst_db, t.margin_db, t.per_target, t.thickness)


def test_robust_terms_match_a_direct_computation():
    """Each sample is the design with the tolerance tab's perturbation applied; its margin is the largest worst-RL
    minus goal over the targets' own grids.  The robust margin is their 'higher' quantile."""
    p = _project(k=10, q=0.7)
    terms = evaluate_terms(p)
    tol = p.tolerance
    rng = np.random.default_rng(tol.seed)
    factors = sample_factors(p, tol, rng, 10)
    mats = MaterialSampler(p, tol, rng, 10)
    margins = []
    for k in range(10):
        pert = {uid: {key: arr[k] for key, arr in d.items()} for uid, d in factors.items()}
        worst = []
        for t in p.optimization.enabled_targets():
            f, th = t.grid()
            res = solve(p.structure, mats.at(k), f, th, pols=tuple(t.pols), perturb=pert)
            r = np.stack([res.pol[q].R for q in t.pols])
            worst.append(float((10 * np.log10(np.maximum(r, 1e-30))).max()) - t.goal_db)
        margins.append(max(worst))
    assert terms.robust_margin_db == float(np.quantile(margins, 0.7, method="higher"))
    assert terms.sample_yield == float(np.mean(np.array(margins) <= 0))
    assert evaluate_terms(p).objective == terms.objective  # fixed samples: deterministic


def test_smooth_term_is_the_tail_mean():
    p = _project(k=8, q=0.75)
    ev = Evaluator(p, p.optimization)
    rough, smooth = ev.terms(), ev.terms(smooth=True)
    assert math.isfinite(smooth.objective) and smooth.objective != rough.objective
    assert smooth.robust_margin_db == rough.robust_margin_db  # the reported values are the true ones


def test_robust_run_never_ends_worse_than_its_start():
    """Starting from the nominal optimum, the robust run's objective (its own samples) can only improve: the start
    is in the initial population and the best evaluated design is kept."""
    p = _project(k=0)
    p.optimization.maxiter, p.optimization.seed = 15, 1
    apply_result(p, optimize(p, throttle_s=0.0))
    p.optimization.robust_samples, p.optimization.seed = 8, 2
    start = evaluate_terms(p)
    r = optimize(p, throttle_s=0.0)
    assert r.terms.objective <= start.objective
    assert r.terms.robust_margin_db <= start.robust_margin_db + 1e-12


def test_validation_and_spec_round_trip():
    p = _project(k=8, q=0.75)
    for k, q in ((-1, 0.8), (1001, 0.8), (True, 0.8), (8, 0.0), (8, 1.5)):
        p.optimization.robust_samples, p.optimization.robust_quantile = k, q
        with pytest.raises(OptimizationError):
            optimize(p)
    p.optimization.robust_samples, p.optimization.robust_quantile = 8, 0.75
    p.tolerance.material_params = [{"path": ["material", "nope", "eps_re"], "tol": 0.1}]
    with pytest.raises(OptimizationError, match="robust mode"):
        optimize(p)
    p = _project(k=8, q=0.75)
    spec = project_to_spec(p)
    assert (spec["optimization"]["robust_samples"], spec["optimization"]["robust_quantile"]) == (8, 0.75)
    back = spec_to_project(spec)[0].optimization
    assert (back.robust_samples, back.robust_quantile) == (8, 0.75)
    assert "robust_samples" not in project_to_spec(_project(k=0))["optimization"]
    for bad in ({"robust_samples": 2.5}, {"robust_samples": -1}, {"robust_quantile": 0}, {"robust_quantile": "x"}):
        s2 = project_to_spec(p)
        s2["optimization"].update(bad)
        with pytest.raises(CliError):
            spec_to_project(s2)
