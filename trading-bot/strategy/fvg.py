"""Fair Value Gap (FVG) retest reversal — proxy automatisable des concepts ICT
(FVG / Balanced Price Range).

FVG haussier sur 3 barres : bar[i-2].high < bar[i].low  -> zone d'imbalance [h2, l0]
qui agit comme SUPPORT. FVG baissier : bar[i-2].low > bar[i].high -> zone [h0, l2]
qui agit comme RESISTANCE.

Trade (reversal sur retest) :
- Prix redescend dans un FVG haussier puis cloture au-dessus -> LONG (support tenu).
- Prix remonte dans un FVG baissier puis cloture en dessous -> SHORT (resistance tenue).
La zone est "consommee" apres test. Stops ATR ; target = rr x stop.
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import Action, Bar, Context, Signal
from .indicators import ATR


@dataclass
class FVGParams:
    atr_period: int = 14
    atr_stop_mult: float = 1.0
    rr_ratio: float = 2.0
    max_age: int = 120          # une FVG expire apres N barres sans test
    tick_size: float = 0.25


class FVGStrategy:
    def __init__(self, params: FVGParams):
        self.p = params
        self.atr = ATR(params.atr_period)
        self._b1 = None  # bar[i-1]
        self._b2 = None  # bar[i-2]
        self.bull_zone = None   # (low, high, age)  support
        self.bear_zone = None   # (low, high, age)  resistance

    def on_bar(self, bar: Bar, context: Context) -> Signal:
        atr = self.atr.update(bar.high, bar.low, bar.close)
        b1, b2 = self._b1, self._b2
        self._b2, self._b1 = self._b1, bar

        # Vieillissement / expiration des zones.
        self.bull_zone = self._age(self.bull_zone)
        self.bear_zone = self._age(self.bear_zone)

        # Detection d'une nouvelle FVG (sur b2, b1, bar).
        if b2 is not None:
            if b2.high < bar.low:                       # gap haussier
                self.bull_zone = (b2.high, bar.low, 0)
            if b2.low > bar.high:                       # gap baissier
                self.bear_zone = (bar.high, b2.low, 0)

        if not atr:
            return Signal(Action.FLAT)
        stop_dist = self.p.atr_stop_mult * atr
        tgt_dist = stop_dist * self.p.rr_ratio

        # Retest d'un support (FVG haussier) : la barre a plonge dans la zone puis cloture au-dessus.
        if self.bull_zone is not None:
            lo, hi, _ = self.bull_zone
            if bar.low <= hi and bar.close > lo and bar.close >= bar.open:
                self.bull_zone = None
                return Signal(Action.LONG, stop_dist=stop_dist, target_dist=tgt_dist,
                              confidence=1.0, reason="FVG support retest (long)")
        # Retest d'une resistance (FVG baissier).
        if self.bear_zone is not None:
            lo, hi, _ = self.bear_zone
            if bar.high >= lo and bar.close < hi and bar.close <= bar.open:
                self.bear_zone = None
                return Signal(Action.SHORT, stop_dist=stop_dist, target_dist=tgt_dist,
                              confidence=1.0, reason="FVG resistance retest (short)")
        return Signal(Action.FLAT)

    def _age(self, zone):
        if zone is None:
            return None
        lo, hi, age = zone
        return None if age + 1 > self.p.max_age else (lo, hi, age + 1)
