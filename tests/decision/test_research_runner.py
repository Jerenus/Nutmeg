import json
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

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
        "stance": {
            "face": "3",
            "structure": "double",
            "cover": "1",
            "confidence": 3,
            "falsifier": "客队首发若有主力门将则本判断作废",
            "why_not_market": "none",
            "tilt": None,
            "alt_face": "1",
            "market_read": "agree",
        },
        "rubric": {"version": "r1", "items": {"S_anchor_side": {"answer": "home"}}},
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
    # 模型是 RSI 的实验变量：产物与运行记录都要带模型标签（注入的 claude → "default"）
    written = json.loads(
        (root / "daily" / "2026-09-19" / "research-周五001.json").read_text(encoding="utf-8")
    )
    assert written["model"] == "default"
    assert all(row["model"] == "default" for row in report["matches"])
    assert all(
        argv[:3] == ["rsi", "fulfill", "--exp"] and argv[3] in {"R0", "R1"} and "--match" in argv
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
    assert RESEARCH_DAILY_BUDGET == 10000  # 2026-10-25 Jun：40 → 10000，预算不再是进样瓶颈


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
    # 2026-10-26 起嵌套标签只是 WARN 入库；拒收只剩缺核心——用非法的表态结构触发
    invalid["stance"] = {**invalid["stance"], "structure": "triple"}
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


def test_max_turns_retries_once_with_marker_then_is_permanent(tmp_path):
    from nutmeg.decision.research_runner import RETRY_MARKER

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

    assert len(calls) == 2
    assert RETRY_MARKER not in calls[0]
    assert RETRY_MARKER in calls[1]
    assert report["used_attempts"] == 2
    assert report["written"] == 0
    rejected_path = root / "daily" / "2026-09-19" / "research-周五001.rejected.json"
    rejected = json.loads(rejected_path.read_text(encoding="utf-8"))
    assert rejected["attempts_total"] == 2
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


def test_max_turns_then_success_on_marked_retry(tmp_path):
    from nutmeg.decision.research_runner import RETRY_MARKER

    root = _board(tmp_path, n=1)

    def claude(system, brief):
        if RETRY_MARKER in brief:
            return 0, GOOD
        return 1, "Error: Reached max turns (12)"

    report = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=claude,
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=10,
        now=lambda: datetime(2026, 9, 19, 10, 0, tzinfo=BJ),
    )

    assert report["matches"][0]["status"] == "done"
    assert report["used_attempts"] == 2
    assert report["written"] == 1
    day_dir = root / "daily" / "2026-09-19"
    assert (day_dir / "research-周五001.json").exists()
    assert not (day_dir / "research-周五001.rejected.json").exists()


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


def test_missing_stance_is_rejected_by_validate(tmp_path):
    from nutmeg.decision.research_runner import _validate

    doc = json.loads(GOOD)
    doc.pop("stance")
    with pytest.raises(ValueError, match="stance"):
        _validate(
            json.dumps(doc, ensure_ascii=False),
            {"fair": {"home": 0.5, "draw": 0.3, "away": 0.2}, "match_no": 1},
        )


@pytest.mark.parametrize("wrap", [
    "先说明：我查了几篇前瞻，下面按契约出判读。\n\n{doc}",
    "```json\n{doc}\n```\n补充说明：伤停未证实。",
    "{doc}\n\n{doc}",
])
def test_validate_takes_the_first_json_object_out_of_chatter(wrap):
    from nutmeg.decision.research_runner import _validate

    doc = _validate(
        wrap.replace("{doc}", GOOD),
        {"fair": {"home": 0.5, "draw": 0.3, "away": 0.2}, "match_no": 1},
    )
    assert doc["name"] == "A-B"


def test_never_attempted_matches_get_the_budget_before_retries(tmp_path):
    """晚上新上板的场次不能被白天的重试饿死（2026-09-26 024/025 skipped_budget）。"""
    root = _board(tmp_path, n=2)
    day_dir = root / "daily" / "2026-09-19"
    (day_dir / "research-周五001.rejected.json").write_text(json.dumps({
        "code": "周五001", "attempts_total": 1, "permanent": False,
        "last_attempt_at": (datetime.now(BJ) - timedelta(hours=6)).isoformat(),
        "attempt_errors": ["not json"], "error": "not json", "raw_output": "x",
    }), encoding="utf-8")
    briefs = []

    report = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=lambda system, brief: briefs.append(brief) or (0, GOOD),
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=1,
        concurrency=1,
    )

    status = {row["code"]: row["status"] for row in report["matches"]}
    assert status == {"周五001": "skipped_budget", "周五002": "done"}


