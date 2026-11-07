---
name: coating-experiment
description: Run coating-design experiments with coating-cli - start from a user's current absorber (layers, materials, mixture fractions, thicknesses) and a reflection-loss target, then simulate, optimise and check yield until the target is met or shown infeasible. Use when the user asks to improve, optimise or "experiment with" a coating / absorber design, find a material combination or thickness, or check whether a target is achievable.
---

# Coating experiments with coating-cli

Read `docs/AGENT_PLAYBOOK.md` in this repository first and follow it. It defines the design-spec format, every
command you need, the loop (inputs → feasibility → baseline → optimise → yield → stop → report) and the stop rules.

Essentials, in case you only skim:

- Run the tool as `coating-cli …` (or `python -m coating_studio.cli …`). Each command prints one JSON object;
  check `ok` and the exit code (5 = stopped with a partial result).
- Never invent material parameters; ask the user for missing values and ranges, and say that built-in materials
  are demonstration values.
- `margin_db = worst_rl_db − goal_db`; ≤ 0 means met.
- Always pass `--journal DIR --note "why"` and finish with `coating-cli journal DIR`.
- Check yield with `tolerance --angle-grid` and report the joint yield, never a single-angle yield.
- Use the CLI for the search loop. The GUI (`coating-studio file.coat`) is only for showing a result to the user.
