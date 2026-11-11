"""Design report: one self-contained HTML file (tables + embedded PNG plots) for sharing or printing.

No Qt here.  matplotlib is used through its Agg canvas, so the report also renders without a display; the CLI
does not import this module (it stays matplotlib-free).
"""

from __future__ import annotations

import base64
import contextvars
import datetime
import html
import io
import math

import numpy as np

from coating_studio import __version__, diagnostics, lengths, spectral
from coating_studio.core.solver import solve
from coating_studio.core.structure import SheetLayer, SlabLayer
from coating_studio.i18n import tr
from coating_studio.limits import target_limits
from coating_studio.optimize import evaluate_terms
from coating_studio.core.units import to_display
from coating_studio.project import describe_path, param_unit
from coating_studio.tolerance import CornerResult, ToleranceResult, result_band, result_settings

_COLORS = {"TE": "#2563eb", "TM": "#dc2626", "avg": "#111827", "target": "#c0262d"}
_REF_COLORS = ("#0d9488", "#9333ea", "#ca8a04", "#db2777", "#4b5563", "#65a30d")
# colours of the tolerance band plot (the GUI passes its theme colours instead)
TOL_COLORS = {"spread": "#2563eb", "nominal": "#dc2626", "target": "#5f6b7a", "band": "#0d9488"}
MAX_TOLERANCE_PLOTS = 6  # per-target tolerance plots in a report; the weakest targets are kept
_CSS = """
body { font-family: -apple-system, "Segoe UI", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif; color: #111827;
       max-width: 960px; margin: 24px auto; padding: 0 16px; line-height: 1.45; }
h1 { font-size: 1.6em; margin-bottom: 0.1em; } h2 { font-size: 1.2em; margin-top: 1.6em;
     border-bottom: 1px solid #d5d9e0; padding-bottom: 0.2em; }
.meta { color: #5f6b7a; font-size: 0.9em; }
table { border-collapse: collapse; margin: 0.6em 0; font-size: 0.92em; }
th, td { border: 1px solid #d5d9e0; padding: 4px 8px; text-align: left; vertical-align: top; }
th { background: #f3f4f6; } td.num { text-align: right; font-variant-numeric: tabular-nums; }
.ok { color: #15803d; font-weight: 600; } .fail { color: #c0262d; font-weight: 600; } .muted { color: #5f6b7a; }
img { max-width: 100%; } ul { padding-left: 1.3em; }
@media print { body { margin: 0; } h2 { break-after: avoid; } img, table { break-inside: avoid; } }
"""


# Print variant (``build_report(print_layout=...)``, used by gui/report_pdf.py): Qt's rich text reads only part of CSS
# (no max-width, no @media, no page-break avoid), so the PDF gets its own style sheet, explicit text and border colours
# (a dark GUI palette must not leak onto white paper), full-width wide tables and sized high-resolution images.
_PRINT = contextvars.ContextVar("report_print_layout", default=None)
PRINT_DPI = 200
_PRINT_CSS = """
body {{ font-family: "{font}"; color: #111827; }}
h1 {{ font-size: 16pt; color: #111827; }} h2 {{ font-size: 12.5pt; color: #111827; margin-top: 14pt; }}
p, li, td, th {{ color: #111827; }} .meta {{ color: #5f6b7a; }}
table {{ border-collapse: collapse; margin-top: 4pt; margin-bottom: 4pt; }}
th, td {{ border: 1px solid #c9ced6; padding: 3px 6px; vertical-align: top; }}
th {{ background-color: #f3f4f6; }} td.num {{ text-align: right; }}
.ok {{ color: #15803d; font-weight: 600; }} .fail {{ color: #c0262d; font-weight: 600; }} .muted {{ color: #5f6b7a; }}
"""


def _table(wide=False):
    """Opening tag of a report table: full page width for wide tables in the print variant."""
    if _PRINT.get() is None:
        return "<table>"
    return '<table width="100%" cellspacing="0">' if wide else '<table cellspacing="0">'


