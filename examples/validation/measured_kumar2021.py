"""Kumar et al. 2021 (U-type hexaferrite/PVA, AIP Adv. 11, 015311, CC BY 4.0).

eps/mu digitised from Fig. 4 -> metal-backed RL at the matching thickness t_m -> compared with
Table II: the paper's calculated RL and the MEASURED short-circuit S11. A Monte Carlo over
eps, mu (+-3 %) and thickness (+-0.02 mm) shows how much digitising error alone moves the result.

Run: python examples/validation/measured_kumar2021.py [--plot out.png]
"""
import json
import sys
from pathlib import Path

import numpy as np

from coating_studio.core import SlabLayer, Structure, solve
from coating_studio.materials import ConstantMaterial
from coating_studio.materials.csvio import load_csv

HERE = Path(__file__).parent
F = np.linspace(2e9, 18e9, 3201)


def materials(sample):
    return {"Air": ConstantMaterial("Air"),
            "X": load_csv(HERE / "data" / "kumar2021" / f"kumar_{sample}.csv", name="X")}


def rl_db(mats, d, perturb=None):
    st = Structure([SlabLayer("X", d, uid="L")])
    g = solve(st, mats, F, 0.0, pols=("TE",), perturb=perturb).pol["TE"].gamma[:, 0]
    return 20 * np.log10(np.abs(g))


def summary(r):
    """(peak frequency [GHz], RLmin [dB], -10 dB bandwidth [GHz])."""
    i = int(np.argmin(r))
    m = r <= -10
    return F[i] / 1e9, r[i], (F[m].max() - F[m].min()) / 1e9 if m.any() else 0.0


def main(plot=None, n_mc=300):
    t2 = json.loads((HERE / "reference.json").read_text(encoding="utf-8"))["kumar2021"]["table2"]
    rng = np.random.default_rng(1)
    curves = {}
    print(f"{'':5} {'t_m':>4} | {'tool: f_peak  RLmin   BW':>25} | {'paper calc':>17} | {'MEASURED':>17} | MC 90 % (f_peak, BW)")
    for s, (fr, crl, cbw, tm, fm, ms, mbw) in t2.items():
        mats = materials(s)
        r = rl_db(mats, tm * 1e-3)
        sf, sr, sb = summary(r)
        mc = np.array([summary(rl_db(mats, tm * 1e-3, {"L": {
            "eps": rng.normal(1, .03), "mu": rng.normal(1, .03),
            "thickness": 1 + rng.normal(0, .02) / tm}})) for _ in range(n_mc)])
        q = lambda c: np.percentile(mc[:, c], [5, 95])
        print(f"{s:5} {tm:4.1f} | {sf:6.2f} GHz {sr:6.1f} {sb:4.1f} | {crl:6.1f} dB {cbw:4.1f} GHz |"
              f" {ms:6.1f} dB {mbw:4.1f} GHz | {q(0)[0]:.1f}-{q(0)[1]:.1f} GHz, {q(2)[0]:.1f}-{q(2)[1]:.1f} GHz"
              f"   (paper f_m {fm} GHz)")
        curves[s] = (r, tm, fm, ms)
    if plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 4.5))
        for (s, (r, tm, fm, ms)), c in zip(curves.items(), ("k", "r", "b", "g", "purple")):
            ax.plot(F / 1e9, r, color=c, label=f"{s} (t={tm} mm) Coating Studio")
            ax.plot([fm], [ms], "o", color=c, mfc="white", ms=8)
        ax.axhline(-10, ls="--", color="grey", lw=.8)
        ax.set(xlabel="Frequency (GHz)", ylabel="RL (dB)", xlim=(2, 18), ylim=(-50, 0),
               title="Kumar et al. 2021: tool RL (lines) vs measured S11min at f_m (circles)")
        ax.legend(fontsize=8, loc="lower left")
        fig.tight_layout()
        fig.savefig(plot, dpi=110)
        print(f"plot -> {plot}")


if __name__ == "__main__":
    main(plot=sys.argv[sys.argv.index("--plot") + 1] if "--plot" in sys.argv else None)
