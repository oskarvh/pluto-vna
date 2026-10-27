"""A calibration: error terms plus the exact sweep settings they are valid for.

Applying a calibration to a sweep taken with different settings is refused, not fudged.
The repeats in scratch/initial_setup.md show why: changing only the RX gain shifts the
raw ratio by up to 0.45 dB / 3°, far above the calibration's own error floor.
"""

import dataclasses
import json
import time
from dataclasses import dataclass

import numpy as np

from plutovna.cal import oneport
from plutovna.hw.pluto import RadioSettings
from plutovna.sweep import SweepPlan


class CalMismatch(ValueError):
    pass


@dataclass
class OnePortCal:
    freq: np.ndarray
    e00: np.ndarray
    e11: np.ndarray
    e10e01: np.ndarray
    plan: SweepPlan
    settings: RadioSettings
    kit: str = "ideal"
    sources: dict = dataclasses.field(default_factory=dict)   # standard → file
    created: str = ""

    @classmethod
    def from_sweeps(cls, sweeps, kit, sources=None):
        """``sweeps`` maps standard name ("open", "short", "load", …) → SweepResult.
        Every sweep must share one plan and one set of radio settings."""
        first = next(iter(sweeps.values()))
        for name, s in sweeps.items():
            _check_same(first, s, f"standard {name!r}")
        f = first.freq
        measured = np.array([s.ratio for s in sweeps.values()])
        actual = np.array([kit[name].gamma(f) for name in sweeps])
        e00, e11, e10e01 = oneport.solve(measured, actual)
        return cls(freq=f, e00=e00, e11=e11, e10e01=e10e01, plan=first.plan,
                   settings=first.settings, kit=kit.name, sources=dict(sources or {}),
                   created=time.strftime("%Y-%m-%dT%H:%M:%S"))

    def correct(self, sweep):
        """Corrected Γ for a SweepResult taken with the same settings."""
        _check_same(self, sweep, "sweep")
        return oneport.apply(sweep.ratio, self.e00, self.e11, self.e10e01)

    def save(self, path):
        meta = {"plan": dataclasses.asdict(self.plan),
                "settings": dataclasses.asdict(self.settings),
                "kit": self.kit, "sources": self.sources, "created": self.created}
        np.savez(path, freq=self.freq, e00=self.e00, e11=self.e11, e10e01=self.e10e01,
                 meta=json.dumps(meta))

    @classmethod
    def load(cls, path):
        d = np.load(path)
        meta = json.loads(str(d["meta"]))
        settings = meta["settings"]
        settings["rx_gain"] = tuple(settings["rx_gain"])
        return cls(freq=d["freq"], e00=d["e00"], e11=d["e11"], e10e01=d["e10e01"],
                   plan=SweepPlan(**meta["plan"]), settings=RadioSettings(**settings),
                   kit=meta["kit"], sources=meta["sources"], created=meta["created"])


def _check_same(ref, other, what):
    diffs = []
    for label, a, b in (("plan", ref.plan, other.plan),
                        ("radio", ref.settings, other.settings)):
        for f in dataclasses.fields(a):
            if f.name == "averages":
                continue        # averaging changes noise, not the error terms
            va, vb = getattr(a, f.name), getattr(b, f.name)
            if va != vb:
                diffs.append(f"{label}.{f.name}: {va} vs {vb}")
    if diffs:
        raise CalMismatch(f"{what} was taken with different settings than the "
                          f"calibration — " + "; ".join(diffs))
