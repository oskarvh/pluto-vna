"""Synthetic backend: a known DUT behind a known error box.

Mimics the parts of the real hardware that the software has to cope with — a random LO
phase on every retune, a DDS tone that is slightly off its nominal frequency, receiver
noise — so the sweep engine and the cal maths can be tested against exactly known
answers with no Pluto attached.
"""

import numpy as np

from plutovna.hw.pluto import RadioSettings

STANDARDS = {"load": 0.0 + 0j, "short": -1.0 + 0j, "open": 1.0 + 0j}


def error_terms(f):
    """Smooth, plausible 3-term error box: (e00 directivity, e11 source match,
    e10e01 reflection tracking). Roughly matches the measured test set: ~−20 dB raw
    directivity, ~−15 dB tracking, electrical length of a few hundred ps."""
    f = np.asarray(f, dtype=float)
    e00 = 0.08 * np.exp(-2j * np.pi * f * 0.9e-9) * (1 + 0.3 * np.cos(f / 2.1e8))
    e11 = 0.15 * np.exp(-2j * np.pi * f * 0.4e-9)
    e10e01 = 0.18 * np.exp(-2j * np.pi * f * 1.6e-9)
    return e00, e11, e10e01


def raw_ratio(f, gamma):
    """The ideal RX2/RX1 ratio the error box produces for reflection ``gamma``."""
    e00, e11, e10e01 = error_terms(f)
    return e00 + e10e01 * gamma / (1 - e11 * gamma)


class MockPluto:
    """Drop-in for ``hw.pluto.Pluto``. ``dut`` is a standard name, a complex Γ, or a
    callable ``f -> Γ``."""

    DDS_ERROR = 0.999953     # the real DDS lands 47 ppm low of what was asked for

    def __init__(self, settings=RadioSettings(), dut="load", noise_lsb=2.0, seed=None):
        self.settings = settings
        self.uri = "mock"
        self.dut = dut
        self.noise_lsb = noise_lsb
        self.rf = None
        self._rng = np.random.default_rng(seed)
        self._lo_phase = 0.0
        self._t0 = 0

    def gamma(self, f):
        d = self.dut
        if callable(d):
            return d(f)
        return STANDARDS[d] if isinstance(d, str) else complex(d)

    def tune(self, rf):
        self.rf = rf
        self._lo_phase = self._rng.uniform(0, 2 * np.pi)   # random per retune, like the AD9363

    def capture(self, flush=0):
        s = self.settings
        self._t0 += (flush + 1) * s.n
        n = np.arange(self._t0, self._t0 + s.n)
        f_tone = s.f_if * self.DDS_ERROR
        # Reference level falls with frequency like the real Pluto's output power.
        ref_amp = 460.0 * (2.6e9 / self.rf) ** 2
        a = ref_amp * np.exp(1j * (2 * np.pi * f_tone * n / s.fs + self._lo_phase))
        b = raw_ratio(self.rf, self.gamma(self.rf)) * a
        return a + self._noise(s.n), b + self._noise(s.n)

    def start_tone(self, tries=6):
        return 0

    def close(self):
        pass

    def _noise(self, n):
        return self.noise_lsb / np.sqrt(2) * (self._rng.standard_normal(n)
                                               + 1j * self._rng.standard_normal(n))
