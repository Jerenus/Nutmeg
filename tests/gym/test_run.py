import json
import shutil
from pathlib import Path

from nutmeg.decision.betslip import BetSlip, SlipLeg
from nutmeg.gym.board import JczqBoard
from nutmeg.gym.policy import Ctx, register
from nutmeg.gym.report import render
from nutmeg.gym.run import max_drawdown, run_gym, summarize
from tests.gym.test_board import DAY, _jczq_day, _zucai_issue


def _two_days(tmp_path: Path) -> Path:
    data = _jczq_day(tmp_path)
    src = data / "jczq" / "daily" / DAY
    dst = data / "jczq" / "daily" / "2026-09-21"
    shutil.copytree(src, dst)
    results = json.loads((data / "jczq" / "jc-results.json").read_text(encoding="utf-8"))
    results["2026-09-21"] = results[DAY]
    (data / "jczq" / "jc-results.json").write_text(json.dumps(results), encoding="utf-8")
    _zucai_issue(tmp_path)
    return data


@register
class _LoseBig:
    """测试用：押周六001 客胜（实际主胜）2 串 1，倍数 1500 → 一天亏 ¥3,000。"""
    name = "_test_lose_big"
    version = "v0"
    channels = ("jczq",)

    def decide(self, board: JczqBoard, ctx: Ctx):
        legs = [SlipLeg(key="周六001", name="a", market="had", line=None, selections=("away",),
                        odds=(3.9,), fair=None),
                SlipLeg(key="周六002", name="b", market="had", line=None, selections=("home",),
                        odds=(1.85,), fair=None)]
        return [BetSlip(slip_id=f"lose-{board.day}", channel="jczq", placed_at=board.day,
                        legs=legs, multiplier=1500, combo_sizes=(2,))]


def test_run_books_every_slip_and_enforces_the_monthly_brake(tmp_path: Path) -> None:
    data = _two_days(tmp_path)
    out = tmp_path / "out"

    result = run_gym(data_dir=data, out_dir=out, run_id="t",
                     policies=["flat", "jczq_max_p", "_test_lose_big", "zucai_max_p"])

    assert result.days == [DAY, "2026-09-21"] and result.issues == ["26127"]
    assert result.per_policy["flat"]["net"] == 0 and result.per_policy["flat"]["slips"] == 0
    lose = [r for r in result.ledger if r["policy"] == "_test_lose_big"]
    # 周六002 无赛果 → 2 串 1 未结；赛果缺的腿不该算输：这里 pending，不触发止损
    assert lose[0]["net"] is None and lose[0]["pending_legs"] == 1
    maxp = [r for r in result.ledger if r["policy"] == "jczq_max_p"]
    assert maxp and all(r["legal"] is None for r in maxp)
    zucai = [r for r in result.ledger if r["policy"] == "zucai_max_p"]
    assert zucai and zucai[0]["issue"] == "26127" and zucai[0]["regime"] in {"hot", "mid", "cold"}
    assert (out / "ledger.jsonl").exists() and (out / "summary.json").exists()
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert set(summary["policies"]) == {"flat", "jczq_max_p", "_test_lose_big", "zucai_max_p"}
    assert "regret_vs_flat" in summary["policies"]["jczq_max_p"]
    text = render(result)
    assert "| flat |" in text and "regime 分桶" in text


def test_brake_forces_flat_after_a_3000_month(tmp_path: Path) -> None:
    data = _two_days(tmp_path)
    results = json.loads((data / "jczq" / "jc-results.json").read_text(encoding="utf-8"))
    for day in (DAY, "2026-09-21"):
        results[day]["周六002"] = {"match_id": "2", "ft_home": 1, "ft_away": 0}   # 让 2 串 1 可结
    (data / "jczq" / "jc-results.json").write_text(json.dumps(results), encoding="utf-8")

    result = run_gym(data_dir=data, policies=["_test_lose_big"], issues=[], run_id="t")

    rows = [r for r in result.ledger if r["policy"] == "_test_lose_big"]
    assert rows[0]["key"] == DAY and rows[0]["net"] == -3000 and rows[0]["forced_flat"] is False
    assert len(rows) == 1                                   # 第二天被止损空仓，没有票
    assert result.per_policy["_test_lose_big"]["net"] == -3000
    assert result.per_policy["_test_lose_big"]["max_drawdown"] == -3000


def test_summarize_and_drawdown_math() -> None:
    rows = [{"key": "d1", "stake": 10, "net": 5.0, "policy": "p"},
            {"key": "d2", "stake": 10, "net": -8.0, "policy": "p"},
            {"key": "d2", "stake": 10, "net": 1.0, "policy": "p"},
            {"key": "d3", "stake": 10, "net": None, "policy": "p", "legal": "single_not_allowed:x"}]
    s = summarize(rows)
    assert s["keys"] == 2 and s["net"] == -2.0 and s["stake"] == 30 and s["illegal"] == 1
    assert s["max_drawdown"] == -7.0 and s["ci"][0] <= s["net"] <= s["ci"][1]   # d1 +5, d2 −7
    assert max_drawdown([5, -8, 1]) == -8.0 and max_drawdown([]) == 0.0          # 峰 5 → 谷 −3
