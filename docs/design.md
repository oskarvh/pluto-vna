# Design

How the instrument works and how the code is laid out. Hardware and RF topology live in
[hardware.md](hardware.md).

## 1. Measurement primitive

One frequency point, one measurement:

1. **Tune.** Set `TX_LO = RX_LO = f_target − f_IF`. Emit a CW tone from the FPGA's TX DDS
   at baseband frequency `f_IF` (≈1 MHz), so the RF output sits at exactly `f_target` and
   comes back down to a baseband tone at `+f_IF`.
   *Why an offset IF and not DC:* a tone at DC sits on top of LO leakage, ADC DC offset
   and 1/f noise. An offset IF moves the measurement away from all three, at zero cost.
   *Why the DDS and not a host TX buffer:* no streaming, no underruns, no TX-side timing
   to reason about. The tone is generated in the FPGA and is rock-steady.
2. **Settle.** Discard the first buffer(s) after a retune — PLL lock, RX filter transient,
   and stale DMA contents.
3. **Capture.** Read `N` samples from *both* receivers as one interleaved buffer. Single
   buffer ⇒ guaranteed sample alignment between channels, which is the whole basis for the
   ratio being meaningful (see hardware.md §4).
4. **Estimate.** Locate the tone by FFT peak plus parabolic interpolation, then take the
   inner product of each channel with an exponential at *that* frequency, giving complex
   amplitudes `A₁`, `A₂`.
   *Why measured and not nominal:* the AD9361 DDS quantizes its output — asking for
   1 000 000 Hz gets 999 953 Hz. A fixed-bin estimator sits off the tone and reads noise,
   which is exactly how the first bring-up attempt failed. Correlating at the measured
   frequency also absorbs any residual LO offset.
   *Why leakage doesn't matter:* both channels are correlated against the same reference
   exponential, so whatever scalloping or leakage this incurs is a common factor that
   divides out in step 5. Only noise survives.
5. **Ratio.** `m = A₂ / A₁`. This is the raw (uncorrected) measurement.
6. **Average.** Repeat M times and average the *complex ratios*. Coherent averaging, so
   noise falls as √M while the signal is untouched.

### IF bandwidth, dynamic range, speed

Effective noise bandwidth is `f_s/N` — the direct analogue of a VNA's "IF bandwidth".

| f_s | N | IF BW | Capture time |
|-----|---|-------|--------------|
| 4 MSPS | 4096 | 977 Hz | 1.0 ms |
| 4 MSPS | 65536 | 61 Hz | 16 ms |
| 2 MSPS | 65536 | 31 Hz | 33 ms |

Thermal noise is not the limit at these bandwidths — receiver spurs and TX→RX crosstalk
inside the AD9363 are. Expect a usable dynamic range in the 60–80 dB region; the isolation
cal (§3) is what pushes the high-attenuation end.

Budget ≈20–30 ms per point including retune, so a 201-point sweep lands around 5 s. Fast
enough to be pleasant, slow enough that Phase 7's multi-tone sweep is worth doing later.

Exposed to the user as an "IF bandwidth" control (sets `N`) plus an "averaging" control
(sets `M`) — the same knobs a commercial VNA offers, and the same tradeoff.

## 2. Error model — one port

The raw ratio `m` relates to the true reflection coefficient `Γ` by the standard 3-term
model:

```
        e₁₀e₀₁ · Γ
m = e₀₀ + ──────────
        1 − e₁₁ · Γ
```

- `e₀₀` — **directivity**: incident signal leaking into the reflected path. Dominated by
  the coupler's finite directivity, which is why coupler orientation matters so much.
- `e₁₁` — **source match**: what the DUT sees looking back at the instrument. The 8 dB pad
  exists to improve this.
- `e₁₀e₀₁` — **reflection tracking**: everything frequency-dependent in the path.

Rearranged into the linear-in-unknowns form used by the solver, with `Δ = e₀₀e₁₁ − e₁₀e₀₁`:

```
m = e₀₀ + Γ·m·e₁₁ − Γ·Δ
```

Three standards (short, open, load) give three equations per frequency point — solve the
3×3 complex linear system directly, per point. Then correct every subsequent measurement:

```
        m − e₀₀
Γ = ──────────────
    m·e₁₁ − Δ
```

Standards are described by a **cal-kit file**, not hardcoded: each standard is an offset
transmission line (delay, loss, Z₀) terminated in a polynomial-in-frequency model —
fringing capacitance `C₀..C₃` for the open, inductance `L₀..L₃` for the short. Ideal
coefficients to start; measured ones dropped in later without touching code. At 4 GHz a
few picoseconds of uncharacterised offset delay is tens of degrees of phase error, so this
matters more than it sounds.

## 3. Error model — transmission

- **Response (normalisation):** `S21 = m_dut / m_thru`. Simple, and correct when both DUT
  ports are well matched.
- **Isolation:** measure with both ports terminated to capture TX→RX crosstalk; subtract
  it. Only matters for DUTs with >40 dB attenuation, but it is nearly free to collect.
- **Enhanced response:** additionally corrects source match using the reflection error
  terms — worth having, since it costs only the S11 cal we already have.

## 4. Full two-port (Phase 6)

With manual DUT reversal we get two half-sweeps: forward (S11, S21) and reverse (S22,
S12). Together with a full SOLT cal on both port definitions, that is the classic 8-term
error model, solvable exactly. Reciprocal DUTs give a free consistency check
(S12 should equal S21).

