"""Shared config schema for both pump-analysis deployments.

Written to the conventions the sibling kensho-controller app uses, so the two
schemas read the same way on site:

* Every element carries an explicit ``name=``. The runtime key in
  ``deployment_config`` is that name, not a sanitised display name — so a
  display name can be reworded without silently repointing the widget
  (``widget/src/lib/pump.ts``) or the keys pinned by
  ``tests/test_imports.py::test_config_schema``.
* Conditions that gate a block of fields are named module-level constants
  referring to a sibling by field name, rather than inline ``config.equal``
  calls repeated at every field.
* Numeric fields carry ``minimum``/``maximum`` bounds, so the form rejects a
  value the maths can't use instead of the app discovering it at runtime.
* Expert knobs are marked ``advanced=True`` and drop out of the ordinary form.

Tag references must sit at the top level of the schema: RemoteTag resolution
only scans top-level TagRef elements (same constraint kensho-controller works
around with fixed remote-sensor slots).

A gated field that is switched off still loads its default at runtime, so
``.value`` reads stay safe everywhere — but it moves out of ``properties`` and
into an ``allOf`` branch in the exported JSON schema.
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
    FlowUnits.M3_PER_HOUR: ("m³/h", 1.0),
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


# Conditions gating whole blocks of config, so the form only shows the fields a
# chosen source actually uses. pydoover conditions test equality against one
# non-conditional sibling by field name — they can't chain or test "is set" —
# so each input is fronted by its own source-type enum and referenced here.
SUCTION_FROM_AI = config.equal("suction_source_type", SourceType.ANALOGUE_IN)
SUCTION_FROM_TAG = config.equal("suction_source_type", SourceType.TAG)
DISCHARGE_FROM_AI = config.equal("discharge_source_type", SourceType.ANALOGUE_IN)
DISCHARGE_FROM_TAG = config.equal("discharge_source_type", SourceType.TAG)
FLOW_FROM_AI = config.equal("flow_source_type", SourceType.ANALOGUE_IN)
FLOW_FROM_TAG = config.equal("flow_source_type", SourceType.TAG)
SPEED_FROM_AI = config.equal("speed_source_type", SourceType.ANALOGUE_IN)
SPEED_FROM_TAG = config.equal("speed_source_type", SourceType.TAG)
# Trip wiring: one branch per action, so an alert-only install sees neither.
TRIP_SETS_TAG = config.equal("trip_action", TripAction.SET_TAG)
TRIP_DRIVES_DO = config.equal("trip_action", TripAction.DIGITAL_OUTPUT)

#: doovit analog pins: AI 0-1 are the 0-10 V inputs, AI 2-5 the 4-20 mA loops.
MAX_IO_PIN = 63


class NullSafeArray(config.Array):
    """A ``config.Array`` that tolerates ``null`` as "no items".

    pydoover's ``Array.load_data`` iterates the value straight away, so a stored
    ``"pump_curve": null`` raises ``TypeError`` while the deployment config is
    being loaded — before ``setup()``, so the app never starts. The site writes
    ``null`` for cleared optional fields, which makes that a one-click outage.
    (Lifted from kensho-controller, which hit exactly this.)
    """

    def load_data(self, data):
        super().load_data(data or [])


class ScaledTagRef(config.TagRef):
    """A tag reference bundled with a scale and offset for the raw value.

    Must subclass TagRef (not wrap it in a plain Object): RemoteTag resolution
    only scans top-level TagRef elements on the schema.
    """

    scale = config.Number(
        "Scale",
        description="Multiplier applied to the raw tag value.",
        default=1.0,
        name="scale",
    )
    offset = config.Number(
        "Offset",
        description="Offset added to the raw tag value after scaling.",
        default=0.0,
        name="offset",
    )

    def apply(self, raw: float | None) -> float | None:
        if raw is None:
            return None
        return raw * self.scale.value + self.offset.value

    @property
    def configured(self) -> bool:
        return self.tag_name._value is not config.NotSet


class CurvePointConfig(config.Object):
    """One digitised point off the manufacturer's curve."""

    # No numeric defaults, and nothing required: a row the operator adds and
    # then leaves half-filled must stay loadable. pydoover raises on a missing
    # required element while the deployment config loads — before setup() — so a
    # required field here turns a half-typed curve row into an app that won't
    # start. build_curve() skips incomplete points instead.
    flow_m3h = config.Number(
        "Flow (m³/h)",
        description="Flow at this point, at the curve's reference speed.",
        default=None,
        minimum=0.0,
        name="flow_m3h",
    )
    head_m = config.Number(
        "Head (m)",
        description="Head the pump makes at that flow.",
        default=None,
        minimum=0.0,
        name="head_m",
    )
    npshr_m = config.Number(
        "NPSHr (m)",
        description=(
            "Net positive suction head required, from the manufacturer's curve. "
            "Optional per point — without it there is no margin to alert on."
        ),
        default=None,
        minimum=0.0,
        name="npshr_m",
    )


