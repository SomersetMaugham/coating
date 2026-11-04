"""Reading measured eps/mu data from CSV files.

Accepted layout (comma, semicolon, tab or whitespace separated)::

    f, eps', eps'', [mu', mu'']

The frequency unit is taken from the header (Hz / kHz / MHz / GHz / THz) and
defaults to GHz.  Loss columns use the engineering convention (eps'' > 0 means
loss).  Lines starting with '#' are comments.
"""

from __future__ import annotations

import csv
import io
import re

import numpy as np

from coating_studio.materials.models import TabulatedMaterial

_UNITS = {"thz": 1e12, "ghz": 1e9, "mhz": 1e6, "khz": 1e3, "hz": 1.0}


class CsvFormatError(ValueError):
    pass


def _detect_unit(header_cell: str) -> float:
    h = header_cell.lower()
    for key in ("thz", "ghz", "mhz", "khz"):
        if key in h:
            return _UNITS[key]
    if re.search(r"\bhz\b|\(hz\)|\[hz\]", h):
        return 1.0
    return 1e9


def parse_csv_text(text: str):
    """Return (f_Hz, eps_re, eps_loss, mu_re, mu_loss) arrays."""
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        raise CsvFormatError("file is empty")
    sample = "\n".join(lines[:5])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t ")
        delim = dialect.delimiter
    except csv.Error:
        delim = None
    rows = []
    for ln in lines:
        cells = [c.strip() for c in (ln.split(delim) if delim and delim != " " else ln.split())]
        rows.append([c for c in cells if c != ""])

    scale = 1e9
    def is_number(s):
        try:
            float(s)
            return True
        except ValueError:
            return False

    if rows and not all(is_number(c) for c in rows[0]):
        scale = _detect_unit(rows[0][0])
        rows = rows[1:]
    data = []
    for n, r in enumerate(rows, start=1):
        try:
            vals = [float(c) for c in r]
        except ValueError:
            raise CsvFormatError(f"row {n}: non-numeric value") from None
        if len(vals) not in (3, 5):
            raise CsvFormatError(f"row {n}: expected 3 or 5 columns, found {len(vals)}")
        data.append(vals)
    if len(data) < 2:
        raise CsvFormatError("need at least two data rows")
    ncol = {len(r) for r in data}
    if len(ncol) != 1:
        raise CsvFormatError("rows have inconsistent column counts")
    arr = np.array(data)
    f = arr[:, 0] * scale
    if np.any(f <= 0):
        raise CsvFormatError("frequencies must be positive")
    if len(np.unique(f)) != len(f):
        raise CsvFormatError("duplicate frequencies")
    if arr.shape[1] == 5:
        return f, arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]
    return f, arr[:, 1], arr[:, 2], np.ones(len(f)), np.zeros(len(f))


def load_csv(path, name=None, density=1000.0) -> TabulatedMaterial:
    import os

    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    f, er, el, mr, ml = parse_csv_text(text)
    name = name or os.path.splitext(os.path.basename(path))[0]
    return TabulatedMaterial(name, f, er, el, mr, ml, source=os.path.basename(path), density=density)


def to_csv_text(f, eps, mu) -> str:
    out = io.StringIO()
    out.write("f [GHz],eps',eps'',mu',mu''\n")
    for fi, e, m in zip(f, eps, mu):
        out.write(f"{fi / 1e9:.9g},{e.real:.9g},{-e.imag:.9g},{m.real:.9g},{-m.imag:.9g}\n")
    return out.getvalue()
