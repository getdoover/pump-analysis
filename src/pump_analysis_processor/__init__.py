from typing import Any

from pydoover.processor import run_app

from .application import PumpAnalysisProcessorApp
from .app_config import PumpAnalysisProcessorConfig

__all__ = ["PumpAnalysisProcessorApp", "handler"]


def handler(event: dict[str, Any], context):
    """AWS-Lambda-style entrypoint.

    Config elements are class-level state, so a warm lambda container would
    otherwise carry the previous invocation's schema across into the next
    agent's run — rebuild the element map each time.
    """
    PumpAnalysisProcessorConfig.clear_elements()
    PumpAnalysisProcessorConfig._load_elements()
    return run_app(PumpAnalysisProcessorApp(), event, context)
