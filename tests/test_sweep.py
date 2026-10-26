import numpy as np
import pytest

from plutovna.dsp.tone import find_tone, tone_amplitude
from plutovna.hw.mock import MockPluto, raw_ratio
from plutovna.hw.pluto import RadioSettings
from plutovna.sweep import SweepPlan, SweepResult, run_sweep


def test_tone_estimate_off_bin():
    fs, n = 4e6, 4096
    f = 999_953.0                                # quantized DDS, not on a bin centre
    x = 300 * np.exp(1j * (2 * np.pi * f * np.arange(n) / fs + 0.7))
    f_hat, snr = find_tone(x, fs)
    assert abs(f_hat - f) < 0.05 * fs / n
    a = tone_amplitude(x, f_hat, fs)
    # Residual frequency error scallops the amplitude slightly; it is common to both
    # channels and cancels in the ratio, so only coarse absolute accuracy is required.
    assert abs(abs(a) - 300) / 300 < 1e-2
    assert snr > 60


def test_dead_tone_reads_low_snr():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(32768) + 1j * rng.standard_normal(32768)
    assert find_tone(x, 4e6)[1] < 40


@pytest.mark.parametrize("dut", ["load", "short", "open"])
def test_sweep_recovers_error_box_despite_random_lo_phase(dut):
    radio = MockPluto(RadioSettings(n=4096), dut=dut, seed=1)
    res = run_sweep(radio, SweepPlan(2.5e9, 4.2e9, 21))
    expected = raw_ratio(res.freq, radio.gamma(0))
    assert np.allclose(res.ratio, expected, atol=2e-3)


def test_averaging_reports_standard_error():
    radio = MockPluto(RadioSettings(n=4096), dut="short", noise_lsb=20, seed=2)
    res = run_sweep(radio, SweepPlan(3e9, 3e9, 1, averages=8))
    p = res.points[0]
    assert 0 < p.sem < 0.01
    assert abs(p.ratio - raw_ratio(3e9, -1)) < 5 * p.sem + 1e-4


def test_csv_round_trip(tmp_path):
    s = RadioSettings(n=4096, tx_gain=-12.0, rx_gain=(18.0, 25.0))
    res = run_sweep(MockPluto(s, dut="open", seed=3), SweepPlan(2.6e9, 4e9, 5, averages=2))
    path = tmp_path / "open.csv"
    res.to_csv(path)
    back = SweepResult.from_csv(path)
    assert back.settings == s
    assert back.plan == res.plan
    assert np.allclose(back.freq, res.freq)
    assert np.allclose(back.ratio, res.ratio, rtol=1e-8)
