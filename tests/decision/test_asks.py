"""应答员（2026-11-02 产品形态 Task 10.4）：问进讨论流、线程按对象前缀、作答写回答行、
改表建议只落成纠正草稿 / 待签提案、失败照样留答行、输出不是 JSON 也能显示、密钥打码。"""
import json
from datetime import datetime

import pytest

from nutmeg.decision import asks, corrections, proposals
from nutmeg.decision.bj_time import BJ
from nutmeg.decision.day_session import read_discussion

AT = datetime(2026, 11, 2, 10, 41, tzinfo=BJ)


def _reply(**doc) -> str:
    return "好的，结论如下：\n" + json.dumps({"answer": "④ 应记 ✗", "sources": [], **doc},
                                         ensure_ascii=False)


def test_ask_goes_into_day_discussion_and_thread_covers_sub_objects(tmp_path):
    asks.ask(tmp_path, obj="issue:26153/m7", text="弗赖堡真的只轮换一处？", at=AT)
    asks.ask(tmp_path, obj="issue:26153/m7/q4", text="④ 格呢", at=AT)
    asks.ask(tmp_path, obj="issue:26153/m70", text="不该算进 m7", at=AT)
    rows = read_discussion(tmp_path, "2026-11-02")
    assert [r["ask"] for r in rows] == [True, True, True]
    assert rows[0]["who"] == "jun" and rows[0]["at"].startswith("2026-11-02T10:41")
    got = asks.thread(tmp_path, "issue:26153/m7", today="2026-11-02")
    assert [q["text"] for q in got] == ["弗赖堡真的只轮换一处？", "④ 格呢"]
    assert all(q["answer"] is None for q in got)
    assert len(asks.pending(tmp_path, today="2026-11-02")) == 3


@pytest.mark.parametrize("bad", ["", "26153/m7", "foo:1", "issue:", "issue:26153 m7"])
def test_bad_obj_is_refused(tmp_path, bad):
    with pytest.raises(ValueError):
        asks.ask(tmp_path, obj=bad, text="x", at=AT)


def test_empty_question_is_refused(tmp_path):
    with pytest.raises(ValueError):
        asks.ask(tmp_path, obj="issue:26153", text="  ", at=AT)


def test_answer_writes_reply_row_and_drafts_only(tmp_path):
    asks.ask(tmp_path, obj="issue:26153/m7", text="④ 对吗", at=AT)
    (q,) = asks.pending(tmp_path, today="2026-11-02")
    seen = {}

    def runner(system, stdin, *, data_dir):
        seen.update(system=system, stdin=stdin)
        return 0, _reply(
            sources=["zucai/26153-research-m7.json：欧战后轮换可控"],
            corrections=[{"obj": "issue:26153/m7/q4", "old": "④ ✓", "new": "④ ✗",
                          "kind": "premise", "evidence": "两场首发变了 7 人"},
                         {"obj": "bad obj", "old": "x", "new": "y"}],
            proposals=[{"title": "④ 机械判加首发对比", "body": "…", "blocks": "六条件 ④"}]), \
            {"duration_s": 100.0, "cost_usd": 0.12, "model": "sonnet"}

    pushed = []
    row = asks.answer(tmp_path, q, excerpt='{"no":"7"}', runner=runner,
                      push=lambda q, r: pushed.append((q["seq"], r["status"])))
    assert row["status"] == "answered" and row["text"] == "④ 应记 ✗"
    assert pushed == [(1, "answered")]
    assert "26153-research-m7.json" in seen["stdin"] and '{"no":"7"}' in seen["stdin"]
    assert "没有写权限" in seen["system"]

    rows = read_discussion(tmp_path, "2026-11-02")
    assert rows[1]["who"] == asks.ANSWERER and rows[1]["reply_to"] == 1
    assert rows[1]["duration_s"] == 100.0 and rows[1]["errors"][0].startswith("纠正草稿丢弃")
    assert asks.pending(tmp_path, today="2026-11-02") == []

    (c,) = corrections.load(tmp_path)
    assert (c["id"], c["status"], c["found_by"], c["new"]) == (rows[1]["corrections"][0], "draft",
                                                                "machine", "④ ✗")
    (p,) = proposals.load(tmp_path, today="2026-11-02")
    assert p["status"] == "pending" and p["id"] == rows[1]["proposals"][0]
    assert asks.thread(tmp_path, "issue:26153", today="2026-11-02")[0]["answer"]["seq"] == 2


def test_failed_run_leaves_a_failed_reply_and_names_login(tmp_path):
    asks.ask(tmp_path, obj="ledger:2026-10", text="10 月净多少", at=AT)
    (q,) = asks.pending(tmp_path, today="2026-11-02")
    row = asks.answer(tmp_path, q, excerpt="{}",
                      runner=lambda *a, **k: (1, "OAuth session expired", {}))
    assert row["status"] == "failed" and "/login" in row["text"]
    assert asks.pending(tmp_path, today="2026-11-02") == []   # 不自动重答；再问一次才重试

    asks.ask(tmp_path, obj="ledger:2026-10", text="再问", at=AT)
    (q,) = asks.pending(tmp_path, today="2026-11-02")

    def boom(*a, **k):
        raise TimeoutError("600s")
    assert "TimeoutError" in asks.answer(tmp_path, q, excerpt="{}", runner=boom)["text"]


def test_parse_reply_falls_back_to_plain_text():
    assert asks.parse_reply("就是不行")["answer"] == "就是不行"
    got = asks.parse_reply('{"answer": "行", "sources": "不是列表"}')
    assert got == {"answer": "行", "sources": [], "corrections": [], "proposals": []}


def test_redact_and_telegram_text():
    assert asks.redact("密码是 hunter2hunter2", ["hunter2hunter2"]) == "密码是 ＊＊＊"
    q = {"obj": "issue:26153/m7", "text": "④ 对吗"}
    text = asks.telegram_text(q, {"text": "不对", "corrections": ["c1"], "proposals": []},
                              base_url="http://10.0.0.2:8787")
    assert "纠正草稿 1 条待你确认" in text and text.endswith("打开 http://10.0.0.2:8787/issue/26153")
    assert "打开" not in asks.telegram_text(q, {"text": "x"}, base_url="")
    assert asks.page_path("jczq:2026-11-01/周日003") == "/jczq/2026-11-01"
    assert asks.page_path("rule:六条件④") == ""


def test_work_answers_pending_one_by_one_and_tracks_busy(tmp_path):
    asks.ask(tmp_path, obj="issue:26153/m1", text="a", at=AT)
    asks.ask(tmp_path, obj="jczq:2026-11-02/周日003", text="b", at=AT)
    busy, seen = set(), []

    def runner(system, stdin, *, data_dir):
        seen.append(set(busy))
        return 0, _reply(), {}

    done = asks.work(tmp_path, today="2026-11-02", excerpt_for=lambda obj: "{}",
                     runner=runner, busy=busy)
    assert [r["obj"] for r in done] == ["issue:26153/m1", "jczq:2026-11-02/周日003"]
    assert seen == [{("2026-11-02", 1)}, {("2026-11-02", 2)}] and busy == set()


def test_daily_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(asks, "DAILY_CAP", 2)
    asks.ask(tmp_path, obj="issue:1", text="a", at=AT)
    asks.ask(tmp_path, obj="issue:1", text="b", at=AT)
    with pytest.raises(ValueError, match="每日上限"):
        asks.ask(tmp_path, obj="issue:1", text="c", at=AT)
