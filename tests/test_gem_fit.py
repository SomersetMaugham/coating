"""GEM pc and t from several loadings (fit-gem), and GEM in the single-composite filler inversion."""

import numpy as np
import pytest

from coating_studio.cli.commands import cmd_fit_gem, cmd_invert_filler
from coating_studio.cli.output import CliError
from coating_studio.core.constants import EPS0
from coating_studio.limits import inversion_shape, inverted_filler_issues
from coating_studio.materials import ConstantMaterial, MixtureMaterial
from coating_studio.materials.csvio import load_csv, to_csv_text
from coating_studio.materials.gem_fit import fit_gem, warning_flags
from coating_studio.materials.inversion import invert_filler, provenance_note, validation_errors
from coating_studio.materials.models import GemParams, TabulatedMaterial, gem
from coating_studio.project import Project

F = np.geomspace(1e9, 18e9, 40)
EM = np.full(F.shape, 3.0 - 0.05j)
EI = 20 - 1j * 100 / (2 * np.pi * F * EPS0)  # carbon-like filler, sigma = 100 S/m
ONES = np.ones(F.shape, complex)
TRUE = GemParams(0.10, 2.0)


def _composites(phis, params=TRUE, noise=0.0, seed=0, em=EM, ei=EI):
    rng = np.random.default_rng(seed)
    c = np.array([gem(em, ei, p, params) for p in phis])
    return c * (1 + noise * (rng.normal(size=c.shape) + 1j * rng.normal(size=c.shape)) / np.sqrt(2))


def _codes(fit, phis, channels):
    return {c for c, _ in warning_flags(fit, phis, channels)}


@pytest.mark.parametrize("phis,expect", [([0.04, 0.08, 0.12, 0.18], set()),
                                         ([0.02, 0.04, 0.06, 0.08], {"gem_one_sided"}),
                                         ([0.12, 0.16, 0.22], {"gem_one_sided"}),
                                         ([0.06, 0.15], {"gem_two_fractions"})])
def test_noiseless_data_give_pc_and_t(phis, expect):
    """Unlike Odelevskiy's N/pc, both parameters follow from noiseless data at any loadings."""
    ch = {"eps": (EM, _composites(phis)), "mu": (ONES, np.ones((len(phis), F.size), complex))}
    fit = fit_gem(phis, ch)
    assert fit.percolation == pytest.approx(0.10, rel=1e-6) and fit.exponent == pytest.approx(2.0, rel=1e-6)
    assert fit.rms < 1e-10 and fit.channels_used == ["eps"] and fit.rms_per["mu"] is None
    assert _codes(fit, phis, ch) == expect


def test_noise_straddling_and_one_sided():
    """1 % complex noise: straddling loadings pin pc and t; loadings all below pc leave both loose (flagged)."""
    phis = [0.04, 0.08, 0.12, 0.18]
    ch = {"eps": (EM, _composites(phis, noise=0.01))}
    fit = fit_gem(phis, ch)
    assert abs(fit.percolation - 0.10) < 0.005 and abs(fit.exponent - 2.0) < 0.1
    assert fit.flat_pc[0] <= fit.percolation <= fit.flat_pc[1] and fit.flat_t[0] <= fit.exponent <= fit.flat_t[1]
    assert not _codes(fit, phis, ch)
    low = [0.02, 0.04, 0.06, 0.08]
    ch = {"eps": (EM, _composites(low, noise=0.01))}
    fit = fit_gem(low, ch)
    assert fit.flat_pc[0] <= 0.10 <= fit.flat_pc[1] and fit.flat_t[0] <= 2.0 <= fit.flat_t[1]  # the truth is inside
    assert {"gem_one_sided", "gem_t_weak"} <= _codes(fit, low, ch)


def test_eps_and_mu_channels():
    phis = [0.04, 0.08, 0.12, 0.18]
    mi = 6 - 2j * np.ones(F.shape)
    ch = {"eps": (EM, _composites(phis)), "mu": (ONES, _composites(phis, em=ONES, ei=mi))}
    fit = fit_gem(phis, ch)
    assert fit.channels_used == ["eps", "mu"] and fit.percolation == pytest.approx(0.10, rel=1e-6)
    assert "gem_channel_mismatch" not in _codes(fit, phis, ch)
    other = {"eps": ch["eps"], "mu": (ONES, _composites(phis, GemParams(0.3, 1.5), em=ONES, ei=mi))}
    assert "gem_channel_mismatch" in _codes(fit_gem(phis, other), phis, other)
    with pytest.raises(ValueError, match="nothing to fit"):
        fit_gem(phis, {"eps": (EM, np.tile(EM, (4, 1)))})


