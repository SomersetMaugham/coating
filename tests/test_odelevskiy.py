"""The Odelevskiy mixing rule for non-spherical inclusions: limits, inversion, saving and the two front ends."""

import io
import json
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from coating_studio.cli import commands as C  # noqa: E402
from coating_studio.cli import main  # noqa: E402
from coating_studio.i18n import tr  # noqa: E402
from coating_studio.limits import (  # noqa: E402
    inversion_provenance, inversion_shape, mixture_range_issues, static_permeability,
)
from coating_studio.materials.checks import check_material  # noqa: E402
from coating_studio.materials.csvio import load_csv, to_csv_text  # noqa: E402
from coating_studio.materials.inversion import (  # noqa: E402
    invert_filler, invert_rule, mix, prediction_checks, prediction_fractions, provenance_note, validation_errors,
)
from coating_studio.materials.models import (  # noqa: E402
    ConstantMaterial, MixtureMaterial, PercolationError, Shape, TabulatedMaterial, bruggeman, material_from_dict,
    maxwell_garnett, odelevskiy,
)
from coating_studio.optimize import optimize  # noqa: E402
from coating_studio.project import SCHEMA_VERSION, ContinuousVariable, Project  # noqa: E402

F = np.linspace(2e9, 18e9, 41)
EM = (3 - 0.02j) * np.ones_like(F, dtype=complex)
MM = np.ones_like(F, dtype=complex)
EI = (30 - 5j) * np.ones_like(F, dtype=complex)
MI = 1 + 4 / (1 + 1j * F / 5e9)
FLAKE = Shape(0.1, 0.2)
MG_SHAPE = Shape(1 / 3, 1.0)


def composite(phi=0.1, shape=FLAKE):
    return mix(EM, EI, phi, "odelevskiy", shape), mix(MM, MI, phi, "odelevskiy", shape)


def resolver_for(*materials):
    table = {m.name: m for m in materials}
    return lambda name: table[name]


def mixture(fraction=0.1, n=0.1, pc=0.2, name="mix"):
    return MixtureMaterial(name, "host", "fill", fraction, "odelevskiy", shape_n=n, percolation=pc)


HOST = ConstantMaterial("host", 3.0, 0.02)
FILL = ConstantMaterial("fill", 30.0, 5.0, 4.0, 0.0)


# ---- the rule ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("ei", [30 - 5j, 1e6 - 1e7j, 3.5 - 0.1j, 0.5 - 2j])
def test_one_third_and_threshold_one_is_maxwell_garnett(ei):
    em, ei = np.array([3 - 0.02j]), np.array([ei])
    assert abs(odelevskiy(em, ei, 0.2, MG_SHAPE)[0] - maxwell_garnett(em, ei, 0.2)[0]) <= 1e-12 * abs(ei[0] + em[0])


def test_threshold_equal_to_the_shape_factor_is_bruggeman_at_high_contrast():
    em, ei = np.array([3 - 0.02j]), np.array([1e6 - 1e7j])
    assert abs(odelevskiy(em, ei, 0.2, Shape(1 / 3, 1 / 3))[0] / bruggeman(em, ei, 0.2)[0] - 1) < 1e-5


def test_published_form_of_the_rule():
    em, ei, phi, n, pc = 2.18 + 0j, 40 - 3j, 0.05, 0.07, 0.13
    expected = em * (1 + phi / ((1 - phi / pc) * n + em / (ei - em)))
    assert odelevskiy(np.array([em]), np.array([ei]), phi, Shape(n, pc))[0] == pytest.approx(expected)


def test_a_filler_equal_to_the_matrix_changes_nothing():
    assert odelevskiy(EM, EM, 0.1, FLAKE) == pytest.approx(EM)


@pytest.mark.parametrize("phi", [0.2, 0.25, 1.0])
def test_at_or_above_the_threshold_raises(phi):
    with pytest.raises(PercolationError):
        odelevskiy(EM, EI, phi, FLAKE)


