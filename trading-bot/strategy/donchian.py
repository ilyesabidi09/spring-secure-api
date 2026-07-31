"""Donchian channel breakout (facon Turtle) — proxy algorithmique du "trendline
breakout". Cassure du plus haut/plus bas des N barres precedentes = entree momentum.
Filtre ADX optionnel pour ne prendre que les cassures avec de la tendance.
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import Action, Bar, Context, Signal
from .indicators import ADX, ATR, Donchian


@dataclass
class DonchianParams:
    channel_period: int = 20
    adx_period: int = 14
    adx_min: float = 20.0        # ne prendre la cassure que si ADX > adx_min
    atr_period: int = 14
    atr_stop_mult: float = 1.5
    rr_ratio: float = 2.0
    tick_size: float = 0.25


class DonchianStrategy:
    def __init__(self, params: DonchianParams):
        self.p = params
        self.dc = Donchian(params.channel_period)
        self.adx = ADX(params.adx_period)
        self.atr = ATR(params.atr_period)

    def on_bar(self, bar: Bar, context: Context) -> Signal:
        channel = self.dc.channel()        # canal des barres PRECEDENTES
        adx = self.adx.update(bar.high, bar.low, bar.close)
        atr = self.atr.update(bar.high, bar.low, bar.close)
        self.dc.update(bar.high, bar.low)  # inclure la barre courante APRES lecture

        if channel is None or adx is None or not atr:
            return Signal(Action.FLAT)
        low_ch, high_ch = channel
        if adx < self.p.adx_min:
            return Signal(Action.FLAT)

        stop_dist = self.p.atr_stop_mult * atr
        tgt_dist = stop_dist * self.p.rr_ratio

        if bar.close > high_ch:
            return Signal(Action.LONG, stop_dist=stop_dist, target_dist=tgt_dist,
                          confidence=1.0, reason="Donchian cassure haussiere")
        if bar.close < low_ch:
            return Signal(Action.SHORT, stop_dist=stop_dist, target_dist=tgt_dist,
                          confidence=1.0, reason="Donchian cassure baissiere")
        return Signal(Action.FLAT)
