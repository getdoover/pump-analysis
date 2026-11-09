import { useMemo, useState } from "react";
import { Link } from "react-router";
import {
  useAgentChannel,
  useDeviceMap,
  useMultiAgentAggregates,
  useMultiAgentChannelMessages,
  type DeviceMapEntry,
} from "doover-js/react";
import { extractSnowflakeId, generateSnowflakeIdAtTime } from "doover-js";
import RemoteComponentWrapper from "customer_site/RemoteComponentWrapper";
import { useRemoteParams } from "customer_site/useRemoteParams";

import "./styles.css";

// Apps whose tags this dashboard reads (both publish the same tag set).
const PUMP_APPS = ["pump_analysis", "pump_analysis_processor"];
// Multi-motor station apps (configured per install) publish one set of
// `<slug>_name/_running/_flow/_power_kw/_volume_*` tags per motor; each
// motor becomes a row, read straight from the station app's own tags.
// No update for this long and the last state can't be trusted: remote pumps
// sleep without ever publishing a stop, so their last speed sticks.
const STALE_MS = 30 * 60_000;
const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;
const WEEK_MS = 7 * DAY_MS;
const RANGES = [
  { label: "24h", days: 1 },
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
];
// Categorical slots in fixed order (dataviz reference palette), light / dark.
const SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
const SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];

interface DashConfig {
  applications?: Record<string, { title?: string | null; multi_pump_apps?: string | null }>;
}

type PumpTags = Partial<{
  state: string;
  fault_text: string;
  pump_rpm: number | null;
  flow_m3h: number | null;
  fuel_per_ml: number | null;
  energy_per_ml: number | null;
  volume_today_ml: number;
  fuel_today_l: number;
  energy_today_kwh: number;
  fuel_per_ml_today: number | null;
  energy_per_ml_today: number | null;
  today_date: string;
  volume_total_ml: number;
}>;

interface Row {
  key: string;
  deviceId: string;
  appKey: string;
  /** cumulative-ML tag (under appKey) the history chart diffs */
  totalTag: string;
  name: string;
  colour: string;
  tags: PumpTags;
  lastUpdated: number | null;
  status: "running" | "stopped" | "fault" | "stale" | "unknown";
}

interface HistoryMessage {
  id?: string | number;
  timestamp?: number | string;
  data?: Record<string, Record<string, unknown> | undefined>;
  channel?: { agent_id?: string | number };
  agent_id?: string | number;
}

function installsOf(d: DeviceMapEntry, apps: string[]): { appKey: string; label: string }[] {
  return (d.app_installs ?? [])
    .filter((i) => apps.includes(i.application_name ?? "") && i.name)
    .map((i) => ({ appKey: i.name as string, label: i.display_name || (i.name as string) }));
}

/** One lift-station motor's tags, mapped onto the pump-analysis tag shape. */
function liftMotorTags(data: Record<string, unknown>, slug: string, now: number): PumpTags {
  const g = (k: string) => data[`${slug}_${k}`];
  const running = g("running") === true;
  const flowMlh = num(g("flow")) ?? 0;
  const power = num(g("power_kw"));
  // volume_today counts until the app's next local-midnight rollover.
  const reset = num(data.daily_reset_time);
  const todayValid = reset != null && now < reset;
  return {
    state: running ? "ok" : "not_running",
    flow_m3h: running ? flowMlh * 1000 : null,
    energy_per_ml: running && power != null && flowMlh > 0 ? power / flowMlh : null,
    volume_today_ml: todayValid ? num(g("volume_today")) ?? 0 : 0,
    today_date: todayValid ? localToday() : "",
    volume_total_ml: num(g("volume_total")) ?? undefined,
  };
}

function localToday(): string {
  // en-CA formats as YYYY-MM-DD, matching the apps' today_date tag.
  return new Date().toLocaleDateString("en-CA");
}

