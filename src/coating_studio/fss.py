"""Equivalent L or C of a dense metal mesh or patch array from its dimensions (no Qt).

Luukkonen et al., IEEE TAP 56, 1624 (2008), eqs. 3-9.  Valid for dense square lattices of ideal conductors under
incidence in a principal plane; docs/CLI_PLAN.md, section 13.10 has the limits and why they are set where they are.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from coating_studio.core.constants import C0, EPS0, MU0
from coating_studio.core.structure import SheetLayer, angle_preset_coeffs

PATTERNS = ("mesh", "patch")
CAUTION_RATIO = 0.3  # of c / (D sqrt(eps_eff)): a rule of thumb for the leading-order formula
LIMIT_RATIO = 0.5  # below every grating lobe when eps_eff = (eps_r + 1) / 2, at any angle
WIDE_RATIO = 0.5  # the formulas are derived for w << D


@dataclass
class GridElement:
    pattern: str
    period: float  # m
    width: float  # m: strip width of a mesh, gap between patches
    eps_eff: float
    L: float | None  # H, mesh only
    C: float | None  # F, patch only
    angle: dict
    caution_hz: float
    limit_hz: float

    @property
    def width_ratio(self) -> float:
        return self.width / self.period

    @property
    def wide(self) -> bool:
        return self.width_ratio > WIDE_RATIO


def grid_element(pattern, period, width, eps_eff) -> GridElement:
    """L of a mesh or C of a patch array.  Raises ValueError for dimensions the formulas cannot describe."""
    if pattern not in PATTERNS:
        raise ValueError(f"unknown pattern {pattern!r}")
    if not all(math.isfinite(x) for x in (period, width, eps_eff)):
        raise ValueError("the dimensions and the permittivity must be finite")
    if not 0 < width < period:
        raise ValueError("the width must be positive and smaller than the period")
    if eps_eff < 1:
        raise ValueError("the effective permittivity must be at least 1")
    log_term = math.log(1.0 / math.sin(math.pi * width / (2.0 * period)))
    if pattern == "mesh":
        L, C = MU0 * period / (2.0 * math.pi) * log_term, None
    else:
        L, C = None, 2.0 * EPS0 * eps_eff * period / math.pi * log_term
    if not (L or C):  # width within rounding of the period
        raise ValueError("the width is too close to the period")
    scale = C0 / (period * math.sqrt(eps_eff))
    return GridElement(pattern, float(period), float(width), float(eps_eff), L, C,
                       angle_preset_coeffs(pattern, eps_eff), CAUTION_RATIO * scale, LIMIT_RATIO * scale)


def apply_to_sheet(sheet: SheetLayer, element: GridElement, keep_other=False) -> None:
    """Make ``sheet`` the mesh or patch.  Unless ``keep_other``, the other element and its coefficients go: a leftover
    reactance would no longer be the sheet the formula describes.  R stays the user's value."""
    coeffs = {k: v for k, v in (sheet.angle_dict() or {}).items()
              if keep_other and k.startswith("C" if element.pattern == "mesh" else "L")}
    if element.pattern == "mesh":
        sheet.L = element.L
        if not keep_other:
            sheet.C = None
    else:
        sheet.C = element.C
        if not keep_other:
            sheet.L = 0.0
    sheet.set_angle({**coeffs, **element.angle})
