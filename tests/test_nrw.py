"""Nicholson-Ross-Weir extraction from two-port S-parameters, against an independent forward model."""

import json

import numpy as np
import pytest
from scipy.linalg import expm

from coating_studio.core import Backing, SlabLayer, Structure, solve
from coating_studio.core.constants import C0
from coating_studio.materials import ConstantMaterial, DispersiveMaterial, make_term
from coating_studio.materials.csvio import load_csv
from coating_studio.materials.extraction import nrw
from coating_studio.touchstone import TouchstoneError, parse_s2p


def slab_sparams(f, eps, mu, d, fc=None):
    """S11, S21 of a slab filling a line (TEM, or the TE10 mode of a waveguide with cutoff ``fc``), reference planes at
    the faces, matched empty line on both sides.  Straight from Maxwell's equations: psi = (Ey, eta0 Hx),
    d psi/dz = -j k0 M psi with the transverse wavenumber kc = k0 fc/f; a 2x2 matrix exponential per frequency.
    It shares nothing with the NRW formulas."""
    s11, s21 = [], []
    for fk, e, m in zip(f, np.broadcast_to(eps, f.shape), np.broadcast_to(mu, f.shape)):
        k0 = 2 * np.pi * fk / C0
        xi = 0.0 if fc is None else fc / fk
        p = expm(-1j * k0 * d * np.array([[0, -m], [-(e - xi ** 2 / m), 0]], dtype=complex))
        c = np.sqrt(1 - xi ** 2 + 0j)  # empty line: forward eta0 Hx = -c Ey, backward +c Ey
        a, b = p @ np.array([1, -c]), p @ np.array([1, c])  # psi(back) = a + G b must be a forward wave
        g = -(a[1] + c * a[0]) / (b[1] + c * b[0])
        s11.append(g)
        s21.append(a[0] + g * b[0])
    return np.array(s11), np.array(s21)


F = np.linspace(2e9, 18e9, 81)
LOSSY = DispersiveMaterial("x", eps_inf=8.0, eps_loss=0.6, mu_terms=[make_term("lorentz", 2.0, 6e9, 4e9)])


def test_forward_model_matches_the_solver():
    eps, mu = LOSSY.eps_mu(F, None)
    s11, _ = slab_sparams(F, eps, mu, 2e-3)
    mats = {"Air": ConstantMaterial("Air", 1.0, 0.0), "x": LOSSY}
    g = solve(Structure(layers=[SlabLayer("x", 2e-3)], backing=Backing("halfspace", "Air")), mats, F, 0.0)
    assert np.max(np.abs(g.pol["TE"].gamma[:, 0] - s11)) < 1e-13


@pytest.mark.parametrize("fc,d", [(None, 2e-3), (None, 6e-3), (6.0e9, 2e-3)])
def test_recovers_eps_and_mu(fc, d):
    f = F if fc is None else np.linspace(8e9, 12e9, 41)
    eps, mu = LOSSY.eps_mu(f, None)
    s11, s21 = slab_sparams(f, eps, mu, d, fc)
    r = nrw(f, s11, s21, d, cutoff_hz=fc)
    assert np.max(np.abs(r.eps - eps) / np.abs(eps)) < 1e-9
    assert np.max(np.abs(r.mu - mu) / np.abs(mu)) < 1e-9
    assert r.suggested_branch == 0 and not r.warnings


def test_reference_plane_offsets():
    eps, mu = LOSSY.eps_mu(F, None)
    s11, s21 = slab_sparams(F, eps, mu, 2e-3)
    l1, l2 = 7e-3, 12e-3
    beta0 = 2 * np.pi * F / C0
    r = nrw(F, s11 * np.exp(-2j * beta0 * l1), s21 * np.exp(-1j * beta0 * (l1 + l2)), 2e-3, offset1=l1, offset2=l2)
    assert np.max(np.abs(r.eps - eps) / np.abs(eps)) < 1e-9


