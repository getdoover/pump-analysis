# Pump Analysis

**Pump operating point, cavitation (NPSH) margin, alerts and protective trip** — from inlet
and discharge pressure, engine speed, and the manufacturer's pump curve.

Built for diesel pump stations (Kensho-controlled engines reporting RPM over Modbus), but
source-agnostic: every signal can come from a native 4–20 mA input on a doovit or from a tag
published by any other app.

## What it computes

| Output | How |
|--------|-----|
| **Total differential head** | (discharge − suction)/ρg + gauge separation + velocity heads |
| **Flow** | Measured (flow meter) or **inferred** by inverting the affinity-scaled manufacturer curve — always published with a slope-derived confidence, capped when the inversion is ambiguous |
| **NPSH available** | Absolute suction pressure − vapour pressure (temperature-aware), referenced to the impeller eye |
| **NPSH margin** | NPSHa − NPSHr (curve lookup at the live operating point, affinity-scaled) |
| **Curve deviation** | Measured vs predicted head (%) when a flow meter is fitted — a pump-degradation indicator |

Alerts fire when the margin goes **marginal**; a debounced, latched **trip** (opt-in, default
`NONE`) can stop the pump when it goes **danger** — via a digital output into the panel stop
input, or by setting a tag on an engine-controller app.

## Two deployments, one analysis

- **`pump_analysis`** (device app, docker) — runs on the doovit; native AI pins and/or tags.
- **`pump_analysis_processor`** (cloud processor) — runs in the Doover cloud on tag updates;
  tag sources only, trip via `SET_TAG` only. No doovit required.

Both share `packages/pump_analysis_common`: the pure maths (`pump_math.py`, `curve.py`,
`engine.py`, `protection.py` — fully unit-tested, no pydoover imports), the config schema,
tags and UI. One app install per pump.

## Structure

```
packages/pump_analysis_common/   # maths core + shared config/tags/ui
src/pump_analysis_device/        # docker device app
src/pump_analysis_processor/     # cloud processor app
widget/                          # pump-curve RemoteComponent (React + rsbuild MF + shadcn-style)
simulators/pump/                 # synthetic pump (normal -> cavitating sweep)
tests/                           # golden maths tests, protection tests, schema smoke tests
```

## Commands

```bash
uv run pytest tests -v            # run tests
uv run export-config              # device app config_schema -> doover_config.json
uv run export-ui                  # device app ui_schema -> doover_config.json
uv run export-config-processor    # processor variants
uv run export-ui-processor
doover app run                    # run app + pump simulator via docker-compose

cd widget && npm run build        # build assets/PumpAnalysisWidget.js (MF remote)
cd widget && npm run serve        # serve the bundle locally (port 8006)
```

Set the app's **DV Widget URL** config to the served/hosted bundle URL to enable the
pump-curve widget.

### Local simulation

`docker compose up -d --build` in `simulators/` runs the device agent
(`spaneng/doover-device-agent:main`), the synthetic pump, and the app — bridge-networked,
so it works on macOS too. Watch the analysis live via the agent's local data API:

```bash
curl -sk https://localhost:49100/ch/v1/agent/1/tag_values/aggregate | python3 -m json.tool
```

The simulated pump sweeps into cavitation and back every 10 minutes, walking the app
through ok → marginal → danger without hardware.

## Configuration notes

- **Sources**: each of suction / discharge / flow / speed picks `analogue_in` or `tag`
  (`flow` may be `none` → inferred). Tag sources carry scale + offset.
- **Pump speed** = engine RPM × ratio + offset (gearbox/pulley transform; offset should be 0
  for any rigid drive).
- **Pump curve**: digitised head-flow(-NPSHr) points at a stated reference RPM. Without a
  valid curve the app still publishes heads and NPSHa, but no inferred flow or margin.
- **Trip**: `trip_action` defaults to `NONE` (alert-only). Arm `DIGITAL_OUTPUT` or `SET_TAG`
  per pump only after thresholds are proven on site. Trips latch until reset from the UI.
- Inferred flow is a **trend indicator, not a measurement** — it assumes the pump still
  follows its published curve, which is exactly what cavitation damage erodes. Fit a flow
  meter where the analysis must be defensible.

## Need Help?

- 📧 Email: support@doover.com
- 📖 [Doover Documentation](https://docs.doover.com)

## License

Licensed under the [Apache License 2.0](LICENSE).
