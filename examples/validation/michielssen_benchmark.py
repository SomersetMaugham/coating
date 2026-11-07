"""Michielssen et al. (1993) multilayer-absorber benchmarks on the 16-material database.

Benchmark A: 5 layers, 2-8 GHz, <= 5 mm (GA, PSO, DE, CFO, BESOA, MIGRO, ...).
Benchmark B: 3 layers, 0.85-5.4 GHz (PSO, UPSO; Amaya & Correa 2013).

This script
  1. builds the database (power-law and relaxation-type materials) from reference.json,
  2. recomputes every published design on the frequency grid its paper used and compares the maximum
     reflection with the published number,
  3. recomputes the design Coating Studio's own optimiser found.

Run:  python examples/validation/michielssen_benchmark.py [--write-spec SPEC.json] [--optimize]
  --write-spec  writes a coating-cli design spec for the search (16 candidates per layer), for agents
  --optimize    re-runs that search in-process (about a minute per restart)
"""
import argparse
import json
from pathlib import Path

import numpy as np

from coating_studio.core import Backing, SlabLayer, Structure, solve
from coating_studio.core.units import power_to_db
from coating_studio.materials.models import ConstantMaterial, DispersiveMaterial, PowerLawMaterial, make_term

HERE = Path(__file__).resolve().parent
BM = json.loads((HERE / "reference.json").read_text())["michielssen1993"]
REPRODUCED_DB = 0.05  # published designs carry 3-decimal thicknesses; this covers the rounding


def material(num, d):
    name = f"M{num}"
    note = "Michielssen et al. 1993 database (benchmark material, not a real product)"
    if d["kind"] == "constant":
        return ConstantMaterial(name, d["eps_re"], 0.0, note=note)
    if d["kind"] == "power_law":
        keys = ("eps_re", "eps_a", "eps_loss", "eps_b", "mu_re", "mu_a", "mu_loss", "mu_b")
        return PowerLawMaterial(name, **{k: d[k] for k in keys if k in d}, note=note)
    return DispersiveMaterial(name, eps_inf=15.0, mu_inf=0.0, note=note,
                              mu_terms=[make_term("debye", d["mu_m"], d["f_m_GHz"] * 1e9)])


def database():
    return {f"M{n}": material(n, d) for n, d in BM["database"].items()}


def max_reflection(mats, layers, step_ghz, band=(2.0, 8.0)):
    """Maximum 20 log10|Gamma| over the band (inclusive) at normal incidence; layer 1 faces the incident wave."""
    s = Structure(layers=[SlabLayer(f"M{m}", t * 1e-3) for m, t in layers], backing=Backing("pec"))
    mats = {"Air": ConstantMaterial("Air", 1.0, 0.0), **mats}
    f = np.round(np.arange(band[0], band[1] + 1e-9, step_ghz), 3) * 1e9
    return float(power_to_db(solve(s, mats, f, 0.0, pols=("TE",)).quantity("R", "TE"))[:, 0].max())


def search_spec():
    """A coating-cli spec of the benchmark search (all layers free among the 16 materials)."""
    mats = [m.to_dict() for m in database().values()]
    names = [m["name"] for m in mats]
    layers = [{"name": f"L{i}", "material": "M6", "thickness_mm": 1.0} for i in range(1, 6)]
    return {"spec_version": 1, "name": "Michielssen 1993 benchmark, 5 layers 2-8 GHz",
            "notes": "Benchmark materials, not real products (materials 14-16 exceed the Snoek limit).",
            "backing": "pec", "materials": mats, "layers": layers,
            "sweep": {"f_ghz": [2, 8], "n_f": 61, "f_at_ghz": 5},
            "targets": [{"name": "2-8 GHz normal", "f_ghz": [2, 8], "n_f": 61, "angle_deg": 0, "pols": ["TE"],
                         "goal_db": -25.885}],
            "variables": [{"layer": f"L{i}", "param": "thickness", "range": [0.01, 5.0], "unit": "mm"}
                          for i in range(1, 6)],
            "choices": [{"layer": f"L{i}", "candidates": names} for i in range(1, 6)],
            "optimization": {"w_worst": 1, "w_mean": 0, "w_thickness": 0, "w_mass": 0, "rl_ref_db": -25.885,
                             "thickness_max_mm": 5.0}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write-spec", metavar="PATH")
    ap.add_argument("--optimize", action="store_true")
    args = ap.parse_args()
    mats = database()
    ok_all = []
    print("Benchmark A (5 layers, 2-8 GHz): published designs on each paper's own grid (max reflection, dB):")
    print(f"  {'design':64s} {'grid':>5s} {'published':>10s} {'here':>9s} {'diff':>7s}  verdict")
    for d in BM["designs"]:
        got = max_reflection(mats, d["layers"], d["grid_step_GHz"])
        diff = got - d["published_dB"]
        ok = abs(diff) <= REPRODUCED_DB
        if d["source"].startswith("asi_dib_2010"):
            ok_all.append(ok)  # the reference set: these must reproduce
        verdict = "reproduced" if ok else "NOT reproduced"
        print(f"  {d['name'] + ' [' + d['source'] + ']':64s} {d['grid_step_GHz']:5.1f} {d['published_dB']:10.3f} "
              f"{got:9.3f} {diff:+7.3f}  {verdict}")
    print("\nBenchmark B (3 layers, 0.85-5.4 GHz; the paper does not state its grid, 0.01 GHz used here):")
    for d in BM["designs_3layer"]:
        got = max_reflection(mats, d["layers"], 0.01, band=(0.85, 5.4))
        diff = got - d["published_dB"]
        ok = abs(diff) <= REPRODUCED_DB
        ok_all.append(ok)
        print(f"  {d['name'] + ' [' + d['source'] + ']':64s} {d['published_dB']:10.3f} {got:9.3f} {diff:+7.3f}  "
              f"{'reproduced' if ok else 'NOT reproduced'}")
    cs = BM["coating_studio_design"]
    got = max_reflection(mats, cs["layers"], 0.1)
    fine = max_reflection(mats, cs["layers"], 0.01)
    total = sum(t for _, t in cs["layers"])
    ok_all.append(abs(got - cs["max_dB_0p1GHz"]) <= 1e-3 and total <= 5.0)
    print(f"\nCoating Studio design: {got:.3f} dB on the 0.1 GHz grid ({fine:.3f} dB on 0.01 GHz), "
          f"{total:.3f} mm thick")
    print(f"\n{sum(ok_all)}/{len(ok_all)} checks pass "
          "(Asi & Dib and Amaya & Correa designs within {:.2f} dB; recorded Coating Studio result)".format(REPRODUCED_DB))
    if args.write_spec:
        Path(args.write_spec).write_text(json.dumps(search_spec(), indent=1))
        print(f"wrote {args.write_spec}: coating-cli build {args.write_spec} -o bench.coat, then "
              "coating-cli optimize bench.coat -o best.coat --restarts 3")
    if args.optimize:
        from coating_studio.cli.spec import spec_to_project
        from coating_studio.optimize import optimize
        p, _ = spec_to_project(search_spec())
        p.optimization.seed = 1
        res = optimize(p, throttle_s=0.0)
        print(f"\nre-run (seed 1, default DE settings): {res.terms.worst_db:.3f} dB, "
              f"{res.terms.thickness * 1e3:.3f} mm, {res.n_evals} evaluations")
    return 0 if all(ok_all) else 1


if __name__ == "__main__":
    raise SystemExit(main())
