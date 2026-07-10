"""Publish a Results onto the app's tags — identical in both deployments."""

from __future__ import annotations

from .app_tags import PumpAnalysisTags
from .engine import AlertState, Results
from .protection import ProtectionMonitor


async def publish_results(
    tags: PumpAnalysisTags,
    results: Results,
    monitor: ProtectionMonitor,
    config_faults: list[str],
    *,
    flow_display_factor: float = 1.0,
    pressure_display_factor: float = 1.0,
) -> None:
    suction_bar = (
        None if results.suction_kpa_g is None else results.suction_kpa_g / 100.0
    )
    discharge_bar = (
        None if results.discharge_kpa_g is None else results.discharge_kpa_g / 100.0
    )
    await tags.suction_bar.set(suction_bar)
    await tags.discharge_bar.set(discharge_bar)
    await tags.suction_display.set(
        None if suction_bar is None else suction_bar * pressure_display_factor
    )
    await tags.discharge_display.set(
        None if discharge_bar is None else discharge_bar * pressure_display_factor
    )
    await tags.pump_rpm.set(results.pump_rpm)
    await tags.tdh_m.set(results.tdh_m)
    await tags.flow_m3h.set(results.flow_m3h)
    await tags.flow_display.set(
        None if results.flow_m3h is None else results.flow_m3h * flow_display_factor
    )
    await tags.pct_of_bep.set(results.pct_of_bep)
    await tags.flow_origin.set(results.flow_source.value)
    await tags.flow_confidence.set(results.flow_confidence)
    await tags.npsha_m.set(results.npsha_m)
    await tags.npshr_m.set(results.npshr_m)
    await tags.npsh_margin_m.set(results.npsh_margin_m)
    await tags.curve_deviation_pct.set(results.curve_deviation_pct)

    await tags.state.set(results.state.value)
    faults = config_faults + results.faults
    await tags.fault_text.set("; ".join(faults))
    await tags.tripped.set(monitor.tripped)
    await tags.trip_reason.set(monitor.trip_reason)

    await tags.marginal_warning_hidden.set(results.state is not AlertState.MARGINAL)
    await tags.danger_warning_hidden.set(results.state is not AlertState.DANGER)
    await tags.tripped_warning_hidden.set(not monitor.tripped)
    await tags.fault_warning_hidden.set(
        not faults and results.state is not AlertState.SENSOR_FAULT
    )
