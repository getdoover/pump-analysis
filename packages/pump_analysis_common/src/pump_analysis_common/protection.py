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
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .engine import AlertState

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


@dataclass
class ProtectionActions:
    send_marginal_alert: bool = False
    send_danger_alert: bool = False
    fire_trip: bool = False


@dataclass
class ProtectionMonitor:
    start_inhibit_s: float
    alert_debounce_s: float
    trip_debounce_s: float

    run_started_at: float | None = None
    _was_running: bool = False
    _marginal_since: float | None = None
    _danger_since: float | None = None
    _marginal_alerted: bool = False
    _danger_alerted: bool = False
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

    def update(self, state: AlertState, now: float) -> ProtectionActions:
        actions = ProtectionActions()

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
                not self.tripped
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
