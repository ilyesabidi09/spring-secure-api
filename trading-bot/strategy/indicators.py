"""Indicateurs techniques minimalistes (sans dependance externe lourde)."""
from __future__ import annotations

import statistics
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


class SMA:
    """Moyenne mobile simple sur fenetre glissante (None tant que non remplie)."""

    def __init__(self, period: int):
        self.period = period
        self.buf: deque[float] = deque(maxlen=period)
        self._sum = 0.0

    def update(self, price: float) -> float | None:
        if len(self.buf) == self.period:
            self._sum -= self.buf[0]
        self.buf.append(price)
        self._sum += price
        return self._sum / self.period if len(self.buf) == self.period else None


class Bollinger:
    """Bandes de Bollinger : (bas, milieu, haut) = SMA +/- k*ecart-type."""

    def __init__(self, period: int, k: float = 2.0):
        self.period = period
        self.k = k
        self.buf: deque[float] = deque(maxlen=period)

    def update(self, price: float):
        self.buf.append(price)
        if len(self.buf) < self.period:
            return None
        mid = statistics.fmean(self.buf)
        sd = statistics.pstdev(self.buf)
        return (mid - self.k * sd, mid, mid + self.k * sd)


class Donchian:
    """Canal de Donchian : plus haut/plus bas des N barres PRECEDENTES (exclut la
    barre courante) -> sert a detecter une cassure de range."""

    def __init__(self, period: int):
        self.period = period
        self.highs: deque[float] = deque(maxlen=period)
        self.lows: deque[float] = deque(maxlen=period)

    def channel(self):
        if len(self.highs) < self.period:
            return None
        return (min(self.lows), max(self.highs))

    def update(self, high: float, low: float) -> None:
        self.highs.append(high)
        self.lows.append(low)


class ADX:
    """Average Directional Index (Wilder) : force de tendance (0-100).
    ADX faible = range (bon pour mean-reversion), ADX eleve = tendance."""

    def __init__(self, period: int):
        self.period = period
        self.prev_high = None
        self.prev_low = None
        self.prev_close = None
        self._tr = 0.0
        self._plus = 0.0
        self._minus = 0.0
        self._count = 0
        self._adx: float | None = None
        self._dx_acc = 0.0
        self._dx_n = 0

    def update(self, high: float, low: float, close: float) -> float | None:
        if self.prev_close is None:
            self.prev_high, self.prev_low, self.prev_close = high, low, close
            return None
        up = high - self.prev_high
        dn = self.prev_low - low
        plus_dm = up if (up > dn and up > 0) else 0.0
        minus_dm = dn if (dn > up and dn > 0) else 0.0
        tr = max(high - low, abs(high - self.prev_close), abs(low - self.prev_close))
        self.prev_high, self.prev_low, self.prev_close = high, low, close

        p = self.period
        self._count += 1
        if self._count <= p:
            self._tr += tr
            self._plus += plus_dm
            self._minus += minus_dm
            if self._count < p:
                return None
        else:
            self._tr = self._tr - self._tr / p + tr
            self._plus = self._plus - self._plus / p + plus_dm
            self._minus = self._minus - self._minus / p + minus_dm

        if self._tr == 0:
            return self._adx
        di_plus = 100 * self._plus / self._tr
        di_minus = 100 * self._minus / self._tr
        denom = di_plus + di_minus
        dx = 100 * abs(di_plus - di_minus) / denom if denom else 0.0
        # ADX = moyenne de Wilder des DX
        if self._adx is None:
            self._dx_acc += dx
            self._dx_n += 1
            if self._dx_n == p:
                self._adx = self._dx_acc / p
        else:
            self._adx = (self._adx * (p - 1) + dx) / p
        return self._adx


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
