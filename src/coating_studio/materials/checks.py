"""Passivity and realism checks for materials (warnings, never hard errors)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from coating_studio.materials.models import DispersiveMaterial, Material, MaterialCycleError, OutOfRangeError, PercolationError

# Snoek's law: (mu_s - 1) * f_r <= (2/3) * gamma' * 4*pi*Ms,  gamma' = 2.8 MHz/Oe.
# Using pure iron (4*pi*Ms ~ 21.5 kG) as an upper bound gives ~40 GHz.
SNOEK_LIMIT_HZ = (2.0 / 3.0) * 2.8e6 * 21_500.0


def _demo_signatures():
    from coating_studio.materials.library import builtin_materials

    sig = {}
    for m in builtin_materials():
        if m.name != "Air":  # vacuum is exact, not a demo value
            d = m.to_dict()
            d.pop("note", None)
            sig[m.name] = d
    return sig


_DEMO = None


def is_builtin_demo(mat: Material) -> bool:
    """True if ``mat`` still has the built-in demonstration values (name and numbers unchanged)."""
    global _DEMO
    if _DEMO is None:
        _DEMO = _demo_signatures()
    ref = _DEMO.get(mat.name)
    if ref is None:
        return False
    d = mat.to_dict()
    d.pop("note", None)
    return d == ref


@dataclass
class Issue:
    level: str  # "info" | "warning" | "error"
    code: str  # stable identifier; the GUI maps it to translated text
    material: str
    args: dict = field(default_factory=dict)

    def english(self) -> str:
        from coating_studio.i18n import issue_text

        return issue_text(self, lang="en")


def check_material(mat: Material, f, resolver) -> list[Issue]:
    issues = []
    f = np.atleast_1d(np.asarray(f, dtype=float))
    try:
        eps, mu = mat.eps_mu(f, resolver)
    except OutOfRangeError as e:
        return [Issue("error", "out_of_range", mat.name,
                      {"lo": e.data_lo / 1e9, "hi": e.data_hi / 1e9,
                       "flo": e.f_lo / 1e9, "fhi": e.f_hi / 1e9})]
    except PercolationError:
        return [Issue("error", "percolation_exceeded", mat.name, {"fraction": mat.fraction, "pc": mat.percolation})]
    except KeyError as e:
        return [Issue("error", "missing_reference", mat.name, {"ref": str(e)})]
    except MaterialCycleError:
        return [Issue("error", "material_cycle", mat.name, {})]
    eps = np.broadcast_to(eps, f.shape)
    mu = np.broadcast_to(mu, f.shape)
    tol = 1e-12
    if np.any(eps.imag > tol * np.maximum(np.abs(eps), 1)):
        i = int(np.argmax(eps.imag))
        issues.append(Issue("warning", "eps_gain", mat.name, {"f": f[i] / 1e9}))
    if np.any(mu.imag > tol * np.maximum(np.abs(mu), 1)):
        i = int(np.argmax(mu.imag))
        issues.append(Issue("warning", "mu_gain", mat.name, {"f": f[i] / 1e9}))
    if isinstance(mat, DispersiveMaterial):
        if mat.eps_inf < 1.0:
            issues.append(Issue("warning", "eps_inf_below_one", mat.name, {"value": mat.eps_inf}))
        for t in mat.mu_terms:
            prod = t["delta"] * t["f0"]
            if prod > SNOEK_LIMIT_HZ:
                issues.append(Issue("warning", "snoek", mat.name,
                                    {"product": prod / 1e9, "limit": SNOEK_LIMIT_HZ / 1e9}))
        for t in mat.eps_terms + mat.mu_terms:
            if t["delta"] < 0 or t["f0"] <= 0 or t.get("gamma", 1.0) < 0:
                issues.append(Issue("warning", "term_negative", mat.name, {}))
                break
    if np.any(eps.real > 1e4):
        issues.append(Issue("warning", "eps_huge", mat.name, {"value": float(eps.real.max())}))
    if is_builtin_demo(mat):
        issues.append(Issue("info", "demo_values", mat.name, {}))
    return issues
