"""
MetaRegimeAdapter – confidence-weighted blend of Kronos + RF regime adapters.

Instead of toggling between Kronos and RF adapters with KRONOS_ENABLED,
this meta-adapter runs both and blends their outputs dynamically.

The blend weight is determined by:
  - Kronos forecast confidence (trend_strength)
  - RF prediction confidence (probability of winning class)
  - When Kronos trend_strength is high → more weight to Kronos
  - When Kronos confidence is low → more weight to RF (statistical confirmation)

Usage::
    from ml.kronos.meta_adapter import MetaRegimeAdapter

    adapter = MetaRegimeAdapter(config, logger)
    adapter.start()
    # ...
    regime = adapter.regime       # blended regime int
    spacing = adapter.spacing     # blended spacing
    levels = adapter.levels
    kronos_weight = adapter.kronos_weight  # current Kronos blend weight
"""

import logging
import threading
import time
from typing import Optional

from .config import (
    KRONOS_TREND_STRENGTH_THRESHOLD,
    KRONOS_BLEND_ENABLED,
    KRONOS_BLEND_TREND_STRENGTH_WEIGHT,
    KRONOS_BLEND_KRONOS_WEIGHT_MIN,
    KRONOS_BLEND_RF_WEIGHT_MAX,
    KRONOS_DEFAULT_SYMBOL,
    KRONOS_DEFAULT_INTERVAL,
    KRONOS_FETCH_PERIOD,
)

log = logging.getLogger("QuantBot")


