"""Rate limits protect the free AI quota without getting in the way of a class sharing one IP."""

import pytest
from fastapi.testclient import TestClient

from app import store
from app.config import get_settings
from app.main import app
from app.ratelimit import RateLimiter

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_store():
    store.clear()


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_limiter_allows_up_to_the_limit_then_says_how_long_to_wait():
    clock = FakeClock()
    rl = RateLimiter(clock)
    assert [rl.hit("k", 3, 60) for _ in range(3)] == [None, None, None]
    assert rl.hit("k", 3, 60) == pytest.approx(60)
    clock.now += 61                       # the window has passed
    assert rl.hit("k", 3, 60) is None


def test_limiter_keys_are_independent():
    rl = RateLimiter(FakeClock())
    for _ in range(2):
        rl.hit("a", 2, 60)
    assert rl.hit("a", 2, 60) is not None
    assert rl.hit("b", 2, 60) is None


def from_ip(ip: str) -> dict:
    return {"X-Forwarded-For": ip}


def test_too_many_players_from_one_ip_get_429():
    limit = get_settings().players_per_ip_per_hour
    for _ in range(limit):
        assert client.post("/api/player", json={}, headers=from_ip("1.2.3.4")).status_code == 201
    r = client.post("/api/player", json={}, headers=from_ip("1.2.3.4"))
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["Retry-After"]) > 0
    # someone else is unaffected
    assert client.post("/api/player", json={}, headers=from_ip("5.6.7.8")).status_code == 201


def test_faking_an_earlier_forwarded_ip_does_not_dodge_the_limit():
    limit = get_settings().players_per_ip_per_hour
    for i in range(limit):
        client.post("/api/player", json={}, headers=from_ip(f"10.0.0.{i}, 9.9.9.9"))
    r = client.post("/api/player", json={}, headers=from_ip("10.0.0.250, 9.9.9.9"))
    assert r.status_code == 429  # the last entry (added by Render's proxy) is what counts


def test_too_many_rounds_for_one_player_get_429():
    pid = client.post("/api/player", json={}).json()["player_id"]
    limit = get_settings().rounds_per_player_per_hour
    for _ in range(limit):
        assert client.post("/api/round/start", json={"player_id": pid, "scenario_id": "bank_alert"}).status_code == 201
    r = client.post("/api/round/start", json={"player_id": pid, "scenario_id": "bank_alert"})
    assert r.status_code == 429 and "minute" in r.json()["error"]["message"]
    # another player on the same IP can still play
    other = client.post("/api/player", json={}).json()["player_id"]
    assert client.post("/api/round/start", json={"player_id": other, "scenario_id": "bank_alert"}).status_code == 201
