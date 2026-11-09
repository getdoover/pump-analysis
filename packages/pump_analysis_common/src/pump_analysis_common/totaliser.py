"""Integrate flow, fuel and power into volume, run hours, fuel and energy.

Pure: the caller supplies the clock, the local date and the previous state,
and persists the returned state (a processor has no memory between runs).

Elapsed run time comes from the engine-hour meter when there is one. Remote
sites sleep and go quiet without ever publishing rpm 0, so the last speed
sticks; the hour meter only moves while the engine actually runs. With no
hour meter, wall-clock time between samples is used, capped at ``max_gap_s``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

#: Largest hour-meter step still counted as run time. The meter only moves
#: while the engine runs, so a jump across a comms gap is real running; only
#: a jump bigger than this (meter swapped/re-read) is discarded.
MAX_HOUR_METER_STEP_H = 24.0


@dataclass(frozen=True)
class Usage:
    """One cycle's rates (None = not available)."""

    flow_m3h: float | None = None
    fuel_lph: float | None = None
    power_kw: float | None = None
    engine_hours: float | None = None


@dataclass
class Period:
    volume_ml: float = 0.0
    run_hours: float = 0.0
    fuel_l: float = 0.0
    energy_kwh: float = 0.0

    def add(self, other: "Period") -> None:
        self.volume_ml += other.volume_ml
        self.run_hours += other.run_hours
        self.fuel_l += other.fuel_l
        self.energy_kwh += other.energy_kwh

    def per_ml(self, amount: float) -> float | None:
        """Fuel or energy used per ML pumped over this period."""
        return amount / self.volume_ml if self.volume_ml > 0 else None


@dataclass
class TotaliserState:
    total: Period = field(default_factory=Period)
    today: Period = field(default_factory=Period)
    today_date: str | None = None
    last_ts: float | None = None
    last_engine_hours: float | None = None
    last_flow_m3h: float = 0.0
    last_fuel_lph: float = 0.0
    last_power_kw: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "TotaliserState":
        if not isinstance(data, dict):
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        for key in ("total", "today"):
            p = known.get(key)
            known[key] = (
                Period(**{k: v for k, v in p.items() if k in Period.__dataclass_fields__})
                if isinstance(p, dict)
                else Period()
            )
        return cls(**known)


def step(
    state: TotaliserState,
    usage: Usage,
    *,
    now_ts: float,
    local_date: str,
    max_gap_s: float,
) -> TotaliserState:
    """Advance the totals to ``now_ts`` and return the new state."""
    if state.today_date != local_date:
        state.today = Period()
        state.today_date = local_date

    flow = usage.flow_m3h or 0.0
    fuel = usage.fuel_lph or 0.0
    power = usage.power_kw or 0.0

    hours = 0.0
    if usage.engine_hours is not None and state.last_engine_hours is not None:
        dh = usage.engine_hours - state.last_engine_hours
        # Negative or huge = meter reset/replaced, not run time.
        if 0.0 < dh <= MAX_HOUR_METER_STEP_H:
            hours = dh
            # The interval ran at some mix of the old and new rate; max()
            # keeps the hour that ended in a stop (new rate 0) and the one
            # that began with a start (old rate 0).
            flow, fuel, power = (
                max(flow, state.last_flow_m3h),
                max(fuel, state.last_fuel_lph),
                max(power, state.last_power_kw),
            )
    elif usage.engine_hours is None and state.last_ts is not None:
        dt = now_ts - state.last_ts
        if 0.0 < dt:
            hours = min(dt, max_gap_s) / 3600.0
            # Wall-clock interval: it ran at the rate seen at its start.
            flow, fuel, power = state.last_flow_m3h, state.last_fuel_lph, state.last_power_kw

    if hours > 0.0:
        inc = Period(
            volume_ml=flow * hours / 1000.0,
            run_hours=hours if flow > 0.0 else 0.0,
            fuel_l=fuel * hours,
            energy_kwh=power * hours,
        )
        state.total.add(inc)
        state.today.add(inc)

    state.last_ts = now_ts
    if usage.engine_hours is not None:
        state.last_engine_hours = usage.engine_hours
    state.last_flow_m3h = usage.flow_m3h or 0.0
    state.last_fuel_lph = usage.fuel_lph or 0.0
    state.last_power_kw = usage.power_kw or 0.0
    return state


def local_date(tz_name: str | None, now_ts: float) -> str:
    """ISO date at ``now_ts`` in ``tz_name``; UTC if the zone is unknown."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        tz = ZoneInfo(tz_name) if tz_name else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        tz = timezone.utc
    return datetime.fromtimestamp(now_ts, tz).date().isoformat()
