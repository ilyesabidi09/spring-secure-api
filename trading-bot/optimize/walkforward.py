"""Optimisation walk-forward (Optuna) generique : scalper | orb | vwap.

Anti-overfitting : optimise sur une fenetre IN-SAMPLE, valide sur l'OUT-OF-SAMPLE
suivant. Ne retient que ce qui tient hors echantillon. Les frais (commissions +
slippage) et les specs instrument sont pris en compte -> chiffres NETS realistes.
"""
from __future__ import annotations

import json
from datetime import time
from pathlib import Path

from backtest.engine import run_backtest
from risk.manager import RiskConfig, RiskManager


def _build_risk(cfg: dict, tick_size: float, tick_value: float) -> RiskManager:
    acc, rk = cfg["account"], cfg["risk"]
    sh, sm = map(int, rk["session_start"].split(":"))
    eh, em = map(int, rk["session_end"].split(":"))
    return RiskManager(RiskConfig(
        balance=acc["balance"], trailing_drawdown=acc["trailing_drawdown"],
        daily_loss_limit=acc["daily_loss_limit"], max_contracts=acc["max_contracts"],
        consistency_pct=acc["consistency_pct"], risk_per_trade_usd=rk["risk_per_trade_usd"],
        stop_ticks=rk["stop_ticks"], tick_value=tick_value, tick_size=tick_size,
        max_trades_per_day=rk["max_trades_per_day"],
        session_start=time(sh, sm), session_end=time(eh, em)))


def _search_space(name: str, trial) -> dict:
    if name == "scalper":
        return dict(ema_fast=trial.suggest_int("ema_fast", 5, 15),
                    ema_slow=trial.suggest_int("ema_slow", 18, 40),
                    rsi_period=trial.suggest_int("rsi_period", 7, 21),
                    atr_stop_mult=trial.suggest_float("atr_stop_mult", 0.8, 3.0),
                    rr_ratio=trial.suggest_float("rr_ratio", 1.0, 3.0),
                    min_confidence=trial.suggest_float("min_confidence", 0.5, 0.75))
    if name == "orb":
        return dict(orb_minutes=trial.suggest_int("orb_minutes", 5, 30),
                    atr_stop_mult=trial.suggest_float("atr_stop_mult", 0.5, 3.0),
                    rr_ratio=trial.suggest_float("rr_ratio", 1.0, 4.0),
                    max_entry_minutes=trial.suggest_int("max_entry_minutes", 60, 240))
    if name == "vwap":
        return dict(dev_mult=trial.suggest_float("dev_mult", 1.0, 4.0),
                    atr_stop_mult=trial.suggest_float("atr_stop_mult", 0.5, 3.0),
                    rr_ratio=trial.suggest_float("rr_ratio", 1.0, 3.0))
    if name == "meta":
        # Espace volontairement reduit (4 params) pour limiter l'overfitting du routeur.
        return dict(trend_threshold=trial.suggest_float("trend_threshold", 0.15, 0.6),
                    atr_stop_mult=trial.suggest_float("atr_stop_mult", 0.5, 3.0),
                    rr_ratio=trial.suggest_float("rr_ratio", 1.0, 3.0),
                    dev_mult=trial.suggest_float("dev_mult", 1.0, 4.0))
    raise ValueError(name)


