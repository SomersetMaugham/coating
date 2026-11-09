"""Effective filler table from one measured composite (the dialog of ``coating-cli invert-filler``)."""

from __future__ import annotations

import html
import os

import matplotlib
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from coating_studio.gui import spectral
from coating_studio.gui.icons import set_button_icon
from coating_studio.gui.theme import mpl_rc
from coating_studio.gui.widgets.inputs import muted
from coating_studio.i18n import tr
from coating_studio.limits import inversion_provenance
from coating_studio.materials.checks import is_builtin_demo
from coating_studio.materials.csvio import CsvFormatError, load_csv
from coating_studio.materials.inversion import (
    ILL_CONDITIONED, diagnostics, invert_filler, prediction_checks, provenance_note, validation_errors, warning_flags,
)
from coating_studio.materials.models import (
    ConstantMaterial, MaterialCycleError, MixtureMaterial, OutOfRangeError, TabulatedMaterial, wt_to_vol,
)

_MATERIAL_ERRORS = (OutOfRangeError, MaterialCycleError, KeyError, ValueError)
_CSV_ERRORS = (CsvFormatError, OSError, ValueError, UnicodeDecodeError)
_SOURCE_VALUES, _SOURCE_CSV, _SOURCE_PROJECT = 0, 1, 2


def _number(edit):
    """The value of a required field, or None if it is empty or not a number."""
    try:
        value = float(edit.text().strip())
    except ValueError:
        return None
    return value if np.isfinite(value) else None


def _flag_text(code, a):
    return {
        "filler_ill_conditioned": lambda: tr("At {n} point(s) measurement errors grow more than {k:g}-fold in the "
                                             "filler values: trust predictions, not the values.", n=a["n"],
                                             k=a["limit"]),
        "filler_negative_real": lambda: tr("{n} point(s) have Re ≤ 0.", n=a["n"]),
        "nonpassive_clamped": lambda: tr("Loss set to 0 at {n} point(s); the composite there is reproduced only to "
                                         "{w:.3g}.", n=a["n"], w=a["worst"]),
        "fraction_sensitive": lambda: tr("A 10 % loading error moves predictions by more than {p:.0%}.", p=a["limit"]),
        "model_disagreement": lambda: tr("The other mixing rule predicts differently by more than {p:.0%}.",
                                         p=a["limit"]),
        "no_validation": lambda: tr("No composite at another loading was given: predictions at other loadings are "
                                    "untested."),
        "validation_poor": lambda: tr("{n}: prediction error above {p:.0%}.", n=a["label"], p=a["limit"]),
    }[code]()


