"""Spectral axis display unit (GHz / THz / µm / nm / cm⁻¹): conversions, storage, CLI spec, texts, report (no Qt)."""
import json

import numpy as np
import pytest

from coating_studio import spectral
from coating_studio.core.constants import C0
from coating_studio.core.units import (
    SPECTRAL_UNITS, from_spectral, spectral_bounds, spectral_reversed, to_spectral,
)
from coating_studio.examples import EXAMPLES
from coating_studio.project import SCHEMA_VERSION, Project


def test_conversions_round_trip_and_known_values():
    f = np.geomspace(1e6, 1e16, 41)
    for unit in SPECTRAL_UNITS:
        assert np.allclose(from_spectral(to_spectral(f, unit), unit), f, rtol=1e-14, atol=0)
    assert to_spectral(C0 / 550e-9, "nm") == pytest.approx(550)
    assert to_spectral(10e9, "GHz") == 10 and to_spectral(1e12, "THz") == 1
    assert from_spectral(1000, "cm-1") == pytest.approx(C0 * 1e5)  # 1000 cm⁻¹ = 10 µm
    assert to_spectral(from_spectral(1000, "cm-1"), "um") == pytest.approx(10)
    assert isinstance(to_spectral(1e9, "nm"), float)
    assert spectral_reversed("nm") and spectral_reversed("um") and not spectral_reversed("cm-1")
    assert spectral_bounds(2e9, 18e9, "nm") == (pytest.approx(C0 / 18e9 * 1e9), pytest.approx(C0 / 2e9 * 1e9))
    for bad in (0.0, -1.0, float("nan")):
        with pytest.raises(ValueError):
            from_spectral(bad, "nm")
    with pytest.raises(ValueError):
        to_spectral(0.0, "nm")
    with pytest.raises(ValueError):
        to_spectral(1e9, "Hz")


def test_texts_keep_ranges_low_to_high():
    assert spectral.fmt_range(8e9, 12e9, "GHz") == "8–12 GHz"
    lo, hi = spectral.fmt_range(C0 / 700e-9, C0 / 400e-9, "nm").split(" ")[0].split("–")
    assert (float(lo), float(hi)) == pytest.approx((400, 700))
    assert spectral.fmt_range(10e9, 10e9, "GHz") == "10 GHz"  # a single-frequency target
    assert spectral.fmt_point(C0 / 550e-9, "nm") == "λ = 550 nm"
    assert spectral.axis_label("cm-1") == "Wavenumber [cm⁻¹]"


@pytest.mark.parametrize("unit", list(SPECTRAL_UNITS))
def test_exported_first_column_reads_back_as_frequency(unit):
    """A data export in any unit can be loaded again as a measured comparison curve (csvio's axis detection)."""
    from coating_studio.comparison import parse_measured_text

    f = np.linspace(8e9, 12e9, 7)
    rl = np.linspace(-5, -25, 7)
    rows = [f"{x:.10g},{y:.6g}" for x, y in zip(spectral.x_values(f, unit), rl)]
    got_f, got_rl, _ = parse_measured_text("\n".join([f"{spectral.csv_header(unit)},RL [dB]"] + rows))
    assert np.allclose(got_f, f, rtol=1e-9) and np.allclose(got_rl, rl)


def test_project_keeps_the_unit_without_a_schema_bump():
    p = EXAMPLES["salisbury"][1]()
    assert p.sweep.spectral_unit == "GHz"
    p.sweep.spectral_unit = "nm"
    d = json.loads(json.dumps(p.to_dict()))
    assert d["schema"] == SCHEMA_VERSION  # display only: older apps ignore the key and show GHz (no bump of its own)
    assert Project.from_dict(d).sweep.spectral_unit == "nm"
    assert p.sweep.key() == EXAMPLES["salisbury"][1]().sweep.key()  # not part of the solve cache key
    d["sweep"]["spectral_unit"] = "µm"  # hand-edited, unknown id
    assert Project.from_dict(d).sweep.spectral_unit == "GHz"
    d["sweep"].pop("spectral_unit")
    assert Project.from_dict(d).sweep.spectral_unit == "GHz"


def test_cli_spec_round_trips_the_unit_and_keeps_ghz_numbers():
    from coating_studio.cli.output import CliError
    from coating_studio.cli.spec import project_to_spec, spec_to_project

    p = EXAMPLES["salisbury"][1]()
    assert "spectral_unit" not in project_to_spec(p)["sweep"]
    p.sweep.spectral_unit = "um"
    spec = project_to_spec(p)
    assert spec["sweep"]["spectral_unit"] == "um" and spec["sweep"]["f_ghz"] == [p.sweep.f_min / 1e9, p.sweep.f_max / 1e9]
    assert spec_to_project(spec)[0].sweep.spectral_unit == "um"
    spec["sweep"]["spectral_unit"] = "mm"
    with pytest.raises(CliError):
        spec_to_project(spec)


def test_issue_texts_follow_the_display_unit():
    from coating_studio.i18n import issue_text
    from coating_studio.materials.checks import Issue

    iss = Issue("error", "out_of_range", "M", {"lo": 300e3, "hi": 1000e3, "flo": 2.0, "fhi": 18.0})  # GHz args
    assert issue_text(iss) == issue_text(iss, unit="GHz")  # unchanged default (the CLI message)
    assert "GHz" in issue_text(iss)
    text = issue_text(iss, unit="nm")
    assert "nm" in text and "GHz" not in text
    data_lo, data_hi = sorted((C0 / 300e12 * 1e9, C0 / 1000e12 * 1e9))
    assert f"{data_lo:.4g}-{data_hi:.4g} nm" in text  # the pair stays low to high after the swap
    assert issue_text(Issue("warning", "eps_gain", "M", {"f": 10.0}), unit="cm-1").endswith("cm⁻¹.")


def test_report_uses_the_project_unit():
    from coating_studio.report import build_report
    from coating_studio.tolerance import run_tolerance, tolerance_frequencies

    p = EXAMPLES["dallenbach"][1]()
    p.sweep.spectral_unit = "nm"
    p.tolerance.n_samples = 4
    html = build_report(p, tolerance=run_tolerance(p, tolerance_frequencies(p)))
    t = p.optimization.enabled_targets()[0]
    assert spectral.fmt_range(t.f_min, t.f_max, "nm") in html and "Best RL" in html and " nm" in html
    p.sweep.spectral_unit = "GHz"
    assert spectral.fmt_range(t.f_min, t.f_max, "GHz") in build_report(p)


def test_tolerance_band_axis_is_ascending_for_wavelengths():
    from matplotlib.figure import Figure

    from coating_studio.report import TOL_COLORS, draw_tolerance_band
    from coating_studio.tolerance import run_tolerance, tolerance_frequencies

    p = EXAMPLES["dallenbach"][1]()
    p.tolerance.n_samples = 4
    r = run_tolerance(p, tolerance_frequencies(p), band=(9e9, 11e9))
    ax = Figure().add_subplot(111)
    draw_tolerance_band(ax, r, -10.0, r.band, 5, 95, TOL_COLORS, unit="um")
    lo, hi = ax.get_xlim()
    assert lo < hi and lo == pytest.approx(to_spectral(r.f[-1], "um")) and hi == pytest.approx(to_spectral(r.f[0], "um"))
    assert np.array_equal(ax.get_lines()[0].get_xdata(), to_spectral(r.f, "um"))
    x0, x1 = ax.patches[0].get_x(), ax.patches[0].get_x() + ax.patches[0].get_width()
    assert (x0, x1) == pytest.approx(spectral_bounds(9e9, 11e9, "um"))
