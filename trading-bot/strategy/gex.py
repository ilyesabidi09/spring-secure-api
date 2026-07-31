"""Filtre GEX (gamma exposure).

Charge des niveaux fournis par un abonnement externe (SpotGamma, MenthorQ, ...).
Format attendu du JSON:
{
  "gamma_flip": 5300.0,
  "call_walls": [5350.0, 5400.0],   # resistances (murs de gamma positif)
  "put_walls":  [5250.0, 5200.0]    # supports
}
Le filtre n'est PAS un signal isole : il autorise/bloque et module la confidence.
"""
from __future__ import annotations

import json
from pathlib import Path

from .base import Action, Signal


def load_gex_levels(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def apply_gex_filter(signal: Signal, price: float, levels: dict,
                     proximity_ticks: int, tick_size: float) -> Signal:
    """Renvoie un signal ajuste selon la proximite aux murs de gamma.

    - Long bloque si trop pres d'un call wall (resistance).
    - Short bloque si trop pres d'un put wall (support).
    - Long booste pres d'un put wall ; short booste pres d'un call wall.
    - Confidence reduite autour du gamma flip (zone instable).
    """
    if not levels or signal.action == Action.FLAT:
        return signal

    prox = proximity_ticks * tick_size
    calls = levels.get("call_walls", [])
    puts = levels.get("put_walls", [])
    flip = levels.get("gamma_flip")

    def near(lvl_list):
        return any(abs(price - lvl) <= prox for lvl in lvl_list)

    if signal.action == Action.LONG:
        if near(calls):
            return Signal(Action.FLAT, reason="GEX: long bloque sous call wall")
        if near(puts):
            signal.confidence = min(1.0, signal.confidence + 0.15)
            signal.reason += " | GEX: rebond put wall"
    elif signal.action == Action.SHORT:
        if near(puts):
            return Signal(Action.FLAT, reason="GEX: short bloque sur put wall")
        if near(calls):
            signal.confidence = min(1.0, signal.confidence + 0.15)
            signal.reason += " | GEX: rejet call wall"

    if flip is not None and abs(price - flip) <= prox:
        signal.confidence *= 0.5
        signal.reason += " | GEX: proche gamma flip (prudence)"

    return signal
