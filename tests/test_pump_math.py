"""Golden tests for the pure hydraulic maths — hand-worked reference values."""

import math

import pytest

from pump_analysis_common import pump_math as pm
from pump_analysis_common.curve import CurvePoint, PumpCurve
from pump_analysis_common.engine import (
    AlertState,
    FlowSource,
    Readings,
    Results,
    SiteParams,
    analyse,
)


class TestProperties:
    def test_vapour_pressure_at_20c(self):
        # Reference: 2.339 kPa at 20 °C
        assert pm.water_vapour_pressure_kpa(20.0) == pytest.approx(2.339, abs=0.005)

    def test_vapour_pressure_at_30c(self):
        # Reference: 4.246 kPa at 30 °C
        assert pm.water_vapour_pressure_kpa(30.0) == pytest.approx(4.246, abs=0.01)

    def test_density_at_20c(self):
        assert pm.water_density_kg_m3(20.0) == pytest.approx(998.2, abs=0.1)

    def test_density_at_4c_is_maximum(self):
        assert pm.water_density_kg_m3(4.0) == pytest.approx(1000.0, abs=0.05)

    def test_barometric_sea_level(self):
        assert pm.barometric_pressure_kpa(0.0) == pytest.approx(101.325)

    def test_barometric_at_500m(self):
        # ~95.46 kPa at 500 m standard atmosphere
        assert pm.barometric_pressure_kpa(500.0) == pytest.approx(95.46, abs=0.05)


class TestScaling:
    def test_4_20_midpoint(self):
        assert pm.scale_4_20ma(12.0, -1.0, 10.0) == pytest.approx(4.5)

    def test_4ma_is_range_low(self):
        assert pm.scale_4_20ma(4.0, -1.0, 10.0) == pytest.approx(-1.0)

    def test_20ma_is_range_high(self):
        assert pm.scale_4_20ma(20.0, -1.0, 10.0) == pytest.approx(10.0)

    def test_droop_band_clamps_to_low(self):
        assert pm.scale_4_20ma(3.9, 0.0, 16.0) == pytest.approx(0.0)

    def test_fault_low_is_none(self):
        assert pm.scale_4_20ma(2.0, -1.0, 10.0) is None

    def test_fault_high_is_none(self):
        assert pm.scale_4_20ma(21.5, -1.0, 10.0) is None

    def test_none_passthrough(self):
        assert pm.scale_4_20ma(None, -1.0, 10.0) is None


class TestHeads:
    def test_tdh_pressure_only(self):
        # ΔP = 4.5 bar = 450 kPa at 20 °C water: 450000/(998.2*9.80665) ≈ 45.97 m
        tdh = pm.total_differential_head_m(-30.0, 420.0, 998.2)
        assert tdh == pytest.approx(45.97, abs=0.02)

    def test_tdh_includes_gauge_separation(self):
        base = pm.total_differential_head_m(0.0, 100.0, 998.2)
        raised = pm.total_differential_head_m(
            0.0, 100.0, 998.2, gauge_separation_m=1.5
        )
        assert raised - base == pytest.approx(1.5)

    def test_npsha_hand_worked(self):
        # -0.3 bar g suction, sea level, 20 °C:
        # (101.325 - 30 - 2.339) kPa = 68.986 kPa → 68986/(998.2*9.80665) ≈ 7.047 m
        npsha = pm.npsh_available_m(-30.0, 101.325, 2.339, 998.2)
        assert npsha == pytest.approx(7.047, abs=0.01)

    def test_npsha_gauge_height_adds(self):
        low = pm.npsh_available_m(-30.0, 101.325, 2.339, 998.2)
        high = pm.npsh_available_m(
            -30.0, 101.325, 2.339, 998.2, gauge_height_above_impeller_m=0.8
        )
        assert high - low == pytest.approx(0.8)

    def test_velocity(self):
        # 100 m³/h through DN100 (ID 100 mm): v = (100/3600)/(π·0.05²) ≈ 3.54 m/s
        v = pm.velocity_m_s(100.0, 100.0)
        assert v == pytest.approx(3.537, abs=0.005)
        assert pm.velocity_m_s(None, 100.0) == 0.0
        assert pm.velocity_m_s(100.0, None) == 0.0


REF_CURVE = PumpCurve(
    points=[
        CurvePoint(0.0, 60.0, 2.0),
        CurvePoint(50.0, 55.0, 2.5),
        CurvePoint(100.0, 45.0, 3.5),
        CurvePoint(150.0, 30.0, 5.5),
        CurvePoint(200.0, 10.0, 9.0),
    ],
    reference_rpm=1800.0,
)