def test_zucai_only_matches_are_researched_first_and_land_in_the_zucai_dir(tmp_path):
    """并集样本池（Jun 2026-09-27）：当天截止足彩里不在竞彩板上的场次先研究。"""
    root = _board(tmp_path, n=1)
    zdir = tmp_path / "zucai"
    zdir.mkdir()
    kickoff = (datetime.now(BJ) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    (zdir / "26133-issue.json").write_text(json.dumps({
        "issue_id": "26133", "sale_deadline": "2026-09-19 20:30",
        "matches": [{"match_no": 1, "competition": "友谊赛", "home_team": "中国",
                     "away_team": "新西兰", "kickoff_bj": kickoff}]}, ensure_ascii=False),
        encoding="utf-8")
    (zdir / "26133-store-ids.json").write_text(json.dumps({"1": {
        "match_no": 1, "match_id": "z-1", "fair": {"home": 0.36, "draw": 0.28, "away": 0.36}}}),
        encoding="utf-8")
    fulfills = []

    report = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=lambda system, brief: (0, GOOD),
        fulfill=lambda argv: fulfills.append(argv) or (0, ""),
        profile=lambda match_id: {},
        budget=1,
        concurrency=1,
    )

    status = {row["code"]: row["status"] for row in report["matches"]}
    assert status == {"周五001": "skipped_budget", "足彩26133-01": "done"}
    assert (zdir / "26133-research-m1.json").exists()
    assert [argv[3] for argv in fulfills] == ["R1"]
    assert fulfills[0][-2:] == ["--issue", "26133"]   # 足彩场次凭期号查开球


