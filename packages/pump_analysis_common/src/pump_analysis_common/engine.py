"""The per-cycle analysis pipeline: readings in, results out.

Pure and deployment-agnostic — the device app and the processor both feed
this the same dataclasses. Anything None-able stays None-able: a missing
input degrades the outputs that need it and nothing else.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from . import pump_math
from .curve import PumpCurve


class FlowSource(enum.Enum):
    NONE = "none"
    MEASURED = "measured"
    INFERRED = "inferred"


class AlertState(enum.Enum):
    NOT_RUNNING = "not_running"
    STARTING = "starting"  # within the start inhibit window
    OK = "ok"
    MARGINAL = "marginal"  # NPSH margin below warning threshold
    DANGER = "danger"  # NPSH margin below trip threshold
    SENSOR_FAULT = "sensor_fault"


@dataclass(frozen=True)
class SiteParams:
    """Static per-install parameters (from config, converted to SI)."""

    elevation_m: float = 0.0
    #: discharge-gauge height minus suction-gauge height, m
    gauge_separation_m: float = 0.0
    #: suction-gauge height above the impeller eye, m
    suction_gauge_above_impeller_m: float = 0.0
    suction_pipe_id_mm: float | None = None
    discharge_pipe_id_mm: float | None = None
    default_water_temp_c: float = 20.0
    #: engine→pump speed linear transform
    speed_ratio: float = 1.0
    speed_offset: float = 0.0
    min_running_rpm: float = 300.0
    npsh_warning_margin_m: float = 1.5
    npsh_danger_margin_m: float = 0.5
    #: best-efficiency-point flow at curve reference speed (manufacturer)
    bep_flow_m3h: float | None = None


@dataclass(frozen=True)
class Readings:
    """One cycle's raw inputs, already in engineering units."""

    suction_bar_g: float | None
    discharge_bar_g: float | None
    engine_rpm: float | None
    flow_measured_m3h: float | None = None
    water_temp_c: float | None = None


@dataclass
class Results:
    state: AlertState
    pump_rpm: float | None = None
    suction_kpa_g: float | None = None
    discharge_kpa_g: float | None = None
    tdh_m: float | None = None
    flow_m3h: float | None = None
    flow_source: FlowSource = FlowSource.NONE
    flow_confidence: float | None = None
    flow_ambiguous: bool = False
    npsha_m: float | None = None
    npshr_m: float | None = None
    npsh_margin_m: float | None = None
    #: measured/predicted head deviation, % — pump-degradation indicator.
    #: Only populated when flow is MEASURED (with inferred flow the predicted
    #: head is the measured head by construction).
    curve_deviation_pct: float | None = None
    #: flow as % of the affinity-scaled best-efficiency-point flow.
    #: ~70–120% is the conventional preferred operating region.
    pct_of_bep: float | None = None
    faults: list[str] = field(default_factory=list)


