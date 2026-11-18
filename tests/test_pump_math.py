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


class TestCurveIndependentProtection:
    """The NPSHa floor and the config-fault state.

    The margin test needs NPSHr, which needs flow, which needs the operating
    point to sit on the configured curve — so on its own it goes quiet exactly
    when the curve is wrong. These cover the backstop.
    """

    # ΔP 0.5 bar at 1800 rpm scales to ~5 m of head, below the curve's 10 m
    # run-out point, so the inversion fails and NPSHr is unknown.
    OFF_CURVE_HEALTHY = Readings(0.2, 0.7, 1800.0)
    OFF_CURVE_STARVED = Readings(-0.92, -0.42, 1800.0)

    def test_off_curve_is_reported_not_swallowed(self):
        r = analyse(self.OFF_CURVE_HEALTHY, REF_CURVE, PARAMS)
        assert r.flow_m3h is None
        assert r.npshr_m is None
        assert r.npsh_margin_m is None
        assert len(r.faults) == 1
        assert r.faults[0].startswith("head too low for this speed")

    def test_head_above_shutoff_says_so(self):
        # 6 bar at 900 rpm is far more head than the curve can make that slow.
        r = analyse(Readings(0.0, 6.0, 900.0), REF_CURVE, PARAMS)
        assert r.flow_m3h is None
        assert len(r.faults) == 1
        assert r.faults[0].startswith("head above the curve for this speed")

    def test_off_curve_does_not_read_as_healthy(self):
        r = analyse(self.OFF_CURVE_HEALTHY, REF_CURVE, PARAMS)
        assert r.state is AlertState.CONFIG_FAULT

    def test_npsha_floor_still_protects_off_curve(self):
        r = analyse(self.OFF_CURVE_STARVED, REF_CURVE, PARAMS)
        # No margin to test against, but NPSHa alone is damning.
        assert r.npsh_margin_m is None
        assert r.npsha_m < PARAMS.min_npsha_m
        assert r.state is AlertState.DANGER

    def test_npsha_floor_warns_in_the_band_above(self):
        params = SiteParams(min_npsha_m=1.5, npsh_warning_margin_m=1.5)
        r = analyse(Readings(-0.75, -0.25, 1800.0), REF_CURVE, params)
        assert 1.5 <= r.npsha_m < 3.0
        assert r.state is AlertState.MARGINAL

    def test_floor_can_be_disabled(self):
        params = SiteParams(min_npsha_m=0.0, min_running_rpm=300.0)
        r = analyse(self.OFF_CURVE_STARVED, REF_CURVE, params)
        assert r.npsha_m < 1.5
        assert r.state is AlertState.CONFIG_FAULT  # fault only, no cavitation alarm

    def test_danger_is_never_downgraded_by_a_later_rule(self):
        # Margin says DANGER; the floor would only say MARGINAL; faults would
        # only say CONFIG_FAULT. DANGER has to survive both.
        r = analyse(Readings(-0.85, 3.65, 1800.0), REF_CURVE, PARAMS)
        assert r.state is AlertState.DANGER

    def test_start_inhibit_outranks_the_floor(self):
        r = analyse(
            self.OFF_CURVE_STARVED, REF_CURVE, PARAMS, in_start_inhibit=True
        )
        assert r.state is AlertState.STARTING