@pytest.mark.parametrize("mat,d,true_n", [
    (DispersiveMaterial("c", eps_inf=10.0, eps_loss=0.5, mu_inf=2.4, mu_loss=0.2), 20e-3, 3),
    (DispersiveMaterial("c", eps_inf=10.0, eps_loss=0.5, mu_inf=2.4, mu_loss=0.2), 40e-3, 5),
    (LOSSY, 20e-3, 1),  # strongly dispersive: the delay check alone would pick 2; passivity decides
])
def test_branch_is_suggested_for_thick_samples(mat, d, true_n):
    f = np.linspace(8e9, 12e9, 161)
    eps, mu = mat.eps_mu(f, None)
    s11, s21 = slab_sparams(f, eps, mu, d)
    r = nrw(f, s11, s21, d)
    assert r.suggested_branch == true_n
    assert ("branch_suspect" in {c for c, _ in r.warnings}) == (true_n != 0)
    good = nrw(f, s11, s21, d, branch=r.suggested_branch)
    assert np.max(np.abs(good.eps - eps) / np.abs(eps)) < 1e-8 and not good.warnings


def test_half_wave_resonance_is_flagged():
    """A nearly lossless sample half a wavelength thick reflects nothing; NRW is ill-conditioned there."""
    m = ConstantMaterial("ptfe", 2.1, 0.0005)
    f = np.linspace(2e9, 18e9, 401)
    eps, mu = m.eps_mu(f, None)
    d = 10e-3  # d = lambda/2 near 10.3 GHz
    s11, s21 = slab_sparams(f, eps, mu, d)
    r = nrw(f, s11, s21, d)
    codes = {c: a for c, a in r.warnings}
    flagged = np.array(codes["half_wave_resonance"]["f_hz"])
    f_half = C0 / (2 * d * np.sqrt(2.1))
    assert np.min(np.abs(flagged - f_half)) < 0.1e9
    assert np.all(r.resonant == (np.abs(s11) < 0.05))


def test_reciprocity_and_input_errors():
    eps, mu = LOSSY.eps_mu(F, None)
    s11, s21 = slab_sparams(F, eps, mu, 2e-3)
    r = nrw(F, s11, s21, 2e-3, s12=s21 * 1.2)
    assert "nonreciprocal" in {c for c, _ in r.warnings} and r.reciprocity_error == pytest.approx(0.2, rel=1e-6)
    for kw in ({"thickness": 0}, {"thickness": 1e-3, "cutoff_hz": 5e9}, {"thickness": 1e-3, "offset1": -1}):
        with pytest.raises(ValueError):
            nrw(F, s11, s21, **kw)
    with pytest.raises(ValueError):
        nrw(F[::-1], s11, s21, 1e-3)


def _s2p_text(f, s11, s21, s12=None, s22=None, fmt="RI"):
    s12 = s21 if s12 is None else s12
    s22 = s11 if s22 is None else s22
    lines = [f"# GHz S {fmt} R 50"]
    for fk, a, b, c, dd in zip(f, s11, s21, s12, s22):
        vals = []
        for s in (a, b, c, dd):  # version 1 two-port order: S11 S21 S12 S22
            vals += [s.real, s.imag] if fmt == "RI" else [20 * np.log10(abs(s)), np.degrees(np.angle(s))]
        lines.append(f"{fk / 1e9:.12g} " + " ".join(f"{v:.17g}" for v in vals))
    return "\n".join(lines) + "\n"


def test_parse_s2p_order_and_formats():
    s11 = np.array([0.1 + 0.2j, 0.3 - 0.1j])
    s21 = np.array([0.5 - 0.5j, 0.6 + 0.1j])
    s12 = np.array([0.4 - 0.4j, 0.7 + 0.2j])
    s22 = np.array([0.0 + 0.1j, -0.2 + 0.0j])
    for fmt in ("RI", "DB"):
        f, a, b, c, d, ref = parse_s2p(_s2p_text(np.array([1e9, 2e9]), s11, s21, s12, s22, fmt))
        assert ref == 50.0 and np.allclose(f, [1e9, 2e9])
        for got, want in ((a, s11), (b, s21), (c, s12), (d, s22)):
            assert np.allclose(got, want, atol=1e-12)
    with pytest.raises(TouchstoneError, match="9 numbers"):
        parse_s2p("# GHz S RI R 50\n1 0 0 0\n2 0 0 0\n")