class TestCurve:
    def test_head_interp(self):
        assert REF_CURVE.head_at_flow(75.0) == pytest.approx(50.0)
        assert REF_CURVE.head_at_flow(250.0) is None

    def test_npshr_interp(self):
        assert REF_CURVE.npshr_at_flow(125.0) == pytest.approx(4.5)

    def test_invert_exact_point(self):
        est = REF_CURVE.flow_at_head(45.0)
        assert est is not None
        assert est.flow_m3h == pytest.approx(100.0)
        assert not est.ambiguous

    def test_invert_between_points(self):
        est = REF_CURVE.flow_at_head(50.0)
        assert est.flow_m3h == pytest.approx(75.0)

    def test_affinity_inversion_at_reduced_speed(self):
        # At 1620 rpm (90%): measured head 36.45 → ref head 45 → ref flow 100
        # → live flow 90.
        est = REF_CURVE.flow_from_measured_head(36.45, 1620.0)
        assert est.flow_m3h == pytest.approx(90.0, abs=0.01)

    def test_flat_region_is_ambiguous_low_confidence(self):
        flat = PumpCurve(
            [CurvePoint(0.0, 50.0), CurvePoint(100.0, 50.0), CurvePoint(200.0, 20.0)],
            reference_rpm=1800.0,
        )
        # Head exactly on the plateau: flow is anywhere on it — the estimate
        # must be flagged ambiguous and capped, never fully trusted.
        est = flat.flow_at_head(50.0)
        assert est.ambiguous
        assert est.confidence <= 0.5

    def test_steep_region_high_confidence(self):
        est = REF_CURVE.flow_at_head(20.0)  # steepest segment, slope 0.4
        assert est.confidence == pytest.approx(1.0)

    def test_droop_curve_is_ambiguous_and_picks_high_flow(self):
        droop = PumpCurve(
            [
                CurvePoint(0.0, 55.0),
                CurvePoint(50.0, 58.0),  # hump
                CurvePoint(100.0, 50.0),
                CurvePoint(150.0, 35.0),
            ],
            reference_rpm=1800.0,
        )
        est = droop.flow_at_head(56.0)
        assert est.ambiguous
        assert est.flow_m3h > 50.0

    def test_npshr_at_operating_point_scales(self):
        # flow 90 @ 1620 rpm → ref flow 100 → npshr 3.5 → × 0.81 = 2.835
        npshr = REF_CURVE.npshr_at_operating_point(90.0, 1620.0)
        assert npshr == pytest.approx(2.835, abs=0.005)


PARAMS = SiteParams(
    elevation_m=0.0,
    npsh_warning_margin_m=1.5,
    npsh_danger_margin_m=0.5,
    min_running_rpm=300.0,
)


class TestEngine:
    def test_not_running_when_no_rpm(self):
        r = analyse(Readings(-0.3, 4.2, None), REF_CURVE, PARAMS)
        assert r.state is AlertState.NOT_RUNNING

    def test_not_running_below_min_rpm(self):
        r = analyse(Readings(-0.3, 4.2, 100.0), REF_CURVE, PARAMS)
        assert r.state is AlertState.NOT_RUNNING

    def test_sensor_fault_when_pressure_missing(self):
        r = analyse(Readings(None, 4.2, 1800.0), REF_CURVE, PARAMS)
        assert r.state is AlertState.SENSOR_FAULT
        assert "suction pressure unavailable" in r.faults

    def test_healthy_operating_point(self):
        # ΔP 4.5 bar ≈ 45.97 m → inferred flow just under 97 m³/h at 1800.
        r = analyse(Readings(-0.3, 4.2, 1800.0), REF_CURVE, PARAMS)
        assert r.state is AlertState.OK
        assert r.flow_source is FlowSource.INFERRED
        # TDH ≈ 45.97 m → interp between (50, 55) and (100, 45): Q ≈ 95.2
        assert r.flow_m3h == pytest.approx(95.2, abs=0.5)
        assert r.npsha_m == pytest.approx(7.05, abs=0.05)
        assert r.npsh_margin_m > 1.5

    def test_marginal_and_danger_states(self):
        # Deep suction vacuum erodes NPSHa: -0.85 bar g → NPSHa ≈ 1.43 m
        r = analyse(Readings(-0.85, 3.65, 1800.0), REF_CURVE, PARAMS)
        assert r.npsha_m == pytest.approx(1.43, abs=0.05)
        assert r.state in (AlertState.MARGINAL, AlertState.DANGER)

    def test_measured_flow_beats_inference(self):
        r = analyse(
            Readings(-0.3, 4.2, 1800.0, flow_measured_m3h=120.0), REF_CURVE, PARAMS
        )
        assert r.flow_source is FlowSource.MEASURED
        assert r.flow_m3h == 120.0
        assert r.curve_deviation_pct is not None

    def test_start_inhibit_reported(self):
        r = analyse(
            Readings(-0.3, 4.2, 1800.0), REF_CURVE, PARAMS, in_start_inhibit=True
        )
        assert r.state is AlertState.STARTING

    def test_no_curve_still_gives_heads(self):
        r = analyse(Readings(-0.3, 4.2, 1800.0), None, PARAMS)
        assert r.state is AlertState.OK
        assert r.tdh_m is not None
        assert r.npsha_m is not None
        assert r.flow_source is FlowSource.NONE
        assert r.npsh_margin_m is None