class TestFluidDensity:
    def test_slurry_head_is_lower_than_water_for_the_same_pressure_rise(self):
        water = analyse(Readings(-0.3, 4.2, 1800.0), None, PARAMS)
        slurry = analyse(
            Readings(-0.3, 4.2, 1800.0),
            None,
            SiteParams(fluid_sg=1.3, min_running_rpm=300.0),
        )
        # Same ΔP, denser fluid → fewer metres of head, by the SG ratio.
        assert slurry.tdh_m == pytest.approx(water.tdh_m * (998.2 / 1300.0), rel=0.01)

    def test_slurry_lowers_npsha(self):
        r = analyse(
            Readings(-0.3, 4.2, 1800.0),
            None,
            SiteParams(fluid_sg=1.3, min_running_rpm=300.0),
        )
        water = analyse(Readings(-0.3, 4.2, 1800.0), None, PARAMS)
        assert r.npsha_m < water.npsha_m

    def test_sg_of_one_matches_water_at_20c(self):
        sg = analyse(
            Readings(-0.3, 4.2, 1800.0),
            None,
            SiteParams(fluid_sg=1.0, min_running_rpm=300.0),
        )
        water = analyse(Readings(-0.3, 4.2, 1800.0), None, PARAMS)
        # 1.0 SG is 1000 kg/m³ exactly; water at 20 °C is 998.2 — close, not equal.
        assert sg.tdh_m == pytest.approx(water.tdh_m, rel=0.002)


class TestPressureUnits:
    def test_metres_head_per_bar_at_20c(self):
        # 100 kPa / (998.2 * 9.80665) ≈ 10.21 m
        assert pm.metres_head_per_bar(20.0) == pytest.approx(10.21, abs=0.01)

    def test_vacuum_converts_negative(self):
        m = pm.bar_to_metres_head(-0.85, pm.water_density_kg_m3(20.0))
        assert m == pytest.approx(-8.68, abs=0.02)

    def test_hot_water_needs_more_metres_per_bar(self):
        # lower density -> a bar is a taller column
        assert pm.metres_head_per_bar(60.0) > pm.metres_head_per_bar(5.0)


def test_pressure_display_factor_follows_temperature():
    from pump_analysis_common.app_config import PumpAnalysisConfig, PressureUnits

    def build(**overrides):
        cfg = PumpAnalysisConfig()
        cfg._inject_deployment_config({"pump_curve": [], **overrides})
        return cfg

    cfg = build(pressure_display_units="metres_head", default_water_temperature_c=20.0)
    label, factor = cfg.pressure_display()
    assert label == "m head"
    assert factor == pytest.approx(10.21, abs=0.01)

    # Hot water: same bar is a taller column of fluid.
    hot = build(pressure_display_units="metres_head", default_water_temperature_c=70.0)
    assert hot.pressure_display()[1] > factor

    label2, factor2 = build(pressure_display_units="psi").pressure_display()
    assert label2 == "psi"
    assert factor2 == pytest.approx(14.5038, abs=0.001)

    assert build(pressure_display_units="bar").pressure_display() == ("bar", 1.0)
    assert PressureUnits.METRES_HEAD.value == "metres_head"


class TestOffCurveIsNotAWarning:
    """Head off the curve is shown on the widget, not as a native warning."""

    class _Tag:
        def __init__(self):
            self.value = None

        async def set(self, v):
            self.value = v

    class _Tags:
        def __getattr__(self, name):
            tag = TestOffCurveIsNotAWarning._Tag()
            setattr(self, name, tag)
            return tag

    def _publish(self, readings):
        import asyncio

        from pump_analysis_common.protection import ProtectionMonitor
        from pump_analysis_common.publish import publish_results

        tags = self._Tags()
        r = analyse(readings, REF_CURVE, PARAMS)
        monitor = ProtectionMonitor(60, 30, 10)
        asyncio.run(publish_results(tags, r, monitor, []))
        return r, tags

    def test_off_curve_alone_hides_the_warning_but_keeps_the_text(self):
        r, tags = self._publish(Readings(0.2, 0.7, 1800.0))
        assert r.state is AlertState.CONFIG_FAULT
        assert tags.fault_warning_hidden.value is True
        assert tags.fault_text.value.startswith("head too low for this speed")

    def test_other_faults_still_warn(self):
        import asyncio

        from pump_analysis_common.protection import ProtectionMonitor
        from pump_analysis_common.publish import publish_results

        tags = self._Tags()
        r = analyse(Readings(0.2, 0.7, 1800.0), REF_CURVE, PARAMS)
        monitor = ProtectionMonitor(60, 30, 10)
        asyncio.run(publish_results(tags, r, monitor, ["speed tag not found"]))
        assert tags.fault_warning_hidden.value is False

    def test_head_above_curve_still_warns(self):
        # A real config fault: more head than the pump can make at this speed.
        r, tags = self._publish(Readings(0.0, 6.0, 900.0))
        assert r.head_below_curve is False
        assert r.no_head_fault is None
        assert tags.fault_warning_hidden.value is False


