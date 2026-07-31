"""Test holdout verrouille — le juge de paix anti-overfitting / anti-data-snooping.

Coupe l'historique en deux : une partie IN-SAMPLE (optimisation) et un HOLDOUT final
JAMAIS utilise pour choisir les parametres. On optimise sur l'in-sample, puis on teste
UNE SEULE FOIS sur le holdout. Si l'edge tient sur le holdout, c'est un vrai signal ;
sinon c'etait du hasard (biais de comparaisons multiples).
"""
from __future__ import annotations

import json
from pathlib import Path

from backtest.engine import run_backtest
from optimize.walkforward import _build_risk, _make_strategy, optimize_window


def run_holdout(bars, cfg: dict, gex: dict, instrument: str, strategy_name: str,
                split: float = 0.75, n_trials: int = 50,
                out_path: str | Path = "holdout_result.json") -> dict:
    spec = cfg["instruments"][instrument]
    tick_size, tick_value = spec["tick_size"], spec["tick_value"]
    comm = cfg["costs"]["commission_per_contract"]
    slip = cfg["costs"]["slippage_points"]

    cut = int(len(bars) * split)
    is_bars, hold_bars = bars[:cut], bars[cut:]

    # 1. Optimisation UNIQUEMENT sur l'in-sample.
    best = optimize_window(is_bars, strategy_name, cfg, gex, tick_size,
                           tick_value, comm, slip, n_trials=n_trials)

    def _bt(segment):
        strat = _make_strategy(strategy_name, cfg, tick_size, best)
        risk = _build_risk(cfg, tick_size, tick_value)
        return run_backtest(segment, strat, risk, tick_size, tick_value, gex,
                            commission_per_contract=comm, slippage_points=slip)

    is_res = _bt(is_bars)
    hold_res = _bt(hold_bars)

    output = {
        "instrument": instrument, "strategy": strategy_name, "split": split,
        "best_params": best,
        "in_sample": is_res.summary(),
        "holdout": hold_res.summary(),
    }
    Path(out_path).write_text(json.dumps(output, indent=2, default=str))
    return output


def main() -> None:
    import argparse
    from config import load_config
    from data.loader import load_csv
    from strategy.gex import load_gex_levels

    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--instrument", default="MNQ")
    ap.add_argument("--strategy", default="donchian")
    ap.add_argument("--split", type=float, default=0.75)
    ap.add_argument("--out", default="holdout_result.json")
    args = ap.parse_args()

    cfg = load_config()
    gex = load_gex_levels(cfg["gex"]["levels_file"]) if cfg["gex"]["enabled"] else {}
    bars = load_csv(args.csv)
    out = run_holdout(bars, cfg, gex, args.instrument, args.strategy,
                      split=args.split, out_path=args.out)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
