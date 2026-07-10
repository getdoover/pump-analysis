from pathlib import Path

from pump_analysis_common.app_config import PumpAnalysisConfig


class PumpAnalysisDeviceConfig(PumpAnalysisConfig):
    pass


def export():
    PumpAnalysisDeviceConfig.export(
        Path(__file__).parents[2] / "doover_config.json", "pump_analysis"
    )


if __name__ == "__main__":
    export()
