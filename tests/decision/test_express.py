# tests/decision/test_express.py
from nutmeg.decision.express import (
    compose_tickets,
    load_budget,
    parlay_odds,
    renjiu_ticket_count,
)
from nutmeg.decision.ontology import Ticket
from nutmeg.decision.store import DecisionStore


def test_budget_buckets_from_config():
    b = load_budget()
    assert b["jczq"]["had_modal"] == 100
    assert b["jczq"]["draw_single"] == 40
    assert b["shengfucai_renjiu"]["fushi"] == 400


def test_renjiu_count_is_2002():
    # 任九 = 从 14 场选 9 场命中(C(14,9)) = 2002
    assert renjiu_ticket_count(14, 9) == 2002


def test_parlay_odds_multiplies():
    assert abs(parlay_odds([1.64, 2.75]) - 4.51) < 1e-9


# --- Task 3: M1.5 express(已声明投注腿 → Ticket,¥400 框架)---------------------
# express 只做确定性预算/串关算术;押哪个玩法是主循环 Claude 判读,作为 legs 传入。

_LEGS = [
    {"match_id": "M-1", "market": "had", "selection": "home", "odds": 1.64,
     "bucket": "main"},
    {"match_id": "M-2", "market": "hhad", "selection": "让平", "odds": 3.10,
     "bucket": "hedge", "line": "-1"},
    {"match_id": "M-2", "market": "hhad", "selection": "让负", "odds": 2.20,
     "bucket": "hedge", "line": "-1"},
    {"match_id": "M-3", "market": "had", "selection": "draw", "odds": 3.35,
     "bucket": "draw"},
    {"match_id": "M-4", "market": "had", "selection": "home", "odds": 1.64,
     "bucket": "parlay"},
    {"match_id": "M-5", "market": "had", "selection": "away", "odds": 2.75,
     "bucket": "parlay"},
]


def test_compose_respects_bucket_caps_and_total(tmp_path):
    store = DecisionStore(tmp_path / "decision")
    s = compose_tickets(_LEGS, load_budget(), channel="jczq", made_at="t", store=store)
    # 各 bucket 总额 ≤ 骨架上限(main/hedge 100 / draw 40 / parlay 60)
    assert s["by_bucket"]["main"]["stake"] <= 100
    assert s["by_bucket"]["hedge"]["stake"] <= 100
    assert s["by_bucket"]["draw"]["stake"] <= 40
    assert s["by_bucket"]["parlay"]["stake"] <= 60
    # channel 总额 ≤ ¥400 硬顶,正常输入不触发缩放
    assert s["total_stake_yuan"] <= 400 and s["scaled"] is False
    # Ticket 幂等落 store:main1 + hedge2 + draw1 + parlay1 = 5
    tks = store.load(Ticket)
    assert len(tks) == s["n_tickets"] == 5
    assert all(isinstance(t.stake_yuan, int) for t in tks)
    # 幂等:同 legs 再跑一次不翻倍
    compose_tickets(_LEGS, load_budget(), channel="jczq", made_at="t", store=store)
    assert len(store.load(Ticket)) == 5


def test_parlay_combined_odds_is_product():
    s = compose_tickets(_LEGS, load_budget(), channel="jczq", made_at="t")
    parlay = next(t for t in s["tickets"] if t["structure"] == "parlay")
    assert abs(parlay["combined_odds"] - 1.64 * 2.75) < 1e-9    # 连乘 = 4.51
    assert parlay["n_legs"] == 2 and parlay["stake_yuan"] <= 60


def test_single_bucket_even_split():
    legs = [
        {"match_id": "M-1", "market": "had", "selection": "home", "odds": 1.8,
         "bucket": "main"},
        {"match_id": "M-2", "market": "had", "selection": "away", "odds": 2.1,
         "bucket": "main"},
    ]
    s = compose_tickets(legs, load_budget(), channel="jczq", made_at="t")
    stakes = sorted(t["stake_yuan"] for t in s["tickets"])
    assert stakes == [50, 50]           # ¥100 均分,各 ≤ 100,和恰为 cap


def test_empty_legs_empty_tickets(tmp_path):
    store = DecisionStore(tmp_path / "decision")
    s = compose_tickets([], load_budget(), channel="jczq", made_at="t", store=store)
    assert s["n_tickets"] == 0 and s["total_stake_yuan"] == 0    # 空仓合法
    assert store.load(Ticket) == []


