import os


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
    KRONOS_ENABLED = os.getenv("KRONOS_ENABLED", "false").lower() == "true"
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
