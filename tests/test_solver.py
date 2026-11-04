"""Engine validation against analytic results."""

import numpy as np
import pytest

from coating_studio.core import ETA0, Backing, SheetLayer, SlabLayer, Structure, kz_sqrt, solve
from coating_studio.core.constants import C0
from coating_studio.materials import ConstantMaterial, DispersiveMaterial, make_term


def mats(*extra):
    d = {"Air": ConstantMaterial("Air", 1.0, 0.0)}
    for m in extra:
        d[m.name] = m
    return d


def test_kz_sqrt_branch():
    z = kz_sqrt(np.array([4.0, -4.0, 4 - 1j, -4 - 1e-9j, -4 + 0j]))
    assert np.all(z.imag <= 0)
    assert z[0] == pytest.approx(2.0)
    assert z[1] == pytest.approx(-2j)
    assert z[4] == pytest.approx(-2j)


def test_salisbury_perfect_absorption():
    f0 = 10e9
    d = C0 / f0 / 4
    s = Structure(layers=[SheetLayer(ETA0), SlabLayer("Air", d)], backing=Backing("pec"))
    res = solve(s, mats(), [f0], 0.0)
    for pol in ("TE", "TM"):
        assert abs(res.pol[pol].gamma[0, 0]) < 1e-9
        assert res.pol[pol].A_layers[0, 0, 0] == pytest.approx(1.0, abs=1e-9)  # all in the sheet
        assert res.pol[pol].A_layers[1, 0, 0] == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("theta", [0.0, 30.0, 60.0, 85.0])
def test_fresnel_single_interface(theta):
    n = 1.5
    glass = ConstantMaterial("Glass", n * n, 0.0)
    s = Structure(layers=[], backing=Backing("halfspace", "Glass"))
    res = solve(s, mats(glass), [1e9], theta)
    ti = np.deg2rad(theta)
    ct = np.sqrt(1 - (np.sin(ti) / n) ** 2)
    ci = np.cos(ti)
    rs = (ci - n * ct) / (ci + n * ct)
    rp = (n * ci - ct) / (n * ci + ct)
    assert res.pol["TE"].R[0, 0] == pytest.approx(rs ** 2, rel=1e-9, abs=1e-12)
    assert res.pol["TM"].R[0, 0] == pytest.approx(rp ** 2, rel=1e-9, abs=1e-12)
    for pol in ("TE", "TM"):
        p = res.pol[pol]
        assert p.R[0, 0] + p.T[0, 0] == pytest.approx(1.0, abs=1e-12)


def test_brewster_angle_tm_zero():
    n = 2.0
    s = Structure(layers=[], backing=Backing("halfspace", "D"))
    res = solve(s, mats(ConstantMaterial("D", n * n)), [1e9], np.rad2deg(np.arctan(n)))
    assert res.pol["TM"].R[0, 0] < 1e-20


def test_lossless_energy_conservation_multilayer():
    m1, m2 = ConstantMaterial("A", 2.2), ConstantMaterial("B", 6.0, 0.0, 1.5, 0.0)
    s = Structure(layers=[SlabLayer("A", 3e-3), SlabLayer("B", 1.2e-3), SlabLayer("A", 5e-3)],
                  backing=Backing("halfspace", "B"))
    f = np.linspace(1e9, 30e9, 50)
    res = solve(s, mats(m1, m2), f, np.array([0, 20, 45, 70]))
    for pol in ("TE", "TM"):
        p = res.pol[pol]
        np.testing.assert_allclose(p.R + p.T, 1.0, atol=1e-10)
        np.testing.assert_allclose(p.A_layers, 0.0, atol=1e-10)


