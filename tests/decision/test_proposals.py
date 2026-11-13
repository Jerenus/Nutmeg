"""待签收件箱（2026-10-30 产品形态 Task 10.3）：建条幂等、问过计数、答复与批、已执行、RSI 项、
种子、CLI。"""
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nutmeg.decision import proposals as px
from nutmeg.interfaces.cli import app as cli

TODAY = "2026-10-30"


def _p(data: Path, **kw) -> str:
    base = {"title": "K1 修正案", "body": "合并 κ ≠ 逐项", "blocks": "K1 判决口径",
            "at": "2026-10-20T12:00:00+08:00"}
    return px.propose(data, **(base | kw))


def _row(data: Path, pid: str) -> dict:
    (row,) = [r for r in px.inbox(data, today=TODAY) if r["id"] == pid]
    return row


def test_propose_validates_and_is_idempotent(tmp_path):
    pid = _p(tmp_path)
    assert pid.startswith("P-") and len(pid) == 10
    assert _p(tmp_path) == pid
    lines = (tmp_path / px.LEDGER).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["op"] == "create"
    with pytest.raises(ValueError):
        _p(tmp_path, title=" ")
    with pytest.raises(ValueError, match="deadline"):
        _p(tmp_path, title="x", deadline="明天")
    row = _row(tmp_path, pid)
    assert (row["status"], row["asked_count"], row["age_days"], row["overdue"]) == (
        "pending", 1, 10, True)                         # 积压 10 天 ≥ 7
    assert row["source"] == "session" and row["history"] == []


def test_propose_defaults_at_to_beijing_now(tmp_path):
    pid = px.propose(tmp_path, title="今天的")
    (row,) = px.load(tmp_path)
    assert row["id"] == pid and row["at"].endswith("+08:00") and row["age_days"] == 0
    assert row["overdue"] is False


def test_ask_increments_asked_count(tmp_path):
    pid = _p(tmp_path, at="2026-10-29T12:00:00+08:00")
    assert _row(tmp_path, pid)["overdue"] is False
    px.ask(tmp_path, pid, where="cc:abc", at="2026-10-29T13:00:00+08:00")
    px.ask(tmp_path, pid, where="cc:def", at="2026-10-30T09:00:00+08:00")
    row = _row(tmp_path, pid)
    assert row["asked_count"] == 3 and row["overdue"] is True
    assert [h["where"] for h in row["history"]] == ["cc:abc", "cc:def"]
    with pytest.raises(KeyError):
        px.ask(tmp_path, "P-00000000")


def test_answer_verdicts_and_modify_requires_words(tmp_path):
    a, b = _p(tmp_path, title="a"), _p(tmp_path, title="b")
    with pytest.raises(ValueError, match="verdict"):
        px.answer(tmp_path, a, "yes")
    with pytest.raises(ValueError, match="改"):
        px.answer(tmp_path, a, "modify", words="  ")
    with pytest.raises(KeyError):
        px.answer(tmp_path, [a, "P-deadbeef"], "sign")
    assert len((tmp_path / px.LEDGER).read_text(encoding="utf-8").splitlines()) == 2  # 一条都没写
    px.answer(tmp_path, a, "sign", words="可以", at="2026-10-30T10:00:00+08:00")
    px.answer(tmp_path, b, "modify", words="只登记不拨动", at="2026-10-30T11:00:00+08:00")
    ra, rb = _row(tmp_path, a), _row(tmp_path, b)
    assert (ra["status"], ra["words"], ra["by"], ra["batch"]) == ("sign", "可以", "jun", "")
    assert (rb["status"], rb["verdict"], rb["words"]) == ("modify", "modify", "只登记不拨动")
    assert ra["overdue"] is False                       # 答过就不再催
    # 改答：最近一次为准
    px.answer(tmp_path, a, "reject", at="2026-10-30T12:00:00+08:00")
    assert _row(tmp_path, a)["status"] == "reject"
    # 已答的按答复时刻新的在前
    assert [r["id"] for r in px.load(tmp_path, today=TODAY)] == [a, b]


def test_batch_answer_covers_several_ids(tmp_path):
    ids = [_p(tmp_path, title=t) for t in ("一", "二", "三")]
    events = px.answer(tmp_path, ids[:2], "sign", words="全部解决",
                       at="2026-10-30T10:00:00+08:00")
    assert len(events) == 2 and events[0]["batch"] == events[1]["batch"]
    assert events[0]["batch"].startswith("B-")
    rows = {r["id"]: r for r in px.load(tmp_path, today=TODAY)}
    assert {rows[i]["batch_size"] for i in ids[:2]} == {2}
    assert rows[ids[2]]["status"] == "pending" and rows[ids[2]]["batch_size"] == 1
    assert px.summary(list(rows.values()))["pending"] == 1


