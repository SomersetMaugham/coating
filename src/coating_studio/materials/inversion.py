"""Effective filler parameters from one measured composite (no Qt).

Inverts the Maxwell-Garnett or Bruggeman rule analytically at each frequency.  The result is tied to the mixing
model and to the loading it came from: it predicts composites of that family, it is not a measured property of the
filler.  Design, numbers and the reasons for each check: docs/CLI_PLAN.md, section 13.9.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from coating_studio.materials.models import INVERTED_PREFIX, TabulatedMaterial, bruggeman, maxwell_garnett

MODELS = ("maxwell_garnett", "bruggeman")
GAIN_TOL = 1e-12  # the tolerance of checks.check_material
SCREENING_MARGIN = 1e-9
ROUNDTRIP_TOL = 1e-6
ILL_CONDITIONED = 20.0
FRACTION_STEP = 0.10  # relative change of the loading in the sensitivity check
MAX_PREDICTED_FRACTION = 0.95
WARN_RMS = 0.10  # relative error above which a prediction check is worth a warning


def mix(em, ei, phi, model):
    """The forward mixing rule."""
    return maxwell_garnett(em, ei, phi) if model == "maxwell_garnett" else bruggeman(em, ei, phi)


def invert_rule(eff, em, phi, model):
    """Filler value from one mixing rule.  Returns ``(ei, x)``, with ``x`` the screening coordinate (Re x < 1 for a
    filler the model can represent).  Each is a single ratio, so ``em + 2 eff = 0`` does not overflow on the way."""
    if not 0.0 < phi < 1.0:
        raise ValueError(f"the fraction must be between 0 and 1, got {phi!r}")
    eff, em = np.asarray(eff, dtype=complex), np.asarray(em, dtype=complex)
    with np.errstate(divide="ignore", invalid="ignore"):
        if model == "maxwell_garnett":
            s, d = phi * (eff + 2 * em), eff - em
            return em * (s + 2 * d) / (s - d), d / s
        if model == "bruggeman":
            s, d = phi * (em + 2 * eff), (1 - phi) * (em - eff)
            return eff * (s - 2 * d) / (s + d), -d / s
    raise ValueError(f"unknown mixing model {model!r}")


def _amplification(eff, em, ei, x, phi, model):
    """Relative condition number |dei/de| |e/ei|; 0 where the composite equals the matrix (nothing was measured)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        if model == "maxwell_garnett":
            d = 9 * em ** 2 / (phi * (eff + 2 * em) ** 2 * (1 - x) ** 2)
        else:
            d = (1 + 2 * x) / (1 - x) + 9 * eff * em * (1 - phi) / (phi * (em + 2 * eff) ** 2 * (1 - x) ** 2)
        k = np.abs(d) * np.abs(eff) / np.abs(ei)
    return np.where(np.abs(eff - em) <= GAIN_TOL * np.maximum(np.abs(em), 1.0), 0.0, k)


@dataclass
class Channel:
    """One of eps or mu; the masks are per frequency."""

    value: np.ndarray
    amplification: np.ndarray
    gain: np.ndarray  # loss < 0, left unclamped
    outside_model: np.ndarray  # beyond the screening limit of the model (or no finite value exists)
    branch: np.ndarray  # the forward rule does not return the data: another Bruggeman root
    clamped: np.ndarray
    roundtrip: np.ndarray  # relative, NaN where the point is outside the model


def _channel(eff, em, phi, model, clamp):
    eff, em = np.broadcast_arrays(np.asarray(eff, dtype=complex), np.asarray(em, dtype=complex))
    ei, x = invert_rule(eff, em, phi, model)
    ei = np.array(ei, dtype=complex)
    finite = np.isfinite(ei)
    outside = ~(finite & (np.nan_to_num(x.real, nan=np.inf) < 1 - SCREENING_MARGIN))
    tol = GAIN_TOL * np.maximum(np.nan_to_num(np.abs(ei)), 1.0)
    positive = finite & (ei.imag > 0)
    gain = positive & (ei.imag > tol)
    ei[positive & ~gain] = ei[positive & ~gain].real  # rounding of a lossless channel, never a negative loss in the file
    # Only a point that keeps Re > 0 may be clamped: where Re changes sign, interpolating the table crosses the
    # Froehlich pole of the mixing rule and the prediction spikes between grid points.
    clamped = (gain & (ei.real > 0) & ~outside) if clamp else np.zeros(ei.shape, dtype=bool)
    ei[clamped] = ei[clamped].real
    gain &= ~clamped
    with np.errstate(divide="ignore", invalid="ignore"):
        back = np.where(outside, np.nan + 0j, mix(em, np.where(outside, em, ei), phi, model))
        rt = np.abs(back - eff) / np.maximum(np.abs(eff), 1e-300)
    branch = ~outside & ~clamped & (rt > ROUNDTRIP_TOL)
    return Channel(ei, _amplification(eff, em, ei, x, phi, model), gain, outside, branch, clamped, rt)


