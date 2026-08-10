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

The whole test set follows from one rule (proved in §4): **a measurement is only valid as
a ratio of two receivers captured in the same buffer.** So one receiver is spent on a
permanent reference, and the other is the actual measurement input.

- **RX1 is always the reference** `a₁` — a tap off the source, taken *before* the DUT. It
  never moves.
- **RX2 is the measured wave**, and selects what you are characterising. Move that one
  cable between two positions:
  - **position ①** = coupler `CPL` → the wave coming *back* from the DUT (`b₁`) → **S11**
  - **position ②** = DUT far port → the wave *through* the DUT (`b₂`) → **S21**

Everything else stays bolted down. That single moved connector is precisely what a
commercial VNA does with an internal transfer switch; Phase 7 automates it (§6 Option B).

There is **no signal junction anywhere** in what follows. `○` marks an open SMA connector
and `┄┄` a loose cable end; the RX2 cable is a single cable that gets unscrewed from one
connector and screwed onto another.

```
   ADALM-PLUTO
  ┌───────────┐          ┌────────┐          ┌─────────────────┐
  │           │          │        │          │ S               │
  │    TX1 ●──┼─────────►│  8 dB  ├─────────►│      ZAPD-4     │
  │           │          │        │          │     splitter    │
  │           │          └────────┘          │  ①           ②  │
  │           │                              └──┬───────────┬──┘
  │           │       ┌────────┐                │           │
  │    RX1 ●◄─┼───────┤ 10 dB  │◄───────────────┘           │ source
  │           │       └────────┘   reference a₁             ▼
  │           │                    (never moves)  ┌─────────────────────┐
  │           │                                   │ OUT                 │
  │           │                                   │   ZADC-10-63-S+     │
  │           │                                   │  «« REVERSED »»     │
  │           │                                   │ CPL             IN  │
  │           │                                   └──┬──────────────┬───┘
  │           │       ┌────────┐                     ○ ①            ▼
  │    RX2 ●◄─┼───────┤  3 dB  ├┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄               DUT port 1
  │           │       └────────┘   loose end:                          ┆
  └───────────┘                    screw onto ① or ②             ( 2-port DUT )
                                                                       ┆
                                                     ○ ② ┄┄┄┄┄┄┄ DUT port 2
```

**Reversed** means the source enters the coupler at `OUT` and the DUT hangs off `IN`. That
is the whole reflectometer trick — see §3 for why the stock orientation measures the wrong
wave.

### Connection list

Every cable, explicitly. Six are permanent; number 7 is the only thing that ever moves.

| # | From | To |
|---|------|-----|
| 1 | Pluto `TX1` | 8 dB pad → ZAPD-4 `S` |
| 2 | ZAPD-4 `①` | 10 dB pad → Pluto `RX1` |
| 3 | ZAPD-4 `②` | Coupler `OUT` |
| 4 | Coupler `IN` | DUT port 1 |
| **7** | 3 dB pad → Pluto `RX2` | **`①` = coupler `CPL`, or `②` = DUT port 2** |

| Cable 7 on | Put 50 Ω on | Ratio RX2/RX1 | Gives | Cal |
|---|---|---|---|---|
| **① coupler `CPL`** | DUT port 2 | `b₁/a₁` | **S11** | SOL (short-open-load) |
| **② DUT port 2** | coupler `CPL` | `b₂/a₁` | **S21** | through + isolation |

Terminating the *unused* branch is not optional bookkeeping — in position ① an unterminated
DUT port 2 changes the load the DUT sees and therefore changes S11, and in position ② an
open `CPL` port degrades the coupler's directivity and its match toward the DUT.

For a **one-port DUT** (your open / short / load standards, an antenna, a filter you only
want return loss on) you only ever use position ①, and nothing needs terminating.

The cost of this single-coupler version: switching between S11 and S21 means unscrewing a
cable *at the DUT itself*, which disturbs the thing you are measuring and changes its port-2
termination. That is what a second coupler fixes.

## 5b. With a second coupler

A second coupler does **not** remove the need to select. Two receivers, one permanently
spent on the reference, leaves exactly one input for the measured wave — so one signal at a
time, regardless of how many couplers are in the box. Simultaneous S11+S21 needs a third
receiver, which the Pluto does not have.

