"""Reading measured eps/mu or refractive-index data from CSV files.

Accepted layouts (comma, semicolon, tab or whitespace separated)::

    x, eps', eps'', [mu', mu'']      permittivity / permeability (default)
    x, eps', tan d, [mu', tan d]     loss tangent instead of a loss column (header needed)
    x, n, k                          refractive index N = n - jk  (mu = 1)
    x, n                             lossless refractive index (k = 0)

A header row is needed to select the n/k layout (value columns named ``n`` and
``k``).  The first header cell sets the abscissa ``x``:

* frequency: Hz / kHz / MHz / GHz / THz (default GHz, also when there is no header)
* wavelength: nm / um (µm) / mm / cm / m, or a bare ``wavelength`` / ``wl`` /
  ``lambda`` / ``λ`` heading, which means micrometres
* wavenumber: cm-1 (cm^-1, cm⁻¹, 1/cm)

refractiveindex.info's two-block export (a ``wl,n`` block followed by a ``wl,k``
block) is also read: k is interpolated onto the n grid (on the file's own axis),
and points outside the k data are dropped.  Loss columns use the engineering convention (eps'' > 0 and
k > 0 mean loss).  Lines starting with '#' are comments.
"""

from __future__ import annotations

import csv
import io
import re

import numpy as np

from coating_studio.core.constants import C0
from coating_studio.materials.models import TabulatedMaterial, eps_from_nk

_FREQ_UNITS = {"thz": 1e12, "ghz": 1e9, "mhz": 1e6, "khz": 1e3}
_LEN_UNITS = {"nm": 1e-9, "um": 1e-6, "µm": 1e-6, "μm": 1e-6, "mm": 1e-3, "cm": 1e-2, "m": 1.0}
_WAVENUMBER = re.compile(r"cm\s*(\^?\s*-\s*1|⁻¹)|1\s*/\s*cm")
_LENGTH = re.compile(r"(?<![a-zµμ])(nm|um|µm|μm|mm|cm|m)(?![a-z])")
_WL_WORDS = re.compile(r"wavelength|\bwl\b|lambda|λ")


class CsvFormatError(ValueError):
    pass


def _abscissa(header_cell: str):
    """Return a function mapping the first column to frequency [Hz]."""
    h = header_cell.lower()
    if _WAVENUMBER.search(h):
        return lambda v: C0 * 100.0 * v
    for key, s in _FREQ_UNITS.items():
        if key in h:
            return lambda v, s=s: v * s
    if re.search(r"\bhz\b|\(hz\)|\[hz\]", h):
        return lambda v: v
    m = _LENGTH.search(h)
    if m or _WL_WORDS.search(h):
        s = _LEN_UNITS[m.group(1)] if m else 1e-6
        return lambda v, s=s: C0 / (v * s)
    return lambda v: v * 1e9


def _is_loss_tangent(cell: str) -> bool:
    """Header names a loss tangent: tan d, tand, tan δ, tanδε, tan_delta_mu, tan(δ), loss tangent ..."""
    c = re.sub(r"[\s_\-]", "", cell.lower())
    if "losstangent" in c:
        return True
    return c.startswith("tan") and c[3:].lstrip("([").startswith(("δ", "d", "delta"))


def _apply_loss_tangents(header, arr):
    """Replace tan δ columns (3rd for ε, 5th for μ) by ε″ = ε′·tan δ / μ″ = μ′·tan δ."""
    if not header:
        return arr
    tan_cols = [i for i, c in enumerate(header) if i > 0 and _is_loss_tangent(c)]
    if not tan_cols:
        return arr
    if any(i not in (2, 4) for i in tan_cols):
        raise CsvFormatError("a loss tangent column must follow its real part (columns 3 and 5)")
    arr = arr.copy()
    for i in tan_cols:
        real, tan = arr[:, i - 1], arr[:, i]
        if np.any(tan < 0):
            raise CsvFormatError("loss tangent must be non-negative")
        if np.any(real <= 0):
            raise CsvFormatError("loss tangent needs a positive real part in the column before it")
        arr[:, i] = real * tan
    return arr


def _column_kind(cell: str) -> str:
    c = re.sub(r"[\s_]", "", cell.lower())
    if c in ("n", "re(n)", "nreal"):
        return "n"
    if c in ("k", "κ", "im(n)", "kappa"):
        return "k"
    return "other"


