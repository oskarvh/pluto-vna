#!/usr/bin/env python
"""Repeatability of the raw load sweep: untouched repeats, reseats, and the 4.05 GHz dip.

    .venv/bin/python tools/plot_repeats.py      # data/load_{rep*,reseat*,zoom}.csv → scratch/img/

Spreads are complex differences expressed relative to |short|, i.e. "how many dB below
a full reflection", which is what limits a calibrated measurement. Comparing dB values
directly would be misleading near a null, where tiny complex changes swing the dB wildly.
"""

import argparse
import glob
import os

import numpy as np

from plot_raw import COLORS, INK, INK2, SURFACE, plt
from plutovna.sweep import SweepResult

SERIES = {"untouched": "#2a78d6", "reseated": "#eb6834", "9 min earlier": "#1baf7a"}


def db(x):
    return 20 * np.log10(np.maximum(np.abs(x), 1e-30))


def rms_spread(stack):
    """Sample standard deviation of complex sweeps, per frequency."""
    m = stack.mean(0)
    return np.sqrt(np.sum(np.abs(stack - m) ** 2, 0) / (len(stack) - 1))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="scratch/img")
    args = ap.parse_args()

    def load(pattern):
        return [SweepResult.from_csv(p)
                for p in sorted(glob.glob(os.path.join(args.data, pattern)))]

    reps, seats = load("load_rep*.csv"), load("load_reseat*.csv")
    orig, short = load("load.csv")[0], load("short.csv")[0]
    zoom = load("load_zoom.csv")[0]
    f = reps[0].freq / 1e9
    R = np.array([r.ratio for r in reps])
    mean = R.mean(0)
    full = np.abs(short.ratio)

    # 1. spread vs frequency
    fig, ax = plt.subplots(figsize=(8, 4.2), layout="constrained")
    ax.set_title("Load sweep repeatability, relative to |short|", pad=18)
    ax.text(0.0, 1.015, f"{len(reps)} untouched repeats · {len(seats)} reseats · "
            "lower is better", transform=ax.transAxes, color=INK2, fontsize=8)
    curves = {
        "untouched": rms_spread(R),
        "reseated": rms_spread(np.array([r.ratio for r in seats])),
        "9 min earlier": np.abs(orig.ratio - mean),
    }
    for k, y in curves.items():
        ax.plot(f, db(y / full), color=SERIES[k], label=k,
                linewidth=2 if k != "9 min earlier" else 1.2)
    ax.set_xlabel("Frequency [GHz]")
    ax.set_ylabel("spread relative to |short| [dB]")
    ax.legend(loc="upper center", ncols=3)
    ax.set_ylim(-80, -20)
    path = os.path.join(args.out, "repeat_spread.png")
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"wrote {path}")

    # 2. the dip, magnitude: every repeat vs the 1 MHz zoom
    fig, ax = plt.subplots(figsize=(8, 4.2), layout="constrained")
    ax.set_title("The 4.05 GHz load dip", pad=18)
    ax.text(0.0, 1.015, "8.5 MHz sweeps (dots) vs 1 MHz zoom with 4 averages (line)",
            transform=ax.transAxes, color=INK2, fontsize=8)
    s = (f >= 3.99) & (f <= 4.11)
    for i, r in enumerate(reps + seats):
        ax.plot(f[s], db(r.ratio[s]), "o", color=SERIES["reseated" if r in seats
                                                       else "untouched"],
                markersize=5, alpha=0.6, markeredgewidth=0,
                label=("untouched" if i == 0 else "reseated" if r is seats[0] else None))
    ax.plot(zoom.freq / 1e9, db(zoom.ratio), color=COLORS["load"], linewidth=2,
            label="zoom")
    ax.set_xlabel("Frequency [GHz]")
    ax.set_ylabel("|RX2/RX1| [dB]")
    ax.legend(loc="lower left", ncols=3)
    path = os.path.join(args.out, "repeat_dip.png")
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"wrote {path}")

    # 3. the dip, complex plane: the trace just passes close to the origin
    fig, ax = plt.subplots(figsize=(6, 6), layout="constrained")
    ax.set_title("The dip in the complex plane", pad=18)
    ax.text(0.0, 1.015, "4.00 → 4.10 GHz, zoom sweep · ● start · ▲ stop",
            transform=ax.transAxes, color=INK2, fontsize=8)
    z = zoom.ratio
    ax.plot(z.real, z.imag, color=COLORS["load"], linewidth=2)
    ax.plot(z.real[0], z.imag[0], "o", color=COLORS["load"], markersize=8,
            markeredgecolor=SURFACE, markeredgewidth=2)
    ax.plot(z.real[-1], z.imag[-1], "^", color=COLORS["load"], markersize=8,
            markeredgecolor=SURFACE, markeredgewidth=2)
    k = int(np.argmin(np.abs(z)))
    ax.annotate(f"closest: {db(z[k]):.1f} dB @ {zoom.freq[k] / 1e9:.3f} GHz",
                (z.real[k], z.imag[k]), xytext=(12, -16), textcoords="offset points",
                color=INK, fontsize=9)
    ax.plot(0, 0, "+", color=INK, markersize=12)
    ax.set_aspect("equal")
    lim = 1.15 * np.abs(z).max()
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_xlabel("Re")
    ax.set_ylabel("Im")
    path = os.path.join(args.out, "repeat_dip_complex.png")
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
