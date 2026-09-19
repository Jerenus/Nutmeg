import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from nutmeg.decision.research_runner import RESEARCH_DAILY_BUDGET, run_day

BJ = ZoneInfo("Asia/Shanghai")
GOOD = json.dumps(
    {
        "name": "A-B",
        "summary": "s",
        "confidence": 3,
        "anchor_integrity": "pass",
        "license_questions": {
            "q1_spine": True,
            "q2_route": True,
            "q3a_opponent_scores": False,
            "q3b_opponent_takes_points": False,
            "q4_no_context_flag": True,
        },
        "death_three_proofs": {},
        "directional_flags": [],
        "nondirectional_flags": [],
        "crash_markers": [],
        "precedents": [],
    },
    ensure_ascii=False,
)


def _board(tmp_path, n=3, hours_ahead=5):
    day_dir = tmp_path / "daily" / "2026-09-19"
    day_dir.mkdir(parents=True)
    kickoff = (datetime.now(BJ) + timedelta(hours=hours_ahead)).isoformat(
        timespec="seconds"
    )
    legs = {
        f"周五00{i}": {
            "match_id": f"m-{i}",
            "name": f"T{i}-U{i}",
            "competition": "x",
            "kickoff_bj": kickoff,
            "fair": {"home": 0.5, "draw": 0.3, "away": 0.2},
            "hhad_line": None,
            "judgment_tier": "price_only",
            "faces": "310",
        }
        for i in range(1, n + 1)
    }
    (day_dir / "jczq-legs-base.json").write_text(
        json.dumps({"day": "2026-09-19", "legs": legs}), encoding="utf-8"
    )
    return tmp_path


def test_runs_each_match_once_and_writes_products_and_fulfills(tmp_path):
    root = _board(tmp_path)
    calls, fulfills = [], []
    report = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=lambda system, brief: (calls.append(brief) or (0, GOOD)),
        fulfill=lambda argv: fulfills.append(argv) or (0, ""),
        profile=lambda match_id: {},
        budget=10,
    )

    assert [row["status"] for row in report["matches"]] == ["done"] * 3
    assert len(calls) == 3
    assert (root / "daily" / "2026-09-19" / "research-周五001.json").exists()
    assert all(
        argv[:4] == ["rsi", "fulfill", "--exp", "R0"] and "--match" in argv
        for argv in fulfills
    )

    second = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=lambda system, brief: (0, GOOD),
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=10,
    )
    assert [row["status"] for row in second["matches"]] == ["skipped_done"] * 3


def test_budget_and_past_kickoff_are_recorded_not_faked(tmp_path):
    root = _board(tmp_path, n=3)
    report = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=lambda system, brief: (0, GOOD),
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=2,
    )
    assert [row["status"] for row in report["matches"]] == [
        "done",
        "done",
        "skipped_budget",
    ]
    legs = json.loads(
        (root / "daily" / "2026-09-19" / "jczq-legs-base.json").read_text(
            encoding="utf-8"
        )
    )["legs"]
    assert legs["周五003"]["judgment_tier"] == "price_only"

    late_root = _board(tmp_path / "late", n=1, hours_ahead=-1)
    late = run_day(
        day="2026-09-19",
        jczq_dir=late_root,
        data_dir=tmp_path / "late",
        claude=lambda system, brief: (0, GOOD),
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=10,
    )
    assert late["matches"][0]["status"] == "skipped_past_kickoff"
    assert RESEARCH_DAILY_BUDGET == 40


def test_invalid_json_is_rejected_once_and_leg_stays_price_only(tmp_path):
    root = _board(tmp_path, n=1)
    attempts = {"count": 0}

    def bad(system, brief):
        attempts["count"] += 1
        return 0, "not json"

    report = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=bad,
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=10,
    )

    assert report["matches"][0]["status"] == "rejected"
    assert attempts["count"] == 2
    day_dir = root / "daily" / "2026-09-19"
    assert (day_dir / "research-周五001.rejected.json").exists()
    assert not (day_dir / "research-周五001.json").exists()