def test_a_fill_scale_is_equivalent_after_inversion():
    """Published (N, pc, k) can be entered as (N/k, pc/k): an inverted table then predicts the same mixtures."""
    n, pc, k, phi0 = 0.07, 0.13, 2 / 3, 0.09

    def with_scale(em, ei, phi):
        p = k * phi
        return em * (1 + p / ((1 - p / pc) * n + em / (ei - em)))

    measured = with_scale(EM, EI, phi0)
    shape = Shape(n / k, pc / k)
    table, _ = invert_rule(measured, EM, phi0, "odelevskiy", shape)
    assert mix(EM, table, 0.14, "odelevskiy", shape) == pytest.approx(with_scale(EM, EI, 0.14))


# ---- the material ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("kw", [{}, {"shape_n": 0.1}, {"percolation": 0.2}, {"shape_n": 0.0, "percolation": 0.2},
                                {"shape_n": 1.0, "percolation": 0.2}, {"shape_n": 0.1, "percolation": 0.0},
                                {"shape_n": 0.1, "percolation": 1.5}])
def test_invalid_or_missing_parameters_are_refused(kw):
    with pytest.raises(ValueError):
        MixtureMaterial("m", "a", "b", 0.1, "odelevskiy", **kw)


def test_spherical_rules_refuse_shape_parameters():
    with pytest.raises(ValueError):
        MixtureMaterial("m", "a", "b", 0.1, "bruggeman", shape_n=0.1, percolation=0.2)


def test_only_this_rule_saves_the_new_keys():
    d = MixtureMaterial("m", "a", "b", 0.1, "bruggeman").to_dict()
    assert "shape_n" not in d and "percolation" not in d
    d = mixture().to_dict()
    assert (d["shape_n"], d["percolation"]) == (0.1, 0.2)
    again = material_from_dict(d)
    assert (again.shape_n, again.percolation, again.model) == (0.1, 0.2, "odelevskiy")


def test_copy_keeps_the_shape():
    import copy

    assert copy.deepcopy(mixture()).shape == FLAKE


def test_fraction_parameter_stays_below_the_threshold():
    assert mixture().params()[0].upper < 0.2
    assert MixtureMaterial("m", "a", "b", 0.1).params()[0].upper == 1.0


def test_density_uses_the_true_fraction():
    host, fill = ConstantMaterial("host", 3.0, density=1000.0), ConstantMaterial("fill", 30.0, density=8000.0)
    assert mixture().get_density(resolver_for(host, fill)) == pytest.approx(0.1 * 8000 + 0.9 * 1000)


def test_project_round_trip_and_schema(tmp_path):
    p = Project()
    for m in (HOST, FILL, mixture()):
        p.add_material(m)
    path = str(tmp_path / "a.coat")
    p.save(path)
    assert json.loads(open(path, encoding="utf-8").read())["schema"] == SCHEMA_VERSION >= 9
    q = Project.load(path)
    assert q.materials["mix"].shape == FLAKE
    assert q.copy().materials["mix"].shape == FLAKE


def test_older_files_load_and_keep_their_rule(tmp_path):
    p = Project()
    for m in (HOST, FILL, MixtureMaterial("old", "host", "fill", 0.1, "maxwell_garnett")):
        p.add_material(m)
    d = p.to_dict()
    d["schema"] = 8
    path = tmp_path / "old.coat"
    path.write_text(json.dumps(d), encoding="utf-8")
    q = Project.load(str(path))
    assert q.materials["old"].shape is None and q.materials["old"].model == "maxwell_garnett"


# ---- diagnostics -------------------------------------------------------------------------------------------------

def test_static_permeability_and_above_the_threshold():
    host, fill = ConstantMaterial("host", 3.0, 0.0), ConstantMaterial("fill", 30.0, 0.0, 4.0, 0.0)
    r = resolver_for(host, fill)
    expected = float(odelevskiy(np.array([1 + 0j]), np.array([4 + 0j]), 0.1, FLAKE)[0].real)
    assert static_permeability(mixture(), r)[0] == pytest.approx(expected)
    assert static_permeability(mixture(fraction=0.3), r)[0] is None


