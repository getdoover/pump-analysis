from pydoover import ui

from .app_config import FLOW_UNIT_INFO, SourceType
from .app_tags import PumpAnalysisTags as T


class PumpAnalysisUI(ui.UI):
    async def setup(self):
        """Runs after config injection — safe to read config values here.

        (Reading them in __init__ crashes: the schema exists but no data has
        been loaded yet, and .value raises rather than returning the default.)
        """
        await super().setup()
        if self.config is None:
            return
        try:
            self._apply_config()
        except Exception:  # never let a display nicety take the app down
            pass

    def _apply_config(self):
        cfg = self.config
        label, fx = FLOW_UNIT_INFO[cfg.flow_display_units.value]

        # Flow gauge: named for what it is — calculated (curve-inferred) when
        # there is no flow meter, plain measured flow when there is one.
        flow_el = self._elements["calculated_flow"]
        inferred = cfg.flow_source_type.value is SourceType.NONE
        flow_el.display_name = "Calculated Flow" if inferred else "Flow"
        flow_el.units = label
        # Confidence only means something for calculated flow.
        self._elements["flow_confidence_gauge"].hidden = not inferred

        # Gauge ranges from the configured curve/BEP, in display units.
        points = cfg.pump_curve.elements or []
        flows = [p.flow_m3h.value for p in points if p.flow_m3h.value is not None]
        if flows:
            max_flow = max(flows) * fx
            bep = cfg.bep_flow_m3h.value
            if bep:
                bep *= fx
                flow_el.ranges = [
                    ui.Range("Low flow", 0, round(bep * 0.7, 3), ui.Colour.yellow),
                    ui.Range("Efficient", round(bep * 0.7, 3), round(bep * 1.2, 3), ui.Colour.green),
                    ui.Range("High flow", round(bep * 1.2, 3), round(max_flow, 3), ui.Colour.yellow),
                ]
            else:
                flow_el.ranges = [ui.Range("Range", 0, round(max_flow, 3), ui.Colour.blue)]

        # Margin gauge ranges follow the configured thresholds.
        warn = cfg.npsh_warning_margin_m.value
        danger = cfg.npsh_danger_margin_m.value
        self._elements["npsh_margin"].ranges = [
            ui.Range("Danger", -1, danger, ui.Colour.red),
            ui.Range("Marginal", danger, warn, ui.Colour.yellow),
            ui.Range("Healthy", warn, warn * 2, ui.Colour.green),
        ]

        # Margin plot threshold lines follow the same configured thresholds.
        margin_series = next(
            (s for s in self._elements["npsh_plot"].series if s.name == "margin_m"), None
        )
        if margin_series is not None:
            margin_series.thresholds = [
                ui.Threshold("Warning", warn, ui.Colour.yellow),
                ui.Threshold("Danger", danger, ui.Colour.red),
            ]

        # Pressure gauges span the transmitter ranges, converted to the
        # configured display units. Inlet severity runs on vacuum depth (the
        # cavitation precursor); discharge low-end means the pump isn't making
        # head. Thresholds are defined in bar and scaled with everything else.
        p_label, pf = cfg.pressure_display()
        self._elements["inlet_pressure"].units = p_label
        self._elements["discharge_pressure"].units = p_label
        # m head reads whole-number-ish; bar needs two decimals.
        precision = 1 if abs(pf) >= 5 else 2
        self._elements["inlet_pressure"].precision = precision
        self._elements["discharge_pressure"].precision = precision

        s_lo = cfg.suction_range_low_bar.value
        s_hi = cfg.suction_range_high_bar.value
        if s_lo is not None and s_hi is not None and s_hi > s_lo:
            self._elements["inlet_pressure"].ranges = [
                ui.Range("Deep vacuum", round(s_lo * pf, 2), round(-0.5 * pf, 2), ui.Colour.red),
                ui.Range("Vacuum", round(-0.5 * pf, 2), round(-0.15 * pf, 2), ui.Colour.yellow),
                ui.Range("Healthy", round(-0.15 * pf, 2), round(s_hi * pf, 2), ui.Colour.green),
            ]
        d_lo = cfg.discharge_range_low_bar.value
        d_hi = cfg.discharge_range_high_bar.value
        if d_lo is not None and d_hi is not None and d_hi > d_lo:
            span = d_hi - d_lo
            self._elements["discharge_pressure"].ranges = [
                ui.Range("Low", round(d_lo * pf, 2), round((d_lo + 0.25 * span) * pf, 2), ui.Colour.yellow),
                ui.Range("Normal", round((d_lo + 0.25 * span) * pf, 2), round((d_lo + 0.85 * span) * pf, 2), ui.Colour.green),
                ui.Range("High", round((d_lo + 0.85 * span) * pf, 2), round(d_hi * pf, 2), ui.Colour.yellow),
            ]

    # ---- native gauges (production home of the headline values; the widget's
    #      own gauges are a testing aid behind Show Widget Gauges)
    calculated_flow = ui.NumericVariable(
        "Calculated Flow",
        value=T.flow_display,
        name="calculated_flow",
        units="ML/day",
        precision=2,
        position=2,
        form=ui.Widget.radial,
        ranges=[ui.Range("Range", 0, 5, ui.Colour.blue)],
    )
    flow_confidence_gauge = ui.NumericVariable(
        "Calculated Flow Confidence",
        value=T.flow_confidence,
        name="flow_confidence_gauge",
        precision=2,
        position=3,
        form=ui.Widget.linear,
        ranges=[
            ui.Range("Low", 0, 0.4, ui.Colour.red),
            ui.Range("Fair", 0.4, 0.7, ui.Colour.yellow),
            ui.Range("Good", 0.7, 1.0, ui.Colour.green),
        ],
    )
    npsh_margin = ui.NumericVariable(
        "NPSH Margin",
        value=T.npsh_margin_m,
        name="npsh_margin",
        units="m",
        precision=2,
        position=4,
        form=ui.Widget.radial,
        ranges=[
            ui.Range("Danger", -1, 0.5, ui.Colour.red),
            ui.Range("Marginal", 0.5, 1.5, ui.Colour.yellow),
            ui.Range("Healthy", 1.5, 3, ui.Colour.green),
        ],
    )

    inlet_pressure = ui.NumericVariable(
        "Inlet Pressure",
        value=T.suction_display,
        name="inlet_pressure",
        units="m head",
        precision=1,
        position=5,
        form=ui.Widget.linear,
        ranges=[
            ui.Range("Deep vacuum", -10.2, -5.1, ui.Colour.red),
            ui.Range("Vacuum", -5.1, -1.53, ui.Colour.yellow),
            ui.Range("Healthy", -1.53, 102, ui.Colour.green),
        ],
    )
    discharge_pressure = ui.NumericVariable(
        "Discharge Pressure",
        value=T.discharge_display,
        name="discharge_pressure",
        units="m head",
        precision=1,
        position=6,
        form=ui.Widget.linear,
        ranges=[
            ui.Range("Low", -10.2, 17.85, ui.Colour.yellow),
            ui.Range("Normal", 17.85, 85.17, ui.Colour.green),
            ui.Range("High", 85.17, 102, ui.Colour.yellow),
        ],
    )

    # Custom XY pump-curve widget (Module Federation remote; see widget/).
    pump_curve_widget = ui.RemoteComponent(
        name="PumpAnalysisWidget",
        display_name="Pump Curve",
        component_url="$config.app().dv_widget_url",
        scope="PumpAnalysisWidget",
        module="./PumpAnalysisWidget",
        app_key="$config.app().APP_KEY",
        position=7,
    )

    # ---- warnings (visibility driven by *_hidden tags)
    tripped_warning = ui.WarningIndicator(
        "tripped_warning", "Pump TRIPPED — reset required", hidden=T.tripped_warning_hidden
    )
    danger_warning = ui.WarningIndicator(
        "danger_warning", "Cavitation risk: NPSH margin critical", hidden=T.danger_warning_hidden
    )
    marginal_warning = ui.WarningIndicator(
        "marginal_warning", "NPSH margin marginal", hidden=T.marginal_warning_hidden
    )
    fault_warning = ui.WarningIndicator(
        "fault_warning", "Sensor / configuration fault", hidden=T.fault_warning_hidden
    )

    # ---- headline values
    tdh = ui.NumericVariable(
        "Total Head", value=T.tdh_m, name="tdh", units="m", precision=1, position=12
    )
    pump_rpm = ui.NumericVariable(
        "Pump Speed",
        value=T.pump_rpm,
        name="pump_rpm",
        units="RPM",
        precision=0,
        position=13,
    )
    state = ui.TextVariable("Status", value=T.state, name="state", position=14)
    pct_of_bep = ui.NumericVariable(
        "BEP Flow",
        value=T.pct_of_bep,
        name="pct_of_bep",
        units="%",
        precision=0,
        position=15,
        ranges=[
            ui.Range("Low flow", 0, 70, ui.Colour.yellow),
            ui.Range("Efficient", 70, 120, ui.Colour.green),
            ui.Range("High flow", 120, 160, ui.Colour.yellow),
        ],
    )

    # ---- trends
    npsh_plot = ui.Multiplot(
        "Cavitation Margin",
        series=[
            ui.Series(
                "NPSH Available",
                value=T.npsha_m,
                name="npsh_available_m",
                colour="blue",
                units="m",
            ),
            ui.Series(
                "NPSH Required",
                value=T.npshr_m,
                name="npsh_required_m",
                colour="red",
                units="m",
            ),
            # Thresholds get restated from config in `_apply_config`.
            ui.Series(
                "Margin",
                value=T.npsh_margin_m,
                name="margin_m",
                colour="green",
                units="m",
                thresholds=[
                    ui.Threshold("Warning", 1.5, ui.Colour.yellow),
                    ui.Threshold("Danger", 0.5, ui.Colour.red),
                ],
            ),
        ],
        default_range_view=ui.RangeView.line,
        position=20,
    )
    pressure_plot = ui.Multiplot(
        "Pressures & Flow",
        series=[
            ui.Series(
                "Suction",
                value=T.suction_bar,
                name="suction_bar",
                colour="orange",
                units="bar",
            ),
            ui.Series(
                "Discharge",
                value=T.discharge_bar,
                name="discharge_bar",
                colour="purple",
                units="bar",
            ),
            ui.Series(
                "Flow",
                value=T.flow_m3h,
                name="flow_m3h",
                colour="teal",
                shared_axis=False,
                units="m3/h",
            ),
        ],
        position=21,
    )

    # ---- detail / operator
    details = ui.Submodule(
        "Details",
        name="details",
        position=30,
        children=[
            ui.NumericVariable(
                "NPSH Available", value=T.npsha_m, name="npsha", units="m", precision=2
            ),
            ui.NumericVariable(
                "NPSH Required", value=T.npshr_m, name="npshr", units="m", precision=2
            ),
            ui.NumericVariable(
                "Engine Speed",
                value=T.engine_rpm,
                name="engine_rpm",
                units="RPM",
                precision=0,
            ),
            ui.TextVariable("Flow Source", value=T.flow_origin, name="flow_origin"),
            ui.NumericVariable(
                "Flow Confidence", value=T.flow_confidence, name="flow_confidence", precision=2
            ),
            ui.NumericVariable(
                "Curve Deviation",
                value=T.curve_deviation_pct,
                name="curve_deviation",
                units="%",
                precision=1,
            ),
            ui.TextVariable("Faults", value=T.fault_text, name="fault_text"),
            ui.TextVariable("Trip Reason", value=T.trip_reason, name="trip_reason"),
            ui.Button(
                "Reset Trip",
                name="reset_trip",
                colour=ui.Colour.red,
                requires_confirm=ui.ConfirmDialog(
                    title="Reset pump trip?",
                    warning_reason=(
                        "The pump tripped on cavitation margin. Confirm the "
                        "suction condition has been corrected before resetting."
                    ),
                    audit=ui.AuditConfig(required=True),
                ),
                # The site marks the command failed if the app doesn't answer.
                command_timeout=30,
            ),
        ],
    )
