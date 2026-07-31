#!/usr/bin/env python3
"""Point d'entree : lance un backtest de demonstration sur donnees synthetiques.

Usage:
    python run_backtest.py                 # backtest sur barres synthetiques
    python run_backtest.py --walkforward   # optimisation walk-forward (Optuna requis)
    python run_backtest.py --csv data.csv  # backtest sur un CSV reel

ATTENTION : les donnees synthetiques servent uniquement a valider le pipeline,
PAS a evaluer la rentabilite. Utilise des donnees MES/MNQ reelles pour ca.
"""
from __future__ import annotations

import argparse
import json
from datetime import time

from config import load_config
from data.loader import load_csv, synthetic_bars
from risk.manager import RiskConfig, RiskManager
from strategy.gex import load_gex_levels
from strategy.scalper import ScalperParams, ScalperStrategy


def build_risk(cfg: dict) -> RiskManager:
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


def build_strategy(cfg: dict) -> ScalperStrategy:
    s = cfg["strategy"]
    return ScalperStrategy(ScalperParams(
        ema_fast=s["ema_fast"], ema_slow=s["ema_slow"], rsi_period=s["rsi_period"],
        rsi_long_max=s["rsi_long_max"], rsi_short_min=s["rsi_short_min"],
        vwap_filter=s["vwap_filter"], min_confidence=s["min_confidence"],
        stop_ticks=cfg["risk"]["stop_ticks"], target_ticks=cfg["risk"]["target_ticks"],
        gex_enabled=cfg["gex"]["enabled"], gex_proximity_ticks=cfg["gex"]["proximity_ticks"],
        tick_size=cfg["tick_size"],
    ))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="CSV de barres (time,open,high,low,close,volume)")
    ap.add_argument("--walkforward", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    gex = load_gex_levels(cfg["gex"]["levels_file"]) if cfg["gex"]["enabled"] else {}
    bars = load_csv(args.csv) if args.csv else synthetic_bars()

    if args.walkforward:
        from optimize.walkforward import walk_forward
        out = walk_forward(bars, cfg, gex)
        print(json.dumps({"best_params": out["best_params"]}, indent=2))
        print(f"\nRapport complet -> best_params.json ({len(out['folds'])} folds)")
        return

    from backtest.engine import run_backtest
    strat = build_strategy(cfg)
    risk = build_risk(cfg)
    res = run_backtest(bars, strat, risk, cfg["tick_size"], cfg["tick_value"], gex)
    print("=== Resultat backtest (donnees:",
          "CSV" if args.csv else "SYNTHETIQUES - pipeline seulement", ")===")
    print(json.dumps(res.summary(), indent=2))
    print("\nRappel: un backtest positif ne garantit pas la rentabilite live.")


if __name__ == "__main__":
    main()