def test_check_reports_a_fraction_above_the_threshold():
    from coating_studio.i18n import issue_text

    issues = check_material(mixture(fraction=0.3), F, resolver_for(HOST, FILL))
    assert [i.code for i in issues] == ["percolation_exceeded"]
    assert "0.2" in issue_text(issues[0], lang="en") and "0.3" in issue_text(issues[0], lang="en")


def warned(fraction, n=0.1, pc=0.2):
    p = Project()
    for m in (HOST, FILL, mixture(fraction=fraction, n=n, pc=pc)):
        p.add_material(m)
    return {i.code for i in mixture_range_issues(p, 1e10, names={"mix"})}


def test_warning_close_to_the_threshold():
    assert "mixture_fraction_range" not in warned(0.17)
    assert "mixture_fraction_range" in warned(0.19)


def test_optimiser_survives_a_range_that_crosses_the_threshold():
    from coating_studio.core import Backing, SlabLayer, Structure

    p = Project()
    for m in (HOST, FILL, mixture()):
        p.add_material(m)
    layer = SlabLayer("mix", 3e-3)
    p.structure = Structure([layer], backing=Backing("pec"))
    o = p.optimization
    from coating_studio.project import BandTarget

    o.targets = [BandTarget(f_min=8e9, f_max=12e9, n_f=11, goal_db=-30.0)]
    o.variables = [ContinuousVariable(("material", "mix", "fraction"), 0.05, 0.5)]
    o.maxiter, o.popsize, o.seed, o.polish = 8, 5, 1, False
    result = optimize(p, throttle_s=0.0)
    assert result.values[("material", "mix", "fraction")] < 0.2


# ---- inversion ---------------------------------------------------------------------------------------------------

def test_inversion_round_trip():
    eps, _ = composite()
    value, _ = invert_rule(eps, EM, 0.1, "odelevskiy", FLAKE)
    assert value == pytest.approx(EI)


def test_same_as_maxwell_garnett_at_its_parameters():
    eff = maxwell_garnett(EM, EI, 0.2)
    a, xa = invert_rule(eff, EM, 0.2, "maxwell_garnett")
    b, xb = invert_rule(eff, EM, 0.2, "odelevskiy", MG_SHAPE)
    assert b == pytest.approx(a) and xb == pytest.approx(xa)
    ra, rb = invert_filler(F, eff, MM, EM, MM, 0.2, "maxwell_garnett"), invert_filler(F, eff, MM, EM, MM, 0.2, "odelevskiy", shape=MG_SHAPE)
    assert rb.eps.amplification == pytest.approx(ra.eps.amplification)


def test_amplification_matches_central_differences():
    eps, _ = composite()
    res = invert_filler(F, eps, MM, EM, MM, 0.1, "odelevskiy", shape=FLAKE)
    h = 1e-6 * np.abs(eps)
    up, _ = invert_rule(eps + h, EM, 0.1, "odelevskiy", FLAKE)
    down, _ = invert_rule(eps - h, EM, 0.1, "odelevskiy", FLAKE)
    fd = np.abs((up - down) / (2 * h)) * np.abs(eps) / np.abs(res.eps.value)
    assert res.eps.amplification == pytest.approx(fd, rel=1e-5)


def test_composite_equal_to_the_matrix_is_finite():
    res = invert_filler(F, EM, MM, EM, MM, 0.1, "odelevskiy", shape=FLAKE)
    assert np.all(np.isfinite(res.eps.value)) and res.eps.value == pytest.approx(EM)
    assert res.ok


def test_flake_composite_needs_this_rule():
    """Above what spheres can reach: the spherical rule blocks it, this one does not."""
    eps = (40 - 1j) * np.ones_like(F, dtype=complex)
    assert invert_filler(F, eps, MM, 2.18 + 0 * EM, MM, 0.03, "maxwell_garnett").outside_model_points
    assert invert_filler(F, eps, MM, 2.18 + 0 * EM, MM, 0.03, "odelevskiy", shape=Shape(0.001, 0.2)).ok


