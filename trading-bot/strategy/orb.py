"""Opening Range Breakout (ORB).

Definit le range (haut/bas) des N premieres minutes de la session RTH, puis prend
la cassure : long au-dessus du haut du range, short en dessous du bas. Un seul trade
par jour et par direction. Stop = ATR, target = R x stop. Classique et robuste pour
les index futures sur l'ouverture US.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from .base import Action, Bar, Context, Signal
from .indicators import ATR


@dataclass
class ORBParams:
    session_start: time = time(9, 30)
    orb_minutes: int = 15         # duree de l'opening range
    atr_period: int = 14
    atr_stop_mult: float = 1.0
    rr_ratio: float = 2.0
    max_entry_minutes: int = 120  # ne prend plus d'entree apres N min de session
    tick_size: float = 0.25


class ORBStrategy:
    def __init__(self, params: ORBParams):
        self.p = params
        self.atr = ATR(params.atr_period)
        self._day = None
        self._hi = None
        self._lo = None
        self._range_done = False
        self._traded_long = False
        self._traded_short = False

    def _reset(self, day):
        self._day = day
        self._hi = None
        self._lo = None
        self._range_done = False
        self._traded_long = False
        self._traded_short = False

    def _minutes_since_open(self, t: time) -> int:
        return (t.hour - self.p.session_start.hour) * 60 + (t.minute - self.p.session_start.minute)

    def on_bar(self, bar: Bar, context: Context) -> Signal:
        atr = self.atr.update(bar.high, bar.low, bar.close)
        t = bar.time.time()
        if bar.time.date() != self._day:
            self._reset(bar.time.date())

        mins = self._minutes_since_open(t)
        if mins < 0:
            return Signal(Action.FLAT)  # avant l'ouverture

        # Construction de l'opening range.
        if mins < self.p.orb_minutes:
            self._hi = bar.high if self._hi is None else max(self._hi, bar.high)
            self._lo = bar.low if self._lo is None else min(self._lo, bar.low)
            return Signal(Action.FLAT)
        self._range_done = True

        if not atr or self._hi is None or mins > self.p.max_entry_minutes:
            return Signal(Action.FLAT)

        stop_dist = self.p.atr_stop_mult * atr
        tgt_dist = stop_dist * self.p.rr_ratio

        if not self._traded_long and bar.close > self._hi:
            self._traded_long = True
            return Signal(Action.LONG, stop_dist=stop_dist, target_dist=tgt_dist,
                          confidence=1.0, reason="ORB cassure haussiere")
        if not self._traded_short and bar.close < self._lo:
            self._traded_short = True
            return Signal(Action.SHORT, stop_dist=stop_dist, target_dist=tgt_dist,
                          confidence=1.0, reason="ORB cassure baissiere")
        return Signal(Action.FLAT)
