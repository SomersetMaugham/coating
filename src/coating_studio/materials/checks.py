"""Passivity and realism checks for materials (warnings, never hard errors)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from coating_studio.materials.models import DispersiveMaterial, Material, OutOfRangeError

# Snoek's law: (mu_s - 1) * f_r <= (2/3) * gamma' * 4*pi*Ms,  gamma' = 2.8 MHz/Oe.
# Using pure iron (4*pi*Ms ~ 21.5 kG) as an upper bound gives ~40 GHz.
SNOEK_LIMIT_HZ = (2.0 / 3.0) * 2.8e6 * 21_500.0


@dataclass
class Issue:
    level: str  # "warning" | "error"
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
    except KeyError as e:
        return [Issue("error", "missing_reference", mat.name, {"ref": str(e)})]
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
    return issues
