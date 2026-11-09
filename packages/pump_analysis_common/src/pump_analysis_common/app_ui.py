from pydoover import ui

from .app_config import FLOW_UNIT_INFO, HeadSource, SourceType, TripAction
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

    def _detail(self, name):
        """A child of the Details submodule.

        Submodule children are not registered in ``self._elements`` (that only
        holds top-level declarations), so they are reached through the
        container's own ``_children`` map.
        """
        return self._elements["details"]._children[name]

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
        self._detail("flow_confidence").hidden = not inferred

        # No trip armed, no latch to clear — the monitor never sets `tripped`
        # for TripAction.NONE, so the reset control would be permanently inert.
        self._detail("reset_trip").hidden = (
            cfg.trip_action.value is TripAction.NONE
        )

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

        # Fixed head: no pressures, so no pressure or NPSH readouts.
        fixed = cfg.head_source.value is HeadSource.FIXED
        if fixed:
            self._elements["tdh"].display_name = "Total Head (assumed)"
        for name in ("npsh_margin", "inlet_pressure", "discharge_pressure"):
            self._detail(name).hidden = fixed

        # Per-ML readouts only for the usage source this pump actually has.
        for name in ("fuel_per_ml", "fuel_per_ml_today"):
            self._elements[name].hidden = not cfg.fuel_rate_tag.configured
        for name in ("energy_per_ml", "energy_per_ml_today"):
            self._elements[name].hidden = not cfg.power_tag.configured

        # Margin ranges follow the configured thresholds.
        warn = cfg.npsh_warning_margin_m.value
        danger = cfg.npsh_danger_margin_m.value
        self._detail("npsh_margin").ranges = [
            ui.Range("Danger", -1, danger, ui.Colour.red),
            ui.Range("Marginal", danger, warn, ui.Colour.yellow),
            ui.Range("Healthy", warn, warn * 2, ui.Colour.green),
        ]

        # Pressure readouts span the transmitter ranges, converted to the
        # configured display units. Inlet severity runs on vacuum depth (the
        # cavitation precursor); discharge low-end means the pump isn't making
        # head. Thresholds are defined in bar and scaled with everything else.
        p_label, pf = cfg.pressure_display()
        inlet = self._detail("inlet_pressure")
        discharge = self._detail("discharge_pressure")
        inlet.units = p_label
        discharge.units = p_label
        # m head reads whole-number-ish; bar needs two decimals.
        precision = 1 if abs(pf) >= 5 else 2
        inlet.precision = precision
        discharge.precision = precision

        s_lo = cfg.suction_range_low_bar.value
        s_hi = cfg.suction_range_high_bar.value
        if s_lo is not None and s_hi is not None and s_hi > s_lo:
            inlet.ranges = [
                ui.Range("Deep vacuum", round(s_lo * pf, 2), round(-0.5 * pf, 2), ui.Colour.red),
                ui.Range("Vacuum", round(-0.5 * pf, 2), round(-0.15 * pf, 2), ui.Colour.yellow),
                ui.Range("Healthy", round(-0.15 * pf, 2), round(s_hi * pf, 2), ui.Colour.green),
            ]
        d_lo = cfg.discharge_range_low_bar.value
        d_hi = cfg.discharge_range_high_bar.value
        if d_lo is not None and d_hi is not None and d_hi > d_lo:
            span = d_hi - d_lo
            discharge.ranges = [
                ui.Range("Low", round(d_lo * pf, 2), round((d_lo + 0.25 * span) * pf, 2), ui.Colour.yellow),
                ui.Range("Normal", round((d_lo + 0.25 * span) * pf, 2), round((d_lo + 0.85 * span) * pf, 2),
                         ui.Colour.green),
                ui.Range("High", round((d_lo + 0.85 * span) * pf, 2), round(d_hi * pf, 2), ui.Colour.yellow),
            ]

    # ---- warnings (visibility driven by *_hidden tags; they render only when
    #      the condition is live, so they cost nothing on a healthy pump)
    tripped_warning = ui.WarningIndicator(
        "Pump TRIPPED — reset required", hidden=T.tripped_warning_hidden
    )
    danger_warning = ui.WarningIndicator(
        "Cavitation risk: NPSH margin critical", hidden=T.danger_warning_hidden
    )
    marginal_warning = ui.WarningIndicator(
        "NPSH margin marginal", hidden=T.marginal_warning_hidden
    )
    fault_warning = ui.WarningIndicator(
        "Sensor / configuration fault", hidden=T.fault_warning_hidden
    )

    # ---- headline values, above the curve widget
    calculated_flow = ui.NumericVariable(
        "Calculated Flow",
        value=T.flow_display,
        name="calculated_flow",
        units="ML/day",
        precision=2,
        position=1,
        form=ui.Widget.radial,
        ranges=[ui.Range("Range", 0, 5, ui.Colour.blue)],
    )
    tdh = ui.NumericVariable(
        "Total Head", value=T.tdh_m, name="tdh", units="m", precision=1, position=2
    )

    pumped_today = ui.NumericVariable(
        "Pumped Today",
        value=T.volume_today_ml,
        name="pumped_today",
        units="ML",
        precision=2,
        position=4,
    )
    fuel_per_ml = ui.NumericVariable(
        "Fuel per ML (now)",
        value=T.fuel_per_ml,
        name="fuel_per_ml",
        units="L/ML",
        precision=1,
        position=5,
    )
    fuel_per_ml_today = ui.NumericVariable(
        "Fuel per ML (today)",
        value=T.fuel_per_ml_today,
        name="fuel_per_ml_today",
        units="L/ML",
        precision=1,
        position=6,
    )
    energy_per_ml = ui.NumericVariable(
        "Energy per ML (now)",
        value=T.energy_per_ml,
        name="energy_per_ml",
        units="kWh/ML",
        precision=1,
        position=7,
    )
    energy_per_ml_today = ui.NumericVariable(
        "Energy per ML (today)",
        value=T.energy_per_ml_today,
        name="energy_per_ml_today",
        units="kWh/ML",
        precision=1,
        position=8,
    )

    # Custom XY pump-curve widget (Module Federation remote; see widget/).
    pump_curve_widget = ui.RemoteComponent(
        name="PumpAnalysisWidget",
        display_name="Pump Curve",
        component_url="$config.app().dv_widget_url",
        scope="PumpAnalysisWidget",
        module="./PumpAnalysisWidget",
        app_key="$config.app().APP_KEY",
        position=3,
    )

    # ---- detail / operator
    details = ui.Submodule(
        "Details",
        name="details",
        position=10,
        children=[
            ui.NumericVariable(
                "Flow Confidence",
                value=T.flow_confidence,
                name="flow_confidence",
                precision=2,
                position=1,
                ranges=[
                    ui.Range("Low", 0, 0.4, ui.Colour.red),
                    ui.Range("Fair", 0.4, 0.7, ui.Colour.yellow),
                    ui.Range("Good", 0.7, 1.0, ui.Colour.green),
                ],
            ),
            ui.NumericVariable(
                "NPSH Margin",
                value=T.npsh_margin_m,
                name="npsh_margin",
                units="m",
                precision=2,
                position=2,
                ranges=[
                    ui.Range("Danger", -1, 0.5, ui.Colour.red),
                    ui.Range("Marginal", 0.5, 1.5, ui.Colour.yellow),
                    ui.Range("Healthy", 1.5, 3, ui.Colour.green),
                ],
            ),
            ui.NumericVariable(
                "Inlet Pressure",
                value=T.suction_display,
                name="inlet_pressure",
                units="m head",
                precision=1,
                position=3,
                ranges=[
                    ui.Range("Deep vacuum", -10.2, -5.1, ui.Colour.red),
                    ui.Range("Vacuum", -5.1, -1.53, ui.Colour.yellow),
                    ui.Range("Healthy", -1.53, 102, ui.Colour.green),
                ],
            ),
            ui.NumericVariable(
                "Discharge Pressure",
                value=T.discharge_display,
                name="discharge_pressure",
                units="m head",
                precision=1,
                position=4,
                ranges=[
                    ui.Range("Low", -10.2, 17.85, ui.Colour.yellow),
                    ui.Range("Normal", 17.85, 85.17, ui.Colour.green),
                    ui.Range("High", 85.17, 102, ui.Colour.yellow),
                ],
            ),
            ui.NumericVariable(
                "Pump Speed",
                value=T.pump_rpm,
                name="pump_rpm",
                units="RPM",
                precision=0,
                position=5,
            ),
            # Kept deliberately: the trip latches until it is reset from here,
            # and both applications bind @ui.handler("reset_trip"). Hidden by
            # _apply_config when trip_action is NONE (nothing can latch).
            ui.Button(
                "Reset Trip",
                name="reset_trip",
                colour=ui.Colour.red,
                position=6,
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
