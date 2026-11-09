"""Tag declarations shared by both deployments.

House style (pydoover 1.5+): typed declarations — ``tags.Number`` /
``tags.Boolean`` / ``tags.String`` — with keyword-only arguments, rather than
the generic ``Tag("number", ...)`` form. The typed classes validate their
``log_on`` auto-log descriptors against the tag type at declaration time.

``live=True`` marks the values an operator watches in real time. Live tags are
republished as a one-shot snapshot each main loop *only while somebody has that
tag open in live mode*, so a watching UI sees fresh values without every
sample being persisted.
"""

from pydoover import tags


class PumpAnalysisTags(tags.Tags):
    # ---- raw upstream values (bound to the *_input TagRef config elements)
    raw_suction = tags.RemoteTag(
        "number", reference_name="suction_input", optional=True, republish_locally=False
    )
    raw_discharge = tags.RemoteTag(
        "number",
        reference_name="discharge_input",
        optional=True,
        republish_locally=False,
    )
    raw_flow = tags.RemoteTag(
        "number", reference_name="flow_input", optional=True, republish_locally=False
    )
    raw_speed = tags.RemoteTag(
        "number", reference_name="speed_input", optional=True, republish_locally=False
    )
    raw_water_temp = tags.RemoteTag(
        "number",
        reference_name="water_temp_input",
        optional=True,
        republish_locally=False,
    )

    raw_engaged = tags.RemoteTag(
        "boolean", reference_name="engaged_input", optional=True, republish_locally=False
    )
    raw_engine_hours = tags.RemoteTag(
        "number",
        reference_name="engine_hours_input",
        optional=True,
        republish_locally=False,
    )
    raw_fuel_rate = tags.RemoteTag(
        "number", reference_name="fuel_rate_input", optional=True, republish_locally=False
    )
    raw_power = tags.RemoteTag(
        "number", reference_name="power_input", optional=True, republish_locally=False
    )

    # ---- computed results (UI + widget read these)
    suction_bar = tags.Number(default=None)
    discharge_bar = tags.Number(default=None)
    #: pressures converted to the configured display units (UI binds to these)
    suction_display = tags.Number(default=None, live=True)
    discharge_display = tags.Number(default=None, live=True)
    engine_rpm = tags.Number(default=None, live=True)
    pump_rpm = tags.Number(default=None, live=True)
    tdh_m = tags.Number(default=None, live=True)
    flow_m3h = tags.Number(default=None)
    #: none | measured | inferred — a change means the operating picture changed
    flow_origin = tags.String(default="none", log_on=tags.AnyChange())
    flow_confidence = tags.Number(default=None)
    #: flow converted to the configured display units (UI binds to this)
    flow_display = tags.Number(default=None, live=True)
    npsha_m = tags.Number(default=None, live=True)
    npshr_m = tags.Number(default=None, live=True)
    #: the headline safety number — log immediately when it crosses either
    #: side of zero margin, whatever the periodic log interval is doing.
    npsh_margin_m = tags.Number(
        default=None, live=True, log_on=tags.Cross(0.0, deadband=0.2)
    )
    curve_deviation_pct = tags.Number(default=None)
    pct_of_bep = tags.Number(default=None)

    # ---- usage (farm overview reads these). Volumes in ML. "today" rolls over
    #      at local midnight. *_per_ml = what it takes to pump one ML: "now" at
    #      the current operating point, "today" averaged over today's pumping.
    fuel_rate_lph = tags.Number(default=None)
    power_kw = tags.Number(default=None)
    fuel_per_ml = tags.Number(default=None, live=True)
    energy_per_ml = tags.Number(default=None, live=True)
    volume_today_ml = tags.Number(default=0.0)
    run_hours_today = tags.Number(default=0.0)
    fuel_today_l = tags.Number(default=0.0)
    energy_today_kwh = tags.Number(default=0.0)
    fuel_per_ml_today = tags.Number(default=None)
    energy_per_ml_today = tags.Number(default=None)
    today_date = tags.String(default="")
    volume_total_ml = tags.Number(default=0.0)
    run_hours_total = tags.Number(default=0.0)
    fuel_total_l = tags.Number(default=0.0)
    energy_total_kwh = tags.Number(default=0.0)

    # ---- state
    state = tags.String(default="not_running", log_on=tags.AnyChange())
    fault_text = tags.String(default="")
    tripped = tags.Boolean(default=False, log_on=tags.AnyChange())
    trip_reason = tags.String(default="")

    # ---- warning-indicator visibility (hidden=True means indicator off)
    marginal_warning_hidden = tags.Boolean(default=True)
    danger_warning_hidden = tags.Boolean(default=True)
    tripped_warning_hidden = tags.Boolean(default=True)
    fault_warning_hidden = tags.Boolean(default=True)
