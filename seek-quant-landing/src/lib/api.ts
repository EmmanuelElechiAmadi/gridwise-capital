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

/* ── Intelligence (research agents / consensus / execution) ────── */

export interface LLMFactCheck {
  passed?: boolean;
  checked?: number;
  flagged?: string[];
  failed_citations?: string[];
}

export interface LLMVerdict {
  direction?: string;
  strength?: number;
  confidence?: number;
  horizon?: string;
  key_risks?: string[];
  evidence_cited?: string[];
  _fact_check?: LLMFactCheck;
}

export interface MarketView {
  id?: string;
  direction: string;
  direction_value?: number;
  strength?: number;
  agreement_index?: number;
  consensus_strength?: number;
  contributions?: Array<{
    source: string;
    direction: string;
    strength?: number;
    confidence?: number;
    contribution?: number;
    evidence?: Record<string, unknown>;
    note?: string;
  }>;
  disagreements?: Array<{ source: string; direction?: string; message?: string }>;
  llm_verdict?: LLMVerdict | null;
  llm_fact_check?: LLMFactCheck | null;
  generated_at?: string;
  sources?: string[];
}

export interface DeploymentRecord {
  id: string;
  strategy_key: string;
  status: string;
  qrice?: number;
  params?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
  quality?: {
    passed?: boolean;
    failed?: string[];
    gates?: Array<{ gate: string; value?: number | null; threshold: number; passed: boolean }>;
  };
  note?: string;
  approved_by?: string | null;
  proposed_at?: string;
  approved_at?: string | null;
}

export interface TradeRecommendation {
  symbol: string;
  action: string;
  side?: string | null;
  confidence?: number;
  suggested_lot?: number;
  risk_fraction?: number;
  reason_chain?: Array<{ step: string; detail: string }>;
  gates?: Array<{ gate: string; passed: boolean; value: number; threshold: number }>;
  generated_at?: string;
}

export interface ShadowReport {
  id: string;
  deployment_id?: string;
  strategy_key?: string;
  status: string;
  metrics?: Record<string, unknown>;
  gates?: Array<{ gate: string; passed: boolean; value: number; threshold: number }>;
  reason?: string;
  window_bars?: number;
}


/**
 * Get the latest consensus MarketView + recent history.
 */
export async function getMarketView(): Promise<{
  status: string;
  market_view: MarketView | null;
  history: MarketView[];
  count: number;
} | null> {
  return fetchJSON("/api/intelligence/market_view");
}

/**
 * Get a trade recommendation from the advisor (consensus + gates + Kronos).
 */
export async function getAdvice(payload?: {
  price?: number;
  equity?: number;
  deployment_id?: string;
}): Promise<{
  status: string;
  market_view: MarketView;
  recommendation: TradeRecommendation;
} | null> {
  const res = await fetch(`${API_BASE}/api/intelligence/advise`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload ?? {}),
  });
  if (!res.ok) return null;
  return res.json();
}

/**
 * List all deployments (proposed / approved / blocked / voided).
 */
export async function getDeployments(): Promise<{
  status: string;
  deployments: DeploymentRecord[];
} | null> {
  return fetchJSON("/api/intelligence/deployments");
}

/**
 * Approve / force-approve / reject / void a deployment.
 */
export async function deploymentAction(
  action: "approve" | "force_approve" | "reject" | "void",
  deployment_id: string,
  reason?: string
): Promise<{ status: string; deployment?: DeploymentRecord; message?: string } | null> {
  const res = await fetch(`${API_BASE}/api/intelligence/deploy`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, deployment_id, reason }),
  });
  if (!res.ok) return null;
  return res.json();
}

/**
 * Forward-test an approved deployment on a held-out recent window.
 */
export async function runShadowTest(deployment_id: string): Promise<{
  status: string;
  report: ShadowReport;
} | null> {
  const res = await fetch(`${API_BASE}/api/intelligence/shadow`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ deployment_id }),
  });
  if (!res.ok) return null;
  return res.json();
}

