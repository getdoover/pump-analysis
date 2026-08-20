# Pump Analysis — working notes for Claude

Pump operating-point / cavitation-margin analysis on the Doover platform, using pydoover 1.12+.
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
- **Every config element carries an explicit `name=`** (kensho-controller convention).
  That name is the `deployment_config` key — display names are free to be reworded.
  The widget reads those keys (`widget/src/lib/pump.ts`) and
  `tests/test_imports.py::test_config_schema` pins them, so changing a `name=` means
  changing the widget key and the test with it. Without `name=`, pydoover falls back to
  the sanitised display name, which is what made this fragile in the first place.
- **TagRef config elements must stay top-level** on the schema — RemoteTag resolution only
  scans top-level TagRefs. Don't nest them in config.Object groups.
- **Trip defaults to `NONE`** (alert-only). The trip latches (`ProtectionMonitor.tripped`)
  until reset from the UI. Never wire `Application.request_shutdown()` for the pump trip —
  that shuts down the *doovit*.
- **`widget/src/lib/` is un-ignored explicitly** in `.gitignore` — the Python `lib/`
  rule otherwise swallows it, and widget sources silently never get committed.
- **Inferred flow always ships with `flow_confidence`**; ambiguous curve inversions are capped
  at 0.5. Don't present inferred flow as a measurement.
- **Widget Tailwind must stay on the same version as `../customer-site`** (v4.1.x today,
  CSS-first config in `widget/src/styles.css`, no `tailwind.config.js`). The bundle's CSS is
  injected into the *host* document, so a version skew breaks the host's own render — under
  v3 the unlayered `--tw-*` defaults outranked the host's `@layer` utilities and collapsed
  every transform on the page.
- **Widget utilities go in `layer(utilities)`, never `layer(app)`** — copy
  `../analog-rain-gauge/widget/src/styles.css`. The host declares
  `properties, theme, base, doover-admin, components, utilities, app` and keeps its *own*
  utilities in `app`, the last layer, precisely so an injected widget can never outrank
  them. Put ours in `app` and our later-injected `.p-2` beats the host's `md:p-6` — the
  host page's layout breaks, not just the widget's.
- **The widget defines no colours of its own.** `@theme inline` maps `--color-card` ->
  `var(--card)` etc., so utilities resolve against customer-site's shadcn tokens on
  `:root`/`.dark` and the widget follows the host theme (dark mode included) for free.
  `inline` substitutes the value into the utility, so nothing of ours reaches `:root`.
  `--success` has no host token — it falls back to `--doover-connection-online`.
  `widget/dev/dev-theme.css` mirrors customer-site's light values for the standalone
  `npm run dev` harness; keep it in sync.
- Widget MF contract: rsbuild `name: "PumpAnalysisWidget"`, expose `./PumpAnalysisWidget` —
  must match `scope`/`module` in `app_ui.py`'s RemoteComponent. Build tooling is
  **rsbuild/rspack**, not webpack.

## pydoover conventions used here

- **Typed tag declarations** — `tags.Number/Boolean/String(default=..., live=..., log_on=...)`
  (keyword-only), not the generic `Tag("number", ...)` form.
- **`live=True`** on the values an operator watches in real time. Live tags are only
  republished while somebody has them open in live mode, so they cost nothing otherwise.
- **`log_on=`** auto-log triggers for the events worth pinning in history:
  `tags.AnyChange()` on `state` / `tripped` / `flow_origin`, `tags.Cross(0.0, deadband=0.2)`
  on `npsh_margin_m`.
- **`show_if=config.equal(<sibling>, <value>)`** gates source-specific config: AI pin/range
  fields show for `ANALOGUE_IN`, the TagRef for `TAG`, trip fields per `TripAction`. Gated
  fields move out of `properties` into `allOf` branches in the exported schema, but still
  load their defaults at runtime — `.value` reads stay safe.
- **App placement elements** (`config.ApplicationPosition/DefaultOpen/InterpreterHidden/
  FullWidth`) back the `$config.app()....` lookups `ui.UI` emits by default.
- **Notifications carry `title=` and `topic=NOTIFY_TOPIC`** so subscriptions can filter.
- **The processor's lambda `handler` lives in `src/pump_analysis_processor/__init__.py`**
  and calls `clear_elements()` / `_load_elements()` first — config elements are class-level
  state and a warm lambda container would otherwise reuse the last invocation's schema.
- **`doover_config.json` carries the publish wiring**: `export_config_command`,
  `export_ui_command`, `widget` + `build_widget_command`, and `lambda_config`
  (`Handler: pump_analysis_processor.handler`) for the processor.

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
