"""The Odelevskiy ratio N/pc from several loadings (materials/shape_fit.py, coating-cli fit-shape)."""

import io
import json

import numpy as np
import pytest

from coating_studio.cli import main
from coating_studio.materials.csvio import to_csv_text
from coating_studio.materials.inversion import invert_filler, invert_rule
from coating_studio.materials.models import Shape, mixing_rule
from coating_studio.materials.shape_fit import admissible_n, fit_shape, flat_interval, solve_u

F = np.linspace(1, 18, 40) * 1e9
G = F / 1e9
EM = np.full(F.size, 3 - 0.05j)
EI = 30 / (1 + 1j * G / 5) + 20 - 2j
MM = np.ones(F.size, complex)
MI = 2 + 5 / (1 + 1j * G / 2)
TRUE = Shape(0.1, 0.25)
PS = [0.05, 0.10, 0.15]


def composites(shape=TRUE, ps=PS, mu=False, noise=0.0, seed=1):
    rng = np.random.default_rng(seed)

    def nz(a):
        return a * (1 + noise * (rng.standard_normal(a.shape) + 1j * rng.standard_normal(a.shape)) / np.sqrt(2))

    eps = nz(np.array([mixing_rule(EM, EI, p, "odelevskiy", shape) for p in ps]))
    mus = nz(np.array([mixing_rule(MM, MI, p, "odelevskiy", shape) for p in ps])) if mu else np.ones((len(ps), F.size))
    return eps, mus.astype(complex)


def test_only_the_ratio_is_determined():
    """Same N/pc, different N: the tables differ, every loading is reproduced the same (the module's premise)."""
    eps, _ = composites()
    preds = []
    for shape in (Shape(0.1, 0.25), Shape(0.08, 0.2), Shape(0.2, 0.5)):
        table, _ = invert_rule(eps[0], EM, PS[0], "odelevskiy", shape)
        preds.append([mixing_rule(EM, table, p, "odelevskiy", shape) for p in PS])
    for other in preds[1:]:
        for a, b in zip(preds[0], other):
            assert np.max(np.abs(a - b) / np.abs(a)) < 1e-13
    table, _ = invert_rule(eps[0], EM, PS[0], "odelevskiy", Shape(0.1, 0.3))  # another ratio does not
    assert np.max(np.abs(mixing_rule(EM, table, PS[2], "odelevskiy", Shape(0.1, 0.3)) - eps[2]) / np.abs(eps[2])) > 0.01


def test_screening_depends_on_n():
    """x = N/u: at one ratio a larger N can leave the model (the review's counterexample, numbers checked)."""
    e, em = np.array([5.0 - 0.1j]), np.array([3.0 + 0j])
    ok = [invert_filler([1e9], e, np.ones(1), em, np.ones(1), 0.1, "odelevskiy", False, s).ok
          for s in (Shape(0.15, 0.3), Shape(0.25, 0.5), Shape(0.5, 1.0))]
    assert ok == [True, False, False]
    _, x = invert_rule(e, em, 0.1, "odelevskiy", Shape(0.25, 0.5))
    u = 0.1 * em / (e - em) + 0.1 * 0.5
    assert x == pytest.approx(0.25 / u)


@pytest.mark.parametrize("shape, ps", [(TRUE, PS), (Shape(0.05, 0.4), [0.1, 0.2]), (Shape(1 / 3, 1.0), [0.1, 0.3]),
                                       (Shape(0.01, 0.5), [0.1, 0.2, 0.3])])
def test_recovers_the_ratio_without_noise(shape, ps):
    eps, mu = composites(shape, ps, mu=True)
    fit = fit_shape(ps, {"eps": (EM, eps), "mu": (MM, mu)})
    assert fit.n_over_pc == pytest.approx(shape.n / shape.pc, rel=1e-6)
    assert fit.rms < 1e-8 and not fit.at_bound
    assert fit.channels_used == ["eps", "mu"]
    lo, hi = fit.flat_interval
    assert lo <= fit.n_over_pc <= hi and hi > lo  # the absolute floor keeps a width without noise


def test_recovers_the_ratio_with_noise():
    for seed in range(5):
        eps, mu = composites(mu=True, noise=0.01, seed=seed)
        fit = fit_shape(PS, {"eps": (EM, eps), "mu": (MM, mu)})
        assert fit.n_over_pc == pytest.approx(0.4, rel=0.05)
        assert 0.003 < fit.rms < 0.02
        lo, hi = fit.flat_interval
        assert lo < 0.4 < hi


