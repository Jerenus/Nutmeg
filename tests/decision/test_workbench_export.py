from nutmeg.decision.workbench import (
    append_candidate,
    append_event,
    append_note,
    read_events,
)
from nutmeg.decision.workbench_export import events_to_markdown


def test_note_and_candidate_events_have_stable_shapes(tmp_path):
    d = "2026-09-19"
    append_note(tmp_path, d, obj_id="ticket:26129", text="SFC-B 否决：C2 ×3（旗面没盖住）")
    append_candidate(tmp_path, d, obj_id="ticket:26129", version="SFC-B",
                     faces={"1": "30", "2": "3"}, notes=128, stake_yuan=256,
                     p_all=0.0038, verdict="rejected", reason="三处 C2")
    n, c = read_events(tmp_path, d)
    assert n["kind"] == "note" and n["obj_id"] == "ticket:26129" and "C2" in n["text"]
    assert c["kind"] == "candidate" and c["payload"]["version"] == "SFC-B"
    assert c["payload"]["verdict"] == "rejected" and c["payload"]["stake_yuan"] == 256


def test_markdown_export_is_a_retro_skeleton(tmp_path):
    d = "2026-09-19"
    append_event(tmp_path, d, {"kind": "user_message", "obj_id": "fr-8", "text": "朗斯不败？"})
    append_event(tmp_path, d, {"kind": "agent_reply", "obj_id": "fr-8", "text": "平局最被支持。"})
    append_candidate(tmp_path, d, obj_id="ticket:26129", version="SFC-D", faces={}, notes=192,
                     stake_yuan=384, p_all=0.00321, verdict="chosen", reason="裸单全 ≥50%")
    md = events_to_markdown(tmp_path, d)
    assert md.startswith("# 2026-09-19 过程回放")
    assert "## 任务" not in md                       # SOP 任务栏 2026-10-08 退役
    assert "## 追问" in md and "**你**（fr-8）：朗斯不败？" in md and "**判**：平局最被支持。" in md
    assert "## 候选票面" in md and "SFC-D · 已选 · 192 注 ¥384 · P 0.32%" in md


def test_markdown_accepts_events_directly_and_reports_judgments(tmp_path):
    """回放必须能吃内核事件（判读/实票），不是只吃文件流。

    出生事故 2026-09-18：/replay.md 在真 26129 上「实票（无）」——4 张真票和 14 条
    判读活在内核态里，而导出只读文件流。
    """
    events = [
        {"kind": "judgment", "obj_id": "fr-8",
         "payload": {"match": "摩纳哥 vs 朗斯", "market": "had"}},
        {"kind": "slip", "obj_id": "slip:26129-RJ9",
         "payload": {"slip_id": "26129-RJ9", "notes": 384, "stake_yuan": 768}},
        {"kind": "user_message", "obj_id": "fr-8", "text": "朗斯不败？"},
    ]
    md = events_to_markdown(tmp_path, "2026-09-19", events=events)
    assert "## 判读" in md and "- 摩纳哥 vs 朗斯（had）" in md
    assert "## 实票" in md and "26129-RJ9 · 384 注 ¥768" in md
    assert "**你**（fr-8）：朗斯不败？" in md


def test_markdown_still_reads_the_file_stream_when_no_events_given(tmp_path):
    append_note(tmp_path, "2026-09-19", obj_id="day", text="刹车：¥1000 帽")
    md = events_to_markdown(tmp_path, "2026-09-19")
    assert "刹车：¥1000 帽" in md


def test_candidate_carries_parent_version_and_export_shows_the_edge(tmp_path):
    """26129 的 SFC-B→C→D→E 四轮只活在聊天窗口——候选必须挂 parent_version 成树，回放才能重走。"""
    d = "2026-09-19"
    append_candidate(tmp_path, d, obj_id="ticket:26129", version="SFC-B", faces={}, notes=128,
                     stake_yuan=256, p_all=0.0038, verdict="rejected", reason="三处 C2")
    append_candidate(tmp_path, d, obj_id="ticket:26129", version="SFC-C", parent_version="SFC-B",
                     faces={}, notes=160, stake_yuan=320, p_all=0.0035, verdict="rejected",
                     reason="裸单还有一条 <50%")
    root, child = read_events(tmp_path, d)
    assert root["payload"]["parent_version"] is None
    assert child["payload"]["parent_version"] == "SFC-B"
    md = events_to_markdown(tmp_path, d)
    assert "- SFC-B · 已否决 · 128 注 ¥256" in md
    assert "SFC-B ←" not in md
    assert "- SFC-C ← SFC-B · 已否决 · 160 注 ¥320 · P 0.35%" in md


def test_cli_export_uses_the_merged_kernel_stream(tmp_path, monkeypatch):
    """day.settle 每天跑 `workbench-export --date <昨天>`；只读文件流时 10-05 的 5 张实票
    与 7 条判读全成了「（无）」。CLI 必须和网页回放走同一份合并流。"""
    from typer.testing import CliRunner

    import nutmeg.interfaces.cli.decision as mod
    from nutmeg.interfaces.cli import app

    append_event(tmp_path, "2026-10-05", {"kind": "note", "text": "手记一条"})
    monkeypatch.setattr(mod, "_kernel_state_factory", lambda output_dir: (
        lambda day: {"events": [
            {"kind": "judgment", "obj_id": "r1", "payload": {"match": "黑山 vs 亚美尼亚"}},
            {"kind": "slip", "obj_id": "20261005-J1",
             "payload": {"slip_id": "20261005-J1", "notes": 1, "stake_yuan": 100}}]}))
    out = tmp_path / "retro.md"
    result = CliRunner().invoke(app, ["workbench-export", "--date", "2026-10-05",
                                      "--output-dir", str(tmp_path), "--out", str(out)])
    assert result.exit_code == 0, result.output
    md = out.read_text(encoding="utf-8")
    assert "20261005-J1" in md and "黑山 vs 亚美尼亚" in md and "手记一条" in md


def test_cli_export_falls_back_to_the_file_stream_when_the_kernel_is_unavailable(
        tmp_path, monkeypatch):
    from typer.testing import CliRunner

    import nutmeg.interfaces.cli.decision as mod
    from nutmeg.interfaces.cli import app

    append_event(tmp_path, "2026-10-05", {"kind": "note", "text": "手记一条"})

    def boom(output_dir):
        raise RuntimeError("内核不可达")

    monkeypatch.setattr(mod, "_kernel_state_factory", boom)
    result = CliRunner().invoke(app, ["workbench-export", "--date", "2026-10-05",
                                      "--output-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "手记一条" in result.output and "内核不可达" in result.output
