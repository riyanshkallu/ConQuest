"""The playtest report counts the right things from saved rounds and quiz scores."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import db, engine, store
from app.main import app
from scripts import playtest_report as report

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_store():
    store.clear()


def play(pid: str, action: str, is_scam: bool, monkeypatch) -> None:
    monkeypatch.setattr(engine, "assign_is_scam", lambda *a, **k: is_scam)
    rid = client.post("/api/round/start", json={"player_id": pid, "scenario_id": "bank_alert"}).json()["round_id"]
    client.post(f"/api/round/{rid}/action", json={"action": action})


def new_tester() -> str:
    return client.post("/api/player", json={}).json()["player_id"]


def test_report_numbers(monkeypatch, tmp_path):
    # Tester A: gets scammed-ish first (trusts a scam), then verifies a scam: learns
    a = new_tester()
    play(a, "trust", True, monkeypatch)       # SCAMMED
    play(a, "verify", True, monkeypatch)      # OUTSMARTED
    # Tester B: false alarm on a real contact, then verifies a real one
    b = new_tester()
    play(b, "hang_up", False, monkeypatch)    # FALSE_ALARM
    play(b, "verify", False, monkeypatch)     # SMART_AND_SAFE

    rounds = report.load_rounds(db.get_engine(), None, None)
    assert len(rounds) == 4
    quiz_file = tmp_path / "quiz.csv"
    quiz_file.write_text("tester,age,before,after\nA,15,3,5\nB,67,2,5\n", encoding="utf-8")
    s = report.summarize(rounds, report.load_radar(db.get_engine(), {a, b}), report.load_quiz(quiz_file))

    assert s["testers"] == 2 and s["rounds"] == 4
    assert s["not_scammed"] == "50%" and s["outsmarted"] == "50%"
    assert s["smart_and_safe"] == "50%" and s["false_alarms"] == "50%"
    assert s["early_good"] == "0%" and s["late_good"] == "100%"   # both did better in their later round
    assert s["verified"] == "50%" and s["verified_sample"] == 4
    assert s["quiz"]["before"] == 2.5 and s["quiz"]["after"] == 5.0 and s["quiz"]["improved"] == "100%"
    assert s["quiz"]["groups"] == {"Teens (13-18)": (1, 3.0, 5.0), "Adults (19+)": (1, 2.0, 5.0)}

    text = report.to_markdown(s, None, None)
    assert "rose from **2.5/6** before playing to **5.0/6**" in text
    assert "| SCAMMED | 1 |" in text


def test_date_range_excludes_other_days(monkeypatch):
    play(new_tester(), "verify", True, monkeypatch)
    today = date.today()
    assert len(report.load_rounds(db.get_engine(), today, today)) == 1
    assert report.load_rounds(db.get_engine(), today + timedelta(days=1), None) == []


def test_unsaved_conversations_are_left_out_of_the_verify_rate(monkeypatch):
    pid = new_tester()
    client.patch(f"/api/player/{pid}/settings", json={"save_conversations": False})
    play(pid, "verify", True, monkeypatch)
    (rnd,) = report.load_rounds(db.get_engine(), None, None)
    assert rnd["verified"] is None
    assert report.summarize([rnd], {}, [])["verified_sample"] == 0


def test_empty_report():
    assert "No finished rounds" in report.to_markdown(report.summarize([], {}, []), None, None)


def test_dates_are_local_days():
    """An evening round in Ohio is already the next day in UTC; it must still count for that local day."""
    from datetime import datetime, time, timezone
    from scripts.playtest_report import _local
    start, end = _local(date(2026, 10, 14), time.min), _local(date(2026, 10, 14), time.max)
    assert end - start > timedelta(hours=23)
    local_evening = datetime(2026, 10, 14, 21, 0).astimezone(timezone.utc)
    assert start <= local_evening <= end


def test_ai_live_share_is_reported(monkeypatch):
    play(new_tester(), "verify", True, monkeypatch)
    rounds = report.load_rounds(db.get_engine(), None, None)
    rounds[0]["ai_live"], rounds[0]["ai_fallback"] = 9, 1  # mock mode is all fallback; pretend
    s = report.summarize(rounds, {}, [])
    assert "The AI answered **90%** of turns live; 1 turn used the pre-written backup lines." in report.to_markdown(s, None, None)