def test_fixed_head_fault_does_not_claim_a_measurement():
    curve = PumpCurve(
        [CurvePoint(0.0, 20.0), CurvePoint(1000.0, 10.0)], reference_rpm=1000.0
    )
    r = analyse(Readings(None, None, 1000.0), curve, SiteParams(fixed_head_m=2.0))
    assert r.state is AlertState.CONFIG_FAULT
    assert r.faults[0].startswith("fixed head too low for this speed")
    assert r.head_below_curve is None  # nothing measured: never "head lost"
    assert r.no_head_fault is None  # so it keeps its native warning


class TestMinimumEngineLoad:
    PARAMS = SiteParams(min_running_rpm=300.0, min_engine_load_pct=10.0)

    def test_low_load_is_not_running_and_flagged(self):
        r = analyse(Readings(0.0, 3.0, 1800.0, engine_load_pct=4.0), REF_CURVE, self.PARAMS)
        assert r.state is AlertState.NOT_RUNNING
        assert r.unloaded is True
        assert r.faults == []

    def test_load_at_or_above_the_minimum_runs(self):
        r = analyse(Readings(0.0, 3.0, 1800.0, engine_load_pct=10.0), REF_CURVE, self.PARAMS)
        assert r.state is not AlertState.NOT_RUNNING
        assert r.unloaded is False

    def test_missing_load_reading_falls_back_to_speed(self):
        r = analyse(Readings(0.0, 3.0, 1800.0), REF_CURVE, self.PARAMS)
        assert r.state is not AlertState.NOT_RUNNING

    def test_disabled_by_default(self):
        r = analyse(Readings(0.0, 3.0, 1800.0, engine_load_pct=0.0), REF_CURVE, PARAMS)
        assert r.state is not AlertState.NOT_RUNNING

    def test_below_running_speed_is_plain_stopped(self):
        r = analyse(Readings(0.0, 0.0, 100.0, engine_load_pct=0.0), REF_CURVE, self.PARAMS)
        assert r.state is AlertState.NOT_RUNNING
        assert r.unloaded is False


