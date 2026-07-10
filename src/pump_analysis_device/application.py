import json
import logging
import time

from pydoover import ui
from pydoover.docker import Application
from pydoover.models import NotificationSeverity

from pump_analysis_common.app_config import TripAction
from pump_analysis_common.engine import analyse
from pump_analysis_common.protection import ProtectionMonitor, RUNNING_STATES
from pump_analysis_common.publish import publish_results
from pump_analysis_common.sources import gather_readings

from .app_config import PumpAnalysisDeviceConfig
from pump_analysis_common.app_tags import PumpAnalysisTags
from pump_analysis_common.app_ui import PumpAnalysisUI

log = logging.getLogger(__name__)

# RemoteTag attribute per TagRef reference name (see app_config / app_tags).
REMOTE_TAGS = {
    "suction_input": "raw_suction",
    "discharge_input": "raw_discharge",
    "flow_input": "raw_flow",
    "speed_input": "raw_speed",
    "water_temp_input": "raw_water_temp",
}


class PumpAnalysisDeviceApplication(Application):
    config_cls = PumpAnalysisDeviceConfig
    tags_cls = PumpAnalysisTags
    ui_cls = PumpAnalysisUI

    config: PumpAnalysisDeviceConfig
    tags: PumpAnalysisTags

    async def setup(self):
        self.site_params = self.config.to_site_params()
        self.curve = self.config.build_curve()
        if self.curve is None:
            log.warning(
                "no valid pump curve configured — flow inference and NPSH margin disabled"
            )
        if (self.config.pump_speed_offset_rpm.value or 0.0) != 0.0:
            log.warning(
                "pump speed offset is non-zero: physically dubious for a rigid drive — confirm the transform"
            )
        self.monitor = ProtectionMonitor(
            start_inhibit_s=self.config.start_inhibit_seconds.value,
            alert_debounce_s=self.config.alert_debounce_seconds.value,
            trip_debounce_s=self.config.trip_debounce_seconds.value,
        )
        self._trip_do_driven = False

    def _get_remote(self, reference_name: str):
        return getattr(self.tags, REMOTE_TAGS[reference_name]).get()

    async def main_loop(self):
        now = time.monotonic()
        readings, config_faults = await gather_readings(
            self.config, fetch_ai=self.fetch_ai, get_remote=self._get_remote
        )
        await self.tags.engine_rpm.set(readings.engine_rpm)

        # Probe run-state first so the inhibit window is tracked correctly.
        probe = analyse(readings, self.curve, self.site_params)
        running = probe.state in RUNNING_STATES
        inhibit = self.monitor.in_start_inhibit(running, now)
        results = analyse(
            readings, self.curve, self.site_params, in_start_inhibit=inhibit
        )

        actions = self.monitor.update(results.state, now)
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
            self.monitor,
            config_faults,
            flow_display_factor=flow_factor,
            pressure_display_factor=pressure_factor,
        )

    async def _execute_trip(self, pump: str, margin: float | None):
        action = self.config.trip_action.value
        margin_txt = f"{margin:.2f} m" if margin is not None else "unknown"

        if action is TripAction.NONE:
            log.warning("trip condition met but trip action is NONE (alert-only)")
            await self.send_notification(
                f"{pump}: trip condition met (margin {margin_txt}) — "
                f"no trip armed, manual intervention required",
                severity=NotificationSeverity.Critical,
            )
            return

        if action is TripAction.DIGITAL_OUTPUT:
            pin = self.config.trip_do_pin.value
            if pin is None:
                log.error("trip action DIGITAL_OUTPUT but no DO pin configured")
                return
            level = bool(self.config.trip_do_value.value)
            await self.set_do(int(pin), level)
            self._trip_do_driven = True
            log.warning("TRIP: drove DO%s to %s", pin, level)

        elif action is TripAction.SET_TAG:
            if self.config.trip_tag.tag_name._value is None:
                log.error("trip action SET_TAG but no trip tag configured")
                return
            tag_name = self.config.trip_tag.tag_name.value
            app_key = self.config.trip_tag.app_name.value
            raw = self.config.trip_tag_value.value
            try:
                value = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                value = raw
            await self.set_tag(tag_name, value, app_key=app_key)
            log.warning("TRIP: set tag %s=%r on app %s", tag_name, value, app_key)

        await self.send_notification(
            f"{pump}: TRIPPED — pump shutdown commanded (NPSH margin {margin_txt}). "
            f"Reset required from the Doover UI.",
            severity=NotificationSeverity.Critical,
        )

    @ui.handler("reset_trip")
    async def on_reset_trip(self, ctx, value):
        log.info("trip reset requested from UI")
        self.monitor.reset()
        if self._trip_do_driven and self.config.trip_do_pin.value is not None:
            await self.set_do(
                int(self.config.trip_do_pin.value),
                not bool(self.config.trip_do_value.value),
            )
            self._trip_do_driven = False
        await self.tags.tripped.set(False)
        await self.tags.trip_reason.set("")
        await self.tags.tripped_warning_hidden.set(True)
        await ctx.set_value(None)