def _e(x):
    return html.escape(str(x))


def _num(x, digits=4):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "—"
    return f"{x:.{digits}g}"


def _rl(db, positive):
    return -db if positive else db


def _png(fig):
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    FigureCanvasAgg(fig)
    buf = io.BytesIO()
    layout = _PRINT.get()
    fig.savefig(buf, format="png", dpi=PRINT_DPI if layout else 110)
    data = base64.b64encode(buf.getvalue()).decode("ascii")
    if layout is None:
        return '<img alt="" src="data:image/png;base64,' + data + '">'
    # Qt needs both sizes: with the width alone it keeps the image's own height (blank space below)
    w_in, h_in = fig.get_size_inches()
    width = layout["image_width"]
    # in a paragraph of its own: right after a list, Qt otherwise keeps the list's indent and the image overflows
    return (f'<p style="margin-left:0; text-indent:0"><img alt="" width="{width:.1f}" '
            f'height="{width * h_in / w_in:.1f}" src="data:image/png;base64,{data}"></p>')


def _rl_label(positive):
    return tr("Reflection loss [dB] (higher is better)") if positive else tr("Reflection loss [dB] (lower is better)")


def _pol_curves(ax, x, res, cut, normal, positive):
    pols = ("TE",) if normal else ("TE", "TM")
    for pol in pols:
        r = cut(res.quantity("R", pol))
        y = _rl(10 * np.log10(np.maximum(r, 1e-30)), positive)
        label = tr("TE = TM (normal incidence)") if normal else pol
        ax.plot(x, y, color=_COLORS[pol], ls="-" if pol == "TE" else "--", lw=1.6, label=label)



def _material_tol_text(project, e):
    """'name: param 5 %' (relative) or 'name: param ±0.2 GHz (absolute)' in the parameter's display unit."""
    name = describe_path(project, e["path"])
    if e.get("mode") != "absolute":
        return f"{name} {e['tol'] * 100:g} %"
    try:
        unit = param_unit(project, e["path"])
    except (KeyError, ValueError):
        unit = ""
    shown = unit if unit not in ("", "frac") else ""
    return f"{name} ±{to_display(e['tol'], unit):g}{' ' + shown if shown else ''} ({tr('absolute')})"

def corner_label(ti, name, angle, pol):
    """'Target 1 (X) 30° TE' — the angle and polarisation of one target row of a tolerance analysis."""
    head = tr("Target {n}", n=ti + 1) + (f" ({name})" if name else "")
    return f"{head} {angle:g}° {pol}"


def samples_text(r, s):
    """'200 samples', or 'stopped after 37 of 200 samples' for a stopped run (``s``: the settings of the run)."""
    if r.stopped:
        return tr("stopped after {n} of {m} samples", n=r.n_samples, m=s.n_samples)
    return tr("{n} samples", n=r.n_samples)


def draw_tolerance_band(ax, r, target_db, bands, lower_pct, upper_pct, colors, positive=False, log_f=False,
                        unit="GHz"):
    """Draw one ToleranceResult: percentile band, median, nominal design, target level and the yield intervals,
    against the spectral axis in ``unit`` (``core.units.SPECTRAL_UNITS``).

    Shared by the GUI's tolerance tab and the report.  ``colors``: {"spread", "nominal", "target", "band"}.
    Labels, legend, title and grid are left to the caller."""
    sgn = -1 if positive else 1
    x = spectral.x_values(r.f, unit)
    ax.fill_between(x, sgn * r.lower_db, sgn * r.upper_db, color=colors["spread"], alpha=0.22,
                    label=tr("{a:g}–{b:g} percentile band", a=lower_pct, b=upper_pct))
    ax.plot(x, sgn * r.median_db, color=colors["spread"], label=tr("Median"))
    ax.plot(x, sgn * r.nominal_db, color=colors["nominal"], ls="--", label=tr("Nominal design"))
    ax.axhline(sgn * target_db, color=colors["target"], lw=1, ls=":", label=tr("Target"))
    for lo, hi in bands:
        ax.axvspan(*spectral.span(lo, hi, unit), color=colors["band"], alpha=0.07)
    if log_f:
        ax.set_xscale("log")  # before set_xlim
    spectral.set_xlim(ax, x)  # ascending even for a wavelength axis


