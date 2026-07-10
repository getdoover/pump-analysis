from pydoover.tags import RemoteTag, Tag, Tags


class PumpAnalysisTags(Tags):
    # ---- raw upstream values (bound to the *_input TagRef config elements)
    raw_suction = RemoteTag(
        "number", reference_name="suction_input", optional=True, republish_locally=False
    )
    raw_discharge = RemoteTag(
        "number", reference_name="discharge_input", optional=True, republish_locally=False
    )
    raw_flow = RemoteTag(
        "number", reference_name="flow_input", optional=True, republish_locally=False
    )
    raw_speed = RemoteTag(
        "number", reference_name="speed_input", optional=True, republish_locally=False
    )
    raw_water_temp = RemoteTag(
        "number", reference_name="water_temp_input", optional=True, republish_locally=False
    )

    # ---- computed results (UI + widget read these)
    suction_bar = Tag("number", default=None)
    discharge_bar = Tag("number", default=None)
    engine_rpm = Tag("number", default=None)
    pump_rpm = Tag("number", default=None)
    tdh_m = Tag("number", default=None)
    flow_m3h = Tag("number", default=None)
    flow_origin = Tag("string", default="none")  # none | measured | inferred
    flow_confidence = Tag("number", default=None)
    #: flow converted to the configured display units (UI binds to this)
    flow_display = Tag("number", default=None)
    npsha_m = Tag("number", default=None)
    npshr_m = Tag("number", default=None)
    npsh_margin_m = Tag("number", default=None)
    curve_deviation_pct = Tag("number", default=None)
    pct_of_bep = Tag("number", default=None)

    # ---- state
    state = Tag("string", default="not_running")
    fault_text = Tag("string", default="")
    tripped = Tag("boolean", default=False)
    trip_reason = Tag("string", default="")

    # ---- warning-indicator visibility (hidden=True means indicator off)
    marginal_warning_hidden = Tag("boolean", default=True)
    danger_warning_hidden = Tag("boolean", default=True)
    tripped_warning_hidden = Tag("boolean", default=True)
    fault_warning_hidden = Tag("boolean", default=True)
