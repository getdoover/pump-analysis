import { useMemo } from "react";
import dayjs from "dayjs";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useAgentChannel, useDooverClient } from "doover-js/react";
import { generateSnowflakeIdAtTime } from "doover-js";
import RemoteComponentWrapper from "customer_site/RemoteComponentWrapper";
import { useRemoteParams } from "customer_site/useRemoteParams";

import { Badge, Card, CardContent, CardHeader } from "./components/ui";
import { RadialGauge } from "./components/RadialGauge";
import {
  parseConfig,
  scaleCurve,
  tagValue,
  STATE_BADGE,
  STATE_LABELS,
  type CurvePoint,
} from "./lib/pump";
import "./styles.css";

const TRAIL_HOURS = 1;
const TRAIL_LIMIT = 500;

// Status colours follow the house dataviz palette (reserved for state);
// the reference curve is a deliberate de-emphasis gray, carried by its
// dash pattern + legend entry rather than hue alone.
const COLOURS = {
  refCurve: "#94a3b8",
  liveCurve: "#2563eb", // blue-600 accent
  liveCurveTrack: "#dbeafe", // blue-100 — gauge track, same ramp
  npshr: "#d03b3b", // status critical
  npsha: "#2563eb",
  margin: "#0ca30c", // status good
  point: "#0ca30c",
  pointDanger: "#d03b3b",
  pointMarginal: "#fab219", // status warning
  marginalTrack: "#fdeecd",
  dangerTrack: "#f6d8d8",
  goodTrack: "#cdeccd",
  trail: "#93c5fd",
  bep: "#0ca30c",
};

interface TrailPoint {
  ts: number;
  flow: number | null;
  head: number | null;
  npsha: number | null;
  npshr: number | null;
  margin: number | null;
}

