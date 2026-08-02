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


def flatten_args(cfg: dict) -> dict:
    """Traduit le bloc config 'flatten' (regle prop firm) en kwargs run_backtest."""
    f = cfg.get("flatten")
    if not f:
        return {}
    def _t(s):
        h, m = map(int, s.split(":"))
        return time(h, m)
    return dict(flatten_from=_t(f["flatten_time"]),
                no_entry_from=_t(f["no_entry_from"]),
                no_entry_to=_t(f["no_entry_to"]))


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
    if name == "rsi2":
        return dict(oversold=trial.suggest_float("oversold", 2.0, 20.0),
                    overbought=trial.suggest_float("overbought", 80.0, 98.0),
                    trend_period=trial.suggest_int("trend_period", 50, 300),
                    atr_stop_mult=trial.suggest_float("atr_stop_mult", 0.8, 3.0),
                    rr_ratio=trial.suggest_float("rr_ratio", 1.0, 3.0))
    if name == "bollinger":
        return dict(bb_k=trial.suggest_float("bb_k", 1.5, 3.0),
                    adx_max=trial.suggest_float("adx_max", 15.0, 35.0),
                    atr_stop_mult=trial.suggest_float("atr_stop_mult", 0.5, 2.5),
                    rr_ratio=trial.suggest_float("rr_ratio", 1.0, 3.0))
    if name == "donchian":
        return dict(channel_period=trial.suggest_int("channel_period", 10, 60),
                    adx_min=trial.suggest_float("adx_min", 15.0, 35.0),
                    atr_stop_mult=trial.suggest_float("atr_stop_mult", 0.8, 3.0),
                    rr_ratio=trial.suggest_float("rr_ratio", 1.5, 4.0))
    if name == "fvg":
        return dict(atr_stop_mult=trial.suggest_float("atr_stop_mult", 0.5, 2.5),
                    rr_ratio=trial.suggest_float("rr_ratio", 1.5, 4.0),
                    max_age=trial.suggest_int("max_age", 30, 240))
    if name == "trendline":
        # exec_minutes / htf_minutes NON optimises (ils definissent la combinaison testee).
        return dict(pivot_lookback=trial.suggest_int("pivot_lookback", 3, 8),
                    min_touches=trial.suggest_int("min_touches", 2, 4),
                    tol_atr=trial.suggest_float("tol_atr", 0.3, 1.0),
                    break_margin_atr=trial.suggest_float("break_margin_atr", 0.0, 0.4),
                    require_retest=trial.suggest_categorical("require_retest", [True, False]),
                    atr_stop_mult=trial.suggest_float("atr_stop_mult", 0.8, 3.0),
                    rr_ratio=trial.suggest_float("rr_ratio", 1.0, 3.5))
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
    if name == "rsi2":
        from strategy.rsi2 import RSI2Params, RSI2Strategy
        r = {**cfg["rsi2"], **overrides}
        return RSI2Strategy(RSI2Params(
            rsi_period=r["rsi_period"], oversold=r["oversold"], overbought=r["overbought"],
            trend_period=r["trend_period"], atr_period=r["atr_period"],
            atr_stop_mult=r["atr_stop_mult"], rr_ratio=r["rr_ratio"], tick_size=tick_size))
    if name == "bollinger":
        from strategy.bollinger import BollingerParams, BollingerStrategy
        b = {**cfg["bollinger"], **overrides}
        return BollingerStrategy(BollingerParams(
            bb_period=b["bb_period"], bb_k=b["bb_k"], adx_period=b["adx_period"],
            adx_max=b["adx_max"], atr_period=b["atr_period"], atr_stop_mult=b["atr_stop_mult"],
            rr_ratio=b["rr_ratio"], tick_size=tick_size))
    if name == "donchian":
        from strategy.donchian import DonchianParams, DonchianStrategy
        dn = {**cfg["donchian"], **overrides}
        return DonchianStrategy(DonchianParams(
            channel_period=dn["channel_period"], adx_period=dn["adx_period"],
            adx_min=dn["adx_min"], atr_period=dn["atr_period"],
            atr_stop_mult=dn["atr_stop_mult"], rr_ratio=dn["rr_ratio"], tick_size=tick_size))
    if name == "fvg":
        from strategy.fvg import FVGParams, FVGStrategy
        fv = {**cfg["fvg"], **overrides}
        return FVGStrategy(FVGParams(
            atr_period=fv["atr_period"], atr_stop_mult=fv["atr_stop_mult"],
            rr_ratio=fv["rr_ratio"], max_age=fv["max_age"], tick_size=tick_size))
    if name == "trendline":
        from strategy.trendline import TrendlineParams, TrendlineBreakoutStrategy
        t = {**cfg["trendline"], **overrides}
        return TrendlineBreakoutStrategy(TrendlineParams(
            exec_minutes=t["exec_minutes"], htf_minutes=t["htf_minutes"],
            pivot_lookback=t["pivot_lookback"], min_touches=t["min_touches"],
            tol_atr=t["tol_atr"], break_margin_atr=t["break_margin_atr"],
            require_retest=t["require_retest"], retest_window=t["retest_window"],
            atr_period=t["atr_period"], atr_stop_mult=t["atr_stop_mult"],
            rr_ratio=t["rr_ratio"], tick_size=tick_size))
    raise ValueError(name)


def _score(bars, name, cfg, gex, tick_size, tick_value, comm, slip, overrides) -> float:
    strat = _make_strategy(name, cfg, tick_size, overrides)
    risk = _build_risk(cfg, tick_size, tick_value)
    res = run_backtest(bars, strat, risk, tick_size, tick_value, gex,
                       commission_per_contract=comm, slippage_points=slip,
                       **flatten_args(cfg))
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

    # Seed fixe -> optimisation reproductible (sinon le resultat holdout vibre
    # d'un run a l'autre et n'est pas fiable, surtout sur petit echantillon).
    study = optuna.create_study(direction="maximize",
                                sampler=optuna.samplers.TPESampler(seed=42))
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
                           commission_per_contract=comm, slippage_points=slip,
                           **flatten_args(cfg))
        reports.append({"fold": k, "oos": res.summary(), "params": best})
        if res.net_pnl > best_oos:
            best_oos = res.net_pnl
            best_overall = best

    output = {"instrument": instrument, "strategy": strategy_name,
              "best_params": best_overall, "folds": reports}
    Path(out_path).write_text(json.dumps(output, indent=2, default=str))
    return output
