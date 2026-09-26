from nutmeg.decision.day_audit import audit_defaults, default_expressions


def _card(**labels) -> dict:
    base = {"judgment_tier": "deep_research", "confidence": 4, "anchor_integrity": "pass",
            "directional_flags": [], "nondirectional_flags": [], "crash_markers": [],
            "precedents": [], "team_tags": [], "tracking_tags": [], "license_questions": None}
    base.update(labels)
    return {"code": "周三001", "name": "阿森纳 vs 切尔西",
            "market": {"fair": {"home": 0.52, "draw": 0.26, "away": 0.22}}, "labels": base}


def test_default_expressions_follow_fair_order():
    assert default_expressions({"home": 0.52, "draw": 0.26, "away": 0.22}) == {
        "naked": "3", "double": "31", "full": "310"}
    assert default_expressions({"home": 0.20, "draw": 0.30, "away": 0.50}) == {
        "naked": "0", "double": "10", "full": "310"}


def test_audit_defaults_returns_codes_per_expression():
    out = audit_defaults(_card())
    assert set(out) == {"naked", "double", "full"}
    assert out["full"]["faces"] == "310" and out["full"]["blocking"] is False
    assert all(isinstance(f["code"], str) and f["level"] in ("ERROR", "WARN", "INFO")
               for f in out["naked"]["findings"])


def test_broken_anchor_naked_single_is_a_hint_not_a_gate():
    # strength-v2（2026-09-26）：锚方完整度 n=70 零预测力 → C5 降为提示
    out = audit_defaults(_card(anchor_integrity="fail"))
    assert out["naked"]["blocking"] is False
    assert any(f["code"] == "broken_anchor_single" for f in out["naked"]["findings"])


def test_audit_defaults_degrades_on_bad_input():
    out = audit_defaults({"code": "x", "name": "x", "market": {"fair": None}, "labels": {}})
    assert out["error"].startswith("fair 缺失")
