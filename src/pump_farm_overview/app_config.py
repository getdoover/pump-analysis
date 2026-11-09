from pathlib import Path

from pydoover import config
from pydoover.processor import ExtendedPermissionsConfig


class PumpFarmOverviewConfig(config.Schema):
    # Grant this dashboard the pumps to show (by group, or "apps installed" =
    # Pump Analysis). The widget lists every granted device that runs a
    # pump_analysis(_processor) install, keyed by that install's app key.
    extended_permissions = ExtendedPermissionsConfig(
        extra_fields=[
            "name",
            "display_name",
            "app_installs__name",
            "app_installs__display_name",
            "app_installs__application_name",
        ]
    )
    title = config.String(
        "Title",
        description="Dashboard heading.",
        default="Farm Pumps",
        name="title",
    )
    multi_pump_apps = config.String(
        "Multi-Pump Station Apps",
        description=(
            "Comma-separated application names of station apps that publish one "
            "set of <slug>_name / _running / _flow (ML/h) / _power_kw / "
            "_volume_today / _volume_total tags per pump. Each pump becomes a row."
        ),
        default="",
        name="multi_pump_apps",
    )
    position = config.ApplicationPosition()


def export():
    PumpFarmOverviewConfig.export(
        Path(__file__).parents[2] / "doover_config.json", "pump_farm_overview"
    )
