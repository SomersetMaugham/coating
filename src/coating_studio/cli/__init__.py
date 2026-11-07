"""``coating-cli``: agent-friendly command-line front end (no Qt).

Every command writes one JSON envelope to stdout (``--help`` and CSV without ``--output`` excepted);
progress goes to stderr as JSON lines with ``--progress``.  Exit codes: 0 ok, 1 internal error, 2 usage,
3 input/output, 4 model, 5 stopped with a partial result, 130 hard interrupt.  RL values are 20*log10|Gamma|
(negative is better); ``margin_db = worst_rl_db - goal_db`` (<= 0 means the target is met).
See docs/CLI_PLAN.md.
"""

from __future__ import annotations

import argparse
import sys
import traceback

from coating_studio.cli import commands as C
from coating_studio.cli.output import (
    EXIT_INTERNAL, EXIT_INTERRUPTED, EXIT_OK, EXIT_STOPPED, EXIT_USAGE, CliError, dumps, envelope,
)
from coating_studio.cli.progress import RunControl, signal_handlers


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _UsageError(f"{self.prog}: {message}")


def _journal(sub):
    sub.add_argument("--journal", metavar="DIR", help="append this run to the experiment journal in DIR")
    sub.add_argument("--note", default="", help="why this run was made (stored in the journal)")


def _common(sub, long_running=False, export=False):
    if export:
        sub.add_argument("--format", choices=("json", "csv"), default="json",
                         help="csv: same columns as the GUI data export (CSV goes to stdout without --output)")
        sub.add_argument("--output", "-o", help="write the result (JSON or CSV) to this file")
        sub.add_argument("--force", action="store_true", help="overwrite an existing --output file")
    if long_running:
        sub.add_argument("--timeout", type=float, help="stop after SEC seconds and return the best partial result (exit 5)")
        sub.add_argument("--progress", action="store_true", help="JSON-lines progress on stderr")
        sub.add_argument("--progress-interval", type=float, default=1.0, metavar="SEC")


