"""Qt-free tests for reference traces (comparison.py)."""

import numpy as np
import pytest

from coating_studio.comparison import (
    MAX_REFERENCES, free_slot, parse_measured_text, snapshot_design,
)
from coating_studio.core import solve
from coating_studio.examples import EXAMPLES
from coating_studio.materials import TabulatedMaterial
from coating_studio.materials.csvio import CsvFormatError


def test_snapshot_is_independent_and_resolves_under_current_sweep():
    p = EXAMPLES["jaumann2"][1]()
    ref = snapshot_design(p, "A")
    reference_r = p.structure.layers[0].R
    p.structure.layers[0].R = 50.0  # later edits must not leak into the snapshot
    p.materials["PMI foam"].eps_re = 3.0
    p.sweep.angle = 30.0  # the reference follows the current sweep
    res = ref.results(p.sweep)["freq"]
    q = EXAMPLES["jaumann2"][1]()
    q.structure.layers[0].R = reference_r
    want = solve(q.structure, q.materials, p.sweep.freq_grid(), 30.0)
    for pol in ("TE", "TM"):
        assert np.allclose(res.pol[pol].gamma, want.pol[pol].gamma, atol=1e-14)


def test_mixture_snapshot_keeps_its_ingredients():
    p = EXAMPLES["carbon"][1]()
    ref = snapshot_design(p, "mix")
    before = ref.results(p.sweep)["freq"].pol["TE"].gamma.copy()
    p.rename_material("Epoxy", "Resin")  # live edits to the matrix material
    p.materials["Resin"].eps_re = 9.0
    ref._cache_key = None  # force a re-solve
    after = ref.results(p.sweep)["freq"].pol["TE"].gamma
    assert np.allclose(before, after)


def test_results_cached_per_sweep_and_errors_per_grid():
    p = EXAMPLES["dallenbach"][1]()
    p.add_material(TabulatedMaterial("Narrow", np.array([8e9, 12e9]), [4, 4], [0.2, 0.2]))
    p.structure.layers[0].material = "Narrow"
    ref = snapshot_design(p, "narrow")
    p.sweep.f_min, p.sweep.f_max, p.sweep.f_at = 2e9, 18e9, 10e9
    r1 = ref.results(p.sweep)
    assert isinstance(r1["freq"], Exception)  # 2-18 GHz is outside the data
    assert not isinstance(r1["angle"], Exception)  # 10 GHz is inside
    assert ref.results(p.sweep) is r1  # same sweep: cached, no re-solve
    p.sweep.f_min, p.sweep.f_max = 9e9, 11e9
    assert not isinstance(ref.results(p.sweep)["freq"], Exception)


def test_free_slot_reuses_gaps():
    p = EXAMPLES["salisbury"][1]()
    refs = [snapshot_design(p, str(i), slot=i) for i in range(MAX_REFERENCES)]
    assert free_slot(refs) is None
    del refs[2]
    assert free_slot(refs) == 2


def test_measured_csv_sign_units_and_errors():
    f, rl, pos = parse_measured_text("f [GHz], RL [dB]\n10, -20\n8, -10\n12, -12\n")
    assert np.allclose(f, [8e9, 10e9, 12e9]) and np.allclose(rl, [-10, -20, -12]) and not pos
    # positive return loss with a little calibration ripple below 0 dB at the band edge
    f, rl, pos = parse_measured_text("f [GHz]; RL [dB]\n2; -0.05\n10; 25\n18; 3\n")
    assert pos and np.allclose(rl, [0.05, -25, -3])
    # wavelength axis: descending frequency is sorted
    f, rl, _ = parse_measured_text("wavelength (mm), RL\n30, -5\n25, -8\n")
    assert f[0] < f[1]
    # the app's own Frequency-tab export: uses the average column
    f, rl, _ = parse_measured_text("f [GHz],RL TE,RL TM,RL avg\n1,-10,-12,-11\n2,-20,-22,-21\n")
    assert np.allclose(rl, [-11, -21])
    with pytest.raises(CsvFormatError):
        parse_measured_text("f [GHz], RL\n1, -10\n2, 12\n")  # ambiguous sign
    with pytest.raises(CsvFormatError):
        parse_measured_text("f [GHz], a, b\n1, -10, 1\n2, -12, 1\n")  # which column?
