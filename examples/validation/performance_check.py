"""Measure the scenario in docs/PERFORMANCE_SCENARIO.md and print one verdict per item.

Run:  python examples/validation/performance_check.py WORKDIR
The pass limits below are fixed by that document: do not change them to make a run pass.
"""
import json
import math
import os
import statistics as st
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
PY = sys.executable
CLI = [PY, "-m", "coating_studio.cli"]
RESULTS = []


def record(tid, value, limit, ok, required=False, near=None):
    near_flag = bool(ok and near)
    RESULTS.append({"id": tid, "value": value, "limit": limit, "ok": bool(ok), "required": required, "near": near_flag})
    state = "PASS (barely)" if near_flag else ("PASS" if ok else "FAIL")
    print(f"[{state:13s}] {tid:4s} {value}   (limit: {limit})", flush=True)


def guarded(tid, fn, required=False):
    try:
        fn()
    except Exception as exc:  # one broken item must not lose the others
        traceback.print_exc()
        record(tid, f"error: {exc}", "runs to completion", False, required)


def cli(*args, timeout=900):
    t0 = time.perf_counter()
    r = subprocess.run([*CLI, *args], capture_output=True, text=True, timeout=timeout)
    return r, time.perf_counter() - t0


def timed(fn, n=7):
    fn()  # warm-up, discarded
    xs = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        xs.append(time.perf_counter() - t0)
    q = st.quantiles(xs, n=4)
    return st.median(xs), q[2] - q[0]


def rl(res, pol="TE"):
    from coating_studio.core.units import power_to_db
    return power_to_db(res.quantity("R", pol))


def wilson(k, n, z=3.0):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def t1():
    a = subprocess.run([PY, str(HERE / "analytic_benchmarks.py")], capture_output=True, text=True)
    m = subprocess.run([PY, str(HERE / "michielssen_benchmark.py")], capture_output=True, text=True)
    ok = a.returncode == 0 and m.returncode == 0 and "12/12" in a.stdout and "13/13 checks pass" in m.stdout
    record("T1", f"analytic exit {a.returncode}, literature exit {m.returncode}", "12/12 and 13/13", ok, True)


def t2b(work):
    from coating_studio.core import solve
    from coating_studio.project import Project
    r, _ = cli("solve", str(work / "sal.coat"), "--sweep", "freq")
    d = json.loads(r.stdout)["result"]["data"]
    p = Project.load(str(work / "sal.coat"))
    res = solve(p.structure, p.materials, np.array(d["f_hz"]), d["theta_deg"] if np.isscalar(d["theta_deg"]) else d["theta_deg"][0])
    worst = 0.0
    for pol in ("TE", "TM"):
        cli_db = np.array(d["rl_db"][pol] if isinstance(d["rl_db"], dict) else d["rl_db"]).ravel()
        worst = max(worst, float(np.abs(cli_db - rl(res, pol)[:, 0]).max()))
    record("T2b", f"max diff {worst:.2e} dB", "<= 1e-12 dB", worst <= 1e-12, True)


def t3a():
    from coating_studio.core import Backing, SlabLayer, Structure, solve
    from coating_studio.materials.models import ConstantMaterial
    m = {"Air": ConstantMaterial("Air", 1.0, 0.0), "H": ConstantMaterial("H", 5.3, 0.0),
         "L": ConstantMaterial("L", 2.1, 0.0), "S": ConstantMaterial("S", 2.3, 0.0)}
    f0 = 5e14
    ly = [SlabLayer("H" if i % 2 == 0 else "L", 299792458.0 / f0 / 4 / math.sqrt(5.3 if i % 2 == 0 else 2.1)) for i in range(17)]
    s = Structure(ly, backing=Backing("halfspace", "S"))
    f, a = np.linspace(f0 * .5, f0 * 1.5, 2001), np.linspace(0, 89, 90)
    med, iqr = timed(lambda: solve(s, m, f, a))
    record("T3a", f"{med:.3f} s (IQR {iqr:.3f})", "<= 0.50 s", med <= 0.50, near=med > 0.45)


