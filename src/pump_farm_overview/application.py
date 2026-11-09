"""Farm-level pump overview.

Hosts the widget and holds the device permissions; all figures are read in
the browser from each pump's pump-analysis tags (flow, volume, fuel/energy per ML).
"""

from datetime import datetime, timezone

from pydoover.models import (
    ConnectionConfig,
    ConnectionDetermination,
    ConnectionStatus,
    ConnectionType,
    DeploymentEvent,
)
from pydoover.models.data.connection import ConnectionDisplay
from pydoover.processor import Application

from .app_config import PumpFarmOverviewConfig
from .app_ui import PumpFarmOverviewUI


class PumpFarmOverviewApp(Application):
    config_cls = PumpFarmOverviewConfig
    ui_cls = PumpFarmOverviewUI

    async def on_deployment(self, event: DeploymentEvent):
        # A dashboard agent has no device behind it; show it as online, never stale.
        await self.api.ping_connection_at(
            datetime.now(timezone.utc),
            ConnectionStatus.continuous_online_no_ping,
            ConnectionDetermination.online,
            user_agent="pump-analysis;pump-farm-overview",
        )
        await self.api.update_connection_config(
            ConnectionConfig(ConnectionType.periodic, display=ConnectionDisplay.never)
        )
