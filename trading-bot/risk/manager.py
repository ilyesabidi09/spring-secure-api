"""RiskManager : garde-fous durs alignes sur les regles Tradeify 50k Select.

Objectif : eviter la violation de compte (trailing drawdown, daily loss, consistency,
taille max). C'est ce qui crame un compte prop, pas une perte de trade normale.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time


@dataclass
class RiskConfig:
    balance: float
    trailing_drawdown: float
    daily_loss_limit: float
    max_contracts: int
    consistency_pct: float
    risk_per_trade_usd: float
    stop_ticks: int
    tick_value: float
    max_trades_per_day: int
    session_start: time
    session_end: time


@dataclass
class RiskState:
    equity: float
    peak_equity: float
    trailing_floor: float          # niveau sous lequel le compte est viole
    day_start_equity: float
    today: date | None = None
    trades_today: int = 0
    day_pnls: dict = field(default_factory=dict)   # date -> pnl du jour
    locked: bool = False           # bloque pour la session courante
    lock_reason: str = ""


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.state = RiskState(
            equity=cfg.balance,
            peak_equity=cfg.balance,
            trailing_floor=cfg.balance - cfg.trailing_drawdown,
            day_start_equity=cfg.balance,
        )

    # ---- sizing -----------------------------------------------------------
    def position_size(self) -> int:
        """Nombre de contrats pour respecter le risque monetaire par trade."""
        risk_per_contract = self.cfg.stop_ticks * self.cfg.tick_value
        if risk_per_contract <= 0:
            return 0
        qty = int(self.cfg.risk_per_trade_usd // risk_per_contract)
        return max(0, min(qty, self.cfg.max_contracts))

    # ---- cycle de vie journalier -----------------------------------------
    def start_day(self, day: date) -> None:
        if self.state.today != day:
            self.state.today = day
            self.state.day_start_equity = self.state.equity
            self.state.trades_today = 0
            self.state.locked = False
            self.state.lock_reason = ""

    def in_session(self, t: time) -> bool:
        return self.cfg.session_start <= t <= self.cfg.session_end

    # ---- autorisation d'entree -------------------------------------------
    def can_trade(self, t: time) -> tuple[bool, str]:
        if self.state.locked:
            return False, self.state.lock_reason
        if not self.in_session(t):
            return False, "hors session RTH"
        if self.state.trades_today >= self.cfg.max_trades_per_day:
            return False, "max trades/jour atteint"
        daily_loss = self.state.day_start_equity - self.state.equity
        if daily_loss >= self.cfg.daily_loss_limit:
            self._lock("daily loss limit atteinte")
            return False, self.state.lock_reason
        if self.state.equity <= self.state.trailing_floor:
            self._lock("trailing drawdown atteint")
            return False, self.state.lock_reason
        return True, "ok"

    def register_trade_open(self) -> None:
        self.state.trades_today += 1

    # ---- comptabilite d'un trade cloture ---------------------------------
    def on_trade_closed(self, pnl: float) -> None:
        self.state.equity += pnl
        day = self.state.today
        if day is not None:
            self.state.day_pnls[day] = self.state.day_pnls.get(day, 0.0) + pnl
        # Le trailing drawdown suit le pic d'equity (regle trailing intraday/EOD).
        if self.state.equity > self.state.peak_equity:
            self.state.peak_equity = self.state.equity
            self.state.trailing_floor = self.state.peak_equity - self.cfg.trailing_drawdown
        # Verifie les seuils apres coup.
        daily_loss = self.state.day_start_equity - self.state.equity
        if daily_loss >= self.cfg.daily_loss_limit:
            self._lock("daily loss limit atteinte")
        if self.state.equity <= self.state.trailing_floor:
            self._lock("trailing drawdown atteint")

    def _lock(self, reason: str) -> None:
        self.state.locked = True
        self.state.lock_reason = reason

    # ---- consistency rule (verification globale) -------------------------
    def consistency_ok(self) -> tuple[bool, float]:
        """Aucun jour ne doit peser plus de consistency_pct du profit total."""
        total = sum(p for p in self.state.day_pnls.values())
        if total <= 0:
            return True, 0.0
        best = max(self.state.day_pnls.values())
        share = best / total
        return share <= self.cfg.consistency_pct, share
