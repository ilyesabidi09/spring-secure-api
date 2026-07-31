"""Types communs et interface Strategy."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol


class Action(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass
class Bar:
    """Une barre OHLCV."""
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class Signal:
    """Decision de la strategie pour une barre donnee.

    Les stops sont exprimes en POINTS de prix (stop_dist/target_dist) pour etre
    dimensionnes a la volatilite (ATR) et rester corrects quel que soit l'instrument.
    Les champs *_ticks restent pour compat ; s'ils sont utilises, l'appelant les
    convertit en points via tick_size."""
    action: Action
    stop_dist: float = 0.0      # distance du stop en points de prix
    target_dist: float = 0.0    # distance du target en points de prix
    stop_ticks: int = 0         # deprecie (compat)
    target_ticks: int = 0       # deprecie (compat)
    confidence: float = 0.0
    reason: str = ""


@dataclass
class Context:
    """Etat transmis a la strategie (position courante, niveaux GEX, etc.)."""
    position: Action = Action.FLAT
    gex_levels: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)


class Strategy(Protocol):
    """Toute strategie implemente on_bar. Les params sont serialisables pour l'optimiseur."""

    def on_bar(self, bar: Bar, context: Context) -> Signal: ...