class TestNpshrEstimate:
    """Opt-in NPSHr estimate for curves published without one."""

    def test_bep_value_single_suction(self):
        # 680 rpm, 5000 m3/h = 22,014 US gpm; N*sqrt(Q)/9000 = 11.21;
        # ^(4/3) = 25.09 ft = 7.65 m.
        assert pm.npshr_at_bep_m(680.0, 5000.0) == pytest.approx(7.65, abs=0.02)

    def test_double_suction_halves_the_eye_flow(self):
        # Q/2 per eye -> NPSHr falls by 2^(2/3): 7.65 / 1.587 = 4.82 m.
        v = pm.npshr_at_bep_m(680.0, 5000.0, double_suction=True)
        assert v == pytest.approx(4.82, abs=0.02)

    def test_flow_factor_is_flat_to_bep_then_squares(self):
        assert pm.npshr_flow_factor(0.5) == 1.0
        assert pm.npshr_flow_factor(1.0) == 1.0
        assert pm.npshr_flow_factor(1.2) == pytest.approx(1.44)

    # REF_CURVE has NPSHr; strip it to stand in for a head-only datasheet.
    BARE = PumpCurve(
        [CurvePoint(p.flow_m3h, p.head_m) for p in REF_CURVE.points],
        reference_rpm=1800.0,
    )

    def test_estimate_is_published_but_never_changes_state(self):
        # Starved suction: an estimate this far under water would be DANGER
        # if it were allowed to count. It must not be.
        params = SiteParams(
            min_running_rpm=300.0, min_npsha_m=0.0,
            bep_flow_m3h=100.0, npshr_est_bep_m=20.0,
        )
        r = analyse(Readings(-0.5, 3.0, 1800.0), self.BARE, params)
        assert r.flow_m3h is not None
        assert r.npshr_m is None and r.npsh_margin_m is None
        assert r.npshr_est_m is not None
        assert r.npsh_margin_est_m == pytest.approx(r.npsha_m - r.npshr_est_m)
        assert r.npsh_margin_est_m < 0
        assert r.state is AlertState.OK

    def test_estimate_scales_with_speed_and_flow(self):
        params = SiteParams(
            min_running_rpm=300.0, bep_flow_m3h=100.0, npshr_est_bep_m=4.0
        )
        r = analyse(Readings(0.0, 1.0, 900.0), self.BARE, params)
        speed = 0.5
        ratio = r.flow_m3h / (100.0 * speed)
        assert r.npshr_est_m == pytest.approx(4.0 * max(1.0, ratio**2) * speed**2)

    def test_real_npshr_wins_over_the_estimate(self):
        params = SiteParams(
            min_running_rpm=300.0, bep_flow_m3h=100.0, npshr_est_bep_m=20.0
        )
        r = analyse(Readings(0.0, 3.0, 1800.0), REF_CURVE, params)
        assert r.npshr_m is not None
        assert r.npshr_est_m is None and r.npsh_margin_est_m is None

    def test_off_by_default(self):
        r = analyse(Readings(0.0, 3.0, 1800.0), self.BARE, PARAMS)
        assert r.npshr_est_m is None


def test_npshr_estimate_config_gating():
    from pump_analysis_common.app_config import PumpAnalysisConfig

    def cfg(**over):
        c = PumpAnalysisConfig()
        base = {
            "curve_reference_speed_rpm": 680,
            "bep_flow_m3h": 5000,
            "estimate_npshr": True,
            "pump_curve": [
                {"flow_m3h": 3000, "head_m": 22},
                {"flow_m3h": 7000, "head_m": 7},
            ],
        }
        base.update(over)
        c._inject_deployment_config(base)
        return c

    assert cfg().npshr_estimate_bep_m() == pytest.approx(7.65, abs=0.02)
    assert cfg(impeller_suction="double").npshr_estimate_bep_m() == pytest.approx(4.82, abs=0.02)
    assert cfg(estimate_npshr=False).npshr_estimate_bep_m() is None
    assert cfg(bep_flow_m3h=None).npshr_estimate_bep_m() is None
    real = [
        {"flow_m3h": 3000, "head_m": 22, "npshr_m": 4.0},
        {"flow_m3h": 7000, "head_m": 7, "npshr_m": 9.0},
    ]
    assert cfg(pump_curve=real).npshr_estimate_bep_m() is None


