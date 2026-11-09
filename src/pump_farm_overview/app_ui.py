from pathlib import Path

from pydoover import ui


class PumpFarmOverviewUI(ui.UI, default_open=True):
    widget = ui.RemoteComponent(
        name="PumpFarmOverviewWidget",
        display_name="Farm Pumps",
        component_url="$config.app().dv_widget_url",
        scope="PumpFarmOverviewWidget",
        module="./PumpFarmOverviewWidget",
        app_key="$config.app().APP_KEY",
    )


def export():
    PumpFarmOverviewUI(None, None, None).export(
        Path(__file__).parents[2] / "doover_config.json", "pump_farm_overview"
    )