def build_parser():
    ap = _Parser(prog="coating-cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="command", required=True, parser_class=_Parser)

    ex = sp.add_parser("examples", help="list bundled example projects or save one as .coat")
    ex_sp = ex.add_subparsers(dest="action", required=True, parser_class=_Parser)
    ex_sp.add_parser("list", help="list the examples")
    ex_save = ex_sp.add_parser("save", help="save an example as a .coat file")
    ex_save.add_argument("key")
    ex_save.add_argument("--output", "-o", required=True)
    ex_save.add_argument("--force", action="store_true")

    info = sp.add_parser("info", help="project summary: layers, materials, targets, variables, parameter paths")
    info.add_argument("file")

    chk = sp.add_parser("check", help="validate the model: trial solve, material checks, optimisation pre-flight")
    chk.add_argument("file")
    chk.add_argument("--no-opt", action="store_true", help="skip the optimisation pre-flight")
    _journal(chk)

    so = sp.add_parser("solve", help="frequency / angle / map sweep with a summary")
    so.add_argument("file")
    so.add_argument("--sweep", choices=("freq", "angle", "map"), default="freq")
    so.add_argument("--quantity", choices=("RL", "R", "T", "A"), default="RL", help="CSV column quantity")
    so.add_argument("--pol", choices=("TE", "TM", "avg"), default="avg", help="map / CSV-map polarisation")
    so.add_argument("--targets", action="store_true", help="add worst RL and margin per enabled target")
    so.add_argument("--summary-only", action="store_true", help="omit the data arrays")
    so.add_argument("--layer-absorption", action="store_true")
    so.add_argument("--touchstone", metavar="PATH",
                    help="also write the frequency sweep's S11 as a Touchstone .s1p (one polarisation: --pol TE or "
                         "TM; avg is accepted only at normal incidence, where TE = TM)")
    for name in ("--f-min-ghz", "--f-max-ghz", "--f-at-ghz", "--angle-deg", "--angle-min-deg", "--angle-max-deg"):
        so.add_argument(name, type=float)
    for name in ("--n-f", "--n-angle", "--map-n-f", "--map-n-angle"):
        so.add_argument(name, type=int)
    so.add_argument("--log-f", dest="log_f", action="store_const", const=True)
    so.add_argument("--linear-f", dest="log_f", action="store_const", const=False)
    _common(so, export=True)
    _journal(so)

    op = sp.add_parser("optimize", help="run the optimisation; -o saves the optimised design")
    op.add_argument("file")
    op.add_argument("--output", "-o", help="save the optimised project (.coat)")
    op.add_argument("--in-place", action="store_true", help="overwrite the input file with the result")
    op.add_argument("--force", action="store_true")
    op.add_argument("--seed", type=int, help="random seed; negative = random (the seed used is reported)")
    op.add_argument("--maxiter", type=int)
    op.add_argument("--popsize", type=int)
    op.add_argument("--no-polish", dest="polish", action="store_const", const=False)
    op.add_argument("--strict", action="store_true", help="stop on pre-flight warnings (exit 4)")
    op.add_argument("--restarts", type=int, default=1, help="run N seeds (seed, seed+1, ...) and keep the best")
    _common(op, long_running=True)
    _journal(op)

    to = sp.add_parser("tolerance", help="Monte-Carlo tolerance analysis (bands and yield)")
    to.add_argument("file")
    to.add_argument("--seed", type=int)
    to.add_argument("--n-samples", type=int)
    to.add_argument("--target-db", type=float, help="yield criterion (default: the project's tolerance target)")
    to.add_argument("--angle-deg", type=float)
    to.add_argument("--pol", choices=("TE", "TM", "avg"))
    to.add_argument("--samples", action="store_true", help="include every sample's in-band worst RL")
    to.add_argument("--summary-only", action="store_true")
    to.add_argument("--corners", action="store_true",
                    help="yield at every angle end x polarisation of each enabled target, plus the joint yield")
    _common(to, long_running=True, export=True)
    _journal(to)

    ma = sp.add_parser("materials", help="built-in materials as spec-ready dicts, with parameter paths")
    ma.add_argument("--name")
    ma.add_argument("--library", help="also list a user library JSON file")

    bo = sp.add_parser("bound", help="Rozanov minimum mu_s*d (and thickness) for a band and RL goal")
    bo.add_argument("--f-ghz", type=float, nargs=2, required=True, metavar=("LO", "HI"))
    bo.add_argument("--goal-db", type=float, required=True)
    bo.add_argument("--mu-s", type=float, default=1.0)

    fi = sp.add_parser("fit", help="fit Debye/Lorentz terms to a measured CSV; prints a spec-ready material",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    fi.add_argument("csv")
    fi.add_argument("--name")
    fi.add_argument("--eps-debye", type=int, default=1)
    fi.add_argument("--eps-lorentz", type=int, default=0)
    fi.add_argument("--sigma", action="store_true")
    fi.add_argument("--eps-const-loss", action="store_true")
    fi.add_argument("--mu-debye", type=int, default=0)
    fi.add_argument("--mu-lorentz", type=int, default=0)
    fi.add_argument("--mu-const-loss", action="store_true")
    fi.add_argument("--density", type=float, default=1000.0)

    bu = sp.add_parser("build", help="build a .coat project from a design spec (JSON)")
    bu.add_argument("spec")
    bu.add_argument("--output", "-o", required=True)
    bu.add_argument("--force", action="store_true")

    se = sp.add_parser("spec", help="export a .coat project as a design spec (inverse of build)")
    se.add_argument("file")
    se.add_argument("--output", "-o", help="write the bare spec to this file (for editing and build)")
    se.add_argument("--force", action="store_true")

    jo = sp.add_parser("journal", help="summarise an experiment journal directory")
    jo.add_argument("dir")
    return ap


def _run(args, control):
    c = args.command
    if c == "examples":
        return C.cmd_examples_list() if args.action == "list" else C.cmd_examples_save(args.key, args.output, args.force)
    if c == "info":
        return C.cmd_info(args.file)
    if c == "check":
        return C.cmd_check(args.file, no_opt=args.no_opt)
    if c == "solve":
        overrides = {k: getattr(args, k) for k in ("f_min_ghz", "f_max_ghz", "f_at_ghz", "angle_deg", "angle_min_deg",
                                                    "angle_max_deg", "n_f", "n_angle", "map_n_f", "map_n_angle", "log_f")}
        return C.cmd_solve(args.file, args.sweep, args.quantity, args.pol, args.targets or bool(args.journal),
                           args.summary_only,
                           args.layer_absorption, args.format, args.output, args.force, overrides,
                           touchstone=args.touchstone)
    if c == "optimize":
        return C.cmd_optimize(args.file, control, args.output, args.in_place, args.force, args.seed, args.maxiter,
                              args.popsize, args.polish, args.strict, args.restarts)
    if c == "tolerance":
        return C.cmd_tolerance(args.file, control, args.seed, args.n_samples, args.target_db, args.angle_deg,
                               args.pol, args.samples, args.summary_only, args.format, args.output, args.force,
                               args.corners)
    if c == "materials":
        return C.cmd_materials(args.name, args.library)
    if c == "bound":
        return C.cmd_bound(args.f_ghz[0], args.f_ghz[1], args.goal_db, args.mu_s)
    if c == "fit":
        return C.cmd_fit(args.csv, args.name, args.eps_debye, args.eps_lorentz, args.sigma, args.eps_const_loss,
                         args.mu_debye, args.mu_lorentz, args.mu_const_loss, args.density)
    if c == "build":
        return C.cmd_build(args.spec, args.output, args.force)
    if c == "spec":
        return C.cmd_spec(args.file, args.output, args.force)
    if c == "journal":
        return C.cmd_journal(args.dir)
    raise _UsageError(f"unknown command {c!r}")


def main(argv=None, stdout=None, stderr=None, control=None) -> int:
    """Run the CLI; returns the exit code (never calls sys.exit, so tests can call it in-process).

    ``control`` lets tests pass a ``RunControl`` whose ``stop_event`` they set themselves."""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    argv = list(sys.argv[1:] if argv is None else argv)
    command = next((a for a in argv if not a.startswith("-")), None)

    def write(env):
        out.write(dumps(env) + "\n")
        out.flush()

    try:
        args = build_parser().parse_args(argv)
    except _UsageError as e:
        write(envelope(command, error={"code": "usage", "message": str(e), "details": {}}))
        return EXIT_USAGE
    except SystemExit as e:  # --help / --version print text and exit 0
        return int(e.code or 0)

    command = args.command
    if control is None:
        control = RunControl(timeout=getattr(args, "timeout", None), progress=getattr(args, "progress", False),
                             progress_interval=getattr(args, "progress_interval", 1.0), command=command, stream=err)
    journal_dir = getattr(args, "journal", None)

    def journal(result, code, stopped, error_code=None):
        if not journal_dir or error_code in ("file_not_found", "file_unreadable", "usage"):
            return  # nothing was run on a design; keep the journal to real trials
        from coating_studio.cli.journal import record
        record(journal_dir, command=command, argv=argv, note=getattr(args, "note", ""),
               input_path=getattr(args, "file", None), result=result, exit_code=code, stopped=stopped,
               error_code=error_code, output_path=getattr(args, "output", None) if command == "optimize" else None)

    try:
        with signal_handlers(control):
            res = _run(args, control)
    except CliError as e:
        try:
            journal(e.result, e.exit_code, False, e.code)
        except CliError:
            pass
        write(envelope(command, result=e.result,
                       error={"code": e.code, "message": e.message, "details": e.details}))
        return e.exit_code
    except KeyboardInterrupt:
        write(envelope(command, error={"code": "interrupted", "message": "interrupted", "details": {}}))
        return EXIT_INTERRUPTED
    except Exception as e:  # noqa: BLE001 - reported as an internal error, never as a raw traceback only
        write(envelope(command, error={"code": "internal_error", "message": f"{type(e).__name__}: {e}",
                                       "details": {"traceback": traceback.format_exc(limit=5)}}))
        return EXIT_INTERNAL
    code = EXIT_STOPPED if res.stopped else EXIT_OK
    try:
        journal(res.result, code, res.stopped)
    except CliError as e:
        res.warnings.append({"code": e.code, "level": "warning", "message": e.message})
    if res.text is not None:
        out.write(res.text)
        out.flush()
        return code
    write(envelope(command, result=res.result, input_info=res.input_info, warnings=res.warnings,
                   stopped=res.stopped))
    return EXIT_STOPPED if res.stopped else EXIT_OK
