"""
Kronos integration configuration.

All Kronos-specific settings are defined here. Values can be overridden
via the main QuantEnv config object (e.g. config.KRONOS_MODEL).
"""

# ── Model Selection ──────────────────────────────────────────────
# Available on Hugging Face: "NeoQuasar/Kronos-small" (24.7M params)
#                            "NeoQuasar/Kronos-base"  (102M params)
KRONOS_MODEL_NAME = "NeoQuasar/Kronos-small"
KRONOS_TOKENIZER_NAME = "NeoQuasar/Kronos-Tokenizer-base"

# ── Inference Parameters ─────────────────────────────────────────
KRONOS_MAX_CONTEXT = 512        # Maximum context length (bars)
KRONOS_PRED_LEN = 20            # Forecast horizon (bars)
KRONOS_SAMPLE_COUNT = 5         # Number of probabilistic samples (averaged)
KRONOS_TEMPERATURE = 1.0        # Sampling temperature
KRONOS_TOP_K = 0                # Top-K filtering (0 = disabled)
KRONOS_TOP_P = 0.9              # Top-p (nucleus) sampling
KRONOS_CLIP = 5                 # Standard deviation clipping for normalization

# ── Regime Derivation ─────────────────────────────────────────────
# Minimum trend-to-volatility ratio to classify as BULL/BEAR (vs RANGING)
# Higher = more conservative (only classifies when forecast is very confident)
KRONOS_TREND_STRENGTH_THRESHOLD = 0.3

# Rolling window for computing forecast volatility
KRONOS_VOL_WINDOW = 10

# ── GC=F (Gold Futures) Default ───────────────────────────────────
# The Kronos model was trained on 45 exchanges. For fetching live data
# we default to the same symbol as the RF-based adapter.
KRONOS_DEFAULT_SYMBOL = "GC=F"
KRONOS_DEFAULT_INTERVAL = "1h"
KRONOS_FETCH_PERIOD = "3mo"     # Enough bars for max_context + padding

# ── Multi-Symbol Support (Item 6) ────────────────────────────────
# Comma-separated list of symbols to forecast independently.
# If empty or None, only KRONOS_DEFAULT_SYMBOL is used.
KRONOS_SYMBOLS = None           # e.g. "GC=F,SI=F,CL=F" for gold/silver/oil
# Whether to fetch per-symbol data concurrently (ThreadPoolExecutor)
KRONOS_PARALLEL_FETCH = True
# Max workers for parallel symbol fetching
KRONOS_PARALLEL_WORKERS = 4

# ── Confidence-Weighted Blending (Item 8) ─────────────────────────
# When KRONOS_BLEND_ENABLED=True, the MetaRegimeAdapter blends Kronos
# and RF adapter outputs weighted by their respective confidences.
KRONOS_BLEND_ENABLED = False
# When blending, minimum Kronos trend_strength to overweight Kronos
# over the RF adapter. Higher = prefer RF more.
KRONOS_BLEND_TREND_STRENGTH_WEIGHT = 0.3
# Weight floor: Kronos weight is clamped to [floor, 1.0 - rf_floor]
KRONOS_BLEND_KRONOS_WEIGHT_MIN = 0.2
# Weight ceiling for RF adapter in the blend
KRONOS_BLEND_RF_WEIGHT_MAX = 0.8

# ── Probabilistic Risk Metrics from Kronos (Item 10) ────────────────
# When True, VaR/CVaR from Kronos sample distribution adjusts positions
KRONOS_RISK_METRICS_ENABLED = False
# VaR confidence level (e.g. 0.95 = 95% VaR)
KRONOS_VAR_CONFIDENCE = 0.95
# Max acceptable loss per trade for VaR-based position sizing
KRONOS_MAX_RISK_PER_TRADE = 0.02

# ── BreakoutStrategy Integration ──────────────────────────────────
# When True, BreakoutStrategy uses Kronos forecasts to filter,
# confirm, and adjust breakout trades.
KRONOS_BREAKOUT_ENABLED = False

# Minimum trend_strength from Kronos to trust its forecast for
# breakout filtering. Higher = fewer but higher-confidence trades.
KRONOS_BREAKOUT_CONFIDENCE_MIN = 0.3

# When True, Kronos forecast direction must align with the breakout
# direction (bullish breakout requires Kronos BULL forecast).
# When False, Kronos is used as a weighting factor only, not a hard gate.
KRONOS_BREAKOUT_FILTER_DIRECTION = True

# When True, Kronos volatility forecast scales the breakout threshold
# (higher vol = wider threshold). Helps avoid false breakouts in
# high-volatility conditions.
KRONOS_BREAKOUT_VOL_ADJUST_THRESHOLD = False

# When True, Kronos volatility forecast adjusts TP/SL dollar amounts.
# Higher vol widens TP/SL; lower vol tightens them.
KRONOS_BREAKOUT_DYNAMIC_TP_SL = False

# Base volatility (annualized) used as reference for TP/SL scaling.
# TP/SL = base * (forecast_vol / this_value). Typical: 0.05–0.20.
KRONOS_BREAKOUT_BASE_VOL = 0.10

# How often (in seconds) to refresh the Kronos forecast for the
# breakout strategy.
KRONOS_BREAKOUT_REFRESH_SEC = 300  # 5 minutes