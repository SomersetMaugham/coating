"""Analytic and textbook benchmarks: optical coatings, water, Salisbury, ferrite tile, random stacks vs an independent TMM, optimiser.

Run: python examples/validation/analytic_benchmarks.py
"""
import time
import numpy as np

from coating_studio.core import Backing, SheetLayer, SlabLayer, Structure, solve, C0, ETA0, MU0, EPS0
from coating_studio.materials.models import ConstantMaterial, DispersiveMaterial

ok_all = []


def check(name, got, exp, tol):
    ok = abs(got - exp) <= tol
    ok_all.append(ok)
    print(f"  [{'OK ' if ok else 'BAD'}] {name}: got {got:.6g}, expected {exp:.6g} (tol {tol:g})")


def n_mat(name, n, k=0.0):  # optical constant n - jk  ->  eps = (n - jk)^2
    e = (n - 1j * k) ** 2
    return ConstantMaterial(name, e.real, -e.imag)


# ---------------------------------------------------------------- independent TMM
def tmm(layers, mats, inc, back, f, th_deg, pol):
    """Born & Wolf characteristic matrices (written independently of the solver)."""
    w = 2 * np.pi * f
    k0 = w / C0
    e0, m0 = (x[0] for x in mats[inc].eps_mu(np.array([f]), mats.get))
    kx = k0 * np.sqrt((e0 * m0).real) * np.sin(np.radians(th_deg))

    def adm(e, m):  # tangential H/E admittance
        kz = np.sqrt(k0 ** 2 * e * m - kx ** 2 + 0j)
        if kz.imag > 0:
            kz = -kz
        if abs(kz.imag) < 1e-15 * abs(kz) and kz.real < 0:
            kz = -kz
        Y = kz / (w * MU0 * m) if pol == "TE" else (w * EPS0 * e) / kz
        return kz, Y

    _, Y0 = adm(e0, m0)
    M = np.eye(2, dtype=complex)
    for ly in layers:
        if isinstance(ly, SheetLayer):
            M = M @ np.array([[1, 0], [1 / ly.impedance, 1]])
        else:
            e, m = (x[0] for x in mats[ly.material].eps_mu(np.array([f]), mats.get))
            kz, Y = adm(e, m)
            d = kz * ly.thickness
            M = M @ np.array([[np.cos(d), 1j * np.sin(d) / Y], [1j * Y * np.sin(d), np.cos(d)]])
    if back.kind == "pec":
        B, C = M[0, 1], M[1, 1]  # E=0, H=1 at back
    else:
        e, m = (x[0] for x in mats[back.material].eps_mu(np.array([f]), mats.get))
        _, Ys = adm(e, m)
        B, C = M @ np.array([1, Ys])
    return (Y0 * B - C) / (Y0 * B + C)


def gamma(st, mats, f, th=0.0, pol="TE"):
    return solve(st, mats, f, th, pols=(pol,)).pol[pol].gamma[:, 0]


def RL(g):
    return 20 * np.log10(np.abs(g))


def band(f, rl, thr):
    m = rl <= thr
    return (f[m].min(), f[m].max()) if m.any() else (np.nan, np.nan)


# =========================================================================== 1. optics
print("\n1) Optical coatings (engine run at 545 THz, SI units)")
lam = 550e-9
f0 = C0 / lam
M = {"Air": ConstantMaterial("Air"), "MgF2": n_mat("MgF2", 1.38), "BK7": n_mat("BK7", 1.52),
     "TiO2": n_mat("TiO2", 2.35), "SiO2": n_mat("SiO2", 1.46)}
bare = Structure([], backing=Backing("halfspace", "BK7"))
check("bare BK7 R @550nm", abs(gamma(bare, M, f0)[0]) ** 2, ((1.52 - 1) / 2.52) ** 2, 1e-12)
ar = Structure([SlabLayer("MgF2", lam / 4 / 1.38)], backing=Backing("halfspace", "BK7"))
check("MgF2 quarter-wave AR R @550nm", abs(gamma(ar, M, f0)[0]) ** 2,
      ((1.52 - 1.38 ** 2) / (1.52 + 1.38 ** 2)) ** 2, 1e-12)
lams = np.linspace(400e-9, 700e-9, 301)
Rv = np.abs(gamma(ar, M, C0 / lams)) ** 2
print(f"     AR reflectance 400-700 nm: min {Rv.min()*100:.2f}% @ {lams[Rv.argmin()]*1e9:.0f} nm, "
      f"max {Rv.max()*100:.2f}%  (textbook: ~1.3% at centre, <2% across visible)")
thB = np.degrees(np.arctan(1.52))
check("Brewster angle glass TM R", abs(gamma(bare, M, f0, thB, "TM")[0]) ** 2, 0.0, 1e-20)
tir = Structure([], incident="BK7", backing=Backing("halfspace", "Air"))
for pol in ("TE", "TM"):
    check(f"TIR glass->air 60deg {pol} R", abs(gamma(tir, M, f0, 60.0, pol)[0]) ** 2, 1.0, 1e-12)