function PumpAnalysisInner({ uiElement }: { uiElement?: { app_key?: string } }) {
  const params = useRemoteParams();
  const agentId = params.agentId;
  const appKey = uiElement?.app_key;
  const client = useDooverClient();

  const { data: depCfg } = useAgentChannel<{ applications?: Record<string, Record<string, unknown>> }>(
    agentId,
    "deployment_config"
  );
  const { data: tagAgg } = useAgentChannel<Record<string, unknown>>(agentId, "tag_values");

  const cfg = useMemo(
    () => parseConfig((appKey ? depCfg?.applications?.[appKey] : undefined) ?? {}),
    [depCfg, appKey]
  );
  const fx = cfg.flowFactor; // m³/h -> display units, applied to every flow axis/value
  const pf = cfg.pressureFactor; // bar -> display units, for the pressure gauges
  const pressurePrecision = Math.abs(pf) >= 5 ? 1 : 2;

  const live = useMemo(() => {
    const t = (tag: string) => (appKey ? tagValue(tagAgg, appKey, tag) : null);
    return {
      flow: t("flow_m3h"),
      head: t("tdh_m"),
      rpm: t("pump_rpm"),
      suction: t("suction_bar"),
      discharge: t("discharge_bar"),
      npsha: t("npsha_m"),
      npshr: t("npshr_m"),
      margin: t("npsh_margin_m"),
      confidence: t("flow_confidence"),
      pctOfBep: t("pct_of_bep"),
      state: (appKey && ((tagAgg?.[appKey] as Record<string, unknown>)?.state as string)) || "not_running",
      flowOrigin:
        (appKey && ((tagAgg?.[appKey] as Record<string, unknown>)?.flow_origin as string)) || "none",
    };
  }, [tagAgg, appKey]);

  // Recent operating-point trail from tag history.
  const trailQuery = useQuery({
    queryKey: ["pump-trail", agentId, appKey],
    enabled: !!agentId && !!appKey,
    refetchInterval: 60_000,
    queryFn: async (): Promise<TrailPoint[]> => {
      const now = dayjs();
      const res = await client.messages.getTimeseries(agentId!, "tag_values", {
        after: generateSnowflakeIdAtTime(now.subtract(TRAIL_HOURS, "hour")),
        before: generateSnowflakeIdAtTime(now.add(1, "minute")),
        field_name: [appKey!],
        limit: TRAIL_LIMIT,
      });
      const rows = (res.results ?? []) as Array<{
        timestamp?: string;
        value: Record<string, unknown>;
      }>;
      return rows
        .map((r) => {
          const v = (k: string): number | null => {
            const nested = r.value?.[appKey!] as Record<string, unknown> | undefined;
            const raw = nested?.[k] ?? r.value?.[`${appKey}.${k}`];
            return typeof raw === "number" ? raw : null;
          };
          return {
            ts: dayjs(r.timestamp).valueOf(),
            flow: v("flow_m3h"),
            head: v("tdh_m"),
            npsha: v("npsha_m"),
            npshr: v("npshr_m"),
            margin: v("npsh_margin_m"),
          };
        })
        .filter((p) => p.flow != null || p.margin != null);
    },
  });
  const trail = trailQuery.data ?? [];

  const haveCurve = cfg.curve.length >= 2 && cfg.referenceRpm != null;
  const speedScale = haveCurve && live.rpm ? live.rpm / cfg.referenceRpm! : 1;
  const liveCurve: CurvePoint[] =
    haveCurve && live.rpm ? scaleCurve(cfg.curve, cfg.referenceRpm!, live.rpm) : [];

  // All flow coordinates below are in DISPLAY units (× fx).
  const refCurveD = cfg.curve.map((p) => ({ ...p, flow: p.flow_m3h * fx }));
  const liveCurveD = liveCurve.map((p) => ({ ...p, flow: p.flow_m3h * fx }));

  // Shared flow-axis domain across the stacked panels (datasheet style:
  // head-flow on top, NPSH in its own panel below, one x-axis).
  const xMax = Math.max(
    ...refCurveD.map((p) => p.flow),
    ...liveCurveD.map((p) => p.flow),
    live.flow != null ? live.flow * fx : 0
  );

  // NPSH risk bands, anchored to the (live-speed) NPSHr curve: if the blue
  // NPSHa point falls inside a band at the operating flow, the pump is in
  // that state.
  const npshrSource = (liveCurveD.length ? liveCurveD : refCurveD).filter(
    (p) => p.npshr_m != null
  );
  const bands = npshrSource.map((p) => ({
    flow: p.flow,
    cavitation_band: [0, p.npshr_m!] as [number, number],
    danger_band: [p.npshr_m!, p.npshr_m! + cfg.dangerMarginM] as [number, number],
    warn_band: [
      p.npshr_m! + cfg.dangerMarginM,
      p.npshr_m! + cfg.warningMarginM,
    ] as [number, number],
  }));
  const labelAnchor = npshrSource.length
    ? npshrSource[Math.floor((npshrSource.length - 1) * 0.7)]
    : null;
  const zoneLabels = labelAnchor
    ? [
        {
          flow: labelAnchor.flow,
          y: labelAnchor.npshr_m! / 2,
          text: "Cavitation",
          colour: COLOURS.npshr,
        },
        {
          flow: labelAnchor.flow,
          y: labelAnchor.npshr_m! + (cfg.dangerMarginM + cfg.warningMarginM) / 2,
          text: "Marginal",
          colour: "#8a6100",
        },
      ]
    : [];

  // Efficient operating zone: 70–120% of BEP flow, affinity-scaled.
  const bepLive = cfg.bepFlowM3h != null ? cfg.bepFlowM3h * speedScale * fx : null;

  // Live cavitation boundary on the head-flow panel: the flow at which the
  // rising NPSHr curve crosses (current NPSHa − margin). Approximates NPSHa
  // as constant across flow (slightly optimistic at high flow, where suction
  // friction erodes it further), so the zone moves with suction conditions.
  const crossingFlow = (margin: number): number | null => {
    if (live.npsha == null || npshrSource.length < 2) return null;
    const target = live.npsha - margin;
    if (npshrSource[0].npshr_m! >= target) return npshrSource[0].flow; // already inside
    for (let i = 0; i < npshrSource.length - 1; i++) {
      const a = npshrSource[i];
      const b = npshrSource[i + 1];
      if (a.npshr_m! < target && b.npshr_m! >= target) {
        const t = (target - a.npshr_m!) / (b.npshr_m! - a.npshr_m!);
        return a.flow + t * (b.flow - a.flow);
      }
    }
    return null; // NPSHr never reaches the target within the curve — no zone
  };
  const cavDangerFlow = crossingFlow(cfg.dangerMarginM);
  // NPSHa so low that even shutoff flow is inside the danger margin: there is
  // no cavitation-safe flow — the suction system is the problem, not the
  // operating point. Label the zone accordingly.
  const suctionLimited =
    cavDangerFlow != null &&
    npshrSource.length > 0 &&
    cavDangerFlow <= npshrSource[0].flow + 1e-9;

  const pointColour =
    live.state === "danger"
      ? COLOURS.pointDanger
      : live.state === "marginal"
        ? COLOURS.pointMarginal
        : COLOURS.point;

  const marginMax = cfg.warningMarginM * 2;
  const marginColour =
    live.margin == null || live.margin >= cfg.warningMarginM
      ? COLOURS.margin
      : live.margin >= cfg.dangerMarginM
        ? COLOURS.pointMarginal
        : COLOURS.pointDanger;
  const marginTrack =
    live.margin == null || live.margin >= cfg.warningMarginM
      ? COLOURS.goodTrack
      : live.margin >= cfg.dangerMarginM
        ? COLOURS.marginalTrack
        : COLOURS.dangerTrack;

  const slimTooltip = (
    <Tooltip
      formatter={(value: number | number[], name: string) =>
        Array.isArray(value) ? [null, null] : [Number(value).toFixed(1), name]
      }
      labelFormatter={(flow: number) => `${Number(flow).toFixed(1)} ${cfg.flowUnit}`}
    />
  );

  return (
    <div className="paw-root">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-center gap-1.5 flex-wrap">
            <Badge variant={STATE_BADGE[live.state] ?? "secondary"}>
              {STATE_LABELS[live.state] ?? live.state}
            </Badge>
            {live.rpm != null && (
              <Badge variant="outline">Pump {Math.round(live.rpm)} RPM</Badge>
            )}
            {live.pctOfBep != null && (
              <Badge variant="outline">{Math.round(live.pctOfBep)}% of BEP</Badge>
            )}
            {live.flowOrigin === "inferred" && (
              <Badge variant="secondary">
                flow inferred{live.confidence != null ? ` · conf ${(live.confidence * 100).toFixed(0)}%` : ""}
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {cfg.showGauges && (live.flow != null || live.margin != null) && (
            <div className="flex items-start justify-center gap-6 flex-wrap">
              {live.flow != null && haveCurve && (
                <RadialGauge
                  value={live.flow * fx}
                  max={Math.max(...cfg.curve.map((p) => p.flow_m3h)) * fx}
                  unit={cfg.flowUnit}
                  label="Flow"
                  precision={2}
                  subtitle={
                    live.flowOrigin === "inferred"
                      ? `inferred${live.confidence != null ? `, ${(live.confidence * 100).toFixed(0)}% confidence` : ""}`
                      : live.flowOrigin === "measured"
                        ? "measured"
                        : undefined
                  }
                  fill={COLOURS.liveCurve}
                  track={COLOURS.liveCurveTrack}
                />
              )}
              {live.margin != null && (
                <RadialGauge
                  value={live.margin}
                  max={marginMax}
                  unit="m"
                  label="NPSH margin"
                  precision={2}
                  subtitle={`warn < ${cfg.warningMarginM} m · danger < ${cfg.dangerMarginM} m`}
                  fill={marginColour}
                  track={marginTrack}
                />
              )}
            </div>
          )}
          {cfg.showGauges && (live.suction != null || live.discharge != null) && (
            <div className="flex items-start justify-center gap-6 flex-wrap">
              {live.suction != null && (
                <RadialGauge
                  size="sm"
                  value={live.suction * pf}
                  min={cfg.suctionRange[0] * pf}
                  max={cfg.suctionRange[1] * pf}
                  unit={cfg.pressureUnit}
                  label="Inlet pressure"
                  precision={pressurePrecision}
                  fill={
                    live.suction <= -0.5
                      ? COLOURS.pointDanger
                      : live.suction <= -0.15
                        ? COLOURS.pointMarginal
                        : COLOURS.margin
                  }
                  track={
                    live.suction <= -0.5
                      ? COLOURS.dangerTrack
                      : live.suction <= -0.15
                        ? COLOURS.marginalTrack
                        : COLOURS.goodTrack
                  }
                />
              )}
              {live.discharge != null && (
                <RadialGauge
                  size="sm"
                  value={live.discharge * pf}
                  min={cfg.dischargeRange[0] * pf}
                  max={cfg.dischargeRange[1] * pf}
                  unit={cfg.pressureUnit}
                  label="Discharge pressure"
                  precision={pressurePrecision}
                  fill={COLOURS.liveCurve}
                  track={COLOURS.liveCurveTrack}
                />
              )}
            </div>
          )}

          <div>
              {!haveCurve ? (
                <p className="text-sm text-muted-foreground py-6 text-center">
                  No pump curve configured — add curve points and a reference speed in the app
                  config to enable the operating-point chart.
                </p>
              ) : (
                <>
                  {/* Datasheet-style stacked panels sharing one flow axis:
                      head-flow on top, NPSH in its own panel below. */}
                  <ResponsiveContainer width="100%" height={252}>
                    <ComposedChart margin={{ top: 8, right: 12, bottom: 18, left: 0 }} syncId="pump-curve">
                      <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
                      <XAxis
                        type="number"
                        dataKey="flow"
                        domain={[0, xMax]}
                        tick={{ fontSize: 11 }}
                        height={34}
                        label={{
                          value: `Flow (${cfg.flowUnit})`,
                          position: "insideBottom",
                          offset: -6,
                          fontSize: 11,
                        }}
                      />
                      <YAxis
                        type="number"
                        width={56}
                        domain={[0, (dataMax: number) => Math.ceil(dataMax / 5) * 5]}
                        tick={{ fontSize: 11 }}
                        label={{ value: "Head (m)", angle: -90, position: "insideLeft", fontSize: 11 }}
                      />
                      {slimTooltip}
                      {/* Efficient operating zone: 70–120% of BEP flow */}
                      {bepLive != null && (
                        <ReferenceArea
                          x1={bepLive * 0.7}
                          x2={bepLive * 1.2}
                          fill={COLOURS.bep}
                          fillOpacity={0.07}
                          label={{
                            value: "Efficient zone",
                            position: "insideTop",
                            fontSize: 10,
                            fill: "#0a7a0a",
                          }}
                        />
                      )}
                      {/* Live cavitation boundary: flows where NPSHr overtakes
                          today's NPSHa. Moves with suction conditions. Red
                          only — an amber pre-band muddied the overlay with the
                          green efficient zone; the NPSH panel below carries
                          the marginal story. */}
                      {cavDangerFlow != null && (
                        <ReferenceArea
                          x1={cavDangerFlow}
                          x2={xMax}
                          fill={COLOURS.npshr}
                          fillOpacity={0.07}
                          label={{
                            value: suctionLimited
                              ? "Cavitating at ALL flows — check suction"
                              : "Cavitation at current suction",
                            position: suctionLimited ? "insideTop" : "insideTopRight",
                            fontSize: 10,
                            fill: COLOURS.npshr,
                          }}
                        />
                      )}
                      {/* Nameplate curve (manufacturer, at reference speed) */}
                      <Line
                        data={refCurveD}
                        dataKey="head_m"
                        name={`Nameplate curve @ ${cfg.referenceRpm} RPM`}
                        stroke={COLOURS.refCurve}
                        strokeDasharray="6 4"
                        dot={false}
                        isAnimationActive={false}
                        tooltipType="none"
                      />
                      {/* Same curve at the live speed — where the pump should sit now */}
                      {liveCurveD.length > 0 && (
                        <Line
                          data={liveCurveD}
                          dataKey="head_m"
                          name={`Expected @ ${Math.round(live.rpm!)} RPM`}
                          stroke={COLOURS.liveCurve}
                          strokeWidth={2}
                          dot={false}
                          isAnimationActive={false}
                        />
                      )}
                      {/* Recent operating-point trail */}
                      <Scatter
                        data={trail
                          .filter((p) => p.flow != null && p.head != null)
                          .map((p) => ({ flow: p.flow! * fx, head: p.head }))}
                        dataKey="head"
                        name="Trail (1 h)"
                        fill={COLOURS.trail}
                        tooltipType="none"
                        shape={(props: { cx?: number; cy?: number }) => (
                          <circle cx={props.cx} cy={props.cy} r={2.5} fill={COLOURS.trail} opacity={0.6} />
                        )}
                        isAnimationActive={false}
                      />
                      {/* Live operating point: (flow, total head), coloured by state */}
                      {live.flow != null && live.head != null && (
                        <Scatter
                          data={[{ flow: live.flow * fx, y: live.head }]}
                          dataKey="y"
                          name="Operating point"
                          fill={pointColour}
                          isAnimationActive={false}
                          shape={(props: { cx?: number; cy?: number }) => (
                            <g>
                              <circle cx={props.cx} cy={props.cy} r={8} fill={pointColour} opacity={0.25} />
                              <circle cx={props.cx} cy={props.cy} r={4.5} fill={pointColour} />
                            </g>
                          )}
                        />
                      )}
                    </ComposedChart>
                  </ResponsiveContainer>

                  {/* NPSH panel — same flow axis, its own metres scale */}
                  <ResponsiveContainer width="100%" height={176}>
                    <ComposedChart margin={{ top: 2, right: 12, bottom: 18, left: 0 }} syncId="pump-curve">
                      <CartesianGrid strokeDasharray="3 3" opacity={0.4} />
                      <XAxis
                        type="number"
                        dataKey="flow"
                        domain={[0, xMax]}
                        tick={{ fontSize: 11 }}
                        height={34}
                        label={{
                          value: `Flow (${cfg.flowUnit})`,
                          position: "insideBottom",
                          offset: -6,
                          fontSize: 11,
                        }}
                      />
                      <YAxis
                        type="number"
                        width={56}
                        domain={[0, (dataMax: number) => Math.ceil(dataMax)]}
                        tick={{ fontSize: 11 }}
                        allowDecimals={false}
                        label={{ value: "NPSH (m)", angle: -90, position: "insideLeft", fontSize: 11 }}
                      />
                      {slimTooltip}
                      {/* Risk zones anchored to the NPSHr curve — the blue
                          NPSHa point must stay above the shading. */}
                      {bands.length > 1 && (
                        <>
                          <Area data={bands} dataKey="cavitation_band" stroke="none"
                            fill={COLOURS.npshr} fillOpacity={0.18} isAnimationActive={false}
                            legendType="none" tooltipType="none" name="cavitation-zone" />
                          <Area data={bands} dataKey="danger_band" stroke="none"
                            fill={COLOURS.npshr} fillOpacity={0.1} isAnimationActive={false}
                            legendType="none" tooltipType="none" name="danger-zone" />
                          <Area data={bands} dataKey="warn_band" stroke="none"
                            fill={COLOURS.pointMarginal} fillOpacity={0.14} isAnimationActive={false}
                            legendType="none" tooltipType="none" name="marginal-zone" />
                        </>
                      )}
                      {zoneLabels.length > 0 && (
                        <Scatter
                          data={zoneLabels}
                          dataKey="y"
                          name="zone-labels"
                          legendType="none"
                          tooltipType="none"
                          isAnimationActive={false}
                          shape={(props: { cx?: number; cy?: number; payload?: { text: string; colour: string } }) => (
                            <text x={props.cx} y={props.cy} textAnchor="middle"
                              fill={props.payload?.colour}
                              style={{ fontSize: 10, fontWeight: 600, opacity: 0.85 }}>
                              {props.payload?.text}
                            </text>
                          )}
                        />
                      )}
                      {npshrSource.length > 1 && (
                        <Line
                          data={npshrSource}
                          dataKey="npshr_m"
                          name="NPSHr (cavitation floor)"
                          stroke={COLOURS.npshr}
                          strokeDasharray="2 3"
                          dot={false}
                          isAnimationActive={false}
                        />
                      )}
                      {/* Live NPSHa at the operating flow — suction-side health */}
                      {live.flow != null && live.npsha != null && (
                        <Scatter
                          data={[{ flow: live.flow * fx, y: live.npsha }]}
                          dataKey="y"
                          name="NPSHa (available)"
                          fill={COLOURS.npsha}
                          isAnimationActive={false}
                          shape={(props: { cx?: number; cy?: number }) => (
                            <g>
                              <circle cx={props.cx} cy={props.cy} r={4} fill={COLOURS.npsha} />
                              <circle cx={props.cx} cy={props.cy} r={7} fill="none" stroke={COLOURS.npsha} strokeWidth={1.5} opacity={0.5} />
                            </g>
                          )}
                        />
                      )}
                    </ComposedChart>
                  </ResponsiveContainer>
                </>
              )}
          </div>

          <p className="text-xs text-muted-foreground mt-2 mb-0 text-center">
            {live.flowOrigin === "inferred"
              ? "Flow is inferred from the pump curve — a trend indicator, not a measurement."
              : live.flowOrigin === "measured"
                ? "Flow from the configured flow meter."
                : "No flow available."}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

export default function PumpAnalysisWidget(props: { uiElement?: { app_key?: string } }) {
  return (
    <RemoteComponentWrapper>
      <PumpAnalysisInner {...props} />
    </RemoteComponentWrapper>
  );
}