class FillerInversionDialog(QDialog):
    """Every input is required and starts empty, so that no material value is invented.  A result can only be used
    while the inputs still match it."""

    def __init__(self, material, ctx, parent=None):
        super().__init__(parent)
        self.src, self.ctx = material, ctx
        self.project = ctx.project
        self.result_filler = None
        self.result_mixture = None  # (matrix name, fraction, model)
        self._report = None
        self._matrix_tab = None
        self._validation = []  # [(label, TabulatedMaterial)], parallel to the table rows
        self.setWindowTitle(tr("Invert filler — {n}", n=material.name))
        self.resize(1040, 700)

        self.ed_name = QLineEdit(tr("{n} filler", n=material.name))
        self.cb_model = QComboBox()
        self.cb_model.addItem(tr("Choose…"), None)
        self.cb_model.addItem("Maxwell-Garnett", "maxwell_garnett")
        self.cb_model.addItem("Bruggeman", "bruggeman")
        self.ed_fraction = QLineEdit()
        self.cb_basis = QComboBox()
        self.cb_basis.addItem(tr("Volume fraction"), "volume")
        self.cb_basis.addItem(tr("Weight fraction"), "weight")
        self.ed_rho_filler = QLineEdit()
        self.ed_rho_matrix = QLineEdit()
        self.ed_rho_matrix.setEnabled(False)
        top = QGroupBox(tr("Composite and filler"))
        form = QFormLayout(top)
        form.addRow(tr("New material name"), self.ed_name)
        form.addRow(tr("Mixing rule"), self.cb_model)
        loading = QHBoxLayout()
        loading.addWidget(self.ed_fraction, 1)
        loading.addWidget(self.cb_basis)
        form.addRow(tr("Filler loading (0–1)"), loading)
        form.addRow(tr("Filler density [kg/m³]"), self.ed_rho_filler)
        form.addRow(tr("Matrix density [kg/m³]"), self.ed_rho_matrix)

        self.cb_source = QComboBox()
        self.cb_source.addItem(tr("Enter values"), _SOURCE_VALUES)
        self.cb_source.addItem(tr("CSV file"), _SOURCE_CSV)
        self.cb_source.addItem(tr("Project material"), _SOURCE_PROJECT)
        self.stack = QStackedWidget()
        self.ed_me_re, self.ed_me_loss, self.ed_mm_re, self.ed_mm_loss = QLineEdit(), QLineEdit(), QLineEdit("1"), QLineEdit("0")
        page = QWidget()
        pf = QFormLayout(page)
        pf.setContentsMargins(0, 0, 0, 0)
        for label, edit in (("ε′", self.ed_me_re), ("ε″", self.ed_me_loss), ("μ′", self.ed_mm_re), ("μ″", self.ed_mm_loss)):
            pf.addRow(label, edit)
        self.stack.addWidget(page)
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        self.lbl_matrix_csv = muted(tr("No file chosen."))
        b = QPushButton(tr("Browse…"))
        b.clicked.connect(self._browse_matrix)
        row.addWidget(self.lbl_matrix_csv, 1)
        row.addWidget(b)
        self.stack.addWidget(page)
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        self.cb_matrix = QComboBox()
        for name in self._matrix_candidates():
            self.cb_matrix.addItem(name)
        row.addWidget(self.cb_matrix, 1)
        self.stack.addWidget(page)
        group_m = QGroupBox(tr("Matrix"))
        lay_m = QVBoxLayout(group_m)
        lay_m.addWidget(self.cb_source)
        lay_m.addWidget(self.stack)

        self.tbl_val = QTableWidget(0, 2)
        self.tbl_val.setHorizontalHeaderLabels([tr("Composite"), tr("Loading")])
        self.tbl_val.verticalHeader().setVisible(False)
        self.tbl_val.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_val.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl_val.setMaximumHeight(110)
        add_csv, add_mat, remove = QPushButton(tr("Add CSV…")), QPushButton(tr("Add material…")), QPushButton(tr("Remove"))
        add_csv.clicked.connect(self._add_validation_csv)
        add_mat.clicked.connect(self._add_validation_material)
        remove.clicked.connect(self._remove_validation)
        buttons = QHBoxLayout()
        for w in (add_csv, add_mat, remove):
            buttons.addWidget(w)
        group_v = QGroupBox(tr("Validation: composites at other loadings (optional)"))
        lay_v = QVBoxLayout(group_v)
        lay_v.addWidget(self.tbl_val)
        lay_v.addLayout(buttons)

        left = QVBoxLayout()
        left.addWidget(top)
        left.addWidget(group_m)
        left.addWidget(group_v)
        left.addStretch(1)

        self.btn_compute = QPushButton(tr("Compute"))
        set_button_icon(self.btn_compute, "fit", True)
        self.btn_compute.setObjectName("primary")
        self.btn_compute.clicked.connect(self.compute)
        self.chk_clamp = QCheckBox(tr("Set negative loss to 0 where allowed"))
        self.chk_clamp.setEnabled(False)
        self.chk_clamp.setToolTip(tr("Only for a few noisy points, and only when you accept the change: those points no "
                                     "longer reproduce the measurement."))
        compute_row = QHBoxLayout()
        compute_row.addWidget(self.btn_compute)
        compute_row.addWidget(self.chk_clamp, 1)
        self.lbl_result = QLabel(tr("Fill in the inputs and press Compute."))
        self.lbl_result.setWordWrap(True)
        self.lbl_result.setTextFormat(Qt.RichText)
        self.lbl_result.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.fig = Figure(figsize=(6, 3), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.chk_mixture = QCheckBox(tr("Also create a mixture with the project matrix"))
        self.chk_mixture.setEnabled(False)
        right = QVBoxLayout()
        right.addLayout(compute_row)
        right.addWidget(self.lbl_result)
        right.addWidget(self.canvas, 1)
        right.addWidget(muted(tr("The result holds effective values tied to this mixing rule and loading, not measured "
                                 "properties of the filler. Confirm it on a new sample.")))
        right.addWidget(self.chk_mixture)

        self.bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_create = self.bb.button(QDialogButtonBox.Ok)
        self.btn_create.setText(tr("Create material"))
        self.btn_create.setEnabled(False)
        self.bb.accepted.connect(self._accept)
        self.bb.rejected.connect(self.reject)

        columns = QHBoxLayout()
        columns.addLayout(left, 2)
        columns.addLayout(right, 3)
        lay = QVBoxLayout(self)
        lay.addLayout(columns, 1)
        lay.addWidget(self.bb)

        self.cb_source.currentIndexChanged.connect(self._on_source)
        self.cb_basis.currentIndexChanged.connect(self._on_basis)
        for sig in (self.cb_model.currentIndexChanged, self.cb_matrix.currentIndexChanged, self.ed_fraction.textChanged,
                    self.ed_rho_filler.textChanged, self.ed_rho_matrix.textChanged, self.ed_me_re.textChanged,
                    self.ed_me_loss.textChanged, self.ed_mm_re.textChanged, self.ed_mm_loss.textChanged,
                    self.tbl_val.itemChanged):
            sig.connect(self._on_input)
        self.chk_clamp.toggled.connect(self._invalidate)  # the name fields do not change the result
        self._plot()

    # ---- inputs ---------------------------------------------------------------------------------------------------

    def _usable(self, m):
        return m is not self.src and not isinstance(m, MixtureMaterial) and inversion_provenance(m) is None

    def _matrix_candidates(self):
        return [m.name for m in self.project.materials.values() if self._usable(m) and not is_builtin_demo(m)]

    def _on_source(self, _index):
        self.stack.setCurrentIndex(self.cb_source.currentData())
        project = self.cb_source.currentData() == _SOURCE_PROJECT
        self.chk_mixture.setEnabled(project)
        if not project:
            self.chk_mixture.setChecked(False)
        self._on_input()

    def _on_basis(self, _index):
        self.ed_rho_matrix.setEnabled(self.cb_basis.currentData() == "weight")
        self._on_input()

    def _on_input(self, *_):
        """A changed input also makes the clampable count stale, so the permission to clamp goes with it."""
        self.chk_clamp.blockSignals(True)
        self.chk_clamp.setChecked(False)
        self.chk_clamp.blockSignals(False)
        self.chk_clamp.setEnabled(False)
        self._invalidate()

    def _invalidate(self, *_):
        if self._report is None and not self.btn_create.isEnabled():
            return
        self._report = None
        self.btn_create.setEnabled(False)
        self.lbl_result.setText(tr("The inputs changed. Press Compute again."))
        self._plot()

    def _read_csv(self, title):
        path, _ = QFileDialog.getOpenFileName(self, title, "", tr("CSV files (*.csv *.txt *.dat);;All files (*)"))
        if not path:
            return None
        try:
            return load_csv(path)
        except _CSV_ERRORS as e:
            QMessageBox.critical(self, tr("Import failed"), str(e))
            return None

    def _browse_matrix(self):
        tab = self._read_csv(tr("Matrix data"))
        if tab is not None:
            self.set_matrix_csv(tab)

    def set_matrix_csv(self, tab):
        self._matrix_tab = tab
        self.lbl_matrix_csv.setText(tab.source or tab.name)
        self._on_input()

    def _add_validation_csv(self):
        tab = self._read_csv(tr("Validation data"))
        if tab is not None:
            self.add_validation(tab.source or tab.name, tab)

    def _add_validation_material(self):
        names = [m.name for m in self.project.materials.values() if isinstance(m, TabulatedMaterial) and self._usable(m)]
        if not names:
            QMessageBox.information(self, tr("Validation"), tr("The project has no other measured material."))
            return
        name, ok = QInputDialog.getItem(self, tr("Validation"), tr("Composite at another loading"), names, 0, False)
        if ok:
            self.add_validation(name, self.project.materials[name])

    def add_validation(self, label, tab, loading=""):
        row = self.tbl_val.rowCount()
        self._validation.append((label, tab))
        self.tbl_val.blockSignals(True)
        self.tbl_val.insertRow(row)
        item = QTableWidgetItem(label)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.tbl_val.setItem(row, 0, item)
        self.tbl_val.setItem(row, 1, QTableWidgetItem(loading))
        self.tbl_val.blockSignals(False)
        self._on_input()

    def _remove_validation(self):
        row = self.tbl_val.currentRow()
        if row >= 0:
            del self._validation[row]
            self.tbl_val.removeRow(row)
            self._on_input()

    def _matrix(self):
        """``(material, label)`` of the chosen matrix, or an error text."""
        source = self.cb_source.currentData()
        if source == _SOURCE_VALUES:
            values = [_number(e) for e in (self.ed_me_re, self.ed_me_loss, self.ed_mm_re, self.ed_mm_loss)]
            if None in values:
                return tr("Enter ε′, ε″, μ′ and μ″ of the matrix.")
            label = f"eps {values[0]:g}-{values[1]:g}j"
            if values[2:] != [1.0, 0.0]:
                label += f" mu {values[2]:g}-{values[3]:g}j"
            return ConstantMaterial("matrix", *values), label
        if source == _SOURCE_CSV:
            if self._matrix_tab is None:
                return tr("Choose the matrix CSV file.")
            return self._matrix_tab, os.path.basename(self._matrix_tab.source or self._matrix_tab.name)
        name = self.cb_matrix.currentText()
        if not name:
            return tr("The project has no matrix material to choose: built-in demonstration values cannot be used.")
        return self.project.materials[name], name

    # ---- computing ------------------------------------------------------------------------------------------------

    def _to_volume(self, value, rho_filler, rho_matrix):
        return value if self.cb_basis.currentData() == "volume" else wt_to_vol(value, rho_filler, rho_matrix)

    def _inputs(self):
        """The parsed inputs as a dict, or a list of what is missing."""
        missing = []
        model = self.cb_model.currentData()
        if model is None:
            missing.append(tr("Choose the mixing rule."))
        fraction, rho_f, rho_m = _number(self.ed_fraction), _number(self.ed_rho_filler), _number(self.ed_rho_matrix)
        if fraction is None or not 0.0 < fraction < 1.0:
            missing.append(tr("Enter a filler loading between 0 and 1."))
        if rho_f is None or rho_f <= 0:
            missing.append(tr("Enter a positive filler density."))
        weight = self.cb_basis.currentData() == "weight"
        if weight and (rho_m is None or rho_m <= 0):
            missing.append(tr("A weight fraction needs a positive matrix density."))
        matrix = self._matrix()
        if isinstance(matrix, str):
            missing.append(matrix)
        return missing or {"model": model, "fraction": fraction, "rho_f": rho_f, "rho_m": rho_m, "matrix": matrix[0],
                           "label": matrix[1]}

    def _validation_rows(self, filler, inp):
        rows = []
        for i, (label, tab) in enumerate(self._validation):
            row = {"csv": label}
            item = self.tbl_val.item(i, 1)
            try:
                value = float(item.text().strip()) if item else float("nan")
            except ValueError:
                value = float("nan")
            if not 0.0 < value < 1.0:
                rows.append({**row, "error": tr("enter a loading between 0 and 1")})
                continue
            row["fraction"] = self._to_volume(value, inp["rho_f"], inp["rho_m"])
            eps, mu = tab.eps_re - 1j * tab.eps_loss, tab.mu_re - 1j * tab.mu_loss
            try:
                rows.append({**row, **validation_errors(filler, inp["matrix"], tab.f, eps, mu, row["fraction"], inp["model"])})
            except _MATERIAL_ERRORS as e:  # one bad row must not lose the inversion
                rows.append({**row, "error": str(e)})
        return rows

    def compute(self):
        self._report = None
        self.btn_create.setEnabled(False)
        inp = self._inputs()
        if isinstance(inp, list):
            self._show_error("<br>".join(html.escape(t) for t in inp))
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._compute(inp)
        except _MATERIAL_ERRORS as e:
            self._show_error(tr("Cannot evaluate the matrix on the composite's frequencies: {e}", e=html.escape(str(e))))
        finally:
            QApplication.restoreOverrideCursor()

    def _compute(self, inp):
        m = self.src
        eps, mu = m.eps_re - 1j * m.eps_loss, m.mu_re - 1j * m.mu_loss
        eps_m, mu_m = inp["matrix"].eps_mu(m.f, self.project.resolver)
        eps_m, mu_m = np.broadcast_to(eps_m, m.f.shape), np.broadcast_to(mu_m, m.f.shape)
        phi = self._to_volume(inp["fraction"], inp["rho_f"], inp["rho_m"])
        res = invert_filler(m.f, eps, mu, eps_m, mu_m, phi, inp["model"], self.chk_clamp.isChecked())
        report = {"res": res, "inp": inp, "phi": phi, "diag": diagnostics(res)}
        if res.ok:
            filler = res.to_tabulated(self._filler_name(), inp["rho_f"], note=provenance_note(m.name, inp["model"], phi, inp["label"]))
            report.update(filler=filler, prediction=prediction_checks(res, eps, mu, eps_m, mu_m),
                          validation=self._validation_rows(filler, inp))
            report["flags"] = warning_flags(res, report["prediction"], report["validation"])
        else:
            self.chk_clamp.setEnabled(res.clampable_points > 0 or self.chk_clamp.isChecked())
        self._report = report
        self.btn_create.setEnabled(res.ok)
        self.lbl_result.setText(self._result_html(report))
        self._plot()

    def _filler_name(self):
        return self.ed_name.text().strip() or tr("{n} filler", n=self.src.name)

    def _show_error(self, text):
        self.lbl_result.setText(f'<span style="color:{self.ctx.colors.error}">{text}</span>')
        self._plot()

    def _result_html(self, report):
        c, res, d = self.ctx.colors, report["res"], report["diag"]

        def span(color, text):
            return f'<span style="color:{color}">{text}</span>'

        if not res.ok:
            text = tr("No usable filler table: {g} point(s) with gain, {o} beyond what this rule can represent, {b} on "
                      "another root. Do not invent values: try the other rule, or measure more loadings.",
                      g=res.gain_points, o=res.outside_model_points, b=res.branch_points)
            if res.clampable_points and not res.clamp_nonpassive:
                text += " " + tr("{n} gain point(s) can be set to 0 if you accept it.", n=res.clampable_points)
            return span(c.error, html.escape(text))

        def kappa(s):
            return "–" if s["median"] is None else f"{s['median']:.3g} / {s['max']:.3g}"

        lines = [tr("Volume fraction used: {v:.4g}", v=report["phi"]),
                 tr("Error amplification κ (median / max): ε {e}, μ {m}", e=kappa(d["amplification"]["eps"]),
                    m=kappa(d["amplification"]["mu"]))]
        p = report["prediction"]
        if p["fraction_sensitivity"]:
            lines.append(tr("Prediction change for a 10 % loading error: ε {e:.1%}, μ {m:.1%}",
                            e=p["fraction_sensitivity"]["rms_eps"], m=p["fraction_sensitivity"]["rms_mu"]))
        if p["model_disagreement"]:
            lines.append(tr("Difference from the other mixing rule: ε {e:.1%}, μ {m:.1%}",
                            e=p["model_disagreement"]["rms_eps"], m=p["model_disagreement"]["rms_mu"]))
        else:
            lines.append(tr("The other mixing rule cannot represent this composite."))
        for v in report["validation"]:
            if "error" in v:
                lines.append(span(c.warn, html.escape(tr("Validation {n}: {e}", n=v["csv"], e=v["error"]))))
            else:
                lines.append(tr("Validation {n} at {p:.4g}: ε {e:.1%}, μ {m:.1%}", n=html.escape(v["csv"]),
                                p=v["fraction"], e=v["rms_eps"], m=v["rms_mu"]))
        lines += [span(c.warn, html.escape(_flag_text(code, a))) for code, a in report["flags"]]
        return "<br>".join(lines)

    def _plot(self):
        c = self.ctx.colors
        with matplotlib.rc_context(mpl_rc(c)):
            self.fig.clear()
            self.fig.set_facecolor(c.base)
            if self._report is not None:
                self._draw(self._report["res"], c)
        self.canvas.draw_idle()

    def _draw(self, res, c):
        """Points only: the table is used by linear interpolation, but a line drawn through a sign change of Re would
        suggest values that the mixing rule's pole makes wrong."""
        unit = spectral.unit_of(self.project)
        x = spectral.x_values(res.f, unit)
        for k, (ch, sym) in enumerate(((res.eps, "ε"), (res.mu, "μ"))):
            ax = self.fig.add_subplot(1, 2, k + 1)
            finite = np.isfinite(ch.value)
            ax.plot(x[finite], ch.value.real[finite], "o", ms=3, color=c.series[0], label=f"{sym}′")
            ax.plot(x[finite], -ch.value.imag[finite], "s", ms=3, color=c.series[1], label=f"{sym}″")
            marks = ((finite & (ch.amplification > ILL_CONDITIONED), "o", c.warn, tr("ill-conditioned"), "none"),
                     (finite & ch.clamped, "x", c.warn, tr("loss set to 0"), c.warn),
                     (finite & (ch.gain | ch.outside_model | ch.branch), "x", c.error, tr("blocked"), c.error))
            for mask, marker, color, label, face in marks:
                if mask.any():
                    ax.plot(x[mask], ch.value.real[mask], marker, ms=7, color=color, mfc=face, label=label)
            ax.set_xscale("log" if res.f[-1] / res.f[0] > 20 else "linear")
            spectral.set_xlim(ax, x)
            ax.set_xlabel(spectral.axis_label(unit))
            ax.legend(fontsize=8)

    def _accept(self):
        report = self._report
        if report is None or not report["res"].ok:
            return
        self.result_filler = report["filler"]
        self.result_filler.name = self._filler_name()
        if self.chk_mixture.isChecked():
            self.result_mixture = (report["inp"]["matrix"].name, report["phi"], report["inp"]["model"])
        self.accept()
