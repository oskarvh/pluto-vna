import dataclasses

import numpy as np
import pytest

from plutovna.cal import oneport
from plutovna.cal.standards import IDEAL, CalKit, Standard, load_kit
from plutovna.cal.state import CalMismatch, OnePortCal
from plutovna.hw.mock import MockPluto, error_terms
from plutovna.hw.pluto import RadioSettings
from plutovna.sweep import SweepPlan, run_sweep

F = np.linspace(2.5e9, 4.2e9, 41)


def test_ideal_standards():
    assert np.allclose(IDEAL["open"].gamma(F), 1)
    assert np.allclose(IDEAL["short"].gamma(F), -1)
    assert np.allclose(IDEAL["load"].gamma(F), 0)


def test_lossless_offset_is_pure_phase():
    tau = 30e-12
    g = Standard("short", delay=tau).gamma(F)
    assert np.allclose(g, -np.exp(-2j * 2 * np.pi * F * tau))


def test_open_capacitance():
    c = 50e-15
    g = Standard("open", poly=(c, 0, 0, 0)).gamma(F)
    z = 1 / (2j * np.pi * F * c)
    assert np.allclose(g, (z - 50) / (z + 50))
    assert np.allclose(np.abs(g), 1)


def test_lossy_offset_loses_magnitude():
    g = Standard("short", delay=50e-12, loss=2e9).gamma(F)
    assert np.all(np.abs(g) < 1)
    assert np.all(np.abs(g) > 0.98)


def test_load_kit(tmp_path):
    p = tmp_path / "kit.toml"
    p.write_text('name = "test"\n[open]\ndelay_ps = 29.2\nc0 = 49.4\nc1 = -310\n'
                 '[short]\nl0 = 2.08\n')
    kit = load_kit(p)
    assert kit.name == "test"
    assert kit["open"].delay == pytest.approx(29.2e-12)
    assert kit["open"].poly[:2] == pytest.approx((49.4e-15, -310e-27))
    assert kit["short"].poly[0] == pytest.approx(2.08e-12)
    assert np.allclose(kit["load"].gamma(F), 0)


def test_solve_recovers_error_terms_exactly():
    e = error_terms(F)
    gammas = [IDEAL[k].gamma(F) for k in ("open", "short", "load")]
    measured = [oneport.raw(g, *e) for g in gammas]
    for got, want in zip(oneport.solve(measured, gammas), e):
        assert np.allclose(got, want, atol=1e-12)


def test_solve_with_nonideal_kit_and_overdetermined():
    kit = CalKit("k", {"open": Standard("open", delay=20e-12, poly=(40e-15, 0, 0, 0)),
                       "short": Standard("short", delay=15e-12),
                       "load": Standard("load", r=52.0),
                       "offset_short": Standard("short", delay=60e-12)})
    e = error_terms(F)
    gammas = [s.gamma(F) for s in kit.standards.values()]
    measured = [oneport.raw(g, *e) for g in gammas]
    for got, want in zip(oneport.solve(measured, gammas), e):
        assert np.allclose(got, want, atol=1e-12)


def test_apply_inverts_raw():
    e = error_terms(F)
    g = 0.3 * np.exp(1j * F / 1e9)
    assert np.allclose(oneport.apply(oneport.raw(g, *e), *e), g)


def _cal_from_mock(settings, plan, seed=0):
    sweeps = {k: run_sweep(MockPluto(settings, dut=k, seed=seed + i), plan)
              for i, k in enumerate(("open", "short", "load"))}
    return OnePortCal.from_sweeps(sweeps, IDEAL)


def test_end_to_end_with_mock():
    s, plan = RadioSettings(n=4096), SweepPlan(2.5e9, 4.2e9, 21)
    cal = _cal_from_mock(s, plan)
    dut = 0.5 * np.exp(-1j * 0.7)
    gamma = cal.correct(run_sweep(MockPluto(s, dut=dut, seed=9), plan))
    assert np.allclose(gamma, dut, atol=0.02)


def test_refuses_mismatched_settings():
    s, plan = RadioSettings(n=4096), SweepPlan(2.5e9, 4.2e9, 5)
    cal = _cal_from_mock(s, plan)
    other = dataclasses.replace(s, rx_gain=(15.0, 15.0))
    with pytest.raises(CalMismatch, match="rx_gain"):
        cal.correct(run_sweep(MockPluto(other, dut="open"), plan))
    with pytest.raises(CalMismatch, match="points"):
        cal.correct(run_sweep(MockPluto(s, dut="open"), SweepPlan(2.5e9, 4.2e9, 6)))
    # Averaging only changes noise, so it is allowed.
    cal.correct(run_sweep(MockPluto(s, dut="open"), dataclasses.replace(plan, averages=2)))


def test_save_load_round_trip(tmp_path):
    cal = _cal_from_mock(RadioSettings(n=4096, rx_gain=(15.0, 15.0)),
                         SweepPlan(2.5e9, 4.2e9, 5))
    cal.save(tmp_path / "cal.npz")
    back = OnePortCal.load(tmp_path / "cal.npz")
    assert back.settings == cal.settings and back.plan == cal.plan
    for k in ("freq", "e00", "e11", "e10e01"):
        assert np.array_equal(getattr(back, k), getattr(cal, k))