def analyse(
    readings: Readings,
    curve: PumpCurve | None,
    params: SiteParams,
    *,
    in_start_inhibit: bool = False,
) -> Results:
    """Run one analysis cycle. Never raises on bad inputs — reports faults."""
    faults: list[str] = []

    # --- speed: decides run-state before anything else
    pump_rpm = None
    if readings.engine_rpm is not None:
        pump_rpm = pump_math.pump_rpm_from_engine(
            readings.engine_rpm, params.speed_ratio, params.speed_offset
        )

    if pump_rpm is None or pump_rpm < params.min_running_rpm:
        return Results(state=AlertState.NOT_RUNNING, pump_rpm=pump_rpm)

    # --- pressures: both required for any hydraulic output
    if readings.suction_bar_g is None or readings.discharge_bar_g is None:
        if readings.suction_bar_g is None:
            faults.append("suction pressure unavailable")
        if readings.discharge_bar_g is None:
            faults.append("discharge pressure unavailable")
        return Results(
            state=AlertState.SENSOR_FAULT, pump_rpm=pump_rpm, faults=faults
        )

    suction_kpa = pump_math.bar_to_kpa(readings.suction_bar_g)
    discharge_kpa = pump_math.bar_to_kpa(readings.discharge_bar_g)

    temp_c = (
        readings.water_temp_c
        if readings.water_temp_c is not None
        else params.default_water_temp_c
    )
    density = pump_math.water_density_kg_m3(temp_c)
    baro = pump_math.barometric_pressure_kpa(params.elevation_m)
    vapour = pump_math.water_vapour_pressure_kpa(temp_c)

    r = Results(
        state=AlertState.OK,
        pump_rpm=pump_rpm,
        suction_kpa_g=suction_kpa,
        discharge_kpa_g=discharge_kpa,
    )

    # --- flow (needed for velocity heads, NPSHr, deviation)
    if readings.flow_measured_m3h is not None:
        r.flow_m3h = readings.flow_measured_m3h
        r.flow_source = FlowSource.MEASURED
        r.flow_confidence = 1.0

    # First-pass TDH without velocity terms; refine once flow is known.
    tdh = pump_math.total_differential_head_m(
        suction_kpa, discharge_kpa, density,
        gauge_separation_m=params.gauge_separation_m,
    )

    if r.flow_source is not FlowSource.MEASURED and curve is not None:
        est = curve.flow_from_measured_head(tdh, pump_rpm)
        if est is not None:
            r.flow_m3h = est.flow_m3h
            r.flow_source = FlowSource.INFERRED
            r.flow_confidence = est.confidence
            r.flow_ambiguous = est.ambiguous
        else:
            faults.append("operating point off the configured curve")

    # --- velocity heads, now that flow is (maybe) known
    v_suction = pump_math.velocity_m_s(r.flow_m3h, params.suction_pipe_id_mm)
    v_discharge = pump_math.velocity_m_s(r.flow_m3h, params.discharge_pipe_id_mm)
    r.tdh_m = pump_math.total_differential_head_m(
        suction_kpa, discharge_kpa, density,
        gauge_separation_m=params.gauge_separation_m,
        suction_velocity_m_s=v_suction,
        discharge_velocity_m_s=v_discharge,
    )

    # --- NPSH
    r.npsha_m = pump_math.npsh_available_m(
        suction_kpa, baro, vapour, density,
        suction_velocity_m_s=v_suction,
        gauge_height_above_impeller_m=params.suction_gauge_above_impeller_m,
    )
    if curve is not None and r.flow_m3h is not None:
        r.npshr_m = curve.npshr_at_operating_point(r.flow_m3h, pump_rpm)
    if r.npshr_m is not None:
        r.npsh_margin_m = r.npsha_m - r.npshr_m

    # --- degradation: measured flow vs curve prediction
    if (
        r.flow_source is FlowSource.MEASURED
        and curve is not None
        and r.flow_m3h is not None
    ):
        predicted = curve.predicted_head_at(r.flow_m3h, pump_rpm)
        if predicted and predicted > 0:
            r.curve_deviation_pct = (r.tdh_m - predicted) / predicted * 100.0

    # --- efficiency: % of BEP flow (affinity-scaled to live speed)
    if params.bep_flow_m3h and r.flow_m3h is not None and curve is not None:
        bep_live = params.bep_flow_m3h * pump_rpm / curve.reference_rpm
        if bep_live > 0:
            r.pct_of_bep = r.flow_m3h / bep_live * 100.0

    # --- state
    r.faults = faults
    if in_start_inhibit:
        r.state = AlertState.STARTING
    elif r.npsh_margin_m is not None:
        if r.npsh_margin_m < params.npsh_danger_margin_m:
            r.state = AlertState.DANGER
        elif r.npsh_margin_m < params.npsh_warning_margin_m:
            r.state = AlertState.MARGINAL
    return r