def _tolerance_figure(r, s, title, positive, log_f, unit):
    from matplotlib.figure import Figure

    fig = Figure(figsize=(8, 3.2), layout="constrained")
    ax = fig.add_subplot(111)
    draw_tolerance_band(ax, r, s.target_db, r.band or [], s.lower_pct, s.upper_pct, TOL_COLORS, positive, log_f,
                        unit)
    ax.set_xlabel(spectral.axis_label(unit))
    ax.set_ylabel(_rl_label(positive))
    ax.set_title(title, fontsize=10, loc="left", wrap=True)
    ax.grid(True, color="#e3e6eb")
    ax.legend(loc="best", fontsize=8)
    return _png(fig)


def _tolerance_figures(p, tolerance, positive):
    """Band plots of a tolerance result: one for a single-angle result; for target rows, the lowest-yield row of each
    target (at most MAX_TOLERANCE_PLOTS, keeping the weakest targets), in target order."""
    log_f, unit = p.sweep.log_f, p.sweep.spectral_unit
    if isinstance(tolerance, ToleranceResult):
        s = result_settings(tolerance, p)
        r = tolerance if tolerance.band is not None else _with_band(tolerance, result_band(tolerance, p))
        title = f"{s.angle:g}° {s.pol} — " + tr("Yield {y} ({s})", y=_pct(r.yield_fraction), s=samples_text(r, s))
        return [_tolerance_figure(r, s, title, positive, log_f, unit)]
    rows = sorted(tolerance.per_target().values(), key=lambda i: tolerance.corners[i][5].yield_fraction)
    out = []
    for i in sorted(rows[:MAX_TOLERANCE_PLOTS]):
        ti, name, ang, pol, _goal, r = tolerance.corners[i]
        s = result_settings(r, p)
        title = corner_label(ti, name, ang, pol) + " — " + tr("Yield {y} ({s})", y=_pct(r.yield_fraction),
                                                                 s=samples_text(r, s))
        out.append(_tolerance_figure(r, s, title, positive, log_f, unit))
    return out


def _with_band(r, band):
    import dataclasses
    return dataclasses.replace(r, band=list(band))


def _freq_figure(project, positive, references):
    from matplotlib.figure import Figure

    sw = project.sweep
    res = solve(project.structure, project.materials, sw.freq_grid(), sw.angle)
    fig = Figure(figsize=(8, 3.8), layout="constrained")
    ax = fig.add_subplot(111)
    unit = sw.spectral_unit
    x = spectral.x_values(res.f, unit)
    _pol_curves(ax, x, res, lambda a: a[:, 0], abs(sw.angle) < 1e-9, positive)
    first = True
    for t in project.optimization.enabled_targets():
        if t.angle_min - 1e-9 <= sw.angle <= t.angle_max + 1e-9:
            y = _rl(t.goal_db, positive)
            ax.hlines(y, *spectral.span(t.f_min, max(t.f_max, t.f_min), unit), colors=_COLORS["target"], lw=2.4,
                      alpha=0.75, label=tr("Targets") if first else None)
            first = False
    for ref in references:
        style = dict(color=_REF_COLORS[ref.slot % len(_REF_COLORS)], lw=1.2, ls=":")
        if ref.kind == "measured":
            ax.plot(spectral.x_values(ref.f_meas, unit), _rl(ref.rl_meas_db, positive),
                    label=f"{ref.name} {tr('(measured)')}", **style)
            continue
        r = ref.results(sw).get("freq")
        if isinstance(r, Exception) or r is None:
            continue
        rr = r.quantity("R", "TE" if abs(sw.angle) < 1e-9 else "avg")[:, 0]
        ax.plot(spectral.x_values(r.f, unit), _rl(10 * np.log10(np.maximum(rr, 1e-30)), positive), label=ref.name,
                **style)
    if sw.log_f:
        ax.set_xscale("log")
    spectral.set_xlim(ax, x)
    ax.set_xlabel(spectral.axis_label(unit))
    ax.set_ylabel(_rl_label(positive))
    ax.set_title(tr("Incidence {a}°", a=f"{sw.angle:g}"), fontsize=10, loc="left")
    ax.grid(True, color="#e3e6eb")
    ax.legend(loc="best", fontsize=8)
    return _png(fig), res


