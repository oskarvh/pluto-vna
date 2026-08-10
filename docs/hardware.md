# Hardware

## 1. What we have

| Part | Model | Spec |
|------|-------|------|
| SDR | ADALM-PLUTO Rev.C, Z7010-**AD9363A**, fw v0.32 | 325–3800 MHz stock; 70–6000 MHz after firmware env change |
| Coupler | Mini-Circuits **ZADC-10-63-S+** | **2500–6000 MHz**, coupling ≈11.7 dB typ, directivity 17–21 dB typ (13 dB min @3.5 GHz), mainline loss 0.5–0.7 dB |
| Attenuator | Mini-Circuits 15542 | 8 dB |
| Splitter | Mini-Circuits **ZAPD-4** | **2000–4200 MHz**, 2-way, ≈3.5 dB/arm, 19 dB isolation |
| Standards | Open, Short, 50 Ω load | one-port, characterisation TBD |

XO correction reads `40000008`, i.e. the 40 MHz reference is within ~0.2 ppm. Frequency
accuracy is a non-issue for a VNA anyway — TX and RX share the same XO, so the tone lands
exactly in the bin we expect.

### Usable frequency band

```
Pluto (after ad9361 compat) │ 70 MHz ────────────────────────── 6000 MHz
ZADC-10-63-S+               │            2500 ──────────────── 6000 MHz
ZAPD-4                      │       2000 ─────────── 4200 MHz
                            └─────────── USABLE: 2500 – 4200 MHz ──────
```

Without the ZAPD-4 in the path the band opens to 2500–6000 MHz (Pluto performance well
outside AD9363 spec above 3.8 GHz — expect falling output power and rising noise figure,
but it is still perfectly usable for *ratiometric* measurements, which is all a VNA does).

Below 2.5 GHz the coupler's directivity collapses and results will be meaningless. If you
want 70 MHz–2.5 GHz coverage later, a wideband resistive-bridge reflectometer or a
0.5–6 GHz coupler is the part to buy.

## 2. Required firmware change — 2R2T ✅ done

**This blocked everything.** Applied and verified — see [setup.md](setup.md) for the exact
commands, the reverting recipe, and the before/after table. The context now reports
`Z7010-AD9361` with `voltage0..3` on the RX DMA, TX2 DDS tones, and a 70 MHz–6 GHz LO
range. Original U-Boot environment backed up in
[`hardware/uboot_env_backup.txt`](../hardware/uboot_env_backup.txt).

The pre-change state, for reference — the IIO context exposed only one RX data channel
pair:

```
cf-ad9361-lpc          : voltage0, voltage1          ← I/Q of ONE receiver
cf-ad9361-dds-core-lpc : voltage0, voltage1, TX1_*   ← ONE transmitter
```

RX2 was physically wired but had no software channel.

Max sample rate halves to 30.72 MSPS in 2R2T. Irrelevant here — we run at 2–10 MSPS with a
very narrow IF filter.

## 3. Current cabling — what it actually measures

```
                                   ┌──────────────┐
  TX1 ──[8 dB]────────────────────►│ IN           │
                                   │   ZADC-10    │
  RX1 ◄────────────────────────────┤ CPL          │
                                   │              │
  RX2 ◄──────────[DUT]─────────────┤ OUT          │
                                   └──────────────┘
```

A directional coupler's `CPL` port is coupled to the **IN→OUT (forward)** wave. So as
cabled:

- **RX1 sees the incident wave** at −11.7 dB. It is a *reference channel*, not a
  reflection channel.
- The DUT's reflection travels OUT→IN, which couples into the coupler's internally
  terminated port. It reaches `CPL` only through the finite directivity, ≈19 dB down.

Consequence: this wiring is a perfectly good **transmission test set** (RX1 = reference
a₁, RX2 = transmitted b₂ → S21 = RX2/RX1). It is a *poor* reflectometer: a short and a
matched load differ by only ~1 dB / ~6° at RX1. A 3-term error model can technically dig
the reflection back out, but with the directivity error term 19 dB *larger* than the
signal, accuracy is drift-limited and the result will be unstable.

**Measured, 3.0 GHz, one-port standard on the DUT connector:** RX1 = −27.4 dBFS,
RX2 = −71.4 dBFS, i.e. RX2 sits **44 dB below RX1**. That is the expected signature: RX1
is receiving the coupled forward wave at full strength while RX2, sitting behind a
one-port standard that passes nothing, sees only leakage. Confirms the analysis above.

