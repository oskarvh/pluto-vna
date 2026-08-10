#!/usr/bin/env python
"""Phase 0/1 bring-up utilities for the Pluto VNA.

Three subcommands:

    info        dump the IIO context: devices, channels, LO and sample-rate ranges
    spectrum    emit a CW tone and report what each receiver sees
    phasegate   the Phase 1 experiment: is TX<->RX phase repeatable across LO retunes?

These are diagnostics, not library code. The tone estimator here moves into
plutovna/dsp/tone.py in Phase 2; it is duplicated for now so this file stays runnable
on its own during hardware bring-up.
"""

import argparse

import numpy as np

URI = "ip:192.168.2.1"


# --------------------------------------------------------------------------- helpers

def open_sdr(fs, n, rf, f_if, tx_gain=-10.0, rx_gain=(20.0, 40.0)):
    """Connect, configure for a single CW measurement point, start the DDS tone.

    The RF output lands at ``rf``: the DDS emits ``f_if`` at baseband and both LOs sit at
    ``rf - f_if``, so the received tone comes back down to ``+f_if``. Keeping the tone off
    DC avoids LO leakage, ADC DC offset and 1/f noise.
    """
    import adi

    sdr = adi.ad9361(uri=URI)
    sdr.rx_enabled_channels = [0, 1]
    sdr.sample_rate = int(fs)
    sdr.rx_rf_bandwidth = int(fs)
    sdr.tx_rf_bandwidth = int(fs)
    sdr.rx_buffer_size = n

    # Manual gain, always. AGC would move the gain mid-sweep and destroy amplitude
    # accuracy — and any gain change between calibration and measurement is straight
    # error.
    sdr.gain_control_mode_chan0 = "manual"
    sdr.gain_control_mode_chan1 = "manual"
    sdr.rx_hardwaregain_chan0 = rx_gain[0]
    sdr.rx_hardwaregain_chan1 = rx_gain[1]

    sdr.tx_hardwaregain_chan0 = tx_gain
    sdr.tx_hardwaregain_chan1 = -89.75          # TX2 off

    sdr.tx_lo = int(rf - f_if)
    sdr.rx_lo = int(rf - f_if)
    start_tone(sdr, f_if, fs)
    return sdr


def capture(sdr, flush=3):
    """Read both receivers out of one interleaved buffer.

    One buffer means the two channels are sample-aligned, which is what makes their ratio
    meaningful. ``flush`` discards buffers left over from before the last retune.
    """
    for _ in range(flush):
        sdr.rx()
    d = sdr.rx()
    return np.asarray(d[0], dtype=complex), np.asarray(d[1], dtype=complex)


def refine_freq(x, fs):
    """Locate the tone to sub-bin accuracy (FFT peak + parabolic log-mag interpolation).

    Needed because the AD9361 DDS quantizes its output — asking for 1 000 000 Hz gets
    999 953 Hz — so a fixed-bin estimator sits off the tone and reads noise. Searches the
    whole spectrum, not just positive frequencies, so a flipped sideband is still found.
    """
    n = len(x)
    s = np.abs(np.fft.fft(x))
    k = int(np.argmax(s))
    a, b, c = (np.log(s[(k + o) % n] + 1e-30) for o in (-1, 0, 1))
    delta = 0.5 * (a - c) / (a - 2 * b + c)
    return float(np.fft.fftfreq(n, 1 / fs)[k] + delta * fs / n)


def tone_snr_db(x, f, fs):
    """Tone level relative to the median of all other bins — the presence test."""
    n = len(x)
    s = np.abs(np.fft.fft(x))
    k = int(round(f * n / fs)) % n
    noise = np.median(np.delete(s, [(k + o) % n for o in (-2, -1, 0, 1, 2)]))
    return 20.0 * np.log10(s[k] / max(noise, 1e-30))


def start_tone(sdr, f_if, fs, scale=0.5, channel=0, tries=6):
    """Start the DDS tone and *verify* it is actually radiating.

    The AD9363 TX path comes up muted maybe two thirds of the time after a fresh context:
    every DDS and phy register reads back correct, but no RF appears. Re-writing the DDS
    alone does not fix it — cycling the ENSM through 'alert' back to 'fdd' is what re-arms
    the transmitter, after which the DDS has to be re-issued.

    Since a VNA sweep is worthless if the source is silently dead, this always confirms
    the tone before returning rather than trusting the register state.

    The check runs on RX1, which carries the reference channel and so is strong by
    construction regardless of the DUT. The two states are cleanly separated — a live tone
    measures ~78 dB SNR, a dead one ~25 dB (the max of N noise bins sits well above their
    median), so the threshold sits comfortably between them.
    """
    for attempt in range(tries):
        sdr.dds_single_tone(int(f_if), scale, channel)
        x, _ = capture(sdr, flush=2)
        f = refine_freq(x, fs)
        if tone_snr_db(x, f, fs) > 40.0:
            return attempt
        ensm = sdr._ctrl.attrs["ensm_mode"]
        ensm.value = "alert"
        ensm.value = "fdd"
    raise RuntimeError(
        "TX did not start after %d attempts — no tone detected on RX1" % tries)


def tone_amplitude(x, f, fs):
    """Complex amplitude of the tone at ``f``, by inner product with that exponential.

    Both channels are correlated against the *same* reference, so whatever spectral
    leakage this incurs is a common factor that cancels in the ratio.
    """
    n = np.arange(len(x))
    return np.vdot(np.exp(2j * np.pi * f * n / fs), x) / len(x)


def circ_std_deg(phases_deg):
    """Circular standard deviation — the ordinary std is meaningless on wrapped angles."""
    r = np.abs(np.mean(np.exp(1j * np.deg2rad(phases_deg))))
    return np.rad2deg(np.sqrt(-2.0 * np.log(max(r, 1e-12))))