N = 8
qw = [SlabLayer("TiO2", lam / 4 / 2.35), SlabLayer("SiO2", lam / 4 / 1.46)] * N + [SlabLayer("TiO2", lam / 4 / 2.35)]
bragg = Structure(qw, backing=Backing("halfspace", "BK7"))
Y = (2.35 / 1.46) ** (2 * N) * 2.35 ** 2 / 1.52
check(f"(HL)^{N}H TiO2/SiO2 Bragg mirror peak R", abs(gamma(bragg, M, f0)[0]) ** 2, ((1 - Y) / (1 + Y)) ** 2, 1e-12)
g = C0 / lams / f0  # normalised frequency lam0/lam
Rb = np.abs(gamma(bragg, M, C0 / lams)) ** 2
hi_m = Rb > 0.5 * Rb.max(); c = np.argmin(abs(g - 1))
a = c
while a > 0 and hi_m[a - 1]: a -= 1
b = c
while b < len(g) - 1 and hi_m[b + 1]: b += 1
sb = g[[a, b]]
dg = (4 / np.pi) * np.arcsin((2.35 - 1.46) / (2.35 + 1.46))
print(f"     stop-band width (Δg, R>50% of peak): {sb.max()-sb.min():.3f};  infinite-stack theory {dg:.3f}")

# =========================================================================== 2. water
print("\n2) Water at 25 °C (single Debye: eps_s=78.36, eps_inf=5.2, tau=8.27 ps; Kaatze 1989)")
water = DispersiveMaterial("Water", eps_inf=5.2,
                           eps_terms=[{"type": "debye", "delta": 78.36 - 5.2, "f0": 1 / (2 * np.pi * 8.27e-12)}])
for fq in (2.45e9, 10e9, 24e9):
    e, _ = water.eps_mu(np.array([fq]), None)
    print(f"     {fq/1e9:5.2f} GHz: eps = {e[0].real:.1f} - j{-e[0].imag:.1f}")
M2 = {"Air": ConstantMaterial("Air"), "Water": water}
half = Structure([], backing=Backing("halfspace", "Water"))
e, _ = water.eps_mu(np.array([2.45e9]), None)
n = np.sqrt(e[0])
check("water half-space R @2.45 GHz vs Fresnel", abs(gamma(half, M2, 2.45e9)[0]) ** 2, abs((1 - n) / (1 + n)) ** 2, 1e-12)
print(f"     -> {abs((1-n)/(1+n))**2*100:.1f}% reflected at 2.45 GHz (literature: ~64%)")

# =========================================================================== 3. Salisbury
print("\n3) Salisbury screen: 377 Ω/sq sheet, λ/4 air gap @10 GHz, PEC")
d = C0 / 10e9 / 4
sal = Structure([SheetLayer(ETA0), SlabLayer("Air", d)])
f = np.linspace(2e9, 18e9, 3201)
gs = gamma(sal, M2, f)
bd = np.tan(2 * np.pi * f / C0 * d)
zin = 1 / (1 / ETA0 + 1 / (1j * ETA0 * bd))
check("max |Γ - analytic| over 2-18 GHz", np.abs(gs - (zin - ETA0) / (zin + ETA0)).max(), 0.0, 1e-12)
lo, hi = band(f, RL(gs), -10)
fb = (hi - lo) / 10e9
# closed form: |Γ| = 1/sqrt(1+4cot^2) ... |Γ|<=g  <=> |cot(βd)| >= ... solved numerically above
print(f"     -10 dB band {lo/1e9:.2f}-{hi/1e9:.2f} GHz (fractional {fb*100:.1f}%)")
lmin, lmax = C0 / hi, C0 / lo
bound = 2 * np.pi ** 2 * d / abs(np.log(10 ** (-10 / 20)))
print(f"     Rozanov limit check: λmax-λmin = {(lmax-lmin)*1e3:.1f} mm  ≤  2π²d/|ln Γ0| = {bound*1e3:.1f} mm "
      f"-> {'OK' if lmax-lmin <= bound else 'VIOLATED'}")
ok_all.append(lmax - lmin <= bound)

# =========================================================================== 4. thin conductive film == sheet
print("\n4) Thin resistive film (σ=1e4 S/m, 265 nm) vs ideal 377 Ω/sq sheet")
film = DispersiveMaterial("Film", eps_inf=1.0, sigma=1e4)
M4 = dict(M2, Film=film)
t = 1 / (1e4 * ETA0)
gf = gamma(Structure([SlabLayer("Film", t), SlabLayer("Air", d)]), M4, f)
check("max |Γ_film - Γ_sheet|", np.abs(gf - gs).max(), 0.0, 2e-3)