def test_mu_channel_alone():
    _, mu = composites(mu=True)
    eps = np.tile(EM, (3, 1))  # the composite's eps equals the matrix
    fit = fit_shape(PS, {"eps": (EM, eps), "mu": (MM, mu)})
    assert fit.channels_used == ["mu"] and fit.rms_per["eps"] is None
    assert fit.n_over_pc == pytest.approx(0.4, rel=1e-6)


def test_both_channels_share_the_ratio_whatever_their_scales():
    eps, mu = composites(mu=True)
    fit = fit_shape(PS, {"eps": (EM * 100, eps * 100), "mu": (MM, mu)})  # 100x larger eps scale
    assert fit.n_over_pc == pytest.approx(0.4, rel=1e-6)


@pytest.mark.parametrize("ps, msg", [([0.1], "two loadings"), ([0.1, 0.1], "differ"), ([0.1, 1.0], "between")])
def test_refuses_unusable_loadings(ps, msg):
    eps = np.tile(EM + 1, (len(ps), 1))
    with pytest.raises(ValueError, match=msg):
        fit_shape(ps, {"eps": (EM, eps)})


def test_refuses_data_without_signal():
    with pytest.raises(ValueError, match="nothing to fit"):
        fit_shape(PS, {"eps": (EM, np.tile(EM, (3, 1))), "mu": (MM, np.ones((3, F.size), complex))})


def test_inner_solver_survives_composites_equal_to_the_matrix():
    """Every loading equals the matrix at one frequency (the linear start divides by zero there): no NaN."""
    eps, _ = composites()
    eps[:, 7] = EM[7]
    u, r = solve_u(0.4, PS, EM, eps)
    assert np.all(np.isfinite(u)) and np.all(np.isfinite(r))


def _cost(u, b, eps, s):
    p = np.asarray(PS)[:, None]
    return np.sum(np.abs((EM[0] * p / (u - b * p) - (eps - EM[0])) / s) ** 2, axis=0)


def test_inner_solver_reaches_the_least_squares_minimum_on_inconsistent_data():
    """Data no u reproduces: the damped steps must still end at each frequency's minimum (checked by a dense
    search around the result) and never above the starting cost."""
    eps, _ = composites()
    eps[2] = eps[0]
    b = 0.4
    s = np.max(np.abs(eps), axis=1)[:, None]
    u, _ = solve_u(b, PS, EM, eps)
    c = _cost(u, b, eps, s)
    for j in (0, 13, 27, 39):
        step = np.linspace(-0.02, 0.02, 81) * abs(u[j])
        grid = (u[j] + step[:, None] + 1j * step[None, :]).ravel()
        dense = _cost(grid[None, :], b, eps[:, [j]], s)
        assert c[j] <= dense.min() * (1 + 1e-9)


def test_profile_minimum_is_kept_when_the_bracket_search_does_worse(monkeypatch):
    import scipy.optimize

    eps, _ = composites()
    exact = fit_shape(PS, {"eps": (EM, eps)})

    class Bad:
        x = np.log(1e-4)  # a point far from the minimum
    monkeypatch.setattr(scipy.optimize, "minimize_scalar", lambda *a, **k: Bad())
    fit = fit_shape(PS, {"eps": (EM, eps)})
    i = int(np.argmin(fit.profile_rms))
    assert fit.n_over_pc == fit.profile_b[i] and fit.rms == fit.profile_rms[i]
    assert fit.n_over_pc == pytest.approx(exact.n_over_pc, rel=0.05)


def test_search_range_and_a_channel_with_partial_signal():
    eps, _ = composites()
    eps2 = np.tile(EM, (3, 1))
    eps2[:, :5] = eps[:, :5]  # differs from the matrix at five frequencies only
    fit = fit_shape(PS, {"eps": (EM, eps2)})
    assert fit.channels_used == ["eps"]
    assert fit.search_range == (1e-4, (1 - 1e-6) / 0.15)


def test_flat_interval_is_the_connected_stretch():
    grid = np.geomspace(0.1, 10, 9)
    prof = np.array([0.5, 0.0101, 0.5, 0.01, 0.0105, 0.5, 0.5, 0.5, 0.0101])  # minimum at index 3
    lo, hi = flat_interval(grid, prof, grid[3], 0.01)
    assert grid[2] < lo < grid[3] and grid[4] < hi < grid[5]  # the dips at 1 and 8 are not joined


def test_admissible_share_counts_only_thresholds_above_every_loading():
    """Maxwell-Garnett composites (B = 1/3, loadings 0.1 and 0.3): every N in (0.1, 1/3] is accepted."""
    eps, mu = composites(Shape(1 / 3, 1.0), [0.1, 0.3])
    lo, hi, share = admissible_n(1 / 3, [0.1, 0.3], F, eps[1], mu[1], EM, MM, 0.3)
    assert share == 1.0 and lo > 0.1 and hi == pytest.approx(1 / 3)


