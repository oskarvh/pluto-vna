"""One-port 3-term error model: solve from standards, apply to measurements.

    m = e00 + e10e01·Γ / (1 − e11·Γ)            (docs/design.md §2)

Rearranged so it is linear in the unknowns (e00, e11, Δ), with Δ = e00·e11 − e10e01:

    m = e00 + Γ·m·e11 − Γ·Δ

Each standard contributes one complex equation per frequency. Three standards give an
exact solve; more give a least-squares fit, whose residual says how well the standard
models agree with each other.
"""

import numpy as np


def solve(measured, actual):
    """Error terms from N ≥ 3 standards.

    ``measured`` and ``actual`` are (N, F) complex arrays: the raw ratio and the modelled
    Γ of each standard at each frequency. Returns ``(e00, e11, e10e01)``, each shape (F,).
    """
    m = np.asarray(measured, dtype=complex)
    g = np.asarray(actual, dtype=complex)
    if m.shape != g.shape or m.ndim != 2 or m.shape[0] < 3:
        raise ValueError("need (N≥3, F) arrays of measured and actual Γ")
    # A[f] is (N, 3): rows [1, Γ·m, −Γ]; b[f] is (N,): m.
    a = np.stack([np.ones_like(m), g * m, -g], axis=-1).transpose(1, 0, 2)
    b = m.T
    if m.shape[0] == 3:
        x = np.linalg.solve(a, b[..., None])[..., 0]
    else:
        x = np.stack([np.linalg.lstsq(a[i], b[i], rcond=None)[0] for i in range(len(b))])
    e00, e11, delta = x.T
    return e00, e11, e00 * e11 - delta


def apply(m, e00, e11, e10e01):
    """Corrected Γ from raw ratio ``m``."""
    m = np.asarray(m, dtype=complex)
    return (m - e00) / (e10e01 + e11 * (m - e00))


def raw(gamma, e00, e11, e10e01):
    """The forward model: the raw ratio a DUT of reflection ``gamma`` produces."""
    return e00 + e10e01 * gamma / (1 - e11 * gamma)