def test_beyond_the_rule_is_outside_the_model():
    eps = (400 - 1j) * np.ones_like(F, dtype=complex)
    assert invert_filler(F, eps, MM, 2.18 + 0 * EM, MM, 0.03, "odelevskiy", shape=Shape(0.2, 0.5)).outside_model_points


def test_invert_needs_a_shape():
    eps, _ = composite()
    with pytest.raises(ValueError):
        invert_filler(F, eps, MM, EM, MM, 0.1, "odelevskiy")


def test_prediction_compares_the_percolation_term():
    eps, mu = composite()
    res = invert_filler(F, eps, mu, EM, MM, 0.1, "odelevskiy", shape=FLAKE)
    p = prediction_checks(res, eps, mu, EM, MM)
    assert p["model_disagreement"]["rms_eps"] > 1e-3 and p["model_disagreement_reason"] is None
    assert all(a < 0.2 for a in p["at_fractions"])
    eps1, mu1 = composite(shape=Shape(0.1, 1.0))
    res1 = invert_filler(F, eps1, mu1, EM, MM, 0.1, "odelevskiy", shape=Shape(0.1, 1.0))
    p1 = prediction_checks(res1, eps1, mu1, EM, MM)
    assert p1["model_disagreement"] is None and "threshold of 1" in p1["model_disagreement_reason"]


def test_prediction_skips_a_step_past_the_threshold():
    shape = Shape(0.1, 0.105)
    eps, mu = composite(0.1, shape)
    res = invert_filler(F, eps, mu, EM, MM, 0.1, "odelevskiy", shape=shape)
    assert prediction_checks(res, eps, mu, EM, MM)["fraction_sensitivity"] is not None  # only the -10 % step remains
    assert max(prediction_fractions(0.1, shape)) < 0.105


def test_validation_above_the_threshold_is_an_error():
    eps, mu = composite()
    res = invert_filler(F, eps, mu, EM, MM, 0.1, "odelevskiy", shape=FLAKE)
    table = res.to_tabulated("t", 1000.0)
    with pytest.raises(ValueError):
        validation_errors(table, HOST, F, eps, mu, 0.25, "odelevskiy", FLAKE)


def test_provenance_keeps_the_shape():
    class Stub:
        note = provenance_note("c", "odelevskiy", 0.1, "m", FLAKE)

    assert inversion_provenance(Stub) == ("odelevskiy", 0.1)
    assert inversion_shape(Stub) == FLAKE


def test_other_shape_parameters_warn():
    def codes(n):
        p = Project()
        table = TabulatedMaterial("fill", F, EI.real, -EI.imag, note=provenance_note("c", "odelevskiy", 0.1, "m", FLAKE))
        for m in (HOST, table, mixture(n=n)):
            p.add_material(m)
        return {i.code: i for i in mixture_range_issues(p, 1e10, names={"mix"})}

    assert "inverted_filler_model" not in codes(0.1)
    issue = codes(0.05)["inverted_filler_model"]
    assert "N = 0.1" in issue.args["extracted"] and "N = 0.05" in issue.args["model"]


def test_allowed_range_ends_at_the_threshold():
    p = Project()
    table = TabulatedMaterial("fill", F, EI.real, -EI.imag, note=provenance_note("c", "odelevskiy", 0.15, "m", FLAKE))
    for m in (HOST, table, mixture(fraction=0.19)):
        p.add_material(m)
    found = mixture_range_issues(p, 1e10, names={"mix"})
    assert not [i for i in found if i.code == "inverted_filler_fraction"]
    issue = next(i for i in found if i.code == "mixture_fraction_range")
    assert issue.args["hi"] == 0.2
    p.optimization.variables = [ContinuousVariable(("material", "mix", "fraction"), 0.1, 0.21)]  # 1.5 phi0 is 0.225
    wide = next(i for i in mixture_range_issues(p, 1e10, names={"mix"}) if i.code == "inverted_filler_fraction")
    assert wide.args["hi"] == 0.2


# ---- CLI and spec ------------------------------------------------------------------------------------------------

def run(*argv):
    out = io.StringIO()
    code = main([str(a) for a in argv], stdout=out, stderr=io.StringIO())
    return code, json.loads(out.getvalue())


