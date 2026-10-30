"""纠正账（2026-10-30 产品形态 Task 10.2）：记账校验与幂等、状态折叠、复发堆、对象前缀、回填。"""
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nutmeg.decision import corrections as cx
from nutmeg.interfaces.cli import app as cli


def _rec(data: Path, **kw) -> str:
    base = {"obj": "issue:26151/m3", "old": "缺阵", "new": "首发", "kind": "premise",
            "found_by": "result", "at": "2026-10-28T09:44:00+08:00"}
    return cx.record(data, **(base | kw))


def test_record_validates_enums_and_is_idempotent(tmp_path):
    cid = _rec(tmp_path)
    assert cid.startswith("C-") and len(cid) == 10
    assert _rec(tmp_path) == cid                       # 同一条再记 → 同 id、不重写
    lines = (tmp_path / cx.LEDGER).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["op"] == "create"
    with pytest.raises(ValueError, match="premise"):
        _rec(tmp_path, kind="nope")
    with pytest.raises(ValueError):
        _rec(tmp_path, dest="nowhere-at-all")
    with pytest.raises(ValueError):
        _rec(tmp_path, obj=" ")


def test_record_defaults_at_to_beijing_now(tmp_path):
    cx.record(tmp_path, obj="rule:x", old="a", new="b", kind="self", found_by="machine")
    (row,) = cx.load(tmp_path)
    assert row["at"].endswith("+08:00") and row["status"] == "draft" and row["dest"] == "none"


def test_set_status_folds_latest_and_keeps_history(tmp_path):
    cid = _rec(tmp_path)
    cx.set_status(tmp_path, cid, "confirmed", note="对", at="2026-10-28T10:00:00+08:00")
    cx.set_status(tmp_path, cid, "written", by="machine", at="2026-10-28T11:00:00+08:00")
    (row,) = cx.load(tmp_path)
    assert row["status"] == "written"
    assert [h["status"] for h in row["history"]] == ["confirmed", "written"]
    assert row["history"][0] == {"at": "2026-10-28T10:00:00+08:00", "status": "confirmed",
                                 "note": "对", "by": "jun"}
    with pytest.raises(KeyError):
        cx.set_status(tmp_path, "C-00000000", "confirmed")
    with pytest.raises(ValueError):
        cx.set_status(tmp_path, cid, "bogus")


def test_load_sorts_newest_first_and_missing_file_is_empty(tmp_path):
    assert cx.load(tmp_path) == []
    _rec(tmp_path, at="2026-10-01T12:00:00+08:00", old="a")
    _rec(tmp_path, at="2026-10-20T12:00:00+08:00", old="b")
    assert [r["old"] for r in cx.load(tmp_path)] == ["b", "a"]


def test_summary_piles_counts_and_open(tmp_path):
    a = _rec(tmp_path, pile="截图抄录", at="2026-10-10T10:00:00+08:00", old="1")
    _rec(tmp_path, pile="截图抄录", at="2026-10-17T10:00:00+08:00", old="2")
    _rec(tmp_path, pile="截图抄录", at="2026-10-17T11:00:00+08:00", old="3", status="written")
    _rec(tmp_path, pile="研究前提错", at="2026-10-15T10:00:00+08:00", old="4")
    _rec(tmp_path, at="2026-10-15T10:00:00+08:00", old="5", kind="data")
    cx.set_status(tmp_path, a, "dismissed")
    s = cx.summary(cx.load(tmp_path))
    assert s["piles"] == [
        {"pile": "截图抄录", "n": 3, "dates": ["2026-10-10", "2026-10-17"], "open": 1},
        {"pile": "研究前提错", "n": 1, "dates": ["2026-10-15"], "open": 1},
    ]
    assert s["by_kind"] == {"premise": 4, "data": 1}
    assert s["by_status"] == {"draft": 3, "written": 1, "dismissed": 1}
    assert s["drafts"] == 3 == cx.draft_count(tmp_path)


def test_for_obj_takes_prefix_and_children_only():
    rows = [{"obj": o} for o in ("issue:26151", "issue:26151/m3", "issue:26151/m3/q4",
                                 "issue:261510", "slip:26151-T1")]
    assert [r["obj"] for r in cx.for_obj(rows, "issue:26151")] == [
        "issue:26151", "issue:26151/m3", "issue:26151/m3/q4"]
    assert [r["obj"] for r in cx.for_obj(rows, "issue:26151/m3")] == [
        "issue:26151/m3", "issue:26151/m3/q4"]


