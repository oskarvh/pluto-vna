#!/usr/bin/env python
"""Plot raw (uncalibrated) one-port sweeps of the load / open / short standards.

    .venv/bin/python tools/plot_raw.py                      # data/{load,open,short}.csv
    .venv/bin/python tools/plot_raw.py --out scratch/img

Writes four PNGs: magnitude, phase, complex plane, and the short−load margin.
"""

import argparse
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from plutovna.sweep import SweepResult  # noqa: E402

# Fixed categorical order — the colour follows the standard, never its position.
COLORS = {"load": "#2a78d6", "open": "#eb6834", "short": "#1baf7a"}
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2,
    "ytick.color": INK2, "text.color": INK, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False,
    "lines.linewidth": 2.0, "font.size": 10, "axes.titlesize": 12,
    "axes.titleweight": "bold", "axes.titlelocation": "left", "legend.frameon": False,
})


def label_end(ax, x, y, text, color):
    """Direct label at the right end of a line, in text ink with a colour swatch."""
    ax.annotate(f"■ {text}", (x[-1], y[-1]), xytext=(6, 0), textcoords="offset points",
                va="center", color=INK, fontsize=9)
    ax.annotate("■", (x[-1], y[-1]), xytext=(6, 0), textcoords="offset points",
                va="center", color=color, fontsize=9)


def break_wraps(phase_deg):
    """NaN at ±180° wrap points so the line doesn't draw a vertical jump."""
    p = np.asarray(phase_deg, dtype=float).copy()
    jumps = np.where(np.abs(np.diff(p)) > 180)[0]
    return np.insert(p, jumps + 1, np.nan), jumps


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data", help="directory holding load/open/short.csv")
    ap.add_argument("--out", default="scratch/img")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    sweeps = {k: SweepResult.from_csv(os.path.join(args.data, f"{k}.csv")) for k in COLORS}
    settings = {(s.settings, s.plan) for s in sweeps.values()}
    if len(settings) != 1:
        sys.exit("the three sweeps were taken with different settings")
    s = next(iter(sweeps.values()))
    subtitle = (f"raw RX2/RX1, uncalibrated · IF BW {s.settings.if_bandwidth:.0f} Hz · "
                f"tx_gain {s.settings.tx_gain:g} dB · rx_gain {s.settings.rx_gain[0]:g} dB")

    def fig(title):
        f, ax = plt.subplots(figsize=(8, 4.2), layout="constrained")
        ax.set_title(title, pad=18)
        ax.text(0.0, 1.015, subtitle, transform=ax.transAxes, ha="left", va="bottom",
                color=INK2, fontsize=8)
        return f, ax

    def save(f, name):
        path = os.path.join(args.out, name)
        f.savefig(path, dpi=130)
        plt.close(f)
        print(f"wrote {path}")

    # 1. magnitude
    f, ax = fig("Raw reflection magnitude")
    for k, r in sweeps.items():
        x, y = r.freq / 1e9, 20 * np.log10(np.abs(r.ratio))
        ax.plot(x, y, color=COLORS[k], label=k)
        label_end(ax, x, y, k, COLORS[k])
    ax.set_xlabel("Frequency [GHz]")
    ax.set_ylabel("|RX2/RX1| [dB]")
    ax.legend(loc="lower left", ncols=3)
    ax.margins(x=0.08)
    save(f, "raw_magnitude.png")

    # 2. phase
    f, ax = fig("Raw reflection phase")
    for k, r in sweeps.items():
        y, jumps = break_wraps(np.angle(r.ratio, deg=True))
        x = np.insert(r.freq / 1e9, jumps + 1, np.nan)
        ax.plot(x, y, color=COLORS[k], label=k)
    ax.set_xlabel("Frequency [GHz]")
    ax.set_ylabel("∠RX2/RX1 [deg]")
    ax.set_yticks(range(-180, 181, 90))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncols=3)
    save(f, "raw_phase.png")

    # 3. complex plane — what the cal solver actually works on
    f, ax = plt.subplots(figsize=(6, 6), layout="constrained")
    ax.set_title("Raw ratio, complex plane")
    ax.text(1.0, 1.02, "● start · ▲ stop", transform=ax.transAxes, ha="right",
            va="bottom", color=INK2, fontsize=8)
    for k, r in sweeps.items():
        z = r.ratio
        ax.plot(z.real, z.imag, color=COLORS[k], label=k, linewidth=1.5)
        ax.plot(z.real[0], z.imag[0], "o", color=COLORS[k], markersize=8,
                markeredgecolor=SURFACE, markeredgewidth=2)
        ax.plot(z.real[-1], z.imag[-1], "^", color=COLORS[k], markersize=8,
                markeredgecolor=SURFACE, markeredgewidth=2)
    ax.axhline(0, color=INK2, linewidth=0.8)
    ax.axvline(0, color=INK2, linewidth=0.8)
    ax.set_aspect("equal")
    ax.set_xlabel("Re")
    ax.set_ylabel("Im")
    ax.legend(loc="upper right")
    save(f, "raw_complex.png")

    # 4. short − load margin: the raw directivity check
    f, ax = fig("Raw directivity margin: |short| − |load|")
    x = sweeps["short"].freq / 1e9
    y = (20 * np.log10(np.abs(sweeps["short"].ratio))
         - 20 * np.log10(np.abs(sweeps["load"].ratio)))
    ax.plot(x, y, color=COLORS["load"])
    ax.set_xlabel("Frequency [GHz]")
    ax.set_ylabel("margin [dB]")
    ax.set_ylim(bottom=0)
    i = int(np.argmin(y))
    ax.annotate(f"min {y[i]:.1f} dB @ {x[i]:.3f} GHz", (x[i], y[i]), xytext=(10, -14),
                textcoords="offset points", color=INK, fontsize=9)
    save(f, "raw_margin.png")


if __name__ == "__main__":
    main()
