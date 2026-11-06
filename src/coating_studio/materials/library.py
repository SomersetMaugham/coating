"""Built-in material library and user-library JSON storage.

The built-in values are *representative textbook-order values* for
demonstration.  They are not datasheet values for any commercial product;
replace them with measured data for real designs.
"""

from __future__ import annotations

import json

from coating_studio.materials.models import (
    ConstantMaterial, DispersiveMaterial, MixtureMaterial, make_term, material_from_dict,
)

LIBRARY_SCHEMA = 1


def builtin_materials():
    """Return a fresh list of built-in materials (Air first)."""
    return [
        ConstantMaterial("Air", 1.0, 0.0, density=1.2, note="vacuum / air"),
        ConstantMaterial("PTFE", 2.1, 0.0004, density=2200.0, note="representative"),
        ConstantMaterial("FR-4", 4.4, 0.088, density=1850.0, note="representative, tan d = 0.02"),
        ConstantMaterial("Epoxy", 3.6, 0.07, density=1200.0, note="representative resin"),
        ConstantMaterial("PMI foam", 1.07, 0.002, density=52.0, note="low-density spacer foam (representative)"),
        ConstantMaterial("Honeycomb (aramid)", 1.1, 0.004, density=48.0, note="representative"),
        DispersiveMaterial("Carbon black", eps_inf=12.0, sigma=200.0, density=1800.0,
                           note="conductive filler for mixtures (representative)"),
        DispersiveMaterial("NiZn ferrite", eps_inf=13.0, eps_loss=0.15,
                           mu_inf=1.0, mu_terms=[make_term("debye", delta=900.0, f0=6e6)],
                           density=5100.0, note="sintered ferrite tile, Snoek relaxation (representative)"),
        DispersiveMaterial("Carbonyl iron / epoxy", eps_inf=12.0, eps_loss=0.4,
                           mu_inf=1.0, mu_terms=[make_term("debye", delta=3.0, f0=3e9)],
                           density=3800.0, note="magnetic RAM composite (representative)"),
        MixtureMaterial("Carbon / epoxy", matrix="Epoxy", inclusion="Carbon black",
                        fraction=0.30, model="bruggeman", note="example mixture (30 vol% carbon black)"),
    ]


def save_library(path, materials):
    data = {"schema": LIBRARY_SCHEMA, "materials": [m.to_dict() for m in materials]}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def load_library(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return [material_from_dict(d) for d in data.get("materials", [])]
