#!/usr/bin/env python3
"""Forward-test DEMO (paper) sur donnees FRAICHES telechargees depuis Databento.

A lancer periodiquement (ex. chaque semaine). Telecharge les dernieres barres 1-min
du future depuis --start jusqu'a maintenant, rejoue la strategie verrouillee
(config strategy_name) via le meme chemin de decision que le live, et affiche les
trades + le P&L cumule. Au fil du temps, ces donnees sont du VRAI hors-echantillon.

Cle API : variable d'environnement DATABENTO_API_KEY (jamais committee).
    export DATABENTO_API_KEY=db-xxxxxxxx
    python forward_demo.py --start 2026-08-01

Cout : ~quelques centimes de credits par appel (ohlcv-1m, 1 symbole), estime AVANT
telechargement et affiche. Rien n'est telecharge si le cout depasse --max-cost.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

import databento as db
import pandas as pd

from config import load_config
from data.loader import Bar
from forward_test import ForwardTester

CONTRACT = {"MNQ": "MNQ.c.0", "NQ": "NQ.c.0", "MES": "ES.c.0", "ES": "ES.c.0"}


def fetch(instrument: str, start: str, end: str, max_cost: float):
    key = os.environ.get("DATABENTO_API_KEY")
    if not key:
        raise SystemExit("Definis DATABENTO_API_KEY (export DATABENTO_API_KEY=db-...)")
    client = db.Historical(key)
    sym = CONTRACT[instrument]
    cost = client.metadata.get_cost(dataset="GLBX.MDP3", symbols=[sym], schema="ohlcv-1m",
                                    start=start, end=end, stype_in="continuous")
    print(f"Cout estime {sym} {start}->{end} : ${cost:.4f}")
    if cost > max_cost:
        raise SystemExit(f"Cout ${cost:.4f} > --max-cost ${max_cost} -> abandon (rien telecharge)")
    data = client.timeseries.get_range(dataset="GLBX.MDP3", symbols=[sym], schema="ohlcv-1m",
                                       start=start, end=end, stype_in="continuous")
    df = data.to_df().reset_index()
    tcol = "ts_event" if "ts_event" in df.columns else df.columns[0]
    ts = pd.to_datetime(df[tcol], utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)
    sc = 1e-9 if float(df["close"].median()) > 1e6 else 1.0
    bars = [Bar(t.to_pydatetime(), o * sc, h * sc, l * sc, c * sc, v)
            for t, o, h, l, c, v in zip(ts, df["open"], df["high"], df["low"], df["close"], df["volume"])]
    return bars


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instrument", default="MNQ")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD (debut de la fenetre forward)")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD (defaut: aujourd'hui)")
    ap.add_argument("--max-cost", type=float, default=1.0, help="cout max en $ de credits (garde-fou)")
    args = ap.parse_args()
    end = args.end or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    cfg = load_config()
    bars = fetch(args.instrument, args.start, end, args.max_cost)
    print(f"{len(bars)} barres 1-min telechargees ({bars[0].time} -> {bars[-1].time})")

    ft = ForwardTester(cfg, args.instrument, verbose=True)
    print(f"Forward-test {args.instrument} / {cfg['strategy_name']} "
          f"M{cfg['timeframe_minutes']} (htf {cfg['trendline']['htf_minutes']}m)")
    for b in bars:
        ft.feed_1m(b)
    import json
    print("\n=== RESULTAT FORWARD-TEST (paper, donnees fraiches) ===")
    print(json.dumps(ft.summary(), indent=2))
    print("\nRappel : edge marginal (PF ~1.03) -> il faut des MOIS de forward pour conclure.")


if __name__ == "__main__":
    main()