**Fix: reverse the coupler.** Feed `OUT`, hang the DUT on `IN`. Now the DUT→source
(reflected) wave is the forward direction, `CPL` samples it at −11.7 dB, and the incident
wave leaks in 19 dB down. Same parts, one cable swap, ~38 dB improvement in raw
directivity.

## 4. Why a reference channel is probably mandatory

The AD9363 has **separate TX and RX LO synthesisers**. They are locked to the same 40 MHz
XO, so they are the same *frequency*, but their relative *phase* after each retune is
arbitrary. A stepped-frequency sweep retunes at every point, so the absolute phase of a
TX→RX path is expected to be random per point — and different again during the
calibration sweep. That would destroy phase, and therefore the Smith chart.

Both RX channels, however, share one RX LO and one ADC clock and are read from a single
interleaved DMA buffer. In the **ratio RX2/RX1** the RX LO phase cancels, and the TX LO
phase appears identically in numerator and denominator so it cancels too. The ratio is
deterministic and repeatable.

**Every measured quantity must therefore be a ratio of two simultaneously captured RX
channels.** With 2 receivers that is exactly one ratio per cabling configuration.

### Measured — the prediction holds

`tools/bringup.py phasegate`, 15–25 trials per frequency, LO parked at 2.4 GHz and retuned
back between every trial:

| RF | circ-std ∠A₁ | circ-std ∠A₂ | **circ-std ∠(A₂/A₁)** | \|A₂/A₁\| spread |
|----|----|----|----|----|
| 2.60 GHz | 86–97° | 85–96° | **2.8–3.2°** | 2.27 dB |
| 3.00 GHz | 88–157° | 87–155° | **1.20–1.27°** | 0.37 dB |
| 3.50 GHz | 108–164° | 108–165° | **3.46–3.58°** | 1.44 dB |

Per-channel absolute phase is essentially uniform on the circle — unusable. The ratio is
stable to a couple of degrees. **The reference-channel topology in §5 is mandatory**, and
the ZAPD-4 is a required part, not an optional one.

The residual 1–3° is receiver noise, not method error: RX2 is looking at a 44 dB-down
leakage path here. It is tightest at 3.0 GHz where RX2's SNR is best, which is the
signature of a noise-limited measurement. With RX2 carrying a proper coupled signal the
residual will be far smaller.

## 5. Recommended topology

The ZAPD-4 provides the reference channel. **Reflection configuration:**

```
                    ┌─────────────┐
 TX1 ──[8 dB]──────►│ S   ZAPD-4  │
                    │             ├──► arm1 ──[10 dB]──► RX1   a₁  (reference)
                    └──────┬──────┘
                           │ arm2
                    ┌──────▼──────┐
                    │ OUT         │
                    │   ZADC-10   │
                    │   (REVERSED)│
                    │ CPL ────────┼──[3 dB]──────────► RX2   b₁  (reflected)
                    │ IN          │
                    └──────┬──────┘
                           ▼
                      DUT (port 1)          →  S11 = (RX2/RX1) after SOL cal
```

**Transmission configuration** — move exactly one cable: RX2 goes from `CPL` to the DUT's
far port, and `CPL` gets a 50 Ω termination:

```
 ... same source chain ...
                    │ CPL ──[50 Ω]
                    │ IN ──► DUT port 1 ──► DUT port 2 ──[3 dB]──► RX2   b₂
                                                 →  S21 = (RX2/RX1) after through cal
```

That single moved connector is what a real VNA does with an internal switch; Phase 7
automates it.

### Level budget (2.5–4 GHz, TX at ≈0 dBm at the connector)

| Node | Level |
|------|-------|
| TX1 output | 0 dBm |
| after 8 dB pad | −8 dBm |
| ZAPD-4 arm (−3.5 dB) | −11.5 dBm |
| **RX1** after 10 dB pad | **−21.5 dBm** ✔ |
| incident at DUT (coupler mainline −0.6 dB) | −12 dBm |
| reflected from a short, at `CPL` (−11.7 dB) | −24 dBm |
| **RX2** after 3 dB pad | **−27 dBm** ✔ |

Pluto RX absolute max is about +2.5 dBm; keep working levels ≤ −15 dBm for linearity.
The extra pads are not optional decoration — a bare Pluto RX port has poor return loss,
and re-reflections between it and the coupler are a first-order source of sweep ripple.
Every pad you add to an RX input doubles its effective match improvement.

