"""HTML design report."""
import re

import numpy as np
import pytest

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
    assert html.count("data:image/png;base64,") == 4  # frequency, angle, and one tolerance plot per target
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


def test_report_tolerance_plots_use_the_settings_of_the_run():
    from coating_studio.i18n import set_language
    p = EXAMPLES["dallenbach"][1]()
    assert build_report(p).count("data:image/png;base64,") == 2  # no tolerance result: no band plot
    p.tolerance.n_samples, p.tolerance.lower_pct, p.tolerance.seed = 6, 10.0, None
    tol = run_tolerance(p, tolerance_frequencies(p))
    p.tolerance.lower_pct, p.tolerance.thickness, p.tolerance.target_db = 25.0, 0.5, -30.0  # edited after the run
    p.tolerance.per_layer[p.structure.layers[0].uid] = {"eps": 0.9}
    html = build_report(p, tolerance=tol)
    assert html.count("data:image/png;base64,") == 3
    assert "thickness 5 %" in html and "thickness 50 %" not in html and "target -10 dB" in html
    assert "6 samples" in html and "normal distribution, seed random" in html
    assert tol.settings.per_layer == {}  # a deep copy: later edits do not reach the result
    try:
        set_language("ko")
        ko = build_report(p, tolerance=tol)
        assert "분포 정규, 시드 무작위" in ko and "표본 6개" in ko
    finally:
        set_language("en")


def test_report_stopped_run_and_plot_cap():
    from coating_studio.project import BandTarget
    from coating_studio.report import MAX_TOLERANCE_PLOTS
    from coating_studio.tolerance import run_tolerance_targets
    p = EXAMPLES["dallenbach"][1]()
    p.tolerance.n_samples = 10
    tol = run_tolerance(p, tolerance_frequencies(p), progress=lambda k, n: k == 4)
    assert tol.stopped and "stopped after 4 of 10 samples" in build_report(p, tolerance=tol)
    # eight single-frequency targets: only the weakest MAX_TOLERANCE_PLOTS get a plot
    p.optimization.targets = [BandTarget(f_min=f, f_max=f, goal_db=-20.0) for f in np.linspace(8e9, 12e9, 8)]
    p.tolerance.n_samples = 5
    rows = run_tolerance_targets(p, tolerance_frequencies(p), "corners")
    html = build_report(p, tolerance=rows)
    assert html.count("data:image/png;base64,") == 2 + MAX_TOLERANCE_PLOTS
    assert "Plots show the 6 targets with the lowest yield." in html


def test_draw_tolerance_band_plots_the_result_arrays():
    from matplotlib.figure import Figure

    from coating_studio.report import TOL_COLORS, draw_tolerance_band
    p = EXAMPLES["dallenbach"][1]()
    p.tolerance.n_samples = 8
    r = run_tolerance(p, tolerance_frequencies(p), band=(9e9, 11e9))
    assert r.band == [(9e9, 11e9)]  # the band is recorded as a list of intervals
    for positive in (False, True):
        sgn = -1 if positive else 1
        ax = Figure().add_subplot(111)
        draw_tolerance_band(ax, r, -10.0, r.band, 5, 95, TOL_COLORS, positive)
        median, nominal, target = ax.get_lines()
        assert np.array_equal(median.get_ydata(), sgn * r.median_db)
        assert np.array_equal(nominal.get_ydata(), sgn * r.nominal_db)
        assert list(target.get_ydata()) == [sgn * -10.0] * 2
        verts = ax.collections[0].get_paths()[0].vertices[:, 1]  # percentile band
        assert np.isclose(verts.min(), min((sgn * r.lower_db).min(), (sgn * r.upper_db).min()))
        assert len(ax.patches) == 1  # one yield interval


def test_report_never_imports_qt():
    """The report (and the band drawing the GUI shares with it) stays outside the Qt boundary (AGENTS.md)."""
    import subprocess
    import sys
    script = (
        "import sys\n"
        "from coating_studio.examples import EXAMPLES\n"
        "from coating_studio.report import build_report\n"
        "from coating_studio.tolerance import run_tolerance_targets, tolerance_frequencies\n"
        "p = EXAMPLES['dualband'][1](); p.tolerance.n_samples = 4\n"
        "html = build_report(p, tolerance=run_tolerance_targets(p, tolerance_frequencies(p), 'grid'))\n"
        "assert html.count('data:image/png;base64,') == 4\n"
        "html = build_report(p, print_layout={'image_width': 600.0, 'font': 'X'})\n"  # the PDF's print variant
        "assert 'width=\"600.0\"' in html\n"
        "bad = [m for m in sys.modules if m.startswith('PySide6')]\n"
        "assert not bad, bad\n")
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_print_variant_sizes_images_and_keeps_the_browser_html():
    """The PDF's print variant: sized high-resolution images in their own paragraph, Qt-readable style sheet, wide
    tables; the browser HTML keeps its own style sheet and unsized images."""
    p = EXAMPLES["dallenbach"][1]()
    html = build_report(p)
    assert "@media print" in html and re.search(r'<img alt="" src=', html) and "width=" not in html.split("<body>")[1]
    pr = build_report(p, print_layout={"image_width": 640.0, "font": "Malgun Gothic"})
    assert "@media print" not in pr and 'font-family: "Malgun Gothic"' in pr
    sizes = re.findall(r'<img alt="" width="([\d.]+)" height="([\d.]+)"', pr)
    assert len(sizes) == 2 and all(float(w) == 640.0 for w, _h in sizes)
    assert float(sizes[0][1]) == pytest.approx(640.0 * 3.8 / 8)  # height from the figure's aspect ratio
    assert '<table width="100%" cellspacing="0">' in pr and '<th width="4%">#</th>' in pr