def t3b(work):
    def once():
        r, _ = cli("solve", str(work / "sal.coat"), "--summary-only")
        assert r.returncode == 0, r.stderr
    med, iqr = timed(once)
    record("T3b", f"{med:.3f} s (IQR {iqr:.3f})", "<= 3.0 s", med <= 3.0, near=med > 2.7)


def t4(work):
    def run(seed, tag):
        out = work / f"{tag}{seed}.coat"
        r, dt = cli("optimize", str(work / "A.coat"), "-o", str(out), "--force", "--restarts", "1", "--seed", str(seed), "--timeout", "800")
        d = json.loads(r.stdout)
        res = d["result"]
        return {"seed": seed, "worst": res["targets"][0]["worst_rl_db"], "time": dt, "file": str(out), "values": res["values"], "code": r.returncode}
    seeds = list(range(1, 11))
    with ThreadPoolExecutor(4) as ex:
        runs = list(ex.map(lambda s: run(s, "s"), seeds))
    w = [r["worst"] for r in runs]
    print("  seeds:", [round(x, 3) for x in w], "times:", [round(r["time"]) for r in runs], "exit:", sorted({r["code"] for r in runs}), flush=True)
    best, med = min(w), st.median(w)
    record("T4a", f"best {best:.3f}, median {med:.3f} dB", "best <= -25.384 and median <= -24.61", best <= -25.384 and med <= -24.61)
    tm = st.median(r["time"] for r in runs)
    record("T4c", f"median {tm:.1f} s (4 processes at once)", "<= 120 s", tm <= 120, near=tm > 108)
    again = run(1, "r")
    same = again["worst"] == runs[0]["worst"] and again["values"] == runs[0]["values"]
    record("T4b", f"worst {again['worst']:.9f} vs {runs[0]['worst']:.9f}", "identical worst RL and variables", same, True)
    return min(runs, key=lambda r: r["worst"])


def t4d(work):
    from michielssen_benchmark import database
    mats = [m.to_dict() for m in database().values()]
    first = ["M14", "M15", "M16", "M6", "M5"]
    twelve = [f"M{i}" for i in range(1, 13)]

    def spec(second):
        return {"spec_version": 1, "name": "branch check", "backing": "pec", "materials": mats,
                "layers": [{"name": "L1", "material": "M6", "thickness_mm": 1.0}, {"name": "L2", "material": "M6", "thickness_mm": 1.0}],
                "sweep": {"f_ghz": [2, 8], "n_f": 61, "f_at_ghz": 5},
                "targets": [{"name": "t", "f_ghz": [2, 8], "n_f": 61, "angle_deg": 0, "pols": ["TE"], "goal_db": -20}],
                "variables": [{"layer": n, "param": "thickness", "range": [0.01, 2.0], "unit": "mm"} for n in ("L1", "L2")],
                "choices": [{"layer": "L1", "candidates": first}, {"layer": "L2", "candidates": second}],
                "optimization": {"w_worst": 1, "w_mean": 0, "w_thickness": 0, "w_mass": 0}}

    def run(name, second):
        path = work / f"{name}.json"
        path.write_text(json.dumps(spec(second)))
        cli("build", str(path), "-o", str(work / f"{name}.coat"), "--force")
        r, dt = cli("optimize", str(work / f"{name}.coat"), "--seed", "3", "--restarts", "1", "--timeout", "500", "--maxiter", "60")
        return json.loads(r.stdout)["result"]["targets"][0]["worst_rl_db"], dt
    with ThreadPoolExecutor(3) as ex:
        a, b, c = ex.map(lambda x: run(*x), [("d60", twelve), ("d5", ["M13"]), ("d65", [*twelve, "M13"])])
    truth = min(a[0], b[0])
    record("T4d", f"integer DE {c[0]:.3f} vs enumerated {truth:.3f} dB ({c[1]:.0f} s vs {a[1]:.0f}+{b[1]:.0f} s)", "integer DE not worse by 0.05 dB", c[0] <= truth + 0.05)