def _overrides(data: Path) -> None:
    z = data / "zucai"
    z.mkdir(parents=True)
    (z / "overrides.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
        {"research": "26134-research-m3.json", "match": "足彩26134-03 比利时 vs 法国",
         "at": "2026-09-28T10:15:52+08:00", "note": "主循环·同组交叉" + "长" * 400,
         "original_tilt": {"face": "1"}, "tilt": {"face": "3", "shift": {"3": 2, "1": 2, "0": -4}}},
        {"research": "26136-research-m6.json", "match": "朗斯-里昂",
         "at": "2026-10-09T09:00:00+08:00", "note": "研究自相矛盾",
         "reason": "research_contradiction", "to_market": True,
         "original_tilt": {"face": None, "shift": {"3": 3, "1": 3, "0": -6}}, "tilt": None},
    ]) + "\n", encoding="utf-8")
    d = data / "jczq" / "daily" / "2026-10-17"
    d.mkdir(parents=True)
    (d / "overrides.jsonl").write_text(json.dumps({
        "research": "research-周六003.json", "match": "蔚山现代-富川FC",
        "at": "2026-10-17T12:00:00+08:00", "note": "官宣停赛", "reason": "new_official_info",
        "to_market": False, "original_tilt": None,
        "tilt": {"face": None, "shift": {"3": 3, "1": 1, "0": -4}},
        "items": {"F_absence_away": {"answer": "yes"}}}, ensure_ascii=False) + "\n",
        encoding="utf-8")


def test_backfill_seed_and_overrides_is_idempotent(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"_about": "x", "rows": [
        {"at": "2026-10-10", "obj": "slip:26137 小票", "old": "¥8", "new": "5 倍 ¥40",
         "kind": "transcription", "found_by": "machine", "evidence": "cc:e28c07e7",
         "dest": "betslips", "status": "written", "pile": "截图抄录"},
        {"at": "2026-10-17", "obj": "slip:26144 胜负彩", "old": "32 注", "new": "128 注",
         "kind": "transcription", "found_by": "machine", "dest": "betslips", "status": "draft"},
    ]}, ensure_ascii=False), encoding="utf-8")
    data = tmp_path / "data"
    _overrides(data)

    assert cx.backfill(data, seed) == {"added": 5, "skipped": 0}
    assert cx.backfill(data, seed) == {"added": 0, "skipped": 5}
    rows = {r["obj"]: r for r in cx.load(data)}
    assert rows["slip:26137 小票"]["at"] == "2026-10-10T12:00:00+08:00"
    assert rows["slip:26137 小票"]["source"] == cx.SEED_SOURCE
    m3 = rows["issue:26134/m3"]
    assert (m3["old"], m3["new"]) == ("原判 表态 1", "表态 3 · 主+2 平+2 客−4")
    assert (m3["kind"], m3["found_by"], m3["dest"], m3["status"], m3["source"]) == (
        "self", "machine", "override", "written", "overrides")
    assert len(m3["evidence"]) == 300 and m3["note"] == "26134-research-m3.json"
    m6 = rows["issue:26136/m6"]
    assert (m6["old"], m6["new"]) == ("原判 主+3 平+3 客−6", "回市场")
    assert m6["evidence"].endswith("理由 research_contradiction")
    j = rows["jczq:2026-10-17/周六003"]
    assert (j["old"], j["new"]) == ("研究原判（不拨）", "主+3 平+1 客−4 · 改项 F_absence_away")


def test_cli_add_list_status(tmp_path):
    run = CliRunner()
    r = run.invoke(cli, ["correction", "add", "--obj", "issue:26153/m6", "--old", "首发",
                         "--new", "缺阵", "--kind", "premise", "--found-by", "jun",
                         "--pile", "研究前提错", "--data-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    cid = r.output.strip()
    assert cid.startswith("C-")
    r = run.invoke(cli, ["correction", "list", "--obj", "issue:26153", "--data-dir", str(tmp_path)])
    assert r.exit_code == 0 and cid in r.output and "首发→缺阵" in r.output and "草稿" in r.output
    r = run.invoke(cli, ["correction", "status", cid, "written", "--data-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    r = run.invoke(cli, ["correction", "list", "--status", "written", "--data-dir", str(tmp_path)])
    assert cid in r.output and "已回写" in r.output
    r = run.invoke(cli, ["correction", "status", "C-deadbeef", "written",
                         "--data-dir", str(tmp_path)])
    assert r.exit_code == 2 and "C-deadbeef" in r.output
    r = run.invoke(cli, ["correction", "add", "--obj", "x", "--old", "a", "--new", "b",
                         "--kind", "bad", "--found-by", "jun", "--data-dir", str(tmp_path)])
    assert r.exit_code == 2 and "kind" in r.output


def test_cli_backfill_with_default_seed_parses(tmp_path):
    r = CliRunner().invoke(cli, ["correction", "backfill", "--data-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert r.output.startswith("added ") and len(cx.load(tmp_path)) > 0
