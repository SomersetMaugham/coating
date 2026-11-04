# Coating Studio

**English** | [한국어](README.ko.md)

Coating Studio is a cross-platform desktop application (Windows, macOS, Linux) for simulating and
optimising planar multilayer coatings. Version 1 focuses on **microwave and radar absorbers**
(GHz range); the physics engine is general so optical coatings (radiative cooling, anti-reflection)
can be added later without rewriting it.

![Main window](docs/images/main_en.png)

## Features

- **Physics engine.** The solver uses transmission-line (impedance) recursion for planar stacks.
  - Oblique incidence, TE and TM.
  - A branch-safe longitudinal wavenumber, so thick or very lossy layers never overflow.
  - Per-layer absorption from the Poynting flux, with R + T + ΣA = 1 checked in the tests.
- **Layers.**
  - Slabs of any material.
  - Zero-thickness **resistive sheets** with Zs = R + jX in Ω/sq.
  - A **metal (PEC)** or **semi-infinite** backing.
- **Materials.**
  - Constant complex ε and μ.
  - Multi-term **Debye / Lorentz** dispersion, including Snoek-type ferrite relaxation and conductivity σ.
  - **Measured CSV** data.
  - **Maxwell-Garnett / Bruggeman** effective-medium mixtures.
- **Material checks.**
  - **CSV → dispersion-model fitting**, which gives a causal model you can extrapolate.
  - Passivity warnings.
  - Snoek-limit realism warnings.
- **Results.** The result views are:
  - Reflection loss / |Γ|² / absorptance / transmittance vs frequency and vs angle.
  - A frequency × angle map.
  - A Smith chart.
  - A per-layer absorption breakdown.
  - Material ε(f), μ(f) curves.
- **Optimisation.**
  - Differential evolution with an optional L-BFGS-B polish.
  - Weighted, normalised objective terms: worst-case RL, mean reflectance, thickness and areal mass, plus an optional thickness limit.
  - Any numeric parameter can be a variable, including dispersion parameters and the volume fraction of a mixture.
  - Each layer's material can be **chosen from a list of candidates**. Small candidate sets are searched exhaustively.
- **Tolerance analysis.**
  - Monte-Carlo perturbation of thickness, ε, μ and sheet impedance, set globally or per layer.
  - Shows a percentile band and the manufacturing yield.
- **Interface.**
  - Undo/redo for edits to the layer stack and materials.
  - `.coat` project files (JSON).
  - Export figures as PNG/SVG/PDF and data as CSV.
  - Light and dark themes, English/Korean UI, and a choice of reflection-loss sign convention.

![Frequency × angle map](docs/images/map_en.png)

## Install and run

You need Python 3.10 or newer.

```bash
git clone https://github.com/SomersetMaugham/coating.git
```

```bash
cd coating
```

```bash
python -m pip install .
```

```bash
coating-studio
```

You can also start it with `python -m coating_studio` or open a project directly: `coating-studio design.coat`.

On **Linux**, Qt needs a few system libraries. On Debian/Ubuntu:

```bash
sudo apt-get install libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0 fonts-noto-cjk
```

Korean text in plots uses Malgun Gothic (Windows), Apple SD Gothic Neo (macOS) or Noto Sans CJK KR /
NanumGothic (Linux) when they are installed.

### Using the engine without the GUI

```python
import numpy as np
from coating_studio.examples import salisbury
from coating_studio.core import solve

p = salisbury(10e9)
res = solve(p.structure, p.materials, np.linspace(8e9, 12e9, 5), theta_deg=[0, 30])
print(10 * np.log10(res.pol["TE"].R))   # reflection loss [dB], shape (5, 2)
```

## Conventions

| Item | Convention |
|---|---|
| Time dependence | e^{+jωt}; ε = ε′ − jε″, μ = μ′ − jμ″ (ε″, μ″ > 0 are lossy) |
| Reflection loss | RL = 20·log₁₀\|Γ\| (negative; −10 dB ≈ 90 % absorbed). The display sign can be switched in Preferences. |
| Γ | Reflection coefficient of the tangential electric field |
| Layer order | The top row of the layer stack faces the incident wave |
| Units (UI) | GHz, mm, degrees, Ω/sq, S/m, g/cm³ (the engine works in SI) |
| Debye term | Δ / (1 + j f/f₀) |
| Lorentz term | Δ·f₀² / (f₀² − f² + j f γ) |

Measured CSV files contain `f, ε′, ε″[, μ′, μ″]`. The frequency unit is read from the header and
defaults to GHz. Data is linearly interpolated, and evaluating outside the measured range is an
error, so fit a dispersion model if you need to extrapolate. A synthetic example is in
[`examples/synthetic_magnetic_composite.csv`](examples/synthetic_magnetic_composite.csv).

The built-in materials use **representative, textbook-order values for demonstration**. They are
not datasheet values; use measured data for real designs.

## Development

```bash
python -m pip install -e ".[dev]"
```

```bash
python -m pytest
```

The tests check the engine against analytic results: a Salisbury screen, Fresnel reflection and the
Brewster angle, the Dallenbach input impedance, energy conservation, total internal reflection, and
numerical stability with thick, very lossy layers. They also cover mixing-rule limits, fitting, the
optimiser and tolerance analysis, translation coverage, and offscreen GUI smoke tests. CI runs them
on Windows, macOS and Linux.

The implementation plan is in [docs/PLAN.md](docs/PLAN.md).

## License

MIT, see [LICENSE](LICENSE).