def write(path, eps, mu):
    path.write_text(to_csv_text(F, eps, mu), encoding="utf-8")
    return path


def test_cli_inverts_with_the_rule_and_reports_it(tmp_path):
    comp = write(tmp_path / "c.csv", *composite())
    code, d = run("invert-filler", comp, "-o", tmp_path / "f.csv", "--model", "odelevskiy", "--shape-n", 0.1,
                  "--percolation", 0.2, "--density-filler", 5000, "--fraction", 0.1, "--matrix-eps", 3, 0.02)
    assert code == 0 and (d["result"]["shape_n"], d["result"]["percolation"]) == (0.1, 0.2)
    table = load_csv(str(tmp_path / "f.csv"))
    assert inversion_shape(table) == FLAKE and inversion_provenance(table) == ("odelevskiy", 0.1)


@pytest.mark.parametrize("extra", [[], ["--shape-n", 0.1], ["--percolation", 0.2], ["--shape-n", 0.1, "--percolation", 0.05]])
def test_cli_refuses_missing_values_and_a_fraction_above_the_threshold(tmp_path, extra):
    comp = write(tmp_path / "c.csv", *composite())
    code, d = run("invert-filler", comp, "-o", tmp_path / "f.csv", "--model", "odelevskiy", *extra,
                  "--density-filler", 5000, "--fraction", 0.1, "--matrix-eps", 3, 0.02)
    assert code == 3 and not d["ok"] and not (tmp_path / "f.csv").exists()


def test_cli_refuses_shape_values_with_a_spherical_rule(tmp_path):
    comp = write(tmp_path / "c.csv", *composite())
    code, _ = run("invert-filler", comp, "-o", tmp_path / "f.csv", "--model", "bruggeman", "--shape-n", 0.1,
                  "--percolation", 0.2, "--density-filler", 5000, "--fraction", 0.1, "--matrix-eps", 3, 0.02)
    assert code == 3


def test_spec_round_trip():
    from coating_studio.cli.spec import project_to_spec, spec_to_project

    spec = {"spec_version": 1, "name": "s", "backing": "pec",
            "materials": [{"name": "host", "kind": "constant", "eps_re": 3.0},
                          {"name": "fill", "kind": "constant", "eps_re": 30.0},
                          {"name": "mix", "kind": "mixture", "matrix": "host", "inclusion": "fill", "fraction": 0.1,
                           "model": "odelevskiy", "shape_n": 0.1, "percolation": 0.2}],
            "layers": [{"name": "A", "material": "mix", "thickness_mm": 2.0}]}
    p, _ = spec_to_project(spec)
    assert p.materials["mix"].shape == FLAKE
    out = next(m for m in project_to_spec(p)["materials"] if m["name"] == "mix")
    assert (out["shape_n"], out["percolation"]) == (0.1, 0.2)


# ---- GUI ---------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app(tmp_path_factory):
    pytest.importorskip("PySide6")
    import matplotlib

    matplotlib.use("QtAgg")
    from PySide6.QtCore import QCoreApplication, QSettings
    from PySide6.QtWidgets import QApplication

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path_factory.mktemp("cfg")))
    QCoreApplication.setOrganizationName("CoatingStudioTest")
    QCoreApplication.setApplicationName("CoatingStudioTest")
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    from coating_studio.examples import EXAMPLES
    from coating_studio.gui.main_window import MainWindow

    w = MainWindow()
    w.doc.set_project(EXAMPLES["salisbury"][1]())
    yield w
    w.doc._settings_dirty = False
    w.doc.undo_stack.setClean()
    w.close()


def tab_of(eps, mu, name="comp"):
    return TabulatedMaterial(name, F, eps.real, -eps.imag, mu.real, -mu.imag)


def dialog_for(window, material):
    from coating_studio.gui.dialogs.invert_filler import FillerInversionDialog

    d = FillerInversionDialog(material, window)
    d.ed_fraction.setText("0.1")
    d.ed_rho_filler.setText("5000")
    d.ed_me_re.setText("3")
    d.ed_me_loss.setText("0.02")
    d.cb_model.setCurrentIndex(d.cb_model.findData("odelevskiy"))
    return d


