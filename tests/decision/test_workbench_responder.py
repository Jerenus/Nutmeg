import json

from nutmeg.decision.workbench import append_event, read_events
from nutmeg.decision.workbench_responder import (
    build_context,
    pending_questions,
    respond_pending,
)


def test_pending_questions_are_user_messages_without_a_later_agent_reply(tmp_path):
    d = "2026-09-19"
    append_event(tmp_path, d, {"kind": "user_message", "obj_id": "fr-1", "text": "朗斯不败？"})
    append_event(tmp_path, d, {"kind": "agent_reply", "obj_id": "fr-1", "text": "…"})
    append_event(tmp_path, d, {"kind": "user_message", "obj_id": "fr-1", "text": "那平呢？"})
    append_event(tmp_path, d, {"kind": "user_message", "obj_id": "fr-2", "text": "拜仁稳吗？"})
    got = pending_questions(tmp_path, d)
    assert [(q["obj_id"], q["text"]) for q in got] == [("fr-1", "那平呢？"), ("fr-2", "拜仁稳吗？")]


def test_no_events_means_no_pending(tmp_path):
    assert pending_questions(tmp_path, "2026-09-19") == []


def _research(tmp_path):
    z = tmp_path / "zucai"
    z.mkdir(exist_ok=True)
    (z / "26129-research-m8.json").write_text(json.dumps({
        "match_no": 8, "name": "摩纳哥 vs 朗斯（法甲第 5 轮）",
        "summary": "锚方=主队摩纳哥…", "hole_location": {"opponent": "defense", "anchor": "attack"},
        "license_questions": {"q3b_opponent_takes_points": True},
        "death_three_proofs": {"draw": {"detail": "平局面活着"}},
        "directional_flags": [], "nondirectional_flags": ["dressing_room_turmoil"],
    }, ensure_ascii=False), encoding="utf-8")
    (z / "26129-legs-base.json").write_text(json.dumps({"legs": {
        "8": {"name": "摩纳哥-朗斯", "faces": "310", "confidence": 2,
              "fair": {"home": 0.464, "draw": 0.253, "away": 0.282}}}}), encoding="utf-8")
    return z


def _judgments():
    return {"fr-8": {"match": "摩纳哥 vs 朗斯", "competition": "Ligue 1", "market": "had",
                     "prior": {"home": 0.464, "draw": 0.253, "away": 0.282},
                     "belief": {"home": 0.464, "draw": 0.253, "away": 0.282}, "note": ""}}


def test_build_context_joins_judgment_research_and_leg_by_match_name(tmp_path):
    z = _research(tmp_path)
    ctx = build_context("fr-8", judgments=_judgments(), issue="26129", zucai_dir=z)
    assert ctx["judgment"]["belief"]["home"] == 0.464
    assert ctx["research"]["hole_location"]["anchor"] == "attack"
    assert ctx["leg"]["confidence"] == 2
    assert "研究文件" not in ctx        # 不暴露路径


class _EchoProvider:
    def __init__(self, text):
        self.text, self.calls = text, []

    def answer(self, context, question):
        self.calls.append((context["judgment"]["match"], question))
        return self.text


def test_respond_pending_writes_agent_reply_for_each_open_question(tmp_path):
    z = _research(tmp_path)
    d = "2026-09-19"
    append_event(tmp_path, d, {"kind": "user_message", "obj_id": "fr-8", "text": "朗斯不败？"})
    prov = _EchoProvider(
        "平局是研究点名最被支持的面。（依据：hole_location, death_three_proofs.draw）"
    )
    n = respond_pending(
        tmp_path, d, provider=prov, judgments=_judgments(), issue="26129", zucai_dir=z
    )
    assert n == 1 and prov.calls == [("摩纳哥 vs 朗斯", "朗斯不败？")]
    evs = read_events(tmp_path, d)
    assert evs[-1]["kind"] == "agent_reply" and evs[-1]["obj_id"] == "fr-8"
    assert evs[-1]["agent"] == "workbench-responder"
    assert respond_pending(
        tmp_path, d, provider=prov, judgments=_judgments(), issue="26129", zucai_dir=z
    ) == 0


def test_reply_that_recommends_a_face_is_refused_and_logged(tmp_path):
    z = _research(tmp_path)
    d = "2026-09-19"
    append_event(tmp_path, d, {"kind": "user_message", "obj_id": "fr-8", "text": "买什么？"})
    prov = _EchoProvider("建议买 平局。")
    n = respond_pending(
        tmp_path, d, provider=prov, judgments=_judgments(), issue="26129", zucai_dir=z
    )
    assert n == 0
    last = read_events(tmp_path, d)[-1]
    assert last["kind"] == "agent_reply"
    assert "应答器拒答" in last["text"] and "判断永不入脚本" in last["text"]


def test_cli_once_runs_responder_with_kernel_judgments(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    import nutmeg.interfaces.cli.decision as cli_mod
    from nutmeg.interfaces.cli import app

    monkeypatch.setattr(cli_mod, "_responder_judgments", lambda date: _judgments())
    monkeypatch.setattr(
        cli_mod, "_responder_provider", lambda: _EchoProvider("解释。（依据：summary）")
    )
    z = _research(tmp_path)
    d = "2026-09-19"
    append_event(tmp_path / "jczq", d, {"kind": "user_message", "obj_id": "fr-8", "text": "?"})
    r = CliRunner().invoke(app, ["workbench-respond", "--date", d, "--issue", "26129",
                                 "--output-dir", str(tmp_path / "jczq"), "--zucai-dir", str(z)])
    assert r.exit_code == 0 and "回复 1 条" in r.output