class TestPressureReadoutBands:
    """Inlet/discharge colour bands derived from NPSH limits and the curve."""

    WARREGO = {
        "curve_reference_speed_rpm": 680,
        "minimum_running_speed_rpm": 470,
        "site_elevation_m": 90,
        "default_water_temperature_c": 28,
        "gauge_separation_m": 0.5,
        "minimum_npsha_m": 1.5,
        "npsh_warning_margin_m": 1.5,
        "npsh_danger_margin_m": 0.5,
        "pump_curve": [
            {"flow_m3h": 2840, "head_m": 22.18},
            {"flow_m3h": 7000, "head_m": 7.07},
        ],
    }

    def cfg(self, **over):
        from pump_analysis_common.app_config import PumpAnalysisConfig

        c = PumpAnalysisConfig()
        c._inject_deployment_config({**self.WARREGO, **over})
        return c

    def test_suction_threshold_inverts_npsha(self):
        kpa = pm.suction_kpa_at_npsha(3.0, 100.0, 3.8, 996.0, gauge_height_above_impeller_m=0.4)
        assert pm.npsh_available_m(
            kpa, 100.0, 3.8, 996.0, gauge_height_above_impeller_m=0.4
        ) == pytest.approx(3.0)

    def test_inlet_thresholds_are_where_npsha_hits_the_floor(self):
        c = self.cfg()
        danger, warn, from_npshr = c.inlet_thresholds_bar()
        assert from_npshr is False
        p = c.to_site_params()
        baro = pm.barometric_pressure_kpa(90)
        vap = pm.water_vapour_pressure_kpa(28)
        rho = pm.water_density_kg_m3(28)
        assert pm.npsh_available_m(danger * 100, baro, vap, rho) == pytest.approx(1.5)
        assert pm.npsh_available_m(warn * 100, baro, vap, rho) == pytest.approx(3.0)
        # ~-0.82 / ~-0.67 bar at this site: the pump's -0.47 bar is healthy.
        assert danger == pytest.approx(-0.82, abs=0.02)
        assert warn == pytest.approx(-0.67, abs=0.02)
        assert p.min_npsha_m == 1.5

    def test_inlet_uses_npshr_at_bep_when_the_curve_has_it(self):
        pts = [
            {"flow_m3h": 2840, "head_m": 22.18, "npshr_m": 4.0},
            {"flow_m3h": 7000, "head_m": 7.07, "npshr_m": 8.0},
        ]
        c = self.cfg(pump_curve=pts, bep_flow_m3h=2840)
        danger, warn, from_npshr = c.inlet_thresholds_bar()
        assert from_npshr is True
        rho = pm.water_density_kg_m3(28)
        args = (pm.barometric_pressure_kpa(90), pm.water_vapour_pressure_kpa(28), rho)
        assert pm.npsh_available_m(danger * 100, *args) == pytest.approx(4.5)
        assert pm.npsh_available_m(warn * 100, *args) == pytest.approx(5.5)

    def test_inlet_unknown_without_a_floor_or_npshr(self):
        assert self.cfg(minimum_npsha_m=0).inlet_thresholds_bar() is None

    def test_discharge_band_follows_the_curve(self):
        low, high = self.cfg().discharge_normal_bar()
        k = pm.water_density_kg_m3(28) * pm.G / 100_000.0
        assert high == pytest.approx((22.18 - 0.5) * k)
        assert low == pytest.approx(
            (7.07 * (470 / 680) ** 2 - 0.5) * k + self.cfg().inlet_thresholds_bar()[1]
        )
        assert low < 1.1 < high  # the pump's healthy 1.1 bar is green

    def test_discharge_overrides_win(self):
        c = self.cfg(discharge_normal_low_bar=0.8, discharge_normal_high_bar=1.6)
        assert c.discharge_normal_bar() == (0.8, 1.6)

    def test_one_override_keeps_the_other_side_smart(self):
        c = self.cfg(discharge_normal_low_bar=0.8)
        low, high = c.discharge_normal_bar()
        assert low == 0.8
        assert high == pytest.approx(self.cfg().discharge_normal_bar()[1])

    def test_ui_applies_them(self):
        from pump_analysis_common.app_ui import PumpAnalysisUI

        u = PumpAnalysisUI(None, None, None)
        u.config = self.cfg(pressure_display_units="bar")
        u._apply_config()
        inlet = u._detail("inlet_pressure").ranges
        # No NPSHr on this curve: the bands mark the floor, and nothing is
        # called healthy.
        assert [r.label for r in inlet] == [
            "Below NPSHa floor", "Near NPSHa floor", "Above NPSHa floor",
        ]
        assert "Healthy" not in [r.label for r in inlet]
        discharge = u._detail("discharge_pressure").ranges
        assert [r.label for r in discharge] == ["Low", "Normal", "High"]