What it does buy you is that **both DUT ports stay permanently connected and permanently
terminated**. You stop touching the DUT between measurements and swap at the coupler `CPL`
ports instead, well away from the reference plane. For repeatability and cal validity that
is a large gain — disturbing the DUT connector between the S11 and S21 sweeps is one of the
bigger error sources in the §5 arrangement.

```
   ADALM-PLUTO
  ┌───────────┐        ┌────────┐        ┌─────────────────┐
  │    TX1 ●──┼───────►│  8 dB  ├───────►│ S    ZAPD-4     │
  │           │        └────────┘        │  ①           ②  │
  │           │      ┌────────┐          └──┬───────────┬──┘
  │    RX1 ●◄─┼──────┤ 10 dB  │◄────────────┘           │
  │           │      └────────┘  reference a₁           ▼
  │           │                            ┌─────────────────────┐
  │           │                            │ OUT   COUPLER F     │
  │           │                            │      (reversed)     │
  │           │                            │ CPL             IN  ├──► DUT port 1
  │           │                            └──┬──────────────────┘        ┆
  │           │                               ○ ①                    ( 2-port DUT )
  │           │      ┌────────┐                                           ┆
  │    RX2 ●◄─┼──────┤  3 dB  ├┄┄┄┄ loose end: screw onto ① or ②      DUT port 2
  │           │      └────────┘                                           │
  └───────────┘                            ┌─────────────────────┐        │
                                           │ OUT   COUPLER R     │        │
                                  [50 Ω]◄──┤      (reversed)     │        │
                                           │ CPL             IN  │◄───────┘
                                           └──┬──────────────────┘
                                              ○ ②
```

Coupler R is reversed too, so its `CPL` samples the wave *leaving* DUT port 2 — which is
`b₂`, exactly what S21 needs — while its mainline runs into a 50 Ω load that becomes the
DUT's permanent, well-matched port-2 termination.

| # | From | To |
|---|------|-----|
| 1 | Pluto `TX1` | 8 dB pad → ZAPD-4 `S` |
| 2 | ZAPD-4 `①` | 10 dB pad → Pluto `RX1` |
| 3 | ZAPD-4 `②` | Coupler F `OUT` |
| 4 | Coupler F `IN` | DUT port 1 |
| 5 | DUT port 2 | Coupler R `IN` |
| 6 | Coupler R `OUT` | 50 Ω termination |
| **7** | 3 dB pad → Pluto `RX2` | **`①` = Coupler F `CPL`, or `②` = Coupler R `CPL`** |

Put a 50 Ω termination on whichever `CPL` is idle — an open coupled port reflects back into
the coupler and costs you directivity.

Two further payoffs:

- **This is the switch-ready arrangement.** Replace the cable-7 swap with one absorptive
  SPDT and S11/S21 becomes automatic (Phase 7). Add a second SPDT on the source side and
  you have all four parameters — §6 Option B is exactly this diagram with switches.
- Nothing about the DUT connection differs between the S11 and S21 sweeps, so a single
  physical setup covers both.

### The alternative: skip the splitter instead

With two couplers you can only cover two of the three taps (reference, port 1, port 2). The
other way to spend them is to drop the ZAPD-4 and use a coupler in **forward** orientation
as the reference tap:

| | Reference tap | Port-1 tap | Port-2 tap | Band | DUT touched? |
|---|---|---|---|---|---|
| **§5b above** | ZAPD-4 | Coupler F | Coupler R | 2.5–4.2 GHz | no |
| **alternative** | Coupler A (forward) | Coupler B | — (RX2 direct) | **2.5–6 GHz** | yes |

The alternative widens the band to the full coupler range and loses ~3 dB less source power
(0.6 dB mainline loss versus 3.5 dB through the splitter), but port 2 goes straight into
RX2's mediocre match and you are back to unscrewing cables at the DUT.

Given the project goal is two-port characterisation, **§5b is the better buy**. Three
couplers eventually gives you both: reference, port 1 and port 2 all coupled, 2.5–6 GHz,
no splitter.

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
