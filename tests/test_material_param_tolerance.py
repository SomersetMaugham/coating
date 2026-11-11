"""Tolerances on material parameters (ToleranceSettings.material_params, schema 10)."""

import numpy as np
import pytest

from coating_studio.cli.output import CliError
from coating_studio.cli.spec import project_to_spec, spec_to_project
from coating_studio.core import solve
from coating_studio.examples import EXAMPLES
from coating_studio.project import Project, ToleranceSettings
from coating_studio.tolerance import (
    MaterialSampler, run_tolerance, run_tolerance_targets, sample_factors, tolerance_frequencies, yield_intervals,
)

CI = "Carbonyl iron / epoxy"
F0 = ["material", CI, "mu_terms", 0, "f0"]


def _quiet(p):
    """Layer tolerances off, so only the material parameters vary."""
    t = p.tolerance
    t.thickness = t.eps = t.mu = t.sheet = 0.0
    t.eps_loss = t.mu_loss = 0.0
    return p


def _band_worst(p, f, band):
    mask = np.zeros(f.shape, dtype=bool)
    for lo, hi in band:
        mask |= (f >= lo) & (f <= hi)
    s = p.tolerance
    pols = ("TE", "TM") if s.pol == "avg" else (s.pol,)
    r = solve(p.structure, p.materials, f, s.angle, pols=pols).quantity("R", s.pol)[:, 0]
    return float((10 * np.log10(np.maximum(r, 1e-30)))[mask].max())


def test_each_sample_is_the_design_with_the_drawn_parameter():
    """Sample k equals a plain solve of the project with f0 set to nominal x the k-th draw (drawn after the layer
    factors), and the project's own material is left untouched."""
    p = _quiet(EXAMPLES["dallenbach"][1]())
    p.tolerance.n_samples = 25
    p.tolerance.material_params = [{"path": F0, "tol": 0.1}]
    f = tolerance_frequencies(p)
    band = yield_intervals(p)
    r = run_tolerance(p, f, band=band)
    nominal = p.materials[CI].get(tuple(F0[2:]))
    rng = np.random.default_rng(p.tolerance.seed)
    sample_factors(p, p.tolerance, rng, 25)
    draws = nominal * (1.0 + rng.normal(0.0, 0.1, 25))
    assert p.materials[CI].get(tuple(F0[2:])) == nominal
    for k in range(25):
        q = p.copy()
        q.materials[CI].set(tuple(F0[2:]), draws[k])
        assert r.worst_db[k] == pytest.approx(_band_worst(q, f, band), abs=1e-12)
    assert np.ptp(r.worst_db) > 0.1  # the band moves


def test_shifting_f0_moves_the_absorption_peak():
    p = _quiet(EXAMPLES["dallenbach"][1]())
    f = tolerance_frequencies(p)
    peak = lambda q: f[np.argmin(solve(q.structure, q.materials, f, 0.0).quantity("R", "avg")[:, 0])]  # noqa: E731
    q = p.copy()
    q.materials[CI].set(tuple(F0[2:]), 1.2 * p.materials[CI].get(tuple(F0[2:])))
    assert abs(peak(q) - peak(p)) > 0.1e9
    # with every layer tolerance off, the f0 entry alone spreads the band
    p.tolerance.material_params = [{"path": F0, "tol": 0.1}]
    assert run_tolerance(p, f).upper_db.max() > run_tolerance(_quiet(EXAMPLES["dallenbach"][1]()), f).upper_db.max()


def test_entries_do_not_change_the_layer_draws():
    """A file without entries, or with an entry whose value is 0, gives the samples of earlier versions bit for bit."""
    p = EXAMPLES["dallenbach"][1]()
    f = tolerance_frequencies(p)
    base = run_tolerance(p, f)
    assert p.materials[CI].get(("mu_loss",)) == 0.0
    p.tolerance.material_params = [{"path": ["material", CI, "mu_loss"], "tol": 0.3}]  # 0 x anything = 0
    same = run_tolerance(p, f)
    assert np.array_equal(base.worst_db, same.worst_db) and np.array_equal(base.median_db, same.median_db)
    rows = run_tolerance_targets(p, f, "corners")
    p.tolerance.material_params = []
    assert np.array_equal(rows.corners[0][5].worst_db, run_tolerance_targets(p, f, "corners").corners[0][5].worst_db)


