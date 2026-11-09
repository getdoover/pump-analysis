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
    diesel_price_per_litre = config.Number(
        "Diesel Price ($/L)",
        description="Estimate used to turn each diesel pump's litres per ML into $ per ML.",
        default=1.8,
        minimum=0.0,
        maximum=100.0,
        name="diesel_price_per_litre",
    )
    electricity_price_per_kwh = config.Number(
        "Electricity Price ($/kWh)",
        description="Estimate used to turn each electric pump's kWh per ML into $ per ML.",
        default=0.3,
        minimum=0.0,
        maximum=100.0,
        name="electricity_price_per_kwh",
    )
    position = config.ApplicationPosition()


def export():
    PumpFarmOverviewConfig.export(
        Path(__file__).parents[2] / "doover_config.json", "pump_farm_overview"
    )
