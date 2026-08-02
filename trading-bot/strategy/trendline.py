"""Trendline breakout MULTI-TIMEFRAME avec confirmations.

La trendline est detectee sur un timeframe SUPERIEUR (htf_minutes) et la cassure est
executee sur le timeframe des barres recues (exec, ex. M5/M15). "Les trendlines des
TF eleves sont les meilleures."

- Agregation interne des barres exec -> barres htf via data.loader.BarAggregator.
- Pivots (swing highs/lows fractals) detectes sur les barres htf.
- Trendlines diagonales : resistance = 2 derniers swing highs descendants ;
  support = 2 derniers swing lows montants. Axe x = TEMPS (minutes epoch) -> la ligne
  htf est evaluable a chaque barre d'execution.
- Confirmations : min_touches (respect historique), cassure en CLOTURE DE CORPS
  au-dela de la ligne (+ marge ATR, pas une meche), break & retest, stops ATR (exec),
  cible = rr x stop.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from data.loader import BarAggregator
from .base import Action, Bar, Context, Signal
from .indicators import ATR


@dataclass
class TrendlineParams:
    exec_minutes: int = 5         # timeframe d'execution (barres recues)
    htf_minutes: int = 30         # timeframe de detection de la trendline (>= exec)
    pivot_lookback: int = 4       # fractale sur barres htf
    min_touches: int = 3
    tol_atr: float = 0.6
    break_margin_atr: float = 0.1
    require_retest: bool = True
    retest_window: int = 20       # barres EXEC pour le retest
    atr_period: int = 14
    atr_stop_mult: float = 1.5
    rr_ratio: float = 2.0
    tick_size: float = 0.25


def _x(bar: Bar) -> float:
    return bar.time.timestamp() / 60.0   # minutes epoch (axe partage entre TF)


def _line_val(pair, x):
    (x1, p1), (x2, p2) = pair
    if x2 == x1:
        return p2
    return p2 + (p2 - p1) / (x2 - x1) * (x - x2)


class TrendlineBreakoutStrategy:
    def __init__(self, params: TrendlineParams):
        self.p = params
        self.atr = ATR(params.atr_period)
        self.htf_agg = BarAggregator(params.htf_minutes)
        self.htf_bars: deque[Bar] = deque(maxlen=2 * params.pivot_lookback + 1)
        self.swing_highs: deque = deque(maxlen=12)   # (x, price)
        self.swing_lows: deque = deque(maxlen=12)
        self.pending = None   # (dir, pair, expire_x_count)
        self._exec_count = -1

    def _on_htf_bar(self, hb: Bar):
        self.htf_bars.append(hb)
        L = self.p.pivot_lookback
        if len(self.htf_bars) == 2 * L + 1:
            mid = self.htf_bars[L]
            if mid.high == max(b.high for b in self.htf_bars):
                self.swing_highs.append((_x(mid), mid.high))
            if mid.low == min(b.low for b in self.htf_bars):
                self.swing_lows.append((_x(mid), mid.low))

    def _touches(self, pivots, pair, tol) -> int:
        return sum(1 for x, price in pivots if abs(price - _line_val(pair, x)) <= tol)

    def _res_line(self):
        if len(self.swing_highs) < 2:
            return None
        a, b = self.swing_highs[-2], self.swing_highs[-1]
        return (a, b) if b[1] < a[1] else None      # descendante

    def _sup_line(self):
        if len(self.swing_lows) < 2:
            return None
        a, b = self.swing_lows[-2], self.swing_lows[-1]
        return (a, b) if b[1] > a[1] else None       # montante

    def on_bar(self, bar: Bar, context: Context) -> Signal:
        self._exec_count += 1
        atr = self.atr.update(bar.high, bar.low, bar.close)
        hb = self.htf_agg.add(bar)
        if hb is not None:
            self._on_htf_bar(hb)

        if not atr:
            return Signal(Action.FLAT)

        stop_dist = self.p.atr_stop_mult * atr
        tgt = stop_dist * self.p.rr_ratio
        tol = self.p.tol_atr * atr
        margin = self.p.break_margin_atr * atr
        x = _x(bar)

        # ---- retest en attente ----
        if self.pending is not None:
            d, pair, expire = self.pending
            if self._exec_count > expire:
                self.pending = None
            else:
                lv = _line_val(pair, x)
                if d == "long" and bar.low <= lv + tol and bar.close > lv:
                    self.pending = None
                    return Signal(Action.LONG, stop_dist=stop_dist, target_dist=tgt,
                                  confidence=1.0, reason="Trendline HTF break+retest long")
                if d == "short" and bar.high >= lv - tol and bar.close < lv:
                    self.pending = None
                    return Signal(Action.SHORT, stop_dist=stop_dist, target_dist=tgt,
                                  confidence=1.0, reason="Trendline HTF break+retest short")
            return Signal(Action.FLAT)

        # ---- detection de cassure (cloture de corps au-dela de la ligne htf) ----
        res = self._res_line()
        if res is not None:
            lv = _line_val(res, x)
            if (self._touches(self.swing_highs, res, tol) >= self.p.min_touches
                    and bar.close > lv + margin and min(bar.open, bar.close) <= lv + 2 * tol):
                if self.p.require_retest:
                    self.pending = ("long", res, self._exec_count + self.p.retest_window)
                    return Signal(Action.FLAT)
                return Signal(Action.LONG, stop_dist=stop_dist, target_dist=tgt,
                              confidence=1.0, reason="Trendline HTF break long")

        sup = self._sup_line()
        if sup is not None:
            lv = _line_val(sup, x)
            if (self._touches(self.swing_lows, sup, tol) >= self.p.min_touches
                    and bar.close < lv - margin and max(bar.open, bar.close) >= lv - 2 * tol):
                if self.p.require_retest:
                    self.pending = ("short", sup, self._exec_count + self.p.retest_window)
                    return Signal(Action.FLAT)
                return Signal(Action.SHORT, stop_dist=stop_dist, target_dist=tgt,
                              confidence=1.0, reason="Trendline HTF break short")

        return Signal(Action.FLAT)
