"""Playtest report: turns the saved rounds (and your quiz scores) into the numbers for the video
and the written answers. It only reads from the database, never changes it.

From backend/, with DATABASE_URL in .env pointing at Supabase:
  .venv/Scripts/python scripts/playtest_report.py --since 2026-10-13 --until 2026-10-14
  .venv/Scripts/python scripts/playtest_report.py --since 2026-10-13 --quiz quiz.csv --out report.md

--since/--until pick the playtest days (inclusive), so your own testing isn't counted.
--quiz is a CSV of the before/after quiz (see scripts/quiz_template.csv):
  tester,age,before,after        (before/after = how many of the 6 messages they got right)
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import Engine, select  # noqa: E402

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.flags import RADAR_CATEGORIES  # noqa: E402

GOOD_ENDINGS = {"OUTSMARTED", "ESCAPED", "SMART_AND_SAFE"}
VERIFY_NOTE = "You called the organization using a number you already trust."
QUIZ_QUESTIONS = 6


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_rounds(engine: Engine, since: date | None, until: date | None) -> list[dict]:
    """Rounds that ended between the start of `since` and the end of `until`, in local time.

    Times are stored in UTC, but playtest days are local: an evening round in Ohio is already
    the next day in UTC, so the dates are converted from this computer's time zone.
    """
    query = select(db.rounds).order_by(db.rounds.c.player_id, db.rounds.c.ended_at)
    if since:
        query = query.where(db.rounds.c.ended_at >= _local(since, time.min))
    if until:
        query = query.where(db.rounds.c.ended_at <= _local(until, time.max))
    with engine.connect() as conn:
        rounds = [dict(r) for r in conn.execute(query).mappings()]
        ids = [r["id"] for r in rounds]
        verified = set()
        saved = set()
        if ids:
            for row in conn.execute(select(db.messages.c.round_id, db.messages.c.text)
                                    .where(db.messages.c.round_id.in_(ids))):
                saved.add(row.round_id)
                if row.text == VERIFY_NOTE:
                    verified.add(row.round_id)
    for r in rounds:
        r["verified"] = r["id"] in verified if r["id"] in saved else None  # None = conversation not saved
    return rounds


def _local(day: date, at: time) -> datetime:
    return datetime.combine(day, at).astimezone(timezone.utc)  # naive = this computer's local time


def load_radar(engine: Engine, player_ids: set[str]) -> dict[str, list[int]]:
    totals = {c: [0, 0] for c in RADAR_CATEGORIES}
    if not player_ids:
        return totals
    with engine.connect() as conn:
        for row in conn.execute(select(db.radar).where(db.radar.c.player_id.in_(player_ids))).mappings():
            if row["category"] in totals:
                totals[row["category"]][0] += row["encountered"]
                totals[row["category"]][1] += row["resisted"]
    return totals


def load_quiz(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = []
        for row in csv.DictReader(f):
            rows.append({"tester": row["tester"].strip(), "age": int(row["age"]),
                         "before": int(row["before"]), "after": int(row["after"])})
    return rows


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

def count(n: int, word: str) -> str:
    """'1 tester', '2 testers'."""
    return f"{n} {word}" + ("" if n == 1 else "s")


def pct(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%" if whole else "n/a"


def summarize(rounds: list[dict], radar: dict[str, list[int]], quiz: list[dict]) -> dict:
    by_player: dict[str, list[dict]] = defaultdict(list)
    for r in rounds:
        by_player[r["player_id"]].append(r)
    scam = [r for r in rounds if r["is_scam"]]
    legit = [r for r in rounds if not r["is_scam"]]
    endings = Counter(r["ending"] for r in rounds)

    # Did players do better later? Compare each player's first half of rounds with their second half.
    early, late = [], []
    for player_rounds in by_player.values():
        if len(player_rounds) >= 2:
            half = len(player_rounds) // 2
            early += player_rounds[:half]
            late += player_rounds[half:]

    known = [r for r in rounds if r["verified"] is not None]
    summary = {
        "testers": len(by_player),
        "rounds": len(rounds),
        "rounds_per_tester": round(len(rounds) / len(by_player), 1) if by_player else 0,
        "scam_rounds": len(scam),
        "not_scammed": pct(sum(r["ending"] != "SCAMMED" for r in scam), len(scam)),
        "outsmarted": pct(endings["OUTSMARTED"], len(scam)),
        "legit_rounds": len(legit),
        "smart_and_safe": pct(endings["SMART_AND_SAFE"], len(legit)),
        "false_alarms": pct(endings["FALSE_ALARM"], len(legit)),
        "lucky": pct(endings["LUCKY"], len(legit)),
        "verified": pct(sum(bool(r["verified"]) for r in known), len(known)),
        "verified_sample": len(known),
        "endings": dict(endings.most_common()),
        "early_good": pct(sum(r["ending"] in GOOD_ENDINGS for r in early), len(early)),
        "late_good": pct(sum(r["ending"] in GOOD_ENDINGS for r in late), len(late)),
        "early_points": round(statistics.mean(r["points"] for r in early), 1) if early else None,
        "late_points": round(statistics.mean(r["points"] for r in late), 1) if late else None,
        "learning_sample": len({r["player_id"] for r in early}),
        "radar": {RADAR_CATEGORIES[c]: (e, res, pct(res, e)) for c, (e, res) in radar.items() if e},
    }
    if quiz:
        summary["quiz"] = {
            "testers": len(quiz),
            "ages": (min(q["age"] for q in quiz), max(q["age"] for q in quiz)),
            "before": round(statistics.mean(q["before"] for q in quiz), 1),
            "after": round(statistics.mean(q["after"] for q in quiz), 1),
            "improved": pct(sum(q["after"] > q["before"] for q in quiz), len(quiz)),
            "groups": {},
        }
        for name, group in (("Teens (13-18)", [q for q in quiz if q["age"] <= 18]),
                            ("Adults (19+)", [q for q in quiz if q["age"] > 18])):
            if group:
                summary["quiz"]["groups"][name] = (len(group), round(statistics.mean(q["before"] for q in group), 1),
                                                   round(statistics.mean(q["after"] for q in group), 1))
    return summary


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def to_markdown(s: dict, since: date | None, until: date | None) -> str:
    when = f"{since or 'start'} to {until or 'now'}"
    lines = [f"# Playtest results ({when})", ""]
    if not s["rounds"]:
        return "\n".join(lines + ["No finished rounds in this date range."])

    lines += ["## Headline numbers", ""]
    if "quiz" in s:
        q = s["quiz"]
        lines.append(f"- Quiz scores rose from **{q['before']:.1f}/{QUIZ_QUESTIONS}** before playing to "
                     f"**{q['after']:.1f}/{QUIZ_QUESTIONS}** after ({count(q['testers'], 'tester')}, ages {q['ages'][0]}-{q['ages'][1]}); "
                     f"{q['improved']} of testers improved.")
    lines += [
        f"- {count(s['testers'], 'tester')} played {count(s['rounds'], 'round')} "
        f"({s['rounds_per_tester']} each on average).",
        f"- Scam rounds: testers avoided being scammed in **{s['not_scammed']}** ({s['scam_rounds']} rounds); "
        f"{s['outsmarted']} were fully outsmarted.",
        f"- Real (legit) contacts: **{s['smart_and_safe']}** handled them the smart way, "
        f"{s['false_alarms']} were false alarms, {s['lucky']} trusted without checking ({s['legit_rounds']} rounds).",
    ]
    if s["learning_sample"]:
        lines.append(f"- Good outcomes went from **{s['early_good']}** in testers' first rounds to "
                     f"**{s['late_good']}** in their later rounds; average points {s['early_points']} → "
                     f"{s['late_points']} ({count(s['learning_sample'], 'tester')} with 2+ rounds).")
    if s["verified_sample"]:
        lines.append(f"- Testers verified independently in {s['verified']} of rounds "
                     f"(of {s['verified_sample']} rounds with saved conversations).")

    if "quiz" in s and s["quiz"]["groups"]:
        lines += ["", "## Quiz by age group", "", "| Group | Testers | Before | After |", "| --- | --- | --- | --- |"]
        for name, (n, before, after) in s["quiz"]["groups"].items():
            lines.append(f"| {name} | {n} | {before:.1f}/{QUIZ_QUESTIONS} | {after:.1f}/{QUIZ_QUESTIONS} |")

    lines += ["", "## All endings", "", "| Ending | Rounds |", "| --- | --- |"]
    lines += [f"| {ending} | {n} |" for ending, n in s["endings"].items()]

    if s["radar"]:
        lines += ["", "## Scam Radar across testers", "", "| Tactic group | Faced | Resisted | Rate |",
                  "| --- | --- | --- | --- |"]
        lines += [f"| {label} | {e} | {r} | {rate} |" for label, (e, r, rate) in s["radar"].items()]

    lines += ["", f"_Small sample: {count(s['testers'], 'tester')}. Report it as a playtest, not a study._"]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--since", type=date.fromisoformat)
    parser.add_argument("--until", type=date.fromisoformat)
    parser.add_argument("--quiz", type=Path, help="CSV with tester,age,before,after")
    parser.add_argument("--out", type=Path, help="also save the report as a Markdown file")
    args = parser.parse_args()

    engine = db.make_engine(get_settings().database_url)  # read-only use: no tables are created
    rounds = load_rounds(engine, args.since, args.until)
    radar = load_radar(engine, {r["player_id"] for r in rounds})
    quiz = load_quiz(args.quiz) if args.quiz else []
    report = to_markdown(summarize(rounds, radar, quiz), args.since, args.until)
    print(report)
    if args.out:
        args.out.write_text(report + "\n", encoding="utf-8")
        print(f"\nSaved to {args.out}")


if __name__ == "__main__":
    main()
