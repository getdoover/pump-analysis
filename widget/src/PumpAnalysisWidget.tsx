import { useMemo } from "react";
import dayjs from "dayjs";
import { useQuery } from "@tanstack/react-query";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
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
  estimatedNpshr,
  NPSHR_ESTIMATE_SPREAD,
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
      engineRpm: t("engine_rpm"),
      suction: t("suction_bar"),
      discharge: t("discharge_bar"),
      npsha: t("npsha_m"),
      npshr: t("npshr_m"),
      margin: t("npsh_margin_m"),
      npshrEstBep: t("npshr_est_bep_m"),
      confidence: t("flow_confidence"),
      pctOfBep: t("pct_of_bep"),
      state: (appKey && ((tagAgg?.[appKey] as Record<string, unknown>)?.state as string)) || "not_running",
      flowOrigin:
        (appKey && ((tagAgg?.[appKey] as Record<string, unknown>)?.flow_origin as string)) || "none",
      faultText:
        (appKey && ((tagAgg?.[appKey] as Record<string, unknown>)?.fault_text as string)) || "",
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

  // Head off the live-speed curve: there is a head and a speed but no point
  // on the curve to read a flow from. Drawn as a line at that head instead
  // of an operating point. Measured head "below" = turning without building
  // pressure (unloaded / not primed / past run-out); "above" = low flow, left
  // of the curve's first published point (normal briefly; a config problem
  // only if it persists at working speed — it keeps its native warning). With a fixed
  // head nothing is measured: below the curve means the configured head is
  // too low for this speed.
  const liveHeads = liveCurve.map((p) => p.head_m);
  const curveMiss: "below" | "above" | null =
    live.flow == null &&
    live.head != null &&
    liveHeads.length > 0 &&
    live.state !== "not_running" &&
    live.state !== "starting"
      ? live.head < Math.min(...liveHeads)
        ? "below"
        : live.head > Math.max(...liveHeads)
          ? "above"
          : null
      : null;
  const curveSpan = liveHeads.length
    ? `${Math.min(...liveHeads).toFixed(1)}–${Math.max(...liveHeads).toFixed(1)} m`
    : "";

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
  // Opt-in rough NPSHr for curves published without one. Drawn as a grey
  // line inside a ±40% band and labelled as an estimate; it gets none of the
  // red/amber risk zones above and drives no state — those need real NPSHr.
  const estNpshr =
    npshrSource.length < 2 && haveCurve && live.npshrEstBep != null && cfg.bepFlowM3h
      ? estimatedNpshr(
          liveCurve.length ? liveCurve : cfg.curve,
          live.npshrEstBep,
          cfg.bepFlowM3h,
          speedScale
        ).map((p) => ({
          flow: p.flow_m3h * fx,
          npshr_est: p.npshr_m,
          est_band: [
            p.npshr_m * (1 - NPSHR_ESTIMATE_SPREAD),
            p.npshr_m * (1 + NPSHR_ESTIMATE_SPREAD),
          ] as [number, number],
        }))
      : [];
  const estLabel = estNpshr.length ? estNpshr[0] : null;

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

  // The figure can be hidden per site; "flow inferred" itself always shows.
  const showConfidence = cfg.showFlowConfidence && live.confidence != null;

  // The axis ends at the widest curve, which is rarely a round number once
  // the live curve is scaled past reference speed.
  const flowTick = (v: number) => (xMax >= 100 ? Math.round(v).toString() : Number(v.toFixed(1)).toString());

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
              {live.state === "config_fault" && curveMiss === "below" && !cfg.headFixed
                ? "No head"
                : (STATE_LABELS[live.state] ?? live.state)}
            </Badge>
            {live.rpm != null && (
              <Badge variant="outline">Pump {Math.round(live.rpm)} RPM</Badge>
            )}
            {/* Engine speed, where there is one and it isn't simply the pump
                speed again (direct drive, ratio 1). */}
            {live.engineRpm != null &&
              (live.rpm == null || Math.round(live.engineRpm) !== Math.round(live.rpm)) && (
                <Badge variant="outline">Engine {Math.round(live.engineRpm)} RPM</Badge>
              )}
            {live.pctOfBep != null && (
              <Badge variant="outline">
                {live.flowOrigin === "inferred" ? "~" : ""}
                {Math.round(live.pctOfBep)}% of BEP
              </Badge>
            )}
            {estNpshr.length > 0 && <Badge variant="secondary">NPSHr estimated</Badge>}
            {live.flowOrigin === "inferred" && (
              <Badge variant="secondary">
                flow inferred, not verified{showConfidence ? ` · conf ${(live.confidence! * 100).toFixed(0)}%` : ""}
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
                      ? `inferred${showConfidence ? `, ${(live.confidence! * 100).toFixed(0)}% confidence` : ""}`
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
                        tickFormatter={flowTick}
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
                      {/* Head off the curve: no operating point to plot, so
                          mark the measured head itself. */}
                      {curveMiss && (
                        <ReferenceLine
                          y={live.head!}
                          stroke={COLOURS.pointMarginal}
                          strokeWidth={2}
                          strokeDasharray="5 4"
                          ifOverflow="extendDomain"
                          label={{
                            value: `${cfg.headFixed ? "Fixed" : "Measured"} head ${live.head!.toFixed(1)} m — ${curveMiss} the curve`,
                            position: curveMiss === "below" ? "insideBottomLeft" : "insideTopLeft",
                            fontSize: 10,
                            fontWeight: 600,
                            fill: "#8a6100",
                          }}
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
                        tickFormatter={flowTick}
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
                      {/* Estimated NPSHr (no datasheet values): band + line,
                          grey on purpose — it is not a cavitation limit. */}
                      {estNpshr.length > 1 && (
                        <>
                          <Area data={estNpshr} dataKey="est_band" stroke="none"
                            fill={COLOURS.refCurve} fillOpacity={0.18} isAnimationActive={false}
                            legendType="none" tooltipType="none" name="npshr-estimate-band" />
                          <Line
                            data={estNpshr}
                            dataKey="npshr_est"
                            name="NPSHr (estimated)"
                            stroke={COLOURS.refCurve}
                            strokeDasharray="6 4"
                            dot={false}
                            isAnimationActive={false}
                          />
                          {estLabel && (
                            <Scatter
                              data={[{
                                flow: estLabel.flow,
                                y: estLabel.est_band[1],
                                text: `Estimated NPSHr ±${Math.round(NPSHR_ESTIMATE_SPREAD * 100)}% (not datasheet)`,
                              }]}
                              dataKey="y"
                              name="npshr-estimate-label"
                              legendType="none"
                              tooltipType="none"
                              isAnimationActive={false}
                              shape={(props: { cx?: number; cy?: number; payload?: { text: string } }) => (
                                <text x={props.cx} y={(props.cy ?? 0) - 4} textAnchor="start"
                                  className="fill-muted-foreground"
                                  style={{ fontSize: 10, fontWeight: 600 }}>
                                  {props.payload?.text}
                                </text>
                              )}
                            />
                          )}
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
              ? "Flow is read off the pump curve at the measured head, so it is only right if the pump is really on this curve. Wear, cavitation or a wrong speed ratio all make it read high, and nothing here can detect that without a flow meter. The confidence figure reflects curve steepness only."
              : live.flowOrigin === "measured"
                ? "Flow from the configured flow meter."
                : curveMiss && cfg.headFixed
                  ? `Fixed head ${live.head!.toFixed(1)} m is off the curve at this speed (${curveSpan}) — check the configured fixed total head. No flow estimate.`
                  : curveMiss === "below"
                  ? `Pump is turning but making ${live.head!.toFixed(1)} m of head; the curve covers ${curveSpan} at this speed. Unloaded, not primed, or past run-out — no flow estimate.`
                  : curveMiss === "above"
                    ? `Measured head ${live.head!.toFixed(1)} m is above the published curve at this speed (${curveSpan}): the pump is at low flow, left of the curve's first point, so there is no flow estimate. If it stays like this at working speed, check the speed ratio, curve points and pressure ranges.`
                    : live.faultText || "No flow available."}
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
