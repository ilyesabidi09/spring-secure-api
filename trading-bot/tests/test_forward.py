"""Parite de l'agregateur temps-reel avec le rsampling batch, + smoke-test du
forward-tester (meme chemin de decision que le live)."""
from datetime import datetime

from config import load_config
from data.loader import BarAggregator, resample_bars
from forward_test import ForwardTester
from strategy.base import Bar


def _series(n):
    return [Bar(datetime(2026, 1, 5, 9, 30) .replace(minute=(30 + i) % 60,
                                                     hour=9 + (30 + i) // 60),
               100 + i, 101 + i, 99 + i, 100 + i, 10) for i in range(n)]


def test_aggregator_matche_resample_bars():
    bars = _series(23)   # 23 barres 1-min
    agg = BarAggregator(5)
    streamed = [b for b in (agg.add(x) for x in bars) if b is not None]
    batch = resample_bars(bars, 5)
    # le streaming n'a pas encore emis le dernier bucket incomplet -> compare les communs
    assert len(streamed) == len(batch) - 1
    for a, b in zip(streamed, batch):
        assert (a.open, a.high, a.low, a.close, a.volume) == \
               (b.open, b.high, b.low, b.close, b.volume)


def test_forward_tester_smoke():
    cfg = load_config()
    ft = ForwardTester(cfg, "MNQ", verbose=False)
    # flux 1-min synthetique en tendance -> doit tourner sans erreur et produire un resume
    for i in range(600):
        t = datetime(2026, 1, 5, 9, 30)
        b = Bar(t.replace(minute=i % 60, hour=9 + i // 60),
                20000 + i, 20002 + i, 19999 + i, 20001 + i, 50)
        ft.feed_1m(b)
    s = ft.summary()
    assert "net_pnl" in s and s["trades"] >= 0
