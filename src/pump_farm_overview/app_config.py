from pathlib import Path

from pydoover import config
from pydoover.processor import ExtendedPermissionsConfig


class PumpFarmOverviewConfig(config.Schema):
    # Grant this dashboard the pumps to show (by group, or "apps installed" =
    # Pump Analysis). The widget lists every granted device that runs a
    # pump_analysis(_processor) install, keyed by that install's app key.
    extended_permissions = ExtendedPermissionsConfig(
        extra_fields=["app_installs__name", "app_installs__application_name"]
    )
    title = config.String(
        "Title",
        description="Dashboard heading.",
        default="Farm Pumps",
        name="title",
    )
    position = config.ApplicationPosition()


def export():
    PumpFarmOverviewConfig.export(
        Path(__file__).parents[2] / "doover_config.json", "pump_farm_overview"
    )
