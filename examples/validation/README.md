# Validation against known and measured data

These scripts check Coating Studio against analytic results, a commercial datasheet and published
measurements. Run them from the repository root after `pip install -e ".[dev]"`.

| Script | Reference | What it checks | Result |
|---|---|---|---|
| `analytic_benchmarks.py` | Textbook formulas, independent TMM | MgF₂ AR on BK7, Brewster angle, TIR, TiO₂/SiO₂ Bragg mirror, water (Debye), Salisbury screen, thin film ≡ sheet, NiZn ferrite tile, 300 random stacks against a separately written characteristic-matrix solver, R+T+ΣA=1, optimiser rediscovering the Salisbury design | 12/12 pass, agreement to ~1e-16 |
| `datasheet_laird.py` | Laird Eccosorb MF datasheet (8 grades, 1–18 GHz) | Imports the published ε, μ as CSV and recomputes the vendor's attenuation (dB/cm) and \|Z\|/Z₀ | Attenuation median 0.4 % (max 5.7 %, from rounding); \|Z\|/Z₀ median 0.003 |
| `measured_kumar2021.py` | Kumar et al. 2021, U-type hexaferrite/PVA | ε, μ digitised from Fig. 4 → metal-backed RL at t_m, compared with the **measured** short-circuit S11 in Table II, with a Monte Carlo for digitising error | Peak frequency within ~1 % for all 5 samples; −10 dB bandwidth matches measurement for 4 of 5 (U8 is the exception, see below) |
| `measured_duan2010.py` | Duan et al. 2010, carbonyl iron/silicone rubber | Same idea, but the paper's ε, μ were measured on the powder, not on the sheets whose RL was measured | **Negative result**: the data set is not self-consistent, so it cannot validate a solver |

`measured_kumar2021.py --plot out.png` draws the comparison (`kumar2021_rl.png` is a copy).

## Reading the results

- **Peak position and bandwidth** are what the tool predicts reliably from real material data.
- **Depth of deep minima** (below about −30 dB) is not a useful comparison. In the Kumar Monte
  Carlo, ±3 % on ε and μ moves the minimum anywhere from −30 to −59 dB. Treat a predicted −45 dB
  as "a deep match near this frequency", not as a number.
- **Kumar U8**: the tool gives a 5.2 GHz −10 dB bandwidth (Monte Carlo 4.9–5.6 GHz). The paper
  reports 7.1 GHz calculated and 7.5 GHz measured. U8's ε, μ lie between U6 and U10, and both of
  those have ~5 GHz bandwidth in the tool, the paper and the measurement. The Table II value is
  the likely outlier, but Fig. 5(c) is a 3D plot and could not be read precisely enough to confirm.
- Kumar does not state the measured sample thickness separately or the measured peak frequency.
  The scripts assume the measurement was at t_m and show the measured minimum at the table's f_m.
- **Duan 2010**: at the nominal thicknesses, the measured peaks imply |n| ≈ 5.7 → 6.35 → 5.2 with
  rising frequency. That is non-monotonic, which a carbonyl-iron composite should not be. Fitting
  ε, μ to each 4 mm sheet predicts the 2 mm peak ~40 % too high. This shows why paired ε/μ and RL
  data from the **same** specimen is needed.

## Data and provenance

`reference.json` holds every number taken from the sources (tables, not digitised curves).

| Path | Content | Source |
|---|---|---|
| `data/laird/MF-*.csv` | ε′, ε″ (K′, K″), μ′, μ″ (M′, M″) at 1, 3, 8.6, 10, 18 GHz, transcribed | [Laird Eccosorb MF datasheet RFP-DS-MF 092115](https://www.laird.com/sites/default/files/2021-01/RFP-DS-MF%20092115.pdf), p. 3. Typical values, not a specification. |
| `data/kumar2021/kumar_*.csv` | ε, μ digitised from Fig. 4 at 0.25 GHz steps | S. Kumar, N. N. Ghosh, R. Chatterjee, *AIP Advances* **11**, 015311 (2021), [doi:10.1063/9.0000056](https://doi.org/10.1063/9.0000056), CC BY 4.0 |
| `data/duan2010/duan_fig3_fig4_digitised.csv` | ε, μ digitised from Figs. 3–4 | Y. Duan, G. Li, L. Liu, S. Liu, *Bull. Mater. Sci.* **33**, 633 (2010), [doi:10.1007/s12034-010-0096-7](https://doi.org/10.1007/s12034-010-0096-7) |
| `digitize/` | The scripts that produced the digitised CSVs | Need the figure images from the papers, which are not redistributed |

Digitising accuracy is about one pixel: ±0.006 in ε′ and ±0.002 in μ″ for Kumar, and ±0.1 in ε and
±0.03 in μ for Duan. Where a legend or another curve hides a curve, the gap is linearly interpolated.
