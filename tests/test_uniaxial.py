"""Uniaxial materials (optic axis = layer normal): solver physics, material plumbing and limits."""

import numpy as np
import pytest
from scipy.linalg import expm

from coating_studio.core import Backing, SlabLayer, Structure, solve
from coating_studio.core.solver import SolverError
from coating_studio.limits import data_range, static_permeability
from coating_studio.materials import (
    ConstantMaterial, DispersiveMaterial, MixtureMaterial, UniaxialMaterial, make_term, material_from_dict,
)
from coating_studio.materials.checks import check_material
from coating_studio.project import Project

AIR = ConstantMaterial("Air", 1.0, 0.0)


def _mats(*ms):
    return {m.name: m for m in (AIR, *ms)}


def _berreman_gamma(layers, mats, f, theta_deg, pol):
    """Reference Gamma of a stack on PEC from Maxwell's equations directly: 4x4 Berreman matrices of each layer,
    exp(-j k0 d M) by scipy's expm, PEC at the back.  Independent of the solver's kz branch and impedance recursion.
    Each layer: (material name, thickness); a uniaxial material gives (et, et, ez), (mt, mt, mz)."""
    out = []
    for fk in np.atleast_1d(f):
        k0 = 2 * np.pi * fk / 299792458.0
        xi = np.sin(np.deg2rad(theta_deg))
        P = np.eye(4, dtype=complex)
        for name, d in layers:
            m = mats[name]
            et, mt = (np.complex128(v) for v in m.eps_mu(np.array([fk]), mats.__getitem__))
            nz = m.eps_mu_normal(np.array([fk]), mats.__getitem__)
            ez, mz = (et, mt) if nz is None else (np.complex128(v) for v in nz)
            et, mt, ez, mz = (complex(np.ravel(v)[0]) for v in (et, mt, ez, mz))
            # psi = (Ex, eta0 Hy, Ey, eta0 Hx); d psi / dz = -j k0 M psi
            M = np.array([[0, mt - xi ** 2 / ez, 0, 0], [et, 0, 0, 0],
                          [0, 0, 0, -mt], [0, 0, -(et - xi ** 2 / mz), 0]], dtype=complex)
            P = expm(-1j * k0 * d * M) @ P
        c = np.cos(np.deg2rad(theta_deg))
        if pol == "TM":  # air: forward Hy = Ex / cos, backward Hy = -Ex / cos; PEC: Ex(back) = 0
            a, b = P[0, 0], P[0, 1] / c
        else:  # TE: forward Hx = -cos Ey, backward Hx = +cos Ey; PEC: Ey(back) = 0
            a, b = P[2, 2], -P[2, 3] * c
        out.append(-(a + b) / (a - b))  # a (1 + G) + b (1 - G) = 0
    return np.array(out)


def _flake():
    inp = DispersiveMaterial("CIP in-plane", eps_inf=12.0, eps_loss=0.4,
                             mu_terms=[make_term("lorentz", 3.0, 4e9, 3e9)], mu_inf=1.2)
    nrm = DispersiveMaterial("CIP normal", eps_inf=6.0, eps_loss=0.2, mu_terms=[make_term("debye", 0.4, 9e9)])
    return inp, nrm, UniaxialMaterial("CIP flakes", "CIP in-plane", "CIP normal")


@pytest.mark.parametrize("pol", ["TE", "TM"])
@pytest.mark.parametrize("theta", [0.0, 30.0, 70.0])
def test_matches_berreman_reference(pol, theta):
    inp, nrm, uni = _flake()
    spacer = ConstantMaterial("Spacer", 2.2, 0.01)
    mats = _mats(inp, nrm, uni, spacer)
    s = Structure(layers=[SlabLayer("Spacer", 0.4e-3), SlabLayer("CIP flakes", 1.3e-3)], backing=Backing("pec"))
    f = np.linspace(2e9, 18e9, 9)
    got = solve(s, mats, f, theta, pols=(pol,)).pol[pol].gamma[:, 0]
    ref = _berreman_gamma([("Spacer", 0.4e-3), ("CIP flakes", 1.3e-3)], mats, f, theta, pol)
    assert np.max(np.abs(got - ref)) < 1e-9
    if theta > 0:  # the normal components matter at oblique incidence
        iso = solve(Structure(layers=[SlabLayer("Spacer", 0.4e-3), SlabLayer("CIP in-plane", 1.3e-3)],
                              backing=Backing("pec")), mats, f, theta, pols=(pol,)).pol[pol].gamma[:, 0]
        assert np.max(np.abs(got - iso)) > 1e-3


@pytest.mark.parametrize("pol", ["TE", "TM"])
def test_uniaxial_brewster_angle(pol):
    """Air onto a lossless uniaxial half-space: R = 0 at sin^2 = ez (et - 1) / (et ez - 1) in TM (mu = 1), and
    at the dual mz (mt - 1) / (mt mz - 1) in TE (eps = 1) (Born & Wolf; Yeh, Optical Waves in Layered Media)."""
    if pol == "TM":
        t, z = 4.0, 2.5
        mats = _mats(ConstantMaterial("T", t, 0.0), ConstantMaterial("Z", z, 0.0), UniaxialMaterial("U", "T", "Z"))
    else:
        t, z = 3.0, 1.8
        mats = _mats(ConstantMaterial("T", 1.0, 0.0, t, 0.0), ConstantMaterial("Z", 1.0, 0.0, z, 0.0),
                     UniaxialMaterial("U", "T", "Z"))
    theta_b = np.rad2deg(np.arcsin(np.sqrt(z * (t - 1) / (t * z - 1))))
    s = Structure(layers=[], backing=Backing("halfspace", "U"))
    r = solve(s, mats, [5e9], [theta_b - 5, theta_b, theta_b + 5], pols=(pol,)).pol[pol].R[0]
    assert r[1] < 1e-28 and r[0] > 1e-4 and r[2] > 1e-4


