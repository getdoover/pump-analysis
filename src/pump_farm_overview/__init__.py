from typing import Any

from pydoover.processor import run_app

from .app_config import PumpFarmOverviewConfig
from .application import PumpFarmOverviewApp

__all__ = ["PumpFarmOverviewApp", "handler"]


def handler(event: dict[str, Any], context):
    """Lambda entrypoint — rebuild the class-level config elements each run."""
    PumpFarmOverviewConfig.clear_elements()
    PumpFarmOverviewConfig._load_elements()
    return run_app(PumpFarmOverviewApp(), event, context)
