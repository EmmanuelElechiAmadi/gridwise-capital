"use client";

import { AuthProvider, useAuth } from "@/lib/auth";
import { redirect } from "next/navigation";
import Link from "next/link";
import { useState, useEffect, useCallback } from "react";
import { LayoutDashboard, LineChart, BarChart3, Settings, LogOut, Wallet, TrendingUp, Activity, Shield, RefreshCw, BrainCircuit } from "lucide-react";
import { getStatus, getPerformance, getRecentTrades, getEquityCurve, startBot, stopBot, type BotStatus, type PerformanceMetrics, type Trade, type EquityPoint } from "@/lib/api";

// Real MT5 broker account id used for all logged-in demo users until
// per-user account provisioning is built (see accounts_store.json).
const DEFAULT_ACCOUNT_ID = process.env.NEXT_PUBLIC_DEFAULT_ACCOUNT_ID || undefined;

function DashboardContent() {
  const { user, isLoading, logout, tier, planLabel } = useAuth();

  const [status, setStatus] = useState<BotStatus | null>(null);
  const [performance, setPerformance] = useState<PerformanceMetrics | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [equityData, setEquityData] = useState<EquityPoint[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [apiLoading, setApiLoading] = useState(true);
  const [botActionLoading, setBotActionLoading] = useState(false);

  const accountId = DEFAULT_ACCOUNT_ID;

  const fetchData = useCallback(async () => {
    setError(null);
    try {
      const [statusRes, perfRes, tradesRes, equityRes] = await Promise.all([
        getStatus(accountId),
        getPerformance(accountId),
        getRecentTrades(accountId),
        getEquityCurve(accountId),
      ]);
      // getStatus returns { accounts: [...] } for aggregate or a single status object when account_id is given
      const botStatus = Array.isArray(statusRes.accounts) ? statusRes.accounts[0] ?? null : null;
      setStatus(botStatus);
      setPerformance(perfRes.status === "no_trades" ? null : perfRes);
      setTrades(tradesRes);
      setEquityData(equityRes);
    } catch (err) {
      console.warn("Dashboard API error (backend may be offline):", err);
      setError("Trading platform unreachable. Showing demo data.");
      // Fall back to empty/null so the UI renders placeholders
      setStatus(null);
      setPerformance(null);
      setTrades([]);
      setEquityData([]);
    } finally {
      setApiLoading(false);
    }
  }, [accountId]);

  const handleStart = async () => {
    setBotActionLoading(true);
    try {
      await startBot(accountId);
      await fetchData();
    } catch (err) {
      console.warn("Failed to start bot:", err);
    } finally {
      setBotActionLoading(false);
    }
  };

  const handleStop = async () => {
    setBotActionLoading(true);
    try {
      await stopBot(accountId);
      await fetchData();
    } catch (err) {
      console.warn("Failed to stop bot:", err);
    } finally {
      setBotActionLoading(false);
    }
  };

  useEffect(() => {
    if (user) {
      fetchData();
      const interval = setInterval(fetchData, 30_000); // poll every 30s
      return () => clearInterval(interval);
    }
  }, [user, fetchData]);

  if (isLoading) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg)" }}>
        <div style={{ width: 24, height: 24, border: "2px solid var(--gold)", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
      </div>
    );
  }

  if (!user) {
    redirect("/login");
  }

  const navItems = [
    { icon: LayoutDashboard, label: "Portfolio", href: "/dashboard", active: true },
    { icon: BrainCircuit, label: "Intelligence", href: "/intelligence", active: false },
    { icon: BarChart3, label: "Analytics", href: "/intelligence", active: false },
    { icon: Settings, label: "Settings", href: "/billing", active: false },
  ];

  // Compute stats from API data
  const portfolioValue = status?.equity ?? status?.balance ?? 0;
  const totalPnl = status?.total_pnl ?? status?.pnl ?? 0;
  const pnlPct = status?.pnl_pct ?? 0;
  const winRate = performance?.win_rate_pct ?? null;
  const numTrades = performance?.num_trades ?? status?.active_orders ?? 0;
  const sharpeRatio = performance?.sharpe_ratio ?? null;
  const regime = status?.regime ?? "unknown";
  const positionDir = status?.position_direction ?? "Neutral";
  const latestPrice = status?.latest_price;

  // Build monthly performance bars from equity curve data
  const monthlyData = equityData.length > 0
    ? equityData.slice(-12).map((pt, i, arr) => {
        if (i === 0) return 0;
        const prev = arr[i - 1]?.equity ?? 0;
        const curr = pt.equity ?? 0;
        return prev ? ((curr - prev) / prev) * 100 : 0;
      })
    : []; // fall back to empty array

  const maxAbs = monthlyData.length > 0 ? Math.max(...monthlyData.map(Math.abs)) : 1;

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "var(--bg)" }}>
      {/* Sidebar */}
      <div className="sidebar">
        <div style={{ padding: "24px 20px", borderBottom: "1px solid var(--border)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ width: 32, height: 32, borderRadius: 8, background: "linear-gradient(135deg, #e8c97a, #c9a84c)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <span style={{ color: "#000", fontWeight: 900, fontSize: 11 }}>SQ</span>
            </div>
            <div>
              <div style={{ fontWeight: 700, fontSize: 13, color: "var(--text)" }}>Seek Quant</div>
              <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.08em", textTransform: "uppercase" }}>Trader Portal</div>
            </div>
          </div>
        </div>

        <nav style={{ padding: "16px 12px", flex: 1 }}>
          {navItems.map((item) => (
            <Link key={item.label} href={item.href} className={`sidebar-link ${item.active ? "active" : ""}`} style={{ marginBottom: 4 }}>
              <item.icon size={16} />
              {item.label}
            </Link>
          ))}
        </nav>

        <div style={{ padding: "16px 12px", borderTop: "1px solid var(--border)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", marginBottom: 8 }}>
            <div style={{ width: 30, height: 30, borderRadius: "50%", background: "rgba(201,168,76,0.2)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: "var(--gold)" }}>{user.name.charAt(0)}</span>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{user.name}</div>
              <div style={{ fontSize: 10, color: "var(--text-muted)" }}>Trader</div>
            </div>
          </div>
          <button onClick={logout} className="sidebar-link" style={{ width: "100%", background: "none", border: "none", textAlign: "left" }}>
            <LogOut size={16} />
            Sign Out
          </button>
        </div>
      </div>

      {/* Main */}
      <div style={{ marginLeft: 240, flex: 1 }}>
        {/* Top bar */}
        <div style={{ height: 64, borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 32px", background: "var(--surface)", position: "sticky", top: 0, zIndex: 10 }}>
          <div>
            <h1 style={{ fontSize: 16, fontWeight: 700, color: "var(--text)" }}>Portfolio Overview</h1>
            <p style={{ fontSize: 11, color: "var(--text-muted)" }}>Welcome back, {user.name}</p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {regime !== "unknown" && (
              <span style={{ fontSize: 11, padding: "4px 10px", borderRadius: 100, background: "rgba(201,168,76,0.1)", color: "var(--gold)" }}>
                Regime: {regime}
              </span>
            )}
            {status && (
              <button
                onClick={status.paused === false ? handleStop : handleStart}
                disabled={botActionLoading}
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  padding: "6px 14px",
                  borderRadius: 8,
                  border: "1px solid var(--border)",
                  cursor: botActionLoading ? "not-allowed" : "pointer",
                  opacity: botActionLoading ? 0.6 : 1,
                  background: status.paused === false ? "rgba(239,68,68,0.1)" : "rgba(34,197,94,0.1)",
                  color: status.paused === false ? "#ef4444" : "#22c55e",
                }}
              >
                {botActionLoading ? "…" : status.paused === false ? "Stop Bot" : "Start Bot"}
              </button>
            )}
            <button onClick={fetchData} className="sidebar-link" style={{ background: "none", border: "none", padding: "6px", cursor: "pointer", display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "var(--text-muted)" }}>
              <RefreshCw size={12} />
              Refresh
            </button>
            <Link href="/" style={{ fontSize: 12, color: "var(--text-muted)", textDecoration: "none" }}>← Back to site</Link>
          </div>
        </div>

        {error && (
          <div style={{ margin: "16px 32px 0", padding: "10px 16px", borderRadius: 8, background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", fontSize: 12, color: "#ef4444" }}>
            {error}
          </div>
        )}

        <div style={{ padding: 32 }}>
          {/* Connection status indicator */}
          {!apiLoading && status && (
            <div style={{ marginBottom: 16, display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "var(--text-muted)" }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: status.broker_connected ? "#22c55e" : "var(--text-muted)" }} />
              {status.broker_connected ? "Broker connected" : "Broker not connected"}
              {positionDir !== "Neutral" && (
                <span style={{ marginLeft: 8 }}>
                  | Position: <strong style={{ color: positionDir === "Long" ? "#22c55e" : "#ef4444" }}>{positionDir}</strong>
                  {latestPrice && ` @ ${latestPrice}`}
                </span>
              )}
            </div>
          )}

          {/* Stats */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
            {[
              { icon: Wallet, label: "Portfolio Value", value: apiLoading ? "—" : `$${portfolioValue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, sub: pnlPct !== 0 ? `${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}% all time` : "No data" },
              { icon: TrendingUp, label: "Total P&L", value: apiLoading ? "—" : `${totalPnl >= 0 ? "+" : ""}$${totalPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, sub: `${numTrades} trades` },
              { icon: Activity, label: "Win Rate", value: apiLoading ? "—" : winRate !== null ? `${winRate.toFixed(1)}%` : "—", sub: winRate !== null ? `${numTrades} trades` : "No trades yet" },
              { icon: Shield, label: "Sharpe Ratio", value: apiLoading ? "—" : sharpeRatio !== null ? sharpeRatio.toFixed(2) : "—", sub: sharpeRatio !== null ? "From live trades" : "Insufficient data" },
            ].map((s) => (
              <div key={s.label} style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 14, padding: "20px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                  <span style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 500 }}>{s.label}</span>
                  <div style={{ width: 32, height: 32, borderRadius: 8, background: "rgba(201,168,76,0.1)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <s.icon size={14} color="var(--gold)" />
                  </div>
                </div>
                <div style={{ fontSize: 24, fontWeight: 800, color: "var(--text)", letterSpacing: "-0.02em" }}>{s.value}</div>
                <div style={{ fontSize: 11, color: "#22c55e", marginTop: 4 }}>{s.sub}</div>
              </div>
            ))}
          </div>

          {/* Chart */}
          <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 14, padding: "24px", marginBottom: 24 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, color: "var(--text)", marginBottom: 20 }}>
              {equityData.length > 0 ? "Equity Curve (Last 12 periods)" : "Monthly Performance"}
            </h3>
            {apiLoading ? (
              <div style={{ height: 140, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 12 }}>
                Loading chart data…
              </div>
            ) : monthlyData.length > 0 ? (
              <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 140 }}>
                {monthlyData.map((val, i) => {
                  const isPos = val >= 0;
                  const heightPct = (Math.abs(val) / maxAbs) * 100;
                  return (
                    <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
                      <span style={{ fontSize: 9, fontWeight: 600, color: isPos ? "#22c55e" : "#ef4444" }}>{isPos ? "+" : ""}{val.toFixed(1)}%</span>
                      <div style={{ width: "100%", height: `${heightPct}%`, background: isPos ? "rgba(34,197,94,0.2)" : "rgba(239,68,68,0.2)", borderTop: `2px solid ${isPos ? "rgba(34,197,94,0.7)" : "rgba(239,68,68,0.7)"}`, borderRadius: "3px 3px 0 0", minHeight: 4 }} />
                      <span style={{ fontSize: 9, color: "var(--text-muted)" }}>{["J","F","M","A","M","J","J","A","S","O","N","D"][i % 12]}</span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div style={{ height: 140, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 12 }}>
                No performance data available yet
              </div>
            )}
          </div>

          {/* Trades table */}
          <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 14, overflow: "hidden" }}>
            <div style={{ padding: "20px 24px", borderBottom: "1px solid var(--border)" }}>
              <h3 style={{ fontSize: 14, fontWeight: 700, color: "var(--text)" }}>Recent Trades</h3>
            </div>
            {apiLoading ? (
              <div style={{ padding: "40px 24px", textAlign: "center", color: "var(--text-muted)", fontSize: 12 }}>
                Loading trades…
              </div>
            ) : trades.length > 0 ? (
              <div style={{ overflowX: "auto" }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>Side</th>
                      <th style={{ textAlign: "right" }}>Price</th>
                      <th style={{ textAlign: "right" }}>Volume</th>
                      <th style={{ textAlign: "right" }}>P&L</th>
                      <th style={{ textAlign: "right" }}>Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t, i) => {
                      const side = t.side ?? "—";
                      const pnl = typeof t.pnl === "number" ? t.pnl : 0;
                      return (
                        <tr key={i}>
                          <td style={{ fontWeight: 600, color: "var(--text)" }}>{t.symbol ?? "—"}</td>
                          <td>
                            <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 100, background: side === "buy" || side === "Long" ? "rgba(34,197,94,0.1)" : "rgba(239,68,68,0.1)", color: side === "buy" || side === "Long" ? "#22c55e" : "#ef4444" }}>
                              {side}
                            </span>
                          </td>
                          <td style={{ textAlign: "right" }}>${typeof t.price === "number" ? t.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—"}</td>
                          <td style={{ textAlign: "right" }}>{typeof t.volume === "number" ? t.volume.toLocaleString() : "—"}</td>
                          <td style={{ textAlign: "right", fontWeight: 600, color: pnl >= 0 ? "#22c55e" : "#ef4444" }}>
                            {pnl >= 0 ? "+" : ""}${Math.abs(pnl).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </td>
                          <td style={{ textAlign: "right", fontSize: 11, color: "var(--text-muted)" }}>{t.timestamp ?? "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div style={{ padding: "40px 24px", textAlign: "center", color: "var(--text-muted)", fontSize: 12 }}>
                No trades yet
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <AuthProvider>
      <DashboardContent />
    </AuthProvider>
  );
}