def tol_cli(path, n, seed, target=None):
    args = ["tolerance", str(path), "--angle-grid", "--samples", "--n-samples", str(n), "--seed", str(seed), "--timeout", "800"]
    if target is not None:
        args += ["--target-db", repr(float(target))]
    r, dt = cli(*args)
    d = json.loads(r.stdout)
    assert d["ok"], r.stdout[:400]
    c = d["result"]["corners"][0]
    key = next(k for k in c if "sample" in k and isinstance(c[k], list))
    return np.array(c[key], float), d["result"]["joint_yield_fraction"], dt


def t5(work, best_file):
    pilot, _, _ = tol_cli(best_file, 500, 999)
    target = float(np.round(np.median(pilot), 2))
    (work / "tol_target.txt").write_text(repr(target))
    s1, y1, dt = tol_cli(best_file, 2000, 21, target)
    record("T5a", f"{dt:.1f} s", "<= 30 s", dt <= 30, near=dt > 27)
    s2, y2, _ = tol_cli(best_file, 2000, 21, target)
    (work / "cli_samples.npy").write_bytes(b"")
    np.save(work / "cli_samples.npy", s1)
    record("T5b-cli", f"yield {y1} and {y2}, target {target} dB", "sample arrays identical", np.array_equal(s1, s2), True)
    runs = [(n, *tol_cli(best_file, n, seed, target)[:2]) for n, seed in ((500, 31), (2000, 32), (8000, 33))]
    iv = [(n, round(y, 4), wilson(round(y * n), n)) for n, _, y in runs]
    low, high = max(i[2][0] for i in iv), min(i[2][1] for i in iv)
    record("T5c", "; ".join(f"n={n}: {y} [{a:.3f}, {b:.3f}]" for n, y, (a, b) in iv), "99.7% Wilson intervals overlap", low <= high)


def t7(work):
    r, dt = cli("optimize", str(work / "A.coat"), "--timeout", "5", "--seed", "4")
    d = json.loads(r.stdout)
    partial = bool(d.get("result") and d["result"].get("values"))
    record("T7a", f"exit {r.returncode}, {dt:.2f} s, partial={partial}", "exit 5, partial result, <= 7.5 s", r.returncode == 5 and partial and dt <= 7.5, near=dt > 6.75)
    bad = work / "bad.json"
    bad.write_text('{"spec_version": 1, "layers": "oops"}')
    cases = [cli("build", str(bad), "-o", str(work / "bad.coat"), "--force")[0], cli("solve", str(work / "missing.coat"))[0]]
    ok, codes = True, []
    for c in cases:
        codes.append(c.returncode)
        try:
            ok &= json.loads(c.stdout)["ok"] is False and c.returncode != 0 and "Traceback" not in c.stderr
        except ValueError:
            ok = False
    record("T7b", f"exit codes {codes}", "JSON error, non-zero exit, no traceback", ok)


def t8():
    from coating_studio.core import Backing, SheetLayer, SlabLayer, Structure, solve
    from coating_studio.materials.models import ConstantMaterial
    m = {"Air": ConstantMaterial("Air", 1.0, 0.0), "X": ConstantMaterial("X", 2.0, 1e5, 1.0, 1e3), "Y": ConstantMaterial("Y", 4.0, 0.1)}
    f, a = np.array([1e9, 1e10, 1e11]), np.array([0.0, 45.0, 89.99])
    worst, finite = 0.0, True
    stacks = [[SlabLayer("X", 1e-3)], [SlabLayer("X", 1e-12)], [SlabLayer("Y", 1e-12), SheetLayer(377.0, 0.0), SlabLayer("X", 1e-6)], [SlabLayer("Y", 2e-3), SlabLayer("X", 5e-3)]]
    for layers in stacks:
        r = solve(Structure(layers, backing=Backing("halfspace", "Air")), m, f, a, pols=("TE", "TM"))
        for pol in ("TE", "TM"):
            R, T, A = r.quantity("R", pol), r.quantity("T", pol), r.layer_absorption(pol)
            total = R + T + (np.sum(A, axis=0) if A.shape[0] == len(layers) else np.sum(A, axis=-1))
            finite &= bool(np.isfinite(total).all())
            worst = max(worst, float(np.nanmax(np.abs(total - 1))))
    record("T8", f"finite={finite}, max |R+T+sum A-1| = {worst:.2e}", "finite and <= 1e-9", finite and worst <= 1e-9)


