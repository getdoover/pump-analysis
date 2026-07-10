"""Shared config schema for both pump-analysis deployments.

Field-naming caution: a config element's runtime key in deployment_config is
derived from its sanitised DISPLAY NAME, not the Python attribute. The widget
reads deployment_config by those keys, so display names here are chosen to
sanitise to exactly the attribute name — change them together or not at all.

Tag references must sit at the top level of the schema: RemoteTag resolution
only scans top-level TagRef elements (see leachate-telemetry's ScaledTagRef).
"""

from __future__ import annotations

import enum

from pydoover import config

from . import pump_math
from .curve import CurvePoint, PumpCurve
from .engine import SiteParams


class SourceType(enum.Enum):
    NONE = "none"
    ANALOGUE_IN = "analogue_in"
    TAG = "tag"


class FlowUnits(enum.Enum):
    ML_PER_DAY = "ml_per_day"
    M3_PER_HOUR = "m3_per_hour"
    L_PER_S = "l_per_s"


#: display label and m³/h -> unit conversion factor
FLOW_UNIT_INFO: dict[FlowUnits, tuple[str, float]] = {
    FlowUnits.ML_PER_DAY: ("ML/day", 24.0 / 1000.0),
    FlowUnits.M3_PER_HOUR: ("m3/h", 1.0),
    FlowUnits.L_PER_S: ("L/s", 1.0 / 3.6),
}


class PressureUnits(enum.Enum):
    METRES_HEAD = "metres_head"
    BAR = "bar"
    KPA = "kpa"
    PSI = "psi"


#: display label and bar -> unit factor. METRES_HEAD is density-dependent and
#: resolved at runtime (see PumpAnalysisConfig.pressure_display), so its factor
#: here is the 20 °C reference value.
PRESSURE_UNIT_INFO: dict[PressureUnits, tuple[str, float]] = {
    PressureUnits.METRES_HEAD: ("m head", 10.1997),
    PressureUnits.BAR: ("bar", 1.0),
    PressureUnits.KPA: ("kPa", 100.0),
    PressureUnits.PSI: ("psi", 14.50377),
}


class TripAction(enum.Enum):
    NONE = "none"  # alert only — the commissioning default
    SET_TAG = "set_tag"  # write a value to another app's tag (e.g. Kensho stop)
    DIGITAL_OUTPUT = "digital_output"  # drive a doovit DO (device app only)


class ScaledTagRef(config.TagRef):
    """A tag reference bundled with a scale and offset for the raw value.

    Must subclass TagRef (not wrap it in a plain Object): RemoteTag resolution
    only scans top-level TagRef elements on the schema.
    """

    scale = config.Number(
        "Scale",
        default=1.0,
        description="Multiplier applied to the raw tag value.",
    )
    offset = config.Number(
        "Offset",
        default=0.0,
        description="Offset added to the raw tag value after scaling.",
    )

    def apply(self, raw: float | None) -> float | None:
        if raw is None:
            return None
        return raw * self.scale.value + self.offset.value

    @property
    def configured(self) -> bool:
        return self.tag_name._value is not config.NotSet


class CurvePointConfig(config.Object):
    flow_m3h = config.Number("Flow (m3/h)")
    head_m = config.Number("Head (m)")
    npshr_m = config.Number(
        "NPSHr (m)",
        default=None,
        description="Net positive suction head required, from the manufacturer's curve. Optional per point.",
    )