# ------------------------------------------------------------------------ subcommands

def cmd_info(args):
    import iio

    ctx = iio.Context(URI)
    for name, value in ctx.attrs.items():
        print(f"ctx  {name} = {value.value if hasattr(value, 'value') else value}")
    print()
    for dev in ctx.devices:
        chans = [c for c in dev.channels]
        print(f"{dev.id:14s} {dev.name}   ({len(chans)} channels)")
        for ch in chans:
            if ch.id.startswith(("voltage", "altvoltage")) and dev.name != "xadc":
                d = "out" if ch.output else "in "
                extra = ""
                for a in ("frequency_available", "sampling_frequency_available"):
                    if a in ch.attrs:
                        extra = f"  {a}={ch.attrs[a].value}"
                print(f"    {d} {ch.id:12s} {ch.name or '':10s}{extra}")


def cmd_spectrum(args):
    sdr = open_sdr(args.fs, args.n, args.rf, args.f_if,
                   tx_gain=args.tx_gain, rx_gain=(args.rx_gain, args.rx_gain))
    a, b = capture(sdr)

    print(f"fs={args.fs/1e6:g} MSPS  N={args.n}  RBW={args.fs/args.n:.1f} Hz  "
          f"RF={args.rf/1e9:g} GHz  tx_gain={args.tx_gain} dB")
    freqs = np.fft.fftshift(np.fft.fftfreq(args.n, 1 / args.fs))
    for label, x in (("RX1", a), ("RX2", b)):
        s = np.fft.fftshift(np.fft.fft(x)) / args.n
        mag = np.abs(s)
        print(f"\n{label}  rms={np.sqrt(np.mean(np.abs(x)**2)):7.1f} LSB   top bins:")
        for i in np.argsort(mag)[::-1][:4]:
            print(f"    {freqs[i]/1e3:+10.3f} kHz  {20*np.log10(mag[i]/2048):7.2f} dBFS")

    f = refine_freq(a, args.fs)
    amp_a, amp_b = tone_amplitude(a, f, args.fs), tone_amplitude(b, f, args.fs)
    print(f"\ntone found at {f:.1f} Hz")
    print(f"RX2/RX1 = {20*np.log10(abs(amp_b/amp_a)):+7.2f} dB  "
          f"{np.angle(amp_b/amp_a, deg=True):+8.2f} deg")
    del sdr


def cmd_phasegate(args):
    """Does the TX->RX phase survive an LO retune, or only the RX2/RX1 ratio?

    Decides the RF topology. If only the ratio is stable, every measured quantity must be
    a ratio of two simultaneously captured receivers, which forces a reference channel
    into the test set (see docs/hardware.md section 4).
    """
    sdr = open_sdr(args.fs, args.n, args.rf, args.f_if,
                   tx_gain=args.tx_gain, rx_gain=(args.rx_gain, args.rx_gain2))

    rfs = [float(x) for x in args.freqs.split(",")]
    print(f"{args.trials} trials per frequency; LO detuned to "
          f"{args.park/1e9:g} GHz and back between each\n")
    print(f"{'RF':>9} {'sd/A1':>9} {'sd/A2':>9} {'sd/(A2/A1)':>12} {'|A2/A1| ptp':>12}")

    for rf in rfs:
        p1, p2, pr, mg = [], [], [], []
        for _ in range(args.trials):
            sdr.rx_lo = int(args.park)                  # park elsewhere...
            sdr.tx_lo = int(args.park)
            sdr.tx_lo = int(rf - args.f_if)             # ...and retune back
            sdr.rx_lo = int(rf - args.f_if)
            a, b = capture(sdr)
            f = refine_freq(a, args.fs)
            amp_a, amp_b = tone_amplitude(a, f, args.fs), tone_amplitude(b, f, args.fs)
            p1.append(np.angle(amp_a, deg=True))
            p2.append(np.angle(amp_b, deg=True))
            pr.append(np.angle(amp_b / amp_a, deg=True))
            mg.append(20 * np.log10(abs(amp_b / amp_a)))
        print(f"{rf/1e9:8.2f}G {circ_std_deg(p1):8.2f}° {circ_std_deg(p2):8.2f}° "
              f"{circ_std_deg(pr):11.3f}° {np.ptp(mg):11.3f} dB")

    print("\nIf the per-channel columns are large (tens of degrees) and the ratio column "
          "is small,\nthe LO phase is random per retune and cancels only in the ratio.")
    del sdr


# ------------------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--fs", type=float, default=4e6, help="sample rate [Hz]")
        sp.add_argument("--n", type=int, default=32768, help="samples per capture")
        sp.add_argument("--f-if", type=float, default=1e6, help="baseband IF [Hz]")
        sp.add_argument("--rf", type=float, default=3.0e9, help="RF test frequency [Hz]")
        sp.add_argument("--tx-gain", type=float, default=-10.0)
        sp.add_argument("--rx-gain", type=float, default=20.0)

    sub.add_parser("info").set_defaults(func=cmd_info)

    sp = sub.add_parser("spectrum")
    common(sp)
    sp.set_defaults(func=cmd_spectrum)

    sp = sub.add_parser("phasegate")
    common(sp)
    sp.add_argument("--rx-gain2", type=float, default=40.0)
    sp.add_argument("--trials", type=int, default=25)
    sp.add_argument("--park", type=float, default=2.4e9, help="park LO here between trials")
    sp.add_argument("--freqs", default="2.6e9,3.0e9,3.5e9")
    sp.set_defaults(func=cmd_phasegate)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