GUI_SRC = r'''
import json, os, sys, time, statistics as st, tracemalloc, traceback, threading
import numpy as np, matplotlib
matplotlib.use("QtAgg")
from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QSettings, QTimer
from PySide6.QtWidgets import QApplication
work, best = sys.argv[1], sys.argv[2]
QSettings.setDefaultFormat(QSettings.IniFormat); QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, os.path.join(work, "cfg"))
QCoreApplication.setOrganizationName("CoatingStudioPerf"); QCoreApplication.setApplicationName("CoatingStudioPerf")
app = QApplication([])
from coating_studio.mplfonts import configure_matplotlib_fonts; configure_matplotlib_fonts()
from coating_studio.core import solve
from coating_studio.gui.main_window import MainWindow
from coating_studio.project import Project
out = {}
# Problem A's materials 14-16 trigger the "Run anyway?" pre-flight dialog; a user would press Yes.
from PySide6.QtWidgets import QMessageBox
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Yes)
def fail_dialog(*a, **k):
    raise RuntimeError(f"unexpected dialog: {a[1:3]}")
QMessageBox.critical = staticmethod(fail_dialog)
QMessageBox.information = staticmethod(fail_dialog)
def pump(ms=30):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
def guarded(k, fn):
    try: fn()
    except Exception as e:
        traceback.print_exc(); out[k] = {"error": str(e)}
w = MainWindow(); w.show(); pump(150)
def load(path):
    p = Project.load(os.path.join(work, path) if not os.path.isabs(path) else path); w.doc.set_project(p); pump(250); return p
def rl(res, pol="TE"):
    from coating_studio.core.units import power_to_db
    return power_to_db(res.quantity("R", pol))
def t2a():
    p = load("sal.coat"); w.recompute(); pump(100); P = w.doc.project; s = P.sweep; same = True
    res = solve(P.structure, P.materials, w._f_grid(s.n_f), s.angle)
    for pol in ("TE", "TM"): same &= np.array_equal(w.results["freq"].quantity("R", pol), res.quantity("R", pol))
    out["T2a"] = {"equal": bool(same)}
guarded("T2a", t2a)
def t3c():
    load("A.coat"); xs = []; w.recompute()
    for _ in range(7):
        t = time.perf_counter(); w.recompute(); xs.append(time.perf_counter() - t); pump(10)
    q = st.quantiles(xs, n=4); out["T3c"] = {"median_ms": st.median(xs) * 1e3, "iqr_ms": (q[2] - q[0]) * 1e3}
guarded("T3c", t3c)
def stall_during(start, running, secs=8):
    gaps = []; last = [time.perf_counter()]; t = QTimer(); t.setInterval(25)
    def tick():
        n = time.perf_counter(); gaps.append(n - last[0]); last[0] = n
    t.timeout.connect(tick); t.start(); start(); t0 = time.perf_counter()
    while running() and time.perf_counter() - t0 < secs: pump(5)
    t.stop(); return max(gaps) * 1e3, len(gaps)
def wait(running, secs=120):
    t0 = time.perf_counter()
    while running() and time.perf_counter() - t0 < secs: pump(5)
def t6ab():
    load("A.coat"); opt_run = w.p_opt.is_running
    g1, n1 = stall_during(w.p_opt.run, opt_run, 8)
    t = time.perf_counter(); w.p_opt.stop(); wait(opt_run, 30); s1 = time.perf_counter() - t
    P = w.doc.project; P.tolerance.n_samples = 200000
    tol_run = lambda: w.p_tol.thread is not None
    g2, n2 = stall_during(w.p_tol.run, tol_run, 8)
    t = time.perf_counter(); w.p_tol.stop(); wait(tol_run, 30); s2 = time.perf_counter() - t
    out["T6a"] = {"opt_ms": g1, "tol_ms": g2, "ticks": [n1, n2]}; out["T6b"] = {"opt_s": s1, "tol_s": s2}
guarded("T6a", t6ab)
def t6d():
    load("A.coat"); w.p_opt.run(); pump(300); assert w.p_opt.is_running()
    wk = w.p_opt.worker; ly = wk.project.structure.layers[0]; d0 = ly.thickness; uid = ly.uid
    d_new = d0 * 1.37
    w.doc.edit("perf edit", lambda p: setattr(p.structure.layer_by_uid(uid), "thickness", d_new)); pump(120)
    copy_same = wk.project.structure.layer_by_uid(uid).thickness == d0
    for _ in range(6): w.p_opt.stop(); pump(5)
    wait(w.p_opt.is_running, 30); pump(300)
    out["T6d"] = {"copy_unchanged": bool(copy_same), "doc_kept": w.doc.project.structure.layer_by_uid(uid).thickness == d_new, "stopped": not w.p_opt.is_running()}
guarded("T6d", t6d)
def t6e():
    load("A.coat"); w.recompute(); pump(120); n = [0]; w._timer.timeout.disconnect()
    def counted(): n[0] += 1; w.recompute()
    w._timer.timeout.connect(counted); ly = w.doc.project.structure.layers[0]; uid = ly.uid; d0 = ly.thickness
    for i in range(50):
        w.doc.edit("perf burst", lambda p, v=d0 * (1 + 1e-4 * (i + 1)): setattr(p.structure.layer_by_uid(uid), "thickness", v)); pump(20)
    pump(400); out["T6e"] = {"recomputes": n[0]}
    w._timer.timeout.disconnect(); w._timer.timeout.connect(w.recompute)
guarded("T6e", t6e)
def t5b():
    p = load(best); P = w.doc.project; P.tolerance.n_samples = 2000; P.tolerance.seed = 21; P.tolerance.target_db = float(open(os.path.join(work, "tol_target.txt")).read())
    i = w.p_tol.angle_mode.findData("grid"); w.p_tol.angle_mode.setCurrentIndex(i); w.p_tol.run(); wait(lambda: w.p_tol.thread is not None, 300); pump(100)
    r = w.p_tol.plot.result; gui = r.corners[0][5].worst_db; c = np.load(os.path.join(work, "cli_samples.npy"))
    out["T5b-gui"] = {"n": int(gui.size), "max_diff": float(np.abs(gui - c).max()) if gui.size == c.size else None, "yield": float(r.joint_yield_fraction)}
guarded("T5b-gui", t5b)
def t6c():
    load("A.coat")
    for _ in range(20): w.recompute(); pump(2)
    n0 = len(w.findChildren(QObject)); tracemalloc.start(); pump(5); a = tracemalloc.take_snapshot()
    base = tracemalloc.get_traced_memory()[0]
    for _ in range(180): w.recompute(); pump(2)
    import gc; gc.collect(); grow = tracemalloc.get_traced_memory()[0] - base; tracemalloc.stop()
    out["T6c"] = {"growth_kb": grow / 1024, "qobjects": [n0, len(w.findChildren(QObject))]}
guarded("T6c", t6c)
w.doc._settings_dirty = False; w.doc.undo_stack.setClean()
json.dump(out, open(os.path.join(work, "gui.json"), "w"))
os._exit(0)
'''


