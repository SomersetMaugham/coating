"""Laird Eccosorb MF: import the datasheet eps/mu tables as CSV and recompute the vendor's
attenuation (dB/cm) and normalised impedance |Z|/Z0.

Run: python examples/validation/datasheet_laird.py
"""
import json
from pathlib import Path

import numpy as np

from coating_studio.core import C0
from coating_studio.materials.csvio import load_csv

HERE = Path(__file__).parent


def recompute(grade):
    """(f [GHz], attenuation [dB/cm], |Z|/Z0) from the imported CSV."""
    m = load_csv(HERE / "data" / "laird" / f"{grade}.csv")
    eps, mu = m.eps_mu(m.f, None)
    n = np.sqrt(eps * mu)
    n = np.where(n.imag > 0, -n, n)  # passive branch, N = n - jk
    att = 20 * np.log10(np.e) * (2 * np.pi * m.f / C0) * (-n.imag) / 100
    return m.f / 1e9, att, np.abs(np.sqrt(mu / eps))


def main():
    ref = json.loads((HERE / "reference.json").read_text(encoding="utf-8"))["laird_eccosorb_mf"]
    rel, dz = [], []
    print(f"{'grade':7} {'f':>5} | {'dB/cm vendor':>12} {'tool':>7} | {'|Z|/Z0 vendor':>13} {'tool':>6}")
    for grade, att_v in ref["vendor_dB_per_cm"].items():
        f, att, z = recompute(grade)
        z_v = ref["vendor_Z_over_Z0"][grade]
        for i in range(len(f)):
            print(f"{grade:7} {f[i]:5.1f} | {att_v[i]:12.3g} {att[i]:7.3g} | {z_v[i]:13.2f} {z[i]:6.2f}")
            if att_v[i] >= 1:
                rel.append(abs(att[i] / att_v[i] - 1))
            dz.append(abs(z[i] - z_v[i]))
    print(f"\nattenuation (vendor >= 1 dB/cm): median diff {np.median(rel) * 100:.1f} %, max {max(rel) * 100:.1f} %")
    print(f"|Z|/Z0: median abs diff {np.median(dz):.3f}, max {max(dz):.3f} "
          "(the max is MF-114 at 1 GHz, which looks like a datasheet typo: 0.57 between 0.44 and 0.41)")


if __name__ == "__main__":
    main()
