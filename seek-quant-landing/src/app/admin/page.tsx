"use client";

import { AuthProvider, useAuth } from "@/lib/auth";
import { redirect } from "next/navigation";
import Link from "next/link";
import { useState, useEffect, useCallback } from "react";
import { LayoutDashboard, Users, BarChart3, Settings, LogOut, Search, DollarSign, TrendingUp, Activity, Target, RefreshCw, Play, Square } from "lucide-react";
import { getStatus, getPerformance, getAccounts, startBot, stopBot, type BotStatus, type Account, type PerformanceMetrics } from "@/lib/api";

function AdminContent() {
  const { user, isLoading, isAdmin, logout } = useAuth();

  const [accounts, setAccounts] = useState<Account[]>([]);
  const [statusList, setStatusList] = useState<BotStatus[]>([]);
  const [performances, setPerformances] = useState<Record<string, PerformanceMetrics>>({});
  const [error, setError] = useState<string | null>(null);
  const [apiLoading, setApiLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const fetchAllData = useCallback(async () => {
    setError(null);
    try {
      const [acctsRes, statusRes] = await Promise.all([
        getAccounts(),
        getStatus(),
      ]);
      setAccounts(acctsRes.accounts);
      setStatusList(statusRes.accounts);

      // Fetch per-account performance
      const perfMap: Record<string, PerformanceMetrics> = {};
      await Promise.all(
        acctsRes.accounts.map(async (a) => {
          try {
            const p = await getPerformance(a.id);
            perfMap[a.id] = p;
          } catch {
            // skip accounts that have no trades yet
          }
        })
      );
      setPerformances(perfMap);
    } catch (err) {
      console.warn("Admin API error (backend may be offline):", err);
      setError("Trading platform unreachable. Showing empty state.");
      setAccounts([]);
      setStatusList([]);
    } finally {
      setApiLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user) {
      fetchAllData();
      const interval = setInterval(fetchAllData, 30_000);
      return () => clearInterval(interval);
    }
  }, [user, fetchAllData]);

  const handleStartBot = async (accountId?: string) => {
    setActionLoading(accountId ?? "__all__");
    try {
      await startBot(accountId);
      await fetchAllData();
    } catch (err) {
      console.error("Failed to start bot:", err);
    } finally {
      setActionLoading(null);
    }
  };

  const handleStopBot = async (accountId?: string) => {
    setActionLoading(accountId ?? "__all__");
    try {
      await stopBot(accountId);
      await fetchAllData();
    } catch (err) {
      console.error("Failed to stop bot:", err);
    } finally {
      setActionLoading(null);
    }
  };

  if (isLoading) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg)" }}>
        <div style={{ width: 24, height: 24, border: "2px solid var(--gold)", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
      </div>
    );
  }

  if (!user || !isAdmin) {
    redirect("/login");
  }

  // Aggregate stats from live account data
  const totalAum = accounts.reduce((s, a) => s + a.balance, 0);
  const tradersWithPerf = accounts.filter((a) => performances[a.id]);
  const avgWinRate = tradersWithPerf.length > 0
    ? tradersWithPerf.reduce((s, a) => s + (performances[a.id]?.win_rate_pct ?? 0), 0) / tradersWithPerf.length
    : 0;
  const avgSharpe = tradersWithPerf.length > 0
    ? tradersWithPerf.reduce((s, a) => s + (performances[a.id]?.sharpe_ratio ?? 0), 0) / tradersWithPerf.length
    : 0;
  const totalPnl = accounts.reduce((s, a) => s + (a.total_pnl ?? 0), 0);

  // Merge account data with status and performance
  const traderRows = accounts
    .map((acct) => {
      const botStatus = statusList.find((s) => s.account_id === acct.id);
      const perf = performances[acct.id];
      return {
        id: acct.id,
        label: acct.label,
        balance: acct.balance,
        totalPnl: acct.total_pnl ?? 0,
        winRate: perf?.win_rate_pct ?? 0,
        sharpeRatio: perf?.sharpe_ratio ?? 0,
        numTrades: perf?.num_trades ?? 0,
        aum: acct.balance,
        status: botStatus?.paused ? "paused" : acct.enabled ? "active" : "inactive",
        paused: botStatus?.paused ?? false,
        brokerConnected: botStatus?.broker_connected ?? acct.connection_status === "connected",
        regime: botStatus?.regime ?? acct.regime ?? "unknown",
      };
    })
    .filter((row) => {
      if (!searchQuery) return true;
      const q = searchQuery.toLowerCase();
      return row.label.toLowerCase().includes(q) || row.id.toLowerCase().includes(q);
    });

  const navItems = [
    { icon: LayoutDashboard, label: "Dashboard", href: "/admin", active: true },
    { icon: Users, label: "Traders", href: "/admin", active: false },
    { icon: BarChart3, label: "Analytics", href: "/admin", active: false },
    { icon: Settings, label: "Settings", href: "/admin", active: false },
  ];

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
              <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.08em", textTransform: "uppercase" }}>Admin Panel</div>
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
              <div style={{ fontSize: 10, color: "var(--text-muted)" }}>Administrator</div>
            </div>
          </div>
          <button onClick={logout} className="sidebar-link" style={{ width: "100%", background: "none", border: "none", textAlign: "left" }}>
            <LogOut size={16} />
            Sign Out
          </button>
        </div>
      </div>

      {/* Main content */}
      <div style={{ marginLeft: 240, flex: 1, display: "flex", flexDirection: "column" }}>
        {/* Top bar */}
        <div style={{ height: 64, borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 32px", background: "var(--surface)", position: "sticky", top: 0, zIndex: 10 }}>
          <div>
            <h1 style={{ fontSize: 16, fontWeight: 700, color: "var(--text)" }}>Admin Dashboard</h1>
            <p style={{ fontSize: 11, color: "var(--text-muted)" }}>Fund overview & account management</p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ position: "relative" }}>
              <Search size={14} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--text-muted)" }} />
              <input
                type="text"
                placeholder="Search accounts..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{ paddingLeft: 36, paddingRight: 16, paddingTop: 8, paddingBottom: 8, background: "rgba(255,255,255,0.03)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 13, color: "var(--text)", outline: "none", width: 200 }}
              />
            </div>
            <button onClick={fetchAllData} className="sidebar-link" style={{ background: "none", border: "none", padding: "6px", cursor: "pointer", display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "var(--text-muted)" }}>
              <RefreshCw size={12} />
              Refresh
            </button>
          </div>
        </div>

        {error && (
          <div style={{ margin: "16px 32px 0", padding: "10px 16px", borderRadius: 8, background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", fontSize: 12, color: "#ef4444" }}>
            {error}
          </div>
        )}

        <div style={{ padding: 32, flex: 1 }}>
          {/* Stats */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
            {[
              { icon: DollarSign, label: "Total AUM", value: apiLoading ? "—" : `$${(totalAum / 1e6).toFixed(1)}M`, sub: `${accounts.length} accounts` },
              { icon: Activity, label: "Avg Win Rate", value: apiLoading ? "—" : `${avgWinRate.toFixed(1)}%`, sub: `${tradersWithPerf.length} traders with data` },
              { icon: TrendingUp, label: "Avg Sharpe", value: apiLoading ? "—" : avgSharpe.toFixed(2), sub: avgSharpe >= 1.5 ? "Above 1.5 target" : "Below 1.5 target" },
              { icon: Target, label: "Fund P&L", value: apiLoading ? "—" : `${totalPnl >= 0 ? "+" : ""}$${(totalPnl / 1e6).toFixed(1)}M`, sub: `${accounts.filter((a) => a.total_pnl > 0).length} profitable accounts` },
            ].map((s) => (
              <div key={s.label} style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 14, padding: "20px 20px" }}>
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

          {/* Accounts table */}
          <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 14, overflow: "hidden" }}>
            <div style={{ padding: "20px 24px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <h3 style={{ fontSize: 14, fontWeight: 700, color: "var(--text)" }}>Accounts</h3>
                <p style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                  {apiLoading ? "Loading..." : `${traderRows.length} account${traderRows.length !== 1 ? "s" : ""}`}
                </p>
              </div>
              {traderRows.length > 0 && (
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    onClick={() => handleStartBot()}
                    disabled={actionLoading === "__all__"}
                    className="btn-gold"
                    style={{ padding: "6px 14px", borderRadius: 8, fontSize: 11, display: "flex", alignItems: "center", gap: 6, opacity: actionLoading === "__all__" ? 0.5 : 1 }}
                  >
                    <Play size={12} />
                    Start All
                  </button>
                  <button
                    onClick={() => handleStopBot()}
                    disabled={actionLoading === "__all__"}
                    className="sidebar-link"
                    style={{ background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)", padding: "6px 14px", borderRadius: 8, fontSize: 11, cursor: "pointer", display: "flex", alignItems: "center", gap: 6, color: "#ef4444", opacity: actionLoading === "__all__" ? 0.5 : 1 }}
                  >
                    <Square size={12} />
                    Stop All
                  </button>
                </div>
              )}
            </div>
            {apiLoading ? (
              <div style={{ padding: "60px 24px", textAlign: "center", color: "var(--text-muted)", fontSize: 12 }}>
                Loading accounts…
              </div>
            ) : traderRows.length > 0 ? (
              <div style={{ overflowX: "auto" }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Account</th>
                      <th>Status</th>
                      <th>Broker</th>
                      <th>Regime</th>
                      <th style={{ textAlign: "right" }}>Balance</th>
                      <th style={{ textAlign: "right" }}>Total P&L</th>
                      <th style={{ textAlign: "right" }}>Win Rate</th>
                      <th style={{ textAlign: "right" }}>Sharpe</th>
                      <th style={{ textAlign: "right" }}>Trades</th>
                      <th style={{ textAlign: "center" }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {traderRows.map((row) => (
                      <tr key={row.id}>
                        <td>
                          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                            <div style={{ width: 32, height: 32, borderRadius: "50%", background: "rgba(201,168,76,0.15)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                              <span style={{ fontSize: 11, fontWeight: 700, color: "var(--gold)" }}>{row.label.split(" ").map((n: string) => n[0]).join("").slice(0, 2)}</span>
                            </div>
                            <div>
                              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>{row.label}</div>
                              <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{row.id}</div>
                            </div>
                          </div>
                        </td>
                        <td>
                          <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 10px", borderRadius: 100,
                            background: row.status === "active" ? "rgba(34,197,94,0.1)" : row.status === "paused" ? "rgba(234,179,8,0.1)" : "rgba(107,107,128,0.1)",
                            color: row.status === "active" ? "#22c55e" : row.status === "paused" ? "#eab308" : "var(--text-muted)" }}>
                            {row.status}
                          </span>
                        </td>
                        <td>
                          <span style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 6 }}>
                            <span style={{ width: 6, height: 6, borderRadius: "50%", background: row.brokerConnected ? "#22c55e" : "var(--text-muted)" }} />
                            {row.brokerConnected ? "Connected" : "Disconnected"}
                          </span>
                        </td>
                        <td style={{ fontSize: 11, color: "var(--text-muted)" }}>{row.regime}</td>
                        <td style={{ textAlign: "right", fontWeight: 600 }}>${row.balance.toLocaleString()}</td>
                        <td style={{ textAlign: "right", fontWeight: 600, color: row.totalPnl >= 0 ? "#22c55e" : "#ef4444" }}>
                          {row.totalPnl >= 0 ? "+" : ""}${Math.abs(row.totalPnl).toLocaleString()}
                        </td>
                        <td style={{ textAlign: "right" }}>{row.winRate > 0 ? `${row.winRate.toFixed(1)}%` : "—"}</td>
                        <td style={{ textAlign: "right" }}>{row.sharpeRatio > 0 ? row.sharpeRatio.toFixed(2) : "—"}</td>
                        <td style={{ textAlign: "right" }}>{row.numTrades}</td>
                        <td style={{ textAlign: "center" }}>
                          <div style={{ display: "flex", gap: 4, justifyContent: "center" }}>
                            <button
                              onClick={() => handleStartBot(row.id)}
                              disabled={actionLoading === row.id || !row.paused}
                              title="Start bot"
                              style={{ padding: "4px 8px", borderRadius: 6, background: !row.paused ? "rgba(34,197,94,0.1)" : "rgba(34,197,94,0.05)", border: "none", cursor: !row.paused ? "pointer" : "not-allowed", opacity: !row.paused ? 0.5 : 1 }}
                            >
                              <Play size={12} color={!row.paused ? "var(--text-muted)" : "#22c55e"} />
                            </button>
                            <button
                              onClick={() => handleStopBot(row.id)}
                              disabled={actionLoading === row.id || row.paused}
                              title="Stop bot"
                              style={{ padding: "4px 8px", borderRadius: 6, background: row.paused ? "rgba(239,68,68,0.1)" : "rgba(239,68,68,0.05)", border: "none", cursor: row.paused ? "pointer" : "not-allowed", opacity: row.paused ? 0.5 : 1 }}
                            >
                              <Square size={12} color={row.paused ? "var(--text-muted)" : "#ef4444"} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div style={{ padding: "60px 24px", textAlign: "center", color: "var(--text-muted)", fontSize: 12 }}>
                No accounts found. Connect a brokerage account to get started.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function AdminPage() {
  return (
    <AuthProvider>
      <AdminContent />
    </AuthProvider>
  );
}