def gui(work, best_file):
    src = work / "gui_part.py"
    src.write_text(GUI_SRC)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    r = subprocess.run([PY, "-u", str(src), str(work), str(best_file)], capture_output=True, text=True, env=env, timeout=900)
    if not (work / "gui.json").exists():
        print(r.stdout[-1500:], r.stderr[-1500:])
        raise RuntimeError("GUI part produced no result")
    print("\n".join(line for line in r.stderr.splitlines() if "Traceback" in line or "Error" in line)[:800])
    g = json.loads((work / "gui.json").read_text())
    E = "error"

    def item(tid, fn, limit, required=False):
        d = g.get(tid.split("/")[0], {E: "missing"})
        if E in d:
            record(tid, f"error: {d[E]}", limit, False, required)
        else:
            fn(d)
    item("T2a", lambda d: record("T2a", f"array_equal={d['equal']}", "identical", d["equal"], True), "identical", True)
    item("T3c", lambda d: record("T3c", f"{d['median_ms']:.1f} ms (IQR {d['iqr_ms']:.1f})", "<= 100 ms", d["median_ms"] <= 100, near=d["median_ms"] > 90), "<= 100 ms")
    item("T6a", lambda d: record("T6a", f"optimiser {d['opt_ms']:.0f} ms, tolerance {d['tol_ms']:.0f} ms ({d['ticks']} ticks)", "<= 200 ms", max(d["opt_ms"], d["tol_ms"]) <= 200, near=max(d["opt_ms"], d["tol_ms"]) > 180), "<= 200 ms")
    item("T6b", lambda d: record("T6b", f"optimiser {d['opt_s']:.3f} s, tolerance {d['tol_s']:.3f} s", "<= 1 s", max(d["opt_s"], d["tol_s"]) <= 1, near=max(d["opt_s"], d["tol_s"]) > 0.9), "<= 1 s")
    item("T6c", lambda d: record("T6c", f"{d['growth_kb']:.1f} KB, QObjects {d['qobjects']}", "<= 100 KB, count constant", d["growth_kb"] <= 100 and d["qobjects"][0] == d["qobjects"][1], near=d["growth_kb"] > 90), "<= 100 KB")
    item("T6d", lambda d: record("T6d", str(d), "copy unchanged, edit kept, stopped", d["copy_unchanged"] and d["doc_kept"] and d["stopped"]), "copy unchanged")
    item("T6e", lambda d: record("T6e", f"{d['recomputes']} recomputes", "<= 2", d["recomputes"] <= 2), "<= 2")
    item("T5b-gui", lambda d: record("T5b-gui", f"n={d['n']}, max diff {d['max_diff']}, yield {d['yield']}", "allclose to CLI within 1e-12 dB", d["max_diff"] is not None and d["max_diff"] <= 1e-12, True), "allclose", True)


