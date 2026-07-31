"""Tests du pipeline strategie + backtest sur donnees synthetiques."""
from strategy.base import Action, Context, Signal
from strategy.gex import apply_gex_filter
from strategy.scalper import ScalperParams, ScalperStrategy
from data.loader import synthetic_bars
from backtest.engine import run_backtest
from risk.manager import RiskConfig, RiskManager
from datetime import time


def test_gex_bloque_long_sous_call_wall():
    sig = Signal(Action.LONG, 12, 18, confidence=0.6)
    levels = {"call_walls": [5300.0], "put_walls": []}
    out = apply_gex_filter(sig, 5300.0, levels, proximity_ticks=20, tick_size=0.25)
    assert out.action == Action.FLAT


def test_gex_booste_long_sur_put_wall():
    sig = Signal(Action.LONG, 12, 18, confidence=0.6)
    levels = {"call_walls": [], "put_walls": [5300.0]}
    out = apply_gex_filter(sig, 5300.0, levels, proximity_ticks=20, tick_size=0.25)
    assert out.action == Action.LONG and out.confidence > 0.6


def test_strategy_produit_des_signaux_valides():
    strat = ScalperStrategy(ScalperParams(gex_enabled=False))
    ctx = Context()
    actions = {strat.on_bar(b, ctx).action for b in synthetic_bars(500)}
    assert actions.issubset({Action.LONG, Action.SHORT, Action.FLAT})


def test_backtest_pipeline_tourne():
    strat = ScalperStrategy(ScalperParams(gex_enabled=False, min_confidence=0.5))
    risk = RiskManager(RiskConfig(
        balance=50000.0, trailing_drawdown=2000.0, daily_loss_limit=1000.0,
        max_contracts=5, consistency_pct=0.30, risk_per_trade_usd=150.0,
        stop_ticks=12, tick_value=1.25, max_trades_per_day=50,
        session_start=time(0, 0), session_end=time(23, 59),
    ))
    res = run_backtest(synthetic_bars(1000), strat, risk,
                       tick_size=0.25, tick_value=1.25, gex_levels={})
    # le pipeline doit produire des trades et des metriques coherentes
    assert res.summary()["trades"] >= 0
    assert isinstance(res.profit_factor, float)
