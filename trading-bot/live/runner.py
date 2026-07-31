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
        s = cfg["strategy"]
        self.strategy = ScalperStrategy(ScalperParams(
            ema_fast=s["ema_fast"], ema_slow=s["ema_slow"], rsi_period=s["rsi_period"],
            rsi_long_max=s["rsi_long_max"], rsi_short_min=s["rsi_short_min"],
            vwap_filter=s["vwap_filter"], min_confidence=s["min_confidence"],
            stop_ticks=cfg["risk"]["stop_ticks"], target_ticks=cfg["risk"]["target_ticks"],
            gex_enabled=cfg["gex"]["enabled"], gex_proximity_ticks=cfg["gex"]["proximity_ticks"],
            tick_size=cfg["tick_size"],
        ))
        self.risk = build_risk(cfg)
        self.context = Context(
            gex_levels=load_gex_levels(cfg["gex"]["levels_file"]) if cfg["gex"]["enabled"] else {})
        self.position = Action.FLAT

    def on_bar(self, bar: Bar) -> None:
        """Appele a la cloture de chaque barre par le flux de donnees."""
        self.risk.start_day(bar.time.date())
        signal = self.strategy.on_bar(bar, self.context)
        if signal.action == Action.FLAT or self.position != Action.FLAT:
            return
        ok, reason = self.risk.can_trade(bar.time.time())
        if not ok:
            log.info("Trade refuse par le risque: %s", reason)
            return
        qty = self.risk.position_size()
        if qty <= 0:
            return
        order = self.client.place_bracket(
            signal.action, qty, bar.close, signal.stop_ticks,
            signal.target_ticks, self.cfg["tick_size"])
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
