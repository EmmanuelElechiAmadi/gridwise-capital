"use client";

/**
 * Lightweight, dependency-free SVG chart components used across the
 * Intelligence page.  All charts are fully typed and theme-aware.
 */

import { useMemo } from "react";

/* ── helpers ──────────────────────────────────────────────────────── */

function buildPath(values: number[], w: number, h: number, pad: number): string {
  if (values.length < 2) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const stepX = (w - pad * 2) / (values.length - 1);
  return values
    .map((v, i) => {
      const x = pad + i * stepX;
      const y = pad + (h - pad * 2) * (1 - (v - min) / span);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

function niceTicks(min: number, max: number, count = 4): number[] {
  const span = max - min || 1;
  const step = span / count;
  return Array.from({ length: count + 1 }, (_, i) => min + step * i);
}

function fmt(v: number, digits = 2): string {
  if (!isFinite(v)) return "0";
  return v.toLocaleString(undefined, { maximumFractionDigits: digits });
}

/* ── LineChart ────────────────────────────────────────────────────── */

export function LineChart({
  values,
  labels,
  height = 180,
  color = "var(--gold)",
  area = true,
  unit = "",
  digits = 2,
}: {
  values: number[];
  labels?: string[];
  height?: number;
  color?: string;
  area?: boolean;
  unit?: string;
  digits?: number;
}) {
  const W = 640;
  const H = height;
  const PAD = 24;
  const path = useMemo(() => buildPath(values, W, H, PAD), [values, W, H]);
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 0;
  const ticks = useMemo(() => niceTicks(min, max), [min, max]);
  const mid = Math.floor(values.length / 2);

  if (values.length === 0) {
    return <div style={{ height, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 12 }}>No data</div>;
  }

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" style={{ display: "block" }}>
        {ticks.map((t, i) => {
          const y = PAD + (H - PAD * 2) * (1 - (t - min) / (max - min || 1));
          return (
            <g key={i}>
              <line x1={PAD} x2={W - PAD} y1={y} y2={y} stroke="rgba(255,255,255,0.05)" strokeWidth={1} />
              <text x={PAD - 6} y={y + 3} textAnchor="end" fill="var(--text-dim)" fontSize={8}>
                {fmt(t, digits)}
              </text>
            </g>
          );
        })}
        {area && path && <path d={`${path} L${W - PAD},${H - PAD} L${PAD},${H - PAD} Z`} fill={color} opacity={0.08} />}
        {path && <path d={path} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" />}
      </svg>
      {labels && labels.length > 0 && (
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "var(--text-dim)", marginTop: 6 }}>
          <span>{labels[0]}</span>
          <span>{labels[Math.min(labels.length - 1, mid)]}</span>
          <span>{labels[labels.length - 1]}</span>
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "var(--text-dim)", marginTop: 2 }}>
        <span>min {fmt(min, digits)}{unit}</span>
        <span>max {fmt(max, digits)}{unit}</span>
      </div>
    </div>
  );
}

/* ── BarChart ─────────────────────────────────────────────────────── */

export function BarChart({
  values,
  labels,
  height = 180,
  positiveColor = "rgba(34,197,94,0.7)",
  negativeColor = "rgba(239,68,68,0.7)",
  unit = "%",
  showValues = true,
}: {
  values: number[];
  labels?: string[];
  height?: number;
  positiveColor?: string;
  negativeColor?: string;
  unit?: string;
  showValues?: boolean;
}) {
  const maxAbs = Math.max(...values.map(Math.abs), 0.0001);
  const barH = Math.max(20, height - 46);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 6, height: barH + 20 }}>
        {values.map((v, i) => {
          const h = Math.max((Math.abs(v) / maxAbs) * barH, v === 0 ? 2 : 6);
          const isPos = v >= 0;
          return (
            <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end", height: barH + 20 }}>
              {showValues && (
                <span style={{ fontSize: 9, fontWeight: 600, color: isPos ? "#22c55e" : "#ef4444", marginBottom: 4 }}>
                  {v > 0 ? "+" : ""}{fmt(v, 2)}{unit}
                </span>
              )}
              <div
                style={{
                  width: "100%",
                  height: h,
                  background: isPos ? positiveColor : negativeColor,
                  borderTop: `2px solid ${isPos ? "#22c55e" : "#ef4444"}`,
                  borderRadius: "3px 3px 0 0",
                }}
              />
            </div>
          );
        })}
      </div>
      {labels && labels.length > 0 && (
        <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
          {labels.map((l, i) => (
            <span key={i} style={{ flex: 1, textAlign: "center", fontSize: 8, color: "var(--text-dim)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {l}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── DonutChart ───────────────────────────────────────────────────── */

export function DonutChart({
  values,
  labels,
  colors,
  size = 140,
}: {
  values: number[];
  labels: string[];
  colors: string[];
  size?: number;
}) {
  const total = values.reduce((s, v) => s + v, 0) || 1;
  let acc = 0;
  const radius = size / 2 - 8;
  const circ = 2 * Math.PI * radius;

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth={14} />
        {values.map((v, i) => {
          const frac = v / total;
          const offset = acc * circ;
          acc += frac;
          return (
            <circle
              key={i}
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={colors[i % colors.length]}
              strokeWidth={14}
              strokeDasharray={`${frac * circ} ${circ}`}
              strokeDashoffset={-offset}
              transform={`rotate(-90 ${size / 2} ${size / 2})`}
              strokeLinecap="butt"
            />
          );
        })}
        <text x={size / 2} y={size / 2 - 2} textAnchor="middle" fill="var(--text)" fontSize={18} fontWeight={800}>
          {fmt(total, 0)}
        </text>
        <text x={size / 2} y={size / 2 + 14} textAnchor="middle" fill="var(--text-muted)" fontSize={9}>
          total
        </text>
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {labels.map((l, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ width: 10, height: 10, borderRadius: 3, background: colors[i % colors.length] }} />
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{l}</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--text)" }}>{fmt(values[i], 0)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}


/* ── HeatmapGrid ──────────────────────────────────────────────────── */

export function HeatmapGrid({
  rows,
  xKey,
  yKey,
  valueKey,
  xLabel,
  yLabel,
  fmtValue,
}: {
  rows: Array<Record<string, number>>;
  xKey: string;
  yKey: string;
  valueKey: string;
  xLabel?: (v: number) => string;
  yLabel?: (v: number) => string;
  fmtValue?: (v: number) => string;
}) {
  if (rows.length === 0) return <div style={{ color: "var(--text-muted)", fontSize: 12, padding: "20px 0", textAlign: "center" }}>No optimization data</div>;

  const xs = Array.from(new Set(rows.map((r) => r[xKey]))).sort((a, b) => a - b);
  const ys = Array.from(new Set(rows.map((r) => r[yKey]))).sort((a, b) => a - b);
  const vals = rows.map((r) => r[valueKey]);
  const minV = Math.min(...vals, 0);
  const maxV = Math.max(...vals, 0.0001);

  const cellColor = (v: number) => {
    const t = (v - minV) / (maxV - minV || 1);
    if (v >= 0) return `rgba(34,197,94,${0.15 + t * 0.5})`;
    return `rgba(239,68,68,${0.15 + (1 - t) * 0.5})`;
  };

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: `auto repeat(${xs.length}, 1fr)`, gap: 4, alignItems: "center" }}>
        <div />
        {xs.map((x) => (
          <div key={x} style={{ textAlign: "center", fontSize: 9, color: "var(--text-muted)" }}>
            {xLabel ? xLabel(x) : x}
          </div>
        ))}
        {ys.map((y) => (
          <div key={y} style={{ display: "contents" }}>
            <div style={{ fontSize: 9, color: "var(--text-muted)", textAlign: "right", paddingRight: 6, whiteSpace: "nowrap" }}>
              {yLabel ? yLabel(y) : y}
            </div>
            {xs.map((x) => {
              const row = rows.find((r) => r[xKey] === x && r[yKey] === y);
              const v = row ? row[valueKey] : 0;
              return (
                <div
                  key={`${x}-${y}`}
                  style={{
                    background: cellColor(v),
                    borderRadius: 6,
                    padding: "10px 4px",
                    textAlign: "center",
                    fontSize: 10,
                    fontWeight: 700,
                    color: "var(--text)",
                    border: "1px solid rgba(255,255,255,0.04)",
                  }}
                  title={`${xLabel ? xLabel(x) : x} × ${yLabel ? yLabel(y) : y}: ${fmtValue ? fmtValue(v) : v}`}
                >
                  {fmtValue ? fmtValue(v) : fmt(v, 2)}
                </div>
              );
            })}
          </div>
        ))}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 12, fontSize: 9, color: "var(--text-muted)" }}>
        <span>Worse</span>
        <div style={{ flex: 1, height: 8, borderRadius: 4, background: "linear-gradient(90deg, rgba(239,68,68,0.6), rgba(255,255,255,0.05), rgba(34,197,94,0.6))" }} />
        <span>Better</span>
      </div>
    </div>
  );
}

/* ── MetricTile (KPI card) ────────────────────────────────────────── */

export function MetricTile({
  label,
  value,
  sub,
  tone = "gold",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "gold" | "green" | "red" | "muted";
}) {
  const colors: Record<string, string> = {
    gold: "var(--gold)",
    green: "#22c55e",
    red: "#ef4444",
    muted: "var(--text)",
  };
  return (
    <div className="intel-card" style={{ padding: "20px 22px" }}>
      <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.1em", fontWeight: 700 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 800, color: colors[tone], marginTop: 8, letterSpacing: "-0.02em", lineHeight: 1.1 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>{sub}</div>}
    </div>
  );
}

