"""Publish a Results onto the app's tags — identical in both deployments."""

from __future__ import annotations

from .app_tags import PumpAnalysisTags
from .engine import AlertState, Results
from .protection import ProtectionMonitor
from .totaliser import TotaliserState, Usage


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
        not faults
        and results.state
        not in (AlertState.SENSOR_FAULT, AlertState.CONFIG_FAULT)
    )


#: Tag holding the persisted TotaliserState (both deployments restore from it).
TOTALISER_STATE_TAG = "_tot_state"


async def publish_usage(
    tags: PumpAnalysisTags,
    usage: Usage,
    state: TotaliserState,
) -> None:
    ml_per_h = (usage.flow_m3h or 0.0) / 1000.0

    def per_ml_now(rate: float | None) -> float | None:
        return rate / ml_per_h if rate is not None and ml_per_h > 0 else None

    def r(v: float | None, n: int) -> float | None:
        return None if v is None else round(v, n)

    await tags.fuel_rate_lph.set(usage.fuel_lph)
    await tags.power_kw.set(usage.power_kw)
    await tags.fuel_per_ml.set(r(per_ml_now(usage.fuel_lph), 1))
    await tags.energy_per_ml.set(r(per_ml_now(usage.power_kw), 1))
    await tags.volume_today_ml.set(round(state.today.volume_ml, 4))
    await tags.run_hours_today.set(round(state.today.run_hours, 3))
    await tags.fuel_today_l.set(round(state.today.fuel_l, 2))
    await tags.energy_today_kwh.set(round(state.today.energy_kwh, 2))
    await tags.fuel_per_ml_today.set(r(state.today.per_ml(state.today.fuel_l), 1))
    await tags.energy_per_ml_today.set(r(state.today.per_ml(state.today.energy_kwh), 1))
    await tags.today_date.set(state.today_date or "")
    await tags.volume_total_ml.set(round(state.total.volume_ml, 4))
    await tags.run_hours_total.set(round(state.total.run_hours, 3))
    await tags.fuel_total_l.set(round(state.total.fuel_l, 1))
    await tags.energy_total_kwh.set(round(state.total.energy_kwh, 1))
