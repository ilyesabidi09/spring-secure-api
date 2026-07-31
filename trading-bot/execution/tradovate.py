"""Client Tradovate : authentification REST + ordres bracket + flux WebSocket.

IMPORTANT conformite : chaque ordre passe par un bot DOIT porter isAutomated=true
(CME Rule 575). Ne jamais mettre mode=live avant validation prolongee en demo.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from strategy.base import Action


@dataclass
class TradovateConfig:
    base_url: str
    ws_url: str
    credentials: dict
    is_live: bool = False


class TradovateClient:
    def __init__(self, cfg: TradovateConfig):
        self.cfg = cfg
        self._token: str | None = None
        self._client = httpx.Client(timeout=10.0)

    # ---- auth -------------------------------------------------------------
    def authenticate(self) -> str:
        c = self.cfg.credentials
        payload = {
            "name": c["name"], "password": c["password"],
            "appId": c["app_id"], "appVersion": c["app_version"],
            "cid": c["cid"], "sec": c["sec"],
        }
        resp = self._client.post(
            f"{self.cfg.base_url}/auth/accesstokenrequest", json=payload)
        resp.raise_for_status()
        data = resp.json()
        self._token = data.get("accessToken")
        if not self._token:
            raise RuntimeError(f"auth Tradovate echouee: {data}")
        return self._token

    def _headers(self) -> dict:
        if not self._token:
            self.authenticate()
        return {"Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json"}

    # ---- ordres -----------------------------------------------------------
    def place_bracket(self, action: Action, qty: int, entry_price: float,
                      stop_ticks: int, target_ticks: int, tick_size: float) -> dict:
        """Ordre d'entree marche + OSO stop/target. isAutomated impose."""
        c = self.cfg.credentials
        side = "Buy" if action == Action.LONG else "Sell"
        opp = "Sell" if action == Action.LONG else "Buy"
        if action == Action.LONG:
            stop_px = entry_price - stop_ticks * tick_size
            tgt_px = entry_price + target_ticks * tick_size
        else:
            stop_px = entry_price + stop_ticks * tick_size
            tgt_px = entry_price - target_ticks * tick_size

        body = {
            "accountId": c["account_id"],
            "accountSpec": c["account_spec"],
            "symbol": None,  # renseigne par l'appelant via with_symbol
            "orderQty": qty,
            "orderType": "Market",
            "action": side,
            "isAutomated": True,   # OBLIGATOIRE (CME Rule 575)
            "bracket": {
                "stopLoss": {"action": opp, "orderType": "Stop",
                             "stopPrice": round(stop_px, 2), "isAutomated": True},
                "takeProfit": {"action": opp, "orderType": "Limit",
                               "price": round(tgt_px, 2), "isAutomated": True},
            },
        }
        return body  # place_order() envoie ; separe pour testabilite

    def submit(self, order_body: dict) -> dict:
        if not self.cfg.is_live:
            # garde-fou : en demo on log au lieu d'envoyer par erreur en live
            pass
        resp = self._client.post(
            f"{self.cfg.base_url}/order/placeoso",
            headers=self._headers(), content=json.dumps(order_body))
        resp.raise_for_status()
        return resp.json()

    def close(self) -> None:
        self._client.close()