class MetaRegimeAdapter:
    """
    Blends KronosRegimeAdapter and the RF-based RegimeAdapter using
    confidence-weighted voting.

    Parameters
    ----------
    config : object
        Global QuantEnv config.
    kronos_adapter : KronosRegimeAdapter
        Initialized Kronos adapter.
    rf_adapter : RegimeAdapter
        Initialized RF-based RegimeAdapter.
    logger : logging.Logger or None
    """

    REGIME_RANGING = 0
    REGIME_BULL = 1
    REGIME_BEAR = -1

    def __init__(self, config, kronos_adapter, rf_adapter, logger=None):
        self.config = config
        self._kronos = kronos_adapter
        self._rf = rf_adapter
        self.logger = logger or log

        self._enabled = getattr(config, "KRONOS_BLEND_ENABLED", KRONOS_BLEND_ENABLED)
        self._regime = self.REGIME_RANGING
        self._regime_name = "RANGING"
        self._spacing = getattr(config, "GRID_SPACING", 80.0)
        self._levels = getattr(config, "NUM_LEVELS", 8)
        self._kronos_weight = 0.5  # current blend weight for Kronos

        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def regime(self) -> int:
        with self._lock:
            return self._regime

    @property
    def regime_name(self) -> str:
        with self._lock:
            return self._regime_name

    @property
    def spacing(self) -> float:
        with self._lock:
            return self._spacing

    @property
    def levels(self) -> int:
        with self._lock:
            return self._levels

    @property
    def kronos_weight(self) -> float:
        """Current blend weight assigned to Kronos (0..1). 1 = full Kronos."""
        with self._lock:
            return self._kronos_weight

    @property
    def confidence(self) -> float:
        """Blended confidence: weighted avg of both adapters' confidence."""
        kronos_conf = self._kronos.confidence if hasattr(self._kronos, "confidence") else 0.0
        rf_conf = self._rf.confidence if hasattr(self._rf, "confidence") else 0.0
        with self._lock:
            kw = self._kronos_weight
        return kw * kronos_conf + (1.0 - kw) * rf_conf

    def start(self):
        self._kronos.start()
        self._rf.start()
        self.logger.info("MetaRegimeAdapter: started (Kronos + RF blending)")

    def stop(self):
        self._kronos.stop()
        self._rf.stop()
        self.logger.info("MetaRegimeAdapter: stopped")

    def refresh_now(self):
        """Force refresh of both adapters and re-blend."""
        self._kronos.refresh_now()
        self._rf.refresh_now()
        self._blend()

    def update(self, data=None):
        """
        Update both adapters and compute blended regime/spacing/levels.
        """
        self._kronos.update(data)
        self._rf.refresh_now()
        self._blend()

    # ── Internal blending logic ────────────────────────────────────

    def _compute_kronos_weight(self) -> float:
        """
        Determine the weight to assign to Kronos in the blend.

        Factors:
        1. Kronos trend_strength: if high, market is directional → trust Kronos
        2. Kronos forecast_features existence: if empty, weight goes to RF
        3. RF confidence: if RF is uncertain, lean more on Kronos
        """
        # Get Kronos trend strength
        k_features = getattr(self._kronos, "forecast_features", {})
        if not k_features:
            return KRONOS_BLEND_KRONOS_WEIGHT_MIN

        trend_strength = k_features.get("trend_strength", 0.0)

        # Get RF confidence
        rf_conf = self._rf.confidence if hasattr(self._rf, "confidence") else 0.0

        # Base weight from Kronos trend strength
        # Map trend_strength [0, ~2] to weight [min, 0.8]
        clipped_ts = min(trend_strength, 2.0) / 2.0
        weight = KRONOS_BLEND_KRONOS_WEIGHT_MIN + clipped_ts * (
            0.8 - KRONOS_BLEND_KRONOS_WEIGHT_MIN
        )

        # If RF is highly confident, cap the Kronos weight
        if rf_conf > 0.8:
            weight = min(weight, KRONOS_BLEND_RF_WEIGHT_MAX)

        # If RF is very uncertain (< 0.4), boost Kronos
        if rf_conf < 0.4 and trend_strength > KRONOS_TREND_STRENGTH_THRESHOLD:
            weight = max(weight, 0.6)

        return max(KRONOS_BLEND_KRONOS_WEIGHT_MIN, min(1.0, weight))

    def _blend(self):
        """
        Blend the regime, spacing, and levels from both adapters.
        """
        kw = self._compute_kronos_weight()
        rfw = 1.0 - kw

        k_features = getattr(self._kronos, "forecast_features", {})
        has_kronos = bool(k_features) and self._kronos.enabled

        with self._lock:
            self._kronos_weight = kw

            # ── Regime blending ─────────────────────────────────────
            k_regime = self._kronos.regime if has_kronos else self.REGIME_RANGING
            rf_regime = self._rf.regime

            # Weighted voting: map regimes to numeric values
            regime_map = {
                self.REGIME_BULL: 1,
                self.REGIME_RANGING: 0,
                self.REGIME_BEAR: -1,
            }
            k_val = regime_map.get(k_regime, 0)
            rf_val = regime_map.get(rf_regime, 0)

            blended_val = kw * k_val + rfw * rf_val

            # Convert back to regime
            if blended_val > 0.3:
                self._regime = self.REGIME_BULL
                self._regime_name = "BULL"
            elif blended_val < -0.3:
                self._regime = self.REGIME_BEAR
                self._regime_name = "BEAR"
            else:
                self._regime = self.REGIME_RANGING
                self._regime_name = "RANGING"

            # ── Spacing blending ────────────────────────────────────
            k_spacing = self._kronos.spacing if has_kronos else self._spacing
            rf_spacing = self._rf.spacing
            self._spacing = round(kw * k_spacing + rfw * rf_spacing, 2)

            # ── Levels blending ─────────────────────────────────────
            k_levels = self._kronos.levels if has_kronos else self._levels
            rf_levels = self._rf.levels
            self._levels = max(1, round(kw * k_levels + rfw * rf_levels))

        self.logger.info(
            f"MetaRegimeAdapter: regime={self._regime_name} "
            f"spacing={self._spacing} levels={self._levels} "
            f"kronos_weight={kw:.2f} rf_weight={rfw:.2f}"
        )

    def __repr__(self):
        return (
            f"MetaRegimeAdapter(regime={self._regime_name}, "
            f"spacing={self._spacing}, levels={self._levels}, "
            f"kronos_weight={self._kronos_weight:.2f})"
        )