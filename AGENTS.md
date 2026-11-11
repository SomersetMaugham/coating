# AGENTS.md

Shared rules for every coding agent working in this repository (Claude Code, Antigravity/agy, etc.).

Coating Studio: a PySide6 desktop app that simulates and optimises planar multilayer coatings.
v1 targets microwave/radar absorbers (GHz). The engine is meant to stay general enough for later
optical modes (radiative cooling, AR). The design spec (in Korean) is `docs/PLAN.md`. Why later
features were designed the way they are (review findings, compatibility decisions, validation numbers,
deferred work) is recorded in `docs/DEVELOPMENT_HISTORY.md` (Korean); read it before changing those areas.

## Commands

```bash
python -m pip install -e ".[dev]"          # dev install (Python >= 3.10)
python -m pytest -n auto                    # all tests in parallel (pytest-xdist; about 20 s instead of 4 min)
python -m pytest                            # all tests, one process (testpaths=tests, -q)
python -m pytest tests/test_solver.py::test_name -v   # single test
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_gui_smoke.py   # GUI smoke, headless
coating-studio [file.coat]                  # run app (or: python -m coating_studio)
coating-cli <command> …                     # Qt-free CLI, JSON on stdout (or: python -m coating_studio.cli)
```

No linter or formatter is configured. CI (`.github/workflows/ci.yml`) runs `pytest -n auto -v` on
ubuntu/windows/macos × Python 3.10/3.13 with `QT_QPA_PLATFORM=offscreen`, but **only when started by hand**
(Actions → CI → Run workflow): the repository is private and automatic runs used up the Actions minutes.
Do not start it, or push changes that re-enable automatic runs, unless the user asks. Before a merge, run the
suite locally on both supported Python versions instead (conda environments `coat-py310` and `coat-py313`,
created with `conda create -n coat-py310 python=3.10` and `pip install -e ".[dev]"`):

```bash
scripts/local_test.sh   # both versions at once, in parallel workers; exit 0 only if both pass with no skipped test
```

Windows and Linux run on the Windows machine next to the Mac (native Windows and its WSL distro, Python 3.10
and 3.13 each), started from the Mac over a hardened ssh setup described in `docs/WINDOWS_WSL_TESTING.md`:

```bash
scripts/remote_test.sh [REF]   # exit 0 only if all four environments pass with no skipped test
```

Its sshd starts with Windows (the user's choice); if the host cannot be reached, ask the user whether the machine
is on rather than retrying. Before a merge, run it when the Windows machine is available; when it is not, say in
the PR that only macOS was checked. Do not weaken the setup's security settings (key-only login, firewall limited to the Mac's IP). On this Mac (macOS 27),
the pip SciPy wheel for Python 3.10 fails to load (`__thread_bss` zero-fill section error), so `coat-py310` uses
SciPy from conda-forge (`conda install -n coat-py310 -c conda-forge "scipy<1.16"`). The version comes from
`src/coating_studio/__init__.py` (hatch).

## Coating experiments for agents

To improve a design for a user (current composition + target → simulate and optimise until met or shown
infeasible), use `coating-cli` and follow `docs/AGENT_PLAYBOOK.md`: design specs (`build`/`spec`), the experiment
journal, the Rozanov feasibility check, yield over each target's angle grid and the stop rules. Never invent material
parameters. Use the CLI, not the GUI, for the search; the design rationale is in `docs/CLI_PLAN.md`.

## Architecture

Layers are kept strictly separate. Nothing under `core/`, `materials/`, `optimize/`, `cli/`, `project.py`,
`tolerance.py`, `limits.py`, `comparison.py`, `diagnostics.py`, `fss.py`, `touchstone.py`, `report.py`, `spectral.py`, `lengths.py` or `mplfonts.py` may import Qt (or matplotlib, for `cli/`; a test checks this). Only `gui/` uses PySide6. `i18n.detect_system_language` is the one
exception, and it falls back if Qt is missing.

