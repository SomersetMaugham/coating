"""Every string passed to tr() must have a Korean translation with matching placeholders."""

import ast
import pathlib
import string

from coating_studio.i18n import _ISSUES_EN, _ISSUES_SPECTRAL
from coating_studio.i18n_ko import KO

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "coating_studio"
INDIRECT = ["Constant", "Dispersive model", "Measured data", "Mixture (EMA)", "Power law", "Uniaxial (in-plane / normal)", "Salisbury screen",
            "Dallenbach layer", "Two-layer Jaumann", "Ferrite tile", "Carbon / epoxy mixture",
            "Before optimisation", "Dual-band Jaumann (X + Ku, oblique)",
            "Circuit-analog absorber (RLC sheet)", "Frequency", "Wavelength", "Wavenumber"]


def _strings():
    out = set(INDIRECT) | set(_ISSUES_EN.values()) | set(_ISSUES_SPECTRAL.values())
    for p in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "tr" and node.args:
                a = node.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    out.add(a.value)
    return out


def _fields(s):
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


def test_all_strings_translated():
    missing = sorted(s for s in _strings() if s not in KO)
    assert not missing, missing


def test_placeholders_match():
    bad = [k for k, v in KO.items() if _fields(k) != _fields(v)]
    assert not bad, bad
