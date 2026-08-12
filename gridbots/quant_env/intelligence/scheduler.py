"""
ResearchScheduler — runs the agent team continuously on the live engine.

Mirrors the ``AdaptiveUpdater`` lifecycle (start/stop + daemon thread) so it
plugs straight into ``App.run()`` / ``GridBot.run()``.  A module-level
singleton guard ensures only ONE research loop runs per process, even when
several account bots are live.

Config knobs (read from the engine Config class or an explicit ctx):
    RESEARCH_ENABLED            bool   — master switch (default False)
    RESEARCH_INTERVAL_MINUTES   int    — minutes between cycles (default 120)
    RESEARCH_MAX_BARS           int    — bars of history per probe (default 1500)
    RESEARCH_PROBE_LIMIT        int    — parameter variants per strategy (default 2)
    RESEARCH_TOP_N              int    — opportunities prioritized per cycle (default 3)
    RESEARCH_LLM_ENABLED        bool   — enable the LLM narrative layer (default False)
"""

import os
import sys
import threading
import time

_QUANT_ENV_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _QUANT_ENV_ROOT not in sys.path:
    sys.path.insert(0, _QUANT_ENV_ROOT)


class ResearchScheduler:
    """Periodically runs a full InsightForge-for-Quant research cycle."""

    _instance = None
    _lock = threading.Lock()

    def __init__(self, config=None, logger=None, interval_minutes=None, ctx=None):
        self.log = logger
        self.config = config or {}
        self.interval_minutes = interval_minutes if interval_minutes is not None \
            else int(getattr(self.config, "RESEARCH_INTERVAL_MINUTES", 120))
        self.ctx = dict(ctx or {})
        self.ctx.setdefault("max_bars", getattr(self.config, "RESEARCH_MAX_BARS", 1500))
        self.ctx.setdefault("probe_limit", getattr(self.config, "RESEARCH_PROBE_LIMIT", 2))
        self.ctx.setdefault("top_n", getattr(self.config, "RESEARCH_TOP_N", 3))
        self.ctx.setdefault("symbols", getattr(self.config, "RESEARCH_SYMBOLS", "GC=F"))
        self.ctx.setdefault("auto_approve_cycles",
                            int(getattr(self.config, "RESEARCH_AUTO_APPROVE_CYCLES", "0")))
        self.ctx.setdefault("llm_enabled", getattr(self.config, "RESEARCH_LLM_ENABLED", False))
        self.running = False
        self.thread = None
        self.cycles_run = 0
        self.last_brief = None
        self._loop_started_at = None

    # ── Singleton (one research loop per process) ─────────────────────
    @classmethod
    def get_instance(cls, config=None, logger=None, interval_minutes=None, ctx=None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(config=config, logger=logger,
                                    interval_minutes=interval_minutes, ctx=ctx)
            return cls._instance

    # ── Lifecycle ─────────────────────────────────────────────────────
    def start(self):
        if self.running:
            return
        self.running = True
        self._loop_started_at = time.time()
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       name="ResearchScheduler")
        self.thread.start()
        if self.log:
            self.log.info(f"ResearchScheduler started (cycle every {self.interval_minutes} min).")

    def stop(self):
        self.running = False
        if self.log:
            self.log.info("ResearchScheduler stopped.")

    # ── Cycle ─────────────────────────────────────────────────────────
    def run_cycle_now(self):
        """Run one full agent cycle synchronously.  Returns the brief."""
        from .coordinator import CoordinatorAgent
        coordinator = CoordinatorAgent(self.ctx)
        brief, _ = coordinator.run_cycle()
        self.cycles_run += 1
        self.last_brief = brief
        return brief

    def _run(self):
        # First cycle a few seconds after start, then on the interval.
        self._loop_started_at = time.time()
        time.sleep(5)
        while self.running:
            try:
                if self.log:
                    self.log.info("Running autonomous research cycle…")
                brief = self.run_cycle_now()
                if self.log and brief:
                    self.log.info(
                        f"Research cycle {brief.get('cycle_id')} complete: "
                        f"{brief.get('probe_count', 0)} probes, "
                        f"{len(brief.get('themes', []))} themes, "
                        f"{len(brief.get('top_opportunities', []))} opportunities prioritized.")
            except Exception as e:
                if self.log:
                    self.log.error(f"ResearchScheduler cycle failed: {e}")
            # Sleep in small increments so stop() responds promptly.
            deadline = time.time() + self.interval_minutes * 60
            while self.running and time.time() < deadline:
                time.sleep(1)
