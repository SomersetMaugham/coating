"""Result views: frequency, angle, map, Smith chart, absorption breakdown, material properties."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel

from coating_studio.core.structure import SheetLayer
from coating_studio.gui.fmt import rl_display
from coating_studio.gui.plots.base import PlotView
from coating_studio.gui.widgets.inputs import SciSpinBox
from coating_studio.i18n import tr

QUANTITIES = ("RL", "R", "A", "T")


def quantity_label(q, positive):
    if q == "RL":
        return (tr("Reflection loss [dB] (higher is better)") if positive
                else tr("Reflection loss [dB] (lower is better)"))
    return {"R": tr("Reflectance |Γ|²"), "A": tr("Absorptance"), "T": tr("Transmittance")}[q]


def quantity_values(res, q, pol, positive):
    if q == "RL":
        r = res.quantity("R", pol)
        db = 10 * np.log10(np.maximum(r, 1e-30))
        return -db if positive else db
    return res.quantity(q, pol)


def pol_label(pol):
    return {"TE": "TE", "TM": "TM", "avg": tr("Average")}[pol]


class _QuantityMixin:
    def _add_quantity_controls(self):
        self.cb_q = QComboBox()
        for q in QUANTITIES:
            self.cb_q.addItem(quantity_label(q, False).split(" [")[0] if q == "RL" else quantity_label(q, False), q)
        self.cb_q.currentIndexChanged.connect(lambda _: self.mark_dirty())
        self.controls.addWidget(QLabel(tr("Show")))
        self.controls.addWidget(self.cb_q)
        self.pol_boxes = {}
        for pol, on in (("TE", True), ("TM", True), ("avg", False)):
            b = QCheckBox(pol_label(pol))
            b.setChecked(on)
            b.toggled.connect(lambda _: self.mark_dirty())
            self.controls.addWidget(b)
            self.pol_boxes[pol] = b
        self.controls.addStretch(1)

    def _pols(self):
        return [p for p, b in self.pol_boxes.items() if b.isChecked()]


class _SweepSpinMixin:
    """One sweep setting (e.g. the incidence angle of the frequency sweep) editable on the plot bar.

    It edits the same ``SweepSettings`` field as the Analysis settings dock; MainWindow calls
    ``sync_controls()`` after every settings change so both editors always agree."""

    def _add_sweep_spin(self, label, attr, scale, minimum, maximum, suffix, tip):
        self._sweep_attr, self._sweep_scale = attr, scale
        lab = QLabel(label)
        self.sp_sweep = SciSpinBox(minimum=minimum, maximum=maximum, suffix=suffix)
        self.sp_sweep.setFixedWidth(92)  # SciSpinBox expands by default
        self.sp_sweep.setToolTip(tip)
        lab.setToolTip(tip)
        self.sp_sweep.valueEdited.connect(self._commit_sweep)
        at = self.controls.count() - 1  # before the trailing stretch
        self.controls.insertWidget(at, lab)
        self.controls.insertWidget(at + 1, self.sp_sweep)
        self.sync_controls()

    def _commit_sweep(self, v):
        value = v * self._sweep_scale
        self.ctx.doc.edit_settings(lambda p: setattr(p.sweep, self._sweep_attr, value))

    def sync_controls(self):
        target = getattr(self.ctx.project.sweep, self._sweep_attr) / self._sweep_scale
        # Skip no-op updates: this runs re-entrantly while the user is editing this very box.
        if not math.isclose(self.sp_sweep.value(), target, rel_tol=1e-12, abs_tol=1e-12):
            self.sp_sweep.set_value(target)


# -- pinned reference traces -----------------------------------------------------------------
def _ref_style(ref, colors):
    return dict(color=colors.ref_series[ref.slot % len(colors.ref_series)], ls="-.", lw=1.6, alpha=0.9)


def _ref_pols(checked, normal, allowed=("TE", "TM", "avg")):
    """Polarisations to draw for a reference, and whether to suffix the label with them.

    At normal incidence TE, TM and their average coincide, so one curve suffices.  Otherwise the
    reference follows the polarisations shown for the live design and says which one it is."""
    checked = [p for p in checked if p in allowed] or [allowed[-1] if "avg" in allowed else allowed[0]]
    if normal:
        return [checked[0]], False
    return checked, True


def _ref_label(ref, pol, suffix):
    return f"{ref.name} ({pol_label(pol)})" if suffix else ref.name


def _visible_refs(ctx):
    return [r for r in getattr(ctx, "references", []) if r.visible]


def _ref_warning(problems):
    if not problems:
        return None
    return tr("Some references cannot be computed for the current settings: {items}",
              items="; ".join(problems))


def _legend_if_any(ax, **kw):
    if ax.get_legend_handles_labels()[0]:
        ax.legend(**kw)


def _style_for(pol, colors):
    return {"TE": dict(color=colors.series[0]), "TM": dict(color=colors.series[1], ls="--"),
            "avg": dict(color=colors.series[2], lw=2.4)}[pol]


# ---------------------------------------------------------------------------
class FrequencyView(_SweepSpinMixin, _QuantityMixin, PlotView):
    title = "reflection_vs_frequency"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self._add_quantity_controls()
        self.chk_target = QCheckBox()
        self.chk_target.setChecked(True)
        self.chk_target.toggled.connect(lambda _: self.mark_dirty())
        self.controls.insertWidget(self.controls.count() - 1, self.chk_target)
        self.chk_mask = QCheckBox(tr("Targets"))
        self.chk_mask.setChecked(True)
        self.chk_mask.setToolTip(tr("Show the optimisation targets whose angle range includes the "
                                    "current incidence angle (goal level over their band)"))
        self.chk_mask.toggled.connect(lambda _: self.mark_dirty())
        self.controls.insertWidget(self.controls.count() - 1, self.chk_mask)
        self.on_rl_sign_changed()
        self._add_sweep_spin(tr("Incidence"), "angle", 1.0, 0.0, 89.9, "°",
                             tr("Incidence angle of the frequency sweep. Also used by the Smith chart "
                                "and absorption tabs."))

    def on_rl_sign_changed(self):
        self.chk_target.setText(tr("10 dB line") if self.ctx.rl_positive else tr("−10 dB line"))

    def draw_plot(self, fig):
        res = self.ctx.results.get("freq")
        if res is None:
            return self.ctx.result_error
        q = self.cb_q.currentData()
        pos = self.ctx.rl_positive
        ax = fig.add_subplot(111)
        x = res.f / 1e9
        for pol in self._pols():
            ax.plot(x, quantity_values(res, q, pol, pos)[:, 0], label=pol_label(pol), **_style_for(pol, self.ctx.colors))
        problems = self._draw_references(ax, q, pos)
        if q == "RL" and self.chk_mask.isChecked():
            self._draw_target_mask(ax, pos)
        if q == "RL" and self.chk_target.isChecked():
            ax.axhline(10 if pos else -10, color=self.ctx.colors.muted, lw=1, ls=":")
        sw = self.ctx.project.sweep
        if sw.log_f:
            ax.set_xscale("log")
        ax.set_xlim(x[0], x[-1])
        ax.set_xlabel(tr("Frequency [GHz]"))
        ax.set_ylabel(quantity_label(q, pos))
        if q != "RL":
            ax.set_ylim(-0.02, 1.02)
        ax.set_title(tr("Incidence {a}°", a=f"{sw.angle:g}"), fontsize=10, loc="left")
        _legend_if_any(ax, loc="best")
        self._ax = ax
        return (_ref_warning(problems), "warn") if problems else None

    def _draw_target_mask(self, ax, pos):
        """Spec mask: each enabled target that applies at the current angle, as its goal level over
        its band (a marker for a single-frequency target)."""
        sw = self.ctx.project.sweep
        c = self.ctx.colors.error
        first = True
        for t in self.ctx.project.optimization.enabled_targets():
            if not (t.angle_min - 1e-9 <= sw.angle <= t.angle_max + 1e-9):
                continue
            y = rl_display(t.goal_db, pos)
            label = tr("Targets") if first else None
            if t.f_max > t.f_min:
                ax.hlines(y, t.f_min / 1e9, t.f_max / 1e9, colors=c, lw=2.2, alpha=0.75, label=label)
            else:
                ax.plot([t.f_min / 1e9], [y], marker="_", ms=14, mew=2.2, color=c, alpha=0.75, ls="", label=label)
            first = False

    def _reference_series(self, q, pos):
        """[(ref, pol or None, label, x [GHz], y)] for the visible references; plus problems."""
        sw = self.ctx.project.sweep
        pols, suffix = _ref_pols(self._pols(), abs(sw.angle) < 1e-9)
        out, problems = [], []
        for ref in _visible_refs(self.ctx):
            if ref.kind == "measured":
                if q not in ("RL", "R"):
                    continue
                y = (-ref.rl_meas_db if pos else ref.rl_meas_db) if q == "RL" else 10 ** (ref.rl_meas_db / 10)
                # measured data does not follow the sweep angle; say so in the legend
                out.append((ref, None, f"{ref.name} {tr('(measured)')}", ref.f_meas / 1e9, y))
                continue
            r = ref.results(sw).get("freq")
            if isinstance(r, Exception):
                problems.append(f"{ref.name}: {r}")
                continue
            for pol in pols:
                out.append((ref, pol, _ref_label(ref, pol, suffix), r.f / 1e9,
                            quantity_values(r, q, pol, pos)[:, 0]))
        return out, problems

    def _draw_references(self, ax, q, pos):
        series, problems = self._reference_series(q, pos)
        for ref, _pol, label, x, y in series:
            ax.plot(x, y, label=label, **_ref_style(ref, self.ctx.colors))
        return problems

    def format_cursor(self, ax, x, y):
        return tr("f = {f} GHz, value = {v}", f=f"{x:.5g}", v=f"{y:.4g}")

    def data_table(self):
        res = self.ctx.results.get("freq")
        if res is None:
            return None
        q = self.cb_q.currentData()
        pols = ["TE", "TM", "avg"]
        cols = [quantity_values(res, q, p, self.ctx.rl_positive)[:, 0] for p in pols]
        header = ["f [GHz]"] + [f"{q} {p}" for p in pols]
        # design references share the live grid; measured curves are the user's own data: not exported
        for ref, pol, _label, _x, y in self._reference_series(q, self.ctx.rl_positive)[0]:
            if pol is not None:
                header.append(f"{q} {pol} ({ref.name})")
                cols.append(y)
        return header, [[f"{a:.9g}" for a in row] for row in zip(res.f / 1e9, *cols)]


# ---------------------------------------------------------------------------
class AngleView(_SweepSpinMixin, _QuantityMixin, PlotView):
    title = "reflection_vs_angle"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self._add_quantity_controls()
        self._add_sweep_spin(tr("Frequency"), "f_at", 1e9, 1e-6, 1e6, "GHz",
                             tr("Frequency of the angle sweep."))

    def draw_plot(self, fig):
        res = self.ctx.results.get("angle")
        if res is None:
            return self.ctx.result_error
        q = self.cb_q.currentData()
        pos = self.ctx.rl_positive
        ax = fig.add_subplot(111)
        for pol in self._pols():
            ax.plot(res.theta, quantity_values(res, q, pol, pos)[0, :], label=pol_label(pol),
                    **_style_for(pol, self.ctx.colors))
        series, problems = self._reference_series(q, pos)
        for ref, _pol, label, x, y in series:
            ax.plot(x, y, label=label, **_ref_style(ref, self.ctx.colors))
        ax.set_xlim(res.theta[0], res.theta[-1])
        ax.set_xlabel(tr("Incidence angle [°]"))
        ax.set_ylabel(quantity_label(q, pos))
        if q != "RL":
            ax.set_ylim(-0.02, 1.02)
        ax.set_title(tr("f = {f} GHz", f=f"{res.f[0] / 1e9:.5g}"), fontsize=10, loc="left")
        _legend_if_any(ax, loc="best")
        return (_ref_warning(problems), "warn") if problems else None

    def _reference_series(self, q, pos):
        """Design references only (a measured S11 has no angle dependence)."""
        sw = self.ctx.project.sweep
        pols, suffix = _ref_pols(self._pols(), False)
        out, problems = [], []
        for ref in _visible_refs(self.ctx):
            if ref.kind != "design":
                continue
            r = ref.results(sw).get("angle")
            if isinstance(r, Exception):
                problems.append(f"{ref.name}: {r}")
                continue
            for pol in pols:
                out.append((ref, pol, _ref_label(ref, pol, suffix), r.theta, quantity_values(r, q, pol, pos)[0, :]))
        return out, problems

    def format_cursor(self, ax, x, y):
        return tr("θ = {a}°, value = {v}", a=f"{x:.4g}", v=f"{y:.4g}")

    def data_table(self):
        res = self.ctx.results.get("angle")
        if res is None:
            return None
        q = self.cb_q.currentData()
        pols = ["TE", "TM", "avg"]
        cols = [quantity_values(res, q, p, self.ctx.rl_positive)[0, :] for p in pols]
        header = ["theta [deg]"] + [f"{q} {p}" for p in pols]
        for ref, pol, _label, _x, y in self._reference_series(q, self.ctx.rl_positive)[0]:
            header.append(f"{q} {pol} ({ref.name})")
            cols.append(y)
        return header, [[f"{a:.9g}" for a in row] for row in zip(res.theta, *cols)]


# ---------------------------------------------------------------------------
class MapView(PlotView):
    title = "reflection_map"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.cb_pol = QComboBox()
        for p in ("avg", "TE", "TM"):
            self.cb_pol.addItem(pol_label(p), p)
        self.cb_pol.currentIndexChanged.connect(lambda _: self.mark_dirty())
        self.controls.addWidget(QLabel(tr("Polarisation")))
        self.controls.addWidget(self.cb_pol)
        self.chk_contour = QCheckBox()
        self.chk_contour.setChecked(True)
        self.chk_contour.toggled.connect(lambda _: self.mark_dirty())
        self.controls.addWidget(self.chk_contour)
        self.controls.addStretch(1)
        self.on_rl_sign_changed()

    def on_rl_sign_changed(self):
        self.chk_contour.setText(tr("10 / 20 dB contours") if self.ctx.rl_positive
                                 else tr("−10 / −20 dB contours"))

    def draw_plot(self, fig):
        res = self.ctx.results.get("map")
        if res is None:
            return self.ctx.result_error
        pos = self.ctx.rl_positive
        pol = self.cb_pol.currentData()
        z = quantity_values(res, "RL", pol, pos)
        ax = fig.add_subplot(111)
        lo = max(float(np.nanmin(z)), -60) if not pos else 0
        hi = 0 if not pos else min(float(np.nanmax(z)), 60)
        cmap = "viridis" if not pos else "viridis_r"
        m = ax.pcolormesh(res.f / 1e9, res.theta, z.T, shading="auto", cmap=cmap, vmin=lo, vmax=hi,
                          rasterized=True)
        cb = fig.colorbar(m, ax=ax)
        cb.set_label(quantity_label("RL", pos))
        if self.chk_contour.isChecked():
            levels = sorted([10, 20] if pos else [-20, -10])
            try:
                cs = ax.contour(res.f / 1e9, res.theta, z.T, levels=levels, colors="white", linewidths=1)
                ax.clabel(cs, fmt="%g dB", fontsize=8)
            except ValueError:
                pass
        if self.ctx.project.sweep.log_f:
            ax.set_xscale("log")
        ax.set_xlabel(tr("Frequency [GHz]"))
        ax.set_ylabel(tr("Incidence angle [°]"))
        ax.grid(False)
        self._z = z
        return None

    def format_cursor(self, ax, x, y):
        res = self.ctx.results.get("map")
        if res is None or not hasattr(self, "_z"):
            return ""
        i = int(np.argmin(np.abs(res.f / 1e9 - x)))
        j = int(np.argmin(np.abs(res.theta - y)))
        return tr("f = {f} GHz, θ = {a}°, RL = {v} dB", f=f"{x:.5g}", a=f"{y:.3g}", v=f"{self._z[i, j]:.2f}")

    def data_table(self):
        res = self.ctx.results.get("map")
        if res is None:
            return None
        pol = self.cb_pol.currentData()
        z = quantity_values(res, "RL", pol, self.ctx.rl_positive)
        header = ["f [GHz] \\ theta [deg]"] + [f"{t:.6g}" for t in res.theta]
        rows = [[f"{fi / 1e9:.9g}"] + [f"{v:.6g}" for v in z[i]] for i, fi in enumerate(res.f)]
        return header, rows


# ---------------------------------------------------------------------------
class SmithView(PlotView):
    title = "smith_chart"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.pol_boxes = {}
        for pol in ("TE", "TM"):
            b = QCheckBox(pol)
            b.setChecked(pol == "TE")
            b.toggled.connect(lambda _: self.mark_dirty())
            self.controls.addWidget(b)
            self.pol_boxes[pol] = b
        self.controls.addWidget(QLabel(tr("Γ locus over the frequency sweep; ● start, ■ stop")))
        self.controls.addStretch(1)

    def _grid(self, ax):
        c = self.ctx.colors
        t = np.linspace(0, 2 * np.pi, 400)
        ax.plot(np.cos(t), np.sin(t), color=c.text, lw=1.2)
        for r in (0.2, 0.5, 1, 2, 5):
            cx, rad = r / (1 + r), 1 / (1 + r)
            ax.plot(cx + rad * np.cos(t), rad * np.sin(t), color=c.grid, lw=0.8)
            ax.text(cx - rad + 0.01, 0.015, f"{r:g}", fontsize=7, color=c.muted)
        for x in (0.2, 0.5, 1, 2, 5):
            for sgn in (1, -1):
                xs = sgn * x
                cy, rad = 1 / xs, 1 / abs(xs)
                pts = 1 + 1j / xs + rad * np.exp(1j * t)
                pts = pts[np.abs(pts) <= 1.0001]
                ax.plot(pts.real, pts.imag, ".", ms=0.6, color=c.grid)
                g = (1j * xs - 1) / (1j * xs + 1)
                ax.text(g.real * 1.06, g.imag * 1.06, f"{xs:+g}j", fontsize=7, color=c.muted,
                        ha="center", va="center")
                _ = cy
        ax.axhline(0, color=c.grid, lw=0.8)

    def draw_plot(self, fig):
        res = self.ctx.results.get("freq")
        if res is None:
            return self.ctx.result_error
        ax = fig.add_subplot(111)
        ax.set_aspect("equal")
        ax.axis("off")
        self._grid(ax)
        c = self.ctx.colors
        for k, pol in enumerate(("TE", "TM")):
            if not self.pol_boxes[pol].isChecked():
                continue
            g = res.pol[pol].gamma[:, 0]
            col = c.series[k]
            ax.plot(g.real, g.imag, color=col, lw=2, label=pol)
            ax.plot(g.real[0], g.imag[0], "o", color=col)
            ax.plot(g.real[-1], g.imag[-1], "s", color=col)
        problems = []
        sw = self.ctx.project.sweep
        checked = [p for p, b in self.pol_boxes.items() if b.isChecked()]
        pols, suffix = _ref_pols(checked, abs(sw.angle) < 1e-9, allowed=("TE", "TM"))
        for ref in _visible_refs(self.ctx):
            if ref.kind != "design":
                continue  # a measured |RL| has no phase
            r = ref.results(sw).get("freq")
            if isinstance(r, Exception):
                problems.append(f"{ref.name}: {r}")
                continue
            st = _ref_style(ref, c)
            for pol in pols:
                g = r.pol[pol].gamma[:, 0]
                ax.plot(g.real, g.imag, label=_ref_label(ref, pol, suffix), **st)
                ax.plot(g.real[0], g.imag[0], "o", ms=4, color=st["color"])
                ax.plot(g.real[-1], g.imag[-1], "s", ms=4, color=st["color"])
        ax.set_xlim(-1.12, 1.12)
        ax.set_ylim(-1.12, 1.12)
        ax.set_title(tr("Incidence {a}°", a=f"{self.ctx.project.sweep.angle:g}"), fontsize=10, loc="left")
        _legend_if_any(ax, loc="upper left")
        return (_ref_warning(problems), "warn") if problems else None

    def format_cursor(self, ax, x, y):
        g = complex(x, y)
        if abs(g) > 1:
            return ""
        z = (1 + g) / (1 - g)
        return tr("Γ = {g}, z = {z}", g=f"{g.real:.3f}{g.imag:+.3f}j", z=f"{z.real:.3f}{z.imag:+.3f}j")

    def data_table(self):
        res = self.ctx.results.get("freq")
        if res is None:
            return None
        rows = []
        for i, f in enumerate(res.f):
            row = [f"{f / 1e9:.9g}"]
            for pol in ("TE", "TM"):
                g = res.pol[pol].gamma[i, 0]
                z = res.pol[pol].z_in[i, 0]
                row += [f"{g.real:.9g}", f"{g.imag:.9g}", f"{z.real:.9g}", f"{z.imag:.9g}"]
            rows.append(row)
        return (["f [GHz]", "Re G TE", "Im G TE", "Re z TE", "Im z TE",
                 "Re G TM", "Im G TM", "Re z TM", "Im z TM"], rows)


# ---------------------------------------------------------------------------
class AbsorptionView(PlotView):
    title = "absorption_breakdown"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.cb_pol = QComboBox()
        for p in ("avg", "TE", "TM"):
            self.cb_pol.addItem(pol_label(p), p)
        self.cb_pol.currentIndexChanged.connect(lambda _: self.mark_dirty())
        self.controls.addWidget(QLabel(tr("Polarisation")))
        self.controls.addWidget(self.cb_pol)
        self.controls.addStretch(1)

    def _labels(self):
        out = []
        for i, ly in enumerate(self.ctx.project.structure.layers):
            name = ly.name or (tr("Sheet") if isinstance(ly, SheetLayer) else ly.material)
            out.append(f"{i + 1}. {name}")
        return out

    def draw_plot(self, fig):
        res = self.ctx.results.get("freq")
        if res is None:
            return self.ctx.result_error
        pol = self.cb_pol.currentData()
        a = res.layer_absorption(pol)[:, :, 0]
        r = res.quantity("R", pol)[:, 0]
        t = res.quantity("T", pol)[:, 0]
        x = res.f / 1e9
        ax = fig.add_subplot(111)
        labels = self._labels()
        series = list(np.clip(a, 0, None)) + [t, r]
        names = labels + [tr("Transmitted"), tr("Reflected")]
        order = (0, 2, 3, 4, 1, 5)
        cols = [self.ctx.colors.series[order[i % len(order)]] for i in range(len(labels))]
        cols += [self.ctx.colors.muted, self.ctx.colors.border]
        ax.stackplot(x, *series, labels=names, colors=cols, alpha=0.85)
        if self.ctx.project.sweep.log_f:
            ax.set_xscale("log")
        ax.set_xlim(x[0], x[-1])
        ax.set_ylim(0, 1)
        ax.set_xlabel(tr("Frequency [GHz]"))
        ax.set_ylabel(tr("Fraction of incident power"))
        ax.set_title(tr("Incidence {a}°", a=f"{self.ctx.project.sweep.angle:g}"), fontsize=10, loc="left")
        ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=8)
        return None

    def format_cursor(self, ax, x, y):
        return tr("f = {f} GHz, value = {v}", f=f"{x:.5g}", v=f"{y:.4g}")

    def data_table(self):
        res = self.ctx.results.get("freq")
        if res is None:
            return None
        pol = self.cb_pol.currentData()
        a = res.layer_absorption(pol)[:, :, 0]
        header = ["f [GHz]"] + [f"A {n}" for n in self._labels()] + ["T", "R"]
        rows = []
        for i, f in enumerate(res.f):
            rows.append([f"{f / 1e9:.9g}"] + [f"{v:.9g}" for v in a[:, i]]
                        + [f"{res.quantity('T', pol)[i, 0]:.9g}", f"{res.quantity('R', pol)[i, 0]:.9g}"])
        return header, rows


# ---------------------------------------------------------------------------
class MaterialView(PlotView):
    title = "material_properties"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.cb_mat = QComboBox()
        self.cb_mat.setMinimumContentsLength(18)
        self.cb_mat.currentIndexChanged.connect(lambda _: self.mark_dirty())
        self.controls.addWidget(QLabel(tr("Material")))
        self.controls.addWidget(self.cb_mat)
        self.controls.addStretch(1)
        self._data = None

    def sync_materials(self, reset=False):
        """Refill the material list.  ``reset`` (new or opened project) jumps to a material the
        design uses; otherwise the user's current choice is kept."""
        cur = self.cb_mat.currentText()
        names = list(self.ctx.project.materials)
        used = [ly.material for ly in self.ctx.project.structure.layers if hasattr(ly, "material")]
        self.cb_mat.blockSignals(True)
        self.cb_mat.clear()
        self.cb_mat.addItems(names)
        if cur in names and not (reset and used):
            self.cb_mat.setCurrentText(cur)
        elif used:
            self.cb_mat.setCurrentText(used[0])
        self.cb_mat.blockSignals(False)
        self.mark_dirty()

    def draw_plot(self, fig):
        p = self.ctx.project
        name = self.cb_mat.currentText()
        if name not in p.materials:
            return None
        sw = p.sweep
        f = np.geomspace(sw.f_min, sw.f_max, 400) if sw.log_f else np.linspace(sw.f_min, sw.f_max, 400)
        eps, mu = p.materials[name].eps_mu(f, p.resolver)
        eps = np.broadcast_to(eps, f.shape)
        mu = np.broadcast_to(mu, f.shape)
        self._data = (f, eps, mu)
        x = f / 1e9
        c = self.ctx.colors
        ax1 = fig.add_subplot(121)
        ax1.plot(x, eps.real, color=c.series[0], label="ε′")
        ax1.plot(x, -eps.imag, color=c.series[1], ls="--", label="ε″")
        ax2 = fig.add_subplot(122)
        ax2.plot(x, mu.real, color=c.series[0], label="μ′")
        ax2.plot(x, -mu.imag, color=c.series[1], ls="--", label="μ″")
        for ax, t in ((ax1, tr("Permittivity")), (ax2, tr("Permeability"))):
            if sw.log_f:
                ax.set_xscale("log")
            ax.set_xlim(x[0], x[-1])
            ax.set_xlabel(tr("Frequency [GHz]"))
            ax.set_title(t, fontsize=10, loc="left")
            ax.legend(loc="best")
        return None

    def format_cursor(self, ax, x, y):
        return tr("f = {f} GHz, value = {v}", f=f"{x:.5g}", v=f"{y:.4g}")

    def data_table(self):
        if self._data is None:
            return None
        f, eps, mu = self._data
        return (["f [GHz]", "eps'", "eps''", "mu'", "mu''"],
                [[f"{fi / 1e9:.9g}", f"{e.real:.9g}", f"{-e.imag:.9g}", f"{m.real:.9g}", f"{-m.imag:.9g}"]
                 for fi, e, m in zip(f, eps, mu)])
