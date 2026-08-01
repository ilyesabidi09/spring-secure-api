#!/usr/bin/env python3
"""Harnais de FORWARD-TEST (paper) de la strategie verrouillee.

Rejoue un flux de barres 1-min EXACTEMENT comme le ferait le live :
  flux 1-min -> BarAggregator -> barre M5 -> strategie -> RiskManager -> broker paper
Le broker paper simule les fills bracket (stop/target) sur les barres M5 suivantes,
avec commissions + slippage de la config. Sortie : journal des trades + equity + stats.

C'est le meme chemin de decision que le runner live : quand tu auras un compte demo
Tradovate, on remplace le broker paper par le client Tradovate + flux WS, sans toucher
a la logique de decision.

Usage:
    python forward_test.py --csv data/nasdaq_1m.csv          # tout l'historique
    python forward_test.py --csv data/nasdaq_1m.csv --tail 40000   # ~fenetre recente
"""
from __future__ import annotations

import argparse
import json
from datetime import time

from backtest.engine import _open, _stop_dist, _try_close
from config import load_config
from data.loader import BarAggregator, load_csv
from risk.manager import RiskConfig, RiskManager
from run_backtest import build_strategy
from strategy.base import Action, Context


def build_risk(cfg, tick_size, tick_value):
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


class ForwardTester:
    """Meme boucle que le live, mais fills simules (paper)."""

    def __init__(self, cfg, instrument, verbose=True):
        spec = cfg["instruments"][instrument]
        self.ts, self.tv = spec["tick_size"], spec["tick_value"]
        self.cfg = cfg
        self.comm = cfg["costs"]["commission_per_contract"]
        self.slip = cfg["costs"]["slippage_points"]
        self.agg = BarAggregator(cfg["timeframe_minutes"])
        self.strategy = build_strategy(cfg["strategy_name"], cfg, self.ts)
        self.risk = build_risk(cfg, self.ts, self.tv)
        self.ctx = Context()
        self.open_trade = None
        self.trades = []
        self.verbose = verbose

    def feed_1m(self, bar):
        m5 = self.agg.add(bar)
        if m5 is not None:
            self._on_bar(m5)

    def _on_bar(self, bar):
        self.risk.start_day(bar.time.date())
        # 1. Gestion de la position ouverte (fills bracket simules).
        if self.open_trade is not None and _try_close(self.open_trade, bar, self.comm, self.slip):
            self.risk.on_trade_closed(self.open_trade.pnl)
            self.trades.append(self.open_trade)
            if self.verbose:
                t = self.open_trade
                print(f"  EXIT  {t.exit_time} {t.direction.value:<5} @{t.exit:.2f} "
                      f"pnl={t.pnl:+.2f} equity={self.risk.state.equity:.2f}")
            self.open_trade = None
        # 2. Nouvelle entree.
        sig = self.strategy.on_bar(bar, self.ctx)
        if self.open_trade is None and sig.action in (Action.LONG, Action.SHORT):
            ok, _ = self.risk.can_trade(bar.time.time())
            if not ok:
                return
            stop_dist = _stop_dist(sig, self.ts)
            qty = self.risk.position_size(stop_dist)
            if qty > 0 and stop_dist > 0:
                self.open_trade = _open(sig, bar, qty, self.ts, self.tv, stop_dist)
                self.risk.register_trade_open()
                if self.verbose:
                    print(f"  ENTRY {bar.time} {sig.action.value:<5} @{bar.close:.2f} "
                          f"x{qty} stop={self.open_trade.stop:.2f} tgt={self.open_trade.target:.2f}")

    def summary(self):
        from backtest.engine import BacktestResult
        r = BacktestResult(trades=self.trades)
        r.equity_curve = []
        eq = self.cfg["account"]["balance"]
        for t in self.trades:
            eq += t.pnl
            r.equity_curve.append(eq)
        return r.summary()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--instrument", default=None)
    ap.add_argument("--tail", type=int, default=0, help="ne rejouer que les N dernieres barres 1-min")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    instrument = args.instrument or cfg["symbol"]
    bars = load_csv(args.csv)
    if args.tail:
        bars = bars[-args.tail:]

    ft = ForwardTester(cfg, instrument, verbose=not args.quiet)
    print(f"Forward-test {instrument} / {cfg['strategy_name']} M{cfg['timeframe_minutes']} "
          f"sur {len(bars)} barres 1-min ({bars[0].time} -> {bars[-1].time})")
    for b in bars:
        ft.feed_1m(b)
    print("\n=== RESULTAT FORWARD-TEST (paper) ===")
    print(json.dumps(ft.summary(), indent=2))


if __name__ == "__main__":
    main()