def test_isotropic_cases_are_exact():
    """A uniaxial material whose two components are the same material, and any uniaxial layer at normal incidence,
    give the isotropic result bit for bit."""
    inp, nrm, uni = _flake()
    same = UniaxialMaterial("Same", "CIP in-plane", "CIP in-plane")
    mats = _mats(inp, nrm, uni, same)
    f = np.linspace(1e9, 20e9, 40)
    th = np.array([0.0, 40.0, 75.0])
    lay = lambda n: Structure(layers=[SlabLayer(n, 1.5e-3)], backing=Backing("pec"))  # noqa: E731
    a, b = solve(lay("Same"), mats, f, th), solve(lay("CIP in-plane"), mats, f, th)
    for pol in ("TE", "TM"):
        assert np.array_equal(a.pol[pol].gamma, b.pol[pol].gamma)
        assert np.array_equal(a.pol[pol].A_layers, b.pol[pol].A_layers)
    c = solve(lay("CIP flakes"), mats, f, 0.0)
    for pol in ("TE", "TM"):
        assert np.array_equal(c.pol[pol].gamma, b.pol[pol].gamma[:, :1])


def test_energy_balance_with_uniaxial_backing():
    inp, nrm, uni = _flake()
    mats = _mats(inp, nrm, uni)
    s = Structure(layers=[SlabLayer("CIP flakes", 0.8e-3), SlabLayer("CIP in-plane", 0.3e-3)],
                  backing=Backing("halfspace", "CIP flakes"))
    res = solve(s, mats, np.linspace(1e9, 18e9, 30), [0.0, 35.0, 80.0])
    for pol in ("TE", "TM"):
        p = res.pol[pol]
        assert np.max(np.abs(p.R + p.T + p.A - 1.0)) < 1e-12
        assert np.all(p.A_layers > -1e-12)


def test_layer_tolerance_factors_scale_both_components():
    inp, nrm, uni = _flake()
    mats = _mats(inp, nrm, uni)
    s = Structure(layers=[SlabLayer("CIP flakes", 1.0e-3, uid="L")], backing=Backing("pec"))
    f = np.linspace(2e9, 12e9, 7)
    pert = solve(s, mats, f, 50.0, perturb={"L": {"eps": 1.1, "mu": 0.9}})
    scaled = _mats(DispersiveMaterial("CIP in-plane", eps_inf=13.2, eps_loss=0.44,
                                      mu_terms=[make_term("lorentz", 2.7, 4e9, 3e9)], mu_inf=1.08),
                   DispersiveMaterial("CIP normal", eps_inf=6.6, eps_loss=0.22, mu_inf=0.9,
                                      mu_terms=[make_term("debye", 0.36, 9e9)]),
                   uni)
    ref = solve(s, scaled, f, 50.0)
    for pol in ("TE", "TM"):
        assert np.max(np.abs(pert.pol[pol].gamma - ref.pol[pol].gamma)) < 1e-12


def test_misuse_is_reported():
    inp, nrm, uni = _flake()
    mix = MixtureMaterial("Mix", "Air", "CIP flakes", 0.2)
    nested = UniaxialMaterial("Nested", "CIP flakes", "CIP normal")
    mats = _mats(inp, nrm, uni, mix, nested)
    for m in (mix, nested):
        assert [i.code for i in check_material(m, [1e9], mats.__getitem__)] == ["uniaxial_misuse"]
    with pytest.raises(ValueError):
        solve(Structure(layers=[SlabLayer("Mix", 1e-3)], backing=Backing("pec")), mats, [1e9])
    with pytest.raises(SolverError, match="isotropic"):
        solve(Structure(layers=[], backing=Backing("pec"), incident="CIP flakes"), mats, [1e9])
    assert check_material(uni, [1e9], mats.__getitem__) == []


def test_project_plumbing():
    inp, nrm, uni = _flake()
    p = Project()
    for m in (inp, nrm, uni):
        p.add_material(m)
    p.structure = Structure(layers=[SlabLayer("CIP flakes", 1e-3)], backing=Backing("pec"))
    d = uni.to_dict()
    assert d == {"kind": "uniaxial", "name": "CIP flakes", "note": "", "inplane": "CIP in-plane", "normal": "CIP normal"}
    assert material_from_dict(d).to_dict() == d
    assert uni.get_density(p.resolver) == inp.density
    q = Project.from_dict(p.to_dict())
    assert q.materials["CIP flakes"].to_dict() == d
    q.rename_material("CIP normal", "CIP z")
    assert q.materials["CIP flakes"].normal == "CIP z"
    paths = {path for path, _, _ in __import__("coating_studio.project", fromlist=["x"]).available_params(q)}
    assert ("material", "CIP z", "mu_terms", 0, "f0") in paths  # components are optimisable through the reference
    # Rozanov: normal incidence sees the in-plane static permeability
    assert static_permeability(uni, p.resolver) == static_permeability(inp, p.resolver)
    assert data_range(uni, p.resolver) is None