def test_done_only_after_sign_or_modify(tmp_path):
    a, b = _p(tmp_path, title="a"), _p(tmp_path, title="b")
    with pytest.raises(ValueError, match="签"):
        px.done(tmp_path, a, result="x")              # 还没答
    px.answer(tmp_path, b, "reject")
    with pytest.raises(ValueError):
        px.done(tmp_path, b, result="x")              # 否了不能执行
    px.answer(tmp_path, a, "sign")
    with pytest.raises(ValueError, match="result"):
        px.done(tmp_path, a, result=" ")
    px.done(tmp_path, a, result="commit abc123")
    row = _row(tmp_path, a)
    assert (row["status"], row["verdict"], row["result"]) == ("done", "sign", "commit abc123")
    assert [h["op"] for h in row["history"]] == ["answer", "done"]
    with pytest.raises(KeyError):
        px.done(tmp_path, "P-deadbeef", result="x")


RID = "RSI-abc123@2026-10-26"            # 账上的 id 带起始日（关了又开＝新一轮）


def _rsi(data: Path, *, closed: bool = False, report: bool = True) -> None:
    d = data / px.RSI_DIR
    d.mkdir(parents=True)
    state = {"rubric_cap:F_x": {"id": "RSI-abc123", "first_seen": "2026-10-26",
                                "last_seen": "2026-10-29"},
             "exit:F9:survived": {"id": "RSI-def456", "first_seen": "2026-10-20",
                                  "last_seen": "2026-10-21", "closed_at": "2026-10-22"}}
    if closed:
        state["rubric_cap:F_x"]["closed_at"] = "2026-10-30"
    (d / "inbox.json").write_text(json.dumps(state), encoding="utf-8")
    if report:
        (d / "2026-10-29.json").write_text(json.dumps({"inbox": [
            {"key": "rubric_cap:F_x", "id": "RSI-abc123", "text": "rubric F_x 上限 3pp → 0",
             "default": "下一版 rubric 改上限", "command": "uv run nutmeg rsi weights propose",
             "first_seen": "2026-10-26", "age_days": 3}]}, ensure_ascii=False), encoding="utf-8")


def test_rsi_items_appear_and_can_be_answered(tmp_path):
    _rsi(tmp_path)
    (item,) = px.rsi_items(tmp_path, today=TODAY)       # 关了的不列
    assert item["id"] == RID and item["source"] == "rsi"
    assert item["title"] == "rubric F_x 上限 3pp → 0"
    assert item["body"] == "默认：下一版 rubric 改上限（`uv run nutmeg rsi weights propose`）"
    assert (item["status"], item["age_days"], item["asked_count"]) == ("pending", 4, 5)
    assert px.pending_count(tmp_path) == 1
    pid = _p(tmp_path)
    assert {r["id"] for r in px.inbox(tmp_path, today=TODAY)} == {RID, pid}
    with pytest.raises(KeyError):
        px.answer(tmp_path, "RSI-def456", "sign")       # 闭环已关的不认
    px.answer(tmp_path, RID, "stale", words="F_x 早退役了")
    rows = [r for r in px.inbox(tmp_path, today=TODAY) if r["id"] == RID]
    assert len(rows) == 1 and rows[0]["status"] == "stale" and rows[0]["source"] == "rsi"
    assert rows[0]["title"] == "rubric F_x 上限 3pp → 0"
    creates = [json.loads(x) for x in (tmp_path / px.LEDGER).read_text("utf-8").splitlines()
               if json.loads(x)["op"] == "create" and json.loads(x)["id"] == RID]
    assert len(creates) == 1 and creates[0]["at"] == "2026-10-26T00:00:00+08:00"
    # 闭环那边关了：答过的照留在账上
    (tmp_path / px.RSI_DIR / "inbox.json").unlink()
    assert [r["status"] for r in px.inbox(tmp_path, today=TODAY) if r["id"] == RID] == [
        "stale"]


def test_rsi_item_without_report_still_listed(tmp_path):
    _rsi(tmp_path, report=False)
    (item,) = px.rsi_items(tmp_path, today=TODAY)
    assert item["title"] == "rubric_cap:F_x" and "找不到" in item["body"]
    assert px.rsi_items(tmp_path / "nowhere") == []


