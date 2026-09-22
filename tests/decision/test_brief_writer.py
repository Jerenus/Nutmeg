import json

from nutmeg.decision.brief_writer import resolve_path, validate_cites, write_logic

CARD = {
    "code": "周三001", "name": "A vs B",
    "market": {"fair": {"home": 0.52}, "drift_pp": 2.0},
    "labels": {"anchor_integrity": "pass"},
    "read": {"moved_pp": 6.0, "judge": "ai:jczq-analyst"},
    "ladder": "偏移", "audit": {"naked": {"blocking": False}},
}
BRIEF = {
    "date": "2026-09-23",
    "jczq": {"matches": [CARD, {**CARD, "code": "周三002"}], "counts": {}},
    "factors": [{"factor_id": "C11", "decision": "propose_zero"}],
}


def test_resolve_path_and_validate_cites():
    assert resolve_path(CARD, "market.drift_pp") == 2.0
    assert resolve_path(CARD, "audit.naked.blocking") is False
    assert resolve_path(CARD, "read.nope") is None
    assert resolve_path(CARD, "factors.0.decision") is None
    assert validate_cites(
        ["market.drift_pp", "read.moved_pp"], CARD, BRIEF["factors"]
    ) == []
    assert validate_cites(
        ["market.zzz", "factors.0.decision"], CARD, BRIEF["factors"]
    ) == ["market.zzz"]


def _fake_claude(responses: dict[str, str]):
    calls = []

    def claude(prompt: str, stdin: str) -> tuple[int, str]:
        code = json.loads(stdin)["code"]
        calls.append(code)
        return 0, responses[code]

    claude.calls = calls  # type: ignore[attr-defined]
    return claude


def test_write_logic_accepts_valid_and_rejects_bad_cites_and_respects_budget():
    ok = json.dumps({
        "code": "周三001", "logic": "锚方完整度 pass 定了面；位移 +2pp。",
        "cites": ["labels.anchor_integrity", "market.drift_pp"],
    })
    bad_doc = {"code": "周三002", "logic": "x", "cites": ["market.nope"]}
    bad = "```json\n" + json.dumps(bad_doc) + "\n```"
    claude = _fake_claude({"周三001": ok, "周三002": bad})
    out = write_logic(BRIEF, claude=claude, budget=5)
    m1, m2 = out["jczq"]["matches"]
    assert m1["logic"] == {
        "status": "ok", "text": "锚方完整度 pass 定了面；位移 +2pp。",
        "cites": ["labels.anchor_integrity", "market.drift_pp"], "author": "claude -p",
    }
    assert m2["logic"]["status"] == "rejected"
    assert "market.nope" in m2["logic"]["reason"]
    assert claude.calls == ["周三001", "周三002"]
    limited = write_logic(BRIEF, claude=_fake_claude({"周三001": ok, "周三002": bad}), budget=1)
    assert limited["jczq"]["matches"][1]["logic"] == {"status": "not_generated", "reason": "budget"}


def test_write_logic_handles_nonzero_exit_and_invalid_json():
    claude = lambda prompt, stdin: (1, "boom")  # noqa: E731
    out = write_logic(BRIEF, claude=claude, budget=5)
    assert out["jczq"]["matches"][0]["logic"]["status"] == "not_generated"
    claude2 = lambda prompt, stdin: (0, "not json")  # noqa: E731
    out2 = write_logic(BRIEF, claude=claude2, budget=5)
    assert out2["jczq"]["matches"][0]["logic"]["status"] == "rejected"
