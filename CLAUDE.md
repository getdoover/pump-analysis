# Pump Analysis — working notes for Claude

Pump operating-point / cavitation-margin analysis on the Doover platform, using pydoover 1.0.
Leachate-telemetry-style layout: a shared workspace package + thin app packages.

## Commands

```bash
uv run pytest tests -v            # run tests (maths golden tests + protection + schema smoke)
uv run export-config              # device app config_schema -> doover_config.json
uv run export-ui                  # device app ui_schema -> doover_config.json
uv run export-config-processor    # processor app variants
uv run export-ui-processor
doover app run                    # app + pump simulator via docker-compose
cd widget && npm run build        # MF remote bundle -> widget/assets/PumpAnalysisWidget.js
```

## Structure

```
packages/pump_analysis_common/src/pump_analysis_common/
  pump_math.py    # PURE hydraulics: vapour pressure, density, TDH, NPSHa, affinity, 4-20mA scaling
  curve.py        # PumpCurve: interpolation, inversion (head->flow) with dH/dQ confidence
  engine.py       # analyse(Readings, curve, SiteParams) -> Results — deployment-agnostic
  protection.py   # ProtectionMonitor: debounce, start inhibit, trip latch (clock-injected)
  sources.py      # gather_readings(config, fetch_ai=?, get_remote=?) — capability-based
  publish.py      # Results -> tags (shared by both apps)
  app_config.py   # shared schema incl. ScaledTagRef sources, CurvePoint array, TripAction
  app_tags.py     # RemoteTags (raw inputs) + computed tags + *_warning_hidden
  app_ui.py       # native UI + ui.RemoteComponent(PumpAnalysisWidget)
src/pump_analysis_device/       # docker app (type DEV) — AI pins + tags, DO trip
src/pump_analysis_processor/    # cloud processor (type PRO) — tags only, SET_TAG trip
widget/                         # React + rsbuild Module Federation + tailwind (shadcn-style)
simulators/pump/                # synthetic pump: normal -> cavitating sweep every 10 min
```

## Invariants — do not break

- **`pump_math.py` / `curve.py` / `engine.py` / `protection.py` import no pydoover.** They are
  golden-tested against hand-worked numbers; keep them pure.
- **Config display names ARE the runtime keys.** `deployment_config` keys derive from
  sanitised display names, not Python attribute names. The widget reads those keys
  (`widget/src/lib/pump.ts`) and `tests/test_imports.py::test_config_schema` pins them.
  Rename display name + widget key + test together, or not at all.
- **TagRef config elements must stay top-level** on the schema — RemoteTag resolution only
  scans top-level TagRefs. Don't nest them in config.Object groups.
- **Trip defaults to `NONE`** (alert-only). The trip latches (`ProtectionMonitor.tripped`)
  until reset from the UI. Never wire `Application.request_shutdown()` for the pump trip —
  that shuts down the *doovit*.
- **Inferred flow always ships with `flow_confidence`**; ambiguous curve inversions are capped
  at 0.5. Don't present inferred flow as a measurement.
- Widget MF contract: rsbuild `name: "PumpAnalysisWidget"`, expose `./PumpAnalysisWidget` —
  must match `scope`/`module` in `app_ui.py`'s RemoteComponent. Build tooling is
  **rsbuild/rspack**, not webpack.

## Local simulation (works on macOS)

```bash
cd simulators && docker compose up -d --build
# watch the analysis flow:
curl -sk https://localhost:49100/ch/v1/agent/1/tag_values/aggregate | python3 -m json.tool
docker compose logs -f pump_analysis
```

- Device agent image is **spaneng/doover-device-agent:main** (hyphenated; the old
  `doover_device_agent:apps` image is a year stale and speaks an older gRPC API).
- The compose file uses **bridge networking + DDA_URI=device_agent:50051**, not
  `network_mode: host` — host mode breaks on macOS Docker Desktop.
- The agent needs **AGENT_ID=1** set — channel events carry agent_id and pydoover's
  models require an int.
- The agent serves a **local HTTPS data API on :49100**: `/ch/v1/agent/{id}`,
  `/ch/v1/agent/{id}/{channel}/aggregate` — this is how you view tags locally
  (the full Doover UI still needs a cloud-connected device).
- The pump simulator sweeps normal → cavitating every 10 min, so state walks
  ok → marginal → danger (and back) without hardware.

## House rules

- **Never run `git commit`/`push` on Tom's behalf** — he commits himself.
- After changing `app_config.py` or `app_ui.py`, re-run the export commands so
  `doover_config.json` stays in sync (CI-published apps render from it).