function statusOf(t: PumpTags, lastUpdated: number | null): Row["status"] {
  if (!t.state) return "unknown";
  const running = !["not_running", "sensor_fault", "config_fault"].includes(t.state);
  if (running && (lastUpdated == null || Date.now() - lastUpdated > STALE_MS)) return "stale";
  if (running) return "running";
  if (t.state === "not_running") return "stopped";
  return "fault";
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

function fmt(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  return v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** What one ML took: diesel litres, else electrical kWh. */
function perMl(fuel: number | null, energy: number | null): string {
  if (fuel != null) return `${fmt(fuel, 0)} L`;
  if (energy != null) return `${fmt(energy, 0)} kWh`;
  return "—";
}

function ago(ts: number | null): string {
  if (ts == null) return "never";
  const m = Math.round((Date.now() - ts) / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
}

function msgTime(m: HistoryMessage): number | null {
  const t = m.timestamp != null ? Number(m.timestamp) : null;
  if (t != null && Number.isFinite(t)) return t < 1e12 ? t * 1000 : t;
  if (m.id != null) return extractSnowflakeId(String(m.id)).timestamp;
  return null;
}

const STATUS: Record<Row["status"], { label: string; cls: string }> = {
  running: { label: "Running", cls: "bg-success/15 text-success" },
  stopped: { label: "Stopped", cls: "bg-muted text-muted-foreground" },
  fault: { label: "Fault", cls: "bg-warning/15 text-warning" },
  stale: { label: "No recent data", cls: "bg-muted text-muted-foreground" },
  unknown: { label: "No data", cls: "bg-muted text-muted-foreground" },
};

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}

interface Bucket {
  start: number;
  values: Record<string, number>; // row key -> ML
  total: number;
}

/** Stacked bars of ML pumped per bucket, one colour per pump. */
function PumpedChart({ rows, buckets, hourly, loading }: { rows: Row[]; buckets: Bucket[]; hourly: boolean; loading: boolean }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 720, H = 220, L = 44, R = 8, T = 8, B = 24;
  const max = Math.max(0.001, ...buckets.map((b) => b.total));
  const nice = (() => {
    const p = Math.pow(10, Math.floor(Math.log10(max)));
    return [1, 2, 2.5, 5, 10].map((m) => m * p).find((v) => v >= max) ?? max;
  })();
  const plotW = W - L - R, plotH = H - T - B;
  const slot = plotW / Math.max(1, buckets.length);
  const barW = Math.max(2, Math.min(28, slot * 0.7));
  const y = (v: number) => T + plotH - (v / nice) * plotH;
  const label = (t: number) =>
    hourly
      ? new Date(t).toLocaleTimeString(undefined, { hour: "numeric" })
      : new Date(t).toLocaleDateString(undefined, { day: "numeric", month: "short" });
  const every = Math.ceil(buckets.length / 8);
  const hb = hover != null ? buckets[hover] : null;

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" style={{ height: "auto" }} role="img" aria-label="ML pumped per pump over time">
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={L} x2={W - R} y1={y(nice * f)} y2={y(nice * f)} stroke="var(--border)" strokeWidth={1} />
            <text x={L - 6} y={y(nice * f) + 4} textAnchor="end" fontSize={11} fill="var(--muted-foreground)">
              {fmt(nice * f, nice * f >= 10 || f === 0 ? 0 : 1)}
            </text>
          </g>
        ))}
        {buckets.map((b, i) => {
          const x = L + i * slot + (slot - barW) / 2;
          let acc = 0;
          return (
            <g key={b.start} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={L + i * slot} y={T} width={slot} height={plotH} fill="transparent" />
              {rows.map((r) => {
                const v = b.values[r.key] ?? 0;
                if (v <= 0) return null;
                const y0 = y(acc), y1 = y(acc + v);
                acc += v;
                // 2px surface gap between stacked segments
                const h = Math.max(1, y0 - y1 - 2);
                return <rect key={r.key} x={x} y={y1} width={barW} height={h} rx={2} fill={r.colour} opacity={hover == null || hover === i ? 1 : 0.55} />;
              })}
              {i % every === 0 && (
                <text x={L + i * slot + slot / 2} y={H - 6} textAnchor="middle" fontSize={11} fill="var(--muted-foreground)">
                  {label(b.start)}
                </text>
              )}
            </g>
          );
        })}
        <text x={4} y={T + 10} fontSize={11} fill="var(--muted-foreground)">ML</text>
      </svg>
      {hb && hb.total > 0 && (
        <div
          className="pointer-events-none absolute rounded-md border border-border bg-card p-2 text-xs shadow"
          style={{ left: `${Math.min(70, ((hover ?? 0) / buckets.length) * 100)}%`, top: 4, minWidth: 160 }}
        >
          <div className="mb-1 font-medium">{hourly ? new Date(hb.start).toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric" }) : label(hb.start)}</div>
          {rows.filter((r) => (hb.values[r.key] ?? 0) > 0).map((r) => (
            <div key={r.key} className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-1.5"><span className="inline-block h-2 w-2 rounded-sm" style={{ background: r.colour }} />{r.name}</span>
              <span className="tabular-nums">{fmt(hb.values[r.key], 2)} ML</span>
            </div>
          ))}
          <div className="mt-1 flex justify-between border-t border-border pt-1 font-medium"><span>Total</span><span className="tabular-nums">{fmt(hb.total, 2)} ML</span></div>
        </div>
      )}
      {loading && <div className="absolute right-2 top-1 text-xs text-muted-foreground">Loading…</div>}
    </div>
  );
}