Phase 7's switched test set produces the same four measurements without touching the DUT;
the correction maths is identical, so Phase 6's solver is written to be reused verbatim.

## 5. Software architecture

```
plutovna/
  hw/
    pluto.py        Context open, LO/gain/sample-rate control, DDS tone,
                    coherent dual-RX capture. The only file that imports adi/iio.
    mock.py         Synthetic backend — a simulated DUT behind a simulated error
                    box, so cal maths and GUI are testable with no hardware attached.
  dsp/
    tone.py         Coherent single-bin DFT, complex averaging, SNR estimate.
  sweep.py          Sweep engine: frequency plan → list of raw ratios. Runs on a
                    worker thread, emits points as they arrive so the GUI draws live.
  cal/
    standards.py    Cal-kit models (offset line + open C / short L polynomials).
    oneport.py      3-term SOL solve and apply.
    twoport.py      Response / enhanced response / 8-term SOLT.
    state.py        Cal state: error terms + the exact sweep settings they are valid
                    for. Applying a cal to a mismatched sweep is refused, not fudged.
  io/
    touchstone.py   .s1p / .s2p read+write (via scikit-rf).
    session.py      Save/load sweeps and cal states.
  gui/
    main.py         PyQt6 main window, sweep control panel.
    traces.py       pyqtgraph rectangular plots: logmag, phase, VSWR, group delay.
    smith.py        Smith chart widget (constant-R/X arc grid, markers, drawn on
                    pyqtgraph for the same interaction model as the other plots).
    calwizard.py    Step-by-step "connect short / open / load / through" flow.
  cli.py            Headless sweep — the bring-up and scripting entry point.
```

Design rules worth stating up front:

- **`hw/pluto.py` is the only hardware-aware module.** Everything above it consumes plain
  numpy arrays, so the mock backend exercises the entire stack. Cal maths gets unit tests
  with exactly known error boxes — a class of bug that is otherwise almost impossible to
  find by staring at a Smith chart.
- **Raw and corrected data are both kept.** Recalculating with a different cal, or
  re-examining a suspicious trace, must never require re-sweeping.
- **A cal state carries the sweep settings it was taken with.** Frequency plan, IF
  bandwidth, gains, IF frequency. Mismatch is an error, not a silent wrong answer.
- **Headless first.** The CLI produces the same corrected data as the GUI; the GUI is a
  view on top, not the place logic lives.

### Stack

Python 3.12 + venv. `libiio` and `python3-libiio` from apt (0.25), then `pyadi-iio`,
`numpy`, `scipy`, `scikit-rf`, `PyQt6`, `pyqtgraph` from pip.

pyqtgraph over matplotlib for the plots: live sweep updates need to redraw at ~10 Hz
without stuttering, and pyqtgraph handles pan/zoom/markers natively. The Smith chart is a
custom widget — the arc grid is a handful of precomputed circles, and building it on
pyqtgraph keeps interaction consistent with the other traces rather than embedding a
second, differently-behaving plotting toolkit.

## 6. Phase 1 experiment — the topology gate ✅ resolved

Run via `tools/bringup.py phasegate`. **Result: LO phase is random per retune and cancels
only in the ratio** — per-channel circular std 86–164°, ratio 1.2–3.6°. Full numbers in
hardware.md §4.

Consequence, now binding on everything downstream: **the reference-channel topology is
mandatory** and the ZAPD-4 is a required part. Usable band 2.5–4.2 GHz. No measured
quantity may be anything other than a ratio of two simultaneously captured receivers.

Still worth logging when the real test set is cabled: phase drift over 10 minutes at fixed
LO (tells us how often recalibration is needed) and residual phase noise per capture (sets
the achievable IF bandwidth).

## 7. Hardware quirks the code has to absorb

Found during bring-up; all of these are handled in `tools/bringup.py` and move into
`hw/pluto.py` in Phase 2.

- **The TX comes up muted about two thirds of the time** after a fresh IIO context. Every
  DDS and phy register reads back correct — frequency, scale, `raw=1`, gain, LO, no
  powerdown — and a full attribute diff between a working and a dead instance shows *no*
  difference except downstream consequences (RSSI, die temperature). It is chip-internal
  state, not something we are failing to write.
  Re-issuing the DDS alone never recovers it (0/8). Cycling the ENSM `alert`→`fdd` and
  *then* re-issuing the DDS does. So startup always **verifies the tone is radiating**
  rather than trusting registers, and kicks the ENSM until it is: 10/10 cold starts, ~1.15 s.
  A VNA whose source silently dies mid-sweep would produce plausible-looking garbage, so
  this check stays in permanently, not just during bring-up.
- **Tone presence must be judged on the reference channel**, which is strong by
  construction whatever the DUT does. The live/dead split is cleanly bimodal (~78 dB vs
  ~25 dB SNR); note that a *dead* channel still reads ~25 dB by this metric because the
  maximum of N noise bins sits well above their median — a naive threshold passes dead
  transmitters, which it initially did.
- **The DDS quantizes tone frequency** (§1 step 4).
- **Buffers must be flushed after a retune** — the first reads back stale DMA contents.

## 8. Deliberately deferred

- Time domain / gating (an IFFT of the frequency sweep — cheap to add once sweeps are
  trustworthy, and genuinely useful for locating faults along a line)
- Multi-tone comb sweep (measure a whole 20 MHz segment per LO retune; ~10× faster)
- Sub-2.5 GHz coverage (needs a different reflectometer — see hardware.md §1)
- Automated switching (Phase 7)
