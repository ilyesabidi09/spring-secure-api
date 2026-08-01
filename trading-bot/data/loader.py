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


def resample_bars(bars: list[Bar], minutes: int) -> list[Bar]:
    """Reagrege des barres 1-min en barres de `minutes` (5, 15, ...). Les intervalles
    divisant l'heure ne franchissent jamais une frontiere d'heure -> agregation exacte.
    Volume = somme. Horodatage = debut du bucket (meme fuseau que l'entree)."""
    if not bars:
        return []
    step = minutes * 60
    out: list[Bar] = []
    cur_key = None
    o = h = l = c = 0.0
    vol = 0.0
    t0 = None
    for b in bars:
        key = int(b.time.timestamp()) // step
        if key != cur_key:
            if cur_key is not None:
                out.append(Bar(t0, o, h, l, c, vol))
            cur_key = key
            t0 = b.time.replace(minute=(b.time.minute // minutes) * minutes,
                                second=0, microsecond=0)
            o, h, l, c, vol = b.open, b.high, b.low, b.close, 0.0
        h = max(h, b.high)
        l = min(l, b.low)
        c = b.close
        vol += b.volume
    if cur_key is not None:
        out.append(Bar(t0, o, h, l, c, vol))
    return out


class BarAggregator:
    """Agrege des barres 1-min en barres de `minutes` EN TEMPS REEL (streaming).
    add() renvoie la barre agregee terminee quand un nouveau bucket commence, sinon None.
    Utilise en live/forward-test pour transformer le flux 1-min en barres M5."""

    def __init__(self, minutes: int):
        self.minutes = minutes
        self.step = minutes * 60
        self.cur_key = None
        self.t0 = None
        self.o = self.h = self.l = self.c = self.vol = 0.0

    def add(self, bar: Bar) -> Bar | None:
        key = int(bar.time.timestamp()) // self.step
        completed = None
        if self.cur_key is not None and key != self.cur_key:
            completed = Bar(self.t0, self.o, self.h, self.l, self.c, self.vol)
            self.cur_key = None
        if self.cur_key is None:
            self.cur_key = key
            self.t0 = bar.time.replace(minute=(bar.time.minute // self.minutes) * self.minutes,
                                       second=0, microsecond=0)
            self.o, self.h, self.l, self.c, self.vol = bar.open, bar.high, bar.low, bar.close, 0.0
        self.h = max(self.h, bar.high)
        self.l = min(self.l, bar.low)
        self.c = bar.close
        self.vol += bar.volume
        return completed


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
