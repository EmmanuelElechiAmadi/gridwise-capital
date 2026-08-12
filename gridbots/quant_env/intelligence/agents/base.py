"""
BaseAgent — the contract shared by every quant professional replacement.

Each subclass declares the human role it replaces (``REPLACES``), its quant
title (``ROLE``) and its primary responsibility, mirroring the InsightForge
agent spec table.
"""


class BaseAgent:
    KEY = "base"
    ROLE = "Quant Professional"
    REPLACES = "Human quant professional"
    PRIMARY_RESPONSIBILITY = "Undefined"
    INTEGRATIONS = []

    def __init__(self, ctx=None):
        self.ctx = ctx or {}
        self._log = []

    # ── Reporting ─────────────────────────────────────────────────────
    def log(self, message):
        self._log.append(str(message))

    def run(self, ledger):
        """Execute the agent's step in the research cycle.  Returns a JSON-safe dict."""
        raise NotImplementedError

    def _report(self, **fields):
        fields.setdefault("agent", self.KEY)
        fields.setdefault("role", self.ROLE)
        fields.setdefault("replaces", self.REPLACES)
        fields.setdefault("log", self._log[-25:])
        return fields