def test_flow_confidence_readout_can_be_hidden():
    from pump_analysis_common.app_config import PumpAnalysisConfig
    from pump_analysis_common.app_ui import PumpAnalysisUI

    def hidden(**over):
        c = PumpAnalysisConfig()
        c._inject_deployment_config({"pump_curve": [], **over})
        u = PumpAnalysisUI(None, None, None)
        u.config = c
        u._apply_config()
        return u._detail("flow_confidence").hidden

    assert hidden() is True  # opt-in: hidden by default
    assert hidden(show_flow_confidence=True) is False
    assert hidden(show_flow_confidence=False) is True


def test_inlet_bands_only_say_healthy_with_real_npshr():
    from pump_analysis_common.app_config import PumpAnalysisConfig
    from pump_analysis_common.app_ui import PumpAnalysisUI

    c = PumpAnalysisConfig()
    c._inject_deployment_config({
        **TestPressureReadoutBands.WARREGO,
        "bep_flow_m3h": 2840,
        "pump_curve": [
            {"flow_m3h": 2840, "head_m": 22.18, "npshr_m": 4.0},
            {"flow_m3h": 7000, "head_m": 7.07, "npshr_m": 8.0},
        ],
    })
    u = PumpAnalysisUI(None, None, None)
    u.config = c
    u._apply_config()
    assert [r.label for r in u._detail("inlet_pressure").ranges] == [
        "Cavitation risk", "Marginal", "Healthy",
    ]


class TestReadoutScalesAndNpshRows:
    def ui(self, **over):
        from pump_analysis_common.app_config import PumpAnalysisConfig
        from pump_analysis_common.app_ui import PumpAnalysisUI

        c = PumpAnalysisConfig()
        c._inject_deployment_config({
            **TestPressureReadoutBands.WARREGO,
            "pressure_display_units": "bar",
            **over,
        })
        u = PumpAnalysisUI(None, None, None)
        u.config = c
        u._apply_config()
        return u

    def test_inlet_scale_stops_just_above_atmospheric(self):
        r = self.ui()._detail("inlet_pressure").ranges
        assert r[0].min == -1.0  # still starts at the transmitter's 4 mA
        assert r[-1].max == 0.25  # not the 10 bar span

    def test_discharge_high_band_is_a_short_tail(self):
        r = self.ui()._detail("discharge_pressure").ranges
        normal, high = r[-2], r[-1]
        assert high.max == pytest.approx(
            normal.max + 0.25 * (normal.max - normal.min), abs=0.02
        )
        assert high.max < 10

    def test_discharge_without_a_curve_keeps_the_full_span(self):
        r = self.ui(pump_curve=[])._detail("discharge_pressure").ranges
        assert r[-1].max == 10

    def test_margin_row_hidden_without_npshr(self):
        u = self.ui()
        assert u._detail("npsh_margin").hidden is True
        assert u._detail("npsh_margin_est").hidden is True

    def test_estimated_margin_row_shows_when_opted_in(self):
        u = self.ui(estimate_npshr=True, bep_flow_m3h=4900)
        assert u._detail("npsh_margin").hidden is True
        assert u._detail("npsh_margin_est").hidden is False
        assert not isinstance(u._detail("npsh_margin_est").ranges, list)  # unset

    def test_real_margin_row_shows_with_npshr(self):
        pts = [
            {"flow_m3h": 2840, "head_m": 22.18, "npshr_m": 4.0},
            {"flow_m3h": 7000, "head_m": 7.07, "npshr_m": 8.0},
        ]
        u = self.ui(pump_curve=pts, estimate_npshr=True, bep_flow_m3h=4900)
        assert u._detail("npsh_margin").hidden is False
        assert u._detail("npsh_margin_est").hidden is True
