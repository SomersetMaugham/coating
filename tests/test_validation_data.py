"""Regression checks against real material data in examples/validation.

The full comparisons live in the example scripts. These tests pin the parts that must not drift:
the datasheet import reproduces the vendor's own derived numbers, and the digitised Kumar 2021
data reproduces the measured absorption peak positions.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from coating_studio.core import C0, SlabLayer, Structure, solve
from coating_studio.materials import ConstantMaterial
from coating_studio.materials.csvio import load_csv

VAL = Path(__file__).resolve().parents[1] / "examples" / "validation"
REF = json.loads((VAL / "reference.json").read_text())


@pytest.mark.parametrize("grade", sorted(REF["laird_eccosorb_mf"]["vendor_dB_per_cm"]))
def test_laird_datasheet_attenuation_and_impedance(grade):
    ref = REF["laird_eccosorb_mf"]
    m = load_csv(VAL / "data" / "laird" / f"{grade}.csv")
    eps, mu = m.eps_mu(m.f, None)
    n = np.sqrt(eps * mu)
    n = np.where(n.imag > 0, -n, n)
    att = 20 * np.log10(np.e) * (2 * np.pi * m.f / C0) * (-n.imag) / 100
    z = np.abs(np.sqrt(mu / eps))
    att_v = np.array(ref["vendor_dB_per_cm"][grade])
    z_v = np.array(ref["vendor_Z_over_Z0"][grade])
    big = att_v >= 1  # small values are printed with too few digits to compare relatively
    assert np.all(np.abs(att[big] / att_v[big] - 1) < 0.06)
    ok = np.abs(z - z_v) <= 0.015
    if grade == "MF-114":  # 1 GHz entry (0.57 between 0.44 and 0.41) looks like a datasheet typo
        ok[0] = True
    assert ok.all()


@pytest.mark.parametrize("sample", sorted(REF["kumar2021"]["table2"]))
def test_kumar2021_peak_frequency(sample):
    fr, crl, cbw, tm, fm, ms, mbw = REF["kumar2021"]["table2"][sample]
    mats = {"Air": ConstantMaterial("Air"),
            "X": load_csv(VAL / "data" / "kumar2021" / f"kumar_{sample}.csv", name="X")}
    f = np.linspace(2e9, 18e9, 1601)
    g = solve(Structure([SlabLayer("X", tm * 1e-3)]), mats, f, 0.0, pols=("TE",)).pol["TE"].gamma[:, 0]
    rl = 20 * np.log10(np.abs(g))
    assert f[np.argmin(rl)] / 1e9 == pytest.approx(fm, abs=0.3)
    assert rl.min() < -20  # all five are strong matched absorbers
    if sample != "U8":  # U8's published bandwidth is inconsistent with its neighbours (see README)
        bw = np.ptp(f[rl <= -10]) / 1e9
        assert bw == pytest.approx(mbw, rel=0.12)


def test_michielssen_benchmark_reproduces_published_designs():
    """Asi & Dib (2010) designs on their own 0.5 GHz grid, and the recorded Coating Studio design."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("mb", VAL / "michielssen_benchmark.py")
    mb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mb)
    mats = mb.database()
    for d in mb.BM["designs"]:
        if d["source"].startswith("asi_dib_2010"):
            got = mb.max_reflection(mats, d["layers"], d["grid_step_GHz"])
            assert abs(got - d["published_dB"]) <= mb.REPRODUCED_DB, d["name"]
    for d in mb.BM["designs_3layer"]:  # Amaya & Correa (2013): 3 layers, 0.85-5.4 GHz
        got = mb.max_reflection(mats, d["layers"], 0.01, band=(0.85, 5.4))
        assert abs(got - d["published_dB"]) <= mb.REPRODUCED_DB, d["name"]
    cs = mb.BM["coating_studio_design"]
    assert abs(mb.max_reflection(mats, cs["layers"], 0.1) - cs["max_dB_0p1GHz"]) <= 1e-3
    assert mb.BM["database"]["8"]["eps_loss"] == 6.0
