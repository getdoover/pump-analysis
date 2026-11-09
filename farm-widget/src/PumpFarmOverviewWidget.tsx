import { useMemo } from "react";
import { Link } from "react-router";
import { useAgentChannel, useDeviceMap, useMultiAgentAggregates, type DeviceMapEntry } from "doover-js/react";
import RemoteComponentWrapper from "customer_site/RemoteComponentWrapper";
import { useRemoteParams } from "customer_site/useRemoteParams";

import "./styles.css";

// Apps whose tags this dashboard reads (both publish the same tag set).
const PUMP_APPS = ["pump_analysis", "pump_analysis_processor"];
// No update for this long and the last state can't be trusted: remote pumps
// sleep without ever publishing a stop, so their last speed sticks.
const STALE_MS = 30 * 60_000;

interface Entry extends DeviceMapEntry {}

interface DashConfig {
  applications?: Record<string, { title?: string | null }>;
}

type PumpTags = Partial<{
  state: string;
  fault_text: string;
  pump_rpm: number | null;
  tdh_m: number | null;
  flow_m3h: number | null;
  flow_confidence: number | null;
  fuel_per_ml: number | null;
  energy_per_ml: number | null;
  volume_today_ml: number;
  fuel_today_l: number;
  energy_today_kwh: number;
  fuel_per_ml_today: number | null;
  energy_per_ml_today: number | null;
  run_hours_today: number;
  today_date: string;
  volume_total_ml: number;
}>;

interface Row {
  key: string;
  deviceId: string;
  name: string;
  tags: PumpTags;
  lastUpdated: number | null;
  status: "running" | "stopped" | "fault" | "stale" | "unknown";
}

function pumpInstalls(d: Entry): { appKey: string; label: string }[] {
  return (d.app_installs ?? [])
    .filter((i) => PUMP_APPS.includes(i.application_name ?? "") && i.name)
    .map((i) => ({ appKey: i.name as string, label: i.display_name || (i.name as string) }));
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

function Inner({ uiElement }: { uiElement: { app_key?: string } }) {
  const params = useRemoteParams();
  const agentId = params?.agentId == null ? undefined : String(params.agentId);
  const appKey = uiElement?.app_key ?? "";

  const { data: deployment } = useAgentChannel<DashConfig>(agentId, "deployment_config");
  const cfg = deployment?.applications?.[appKey] ?? {};
  const title = cfg.title?.trim() || "Farm Pumps";

  const { devices, isLoading, hasDeviceMap } = useDeviceMap<Entry>(agentId, appKey);
  const installs = useMemo(
    () => devices.flatMap((d) => pumpInstalls(d).map((i) => ({ device: d, ...i }))),
    [devices],
  );
  const deviceIds = useMemo(() => [...new Set(installs.map((i) => i.device.id))], [installs]);
  const fields = useMemo(() => [...new Set(installs.map((i) => i.appKey))], [installs]);
  const { aggregatesByAgent } = useMultiAgentAggregates<Record<string, PumpTags>>(
    "tag_values",
    deviceIds,
    { fields },
  );

  const rows = useMemo<Row[]>(() => {
    const perDevice = new Map<string, number>();
    installs.forEach((i) => perDevice.set(i.device.id, (perDevice.get(i.device.id) ?? 0) + 1));
    return installs
      .map(({ device, appKey: key, label }) => {
        const agg = aggregatesByAgent[device.id];
        const tags = (agg?.data?.[key] ?? {}) as PumpTags;
        const raw = agg?.last_updated;
        const lastUpdated = raw == null ? null : Number(raw) < 1e12 ? Number(raw) * 1000 : Number(raw);
        const base = device.display_name || device.name || device.id;
        return {
          key: `${device.id}:${key}`,
          deviceId: device.id,
          name: (perDevice.get(device.id) ?? 0) > 1 ? `${base} — ${label}` : base,
          tags,
          lastUpdated,
          status: statusOf(tags, lastUpdated),
        };
      })
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [installs, aggregatesByAgent]);

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
    return {
      flowMlDay: (flow * 24) / 1000,
      vol,
      running,
      today,
      fuelPerMl: fuelVol > 0 ? fuelL / fuelVol : null,
      kwhPerMl: kwhVol > 0 ? kwh / kwhVol : null,
    };
  }, [rows]);

  if (!isLoading && !hasDeviceMap) {
    return <p className="p-4 text-sm text-muted-foreground">Grant this dashboard access to the pump devices in its Devices (extended permissions) config.</p>;
  }

  return (
    <div className="flex flex-col gap-3 p-1 text-sm text-foreground">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold">{title}</h2>
        <span className="text-xs text-muted-foreground">Flow is estimated from each pump's curve, speed and assumed head</span>
      </div>

      <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
        <Stat label="Pumps running" value={`${totals.running} / ${rows.length}`} />
        <Stat label="Current flow" value={`${fmt(totals.flowMlDay, 1)} ML/day`} sub={`${fmt((totals.flowMlDay * 1000) / 24, 0)} m³/h`} />
        <Stat label="Pumped today" value={`${fmt(totals.vol, 2)} ML`} />
        {totals.fuelPerMl != null && <Stat label="Diesel per ML today" value={`${fmt(totals.fuelPerMl, 0)} L/ML`} sub="diesel pumps, farm average" />}
        {totals.kwhPerMl != null && <Stat label="Energy per ML today" value={`${fmt(totals.kwhPerMl, 0)} kWh/ML`} sub="electric pumps, farm average" />}
      </div>

      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <table className="w-full border-collapse" style={{ minWidth: 760 }}>
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              {["Pump", "Status", "Pump speed", "Head", "Flow", "Pumped today", "Per ML now", "Per ML today", "Updated"].map((h, i) => (
                <th key={h} className={`border-b border-border px-3 py-2 font-medium ${i >= 2 && i <= 7 ? "text-right" : ""}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-6 text-center text-muted-foreground">
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
                  <td className="px-3 py-2 font-medium">
                    <Link to={`/agent/${r.deviceId}`} className="hover:underline">{r.name}</Link>
                  </td>
                  <td className="px-3 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs ${s.cls}`} title={t.fault_text || undefined}>{s.label}</span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{live ? `${fmt(num(t.pump_rpm), 0)} rpm` : "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{num(t.tdh_m) != null ? `${fmt(num(t.tdh_m), 1)} m` : "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{live ? `${fmt(((num(t.flow_m3h) ?? 0) * 24) / 1000, 1)} ML/d` : "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{isToday ? `${fmt(num(t.volume_today_ml), 2)} ML` : "0.00 ML"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{live ? perMl(num(t.fuel_per_ml), num(t.energy_per_ml)) : "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{isToday ? perMl(num(t.fuel_per_ml_today), num(t.energy_per_ml_today)) : "—"}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">{ago(r.lastUpdated)}</td>
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
