"""RSI(2) mean-reversion facon Larry Connors, adapte intraday.

Idee (edge mean-reversion documente sur les indices) : n'acheter les creux que dans
une tendance de fond haussiere, et ne vendre les pics que dans une tendance baissiere.
- Filtre de tendance : SMA longue (ex. 200). Long seulement si close > SMA ; short si close < SMA.
- Declencheur : RSI(2) en zone extreme (survente pour long, surachat pour short).
- Stops ATR, target = rr x stop.
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import Action, Bar, Context, Signal
from .indicators import ATR, RSI, SMA


@dataclass
class RSI2Params:
    rsi_period: int = 2
    oversold: float = 10.0
    overbought: float = 90.0
    trend_period: int = 200
    atr_period: int = 14
    atr_stop_mult: float = 1.5
    rr_ratio: float = 1.5
    tick_size: float = 0.25


class RSI2Strategy:
    def __init__(self, params: RSI2Params):
        self.p = params
        self.rsi = RSI(params.rsi_period)
        self.sma = SMA(params.trend_period)
        self.atr = ATR(params.atr_period)

    def on_bar(self, bar: Bar, context: Context) -> Signal:
        rsi = self.rsi.update(bar.close)
        trend = self.sma.update(bar.close)
        atr = self.atr.update(bar.high, bar.low, bar.close)
        if rsi is None or trend is None or not atr:
            return Signal(Action.FLAT)

        stop_dist = self.p.atr_stop_mult * atr
        tgt_dist = stop_dist * self.p.rr_ratio

        # Long : creux (RSI bas) dans une tendance haussiere.
        if bar.close > trend and rsi <= self.p.oversold:
            return Signal(Action.LONG, stop_dist=stop_dist, target_dist=tgt_dist,
                          confidence=1.0, reason="RSI2 survente en tendance haussiere")
        # Short : pic (RSI haut) dans une tendance baissiere.
        if bar.close < trend and rsi >= self.p.overbought:
            return Signal(Action.SHORT, stop_dist=stop_dist, target_dist=tgt_dist,
                          confidence=1.0, reason="RSI2 surachat en tendance baissiere")
        return Signal(Action.FLAT)