def _angle_figure(project, positive):
    from matplotlib.figure import Figure

    sw = project.sweep
    res = solve(project.structure, project.materials, [sw.f_at], sw.angle_grid())
    fig = Figure(figsize=(8, 3.4), layout="constrained")
    ax = fig.add_subplot(111)
    _pol_curves(ax, res.theta, res, lambda a: a[0, :], False, positive)
    first = True
    for t in project.optimization.enabled_targets():
        if t.f_min * (1 - 1e-9) <= sw.f_at <= t.f_max * (1 + 1e-9):
            y = _rl(t.goal_db, positive)
            if t.angle_max > t.angle_min:
                ax.hlines(y, t.angle_min, t.angle_max, colors=_COLORS["target"], lw=2.4, alpha=0.75,
                          label=tr("Targets") if first else None)
            else:
                ax.plot([t.angle_min], [y], marker="_", ms=14, mew=2.4, color=_COLORS["target"], ls="",
                        label=tr("Targets") if first else None)
            first = False
    ax.set_xlim(res.theta[0], res.theta[-1])
    ax.set_xlabel(tr("Incidence angle [°]"))
    ax.set_ylabel(_rl_label(positive))
    ax.set_title(spectral.fmt_point(sw.f_at, sw.spectral_unit), fontsize=10, loc="left")
    ax.grid(True, color="#e3e6eb")
    ax.legend(loc="best", fontsize=8)
    return _png(fig)


def _layer_rows(project):
    rows = []
    for i, ly in enumerate(project.structure.layers, start=1):
        if isinstance(ly, SlabLayer):
            mat = project.materials.get(ly.material)
            kind = mat.to_dict().get("kind", "") if mat is not None else "?"
            rows.append((i, ly.name, f"{ly.material} <span class=muted>({_e(kind)})</span>",
                         lengths.fmt_length(ly.thickness, project.sweep.length_unit)))
        elif isinstance(ly, SheetLayer):
            if ly.model == "parallel_rlc":
                spec = tr("Parallel RLC") + f": R = {ly.R:.4g} Ω/sq, " + (
                    f"L = {ly.L * 1e9:.4g} nH" if ly.L > 0 else tr("no inductor")) + ", " + (
                    f"C = {ly.C * 1e12:.4g} pF" if ly.C is not None else tr("no capacitor"))
            elif ly.model == "rlc":
                spec = f"R = {ly.R:.4g} Ω/sq, L = {ly.L * 1e9:.4g} nH, " + (
                    f"C = {ly.C * 1e12:.4g} pF" if ly.C is not None else tr("no capacitor"))
            else:
                spec = f"Zs = {ly.R:.4g} {'+' if ly.X >= 0 else '−'} j{abs(ly.X):.4g} Ω/sq"
            if ly.has_angle:
                spec += "; " + tr("angle coefficients") + ": " + ", ".join(
                    f"{k} {v:+.4g}" for k, v in ly.angle_dict().items() if v)
            rows.append((i, ly.name, _e(tr("Resistive sheet")) + f" <span class=muted>({_e(spec)})</span>", "—"))
    return rows


