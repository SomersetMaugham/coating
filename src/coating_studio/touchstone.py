"""Touchstone 1.x files: write a design's reflection (.s1p), read a measured S11 (.s1p) or two-port data (.s2p).

No Qt or matplotlib here (the CLI uses it).

S11 is the reflection coefficient Gamma of one polarisation, which is normalised to the modal wave impedance
of the incident medium (TE: eta/cos(theta), TM: eta*cos(theta)).  That impedance is written as the reference
resistance ``R``, so a tool that converts S11 to an impedance, Z = R(1 + S11)/(1 - S11), obtains the input
wave impedance in ohms.  Both formats use the engineering time convention e^{+j omega t}, as the solver does.
"""

from __future__ import annotations

import io

import numpy as np

from coating_studio.core.constants import ETA0
from coating_studio.core.solver import solve

_UNITS = {"HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9}


class TouchstoneError(ValueError):
    pass


def modal_impedance(project, f, theta_deg, pol):
    """Wave impedance of the incident medium for ``pol`` at angle ``theta_deg`` (ohm), per frequency."""
    mat = project.materials[project.structure.incident]
    eps, mu = mat.eps_mu(np.asarray(f, dtype=float), project.resolver)
    eps, mu = np.broadcast_to(eps, np.shape(f)), np.broadcast_to(mu, np.shape(f))
    eta = ETA0 * np.sqrt(mu / eps)
    c = np.cos(np.radians(theta_deg))
    return eta / c if pol == "TE" else eta * c


def design_s11(project, pol="TE", f=None, theta_deg=None):
    """(f [Hz], S11, reference resistance [ohm], comment lines) of the current design on the sweep grid."""
    if pol not in ("TE", "TM"):
        raise ValueError("a Touchstone file holds one polarisation: TE or TM")
    sw = project.sweep
    f = sw.freq_grid() if f is None else np.asarray(f, dtype=float)
    theta = sw.angle if theta_deg is None else float(theta_deg)
    res = solve(project.structure, project.materials, f, theta, pols=(pol,))
    s11 = res.pol[pol].gamma[:, 0]
    z = modal_impedance(project, f, theta, pol)
    zr = np.real(z)
    ref = float(zr[len(zr) // 2])
    notes = [f"Coating Studio design '{project.name}': reflection coefficient, {pol}, incidence {theta:g} deg",
             f"Reference R = wave impedance of the incident medium ({project.structure.incident}) for {pol}",
             "Time convention exp(+j*omega*t); RL [dB] = 20*log10|S11|"]
    if np.max(np.abs(z - ref)) > 1e-6 * abs(ref):
        notes.append("The incident medium is dispersive: S11 is normalised to its wave impedance at each "
                     f"frequency; R is the value at {f[len(f) // 2] / 1e9:.6g} GHz")
    return f, s11, ref, notes


def format_s1p(f, s11, ref_ohm=50.0, comments=(), fmt="RI"):
    """Touchstone 1.x text, frequencies in GHz."""
    fmt = fmt.upper()
    out = io.StringIO()
    for line in comments:
        out.write(f"! {line}\n")
    out.write(f"# GHZ S {fmt} R {ref_ohm:.9g}\n")
    for fi, s in zip(np.asarray(f, dtype=float), np.asarray(s11, dtype=complex)):
        if fmt == "RI":
            a, b = s.real, s.imag
        elif fmt == "MA":
            a, b = abs(s), np.degrees(np.angle(s))
        elif fmt == "DB":
            a, b = 20 * np.log10(max(abs(s), 1e-300)), np.degrees(np.angle(s))
        else:
            raise ValueError(f"unknown Touchstone format {fmt!r}")
        out.write(f"{fi / 1e9:.12g} {a:.12g} {b:.12g}\n")
    return out.getvalue()


def write_design_s1p(path, project, pol="TE"):
    f, s11, ref, notes = design_s11(project, pol)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(format_s1p(f, s11, ref, notes))
    return len(f)


def parse_touchstone(text, nports):
    """(f [Hz] ascending, S [n_f, nports, nports] complex, reference R [ohm]) from Touchstone 1.x text (any unit,
    RI/MA/DB).  Version 1 lists a 2-port's parameters in the order S11, S21, S12, S22; larger files go row by row."""
    unit, fmt, param, ref = "GHZ", "MA", "S", 50.0  # the format's defaults
    seen_option = False
    values = []
    for raw in text.splitlines():
        line = raw.split("!", 1)[0].strip()
        if not line:
            continue
        if line.startswith("#"):
            if seen_option:
                continue  # only the first option line counts
            seen_option = True
            toks = line[1:].upper().split()
            i = 0
            while i < len(toks):
                t = toks[i]
                if t in _UNITS:
                    unit = t
                elif t in ("RI", "MA", "DB"):
                    fmt = t
                elif t in ("S", "Y", "Z", "H", "G"):
                    param = t
                elif t == "R" and i + 1 < len(toks):
                    i += 1
                    try:
                        ref = float(toks[i])
                    except ValueError:
                        raise TouchstoneError(f"reference resistance is not a number: {toks[i]!r}") from None
                i += 1
            continue
        if line.startswith("["):
            raise TouchstoneError("Touchstone 2.0 keyword files are not supported; save as version 1")
        try:
            values.extend(float(x) for x in line.split())
        except ValueError:
            raise TouchstoneError(f"not a number in line: {raw.strip()!r}") from None
    if param != "S":
        raise TouchstoneError(f"only S parameters are supported, not {param}")
    per = 1 + 2 * nports * nports
    if len(values) % per:
        hint = " (is this a 2-port .s2p file?)" if nports == 1 else ""
        raise TouchstoneError(f"a {nports}-port file needs {per} numbers per frequency{hint}")
    arr = np.array(values, dtype=float).reshape(-1, per)
    if len(arr) < 2:
        raise TouchstoneError("need at least two frequencies")
    f = arr[:, 0] * _UNITS[unit]
    a, b = arr[:, 1::2], arr[:, 2::2]
    if fmt == "RI":
        flat = a + 1j * b
    elif fmt == "MA":
        flat = a * np.exp(1j * np.radians(b))
    else:
        flat = 10 ** (a / 20) * np.exp(1j * np.radians(b))
    s = flat.reshape(-1, nports, nports)
    if nports == 2:
        s = s.transpose(0, 2, 1)  # file order S11 S21 S12 S22 is column-major for two ports
    if np.any(f <= 0):
        raise TouchstoneError("frequencies must be positive")
    order = np.argsort(f)
    f, s = f[order], s[order]
    if len(np.unique(f)) != len(f):
        raise TouchstoneError("duplicate frequencies")
    return f, s, ref


def parse_s1p(text):
    """(f [Hz] ascending, S11 complex) from Touchstone 1.x one-port text (any unit, RI/MA/DB)."""
    f, s, _ = parse_touchstone(text, 1)
    return f, s[:, 0, 0]


def parse_s2p(text):
    """(f [Hz] ascending, S11, S21, S12, S22, reference R [ohm]) from Touchstone 1.x two-port text."""
    f, s, ref = parse_touchstone(text, 2)
    return f, s[:, 0, 0], s[:, 1, 0], s[:, 0, 1], s[:, 1, 1], ref
