class Config:
    # Trading parameters
    SYMBOL = "XAUUSD.r"
    SYMBOLS = ["XAUUSD.r"]
    LOT_SIZE = 0.01
    MAGIC_NUMBER = 123456

    # Grid defaults
    GRID_SPACING = 2.0
    GRID_SPACING_MULT = 1.0
    NUM_LEVELS = 3

    # Risk
    TAKE_PROFIT_DOLLARS = 2.0
    STOP_LOSS_DOLLARS = 0
    MAX_POSITION_OZ = 1.0
    MAX_DRAWDOWN_PERCENT = 0

    # Environment
    MODE = "bridge"
    BRIDGE_URL = "http://192.166.34.2:8080"   # <-- set to your VM’s IP

    # Telegram (optional)
    TELEGRAM_TOKEN = ""
    TELEGRAM_CHAT_ID = ""
    
    # Email notifications
    EMAIL_ENABLED = True
    EMAIL_SMTP_SERVER = "smtp.gmail.com"
    EMAIL_PORT = 587
    EMAIL_USERNAME = "your_email@gmail.com"
    EMAIL_PASSWORD = "lyas kwcw uloi uesp"      # use Gmail app password, not your real password
    EMAIL_TO = "your_email@gmail.com"
        
        # Adaptive parameter updating
    ADAPTIVE_ENABLED = True                # set to False to disable
    ADAPTIVE_INTERVAL_MINUTES = 120        # how often to run walk‑forward (minutes)
    ADAPTIVE_SHARPE_THRESHOLD = 0.5        # update if Sharpe >= this
    ADAPTIVE_PAUSE_SHARPE = -0.5           # pause grid if Sharpe <= this
    # Yahoo Finance symbol for data downloading (different from broker symbol)
    YAHOO_SYMBOL = "GC=F"   # gold futures – always works on Yahoo
    
        # Economic news filter
    NEWS_FILTER_ENABLED = True
    NEWS_FILTER_HOURS_AHEAD = 6         # how far ahead to check
    NEWS_FILTER_MINUTES_BEFORE = 30     # pause grid this many minutes before high‑impact event
    NEWS_FILTER_MINUTES_AFTER = 30      # and this many minutes after