"""Bollinger Band reversion filtre par ADX.

Fade les extensions hors des bandes de Bollinger UNIQUEMENT en marche de range
(ADX faible) — car en tendance forte, le fade se fait ecraser. Entree sur retour
a l'interieur de la bande (rejet), target vers la bande mediane.
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import Action, Bar, Context, Signal
from .indicators import ADX, ATR, Bollinger


@dataclass
class BollingerParams:
    bb_period: int = 20
    bb_k: float = 2.0
    adx_period: int = 14
    adx_max: float = 25.0        # ne trader que si ADX < adx_max (range)
    atr_period: int = 14
    atr_stop_mult: float = 1.0
    rr_ratio: float = 1.5
    tick_size: float = 0.25


class BollingerStrategy:
    def __init__(self, params: BollingerParams):
        self.p = params
        self.bb = Bollinger(params.bb_period, params.bb_k)
        self.adx = ADX(params.adx_period)
        self.atr = ATR(params.atr_period)
        self._prev_close: float | None = None

    def on_bar(self, bar: Bar, context: Context) -> Signal:
        bands = self.bb.update(bar.close)
        adx = self.adx.update(bar.high, bar.low, bar.close)
        atr = self.atr.update(bar.high, bar.low, bar.close)
        prev = self._prev_close
        self._prev_close = bar.close
        if bands is None or adx is None or not atr or prev is None:
            return Signal(Action.FLAT)
        if adx >= self.p.adx_max:      # trop de tendance -> pas de fade
            return Signal(Action.FLAT)

        lower, mid, upper = bands
        stop_dist = self.p.atr_stop_mult * atr
        max_tgt = stop_dist * self.p.rr_ratio

        # Sous la bande basse et retour vers le haut -> long, target = bande mediane.
        if prev < lower and bar.close > prev:
            tgt = min(max_tgt, abs(mid - bar.close))
            if tgt > 0:
                return Signal(Action.LONG, stop_dist=stop_dist, target_dist=tgt,
                              confidence=1.0, reason="BB fade bas (range)")
        # Au-dessus de la bande haute et retour vers le bas -> short.
        if prev > upper and bar.close < prev:
            tgt = min(max_tgt, abs(bar.close - mid))
            if tgt > 0:
                return Signal(Action.SHORT, stop_dist=stop_dist, target_dist=tgt,
                              confidence=1.0, reason="BB fade haut (range)")
        return Signal(Action.FLAT)
