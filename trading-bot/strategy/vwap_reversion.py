"""VWAP mean-reversion.

Fade les extensions par rapport au VWAP de session : quand le prix s'ecarte de plus
de `dev_mult` x ATR du VWAP ET amorce un retour, on parie sur le retour vers le VWAP.
Stop = ATR au-dela de l'extreme, target = retour au VWAP (borne par rr_ratio).
Adapte au comportement de range/retour a la moyenne des index en intraday.
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import Action, Bar, Context, Signal
from .indicators import ATR, SessionVWAP


@dataclass
class VwapReversionParams:
    atr_period: int = 14
    dev_mult: float = 2.0        # ecart mini au VWAP (en ATR) pour fader
    atr_stop_mult: float = 1.0
    rr_ratio: float = 1.5        # borne max du target (en R)
    tick_size: float = 0.25


class VwapReversionStrategy:
    def __init__(self, params: VwapReversionParams):
        self.p = params
        self.atr = ATR(params.atr_period)
        self.vwap = SessionVWAP()
        self._prev_close: float | None = None

    def on_bar(self, bar: Bar, context: Context) -> Signal:
        atr = self.atr.update(bar.high, bar.low, bar.close)
        vwap = self.vwap.update(bar.time.date(), bar.close, bar.volume)
        prev = self._prev_close
        self._prev_close = bar.close

        if not atr or prev is None:
            return Signal(Action.FLAT)

        dev = bar.close - vwap
        threshold = self.p.dev_mult * atr
        stop_dist = self.p.atr_stop_mult * atr
        max_tgt = stop_dist * self.p.rr_ratio

        # Au-dessus du VWAP de > seuil et barre qui retourne vers le bas -> short.
        if dev > threshold and bar.close < prev:
            tgt = min(max_tgt, abs(dev))
            if tgt > 0:
                return Signal(Action.SHORT, stop_dist=stop_dist, target_dist=tgt,
                              confidence=1.0, reason="VWAP fade (extension haute)")
        # En dessous du VWAP de > seuil et barre qui retourne vers le haut -> long.
        if dev < -threshold and bar.close > prev:
            tgt = min(max_tgt, abs(dev))
            if tgt > 0:
                return Signal(Action.LONG, stop_dist=stop_dist, target_dist=tgt,
                              confidence=1.0, reason="VWAP fade (extension basse)")
        return Signal(Action.FLAT)
