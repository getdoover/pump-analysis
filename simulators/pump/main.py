"""Synthetic pump for local dev: publishes the tags a real telemetry source would.

Two behaviours on a cycle so every UI state can be exercised without hardware:
- NORMAL: healthy operating point wandering around the curve.
- CAVITATING: suction pressure sags toward deep vacuum until the NPSH margin
  collapses, then recovers.
"""

import math
import random
import time

from pydoover.docker import Application, run_app
from pydoover.tags import Tag, Tags

CYCLE_S = 600.0  # full normal->cavitating->normal sweep
REFERENCE_RPM = 1800.0


class PumpSimulatorTags(Tags):
    suction_bar = Tag("number", default=0.0)
    discharge_bar = Tag("number", default=0.0)
    engine_rpm = Tag("number", default=0.0)
    flow_m3h = Tag("number", default=0.0)
    water_temp_c = Tag("number", default=20.0)


class PumpSimulator(Application):
    tags_cls = PumpSimulatorTags

    async def setup(self):
        self.t0 = time.monotonic()

    async def main_loop(self):
        t = time.monotonic() - self.t0
        phase = (t % CYCLE_S) / CYCLE_S  # 0..1

        rpm = REFERENCE_RPM * (0.92 + 0.06 * math.sin(t / 47.0))

        # Cavitation sweep: suction sags from -0.25 to -0.85 bar mid-cycle.
        sag = math.sin(phase * math.pi)  # 0 -> 1 -> 0 across the cycle
        suction = -0.25 - 0.60 * sag + random.gauss(0, 0.01)

        # Discharge follows the curve-ish head at ~95 m3/h, dropping as
        # cavitation develops (head collapse is the classic signature).
        healthy_head_bar = 4.5 * (rpm / REFERENCE_RPM) ** 2
        collapse = 0.35 * max(0.0, sag - 0.7) / 0.3  # only near full sag
        discharge = suction + healthy_head_bar * (1.0 - collapse) + random.gauss(0, 0.02)

        flow = 95.0 * (rpm / REFERENCE_RPM) * (1.0 - 0.3 * collapse)

        await self.tags.suction_bar.set(round(suction, 4))
        await self.tags.discharge_bar.set(round(discharge, 4))
        await self.tags.engine_rpm.set(round(rpm, 1))
        await self.tags.flow_m3h.set(round(flow, 2))
        await self.tags.water_temp_c.set(round(20.0 + 8.0 * sag, 2))


def main():
    """Run the pump simulator application."""
    run_app(PumpSimulator())


if __name__ == "__main__":
    main()
