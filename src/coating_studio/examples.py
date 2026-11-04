"""Bundled example projects (built in code so they always match the current schema)."""

from __future__ import annotations

from coating_studio.core.constants import C0
from coating_studio.core.structure import Backing, SheetLayer, SlabLayer, Structure
from coating_studio.project import (
    ContinuousVariable, MaterialChoice, OptimizationSettings, Project, SweepSettings,
)


def salisbury(f0=10e9):
    """377 Ohm/sq sheet a quarter wavelength (in the foam) above a metal plate."""
    p = Project(name="Salisbury screen")
    eps_foam = p.materials["PMI foam"].eps_re
    d = C0 / f0 / 4 / eps_foam ** 0.5
    p.structure = Structure(layers=[SheetLayer(376.73, 0.0, name="Resistive sheet"),
                                    SlabLayer("PMI foam", d, name="Spacer")],
                            backing=Backing("pec"))
    p.sweep = SweepSettings(f_min=2e9, f_max=18e9, f_at=f0)
    p.optimization = OptimizationSettings(
        f_min=8e9, f_max=12e9,
        variables=[ContinuousVariable(("layer", p.structure.layers[0].uid, "R"), 100.0, 2000.0),
                   ContinuousVariable(("layer", p.structure.layers[1].uid, "thickness"), 2e-3, 15e-3)])
    p.notes = "Classic narrow-band absorber: Gamma = 0 at the design frequency for normal incidence."
    return p


def dallenbach():
    """Single homogeneous magnetic-composite layer on metal."""
    p = Project(name="Dallenbach layer")
    p.structure = Structure(layers=[SlabLayer("Carbonyl iron / epoxy", 1.7e-3, name="Absorber")],
                            backing=Backing("pec"))
    p.sweep = SweepSettings(f_min=1e9, f_max=18e9)
    uid = p.structure.layers[0].uid
    p.optimization = OptimizationSettings(
        f_min=8e9, f_max=12e9, w_worst=1.0, w_thickness=0.2,
        variables=[ContinuousVariable(("layer", uid, "thickness"), 0.3e-3, 6e-3)])
    return p


def jaumann2():
    """Two resistive sheets with quarter-wave foam spacers (broadband Jaumann)."""
    p = Project(name="Two-layer Jaumann")
    eps_foam = p.materials["PMI foam"].eps_re
    d = C0 / 10e9 / 4 / eps_foam ** 0.5
    s1, sp1 = SheetLayer(1100.0, name="Front sheet"), SlabLayer("PMI foam", d, name="Spacer 1")
    s2, sp2 = SheetLayer(300.0, name="Back sheet"), SlabLayer("PMI foam", d, name="Spacer 2")
    p.structure = Structure(layers=[s1, sp1, s2, sp2], backing=Backing("pec"))
    p.sweep = SweepSettings(f_min=2e9, f_max=20e9)
    p.optimization = OptimizationSettings(
        f_min=6e9, f_max=16e9, n_f=51,
        variables=[ContinuousVariable(("layer", s1.uid, "R"), 100.0, 3000.0),
                   ContinuousVariable(("layer", s2.uid, "R"), 50.0, 2000.0),
                   ContinuousVariable(("layer", sp1.uid, "thickness"), 2e-3, 12e-3),
                   ContinuousVariable(("layer", sp2.uid, "thickness"), 2e-3, 12e-3)])
    return p


def ferrite_tile():
    """Sintered NiZn ferrite tile on metal: VHF/UHF absorber."""
    p = Project(name="Ferrite tile")
    p.structure = Structure(layers=[SlabLayer("NiZn ferrite", 6.0e-3, name="Ferrite tile")],
                            backing=Backing("pec"))
    p.sweep = SweepSettings(f_min=10e6, f_max=2e9, log_f=True, n_f=401, f_at=300e6)
    p.optimization = OptimizationSettings(
        f_min=30e6, f_max=1e9, w_worst=1.0,
        variables=[ContinuousVariable(("layer", p.structure.layers[0].uid, "thickness"), 2e-3, 12e-3)])
    p.tolerance.target_db = -10.0
    return p


def carbon_mixture():
    """Carbon black in epoxy (Bruggeman) with a material-choice example."""
    p = Project(name="Carbon / epoxy mixture")
    ly = SlabLayer("Carbon / epoxy 5 vol%", 3.0e-3, name="Lossy layer")
    p.structure = Structure(layers=[ly], backing=Backing("pec"))
    p.sweep = SweepSettings(f_min=2e9, f_max=18e9)
    p.optimization = OptimizationSettings(
        f_min=8e9, f_max=12e9, w_worst=1.0, w_mass=0.1,
        variables=[ContinuousVariable(("layer", ly.uid, "thickness"), 0.5e-3, 8e-3),
                   ContinuousVariable(("material", "Carbon / epoxy 5 vol%", "fraction"), 0.005, 0.3)],
        choices=[])
    return p


EXAMPLES = {
    "salisbury": ("Salisbury screen", salisbury),
    "dallenbach": ("Dallenbach layer", dallenbach),
    "jaumann2": ("Two-layer Jaumann", jaumann2),
    "ferrite": ("Ferrite tile", ferrite_tile),
    "carbon": ("Carbon / epoxy mixture", carbon_mixture),
}

__all__ = ["EXAMPLES", "MaterialChoice"]