def test_seed_is_idempotent(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"_about": "x", "rows": [
        {"at": "2026-10-06", "title": "K1 修正案", "body": "b", "blocks": "K1", "asked": 5,
         "ref": "cc:7fdecc12"},
        {"at": "2026-10-28", "title": "死面口径", "body": "b2", "blocks": "", "asked": 1,
         "ref": ""},
    ]}, ensure_ascii=False), encoding="utf-8")
    data = tmp_path / "data"
    assert px.seed(data, seed) == {"added": 2, "skipped": 0}
    assert px.seed(data, seed) == {"added": 0, "skipped": 2}
    rows = {r["title"]: r for r in px.load(data, today=TODAY)}
    k1 = rows["K1 修正案"]
    assert (k1["at"], k1["source"], k1["asked_count"], k1["age_days"]) == (
        "2026-10-06T12:00:00+08:00", px.SEED_SOURCE, 5, 24)
    px.ask(data, k1["id"])
    assert _row(data, k1["id"])["asked_count"] == 6
    assert rows["死面口径"]["asked_count"] == 1 and rows["死面口径"]["overdue"] is False


def test_real_seed_file_loads(tmp_path):
    out = px.seed(tmp_path)
    assert out["added"] >= 1 and out["skipped"] == 0
    assert all(r["status"] == "pending" for r in px.load(tmp_path))


def test_bad_ledger_lines_are_skipped(tmp_path):
    (tmp_path / px.LEDGER).write_text(
        "不是 json\n" + json.dumps({"op": "answer", "id": "P-x", "at": "2026-10-30"}) + "\n",
        encoding="utf-8")
    assert px.load(tmp_path) == [] and px.pending_count(tmp_path) == 0


def test_cli_propose_ask_answer_done_list_seed(tmp_path):
    run = CliRunner()
    d = ["--data-dir", str(tmp_path)]
    r = run.invoke(cli, ["inbox", "propose", "--title", "止损余帽", "--body", "余帽算法",
                         "--blocks", "26148 三提案", *d])
    assert r.exit_code == 0, r.output
    a = r.output.strip()
    b = run.invoke(cli, ["inbox", "propose", "--title", "胜负彩≤¥100", "--body", "x", *d]
                   ).output.strip()
    assert a.startswith("P-") and b.startswith("P-") and a != b
    assert run.invoke(cli, ["inbox", "ask", a, "--where", "cc:1", *d]).exit_code == 0
    r = run.invoke(cli, ["inbox", "list", "--pending", *d])
    assert r.exit_code == 0 and a in r.output and "问2/" in r.output and "待签" in r.output
    r = run.invoke(cli, ["inbox", "answer", a, b, "--verdict", "sign",
                         "--words", "1，可以。2，可以", *d])
    assert r.exit_code == 0, r.output
    assert "→ 签 · 批 B-" in r.output
    assert run.invoke(cli, ["inbox", "list", "--pending", *d]).output.strip() == "（无）"
    assert run.invoke(cli, ["inbox", "done", a, "--result", "commit 1234", *d]).exit_code == 0
    r = run.invoke(cli, ["inbox", "list", *d])
    assert "已执行" in r.output and "1，可以。2，可以" in r.output
    # 坏输入 → exit 2
    for bad in (["inbox", "answer", a, "--verdict", "modify", *d],
                ["inbox", "answer", a, "--verdict", "ok", *d],
                ["inbox", "answer", "P-nope", "--verdict", "sign", *d],
                ["inbox", "ask", "P-nope", *d],
                ["inbox", "done", b, "--result", "x", "--data-dir", str(tmp_path / "empty")],
                ["inbox", "propose", "--title", " ", "--body", "x", *d]):
        r = run.invoke(cli, bad)
        assert r.exit_code == 2 and "inbox error:" in r.output, (bad, r.output)
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"rows": [{"at": "2026-10-06", "title": "t", "body": "b",
                                          "blocks": "", "asked": 2, "ref": ""}]}),
                    encoding="utf-8")
    r = run.invoke(cli, ["inbox", "seed", "--seed", str(seed), *d])
    assert r.output.strip() == "added 1 · skipped 0"