class PumpAnalysisConfig(config.Schema):
    pump_name = config.String("Pump Name", default="Pump")

    # ------------------------------------------------------- suction pressure
    suction_source_type = config.Enum(
        "Suction Source Type", choices=SourceType, default=SourceType.ANALOGUE_IN
    )
    suction_ai_pin = config.Integer("Suction AI Pin", default=2)
    suction_range_low_bar = config.Number(
        "Suction Range Low (bar)",
        default=-1.0,
        description="Transmitter reading at 4 mA.",
    )
    suction_range_high_bar = config.Number(
        "Suction Range High (bar)",
        default=10.0,
        description="Transmitter reading at 20 mA.",
    )
    suction_tag = ScaledTagRef(
        "Suction Tag",
        default=None,
        description="Tag carrying suction pressure. Scale/offset must yield bar gauge.",
        reference_name__default="suction_input",
        reference_name__hidden=True,
    )

    # ----------------------------------------------------- discharge pressure
    discharge_source_type = config.Enum(
        "Discharge Source Type", choices=SourceType, default=SourceType.ANALOGUE_IN
    )
    discharge_ai_pin = config.Integer("Discharge AI Pin", default=3)
    discharge_range_low_bar = config.Number(
        "Discharge Range Low (bar)", default=-1.0
    )
    discharge_range_high_bar = config.Number(
        "Discharge Range High (bar)", default=10.0
    )
    discharge_tag = ScaledTagRef(
        "Discharge Tag",
        default=None,
        description="Tag carrying discharge pressure. Scale/offset must yield bar gauge.",
        reference_name__default="discharge_input",
        reference_name__hidden=True,
    )

    # ------------------------------------------------------ flow (optional)
    flow_source_type = config.Enum(
        "Flow Source Type",
        choices=SourceType,
        default=SourceType.NONE,
        description="With no flow meter, flow is inferred from the pump curve.",
    )
    flow_ai_pin = config.Integer("Flow AI Pin", default=4)
    flow_range_low_m3h = config.Number("Flow Range Low (m3/h)", default=0.0)
    flow_range_high_m3h = config.Number("Flow Range High (m3/h)", default=200.0)
    flow_tag = ScaledTagRef(
        "Flow Tag",
        default=None,
        description="Tag carrying measured flow. Scale/offset must yield m3/h.",
        reference_name__default="flow_input",
        reference_name__hidden=True,
    )

    # -------------------------------------------------------------- speed
    speed_source_type = config.Enum(
        "Speed Source Type",
        choices=SourceType,
        default=SourceType.TAG,
        description="Engine speed. Usually a tag from the engine controller app (e.g. kensho engine_rpm).",
    )
    speed_ai_pin = config.Integer("Speed AI Pin", default=5)
    speed_range_low_rpm = config.Number("Speed Range Low (RPM)", default=0.0)
    speed_range_high_rpm = config.Number("Speed Range High (RPM)", default=3000.0)
    speed_tag = ScaledTagRef(
        "Speed Tag",
        default=None,
        description="Tag carrying engine RPM.",
        reference_name__default="speed_input",
        reference_name__hidden=True,
    )
    pump_speed_ratio = config.Number(
        "Pump Speed Ratio",
        default=1.0,
        description="pump_rpm = engine_rpm x ratio + offset. 1.0 for direct drive; gearbox/pulley ratio otherwise.",
    )
    pump_speed_offset_rpm = config.Number(
        "Pump Speed Offset (RPM)",
        default=0.0,
        description="Linear offset of the speed transform. Should be 0 for any rigid drive.",
    )

    # -------------------------------------------------------- water temperature
    water_temperature_tag = ScaledTagRef(
        "Water Temperature Tag",
        default=None,
        description="Optional tag carrying water temperature (degrees C). Drives vapour pressure in NPSHa.",
        reference_name__default="water_temp_input",
        reference_name__hidden=True,
    )
    default_water_temperature_c = config.Number(
        "Default Water Temperature (C)",
        default=20.0,
        description="Used when no temperature tag is configured.",
    )

    # -------------------------------------------------------------- display
    show_widget_gauges = config.Boolean(
        "Show Widget Gauges",
        default=False,
        description="Show flow/margin gauges inside the pump-curve widget. Testing aid — production installs use the native gauge variables instead.",
    )
    flow_display_units = config.Enum(
        "Flow Display Units",
        choices=FlowUnits,
        default=FlowUnits.ML_PER_DAY,
        description="Units flow is displayed in (UI and widget). Internal maths and the curve stay in m3/h.",
    )
    pressure_display_units = config.Enum(
        "Pressure Display Units",
        choices=PressureUnits,
        default=PressureUnits.METRES_HEAD,
        description="Units inlet/discharge pressure are displayed in. Metres of head is density-corrected at the default water temperature. Internal maths stays in bar/kPa.",
    )

    # ------------------------------------------------------------- pump curve
    bep_flow_m3h = config.Number(
        "BEP Flow (m3/h)",
        default=None,
        description="Best-efficiency-point flow at the curve reference speed, from the manufacturer. Enables the efficient-zone shading and % of BEP output.",
    )
    pump_curve = config.Array(
        "Pump Curve",
        element=CurvePointConfig("Point"),
        description="Manufacturer head-flow(-NPSHr) points at the reference speed. Digitise from the datasheet.",
    )
    curve_reference_speed_rpm = config.Number(
        "Curve Reference Speed (RPM)",
        default=None,
        description="Pump speed the curve points were published at.",
    )

    # ----------------------------------------------------------------- site
    site_elevation_m = config.Number(
        "Site Elevation (m)",
        default=0.0,
        description="Metres above sea level; sets barometric pressure for NPSHa.",
    )
    gauge_separation_m = config.Number(
        "Gauge Separation (m)",
        default=0.0,
        description="Discharge gauge height minus suction gauge height.",
    )
    suction_gauge_height_above_impeller_m = config.Number(
        "Suction Gauge Height Above Impeller (m)",
        default=0.0,
        description="Height of the suction tapping above the impeller eye (negative if below).",
    )
    suction_pipe_id_mm = config.Number(
        "Suction Pipe ID (mm)",
        default=None,
        description="Optional; enables velocity-head terms.",
    )
    discharge_pipe_id_mm = config.Number(
        "Discharge Pipe ID (mm)",
        default=None,
        description="Optional; enables velocity-head terms.",
    )

    # ------------------------------------------------------------ protection
    minimum_running_speed_rpm = config.Number(
        "Minimum Running Speed (RPM)",
        default=300.0,
        description="Below this pump speed the pump is treated as not running.",
    )
    start_inhibit_seconds = config.Number(
        "Start Inhibit (Seconds)",
        default=60.0,
        description="Alerts and trips are suppressed for this long after the pump starts (priming).",
    )
    npsh_warning_margin_m = config.Number(
        "NPSH Warning Margin (m)",
        default=1.5,
        description="NPSHa - NPSHr below this raises the marginal alert.",
    )
    npsh_danger_margin_m = config.Number(
        "NPSH Danger Margin (m)",
        default=0.5,
        description="NPSHa - NPSHr below this is the danger/trip condition.",
    )
    alert_debounce_seconds = config.Number(
        "Alert Debounce (Seconds)",
        default=30.0,
        description="A condition must persist this long before an alert is sent.",
    )
    trip_debounce_seconds = config.Number(
        "Trip Debounce (Seconds)",
        default=10.0,
        description="DANGER must persist this long before the trip action fires.",
    )
    trip_action = config.Enum(
        "Trip Action",
        choices=TripAction,
        default=TripAction.NONE,
        description="NONE = alert only (commissioning default). Arm per pump only after thresholds are proven on site.",
    )
    trip_tag = config.TagRef(
        "Trip Tag",
        default=None,
        description="For SET_TAG: the tag to write (e.g. an engine controller stop command).",
        reference_name__default="trip_command",
        reference_name__hidden=True,
    )
    trip_tag_value = config.String(
        "Trip Tag Value",
        default="true",
        description="Value written to the trip tag. Parsed as JSON where possible (true, 0, \"stop\").",
    )
    trip_do_pin = config.Integer(
        "Trip DO Pin",
        default=None,
        description="For DIGITAL_OUTPUT: the doovit DO wired to the panel stop input.",
    )
    trip_do_value = config.Boolean(
        "Trip DO Value",
        default=True,
        description="Level driven onto the trip DO when tripping.",
    )

    # ---------------------------------------------------------------- widget
    dv_widget_url = config.String(
        "DV Widget URL",
        default=None,
        description="URL of the pump-curve widget bundle (Module Federation remote entry).",
    )

    # ------------------------------------------------------------- helpers

    def flow_display(self) -> tuple[str, float]:
        """(unit label, m³/h -> display conversion factor)."""
        return FLOW_UNIT_INFO[self.flow_display_units.value]

    def pressure_display(self) -> tuple[str, float]:
        """(unit label, bar -> display conversion factor).

        Metres of head depends on fluid density, so it is resolved against the
        configured default water temperature rather than the 20 °C reference.
        """
        units = self.pressure_display_units.value
        label, factor = PRESSURE_UNIT_INFO[units]
        if units is PressureUnits.METRES_HEAD:
            factor = pump_math.metres_head_per_bar(
                self.default_water_temperature_c.value or 20.0
            )
        return label, factor

    def to_site_params(self) -> SiteParams:
        return SiteParams(
            elevation_m=self.site_elevation_m.value or 0.0,
            gauge_separation_m=self.gauge_separation_m.value or 0.0,
            suction_gauge_above_impeller_m=(
                self.suction_gauge_height_above_impeller_m.value or 0.0
            ),
            suction_pipe_id_mm=self.suction_pipe_id_mm.value,
            discharge_pipe_id_mm=self.discharge_pipe_id_mm.value,
            default_water_temp_c=self.default_water_temperature_c.value or 20.0,
            speed_ratio=self.pump_speed_ratio.value or 1.0,
            speed_offset=self.pump_speed_offset_rpm.value or 0.0,
            min_running_rpm=self.minimum_running_speed_rpm.value or 300.0,
            npsh_warning_margin_m=self.npsh_warning_margin_m.value or 1.5,
            npsh_danger_margin_m=self.npsh_danger_margin_m.value or 0.5,
            bep_flow_m3h=self.bep_flow_m3h.value,
        )

    def build_curve(self) -> PumpCurve | None:
        """The configured PumpCurve, or None when not (validly) configured."""
        ref_rpm = self.curve_reference_speed_rpm.value
        # Array-of-Object config yields CurvePointConfig instances, not dicts.
        elements = self.pump_curve.elements or []
        points = [
            CurvePoint(
                flow_m3h=float(p.flow_m3h.value),
                head_m=float(p.head_m.value),
                npshr_m=None if p.npshr_m.value is None else float(p.npshr_m.value),
            )
            for p in elements
            if p.flow_m3h.value is not None and p.head_m.value is not None
        ]
        if not ref_rpm or len(points) < 2:
            return None
        try:
            return PumpCurve(points, reference_rpm=ref_rpm)
        except ValueError:
            return None