def test_admissible_n_matches_invert_filler():
    eps, mu = composites()
    lo, hi, share = admissible_n(0.4, PS, F, eps[1], mu[1], EM, MM, PS[1])
    assert lo < TRUE.n < hi and 0 < share <= 1
    for n in (lo, hi):
        assert invert_filler(F, eps[1], mu[1], EM, MM, PS[1], "odelevskiy", False, Shape(n, n / 0.4)).ok
    beyond = hi * 1.2
    assert not invert_filler(F, eps[1], mu[1], EM, MM, PS[1], "odelevskiy", False, Shape(beyond, beyond / 0.4)).ok


# ---- CLI -------------------------------------------------------------------------------------------------------

def run(argv):
    out = io.StringIO()
    code = main(argv, stdout=out, stderr=io.StringIO())
    return code, json.loads(out.getvalue())


@pytest.fixture
def csvs(tmp_path):
    eps, _ = composites()
    paths = []
    for p, e in zip(PS, eps):
        path = tmp_path / f"c{p}.csv"
        path.write_text(to_csv_text(F, e, np.ones(F.size, complex)), encoding="utf-8")
        paths.append(str(path))
    return paths


def argv_for(paths, ps=PS, *extra):
    out = ["fit-shape"]
    for path, p in zip(paths, ps):
        out += ["--composite", path, str(p)]
    return out + ["--matrix-eps", "3", "0.05", *extra]


def test_cli_matches_the_engine(csvs):
    code, env = run(argv_for(csvs))
    assert code == 0 and env["ok"] and env["warnings"] == []
    r = env["result"]
    from coating_studio.materials.csvio import load_csv
    from coating_studio.materials.models import ConstantMaterial
    tabs = [load_csv(p) for p in csvs]
    f = tabs[0].f  # the grid as read back from the CSV
    em, mm = ConstantMaterial("m", 3, 0.05).eps_mu(f, None)
    eps = np.array([t.eps_mu(f, None)[0] for t in tabs])
    mus = np.array([t.eps_mu(f, None)[1] for t in tabs])
    fit = fit_shape(PS, {"eps": (em, eps), "mu": (mm, mus)})
    assert r["n_over_pc"] == fit.n_over_pc and r["rms"] == fit.rms
    assert r["profile"]["rms"] == fit.profile_rms.tolist() and r["flat_interval"] == list(fit.flat_interval)
    assert r["channels_used"] == ["eps"] and r["n_points"] == F.size
    row = r["per_composite"][1]
    assert row["rms_mu"] is None and row["fraction"] == 0.1
    lo, hi, share = admissible_n(fit.n_over_pc, PS, f, eps[1], mus[1], em, mm, 0.1)
    assert row["shape_n_range"] == [lo, hi] and row["admissible_share"] == share
    assert row["percolation_range"] == [lo / fit.n_over_pc, hi / fit.n_over_pc]


def test_cli_range_round_trips_through_invert_filler(csvs, tmp_path):
    """A shape factor from the reported range is accepted by invert-filler, and the other loadings validate."""
    _, env = run(argv_for(csvs))
    r = env["result"]
    n = sum(r["per_composite"][1]["shape_n_range"]) / 2
    pc = n / r["n_over_pc"]
    code, inv = run(["invert-filler", csvs[1], "-o", str(tmp_path / "filler.csv"), "--model", "odelevskiy",
                     "--shape-n", repr(n), "--percolation", repr(pc), "--fraction", "0.1", "--density-filler", "7800",
                     "--matrix-eps", "3", "0.05", "--validate", csvs[0], "0.05", "--validate", csvs[2], "0.15"])
    assert code == 0, inv
    assert all(v["rms_eps"] < 1e-6 for v in inv["result"]["validation"])


def test_cli_warns_on_two_loadings_and_a_poor_fit(csvs, tmp_path):
    code, env = run(argv_for(csvs[:2], PS[:2]))
    assert code == 0 and [w["code"] for w in env["warnings"]] == ["shape_two_fractions"]
    bad = tmp_path / "bad.csv"  # the 0.15 composite measured like the 0.05 one: no ratio joins them
    eps, _ = composites()
    bad.write_text(to_csv_text(F, eps[0], np.ones(F.size, complex)), encoding="utf-8")
    code, env = run(argv_for([csvs[0], csvs[1], str(bad)]))
    codes = [w["code"] for w in env["warnings"]]
    assert code == 0 and codes[:2] == ["shape_fit_poor", "shape_at_bound"]


