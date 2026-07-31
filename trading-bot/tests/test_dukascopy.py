"""Test offline du parsing/aggregation Dukascopy (aucun reseau).

Utilise un echantillon .bi5 fige (4 ticks S&P reels encodes en base64) pour verifier
la decompression LZMA, le decodage des enregistrements 20 octets et l'agregation OHLCV.
"""
import base64
import lzma
import struct
from datetime import datetime, timezone

from data.download_dukascopy import RECORD, resample_ohlcv

# 4 ticks reels (ask, bid *1000) captures sur USA500IDXUSD, recompresses.
SAMPLE_B64 = ("XQAAgAD//////////wAAYAdT6RopKDRZWQSrvdYZSt0/rfjjPeBswjtezBw7bHMq"
              "rBlVKM69DNWc6XzPOujH3n6N/vGL9AA=")


def test_bi5_decode_et_prix():
    raw = lzma.decompress(base64.b64decode(SAMPLE_B64))
    assert len(raw) % RECORD.size == 0
    recs = [RECORD.unpack_from(raw, o) for o in range(0, len(raw), RECORD.size)]
    assert len(recs) == 4
    ms, ask, bid, _av, _bv = recs[0]
    # ask/bid stockes *1000 -> S&P autour de 7433-7434
    assert 7433 < ask / 1000.0 < 7435
    assert 7433 < bid / 1000.0 < 7435


def test_resample_ohlcv():
    base = datetime(2026, 5, 12, 10, 0, tzinfo=timezone.utc)
    ticks = [
        (base.replace(second=1), 7433.8),
        (base.replace(second=30), 7434.5),   # high
        (base.replace(second=59), 7433.0),   # low + close de la 1ere minute
        (base.replace(minute=1, second=5), 7435.0),  # nouvelle barre
    ]
    bars = resample_ohlcv(ticks, rule_seconds=60)
    assert len(bars) == 2
    b0 = bars[0]
    assert b0["open"] == 7433.8 and b0["high"] == 7434.5
    assert b0["low"] == 7433.0 and b0["close"] == 7433.0
    assert b0["volume"] == 3   # 3 ticks
