"""Holdout poole MNQ+MES : optimise le Donchian sur l'in-sample combine des deux
instruments, teste UNE fois sur le holdout combine. Variante avec/sans filtre SMT.

Pooler double l'echantillon de trades -> statistiques plus fermes. Le compte est
partage (drawdown combine realiste). C'est le test qui doit confirmer (ou infirmer)
l'edge breakout M5 vu par instrument.
"""
from __future__ import annotations

import json
from pathlib import Path

from backtest.portfolio import run_portfolio
from optimize.walkforward import _build_risk, _make_strategy
from strategy.smt import SMTFilter


def _slice(streams, lo, hi):
    return {i: {**s, "bars": s["bars"][int(len(s["bars"]) * lo):int(len(s["bars"]) * hi)]}
            for i, s in streams.items()}


def _run(streams, cfg, strat_name, overrides, use_smt, smt_lookback=20):
    strategies = {i: _make_strategy(strat_name, cfg, s["tick_size"], overrides)
                  for i, s in streams.items()}
    risk = _build_risk(cfg, 0.25, 0.50)  # compte partage ; sizing par stop_dist reel
    smt = SMTFilter(smt_lookback) if use_smt else None
    return run_portfolio(streams, strategies, risk, cfg["costs"],
                         gex=None, smt=smt)


def pooled_holdout(streams, cfg, strat_name="donchian", split=0.75,
                   n_trials=40, use_smt=False, out_path="pooled_holdout.json"):
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    from optimize.walkforward import _search_space

    is_streams = _slice(streams, 0.0, split)
    ho_streams = _slice(streams, split, 1.0)

    def objective(trial):
        ov = _search_space(strat_name, trial)
        res = _run(is_streams, cfg, strat_name, ov, use_smt)
        if len(res.trades) < 20:
            return -1e9
        return res.net_pnl - 0.5 * res.max_drawdown

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials)
    best = study.best_params

    is_res = _run(is_streams, cfg, strat_name, best, use_smt)
    ho_res = _run(ho_streams, cfg, strat_name, best, use_smt)
    out = {"strategy": strat_name, "smt": use_smt, "split": split, "best_params": best,
           "in_sample": is_res.summary(), "holdout": ho_res.summary()}
    Path(out_path).write_text(json.dumps(out, indent=2, default=str))
    return out