@dataclass
class InversionResult:
    f: np.ndarray
    fraction: float
    model: str
    eps: Channel
    mu: Channel
    clamp_nonpassive: bool = False

    def _count(self, mask_name):
        return int(np.count_nonzero(getattr(self.eps, mask_name) | getattr(self.mu, mask_name)))

    @property
    def gain_points(self):
        return self._count("gain")

    @property
    def outside_model_points(self):
        return self._count("outside_model")

    @property
    def branch_points(self):
        return self._count("branch")

    @property
    def clamped_points(self):
        return self._count("clamped")

    @property
    def clampable_points(self):
        """Gain points that ``clamp_nonpassive`` would accept."""
        return int(np.count_nonzero((self.eps.gain & (self.eps.value.real > 0) & ~self.eps.outside_model)
                                    | (self.mu.gain & (self.mu.value.real > 0) & ~self.mu.outside_model)))

    @property
    def ok(self):
        return not (self.gain_points or self.outside_model_points or self.branch_points)

    @property
    def ill_conditioned_points(self):
        return int(np.count_nonzero((self.eps.amplification > ILL_CONDITIONED)
                                    | (self.mu.amplification > ILL_CONDITIONED)))

    @property
    def negative_real_points(self):
        def neg(c):
            return np.isfinite(c.value) & (c.value.real <= 0)
        return int(np.count_nonzero(neg(self.eps) | neg(self.mu)))

    @property
    def roundtrip_max(self):
        """Largest relative round-trip error at the points kept as computed (clamped points differ on purpose)."""
        kept = np.concatenate([self.eps.roundtrip[~self.eps.clamped], self.mu.roundtrip[~self.mu.clamped]])
        kept = kept[np.isfinite(kept)]
        return float(kept.max()) if kept.size else None

    def amplification_stats(self):
        def stats(a):
            a = a[(a > 0) & np.isfinite(a)]
            return {"median": float(np.median(a)), "max": float(a.max())} if a.size else {"median": None, "max": None}
        return {"eps": stats(self.eps.amplification), "mu": stats(self.mu.amplification)}

    def to_tabulated(self, name, density, note="", source=""):
        return TabulatedMaterial(name, self.f, self.eps.value.real, -self.eps.value.imag, self.mu.value.real,
                                 -self.mu.value.imag, source=source, density=density, note=note)


def invert_filler(f, eps_eff, mu_eff, eps_m, mu_m, phi, model, clamp_nonpassive=False) -> InversionResult:
    """Invert both channels on the grid ``f``.  Always returns; ``result.ok`` tells whether the table may be used."""
    if model not in MODELS:
        raise ValueError(f"unknown mixing model {model!r}")
    return InversionResult(np.asarray(f, dtype=float), float(phi), model,
                           _channel(eps_eff, eps_m, phi, model, clamp_nonpassive),
                           _channel(mu_eff, mu_m, phi, model, clamp_nonpassive), clamp_nonpassive)


def rms_relative(pred, ref):
    """rms |pred - ref| / max |ref|, the measure ``fitting`` reports."""
    pred, ref = np.asarray(pred, dtype=complex), np.asarray(ref, dtype=complex)
    return float(np.sqrt(np.mean(np.abs(pred - ref) ** 2)) / max(float(np.max(np.abs(ref))), 1e-12))


def prediction_fractions(phi):
    return [phi / 2, min(1.5 * phi, MAX_PREDICTED_FRACTION)]


def _predict(res, eps_m, mu_m, phi):
    return mix(eps_m, res.eps.value, phi, res.model), mix(mu_m, res.mu.value, phi, res.model)


def _worst(rows):
    return {"rms_eps": max(r[0] for r in rows), "rms_mu": max(r[1] for r in rows)}