def _source_tag(
    display_name: str,
    reference_name: str,
    key: str,
    description: str,
    show_if,
) -> ScaledTagRef:
    """A tag-sourced input slot.

    ``reference_name`` is fixed and hidden: it is the handle the matching
    RemoteTag declaration binds by (app_tags.py), never an operator's choice.
    """
    return ScaledTagRef(
        display_name,
        description=description,
        default=None,  # blank slot → skipped by RemoteTag resolution
        reference_name__default=reference_name,
        reference_name__hidden=True,
        show_if=show_if,
        name=key,
    )


class PumpAnalysisConfig(config.Schema):
    pump_name = config.String(
        "Pump Name",
        description="Name this pump is referred to in the UI and notifications.",
        default="Pump",
        name="pump_name",
    )

    # --- Suction pressure ---
    suction_source_type = config.Enum(
        "Suction Source Type",
        description="Where the inlet pressure reading comes from.",
        choices=SourceType,
        default=SourceType.ANALOGUE_IN,
        name="suction_source_type",
    )
    suction_ai_pin = config.Integer(
        "Suction AI Pin",
        description=(
            "Device analog-input pin the inlet transmitter is wired to. On a "
            "doovit, AI 0-1 are the 0-10 V inputs and AI 2-5 the 4-20 mA loops."
        ),
        default=2,
        minimum=0,
        maximum=MAX_IO_PIN,
        show_if=SUCTION_FROM_AI,
        name="suction_ai_pin",
    )
    suction_range_low_bar = config.Number(
        "Suction Range Low (bar)",
        description="Transmitter reading at 4 mA.",
        default=-1.0,
        show_if=SUCTION_FROM_AI,
        name="suction_range_low_bar",
    )
    suction_range_high_bar = config.Number(
        "Suction Range High (bar)",
        description="Transmitter reading at 20 mA.",
        default=10.0,
        show_if=SUCTION_FROM_AI,
        name="suction_range_high_bar",
    )
    suction_tag = _source_tag(
        "Suction Tag",
        "suction_input",
        "suction_tag",
        "Tag carrying suction pressure. Scale/offset must yield bar gauge.",
        SUCTION_FROM_TAG,
    )

    # --- Discharge pressure ---
    discharge_source_type = config.Enum(
        "Discharge Source Type",
        description="Where the discharge pressure reading comes from.",
        choices=SourceType,
        default=SourceType.ANALOGUE_IN,
        name="discharge_source_type",
    )
    discharge_ai_pin = config.Integer(
        "Discharge AI Pin",
        description="Device analog-input pin the discharge transmitter is wired to.",
        default=3,
        minimum=0,
        maximum=MAX_IO_PIN,
        show_if=DISCHARGE_FROM_AI,
        name="discharge_ai_pin",
    )
    discharge_range_low_bar = config.Number(
        "Discharge Range Low (bar)",
        description="Transmitter reading at 4 mA.",
        default=-1.0,
        show_if=DISCHARGE_FROM_AI,
        name="discharge_range_low_bar",
    )
    discharge_range_high_bar = config.Number(
        "Discharge Range High (bar)",
        description="Transmitter reading at 20 mA.",
        default=10.0,
        show_if=DISCHARGE_FROM_AI,
        name="discharge_range_high_bar",
    )
    discharge_tag = _source_tag(
        "Discharge Tag",
        "discharge_input",
        "discharge_tag",
        "Tag carrying discharge pressure. Scale/offset must yield bar gauge.",
        DISCHARGE_FROM_TAG,
    )

    # --- Flow (optional) ---
    flow_source_type = config.Enum(
        "Flow Source Type",
        description="With no flow meter, flow is inferred from the pump curve.",
        choices=SourceType,
        default=SourceType.NONE,
        name="flow_source_type",
    )
    flow_ai_pin = config.Integer(
        "Flow AI Pin",
        description="Device analog-input pin the flow meter is wired to.",
        default=4,
        minimum=0,
        maximum=MAX_IO_PIN,
        show_if=FLOW_FROM_AI,
        name="flow_ai_pin",
    )
    flow_range_low_m3h = config.Number(
        "Flow Range Low (m³/h)",
        description="Flow the meter reads at 4 mA.",
        default=0.0,
        show_if=FLOW_FROM_AI,
        name="flow_range_low_m3h",
    )
    flow_range_high_m3h = config.Number(
        "Flow Range High (m³/h)",
        description="Flow the meter reads at 20 mA.",
        default=200.0,
        show_if=FLOW_FROM_AI,
        name="flow_range_high_m3h",
    )
    flow_tag = _source_tag(
        "Flow Tag",
        "flow_input",
        "flow_tag",
        "Tag carrying measured flow. Scale/offset must yield m³/h.",
        FLOW_FROM_TAG,
    )

    # --- Speed ---
    speed_source_type = config.Enum(
        "Speed Source Type",
        description=(
            "Engine speed. Usually a tag from the engine controller app "
            "(e.g. kensho engine_rpm)."
        ),
        choices=SourceType,
        default=SourceType.TAG,
        name="speed_source_type",
    )
    speed_ai_pin = config.Integer(
        "Speed AI Pin",
        description="Device analog-input pin a speed transmitter is wired to.",
        default=5,
        minimum=0,
        maximum=MAX_IO_PIN,
        show_if=SPEED_FROM_AI,
        name="speed_ai_pin",
    )
    speed_range_low_rpm = config.Number(
        "Speed Range Low (RPM)",
        description="Engine speed the transmitter reads at 4 mA.",
        default=0.0,
        minimum=0.0,
        show_if=SPEED_FROM_AI,
        name="speed_range_low_rpm",
    )
    speed_range_high_rpm = config.Number(
        "Speed Range High (RPM)",
        description="Engine speed the transmitter reads at 20 mA.",
        default=3000.0,
        minimum=0.0,
        show_if=SPEED_FROM_AI,
        name="speed_range_high_rpm",
    )
    speed_tag = _source_tag(
        "Speed Tag",
        "speed_input",
        "speed_tag",
        "Tag carrying engine RPM.",
        SPEED_FROM_TAG,
    )
    pump_speed_ratio = config.Number(
        "Pump Speed Ratio",
        description=(
            "pump_rpm = engine_rpm x ratio + offset. 1.0 for direct drive; the "
            "gearbox/pulley ratio otherwise. Everything downstream — the "
            "affinity-scaled curve, NPSHr, and Minimum Running Speed — is in "
            "PUMP rpm, so this has to be right before those thresholds mean "
            "anything."
        ),
        default=1.0,
        minimum=0.01,
        maximum=20.0,
        name="pump_speed_ratio",
    )
    pump_speed_offset_rpm = config.Number(
        "Pump Speed Offset (RPM)",
        description="Linear offset of the speed transform. Should be 0 for any rigid drive.",
        default=0.0,
        advanced=True,
        name="pump_speed_offset_rpm",
    )

    # --- Water temperature ---
    water_temperature_tag = ScaledTagRef(
        "Water Temperature Tag",
        description=(
            "Optional tag carrying water temperature (degrees C). Drives vapour "
            "pressure in NPSHa."
        ),
        default=None,
        reference_name__default="water_temp_input",
        reference_name__hidden=True,
        name="water_temperature_tag",
    )
    default_water_temperature_c = config.Number(
        "Default Water Temperature (C)",
        description="Used when no temperature tag is configured.",
        default=20.0,
        minimum=0.0,
        maximum=100.0,
        name="default_water_temperature_c",
    )

    # --- Display ---
    show_widget_gauges = config.Boolean(
        "Show Widget Gauges",
        description=(
            "Show flow/margin gauges inside the pump-curve widget. Testing aid — "
            "production installs use the native gauge variables instead."
        ),
        default=False,
        advanced=True,
        name="show_widget_gauges",
    )
    flow_display_units = config.Enum(
        "Flow Display Units",
        description=(
            "Units flow is displayed in (UI and widget). Internal maths and the "
            "curve stay in m³/h."
        ),
        choices=FlowUnits,
        default=FlowUnits.ML_PER_DAY,
        name="flow_display_units",
    )
    pressure_display_units = config.Enum(
        "Pressure Display Units",
        description=(
            "Units inlet/discharge pressure are displayed in. Metres of head is "
            "density-corrected at the default water temperature. Internal maths "
            "stays in bar/kPa."
        ),
        choices=PressureUnits,
        default=PressureUnits.METRES_HEAD,
        name="pressure_display_units",
    )

    # --- Pump curve ---
    bep_flow_m3h = config.Number(
        "BEP Flow (m³/h)",
        description=(
            "Best-efficiency-point flow at the curve reference speed, from the "
            "manufacturer. Enables the efficient-zone shading and % of BEP output."
        ),
        default=None,
        minimum=0.0,
        name="bep_flow_m3h",
    )
    pump_curve = NullSafeArray(
        "Pump Curve",
        element=CurvePointConfig("Point", default=None),
        description=(
            "Manufacturer head-flow(-NPSHr) points at the reference speed. "
            "Digitise from the datasheet."
        ),
        name="pump_curve",
    )
    curve_reference_speed_rpm = config.Number(
        "Curve Reference Speed (RPM)",
        description="Pump speed the curve points were published at.",
        default=None,
        minimum=1.0,
        maximum=10000.0,
        name="curve_reference_speed_rpm",
    )

    # --- Site ---
    site_elevation_m = config.Number(
        "Site Elevation (m)",
        description=(
            "Metres above sea level; sets barometric pressure for NPSHa. Worth "
            "getting right — every 1000 m costs about 1.1 m of NPSHa."
        ),
        default=0.0,
        minimum=-500.0,
        maximum=6000.0,
        name="site_elevation_m",
    )
    gauge_separation_m = config.Number(
        "Gauge Separation (m)",
        description="Discharge gauge height minus suction gauge height.",
        default=0.0,
        name="gauge_separation_m",
    )
    suction_gauge_height_above_impeller_m = config.Number(
        "Suction Gauge Height Above Impeller (m)",
        description="Height of the suction tapping above the impeller eye (negative if below).",
        default=0.0,
        name="suction_gauge_height_above_impeller_m",
    )
    suction_pipe_id_mm = config.Number(
        "Suction Pipe ID (mm)",
        description="Optional; enables velocity-head terms.",
        default=None,
        minimum=1.0,
        maximum=5000.0,
        advanced=True,
        name="suction_pipe_id_mm",
    )
    discharge_pipe_id_mm = config.Number(
        "Discharge Pipe ID (mm)",
        description="Optional; enables velocity-head terms.",
        default=None,
        minimum=1.0,
        maximum=5000.0,
        advanced=True,
        name="discharge_pipe_id_mm",
    )

    # --- Protection ---
    minimum_running_speed_rpm = config.Number(
        "Minimum Running Speed (RPM)",
        description=(
            "Below this PUMP speed the pump is treated as not running and no "
            "hydraulic outputs are produced. Remember this is engine rpm through "
            "Pump Speed Ratio, not engine rpm itself."
        ),
        default=300.0,
        minimum=0.0,
        maximum=10000.0,
        name="minimum_running_speed_rpm",
    )
    start_inhibit_seconds = config.Number(
        "Start Inhibit (Seconds)",
        description="Alerts and trips are suppressed for this long after the pump starts (priming).",
        default=60.0,
        minimum=0.0,
        maximum=3600.0,
        name="start_inhibit_seconds",
    )
    npsh_warning_margin_m = config.Number(
        "NPSH Warning Margin (m)",
        description="NPSHa - NPSHr below this raises the marginal alert.",
        default=1.5,
        minimum=0.0,
        maximum=50.0,
        name="npsh_warning_margin_m",
    )
    npsh_danger_margin_m = config.Number(
        "NPSH Danger Margin (m)",
        description="NPSHa - NPSHr below this is the danger/trip condition.",
        default=0.5,
        minimum=0.0,
        maximum=50.0,
        name="npsh_danger_margin_m",
    )
    alert_debounce_seconds = config.Number(
        "Alert Debounce (Seconds)",
        description="A condition must persist this long before an alert is sent.",
        default=30.0,
        minimum=0.0,
        maximum=3600.0,
        advanced=True,
        name="alert_debounce_seconds",
    )
    trip_debounce_seconds = config.Number(
        "Trip Debounce (Seconds)",
        description="DANGER must persist this long before the trip action fires.",
        default=10.0,
        minimum=0.0,
        maximum=3600.0,
        advanced=True,
        name="trip_debounce_seconds",
    )
    trip_action = config.Enum(
        "Trip Action",
        description=(
            "NONE = alert only (commissioning default). Arm per pump only after "
            "thresholds are proven on site."
        ),
        choices=TripAction,
        default=TripAction.NONE,
        name="trip_action",
    )
    trip_tag = config.TagRef(
        "Trip Tag",
        description="For SET_TAG: the tag to write (e.g. an engine controller stop command).",
        default=None,
        reference_name__default="trip_command",
        reference_name__hidden=True,
        show_if=TRIP_SETS_TAG,
        name="trip_tag",
    )
    trip_tag_value = config.String(
        "Trip Tag Value",
        description=(
            'Value written to the trip tag. Parsed as JSON where possible '
            '(true, 0, "stop").'
        ),
        default="true",
        show_if=TRIP_SETS_TAG,
        name="trip_tag_value",
    )
    trip_do_pin = config.Integer(
        "Trip DO Pin",
        description="For DIGITAL_OUTPUT: the doovit DO wired to the panel stop input.",
        default=None,
        minimum=0,
        maximum=MAX_IO_PIN,
        show_if=TRIP_DRIVES_DO,
        name="trip_do_pin",
    )
    trip_do_value = config.Boolean(
        "Trip DO Value",
        description="Level driven onto the trip DO when tripping.",
        default=True,
        show_if=TRIP_DRIVES_DO,
        name="trip_do_value",
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