def test_cli_weight_fractions(csvs):
    rho_f, rho_m = 7800.0, 1200.0
    wt = [p * rho_f / (p * rho_f + (1 - p) * rho_m) for p in PS]
    code, env = run(argv_for(csvs, wt, "--weight-fractions", "--density-filler", "7800", "--density-matrix", "1200"))
    assert code == 0
    assert [row["fraction"] for row in env["result"]["per_composite"]] == pytest.approx(PS)
    assert env["result"]["n_over_pc"] == pytest.approx(0.4, rel=1e-6)


@pytest.mark.parametrize("extra, msg", [
    (["--density-filler", "7800"], "go with --weight-fractions"),
    (["--weight-fractions"], "needs a positive"),
    (["--matrix-mu", "1", "0"], None),  # allowed with --matrix-eps
])
def test_cli_density_options(csvs, extra, msg):
    code, env = run(argv_for(csvs, PS, *extra))
    if msg is None:
        assert code == 0
    else:
        assert code == 3 and env["error"]["code"] == "invalid_value" and msg in env["error"]["message"]


def test_cli_refuses_bad_input(csvs, tmp_path):
    code, env = run(argv_for(csvs[:1], PS[:1]))
    assert code == 3 and "at least two" in env["error"]["message"]
    code, env = run(argv_for([csvs[0], csvs[0]], [0.05, 0.1]))
    assert code == 3 and "twice" in env["error"]["message"]
    code, env = run(argv_for(csvs[:2], [0.1, 0.1]))
    assert code == 3 and "differ" in env["error"]["message"]
    code, env = run(argv_for(csvs[:2], [0.1, 1.5]))
    assert code == 3 and "between 0 and 1" in env["error"]["message"]
    code, env = run(argv_for(csvs[:1] + [str(tmp_path / "missing.csv")], PS[:2]))
    assert code == 3 and env["error"]["code"] == "file_not_found"
    far = tmp_path / "far.csv"  # no overlap with the others
    far.write_text(to_csv_text(F + 100e9, composites()[0][1], np.ones(F.size, complex)), encoding="utf-8")
    code, env = run(argv_for([csvs[0], str(far)], PS[:2]))
    assert code == 3 and "fewer than two frequencies" in env["error"]["message"]


def test_cli_interpolates_other_grids(csvs, tmp_path):
    """The first composite's grid is used; another composite on a finer grid is interpolated onto it."""
    f2 = np.linspace(0.5, 20, 200) * 1e9
    e2 = mixing_rule(np.full(f2.size, 3 - 0.05j), 30 / (1 + 1j * f2 / 5e9) + 20 - 2j, 0.1, "odelevskiy", TRUE)
    fine = tmp_path / "fine.csv"
    fine.write_text(to_csv_text(f2, e2, np.ones(f2.size, complex)), encoding="utf-8")
    code, env = run(argv_for([csvs[0], str(fine), csvs[2]]))
    assert code == 0 and env["result"]["n_points"] == F.size
    assert env["result"]["n_over_pc"] == pytest.approx(0.4, rel=0.02)  # linear interpolation of the fine grid


@pytest.mark.parametrize("seed", [0, 1, 4, 28])
def test_inner_solver_converges_on_hard_random_data(seed):
    """Random composites far from any rule: undamped Gauss-Newton diverged or stalled at these seeds (NaN at 1320 of
    15000 frequencies over 300 seeds); the damped solver must end finite and at a local minimum everywhere."""
    rng = np.random.default_rng(seed)
    k = rng.integers(2, 5)
    ps = np.sort(rng.uniform(0.02, 0.4, k))
    eh = np.full(50, rng.uniform(1.5, 6) - 0.05j)
    e = eh + (rng.standard_normal((k, 50)) + 1j * rng.standard_normal((k, 50))) * rng.uniform(0.1, 20)
    e.imag = -np.abs(e.imag)
    b = 10 ** rng.uniform(-3, np.log10(0.99 / ps.max()))
    s = np.max(np.abs(e), axis=1)[:, None]

    def cost(u, ej):
        return np.sum(np.abs((eh[0] * ps[:, None] / (u - b * ps[:, None]) - (ej - eh[0])) / s) ** 2, axis=0)

    u, _ = solve_u(b, ps, eh, e)
    c = cost(u, e)
    assert np.all(np.isfinite(c))
    for j in range(50):
        step = np.linspace(-0.01, 0.01, 41) * abs(u[j])
        grid = (u[j] + step[:, None] + 1j * step[None, :]).ravel()
        assert c[j] <= cost(grid[None, :], e[:, [j]]).min() * (1 + 1e-6), j
