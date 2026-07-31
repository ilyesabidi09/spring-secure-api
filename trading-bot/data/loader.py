"""Chargement de barres historiques + generateur synthetique pour la demo/tests."""
from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

from strategy.base import Bar


def load_csv(path: str | Path) -> list[Bar]:
    """CSV attendu: time,open,high,low,close,volume (time ISO 8601)."""
    bars: list[Bar] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            bars.append(Bar(
                time=datetime.fromisoformat(row["time"]),
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
                volume=float(row.get("volume", 0) or 0),
            ))
    return bars


def synthetic_bars(n: int = 2000, start_price: float = 5300.0,
                   seed: int = 42, days: int = 5) -> list[Bar]:
    """Barres 1-minute synthetiques (marche aleatoire + cycles) pour tester le
    pipeline sans donnees reelles. NE PAS utiliser pour evaluer la rentabilite."""
    rng = random.Random(seed)
    bars: list[Bar] = []
    price = start_price
    per_day = n // days
    day0 = datetime(2026, 1, 5, 9, 30)
    for i in range(n):
        day_idx = i // per_day
        minute = i % per_day
        t = day0 + timedelta(days=day_idx) + timedelta(minutes=minute)
        drift = 0.6 * math.sin(i / 40.0)
        step = rng.gauss(drift, 1.2)
        o = price
        c = price + step
        h = max(o, c) + abs(rng.gauss(0, 0.6))
        l = min(o, c) - abs(rng.gauss(0, 0.6))
        bars.append(Bar(t, o, h, l, c, volume=rng.randint(50, 500)))
        price = c
    return bars
