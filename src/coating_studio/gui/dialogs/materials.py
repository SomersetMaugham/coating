"""Material manager: create, edit, import, fit and delete project materials."""

from __future__ import annotations

import numpy as np
import matplotlib
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QMessageBox, QPushButton, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QToolButton,
    QVBoxLayout, QWidget,
)

from coating_studio.gui.dialogs.fit import FitDialog
from coating_studio.gui.fmt import fmt_num
from coating_studio.gui.icons import icon, set_button_icon
from coating_studio.gui.theme import mpl_rc
from coating_studio.gui.widgets.inputs import SciSpinBox, muted
from coating_studio.i18n import issue_text, tr
from coating_studio.materials import (
    ConstantMaterial, DispersiveMaterial, MixtureMaterial, TabulatedMaterial, eps_from_nk, loss_from_tangent,
    loss_tangent, make_term, material_from_dict, nk_from_eps_mu,
)
from coating_studio.materials.checks import check_material
from coating_studio.materials.csvio import CsvFormatError, load_csv
from coating_studio.materials.library import load_library, save_library
from coating_studio.project import ProjectError

KIND_LABEL = {"constant": "Constant", "dispersive": "Dispersive model", "tabulated": "Measured data",
              "mixture": "Mixture (EMA)"}


class _TermsTable(QWidget):
    """Editable list of Debye / Lorentz terms."""

    def __init__(self, on_change, parent=None):
        super().__init__(parent)
        self.on_change = on_change
        self.terms = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tbl = QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels([tr("Type"), "Δ", "f₀ [GHz]", "γ [GHz]", ""])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setSelectionMode(QAbstractItemView.NoSelection)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.tbl.setMinimumHeight(90)
        lay.addWidget(self.tbl)
        row = QHBoxLayout()
        b1 = QPushButton(tr("Debye term"))
        set_button_icon(b1, "add")
        b1.clicked.connect(lambda: self._add("debye"))
        b2 = QPushButton(tr("Lorentz term"))
        set_button_icon(b2, "add")
        b2.clicked.connect(lambda: self._add("lorentz"))
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch(1)
        lay.addLayout(row)

    def set_terms(self, terms):
        self.terms = [dict(t) for t in terms]
        self.tbl.setRowCount(len(self.terms))
        for r, t in enumerate(self.terms):
            it = QTableWidgetItem(tr("Debye") if t["type"] == "debye" else tr("Lorentz"))
            it.setFlags(Qt.ItemIsEnabled)
            self.tbl.setItem(r, 0, it)
            for c, key, scale in ((1, "delta", 1.0), (2, "f0", 1e9), (3, "gamma", 1e9)):
                if key == "gamma" and t["type"] != "lorentz":
                    dash = QTableWidgetItem("—")
                    dash.setFlags(Qt.NoItemFlags)
                    self.tbl.removeCellWidget(r, c)
                    self.tbl.setItem(r, c, dash)
                    continue
                sp = SciSpinBox(minimum=0.0, maximum=1e12)
                sp.setFrame(False)
                sp.set_value(t[key] / scale)
                sp.valueEdited.connect(lambda v, r=r, k=key, s=scale: self._edit(r, k, v * s))
                self.tbl.setCellWidget(r, c, sp)
            b = QToolButton()
            set_button_icon(b, "delete")
            b.setAutoRaise(True)
            b.setToolTip(tr("Remove term"))
            b.clicked.connect(lambda _=False, r=r: self._remove(r))
            self.tbl.setCellWidget(r, 4, b)

    def _edit(self, r, key, v):
        if key == "f0" and v <= 0:
            return
        self.terms[r][key] = v
        self.on_change()

    def _add(self, kind):
        self.terms.append(make_term(kind, 1.0, 1e9, 1e9))
        self.set_terms(self.terms)
        self.on_change()

    def _remove(self, r):
        del self.terms[r]
        self.set_terms(self.terms)
        self.on_change()


