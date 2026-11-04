"""Branch-safe complex square root for longitudinal wavenumbers.

Convention: time dependence exp(+j*omega*t), waves propagate as exp(-j*kz*z).
A passive medium therefore requires Im(kz) <= 0 (decay along +z).  For a
lossless evanescent wave (negative real argument) this yields kz = -j*|kz|.
For a lossless propagating wave (positive real argument) Re(kz) >= 0.
"""

import numpy as np


def kz_sqrt(arg):
    """Square root of ``arg`` with Im(result) <= 0 and, when Im == 0, Re >= 0."""
    s = np.sqrt(np.asarray(arg, dtype=complex))
    flip = s.imag > 0.0
    return np.where(flip, -s, s)
