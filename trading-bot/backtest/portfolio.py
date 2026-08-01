"""Backtest multi-instruments sur UN SEUL compte (comme Tradeify).

Fusionne les flux de barres de plusieurs instruments (ex. MNQ + MES) dans un ordre
chronologique, avec un RiskManager PARTAGE (equity, trailing drawdown, daily loss et
plafond de contrats communs). Le drawdown combine est mesure sur l'equity du compte
-> realiste : MNQ et MES etant correles, leurs pertes ne se diversifient pas comme
des actifs independants.

Filtre SMT optionnel : ne prend une cassure que si l'instrument correle confirme
(pas de divergence) — concept ICT "SMT divergence".
"""
from __future__ import annotations

from backtest.engine import BacktestResult, _open, _stop_dist, _try_close
from strategy.base import Action, Context


def run_portfolio(streams: dict, strategies: dict, risk, costs: dict,
                  gex: dict | None = None, smt=None) -> BacktestResult:
    """streams: {instr: {"bars":[Bar], "tick_size":ts, "tick_value":tv}}
       strategies: {instr: Strategy}
       smt: filtre SMT optionnel (voir strategy/smt.py)."""
    comm = costs["commission_per_contract"]
    slip = costs["slippage_points"]

    events = []
    for instr, s in streams.items():
        for b in s["bars"]:
            events.append((b.time, instr, b))
    events.sort(key=lambda e: (e[0], e[1]))

    contexts = {instr: Context(gex_levels=gex or {}) for instr in streams}
    open_trades = {instr: None for instr in streams}
    result = BacktestResult()

    for _t, instr, bar in events:
        risk.start_day(bar.time.date())
        ts = streams[instr]["tick_size"]
        tv = streams[instr]["tick_value"]

        if smt is not None:
            smt.update(instr, bar)

        # 1. Gerer la position ouverte de cet instrument.
        ot = open_trades[instr]
        if ot is not None and _try_close(ot, bar, comm, slip):
            risk.on_trade_closed(ot.pnl)
            result.trades.append(ot)
            result.equity_curve.append(risk.state.equity)
            open_trades[instr] = None

        # 2. Nouvelle entree ?
        signal = strategies[instr].on_bar(bar, contexts[instr])
        if open_trades[instr] is None and signal.action in (Action.LONG, Action.SHORT):
            ok, _reason = risk.can_trade(bar.time.time())
            if not ok:
                continue
            if smt is not None:
                others = [i for i in streams if i != instr]
                if not smt.allows(instr, signal.action, others):
                    continue
            stop_dist = _stop_dist(signal, ts)
            open_qty = sum(o.qty for o in open_trades.values() if o is not None)
            qty = risk.position_size(stop_dist)
            qty = min(qty, max(0, risk.cfg.max_contracts - open_qty))  # plafond compte
            if qty > 0 and stop_dist > 0:
                open_trades[instr] = _open(signal, bar, qty, ts, tv, stop_dist)
                risk.register_trade_open()

    return result
