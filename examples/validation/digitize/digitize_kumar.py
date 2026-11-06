"""How the CSVs in ../data were produced (kept for reproducibility; not needed to run the checks).

Source: Kumar et al., AIP Adv. 11, 015311 (2021), Fig. 4. The paper PDF is not redistributed here. To re-run, download the PDF,
extract the embedded figure images with PyMuPDF and run this script next to them:

    import pymupdf
    doc = pymupdf.open("paper.pdf")
    for p, page in enumerate(doc):
        for i, im in enumerate(page.get_images(full=True)):
            pymupdf.Pixmap(doc, im[0]).save(f"img_p{p+1}_{i}.png")

Expected image: img_p5_1.png (page 5, 2nd embedded image). Requires numpy and Pillow. Axis calibration uses the pixel rows of the
tick labels / dashed reference lines, which are hard-coded below for that image.
Digitise Kumar et al. 2021 Fig. 4(a,b,d,e) by colour: U4 black, U6 red, U8 blue, U10 green, UMix purple."""
import numpy as np
from PIL import Image

a = np.array(Image.open("img_p5_1.png").convert("RGB")).astype(int)
R, G, B = a[..., 0], a[..., 1], a[..., 2]
masks = {
    "U4": (R < 90) & (G < 90) & (B < 90),
    "U6": (R > 180) & (G < 90) & (B < 90),
    "U8": (R < 90) & (G < 110) & (B > 180),
    "U10": (R < 90) & (G > 90) & (B < 90),
    "UMix": (R > 90) & (R < 190) & (G < 80) & (B > 90) & (B < 200),
}
# panel: rows, cols, (label row, value) pairs for linear calibration
panels = {
    "eps1": ((12, 249), (130, 563), (39, 8.7), (236, 7.5)),
    "eps2": ((263, 500), (130, 563), (269, 1.6), (486.5, 1.2)),
    "mu1":  ((12, 249), (719, 1151), (34, 1.4), (196, 1.0)),
    "mu2":  ((263, 500), (719, 1151), (319, 0.5), (467, 0.3)),
}
X = {"eps": (116.5, 573.25), "mu": (705.0, 1162.25)}
legend = (10, 251, 711, 850)  # legend block in panel (d): rows, rows, cols, cols
grid = np.arange(2.0, 18.01, 0.25)
data = {s: {} for s in masks}
for pname, ((r0, r1), (c0, c1), (ra, va), (rb, vb)) in panels.items():
    xa, xb = X["eps" if pname.startswith("eps") else "mu"]
    for s, m in masks.items():
        mm = m.copy()
        if pname == "mu1":
            mm[legend[0]:legend[1], legend[2]:legend[3]] = False
        pts = []
        for col in range(c0, c1):
            rows = np.nonzero(mm[r0:r1, col])[0]
            if len(rows) >= 2:
                row = np.median(rows) + r0
                pts.append((2 + (col - xa) * 16 / (xb - xa), va + (row - ra) * (vb - va) / (rb - ra)))
        pts = np.array(pts)
        vals = []
        for g in grid:
            sel = np.abs(pts[:, 0] - g) <= 0.3
            vals.append(np.median(pts[sel, 1]) if sel.any() else np.nan)
        vals = np.array(vals)
        ok = ~np.isnan(vals)
        data[s][pname] = np.interp(grid, grid[ok], vals[ok])  # fill hidden points
        data[s][pname + "_cov"] = ok.mean()
for s, d in data.items():
    with open(f"kumar_{s}.csv", "w") as fh:
        fh.write(f"# Kumar et al., AIP Adv. 11, 015311 (2021), Fig. 4, sample {s}, digitised by colour\n")
        fh.write("f [GHz], eps', eps'', mu', mu''\n")
        for i, g in enumerate(grid):
            fh.write(f"{g:.2f},{d['eps1'][i]:.4f},{d['eps2'][i]:.4f},{d['mu1'][i]:.4f},{d['mu2'][i]:.4f}\n")
    cov = " ".join(f"{k}:{d[k+'_cov']*100:.0f}%" for k in ("eps1", "eps2", "mu1", "mu2"))
    pk = grid[np.argmax(d["mu2"])]
    print(f"{s:5} coverage {cov} | mu'' peak {d['mu2'].max():.3f} @ {pk:.2f} GHz | "
          f"@10 GHz eps={d['eps1'][32]:.2f}-j{d['eps2'][32]:.2f} mu={d['mu1'][32]:.2f}-j{d['mu2'][32]:.2f}")
