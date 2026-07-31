"""Serveur webhook FastAPI : recoit les alertes TradingView -> execution Tradovate.

Permet de prototyper la strategie en Pine Script cote TradingView, puis de router
l'alerte vers le meme chemin d'execution (RiskManager + Tradovate, isAutomated=true).

Alerte TradingView (JSON) attendue:
{ "secret": "...", "action": "long|short|flat", "symbol": "MES", "price": 5300.0 }
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Request

from config import load_config
from live.runner import LiveRunner
from strategy.base import Action, Bar
from datetime import datetime

app = FastAPI(title="Tradeify Scalper Webhook")
_cfg = load_config()
_runner = LiveRunner(_cfg)
_SECRET = os.environ.get("WEBHOOK_SECRET", "")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mode": _cfg["mode"], "symbol": _cfg["symbol"]}


@app.post("/tradingview")
async def tradingview(req: Request) -> dict:
    payload = await req.json()
    if not _SECRET or payload.get("secret") != _SECRET:
        raise HTTPException(status_code=401, detail="secret invalide")
    action = payload.get("action", "flat")
    price = float(payload.get("price", 0) or 0)
    if action not in ("long", "short"):
        return {"handled": False, "reason": "action ignoree"}
    # On fabrique une pseudo-barre a partir de l'alerte pour reutiliser on_bar.
    now = datetime.now()
    bar = Bar(now, price, price, price, price, volume=1)
    # NB: la strategie interne recalcule ses signaux ; ici on delegue au meme risk path.
    _runner.on_bar(bar)
    return {"handled": True, "mode": _cfg["mode"]}
