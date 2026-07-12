"use client";

import Link from "next/link";

const tickers = [
  { sym: "BTC/USD", val: "67,450", chg: "+2.4%" },
  { sym: "ETH/USD", val: "3,512", chg: "+1.8%" },
  { sym: "S&P 500", val: "5,234", chg: "+0.6%" },
  { sym: "GOLD", val: "2,318", chg: "+0.3%" },
  { sym: "EUR/USD", val: "1.0892", chg: "-0.2%" },
  { sym: "NASDAQ", val: "18,420", chg: "+1.1%" },
  { sym: "OIL/WTI", val: "78.40", chg: "+0.9%" },
  { sym: "GBP/USD", val: "1.2740", chg: "+0.4%" },
];

const stats = [
  { label: "Assets Under Management", value: "$28.4M", sub: "Across all strategies" },
  { label: "Annualised Return", value: "+34.2%", sub: "Net of all fees" },
  { label: "Sharpe Ratio", value: "2.41", sub: "Risk-adjusted performance" },
  { label: "Win Rate", value: "72.1%", sub: "847 closed trades" },
];

export default function HeroSection() {
  const doubled = [...tickers, ...tickers];

  return (
    <section className="relative min-h-screen flex flex-col overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Grid background */}
      <div className="absolute inset-0 hero-grid opacity-100 pointer-events-none" />

      {/* Radial glow */}
      <div
        className="absolute pointer-events-none"
        style={{
          top: "20%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: 700,
          height: 700,
          background: "radial-gradient(circle, rgba(201,168,76,0.08) 0%, transparent 70%)",
        }}
      />

      {/* ── NAVBAR ── */}
      <nav
        className="relative z-20 flex items-center justify-between px-8 py-5"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        {/* Logo */}
        <div className="flex items-center gap-3">
          <div
            className="flex items-center justify-center rounded-lg"
            style={{
              width: 36,
              height: 36,
              background: "linear-gradient(135deg, #e8c97a, #c9a84c)",
            }}
          >
            <span style={{ color: "#000", fontWeight: 900, fontSize: 13, letterSpacing: "-0.02em" }}>SQ</span>
          </div>
          <div>
            <span style={{ fontWeight: 700, fontSize: 15, letterSpacing: "-0.02em", color: "#f0f0f0" }}>
              Seek<span className="gold-gradient"> Quant</span>
            </span>
            <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.12em", textTransform: "uppercase", marginTop: -1 }}>
              Capital Management
            </div>
          </div>
        </div>

        {/* Nav links */}
        <div className="hidden md:flex items-center gap-8">
          {["Strategy", "Performance", "About", "Contact"].map((item) => (
            <a
              key={item}
              href={`#${item.toLowerCase()}`}
              style={{ fontSize: 13, color: "var(--text-muted)", fontWeight: 500, textDecoration: "none", transition: "color 0.15s" }}
              onMouseEnter={(e) => (e.currentTarget.style.color = "var(--text)")}
              onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text-muted)")}
            >
              {item}
            </a>
          ))}
        </div>

        {/* Auth */}
        <div className="flex items-center gap-3">
          <Link
            href="/login"
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: "var(--text-muted)",
              textDecoration: "none",
              padding: "8px 16px",
              borderRadius: 8,
              border: "1px solid var(--border)",
              transition: "all 0.15s",
            }}
          >
            Sign In
          </Link>
          <Link
            href="/signup"
            className="btn-gold"
            style={{ fontSize: 13, padding: "8px 20px", borderRadius: 8, textDecoration: "none", display: "inline-block" }}
          >
            Get Access
          </Link>
        </div>
      </nav>

      {/* ── TICKER ── */}
      <div
        className="relative z-10 overflow-hidden"
        style={{ borderBottom: "1px solid var(--border)", background: "rgba(255,255,255,0.01)", padding: "10px 0" }}
      >
        <div className="ticker-track">
          {doubled.map((t, i) => (
            <div
              key={i}
              className="flex items-center gap-2"
              style={{ padding: "0 32px", whiteSpace: "nowrap" }}
            >
              <span style={{ fontSize: 11, fontWeight: 700, color: "var(--text-muted)", letterSpacing: "0.06em" }}>{t.sym}</span>
              <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text)" }}>{t.val}</span>
              <span style={{ fontSize: 11, fontWeight: 600, color: t.chg.startsWith("+") ? "#22c55e" : "#ef4444" }}>{t.chg}</span>
              <span style={{ color: "var(--border-hover)", marginLeft: 16 }}>·</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── HERO CONTENT ── */}
      <div className="relative z-10 flex-1 flex flex-col items-center justify-center px-6 py-20 text-center">
        {/* Eyebrow */}
        <div
          className="animate-fade-up inline-flex items-center gap-2 mb-8"
          style={{
            background: "rgba(201,168,76,0.08)",
            border: "1px solid rgba(201,168,76,0.2)",
            borderRadius: 100,
            padding: "5px 14px",
          }}
        >
          <span
            className="animate-pulse-slow"
            style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--gold)", display: "inline-block" }}
          />
          <span style={{ fontSize: 11, fontWeight: 600, color: "var(--gold)", letterSpacing: "0.1em", textTransform: "uppercase" }}>
            Quantitative Alpha Generation
          </span>
        </div>

        {/* Headline */}
        <h1
          className="animate-fade-up-delay-1"
          style={{
            fontSize: "clamp(40px, 7vw, 80px)",
            fontWeight: 900,
            lineHeight: 1.05,
            letterSpacing: "-0.03em",
            maxWidth: 900,
            color: "#f0f0f0",
          }}
        >
          Where{" "}
          <span className="gold-gradient">Data</span>
          {" "}Meets<br />
          <span className="gold-gradient">Precision</span>
          {" "}Trading
        </h1>

        {/* Subheadline */}
        <p
          className="animate-fade-up-delay-2"
          style={{
            marginTop: 24,
            fontSize: 17,
            color: "var(--text-muted)",
            maxWidth: 560,
            lineHeight: 1.7,
            fontWeight: 400,
          }}
        >
          Seek Quant deploys proprietary machine learning models and systematic
          quantitative strategies to generate consistent, risk-adjusted alpha
          across global markets.
        </p>

        {/* CTAs */}
        <div className="animate-fade-up-delay-3 flex flex-col sm:flex-row gap-3 mt-10">
          <Link
            href="/signup"
            className="btn-gold"
            style={{ padding: "14px 32px", borderRadius: 10, fontSize: 14, textDecoration: "none", display: "inline-block" }}
          >
            Request Fund Access →
          </Link>
          <a
            href="#strategy"
            className="btn-outline"
            style={{ padding: "14px 32px", borderRadius: 10, fontSize: 14, textDecoration: "none", display: "inline-block" }}
          >
            View Strategy
          </a>
        </div>

        {/* Stats row */}
        <div
          className="animate-fade-up-delay-4"
          style={{
            marginTop: 64,
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 1,
            maxWidth: 800,
            width: "100%",
            background: "var(--border)",
            borderRadius: 16,
            overflow: "hidden",
            border: "1px solid var(--border)",
          }}
        >
          {stats.map((s, i) => (
            <div
              key={i}
              style={{
                background: "var(--surface)",
                padding: "24px 20px",
                textAlign: "center",
              }}
            >
              <div
                className="gold-gradient"
                style={{ fontSize: 28, fontWeight: 800, letterSpacing: "-0.02em", lineHeight: 1 }}
              >
                {s.value}
              </div>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text)", marginTop: 6, letterSpacing: "0.02em" }}>
                {s.label}
              </div>
              <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 3 }}>{s.sub}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Bottom fade */}
      <div
        className="absolute bottom-0 left-0 right-0 pointer-events-none"
        style={{ height: 120, background: "linear-gradient(to top, var(--bg), transparent)" }}
      />
    </section>
  );
}
