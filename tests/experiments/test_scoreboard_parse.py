import importlib.util
from pathlib import Path

_PATH = Path(__file__).parents[2] / "experiments" / "scoreboard_parse.py"
_SPEC = importlib.util.spec_from_file_location("scoreboard_parse", _PATH)
assert _SPEC and _SPEC.loader
scoreboard_parse = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(scoreboard_parse)


def test_parse_tally_extracts_counts_residual_ci_and_verdict():
    entry = scoreboard_parse.parse_tally("⛔证伪 (291条决策/18期, R_excl=-2.3pp, CI含0)")
    assert entry["n"] == 291 and entry["issues"] == 18
    assert entry["R_pp"] == -2.3 and entry["ci_contains_zero"] is True
    assert entry["verdict"] == "falsified"
    entry = scoreboard_parse.parse_tally("⛔证伪 (n=178, R=-0.9pp, MDE80=8.9pp)")
    assert entry["n"] == 178 and entry["mde80_pp"] == 8.9 and entry["ci"] is None


def test_parse_tally_reads_fractions_streaks_and_explicit_ci():
    entry = scoreboard_parse.parse_tally("3/6未赢;持平开平分型2/2→3/6已退休")
    assert (entry["hits"], entry["total"]) == (3, 6) and entry["verdict"] == "retired"
    entry = scoreboard_parse.parse_tally("连续2期保守成本(26123+26124)")
    assert entry["streak_issues"] == 2 and entry["verdict"] == "conservatism_cost"
    entry = scoreboard_parse.parse_tally("n=42 R=+5.1pp CI[+0.3,+9.9] 确认")
    assert entry["ci"] == [0.3, 9.9] and entry["ci_contains_zero"] is False
    assert entry["verdict"] == "confirmed"


def test_parse_tally_leaves_unknown_fields_none_and_never_guesses():
    entry = scoreboard_parse.parse_tally("4例后已禁用")
    assert entry["cases"] == 4 and entry["verdict"] == "disabled"
    assert entry["n"] is None and entry["R_pp"] is None and entry["hits"] is None
    issues = scoreboard_parse.parse_tally("26127/26128 两期严格裁决 3/9")
    assert (issues["hits"], issues["total"]) == (3, 9)
    empty = scoreboard_parse.parse_tally("")
    assert all(empty[k] is None for k in ("n", "hits", "R_pp", "ci", "verdict"))


def test_parse_scoreboard_reports_coverage_and_copies_status():
    doc = {
        "updated_at": "2026-09-19",
        "chains": {
            "a": {"tally": "1/1正样本", "status": "active"},
            "b": {"tally": "散文而已", "status": "probation"},
        },
    }
    result = scoreboard_parse.parse_scoreboard(doc)
    assert result["coverage"] == {"chains": 2, "machine_readable": 1}
    assert result["chains"]["a"]["status"] == "active"
    assert result["chains"]["b"]["machine_readable"] is False
