# Agent playbook: coating experiments with `coating-cli`

This is for an AI agent asked to improve an absorber design: the user describes the current coating
(layers, materials, mixture fractions, thicknesses) and a target, and you run simulations and optimisations
until the target is met or you can show it cannot be. The tool is `coating-cli` (also `python -m coating_studio.cli`).
The design rationale is in `docs/CLI_PLAN.md` (Korean); this page is all you need to run the loop.

## Ground rules

- **Never invent material parameters.** If you need a model of measured data, use `coating-cli fit` and show the
  user the residuals (`rms_eps`, `rms_mu`) before relying on it. If the task seems to need something this page
  does not describe, stop and tell the user.
- **Ask, do not guess**, for anything the user did not give: layer order, materials, fractions, thicknesses, the
  band, angles, polarisations, the RL goal, the thickness limit, manufacturable ranges, the required yield.
- Built-in materials carry **demonstration values** (`demo_values` info issue, `is_demo` in `materials`). Say so
  in every report: results are indicative until measured data replaces them.
- Every command prints **one JSON object** on stdout. Check `ok` and the exit code: 0 ok, 2 usage, 3 input/output,
  4 model, 5 stopped with a partial result (`stopped: true`). Errors carry `error.code` and `error.details`.
- RL is `20·log10|Γ|` (negative is better). **`margin_db = worst_rl_db − goal_db`**: ≤ 0 means the target is met,
  a positive value is the shortfall in dB. `max_margin_db` is the largest over the targets.
- Use one journal directory per task and pass `--journal DIR --note "why"` to `check`, `solve`, `optimize` and
  `tolerance`. The tool writes the record (inputs are snapshotted); `coating-cli journal DIR` summarises it.

## The design spec

Write the design as a JSON spec and turn it into a project with `coating-cli build spec.json -o design.coat`.
To change a design later, export it (`coating-cli spec design.coat -o spec.json`), edit, and build again.
Building or optimising onto an existing file needs `--force` (otherwise exit 3 `file_exists`, and the next step
would silently use the old file). Prefer a new file name per trial (`d1.coat`, `d2.coat`, …).

```json
{
  "spec_version": 1,
  "name": "CB absorber",
  "incident": "Air",
  "backing": "pec",
  "materials": [
    {"name": "CB mix A", "kind": "mixture", "matrix": "Epoxy", "inclusion": "Carbon black",
     "fraction": 0.20, "model": "bruggeman"}
  ],
  "layers": [{"name": "Absorber", "material": "CB mix A", "thickness_mm": 3.0}],
  "targets": [{"name": "X 0-30", "f_ghz": [8, 12], "n_f": 41, "angle_deg": [0, 30], "n_angle": 4,
               "pols": ["TE", "TM"], "goal_db": -15}],
  "variables": [
    {"layer": "Absorber", "param": "thickness", "range": [0.3, 4.0], "unit": "mm"},
    {"material": "CB mix A", "param": ["fraction"], "range": [0.05, 0.24], "unit": "frac"}
  ],
  "optimization": {"thickness_max_mm": 4.0, "w_thickness": 0}
}
```

- Layers run from the incident side to the backing. Refer to a layer by its unique name or its 1-based index.
- Units are fixed by the key suffix: `thickness_mm`, `f_ghz`, `angle_deg`, `R_ohm`, `X_ohm`, `L_nh`, `C_pf`,
  `_kg_m2`. Material dicts are the exception: they use the project-file format in SI (see below).
- A normal-incidence target is `"angle_deg": 0`. An angle range needs `"n_angle"` ≥ 2.
- Variable `param`: a layer attribute string (`"thickness"`, `"R"`, `"X"`, `"L"`, `"C"`), or a material path list
  (`["fraction"]`, `["mu_terms", 0, "delta"]`). `unit` must be the parameter's display unit as listed by
  `coating-cli info` or `materials` (`mm`, `ohm`, `nH`, `pF`, `GHz`, `S/m`, `frac`, `""`); a mixture fraction
  also accepts `"wt"`.
