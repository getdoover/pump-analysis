"""Resolve configured signal sources into a Readings for the engine.

Deployment-agnostic: callers supply the two capability callbacks they have —
``fetch_ai`` (device app only) and ``get_remote`` (raw value of a bound
RemoteTag by reference name). A source configured for a capability the caller
doesn't have is a config fault, reported rather than raised.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from pydoover.config import NotSet

from . import pump_math
from .app_config import HeadSource, PumpAnalysisConfig, ScaledTagRef, SourceType
from .engine import Readings
from .totaliser import Usage

FetchAI = Callable[[int], Awaitable[float | None]]
GetRemote = Callable[[str], float | None]


async def _resolve(
    label: str,
    source_type: SourceType,
    *,
    ai_pin: int | None,
    range_low: float,
    range_high: float,
    tag_cfg: ScaledTagRef,
    reference_name: str,
    fetch_ai: FetchAI | None,
    get_remote: GetRemote | None,
    faults: list[str],
    required: bool,
) -> float | None:
    if source_type is SourceType.NONE:
        if required:
            faults.append(f"{label}: no source configured")
        return None

    if source_type is SourceType.ANALOGUE_IN:
        if fetch_ai is None:
            faults.append(f"{label}: analogue input source not available in this deployment")
            return None
        if ai_pin is None:
            faults.append(f"{label}: AI pin not configured")
            return None
        reading_ma = await fetch_ai(int(ai_pin))
        value = pump_math.scale_4_20ma(reading_ma, range_low, range_high)
        if value is None and reading_ma is not None:
            faults.append(f"{label}: loop current {reading_ma:.2f} mA out of band")
        return value

    # SourceType.TAG
    if get_remote is None:
        faults.append(f"{label}: tag source not available in this deployment")
        return None
    if not tag_cfg.configured:
        faults.append(f"{label}: tag source selected but no tag configured")
        return None
    return tag_cfg.apply(get_remote(reference_name))


async def gather_readings(
    cfg: PumpAnalysisConfig,
    *,
    fetch_ai: FetchAI | None = None,
    get_remote: GetRemote | None = None,
) -> tuple[Readings, list[str]]:
    """Resolve every configured source. Returns (readings, config faults).

    Config faults are misconfigurations and capability mismatches — distinct
    from a live sensor fault (an in-config source reading None), which the
    engine reports per cycle.
    """
    faults: list[str] = []
    fixed_head = cfg.head_source.value is HeadSource.FIXED
    if fixed_head and cfg.fixed_total_head_m.value is None:
        faults.append("head source FIXED but no fixed total head set")

    suction = None if fixed_head else await _resolve(
        "suction pressure",
        cfg.suction_source_type.value,
        ai_pin=cfg.suction_ai_pin.value,
        range_low=cfg.suction_range_low_bar.value,
        range_high=cfg.suction_range_high_bar.value,
        tag_cfg=cfg.suction_tag,
        reference_name="suction_input",
        fetch_ai=fetch_ai,
        get_remote=get_remote,
        faults=faults,
        required=True,
    )
    discharge = None if fixed_head else await _resolve(
        "discharge pressure",
        cfg.discharge_source_type.value,
        ai_pin=cfg.discharge_ai_pin.value,
        range_low=cfg.discharge_range_low_bar.value,
        range_high=cfg.discharge_range_high_bar.value,
        tag_cfg=cfg.discharge_tag,
        reference_name="discharge_input",
        fetch_ai=fetch_ai,
        get_remote=get_remote,
        faults=faults,
        required=True,
    )
    flow = await _resolve(
        "flow",
        cfg.flow_source_type.value,
        ai_pin=cfg.flow_ai_pin.value,
        range_low=cfg.flow_range_low_m3h.value,
        range_high=cfg.flow_range_high_m3h.value,
        tag_cfg=cfg.flow_tag,
        reference_name="flow_input",
        fetch_ai=fetch_ai,
        get_remote=get_remote,
        faults=faults,
        required=False,
    )
    engine_rpm = await _resolve(
        "engine speed",
        cfg.speed_source_type.value,
        ai_pin=cfg.speed_ai_pin.value,
        range_low=cfg.speed_range_low_rpm.value,
        range_high=cfg.speed_range_high_rpm.value,
        tag_cfg=cfg.speed_tag,
        reference_name="speed_input",
        fetch_ai=fetch_ai,
        get_remote=get_remote,
        faults=faults,
        # Fixed-speed pumps run off the engaged tag instead.
        required=cfg.pump_engaged_tag.tag_name._value is NotSet,
    )

    water_temp = None
    if get_remote is not None and cfg.water_temperature_tag.configured:
        water_temp = cfg.water_temperature_tag.apply(get_remote("water_temp_input"))

    engaged = None
    if get_remote is not None and cfg.pump_engaged_tag.tag_name._value is not NotSet:
        raw = get_remote("engaged_input")
        engaged = None if raw is None else bool(raw)

    return (
        Readings(
            suction_bar_g=suction,
            discharge_bar_g=discharge,
            engine_rpm=engine_rpm,
            flow_measured_m3h=flow,
            water_temp_c=water_temp,
            pump_engaged=engaged,
        ),
        faults,
    )


def gather_usage(
    cfg: PumpAnalysisConfig, flow_m3h: float | None, get_remote: GetRemote | None
) -> Usage:
    """Rates for the totaliser. Tag sources only; unconfigured -> None."""

    def tag(ref: ScaledTagRef, reference_name: str) -> float | None:
        if get_remote is None or not ref.configured:
            return None
        return ref.apply(get_remote(reference_name))

    return Usage(
        flow_m3h=flow_m3h,
        fuel_lph=tag(cfg.fuel_rate_tag, "fuel_rate_input"),
        power_kw=tag(cfg.power_tag, "power_input"),
        engine_hours=tag(cfg.engine_hours_tag, "engine_hours_input"),
    )
