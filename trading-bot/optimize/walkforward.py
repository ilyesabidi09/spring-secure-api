"""Optimisation walk-forward avec Optuna.

Principe anti-overfitting : on optimise les parametres sur une fenetre IN-SAMPLE,
puis on valide sur la fenetre OUT-OF-SAMPLE suivante. On n'avance que les jeux de
parametres qui tiennent hors echantillon. Le meilleur jeu global est ecrit dans
best_params.json, recharge par le live -> c'est la boucle "qui s'ameliore".
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import time
from pathlib import Path

from backtest.engine import run_backtest
from risk.manager import RiskConfig, RiskManager
from strategy.scalper import ScalperParams, ScalperStrategy


def _build_risk(cfg: dict) -> RiskManager:
    acc, rk = cfg["account"], cfg["risk"]
    sh, sm = map(int, rk["session_start"].split(":"))
    eh, em = map(int, rk["session_end"].split(":"))
    return RiskManager(RiskConfig(
        balance=acc["balance"], trailing_drawdown=acc["trailing_drawdown"],
        daily_loss_limit=acc["daily_loss_limit"], max_contracts=acc["max_contracts"],
        consistency_pct=acc["consistency_pct"], risk_per_trade_usd=rk["risk_per_trade_usd"],
        stop_ticks=rk["stop_ticks"], tick_value=cfg["tick_value"],
        max_trades_per_day=rk["max_trades_per_day"],
        session_start=time(sh, sm), session_end=time(eh, em),
    ))


def _score(bars, params: ScalperParams, cfg: dict, gex: dict) -> float:
    strat = ScalperStrategy(params)
    risk = _build_risk(cfg)
    res = run_backtest(bars, strat, risk, cfg["tick_size"], cfg["tick_value"], gex)
    if len(res.trades) < 5:      # trop peu de trades = non significatif
        return -1e9
    # objectif = expectancy penalisee par le drawdown
    return res.net_pnl - 0.5 * res.max_drawdown


def optimize_window(bars, cfg: dict, gex: dict, n_trials: int = 40) -> ScalperParams:
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial):
        params = ScalperParams(
            ema_fast=trial.suggest_int("ema_fast", 5, 15),
            ema_slow=trial.suggest_int("ema_slow", 18, 40),
            rsi_period=trial.suggest_int("rsi_period", 7, 21),
            stop_ticks=trial.suggest_int("stop_ticks", 6, 20),
            target_ticks=trial.suggest_int("target_ticks", 8, 30),
            min_confidence=trial.suggest_float("min_confidence", 0.5, 0.75),
            tick_size=cfg["tick_size"],
            gex_enabled=cfg["gex"]["enabled"],
            gex_proximity_ticks=cfg["gex"]["proximity_ticks"],
        )
        return _score(bars, params, cfg, gex)

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials)
    best = study.best_params
    return ScalperParams(
        ema_fast=best["ema_fast"], ema_slow=best["ema_slow"],
        rsi_period=best["rsi_period"], stop_ticks=best["stop_ticks"],
        target_ticks=best["target_ticks"], min_confidence=best["min_confidence"],
        tick_size=cfg["tick_size"], gex_enabled=cfg["gex"]["enabled"],
        gex_proximity_ticks=cfg["gex"]["proximity_ticks"],
    )


def walk_forward(bars, cfg: dict, gex: dict, folds: int = 4,
                 out_path: str | Path = "best_params.json") -> dict:
    """Decoupe en `folds`, optimise sur chaque IS, valide sur l'OS suivant."""
    n = len(bars)
    win = n // (folds + 1)
    reports = []
    best_overall = None
    best_oos = -1e18

    for k in range(folds):
        is_bars = bars[k * win:(k + 1) * win]
        oos_bars = bars[(k + 1) * win:(k + 2) * win]
        if len(oos_bars) < 20:
            break
        params = optimize_window(is_bars, cfg, gex)
        # validation out-of-sample
        strat = ScalperStrategy(params)
        risk = _build_risk(cfg)
        res = run_backtest(oos_bars, strat, risk, cfg["tick_size"],
                           cfg["tick_value"], gex)
        reports.append({"fold": k, "oos": res.summary(), "params": asdict(params)})
        if res.net_pnl > best_oos:
            best_oos = res.net_pnl
            best_overall = asdict(params)

    output = {"best_params": best_overall, "folds": reports}
    Path(out_path).write_text(json.dumps(output, indent=2, default=str))
    return output