# =========================================================================== 5. ferrite tile
print("\n5) NiZn ferrite tile (Snoek-type Debye μ: μs≈1500, f_r=4 MHz, ε=13-j0.15)  on PEC")
fer = DispersiveMaterial("NiZn", eps_inf=13.0, eps_loss=0.15,
                         mu_inf=1.0, mu_terms=[{"type": "debye", "delta": 1500, "f0": 4e6}])
M5 = dict(M2, NiZn=fer)
ff = np.logspace(np.log10(10e6), np.log10(3e9), 2000)
dpred = C0 / (2 * np.pi * 1500 * 4e6)
print(f"     thin-magnetic matching: d ≈ c/(2π·Δμ·f_r) = {dpred*1e3:.2f} mm  (commercial tiles: 5.5-7 mm)")
for dd in (5e-3, 6e-3, 7e-3, dpred):
    r = RL(gamma(Structure([SlabLayer("NiZn", dd)]), M5, ff))
    lo, hi = band(ff, r, -20)
    lo10, hi10 = band(ff, r, -10)
    print(f"     d={dd*1e3:5.2f} mm: min RL {r.min():6.1f} dB @ {ff[r.argmin()]/1e6:6.0f} MHz; "
          f"-20 dB {lo/1e6:5.0f}-{hi/1e6:5.0f} MHz; -10 dB {lo10/1e6:5.0f}-{hi10/1e6:5.0f} MHz")

# =========================================================================== 6. random stacks vs TMM + energy
print("\n6) 300 random stacks (lossy/magnetic/sheets, oblique, PEC or half-space) vs independent TMM")
rng = np.random.default_rng(1)
worst, worst_e = 0.0, 0.0
for i in range(300):
    mats = {"Air": ConstantMaterial("Air")}
    layers = []
    for j in range(rng.integers(1, 7)):
        if rng.random() < 0.2:
            layers.append(SheetLayer(rng.uniform(20, 2000), rng.uniform(-300, 300)))
        else:
            nm = f"m{j}"
            mats[nm] = ConstantMaterial(nm, rng.uniform(1, 30), rng.uniform(0, 10) * (rng.random() < .7),
                                        rng.uniform(1, 5), rng.uniform(0, 3) * (rng.random() < .4))
            layers.append(SlabLayer(nm, rng.uniform(1e-5, 2e-2)))
    if rng.random() < 0.5:
        back = Backing("pec")
    else:
        mats["sub"] = ConstantMaterial("sub", rng.uniform(1, 12), rng.uniform(0, 1))
        back = Backing("halfspace", "sub")
    st = Structure(layers, backing=back)
    fq, th, pol = rng.uniform(0.1e9, 40e9), rng.uniform(0, 85), rng.choice(["TE", "TM"])
    res = solve(st, mats, fq, th, pols=(pol,)).pol[pol]
    worst = max(worst, abs(res.gamma[0, 0] - tmm(layers, mats, "Air", back, fq, th, pol)))
    worst_e = max(worst_e, abs(res.R[0, 0] + res.T[0, 0] + res.A[0, 0] - 1))
check("max |Γ_solver - Γ_TMM|", worst, 0.0, 1e-9)
check("max |R+T+ΣA - 1|", worst_e, 0.0, 1e-9)

# =========================================================================== 7. optimizer
print("\n7) Optimizer rediscovers the Salisbury design (R, d free, 9-11 GHz, worst-case RL)")
from coating_studio.project import Project, OptimizationSettings, ContinuousVariable
from coating_studio.optimize.optimizer import optimize
p = Project(name="sal")
p.materials["Air"] = ConstantMaterial("Air")
s, sp = SheetLayer(1000.0), SlabLayer("Air", 3e-3)
p.structure = Structure([s, sp])
st = OptimizationSettings(f_min=9e9, f_max=11e9, n_f=41, seed=0,
                          variables=[ContinuousVariable(("layer", s.uid, "R"), 50, 3000),
                                     ContinuousVariable(("layer", sp.uid, "thickness"), 1e-3, 15e-3)])
t0 = time.time()
r = optimize(p, st)
Rf, df = r.values[("layer", s.uid, "R")], r.values[("layer", sp.uid, "thickness")]
print(f"     -> R = {Rf:.1f} Ω/sq, d = {df*1e3:.3f} mm, worst RL in band = {r.terms.worst_db if hasattr(r.terms,'worst_db') else r.terms}  ({time.time()-t0:.1f}s)")
print(f"        (λ/4 @10 GHz = {C0/10e9/4*1e3:.3f} mm, η0 = {ETA0:.1f} Ω)")

# =========================================================================== speed
t0 = time.time()
solve(Structure(qw, backing=Backing("halfspace", "BK7")), M, np.linspace(f0 * .5, f0 * 1.5, 2001), np.linspace(0, 89, 90))
print(f"\nSpeed: 17-layer stack, 2001 freq x 90 angles x 2 pol: {time.time()-t0:.2f} s")
print(f"\nSUMMARY: {sum(ok_all)}/{len(ok_all)} checks passed")
