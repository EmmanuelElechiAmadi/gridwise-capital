import { Brain, BarChart3, Globe, Lock } from "lucide-react";

const features = [
  {
    icon: Brain,
    title: "Machine Learning Models",
    description: "Proprietary ML algorithms analyze market patterns across multiple timeframes to identify high-probability trading opportunities with superior predictive accuracy.",
  },
  {
    icon: BarChart3,
    title: "Risk-Managed Execution",
    description: "Advanced position sizing and dynamic risk management protocols protect capital while maximizing risk-adjusted returns across all market conditions.",
  },
  {
    icon: Globe,
    title: "Global Market Coverage",
    description: "Strategies span equities, FX, commodities, and fixed income across major global exchanges, ensuring diversified alpha generation with low correlation.",
  },
  {
    icon: Lock,
    title: "Institutional-Grade Security",
    description: "Enterprise-level infrastructure with multi-factor authentication, encrypted data channels, and segregated assets meeting the highest security standards.",
  },
];

export default function StrategySection() {
  return (
    <section id="strategy" style={{ padding: "96px 0", background: "var(--bg)", position: "relative" }}>
      {/* Subtle divider top */}
      <div style={{ height: 1, background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent)", marginBottom: 96 }} />

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
              Our Methodology
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
            A Systematic{" "}
            <span
              style={{
                background: "linear-gradient(135deg, #e8c97a, #c9a84c)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
              }}
            >
              Approach
            </span>
          </h2>
          <p style={{ marginTop: 16, fontSize: 16, color: "var(--text-muted)", maxWidth: 480, margin: "16px auto 0" }}>
            Every decision is driven by data. Our systematic approach removes emotion and bias from trading.
          </p>
        </div>

        {/* Grid */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(2, 1fr)",
            gap: 2,
            background: "var(--border)",
            borderRadius: 20,
            overflow: "hidden",
            border: "1px solid var(--border)",
          }}
        >
          {features.map((feature, i) => (
            <div
              key={i}
              style={{
                background: "var(--surface)",
                padding: "40px 36px",
                transition: "background 0.2s",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--surface-2)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "var(--surface)")}
            >
              <div
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: 12,
                  background: "rgba(201,168,76,0.1)",
                  border: "1px solid rgba(201,168,76,0.2)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  marginBottom: 20,
                }}
              >
                <feature.icon size={20} color="var(--gold)" />
              </div>
              <h3 style={{ fontSize: 17, fontWeight: 700, color: "var(--text)", marginBottom: 10, letterSpacing: "-0.01em" }}>
                {feature.title}
              </h3>
              <p style={{ fontSize: 14, color: "var(--text-muted)", lineHeight: 1.7 }}>
                {feature.description}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
