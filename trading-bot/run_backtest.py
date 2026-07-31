#!/usr/bin/env python3
"""Point d'entree backtest / walk-forward.

Usage:
    python run_backtest.py --csv data/nasdaq_1m.csv --instrument MNQ --strategy scalper
    python run_backtest.py --csv data/nasdaq_1m.csv --instrument MNQ --strategy orb
    python run_backtest.py --csv data/nasdaq_1m.csv --instrument MNQ --strategy vwap --walkforward

Les frais (commissions + slippage) et les specs de l'instrument (MES/MNQ) sont lus
depuis config/settings.yaml. Sans --csv, un jeu synthetique valide juste la plomberie.
"""
from __future__ import annotations

import argparse
import json
from datetime import time

from config import load_config
from data.loader import load_csv, synthetic_bars
from risk.manager import RiskConfig, RiskManager
from strategy.gex import load_gex_levels


def build_risk(cfg: dict, tick_size: float, tick_value: float) -> RiskManager:
    acc, rk = cfg["account"], cfg["risk"]
    sh, sm = map(int, rk["session_start"].split(":"))
    eh, em = map(int, rk["session_end"].split(":"))
    return RiskManager(RiskConfig(
        balance=acc["balance"], trailing_drawdown=acc["trailing_drawdown"],
        daily_loss_limit=acc["daily_loss_limit"], max_contracts=acc["max_contracts"],
        consistency_pct=acc["consistency_pct"], risk_per_trade_usd=rk["risk_per_trade_usd"],
        stop_ticks=rk["stop_ticks"], tick_value=tick_value, tick_size=tick_size,
        max_trades_per_day=rk["max_trades_per_day"],
        session_start=time(sh, sm), session_end=time(eh, em),
    ))


def build_strategy(name: str, cfg: dict, tick_size: float):
    """Instancie la strategie choisie. Fabrique reutilisee par le walk-forward."""
    if name == "scalper":
        from strategy.scalper import ScalperParams, ScalperStrategy
        s = cfg["strategy"]
        return ScalperStrategy(ScalperParams(
            ema_fast=s["ema_fast"], ema_slow=s["ema_slow"], rsi_period=s["rsi_period"],
            rsi_long_max=s["rsi_long_max"], rsi_short_min=s["rsi_short_min"],
            vwap_filter=s["vwap_filter"], min_confidence=s["min_confidence"],
            atr_period=s["atr_period"], atr_stop_mult=s["atr_stop_mult"], rr_ratio=s["rr_ratio"],
            gex_enabled=cfg["gex"]["enabled"], gex_proximity_ticks=cfg["gex"]["proximity_ticks"],
            tick_size=tick_size))
    if name == "orb":
        from strategy.orb import ORBParams, ORBStrategy
        o = cfg["orb"]
        sh, sm = map(int, cfg["risk"]["session_start"].split(":"))
        return ORBStrategy(ORBParams(
            session_start=time(sh, sm), orb_minutes=o["orb_minutes"], atr_period=o["atr_period"],
            atr_stop_mult=o["atr_stop_mult"], rr_ratio=o["rr_ratio"],
            max_entry_minutes=o["max_entry_minutes"], tick_size=tick_size))
    if name == "vwap":
        from strategy.vwap_reversion import VwapReversionParams, VwapReversionStrategy
        v = cfg["vwap"]
        return VwapReversionStrategy(VwapReversionParams(
            atr_period=v["atr_period"], dev_mult=v["dev_mult"],
            atr_stop_mult=v["atr_stop_mult"], rr_ratio=v["rr_ratio"], tick_size=tick_size))
    if name == "meta":
        from meta.regime import RegimeMetaStrategy, RegimeParams
        m = cfg["meta"]
        return RegimeMetaStrategy(
            RegimeParams(ema_fast=m["ema_fast"], ema_slow=m["ema_slow"],
                         atr_period=m["atr_period"], trend_threshold=m["trend_threshold"]),
            trend_strategy=build_strategy("scalper", cfg, tick_size),
            range_strategy=build_strategy("vwap", cfg, tick_size))
    if name == "rsi2":
        from strategy.rsi2 import RSI2Params, RSI2Strategy
        r = cfg["rsi2"]
        return RSI2Strategy(RSI2Params(
            rsi_period=r["rsi_period"], oversold=r["oversold"], overbought=r["overbought"],
            trend_period=r["trend_period"], atr_period=r["atr_period"],
            atr_stop_mult=r["atr_stop_mult"], rr_ratio=r["rr_ratio"], tick_size=tick_size))
    if name == "bollinger":
        from strategy.bollinger import BollingerParams, BollingerStrategy
        b = cfg["bollinger"]
        return BollingerStrategy(BollingerParams(
            bb_period=b["bb_period"], bb_k=b["bb_k"], adx_period=b["adx_period"],
            adx_max=b["adx_max"], atr_period=b["atr_period"], atr_stop_mult=b["atr_stop_mult"],
            rr_ratio=b["rr_ratio"], tick_size=tick_size))
    if name == "donchian":
        from strategy.donchian import DonchianParams, DonchianStrategy
        dn = cfg["donchian"]
        return DonchianStrategy(DonchianParams(
            channel_period=dn["channel_period"], adx_period=dn["adx_period"],
            adx_min=dn["adx_min"], atr_period=dn["atr_period"],
            atr_stop_mult=dn["atr_stop_mult"], rr_ratio=dn["rr_ratio"], tick_size=tick_size))
    if name == "fvg":
        from strategy.fvg import FVGParams, FVGStrategy
        fv = cfg["fvg"]
        return FVGStrategy(FVGParams(
            atr_period=fv["atr_period"], atr_stop_mult=fv["atr_stop_mult"],
            rr_ratio=fv["rr_ratio"], max_age=fv["max_age"], tick_size=tick_size))
    raise ValueError(f"strategie inconnue: {name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="CSV de barres (time,open,high,low,close,volume)")
    ap.add_argument("--instrument", default=None, help="MES | MNQ (defaut: symbol de la config)")
    ap.add_argument("--strategy", default=None, help="scalper | orb | vwap")
    ap.add_argument("--walkforward", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    instrument = args.instrument or cfg["symbol"]
    spec = cfg["instruments"][instrument]
    tick_size, tick_value = spec["tick_size"], spec["tick_value"]
    strat_name = args.strategy or cfg["strategy_name"]
    comm = cfg["costs"]["commission_per_contract"]
    slip = cfg["costs"]["slippage_points"]

    gex = load_gex_levels(cfg["gex"]["levels_file"]) if cfg["gex"]["enabled"] else {}
    bars = load_csv(args.csv) if args.csv else synthetic_bars()

    if args.walkforward:
        from optimize.walkforward import walk_forward
        out = walk_forward(bars, cfg, gex, instrument=instrument, strategy_name=strat_name)
        print(json.dumps({"best_params": out["best_params"]}, indent=2))
        print(f"\nRapport complet -> best_params.json ({len(out['folds'])} folds)")
        return

    from backtest.engine import run_backtest
    strat = build_strategy(strat_name, cfg, tick_size)
    risk = build_risk(cfg, tick_size, tick_value)
    res = run_backtest(bars, strat, risk, tick_size, tick_value, gex,
                       commission_per_contract=comm, slippage_points=slip)
    src = "CSV" if args.csv else "SYNTHETIQUES (plomberie seulement)"
    print(f"=== Backtest {instrument} / {strat_name} (donnees: {src}) ===")
    print(json.dumps(res.summary(), indent=2))
    print("\nRappel: un backtest positif ne garantit pas la rentabilite live.")


if __name__ == "__main__":
    main()