def test_gem_inversion_matches_bruggeman_and_crosses_the_threshold():
    rng = np.random.default_rng(3)
    em = rng.uniform(2, 5, 50) - 1j * rng.uniform(0, 0.2, 50)
    ei = rng.uniform(5, 40, 50) - 1j * rng.uniform(0, 300, 50)
    f = np.linspace(1e9, 10e9, 50)
    e = gem(em, ei, 0.2, GemParams(1 / 3, 1.0))
    g = invert_filler(f, e, np.ones(50), em, np.ones(50), 0.2, "gem", shape=GemParams(1 / 3, 1.0))
    b = invert_filler(f, e, np.ones(50), em, np.ones(50), 0.2, "bruggeman")
    assert np.allclose(g.eps.value, b.eps.value, rtol=1e-12)
    assert np.allclose(g.eps.amplification, b.eps.amplification, rtol=1e-9)
    assert np.array_equal(g.eps.outside_model, b.eps.outside_model) and g.ok == b.ok
    # one composite below pc gives the filler; it predicts a loading above pc
    below = gem(EM, EI, 0.06, TRUE)
    res = invert_filler(F, below, ONES, EM, ONES, 0.06, "gem", shape=TRUE)
    assert res.ok and np.max(np.abs(res.eps.value - EI) / np.abs(EI)) < 1e-10
    tab = res.to_tabulated("cb", 1800.0)
    v = validation_errors(tab, ConstantMaterial("m", 3.0, 0.05), F, gem(EM, EI, 0.2, TRUE), ONES, 0.2, "gem", TRUE)
    assert v["rms_eps"] < 1e-10


def test_provenance_and_mixture_rule_check():
    note = provenance_note("comp.csv", "gem", 0.06, "resin", TRUE)
    assert "pc=0.1; t=2;" in note
    tab = TabulatedMaterial("cb", [1e9, 2e9], [20, 20], [5, 5], note=note)
    assert inversion_shape(tab) == TRUE
    p = Project()
    p.add_material(ConstantMaterial("resin", 3.0, 0.05))
    p.add_material(tab)
    good = MixtureMaterial("mix", "resin", "cb", 0.06, "gem", percolation=0.1, exponent=2.0)
    bad = MixtureMaterial("mix2", "resin", "cb", 0.06, "gem", percolation=0.1, exponent=1.5)
    assert "inverted_filler_model" not in {i.code for i in inverted_filler_issues(p, good, 0.06, 0.06)}
    assert "inverted_filler_model" in {i.code for i in inverted_filler_issues(p, bad, 0.06, 0.06)}


def _write(path, e):
    path.write_text(to_csv_text(F, e, ONES))
    return str(path)


def test_cli_fit_gem_and_invert_filler_gem(tmp_path):
    phis = [0.04, 0.08, 0.12, 0.18]
    comps = [[_write(tmp_path / f"c{k}.csv", c), str(p)] for k, (c, p) in enumerate(zip(_composites(phis), phis))]
    res = cmd_fit_gem(comps, matrix_eps=(3.0, 0.05))
    assert res.result["percolation"] == pytest.approx(0.10, rel=1e-6) and res.result["exponent"] == pytest.approx(2.0)
    assert res.result["channels_used"] == ["eps"] and len(res.result["per_composite"]) == 4 and not res.warnings
    with pytest.raises(CliError):
        cmd_fit_gem(comps[:1], matrix_eps=(3.0, 0.05))
    out = tmp_path / "filler.csv"
    inv = cmd_invert_filler(comps[1][0], str(out), "gem", 1800.0, fraction="0.08", matrix_eps=(3.0, 0.05),
                            percolation=0.1, exponent=2.0, validate=[(comps[3][0], "0.18")])
    assert inv.result["exponent"] == 2.0 and inv.result["validation"][0]["rms_eps"] < 1e-6
    assert "t=2;" in inv.result["material"]["note"]
    filler = load_csv(str(out), name="f")
    assert np.max(np.abs(filler.eps_mu(F, None)[0] - EI) / np.abs(EI)) < 1e-7
    for kw in ({"percolation": 0.1}, {"percolation": 0.1, "exponent": 2.0, "shape_n": 0.2}):
        with pytest.raises(CliError):
            cmd_invert_filler(comps[1][0], str(tmp_path / "x.csv"), "gem", 1800.0, fraction="0.08",
                              matrix_eps=(3.0, 0.05), **kw)
    with pytest.raises(CliError, match="exponent"):
        cmd_invert_filler(comps[1][0], str(tmp_path / "y.csv"), "bruggeman", 1800.0, fraction="0.08",
                          matrix_eps=(3.0, 0.05), exponent=2.0)
