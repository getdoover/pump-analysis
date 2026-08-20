"""Clock-injected tests for the alert/trip supervisor."""

from pump_analysis_common.engine import AlertState
from pump_analysis_common.protection import ProtectionMonitor


def make_monitor(trip_armed: bool = True) -> ProtectionMonitor:
    return ProtectionMonitor(
        start_inhibit_s=60.0,
        alert_debounce_s=30.0,
        trip_debounce_s=10.0,
        trip_armed=trip_armed,
    )


class TestStartInhibit:
    def test_window_opens_on_run_transition(self):
        m = make_monitor()
        assert m.in_start_inhibit(False, 0.0) is False
        assert m.in_start_inhibit(True, 100.0) is True
        assert m.in_start_inhibit(True, 130.0) is True
        assert m.in_start_inhibit(True, 161.0) is False

    def test_window_reopens_on_restart(self):
        m = make_monitor()
        m.in_start_inhibit(True, 0.0)
        m.in_start_inhibit(True, 100.0)
        m.in_start_inhibit(False, 200.0)
        assert m.in_start_inhibit(True, 300.0) is True


class TestDebounce:
    def test_marginal_alert_after_debounce_only(self):
        m = make_monitor()
        assert not m.update(AlertState.MARGINAL, 0.0).send_marginal_alert
        assert not m.update(AlertState.MARGINAL, 29.0).send_marginal_alert
        assert m.update(AlertState.MARGINAL, 30.0).send_marginal_alert

    def test_alert_fires_once_until_condition_clears(self):
        m = make_monitor()
        m.update(AlertState.MARGINAL, 0.0)
        assert m.update(AlertState.MARGINAL, 30.0).send_marginal_alert
        assert not m.update(AlertState.MARGINAL, 60.0).send_marginal_alert
        m.update(AlertState.OK, 90.0)  # clears, re-arms
        m.update(AlertState.MARGINAL, 100.0)
        assert m.update(AlertState.MARGINAL, 130.0).send_marginal_alert

    def test_blip_does_not_alert(self):
        m = make_monitor()
        m.update(AlertState.MARGINAL, 0.0)
        m.update(AlertState.OK, 10.0)
        assert not m.update(AlertState.MARGINAL, 15.0).send_marginal_alert


class TestTrip:
    def test_trip_after_danger_debounce(self):
        m = make_monitor()
        assert not m.update(AlertState.DANGER, 0.0).fire_trip
        assert not m.update(AlertState.DANGER, 9.0).fire_trip
        actions = m.update(AlertState.DANGER, 10.0)
        assert actions.fire_trip
        assert actions.send_danger_alert
        assert m.tripped

    def test_trip_latches(self):
        m = make_monitor()
        m.update(AlertState.DANGER, 0.0)
        m.update(AlertState.DANGER, 10.0)
        assert m.tripped
        # Pump stops (trip worked) — the latch must survive.
        m.update(AlertState.NOT_RUNNING, 20.0)
        assert m.tripped
        # And no re-trip fires while latched.
        m.update(AlertState.DANGER, 30.0)
        assert not m.update(AlertState.DANGER, 40.0).fire_trip

    def test_reset_rearms(self):
        m = make_monitor()
        m.update(AlertState.DANGER, 0.0)
        m.update(AlertState.DANGER, 10.0)
        m.reset()
        assert not m.tripped
        m.update(AlertState.DANGER, 20.0)
        assert m.update(AlertState.DANGER, 30.0).fire_trip

    def test_danger_blip_does_not_trip(self):
        m = make_monitor()
        m.update(AlertState.DANGER, 0.0)
        m.update(AlertState.MARGINAL, 5.0)  # back to marginal before debounce
        assert not m.update(AlertState.DANGER, 8.0).fire_trip  # timer restarted
        assert not m.tripped

class TestDisarmed:
    """TripAction.NONE: alert-only. Nothing may latch — the UI hides the reset
    control in this mode, so a latch would have no way out."""

    def test_danger_alerts_but_never_latches(self):
        m = make_monitor(trip_armed=False)
        m.update(AlertState.DANGER, 0.0)
        actions = m.update(AlertState.DANGER, 10.0)
        assert actions.send_danger_alert
        assert not actions.fire_trip
        assert not m.tripped
        assert m.trip_reason == ""

    def test_prolonged_danger_alerts_once(self):
        m = make_monitor(trip_armed=False)
        m.update(AlertState.DANGER, 0.0)
        assert m.update(AlertState.DANGER, 10.0).send_danger_alert
        assert not m.update(AlertState.DANGER, 20.0).send_danger_alert
        assert not m.update(AlertState.DANGER, 600.0).send_danger_alert

    def test_marginal_alert_still_works(self):
        m = make_monitor(trip_armed=False)
        m.update(AlertState.MARGINAL, 0.0)
        assert m.update(AlertState.MARGINAL, 30.0).send_marginal_alert

    def test_stale_latch_is_cleared(self):
        """A site that tripped, then disarmed, must not stay stuck TRIPPED."""
        m = make_monitor(trip_armed=True)
        m.update(AlertState.DANGER, 0.0)
        m.update(AlertState.DANGER, 10.0)
        assert m.tripped

        m.trip_armed = False
        m.update(AlertState.DANGER, 20.0)
        assert not m.tripped
        assert m.trip_reason == ""

    def test_clearing_stale_latch_does_not_re_alert(self):
        m = make_monitor(trip_armed=True)
        m.update(AlertState.DANGER, 0.0)
        m.update(AlertState.DANGER, 10.0)  # danger alert already sent

        m.trip_armed = False
        # Same unbroken danger condition — no second notification for it.
        assert not m.update(AlertState.DANGER, 20.0).send_danger_alert


def test_config_fault_counts_as_running():
    """A pump turning with an incomplete analysis is still running.

    If CONFIG_FAULT fell outside RUNNING_STATES, an operating point drifting off
    the curve would clear the run timer and re-arm the start-inhibit window —
    suppressing alerts every time the curve stopped fitting.
    """
    from pump_analysis_common.protection import RUNNING_STATES

    assert AlertState.CONFIG_FAULT in RUNNING_STATES
    assert AlertState.NOT_RUNNING not in RUNNING_STATES
    assert AlertState.SENSOR_FAULT not in RUNNING_STATES