def test_zucai_pool_still_runs_when_the_jczq_board_failed_to_load(tmp_path):
    """2026-09-28 出生事故：08:00 体彩 WAF 降级，当天没有 jczq-legs-base.json →
    run_day 读板直接 FileNotFoundError，足彩 26134 十四场一场都研究不了。"""
    zdir = tmp_path / "zucai"
    zdir.mkdir()
    kickoff = (datetime.now(BJ) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    (zdir / "26134-issue.json").write_text(json.dumps({
        "issue_id": "26134", "sale_deadline": "2026-09-19 22:00",
        "matches": [{"match_no": 1, "competition": "欧国联", "home_team": "亚美尼",
                     "away_team": "黑山", "kickoff_bj": kickoff}]}, ensure_ascii=False),
        encoding="utf-8")
    (zdir / "26134-store-ids.json").write_text(json.dumps({"1": {
        "match_no": 1, "match_id": "z-1", "fair": {"home": 0.33, "draw": 0.30, "away": 0.37}}}),
        encoding="utf-8")

    report = run_day(
        day="2026-09-19",
        jczq_dir=tmp_path,
        data_dir=tmp_path,
        claude=lambda system, brief: (0, GOOD),
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=1,
        concurrency=1,
    )

    assert {row["code"]: row["status"] for row in report["matches"]} == {"足彩26134-01": "done"}
    assert (zdir / "26134-research-m1.json").exists()


def _overlap_issue(tmp_path, *, with_research=True):
    """足彩 26133 场1 = 竞彩 周五001（同一场比赛），足彩那边已研究完。"""
    zdir = tmp_path / "zucai"
    zdir.mkdir()
    kickoff = (datetime.now(BJ) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")
    (zdir / "26133-issue.json").write_text(json.dumps({
        "issue_id": "26133", "sale_deadline": "2026-09-19 22:00",
        "matches": [{"match_no": 1, "competition": "欧国联", "home_team": "中国",
                     "away_team": "新西兰", "kickoff_bj": kickoff,
                     "match_date": "2026-09-19"}]}, ensure_ascii=False), encoding="utf-8")
    (zdir / "26133-store-ids.json").write_text(json.dumps({"1": {
        "match_no": 1, "match_id": "z-1", "fair": {"home": 0.36, "draw": 0.28, "away": 0.36}}}),
        encoding="utf-8")
    if with_research:
        (zdir / "26133-research-m1.json").write_text(GOOD, encoding="utf-8")
    return zdir


def _run(tmp_path, root, calls, fulfills, **kwargs):
    return run_day(
        day="2026-09-19", jczq_dir=root, data_dir=tmp_path,
        claude=lambda system, brief: (calls.append(brief) or (0, GOOD)),
        fulfill=lambda argv: fulfills.append(argv) or (0, ""),
        profile=lambda match_id: {}, budget=5, concurrency=1, **kwargs)


def test_board_match_reuses_zucai_research_instead_of_researching_twice(tmp_path):
    """2026-09-28 出生事故：足彩 08:03 已研究 6 场，11:01 竞彩开售后 11:04 又按竞彩编号
    研究一遍——同一场比赛花两次预算。经对号表认定同场的，竞彩一侧直接复用。"""
    root = _board(tmp_path, n=1)
    zdir = _overlap_issue(tmp_path)
    (zdir / "26133-channel-map.json").write_text(json.dumps({"m-1": 1}), encoding="utf-8")
    calls, fulfills = [], []

    report = _run(tmp_path, root, calls, fulfills)

    assert {row["code"]: row["status"] for row in report["matches"]} == {"周五001": "reused_zucai"}
    assert calls == [] and report["used_attempts"] == 0
    written = json.loads((root / "daily" / "2026-09-19" / "research-周五001.json")
                         .read_text(encoding="utf-8"))
    assert written["reused_from"].endswith("26133-research-m1.json")
    # 只补 R0：R1 并集池里这场已由足彩研究计过
    assert [argv[3] for argv in fulfills] == ["R0"]


def test_code_can_target_a_zucai_only_match(tmp_path):
    """2026-09-28：`--code 足彩26134-14` 只匹配竞彩板，反而把足彩池整个跳过。"""
    root = _board(tmp_path, n=1)
    _overlap_issue(tmp_path, with_research=False)
    calls, fulfills = [], []

    report = _run(tmp_path, root, calls, fulfills, code="足彩26133-01")

    assert {row["code"]: row["status"] for row in report["matches"]} == {"足彩26133-01": "done"}
    assert len(calls) == 1


def test_missing_channel_map_is_built_from_the_live_board_before_reuse(tmp_path):
    """11:00 早间备料时板面还没开售、没有对号表；研究时板面已在，就地按备料同一
    对齐函数补落 `.auto`，再据此复用——身份不靠 fair 反查。"""
    root = _board(tmp_path, n=1)
    zdir = _overlap_issue(tmp_path)
    (root / "daily" / "2026-09-19" / "sporttery_markets.json").write_text(json.dumps({
        "matchInfoList": [{"businessDate": "2026-09-19", "subMatchList": [{
            "matchNum": 5001, "matchNumStr": "周五001", "businessDate": "2026-09-19",
            "homeTeamAllName": "中国", "homeTeamAbbName": "中国",
            "awayTeamAllName": "新西兰", "awayTeamAbbName": "新西兰"}]}]},
        ensure_ascii=False), encoding="utf-8")
    calls, fulfills = [], []

    report = _run(tmp_path, root, calls, fulfills)

    assert json.loads((zdir / "26133-channel-map.auto.json").read_text(encoding="utf-8")) \
        == {"m-1": 1}
    assert {row["code"]: row["status"] for row in report["matches"]} == {"周五001": "reused_zucai"}
    assert calls == []


def test_evidence_timestamps_are_stamped_by_the_system(tmp_path, monkeypatch):
    """派生 tilt 的 evidence 与 rubric 项都由系统盖章；分析员自填的时刻只留 *_declared。"""
    import functools

    from nutmeg.decision import rubric
    # 聚合按 r2 上限测（r3 起没有拨动项，2026-10-20）
    monkeypatch.setattr(rubric, "rubric_to_tilt",
                        functools.partial(rubric.rubric_to_tilt, version="r2"))
    root = _board(tmp_path, n=1)
    doc = json.loads(GOOD)
    doc["rubric"] = {"version": "r2", "items": {                  # r2 起只有 F_suspension 拨动
        "F_suspension": {"answer": "away", "p": 0.9, "source": "s",
                         "captured_at": "2026-09-19T00:00:00+08:00"},
        "S_anchor_side": {"answer": "home"}}}

    run_day(day="2026-09-19", jczq_dir=root, data_dir=tmp_path,
            claude=lambda system, brief: (0, json.dumps(doc, ensure_ascii=False)),
            fulfill=lambda argv: (0, ""), profile=lambda match_id: {}, budget=1)

    written = json.loads((root / "daily" / "2026-09-19" / "research-周五001.json")
                         .read_text(encoding="utf-8"))
    [evidence] = written["stance"]["tilt"]["evidence"]
    assert evidence["captured_at"] == written["captured_at"]
    assert evidence["captured_at_declared"] == "2026-09-19T00:00:00+08:00"
    item = written["rubric"]["items"]["F_suspension"]
    assert item["captured_at"] == written["captured_at"]
    assert item["captured_at_declared"] == "2026-09-19T00:00:00+08:00"


def test_missing_or_bad_rubric_never_rejects_a_deep_research(tmp_path):
    """保护池子（R0/R1 覆盖与 40 场/日预算）：rubric 缺失＝全部弃权，不合法选项改弃权。"""
    from nutmeg.decision.research_runner import _validate

    leg = {"fair": {"home": 0.5, "draw": 0.3, "away": 0.2}}
    doc = json.loads(GOOD)
    doc.pop("rubric")
    out = _validate(json.dumps(doc), leg)
    assert out["rubric_missing"] is True and out["stance"]["tilt"] is None
    assert all(r["abstain"] for r in out["rubric"]["items"].values())
    assert out["rubric_notes"] == ["rubric 缺失 → 全部弃权（跟市场）"]
    doc["rubric"] = {"version": "r7", "items": {"F_absence_home": {"p": 2},
                                                "F_goalkeeper": {"answer": "both"},
                                                "S_anchor_side": {"answer": "home"}},
                     "belief": {"3": 3}}
    out = _validate(json.dumps(doc), leg)
    assert out["rubric_missing"] is False and out["rubric"]["version"] == "r3"
    assert out["rubric"]["items"]["F_absence_home"]["abstain"]
    assert out["rubric"]["items"]["F_goalkeeper"]["answer"] == "unknown"
    assert out["rubric"]["items"]["S_anchor_side"]["answer"] == "home"
    assert out["rubric"]["belief"] is None and len(out["rubric_notes"]) >= 3


def test_rubric_items_are_stamped_and_tilt_is_derived_from_them(tmp_path, monkeypatch):
    import functools

    from nutmeg.decision import rubric
    # 聚合按 r2 上限测（r3 起没有拨动项，2026-10-20）
    monkeypatch.setattr(rubric, "rubric_to_tilt",
                        functools.partial(rubric.rubric_to_tilt, version="r2"))
    root = _board(tmp_path, n=1)
    doc = json.loads(GOOD)
    doc["stance"] = {**doc["stance"], "tilt": {"face": "3", "expires_if": "x", "evidence": [
        {"tier": "official", "kind": "absence_official", "pp": 5, "source": "s",
         "captured_at": "2026-09-19T08:00:00+08:00"}]}}
    doc["rubric"] = {"version": "r2", "items": {
        "F_suspension": {"answer": "away", "p": 0.9, "source": "https://club.example/news",
                         "captured_at": "2026-09-19T08:00:00+08:00"},
        # r2 上限退役：照记不拨
        "F_absence_away": {"p": 0.9, "source": "https://club.example/news",
                           "captured_at": "2026-09-19T08:00:00+08:00"},
        "F_absence_home": {"p": 0.9},                      # 无来源 → 强制弃权
        "S_anchor_side": {"answer": "home"},
        "M_market_read": {"answer": "agree"}},
        "belief": {"3": 0.55, "1": 0.27, "0": 0.18}}

    run_day(day="2026-09-19", jczq_dir=root, data_dir=tmp_path,
            claude=lambda system, brief: (0, json.dumps(doc, ensure_ascii=False)),
            fulfill=lambda argv: (0, ""), profile=lambda match_id: {}, budget=1)

    written = json.loads((root / "daily" / "2026-09-19" / "research-周五001.json")
                         .read_text(encoding="utf-8"))
    tilt = written["stance"]["tilt"]
    assert tilt["derived_from"] == "rubric:r2" and tilt["shift"]["0"] < 0 < tilt["shift"]["3"]
    assert [e["item"] for e in tilt["evidence"]] == ["F_suspension"]
    assert written["stance"]["tilt_declared"]["face"] == "3"          # 分析员手写的 tilt 只留痕
    assert written["stance"]["why_not_market"] == "tilt_evidence"
    items = written["rubric"]["items"]
    assert items["F_absence_home"]["abstain"] and items["F_absence_home"]["coerced"]
    assert items["F_suspension"]["captured_at"] == written["captured_at"]
    assert items["F_suspension"]["captured_at_declared"] == "2026-09-19T08:00:00+08:00"
    assert items["F_absence_away"]["answer"] == "yes"                 # 退役上限的项照记
    assert written["rubric"]["belief"] == {"3": 0.55, "1": 0.27, "0": 0.18}
    assert written["rubric"]["coerced"] == ["F_absence_home: 答是但无来源 → 弃权"]


AUTH_FAIL = "Failed to authenticate: OAuth session expired and could not be refreshed\n"


def test_auth_failure_stops_the_run_without_burning_budget_or_marking_permanent(tmp_path):
    """10-06 11:13：launchd 下 claude OAuth 过期，12 场每场试 2 次、各记一份「永久拒绝」，
    烧掉 24 次预算，修好登录后补跑也不会再试。认证失败是环境问题，不是这场比赛的问题：
    第一次撞到就停整轮，不重试、不记拒绝、不占预算。"""
    root = _board(tmp_path, n=3)
    calls = []

    def logged_out(system, brief):
        calls.append(brief)
        return 1, AUTH_FAIL

    report = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=logged_out,
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=10,
        concurrency=1,
    )

    assert len(calls) == 1
    assert report["used_attempts"] == 0
    assert report["auth_failed"] is True
    assert [row["status"] for row in report["matches"]] == [
        "auth_failed", "skipped_auth", "skipped_auth"]
    assert not list((root / "daily" / "2026-09-19").glob("*.rejected.json"))


def test_legacy_auth_only_rejection_is_retried_as_never_attempted(tmp_path):
    """修复前写下的「永久拒绝」若全是认证错误，按没试过处理（今天那 12 份）。"""
    root = _board(tmp_path, n=1)
    rejected_path = root / "daily" / "2026-09-19" / "research-周五001.rejected.json"
    rejected_path.write_text(
        json.dumps(
            {
                "code": "周五001",
                "attempts": 2,
                "attempts_total": 2,
                "last_attempt_at": datetime.now(BJ).isoformat(timespec="seconds"),
                "next_retry_after": None,
                "permanent": True,
                "attempt_errors": [f"claude 退出码 1\n{AUTH_FAIL.strip()}"] * 2,
                "error": "claude 退出码 1",
                "raw_output": AUTH_FAIL,
            },
            ensure_ascii=False,
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
    )

    assert report["matches"][0]["status"] == "done"


def test_legacy_auth_only_attempts_are_refunded_to_the_daily_budget(tmp_path):
    """修复前认证失败记下的尝试没调到模型，退回当天预算（10-06 烧掉的 24 次）。"""
    from nutmeg.decision.research_ledger import ResearchRunLedger

    root = _board(tmp_path, n=1)
    day_dir = root / "daily" / "2026-09-19"
    (day_dir / "research-周五001.rejected.json").write_text(
        json.dumps(
            {
                "code": "周五001", "attempts": 2, "attempts_total": 2,
                "last_attempt_at": datetime.now(BJ).isoformat(timespec="seconds"),
                "next_retry_after": None, "permanent": True,
                "attempt_errors": [f"claude 退出码 1\n{AUTH_FAIL.strip()}"] * 2,
                "error": "claude 退出码 1", "raw_output": AUTH_FAIL,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ResearchRunLedger(day_dir).append({
        "run_id": "rr-legacy", "idempotency_key": "research-run:2026-09-19:rr-legacy",
        "day": "2026-09-19", "budget": 2, "used_attempts": 2, "written": 0,
        "concurrency": 2, "started_at": "2026-09-19T08:00:00+08:00",
        "finished_at": "2026-09-19T08:00:05+08:00",
        "matches": [{"code": "周五001", "status": "rejected", "attempts": 2}],
    })

    report = run_day(
        day="2026-09-19",
        jczq_dir=root,
        data_dir=tmp_path,
        claude=lambda system, brief: (0, GOOD),
        fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {},
        budget=2,
    )

    assert report["matches"][0]["status"] == "done"


def test_a_second_run_on_the_same_day_skips_while_one_is_in_progress(tmp_path):
    """10-07 15:53 手动触发的一轮还在跑，16:00 sweep 又起一轮：同样 6 场研究两遍、
    多烧 12 次预算，第二轮还覆盖了已被读者 B 读过的研究原件。同日只许一轮在跑。"""
    import fcntl

    root = _board(tmp_path, n=2)
    day_dir = root / "daily" / "2026-09-19"
    calls = []
    with open(day_dir / ".research-run.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = run_day(
            day="2026-09-19",
            jczq_dir=root,
            data_dir=tmp_path,
            claude=lambda system, brief: (calls.append(brief), (0, GOOD))[1],
            fulfill=lambda argv: (0, ""),
            profile=lambda match_id: {},
            budget=10,
        )
    assert calls == []
    assert report["used_attempts"] == 0 and report["written"] == 0
    assert {row["status"] for row in report["matches"]} == {"skipped_busy"}


def test_board_match_that_is_also_a_zucai_match_jumps_the_queue(tmp_path):
    """2026-10-10 出生事故：26137 十四场里 11 场对上了竞彩板，排队时被当普通竞彩场按开球
    排在周六001–011 后面；预算 14 只研究了 3 场足彩。对上当天截止足彩期次的板面场同样优先。"""
    root = _board(tmp_path, n=2)
    zdir = _overlap_issue(tmp_path, with_research=False)
    (zdir / "26133-channel-map.json").write_text(json.dumps({"m-2": 1}), encoding="utf-8")

    report = run_day(
        day="2026-09-19", jczq_dir=root, data_dir=tmp_path,
        claude=lambda system, brief: (0, GOOD), fulfill=lambda argv: (0, ""),
        profile=lambda match_id: {}, budget=1, concurrency=1)

    status = {row["code"]: row["status"] for row in report["matches"]}
    assert status == {"周五001": "skipped_budget", "周五002": "done"}


def test_research_telemetry_is_recorded_per_match_and_summarised(tmp_path):
    """2026-10-26 Tier 1 #4：研究层此前零遥测。真 CLI 回三元 (rc, text, meta)，每场落
    model/duration_s/tokens/cost_usd；日投影顶层加 telemetry 汇总；旧式二元回调照样能跑。"""
    from nutmeg.decision.research_runner import research_telemetry_summary

    root = _board(tmp_path, n=2)
    meta = {"model": "claude-opus-5-5", "duration_s": 42.5, "input_tokens": 1200,
            "cache_read_input_tokens": 300, "cache_creation_input_tokens": 0,
            "output_tokens": 800, "cost_usd": 0.1234}
    calls = {"n": 0}

    def claude(system, brief):
        calls["n"] += 1
        if calls["n"] == 1:
            return 0, GOOD, meta            # 三元：带遥测
        return 0, GOOD                      # 二元：假回调仍兼容

    report = run_day(day="2026-09-19", jczq_dir=root, data_dir=tmp_path / "d", claude=claude,
                     fulfill=lambda argv: (0, ""), profile=lambda match_id: {}, budget=10,
                     concurrency=1)
    rows = {m["code"]: m for m in report["matches"]}
    assert rows["周五001"]["status"] == rows["周五002"]["status"] == "done"
    with_meta = rows["周五001"] if rows["周五001"]["cost_usd"] is not None else rows["周五002"]
    without = rows["周五002"] if with_meta is rows["周五001"] else rows["周五001"]
    assert with_meta["model"] == "claude-opus-5-5" and with_meta["cost_usd"] == 0.1234
    assert with_meta["duration_s"] == 42.5 and with_meta["input_tokens"] == 1200
    assert with_meta["output_tokens"] == 800
    assert without["cost_usd"] is None and without["model"] == "default"
    projection = json.loads(
        (root / "daily" / "2026-09-19" / "research-run-2026-09-19.json").read_text())
    tele = projection["telemetry"]
    assert tele["matches"] == 1 and tele["total_cost_usd"] == 0.1234
    assert tele["by_model"] == {"claude-opus-5-5": {"matches": 1, "cost_usd": 0.1234,
                                                    "duration_s": 42.5}}
    assert research_telemetry_summary(tmp_path / "d", "2026-09-19", jczq_dir=root) == tele
    assert research_telemetry_summary(tmp_path / "d", "2026-01-01")["matches"] == 0


def test_telemetry_accumulates_across_attempts(tmp_path):
    """首轮撞 max turns、重试成功 → 两次 tokens/成本相加，model 取最后一个。"""
    root = _board(tmp_path, n=1)
    replies = iter([
        (0, "Reached max turns", {"model": "m1", "cost_usd": 0.1, "output_tokens": 10,
                                  "duration_s": 5}),
        (0, GOOD, {"model": "m2", "cost_usd": 0.2, "output_tokens": 20, "duration_s": 7}),
    ])
    report = run_day(day="2026-09-19", jczq_dir=root, data_dir=tmp_path / "d",
                     claude=lambda s, b: next(replies), fulfill=lambda argv: (0, ""),
                     profile=lambda match_id: {}, budget=10)
    row = report["matches"][0]
    assert row["status"] == "done" and row["attempts"] == 2
    assert row["model"] == "m2" and row["cost_usd"] == 0.3 and row["output_tokens"] == 30
    assert row["duration_s"] == 12
