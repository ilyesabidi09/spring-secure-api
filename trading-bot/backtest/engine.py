"""Moteur de backtest barre-par-barre avec parite backtest/live.

Utilise la MEME strategie et le MEME RiskManager que le live. Un trade est ouvert
sur signal, puis clos quand le stop ou le target est touche par une barre ulterieure
(le stop est prioritaire si les deux sont touches sur la meme barre = hypothese
conservatrice).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from risk.manager import RiskManager
from strategy.base import Action, Bar, Context


@dataclass
class Trade:
    direction: Action
    entry: float
    stop: float
    target: float
    qty: int
    entry_time: object
    tick_size: float = 0.25
    tick_value: float = 1.25
    exit: float = 0.0
    exit_time: object = None
    pnl: float = 0.0


@dataclass
class BacktestResult:
    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)

    @property
    def net_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return wins / len(self.trades)

    @property
    def profit_factor(self) -> float:
        gains = sum(t.pnl for t in self.trades if t.pnl > 0)
        losses = -sum(t.pnl for t in self.trades if t.pnl < 0)
        if losses == 0:
            return float("inf") if gains > 0 else 0.0
        return gains / losses

    @property
    def expectancy(self) -> float:
        return self.net_pnl / len(self.trades) if self.trades else 0.0

    @property
    def max_drawdown(self) -> float:
        peak = float("-inf")
        mdd = 0.0
        for eq in self.equity_curve:
            peak = max(peak, eq)
            mdd = max(mdd, peak - eq)
        return mdd

    def summary(self) -> dict:
        return {
            "trades": len(self.trades),
            "net_pnl": round(self.net_pnl, 2),
            "win_rate": round(self.win_rate, 3),
            "profit_factor": round(self.profit_factor, 3),
            "expectancy": round(self.expectancy, 2),
            "max_drawdown": round(self.max_drawdown, 2),
        }


def run_backtest(bars: list[Bar], strategy, risk: RiskManager,
                 tick_size: float, tick_value: float,
                 gex_levels: dict | None = None) -> BacktestResult:
    result = BacktestResult()
    context = Context(gex_levels=gex_levels or {})
    open_trade: Trade | None = None

    for bar in bars:
        risk.start_day(bar.time.date())

        # 1. Gerer une position ouverte : stop/target touche ?
        if open_trade is not None:
            closed = _try_close(open_trade, bar, tick_value)
            if closed:
                risk.on_trade_closed(open_trade.pnl)
                result.trades.append(open_trade)
                result.equity_curve.append(risk.state.equity)
                open_trade = None

        # 2. Chercher une nouvelle entree.
        signal = strategy.on_bar(bar, context)
        if open_trade is None and signal.action in (Action.LONG, Action.SHORT):
            ok, _reason = risk.can_trade(bar.time.time())
            if ok:
                qty = risk.position_size()
                if qty > 0:
                    open_trade = _open(signal, bar, qty, tick_size, tick_value)
                    risk.register_trade_open()

    return result


def _open(signal, bar, qty, tick_size, tick_value) -> Trade:
    entry = bar.close
    if signal.action == Action.LONG:
        stop = entry - signal.stop_ticks * tick_size
        target = entry + signal.target_ticks * tick_size
    else:
        stop = entry + signal.stop_ticks * tick_size
        target = entry - signal.target_ticks * tick_size
    return Trade(signal.action, entry, stop, target, qty, bar.time, tick_size, tick_value)


def _try_close(t: Trade, bar: Bar, tick_value: float) -> bool:
    """Stop prioritaire sur target si les deux sont touches (conservateur)."""
    hit_exit = None
    if t.direction == Action.LONG:
        if bar.low <= t.stop:
            hit_exit = t.stop
        elif bar.high >= t.target:
            hit_exit = t.target
    else:  # SHORT
        if bar.high >= t.stop:
            hit_exit = t.stop
        elif bar.low <= t.target:
            hit_exit = t.target
    if hit_exit is None:
        return False
    t.exit = hit_exit
    t.exit_time = bar.time
    move = (t.exit - t.entry) if t.direction == Action.LONG else (t.entry - t.exit)
    t.pnl = move / t.tick_size * t.tick_value * t.qty
    return True
