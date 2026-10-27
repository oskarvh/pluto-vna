"""Calibration-standard models: what Γ each standard *actually* presents.

Each standard is an offset transmission line terminated in a lumped element, using the
usual vendor cal-kit convention (Keysight application note 1287-11), so published
coefficients drop straight in:

- **offset**: one-way delay [s], loss [Ω/s, specified at 1 GHz] and impedance Z0 [Ω]
- **open**:   fringing capacitance C(f) = C0 + C1·f + C2·f² + C3·f³
- **short**:  inductance          L(f) = L0 + L1·f + L2·f² + L3·f³
- **load**:   a resistance (50 Ω for an ideal load)

Kits are TOML files (see ``calkits/``) with coefficients in the vendor units:
C0..C3 in 1e-15 F, 1e-27 F/Hz, 1e-36 F/Hz², 1e-45 F/Hz³; L0..L3 in 1e-12 H, 1e-24 H/Hz,
1e-33 H/Hz², 1e-42 H/Hz³; delay in ps; loss in GΩ/s.
"""

import tomllib
from dataclasses import dataclass, field

import numpy as np

Z_REF = 50.0


@dataclass(frozen=True)
class Standard:
    kind: str                          # "open" | "short" | "load"
    delay: float = 0.0                 # one-way offset delay [s]
    loss: float = 0.0                  # offset loss [Ω/s] at 1 GHz
    z0: float = Z_REF                  # offset impedance [Ω]
    poly: tuple = (0.0, 0.0, 0.0, 0.0)  # C [F, F/Hz, …] or L [H, H/Hz, …]
    r: float = Z_REF                   # load resistance [Ω]

    def gamma(self, f):
        """Reflection coefficient at frequencies ``f`` [Hz], referred to Z_REF."""
        f = np.asarray(f, dtype=float)
        w = 2 * np.pi * f
        p = sum(c * f ** i for i, c in enumerate(self.poly))
        if self.kind == "open":
            z_term = np.where(p == 0, np.inf, 1 / (1j * w * np.where(p == 0, 1, p)))
        elif self.kind == "short":
            z_term = 1j * w * p
        elif self.kind == "load":
            z_term = np.full_like(f, self.r, dtype=complex)
        else:
            raise ValueError(f"unknown standard kind {self.kind!r}")
        return _offset(z_term, f, self.delay, self.loss, self.z0)


def _offset(z_term, f, delay, loss, z0):
    """Γ of ``z_term`` seen through an offset line, referred to Z_REF."""
    if delay == 0 and loss == 0 and z0 == Z_REF:
        return _gamma(z_term, Z_REF)
    rf = np.sqrt(f / 1e9)
    al = loss * delay / (2 * z0) * rf                         # attenuation × length
    bl = 2 * np.pi * f * delay + al                           # phase × length
    with np.errstate(divide="ignore", invalid="ignore"):
        zc = z0 + (1 - 1j) * loss / (4 * np.pi * np.maximum(f, 1e-30)) * rf
    e = np.exp(-2 * (al + 1j * bl))
    g1 = _gamma(z_term, zc)                                   # termination vs line
    g0 = (zc - Z_REF) / (zc + Z_REF)                          # line vs reference
    return (g0 * (1 - e - g0 * g1) + e * g1) / (1 - g0 * (e * g0 + g1 * (1 - e)))


def _gamma(z, z0):
    with np.errstate(divide="ignore", invalid="ignore"):
        g = (z - z0) / (z + z0)
    return np.where(np.isinf(z), 1.0 + 0j, g)


@dataclass(frozen=True)
class CalKit:
    name: str
    standards: dict = field(default_factory=dict)   # kind → Standard

    def __getitem__(self, kind):
        return self.standards[kind]


IDEAL = CalKit("ideal", {k: Standard(k) for k in ("open", "short", "load")})

# Vendor units → SI, per polynomial order.
_C_UNITS = (1e-15, 1e-27, 1e-36, 1e-45)    # F, F/Hz, F/Hz², F/Hz³
_L_UNITS = (1e-12, 1e-24, 1e-33, 1e-42)    # H, H/Hz, H/Hz², H/Hz³


def load_kit(path):
    """Read a TOML cal kit. Missing standards and missing keys default to ideal."""
    with open(path, "rb") as fh:
        d = tomllib.load(fh)
    stds = {}
    for kind in ("open", "short", "load"):
        s = d.get(kind, {})
        units, prefix = (_C_UNITS, "c") if kind == "open" else (_L_UNITS, "l")
        poly = tuple(s.get(f"{prefix}{i}", 0.0) * u for i, u in enumerate(units))
        stds[kind] = Standard(kind, delay=s.get("delay_ps", 0.0) * 1e-12,
                              loss=s.get("loss_gohm_per_s", 0.0) * 1e9,
                              z0=s.get("z0", Z_REF), poly=poly, r=s.get("r", Z_REF))
    return CalKit(d.get("name", str(path)), stds)