def test_mixture_fraction_is_clipped_and_shared_through_references():
    p = EXAMPLES["carbon"][1]()
    p.tolerance.material_params = [{"path": ["material", "Carbon / epoxy", "fraction"], "tol": 5.0},
                                   {"path": ["material", "Carbon black", "sigma"], "tol": 0.2}]
    m = MaterialSampler(p, p.tolerance, np.random.default_rng(3), 200)
    fr = np.array([m.at(k)["Carbon / epoxy"].fraction for k in range(200)])
    assert fr.min() == 0.0 and fr.max() == 1.0  # clipped to the physical range
    mats = m.at(7)
    assert mats["Carbon / epoxy"].fraction == fr[7]
    assert mats["Carbon black"].sigma == p.materials["Carbon black"].sigma * m.entries[1][1][7]
    p.materials["Carbon black"].sigma *= 2  # factors apply to the current nominal value (robust optimisation)
    assert m.at(7)["Carbon black"].sigma == p.materials["Carbon black"].sigma * m.entries[1][1][7]
    assert mats["Epoxy"] is p.materials["Epoxy"]  # untouched materials are not copied
    assert p.materials["Carbon / epoxy"].fraction == 0.3
    assert MaterialSampler(_quiet(EXAMPLES["carbon"][1]()), ToleranceSettings(), np.random.default_rng(0), 5).at(0) is None


def test_unknown_parameter_or_bad_tolerance_is_rejected():
    p = EXAMPLES["dallenbach"][1]()
    f = tolerance_frequencies(p)
    for entry in ({"path": ["material", "nope", "sigma"], "tol": 0.1},
                  {"path": ["material", CI, "mu_terms", 3, "f0"], "tol": 0.1},
                  {"path": F0, "tol": -0.1}, {"path": F0, "tol": float("nan")}):
        p.tolerance.material_params = [entry]
        with pytest.raises(ValueError):
            run_tolerance(p, f)


def test_save_load_rename_remove_and_undo():
    p = EXAMPLES["dallenbach"][1]()
    p.tolerance.material_params = [{"path": F0, "tol": 0.1}]
    q = Project.from_dict(p.to_dict())
    assert q.tolerance.material_params == [{"path": F0, "tol": 0.1}]
    assert q.tolerance.material_tolerance(tuple(F0)) == 0.1 and q.tolerance.material_tolerance(["x"]) is None
    old = p.to_dict()
    old["schema"] = 9
    old["tolerance"].pop("material_params")
    assert Project.from_dict(old).tolerance.material_params == []
    state = q.model_state()
    q.rename_material(CI, "CIP")
    assert q.tolerance.material_params[0]["path"] == ["material", "CIP", "mu_terms", 0, "f0"]
    q.restore_model_state(state)
    assert q.tolerance.material_params[0]["path"] == F0
    q.tolerance.material_params.append({"path": ["material", "PMI foam", "eps_re"], "tol": 0.02})
    q.remove_material("PMI foam")
    assert q.tolerance.material_params == [{"path": F0, "tol": 0.1}]
    legacy = {k: v for k, v in state.items() if k != "material_tol"}  # a state taken before schema 10
    q.restore_model_state(legacy)
    assert q.tolerance.material_params == []


def test_spec_round_trip_and_errors():
    p = EXAMPLES["dallenbach"][1]()
    assert "material_params" not in project_to_spec(p)["tolerance"]
    p.tolerance.material_params = [{"path": F0, "tol": 0.1}]
    spec = project_to_spec(p)
    assert spec["tolerance"]["material_params"] == [{"material": CI, "param": ["mu_terms", 0, "f0"], "tol": 0.1}]
    assert spec_to_project(spec)[0].tolerance.material_params == p.tolerance.material_params
    bad = [({"material": "X", "param": "sigma", "tol": 0.1}, "material"),
           ({"material": CI, "param": ["mu_terms", 9, "f0"], "tol": 0.1}, "param"),
           ({"material": CI, "param": "sigma", "tol": -1}, "tol"),
           ({"material": CI, "param": "sigma", "tol": True}, "tol"),
           ({"material": CI, "param": "sigma", "tol": "5%"}, "tol")]
    for entry, field in bad:
        spec["tolerance"]["material_params"] = [entry]
        with pytest.raises(CliError, match=rf"material_params\[0\]\.{field}"):
            spec_to_project(spec)
    spec["tolerance"]["material_params"] = [{"material": CI, "param": "sigma", "tol": 0.1}] * 2
    with pytest.raises(CliError, match="listed twice"):
        spec_to_project(spec)
