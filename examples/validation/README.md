# Validation against known and measured data

These scripts check Coating Studio against analytic results, a commercial datasheet and published
measurements. Run them from the repository root after `pip install -e ".[dev]"`.

| Script | Reference | What it checks | Result |
|---|---|---|---|
| `analytic_benchmarks.py` | Textbook formulas, independent TMM | MgF₂ AR on BK7, Brewster angle, TIR, TiO₂/SiO₂ Bragg mirror, water (Debye), Salisbury screen, thin film ≡ sheet, NiZn ferrite tile, 300 random stacks against a separately written characteristic-matrix solver, R+T+ΣA=1, optimiser rediscovering the Salisbury design | 12/12 pass, agreement to ~1e-16 |
| `datasheet_laird.py` | Laird Eccosorb MF datasheet (8 grades, 1–18 GHz) | Imports the published ε, μ as CSV and recomputes the vendor's attenuation (dB/cm) and \|Z\|/Z₀ | Attenuation median 0.4 % (max 5.7 %, from rounding); \|Z\|/Z₀ median 0.003 |
| `measured_kumar2021.py` | Kumar et al. 2021, U-type hexaferrite/PVA | ε, μ digitised from Fig. 4 → metal-backed RL at t_m, compared with the **measured** short-circuit S11 in Table II, with a Monte Carlo for digitising error | Peak frequency within ~1 % for all 5 samples; −10 dB bandwidth matches measurement for 4 of 5 (U8 is the exception, see below) |
| `michielssen_benchmark.py` | Michielssen et al. 1993 absorber database (16 materials); three problems: A = 5 layers 2–8 GHz ≤ 5 mm, B = 3 layers 0.85–5.4 GHz, C = 7 layers 0.1–20 GHz ≤ 10 mm; designs from Asi & Dib 2010, Amaya & Correa 2013, Kankılıç & Karpat 2023, Zong et al. 2024, Chamaani et al. 2008 | Recomputes every published design on its paper's own frequency grid, and the designs Coating Studio's optimiser found; `--write-spec --problem A/B/C` writes each search as a `coating-cli` spec | The papers' own designs reproduce within 0.05 dB (12/12 checks); several reprints do not (see below). Coating Studio: A −25.956 dB (best reproducible published −25.884), B −21.460 (−21.454), C −18.843 (−18.709) |
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

- **Michielssen benchmark**: the five designs in Asi & Dib (2010) reproduce to 0.005–0.046 dB on the paper's
  0.5 GHz grid; the residue fits their 3-decimal thicknesses. Two later papers compare results on different
  grids: Zong et al. (2024) put the CFO value from the 0.5 GHz grid next to 0.1 GHz results. Their own (MIGRO)
  design and the BESOA design (Kankılıç & Karpat 2023) come out 0.12 and 0.19 dB worse than published on any grid,
  although their thicknesses are given to 4–5 decimals; we report them as not reproduced rather than as wrong.
  The best published design that reproduces is Asi & Dib's Table 4 CFO design (−25.884 dB). Coating Studio's
  own search found −25.956 dB at 4.999 mm (−25.953 dB on a 0.01 GHz grid).
- **Third benchmark** (7 layers, 0.1–20 GHz, ≤ 10 mm): Asi & Dib's CFO design and the MIGRO, GRO and DE designs
  reproduce within 0.05 dB; BLSA-SA (0.064 dB) and CAS (0.73 dB) do not. The DE design is printed twice with
  layers 1 and 3 swapped: Kankılıç & Karpat's 16/…/14 reproduces, Zong et al.'s 14/…/16 gives −15.5 dB (a
  transcription error). Chamaani et al.'s 9.6 mm design recomputes to −18.709 dB, better than its published
  −18.5 (apparently rounded). Coating Studio's search reached −18.843 dB at 9.603 mm, the same on a 0.01 GHz grid.