def test_dialog_needs_the_shape_values(window):
    d = dialog_for(window, tab_of(*composite()))
    assert not d.ed_n.text() and not d.ed_pc.text()
    d.compute()
    assert d._report is None
    d.ed_n.setText("0.1")
    d.ed_pc.setText("0.05")  # below the loading
    d.compute()
    assert d._report is None
    assert tr("The volume fraction must be below the percolation threshold.") in d.lbl_result.text()


def test_dialog_matches_the_cli_and_changing_a_shape_value_invalidates(window, tmp_path):
    comp = write(tmp_path / "c.csv", *composite())
    cli = C.cmd_invert_filler(str(comp), str(tmp_path / "f.csv"), "odelevskiy", 5000.0, fraction=0.1, matrix_eps=(3.0, 0.02),
                              shape_n=0.1, percolation=0.2)
    d = dialog_for(window, load_csv(str(comp)))
    d.ed_n.setText("0.1")
    d.ed_pc.setText("0.2")
    d.compute()
    assert d.btn_create.isEnabled()
    for key, value in d._report["diag"].items():
        assert cli.result[key] == value, key
    assert cli.result["prediction"] == d._report["prediction"]
    assert [w["code"] for w in cli.warnings] == [c for c, _ in d._report["flags"]]
    assert inversion_shape(d._report["filler"]) == FLAKE
    d.ed_pc.setText("0.21")
    assert d._report is None and not d.btn_create.isEnabled()


def test_dialog_creates_a_mixture_with_the_shape(window):
    from coating_studio.gui.dialogs.materials import MaterialManager

    comp = tab_of(*composite())
    p = window.doc.project
    p.add_material(comp)
    p.add_material(ConstantMaterial("resin", 3.0, 0.02))
    manager = MaterialManager(window.doc, window)
    d = dialog_for(window, comp)
    d.ed_n.setText("0.1")
    d.ed_pc.setText("0.2")
    d.cb_source.setCurrentIndex(d.cb_source.findData(2))
    d.cb_matrix.setCurrentText("resin")
    d.chk_mixture.setChecked(True)
    d.compute()
    d._accept()
    manager._add_inverted(d.result_filler, d.result_mixture)
    made = next(m for m in window.doc.project.materials.values()
                if isinstance(m, MixtureMaterial) and m.inclusion == d.result_filler.name)
    assert made.shape == FLAKE and made.model == "odelevskiy"
    assert not [i for i in mixture_range_issues(window.doc.project, 1e10) if i.code == "inverted_filler_model"]


def test_material_manager_edits_the_rule(window):
    from coating_studio.gui.dialogs.materials import MaterialManager

    p = window.doc.project
    for m in (HOST, FILL, MixtureMaterial("mix", "host", "fill", 0.1, "maxwell_garnett")):
        p.add_material(m)
    manager = MaterialManager(window.doc, window, select="mix")
    assert not manager.m_form.isRowVisible(manager.m_n)
    manager.m_model.setCurrentIndex(manager.m_model.findData("odelevskiy"))
    manager._on_mix_model()
    assert manager.m_form.isRowVisible(manager.m_n)
    m = window.doc.project.materials["mix"]
    assert m.shape == pytest.approx(MG_SHAPE)  # Maxwell-Garnett until the user changes the values
    assert m.eps_mu(F, window.doc.project.resolver)[0] == pytest.approx(maxwell_garnett(3 - 0.02j, 30 - 5j, 0.1))
    manager.m_n.setValue(0.1)
    manager.m_n.valueEdited.emit(0.1)
    manager.m_pc.setValue(0.2)
    manager.m_pc.valueEdited.emit(0.2)
    assert window.doc.project.materials["mix"].shape == FLAKE
    manager.m_model.setCurrentIndex(manager.m_model.findData("bruggeman"))
    manager._on_mix_model()
    assert window.doc.project.materials["mix"].shape is None
