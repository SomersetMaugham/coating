"""Physical constants in SI units (CODATA 2018)."""

import math

C0 = 299_792_458.0  # speed of light in vacuum [m/s]
MU0 = 1.25663706212e-6  # vacuum permeability [H/m]
EPS0 = 1.0 / (MU0 * C0 * C0)  # vacuum permittivity [F/m]
ETA0 = MU0 * C0  # free-space wave impedance [Ohm], ~376.73
TWO_PI = 2.0 * math.pi
