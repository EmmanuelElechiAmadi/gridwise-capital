/**
 * Analytics client for the Flask backend's `/api/analytics/*` endpoints.
 * Each fetcher falls back to the real data captured from the engine
 * (CSVs / JSON / trade DB) so the Intelligence page renders even when the
 * Flask backend is offline.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:5050";

async function fetchJSON<T>(endpoint: string): Promise<T | null> {
  try {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      headers: { "Content-Type": "application/json" },
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return null;
    return res.json() as Promise<T>;
  } catch {
    return null;
  }
}

/* ── Types ─────────────────────────────────────────────────────────── */

export interface StrategyOps {
  backtest?: Record<string, number>;
  optimize?: Record<string, number>;
  walkforward?: Record<string, number>;
  train_ml?: Record<string, unknown>;
}

export interface AnalyticsOverview {
  status: string;
  strategies: Record<string, StrategyOps>;
  live: {
    fill_count: number;
    trade_count: number;
    equity_points: number;
    first_fill: string | null;
    last_fill: string | null;
    metrics: Record<string, number> | null;
    side_split: { buy: number; sell: number };
  };
  config: {
    symbol: string;
    yahoo_symbol: string;
    ml_enabled: boolean;
    kronos_enabled: boolean;
    kronos_blend_enabled: boolean;
    kronos_risk_metrics: boolean;
    kronos_symbols: string;
    kronos_model: string;
    adaptive_enabled: boolean;
  };
}

export interface OptRow {
  spacing: number;
  levels: number;
  total_return_pct: number;
  total_pnl: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  num_trades: number;
  win_rate_pct: number;
  profit_factor: number;
}

export interface WalkforwardWindow {
  start_date: string;
  end_date: string;
  total_return_pct: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  win_rate_pct: number;
  profit_factor: number;
  spacing: number;
  levels: number;
}

export interface MLModel {
  lookback: number;
  threshold: number;
  confidence_threshold: number;
  regime_threshold: number;
  features: string[];
  feature_importances: Record<string, number>;
}

export interface PricePoint {
  t: string;
  close: number;
  high: number;
  low: number;
}

export interface EquityPoint2 {
  timestamp: string;
  equity: number;
  balance: number;
}

export interface FillRow {
  timestamp: string;
  symbol: string;
  side: string;
  price: number;
  volume: number;
  pnl: number;
}

export interface TradeRow {
  entry_time: string;
  exit_time: string;
  entry_price: number;
  exit_price: number;
  volume: number;
  pnl: number;
}

/* ── Real fallback data (captured from engine artifacts, 2026-07-12) ── */

const FALLBACK_OPTIMIZATION: OptRow[] = [
  { spacing: 0.05, levels: 5, total_return_pct: -3.08, total_pnl: -301.88, sharpe_ratio: -0.22, max_drawdown_pct: 3.08, num_trades: 5, win_rate_pct: 0, profit_factor: 0 },
  { spacing: 0.1, levels: 3, total_return_pct: -1.53, total_pnl: -150.77, sharpe_ratio: -0.22, max_drawdown_pct: 1.53, num_trades: 3, win_rate_pct: 0, profit_factor: 0 },
  { spacing: 0.05, levels: 7, total_return_pct: -3.64, total_pnl: -351.54, sharpe_ratio: -0.26, max_drawdown_pct: 3.64, num_trades: 7, win_rate_pct: 0, profit_factor: 0 },
  { spacing: 0.05, levels: 3, total_return_pct: -2.03, total_pnl: -201.17, sharpe_ratio: -0.28, max_drawdown_pct: 2.03, num_trades: 3, win_rate_pct: 0, profit_factor: 0 },
  { spacing: 0.2, levels: 3, total_return_pct: -1.52, total_pnl: -150.17, sharpe_ratio: -0.3, max_drawdown_pct: 1.52, num_trades: 3, win_rate_pct: 33.33, profit_factor: 0.44 },
  { spacing: 0.1, levels: 5, total_return_pct: -3.07, total_pnl: -300.57, sharpe_ratio: -0.31, max_drawdown_pct: 3.07, num_trades: 5, win_rate_pct: 20, profit_factor: 0.16 },
  { spacing: 0.2, levels: 5, total_return_pct: -3.53, total_pnl: -347.78, sharpe_ratio: -0.33, max_drawdown_pct: 3.53, num_trades: 5, win_rate_pct: 60, profit_factor: 4.16 },
  { spacing: 0.1, levels: 7, total_return_pct: -4.61, total_pnl: -449.21, sharpe_ratio: -0.4, max_drawdown_pct: 4.61, num_trades: 7, win_rate_pct: 57.14, profit_factor: 0.97 },
  { spacing: 0.2, levels: 7, total_return_pct: -5.52, total_pnl: -543.85, sharpe_ratio: -0.48, max_drawdown_pct: 5.52, num_trades: 7, win_rate_pct: 71.43, profit_factor: 10.28 },
];

