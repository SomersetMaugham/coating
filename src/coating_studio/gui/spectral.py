"""Spin boxes that edit frequencies in the project's spectral unit; the rest of the spectral helpers live in the
Qt-free ``coating_studio.spectral`` and are re-exported here for the GUI."""

from __future__ import annotations

from coating_studio.core.units import SPECTRAL_LABEL, from_spectral, spectral_kind, spectral_reversed, to_spectral  # noqa: F401
from coating_studio.spectral import (  # noqa: F401 (re-exported)
    INPUT_RANGE, ascending, axis_label, csv_header, cursor_text, fmt_point, fmt_range, fmt_value, param_display_unit,
    param_from_display, param_kind, param_reversed, param_to_display, position_symbol, quantity_name, set_xlim, span,
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


LENGTH_INPUT_RANGE = (0.0, 1e15)  # display values: 1 m is 1e9 nm; 0 is a valid thickness


class LengthInputs:
    """Spin boxes that edit lengths [m] in the project's length unit (mm, µm, nm), with the same write-back rule as
    ``SpectralInputs``: a box whose number did not change returns the stored metres, not a float round trip."""

    def __init__(self, *spins, minimum=None):
        self.spins = spins
        self.unit = None
        self._shown = []
        self._min = minimum  # display minimum in metres (e.g. a positive reference thickness), or the range floor

    def show(self, unit, *m):
        from coating_studio.core.units import LENGTH_LABEL, to_length

        self.unit = unit
        self._shown = []
        for spin, si in zip(self.spins, m):
            spin.setSuffix(f" {LENGTH_LABEL[unit]}")
            lo = LENGTH_INPUT_RANGE[0] if self._min is None else to_length(self._min, unit)
            spin.setRange(lo, LENGTH_INPUT_RANGE[1])
            spin.set_value(to_length(float(si), unit))
            self._shown.append((spin.value(), float(si)))

    def values(self):
        from coating_studio.core.units import from_length

        return [si if spin.value() == shown else from_length(spin.value(), self.unit)
                for spin, (shown, si) in zip(self.spins, self._shown)]

    def value(self):
        return self.values()[0]
