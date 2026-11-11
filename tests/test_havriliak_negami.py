"""Havriliak-Negami dispersion terms: analytic values, passivity, causality, fitting and plumbing."""

import numpy as np
import pytest

from coating_studio.limits import static_permeability
from coating_studio.materials import DispersiveMaterial, make_term, material_from_dict
from coating_studio.materials.checks import check_material
from coating_studio.materials.fitting import FitSpec, fit_dispersive
from coating_studio.materials.models import eval_terms
from coating_studio.project import Project, available_params, set_param

HN = "havriliak_negami"


def test_reduces_to_debye_and_matches_cole_cole_and_cole_davidson():
    f = np.geomspace(1e7, 1e12, 200)
    d = 7.0
    assert np.max(np.abs(eval_terms([make_term(HN, d, 3e9, alpha=1.0, beta=1.0)], f)
                         - eval_terms([make_term("debye", d, 3e9)], f))) < 1e-14 * d
    for a in (0.3, 0.6, 0.9):  # Cole-Cole loss peak at f0: eps'' = (delta/2) tan(alpha pi / 4)
        v = eval_terms([make_term(HN, d, 3e9, alpha=a, beta=1.0)], np.array([3e9]))[0]
        assert -v.imag == pytest.approx(d / 2 * np.tan(a * np.pi / 4), rel=1e-12)
        assert v.real == pytest.approx(d / 2, rel=1e-12)  # symmetric: half the step at f0
    for b in (0.2, 0.5, 0.8):  # Cole-Davidson at f0: delta (1 + j)^-beta = delta 2^(-beta/2) e^(-j pi beta / 4)
        v = eval_terms([make_term(HN, d, 3e9, alpha=1.0, beta=b)], np.array([3e9]))[0]
        assert v == pytest.approx(d * 2 ** (-b / 2) * np.exp(-1j * np.pi * b / 4), rel=1e-12)


@pytest.mark.parametrize("a,b", [(0.2, 0.3), (0.5, 1.0), (1.0, 0.4), (0.8, 0.6)])
def test_passive_and_static_value(a, b):
    t = make_term(HN, 5.0, 1e9, alpha=a, beta=b)
    v = eval_terms([t], np.geomspace(1e-3, 1e21, 20001))
    assert np.all(-v.imag >= 0)  # passive (eps'' >= 0) for exponents in (0, 1]
    assert np.all(np.diff(v.real) <= 1e-12)  # a relaxation: eps' falls monotonically
    assert eval_terms([t], np.array([1e-30]))[0].real == pytest.approx(5.0, rel=1e-6)  # static value = delta


@pytest.mark.parametrize("a,b", [(0.5, 1.0), (1.0, 0.4), (0.8, 0.6), (0.6, 0.7)])
def test_kramers_kronig(a, b):
    """Causality: eps'(w) = (2/pi) PV int_0^inf x eps''(x) / (x^2 - w^2) dx (eps_inf = 0 for a bare term).  The pole
    is removed by subtracting w eps''(w), whose principal-value integral over (0, inf) is 0."""
    t = make_term(HN, 5.0, 1e9, alpha=a, beta=b)
    x = np.geomspace(1.0137e-8, 1.0137e24, 600001)  # offset so no grid point falls on w (0/0)
    loss = -eval_terms([t], x).imag
    for w in (3e8, 1e9, 4e9):
        lw = -eval_terms([t], np.array([w]))[0].imag
        g = (x * loss - w * lw) / (x * x - w * w)
        kk = 2 / np.pi * np.trapezoid(g * x, np.log(x))
        assert kk == pytest.approx(eval_terms([t], np.array([w]))[0].real, abs=1e-3 * 5.0)


def test_fit_recovers_havriliak_negami():
    true = DispersiveMaterial("T", eps_inf=3.0, eps_terms=[make_term(HN, 9.0, 2e9, alpha=0.7, beta=0.5)])
    f = np.geomspace(0.1e9, 40e9, 120)
    eps, mu = true.eps_mu(f, None)
    res = fit_dispersive("fit", f, eps, mu, FitSpec(0, 0, n_hn=1))
    t = res.material.eps_terms[0]
    assert res.rms_eps < 1e-6
    assert (t["alpha"], t["beta"]) == (pytest.approx(0.7, rel=1e-4), pytest.approx(0.5, rel=1e-4))
    assert t["f0"] == pytest.approx(2e9, rel=1e-4) and res.material.eps_inf == pytest.approx(3.0, rel=1e-4)
    # one Debye term cannot follow it; the broadened term is what makes the fit good
    assert fit_dispersive("d", f, eps, mu, FitSpec(1, 0)).rms_eps > 100 * res.rms_eps


def test_params_checks_and_plumbing():
    m = DispersiveMaterial("HN", eps_inf=2.5, mu_terms=[make_term(HN, 4.0, 1e9, alpha=0.6, beta=0.9)])
    keys = {p.key: p for p in m.params()}
    assert keys[("mu_terms", 0, "alpha")].upper == 1.0 and keys[("mu_terms", 0, "beta")].lower > 0
    assert material_from_dict(m.to_dict()).to_dict() == m.to_dict()
    assert static_permeability(m, None) == (pytest.approx(5.0), False)
    assert check_material(m, [1e9], None) == []
    m.mu_terms[0]["alpha"] = 1.3
    assert "hn_exponent" in {i.code for i in check_material(m, [1e9], None)}
    with pytest.raises(ValueError):
        make_term("cole_cole")
    p = Project()
    p.add_material(DispersiveMaterial("HN", eps_inf=2.5, mu_terms=[make_term(HN, 4.0, 1e9, alpha=0.6, beta=0.9)]))
    from coating_studio.core import Backing, SlabLayer, Structure

    p.structure = Structure(layers=[SlabLayer("HN", 1e-3)], backing=Backing("pec"))
    path = ("material", "HN", "mu_terms", 0, "beta")
    assert path in {q for q, _, _ in available_params(p)}
    set_param(p, path, 0.4)
    assert Project.from_dict(p.to_dict()).materials["HN"].mu_terms[0]["beta"] == 0.4


def test_cli_fit_takes_hn_terms(tmp_path):
    from coating_studio.cli.commands import cmd_fit

    true = DispersiveMaterial("T", eps_inf=3.0, eps_terms=[make_term(HN, 9.0, 2e9, alpha=0.7, beta=0.5)])
    f = np.geomspace(0.1e9, 40e9, 120)
    eps, _ = true.eps_mu(f, None)
    path = tmp_path / "m.csv"
    path.write_text("f,eps',eps''\n" + "".join(f"{a / 1e9:.17g},{e.real:.17g},{-e.imag:.17g}\n" for a, e in zip(f, eps)))
    r = cmd_fit(str(path), eps_debye=0, eps_hn=1)
    t = r.result["material"]["eps_terms"][0]
    assert t["type"] == HN and t["alpha"] == pytest.approx(0.7, rel=1e-4) and r.result["rms_eps"] < 1e-6