const FALLBACK_WALKFORWARD: WalkforwardWindow[] = [
  { start_date: "2025-12-24", end_date: "2026-01-08", total_return_pct: 0, sharpe_ratio: 0, max_drawdown_pct: 0, win_rate_pct: 100, profit_factor: 0, spacing: 0.5, levels: 3 },
  { start_date: "2026-01-09", end_date: "2026-01-23", total_return_pct: 14.57, sharpe_ratio: 11.82, max_drawdown_pct: 1.09, win_rate_pct: 100, profit_factor: 0, spacing: 0.5, levels: 3 },
  { start_date: "2026-01-26", end_date: "2026-02-06", total_return_pct: 0, sharpe_ratio: 0, max_drawdown_pct: 0, win_rate_pct: 100, profit_factor: 0, spacing: 0.5, levels: 3 },
  { start_date: "2026-02-09", end_date: "2026-02-23", total_return_pct: 0, sharpe_ratio: 0, max_drawdown_pct: 0, win_rate_pct: 100, profit_factor: 0, spacing: 2.0, levels: 5 },
  { start_date: "2026-02-24", end_date: "2026-03-09", total_return_pct: 0, sharpe_ratio: 0, max_drawdown_pct: 0, win_rate_pct: 100, profit_factor: 0, spacing: 0.5, levels: 3 },
  { start_date: "2026-03-10", end_date: "2026-03-23", total_return_pct: -24.77, sharpe_ratio: -14.44, max_drawdown_pct: 24.77, win_rate_pct: 0, profit_factor: 0, spacing: 0.5, levels: 3 },
  { start_date: "2026-03-24", end_date: "2026-04-07", total_return_pct: 0.29, sharpe_ratio: 0.39, max_drawdown_pct: 6.71, win_rate_pct: 100, profit_factor: 0, spacing: 2.0, levels: 5 },
  { start_date: "2026-04-08", end_date: "2026-04-21", total_return_pct: 0, sharpe_ratio: 0, max_drawdown_pct: 0, win_rate_pct: 100, profit_factor: 0, spacing: 0.5, levels: 5 },
  { start_date: "2026-04-22", end_date: "2026-05-05", total_return_pct: 0.29, sharpe_ratio: 5.29, max_drawdown_pct: 0, win_rate_pct: 100, profit_factor: 0, spacing: 2.0, levels: 5 },
  { start_date: "2026-05-06", end_date: "2026-05-19", total_return_pct: 0, sharpe_ratio: 0, max_drawdown_pct: 0, win_rate_pct: 100, profit_factor: 0, spacing: 0.5, levels: 3 },
];

const FALLBACK_ML: MLModel = {
  lookback: 20,
  threshold: 25,
  confidence_threshold: 0.4,
  regime_threshold: 1.0,
  features: [
    "volatility", "atr_ratio", "bb_width", "rsi", "macd", "macd_signal", "macd_hist",
    "price_to_sma_20", "price_to_sma_50", "price_to_sma_200", "sma_20_slope", "sma_50_slope",
    "bb_pct_b", "volume_ratio", "high_low_ratio", "adx_current", "returns",
  ],
  feature_importances: {
    macd_signal: 0.0852, sma_50_slope: 0.0664, macd: 0.0609, price_to_sma_200: 0.0604,
    adx_current: 0.0537, sma_20_slope: 0.0489, atr_ratio: 0.0471, volatility_lag5: 0.0425,
    volatility_lag4: 0.0398, price_to_sma_20: 0.0347, price_to_sma_50: 0.0341, bb_width: 0.0339,
    volatility_lag3: 0.0306, volatility: 0.0293, volatility_lag2: 0.0277, macd_hist: 0.0274,
    bb_pct_b: 0.0261, volatility_lag1: 0.0262, rsi: 0.0222, rsi_lag3: 0.0217,
  },
};


