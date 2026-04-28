"""Tool-level tests: register_trade + should_stop_trading + daily_status."""
import server


def test_register_loss_increments_streak(fresh_state):
    server.register_trade(profit=-8, r_multiple=-1.0, symbol="EURUSD",
                           side="buy", deal_ticket=1)
    server.register_trade(profit=-8, r_multiple=-1.0, symbol="EURUSD",
                           side="buy", deal_ticket=2)
    s = server.daily_status()
    assert s["consecutive_losses"] == 2


def test_register_win_resets_streak(fresh_state):
    server.register_trade(profit=-8, r_multiple=-1.0, symbol="EURUSD",
                           side="buy", deal_ticket=1)
    server.register_trade(profit=16, r_multiple=2.0, symbol="EURUSD",
                           side="buy", deal_ticket=2)
    s = server.daily_status()
    assert s["consecutive_losses"] == 0


def test_idempotent_registration(fresh_state):
    server.register_trade(profit=-8, r_multiple=-1.0, symbol="EURUSD",
                           side="buy", deal_ticket=42)
    res = server.register_trade(profit=-8, r_multiple=-1.0, symbol="EURUSD",
                                 side="buy", deal_ticket=42)
    assert res["registered"] is False
    assert res["reason"] == "DUPLICATE_TICKET"
    assert server.daily_status()["trades_count"] == 1


def test_lockout_after_3pct_loss(fresh_state):
    # 3% of 800 = 24. One trade losing 25 should trigger lockout.
    server.register_trade(profit=-25, r_multiple=-3.1, symbol="EURUSD",
                           side="buy", deal_ticket=1)
    decision = server.should_stop_trading()
    assert decision["stop"] is True
    reasons = [r[0] for r in decision["reasons"]]
    assert "DAILY_LOSS_LIMIT" in reasons


def test_loss_streak_triggers_stop(fresh_state):
    for i in range(3):
        server.register_trade(profit=-2, r_multiple=-0.5, symbol="EURUSD",
                               side="buy", deal_ticket=i)
    decision = server.should_stop_trading()
    reasons = [r[0] for r in decision["reasons"]]
    assert "LOSS_STREAK" in reasons


def test_overtrading_caps_at_5(fresh_state):
    for i in range(5):
        server.register_trade(profit=0.5, r_multiple=0.1, symbol="EURUSD",
                               side="buy", deal_ticket=i)
    decision = server.should_stop_trading()
    reasons = [r[0] for r in decision["reasons"]]
    assert "OVERTRADING" in reasons


def test_daily_status_basic_math(fresh_state):
    server.register_trade(profit=10, r_multiple=2.0, symbol="EURUSD",
                           side="buy", deal_ticket=1)
    server.register_trade(profit=-4, r_multiple=-1.0, symbol="EURUSD",
                           side="sell", deal_ticket=2)
    s = server.daily_status()
    assert s["trades_count"] == 2
    assert s["wins_today"] == 1
    assert s["losses_today"] == 1
    assert s["daily_pl_usd"] == 6.0
    assert s["current_equity"] == 806.0
