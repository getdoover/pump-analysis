"""Cloud-side deployment: same analysis, triggered by tag updates.

Runs against telemetry that already lands in the Doover cloud (any device or
bridge that publishes tags), so a site needs no doovit for the analysis —
only for the ANALOGUE_IN sources and the DIGITAL_OUTPUT trip action, which
are device-app-only and rejected here.
"""

import json
import logging
import time

from pydoover import ui
from pydoover.models import MessageCreateEvent, NotificationSeverity
from pydoover.processor import Application

from pump_analysis_common.app_config import SourceType, TripAction
from pump_analysis_common.engine import analyse
from pump_analysis_common.protection import ProtectionMonitor, RUNNING_STATES
from pump_analysis_common.publish import publish_results
from pump_analysis_common.sources import gather_readings

from .app_config import PumpAnalysisProcessorConfig
from pump_analysis_common.app_tags import PumpAnalysisTags
from pump_analysis_common.app_ui import PumpAnalysisUI

log = logging.getLogger(__name__)

REMOTE_TAGS = {
    "suction_input": "raw_suction",
    "discharge_input": "raw_discharge",
    "flow_input": "raw_flow",
    "speed_input": "raw_speed",
    "water_temp_input": "raw_water_temp",
}

# Monitor timing state must survive between invocations — persisted as tags.
_MONITOR_TAGS = ("_mon_run_started", "_mon_marginal_since", "_mon_danger_since")


class PumpAnalysisProcessorApp(Application):
    config_cls = PumpAnalysisProcessorConfig
    tags_cls = PumpAnalysisTags
    ui_cls = PumpAnalysisUI

    config: PumpAnalysisProcessorConfig
    tags: PumpAnalysisTags

    def _get_remote(self, reference_name: str):
        return getattr(self.tags, REMOTE_TAGS[reference_name]).get()

    def _load_monitor(self) -> ProtectionMonitor:
        """Rebuild the supervisor from persisted state (processor is stateless)."""
        m = ProtectionMonitor(
            start_inhibit_s=self.config.start_inhibit_seconds.value,
            alert_debounce_s=self.config.alert_debounce_seconds.value,
            trip_debounce_s=self.config.trip_debounce_seconds.value,
        )
        state = self.get_tag("_mon_state") or {}
        m.run_started_at = state.get("run_started_at")
        m._was_running = state.get("was_running", False)
        m._marginal_since = state.get("marginal_since")
        m._danger_since = state.get("danger_since")
        m._marginal_alerted = state.get("marginal_alerted", False)
        m._danger_alerted = state.get("danger_alerted", False)
        m.tripped = bool(self.tags.tripped.get())
        m.trip_reason = self.tags.trip_reason.get() or ""
        return m

    async def _save_monitor(self, m: ProtectionMonitor):
        await self.set_tag(
            "_mon_state",
            {
                "run_started_at": m.run_started_at,
                "was_running": m._was_running,
                "marginal_since": m._marginal_since,
                "danger_since": m._danger_since,
                "marginal_alerted": m._marginal_alerted,
                "danger_alerted": m._danger_alerted,
            },
        )

    async def on_message_create(self, event: MessageCreateEvent):
        if event.channel.name != "tag_values":
            return
        await self._run_analysis()

    async def _run_analysis(self):
        # Wall-clock is the only clock a stateless invocation has.
        now = time.time()

        config_faults = []
        for label, source in (
            ("suction", self.config.suction_source_type.value),
            ("discharge", self.config.discharge_source_type.value),
            ("flow", self.config.flow_source_type.value),
            ("speed", self.config.speed_source_type.value),
        ):
            if source is SourceType.ANALOGUE_IN:
                config_faults.append(
                    f"{label}: ANALOGUE_IN source is device-app-only — use a tag source"
                )
        if self.config.trip_action.value is TripAction.DIGITAL_OUTPUT:
            config_faults.append(
                "trip action DIGITAL_OUTPUT is device-app-only — use SET_TAG"
            )

        readings, faults = await gather_readings(
            self.config, fetch_ai=None, get_remote=self._get_remote
        )
        config_faults.extend(faults)
        await self.tags.engine_rpm.set(readings.engine_rpm)

        site_params = self.config.to_site_params()
        curve = self.config.build_curve()
        monitor = self._load_monitor()

        probe = analyse(readings, curve, site_params)
        running = probe.state in RUNNING_STATES
        inhibit = monitor.in_start_inhibit(running, now)
        results = analyse(readings, curve, site_params, in_start_inhibit=inhibit)

        actions = monitor.update(results.state, now)
        pump = self.config.pump_name.value

        if actions.send_marginal_alert:
            await self.send_notification(
                f"{pump}: NPSH margin marginal ({results.npsh_margin_m:.2f} m) — "
                f"cavitation risk developing",
                severity=NotificationSeverity.Warn,
            )
        if actions.send_danger_alert:
            await self.send_notification(
                f"{pump}: NPSH margin critical ({results.npsh_margin_m:.2f} m) — "
                f"cavitation conditions",
                severity=NotificationSeverity.Critical,
            )
        if actions.fire_trip:
            await self._execute_trip(pump, results.npsh_margin_m)

        _, flow_factor = self.config.flow_display()
        _, pressure_factor = self.config.pressure_display()
        await publish_results(
            self.tags,
            results,
            monitor,
            config_faults,
            flow_display_factor=flow_factor,
            pressure_display_factor=pressure_factor,
        )
        await self._save_monitor(monitor)

    async def _execute_trip(self, pump: str, margin: float | None):
        action = self.config.trip_action.value
        margin_txt = f"{margin:.2f} m" if margin is not None else "unknown"

        if action is TripAction.SET_TAG and self.config.trip_tag.tag_name._value:
            tag_name = self.config.trip_tag.tag_name.value
            app_key = self.config.trip_tag.app_name.value
            raw = self.config.trip_tag_value.value
            try:
                value = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                value = raw
            # The processor's set_tag wrapper has no app_key parameter — go
            # through the tag manager for the cross-app write.
            await self.tag_manager.set_tag(tag_name, value, app_key=app_key)
            log.warning("TRIP: set tag %s=%r on app %s", tag_name, value, app_key)
            await self.send_notification(
                f"{pump}: TRIPPED — pump shutdown commanded (NPSH margin {margin_txt}). "
                f"Reset required from the Doover UI.",
                severity=NotificationSeverity.Critical,
            )
        else:
            await self.send_notification(
                f"{pump}: trip condition met (margin {margin_txt}) — "
                f"no trip armed, manual intervention required",
                severity=NotificationSeverity.Critical,
            )

    @ui.handler("reset_trip")
    async def on_reset_trip(self, ctx, value):
        log.info("trip reset requested from UI")
        await self.tags.tripped.set(False)
        await self.tags.trip_reason.set("")
        await self.tags.tripped_warning_hidden.set(True)
        state = self.get_tag("_mon_state") or {}
        state.update({"danger_since": None, "danger_alerted": False})
        await self.set_tag("_mon_state", state)
        await ctx.set_value(None)


def handler(event, context):
    """AWS-Lambda-style entrypoint."""
    from pydoover.processor import run_app

    return run_app(PumpAnalysisProcessorApp(), event, context)
