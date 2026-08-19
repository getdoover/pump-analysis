from pathlib import Path

from pydoover.processor import ManySubscriptionConfig, ProcessorConfig

from pump_analysis_common.app_config import PumpAnalysisConfig


class PumpAnalysisProcessorConfig(PumpAnalysisConfig):
    # Re-run the analysis whenever the agent's tag aggregate changes — i.e.
    # whenever a source app (telemetry bridge, engine controller) publishes.
    subscriptions = ManySubscriptionConfig(
        default=["tag_values"],
        hidden=True,
    )
    # Framework-level processor runtime config (log level/overrides, invocation
    # summary targets, live logs). Embedding it surfaces those knobs per
    # install instead of leaving them to the platform default.
    processor = ProcessorConfig()


def export():
    PumpAnalysisProcessorConfig.export(
        Path(__file__).parents[2] / "doover_config.json", "pump_analysis_processor"
    )


if __name__ == "__main__":
    export()
