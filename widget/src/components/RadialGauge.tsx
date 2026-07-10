/* Semicircular radial meter.

   Dataviz meter spec: the unfilled track is a lighter step of the same ramp
   as the fill so state reads across the whole bar; the value is a big
   proportional figure in ink (never the series colour); label sentence case
   below. The fill colour may carry severity (accent → warning → danger). */

export function RadialGauge({
  value,
  max,
  min = 0,
  unit,
  label,
  subtitle,
  fill,
  track,
  precision = 1,
  size = "md",
}: {
  value: number;
  max: number;
  min?: number;
  unit: string;
  label: string;
  subtitle?: string;
  fill: string;
  track: string;
  precision?: number;
  size?: "md" | "sm";
}) {
  const r = size === "sm" ? 42 : 60;
  const stroke = size === "sm" ? 9 : 13;
  const w = r * 2 + stroke;
  const h = r + stroke;
  const cx = w / 2;
  const cy = r + stroke / 2;
  const arcLen = Math.PI * r;
  const fraction = Math.max(0, Math.min((value - min) / (max - min), 1));
  const valueFont = size === "sm" ? 17 : 24;
  const unitFont = size === "sm" ? 10 : 11;

  const arc = `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`;

  return (
    <div className="flex flex-col items-center py-1">
      <svg
        width={w}
        height={h + 4}
        role="img"
        aria-label={`${label} ${value.toFixed(precision)} ${unit}`}
      >
        <path d={arc} fill="none" stroke={track} strokeWidth={stroke} strokeLinecap="round" />
        <path
          d={arc}
          fill="none"
          stroke={fill}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${arcLen} ${arcLen}`}
          strokeDashoffset={arcLen * (1 - fraction)}
          style={{ transition: "stroke-dashoffset 600ms ease, stroke 300ms ease" }}
        />
        <text
          x={cx}
          y={cy - (size === "sm" ? 9 : 13)}
          textAnchor="middle"
          className="fill-foreground"
          style={{ fontSize: valueFont, fontWeight: 600 }}
        >
          {value.toFixed(precision)}
        </text>
        <text
          x={cx}
          y={cy + 4}
          textAnchor="middle"
          className="fill-muted-foreground"
          style={{ fontSize: unitFont }}
        >
          {unit}
        </text>
      </svg>
      <span className="text-xs text-muted-foreground -mt-1 text-center">
        {label}
        {subtitle ? <span className="block opacity-80">{subtitle}</span> : null}
      </span>
    </div>
  );
}