def test_cli_extract_nrw_round_trip(tmp_path):
    from coating_studio.cli.commands import cmd_extract_nrw

    f = np.linspace(8e9, 12e9, 41)
    eps, mu = LOSSY.eps_mu(f, None)
    a = 22.86e-3  # WR-90
    fc = C0 / (2 * a)
    s11, s21 = slab_sparams(f, eps, mu, 3e-3, fc)
    src = tmp_path / "sample.s2p"
    src.write_text(_s2p_text(f, s11, s21))
    out = tmp_path / "sample.csv"
    res = cmd_extract_nrw(str(src), 3.0, str(out), waveguide_a_mm=22.86)
    assert res.result["line"] == "TE10 waveguide" and res.result["cutoff_hz"] == pytest.approx(fc)
    assert res.result["n_points"] == 41 and res.result["suggested_branch"] == 0 and not res.warnings
    tab = load_csv(str(out), name="sample")
    e2, m2 = tab.eps_mu(f, None)
    assert np.max(np.abs(e2 - eps) / np.abs(eps)) < 1e-7  # 9 significant digits in the CSV
    assert np.max(np.abs(m2 - mu) / np.abs(mu)) < 1e-7
    json.dumps(res.result)  # the result is JSON-serialisable as is
    from coating_studio.cli.output import CliError

    with pytest.raises(CliError):
        cmd_extract_nrw(str(src), 3.0, str(src), force=True)  # never overwrite the input


def test_uncertainty_thickness_is_analytic_and_resonances_stand_out():
    """In NRW eps and mu are exactly proportional to 1/d, so a thickness error alone gives a relative spread of
    sigma_d/d.  S-parameter noise is amplified most where |S11| -> 0 (half-wave resonance)."""
    from coating_studio.materials.extraction import nrw_uncertainty

    f = np.linspace(2e9, 18e9, 161)
    eps, mu = ConstantMaterial("x", 4.0, 0.08).eps_mu(f, None)
    d = 5e-3
    s11, s21 = slab_sparams(f, eps, mu, d)
    u = nrw_uncertainty(f, s11, s21, d, sigma_thickness=0.01e-3, n_samples=2000, seed=2)
    assert np.allclose(u.eps_re / eps.real, 0.002, rtol=0.06) and np.allclose(u.mu_re / mu.real, 0.002, rtol=0.06)
    zero = nrw_uncertainty(f, s11, s21, d, n_samples=5)
    assert np.max(zero.eps_re) < 1e-12 and np.max(zero.mu_loss) < 1e-12  # (np.std of equal values: rounding only)
    noisy = nrw_uncertainty(f, s11, s21, d, sigma_mag_db=0.05, sigma_phase_deg=0.5, n_samples=300, seed=1)
    i, j = np.argmin(abs(f - 4e9)), np.argmin(abs(f - C0 / (2 * d * 2.0)))  # off and at the half-wave resonance
    assert noisy.eps_re[j] > 5 * noisy.eps_re[i]
    again = nrw_uncertainty(f, s11, s21, d, sigma_mag_db=0.05, sigma_phase_deg=0.5, n_samples=300, seed=1)
    assert np.array_equal(again.eps_re, noisy.eps_re)  # reproducible with the seed
    for kw in ({"sigma_thickness": -1e-3}, {"n_samples": 1}):
        with pytest.raises(ValueError):
            nrw_uncertainty(f, s11, s21, d, **kw)


def test_cli_uncertainty_csv(tmp_path):
    from coating_studio.cli.commands import cmd_extract_nrw
    from coating_studio.cli.output import CliError

    f = np.linspace(2e9, 18e9, 41)
    eps, mu = LOSSY.eps_mu(f, None)
    s11, s21 = slab_sparams(f, eps, mu, 2e-3)
    src = tmp_path / "s.s2p"
    src.write_text(_s2p_text(f, s11, s21))
    res = cmd_extract_nrw(str(src), 2.0, str(tmp_path / "s.csv"), uncertainty_csv=str(tmp_path / "u.csv"),
                          thickness_sigma_mm=0.01, uncertainty_samples=50)
    unc = res.result["uncertainty"]
    assert unc["n_samples"] == 50 and unc["median_relative"]["eps_re"] == pytest.approx(0.005, rel=0.3)
    lines = (tmp_path / "u.csv").read_text().splitlines()
    assert lines[0] == "f [GHz],u(eps'),u(eps''),u(mu'),u(mu'')" and len(lines) == 42
    assert cmd_extract_nrw(str(src), 2.0, str(tmp_path / "t.csv")).result["uncertainty"] is None
    for kw in ({"uncertainty_csv": str(tmp_path / "v.csv")},  # no error assumed by default
               {"thickness_sigma_mm": 0.01},  # sigma without an output
               {"uncertainty_csv": str(tmp_path / "w.csv"), "thickness_sigma_mm": 0.01, "force": True,
                "output": None}):
        out = kw.pop("output", str(tmp_path / "x.csv"))
        with pytest.raises((CliError, TypeError)):
            cmd_extract_nrw(str(src), 2.0, out, **kw)