def test_lossy_energy_conservation_with_sheets():
    lossy = DispersiveMaterial("L", eps_inf=4, sigma=0.5, eps_terms=[make_term("debye", 3, 5e9)],
                               mu_terms=[make_term("lorentz", 2, 3e9, 4e9)])
    sub = ConstantMaterial("S", 3.0, 0.2)
    s = Structure(layers=[SheetLayer(500, 80), SlabLayer("L", 1.5e-3), SheetLayer(200, -40),
                          SlabLayer("Air", 4e-3)], backing=Backing("halfspace", "S"))
    f = np.linspace(0.5e9, 25e9, 60)
    res = solve(s, mats(lossy, sub), f, np.array([0, 40, 75]))
    for pol in ("TE", "TM"):
        p = res.pol[pol]
        np.testing.assert_allclose(p.R + p.T + p.A, 1.0, atol=1e-10)
        assert np.all(p.A_layers >= -1e-12)


def test_normal_incidence_te_equals_tm():
    lossy = DispersiveMaterial("L", eps_inf=7, eps_loss=1.2, mu_terms=[make_term("debye", 4, 2e9)])
    s = Structure(layers=[SheetLayer(800), SlabLayer("L", 2e-3)], backing=Backing("pec"))
    res = solve(s, mats(lossy), np.linspace(1e9, 18e9, 30), 0.0)
    np.testing.assert_allclose(res.pol["TE"].R, res.pol["TM"].R, rtol=1e-12)


def test_dallenbach_matched_layer():
    # eps = mu (complex) -> intrinsic impedance equals free space; thick enough -> no reflection
    m = ConstantMaterial("M", 3.0, 2.0, 3.0, 2.0)
    s = Structure(layers=[SlabLayer("M", 0.2)], backing=Backing("pec"))
    res = solve(s, mats(m), [10e9], 0.0)
    assert res.pol["TE"].R[0, 0] < 1e-12


def test_dallenbach_analytic_input_impedance():
    eps, mu, d, f = complex(10, -2), complex(1.5, -0.8), 1.7e-3, 9e9
    m = ConstantMaterial("M", eps.real, -eps.imag, mu.real, -mu.imag)
    s = Structure(layers=[SlabLayer("M", d)], backing=Backing("pec"))
    res = solve(s, mats(m), [f], 0.0)
    k = 2 * np.pi * f / C0 * np.sqrt(eps * mu)
    zin = np.sqrt(mu / eps) * 1j * np.tan(k * d)
    gamma = (zin - 1) / (zin + 1)
    assert res.pol["TE"].gamma[0, 0] == pytest.approx(gamma, rel=1e-10)


def test_total_internal_reflection_no_gain():
    dense = ConstantMaterial("Dense", 4.0)
    s = Structure(layers=[SlabLayer("Air", 3e-3)], backing=Backing("halfspace", "Air"),
                  incident="Dense")
    res = solve(s, mats(dense), np.linspace(1e9, 40e9, 20), np.array([40.0, 60.0, 80.0]))
    for pol in ("TE", "TM"):
        p = res.pol[pol]
        np.testing.assert_allclose(p.R, 1.0, atol=1e-10)
        np.testing.assert_allclose(p.T, 0.0, atol=1e-12)


def test_thick_very_lossy_layer_is_stable():
    m = DispersiveMaterial("Metalish", eps_inf=10, sigma=1e5)
    s = Structure(layers=[SlabLayer("Metalish", 0.5)], backing=Backing("pec"))
    with np.errstate(over="raise", invalid="raise", divide="raise", under="ignore"):
        res = solve(s, mats(m), np.geomspace(1e8, 1e12, 30), np.array([0.0, 70.0]))
    for pol in ("TE", "TM"):
        p = res.pol[pol]
        assert np.all(np.isfinite(p.gamma))
        np.testing.assert_allclose(p.R + p.A, 1.0, atol=1e-9)


def test_frequency_angle_broadcast_shape():
    s = Structure(layers=[SlabLayer("Air", 1e-3)], backing=Backing("pec"))
    res = solve(s, mats(), np.linspace(1e9, 2e9, 7), np.linspace(0, 80, 5))
    assert res.pol["TE"].R.shape == (7, 5)
    assert res.pol["TM"].A_layers.shape == (1, 7, 5)