- **`core/`**: the physics engine. `solve(structure, materials, f, theta_deg)` returns a
  `SolveResult` with `.pol["TE"|"TM"]`, vectorised over frequency × angle via NumPy broadcasting.
  It uses impedance recursion expressed in reflection coefficients from the backing outward, so only
  decaying `exp(-2j·kz·d)` factors appear. Per-layer absorption comes from a forward pass plus a
  Poynting-flux difference. `csqrt.kz_sqrt` enforces Im(kz) ≤ 0 and is the branch-cut fix. Keep it
  when touching the solver. `materials` is any mapping name→Material. Everything is SI internally,
  and `core/units.py` converts to display units (GHz, mm, °, Ω/sq).
- **`materials/`**: the `Material` subclasses are Constant, Dispersive (Debye/Lorentz/σ), Tabulated
  (CSV), Mixture (MG/Bruggeman/Odelevskiy, the last needing a shape factor and percolation threshold) and PowerLaw (Michielssen-style ε′(1 GHz)/fᵃ fits; not causal, so its static μ is
  unknown). Uniaxial references two isotropic materials (in-plane, normal); `eps_mu` returns the in-plane values,
  `eps_mu_normal` the z components (None for isotropic materials), and only the solver uses the latter. `eps_mu(f, resolver)` takes a resolver because mixtures
  reference other materials by **name**. Cycles raise `MaterialCycleError`. Tabulated data raises
  `OutOfRangeError` outside its measured range and never extrapolates. Each material exposes
  `params()`/`get(key)`/`set(key)` so the optimiser can address its numbers. `inversion.py` turns one measured composite into effective filler values for a mixture (`coating-cli invert-filler` and `gui/dialogs/invert_filler.py`, which share its checks; docs/CLI_PLAN.md 13.9); `shape_fit.py` fits the Odelevskiy ratio N/pc from several loadings (`coating-cli fit-shape`, 13.11: only the ratio is determined, never N and pc separately); `fitting.py` fits CSV
  data to dispersion models. `checks.py` returns issue objects that carry `code` + `args`, and
  `i18n.issue_text` renders them.
- **`project.py`**: `Project` holds materials, the `Structure` and the sweep/optimisation/tolerance
  settings. It is saved as `.coat` JSON with `SCHEMA_VERSION`. Optimisable parameters are addressed
  by **path tuples**: `('layer', uid, attr)` or `('material', name, *key)`, through
  `get_param`/`set_param`/`available_params`. `rename_material` has to rewrite references in
  mixtures, layers, variables and choices.
- **`optimize/optimizer.py`**: SciPy differential evolution, with optional L-BFGS-B polish on a
  LogSumExp-smoothed worst RL. It reports the true worst value. If there are at most 64
  discrete-material combinations it enumerates them all. Otherwise it treats them as integer
  variables ordered by impedance. A `progress` callback returns True to stop.
- **`tolerance.py`**: Monte Carlo perturbation that gives percentile bands and yield. `yield_intervals` and
  `tolerance_frequencies` define the yield band and grid shared by the GUI and the CLI. `MaterialSampler` varies
  material parameters (`ToleranceSettings.material_params`) after all layer draws; keep that order, since files
  without entries must give the same samples bit for bit.
- **`limits.py`**: Rozanov thickness bound (PEC backing, normal incidence), analytic static permeability, the
  mixing-model validity warning and measured-data ranges.
- **`comparison.py`**: comparison curves (pinned design snapshots, measured CSV/.s1p curves); saved in the `.coat`.
- **`diagnostics.py`**: the material / mixture / Rozanov checks shown in the GUI's diagnostics panel and the report.
- **`touchstone.py`**: `.s1p` export of S11 (reference R = the incident medium's modal wave impedance) and import.
- **`report.py`**: the one-file HTML design report (matplotlib Agg; the CLI does not import it). With
  `print_layout=...` it produces the print variant that `gui/report_pdf.py` lays out with Qt into an A4 PDF (the page
  drawing and the measured image scale are explained there).
- **`spectral.py`**: the spectral axis in the project's display unit (`SweepSettings.spectral_unit`: GHz, THz, vacuum
  wavelength µm/nm, wavenumber cm⁻¹; conversions in `core/units.py`). Plots, texts and exports of the GUI and the report
  go through it; `gui/spectral.py` adds the input boxes. Its `param_*` helpers show a dispersion term's f0 in this unit
  (λ₀, ν̃₀) and gamma as a damping rate (THz for wavelengths); the CLI and `ParamInfo.unit` keep "GHz". Display only: the engine, files and CLI numbers stay in Hz/GHz.
