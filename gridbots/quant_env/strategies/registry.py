"""
Strategy Registry
-----------------
Auto-discovers all strategy classes in the strategies/ folder that extend
BaseStrategy.  Drop a new .py file in this folder and it will appear in the
dashboard automatically — no other changes needed.

Each strategy class may optionally define:

    STRATEGY_NAME  : str   — human-readable display name
    STRATEGY_DESC  : str   — short description shown in the dashboard
    PARAMS         : dict  — configurable parameters with defaults and metadata

Example PARAMS format:
    PARAMS = {
        'spacing': {
            'label': 'Grid Spacing',
            'type': 'number',
            'default': 0.1,
            'step': 0.01,
            'min': 0.01,
        },
        'levels': {
            'label': 'Grid Levels',
            'type': 'number',
            'default': 5,
            'step': 1,
            'min': 1,
        },
    }
"""

import importlib
import inspect
import os
import pkgutil
from pathlib import Path

from typing import Optional

from .base_strategy import BaseStrategy

# ── Internal cache ────────────────────────────────────────────────────
_registry: dict[str, type] = {}
_loaded = False


def _load_strategies():
    """Scan the strategies package and register all BaseStrategy subclasses."""
    global _registry, _loaded
    if _loaded:
        return

    strategies_dir = Path(__file__).parent
    package_name = __name__.rsplit('.', 1)[0]  # e.g. 'quant_env.strategies'

    for finder, module_name, is_pkg in pkgutil.iter_modules([str(strategies_dir)]):
        if module_name in ('base_strategy', 'registry', '__init__'):
            continue
        try:
            module = importlib.import_module(f'.{module_name}', package=package_name)
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if (
                    inspect.isclass(obj)
                    and issubclass(obj, BaseStrategy)
                    and obj is not BaseStrategy
                ):
                    key = _strategy_key(obj, module_name)
                    _registry[key] = obj
        except Exception as e:
            print(f"[StrategyRegistry] Could not load {module_name}: {e}")

    _loaded = True


def _strategy_key(cls, module_name: str) -> str:
    """Return a stable snake_case key for a strategy class."""
    return getattr(cls, 'STRATEGY_KEY', module_name)


# ── Public API ────────────────────────────────────────────────────────

def get_all() -> dict[str, type]:
    """Return {key: class} for every discovered strategy."""
    _load_strategies()
    return dict(_registry)


def get_class(key: str) -> Optional[type]:
    """Return the strategy class for *key*, or None if not found."""
    _load_strategies()
    return _registry.get(key)


def list_strategies() -> list[dict]:
    """
    Return a list of strategy metadata dicts suitable for JSON serialisation.

    Each dict has:
        key         : str   — stable identifier used in API calls
        name        : str   — human-readable display name
        description : str   — short description
        params      : dict  — parameter schema (see module docstring)
    """
    _load_strategies()
    result = []
    for key, cls in sorted(_registry.items()):
        result.append({
            'key': key,
            'name': getattr(cls, 'STRATEGY_NAME', key.replace('_', ' ').title()),
            'description': getattr(cls, 'STRATEGY_DESC', ''),
            'params': getattr(cls, 'PARAMS', _default_params()),
        })
    return result


def reload():
    """Force a re-scan of the strategies folder (useful after adding a new file)."""
    global _registry, _loaded
    _registry = {}
    _loaded = False
    _load_strategies()


# ── Fallback default params ───────────────────────────────────────────

def _default_params() -> dict:
    """Minimal parameter schema used when a strategy doesn't define PARAMS."""
    return {
        'spacing': {
            'label': 'Grid Spacing',
            'type': 'number',
            'default': 0.1,
            'step': 0.01,
            'min': 0.001,
        },
        'levels': {
            'label': 'Grid Levels',
            'type': 'number',
            'default': 5,
            'step': 1,
            'min': 1,
        },
        'lot': {
            'label': 'Lot Size',
            'type': 'number',
            'default': 1.0,
            'step': 0.1,
            'min': 0.01,
        },
    }