def test_reopened_rsi_item_is_pending_again(tmp_path: Path) -> None:
    """同一 key 关了又开：闭环 RSI id 不变，但这是新一轮待办，不沿用上一轮的回答。"""
    _rsi(tmp_path)
    px.answer(tmp_path, RID, "sign", words="批")
    state_path = tmp_path / "analytics" / "rsi-loop" / "inbox.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["rubric_cap:F_x"].update(first_seen="2026-10-29", last_seen="2026-10-29")
    state_path.write_text(json.dumps(state), encoding="utf-8")
    rows = {r["id"]: r["status"] for r in px.inbox(tmp_path, today=TODAY)
            if r["id"].startswith("RSI-abc123")}
    assert rows == {RID: "sign", "RSI-abc123@2026-10-29": "pending"}


# ---- 默认动作与到期（2026-11-13 Jun 签 P-574c4d0b ①） ----------------------

def test_new_proposal_carries_a_default_and_a_deadline(tmp_path):
    pid = px.propose(tmp_path, title="不写条款", at="2026-11-13T10:00:00+08:00")
    row = _row(tmp_path, pid)
    assert row["default"] == "stale"
    assert row["deadline"] == "2026-11-27T10:00:00+08:00"   # 起草后 14 天
    pid2 = px.propose(tmp_path, title="写了条款", at="2026-11-13T10:00:00+08:00",
                      default="sign", deadline="2026-11-15T21:00:00+08:00")
    row2 = _row(tmp_path, pid2)
    assert (row2["default"], row2["deadline"]) == ("sign", "2026-11-15T21:00:00+08:00")
    with pytest.raises(ValueError, match="default"):
        px.propose(tmp_path, title="坏条款", default="reject")


def test_terms_rewrites_default_and_deadline_of_an_existing_proposal(tmp_path):
    (tmp_path / px.LEDGER).write_text(json.dumps(
        {"op": "create", "id": "P-old", "at": "2026-10-06T10:00:00+08:00", "title": "旧提案",
         "body": "", "blocks": "", "deadline": None, "source": "session", "ref": ""},
        ensure_ascii=False) + "\n", encoding="utf-8")
    assert _row(tmp_path, "P-old")["default"] is None            # 旧账没有条款：不会自己到期
    px.terms(tmp_path, ["P-old"], default="stale", deadline="2026-11-27T21:00:00+08:00",
             note="维持现状")
    row = _row(tmp_path, "P-old")
    assert (row["default"], row["deadline"], row["default_note"]) == (
        "stale", "2026-11-27T21:00:00+08:00", "维持现状")
    with pytest.raises(KeyError):
        px.terms(tmp_path, ["P-nope"], default="stale", deadline="2026-11-27T21:00:00+08:00")


def test_expire_books_the_default_once_and_only_after_the_deadline(tmp_path):
    late = px.propose(tmp_path, title="到期·做", at="2026-11-01T10:00:00+08:00",
                      default="sign", deadline="2026-11-10T21:00:00+08:00")
    soon = px.propose(tmp_path, title="没到期", at="2026-11-01T11:00:00+08:00",
                      default="stale", deadline="2026-11-20T21:00:00+08:00")
    answered = px.propose(tmp_path, title="已答", at="2026-11-01T12:00:00+08:00",
                          default="stale", deadline="2026-11-10T21:00:00+08:00")
    px.answer(tmp_path, answered, "reject", at="2026-11-02T09:00:00+08:00")

    events = px.expire(tmp_path, now="2026-11-13T09:00:00+08:00")
    assert [e["id"] for e in events] == [late]
    row = _row(tmp_path, late)
    assert row["status"] == "sign" and row["by"] == "default" and row["by_default"] is True
    assert "到期未答" in row["words"]
    assert _row(tmp_path, soon)["status"] == "pending"
    assert _row(tmp_path, answered)["by"] == "jun"
    assert px.expire(tmp_path, now="2026-11-13T09:05:00+08:00") == []      # 不重复落账
    # 到期之后 Jun 改答：以他最近一次答复为准
    px.answer(tmp_path, late, "reject", words="不做了", at="2026-11-14T09:00:00+08:00")
    assert _row(tmp_path, late)["status"] == "reject"
    assert _row(tmp_path, late)["by_default"] is False


def test_inbox_books_expired_defaults_when_read(tmp_path, monkeypatch):
    pid = px.propose(tmp_path, title="读时落账", at="2026-11-01T10:00:00+08:00",
                     default="stale", deadline="2026-11-10T21:00:00+08:00")
    rows = px.inbox(tmp_path, today="2026-11-13")
    row = next(r for r in rows if r["id"] == pid)
    assert row["status"] == "stale" and row["by_default"] is True
