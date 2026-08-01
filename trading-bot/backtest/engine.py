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
    pnl: float = 0.0          # net (apres commissions + slippage)
    gross_pnl: float = 0.0    # brut (avant frais)
    cost: float = 0.0         # commissions + slippage


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

    @property
    def gross_pnl(self) -> float:
        return sum(t.gross_pnl for t in self.trades)

    @property
    def total_cost(self) -> float:
        return sum(t.cost for t in self.trades)

    def summary(self) -> dict:
        return {
            "trades": len(self.trades),
            "gross_pnl": round(self.gross_pnl, 2),
            "cost": round(self.total_cost, 2),
            "net_pnl": round(self.net_pnl, 2),
            "win_rate": round(self.win_rate, 3),
            "profit_factor": round(self.profit_factor, 3),
            "expectancy": round(self.expectancy, 2),
            "max_drawdown": round(self.max_drawdown, 2),
        }


def run_backtest(bars: list[Bar], strategy, risk: RiskManager,
                 tick_size: float, tick_value: float,
                 gex_levels: dict | None = None,
                 commission_per_contract: float = 0.0,
                 slippage_points: float = 0.0,
                 flatten_from=None, no_entry_from=None, no_entry_to=None) -> BacktestResult:
    """flatten_from/no_entry_from/no_entry_to (datetime.time) : regle prop firm
    'pas d'overnight' -> force-close des positions a flatten_from et blocage des
    entrees dans [no_entry_from, no_entry_to). Si None, comportement inchange."""
    result = BacktestResult()
    context = Context(gex_levels=gex_levels or {})
    open_trade: Trade | None = None

    for bar in bars:
        risk.start_day(bar.time.date())
        t = bar.time.time()

        # 1. Gerer une position ouverte : stop/target touche ?
        if open_trade is not None:
            closed = _try_close(open_trade, bar, commission_per_contract, slippage_points)
            if closed:
                risk.on_trade_closed(open_trade.pnl)
                result.trades.append(open_trade)
                result.equity_curve.append(risk.state.equity)
                open_trade = None

        # 1b. Flatten obligatoire (prop firm) : force-close au prix marche.
        if open_trade is not None and flatten_from is not None and t >= flatten_from \
                and (no_entry_to is None or t < no_entry_to):
            _force_flat(open_trade, bar, commission_per_contract, slippage_points)
            risk.on_trade_closed(open_trade.pnl)
            result.trades.append(open_trade)
            result.equity_curve.append(risk.state.equity)
            open_trade = None

        # 2. Chercher une nouvelle entree (bloquee pendant la fenetre flatten+break).
        in_no_entry = (no_entry_from is not None and no_entry_to is not None
                       and no_entry_from <= t < no_entry_to)
        signal = strategy.on_bar(bar, context)
        if open_trade is None and not in_no_entry and signal.action in (Action.LONG, Action.SHORT):
            ok, _reason = risk.can_trade(bar.time.time())
            if ok:
                stop_dist = _stop_dist(signal, tick_size)
                qty = risk.position_size(stop_dist)
                if qty > 0 and stop_dist > 0:
                    open_trade = _open(signal, bar, qty, tick_size, tick_value, stop_dist)
                    risk.register_trade_open()

    return result


def _stop_dist(signal, tick_size) -> float:
    """Distance de stop en points : privilegie stop_dist (ATR), sinon stop_ticks."""
    if signal.stop_dist > 0:
        return signal.stop_dist
    return signal.stop_ticks * tick_size


def _open(signal, bar, qty, tick_size, tick_value, stop_dist) -> Trade:
    entry = bar.close
    tgt_dist = signal.target_dist if signal.target_dist > 0 else signal.target_ticks * tick_size
    if signal.action == Action.LONG:
        stop = entry - stop_dist
        target = entry + tgt_dist
    else:
        stop = entry + stop_dist
        target = entry - tgt_dist
    return Trade(signal.action, entry, stop, target, qty, bar.time, tick_size, tick_value)


def _force_flat(t: Trade, bar: Bar, commission_per_contract: float,
                slippage_points: float) -> None:
    """Cloture forcee au marche (regle prop firm 'flatten EOD'), prix = close de la barre."""
    t.exit = bar.close
    t.exit_time = bar.time
    move = (t.exit - t.entry) if t.direction == Action.LONG else (t.entry - t.exit)
    t.gross_pnl = move / t.tick_size * t.tick_value * t.qty
    slip_cost = 2 * (slippage_points / t.tick_size) * t.tick_value
    t.cost = (2 * commission_per_contract + slip_cost) * t.qty
    t.pnl = t.gross_pnl - t.cost


def _try_close(t: Trade, bar: Bar, commission_per_contract: float,
               slippage_points: float) -> bool:
    """Stop prioritaire sur target si les deux sont touches (conservateur).
    PnL net = brut - commissions (aller-retour) - slippage (entree + sortie)."""
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
    t.gross_pnl = move / t.tick_size * t.tick_value * t.qty
    # commission aller-retour + slippage sur entree ET sortie (2x)
    slip_cost = 2 * (slippage_points / t.tick_size) * t.tick_value
    t.cost = (2 * commission_per_contract + slip_cost) * t.qty
    t.pnl = t.gross_pnl - t.cost
    return True