const FALLBACK_OVERVIEW: AnalyticsOverview = {
  status: "ok",
  strategies: {
    breakout_strategy: {
      backtest: {
        total_return_pct: -0.08, total_pnl: -0.08, sharpe_ratio: -0.01,
        max_drawdown_pct: 2.2, num_trades: 2, win_rate_pct: 50, profit_factor: 0,
        avg_win: 0.92, avg_loss: 0,
      },
      optimize: {
        total_return_pct: -8.47, sharpe_ratio: 0.88, max_drawdown_pct: 79.82,
        num_trades: 2, win_rate_pct: 50, spacing: 0.05, levels: 3,
      },
      walkforward: { windows: 1 },
      train_ml: { trained_at: "2026-07-12 21:59:33" },
    },
  },
  live: {
    fill_count: 550,
    trade_count: 241,
    equity_points: 28436,
    first_fill: "2026-05-11T11:17:32",
    last_fill: "2026-06-29T15:52:38",
    metrics: {
      win_rate_pct: 74.69, profit_factor: 0.95, sharpe_ratio: 0.16,
      num_trades: 241, total_pnl: -15.47, avg_win: 0.29, avg_loss: -0.9,
    },
    side_split: { buy: 309, sell: 241 },
  },
  config: {
    symbol: "XAUUSD.r",
    yahoo_symbol: "GC=F",
    ml_enabled: false,
    kronos_enabled: false,
    kronos_blend_enabled: false,
    kronos_risk_metrics: false,
    kronos_symbols: "",
    kronos_model: "NeoQuasar/Kronos-small",
    adaptive_enabled: true,
  },
};

/* ── API client ────────────────────────────────────────────────────── */

export async function getAnalyticsOverview(): Promise<AnalyticsOverview> {
  const data = await fetchJSON<AnalyticsOverview>("/api/analytics/overview");
  return data?.status === "ok" ? data : FALLBACK_OVERVIEW;
}

export async function getOptimization(): Promise<{ rows: OptRow[]; best: OptRow | null }> {
  const data = await fetchJSON<{ status: string; rows: OptRow[]; best: OptRow | null }>("/api/analytics/optimization");
  if (data?.status === "ok") return { rows: data.rows ?? [], best: data.best ?? null };
  return { rows: FALLBACK_OPTIMIZATION, best: FALLBACK_OPTIMIZATION[1] ?? null };
}

export async function getWalkforward(): Promise<WalkforwardWindow[]> {
  const data = await fetchJSON<{ status: string; windows: WalkforwardWindow[] }>("/api/analytics/walkforward");
  if (data?.status === "ok" && data.windows?.length) return data.windows;
  return FALLBACK_WALKFORWARD;
}

export async function getML(): Promise<{ model: MLModel; trained: boolean }> {
  const data = await fetchJSON<{ status: string; model: MLModel; trained: boolean }>("/api/analytics/ml");
  if (data?.status === "ok") return { model: data.model ?? FALLBACK_ML, trained: Boolean(data.trained) };
  return { model: FALLBACK_ML, trained: true };
}

export async function getEquity(): Promise<{ price: PricePoint[]; live_equity: EquityPoint2[]; fills: FillRow[] }> {
  const data = await fetchJSON<{ status: string; price: PricePoint[]; live_equity: EquityPoint2[]; fills: FillRow[] }>("/api/analytics/equity");
  return data?.status === "ok"
    ? { price: data.price ?? [], live_equity: data.live_equity ?? [], fills: data.fills ?? [] }
    : { price: [], live_equity: [], fills: [] };
}

export async function getLiveTrades(): Promise<{ trades: TradeRow[]; fills: FillRow[] }> {
  const data = await fetchJSON<{ status: string; trades: TradeRow[]; fills: FillRow[] }>("/api/analytics/live");
  if (data?.status === "ok") return { trades: data.trades ?? [], fills: data.fills ?? [] };
  return { trades: [], fills: [] };
}

