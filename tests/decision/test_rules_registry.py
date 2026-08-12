# tests/decision/test_rules_registry.py
from nutmeg.decision.rules_registry import (
    format_rules,
    load_rules,
    save_rules,
    verify_issue,
)


def _rule(falsifier):
    return {"rule_id": "r1", "status": "probation", "falsifiers": [falsifier]}


def _seed(tmp_path, falsifier):
    save_rules(tmp_path, [_rule(falsifier)])
    return tmp_path


def test_outcome_eq_confirmed_and_refuted(tmp_path):
    """26103 场9 那条:总分持平的第三个样本,开平即兑现。"""
    f = {"id": "f1", "issue": "26103", "description": "场9 开平",
         "on_true": "持平档 3/3", "check": {"kind": "outcome_eq", "matches": {"9": "1"}},
         "outcome": "pending"}
    d = _seed(tmp_path, dict(f))
    out = verify_issue(d, "26103", {"9": "1"}, None, verified_at="t")
    assert any("✅兑现" in ln for ln in out) and any("持平档 3/3" in ln for ln in out)
    assert load_rules(d)[0]["falsifiers"][0]["outcome"] == "confirmed"

    d2 = _seed(tmp_path / "b", dict(f))
    out2 = verify_issue(d2, "26103", {"9": "3"}, None, verified_at="t")
    assert any("❌未兑现" in ln for ln in out2)
    assert load_rules(d2)[0]["falsifiers"][0]["outcome"] == "refuted"


def test_outcome_count_crash_tier(tmp_path):
    """p 条修正:三个 FAIL 锚 ≥2 未取胜。用 26101 的真实形状(2/2 倒)作正例。"""
    f = {"id": "f2", "issue": "X", "description": "≥2 未取胜",
         "check": {"kind": "outcome_count",
                   "targets": [{"no": 6, "codes": "10"}, {"no": 10, "codes": "31"}],
                   "op": ">=", "k": 2},
         "outcome": "pending"}
    d = _seed(tmp_path, f)
    # 26101 实况:场6 开平(锚主胜未成)、场10 开平(锚客胜未成) → 两条都命中"未取胜"面
    out = verify_issue(d, "X", {"6": "1", "10": "1"}, None, verified_at="t")
    assert any("✅兑现" in ln and "2/2" in ln for ln in out)


def test_margin_needs_scores_stays_pending(tmp_path):
    f = {"id": "f3", "issue": "X", "description": "客净胜2",
         "check": {"kind": "margin", "no": 8, "side": "away", "op": ">=", "k": 2},
         "outcome": "pending"}
    d = _seed(tmp_path, dict(f))
    out = verify_issue(d, "X", {"8": "0"}, None, verified_at="t")   # 无比分
    assert any("⏳" in ln and "pending" in ln for ln in out)
    assert load_rules(d)[0]["falsifiers"][0]["outcome"] == "pending"
    # 有比分:0-2 客净胜 2 → 兑现
    out2 = verify_issue(d, "X", {"8": "0"}, {"8": (0, 2)}, verified_at="t")
    assert any("✅兑现" in ln for ln in out2)


def test_verify_is_idempotent(tmp_path):
    f = {"id": "f4", "issue": "X", "description": "d",
         "check": {"kind": "outcome_eq", "matches": {"1": "3"}}, "outcome": "pending"}
    d = _seed(tmp_path, f)
    verify_issue(d, "X", {"1": "3"}, None, verified_at="t1")
    out = verify_issue(d, "X", {"1": "0"}, None, verified_at="t2")   # 已判,不重判
    assert any("无 pending" in ln for ln in out)
    assert load_rules(d)[0]["falsifiers"][0]["verified_at"] == "t1"


def test_missing_result_stays_pending(tmp_path):
    """数据不足必须保持 pending 并说话——不许猜,也不许静默。"""
    f = {"id": "f5", "issue": "X", "description": "d",
         "check": {"kind": "outcome_eq", "matches": {"9": "1"}}, "outcome": "pending"}
    d = _seed(tmp_path, f)
    out = verify_issue(d, "X", {}, None, verified_at="t")
    assert any("数据不足" in ln for ln in out)


def test_unknown_check_kind_is_visible(tmp_path):
    f = {"id": "f6", "issue": "X", "description": "d",
         "check": {"kind": "llm_judgment"}, "outcome": "pending"}
    d = _seed(tmp_path, f)
    out = verify_issue(d, "X", {"1": "3"}, None, verified_at="t")
    assert any("未知 check.kind" in ln for ln in out)      # 判断类条件进不来,且报错可见


def test_format_rules_summarises(tmp_path):
    f = {"id": "f7", "issue": "X", "description": "d",
         "check": {"kind": "outcome_eq", "matches": {"1": "3"}}, "outcome": "pending"}
    save_rules(tmp_path, [_rule(f)])
    txt = format_rules(load_rules(tmp_path))
    assert "1 pending" in txt and "r1" in txt
