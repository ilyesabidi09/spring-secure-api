"""Test du routeur de regime : verifie qu'il bascule bien momentum/reversion
selon la force de tendance, et qu'il garde les deux sous-strategies a jour."""
from datetime import datetime

from meta.regime import RegimeMetaStrategy, RegimeParams
from strategy.base import Action, Bar, Context, Signal


class _Stub:
    """Sous-strategie factice qui renvoie toujours la meme action et compte les appels."""
    def __init__(self, action):
        self.action = action
        self.calls = 0

    def on_bar(self, bar, context):
        self.calls += 1
        return Signal(self.action, stop_dist=10, target_dist=15, confidence=1.0)


def _bar(t, price):
    return Bar(datetime(2026, 1, 5, 10, t % 60), price, price + 1, price - 1, price, 100)


def test_les_deux_sous_strategies_sont_toujours_appelees():
    trend, rng = _Stub(Action.LONG), _Stub(Action.SHORT)
    meta = RegimeMetaStrategy(RegimeParams(ema_fast=2, ema_slow=3, atr_period=2,
                                           trend_threshold=1.0), trend, rng)
    for i in range(10):
        meta.on_bar(_bar(i, 100 + i), Context())
    assert trend.calls == 10 and rng.calls == 10  # etat garde chaud


def test_bascule_momentum_en_forte_tendance():
    trend, rng = _Stub(Action.LONG), _Stub(Action.SHORT)
    meta = RegimeMetaStrategy(RegimeParams(ema_fast=2, ema_slow=3, atr_period=2,
                                           trend_threshold=0.3), trend, rng)
    sig = None
    for i in range(20):  # prix en forte hausse reguliere -> tendance
        sig = meta.on_bar(_bar(i, 100 + i * 5), Context())
    assert meta.last_regime == "trend" and sig.action == Action.LONG
