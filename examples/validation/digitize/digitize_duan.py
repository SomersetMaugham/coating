"""How the CSVs in ../data were produced (kept for reproducibility; not needed to run the checks).

Source: Duan et al., Bull. Mater. Sci. 33, 633 (2010), Figs. 3 and 4. The paper PDF is not redistributed here. To re-run, download the PDF,
extract the embedded figure images with PyMuPDF and run this script next to them:

    import pymupdf
    doc = pymupdf.open("paper.pdf")
    for p, page in enumerate(doc):
        for i, im in enumerate(page.get_images(full=True)):
            pymupdf.Pixmap(doc, im[0]).save(f"img_p{p+1}_{i}.png")

Expected image: img_p3_0.png / img_p3_1.png (page 3, 1st and 2nd embedded images). Requires numpy and Pillow. Axis calibration uses the pixel rows of the
tick labels / dashed reference lines, which are hard-coded below for that image.
Digitise Duan 2010 Fig. 3 (eps) and Fig. 4 (mu) by per-column tracing of marker/line pixels."""
import numpy as np
from PIL import Image

def trace(fn, x0px, x1px, ybot_px, ytop_px, ybot, ytop, bands, skip_rows, legend_box):
    a = np.array(Image.open(fn).convert("L")).astype(int)
    dark = a < 140
    for r in skip_rows:
        dark[r - 1:r + 2, :] = False          # dashed reference lines
    c0, c1, r0, r1 = legend_box
    dark[r0:r1, c0:c1] = False               # legend
    to_y = lambda row: ybot + (ybot_px - row) * (ytop - ybot) / (ybot_px - ytop_px)
    to_x = lambda col: 2 + (col - x0px) * 16 / (x1px - x0px)
    out = {k: [] for k in bands}
    for col in range(x0px + 3, x1px - 2):
        rows = np.nonzero(dark[ytop_px + 3:ybot_px - 2, col])[0] + ytop_px + 3
        for k, (lo, hi) in bands.items():
            vals = [to_y(r) for r in rows if lo <= to_y(r) <= hi]
            if vals:
                out[k].append((to_x(col), float(np.median(vals))))
    return {k: np.array(v) for k, v in out.items()}

def resample(xy, grid, win=0.35):
    return np.array([np.median(xy[np.abs(xy[:, 0] - g) <= win, 1]) for g in grid])

grid = np.arange(2.0, 18.01, 0.25)
e = trace("img_p3_0.png", 60, 489, 332, 12, 8, 40,
          {"eps1": (24.5, 40), "eps2": (8, 19.5)}, [92, 172, 253], (330, 430, 165, 255))
# mu: the two curves are close; split each column at the gap between the upper and lower cluster
a = np.array(Image.open("img_p3_1.png").convert("L")).astype(int)
dark = a < 140
for r in (259, 134):
    dark[r - 1:r + 2, :] = False
dark[150:250, 320:430] = False
to_y = lambda row: (321 - row) * 10 / (321 - 9)
to_x = lambda col: 2 + (col - 71) * 16 / (490 - 71)
mu1, mu2 = [], []
for col in range(74, 488):
    rows = np.nonzero(dark[12:319, col])[0] + 12
    if len(rows) < 2:
        continue
    gaps = np.diff(rows)
    k = int(np.argmax(gaps))
    if gaps[k] < 4:
        continue
    up, lo = rows[:k + 1], rows[k + 1:]
    mu1.append((to_x(col), to_y(np.median(up))))
    mu2.append((to_x(col), to_y(np.median(lo))))
mu1, mu2 = np.array(mu1), np.array(mu2)
E1, E2, M1, M2 = (resample(x, grid) for x in (e["eps1"], e["eps2"], mu1, mu2))
with open("duan_fig3_fig4_digitised.csv", "w") as fh:
    fh.write("# Duan et al., Bull. Mater. Sci. 33 (2010) 633, Figs. 3-4, digitised (carbonyl iron, coaxial method)\n")
    fh.write("f [GHz], eps', eps'', mu', mu''\n")
    for row in zip(grid, E1, E2, M1, M2):
        fh.write(",".join(f"{v:.4g}" for v in row) + "\n")
for g in (2, 3, 4, 6, 8, 10, 12, 14, 16, 18):
    i = int(round((g - 2) / 0.25))
    print(f"{g:4.0f} GHz  eps = {E1[i]:5.2f} - j{E2[i]:5.2f}   mu = {M1[i]:4.2f} - j{M2[i]:4.2f}")
