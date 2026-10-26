"""Sweep engine: frequency plan → raw complex ratios RX2/RX1.

Backend-agnostic: anything with ``settings``, ``tune(rf)`` and ``capture(flush)`` works,
so ``hw.mock.MockPluto`` exercises all of this with no hardware.
"""

import dataclasses
import time
from dataclasses import dataclass, field

import numpy as np

from plutovna.dsp.tone import find_tone, to_dbfs, tone_amplitude
from plutovna.hw.pluto import TONE_SNR_MIN_DB, RadioSettings

CSV_VERSION = 1


@dataclass(frozen=True)
class SweepPlan:
    start: float = 2.5e9
    stop: float = 4.2e9
    points: int = 201
    averages: int = 1          # captures per point; noise falls as √averages

    def frequencies(self):
        return np.linspace(self.start, self.stop, self.points)


@dataclass(frozen=True)
class Point:
    freq: float
    ratio: complex             # mean of the per-capture RX2/RX1 ratios
    sem: float                 # standard error of that mean, |ratio| units (nan if 1 avg)
    a1_dbfs: float             # reference level
    a2_dbfs: float             # measured-wave level
    ref_snr_db: float          # worst reference-tone SNR seen at this point


def measure_point(radio, rf, averages=1):
    """One frequency point (docs/design.md §1): tune, settle, capture, estimate, ratio,
    average.

    The complex *ratios* are averaged, never the per-channel amplitudes: each channel's
    absolute phase is random after the retune and only the ratio is coherent.

    The reference-tone check runs on every capture. A source that dies mid-sweep would
    otherwise produce plausible-looking noise, so it gets one restart and then the sweep
    fails loudly.
    """
    s = radio.settings
    radio.tune(rf)
    ratios, a1s, a2s, snrs = [], [], [], []
    for i in range(averages):
        a, b = _capture_live(radio, flush=s.flush if i == 0 else 0)
        f, snr = find_tone(a, s.fs)
        A1, A2 = tone_amplitude(a, f, s.fs), tone_amplitude(b, f, s.fs)
        ratios.append(A2 / A1)
        a1s.append(abs(A1))
        a2s.append(abs(A2))
        snrs.append(snr)

    ratios = np.asarray(ratios)
    sem = float(np.std(ratios, ddof=1) / np.sqrt(averages)) if averages > 1 else float("nan")
    return Point(freq=float(rf), ratio=complex(ratios.mean()), sem=sem,
                 a1_dbfs=float(to_dbfs(np.mean(a1s))), a2_dbfs=float(to_dbfs(np.mean(a2s))),
                 ref_snr_db=float(min(snrs)))


def _capture_live(radio, flush):
    a, b = radio.capture(flush=flush)
    if find_tone(a, radio.settings.fs)[1] > TONE_SNR_MIN_DB:
        return a, b
    radio.start_tone()
    a, b = radio.capture(flush=radio.settings.flush)
    if find_tone(a, radio.settings.fs)[1] > TONE_SNR_MIN_DB:
        return a, b
    raise RuntimeError(f"reference tone lost at {radio.rf / 1e9:.4f} GHz and did not "
                       "recover — check the TX1 → splitter → RX1 path")


def iter_sweep(radio, plan):
    """Yield one ``Point`` per frequency, as each is measured — the GUI draws live."""
    for rf in plan.frequencies():
        yield measure_point(radio, rf, plan.averages)


@dataclass
class SweepResult:
    plan: SweepPlan
    settings: RadioSettings
    points: list = field(default_factory=list)
    backend: str = ""
    started: str = ""
    duration_s: float = float("nan")

    @property
    def freq(self):
        return np.array([p.freq for p in self.points])

    @property
    def ratio(self):
        return np.array([p.ratio for p in self.points])

    def to_csv(self, path):
        """Raw data plus every setting it depends on, as ``# key = value`` header lines,
        so a later calibration can refuse data taken with different settings."""
        meta = {"plutovna_sweep": CSV_VERSION, "backend": self.backend,
                "started": self.started, "duration_s": f"{self.duration_s:.2f}"}
        meta.update({f"plan.{k}": v for k, v in dataclasses.asdict(self.plan).items()})
        meta.update({f"radio.{k}": v for k, v in dataclasses.asdict(self.settings).items()})
        with open(path, "w") as fh:
            for k, v in meta.items():
                fh.write(f"# {k} = {v}\n")
            fh.write("freq_hz,re,im,mag_db,phase_deg,sem,a1_dbfs,a2_dbfs,ref_snr_db\n")
            for p in self.points:
                fh.write(f"{p.freq:.0f},{p.ratio.real:.9e},{p.ratio.imag:.9e},"
                         f"{20 * np.log10(abs(p.ratio)):.4f},"
                         f"{np.angle(p.ratio, deg=True):.4f},{p.sem:.4e},"
                         f"{p.a1_dbfs:.2f},{p.a2_dbfs:.2f},{p.ref_snr_db:.1f}\n")

    @classmethod
    def from_csv(cls, path):
        meta = {}
        with open(path) as fh:
            for line in fh:
                if not line.startswith("#"):
                    break
                k, _, v = line[1:].partition("=")
                meta[k.strip()] = v.strip()
        d = np.atleast_1d(np.genfromtxt(path, delimiter=",", skip_header=len(meta),
                                        names=True))

        def parse(typ, v):
            if typ is tuple:
                return tuple(float(x) for x in v.strip("()").split(","))
            return typ(v)

        def fields(dc, prefix):
            return dc(**{f.name: parse(f.type, meta[f"{prefix}.{f.name}"])
                         for f in dataclasses.fields(dc)})

        pts = [Point(freq=float(r["freq_hz"]), ratio=complex(r["re"], r["im"]),
                     sem=float(r["sem"]), a1_dbfs=float(r["a1_dbfs"]),
                     a2_dbfs=float(r["a2_dbfs"]), ref_snr_db=float(r["ref_snr_db"]))
               for r in d]
        return cls(plan=fields(SweepPlan, "plan"), settings=fields(RadioSettings, "radio"),
                   points=pts, backend=meta.get("backend", ""),
                   started=meta.get("started", ""),
                   duration_s=float(meta.get("duration_s", "nan")))


def run_sweep(radio, plan, on_point=None):
    """Measure the whole plan into a ``SweepResult``; ``on_point(i, point)`` per point."""
    res = SweepResult(plan=plan, settings=radio.settings, backend=radio.uri,
                      started=time.strftime("%Y-%m-%dT%H:%M:%S"))
    t0 = time.monotonic()
    for i, p in enumerate(iter_sweep(radio, plan)):
        res.points.append(p)
        if on_point:
            on_point(i, p)
    res.duration_s = time.monotonic() - t0
    return res