- Sheet layers: `{"name": "R-card", "sheet": {"model": "constant", "R_ohm": 377, "X_ohm": 0}}` or
  `{"sheet": {"model": "rlc", "R_ohm": 50, "L_nh": 2.0, "C_pf": 0.08}}` (`"C_pf": null` = no capacitor).
- Tolerance values (`tolerance.thickness`, `eps`, `mu`, `sheet`, `eps_loss`, `mu_loss`) are relative (0.05 = 5 %),
  1 σ for `"normal"`, ± half-width for `"uniform"`. `tolerance.loss_correlation` (−1…1, default 0) correlates each
  layer's real-part and loss errors (ε′ with ε″, μ′ with μ″) where a loss tolerance is set; use it only when the
  user knows the errors move together (e.g. filler content raises ε′ and ε″ together → positive).
- Omitted sections use defaults; omitted `targets` means **no target** (optimisation then refuses to run).
- Do not put fractions in material names ("CB 20%"): an optimised fraction makes the name wrong.

### Material dicts (SI, no suffixes)

| `kind` | fields |
|---|---|
| `constant` | `eps_re`, `eps_loss`, `mu_re`, `mu_loss` (ε = eps_re − j·eps_loss; loss > 0) |
| `dispersive` | `eps_inf`, `eps_loss`, `sigma` (S/m), `eps_terms`, `mu_inf`, `mu_loss`, `mu_terms`; terms are `{"type": "debye", "delta", "f0"}` or `{"type": "lorentz", "delta", "f0", "gamma"}` (Hz) |
| `power_law` | `eps_re`, `eps_a`, `eps_loss`, `eps_b`, `mu_re`, `mu_a`, `mu_loss`, `mu_b`: ε′ = eps_re/f^eps_a, ε″ = eps_loss/f^eps_b, same for μ (f in GHz, values at 1 GHz). A curve fit (Michielssen 1993 database); not causal, valid only in its fitted band |
| `mixture` | `matrix`, `inclusion` (material names), `fraction` (volume, 0–1) or `fraction_wt` (weight), `model`: `"maxwell_garnett"` or `"bruggeman"` |
| measured | `{"name", "csv": "file.csv", "density"?, "note"?}`; the path is relative to **the spec file's folder**; CSV columns `f, eps', eps'', [mu', mu'']`, first header cell sets the unit (default GHz) |

Every material except mixtures also takes `density` (kg/m³; a mixture computes it from its constituents), and all take `note`. `coating-cli materials` prints the built-ins in exactly
this format, with their parameter paths and static permeability.

## The loop

1. **Inputs.** Extract the design and target; ask for what is missing (see ground rules). Ask for the required
   yield; if the user has no answer, use a joint yield of 80 % and say so.
   - **Measured data (CSV)**: keep the sweep and targets inside the measured range (`build` checks it and clamps
     an omitted sweep). A CSV describes one sample, so its composition cannot be varied. If the user wants to vary
     the loading, offer: (a) several CSVs measured at different loadings, used as `choices` candidates;
     (b) constituent data (matrix and filler) with a mixture and `fraction_wt`; (c) otherwise, optimise the
     thickness only and report that exploring the loading needs more measurements.
2. **Feasibility.** `coating-cli bound --f-ghz LO HI --goal-db G [--mu-s M]`, then `build`, then
   `coating-cli check design.coat --journal DIR`. Fix errors. If `result.limits[].status` is `"infeasible"`
   (`rozanov_infeasible`), no design inside the allowed ranges can meet the target: propose a thinner goal, a
   larger thickness limit or a higher-permeability material, and stop. `"ok"` only means this necessary
   condition holds, not that the target is reachable.
   - With measured (CSV) materials the status is `"unknown"`: the static permeability μs lies outside the data and
     is never extrapolated. To estimate it, run `coating-cli fit data.csv --mu-debye 1` (check `rms_mu`), take
     μs = `mu_inf` + Σ `delta` of the fitted μ terms, and run `coating-cli bound … --mu-s μs`. Treat the result
     as an estimate (extrapolated), not as proof.
3. **Baseline.** `coating-cli solve design.coat --targets --summary-only --journal DIR --note "baseline"`.
   (`--touchstone out.s1p --pol TE` also writes S11 for circuit or network-analyser tools, if the user asks for it.)
4. **Optimise.** Set variables and ranges in the spec (the ranges must be what the user can manufacture; ask),
   build, then
   `coating-cli optimize design.coat -o next.coat --restarts 3 --journal DIR --note "..."`.
   Read `result.targets[].margin_db`, `result.values[].at_bound` and `result.terms.thickness_at_limit` (true when
   the total thickness sits on `thickness_max_mm`; the individual layers are then usually not at their own bounds).
   Run options (`--maxiter`, `--popsize`, `--seed`) apply to that run only; they are not saved into `next.coat`.
   Run one `optimize` per tool call, and keep `--timeout` below your tool-call time limit.
   - All margins ≤ 0 → step 5.
   - A thickness at its upper bound, or `thickness_at_limit` → propose relaxing the limit, or add a
     higher-permeability material or a layer.
   - To tell a material limit from a thickness limit, re-optimise once with a much larger thickness limit: if the
     best thickness then stops **inside** the range and the target is still missed, the materials themselves cannot
     reach it (more thickness will not help).
   - A resistive sheet (R-card) adds a variable `{"layer": "R-card", "param": "R", "range": [lo, hi], "unit": "ohm"}`;
     ask the user which sheet resistances they can buy or print. Its position in the stack is not a variable:
     build one spec per position and compare.
   - Only some bands or angles miss → add a layer (graded or Jaumann-type), insert a resistive sheet, or add
     material candidates (`choices`).
   - Keep mixture fractions below the `mixture_fraction_range` interval unless the user accepts it: the optimiser
     likes the region where the mixing model is least trustworthy (near Bruggeman percolation, ~1/3).
   - More layers giving a worse result usually means a local optimum: restart from the previous best design.
   - Size runs with `estimated_max_evals` from `info`/`check` (thousands to tens of thousands of evaluations take
     seconds). Material candidates multiply the cost; keep `--timeout` below your tool-call time limit. A run
     stopped by `--timeout` exits 5 with the best design found so far.
   - Set `w_thickness` to 0 when a thickness limit is used to meet a strict goal; otherwise the thickness term
     trades RL for thickness and stops short of the goal.
5. **Yield.** `coating-cli tolerance next.coat --corners --journal DIR` (each target's own goal is the criterion;
   `--target-db` overrides it). Report `joint_yield_fraction` and `min_corner`, never a single-angle yield.
   Corners are the ends of each target's angle range; angles in between are not sampled.
   A design optimised to exactly meet the goal usually has a low yield (about half the samples fall on the wrong
   side). If the yield matters, re-optimise with a stricter goal (for example 1–2 dB below the user's) and check
   the yield again against the user's goal with `--target-db`.
6. **Stop** when the targets and the yield requirement are met, when the trial budget is used up (20 runs unless
   the user said otherwise), after three runs without improvement on the same targets (each with `--restarts 3`),
   or when `rozanov_infeasible` appears.
7. **Report.** `coating-cli journal DIR` (best trial per fingerprint), the final spec (`coating-cli spec`), the
   `best_seed` for reproduction (`optimize … --seed <best_seed> --restarts 1` with the same run options reruns the reported design;
   `seed_used` is only the first seed of the restarts), and the remaining risks: demonstration materials, yield, corners only, mixing-model
   range, fitted models. If the target was missed, give the best margin and the trade-offs, each re-optimised:
   a goal near the best achieved, a larger thickness limit, a narrower angle range.

To show a result to the user in the GUI, open the snapshot: `coating-studio DIR/snapshots/<sha>.coat`.
