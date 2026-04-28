import time

from lib import idempotency


def test_remember_returns_cached_within_ttl():
    idempotency.reset()
    coid = "abc-123"
    payload = {"ok": True, "ticket": 999}
    idempotency.remember(coid, payload)
    assert idempotency.check(coid) == payload


def test_different_ids_dont_collide():
    idempotency.reset()
    idempotency.remember("a", {"ticket": 1})
    idempotency.remember("b", {"ticket": 2})
    assert idempotency.check("a") == {"ticket": 1}
    assert idempotency.check("b") == {"ticket": 2}


def test_no_id_means_no_cache():
    idempotency.reset()
    assert idempotency.check(None) is None


def test_purge_evicts_stale_entries(monkeypatch):
    idempotency.reset()
    coid = "stale"
    idempotency.remember(coid, {"ticket": 1})
    # Fast-forward time past TTL.
    real_time = time.time
    monkeypatch.setattr(idempotency.time, "time", lambda: real_time() + 120.0)
    assert idempotency.check(coid) is None