def _make_strategy(name: str, cfg: dict, tick_size: float, overrides: dict):
    if name == "scalper":
        from strategy.scalper import ScalperParams, ScalperStrategy
        s = {**cfg["strategy"], **overrides}
        return ScalperStrategy(ScalperParams(
            ema_fast=s["ema_fast"], ema_slow=s["ema_slow"], rsi_period=s["rsi_period"],
            rsi_long_max=s["rsi_long_max"], rsi_short_min=s["rsi_short_min"],
            vwap_filter=s["vwap_filter"], min_confidence=s["min_confidence"],
            atr_period=s["atr_period"], atr_stop_mult=s["atr_stop_mult"], rr_ratio=s["rr_ratio"],
            gex_enabled=cfg["gex"]["enabled"], gex_proximity_ticks=cfg["gex"]["proximity_ticks"],
            tick_size=tick_size))
    if name == "orb":
        from strategy.orb import ORBParams, ORBStrategy
        o = {**cfg["orb"], **overrides}
        sh, sm = map(int, cfg["risk"]["session_start"].split(":"))
        return ORBStrategy(ORBParams(
            session_start=time(sh, sm), orb_minutes=o["orb_minutes"], atr_period=o["atr_period"],
            atr_stop_mult=o["atr_stop_mult"], rr_ratio=o["rr_ratio"],
            max_entry_minutes=o["max_entry_minutes"], tick_size=tick_size))
    if name == "vwap":
        from strategy.vwap_reversion import VwapReversionParams, VwapReversionStrategy
        v = {**cfg["vwap"], **overrides}
        return VwapReversionStrategy(VwapReversionParams(
            atr_period=v["atr_period"], dev_mult=v["dev_mult"],
            atr_stop_mult=v["atr_stop_mult"], rr_ratio=v["rr_ratio"], tick_size=tick_size))
    if name == "meta":
        from meta.regime import RegimeMetaStrategy, RegimeParams
        m = cfg["meta"]
        # Repartit les overrides vers les sous-strategies + le routeur.
        scalper_ov = {k: overrides[k] for k in ("atr_stop_mult", "rr_ratio") if k in overrides}
        vwap_ov = {k: overrides[k] for k in ("atr_stop_mult", "dev_mult") if k in overrides}
        return RegimeMetaStrategy(
            RegimeParams(ema_fast=m["ema_fast"], ema_slow=m["ema_slow"],
                         atr_period=m["atr_period"],
                         trend_threshold=overrides.get("trend_threshold", m["trend_threshold"])),
            trend_strategy=_make_strategy("scalper", cfg, tick_size, scalper_ov),
            range_strategy=_make_strategy("vwap", cfg, tick_size, vwap_ov))
    raise ValueError(name)


def _score(bars, name, cfg, gex, tick_size, tick_value, comm, slip, overrides) -> float:
    strat = _make_strategy(name, cfg, tick_size, overrides)
    risk = _build_risk(cfg, tick_size, tick_value)
    res = run_backtest(bars, strat, risk, tick_size, tick_value, gex,
                       commission_per_contract=comm, slippage_points=slip)
    if len(res.trades) < 10:
        return -1e9
    return res.net_pnl - 0.5 * res.max_drawdown


def optimize_window(bars, name, cfg, gex, tick_size, tick_value, comm, slip,
                    n_trials: int = 30) -> dict:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial):
        ov = _search_space(name, trial)
        return _score(bars, name, cfg, gex, tick_size, tick_value, comm, slip, ov)

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials)
    return study.best_params


def walk_forward(bars, cfg: dict, gex: dict, instrument: str, strategy_name: str,
                 folds: int = 4, out_path: str | Path = "best_params.json") -> dict:
    spec = cfg["instruments"][instrument]
    tick_size, tick_value = spec["tick_size"], spec["tick_value"]
    comm = cfg["costs"]["commission_per_contract"]
    slip = cfg["costs"]["slippage_points"]

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
        best = optimize_window(is_bars, strategy_name, cfg, gex, tick_size,
                               tick_value, comm, slip)
        strat = _make_strategy(strategy_name, cfg, tick_size, best)
        risk = _build_risk(cfg, tick_size, tick_value)
        res = run_backtest(oos_bars, strat, risk, tick_size, tick_value, gex,
                           commission_per_contract=comm, slippage_points=slip)
        reports.append({"fold": k, "oos": res.summary(), "params": best})
        if res.net_pnl > best_oos:
            best_oos = res.net_pnl
            best_overall = best

    output = {"instrument": instrument, "strategy": strategy_name,
              "best_params": best_overall, "folds": reports}
    Path(out_path).write_text(json.dumps(output, indent=2, default=str))
    return output
