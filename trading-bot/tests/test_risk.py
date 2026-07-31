"""Tests deterministes du RiskManager : c'est le composant qui protege le compte."""
from datetime import date, time

import pytest

from risk.manager import RiskConfig, RiskManager


def make_risk(**over):
    base = dict(
        balance=50000.0, trailing_drawdown=2000.0, daily_loss_limit=1000.0,
        max_contracts=5, consistency_pct=0.30, risk_per_trade_usd=150.0,
        stop_ticks=12, tick_value=1.25, tick_size=0.25, max_trades_per_day=10,
        session_start=time(9, 30), session_end=time(16, 0),
    )
    base.update(over)
    return RiskManager(RiskConfig(**base))


def test_position_size_respecte_risque_et_max():
    r = make_risk()
    # 12 ticks * 1.25 = 15 USD/contrat ; 150/15 = 10 -> plafonne a max_contracts=5
    assert r.position_size() == 5


def test_position_size_zero_si_risque_trop_petit():
    r = make_risk(risk_per_trade_usd=10.0)  # < 15 USD/contrat
    assert r.position_size() == 0


def test_daily_loss_limit_verrouille():
    r = make_risk()
    r.start_day(date(2026, 1, 5))
    r.on_trade_closed(-1000.0)
    ok, reason = r.can_trade(time(10, 0))
    assert not ok and "daily" in reason


def test_trailing_drawdown_verrouille():
    r = make_risk(daily_loss_limit=100000.0)  # neutralise la limite jour
    r.start_day(date(2026, 1, 5))
    r.on_trade_closed(-2000.0)  # equity = floor
    ok, reason = r.can_trade(time(10, 0))
    assert not ok and "trailing" in reason


def test_trailing_floor_monte_avec_les_gains():
    r = make_risk()
    r.start_day(date(2026, 1, 5))
    r.on_trade_closed(1000.0)  # equity 51000, peak 51000
    assert r.state.trailing_floor == pytest.approx(49000.0)


def test_hors_session_refuse():
    r = make_risk()
    r.start_day(date(2026, 1, 5))
    ok, reason = r.can_trade(time(8, 0))
    assert not ok and "session" in reason


def test_max_trades_par_jour():
    r = make_risk(max_trades_per_day=2)
    r.start_day(date(2026, 1, 5))
    r.register_trade_open()
    r.register_trade_open()
    ok, reason = r.can_trade(time(10, 0))
    assert not ok and "max trades" in reason


def test_consistency_rule():
    r = make_risk()
    r.start_day(date(2026, 1, 5))
    r.on_trade_closed(900.0)
    r.start_day(date(2026, 1, 6))
    r.on_trade_closed(100.0)
    ok, share = r.consistency_ok()
    # jour 1 = 90% du profit total -> viole la regle des 30%
    assert not ok and share == pytest.approx(0.9)
