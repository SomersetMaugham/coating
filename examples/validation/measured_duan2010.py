"""Duan et al. 2010 (carbonyl iron / silicone rubber, Bull. Mater. Sci. 33, 633): a NEGATIVE result.

The paper's eps/mu (Figs. 3-4, digitised) were measured on "carbonyl iron powder" by the coaxial
method, not on the rubber sheets whose reflectivity was measured (arch method, Table 1). This
script shows that:

1. eps/mu used as published cannot reproduce the measured peaks (|n| is ~9 instead of ~5.7).
2. Scaling eps and mu to fit each 4 mm sheet's first peak, then PREDICTING the 2 mm sheet,
   puts the 2 mm peak ~40 % too high in frequency.
3. The measured peaks alone imply a non-monotonic |n(f)| (lambda/4 and 3 lambda/4 estimates),
   so the 2 mm and 4 mm sheets are unlikely to be the same material at the nominal thickness.

Use it as an example of why paired eps/mu + RL data from the SAME sample is needed.

Run: python examples/validation/measured_duan2010.py
"""
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from coating_studio.core import C0, SlabLayer, Structure, solve
from coating_studio.materials import ConstantMaterial, TabulatedMaterial

HERE = Path(__file__).parent
F = np.linspace(2e9, 18e9, 3201)

raw = np.genfromtxt(HERE / "data" / "duan2010" / "duan_fig3_fig4_digitised.csv",
                    delimiter=",", comments="#", skip_header=2)
FG = raw[:, 0]
# remove digitising ripple: cubic fit in log f per column
SMOOTH = [np.polyval(np.polyfit(np.log(FG), raw[:, c], 3), np.log(FG)) for c in range(1, 5)]


def rl_db(a, b, d):
    m = TabulatedMaterial("CI", FG * 1e9, a * SMOOTH[0], a * SMOOTH[1], b * SMOOTH[2], b * SMOOTH[3])
    g = solve(Structure([SlabLayer("CI", d)]), {"Air": ConstantMaterial("Air"), "CI": m},
              F, 0.0, pols=("TE",)).pol["TE"].gamma[:, 0]
    return 20 * np.log10(np.abs(g))


def minima(r, thr=-3):
    return [(F[i] / 1e9, r[i]) for i in range(1, len(r) - 1)
            if r[i] < r[i - 1] and r[i] <= r[i + 1] and r[i] < thr]


def nearest(mins, f0):
    return min(mins, key=lambda x: abs(x[0] - f0)) if mins else (np.nan, np.nan)


def main():
    peaks = json.loads((HERE / "reference.json").read_text())["duan2010"]["peaks"]

    print("1) eps/mu as published")
    for d in ("2", "4"):
        r = rl_db(1, 1, int(d) * 1e-3)
        print(f"   {d} mm: deepest simulated RL {r.min():.1f} dB; measured 80 wt% "
              f"{peaks[d]['80'][0][0]} GHz / {peaks[d]['80'][0][1]} dB")

    print("\n2) fit eps/mu scale on the 4 mm first peak, PREDICT the 2 mm peak")
    for wt in ("50", "60", "70", "80"):
        f1, d1 = peaks["4"][wt][0]

        def res(p):
            fm, dm = nearest(minima(rl_db(np.exp(p[0]), np.exp(p[1]), 4e-3)), f1)
            return [10, 10] if np.isnan(fm) else [np.log(fm / f1) * 20, (dm - d1) / 5]

        best = min((least_squares(res, [np.log(a0), np.log(b0)], diff_step=1e-3)
                    for a0 in (0.3, 0.5, 0.8) for b0 in (0.7, 1.0, 1.5)), key=lambda s: s.cost)
        a, b = np.exp(best.x)
        f2, d2 = peaks["2"][wt][0]
        p2 = nearest(minima(rl_db(a, b, 2e-3)), f2)
        print(f"   {wt} wt%: eps x{a:.2f}, mu x{b:.2f} -> 2 mm predicted {p2[0]:.2f} GHz / {p2[1]:.1f} dB,"
              f" measured {f2} GHz / {d2} dB")

    print("\n3) |n| straight from the measured peaks (no material model)")
    for wt in ("60", "70", "80"):
        (fa, _), (fb, _) = peaks["4"][wt]
        fc = peaks["2"][wt][0][0]
        print(f"   {wt} wt%: {C0 / (4 * fa * 1e9 * 4e-3):.2f} @ {fa} GHz (4 mm, l/4) | "
              f"{C0 / (4 * fc * 1e9 * 2e-3):.2f} @ {fc} GHz (2 mm, l/4) | "
              f"{3 * C0 / (4 * fb * 1e9 * 4e-3):.2f} @ {fb} GHz (4 mm, 3l/4)")


if __name__ == "__main__":
    main()
