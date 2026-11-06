"""Result views: frequency, angle, map, Smith chart, absorption breakdown, material properties."""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel

from coating_studio.core.structure import SheetLayer
from coating_studio.gui.plots.base import PlotView
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


def _style_for(pol, colors):
    return {"TE": dict(color=colors.series[0]), "TM": dict(color=colors.series[1], ls="--"),
            "avg": dict(color=colors.series[2], lw=2.4)}[pol]


# ---------------------------------------------------------------------------
class FrequencyView(_QuantityMixin, PlotView):
    title = "reflection_vs_frequency"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self._add_quantity_controls()
        self.chk_target = QCheckBox(tr("−10 dB line"))
        self.chk_target.setChecked(True)
        self.chk_target.toggled.connect(lambda _: self.mark_dirty())
        self.controls.insertWidget(self.controls.count() - 1, self.chk_target)

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
        if self._pols():
            ax.legend(loc="best")
        self._ax = ax
        return None

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
        return header, [[f"{a:.9g}" for a in row] for row in zip(res.f / 1e9, *cols)]


# ---------------------------------------------------------------------------
class AngleView(_QuantityMixin, PlotView):
    title = "reflection_vs_angle"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self._add_quantity_controls()

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
        ax.set_xlim(res.theta[0], res.theta[-1])
        ax.set_xlabel(tr("Incidence angle [°]"))
        ax.set_ylabel(quantity_label(q, pos))
        if q != "RL":
            ax.set_ylim(-0.02, 1.02)
        ax.set_title(tr("f = {f} GHz", f=f"{res.f[0] / 1e9:.5g}"), fontsize=10, loc="left")
        if self._pols():
            ax.legend(loc="best")
        return None

    def format_cursor(self, ax, x, y):
        return tr("θ = {a}°, value = {v}", a=f"{x:.4g}", v=f"{y:.4g}")

    def data_table(self):
        res = self.ctx.results.get("angle")
        if res is None:
            return None
        q = self.cb_q.currentData()
        pols = ["TE", "TM", "avg"]
        cols = [quantity_values(res, q, p, self.ctx.rl_positive)[0, :] for p in pols]
        return (["theta [deg]"] + [f"{q} {p}" for p in pols],
                [[f"{a:.9g}" for a in row] for row in zip(res.theta, *cols)])


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
        self.chk_contour = QCheckBox(tr("−10 / −20 dB contours"))
        self.chk_contour.setChecked(True)
        self.chk_contour.toggled.connect(lambda _: self.mark_dirty())
        self.controls.addWidget(self.chk_contour)
        self.controls.addStretch(1)

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
        ax.set_xlim(-1.12, 1.12)
        ax.set_ylim(-1.12, 1.12)
        if any(b.isChecked() for b in self.pol_boxes.values()):
            ax.legend(loc="upper left")
        return None

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