- **Restarting the optimiser**: the first 7-layer runs stalled at 5.8 mm (−17.94 dB), and one restart from a
  −18.29 dB design ended *worse* (−17.85 dB). With more than 64 material combinations the optimiser did not seed
  its search with the starting design. Fixed in the same change (`optimize.optimizer`): the best results above
  come from restarts after the fix.
- **Second benchmark** (Amaya & Correa 2013, 3 layers, 0.85–5.4 GHz): its three designs reproduce within
  0.01 dB on any grid (the paper does not state one). They use materials 3 and 4, which the 5-layer designs do
  not, so they also check those power-law exponents, which that paper itself does not print. Its Table 1 lists
  materials 9–16 as μm·fm²·10⁻³ and μm·fm·10⁻² under headings that read μ′(1 GHz)·10⁻⁷ and μ″(1 GHz)·10⁻⁷;
  the numbers agree with the database, the headings do not.
- Materials 14–16 of the database exceed the Snoek limit (`coating-cli check` warns), and the best designs all use
  them: the benchmark compares optimisers on synthetic materials; it is not a manufacturable design.
- Material 8 has ε″(1 GHz) = 6 in both reprints used; Zong et al. (2024) print 16 (a typo, which a research
  summary copied).

## Data and provenance

`reference.json` holds every number taken from the sources (tables, not digitised curves).

| Path | Content | Source |
|---|---|---|
| `data/laird/MF-*.csv` | ε′, ε″ (K′, K″), μ′, μ″ (M′, M″) at 1, 3, 8.6, 10, 18 GHz, transcribed | [Laird Eccosorb MF datasheet RFP-DS-MF 092115](https://www.laird.com/sites/default/files/2021-01/RFP-DS-MF%20092115.pdf), p. 3. Typical values, not a specification. |
| `data/kumar2021/kumar_*.csv` | ε, μ digitised from Fig. 4 at 0.25 GHz steps | S. Kumar, N. N. Ghosh, R. Chatterjee, *AIP Advances* **11**, 015311 (2021), [doi:10.1063/9.0000056](https://doi.org/10.1063/9.0000056), CC BY 4.0 |
| `data/duan2010/duan_fig3_fig4_digitised.csv` | ε, μ digitised from Figs. 3–4 | Y. Duan, G. Li, L. Liu, S. Liu, *Bull. Mater. Sci.* **33**, 633 (2010), [doi:10.1007/s12034-010-0096-7](https://doi.org/10.1007/s12034-010-0096-7); open full text at [ias.ac.in](https://www.ias.ac.in/article/fulltext/boms/033/05/0633-0636) |
| `reference.json` → `michielssen1993` | The 16-material database, the problem, and every design with its source table | Database: Michielssen et al., *IEEE Trans. MTT* **41**, 1024 (1993), [doi:10.1109/22.238519](https://doi.org/10.1109/22.238519), as reprinted in Asi & Dib, *PIER B* **26**, 101 (2010), [doi:10.2528/PIERB10090103](https://doi.org/10.2528/PIERB10090103), Table 1, and Kankılıç & Karpat, *Appl. Sci.* **13**, 10301 (2023), [doi:10.3390/app131810301](https://doi.org/10.3390/app131810301), Table 1 (identical). Designs: those papers, Zong et al., *ACES J.* **39**, 708 (2024), [doi:10.13052/2024.ACES.J.390806](https://doi.org/10.13052/2024.ACES.J.390806), and I. Amaya, R. Correa, *Revista de Ingeniería* (Univ. de los Andes) **38**, 33 (2013), ISSN 0121-4993 |
| `digitize/` | The scripts that produced the digitised CSVs | Need the figure images from the papers, which are not redistributed |

Digitising accuracy is about one pixel: ±0.006 in ε′ and ±0.002 in μ″ for Kumar, and ±0.1 in ε and
±0.03 in μ for Duan. Where a legend or another curve hides a curve, the gap is linearly interpolated.

The digitised and transcribed values are reproduced only to check the solver, with full credit to the
original authors and to Laird. Please cite the original sources when you reuse them.