Buy list for this configuration: 2× SMA pads (10 dB, 3 dB), 1× SMA 50 Ω termination, and
enough phase-stable SMA cables that nothing has to flex between the cal and the
measurement. **Cable flexing between cal and DUT is the dominant error source in this
class of instrument** — dress the cables and leave them alone.

## 6. Hardware for S21/S22 (the "future work" question)

Full two-port needs the stimulus applied from *both* ends. Three options, cheapest first.

### Option A — manual DUT reversal (free, do this first)

Measure S11 and S21. Physically turn the DUT around. Measure again — those readings are
S22 and S12. Combine into a full 8-term ("SOLT") correction offline. This yields a
genuinely full two-port result, correcting source match, load match and tracking on both
sides. The only cost is that the DUT gets handled between halves, and reciprocal DUTs
(S12 = S21) let you sanity-check the result. **Recommended for Phase 6 — no purchases.**

### Option B — second coupler + two absorptive SPDT switches (recommended end state)

```
                            ┌──────────────────────────────► RX1  (a, reference)
 TX1 ─[8 dB]─ ZAPD-4 ───────┤
                            │        ┌──────────┐
                            └─ SW-A ─┤ Coupler F│ OUT→IN ──► DUT port 1
                              (SPDT) │   CPL ───┼──┐
                              absorp.│          │  │
                                     └──────────┘  │
                                     ┌──────────┐  │
                              └──────┤ Coupler R│  │
                                     │ OUT→IN ──┼──┼──────► DUT port 2
                                     │   CPL ───┼──┤
                                     └──────────┘  │
                                                   └─ SW-B (SPDT, absorptive) ─► RX2
```

Both couplers are wired **reversed** (source into `OUT`, DUT on `IN`), so each `CPL`
samples the wave *leaving* the DUT port it is attached to. That is the whole trick:

| SW-A (source) | SW-B (receiver) | RX2/RX1 gives |
|---------------|-----------------|---------------|
| Coupler F | Coupler F CPL | b₁/a₁ → **S11** |
| Coupler F | Coupler R CPL | b₂/a₁ → **S21** |
| Coupler R | Coupler R CPL | b₂/a₂ → **S22** |
| Coupler R | Coupler F CPL | b₁/a₂ → **S12** |

All four parameters, no recabling, DUT never touched. The switches **must be absorptive**
(reflective switches leave the idle path unterminated, which wrecks the load match seen by
the DUT).

Parts:
- 1× ZADC-10-63-S+ (identical second coupler — matching parts simplifies cal)
- 2× absorptive SPDT, DC–5 GHz, TTL-controlled — e.g. Mini-Circuits **ZASWA-2-50DR+**
- 1× SMA 50 Ω termination, pads as in §5

Switch control: the AD9363 has GPO pins reachable through the ad9361-phy debug interface
(`/sys/kernel/debug/iio/iio:device0/gpo_set`) — elegant, no extra USB device, but needs
checking that the Pluto breaks those pins out. Fallback: any USB GPIO (FT232H bitbang, a
Pi Pico running a 3-line serial protocol, or a USB relay board). Budget ~$200–350 total,
dominated by the switches.

### Option C — drive the DUT from TX2

The board mod already exposes TX2, and both transmitters share one TX LO, so they are
phase-coherent. Feeding port 2 from TX2 removes the source switch (SW-A). Attractive, but
it still needs the second coupler and the receiver switch, and you must characterise two
different source chains instead of one. Only worth it if switches are hard to get — the
switch route reuses one calibrated source path, which is easier to make accurate.

## 7. Practical notes

- **Fixed manual gain, never AGC.** AGC changes the receiver gain mid-sweep and destroys
  amplitude accuracy. Pick a gain that keeps the strongest signal ≥15 dB below clipping
  and leave it for the whole sweep *and* the cal.
- **Let it warm up.** Give the Pluto 10–15 minutes before calibrating; the XO and the
  AD9363 gain drift while warming, and cal drift is directly measurement error.
- **Recalibrate whenever anything moves.** Cables, temperature, gain settings, IF
  frequency — all invalidate the cal.
- **Characterise the standards eventually.** "Open / short / load" as bare SMA parts have
  real offset delay and fringing capacitance. Ideal models are fine to start; at 4 GHz an
  uncharacterised open can be tens of degrees off. Phase 3 includes a cal-kit file so
  those coefficients can be filled in later without touching code.
