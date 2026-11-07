"""Touchstone .s1p export and import."""
import numpy as np
import pytest

from coating_studio.comparison import load_measured
from coating_studio.core import ETA0, solve
from coating_studio.examples import EXAMPLES
from coating_studio.touchstone import TouchstoneError, design_s11, format_s1p, parse_s1p, write_design_s1p


@pytest.mark.parametrize("fmt", ["RI", "MA", "DB"])
def test_format_and_parse_round_trip(fmt):
    f = np.array([2e9, 5.5e9, 18e9])
    s = np.array([0.5 - 0.2j, -0.01 + 0.003j, 0.9j])
    text = format_s1p(f, s, 376.73, ["a comment"], fmt=fmt)
    assert text.startswith("! a comment\n# GHZ S " + fmt + " R 376.73\n")
    f2, s2 = parse_s1p(text)
    assert np.allclose(f2, f) and np.allclose(s2, s, atol=1e-12)


def test_parse_units_defaults_and_errors():
    f, s = parse_s1p("! no option line: GHz, MA\n1 0.5 90\n2 0.25 0\n")
    assert np.allclose(f, [1e9, 2e9]) and np.allclose(s, [0.5j, 0.25])
    f, _ = parse_s1p("# MHz S RI R 50\n3000 0.1 0 ! trailing comment\n1000 0.2 0\n")
    assert np.allclose(f, [1e9, 3e9])  # sorted
    for bad, why in (("# GHZ Z RI R 50\n1 1 0\n2 1 0\n", "S parameters"),
                     ("# GHZ S RI R 50\n1 1 0 0 0\n", "2-port"),
                     ("[Version] 2.0\n# GHZ S RI R 50\n", "2.0"),
                     ("# GHZ S RI R 50\n1 0.1 0\n1 0.2 0\n", "duplicate")):
        with pytest.raises(TouchstoneError, match=why):
            parse_s1p(bad)


def test_design_s11_is_the_solver_gamma_with_the_modal_reference():
    p = EXAMPLES["dallenbach"][1]()
    f, s11, ref, notes = design_s11(p, "TE")
    assert np.array_equal(s11, solve(p.structure, p.materials, p.sweep.freq_grid(), p.sweep.angle).pol["TE"].gamma[:, 0])
    assert ref == pytest.approx(ETA0) and any("exp(+j*omega*t)" in n for n in notes)
    # R(1+S)/(1-S) is the input wave impedance: eta0 * z_in
    z_in = solve(p.structure, p.materials, f, 0.0).pol["TE"].z_in[:, 0]
    assert np.allclose(ref * (1 + s11) / (1 - s11), ETA0 * z_in)
    p.sweep.angle = 60.0
    assert design_s11(p, "TE")[2] == pytest.approx(2 * ETA0) and design_s11(p, "TM")[2] == pytest.approx(ETA0 / 2)
    with pytest.raises(ValueError):
        design_s11(p, "avg")


def test_s1p_export_imports_back_as_a_measured_curve(tmp_path):
    p = EXAMPLES["jaumann2"][1]()
    path = tmp_path / "design.s1p"
    assert write_design_s1p(path, p, "TE") == p.sweep.n_f
    ref, positive = load_measured(str(path))
    rl = 20 * np.log10(np.abs(solve(p.structure, p.materials, p.sweep.freq_grid(), 0.0).pol["TE"].gamma[:, 0]))
    assert not positive and ref.name == "design" and np.allclose(ref.rl_meas_db, rl, atol=1e-9)
    assert np.allclose(ref.f_meas, p.sweep.freq_grid())
