"""Strategie de scalping : EMA cross + VWAP + RSI, stops dimensionnes a l'ATR,
filtree par GEX. Stops en POINTS (ATR) -> valide sur S&P comme sur Nasdaq."""
from __future__ import annotations

from dataclasses import dataclass

from .base import Action, Bar, Context, Signal
from .gex import apply_gex_filter
from .indicators import ATR, EMA, RSI, SessionVWAP


@dataclass
class ScalperParams:
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    rsi_long_max: float = 65.0
    rsi_short_min: float = 35.0
    vwap_filter: bool = True
    min_confidence: float = 0.55
    atr_period: int = 14
    atr_stop_mult: float = 1.5   # stop = 1.5 x ATR
    rr_ratio: float = 1.5        # target = 1.5 x stop
    gex_enabled: bool = True
    gex_proximity_ticks: int = 20
    tick_size: float = 0.25


class ScalperStrategy:
    def __init__(self, params: ScalperParams):
        self.p = params
        self.ema_fast = EMA(params.ema_fast)
        self.ema_slow = EMA(params.ema_slow)
        self.rsi = RSI(params.rsi_period)
        self.atr = ATR(params.atr_period)
        self.vwap = SessionVWAP()
        self._prev_fast: float | None = None
        self._prev_slow: float | None = None

    def on_bar(self, bar: Bar, context: Context) -> Signal:
        fast = self.ema_fast.update(bar.close)
        slow = self.ema_slow.update(bar.close)
        rsi = self.rsi.update(bar.close)
        atr = self.atr.update(bar.high, bar.low, bar.close)
        vwap = self.vwap.update(bar.time.date(), bar.close, bar.volume)

        signal = Signal(Action.FLAT)

        if self._prev_fast is not None and rsi is not None and atr:
            stop_dist = self.p.atr_stop_mult * atr
            tgt_dist = stop_dist * self.p.rr_ratio
            crossed_up = self._prev_fast <= self._prev_slow and fast > slow
            crossed_dn = self._prev_fast >= self._prev_slow and fast < slow

            if crossed_up and rsi <= self.p.rsi_long_max:
                if not self.p.vwap_filter or bar.close >= vwap:
                    signal = Signal(Action.LONG, stop_dist=stop_dist, target_dist=tgt_dist,
                                    confidence=0.6, reason="EMA up + VWAP/RSI ok")
            elif crossed_dn and rsi >= self.p.rsi_short_min:
                if not self.p.vwap_filter or bar.close <= vwap:
                    signal = Signal(Action.SHORT, stop_dist=stop_dist, target_dist=tgt_dist,
                                    confidence=0.6, reason="EMA down + VWAP/RSI ok")

        self._prev_fast, self._prev_slow = fast, slow

        if self.p.gex_enabled and signal.action != Action.FLAT:
            signal = apply_gex_filter(signal, bar.close, context.gex_levels,
                                      self.p.gex_proximity_ticks, self.p.tick_size)

        if signal.action != Action.FLAT and signal.confidence < self.p.min_confidence:
            return Signal(Action.FLAT, reason=f"confidence {signal.confidence:.2f} < min")
        return signal
