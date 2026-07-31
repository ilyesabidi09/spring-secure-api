"""Meta-strategie a base de regime : route entre momentum (scalper) et
mean-reversion (VWAP) selon la force de tendance du marche.

Indicateur de regime = |EMA_fast - EMA_slow| / ATR (force de tendance normalisee
par la volatilite). Au-dessus d'un seuil -> tendance -> on prend les signaux du
scalper (momentum). En dessous -> range -> on prend les signaux du VWAP (fade).

IMPORTANT : les deux sous-strategies sont mises a jour a CHAQUE barre (pour garder
leurs indicateurs "chauds"), mais une seule voit son signal execute selon le regime.
Le seuil est calibre en in-sample et applique a l'aveugle en out-of-sample (pas de
triche : la decision n'utilise que le passe).
"""
from __future__ import annotations

from dataclasses import dataclass

from strategy.base import Action, Bar, Context, Signal
from strategy.indicators import ATR, EMA


@dataclass
class RegimeParams:
    ema_fast: int = 20
    ema_slow: int = 50
    atr_period: int = 14
    trend_threshold: float = 1.0   # force de tendance mini pour basculer en momentum


class RegimeMetaStrategy:
    def __init__(self, params: RegimeParams, trend_strategy, range_strategy):
        self.p = params
        self.trend_strategy = trend_strategy   # scalper (momentum)
        self.range_strategy = range_strategy   # vwap (mean-reversion)
        self.ema_fast = EMA(params.ema_fast)
        self.ema_slow = EMA(params.ema_slow)
        self.atr = ATR(params.atr_period)
        self.last_regime = "none"

    def on_bar(self, bar: Bar, context: Context) -> Signal:
        f = self.ema_fast.update(bar.close)
        s = self.ema_slow.update(bar.close)
        a = self.atr.update(bar.high, bar.low, bar.close)

        # Toujours mettre a jour les deux sous-strategies (etat des indicateurs).
        sig_trend = self.trend_strategy.on_bar(bar, context)
        sig_range = self.range_strategy.on_bar(bar, context)

        if not a:
            return Signal(Action.FLAT)

        strength = abs(f - s) / a
        if strength >= self.p.trend_threshold:
            self.last_regime = "trend"
            return sig_trend
        self.last_regime = "range"
        return sig_range
