"""Physics engine: no GUI dependencies.  All quantities are SI internally."""

from coating_studio.core.constants import C0, EPS0, ETA0, MU0
from coating_studio.core.csqrt import kz_sqrt
from coating_studio.core.structure import Backing, SheetLayer, SlabLayer, Structure, new_uid
from coating_studio.core.solver import PolarizationResult, SolveResult, solve

__all__ = [
    "C0", "EPS0", "ETA0", "MU0", "kz_sqrt",
    "Backing", "SheetLayer", "SlabLayer", "Structure", "new_uid",
    "PolarizationResult", "SolveResult", "solve",
]