- **`lengths.py`**: layer thicknesses in the project's display unit (`SweepSettings.length_unit`: mm, µm, nm), chosen
  independently of the spectral unit. Optimiser parameters keep the unit "mm" (the CLI contract); the GUI maps it with
  `spectral.param_display_unit` (which hands lengths to `lengths`). `gui/spectral.py`'s `LengthInputs` edits thicknesses without float drift.
- **`cli/`**: `coating-cli`. `commands.py` holds one plain function per command (result dict or `CliError`);
  `output.py` the JSON envelope, value sanitising and the exception → error-code table; `progress.py`
  cancellation (one stop event for Ctrl-C/SIGTERM/`--timeout`; call `optimize` with `throttle_s=0`);
  `spec.py` the design spec ↔ Project conversion; `journal.py` the experiment journal. Output keys are a
  contract (docs/CLI_PLAN.md, appendix B) and tests compare CLI numbers with direct engine calls exactly.

### GUI (`gui/`)

- **`Document`** (`gui/document.py`) wraps the `Project` and owns the `QUndoStack`. Undo is
  **snapshot-based**: `doc.edit(text, mutator)` takes `Project.model_state()` before and after the
  mutator, pushes the change only if the state changed, and rolls back if the mutator raises. Only
  the materials, layer stack, opt variables/choices and per-layer tolerances (`model_state`) are
  undoable. Use `doc.edit_settings(mutator)` for settings: they mark the file dirty but are not
  undoable. If a new field must be undoable, add it to both `model_state` and `restore_model_state`.
- `Document.changed(str)` triggers `MainWindow`'s 60 ms debounced `recompute()`, which re-solves the
  freq, angle and map grids and marks the views dirty (`gui/plots/views.py` on `plots/base.py`).
- Long jobs run in `gui/workers.py` (`OptimizationWorker`, `ToleranceWorker`) on a QThread through
  `start_worker`. Workers operate on `project.copy()`, and the caller must keep a Python reference
  until the thread finishes. Do not add `deleteLater` on the worker, because that double-frees it.

## Conventions and gotchas

- Physics sign conventions: e^{+jωt}; ε = ε′ − jε″ (loss > 0); RL = 20·log₁₀|Γ| (negative is
  better) internally. The display sign is a preference. The top row of the layer stack faces the
  incident wave. The Debye term is Δ/(1 + j f/f₀), the Lorentz term is Δ·f₀²/(f₀² − f² + j f γ) and the
  Havriliak-Negami term is Δ/(1 + (j f/f₀)^α)^β with 0 < α, β ≤ 1 (principal powers; α = β = 1 is Debye).
- **i18n**: UI strings are English source text wrapped in `tr("...", **kwargs)` (`i18n.py`).
  Korean lives in the `KO` dict in `i18n_ko.py`. `tests/test_i18n.py` AST-scans every literal
  `tr()` call and fails if a translation is missing or its `{placeholders}` don't match. When you add
  or change any `tr()` string, add the matching `KO` entry. Strings translated indirectly (not as
  literals) go in that test's `INDIRECT` list. Language changes apply after a restart.
- The built-in material values are demo values, not datasheet values.
- The solver tests compare against analytic results (Salisbury Γ=0, Fresnel/Brewster, Dallenbach,
  R+T+ΣA=1, stability of thick lossy layers). Solver changes must keep them passing exactly rather
  than by loosening tolerances.

## Hard rules for agents

- The gate is `python -m pytest`, run with `QT_QPA_PLATFORM=offscreen` when there is no display. Run it
  in the real environment. Do not edit installed packages, stub out dependencies (numpy, scipy,
  matplotlib, PySide6) or skip tests to get it passing.
- Do not loosen numerical tolerances in `tests/test_solver.py` to make a change pass.
- Keep the Qt boundary: no PySide6 imports outside `gui/` (except the guarded one in `i18n.py`).
- Every new or changed `tr()` string needs a `KO` entry in `i18n_ko.py` with the same placeholders.
- Bump `SCHEMA_VERSION` in `project.py` and keep old `.coat` files loadable when the saved JSON
  format changes.