def test_closed_form_slab_model_matches_the_independent_one():
    from coating_studio.materials.extraction import slab_sparams as closed

    eps, mu = LOSSY.eps_mu(F, None)
    for fc, f in ((None, F), (6.557e9, np.linspace(8e9, 12e9, 41))):
        e, m = LOSSY.eps_mu(f, None)
        a, b = slab_sparams(f, e, m, 3e-3, fc)
        c, d = closed(f, e, m, 3e-3, fc)
        assert np.max(np.abs(a - c)) < 1e-13 and np.max(np.abs(b - d)) < 1e-13


def _noisy(s, rng):
    """VNA-like noise: 0.02 dB and 0.2 deg relative, plus an additive floor at -50 dB.  Without the floor a small
    |S11| would be almost noise-free, which flatters S11 near a half-wave resonance."""
    floor = 10 ** (-50 / 20) / np.sqrt(2) * (rng.normal(size=s.shape) + 1j * rng.normal(size=s.shape))
    return s * 10 ** (rng.normal(0, 0.02, s.shape) / 20) * np.exp(1j * np.radians(rng.normal(0, 0.2, s.shape))) + floor


def test_nonmagnetic_fit_is_stable_where_nrw_is_not():
    """A 10 mm PTFE sample is half a wavelength thick near 10.35 GHz.  With VNA-like noise NRW's eps' is off by more
    than 0.3 there (0.42-1.32 over seeds 0-5), while the mu = 1 fit of S11 and S21 stays within 0.016 (0.006-0.0145);
    fitting S11 alone gives 0.017-0.025, so both measurements are needed."""
    from coating_studio.materials.extraction import nonmagnetic

    f = np.linspace(2e9, 18e9, 401)
    eps, mu = ConstantMaterial("ptfe", 2.1, 0.0005).eps_mu(f, None)
    d = 10e-3
    s11, s21 = slab_sparams(f, eps, mu, d)
    exact = nonmagnetic(f, s11, s21, d)
    assert np.max(np.abs(exact.eps - eps)) < 1e-12 and np.all(exact.mu == 1) and not exact.warnings
    rng = np.random.default_rng(0)
    n11, n21 = _noisy(s11, rng), _noisy(s21, rng)
    near = np.abs(f - C0 / (2 * d * np.sqrt(2.1))) < 0.4e9
    err_nrw = np.abs(nrw(f, n11, n21, d).eps.real - 2.1)
    err_fit = np.abs(nonmagnetic(f, n11, n21, d).eps.real - 2.1)
    assert err_nrw[near].max() > 0.3 and err_fit[near].max() < 0.016
    assert np.median(err_fit[~near]) < 1.2 * np.median(err_nrw[~near])


def test_nonmagnetic_fit_flags_a_magnetic_sample_and_works_in_a_waveguide():
    from coating_studio.materials.extraction import nonmagnetic

    f = np.linspace(8e9, 12e9, 41)
    fc = C0 / (2 * 22.86e-3)
    eps, mu = ConstantMaterial("d", 4.0, 0.1).eps_mu(f, None)
    s11, s21 = slab_sparams(f, eps, mu, 3e-3, fc)
    assert np.max(np.abs(nonmagnetic(f, s11, s21, 3e-3, cutoff_hz=fc).eps - eps)) < 1e-10
    eps, mu = LOSSY.eps_mu(f, None)
    s11, s21 = slab_sparams(f, eps, mu, 2e-3)
    assert "fit_poor" in {c for c, _ in nonmagnetic(f, s11, s21, 2e-3).warnings}