def build_report(project, rl_positive=False, references=(), tolerance=None, source="", print_layout=None):
    """HTML text of the design report.  ``references``: visible comparison curves to draw; ``tolerance``: the last
    ToleranceResult / CornerResult (or None); ``source``: the file path to show.  ``print_layout``: None for the
    browser HTML, or {"image_width": width of a full-width image in the target layout's units, "font": family} for
    the print variant that gui/report_pdf.py lays out with Qt."""
    token = _PRINT.set(print_layout)
    try:
        return _build_report(project, rl_positive, references, tolerance, source, print_layout)
    finally:
        _PRINT.reset(token)


def _build_report(project, rl_positive, references, tolerance, source, print_layout):
    from coating_studio.mplfonts import configure_matplotlib_fonts

    configure_matplotlib_fonts()  # Korean axis labels
    p = project
    pos = bool(rl_positive)
    sign = tr("Reflection loss is shown as positive dB (higher is better).") if pos else \
        tr("Reflection loss is 20·log₁₀|Γ| in dB (negative, lower is better).")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>{_e(p.name)}</title>"
           f"<style>{_CSS if print_layout is None else _PRINT_CSS.format(font=print_layout.get('font', 'sans-serif'))}"
           "</style></head><body>",
           f"<h1>{_e(p.name)}</h1>",
           f"<p class=meta>{_e(tr('Coating Studio {v} design report', v=__version__))} · {_e(now)}"
           + (f" · {_e(source)}" if source else "") + "</p>"]
    if p.notes:
        out.append(f"<p>{_e(p.notes)}</p>")

    # summary
    try:
        mass = p.areal_mass()
    except Exception:  # noqa: BLE001 - an unresolved material only hides the mass
        mass = float("nan")
    out.append(f"<h2>{_e(tr('Summary'))}</h2>{_table()}")
    out.append(f"<tr><th>{_e(tr('Total thickness'))}</th><td class=num>{lengths.fmt_length(p.structure.total_thickness(), p.sweep.length_unit)}</td></tr>")
    out.append(f"<tr><th>{_e(tr('Areal mass'))}</th><td class=num>{_num(mass)} kg/m²</td></tr>")
    backing = tr("Metal plate (PEC)") if p.structure.backing.kind == "pec" else p.structure.backing.material
    out.append(f"<tr><th>{_e(tr('Backing'))}</th><td>{_e(backing)}</td></tr>")
    out.append(f"<tr><th>{_e(tr('Incident medium'))}</th><td>{_e(p.structure.incident)}</td></tr></table>")
    out.append(f"<p class=muted>{_e(sign)}</p>")

    # targets
    targets = p.optimization.enabled_targets()
    out.append(f"<h2>{_e(tr('Targets'))}</h2>")
    if not targets:
        out.append(f"<p class=muted>{_e(tr('No enabled targets.'))}</p>")
    else:
        try:
            per_target = evaluate_terms(p).per_target
        except Exception as e:  # noqa: BLE001 - reported in the table
            per_target = [(None, None)] * len(targets)
            out.append(f"<p class=fail>{_e(tr('Cannot compute: {e}', e=e))}</p>")
        try:
            limits = {r["target"]: r for r in target_limits(p)}
        except Exception:  # noqa: BLE001 - the bound is a hint only
            limits = {}
        out.append(_table(wide=True) + "<tr>" + "".join(f"<th>{_e(h)}</th>" for h in (
            tr("Target"), tr("Band"), tr("Angles"), tr("Polarisation"), tr("Goal"), tr("Worst RL"), tr("Margin"),
            tr("Rozanov bound"))) + "</tr>")
        for i, (t, (worst, margin)) in enumerate(zip(targets, per_target)):
            met = margin is not None and math.isfinite(margin) and margin <= 0
            verdict = (f"<span class=ok>{_e(tr('met'))}</span>" if met else f"<span class=fail>{_e(tr('not met'))}</span>"
                       ) if margin is not None and math.isfinite(margin) else "—"
            band = spectral.fmt_range(t.f_min, t.f_max, p.sweep.spectral_unit)
            ang = f"{t.angle_min:g}–{t.angle_max:g}°" if t.angle_max > t.angle_min else f"{t.angle_min:g}°"
            lim = limits.get(i, {})
            status = {"ok": tr("satisfied"), "violated": tr("thicker needed"), "infeasible": tr("infeasible"),
                      "unknown": tr("not evaluated")}.get(lim.get("status"), "—")
            name = f"{i + 1}" + (f" ({t.name})" if t.name else "")
            margin_txt = "—" if margin is None or not math.isfinite(margin) else f"{margin:+.2f} dB"
            out.append(f"<tr><td>{_e(name)}</td><td>{band}</td><td>{ang}</td><td>{_e(', '.join(t.pols))}</td>"
                       f"<td class=num>{_rl(t.goal_db, pos):g} dB</td>"
                       f"<td class=num>{'—' if worst is None else f'{_rl(worst, pos):.2f} dB'}</td>"
                       f"<td class=num>{margin_txt} {verdict}</td><td>{_e(status)}</td></tr>")
        out.append("</table>")
        out.append(f"<p class=muted>{_e(tr('Margin = worst RL − goal (20·log₁₀|Γ|); ≤ 0 dB means the target is met. Each target is evaluated on its own band, angles and polarisations. The Rozanov bound is a normal-incidence thickness limit for a metal-backed absorber.'))}</p>")

    # layers
    out.append(f"<h2>{_e(tr('Layer stack'))}</h2>")
    out.append(f"<p class=muted>{_e(tr('Layer 1 faces the incident wave.'))}</p>{_table(wide=True)}<tr>"
               + ('<th width="4%">#</th>' if print_layout else "<th>#</th>")  # a full-width table spreads "#" too
               + "".join(f"<th>{_e(h)}</th>" for h in (tr("Layer"), tr("Material / sheet"), tr("Thickness")))
               + "</tr>")
    for i, name, what, thick in _layer_rows(p):
        out.append(f"<tr><td class=num>{i}</td><td>{_e(name)}</td><td>{what}</td><td class=num>{thick}</td></tr>")
    out.append("</table>")

    # plots
    out.append(f"<h2>{_e(tr('Reflection'))}</h2>")
    try:
        img, res = _freq_figure(p, pos, [r for r in references if r.visible])
        out.append(img)
        out.append(_angle_figure(p, pos))
    except Exception as e:  # noqa: BLE001 - the rest of the report is still useful
        out.append(f"<p class=fail>{_e(tr('Cannot compute: {e}', e=e))}</p>")
        res = None
    if res is not None:
        r = res.quantity("R", "avg")[:, 0]
        db = 10 * np.log10(np.maximum(r, 1e-30))
        k = int(np.argmin(db))
        out.append(f"<p>{_e(tr('Best RL {v} dB at {x}', v=f'{_rl(db[k], pos):.1f}', x=spectral.fmt_value(res.f[k], p.sweep.spectral_unit)))}</p>")

    # tolerance
    if tolerance is not None:
        out.append(f"<h2>{_e(tr('Tolerance analysis'))}</h2>")
        s = result_settings(tolerance, p)  # the settings of the run, not the current ones
        if isinstance(tolerance, CornerResult):
            grid = tolerance.angle_mode == "grid"
            n_txt = samples_text(tolerance, s)
            if grid:
                head_text = tr("Joint yield over every target's angle grid ({k} points): {y} ({s}). Lowest "
                               "yield per target:", k=len(tolerance.corners), y=_pct(tolerance.joint_yield_fraction),
                               s=n_txt)
                shown = list(tolerance.per_target().values())  # a grid has too many rows to list them all
            else:
                head_text = tr("Joint yield over all target corners: {y} ({s})",
                               y=_pct(tolerance.joint_yield_fraction), s=n_txt)
                shown = range(len(tolerance.corners))
            out.append(f"<p>{_e(head_text)}</p><ul>")
            for i in shown:
                ti, name, ang, pol, goal, r = tolerance.corners[i]
                out.append(f"<li>{_e(corner_label(ti, name, ang, pol))}: {_e(_pct(r.yield_fraction))}"
                           f" ({_e(tr('goal'))} {_rl(goal, pos):g} dB)</li>")
            out.append("</ul>")
            for ti in tolerance.fallback_targets:
                out.append(f"<p class=muted>{_e(tr('Target {n}: fewer than 2 angle-grid points, so the two ends of its range were used.', n=ti + 1))}</p>")
        elif isinstance(tolerance, ToleranceResult):
            out.append(f"<p>{_e(tr('Yield {y} at {a}° {pol} ({s}), target {t} dB', y=_pct(tolerance.yield_fraction), a=f'{s.angle:g}', pol=s.pol, s=samples_text(tolerance, s), t=f'{_rl(s.target_db, pos):g}'))}</p>")
        try:
            out.extend(_tolerance_figures(p, tolerance, pos))
        except Exception as e:  # noqa: BLE001 - the text above is still useful
            out.append(f"<p class=fail>{_e(tr('Cannot compute: {e}', e=e))}</p>")
        if isinstance(tolerance, CornerResult) and len(tolerance.per_target()) > MAX_TOLERANCE_PLOTS:
            out.append(f"<p class=muted>{_e(tr('Plots show the {k} targets with the lowest yield.', k=MAX_TOLERANCE_PLOTS))}</p>")
        loss = lambda v: tr("follows the real part") if v is None else f"{v * 100:g} %"  # noqa: E731
        dist = tr("uniform") if s.distribution == "uniform" else tr("normal")
        seed = tr("random") if s.seed is None else s.seed
        out.append(f"<p class=muted>{_e(tr('Tolerances: thickness {t} %, ε′ {e} %, ε″ {el}, μ′ {m} %, μ″ {ml}, sheet {sh} %, real/loss correlation ρ = {rho}; {d} distribution, seed {seed}. Per-layer overrides are not listed.', t=f'{s.thickness * 100:g}', e=f'{s.eps * 100:g}', el=loss(s.eps_loss), m=f'{s.mu * 100:g}', ml=loss(s.mu_loss), sh=f'{s.sheet * 100:g}', rho=f'{s.loss_correlation:g}', d=dist, seed=seed))}</p>")
        if s.material_params:
            items = "; ".join(_material_tol_text(p, e) for e in s.material_params)
            out.append(f"<p class=muted>{_e(tr('Material parameters varied per sample (relative): {items}.', items=items))}</p>")

    # diagnostics
    out.append(f"<h2>{_e(tr('Diagnostics'))}</h2>")
    try:
        sw = p.sweep
        problems, notes = diagnostics.collect(p, sw.freq_grid(min(sw.n_f, 200)))
    except Exception as e:  # noqa: BLE001
        problems, notes = [("error", str(e))], []
    if not problems and not notes:
        out.append(f"<p>{_e(tr('No problems found in the materials used.'))}</p>")
    else:
        out.append("<ul>" + "".join(f"<li class={'fail' if lv == 'error' else ''}>{_e(t)}</li>" for lv, t in problems)
                   + "".join(f"<li class=muted>{_e(t)}</li>" for t in notes) + "</ul>")

    if references:
        out.append(f"<h2>{_e(tr('Comparison curves'))}</h2><ul>")
        for ref in references:
            kind = tr("(measured)") if ref.kind == "measured" else tr("design snapshot")
            hidden = "" if ref.visible else " · " + tr("hidden")
            out.append(f"<li>{_e(ref.name)} <span class=muted>{_e(kind)}{_e(hidden)}</span></li>")
        out.append("</ul>")
    out.append("</body></html>\n")
    return "\n".join(out)


def _pct(x):
    return "—" if x is None else f"{x * 100:.1f} %"


def write_report(path, project, **kw):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(build_report(project, **kw))
