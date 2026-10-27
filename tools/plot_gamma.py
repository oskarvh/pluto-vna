#!/usr/bin/env python
"""Plot calibrated one-port results: return loss and a Smith chart.

    .venv/bin/python tools/plot_gamma.py data/antenna_jcg401_gamma.csv --name jcg401

Reads the CSVs written by ``plutovna.cli correct``. Up to three files per plot.
"""

import argparse
import os

import numpy as np

from plot_raw import INK, INK2, GRID, SURFACE, plt

SLOTS = ("#2a78d6", "#eb6834", "#1baf7a")   # fixed categorical order


def read(path):
    d = np.genfromtxt(path, delimiter=",", comments="#", skip_header=3, names=True)
    return d["freq_hz"], d["re"] + 1j * d["im"]


def smith_grid(ax):
    t = np.linspace(0, 2 * np.pi, 400)
    for r in (0, 0.2, 0.5, 1, 2, 5):                       # constant resistance
        c, rad = r / (1 + r), 1 / (1 + r)
        ax.plot(c + rad * np.cos(t), rad * np.sin(t), color=GRID if r else INK2,
                linewidth=0.8 if r else 1.0)
    for x in (0.2, 0.5, 1, 2, 5):                          # constant reactance
        for s in (1, -1):
            z = 1j * s * x + np.linspace(0, 50, 2000) ** 2
            g = (z - 1) / (z + 1)
            ax.plot(g.real, g.imag, color=GRID, linewidth=0.8)
    ax.axhline(0, color=GRID, linewidth=0.8)
    ax.set_aspect("equal")
    ax.set_xlim(-1.05, 1.05)
    ax.set_ylim(-1.05, 1.05)
    ax.axis("off")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--name", required=True, help="output file stem")
    ap.add_argument("--out", default="scratch/img")
    ap.add_argument("--spec-vswr", type=float, help="draw a VSWR limit line")
    args = ap.parse_args()
    data = {os.path.splitext(os.path.basename(p))[0].removesuffix("_gamma"): read(p)
            for p in args.files[:3]}

    fig, (ax, sx) = plt.subplots(1, 2, figsize=(11, 4.6), layout="constrained",
                                 width_ratios=(1.5, 1))
    ax.set_title("Calibrated return loss", pad=18)
    ax.text(0.0, 1.015, "one-port SOL, ideal kit", transform=ax.transAxes,
            color=INK2, fontsize=8)
    for (name, (f, g)), c in zip(data.items(), SLOTS):
        ax.plot(f / 1e9, 20 * np.log10(np.abs(g)), color=c, label=name)
        k = int(np.argmin(np.abs(g)))
        ax.annotate(f"{20 * np.log10(abs(g[k])):.1f} dB @ {f[k] / 1e9:.3f} GHz",
                    (f[k] / 1e9, 20 * np.log10(abs(g[k]))), xytext=(10, 0),
                    textcoords="offset points", va="center", color=INK, fontsize=9)
    if args.spec_vswr:
        s = args.spec_vswr
        ax.axhline(20 * np.log10((s - 1) / (s + 1)), color=INK2, linewidth=1,
                   linestyle="--")
        ax.text(1.0, 20 * np.log10((s - 1) / (s + 1)), f"VSWR {s:g} ", color=INK2,
                fontsize=8, ha="right", va="bottom", transform=ax.get_yaxis_transform())
    ax.set_xlabel("Frequency [GHz]")
    ax.set_ylabel("|Γ| [dB]")
    if len(data) > 1:
        ax.legend(loc="lower right")

    sx.set_title("Smith chart", pad=18)
    smith_grid(sx)
    for (name, (f, g)), c in zip(data.items(), SLOTS):
        sx.plot(g.real, g.imag, color=c, linewidth=1.5)
        sx.plot(g.real[0], g.imag[0], "o", color=c, markersize=8,
                markeredgecolor=SURFACE, markeredgewidth=2)
        sx.plot(g.real[-1], g.imag[-1], "^", color=c, markersize=8,
                markeredgecolor=SURFACE, markeredgewidth=2)
    f0, f1 = next(iter(data.values()))[0][[0, -1]] / 1e9
    sx.text(0.5, 1.015, f"● {f0:g} GHz · ▲ {f1:g} GHz", transform=sx.transAxes,
            ha="center", color=INK2, fontsize=8)

    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{args.name}.png")
    fig.savefig(path, dpi=130)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
