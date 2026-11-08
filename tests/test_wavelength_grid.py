"""Sweep points evenly spaced in vacuum wavelength (SweepSettings.uniform_wavelength, schema 7)."""
import io
import json

import numpy as np
import pytest

from coating_studio.cli import main
from coating_studio.core.constants import C0
from coating_studio.examples import EXAMPLES
from coating_studio.project import SCHEMA_VERSION, Project, SweepSettings, wavelength_grid
from coating_studio.tolerance import tolerance_frequencies


def _optical(n=81):
    return SweepSettings(f_min=C0 / 800e-9, f_max=C0 / 400e-9, n_f=n, uniform_wavelength=True)


def test_grid_is_even_in_wavelength_with_exact_ends():
    sw = _optical()
    f = sw.freq_grid()
    assert f[0] == sw.f_min and f[-1] == sw.f_max and np.all(np.diff(f) > 0)  # ascending, exact ends
    wl = C0 / f
    assert np.allclose(np.diff(wl), -5e-9, rtol=1e-9, atol=0)  # 800, 795, ... 400 nm
    assert np.allclose(wl[1:-1] * 1e9, np.arange(795, 400, -5), rtol=1e-12)
    assert wavelength_grid(1e9, 2e9, 1).tolist() == [1e9] and len(wavelength_grid(1e9, 2e9, 2)) == 2
    assert np.all(wavelength_grid(5e9, 5e9, 3) == 5e9)
    with pytest.raises(ValueError):
        wavelength_grid(0.0, 1e9, 5)


def test_existing_grids_are_unchanged_and_log_takes_precedence():
    sw = SweepSettings()
    assert np.array_equal(sw.freq_grid(), np.linspace(sw.f_min, sw.f_max, sw.n_f))
    sw.log_f = True
    assert np.array_equal(sw.freq_grid(), np.geomspace(sw.f_min, sw.f_max, sw.n_f))
    sw.uniform_wavelength = True  # log wins: a log grid is the same in wavelength and frequency
    assert np.array_equal(sw.freq_grid(), np.geomspace(sw.f_min, sw.f_max, sw.n_f))
    assert not sw.wavelength_spaced()
    assert SweepSettings().key() != _optical(SweepSettings().n_f).key()  # comparison curves re-solve


def test_saved_with_schema_7_and_old_files_read_frequency_spacing():
    p = EXAMPLES["dallenbach"][1]()
    p.sweep.uniform_wavelength = True
    d = json.loads(json.dumps(p.to_dict()))
    assert d["schema"] == SCHEMA_VERSION >= 7  # older apps would solve other points
    assert Project.from_dict(d).sweep.uniform_wavelength
    d["sweep"].pop("uniform_wavelength")
    d["schema"] = 6
    assert not Project.from_dict(d).sweep.uniform_wavelength
    d["sweep"].update(uniform_wavelength=True, log_f=True)  # hand-edited: both on means log
    q = Project.from_dict(d)
    assert q.sweep.log_f and not q.sweep.uniform_wavelength


def test_followers_use_the_sweep_grid():
    p = EXAMPLES["dallenbach"][1]()
    p.sweep = SweepSettings(f_min=2e9, f_max=18e9, n_f=401, uniform_wavelength=True)
    f = tolerance_frequencies(p)
    assert np.array_equal(f, p.sweep.freq_grid(301))  # the tolerance grid, capped at 301 points
    assert np.allclose(np.diff(C0 / f), np.diff(C0 / f)[0])


def _cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = main([str(a) for a in argv], stdout=out, stderr=err)
    text = out.getvalue()
    return code, (json.loads(text) if text.lstrip().startswith("{") else None)


def test_cli_spec_info_and_solve_options(tmp_path):
    from coating_studio.cli.output import CliError
    from coating_studio.cli.spec import project_to_spec, spec_to_project

    p = EXAMPLES["dallenbach"][1]()
    assert "uniform_wavelength" not in project_to_spec(p)["sweep"]
    p.sweep.uniform_wavelength = True
    spec = project_to_spec(p)
    assert spec["sweep"]["uniform_wavelength"] is True and spec_to_project(spec)[0].sweep.uniform_wavelength
    spec["sweep"]["uniform_wavelength"] = "yes"
    with pytest.raises(CliError):
        spec_to_project(spec)
    path = tmp_path / "w.coat"
    p.save(path)
    code, env = _cli("info", path)
    assert code == 0 and env["result"]["sweep"]["uniform_wavelength"] is True
    code, env = _cli("solve", path, "--n-f", "21")
    assert np.allclose(env["result"]["data"]["f_hz"], wavelength_grid(p.sweep.f_min, p.sweep.f_max, 21))
    code, env = _cli("solve", path, "--n-f", "21", "--linear-f")  # clears the wavelength spacing for this run
    assert np.allclose(env["result"]["data"]["f_hz"], np.linspace(p.sweep.f_min, p.sweep.f_max, 21))
    q = EXAMPLES["ferrite"][1]()  # a log-spaced file
    q.save(tmp_path / "f.coat")
    code, env = _cli("solve", tmp_path / "f.coat", "--n-f", "11", "--linear-wavelength")  # replaces log
    assert np.allclose(env["result"]["data"]["f_hz"], wavelength_grid(q.sweep.f_min, q.sweep.f_max, 11))
    code, _env = _cli("solve", path, "--log-f", "--linear-wavelength")
    assert code == 2  # one spacing at a time