def test_hard_cap_scales_down_proportionally():
    # 人为把 cap 抬到总和 > 400 → 触发按比例缩(整数 floor 除)
    budget = {"period_cap_yuan": 400,
              "jczq": {"had_modal": 300, "hhad_cover": 300,
                       "draw_single": 40, "parlay": 60}}
    legs = [
        {"match_id": "M-1", "market": "had", "selection": "home", "odds": 1.8,
         "bucket": "main"},
        {"match_id": "M-2", "market": "hhad", "selection": "让平", "odds": 3.1,
         "bucket": "hedge"},
    ]
    s = compose_tickets(legs, budget, channel="jczq", made_at="t")
    assert s["scaled"] is True
    assert s["total_stake_yuan"] <= 400
    assert sorted(t["stake_yuan"] for t in s["tickets"]) == [200, 200]   # 300:300 等比


def test_computed_hit_prob_from_leg_probs():
    legs = [
        {"match_id": "M-4", "market": "had", "selection": "home", "odds": 1.64,
         "bucket": "parlay", "prob": 0.6},
        {"match_id": "M-5", "market": "had", "selection": "away", "odds": 2.75,
         "bucket": "parlay", "prob": 0.4},
    ]
    s = compose_tickets(legs, load_budget(), channel="jczq", made_at="t")
    assert abs(s["tickets"][0]["computed_hit_prob"] - 0.24) < 1e-9      # 0.6*0.4 连乘


def test_hit_prob_none_when_leg_prob_missing():
    s = compose_tickets(_LEGS, load_budget(), channel="jczq", made_at="t")
    # legs 无 prob → express 不臆造命中率
    assert all(t["computed_hit_prob"] is None for t in s["tickets"])


def test_decision_express_cli(tmp_path):
    import json

    from typer.testing import CliRunner

    from nutmeg.interfaces.cli import app

    legs_file = tmp_path / "legs.json"
    legs_file.write_text(json.dumps(_LEGS), encoding="utf-8")
    result = CliRunner().invoke(app, [
        "decision-express", "--legs-file", str(legs_file),
        "--channel", "jczq", "--output-dir", str(tmp_path), "--made-at", "t"])
    assert result.exit_code == 0, result.output
    assert "5 票" in result.output
    assert len(DecisionStore(tmp_path / "decision").load(Ticket)) == 5


# ── legs 形状闸（2026-09-14 入码）────────────────────────────────────────
#
# 出生事故：`com.nutmeg.decision.close` 2026-08-13 19:00 那次跑挂在
#   by_bucket.setdefault(str(leg.get("bucket") or ""), []).append(leg)
#   AttributeError: 'str' object has no attribute 'get'
# 此后该 agent 一直未加载（2026-09-14 退役移除）。根因：`run_express` /
# `run_decision_express_v2` 都是 `json.loads(...)` 之后**直接喂进来、零形状校验**；
# 喂进一个 dict（票面结构形状 `{"issue":…,"legs":{…}}`，即 `decision-audit-legs`
# 的输入）时，迭代 dict 得到的是**字符串键**，于是深处炸一个看不懂的 AttributeError。
#
# `decision-audit-legs` 对反向错配（把扁平数组喂给它）早就有具名拒绝
# （`missing_audit_metadata` + 退出码 1）。本闸补上对称的那一半。


def test_ticket_structure_shape_is_rejected_with_a_named_error():
    """票面结构（dict）误喂给 express → 具名报错并指出该走哪条命令。"""
    import pytest

    payload = {"issue": "26124", "legs": {"1": {"faces": "31"}, "2": {"faces": "310"}}}
    with pytest.raises(TypeError) as exc:
        compose_tickets(payload, load_budget(), channel="jczq", made_at="2026-08-13")
    message = str(exc.value)
    assert "decision-audit-legs" in message   # 指路：票面结构归那条命令
    assert "dict" in message


def test_string_element_is_rejected_with_its_index():
    """元素不是 dict → 报出**第几条腿**，不是深处的 AttributeError。"""
    import pytest

    with pytest.raises(TypeError) as exc:
        compose_tickets(
            [{"match_id": "m1", "market": "had", "selection": "3",
              "odds": 2.0, "bucket": "main"}, "周一001"],
            load_budget(), channel="jczq", made_at="2026-08-13")
    assert "第 2 条" in str(exc.value)


def test_valid_flat_array_still_composes(tmp_path):
    """闸不得误伤正常输入。"""
    summary = compose_tickets(
        [{"match_id": "m1", "market": "had", "selection": "3",
          "odds": 2.0, "bucket": "had_modal"}],
        load_budget(), channel="jczq", made_at="2026-08-13",
        store=DecisionStore(tmp_path / "decision"))
    assert summary["n_tickets"] >= 0
