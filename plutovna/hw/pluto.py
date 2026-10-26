"""ADALM-PLUTO backend. The only module that imports adi/iio.

Everything above this layer sees two methods — ``tune(rf)`` and ``capture(flush)`` —
returning plain numpy arrays, so ``hw/mock.py`` can stand in for the hardware.
"""

from dataclasses import dataclass

import numpy as np

from plutovna.dsp.tone import find_tone

URI = "ip:192.168.2.1"
TONE_SNR_MIN_DB = 40.0   # live tone ~78 dB, dead TX ~25 dB on the reference channel


@dataclass(frozen=True)
class RadioSettings:
    """Everything that changes the raw ratio. A calibration is only valid for the exact
    settings it was taken with, so these get recorded alongside every sweep."""
    fs: float = 4e6                      # sample rate [Hz]; IF bandwidth = fs / n
    n: int = 32768                       # samples per capture
    f_if: float = 1e6                    # baseband tone offset [Hz]
    tx_gain: float = -10.0               # TX1 attenuation [dB], 0 … −89.75
    rx_gain: tuple = (20.0, 20.0)        # manual RX gain [dB], (RX1, RX2)
    tone_scale: float = 0.5              # DDS amplitude, fraction of full scale
    flush: int = 3                       # buffers discarded after every retune

    @property
    def if_bandwidth(self):
        return self.fs / self.n


class Pluto:
    def __init__(self, settings=RadioSettings(), uri=URI):
        import adi

        self.settings = s = settings
        self.uri = uri
        self.rf = None
        sdr = self._sdr = adi.ad9361(uri=uri)
        sdr.rx_enabled_channels = [0, 1]
        sdr.sample_rate = int(s.fs)
        sdr.rx_rf_bandwidth = int(s.fs)
        sdr.tx_rf_bandwidth = int(s.fs)
        sdr.rx_buffer_size = s.n

        # Manual gain, always. AGC would move the gain mid-sweep and destroy amplitude
        # accuracy — and any gain change between calibration and measurement is straight
        # error.
        sdr.gain_control_mode_chan0 = "manual"
        sdr.gain_control_mode_chan1 = "manual"
        sdr.rx_hardwaregain_chan0 = s.rx_gain[0]
        sdr.rx_hardwaregain_chan1 = s.rx_gain[1]
        sdr.tx_hardwaregain_chan0 = s.tx_gain
        sdr.tx_hardwaregain_chan1 = -89.75          # TX2 off

    def tune(self, rf):
        """Put the RF tone at ``rf``: both LOs at ``rf - f_if``, DDS at ``+f_if``."""
        lo = int(round(rf - self.settings.f_if))
        self._sdr.tx_lo = lo
        self._sdr.rx_lo = lo
        if self.rf is None:
            self.start_tone()
        self.rf = rf

    def capture(self, flush=0):
        """Read both receivers out of one interleaved buffer.

        One buffer means the two channels are sample-aligned, which is what makes their
        ratio meaningful. ``flush`` discards buffers left over from before a retune.
        """
        for _ in range(flush):
            self._sdr.rx()
        d = self._sdr.rx()
        return np.asarray(d[0], dtype=complex), np.asarray(d[1], dtype=complex)

    def start_tone(self, tries=6):
        """Start the DDS tone and *verify* it is actually radiating.

        The AD9363 TX path comes up muted maybe two thirds of the time after a fresh
        context: every DDS and phy register reads back correct, but no RF appears.
        Re-writing the DDS alone does not fix it — cycling the ENSM through 'alert' back
        to 'fdd' re-arms the transmitter, after which the DDS has to be re-issued.

        The check runs on RX1, which carries the reference and so is strong by
        construction regardless of the DUT. Returns the number of kicks it took.
        """
        s = self.settings
        for attempt in range(tries):
            self._sdr.dds_single_tone(int(s.f_if), s.tone_scale, 0)
            x, _ = self.capture(flush=2)
            if find_tone(x, s.fs)[1] > TONE_SNR_MIN_DB:
                return attempt
            ensm = self._sdr._ctrl.attrs["ensm_mode"]
            ensm.value = "alert"
            ensm.value = "fdd"
        raise RuntimeError(
            "TX did not start after %d attempts — no tone detected on RX1" % tries)

    def close(self):
        self._sdr.tx_hardwaregain_chan0 = -89.75
        del self._sdr
