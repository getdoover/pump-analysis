import pytest

from pump_analysis_common.curve import CurvePoint, PumpCurve
from pump_analysis_common.engine import AlertState, FlowSource, Readings, SiteParams, analyse
from pump_analysis_common.totaliser import (
    TotaliserState,
    Usage,
    local_date,
    step,
)

CURVE = PumpCurve(
    [CurvePoint(0, 20), CurvePoint(1000, 15), CurvePoint(2000, 5)], reference_rpm=600
)
FIXED = SiteParams(fixed_head_m=10.0, min_running_rpm=100)


def test_fixed_head_infers_flow_without_pressures():
    r = analyse(Readings(None, None, engine_rpm=600), CURVE, FIXED)
    assert r.state is AlertState.OK
    assert r.tdh_m == 10.0
    assert r.flow_source is FlowSource.INFERRED
    assert r.flow_m3h == pytest.approx(1500)
    assert r.npsha_m is None


def test_fixed_head_beyond_curve_runout_is_config_fault():
    r = analyse(Readings(None, None, engine_rpm=600), CURVE, SiteParams(fixed_head_m=2.0))
    assert r.state is AlertState.CONFIG_FAULT
    assert r.flow_m3h is None


def test_fixed_head_too_slow_to_lift_is_zero_flow():
    r = analyse(Readings(None, None, engine_rpm=300), CURVE, FIXED)  # shutoff 5 m < 10 m
    assert r.state is AlertState.OK
    assert r.flow_m3h == 0.0


def test_disengaged_pump_is_not_running():
    r = analyse(Readings(None, None, engine_rpm=600, pump_engaged=False), CURVE, FIXED)
    assert r.state is AlertState.NOT_RUNNING


def test_fixed_speed_pump_runs_off_engaged_tag_with_measured_flow():
    p = SiteParams(fixed_head_m=6.0, speed_optional=True)
    on = analyse(Readings(None, None, engine_rpm=None, flow_measured_m3h=1500, pump_engaged=True), None, p)
    off = analyse(Readings(None, None, engine_rpm=None, flow_measured_m3h=0, pump_engaged=False), None, p)
    assert on.state is AlertState.OK and on.flow_m3h == 1500 and on.pump_rpm is None
    assert off.state is AlertState.NOT_RUNNING


def _run(samples, gap_s=1800):
    s = TotaliserState()
    for ts, usage in samples:
        s = step(s, usage, now_ts=ts, local_date="2026-11-09", max_gap_s=gap_s)
    return s


def test_hour_meter_integration_and_fuel_per_ml():
    s = _run([
        (0, Usage(flow_m3h=0, fuel_lph=0, engine_hours=10.0)),
        (900, Usage(flow_m3h=2000, fuel_lph=10, engine_hours=10.25)),
        (1800, Usage(flow_m3h=2000, fuel_lph=10, engine_hours=10.5)),
        (2700, Usage(flow_m3h=0, fuel_lph=0, engine_hours=10.75)),  # stopped
    ])
    # 0.75 h at 2000 m3/h and 10 L/h -> 1.5 ML for 7.5 L
    assert s.today.volume_ml == pytest.approx(1.5)
    assert s.today.run_hours == pytest.approx(0.75)
    assert s.today.per_ml(s.today.fuel_l) == pytest.approx(5.0)


def test_stale_speed_does_not_accumulate_without_hour_meter_movement():
    s = _run([(t, Usage(flow_m3h=2000, engine_hours=10.0)) for t in range(0, 36000, 900)])
    assert s.total.volume_ml == 0


def test_wall_clock_gap_is_capped():
    s = _run([(0, Usage(flow_m3h=1000)), (7200, Usage(flow_m3h=1000))], gap_s=1800)
    assert s.total.volume_ml == pytest.approx(0.5)


def test_today_rolls_over_and_state_round_trips():
    s = _run([(0, Usage(flow_m3h=1000, engine_hours=1.0)), (3600, Usage(flow_m3h=1000, engine_hours=1.5))])
    s = TotaliserState.from_dict(s.to_dict())
    s = step(s, Usage(flow_m3h=1000, engine_hours=2.0), now_ts=7200,
             local_date="2026-11-10", max_gap_s=1800)
    assert s.today.volume_ml == pytest.approx(0.5)
    assert s.total.volume_ml == pytest.approx(1.0)


def test_local_date_uses_timezone():
    # 2026-11-09 15:00 UTC is already the 10th in Brisbane (UTC+10)
    ts = 1794236400
    assert local_date("Australia/Brisbane", ts) == "2026-11-10"
    assert local_date("Not/AZone", ts) == "2026-11-09"
