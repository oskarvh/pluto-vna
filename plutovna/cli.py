"""Headless sweep — the bring-up and scripting entry point.

    .venv/bin/python -m plutovna.cli sweep --points 201 --out data/load.csv
    .venv/bin/python -m plutovna.cli sweep --mock short --points 51

Writes raw (uncalibrated) RX2/RX1 ratios plus every setting they depend on.
"""

import argparse
import os

import numpy as np

from plutovna.hw.pluto import URI, RadioSettings
from plutovna.sweep import SweepPlan, run_sweep


def cmd_sweep(args):
    settings = RadioSettings(fs=args.fs, n=args.n, f_if=args.f_if, tx_gain=args.tx_gain,
                             rx_gain=(args.rx_gain, args.rx_gain2 if args.rx_gain2
                                      is not None else args.rx_gain))
    plan = SweepPlan(start=args.start, stop=args.stop, points=args.points,
                     averages=args.avg)

    if args.mock:
        from plutovna.hw.mock import MockPluto
        radio = MockPluto(settings, dut=args.mock)
    else:
        from plutovna.hw.pluto import Pluto
        radio = Pluto(settings, uri=args.uri)

    print(f"{plan.points} points  {plan.start / 1e9:g}–{plan.stop / 1e9:g} GHz  "
          f"IF BW {settings.if_bandwidth:.0f} Hz  avg {plan.averages}  "
          f"tx_gain {settings.tx_gain} dB  rx_gain {settings.rx_gain}  [{radio.uri}]")

    def show(i, p):
        if not args.quiet:
            print(f"{i + 1:4d}/{plan.points}  {p.freq / 1e9:8.4f} GHz  "
                  f"{20 * np.log10(abs(p.ratio)):+8.2f} dB  "
                  f"{np.angle(p.ratio, deg=True):+8.2f}°   "
                  f"RX1 {p.a1_dbfs:6.1f} dBFS  RX2 {p.a2_dbfs:6.1f} dBFS")

    try:
        res = run_sweep(radio, plan, on_point=show)
    finally:
        radio.close()

    peak = max(max(p.a1_dbfs, p.a2_dbfs) for p in res.points)
    print(f"\n{res.duration_s:.1f} s  ({res.duration_s / plan.points * 1e3:.0f} ms/point)  "
          f"strongest tone {peak:.1f} dBFS")
    if peak > -15.0:
        print("WARNING: less than 15 dB headroom to full scale — lower --tx-gain or "
              "--rx-gain before calibrating")

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        res.to_csv(args.out)
        print(f"wrote {args.out}")


def cmd_cal(args):
    from plutovna.cal.standards import IDEAL, load_kit
    from plutovna.cal.state import OnePortCal
    from plutovna.sweep import SweepResult

    kit = load_kit(args.kit) if args.kit else IDEAL
    files = {"open": args.open, "short": args.short, "load": args.load}
    cal = OnePortCal.from_sweeps({k: SweepResult.from_csv(v) for k, v in files.items()},
                                 kit, sources=files)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    cal.save(args.out)

    def db(x):
        return 20 * np.log10(np.abs(x))

    print(f"one-port cal, kit {kit.name!r}, {len(cal.freq)} points "
          f"{cal.freq[0] / 1e9:g}–{cal.freq[-1] / 1e9:g} GHz")
    for name, e in (("directivity  e00", cal.e00), ("source match e11", cal.e11),
                    ("tracking  e10e01", cal.e10e01)):
        print(f"  {name}: {db(e).min():7.1f} … {db(e).max():6.1f} dB")
    print(f"wrote {args.out}")


def cmd_correct(args):
    from plutovna.cal.state import OnePortCal
    from plutovna.sweep import SweepResult

    cal = OnePortCal.load(args.cal)
    sweep = SweepResult.from_csv(args.sweep)
    gamma = cal.correct(sweep)
    mag = 20 * np.log10(np.maximum(np.abs(gamma), 1e-30))
    print(f"|Γ|: {mag.min():.1f} … {mag.max():.1f} dB, median {np.median(mag):.1f} dB")
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w") as fh:
            fh.write(f"# sweep = {args.sweep}\n# cal = {args.cal}\n# kit = {cal.kit}\n")
            fh.write("freq_hz,re,im,mag_db,phase_deg\n")
            for f, g, m in zip(sweep.freq, gamma, mag):
                fh.write(f"{f:.0f},{g.real:.9e},{g.imag:.9e},{m:.4f},"
                         f"{np.angle(g, deg=True):.4f}\n")
        print(f"wrote {args.out}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("cal", help="one-port SOL calibration from three raw sweeps")
    sp.add_argument("--open", default="data/open.csv")
    sp.add_argument("--short", default="data/short.csv")
    sp.add_argument("--load", default="data/load.csv")
    sp.add_argument("--kit", help="cal-kit TOML (default: ideal standards)")
    sp.add_argument("--out", default="data/cal.npz")
    sp.set_defaults(func=cmd_cal)

    sp = sub.add_parser("correct", help="apply a calibration to a raw sweep")
    sp.add_argument("sweep", help="raw sweep CSV")
    sp.add_argument("--cal", default="data/cal.npz")
    sp.add_argument("--out", help="corrected Γ CSV")
    sp.set_defaults(func=cmd_correct)

    sp = sub.add_parser("sweep", help="stepped-frequency sweep → raw ratio CSV")
    d = RadioSettings()
    sp.add_argument("--start", type=float, default=2.5e9, help="start frequency [Hz]")
    sp.add_argument("--stop", type=float, default=4.2e9, help="stop frequency [Hz]")
    sp.add_argument("--points", type=int, default=201)
    sp.add_argument("--avg", type=int, default=1, help="captures averaged per point")
    sp.add_argument("--fs", type=float, default=d.fs, help="sample rate [Hz]")
    sp.add_argument("--n", type=int, default=d.n,
                    help="samples per capture (IF bandwidth = fs/n)")
    sp.add_argument("--f-if", type=float, default=d.f_if, help="baseband IF [Hz]")
    sp.add_argument("--tx-gain", type=float, default=d.tx_gain)
    sp.add_argument("--rx-gain", type=float, default=d.rx_gain[0],
                    help="RX gain [dB], both channels unless --rx-gain2 is given")
    sp.add_argument("--rx-gain2", type=float, default=None, help="RX2 gain [dB]")
    sp.add_argument("--uri", default=URI)
    sp.add_argument("--mock", metavar="DUT", choices=["load", "short", "open"],
                    help="use the synthetic backend with this standard attached")
    sp.add_argument("--out", help="CSV output path (data/ is gitignored)")
    sp.add_argument("-q", "--quiet", action="store_true", help="no per-point output")
    sp.set_defaults(func=cmd_sweep)

    args = p.parse_args()
    from plutovna.cal.state import CalMismatch
    try:
        args.func(args)
    except CalMismatch as e:
        raise SystemExit(f"error: {e}")


if __name__ == "__main__":
    main()
