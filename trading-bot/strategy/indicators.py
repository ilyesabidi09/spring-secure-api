"""Indicateurs techniques minimalistes (sans dependance externe lourde)."""
from __future__ import annotations

from collections import deque


class EMA:
    """Moyenne mobile exponentielle incrementale."""

    def __init__(self, period: int):
        self.k = 2.0 / (period + 1)
        self.value: float | None = None

    def update(self, price: float) -> float:
        if self.value is None:
            self.value = price
        else:
            self.value = price * self.k + self.value * (1 - self.k)
        return self.value


class RSI:
    """RSI de Wilder, incremental."""

    def __init__(self, period: int):
        self.period = period
        self.prev: float | None = None
        self.avg_gain = 0.0
        self.avg_loss = 0.0
        self.count = 0

    def update(self, price: float) -> float | None:
        if self.prev is None:
            self.prev = price
            return None
        change = price - self.prev
        self.prev = price
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        self.count += 1
        if self.count <= self.period:
            self.avg_gain += gain / self.period
            self.avg_loss += loss / self.period
            if self.count < self.period:
                return None
        else:
            self.avg_gain = (self.avg_gain * (self.period - 1) + gain) / self.period
            self.avg_loss = (self.avg_loss * (self.period - 1) + loss) / self.period
        if self.avg_loss == 0:
            return 100.0
        rs = self.avg_gain / self.avg_loss
        return 100.0 - 100.0 / (1 + rs)


class ATR:
    """Average True Range (Wilder), incremental. Mesure la volatilite pour
    dimensionner les stops proportionnellement au marche (indispensable quand on
    passe du S&P ~7400 au Nasdaq ~25000)."""

    def __init__(self, period: int):
        self.period = period
        self.prev_close: float | None = None
        self.value: float | None = None
        self.count = 0
        self._acc = 0.0

    def update(self, high: float, low: float, close: float) -> float | None:
        if self.prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - self.prev_close), abs(low - self.prev_close))
        self.prev_close = close
        self.count += 1
        if self.count <= self.period:
            self._acc += tr
            if self.count == self.period:
                self.value = self._acc / self.period
            return self.value
        self.value = (self.value * (self.period - 1) + tr) / self.period
        return self.value


class SessionVWAP:
    """VWAP remis a zero a chaque nouvelle session (jour)."""

    def __init__(self):
        self.cum_pv = 0.0
        self.cum_vol = 0.0
        self._day = None

    def update(self, day, price: float, volume: float) -> float:
        if day != self._day:
            self._day = day
            self.cum_pv = 0.0
            self.cum_vol = 0.0
        vol = volume if volume > 0 else 1.0
        self.cum_pv += price * vol
        self.cum_vol += vol
        return self.cum_pv / self.cum_vol if self.cum_vol else price
