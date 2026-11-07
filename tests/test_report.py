"""HTML design report."""
import re

import numpy as np

from coating_studio.comparison import ReferenceTrace, snapshot_design
from coating_studio.examples import EXAMPLES
from coating_studio.optimize import evaluate_terms
from coating_studio.report import build_report
from coating_studio.tolerance import run_tolerance, run_tolerance_corners, tolerance_frequencies


def test_report_contents():
    p = EXAMPLES["dualband"][1]()
    p.name = "Dual <b>band</b>"  # user text is escaped
    p.tolerance.n_samples = 12
    tol = run_tolerance_corners(p, tolerance_frequencies(p))
    refs = [snapshot_design(p, "pinned"),
            ReferenceTrace(name="meas", kind="measured", visible=False,
                           f_meas=np.array([8e9, 12e9]), rl_meas_db=np.array([-12.0, -15.0]))]
    html = build_report(p, references=refs, tolerance=tol, source="/tmp/x.coat")
    assert "Dual &lt;b&gt;band&lt;/b&gt;" in html and "<b>band</b>" not in html
    assert html.count("data:image/png;base64,") == 2  # frequency and angle plots
    # each target's worst RL and margin, as evaluate_terms gives them
    for worst, margin in evaluate_terms(p).per_target:
        assert f"{worst:.2f} dB" in html and f"{margin:+.2f} dB" in html
    assert "Joint yield over all target corners" in html and f"{tol.joint_yield_fraction * 100:.1f} %" in html
    assert "pinned" in html and "meas" in html and "hidden" in html
    assert "/tmp/x.coat" in html and "Layer 1 faces the incident wave." in html
    assert len(re.findall(r"<tr><td class=num>\d+</td>", html)) == len(p.structure.layers)


def test_report_positive_sign_and_plain_tolerance():
    p = EXAMPLES["dallenbach"][1]()
    p.tolerance.n_samples = 8
    tol = run_tolerance(p, tolerance_frequencies(p))
    html = build_report(p, rl_positive=True, tolerance=tol)
    worst, _ = evaluate_terms(p).per_target[0]
    assert f"{-worst:.2f} dB" in html and "higher is better" in html
    assert "Yield " in html and "Comparison curves" not in html


def test_report_survives_a_broken_model():
    p = EXAMPLES["dallenbach"][1]()
    p.structure.layers[0].material = "missing"
    html = build_report(p)
    assert "Cannot compute" in html and html.rstrip().endswith("</html>")


def test_report_angle_grid_lists_the_lowest_row_per_target():
    from coating_studio.tolerance import run_tolerance_targets
    p = EXAMPLES["dualband"][1]()
    p.tolerance.n_samples = 8
    tol = run_tolerance_targets(p, tolerance_frequencies(p), "grid")
    html = build_report(p, tolerance=tol)
    assert "angle grid (10 points)" in html and f"{tol.joint_yield_fraction * 100:.1f} %" in html
    section = html[html.index("Tolerance analysis"):]
    assert section.count("<li>") == 2  # one line per target, not one per grid point
    p.optimization.enabled_targets()[1].n_angle = 1
    tol = run_tolerance_targets(p, tolerance_frequencies(p), "grid")
    assert "Target 2: fewer than 2 angle-grid points" in build_report(p, tolerance=tol)
