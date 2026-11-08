"""Layer thicknesses in the project's display unit (``SweepSettings.length_unit``: mm, µm or nm).  Display only:
layers, files and the CLI keep metres / millimetres.  No Qt (the report uses it); see ``spectral.py`` for the
spectral axis, which is chosen independently."""

from __future__ import annotations

from coating_studio.core.units import (
    LENGTH_LABEL, NEW_SLAB_THICKNESS, ZERO_THICKNESS_RANGE, fmt_num, from_length, to_length,
)


def unit_of(project):
    return project.sweep.length_unit


def label(unit):
    return LENGTH_LABEL[unit]


def fmt_length(m, unit, digits=4):
    """'99.64 nm', '1.7 mm'."""
    return f"{fmt_num(to_length(m, unit), digits)} {LENGTH_LABEL[unit]}"


def display_unit(project, unit):
    """The display unit for a parameter whose own unit is ``unit``: thicknesses ("mm", the unit of the optimiser's
    parameter paths and the CLI) follow the project's length unit; other units are returned unchanged."""
    return project.sweep.length_unit if unit == "mm" else unit


def to_display_unit(si, project, unit):
    """SI value -> number in ``display_unit(project, unit)`` (non-length units: ``core.units.to_display``)."""
    from coating_studio.core.units import to_display

    return to_length(si, project.sweep.length_unit) if unit == "mm" else to_display(si, unit)


def from_display_unit(x, project, unit):
    from coating_studio.core.units import from_display

    return from_length(x, project.sweep.length_unit) if unit == "mm" else from_display(x, unit)


def new_slab_thickness(project):
    return NEW_SLAB_THICKNESS[project.sweep.length_unit]


def zero_thickness_range(project):
    """(lo, hi) [m] of an optimisation variable for a layer whose thickness is 0."""
    return ZERO_THICKNESS_RANGE[project.sweep.length_unit]
