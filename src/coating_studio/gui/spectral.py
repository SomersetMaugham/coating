"""Spin boxes that edit frequencies in the project's spectral unit; the rest of the spectral helpers live in the
Qt-free ``coating_studio.spectral`` and are re-exported here for the GUI."""

from __future__ import annotations

from coating_studio.core.units import SPECTRAL_LABEL, from_spectral, spectral_reversed, to_spectral
from coating_studio.spectral import (  # noqa: F401 (re-exported)
    INPUT_RANGE, ascending, axis_label, csv_header, cursor_text, fmt_point, fmt_range, fmt_value, set_xlim, span,
    symbol, unit_label, unit_of, x_values,
)


class SpectralInputs:
    """Spin boxes that edit frequencies [Hz] in the project's spectral unit.

    One box edits one frequency; two boxes are a (start, end) pair for (f_min, f_max).  For a wavelength unit the
    start box (short wavelength) holds f_max and the end box f_min.  ``show`` remembers the Hz value behind every
    box, and ``values`` converts only the boxes whose number changed, so a commit triggered by another control (or
    a box the user did not touch) writes back the stored Hz unchanged instead of a float round trip."""

    def __init__(self, *spins):
        self.spins = spins
        self.unit = None
        self._shown = []

    def _order(self):
        """Model index shown in each box."""
        if len(self.spins) == 2 and spectral_reversed(self.unit):
            return [1, 0]
        return list(range(len(self.spins)))

    def show(self, unit, *f_hz):
        self.unit = unit
        self._shown = []
        order = self._order()
        for spin, i in zip(self.spins, order):
            spin.setSuffix(f" {SPECTRAL_LABEL[unit]}")
            spin.setRange(*INPUT_RANGE)
            spin.set_value(to_spectral(float(f_hz[i]), unit))
            self._shown.append((spin.value(), float(f_hz[i])))

    def values(self):
        """Frequencies [Hz] in model order (f_min, f_max for a pair).  The caller checks their order."""
        out = [0.0] * len(self.spins)
        for spin, i, (shown, hz) in zip(self.spins, self._order(), self._shown):
            out[i] = hz if spin.value() == shown else from_spectral(spin.value(), self.unit)
        return out

    def value(self):
        return self.values()[0]
