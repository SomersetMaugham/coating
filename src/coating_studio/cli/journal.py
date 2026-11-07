"""Experiment journal written by the tool itself (docs/CLI_PLAN.md, section 13.3).

``--journal DIR`` appends one JSON line per command to ``DIR/journal.jsonl`` and keeps content-addressed
snapshots of the input (and output) project in ``DIR/snapshots/<sha256[:12]>.coat``.  Trials are comparable
only within one ``spec_fingerprint`` (the enabled targets and the thickness limit).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil

from coating_studio.cli.output import CliError, dumps
from coating_studio.project import Project


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(directory, path):
    """Copy ``path`` into the journal's snapshot store; returns (relative path, sha256)."""
    sha = _sha(path)
    rel = os.path.join("snapshots", sha[:12] + ".coat")
    dest = os.path.join(directory, rel)
    if not os.path.exists(dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(path, dest)
    return rel.replace(os.sep, "/"), sha


def spec_fingerprint(project: Project):
    s = project.optimization
    key = {"targets": [t.to_dict() for t in s.enabled_targets()], "thickness_max": s.thickness_max}
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:12]


def summarize(command, result):
    """The comparable numbers of a result (kept small: the journal is read back by agents)."""
    r = result or {}
    out = {}
    if command == "solve":
        out["best_rl_db"] = {q: v.get("rl_db") for q, v in r.get("summary", {}).get("best", {}).items()}
        out["total_thickness_m"] = r.get("summary", {}).get("total_thickness_m")
    elif command == "optimize":
        out["terms"] = r.get("terms")
        out["total_thickness_m"] = (r.get("terms") or {}).get("thickness_m")
        out["seed_used"] = r.get("seed_used")
    elif command == "tolerance":
        out["yield_fraction"] = r.get("yield_fraction", r.get("joint_yield_fraction"))
        out["target_db"] = r.get("target_db")
        out["seed_used"] = r.get("seed_used")
        if r.get("angle_mode"):
            out["angle_mode"] = r["angle_mode"]
    elif command == "check":
        out["counts"] = r.get("counts")
        out["limits"] = [lim.get("status") for lim in r.get("limits", [])]
    if "targets" in r:
        out["targets"] = r["targets"]
        out["max_margin_db"] = r.get("max_margin_db")
    return out


def record(directory, *, command, argv, note, input_path, result, exit_code, stopped, error_code=None,
           output_path=None, extra_summary=None):
    try:
        os.makedirs(directory, exist_ok=True)
        jpath = os.path.join(directory, "journal.jsonl")
        seq = 1
        if os.path.exists(jpath):
            with open(jpath, encoding="utf-8") as fh:
                seq = sum(1 for line in fh if line.strip()) + 1
        entry = {"seq": seq, "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                 "command": command, "argv": list(argv), "note": note, "exit_code": exit_code,
                 "stopped": stopped, "error_code": error_code}
        if input_path and os.path.isfile(input_path):
            snap, sha = snapshot(directory, input_path)
            entry["input"] = {"path": str(input_path), "sha256": sha}
            entry["snapshot"] = snap
            try:
                p = Project.load(input_path)
                entry["spec_fingerprint"] = spec_fingerprint(p)
                entry["thickness_max_m"] = p.optimization.thickness_max
            except Exception:  # noqa: BLE001 - a broken input is still journaled
                entry["spec_fingerprint"] = None
        if output_path and str(output_path).endswith(".coat") and os.path.isfile(output_path):
            entry["output_snapshot"], _ = snapshot(directory, output_path)
        summary = summarize(command, result)
        summary.update(extra_summary or {})
        entry["summary"] = summary
        entry["seed_used"] = (result or {}).get("seed_used")
        if (result or {}).get("best_seed") is not None:
            entry["best_seed"] = result["best_seed"]  # the seed that produced the reported design
        with open(jpath, "a", encoding="utf-8") as fh:
            fh.write(dumps(entry) + "\n")
    except OSError as e:
        raise CliError("file_unwritable", f"journal {directory}: {e.strerror or e}", 3, {"path": str(directory)}) from None


def read(directory):
    jpath = os.path.join(directory, "journal.jsonl")
    if not os.path.isfile(jpath):
        raise CliError("file_not_found", f"{jpath}: no journal", 3, {"path": jpath})
    entries = []
    with open(jpath, encoding="utf-8") as fh:
        for n, line in enumerate(fh, start=1):
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    raise CliError("invalid_value", f"{jpath}:{n}: not JSON", 3, {"line": n}) from None
    return entries


def report(directory):
    entries = read(directory)
    groups = {}
    for e in entries:
        groups.setdefault(e.get("spec_fingerprint"), []).append(e)
    fingerprints = []
    for fp, es in groups.items():
        best = None
        for e in es:
            m = (e.get("summary") or {}).get("max_margin_db")
            if m is None or e.get("error_code"):
                continue
            tmax = e.get("thickness_max_m")
            th = (e.get("summary") or {}).get("total_thickness_m")
            if tmax is not None and th is not None and th > tmax * (1 + 1e-9):
                continue
            if best is None or m < best["max_margin_db"]:
                best = {"seq": e["seq"], "command": e["command"], "max_margin_db": m,
                        "snapshot": e.get("output_snapshot") or e.get("snapshot"), "note": e.get("note")}
        targets = next(((e.get("summary") or {}).get("targets") for e in es if (e.get("summary") or {}).get("targets")), None)
        fingerprints.append({"spec_fingerprint": fp, "n_trials": len(es),
                             "targets": [{"name": t.get("name"), "goal_db": t.get("goal_db")} for t in targets or []],
                             "thickness_max_m": es[-1].get("thickness_max_m"), "best": best})
    trials = [{"seq": e["seq"], "command": e["command"], "note": e.get("note"), "exit_code": e.get("exit_code"),
               "stopped": e.get("stopped"), "spec_fingerprint": e.get("spec_fingerprint"),
               "max_margin_db": (e.get("summary") or {}).get("max_margin_db"),
               "snapshot": e.get("snapshot"), "output_snapshot": e.get("output_snapshot"),
               "seed_used": e.get("seed_used"), "best_seed": e.get("best_seed")} for e in entries]
    warnings = []
    if len(groups) > 1:
        warnings.append({"code": "targets_changed", "level": "warning",
                         "message": f"targets or thickness limit changed during the run ({len(groups)} fingerprints); "
                                    "margins are comparable only within one fingerprint"})
    return {"n_trials": len(entries), "fingerprints": fingerprints, "trials": trials}, warnings
