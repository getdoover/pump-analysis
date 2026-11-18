"""Alert/trip supervision: debounce, start inhibit, latch.

Pure and clock-injected (callers pass ``now`` as a monotonic-ish float), so
every path — including the ones that stop a customer's pump — is unit-testable
without sleeping.

Semantics:
- Start inhibit: alerts/trips are suppressed for a window after the pump
  transitions into a running state (priming transients).
- Debounce: MARGINAL must persist ``alert_debounce_s`` before an alert is
  requested; DANGER must persist ``trip_debounce_s`` before a trip is
  requested. DANGER also raises the alert path immediately after its own
  debounce.
- Latch: once tripped, the monitor stays tripped until ``reset()``. Alerts
  re-arm only after the condition clears (no repeat spam while it persists).
- Head lost: once a run has shown head on the curve, head dropping below
  the curve while the pump holds its speed must persist ``head_lost_delay_s``
  before one alert is requested. "Holds its speed" is within
  ``HEAD_LOST_SPEED_FRACTION`` of the speed head was last seen at — slowing
  the pump down is expected to shed head and does not count. It re-arms when
  head returns or the pump stops. A run that never built head (idling, never
  primed) does not alert. A pump judged stopped only by low engine load is
  still watched: a pump that has run dry sheds load exactly like a declutched
  one, and that is the case this alert exists for.
- Sensor fault: SENSOR_FAULT (a pressure reading missing while the pump is
  at running speed) must persist ``alert_debounce_s`` before one alert is
  requested; it re-arms when the fault clears. A stopped pump with dead
  sensors never reaches that state, so loops that power down with the engine
  stay quiet.
- Arming: with ``trip_armed=False`` (the ``TripAction.NONE`` alert-only
  install) the danger alert is the entire behaviour — nothing latches, so the
  operator is never shown a TRIPPED state that no trip produced and no reset
  can clear.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .engine import AlertState, Results

# CONFIG_FAULT is a running state: the pump is turning and readable, only the
# analysis is incomplete. Leaving it out would clear run_started_at and re-arm
# the start-inhibit window every time the operating point wandered off the curve.
RUNNING_STATES = frozenset(
    {
        AlertState.OK,
        AlertState.MARGINAL,
        AlertState.DANGER,
        AlertState.STARTING,
        AlertState.CONFIG_FAULT,
    }
)


#: Head lost only counts while pump speed is at least this fraction of the
#: speed at which head was last on the curve.
HEAD_LOST_SPEED_FRACTION = 0.9


@dataclass
class ProtectionActions:
    send_marginal_alert: bool = False
    send_danger_alert: bool = False
    send_head_lost_alert: bool = False
    send_sensor_fault_alert: bool = False
    fire_trip: bool = False


@dataclass
class ProtectionMonitor:
    start_inhibit_s: float
    alert_debounce_s: float
    trip_debounce_s: float
    #: False for TripAction.NONE. A disarmed monitor still alerts, but never
    #: latches — a latch with no trip behind it only strands the operator.
    trip_armed: bool = True
    head_lost_delay_s: float = 60.0

    run_started_at: float | None = None
    _was_running: bool = False
    _marginal_since: float | None = None
    _danger_since: float | None = None
    _marginal_alerted: bool = False
    _danger_alerted: bool = False
    _sensor_fault_since: float | None = None
    _sensor_fault_alerted: bool = False
    _head_seen: bool = False
    _head_seen_rpm: float | None = None
    _head_lost_since: float | None = None
    _head_lost_alerted: bool = False
    tripped: bool = False
    trip_reason: str = ""
    _history: list[str] = field(default_factory=list)

    def in_start_inhibit(self, running: bool, now: float) -> bool:
        """Track run transitions; True while inside the inhibit window."""
        if running and not self._was_running:
            self.run_started_at = now
        if not running:
            self.run_started_at = None
        self._was_running = running
        return (
            self.run_started_at is not None
            and (now - self.run_started_at) < self.start_inhibit_s
        )

    @property
    def head_lost(self) -> bool:
        """True from the head-lost alert until head returns or the pump stops."""
        return self._head_lost_alerted

    def _track_head(
        self,
        state: AlertState,
        head_below_curve: bool | None,
        pump_rpm: float | None,
        unloaded: bool,
        now: float,
        actions: ProtectionActions,
    ) -> None:
        if state in RUNNING_STATES:
            if state is AlertState.STARTING or head_below_curve is None:
                # Priming transients / nothing to judge by: neither
                # establishes head nor counts towards losing it.
                self._head_lost_since = None
                return
            if not head_below_curve:
                self._head_seen = True
                self._head_seen_rpm = pump_rpm
                self._head_lost_since = None
                self._head_lost_alerted = False
                return
        elif not (unloaded and self._head_seen):
            # Really stopped (speed, clutch signal, sensor fault).
            self._head_seen = False
            self._head_seen_rpm = None
            self._head_lost_since = None
            self._head_lost_alerted = False
            return
        # Head is below the curve, or the pump has shed its load at speed.
        if not self._head_seen:
            return
        if (
            self._head_seen_rpm is not None
            and pump_rpm is not None
            and pump_rpm < self._head_seen_rpm * HEAD_LOST_SPEED_FRACTION
        ):
            # Slowed down since head was last seen: losing head is expected.
            self._head_lost_since = None
            return
        if self._head_lost_since is None:
            self._head_lost_since = now
        if (
            not self._head_lost_alerted
            and (now - self._head_lost_since) >= self.head_lost_delay_s
        ):
            self._head_lost_alerted = True
            actions.send_head_lost_alert = True

    def update(
        self,
        state: AlertState,
        now: float,
        head_below_curve: bool | None = None,
        pump_rpm: float | None = None,
        unloaded: bool = False,
    ) -> ProtectionActions:
        actions = ProtectionActions()
        self._track_head(state, head_below_curve, pump_rpm, unloaded, now, actions)

        if state is AlertState.SENSOR_FAULT:
            if self._sensor_fault_since is None:
                self._sensor_fault_since = now
            if (
                not self._sensor_fault_alerted
                and (now - self._sensor_fault_since) >= self.alert_debounce_s
            ):
                self._sensor_fault_alerted = True
                actions.send_sensor_fault_alert = True
        else:
            self._sensor_fault_since = None
            self._sensor_fault_alerted = False

        # Self-heal a latch left behind by a site that has since disarmed the
        # trip: the reset control is hidden in that mode, so nothing else could.
        # Only the latch is dropped — clearing the debounce timers here would
        # re-alert on a condition that has been continuously present.
        if not self.trip_armed and self.tripped:
            self.tripped = False
            self.trip_reason = ""

        if state not in (AlertState.MARGINAL, AlertState.DANGER):
            # Condition cleared (or pump stopped): re-arm alerts. The trip
            # latch deliberately survives — a tripped pump stopping is the
            # trip working, not the condition clearing.
            self._marginal_since = None
            self._danger_since = None
            self._marginal_alerted = False
            self._danger_alerted = False
            return actions

        if self._marginal_since is None:
            self._marginal_since = now
        if state is AlertState.DANGER:
            if self._danger_since is None:
                self._danger_since = now
        else:
            self._danger_since = None
            self._danger_alerted = False

        if (
            not self._marginal_alerted
            and (now - self._marginal_since) >= self.alert_debounce_s
        ):
            self._marginal_alerted = True
            actions.send_marginal_alert = state is AlertState.MARGINAL

        if self._danger_since is not None:
            danger_for = now - self._danger_since
            if not self._danger_alerted and danger_for >= self.trip_debounce_s:
                self._danger_alerted = True
                actions.send_danger_alert = True
            if (
                self.trip_armed
                and not self.tripped
                and danger_for >= self.trip_debounce_s
            ):
                self.tripped = True
                self.trip_reason = "NPSH margin below danger threshold"
                actions.fire_trip = True

        return actions

    def reset(self) -> None:
        """Operator-initiated reset of the trip latch."""
        self.tripped = False
        self.trip_reason = ""
        self._danger_since = None
        self._danger_alerted = False


def sensor_fault_text(pump: str, faults: list[str]) -> tuple[str, str]:
    """(title, body) for the sensor-fault-while-running notification."""
    detail = "; ".join(faults) if faults else "pressure reading unavailable"
    return (
        f"{pump}: sensor fault while pump running",
        f"{pump}: sensor fault while pump running — {detail}. "
        "Cavitation protection is not active until it is fixed.",
    )


def head_lost_text(pump: str, results: Results) -> tuple[str, str]:
    """(title, body) for the head-lost-while-running notification."""
    detail = []
    if results.tdh_m is not None:
        detail.append(f"total head {results.tdh_m:.1f} m")
    if results.pump_rpm is not None:
        detail.append(f"pump still at {results.pump_rpm:.0f} rpm")
    tail = f" ({', '.join(detail)})" if detail else ""
    return (
        f"{pump}: head lost while pump running",
        f"{pump}: head lost while pump running{tail} — check prime and suction",
    )


def alert_text(pump: str, results: Results, *, danger: bool) -> tuple[str, str]:
    """(title, body) for a marginal/danger cavitation notification.

    MARGINAL/DANGER come from either the NPSH margin (needs NPSHr from the
    curve) or the absolute NPSHa floor, which fires with no NPSHr at all —
    the normal case for a curve without NPSHr points. So the margin can be
    None here and the text must not assume it.
    """
    level = "critical" if danger else "marginal"
    tail = "cavitation conditions" if danger else "cavitation risk developing"
    if results.npsh_margin_m is not None:
        return (
            f"{pump}: cavitation margin {level}",
            f"{pump}: NPSH margin {level} ({results.npsh_margin_m:.2f} m) — {tail}",
        )
    npsha = f" ({results.npsha_m:.2f} m)" if results.npsha_m is not None else ""
    return (
        f"{pump}: suction head {level}",
        f"{pump}: NPSH available {level}{npsha} — {tail}",
    )
