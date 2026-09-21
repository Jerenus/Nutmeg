import json
import threading
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
    daily = json.loads(
        (root / "daily" / "2026-09-19" / "research-run-2026-09-19.json").read_text(
            encoding="utf-8"
        )
    )
    assert daily["run_count"] == 2
    assert len(daily["runs"]) == 2
    assert {row["status"] for row in daily["matches"]} == {"done", "skipped_done"}


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


def test_intake_error_is_rejected_before_fulfill(tmp_path):
    root = _board(tmp_path, n=1)
    invalid = json.loads(GOOD)
    invalid["crash_markers"] = ["这是一整段被错误写进标签位的叙述" * 8]
    fulfills = []

    report = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=lambda system, brief: (0, json.dumps(invalid, ensure_ascii=False)),
        fulfill=lambda argv: fulfills.append(argv) or (0, ""),
        profile=lambda match_id: {},
        budget=1,
    )

    assert report["matches"][0]["status"] == "rejected"
    assert fulfills == []
    day_dir = root / "daily" / "2026-09-19"
    board = json.loads((day_dir / "jczq-legs-base.json").read_text(encoding="utf-8"))
    assert board["legs"]["周五001"]["judgment_tier"] == "price_only"
    assert not (day_dir / "research-周五001.json").exists()


def test_runner_honours_concurrency_limit(tmp_path):
    root = _board(tmp_path, n=2)
    barrier = threading.Barrier(2)

    def concurrent(system, brief):
        barrier.wait(timeout=2)
        return 0, GOOD

    report = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=concurrent,
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=2,
        concurrency=2,
    )

    assert [row["status"] for row in report["matches"]] == ["done", "done"]


def test_max_turns_is_permanent_without_resending_same_brief(tmp_path):
    root = _board(tmp_path, n=1)
    calls = []
    now = datetime(2026, 9, 19, 10, 0, tzinfo=BJ)

    report = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=lambda system, brief: (
            calls.append(brief) or (1, "Error: Reached max turns (12)")
        ),
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=10,
        now=lambda: now,
    )

    assert len(calls) == 1
    assert report["used_attempts"] == 1
    assert report["written"] == 0
    rejected_path = root / "daily" / "2026-09-19" / "research-周五001.rejected.json"
    rejected = json.loads(rejected_path.read_text(encoding="utf-8"))
    assert rejected["attempts_total"] == 1
    assert rejected["last_attempt_at"] == now.isoformat(timespec="seconds")
    assert rejected["next_retry_after"] is None
    assert rejected["permanent"] is True

    second_calls = []
    second = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=lambda system, brief: second_calls.append(brief) or (0, GOOD),
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=10,
        now=lambda: now + timedelta(hours=6),
    )
    assert second["matches"][0]["status"] == "skipped_permanent"
    assert second["used_attempts"] == 0
    assert second_calls == []


def test_network_failure_retries_then_obeys_cross_call_backoff(tmp_path):
    root = _board(tmp_path, n=1)
    calls = []
    now = datetime(2026, 9, 19, 10, 0, tzinfo=BJ)

    def network_failure(system, brief):
        calls.append(brief)
        raise TimeoutError("network timeout")

    first = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=network_failure,
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=10,
        now=lambda: now,
    )
    assert first["matches"][0]["status"] == "rejected"
    assert first["used_attempts"] == 2
    assert len(calls) == 2
    rejected_path = root / "daily" / "2026-09-19" / "research-周五001.rejected.json"
    rejected = json.loads(rejected_path.read_text(encoding="utf-8"))
    assert rejected["attempts_total"] == 2
    assert rejected["next_retry_after"] == (
        now + timedelta(hours=4)
    ).isoformat(timespec="seconds")
    assert rejected["permanent"] is False

    backoff_calls = []
    backed_off = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=lambda system, brief: backoff_calls.append(brief) or (0, GOOD),
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=10,
        now=lambda: now + timedelta(hours=3),
    )
    assert backed_off["matches"][0]["status"] == "skipped_backoff"
    assert backed_off["used_attempts"] == 0
    assert backoff_calls == []

    retried = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=lambda system, brief: (0, GOOD),
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=10,
        now=lambda: now + timedelta(hours=4),
    )
    assert retried["matches"][0]["status"] == "done"
    assert retried["used_attempts"] == 1
    assert retried["written"] == 1


def test_varying_cli_exit_failures_are_not_marked_permanent(tmp_path):
    root = _board(tmp_path, n=1)
    now = datetime(2026, 9, 19, 10, 0, tzinfo=BJ)
    return_codes = iter((1, 2))

    first = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=lambda system, brief: (next(return_codes), "provider rejected"),
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=10,
        now=lambda: now,
    )
    assert first["matches"][0]["status"] == "rejected"
    rejected_path = root / "daily" / "2026-09-19" / "research-周五001.rejected.json"
    rejected = json.loads(rejected_path.read_text(encoding="utf-8"))
    assert rejected["permanent"] is False
    assert len(set(rejected["attempt_errors"])) == 2

    second = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=lambda system, brief: (0, GOOD),
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=10,
        now=lambda: now + timedelta(hours=1),
    )
    assert second["matches"][0]["status"] == "skipped_backoff"


def test_identical_cli_exit_failures_are_permanent_with_explicit_evidence(tmp_path):
    root = _board(tmp_path, n=1)

    report = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=lambda system, brief: (1, "provider rejected"),
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=10,
    )

    assert report["matches"][0]["status"] == "rejected"
    rejected = json.loads(
        (
            root / "daily" / "2026-09-19" / "research-周五001.rejected.json"
        ).read_text(encoding="utf-8")
    )
    assert rejected["permanent"] is True
    assert len(rejected["attempt_errors"]) == 2
    assert rejected["attempt_errors"][0] == rejected["attempt_errors"][1]


def test_legacy_cli_exit_without_attempt_evidence_stays_retryable(tmp_path):
    root = _board(tmp_path, n=1)
    now = datetime(2026, 9, 19, 10, 0, tzinfo=BJ)
    rejected_path = root / "daily" / "2026-09-19" / "research-周五001.rejected.json"
    rejected_path.write_text(
        json.dumps(
            {
                "code": "周五001",
                "attempts": 2,
                "error": "claude 退出码 1",
                "raw_output": "provider rejected",
                "last_attempt_at": now.isoformat(timespec="seconds"),
            }
        ),
        encoding="utf-8",
    )

    report = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=lambda system, brief: (0, GOOD),
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=10,
        now=lambda: now + timedelta(hours=1),
    )

    assert report["matches"][0]["status"] == "skipped_backoff"
    migrated = json.loads(rejected_path.read_text(encoding="utf-8"))
    assert migrated["permanent"] is False


def test_budget_is_consumed_by_actual_attempts_not_matches(tmp_path):
    root = _board(tmp_path, n=2)
    calls = []

    def invalid(system, brief):
        calls.append(brief)
        return 0, "not json"

    report = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=invalid,
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=2,
        concurrency=1,
    )

    assert len(calls) == 2
    assert report["used_attempts"] == 2
    assert report["written"] == 0
    assert [row["status"] for row in report["matches"]] == ["rejected", "rejected"]
    assert all(row["attempts"] == 1 for row in report["matches"])
