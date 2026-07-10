from pydoover.docker import run_app

from .application import PumpAnalysisDeviceApplication


def main():
    """Run the pump-analysis device application."""
    run_app(PumpAnalysisDeviceApplication())
