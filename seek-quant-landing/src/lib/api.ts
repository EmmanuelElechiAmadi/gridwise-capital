/**
 * API client for the Flask trading backend (port 5050).
 * Provides typed functions for all dashboard/admin data endpoints.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:5050";

async function fetchJSON<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${res.statusText} — ${url}`);
  }
  return res.json();
}

/* ── Types ───────────────────────────────────────────────────── */

export interface BotStatus {
  account_id?: string;
  label?: string;
  broker_type?: string;
  connection_status?: string;
  balance: number;
  equity: number;
  total_pnl?: number;
  pnl?: number;
  pnl_pct?: number;
  num_orders?: number;
  active_orders: number;
  open_positions?: number;
  net_position?: number;
  current_price?: number | null;
  regime?: string;
  regime_confidence?: number;
  position_direction?: string;
  grid_spacing?: number | null;
  grid_levels?: number | null;
  paused?: boolean;
  trading_active?: boolean;
  has_bot?: boolean;
  broker_connected?: boolean;
  latest_price?: number | null;
  max_drawdown_pct?: number;
}

export interface Account {
  id: string;
  label: string;
  user_id?: string;
  broker_type?: string;
  connection_status?: string;
  enabled?: boolean;
  balance: number;
  equity: number;
  total_pnl: number;
  active_orders: number;
  open_positions: number;
  paused: boolean;
  regime: string;
  position_direction: string;
  created_at?: string;
  updated_at?: string;
  last_error?: string | null;
}

export interface PerformanceMetrics {
  status: string;
  win_rate_pct: number;
  profit_factor: number;
  sharpe_ratio: number;
  num_trades: number;
  total_return_pct: number;
  avg_win: number;
  avg_loss: number;
  max_drawdown_pct: number;
}

export interface Trade {
  timestamp?: string;
  symbol?: string;
  side?: string;
  price?: number;
  volume?: number;
  pnl?: number;
  [key: string]: unknown;
}

export interface EquityPoint {
  timestamp?: string;
  equity?: number;
  [key: string]: unknown;
}

/* ── API Functions ──────────────────────────────────────────── */

/**
 * Get aggregate dashboard status (all accounts or a specific one).
 */
export async function getStatus(accountId?: string): Promise<{
  accounts: BotStatus[];
  total_balance?: number;
  total_equity?: number;
  total_pnl?: number;
  total_pnl_pct?: number;
  num_accounts?: number;
}> {
  const params = accountId ? `?account_id=${encodeURIComponent(accountId)}` : "";
  return fetchJSON(`/api/status${params}`);
}

/**
 * Get performance metrics for an account.
 */
export async function getPerformance(accountId?: string): Promise<PerformanceMetrics> {
  const params = accountId ? `?account_id=${encodeURIComponent(accountId)}` : "";
  return fetchJSON(`/api/performance${params}`);
}

/**
 * Get recent trades for an account.
 */
export async function getRecentTrades(
  accountId?: string,
  limit = 50
): Promise<Trade[]> {
  const params = new URLSearchParams();
  if (accountId) params.set("account_id", accountId);
  params.set("limit", String(limit));
  return fetchJSON(`/api/recent_trades?${params.toString()}`);
}

/**
 * Get equity curve data for an account.
 */
export async function getEquityCurve(accountId?: string): Promise<EquityPoint[]> {
  const params = accountId ? `?account_id=${encodeURIComponent(accountId)}` : "";
  return fetchJSON(`/api/equity_chart${params}`);
}

/**
 * List all brokerage accounts.
 */
export async function getAccounts(): Promise<{ accounts: Account[] }> {
  return fetchJSON("/api/accounts");
}

/**
 * Start/resume a bot. If no accountId, starts all.
 */
export async function startBot(accountId?: string): Promise<{ status: string }> {
  return fetchJSON("/api/bot/start", {
    method: "POST",
    body: JSON.stringify(accountId ? { account_id: accountId } : {}),
  });
}

/**
 * Stop/pause a bot. If no accountId, stops all.
 */
export async function stopBot(accountId?: string): Promise<{ status: string }> {
  return fetchJSON("/api/bot/stop", {
    method: "POST",
    body: JSON.stringify(accountId ? { account_id: accountId } : {}),
  });
}