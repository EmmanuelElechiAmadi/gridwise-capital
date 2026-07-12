import { TrendingUp, Activity, Target, DollarSign } from "lucide-react";

const metrics = [
  { icon: TrendingUp, value: "+34.2%", label: "YTD Return", sub: "Net of fees", color: "#22c55e" },
  { icon: Activity, value: "2.41", label: "Sharpe Ratio", sub: "Risk-adjusted", color: "var(--gold)" },
  { icon: Target, value: "72.1%", label: "Win Rate", sub: "847 trades", color: "var(--gold)" },
  { icon: DollarSign, value: "$28.4M", label: "AUM", sub: "Under management", color: "var(--gold)" },
];

const monthlyData = [2.1, -0.5, 1.8, 3.2, -1.1, 2.4, 0.9, 1.5, -0.3, 2.8, 3.5, 1.9];
const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export default function PerformanceSection() {
  const maxAbs = Math.max(...monthlyData.map(Math.abs));

  return (
    <section id="performance" style={{ padding: "96px 0", background: "var(--bg)" }}>
      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "0 32px" }}>
        {/* Header */}
        <div style={{ textAlign: "center", marginBottom: 64 }}>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              background: "rgba(201,168,76,0.08)",
              border: "1px solid rgba(201,168,76,0.2)",
              borderRadius: 100,
              padding: "4px 14px",
              marginBottom: 20,
            }}
          >
            <span style={{ fontSize: 10, fontWeight: 700, color: "var(--gold)", letterSpacing: "0.12em", textTransform: "uppercase" }}>
              Track Record
            </span>
          </div>
          <h2
            style={{
              fontSize: "clamp(28px, 4vw, 44px)",
              fontWeight: 800,
              letterSpacing: "-0.02em",
              color: "var(--text)",
              lineHeight: 1.1,
            }}
          >
            Consistent{" "}
            <span
              style={{
                background: "linear-gradient(135deg, #e8c97a, #c9a84c)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}
            >
              Performance
            </span>
          </h2>
          <p style={{ marginTop: 16, fontSize: 16, color: "var(--text-muted)", maxWidth: 480, margin: "16px auto 0" }}>
            Consistent performance across market cycles through rigorous risk management.
          </p>
        </div>

        {/* Metrics */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 2, background: "var(--border)", borderRadius: 16, overflow: "hidden", marginBottom: 24 }}>
          {metrics.map((m, i) => (
            <div key={i} style={{ background: "var(--surface)", padding: "32px 24px", textAlign: "center" }}>
              <div style={{ width: 40, height: 40, borderRadius: 10, background: "rgba(201,168,76,0.1)", border: "1px solid rgba(201,168,76,0.2)", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px" }}>
                <m.icon size={18} color={m.color} />
              </div>
              <div style={{ fontSize: 32, fontWeight: 800, letterSpacing: "-0.02em", color: m.color, lineHeight: 1 }}>{m.value}</div>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text)", marginTop: 8 }}>{m.label}</div>
              <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>{m.sub}</div>
            </div>
          ))}
        </div>

        {/* Chart */}
        <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 16, padding: "32px 28px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 28 }}>
            <div>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: "var(--text)" }}>Monthly Returns</h3>
              <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>2024 performance by month</p>
            </div>
            <div style={{ display: "flex", gap: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{ width: 8, height: 8, borderRadius: 2, background: "rgba(34,197,94,0.6)" }} />
                <span style={{ fontSize: 11, color: "var(--text-muted)" }}>Positive</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{ width: 8, height: 8, borderRadius: 2, background: "rgba(239,68,68,0.6)" }} />
                <span style={{ fontSize: 11, color: "var(--text-muted)" }}>Negative</span>
              </div>
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 160 }}>
            {monthlyData.map((val, i) => {
              const isPos = val >= 0;
              const heightPct = (Math.abs(val) / maxAbs) * 100;
              return (
                <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 10, fontWeight: 600, color: isPos ? "#22c55e" : "#ef4444" }}>
                    {isPos ? "+" : ""}{val}%
                  </span>
                  <div
                    style={{
                      width: "100%",
                      height: `${heightPct}%`,
                      background: isPos ? "rgba(34,197,94,0.2)" : "rgba(239,68,68,0.2)",
                      borderTop: `2px solid ${isPos ? "rgba(34,197,94,0.7)" : "rgba(239,68,68,0.7)"}`,
                      borderRadius: "3px 3px 0 0",
                      minHeight: 4,
                    }}
                  />
                  <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{months[i]}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
