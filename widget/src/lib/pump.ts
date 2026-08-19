/* Curve + config helpers for the pump-analysis widget.

   Config keys here are the explicit `name=` keys declared in app_config.py —
   they are asserted by tests/test_imports.py on the Python side. If a key is
   renamed there, rename it here in the same change. */

export interface CurvePoint {
  flow_m3h: number;
  head_m: number;
  npshr_m?: number | null;
}

export interface PumpConfig {
  pumpName: string;
  curve: CurvePoint[];
  referenceRpm: number | null;
  warningMarginM: number;
  dangerMarginM: number;
  bepFlowM3h: number | null;
  /** display unit label + m³/h -> display factor (matches FLOW_UNIT_INFO in app_config.py) */
  flowUnit: string;
  flowFactor: number;
  /** testing aid — production installs show the native gauge variables instead */
  showGauges: boolean;
  /** transmitter spans, bar gauge (drive the pressure gauge scales) */
  suctionRange: [number, number];
  dischargeRange: [number, number];
  /** display unit label + bar -> display factor */
  pressureUnit: string;
  pressureFactor: number;
}

const PRESSURE_UNITS: Record<string, [string, number]> = {
  // metres_head factor is density-dependent; the app publishes pre-converted
  // display tags, so this is only used for the gauge scales/thresholds.
  metres_head: ["m head", 10.1997],
  bar: ["bar", 1],
  kpa: ["kPa", 100],
  psi: ["psi", 14.50377],
};

const FLOW_UNITS: Record<string, [string, number]> = {
  ml_per_day: ["ML/day", 24 / 1000],
  m3_per_hour: ["m³/h", 1],
  l_per_s: ["L/s", 1 / 3.6],
};

// deployment_config applications entry (loosely typed — written by pydoover)
type RawConfig = Record<string, unknown>;

export function parseConfig(raw: RawConfig): PumpConfig {
  const curve = Array.isArray(raw.pump_curve)
    ? (raw.pump_curve as CurvePoint[]).filter(
        (p) => typeof p?.flow_m3h === "number" && typeof p?.head_m === "number"
      )
    : [];
  curve.sort((a, b) => a.flow_m3h - b.flow_m3h);
  const [flowUnit, flowFactor] =
    FLOW_UNITS[String(raw.flow_display_units ?? "ml_per_day")] ?? FLOW_UNITS.ml_per_day;
  const [pressureUnit, pressureFactor] =
    PRESSURE_UNITS[String(raw.pressure_display_units ?? "metres_head")] ??
    PRESSURE_UNITS.metres_head;
  return {
    pumpName: typeof raw.pump_name === "string" ? raw.pump_name : "Pump",
    curve,
    referenceRpm:
      typeof raw.curve_reference_speed_rpm === "number"
        ? raw.curve_reference_speed_rpm
        : null,
    warningMarginM:
      typeof raw.npsh_warning_margin_m === "number" ? raw.npsh_warning_margin_m : 1.5,
    dangerMarginM:
      typeof raw.npsh_danger_margin_m === "number" ? raw.npsh_danger_margin_m : 0.5,
    bepFlowM3h: typeof raw.bep_flow_m3h === "number" ? raw.bep_flow_m3h : null,
    flowUnit,
    flowFactor,
    showGauges: raw.show_widget_gauges === true,
    suctionRange: [
      typeof raw.suction_range_low_bar === "number" ? raw.suction_range_low_bar : -1,
      typeof raw.suction_range_high_bar === "number" ? raw.suction_range_high_bar : 10,
    ],
    dischargeRange: [
      typeof raw.discharge_range_low_bar === "number" ? raw.discharge_range_low_bar : -1,
      typeof raw.discharge_range_high_bar === "number" ? raw.discharge_range_high_bar : 10,
    ],
    pressureUnit,
    pressureFactor,
  };
}

/** Affinity-scale the reference curve to a live speed: Q ∝ N, H ∝ N², NPSHr ∝ N². */
export function scaleCurve(curve: CurvePoint[], refRpm: number, liveRpm: number): CurvePoint[] {
  const n = liveRpm / refRpm;
  return curve.map((p) => ({
    flow_m3h: p.flow_m3h * n,
    head_m: p.head_m * n * n,
    npshr_m: p.npshr_m == null ? null : p.npshr_m * n * n,
  }));
}

/** Read a tag out of the tag_values aggregate — tolerant of nested
    ({app: {tag: v}}) and flat ("app.tag": v) shapes. */
export function tagValue(
  agg: Record<string, unknown> | undefined,
  appKey: string,
  tag: string
): number | null {
  if (!agg) return null;
  const nested = agg[appKey];
  if (nested && typeof nested === "object") {
    const v = (nested as Record<string, unknown>)[tag];
    if (typeof v === "number") return v;
  }
  const flat = agg[`${appKey}.${tag}`];
  return typeof flat === "number" ? flat : null;
}

export const STATE_LABELS: Record<string, string> = {
  not_running: "Stopped",
  starting: "Starting",
  ok: "Running",
  marginal: "Marginal",
  danger: "DANGER",
  sensor_fault: "Sensor fault",
  config_fault: "Config fault",
};

export const STATE_BADGE: Record<string, "secondary" | "success" | "warning" | "destructive" | "outline"> = {
  not_running: "secondary",
  starting: "outline",
  ok: "success",
  marginal: "warning",
  danger: "destructive",
  sensor_fault: "destructive",
  config_fault: "warning",
};
