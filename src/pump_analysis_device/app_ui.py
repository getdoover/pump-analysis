from pathlib import Path

from pump_analysis_common.app_ui import PumpAnalysisUI


def export():
    PumpAnalysisUI(None, None, None).export(
        Path(__file__).parents[2] / "doover_config.json", "pump_analysis"
    )


if __name__ == "__main__":
    export()
