"""Output contract of ``coating-cli``: the JSON envelope, value sanitising, error codes, exit codes.

Every command writes exactly one JSON object to stdout (docs/CLI_PLAN.md, section 4).  Invariant:
``ok`` is true exactly when the exit code is 0 or 5 (stopped with a partial result).
"""

from __future__ import annotations

import json
import math

import numpy as np

from coating_studio import __version__
from coating_studio.core.solver import SolverError
from coating_studio.materials.csvio import CsvFormatError
from coating_studio.materials.models import MaterialCycleError, OutOfRangeError
from coating_studio.optimize.optimizer import OptimizationError
from coating_studio.project import NewerSchemaError, ProjectError

CLI_SCHEMA = 1

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_INPUT = 3
EXIT_MODEL = 4
EXIT_STOPPED = 5
EXIT_INTERRUPTED = 130


class CliError(Exception):
    """A failure reported as ``ok: false``.  ``result`` (optional) is still written (e.g. ``check``)."""

    def __init__(self, code, message, exit_code, details=None, result=None):
        super().__init__(message)
        self.code, self.message, self.exit_code = code, message, exit_code
        self.details = details or {}
        self.result = result


def sanitize(obj):
    """Make ``obj`` strict-JSON safe: non-finite floats -> None, numpy scalars/arrays -> Python, tuples -> lists.

    ``json.dumps`` handles floats before calling ``default``, so ``allow_nan=False`` alone would raise on NaN
    instead of writing null; hence this explicit pass."""
    if isinstance(obj, dict):
        return {str(k): sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return sanitize(obj.tolist())
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        x = float(obj)
        return x if math.isfinite(x) else None
    if isinstance(obj, complex):
        raise TypeError("complex values are not part of the CLI output")
    return obj


def dumps(obj) -> str:
    return json.dumps(sanitize(obj), allow_nan=False, ensure_ascii=False)


def envelope(command, *, result=None, error=None, input_info=None, warnings=None, stopped=False):
    env = {"ok": error is None, "command": command, "cli_schema": CLI_SCHEMA, "app_version": __version__,
           "input": input_info}
    if result is not None:
        env["result"] = result
    env["warnings"] = list(warnings or [])
    env["stopped"] = bool(stopped)
    if error is not None:
        env["error"] = error
    return env


# ---------------------------------------------------------------------------
# exception -> (code, exit code, details)

def load_error(exc, path) -> CliError:
    """Map an exception raised while reading a project file (section 4.5, file stage)."""
    if isinstance(exc, FileNotFoundError):
        return CliError("file_not_found", f"{path}: no such file", 3, {"path": str(path)})
    if isinstance(exc, OSError):
        return CliError("file_unreadable", f"{path}: {exc.strerror or exc}", 3, {"path": str(path)})
    if isinstance(exc, NewerSchemaError):
        return CliError("newer_schema", str(exc), 3, {"schema": exc.schema, "supported": exc.supported})
    return CliError("invalid_project", f"{path}: {exc}", 3, {"path": str(path), "exception": type(exc).__name__})


LOAD_ERRORS = (OSError, ProjectError, UnicodeDecodeError, ValueError, KeyError, TypeError, AttributeError)


def model_error(exc) -> CliError:
    """Map an exception raised while computing (section 4.5, computation stage).  Subclasses first."""
    if isinstance(exc, OutOfRangeError):
        return CliError("material_out_of_range", str(exc), 4,
                        {"material": exc.material, "data_lo_hz": exc.data_lo, "data_hi_hz": exc.data_hi,
                         "req_lo_hz": exc.f_lo, "req_hi_hz": exc.f_hi})
    if isinstance(exc, MaterialCycleError):
        return CliError("material_cycle", str(exc), 4)
    if isinstance(exc, SolverError):
        return CliError("solver_error", str(exc), 4)
    if isinstance(exc, OptimizationError):
        return CliError("invalid_optimization_settings", str(exc), 4)
    if isinstance(exc, CsvFormatError):
        return CliError("invalid_value", str(exc), 4)
    if isinstance(exc, KeyError):
        return CliError("unknown_reference", f"unknown reference {exc}", 4, {"ref": str(exc.args[0]) if exc.args else ""})
    if isinstance(exc, ValueError):
        return CliError("invalid_value", str(exc), 4)
    raise exc


MODEL_ERRORS = (OutOfRangeError, MaterialCycleError, SolverError, OptimizationError, KeyError, ValueError)


def issue_dict(issue, target=None):
    """A ``materials.checks.Issue`` (or compatible) as JSON."""
    from coating_studio.i18n import issue_text

    return {"level": issue.level, "code": issue.code, "material": issue.material, "target": target,
            "args": dict(issue.args), "message": issue_text(issue, lang="en")}
