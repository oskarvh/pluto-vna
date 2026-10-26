"""Single-tone estimation: locate the IF tone, measure its complex amplitude.

Pure numpy, no hardware. See docs/design.md §1 step 4 for why the tone is located per
capture rather than assumed to sit at the nominal IF.
"""

import numpy as np

FULL_SCALE = 2048.0   # 12-bit ADC: a full-scale complex tone has amplitude 2048 LSB


def find_tone(x, fs):
    """Locate the strongest tone and judge whether it is really there.

    Returns ``(f, snr_db)``. The frequency is the FFT peak refined to sub-bin accuracy by
    parabolic interpolation on log magnitude — needed because the AD9361 DDS quantizes
    its output (1 000 000 Hz requested → 999 953 Hz). The whole spectrum is searched, so
    a flipped sideband is still found.

    ``snr_db`` is the peak bin relative to the median of all other bins. On the reference
    channel this cleanly separates a live tone (~78 dB) from a dead TX (~25 dB — the max
    of N noise bins sits well above their median, so the threshold must not be naive).
    """
    n = len(x)
    s = np.abs(np.fft.fft(x))
    k = int(np.argmax(s))
    a, b, c = (np.log(s[(k + o) % n] + 1e-30) for o in (-1, 0, 1))
    den = a - 2 * b + c
    delta = 0.5 * (a - c) / den if den != 0 else 0.0
    f = float(np.fft.fftfreq(n, 1 / fs)[k] + delta * fs / n)

    noise = np.median(np.delete(s, [(k + o) % n for o in (-2, -1, 0, 1, 2)]))
    snr_db = 20.0 * np.log10(s[k] / max(noise, 1e-30))
    return f, float(snr_db)


def tone_amplitude(x, f, fs):
    """Complex amplitude of the tone at ``f``, by inner product with that exponential.

    Both channels are correlated against the *same* reference, so whatever spectral
    leakage this incurs is a common factor that cancels in the ratio.
    """
    n = np.arange(len(x))
    return np.vdot(np.exp(2j * np.pi * f * n / fs), x) / len(x)


def to_dbfs(amplitude):
    return 20.0 * np.log10(np.maximum(np.abs(amplitude), 1e-30) / FULL_SCALE)
