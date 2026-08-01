"""Orchestrateur temps reel : data -> strategy -> risk -> execution.

Squelette de la boucle live. Se connecte a Tradovate (demo par defaut), recoit les
quotes/barres, applique strategie + RiskManager, et n'envoie un ordre que si toutes
les regles sont respectees. NE PAS activer mode=live avant validation demo prolongee.
"""
from __future__ import annotations

import logging
from datetime import datetime, time

from config import load_config
from execution.tradovate import TradovateClient, TradovateConfig
from risk.manager import RiskConfig, RiskManager
from strategy.base import Action, Bar, Context
from strategy.gex import load_gex_levels
from strategy.scalper import ScalperParams, ScalperStrategy

log = logging.getLogger("live")


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


class LiveRunner:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.is_live = cfg["mode"] == "live"
        tv = cfg["tradovate"]
        self.client = TradovateClient(TradovateConfig(
            base_url=tv["live_base_url"] if self.is_live else tv["demo_base_url"],
            ws_url=tv["ws_live_url"] if self.is_live else tv["ws_demo_url"],
            credentials=cfg["credentials"], is_live=self.is_live,
        ))
        from run_backtest import build_strategy
        spec = cfg["instruments"][cfg["symbol"]]
        self.tick_size, self.tick_value = spec["tick_size"], spec["tick_value"]
        self.strategy = build_strategy(cfg["strategy_name"], cfg, self.tick_size)
        self.risk = build_risk(cfg, self.tick_size, self.tick_value)
        self.context = Context(
            gex_levels=load_gex_levels(cfg["gex"]["levels_file"]) if cfg["gex"]["enabled"] else {})
        self.position = Action.FLAT
        from data.loader import BarAggregator
        self.agg = BarAggregator(cfg["timeframe_minutes"])

    def feed_1m(self, bar: Bar) -> None:
        """Point d'entree du flux 1-min (Tradovate WS) : agrege vers le timeframe
        de la strategie (M5) puis declenche on_bar sur chaque barre terminee."""
        agg_bar = self.agg.add(bar)
        if agg_bar is not None:
            self.on_bar(agg_bar)

    def on_bar(self, bar: Bar) -> None:
        """Appele a la cloture de chaque barre du timeframe strategie par le flux."""
        self.risk.start_day(bar.time.date())
        signal = self.strategy.on_bar(bar, self.context)
        if signal.action == Action.FLAT or self.position != Action.FLAT:
            return
        ok, reason = self.risk.can_trade(bar.time.time())
        if not ok:
            log.info("Trade refuse par le risque: %s", reason)
            return
        stop_dist = signal.stop_dist if signal.stop_dist > 0 else signal.stop_ticks * self.tick_size
        tgt_dist = signal.target_dist if signal.target_dist > 0 else signal.target_ticks * self.tick_size
        qty = self.risk.position_size(stop_dist)
        if qty <= 0 or stop_dist <= 0:
            return
        stop_ticks = round(stop_dist / self.tick_size)
        target_ticks = round(tgt_dist / self.tick_size)
        order = self.client.place_bracket(
            signal.action, qty, bar.close, stop_ticks, target_ticks, self.tick_size)
        order["symbol"] = self.cfg["symbol"]
        if self.is_live:
            self.client.submit(order)
            self.risk.register_trade_open()
            self.position = signal.action
            log.info("Ordre %s x%d envoye (LIVE): %s", signal.action, qty, signal.reason)
        else:
            log.info("[DEMO/dry-run] ordre %s x%d @%.2f : %s",
                     signal.action, qty, bar.close, signal.reason)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    runner = LiveRunner(cfg)
    log.info("LiveRunner pret en mode=%s symbol=%s", cfg["mode"], cfg["symbol"])
    log.warning("Boucle WS non branchee dans ce squelette : connecte le flux de barres "
                "Tradovate (WebSocket) a runner.on_bar(). Reste en DEMO.")


if __name__ == "__main__":
    main()
