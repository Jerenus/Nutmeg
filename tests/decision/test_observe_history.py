import json
from pathlib import Path

from nutmeg.decision.observe_history import (
    factor_history,
    parse_attempts,
    rule_changes,
    trace_day,
)

GIT_OUT = ("abc1234|2026-09-19T10:00:00+08:00|feat(rules): C14 exemption\n"
           "def5678|2026-09-14T09:00:00+08:00|docs(rulebook): probation r3\n")


def test_rule_changes_parses_git_log_per_tracked_file(tmp_path: Path):
    calls = []

    def git(args: list[str]) -> str:
        calls.append(args)
        return GIT_OUT if "RULEBOOK.md" in args[-1] else ""

    rows = rule_changes(tmp_path, git=git)
    assert rows[0] == {"file": "docs/sop/RULEBOOK.md", "sha": "abc1234",
                       "at": "2026-09-19T10:00:00+08:00",
                       "subject": "feat(rules): C14 exemption"}
    assert [r["file"] for r in rows] == ["docs/sop/RULEBOOK.md"] * 2
    assert any("experiments/factors.json" in c[-1] for c in calls)


def test_parse_attempts_and_factor_history(tmp_path: Path):
    log = tmp_path / "experiments" / "attempts.log"
    log.parent.mkdir(parents=True)
    log.write_text("# 头\n# ts | 实验 | 参数 | 结果 | 结论\n"
                   "2026-09-22T17:11 | propose C11 | n=120 | R=+0.2pp | propose_zero\n"
                   "2026-09-22T17:11 | hyp 基线 | corpus=v2 | R=+1.5pp | 证伪\n"
                   "bad line\n", encoding="utf-8")
    rows = parse_attempts(log)
    assert rows == [
        {"ts": "2026-09-22T17:11", "experiment": "propose C11", "params": "n=120",
         "result": "R=+0.2pp", "conclusion": "propose_zero"},
        {"ts": "2026-09-22T17:11", "experiment": "hyp 基线", "params": "corpus=v2",
         "result": "R=+1.5pp", "conclusion": "证伪"},
    ]
    (tmp_path / "experiments" / "factors.json").write_text(json.dumps({"factors": [
        {"factor_id": "C11", "layer": "probability", "current_weight_pp": 0,
         "rule_name": "价格带"}]}), encoding="utf-8")
    hist = factor_history(tmp_path)
    assert hist["factors"][0]["factor_id"] == "C11"
    assert hist["factors"][0]["attempts"][0]["conclusion"] == "propose_zero"
    assert hist["other_attempts"][0]["experiment"] == "hyp 基线"


def test_trace_day_joins_reads_with_next_day_results(tmp_path: Path):
    out = tmp_path / "daily" / "2026-09-22"
    out.mkdir(parents=True)
    (out / "brief.json").write_text(json.dumps({"date": "2026-09-22", "jczq": {"matches": [
        {"code": "周二001", "name": "A vs B", "ladder": "偏移",
         "read": {"judge": "ai", "prior": {"home": .5, "draw": .3, "away": .2},
                  "belief": {"home": .3, "draw": .3, "away": .4}}},
        {"code": "周二002", "name": "C vs D", "ladder": "跟市场",
         "read": {"judge": "market-anchor", "prior": {"home": .6, "draw": .2, "away": .2},
                  "belief": {"home": .6, "draw": .2, "away": .2}}},
        {"code": "周二003", "name": "E vs F", "ladder": "未判", "read": None},
    ], "counts": {}}, "zucai": {"issue": None}, "rsi": None, "factors": [], "errors": []}),
        encoding="utf-8")
    nxt = tmp_path / "daily" / "2026-09-23"
    nxt.mkdir()
    (nxt / "results-90.json").write_text(json.dumps(
        {"周二001": {"outcome_90": "0", "goals_h": 0, "goals_a": 1},
         "周二002": {"outcome_90": "1", "goals_h": 1, "goals_a": 1}}), encoding="utf-8")
    (tmp_path / "analytics" / "rsi-loop").mkdir(parents=True)
    (tmp_path / "analytics" / "rsi-loop" / "2026-09-22.json").write_text(json.dumps(
        {"verdicts": [{"cmd": "rsi verdict --exp F3", "status": "not_due",
                       "line": "未到期：距 n_min 还差 97"}]}), encoding="utf-8")
    tr = trace_day(tmp_path, "2026-09-22")
    by = {r["code"]: r for r in tr["matches"]}
    assert by["周二001"] == {"code": "周二001", "name": "A vs B", "ladder": "偏移",
                            "judge": "ai", "prior_top": "home", "belief_top": "away",
                            "outcome": "away", "market_right": False, "read_right": True,
                            "moved_helped": True}
    assert by["周二002"]["read_right"] is False
    assert by["周二002"]["moved_helped"] is None
    assert by["周二003"]["outcome"] is None
    assert tr["not_due"] == [{"exp": "F3", "line": "未到期：距 n_min 还差 97"}]
    assert tr["summary"] == {"graded": 2, "read_right": 1, "market_right": 0, "moved": 1,
                             "moved_helped": 1}
