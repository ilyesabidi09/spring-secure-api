"""Telechargement de donnees tick REELLES depuis Dukascopy (gratuit) -> CSV OHLCV.

Dukascopy expose des ticks historiques en fichiers .bi5 (LZMA) par heure :
  https://datafeed.dukascopy.com/datafeed/{INSTR}/{YYYY}/{MM-1:02d}/{DD:02d}/{HH:02d}h_ticks.bi5
Chaque enregistrement = 20 octets big-endian : >IIIff
  (ms depuis le debut de l'heure, ask*scale, bid*scale, askVolume, bidVolume)

On agrege les ticks (prix = mid = (bid+ask)/2) en barres OHLCV et on ecrit un CSV
au format attendu par data/loader.py::load_csv (time,open,high,low,close,volume).

ATTENTION : c'est le CFD indice de Dukascopy (proxy du S&P/Nasdaq), pas le contrat
CME MES/MNQ. Les prix suivent l'indice de tres pres (bon pour tester le SIGNAL),
mais le volume n'est PAS le volume CME (souvent 0 pour les indices) et il existe un
leger basis. Suffisant pour la recherche de strategie, pas pour un chiffrage exact.

Usage:
    python -m data.download_dukascopy --instrument USA500IDXUSD \
        --start 2026-05-01 --end 2026-06-01 --interval 5min --out data/sp500_5m.csv
"""
from __future__ import annotations

import argparse
import csv
import lzma
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

BASE = "https://datafeed.dukascopy.com/datafeed"
RECORD = struct.Struct(">IIIff")  # ms, ask, bid, askVol, bidVol
EASTERN = ZoneInfo("America/New_York")

# Facteur de prix par instrument (nb de decimales). Indices Dukascopy = 3 -> /1000.
POINT_SCALE = {
    "USA500IDXUSD": 1000.0,   # S&P 500
    "USATECHIDXUSD": 1000.0,  # Nasdaq 100
}


def _hour_url(instrument: str, dt: datetime) -> str:
    # Mois indexe a 0 chez Dukascopy.
    return (f"{BASE}/{instrument}/{dt.year}/{dt.month - 1:02d}/"
            f"{dt.day:02d}/{dt.hour:02d}h_ticks.bi5")


def fetch_hour_ticks(client: httpx.Client, instrument: str, hour: datetime,
                     scale: float) -> list[tuple[datetime, float]]:
    """Retourne [(timestamp_utc, mid_price)] pour une heure. Vide si pas de data."""
    url = _hour_url(instrument, hour)
    try:
        resp = client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    except httpx.HTTPError:
        return []
    if resp.status_code != 200 or not resp.content:
        return []
    try:
        raw = lzma.decompress(resp.content)
    except lzma.LZMAError:
        return []
    ticks: list[tuple[datetime, float]] = []
    for off in range(0, len(raw) - len(raw) % RECORD.size, RECORD.size):
        ms, ask, bid, _av, _bv = RECORD.unpack_from(raw, off)
        mid = (ask + bid) / 2.0 / scale
        ts = hour + timedelta(milliseconds=ms)
        ticks.append((ts, mid))
    return ticks


def resample_ohlcv(ticks: list[tuple[datetime, float]], rule_seconds: int
                   ) -> list[dict]:
    """Agrege des ticks (tries) en barres OHLCV. Volume = nombre de ticks (proxy,
    le vrai volume CME n'est pas fourni par le feed indice de Dukascopy)."""
    bars: list[dict] = []
    cur_key = None
    o = h = l = c = 0.0
    count = 0
    for ts, price in ticks:
        key = int(ts.timestamp()) // rule_seconds
        if key != cur_key:
            if cur_key is not None:
                bars.append({"time": _bar_time(cur_key, rule_seconds),
                             "open": o, "high": h, "low": l, "close": c,
                             "volume": count})
            cur_key = key
            o = h = l = c = price
            count = 0
        h = max(h, price)
        l = min(l, price)
        c = price
        count += 1
    if cur_key is not None:
        bars.append({"time": _bar_time(cur_key, rule_seconds),
                     "open": o, "high": h, "low": l, "close": c, "volume": count})
    return bars