function Inner({ uiElement, ui_element_props }: { uiElement: { app_key?: string }; ui_element_props?: { ui?: { id?: string | number } } }) {
  const params = useRemoteParams();
  // Group pages don't put the agent in the URL; the host passes the rendered
  // agent in ui_element_props.ui, which works on both page types.
  const rawAgent = params?.agentId ?? ui_element_props?.ui?.id;
  const agentId = rawAgent == null ? undefined : String(rawAgent);
  const appKey = uiElement?.app_key ?? "";

  const { data: deployment } = useAgentChannel<DashConfig>(agentId, "deployment_config");
  const title = deployment?.applications?.[appKey]?.title?.trim() || "Farm Pumps";
  const multiPumpApps = useMemo(
    () => (deployment?.applications?.[appKey]?.multi_pump_apps ?? "").split(",").map((a) => a.trim()).filter(Boolean),
    [deployment, appKey],
  );

  const { devices, isLoading, hasDeviceMap } = useDeviceMap(agentId, appKey);
  const installs = useMemo(
    () => devices.flatMap((d) => installsOf(d, PUMP_APPS).map((i) => ({ device: d, ...i }))),
    [devices],
  );
  const lifts = useMemo(
    () => devices.flatMap((d) => installsOf(d, multiPumpApps).map((i) => ({ device: d, ...i }))),
    [devices, multiPumpApps],
  );
  const deviceIds = useMemo(
    () => [...new Set([...installs, ...lifts].map((i) => i.device.id))],
    [installs, lifts],
  );
  const fields = useMemo(() => [...new Set([...installs, ...lifts].map((i) => i.appKey))], [installs, lifts]);
  const { aggregatesByAgent } = useMultiAgentAggregates<Record<string, PumpTags>>("tag_values", deviceIds, { fields });

  const dark = typeof document !== "undefined" && document.documentElement.classList.contains("dark");
  const rows = useMemo<Row[]>(() => {
    const perDevice = new Map<string, number>();
    installs.forEach((i) => perDevice.set(i.device.id, (perDevice.get(i.device.id) ?? 0) + 1));
    const palette = dark ? SERIES_DARK : SERIES_LIGHT;
    const updatedOf = (id: string) => {
      const raw = aggregatesByAgent[id]?.last_updated;
      return raw == null ? null : Number(raw) < 1e12 ? Number(raw) * 1000 : Number(raw);
    };
    const pumpRows: Row[] = installs.map(({ device, appKey: key, label }) => {
      const tags = (aggregatesByAgent[device.id]?.data?.[key] ?? {}) as PumpTags;
      const lastUpdated = updatedOf(device.id);
      const base = device.display_name || device.name || device.id;
      return {
        key: `${device.id}:${key}`,
        deviceId: device.id,
        appKey: key,
        totalTag: "volume_total_ml",
        name: (perDevice.get(device.id) ?? 0) > 1 ? `${base} — ${label}` : base,
        colour: "",
        tags,
        lastUpdated,
        status: statusOf(tags, lastUpdated),
      };
    });
    const now = Date.now();
    const liftRows: Row[] = lifts.flatMap(({ device, appKey: key }) => {
      const data = (aggregatesByAgent[device.id]?.data?.[key] ?? {}) as Record<string, unknown>;
      const lastUpdated = updatedOf(device.id);
      const base = device.display_name || device.name || device.id;
      return Object.keys(data)
        .filter((k) => k.endsWith("_name") && typeof data[k] === "string")
        .map((k) => {
          const slug = k.slice(0, -"_name".length);
          const tags = liftMotorTags(data, slug, now);
          return {
            key: `${device.id}:${key}:${slug}`,
            deviceId: device.id,
            appKey: key,
            totalTag: `${slug}_volume_total`,
            name: `${base} — ${data[k] as string}`,
            colour: "",
            tags,
            lastUpdated,
            status: statusOf(tags, lastUpdated),
          };
        });
    });
    return [...pumpRows, ...liftRows]
      // Colour follows the pump (sorted by name), not its rank on any metric.
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((r, i) => ({ ...r, colour: palette[i % palette.length] }));
  }, [installs, lifts, aggregatesByAgent, dark]);

  // ---- history: ML pumped per bucket, from each pump's cumulative total
  const [rangeDays, setRangeDays] = useState(7);
  const top = useMemo(() => Date.now() + 60_000, [rangeDays]);
  const before = useMemo(() => generateSnowflakeIdAtTime(top), [top]);
  const after = useMemo(() => generateSnowflakeIdAtTime(top - rangeDays * DAY_MS), [top, rangeDays]);
  const historyFields = useMemo(() => [...new Set(rows.map((r) => `${r.appKey}.${r.totalTag}`))], [rows]);
  const maxPages = Math.ceil((rangeDays * DAY_MS) / WEEK_MS) * 4;
  const history = useMultiAgentChannelMessages<HistoryMessage["data"]>("tag_values", deviceIds, {
    initialBefore: before,
    after,
    fields: historyFields,
    agentMessageLimit: 1000,
    liveUpdates: false,
    autoPaginate: true,
    maxPages,
  });
  const historyLoading = history.isFetching || (history.hasNextPage && (history.data?.pages.length ?? 0) < maxPages);

  const hourly = rangeDays === 1;
  const buckets = useMemo<Bucket[]>(() => {
    const step = hourly ? HOUR_MS : DAY_MS;
    const startOf = (t: number) => {
      const d = new Date(t);
      if (hourly) d.setMinutes(0, 0, 0);
      else d.setHours(0, 0, 0, 0);
      return d.getTime();
    };
    const first = startOf(top - rangeDays * DAY_MS + step);
    const out: Bucket[] = [];
    for (let s = first; s <= top; s += step) out.push({ start: s, values: {}, total: 0 });
    // A day bucket isn't exactly 24 h across DST; index by start time.
    const index = new Map(out.map((b, i) => [b.start, i]));
    const series = new Map<string, { t: number; v: number }[]>();
    const rowsByAgent = new Map<string, Row[]>();
    rows.forEach((r) => rowsByAgent.set(r.deviceId, [...(rowsByAgent.get(r.deviceId) ?? []), r]));
    for (const m of history.messages as HistoryMessage[]) {
      const agent = String(m.channel?.agent_id ?? m.agent_id ?? "");
      const t = msgTime(m);
      if (!agent || t == null) continue;
      for (const r of rowsByAgent.get(agent) ?? []) {
        const tags = m.data?.[r.appKey] as Record<string, unknown> | undefined;
        const v = num(tags?.[r.totalTag]);
        if (v == null) continue;
        (series.get(r.key) ?? series.set(r.key, []).get(r.key)!).push({ t, v });
      }
    }
    for (const [k, pts] of series) {
      pts.sort((a, b) => a.t - b.t);
      // Diff against the running high-water mark, not the previous point, so
      // a total that dips (a bad 0, a restart) and recovers isn't counted twice.
      let high = pts[0]?.v ?? 0;
      for (let i = 1; i < pts.length; i++) {
        const d = pts[i].v - high;
        if (d <= 0) continue;
        high = pts[i].v;
        const bi = index.get(startOf(pts[i].t));
        if (bi == null) continue;
        out[bi].values[k] = (out[bi].values[k] ?? 0) + d;
        out[bi].total += d;
      }
    }
    return out;
  }, [history.messages, rows, top, rangeDays, hourly]);
  const rangeTotal = buckets.reduce((s, b) => s + b.total, 0);

  const totals = useMemo(() => {
    const today = localToday();
    let flow = 0, vol = 0, running = 0;
    // Farm averages only over pumps that report that kind of usage, so a
    // pump with no fuel data doesn't dilute litres per ML.
    let fuelL = 0, fuelVol = 0, kwh = 0, kwhVol = 0;
    for (const r of rows) {
      if (r.status === "running") {
        running += 1;
        flow += num(r.tags.flow_m3h) ?? 0;
      }
      if (r.tags.today_date !== today) continue;
      const v = num(r.tags.volume_today_ml) ?? 0;
      vol += v;
      if (num(r.tags.fuel_per_ml_today) != null) { fuelL += num(r.tags.fuel_today_l) ?? 0; fuelVol += v; }
      if (num(r.tags.energy_per_ml_today) != null) { kwh += num(r.tags.energy_today_kwh) ?? 0; kwhVol += v; }
    }
    for (const { device, appKey: key } of lifts) {
      const data = (aggregatesByAgent[device.id]?.data?.[key] ?? {}) as Record<string, unknown>;
      const reset = num(data.daily_reset_time);
      if (reset == null || Date.now() >= reset) continue;
      const e = num(data.energy_today_kwh) ?? 0, v = num(data.volume_today) ?? 0;
      if (v > 0) { kwh += e; kwhVol += v; }
    }
    return {
      flowMlDay: (flow * 24) / 1000,
      vol,
      running,
      today,
      fuelPerMl: fuelVol > 0 ? fuelL / fuelVol : null,
      kwhPerMl: kwhVol > 0 ? kwh / kwhVol : null,
    };
  }, [rows, lifts, aggregatesByAgent]);

  if (!isLoading && !hasDeviceMap) {
    return <p className="p-4 text-sm text-muted-foreground">Grant this dashboard access to the pump devices in its Devices (extended permissions) config.</p>;
  }

  return (
    <div className="flex flex-col gap-3 p-1 text-sm text-foreground">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold">{title}</h2>
        <span className="text-xs text-muted-foreground">Flow is estimated from each pump's speed, curve and assumed head</span>
      </div>

      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
        <Stat label="Pumps running" value={`${totals.running} / ${rows.length}`} />
        <Stat label="Current flow" value={`${fmt(totals.flowMlDay, 1)} ML/day`} sub={`${fmt((totals.flowMlDay * 1000) / 24, 0)} m³/h`} />
        <Stat label="Pumped today" value={`${fmt(totals.vol, 2)} ML`} />
        {totals.fuelPerMl != null && <Stat label="Diesel per ML today" value={`${fmt(totals.fuelPerMl, 0)} L/ML`} sub="diesel pumps" />}
        {totals.kwhPerMl != null && <Stat label="Energy per ML today" value={`${fmt(totals.kwhPerMl, 0)} kWh/ML`} sub="electric pumps" />}
      </div>

      <div className="rounded-lg border border-border bg-card p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-sm font-medium">Pumped</div>
            <div className="text-xs text-muted-foreground">{fmt(rangeTotal, 1)} ML in the last {RANGES.find((r) => r.days === rangeDays)?.label}</div>
          </div>
          <div className="flex gap-1">
            {RANGES.map((r) => (
              <button
                key={r.days}
                type="button"
                onClick={() => setRangeDays(r.days)}
                aria-pressed={r.days === rangeDays}
                className={`rounded-md border px-2 py-0.5 text-xs ${r.days === rangeDays ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-foreground"}`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
        <PumpedChart rows={rows} buckets={buckets} hourly={hourly} loading={historyLoading} />
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {rows.map((r) => (
            <span key={r.key} className="flex items-center gap-1.5">
              <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: r.colour }} />
              {r.name}
            </span>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-border bg-card">
        <table className="w-full border-collapse" style={{ tableLayout: "auto" }}>
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              {["Pump", "Status", "Flow", "Pumped today", "Per ML now", "Per ML today", "Updated"].map((h, i) => (
                <th key={h} className={`border-b border-border px-2 py-2 font-medium ${i >= 2 && i <= 5 ? "text-right" : ""}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-2 py-6 text-center text-muted-foreground">
                  {isLoading ? "Loading…" : "No granted devices run Pump Analysis."}
                </td>
              </tr>
            )}
            {rows.map((r) => {
              const t = r.tags;
              const live = r.status === "running";
              const isToday = t.today_date === totals.today;
              const s = STATUS[r.status];
              return (
                <tr key={r.key} className="border-b border-border last:border-0">
                  <td className="px-2 py-2 font-medium">
                    <span className="mr-1.5 inline-block h-2.5 w-2.5 rounded-sm align-middle" style={{ background: r.colour }} />
                    <Link to={`/agent/${r.deviceId}`} className="hover:underline">{r.name}</Link>
                  </td>
                  <td className="px-2 py-2">
                    <span className={`whitespace-nowrap rounded px-2 py-0.5 text-xs ${s.cls}`} title={t.fault_text || undefined}>{s.label}</span>
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-right tabular-nums">{live ? `${fmt(((num(t.flow_m3h) ?? 0) * 24) / 1000, 1)} ML/d` : "—"}</td>
                  <td className="whitespace-nowrap px-2 py-2 text-right tabular-nums">{isToday ? `${fmt(num(t.volume_today_ml), 2)} ML` : "0.00 ML"}</td>
                  <td className="whitespace-nowrap px-2 py-2 text-right tabular-nums">{live ? perMl(num(t.fuel_per_ml), num(t.energy_per_ml)) : "—"}</td>
                  <td className="whitespace-nowrap px-2 py-2 text-right tabular-nums">{isToday ? perMl(num(t.fuel_per_ml_today), num(t.energy_per_ml_today)) : "—"}</td>
                  <td className="whitespace-nowrap px-2 py-2 text-xs text-muted-foreground">{ago(r.lastUpdated)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const PumpFarmOverviewWidget = (props: any) => (
  <RemoteComponentWrapper>
    <Inner {...props} />
  </RemoteComponentWrapper>
);

export default PumpFarmOverviewWidget;
