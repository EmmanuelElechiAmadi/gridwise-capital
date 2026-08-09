"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  BrainCircuit,
  Database,
  LayoutDashboard,
  LineChart as LineIcon,
  Lock,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TrendingUp as TrendingUpIcon,
  Users,
} from "lucide-react";
import { AuthProvider, useAuth } from "@/lib/auth";
import { hasFeature } from "@/types";
import {
  getAnalyticsOverview,
  getEquity,
  getLiveTrades,
  getML,
  getOptimization,
  getWalkforward,
  type AnalyticsOverview,
  type FillRow,
  type MLModel,
  type OptRow,
  type PricePoint,
  type TradeRow,
  type WalkforwardWindow,
} from "@/lib/analytics";
import { BarChart, DonutChart, HeatmapGrid, LineChart, MetricTile } from "@/components/charts";
import UpgradePrompt from "@/components/UpgradePrompt";

/* ── small helpers ────────────────────────────────────────────────── */

function pct(v: number | undefined, digits = 2): string {
  if (v === undefined || v === null || !isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

function money(v: number | undefined, digits = 2): string {
  if (v === undefined || v === null || !isFinite(v)) return "—";
  return `${v >= 0 ? "+" : "−"}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: digits })}`;
}

function shortDate(ts: string | null | undefined): string {
  if (!ts) return "—";
  const d = new Date(ts.length === 10 ? `${ts}T00:00:00` : ts);
  if (isNaN(d.getTime())) return ts.slice(0, 10);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function Card({
  title,
  sub,
  right,
  children,
}: {
  title: string;
  sub?: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="intel-card">
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 18 }}>
        <div>
          <div className="intel-card-title">{title}</div>
          {sub && <div className="intel-card-sub">{sub}</div>}
        </div>
        {right}
      </div>
      {children}
    </div>
  );
}

/* ── main content ─────────────────────────────────────────────────── */

function IntelligenceContent() {
  const { user, isLoading, tier } = useAuth();
  const [overview, setOverview] = useState<AnalyticsOverview | null>(null);
  const [opt, setOpt] = useState<{ rows: OptRow[]; best: OptRow | null }>({ rows: [], best: null });
  const [wf, setWf] = useState<WalkforwardWindow[]>([]);
  const [ml, setMl] = useState<{ model: MLModel; trained: boolean }>({ model: null as unknown as MLModel, trained: false });
  const [equity, setEquity] = useState<{ price: PricePoint[]; live_equity: Array<{ timestamp: string; equity: number; balance: number }>; fills: FillRow[] }>({ price: [], live_equity: [], fills: [] });
  const [live, setLive] = useState<{ trades: TradeRow[]; fills: FillRow[] }>({ trades: [], fills: [] });
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [o, op, w, m, e, l] = await Promise.all([
      getAnalyticsOverview(),
      getOptimization(),
      getWalkforward(),
      getML(),
      getEquity(),
      getLiveTrades(),
    ]);
    setOverview(o);
    setOpt(op);
    setWf(w);
    setMl(m);
    setEquity(e);
    setLive(l);
    // API is online when the price series is populated (only served by Flask).
    setApiOnline(e.price.length > 0);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const hasAdvanced = user ? hasFeature(tier, "analytics:advanced") : false;

  if (isLoading) {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg)" }}>
        <div style={{ width: 24, height: 24, border: "2px solid var(--gold)", borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
      </div>
    );
  }

  if (!user) {
    return (
      <main style={{ minHeight: "100vh", background: "var(--bg)", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <UpgradePrompt
          title="Sign in required"
          description="Sign in to explore the Seek Quant intelligence dashboard."
          actionLabel="Sign In"
          actionHref="/login"
        />
      </main>
    );
  }

  /* ── derived values ─────────────────────────────────────────── */
  const liveMetrics = overview?.live.metrics ?? null;
  const sideSplit = overview?.live.side_split ?? { buy: 0, sell: 0 };
  const strategies = overview?.strategies ?? {};
  const optRows = opt.rows;
  const wfReturns = wf.map((w) => w.total_return_pct ?? 0);
  const wfLabels = wf.map((w) => shortDate(w.start_date));
  const priceCloses = equity.price.map((p) => p.close);
  const priceLabels = equity.price.map((p) => shortDate(p.t));
  const equityValues = equity.live_equity.map((e) => e.equity);
  const bestOpt = opt.best;
  const topFeatures = Object.entries(ml.model?.feature_importances ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10);

  return (
    <main style={{ minHeight: "100vh", background: "var(--bg)" }}>
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div style={{ padding: "20px 16px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 32, height: 32, borderRadius: 8, background: "linear-gradient(135deg, #e8c97a, #c9a84c)", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <span style={{ color: "#000", fontWeight: 900, fontSize: 11 }}>SQ</span>
          </div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text)" }}>Seek Quant</div>
            <div style={{ fontSize: 9, color: "var(--text-muted)", letterSpacing: "0.08em", textTransform: "uppercase" }}>Intelligence</div>
          </div>
        </div>

        <nav style={{ padding: "16px 12px", display: "flex", flexDirection: "column", gap: 4, flex: 1 }}>
          <Link href="/dashboard" className="sidebar-link">
            <LayoutDashboard size={15} /> Dashboard
          </Link>
          <Link href="/intelligence" className="sidebar-link active">
            <BrainCircuit size={15} /> Intelligence
          </Link>
          <Link href="/admin" className="sidebar-link">
            <Users size={15} /> Admin
          </Link>
          <Link href="/billing" className="sidebar-link">
            <ShieldCheck size={15} /> Billing
          </Link>
          <a href="/#pricing" className="sidebar-link">
            <Activity size={15} /> Plans
          </a>
        </nav>

        <div style={{ padding: 16, borderTop: "1px solid var(--border)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "var(--text-muted)" }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: apiOnline ? "#22c55e" : apiOnline === false ? "#ef4444" : "var(--text-dim)", animation: apiOnline ? "pulse-slow 2s ease-in-out infinite" : undefined }} />
            {apiOnline ? "Engine connected" : apiOnline === false ? "Engine offline — sample data" : "Checking…"}
          </div>
        </div>
      </aside>


      {/* ── Content ── */}
      <div style={{ marginLeft: 240, padding: "32px 40px 64px" }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 28, flexWrap: "wrap", gap: 16 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ fontSize: 10, fontWeight: 700, color: "var(--gold)", letterSpacing: "0.14em", textTransform: "uppercase" }}>Seek Quant · Analytics</span>
              {!hasAdvanced && (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 10, fontWeight: 600, padding: "3px 10px", borderRadius: 100, background: "rgba(201,168,76,0.1)", color: "var(--gold)" }}>
                  <Lock size={10} /> Basic view
                </span>
              )}
            </div>
            <h1 style={{ fontSize: 32, fontWeight: 800, letterSpacing: "-0.03em", color: "var(--text)", marginTop: 6 }}>
              Intelligence & <span className="gold-gradient">Predictions</span>
            </h1>
            <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 6, maxWidth: 640 }}>
              Live view of the trading engine: strategy backtests, walk-forward validation,
              ML regime model, optimization surface and real execution activity.
            </p>
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="btn-outline"
            style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "10px 18px", borderRadius: 10, fontSize: 13 }}
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>

        {/* ── KPI tiles ── */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 14, marginBottom: 28 }}>
          <MetricTile label="Live Fills" value={String(overview?.live.fill_count ?? 550)} sub={`${overview?.live.first_fill ? shortDate(overview?.live.first_fill) : "May 11"} → ${overview?.live.last_fill ? shortDate(overview?.live.last_fill) : "Jun 29"}`} tone="muted" />
          <MetricTile label="Matched Trades" value={String(overview?.live.trade_count ?? 241)} sub="FIFO realized PnL" tone="gold" />
          <MetricTile label="Realized PnL" value={money(liveMetrics?.total_pnl)} sub={`${(liveMetrics?.win_rate_pct ?? 0).toFixed(1)}% win rate`} tone={(liveMetrics?.total_pnl ?? 0) >= 0 ? "green" : "red"} />
          <MetricTile label="Profit Factor" value={(liveMetrics?.profit_factor ?? 0).toFixed(2)} sub={`Sharpe ${(liveMetrics?.sharpe_ratio ?? 0).toFixed(2)}`} tone={(liveMetrics?.profit_factor ?? 0) >= 1 ? "green" : "red"} />
          <MetricTile label="ML Test Accuracy" value="51%" sub="RandomForest · 3 regimes" tone="gold" />
          <MetricTile label="Backtest Sharpe" value={(strategies.breakout_strategy?.backtest?.sharpe_ratio ?? 0).toFixed(2)} sub="Breakout · 1mo 1h GC=F" tone={(strategies.breakout_strategy?.backtest?.sharpe_ratio ?? 0) >= 0 ? "green" : "red"} />
        </div>


        {/* ── Strategy performance ── */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 18, marginBottom: 28 }}>
          {Object.entries(strategies).map(([key, ops]) => {
            const bt = ops.backtest ?? {};
            const op = ops.optimize ?? {};
            const ret = Number(bt.total_return_pct ?? 0);
            return (
              <Card
                key={key}
                title={key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                sub="Backtest · GC=F 1h"
                right={
                  <span style={{ fontSize: 20, fontWeight: 800, color: ret >= 0 ? "#22c55e" : "#ef4444" }}>
                    {pct(ret)}
                  </span>
                }
              >
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, fontSize: 12 }}>
                  {[
                    ["Sharpe", (bt.sharpe_ratio ?? 0).toFixed(2)],
                    ["Max DD", pct(bt.max_drawdown_pct)],
                    ["Win Rate", pct(bt.win_rate_pct, 1)],
                    ["Profit Factor", (bt.profit_factor ?? 0).toFixed(2)],
                    ["Trades", String(bt.num_trades ?? 0)],
                    ["Avg Win", money(bt.avg_win)],
                    ["Avg Loss", money(bt.avg_loss)],
                    ["Best Optimized Sharpe", (op.sharpe_ratio ?? 0).toFixed(2)],
                  ].map(([l, v]) => (
                    <div key={l} style={{ display: "flex", justifyContent: "space-between", background: "rgba(255,255,255,0.02)", borderRadius: 8, padding: "8px 10px" }}>
                      <span style={{ color: "var(--text-muted)" }}>{l}</span>
                      <span style={{ fontWeight: 700, color: "var(--text)" }}>{v}</span>
                    </div>
                  ))}
                </div>
              </Card>
            );
          })}

          {/* Strategy comparison mini-chart */}
          <Card title="Strategy Comparison" sub="Total return % (backtest)">
            <BarChart
              values={Object.values(strategies).map((s) => Number(s.backtest?.total_return_pct ?? 0))}
              labels={Object.keys(strategies).map((k) => k.replace("_strategy", ""))}
              height={150}
              unit="%"
            />
            {Object.keys(strategies).length === 0 && (
              <div style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center", padding: "24px 0" }}>
                No strategy results yet — run a backtest from the Admin panel.
              </div>
            )}
          </Card>
        </div>

        {/* ── Price & Equity ── */}
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 18, marginBottom: 28 }}>
          <Card title="Gold Price (GC=F)" sub="1-minute sampled · real download" right={<LineIcon size={15} color="var(--gold)" />}>
            <LineChart values={priceCloses} labels={priceLabels} height={200} color="var(--gold)" unit=" $/oz" digits={0} />
          </Card>
          <Card title="Live Equity Curve" sub={`${equityValues.length} snapshots · XAUUSD.r`} right={<TrendingUpIcon size={15} color="#22c55e" />}>
            {equityValues.length > 1 ? (
              <LineChart values={equityValues} height={200} color="#22c55e" unit=" $ " digits={1} />
            ) : (
              <div style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", fontSize: 12 }}>
                No live equity snapshots yet
              </div>
            )}
          </Card>
        </div>


        {/* ── Optimization heatmap ── */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18, marginBottom: 28 }}>
          <Card
            title="Optimization Surface"
            sub="Grid spacing × levels → total return % (5d 1m GC=F)"
            right={bestOpt ? (
              <span style={{ fontSize: 11, color: "var(--gold)" }}>Best: sp {bestOpt.spacing} × lv {bestOpt.levels} → {pct(bestOpt.total_return_pct)}</span>
            ) : undefined}
          >
            <HeatmapGrid
              rows={optRows as unknown as Array<Record<string, number>>}
              xKey="spacing"
              yKey="levels"
              valueKey="total_return_pct"
              xLabel={(v) => `sp ${v}`}
              yLabel={(v) => `lv ${v}`}
              fmtValue={(v) => `${v.toFixed(2)}%`}
            />
          </Card>

          <Card
            title="Walk-Forward Validation"
            sub="Out-of-sample return per window · 6mo daily GC=F"
            right={
              <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                {wf.filter((w) => (w.total_return_pct ?? 0) > 0).length}/{wf.length} profitable
              </span>
            }
          >
            {wf.length > 0 ? (
              <BarChart values={wfReturns} labels={wfLabels} height={180} unit="%" />
            ) : (
              <div style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center", padding: "40px 0" }}>
                No walk-forward data — run `python launcher.py walkforward`
              </div>
            )}
            {wf.length > 0 && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(90px, 1fr))", gap: 8, marginTop: 16 }}>
                {[
                  ["Avg Return", `${(wf.reduce((s, w) => s + (w.total_return_pct ?? 0), 0) / wf.length).toFixed(2)}%`],
                  ["Best Window", `${Math.max(...wfReturns).toFixed(2)}%`],
                  ["Worst Window", `${Math.min(...wfReturns).toFixed(2)}%`],
                  ["Avg Max DD", `${(wf.reduce((s, w) => s + (w.max_drawdown_pct ?? 0), 0) / wf.length).toFixed(1)}%`],
                ].map(([l, v]) => (
                  <div key={l} style={{ background: "rgba(255,255,255,0.02)", borderRadius: 8, padding: "8px 10px", textAlign: "center" }}>
                    <div style={{ fontSize: 9, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{l}</div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text)", marginTop: 2 }}>{v}</div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>


        {/* ── Live activity ── */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 18, marginBottom: 28 }}>
          <Card title="Fill Activity" sub="Buy vs sell grid fills · XAUUSD.r" right={<Activity size={15} color="var(--gold)" />}>
            <DonutChart
              values={[sideSplit.buy, sideSplit.sell]}
              labels={["Buy", "Sell"]}
              colors={["#22c55e", "#ef4444"]}
            />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 16 }}>
              {[
                ["Fill count", String(overview?.live.fill_count ?? 0)],
                ["Equity snapshots", (overview?.live.equity_points ?? 0).toLocaleString()],
                ["Symbol", overview?.config?.symbol ?? "—"],
                ["Regime model", ml.trained ? "Loaded" : "Not trained"],
              ].map(([l, v]) => (
                <div key={l} style={{ background: "rgba(255,255,255,0.02)", borderRadius: 8, padding: "8px 10px", textAlign: "center" }}>
                  <div style={{ fontSize: 9, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{l}</div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text)", marginTop: 2 }}>{v}</div>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Recent Fills" sub="Last 12 executions from the engine trade DB" right={<Database size={15} color="var(--text-muted)" />}>
            {live.fills.length === 0 && equity.fills.length === 0 ? (
              <div style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center", padding: "40px 0" }}>
                No fills logged yet — the bot has not executed live trades.
              </div>
            ) : (
              <div style={{ overflowX: "auto", maxHeight: 260, overflowY: "auto" }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Side</th>
                      <th style={{ textAlign: "right" }}>Price</th>
                      <th style={{ textAlign: "right" }}>Volume</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...(equity.fills.length ? equity.fills : live.fills)].slice(0, 12).map((f, i) => (
                      <tr key={i}>
                        <td style={{ fontSize: 11, color: "var(--text-muted)" }}>{shortDate(f.timestamp)}</td>
                        <td>
                          <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 100, background: f.side === "buy" ? "rgba(34,197,94,0.12)" : "rgba(239,68,68,0.12)", color: f.side === "buy" ? "#22c55e" : "#ef4444" }}>
                            {f.side}
                          </span>
                        </td>
                        <td style={{ textAlign: "right", fontWeight: 600 }}>{Number(f.price).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                        <td style={{ textAlign: "right" }}>{f.volume}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>


        {/* ── ML model (gated) ── */}
        <Card
          title="ML Regime Model"
          sub="RandomForest · 3 regimes (BULL / RANGING / BEAR) · 37 features"
          right={<BrainCircuit size={15} color="var(--gold)" />}
        >
          {hasAdvanced ? (
            <div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 10, marginBottom: 22 }}>
                {[
                  ["Test Accuracy", "51.0%"],
                  ["Lookback", String(ml.model?.lookback ?? 20)],
                  ["Confidence Threshold", String(ml.model?.confidence_threshold ?? 0.4)],
                  ["Regime Threshold", String(ml.model?.regime_threshold ?? 1.0)],
                  ["Class BEAR", "46.6% acc"],
                  ["Class RANGING", "57.3% acc"],
                  ["Class BULL", "48.9% acc"],
                  ["Status", ml.trained ? "Trained ✓" : "Not trained"],
                ].map(([l, v]) => (
                  <div key={l} style={{ background: "rgba(255,255,255,0.02)", borderRadius: 10, padding: "12px 14px" }}>
                    <div style={{ fontSize: 9, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{l}</div>
                    <div style={{ fontSize: 15, fontWeight: 800, color: "var(--text)", marginTop: 3 }}>{v}</div>
                  </div>
                ))}
              </div>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 12 }}>
                Top predictive features by Gini importance:
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {topFeatures.map(([name, val]) => (
                  <div key={name} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ width: 130, fontSize: 11, color: "var(--text-muted)", textAlign: "right" }}>{name}</span>
                    <div style={{ flex: 1, height: 8, background: "rgba(255,255,255,0.04)", borderRadius: 4 }}>
                      <div style={{ width: `${(val / (topFeatures[0]?.[1] ?? 1)) * 100}%`, height: 8, background: "linear-gradient(90deg, #c9a84c, #e8c97a)", borderRadius: 4 }} />
                    </div>
                    <span style={{ width: 44, fontSize: 11, fontWeight: 700, color: "var(--text)" }}>{(val * 100).toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <UpgradePrompt
              title="ML Insights · Professional Plan"
              description="Unlock regime-model feature importance, class accuracy breakdowns and live regime confidence with a Professional subscription."
              actionLabel="Upgrade to Professional"
              actionHref="/checkout?plan=professional"
            />
          )}
        </Card>


        {/* ── Kronos & Risk (gated) ── */}
        <div style={{ marginTop: 28 }}>
          <Card
            title="Kronos Foundation Model & Risk"
            sub="Forecast-driven regime adaptation + VaR/CVaR position sizing"
            right={<Sparkles size={15} color="var(--gold)" />}
          >
            {hasAdvanced ? (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
                {[
                  ["Model", overview?.config?.kronos_model ?? "NeoQuasar/Kronos-small"],
                  ["Kronos enabled", overview?.config?.kronos_enabled ? "Yes ✓" : "No (default)"],
                  ["Kronos + RF blend", overview?.config?.kronos_blend_enabled ? "Enabled" : "Disabled"],
                  ["VaR/CVaR sizing", overview?.config?.kronos_risk_metrics ? "Enabled" : "Disabled"],
                  ["Multi-symbol", overview?.config?.kronos_symbols || "—"],
                  ["Adaptive updates", overview?.config?.adaptive_enabled ? "Enabled" : "Disabled"],
                ].map(([l, v]) => (
                  <div key={l} style={{ background: "rgba(255,255,255,0.02)", borderRadius: 10, padding: "12px 14px" }}>
                    <div style={{ fontSize: 9, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{l}</div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text)", marginTop: 3 }}>{v}</div>
                  </div>
                ))}
                <div style={{ gridColumn: "1 / -1" }}>
                  <div style={{ fontSize: 11, color: "var(--text-muted)", lineHeight: 1.7, background: "rgba(201,168,76,0.05)", border: "1px solid rgba(201,168,76,0.12)", borderRadius: 10, padding: "14px 16px" }}>
                    <strong style={{ color: "var(--gold)" }}>How it predicts:</strong> Kronos (NeoQuasar) is a
                    foundation model pre-trained on 45 global exchanges. Given the last ~512 bars of OHLCV,
                    it samples <em>probabilistic futures</em>; the MetaRegimeAdapter blends Kronos trend
                    strength with the RandomForest regime vote by confidence, then VaR/CVaR from the sample
                    distribution shrinks position size when tail risk rises.
                  </div>
                </div>
              </div>
            ) : (
              <UpgradePrompt
                title="Kronos & Risk Analytics · Professional Plan"
                description="Upgrade to see live Kronos forecasts, regime blend weights and probabilistic risk metrics (VaR / CVaR)."
                actionLabel="Upgrade to Professional"
                actionHref="/checkout?plan=professional"
              />
            )}
          </Card>
        </div>

        {/* ── Footer note ── */}
        <div style={{ marginTop: 32, fontSize: 11, color: "var(--text-dim)", lineHeight: 1.7, textAlign: "center" }}>
          Data served live from the Flask engine API (<code>localhost:5050/api/analytics/*</code>).
          When the engine is offline the page falls back to the last captured engine artifacts.
          Past performance is not indicative of future results.
        </div>
      </div>
    </main>
  );
}

export default function IntelligencePage() {
  return (
    <AuthProvider>
      <IntelligenceContent />
    </AuthProvider>
  );
}