class MaterialManager(QDialog):
    def __init__(self, doc, ctx, select=None, parent=None):
        super().__init__(parent)
        self.doc, self.ctx = doc, ctx
        self.setWindowTitle(tr("Materials"))
        self.resize(1040, 660)
        self._loading = False
        self.current = None

        split = QSplitter(Qt.Horizontal)
        # ---------------- left: list ------------------------------------------
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.lst = QListWidget()
        self.lst.currentItemChanged.connect(self._on_select)
        ll.addWidget(self.lst, 1)
        row = QHBoxLayout()
        # QPushButton reserves room for the menu arrow; an InstantPopup QToolButton painted the
        # arrow over the last glyph of longer (e.g. Korean) labels.
        self.btn_new = QPushButton(tr("New"))
        set_button_icon(self.btn_new, "add")
        menu = QMenu(self)
        for kind in ("constant", "dispersive", "mixture"):
            menu.addAction(tr(KIND_LABEL[kind]), lambda k=kind: self._new(k))
        menu.addSeparator()
        menu.addAction(icon("import"), tr("Import measured CSV…"), self._import_csv)
        self.btn_new.setMenu(menu)
        self.btn_dup = QToolButton()
        set_button_icon(self.btn_dup, "duplicate")
        self.btn_dup.setToolTip(tr("Duplicate"))
        self.btn_dup.clicked.connect(self._duplicate)
        self.btn_del = QToolButton()
        set_button_icon(self.btn_del, "delete")
        self.btn_del.setToolTip(tr("Delete"))
        self.btn_del.clicked.connect(self._delete)
        self.btn_lib = QPushButton(tr("Library"))
        lm = QMenu(self)
        lm.addAction(tr("Import materials from library file…"), self._import_library)
        lm.addAction(tr("Export all materials to library file…"), self._export_library)
        self.btn_lib.setMenu(lm)
        for b in (self.btn_new, self.btn_dup, self.btn_del):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_lib)
        ll.addLayout(row)
        split.addWidget(left)

        # ---------------- right: editor -------------------------------------
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        common = QGroupBox(tr("General"))
        cf = QFormLayout(common)
        cf.setLabelAlignment(Qt.AlignRight)
        self.ed_name = QLineEdit()
        self.ed_name.editingFinished.connect(self._commit)
        self.lbl_kind = QLabel()
        self.sp_density = SciSpinBox(minimum=0.0, maximum=1e3, suffix="g/cm³")
        self.sp_density.valueEdited.connect(self._commit)
        self.ed_note = QLineEdit()
        self.ed_note.editingFinished.connect(self._commit)
        cf.addRow(tr("Name"), self.ed_name)
        cf.addRow(tr("Type"), self.lbl_kind)
        cf.addRow(tr("Density"), self.sp_density)
        cf.addRow(tr("Note"), self.ed_note)
        rl.addWidget(common)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_constant())
        self.stack.addWidget(self._build_dispersive())
        self.stack.addWidget(self._build_tabulated())
        self.stack.addWidget(self._build_mixture())
        rl.addWidget(self.stack)

        self.lbl_issues = QLabel()
        self.lbl_issues.setWordWrap(True)
        self.lbl_issues.setObjectName("banner")
        rl.addWidget(self.lbl_issues)
        self.fig = Figure(figsize=(5, 2.2), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setMinimumHeight(170)
        rl.addWidget(self.canvas, 1)
        split.addWidget(right)
        split.setSizes([260, 780])

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        lay = QVBoxLayout(self)
        lay.addWidget(split, 1)
        hint = muted(tr("Changes apply immediately and can be undone with Ctrl+Z in the main window. "
                        "Loss uses the convention ε = ε′ − jε″ (ε″ > 0 is lossy)."))
        lay.addWidget(hint)
        lay.addWidget(muted(tr("Bold: material is used in the current design.")))
        lay.addWidget(bb)
        self.doc.changed.connect(self._on_doc_changed)
        self._fill_list(select)

    # ---------------- editor pages ----------------------------------------
    def _build_constant(self):
        # Two columns (real | loss) keep the editor short so the preview plot keeps its height.
        w = QGroupBox(tr("Constant complex ε and μ"))
        g = QGridLayout(w)
        self.c_er = SciSpinBox(minimum=-1e6, maximum=1e9)
        self.c_el = SciSpinBox(minimum=-1e6, maximum=1e9)
        self.c_mr = SciSpinBox(minimum=-1e6, maximum=1e9)
        self.c_ml = SciSpinBox(minimum=-1e6, maximum=1e9)
        for sp in (self.c_er, self.c_el, self.c_mr, self.c_ml):
            sp.valueEdited.connect(self._commit)
        # Two other views of the same numbers: loss tangents (keep the real part) and the
        # refractive index (keeps μ).  Editing either rewrites ε″/μ″ or ε.
        self.c_tde = SciSpinBox(minimum=0.0, maximum=1e6)
        self.c_tdm = SciSpinBox(minimum=0.0, maximum=1e6)
        self.c_tde.valueEdited.connect(lambda v: self._commit_tand("eps", v))
        self.c_tdm.valueEdited.connect(lambda v: self._commit_tand("mu", v))
        self.c_n = SciSpinBox(minimum=0.0, maximum=1e6)
        self.c_k = SciSpinBox(minimum=0.0, maximum=1e6)
        for sp in (self.c_n, self.c_k):
            sp.valueEdited.connect(self._commit_nk)
        rows = ((("ε′", self.c_er), ("ε″", self.c_el)), (("μ′", self.c_mr), ("μ″", self.c_ml)),
                (("tan δε", self.c_tde), ("tan δμ", self.c_tdm)), (("n", self.c_n), ("k", self.c_k)))
        for r, pair in enumerate(rows):
            for c, (lab, sp) in enumerate(pair):
                lbl = QLabel(lab)
                lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                g.addWidget(lbl, r, 2 * c)
                g.addWidget(sp, r, 2 * c + 1)
        g.addWidget(muted(tr("tan δ = ε″/ε′ (or μ″/μ′); editing it keeps the real part. Refractive index "
                             "N = n − jk = √(εμ); editing n or k sets ε = N²/μ and keeps μ.")), len(rows), 0, 1, 4)
        return w

    def _show_tand(self):
        for re_sp, loss_sp, tan_sp in ((self.c_er, self.c_el, self.c_tde), (self.c_mr, self.c_ml, self.c_tdm)):
            ok = re_sp.value() > 0
            tan_sp.setEnabled(ok)
            tan_sp.setToolTip("" if ok else tr("Loss tangent is only defined when the real part is positive."))
            tan_sp.set_value(loss_tangent(re_sp.value(), loss_sp.value()) if ok else 0.0)

    def _commit_tand(self, which, tan_delta):
        if self._loading:
            return
        re_sp, loss_sp = (self.c_er, self.c_el) if which == "eps" else (self.c_mr, self.c_ml)
        if re_sp.value() <= 0:
            return
        self._loading = True
        try:
            loss_sp.set_value(loss_from_tangent(re_sp.value(), tan_delta))
        finally:
            self._loading = False
        self._commit()

    def _show_nk(self):
        n, k = nk_from_eps_mu(complex(self.c_er.value(), -self.c_el.value()),
                              complex(self.c_mr.value(), -self.c_ml.value()))
        self.c_n.set_value(n)
        self.c_k.set_value(k)

    def _commit_nk(self, *_):
        if self._loading:
            return
        mu = complex(self.c_mr.value(), -self.c_ml.value())
        if mu == 0:
            return
        eps = eps_from_nk(self.c_n.value(), self.c_k.value(), mu)
        self._loading = True
        try:
            self.c_er.set_value(eps.real)
            self.c_el.set_value(-eps.imag)
        finally:
            self._loading = False
        self._commit()

    def _build_dispersive(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        ge = QGroupBox(tr("Permittivity ε(f)"))
        fe = QFormLayout(ge)
        self.d_einf = SciSpinBox(minimum=-1e6, maximum=1e9)
        self.d_eloss = SciSpinBox(minimum=0, maximum=1e9)
        self.d_sigma = SciSpinBox(minimum=0, maximum=1e12, suffix="S/m")
        fe.addRow("ε∞", self.d_einf)
        fe.addRow(tr("ε″ (constant)"), self.d_eloss)
        fe.addRow("σ", self.d_sigma)
        self.d_eterms = _TermsTable(self._commit)
        fe.addRow(self.d_eterms)
        gm = QGroupBox(tr("Permeability μ(f)"))
        fm = QFormLayout(gm)
        self.d_minf = SciSpinBox(minimum=-1e6, maximum=1e9)
        self.d_mloss = SciSpinBox(minimum=0, maximum=1e9)
        fm.addRow("μ∞", self.d_minf)
        fm.addRow(tr("μ″ (constant)"), self.d_mloss)
        self.d_mterms = _TermsTable(self._commit)
        fm.addRow(self.d_mterms)
        fm.addRow(muted(tr("Debye: Δ/(1 + jf/f₀). Lorentz: Δ·f₀²/(f₀² − f² + jfγ). "
                           "A Debye μ-term models Snoek-type ferrite relaxation.")))
        for sp in (self.d_einf, self.d_eloss, self.d_sigma, self.d_minf, self.d_mloss):
            sp.valueEdited.connect(self._commit)
        lay.addWidget(ge)
        lay.addWidget(gm)
        return w

    def _build_tabulated(self):
        w = QGroupBox(tr("Measured data"))
        lay = QVBoxLayout(w)
        self.t_info = QLabel()
        lay.addWidget(self.t_info)
        self.t_tbl = QTableWidget(0, 5)
        self.t_tbl.setHorizontalHeaderLabels(["f [GHz]", "ε′", "ε″", "μ′", "μ″"])
        self.t_tbl.verticalHeader().setVisible(False)
        self.t_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.t_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        lay.addWidget(self.t_tbl)
        row = QHBoxLayout()
        b = QPushButton(tr("Fit dispersion model…"))
        set_button_icon(b, "fit")
        b.clicked.connect(self._fit)
        row.addStretch(1)
        row.addWidget(b)
        lay.addLayout(row)
        lay.addWidget(muted(tr("Linear interpolation inside the measured range; evaluating outside it is "
                               "an error. Fit a causal model to extrapolate.")))
        return w

    def _build_mixture(self):
        w = QGroupBox(tr("Effective-medium mixture"))
        f = QFormLayout(w)
        f.setLabelAlignment(Qt.AlignRight)
        self.m_matrix = QComboBox()
        self.m_incl = QComboBox()
        self.m_frac = SciSpinBox(minimum=0.0, maximum=100.0, suffix="vol%")
        self.m_model = QComboBox()
        self.m_model.addItem("Maxwell-Garnett", "maxwell_garnett")
        self.m_model.addItem("Bruggeman", "bruggeman")
        self.m_density = QLabel()
        f.addRow(tr("Matrix (host)"), self.m_matrix)
        f.addRow(tr("Inclusion (filler)"), self.m_incl)
        f.addRow(tr("Volume fraction"), self.m_frac)
        f.addRow(tr("Mixing rule"), self.m_model)
        f.addRow(tr("Density (computed)"), self.m_density)
        f.addRow(muted(tr("Maxwell-Garnett: dilute spherical inclusions. Bruggeman: symmetric, valid "
                          "through percolation — preferred for conductive fillers.")))
        self.m_matrix.activated.connect(self._commit)
        self.m_incl.activated.connect(self._commit)
        self.m_model.activated.connect(self._commit)
        self.m_frac.valueEdited.connect(self._commit)
        return w

    # ---------------- list --------------------------------------------------
    def _fill_list(self, select=None):
        self._loading = True
        try:
            self.lst.clear()
            p = self.doc.project
            for name, m in p.materials.items():
                it = QListWidgetItem(name)
                users = p.material_users(name)
                tip = tr(KIND_LABEL.get(m.kind, m.kind))
                if users:
                    font = it.font()
                    font.setBold(True)
                    it.setFont(font)
                    tip += "\n" + tr("In use: {u}", u=", ".join(users))
                it.setToolTip(tip)
                self.lst.addItem(it)
        finally:
            self._loading = False
        target = select or self.current
        items = self.lst.findItems(target, Qt.MatchExactly) if target else []
        if items:
            self.lst.setCurrentItem(items[0])
        elif self.lst.count():
            self.lst.setCurrentRow(0)

    def _on_select(self, cur, _prev):
        if self._loading or cur is None:
            return
        self.current = cur.text()
        self._load_editor()

    def _on_doc_changed(self, kind):
        if kind != "model" or self._loading:
            return
        names = list(self.doc.project.materials)
        listed = [self.lst.item(i).text() for i in range(self.lst.count())]
        if names != listed:
            self._fill_list(self.current if self.current in names else None)
        else:
            self._load_editor()

    # ---------------- editor --------------------------------------------------
    def _mat(self):
        return self.doc.project.materials.get(self.current)

    def _load_editor(self):
        m = self._mat()
        if m is None:
            return
        self._loading = True
        try:
            self.ed_name.setText(m.name)
            self.lbl_kind.setText(tr(KIND_LABEL.get(m.kind, m.kind)))
            self.ed_note.setText(m.note)
            try:
                rho = m.get_density(self.doc.project.resolver)
            except Exception:  # noqa: BLE001 - broken references are reported elsewhere
                rho = m.density
            self.sp_density.set_value(rho / 1000)
            self.sp_density.setEnabled(m.kind != "mixture")
            if isinstance(m, ConstantMaterial):
                self.stack.setCurrentIndex(0)
                self.c_er.set_value(m.eps_re)
                self.c_el.set_value(m.eps_loss)
                self.c_mr.set_value(m.mu_re)
                self.c_ml.set_value(m.mu_loss)
                self._show_nk()
                self._show_tand()
            elif isinstance(m, DispersiveMaterial):
                self.stack.setCurrentIndex(1)
                self.d_einf.set_value(m.eps_inf)
                self.d_eloss.set_value(m.eps_loss)
                self.d_sigma.set_value(m.sigma)
                self.d_eterms.set_terms(m.eps_terms)
                self.d_minf.set_value(m.mu_inf)
                self.d_mloss.set_value(m.mu_loss)
                self.d_mterms.set_terms(m.mu_terms)
            elif isinstance(m, TabulatedMaterial):
                self.stack.setCurrentIndex(2)
                lo, hi = m.f_range
                self.t_info.setText(tr("{n} points, {lo}–{hi} GHz · source: {src}", n=len(m.f),
                                       lo=fmt_num(lo / 1e9), hi=fmt_num(hi / 1e9), src=m.source or "—"))
                self.t_tbl.setRowCount(len(m.f))
                for r in range(len(m.f)):
                    for c, v in enumerate((m.f[r] / 1e9, m.eps_re[r], m.eps_loss[r], m.mu_re[r], m.mu_loss[r])):
                        it = QTableWidgetItem(fmt_num(float(v), 6))
                        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                        self.t_tbl.setItem(r, c, it)
            elif isinstance(m, MixtureMaterial):
                self.stack.setCurrentIndex(3)
                others = [n for n in self.doc.project.materials if n != m.name]
                for cb, val in ((self.m_matrix, m.matrix), (self.m_incl, m.inclusion)):
                    cb.clear()
                    cb.addItems(others)
                    if val not in others:
                        cb.addItem(val)
                    cb.setCurrentText(val)
                self.m_frac.set_value(m.fraction * 100)
                self.m_model.setCurrentIndex(0 if m.model == "maxwell_garnett" else 1)
                try:
                    self.m_density.setText(fmt_num(m.get_density(self.doc.project.resolver) / 1000, 5) + " g/cm³")
                except Exception:  # noqa: BLE001
                    self.m_density.setText("—")
        finally:
            self._loading = False
        self._update_preview()

    def _editor_dict(self):
        m = self._mat()
        d = m.to_dict()
        d["name"] = self.ed_name.text().strip() or m.name
        d["note"] = self.ed_note.text()
        if m.kind != "mixture":
            d["density"] = self.sp_density.value() * 1000
        if m.kind == "constant":
            d.update(eps_re=self.c_er.value(), eps_loss=self.c_el.value(),
                     mu_re=self.c_mr.value(), mu_loss=self.c_ml.value())
        elif m.kind == "dispersive":
            d.update(eps_inf=self.d_einf.value(), eps_loss=self.d_eloss.value(), sigma=self.d_sigma.value(),
                     eps_terms=self.d_eterms.terms, mu_inf=self.d_minf.value(), mu_loss=self.d_mloss.value(),
                     mu_terms=self.d_mterms.terms)
        elif m.kind == "mixture":
            d.update(matrix=self.m_matrix.currentText(), inclusion=self.m_incl.currentText(),
                     fraction=self.m_frac.value() / 100, model=self.m_model.currentData())
        return d

    def _commit(self, *_):
        if self._loading or self._mat() is None:
            return
        old = self.current
        d = self._editor_dict()
        new_name = d["name"]
        if new_name != old and new_name in self.doc.project.materials:
            QMessageBox.warning(self, tr("Name in use"), tr("A material named “{n}” already exists.", n=new_name))
            self.ed_name.setText(old)
            return
        mat = material_from_dict(d)
        self._loading = True
        try:
            self.doc.edit(tr("Edit material {n}", n=old), lambda p: p.replace_material(old, mat),
                          merge_key=("material", old) if new_name == old else None)
        finally:
            self._loading = False
        if new_name != old:
            self.current = new_name
            self._fill_list(new_name)
        else:
            if mat.kind == "constant":
                self._show_nk()
                self._show_tand()
            self._update_preview()

    def _update_preview(self):
        m = self._mat()
        p = self.doc.project
        sw = p.sweep
        c = self.ctx.colors
        f = np.geomspace(sw.f_min, sw.f_max, 300) if sw.log_f else np.linspace(sw.f_min, sw.f_max, 300)
        issues = check_material(m, f, p.resolver) if m else []
        if issues:
            levels = {i.level for i in issues}
            col = c.error if "error" in levels else c.warn if "warning" in levels else c.muted
            self.lbl_issues.setStyleSheet(f"color: {col}; border: 1px solid {col};")
            self.lbl_issues.setText("\n".join("• " + issue_text(i) for i in issues))
            self.lbl_issues.show()
        else:
            self.lbl_issues.hide()
        with matplotlib.rc_context(mpl_rc(c)):
            self.fig.clear()
            self.fig.set_facecolor(c.base)
            if m is None:
                self.canvas.draw_idle()
                return
            try:
                if isinstance(m, TabulatedMaterial):
                    lo, hi = m.f_range
                    f = np.linspace(lo, hi, 300)
                eps, mu = m.eps_mu(f, p.resolver)
                eps = np.broadcast_to(eps, f.shape)
                mu = np.broadcast_to(mu, f.shape)
            except Exception as e:  # noqa: BLE001
                ax = self.fig.add_subplot(111)
                ax.axis("off")
                ax.text(0.5, 0.5, str(e), ha="center", va="center", color=c.error, wrap=True)
                self.canvas.draw_idle()
                return
            x = f / 1e9
            for k, (vals, sym) in enumerate(((eps, "ε"), (mu, "μ"))):
                ax = self.fig.add_subplot(1, 2, k + 1)
                ax.plot(x, vals.real, color=c.series[0], label=f"{sym}′")
                ax.plot(x, -vals.imag, color=c.series[1], ls="--", label=f"{sym}″")
                if sw.log_f:
                    ax.set_xscale("log")
                ax.set_xlabel(tr("Frequency [GHz]"))
                ax.legend(loc="best", fontsize=8)
        self.canvas.draw_idle()

    # ---------------- actions ---------------------------------------------------
    def _new(self, kind):
        p = self.doc.project
        if kind == "constant":
            m = ConstantMaterial(p.unique_material_name(tr("New dielectric")), 3.0, 0.03)
        elif kind == "dispersive":
            m = DispersiveMaterial(p.unique_material_name(tr("New dispersive material")), eps_inf=3.0,
                                   eps_terms=[make_term("debye", 5.0, 5e9)])
        else:
            names = [n for n in p.materials if n != p.structure.incident]
            if len(names) < 2:
                QMessageBox.information(self, tr("Mixture"), tr("A mixture needs at least two other materials."))
                return
            m = MixtureMaterial(p.unique_material_name(tr("New mixture")), names[0], names[1], 0.1)
        self.doc.edit(tr("Add material"), lambda pr: pr.add_material(m))
        self._fill_list(m.name)

    def _import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Import measured data"), "",
                                              tr("CSV files (*.csv *.txt *.dat);;All files (*)"))
        if not path:
            return
        try:
            m = load_csv(path)
        except (CsvFormatError, OSError, ValueError, UnicodeDecodeError) as e:
            QMessageBox.critical(self, tr("Import failed"), str(e))
            return
        m.name = self.doc.project.unique_material_name(m.name)
        self.doc.edit(tr("Import material"), lambda pr: pr.add_material(m))
        self._fill_list(m.name)

    def _duplicate(self):
        m = self._mat()
        if m is None:
            return
        c = m.clone(self.doc.project.unique_material_name(m.name))
        self.doc.edit(tr("Duplicate material"), lambda pr: pr.add_material(c))
        self._fill_list(c.name)

    def _delete(self):
        m = self._mat()
        if m is None:
            return
        users = self.doc.project.material_users(m.name)
        if users:
            QMessageBox.warning(self, tr("Material in use"),
                                tr("“{n}” is used by: {u}. Change those first.", n=m.name, u=", ".join(users)))
            return
        name = m.name
        try:
            self.doc.edit(tr("Delete material"), lambda pr: pr.remove_material(name))
        except ProjectError as e:
            QMessageBox.warning(self, tr("Cannot delete"), str(e))
            return
        self.current = None
        self._fill_list()

    def _fit(self):
        m = self._mat()
        if not isinstance(m, TabulatedMaterial):
            return
        dlg = FitDialog(m, self.ctx, self)
        if dlg.exec() and dlg.result_material is not None:
            new = dlg.result_material
            new.name = self.doc.project.unique_material_name(new.name)
            self.doc.edit(tr("Add fitted material"), lambda pr: pr.add_material(new))
            self._fill_list(new.name)

    def _import_library(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Import library"), "",
                                              tr("Material library (*.json);;All files (*)"))
        if not path:
            return
        try:
            mats = load_library(path)
        except (OSError, ValueError, KeyError) as e:
            QMessageBox.critical(self, tr("Import failed"), str(e))
            return
        names = [m.name for m in mats]
        chosen, ok = QInputDialog.getItem(self, tr("Import library"),
                                          tr("Import which material? ({n} available)", n=len(names)),
                                          [tr("All materials")] + names, 0, False)
        if not ok:
            return
        sel = mats if chosen == tr("All materials") else [m for m in mats if m.name == chosen]

        def mut(p):
            for m in sel:
                if m.name in p.materials:
                    m.name = p.unique_material_name(m.name)
                p.add_material(m)
        self.doc.edit(tr("Import materials"), mut)
        self._fill_list(sel[0].name if sel else None)

    def _export_library(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Export library"), "materials.json",
                                              tr("Material library (*.json)"))
        if not path:
            return
        try:
            save_library(path, list(self.doc.project.materials.values()))
        except OSError as e:
            QMessageBox.critical(self, tr("Export failed"), str(e))
