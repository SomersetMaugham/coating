"""Model diagnostics shared by the GUI's diagnostics panel and the report (no Qt).

The coverage matches ``coating-cli check``: every material the design uses, including optimisation candidates
and mixture constituents, plus the mixing-model range and the Rozanov feasibility hint of each target.
"""

from __future__ import annotations

import numpy as np

from coating_studio.i18n import issue_text
from coating_studio.limits import limit_issues, mixture_range_issues, sheet_proximity_issues, target_limits
from coating_studio.materials.checks import check_material


def collect(project, f):
    """([(level, text)] problems with level "error" | "warning", [text] informational notes) on grid ``f``."""
    p = project
    names = [n for n in p.used_materials() if n in p.materials]
    problems, notes = [], []
    unit = p.sweep.spectral_unit  # frequencies in the messages follow the project's spectral display unit
    for n in names:
        for iss in check_material(p.materials[n], f, p.resolver):
            text = f"{n}: {issue_text(iss, unit=unit)}"
            if iss.level == "info":
                notes.append(text)
            else:
                problems.append(("error" if iss.level == "error" else "warning", text))
    s = p.sweep
    extra = mixture_range_issues(p, float(np.sqrt(s.f_min * s.f_max)), names=set(names))
    try:
        extra += [iss for _ti, iss in limit_issues(target_limits(p))]
    except Exception:  # noqa: BLE001 - the feasibility hint must never break the diagnostics
        pass
    for iss in extra:
        msg = issue_text(iss, unit=unit)
        problems.append(("warning", f"{iss.material}: {msg}" if iss.material else msg))
    for iss in sheet_proximity_issues(p, s.f_max):
        if iss.level == "info":
            notes.append(issue_text(iss, unit=unit))
        else:
            problems.append(("warning", issue_text(iss, unit=unit)))
    return problems, notes