def _is_number(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def _split_rows(text):
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        raise CsvFormatError("file is empty")
    try:
        delim = csv.Sniffer().sniff("\n".join(lines[:5]), delimiters=",;\t ").delimiter
    except csv.Error:
        delim = None
    rows = []
    for ln in lines:
        cells = [c.strip() for c in (ln.split(delim) if delim and delim != " " else ln.split())]
        rows.append([c for c in cells if c != ""])
    return rows


def _blocks(rows):
    """Split into (header or None, numeric array) blocks at every header row."""
    blocks, header, data = [], None, []

    def flush():
        if header is not None or data:
            blocks.append((header, data))

    for n, r in enumerate(rows, start=1):
        if not all(_is_number(c) for c in r):
            if data or header is not None:
                flush()
            header, data = r, []
            continue
        data.append((n, [float(c) for c in r]))
    flush()
    out = []
    for header, data in blocks:
        if len(data) < 2:
            raise CsvFormatError("need at least two data rows")
        if len({len(v) for _, v in data}) != 1:
            raise CsvFormatError("rows have inconsistent column counts")
        out.append((header, np.array([v for _, v in data])))
    return out


def _check_f(f):
    if np.any(~np.isfinite(f)) or np.any(f <= 0):
        raise CsvFormatError("frequencies must be positive")
    if len(np.unique(f)) != len(f):
        raise CsvFormatError("duplicate frequencies")


def _nk_result(f, n, k):
    if np.any(n < 0) or np.any(k < 0):
        raise CsvFormatError("n and k must be non-negative")
    eps = eps_from_nk(n, k)
    return f, eps.real, -eps.imag, np.ones(len(f)), np.zeros(len(f))


def _merge_nk_blocks(blocks):
    """refractiveindex.info style: separate (x, n) and (x, k) blocks."""
    cols = {}
    for header, arr in blocks:
        kind = _column_kind(header[1]) if header and len(header) == 2 else "other"
        if arr.shape[1] != 2 or kind not in ("n", "k") or kind in cols:
            raise CsvFormatError("multiple blocks are only supported as one 'x, n' and one 'x, k' block")
        cols[kind] = (_abscissa(header[0])(arr[:, 0]), arr[:, 1], arr[:, 0], header[0])
    if "n" not in cols:
        raise CsvFormatError("no n block found")
    f, n, xn, hn = cols["n"]
    _check_f(f)
    if "k" not in cols:
        return _nk_result(f, n, np.zeros(len(f)))
    fk, k, xk, hk = cols["k"]
    _check_f(fk)
    # Interpolate on the file's own axis (e.g. wavelength) when both blocks share it.
    if hn.strip().lower() != hk.strip().lower():
        xn, xk = f, fk
    order = np.argsort(xk)
    xk, k = xk[order], k[order]
    span = 1e-12 * abs(xk[-1])
    keep = (xn >= xk[0] - span) & (xn <= xk[-1] + span)
    if keep.sum() < 2:
        raise CsvFormatError("the n and k blocks do not overlap")
    return _nk_result(f[keep], n[keep], np.interp(xn[keep], xk, k))


def parse_csv_text(text: str):
    """Return (f_Hz, eps_re, eps_loss, mu_re, mu_loss) arrays."""
    blocks = _blocks(_split_rows(text))
    if len(blocks) > 1:
        return _merge_nk_blocks(blocks)
    header, arr = blocks[0]
    to_f = _abscissa(header[0]) if header else (lambda v: v * 1e9)
    f = to_f(arr[:, 0])
    kinds = [_column_kind(c) for c in header[1:]] if header else []
    if kinds[:2] in (["n", "k"], ["n"]):
        if arr.shape[1] != len(kinds) + 1 or arr.shape[1] not in (2, 3):
            raise CsvFormatError(f"n/k data: expected 2 or 3 columns, found {arr.shape[1]}")
        _check_f(f)
        k = arr[:, 2] if arr.shape[1] == 3 else np.zeros(len(f))
        return _nk_result(f, arr[:, 1], k)
    if arr.shape[1] not in (3, 5):
        raise CsvFormatError(f"expected 3 or 5 columns, found {arr.shape[1]}")
    _check_f(f)
    arr = _apply_loss_tangents(header, arr)
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