def prediction_checks(res: InversionResult, eps_eff, mu_eff, eps_m, mu_m) -> dict:
    """How far predictions at other loadings move under a loading error, and under the other mixing model."""
    at = prediction_fractions(res.fraction)
    base = [_predict(res, eps_m, mu_m, p) for p in at]

    def changes(other):
        return [(rms_relative(a[0], b[0]), rms_relative(a[1], b[1])) for a, b in zip(other, base)]

    rows = []
    for sign in (-1, 1):
        phi = res.fraction * (1 + sign * FRACTION_STEP)
        if phi >= 1:
            continue
        moved = invert_filler(res.f, eps_eff, mu_eff, eps_m, mu_m, phi, res.model, res.clamp_nonpassive)
        if moved.outside_model_points:
            continue
        rows += changes([_predict(moved, eps_m, mu_m, p) for p in at])
    other_model = next(m for m in MODELS if m != res.model)
    other = invert_filler(res.f, eps_eff, mu_eff, eps_m, mu_m, res.fraction, other_model, res.clamp_nonpassive)
    disagreement, reason = None, None
    if other.ok:
        disagreement = _worst(changes([_predict(other, eps_m, mu_m, p) for p in at]))
    else:
        reason = f"the {other_model} rule cannot represent this composite"
    return {"at_fractions": at, "fraction_sensitivity": _worst(rows) if rows else None,
            "model_disagreement": disagreement, "model_disagreement_reason": reason}


def validation_errors(filler: TabulatedMaterial, matrix, f, eps, mu, phi, model) -> dict:
    """Predict a composite measured at another loading and compare, on the part of its grid the filler covers."""
    f = np.asarray(f, dtype=float)
    lo, hi = filler.f_range
    keep = (f >= lo * (1 - 1e-9)) & (f <= hi * (1 + 1e-9))
    if np.count_nonzero(keep) < 2:
        raise ValueError(f"fewer than two validation points lie inside the filler data {lo / 1e9:g}-{hi / 1e9:g} GHz")
    fv = f[keep]
    ei, mi = filler.eps_mu(fv, None)
    em, mm = matrix.eps_mu(fv, None)
    return {"n_points": int(fv.size), "rms_eps": rms_relative(mix(em, ei, phi, model), np.asarray(eps)[keep]),
            "rms_mu": rms_relative(mix(mm, mi, phi, model), np.asarray(mu)[keep])}


def diagnostics(res: InversionResult) -> dict:
    """The per-point counts and condition numbers of a result, for the CLI's JSON and the dialog."""
    return {"fraction": res.fraction, "model": res.model, "n_points": int(res.f.size),
            "data_range_hz": [float(res.f[0]), float(res.f[-1])], "amplification": res.amplification_stats(),
            "ill_conditioned_points": res.ill_conditioned_points, "negative_real_points": res.negative_real_points,
            "gain_points": res.gain_points, "outside_model_points": res.outside_model_points,
            "branch_points": res.branch_points, "clamped_points": res.clamped_points,
            "roundtrip_max": res.roundtrip_max}


def warning_flags(res: InversionResult, prediction: dict, validation: list) -> list:
    """``[(code, args)]`` for a usable result.  ``validation`` rows hold ``csv`` (a label) and ``rms_eps``/``rms_mu``,
    or ``error`` when that row could not be evaluated."""
    def over(values):
        return max(values) > WARN_RMS

    flags = []
    if res.ill_conditioned_points:
        flags.append(("filler_ill_conditioned", {"n": res.ill_conditioned_points, "limit": ILL_CONDITIONED}))
    if res.negative_real_points:
        flags.append(("filler_negative_real", {"n": res.negative_real_points}))
    if res.clamped_points:
        worst = max(np.nanmax(c.roundtrip[c.clamped], initial=0.0) for c in (res.eps, res.mu))
        flags.append(("nonpassive_clamped", {"n": res.clamped_points, "worst": float(worst)}))
    for key, code in (("fraction_sensitivity", "fraction_sensitive"), ("model_disagreement", "model_disagreement")):
        if prediction[key] and over(prediction[key].values()):
            flags.append((code, {"limit": WARN_RMS}))
    rows = [v for v in validation if "error" not in v]
    if not rows:
        flags.append(("no_validation", {}))
    flags += [("validation_poor", {"label": v["csv"], "limit": WARN_RMS}) for v in rows
              if over([v["rms_eps"], v["rms_mu"]])]
    return flags


def provenance_note(source, model, fraction, matrix) -> str:
    """The note of an inverted table; ``limits.inversion_provenance`` reads it back.  A ";" in a name is replaced,
    because a name like "a; model=bruggeman; fraction=0.9" would otherwise be read back as the provenance."""
    source, matrix = str(source).replace(";", ","), str(matrix).replace(";", ",")
    return " ".join(f"{INVERTED_PREFIX} {source}; model={model}; fraction={fraction:.12g}; matrix={matrix}".split())