def _bar_time(key: int, rule_seconds: int) -> str:
    """Debut de la barre en heure US/Eastern (aligne sur les sessions RTH du bot)."""
    dt_utc = datetime.fromtimestamp(key * rule_seconds, tz=timezone.utc)
    return dt_utc.astimezone(EASTERN).replace(tzinfo=None).isoformat()


def _last_utc_hour_in_csv(out: Path) -> datetime | None:
    """Derniere heure UTC deja ecrite (pour reprendre un telechargement interrompu).
    Les timestamps du CSV sont en US/Eastern -> on reconvertit en UTC."""
    if not out.exists() or out.stat().st_size == 0:
        return None
    last = None
    with open(out, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            last = row["time"]
    if not last:
        return None
    et = datetime.fromisoformat(last).replace(tzinfo=EASTERN)
    return et.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def download(instrument: str, start: datetime, end: datetime, rule_seconds: int,
             out_path: str | Path, resume: bool = True) -> int:
    """Streaming per-heure (memoire constante) : chaque heure est telechargee,
    resamplee et ecrite immediatement. Les intervalles qui divisent l'heure
    (1,5,15,30,60 min) ne franchissent jamais une frontiere d'heure -> exact.
    `resume` saute les heures deja presentes dans le CSV existant."""
    if 3600 % rule_seconds != 0:
        raise ValueError("interval doit diviser 3600s (1,5,15,30,60 min) "
                         "pour le mode streaming")
    scale = POINT_SCALE.get(instrument, 1000.0)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    resume_from = _last_utc_hour_in_csv(out) if resume else None
    new_file = resume_from is None
    total_bars = 0
    hours = int((end - start).total_seconds() // 3600)

    mode = "w" if new_file else "a"
    with open(out, mode, newline="", encoding="utf-8") as fh, httpx.Client() as client:
        w = csv.DictWriter(fh, fieldnames=["time", "open", "high", "low", "close", "volume"])
        if new_file:
            w.writeheader()
        for i in range(hours):
            hour = (start + timedelta(hours=i)).replace(
                minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
            if resume_from is not None and hour <= resume_from:
                continue
            ticks = fetch_hour_ticks(client, instrument, hour, scale)
            if ticks:
                for b in resample_ohlcv(ticks, rule_seconds):
                    w.writerow(b)
                    total_bars += 1
            if i % 24 == 0:
                fh.flush()
                print(f"  {hour.date()}  barres ecrites: {total_bars}", flush=True)
    print(f"OK -> {out}  ({total_bars} nouvelles barres)")
    return total_bars


def _parse_interval(s: str) -> int:
    s = s.strip().lower()
    if s.endswith("min"):
        return int(s[:-3]) * 60
    if s.endswith("s"):
        return int(s[:-1])
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    raise ValueError(f"interval invalide: {s} (ex: 1min, 5min)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Telecharge des ticks Dukascopy -> CSV OHLCV")
    ap.add_argument("--instrument", default="USA500IDXUSD",
                    help="USA500IDXUSD (S&P) | USATECHIDXUSD (Nasdaq)")
    ap.add_argument("--start", required=True, help="date debut YYYY-MM-DD (UTC)")
    ap.add_argument("--end", required=True, help="date fin exclue YYYY-MM-DD (UTC)")
    ap.add_argument("--interval", default="5min", help="1min, 5min, 15min...")
    ap.add_argument("--out", default="data/sp500.csv")
    ap.add_argument("--no-resume", action="store_true",
                    help="repart de zero (ecrase) au lieu de reprendre le CSV existant")
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")
    print(f"Telechargement {args.instrument} {args.start} -> {args.end} "
          f"({args.interval}) depuis Dukascopy...")
    download(args.instrument, start, end, _parse_interval(args.interval), args.out,
             resume=not args.no_resume)


if __name__ == "__main__":
    main()
