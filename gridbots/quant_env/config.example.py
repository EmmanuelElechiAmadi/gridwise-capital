import os


# Ensure gridbots/.env is loaded BEFORE any env-derived config is evaluated,
# so RESEARCH_LLM_ENABLED / LLM_* / BRIDGE_URL etc. are correct no matter
# which module imports Config first.
try:
    from dotenv import load_dotenv
    _CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(_CONFIG_DIR, "..", ".env"))   # gridbots/.env
except Exception:
    pass


class Config:
    # ── Trading parameters ───────────────────────────────────────────
    SYMBOL = "XAUUSD.r"
    SYMBOLS = ["XAUUSD.r"]
    LOT_SIZE = 0.01
    MAGIC_NUMBER = 123456

    # ── Grid defaults ────────────────────────────────────────────────
    GRID_SPACING = 2.0
    GRID_SPACING_MULT = 1.0
    NUM_LEVELS = 3

    # ── Risk ─────────────────────────────────────────────────────────
    TAKE_PROFIT_DOLLARS = 2.0
    STOP_LOSS_DOLLARS = 0
    MAX_POSITION_OZ = 1.0
    MAX_DRAWDOWN_PERCENT = 0

    # ── Environment ──────────────────────────────────────────────────
    MODE = "bridge"
    BRIDGE_URL = os.getenv("BRIDGE_URL", "http://127.0.0.1:8080")

    # ── Telegram (optional) ──────────────────────────────────────────
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    # ── Email notifications ──────────────────────────────────────────
    EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "true").lower() == "true"
    EMAIL_SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
    EMAIL_USERNAME = os.getenv("EMAIL_USERNAME", "your_email@gmail.com")
    EMAIL_PASSWORD = os.getenv(
        "EMAIL_PASSWORD", ""
    )  # set via .env — never hardcode secrets
    EMAIL_TO = os.getenv("EMAIL_TO", "your_email@gmail.com")

    # ── Adaptive parameter updating ──────────────────────────────────
    ADAPTIVE_ENABLED = os.getenv("ADAPTIVE_ENABLED", "true").lower() == "true"
    ADAPTIVE_INTERVAL_MINUTES = int(os.getenv("ADAPTIVE_INTERVAL_MINUTES", "120"))
    ADAPTIVE_SHARPE_THRESHOLD = float(os.getenv("ADAPTIVE_SHARPE_THRESHOLD", "0.5"))
    ADAPTIVE_PAUSE_SHARPE = float(os.getenv("ADAPTIVE_PAUSE_SHARPE", "-0.5"))

    # Yahoo Finance symbol for data downloading (different from broker symbol)
    YAHOO_SYMBOL = os.getenv("YAHOO_SYMBOL", "GC=F")  # gold futures

    # ── Economic news filter ─────────────────────────────────────────
    NEWS_FILTER_ENABLED = os.getenv("NEWS_FILTER_ENABLED", "false").lower() == "true"
    NEWS_FILTER_HOURS_AHEAD = int(os.getenv("NEWS_FILTER_HOURS_AHEAD", "6"))
    NEWS_FILTER_MINUTES_BEFORE = int(os.getenv("NEWS_FILTER_MINUTES_BEFORE", "30"))
    NEWS_FILTER_MINUTES_AFTER = int(os.getenv("NEWS_FILTER_MINUTES_AFTER", "30"))

    # ── ML / Regime classification (directional: BULL / RANGING / BEAR) ──
    ML_ENABLED = os.getenv("ML_ENABLED", "false").lower() == "true"
    ML_MODEL_PATH = os.getenv("ML_MODEL_PATH", "quant_env/ml/model.pkl")
    ML_REFRESH_MINUTES = int(os.getenv("ML_REFRESH_MINUTES", "60"))
    ML_CONFIDENCE_THRESHOLD = float(os.getenv("ML_CONFIDENCE_THRESHOLD", "0.4"))

    # Regime-specific grid tuning (used when ML_ENABLED=True)
    # BULL regime – wider grid, asymmetric (more buy levels)
    REGIME_SPACING_BULL = float(os.getenv("REGIME_SPACING_BULL", "4.0"))
    REGIME_LEVELS_BULL = int(os.getenv("REGIME_LEVELS_BULL", "3"))
    # BEAR regime – wider grid, asymmetric (more sell levels)
    REGIME_SPACING_BEAR = float(os.getenv("REGIME_SPACING_BEAR", "4.0"))
    REGIME_LEVELS_BEAR = int(os.getenv("REGIME_LEVELS_BEAR", "3"))
    # RANGING regime – tight grid, many symmetric levels
    REGIME_SPACING_RANGING = float(os.getenv("REGIME_SPACING_RANGING", "1.6"))
    REGIME_LEVELS_RANGING = int(os.getenv("REGIME_LEVELS_RANGING", "5"))

    # ── Kronos foundation model (forecast-driven regime adaptation) ──
    KRONOS_ENABLED = os.getenv("KRONOS_ENABLED", "true").lower() == "true"
    # Kronos breakout enhancer (trade filtering + dynamic TP/SL on BreakoutStrategy)
    KRONOS_BREAKOUT_ENABLED = os.getenv("KRONOS_BREAKOUT_ENABLED", "false").lower() == "true"
    KRONOS_MODEL = os.getenv("KRONOS_MODEL", "NeoQuasar/Kronos-small")
    KRONOS_TOKENIZER = os.getenv("KRONOS_TOKENIZER", "NeoQuasar/Kronos-Tokenizer-base")
    # Override the data-fetching symbol/interval for Kronos (defaults to YAHOO_SYMBOL)
    KRONOS_SYMBOL = os.getenv("KRONOS_SYMBOL", "")  # "" = uses YAHOO_SYMBOL
    KRONOS_INTERVAL = os.getenv("KRONOS_INTERVAL", "1h")
    KRONOS_PRED_LEN = int(os.getenv("KRONOS_PRED_LEN", "20"))
    KRONOS_REFRESH_MINUTES = int(os.getenv("KRONOS_REFRESH_MINUTES", "30"))
    KRONOS_TREND_STRENGTH_THRESHOLD = float(
        os.getenv("KRONOS_TREND_STRENGTH_THRESHOLD", "0.3")
    )

    # ── Multi-Symbol Portfolio Forecasting (Item 6) ──────────────────
    # Comma-separated list of symbols for independent Kronos forecasts.
    # E.g. "GC=F,SI=F,CL=F" for gold, silver, crude oil.
    KRONOS_SYMBOLS = os.getenv("KRONOS_SYMBOLS", "")
    # Number of parallel workers for per-symbol fetch/forecast
    KRONOS_PARALLEL_WORKERS = int(os.getenv("KRONOS_PARALLEL_WORKERS", "4"))

    # ── Portfolio Optimizer (Item 6) ─────────────────────────────────
    # Blend weight for Kronos forecasts when allocating capital
    KRONOS_PORTFOLIO_WEIGHT = float(os.getenv("KRONOS_PORTFOLIO_WEIGHT", "0.4"))
    # Max fraction of equity to risk across the portfolio
    PORTFOLIO_MAX_RISK = float(os.getenv("PORTFOLIO_MAX_RISK", "0.1"))

    # ── Kronos + RF Confidence Blending (Item 8) ─────────────────────
    # When True, the MetaRegimeAdapter blends Kronos and RF adapter
    # outputs based on their respective confidences.
    KRONOS_BLEND_ENABLED = os.getenv("KRONOS_BLEND_ENABLED", "false").lower() == "true"
    # Kronos weight floor in the blend (0..1)
    KRONOS_BLEND_KRONOS_WEIGHT_MIN = float(os.getenv("KRONOS_BLEND_KRONOS_WEIGHT_MIN", "0.2"))
    # RF weight ceiling in the blend (0..1)
    KRONOS_BLEND_RF_WEIGHT_MAX = float(os.getenv("KRONOS_BLEND_RF_WEIGHT_MAX", "0.8"))

    # ── Probabilistic Risk Metrics from Kronos (Item 10) ─────────────
    # When True, VaR/CVaR from Kronos sample distribution adjusts positions
    KRONOS_RISK_METRICS_ENABLED = os.getenv("KRONOS_RISK_METRICS_ENABLED", "false").lower() == "true"
    # VaR confidence level (e.g. 0.95 = 95% VaR)
    KRONOS_VAR_CONFIDENCE = float(os.getenv("KRONOS_VAR_CONFIDENCE", "0.95"))
    # Max acceptable loss per trade for VaR-based position sizing
    KRONOS_MAX_RISK_PER_TRADE = float(os.getenv("KRONOS_MAX_RISK_PER_TRADE", "0.02"))

    # ── Autonomous research loop (InsightForge for Quant) ─────────────
    # Master switch — when True the ResearchScheduler starts with the bot
    # and runs the agent team (scout→prober→analyst→strategist→brief)
    # continuously.  Singleton-guarded: one loop per process.
    RESEARCH_ENABLED = os.getenv("RESEARCH_ENABLED", "false").lower() == "true"
    # Minutes between research cycles
    RESEARCH_INTERVAL_MINUTES = int(os.getenv("RESEARCH_INTERVAL_MINUTES", "120"))
    # Bars of cached history to probe per strategy
    RESEARCH_MAX_BARS = int(os.getenv("RESEARCH_MAX_BARS", "1500"))
    # Parameter variants probed per strategy
    RESEARCH_PROBE_LIMIT = int(os.getenv("RESEARCH_PROBE_LIMIT", "2"))
    # Opportunities prioritized per cycle
    RESEARCH_TOP_N = int(os.getenv("RESEARCH_TOP_N", "3"))
    # Symbol corpus the Prober probes (comma-separated): GC=F,SI=F,CL=F
    RESEARCH_SYMBOLS = os.getenv("RESEARCH_SYMBOLS", "GC=F")
    # Auto-approve a deployment only after N consistent cycles (0 = human gate only)
    RESEARCH_AUTO_APPROVE_CYCLES = int(os.getenv("RESEARCH_AUTO_APPROVE_CYCLES", "0"))
    # Enable the optional LLM narrative layer (requires an API key below)
    RESEARCH_LLM_ENABLED = os.getenv("RESEARCH_LLM_ENABLED", "false").lower() == "true"
    # News Desk: enable the News Research Analyst in the agent team (default on;
    # the fetcher is fail-safe — offline simply means "no news this cycle").
    RESEARCH_NEWS_ENABLED = os.getenv("RESEARCH_NEWS_ENABLED", "true").lower() == "true"
    # Max curated headlines handed to Claude Sonnet per cycle.
    RESEARCH_NEWS_MAX_ARTICLES = int(os.getenv("RESEARCH_NEWS_MAX_ARTICLES", "20"))
    # Air-gapped / demo mode: use the deterministic OFFLINE sample corpus
    # instead of live RSS (clearly labelled "Sample corpus", never live news).
    RESEARCH_NEWS_USE_SAMPLE = os.getenv("RESEARCH_NEWS_USE_SAMPLE", "false").lower() == "true"

    # ── LLM narrative layer (optional, fail-safe) ─────────────────────
    # Provider: "openai" or "anthropic".  Leave empty to disable.
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    # Latest tiers (2026): Haiku 4.5 = fast summaries, Opus 5 = deep synthesis,
    # Sonnet 5 = the NEWS DESK tier (best cost/capability for multi-outlet
    # synthesis + verbatim-citation grounding).  The client falls back
    # Opus 4.8 -> Sonnet 5 -> 3.5-gen automatically, and auto-discovers
    # working models from /v1/models if even those fail.
    LLM_FAST_MODEL = os.getenv("LLM_FAST_MODEL", "claude-haiku-4-5")           # summaries
    LLM_CAPABLE_MODEL = os.getenv("LLM_CAPABLE_MODEL", "claude-opus-5")        # deep synthesis
    LLM_NEWS_MODEL = os.getenv("LLM_NEWS_MODEL", "claude-sonnet-5")            # news desk
    LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "500"))
    LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "30"))
    # NewsAPI.org key (optional) — enables the richer NewsAPI fetcher in
    # addition to the default public RSS outlets.
    NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

    # ── Consensus engine (Phase 1 — common conclusion across brains) ──
    # Direction decided when |consensus value| exceeds this.
    CONSENSUS_DIRECTION_THRESHOLD = float(os.getenv("CONSENSUS_DIRECTION_THRESHOLD", "0.2"))
    # v4 source-correlation penalty (#18): agreement uses independence-
    # corrected weights (weight / VIF) so two correlated brains cannot
    # double-count the same information.  The pairwise source correlations
    # are JSON: {"backtest,trend_filter": 0.4, ...} — keys are case-
    # insensitive and symmetric; unknown pairs fall back to 0.15.  The News
    # Desk is the panel's most independent brain (~0.05 vs price sources),
    # so it genuinely raises the effective sample size.
    CONSENSUS_DIVERSITY_ADJUST = os.getenv("CONSENSUS_DIVERSITY_ADJUST", "true").lower() == "true"
    CONSENSUS_SOURCE_CORRELATIONS = os.getenv("CONSENSUS_SOURCE_CORRELATIONS", "")

    # ── Deployment quality gates (Phase 0) ────────────────────────────
    # A deployment cannot be approved unless every gate passes (or the human
    # explicitly force-approves, which is logged and auditable).
    DEPLOY_MIN_TRADES = int(os.getenv("DEPLOY_MIN_TRADES", "30"))
    DEPLOY_MIN_SHARPE = float(os.getenv("DEPLOY_MIN_SHARPE", "0.8"))
    DEPLOY_MIN_OOS_CONSISTENCY = float(os.getenv("DEPLOY_MIN_OOS_CONSISTENCY", "0.6"))
    DEPLOY_MIN_MC_PROB_PROFIT = float(os.getenv("DEPLOY_MIN_MC_PROB_PROFIT", "60.0"))
    DEPLOY_MIN_Q_RICE = float(os.getenv("DEPLOY_MIN_Q_RICE", "0.03"))
    DEPLOY_MAX_DRAWDOWN_PCT = float(os.getenv("DEPLOY_MAX_DRAWDOWN_PCT", "20.0"))
    # v4 empirical gate (#16): Probability of Backtest Overfitting (PBO via
    # CSCV, Bailey et al. 2017).  OPTIONAL — only enforced when the probe
    # corpus yields a PBO estimate; above this the IS-best strategy is
    # considered overfit and deployment is blocked.
    DEPLOY_MAX_PBO = float(os.getenv("DEPLOY_MAX_PBO", "0.5"))

    # ── Execution layer (Phase 3 — safe auto-execution) ───────────────
    # Minimum consensus strength before the advisor can recommend a trade.
    EXEC_MIN_CONSENSUS_STRENGTH = float(os.getenv("EXEC_MIN_CONSENSUS_STRENGTH", "0.35"))
    # Maximum risk fraction of equity per trade (VaR-informed sizing).
    EXEC_MAX_RISK_PER_TRADE = float(os.getenv("EXEC_MAX_RISK_PER_TRADE", "0.02"))
    # Shadow forward-test minimums before a deployment can go live.
    SHADOW_MIN_TRADES = int(os.getenv("SHADOW_MIN_TRADES", "20"))
    SHADOW_MIN_SHARPE = float(os.getenv("SHADOW_MIN_SHARPE", "0.6"))
    SHADOW_MIN_MC_PROB = float(os.getenv("SHADOW_MIN_MC_PROB", "55.0"))
    # Kill-switches for live positions.
    EXEC_KILL_MAX_DRAWDOWN_PCT = float(os.getenv("EXEC_KILL_MAX_DRAWDOWN_PCT", "15.0"))
    EXEC_KILL_CONSENSUS_COLLAPSE = os.getenv("EXEC_KILL_CONSENSUS_COLLAPSE", "true").lower() == "true"
    EXEC_KILL_CONSENSUS_FLOOR = float(os.getenv("EXEC_KILL_CONSENSUS_FLOOR", "0.15"))
    EXEC_KILL_REGIME_FLIP = os.getenv("EXEC_KILL_REGIME_FLIP", "true").lower() == "true"
