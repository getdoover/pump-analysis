"""Smoke tests: modules import, schemas are well-formed, exports run end-to-end."""

import json

from pydoover.config import Schema
from pydoover.tags import Tags
from pydoover.ui import UI


def test_import_device_app():
    from pump_analysis_device.application import PumpAnalysisDeviceApplication

    assert PumpAnalysisDeviceApplication.config_cls is not None
    assert PumpAnalysisDeviceApplication.tags_cls is not None
    assert PumpAnalysisDeviceApplication.ui_cls is not None


def test_import_processor_app():
    from pump_analysis_processor.application import PumpAnalysisProcessorApp

    assert PumpAnalysisProcessorApp.config_cls is not None
    assert PumpAnalysisProcessorApp.tags_cls is not None


def test_config_schema():
    from pump_analysis_common.app_config import PumpAnalysisConfig

    assert issubclass(PumpAnalysisConfig, Schema)
    schema = PumpAnalysisConfig.to_schema()
    assert schema["type"] == "object"

    # Conditional fields (show_if) live in `allOf` branches rather than at the
    # top level, but their runtime deployment_config keys are the same.
    declared = set(schema["properties"])
    for branch in schema.get("allOf", []):
        declared.update(branch["then"]["properties"])

    # The widget reads deployment_config by sanitised-display-name keys —
    # these must never drift from the Python attribute names.
    for key in (
        "suction_source_type",
        "suction_tag",
        "discharge_tag",
        "speed_tag",
        "pump_curve",
        "curve_reference_speed_rpm",
        "npsh_warning_margin_m",
        "npsh_danger_margin_m",
        "trip_action",
    ):
        assert key in declared, f"missing config key {key}"


def test_source_fields_are_conditional():
    """Source-specific fields only show for the source type that uses them."""
    from pump_analysis_common.app_config import PumpAnalysisConfig, SourceType

    schema = PumpAnalysisConfig.to_schema()
    branches = {
        (
            branch["if"]["properties"]["suction_source_type"]["const"]
            if "suction_source_type" in branch["if"]["properties"]
            else None
        ): branch
        for branch in schema["allOf"]
    }
    assert (
        "suction_ai_pin" in branches[SourceType.ANALOGUE_IN.value]["then"]["properties"]
    )
    assert "suction_tag" in branches[SourceType.TAG.value]["then"]["properties"]


def test_gated_fields_still_load_defaults():
    """A field hidden by show_if must still read its default at runtime."""
    from pump_analysis_common.app_config import PumpAnalysisConfig

    cfg = PumpAnalysisConfig()
    cfg._inject_deployment_config(
        {"suction_source_type": "analogue_in", "pump_curve": []}
    )
    assert cfg.suction_ai_pin.value == 2  # shown
    assert cfg.suction_tag.configured is False  # hidden, unset
    assert cfg.trip_do_pin.value is None  # hidden, default


def test_tags():
    from pump_analysis_common.app_tags import PumpAnalysisTags

    assert issubclass(PumpAnalysisTags, Tags)


def test_ui():
    from pump_analysis_common.app_ui import PumpAnalysisUI

    assert issubclass(PumpAnalysisUI, UI)


def test_device_config_export(tmp_path):
    from pump_analysis_common.app_config import PumpAnalysisConfig

    fp = tmp_path / "doover_config.json"
    PumpAnalysisConfig.export(fp, "pump_analysis")
    data = json.loads(fp.read_text())
    assert "config_schema" in data["pump_analysis"]


def test_ui_export(tmp_path):
    from pump_analysis_common.app_ui import PumpAnalysisUI

    fp = tmp_path / "doover_config.json"
    PumpAnalysisUI(None, None, None).export(fp, "pump_analysis")
    data = json.loads(fp.read_text())
    schema = data["pump_analysis"]["ui_schema"]
    assert schema["type"] == "uiApplication"
    assert "PumpAnalysisWidget" in schema["children"]
    assert schema["children"]["PumpAnalysisWidget"]["type"] == "uiRemoteComponent"


def test_build_curve_from_loaded_config():
    """Array-of-Object config points must round-trip into a PumpCurve."""
    from pump_analysis_common.app_config import PumpAnalysisConfig

    cfg = PumpAnalysisConfig()
    cfg._inject_deployment_config(
        {
            "curve_reference_speed_rpm": 1800,
            "pump_curve": [
                {"flow_m3h": 0, "head_m": 60, "npshr_m": 2.0},
                {"flow_m3h": 100, "head_m": 45},
                {"flow_m3h": 200, "head_m": 10, "npshr_m": 9.0},
            ],
        }
    )
    curve = cfg.build_curve()
    assert curve is not None
    assert curve.reference_rpm == 1800
    assert len(curve.points) == 3
    assert curve.points[1].npshr_m is None
