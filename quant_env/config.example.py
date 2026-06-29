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
    BRIDGE_URL = os.getenv("BRIDGE_URL", "http://192.166.34.2:8080")

    # ── Telegram (optional) ──────────────────────────────────────────
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    # ── Email notifications ──────────────────────────────────────────
    EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "true").lower() == "true"
    EMAIL_SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
    EMAIL_USERNAME = os.getenv("EMAIL_USERNAME", "your_email@gmail.com")
    EMAIL_PASSWORD = os.getenv(
        "EMAIL_PASSWORD", "lyas kwcw uloi uesp"
    )  # Gmail app password
    EMAIL_TO = os.getenv("EMAIL_TO", "your_email@gmail.com")

    # ── Adaptive parameter updating ──────────────────────────────────
    ADAPTIVE_ENABLED = os.getenv("ADAPTIVE_ENABLED", "true").lower() == "true"
    ADAPTIVE_INTERVAL_MINUTES = int(os.getenv("ADAPTIVE_INTERVAL_MINUTES", "120"))
    ADAPTIVE_SHARPE_THRESHOLD = float(os.getenv("ADAPTIVE_SHARPE_THRESHOLD", "0.5"))
    ADAPTIVE_PAUSE_SHARPE = float(os.getenv("ADAPTIVE_PAUSE_SHARPE", "-0.5"))

    # Yahoo Finance symbol for data downloading (different from broker symbol)
    YAHOO_SYMBOL = os.getenv("YAHOO_SYMBOL", "GC=F")  # gold futures

    # ── Economic news filter ─────────────────────────────────────────
    NEWS_FILTER_ENABLED = os.getenv("NEWS_FILTER_ENABLED", "true").lower() == "true"
    NEWS_FILTER_HOURS_AHEAD = int(os.getenv("NEWS_FILTER_HOURS_AHEAD", "6"))
    NEWS_FILTER_MINUTES_BEFORE = int(os.getenv("NEWS_FILTER_MINUTES_BEFORE", "30"))
    NEWS_FILTER_MINUTES_AFTER = int(os.getenv("NEWS_FILTER_MINUTES_AFTER", "30"))

    # ── ML / Regime classification ───────────────────────────────────
    ML_ENABLED = os.getenv("ML_ENABLED", "false").lower() == "true"
    ML_MODEL_PATH = os.getenv("ML_MODEL_PATH", "quant_env/ml/model.pkl")
    ML_REFRESH_MINUTES = int(os.getenv("ML_REFRESH_MINUTES", "60"))

    # Regime-specific grid tuning (used when ML_ENABLED=True)
    REGIME_SPACING_TRENDING = float(os.getenv("REGIME_SPACING_TRENDING", "0.4"))
    REGIME_LEVELS_TRENDING = int(os.getenv("REGIME_LEVELS_TRENDING", "3"))
    REGIME_SPACING_RANGING = float(os.getenv("REGIME_SPACING_RANGING", "0.1"))
    REGIME_LEVELS_RANGING = int(os.getenv("REGIME_LEVELS_RANGING", "5"))