def main():
    from coating_studio.examples import EXAMPLES
    work = Path(sys.argv[1]).resolve()
    work.mkdir(parents=True, exist_ok=True)
    head = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    print(f"commit {head}, python {sys.version.split()[0]}", flush=True)
    EXAMPLES["salisbury"][1]().save(str(work / "sal.coat"))
    from michielssen_benchmark import search_spec
    (work / "A.json").write_text(json.dumps(search_spec("A")))
    r, _ = cli("build", str(work / "A.json"), "-o", str(work / "A.coat"), "--force")
    assert r.returncode == 0, r.stdout
    t0 = time.time()
    for tid, fn, req in (("T1", t1, True), ("T2b", lambda: t2b(work), True), ("T3a", t3a, False), ("T3b", lambda: t3b(work), False), ("T8", t8, False), ("T7", lambda: t7(work), False)):
        guarded(tid, fn, req)
    best = t4(work)
    guarded("T4d", lambda: t4d(work))
    guarded("T5", lambda: t5(work, best["file"]))
    guarded("GUI", lambda: gui(work, best["file"]), required=True)  # holds the required T2a and T5b-gui
    failed_required = [x["id"] for x in RESULTS if x["required"] and not x["ok"]]
    n_ok = sum(x["ok"] for x in RESULTS)
    print(f"\n{n_ok}/{len(RESULTS)} items passed in {time.time() - t0:.0f} s; required failures: {failed_required or 'none'}")
    (work / "results.json").write_text(json.dumps(RESULTS, indent=1))
    return 1 if failed_required else 0


if __name__ == "__main__":
    raise SystemExit(main())