def test_cli_method_option(tmp_path):
    from coating_studio.cli.commands import cmd_extract_nrw

    f = np.linspace(2e9, 18e9, 81)
    eps, mu = ConstantMaterial("ptfe", 2.1, 0.0005).eps_mu(f, None)
    s11, s21 = slab_sparams(f, eps, mu, 10e-3)
    src = tmp_path / "p.s2p"
    src.write_text(_s2p_text(f, s11, s21))
    res = cmd_extract_nrw(str(src), 10.0, str(tmp_path / "p.csv"), method="nonmagnetic",
                          uncertainty_csv=str(tmp_path / "u.csv"), mag_sigma_db=0.02, uncertainty_samples=20)
    assert res.result["method"] == "nonmagnetic" and res.result["uncertainty"]["n_samples"] == 20
    tab = load_csv(str(tmp_path / "p.csv"), name="p")
    assert np.max(np.abs(tab.eps_mu(f, None)[0] - eps)) < 1e-7


def test_coax_gap_correction():
    """Radial layers of a coax are capacitors in series (eps) and inductors in series (mu) per unit length; the
    correction inverts that composition, is the identity without gaps, and raises a gap-lowered eps'."""
    from coating_studio.materials.extraction import coax_gap_correction

    r1, r2, r3, r4 = 1.52, 1.53, 3.49, 3.50  # APC-7 with 10 um gaps on both sides [mm]
    eps_c, mu_c = np.array([10.0 - 0.5j, 3.0 - 0.01j]), np.array([2.0 - 0.3j, 1.0 + 0j])
    # forward: elastance (1/C) and inductance of each layer, summed over the radial layers
    layers = [(r1, r2, 1.0, 1.0), (r2, r3, None, None), (r3, r4, 1.0, 1.0)]
    for k in range(2):
        el = sum(np.log(b / a) / (eps_c[k] if e is None else e) for a, b, e, _ in layers)
        ind = sum(np.log(b / a) * (mu_c[k] if m is None else m) for a, b, _, m in layers)
        eps_m, mu_m = np.log(r4 / r1) / el, ind / np.log(r4 / r1)
        e2, m2 = coax_gap_correction(eps_m, mu_m, r1, r2, r3, r4)
        assert abs(e2 - eps_c[k]) < 1e-12 * abs(eps_c[k]) and abs(m2 - mu_c[k]) < 1e-12 * abs(mu_c[k])
        assert eps_m.real < eps_c[k].real  # the gaps lower the apparent permittivity
    e0, m0 = coax_gap_correction(eps_c, mu_c, r1, r1, r4, r4)
    assert np.allclose(e0, eps_c, rtol=1e-15) and np.allclose(m0, mu_c, rtol=1e-15)
    with pytest.raises(ValueError):
        coax_gap_correction(10.0, 1.0, 1.52, 1.40, 3.49, 3.50)  # bore smaller than the conductor
    with pytest.raises(ValueError, match="ill-conditioned"):
        coax_gap_correction(200.0, 1.0, 1.52, 1.62, 3.40, 3.50)  # large eps with a large gap


def test_cli_coax_gap(tmp_path):
    from coating_studio.cli.commands import cmd_extract_nrw
    from coating_studio.cli.output import CliError

    f = np.linspace(2e9, 18e9, 41)
    eps, mu = LOSSY.eps_mu(f, None)
    s11, s21 = slab_sparams(f, eps, mu, 2e-3)
    src = tmp_path / "c.s2p"
    src.write_text(_s2p_text(f, s11, s21))
    gap = [1.52, 1.53, 3.49, 3.50]
    res = cmd_extract_nrw(str(src), 2.0, str(tmp_path / "c.csv"), coax_gap=gap, uncertainty_csv=str(tmp_path / "u.csv"),
                          thickness_sigma_mm=0.01, uncertainty_samples=20)
    assert res.result["coax_gap_mm"] == gap
    from coating_studio.materials.extraction import coax_gap_correction

    want, _ = coax_gap_correction(eps, mu, *gap)
    got = load_csv(str(tmp_path / "c.csv"), name="c").eps_mu(f, None)[0]
    assert np.max(np.abs(got - want) / np.abs(want)) < 1e-7
    with pytest.raises(CliError):
        cmd_extract_nrw(str(src), 2.0, str(tmp_path / "d.csv"), coax_gap=gap, waveguide_a_mm=22.86)
