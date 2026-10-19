from nutmeg.decision.rubric import derive_stance, rubric_summary, rubric_to_tilt, validate_rubric
from nutmeg.decision.rubric_items import ITEMS, RUBRIC_VERSION, question_table
from nutmeg.decision.stance import apply_tilt, validate_stance

KICK = "2026-10-03T22:00:00+08:00"
PRIOR = {"home": 0.50, "draw": 0.28, "away": 0.22}
SRC = {"source": "https://club.example/news", "captured_at": "2026-10-03T10:00:00+08:00"}


def _rubric(**items) -> dict:
    return {"version": RUBRIC_VERSION, "items": items}


def test_question_table_lists_every_item_once():
    text = question_table()
    assert all(item_id in text for item_id in ITEMS) and "F_absence_home" in text


def test_validate_accepts_legal_answers_and_rejects_structural_errors():
    norm, issues = validate_rubric(_rubric(
        F_absence_home={"p": 0.9, **SRC}, S_anchor_side={"answer": "home"},
        M_market_read={"answer": "agree"}), kickoff=KICK)
    assert not issues and norm["items"]["F_absence_home"]["answer"] == "yes"
    assert norm["items"]["F_absence_away"]["abstain"] is True        # 没答的项＝弃权
    _, bad = validate_rubric(_rubric(F_absence_home={"p": 1.4}, S_anchor_side={"answer": "left"},
                                     X_made_up={"p": 1}), kickoff=KICK)
    fields = {i.field for i in bad}
    assert {"rubric.items.F_absence_home.p", "rubric.items.S_anchor_side.answer",
            "rubric.items.X_made_up"} <= fields
    assert validate_rubric("nope")[1][0].field == "rubric"


def test_yes_without_source_or_after_kickoff_is_coerced_to_abstain():
    norm, issues = validate_rubric(_rubric(
        F_absence_home={"p": 0.9},
        F_suspension={"answer": "away", "p": 0.8, "source": "x",
                      "captured_at": "2026-10-03T23:00:00+08:00"},
        S_underdog_path={"p": 0.8}), kickoff=KICK)
    assert not issues
    assert norm["items"]["F_absence_home"]["abstain"] and norm["items"]["F_absence_home"]["coerced"]
    assert norm["items"]["F_suspension"]["answer"] == "unknown"
    assert norm["items"]["S_underdog_path"]["answer"] == "yes"       # 不要求来源的项照常
    assert len(norm["coerced"]) == 2 and "T12" in norm["coerced"][1]


def test_no_fact_or_no_anchor_means_no_tilt():
    norm, _ = validate_rubric(_rubric(S_anchor_side={"answer": "home"},
                                      S_underdog_path={"p": 0.9}, S_draw_mode={"p": 0.8}))
    assert rubric_to_tilt(norm, PRIOR) is None                       # 事实层空 → 无锚归零
    norm, _ = validate_rubric(_rubric(F_absence_away={"p": 0.9, **SRC},
                                      S_anchor_side={"answer": "none"}))
    assert rubric_to_tilt(norm, PRIOR) is None                       # 均势 → 归零
    assert derive_stance({"face": "3", "structure": "single", "tilt": None}, norm, PRIOR)[
        "why_not_market"] == "none"
    norm, _ = validate_rubric(_rubric(F_absence_away={"p": 0.9, **SRC},
                                      S_anchor_side={"answer": "unknown"}))
    tilt = rubric_to_tilt(norm, PRIOR, version="r1")              # 锚方未知 ≠ 均势：事实项照拨
    assert tilt and tilt["shift"]["0"] < 0


def test_tilt_is_a_zero_sum_shift_with_per_item_evidence_that_passes_stance_rules():
    norm, _ = validate_rubric(_rubric(
        F_absence_away={"p": 0.9, **SRC},                              # 6×0.9 = 5.4 → 客减
        F_suspension={"answer": "away", "p": 1.0, **SRC},               # 4 → 客减
        S_anchor_side={"answer": "home"},
        S_underdog_path={"p": 0.8},                                     # 2×0.8 → 弱方(客)加
        S_draw_mode={"p": 0.6}), kickoff=KICK)                           # 2×0.6 → 平加
    tilt = rubric_to_tilt(norm, PRIOR, version="r1")         # 聚合机制按 r1 上限测
    assert sum(tilt["shift"].values()) == 0 and tilt["shift"]["0"] < 0 < tilt["shift"]["3"]
    assert {e["item"] for e in tilt["evidence"]} == {"F_absence_away", "F_suspension",
                                                      "S_underdog_path", "S_draw_mode"}
    assert tilt["evidence"][0]["tier"] == "official" and tilt["derived_from"] == "rubric:r1"
    stance = derive_stance({"face": "3", "structure": "double", "cover": "1", "confidence": 3,
                            "falsifier": "客队首发公布主力中卫在列则作废", "why_not_market": "none",
                            "tilt": {"face": "3", "evidence": []}}, norm, PRIOR)
    assert stance["tilt_declared"] == {"face": "3", "evidence": []}
    assert stance["why_not_market"] == "tilt_evidence"            # r2 下仍有 F_suspension 拨动
    _, issues = validate_stance(stance, confidence=3, death_three_proofs={})
    assert not issues, [i.message for i in issues]
    result = apply_tilt(PRIOR, tilt, kickoff=KICK)
    assert not result.zeroed and result.belief["home"] > PRIOR["home"]
    assert result.belief["away"] < PRIOR["away"] and abs(sum(result.belief.values()) - 1) < 1e-9
    peak = max(abs(v) for v in tilt["shift"].values())
    assert result.applied_pp == peak                                  # 证据预算盖住峰值，不二次截断


def test_r2_retires_ten_caps_and_only_suspension_still_moves_belief():
    """2026-10-19 Jun 裁「可以」：9 项 T13 propose_zero + F_rotation（反号）上限退役。
    问题照问、照记账、T13 照测；拨动只剩 F_suspension。"""
    from nutmeg.decision.rubric_items import (
        EFFECT_ITEMS,
        RUBRIC_CHANGELOG,
        SUPPORTED_VERSIONS,
        directional_items,
        items_markdown,
    )

    assert RUBRIC_VERSION == "r2" and SUPPORTED_VERSIONS == ("r1", "r2")
    assert directional_items() == ("F_suspension",)
    assert len(directional_items("r1")) == 11 and set(directional_items("r1")) == set(EFFECT_ITEMS)
    assert RUBRIC_CHANGELOG[-1]["version"] == "r2"
    assert "#rubric-r2" in RUBRIC_CHANGELOG[-1]["evidence"]
    answers = dict(F_absence_away={"p": 0.9, **SRC}, S_anchor_side={"answer": "home"},
                   S_underdog_path={"p": 0.8}, F_rotation={"answer": "away", "p": 1.0, **SRC})
    norm, _ = validate_rubric(_rubric(**answers), kickoff=KICK)
    assert rubric_to_tilt(norm, PRIOR) is None                        # 成立的项全是退役上限
    norm, _ = validate_rubric(_rubric(**answers, F_suspension={"answer": "away", "p": 1.0, **SRC}),
                              kickoff=KICK)
    tilt = rubric_to_tilt(norm, PRIOR)
    assert [e["item"] for e in tilt["evidence"]] == ["F_suspension"]
    assert tilt["derived_from"] == "rubric:r2" and tilt["shift"]["0"] == -4
    assert "0（r2 退役，原 6）" in items_markdown()


def test_priced_in_halves_fact_pp_and_peak_is_capped_at_15():
    base = dict(F_absence_home={"p": 1.0, **SRC}, F_suspension={"answer": "home", "p": 1.0, **SRC},
                F_rotation={"answer": "home", "p": 1.0, **SRC},
                F_goalkeeper={"answer": "home", "p": 1.0, **SRC},
                S_anchor_side={"answer": "home"})
    full = rubric_to_tilt(validate_rubric(_rubric(**base))[0], PRIOR, version="r1")
    assert full["shift"]["3"] == -15                                  # 6+4+3+3=16 → 封顶 15
    halved = rubric_to_tilt(validate_rubric(_rubric(**base, M_facts_priced={"p": 0.9}))[0], PRIOR,
                            version="r1")
    assert halved["shift"]["3"] == -8 and halved["priced_halved"] is True


def test_spine_intact_no_hits_the_anchor_and_summary_counts():
    norm, _ = validate_rubric(_rubric(
        F_absence_home={"p": 0.8, **SRC}, S_anchor_side={"answer": "home"},
        S_spine_intact={"p": 0.1, **SRC}))
    tilt = rubric_to_tilt(norm, PRIOR, version="r1")
    items = {e["item"]: e for e in tilt["evidence"]}
    assert "S_spine_intact" in items and items["S_spine_intact"]["tier"] == "confirmed_structural"
    assert rubric_summary(norm, kappa=0.6).startswith("事实1/7 结构1/4 弃权")
    assert rubric_summary(None) == "—"


def test_reader_belief_is_normalised_and_bad_belief_is_an_error():
    norm, issues = validate_rubric({"version": "r1", "items": {},
                                    "belief": {"3": 0.5, "1": 0.3, "0": 0.2}})
    assert not issues and norm["belief"] == {"3": 0.5, "1": 0.3, "0": 0.2}
    _, issues = validate_rubric({"version": "r1", "items": {}, "belief": {"3": 0.9, "1": 0.9}})
    assert any(i.field == "rubric.belief" for i in issues)


def test_governance_versions_source_tier_and_items_table():
    from nutmeg.decision.rubric_items import (
        RUBRIC_CHANGELOG,
        SOURCE_TIERS,
        SUPPORTED_VERSIONS,
        active_items,
        items_markdown,
    )

    assert RUBRIC_VERSION in SUPPORTED_VERSIONS and RUBRIC_CHANGELOG[0]["version"] == "r1"
    assert set(active_items("r1")) == set(ITEMS)
    _, issues = validate_rubric({"version": "r9", "items": {}})
    assert any(i.field == "rubric.version" for i in issues)
    norm, issues = validate_rubric(_rubric(
        F_absence_home={"p": 0.9, "source_tier": "club_official", **SRC},
        F_absence_away={"p": 0.9, "source_tier": "blog", **SRC}), kickoff=KICK)
    assert not issues
    assert norm["items"]["F_absence_home"]["source_tier"] == "club_official"
    assert norm["items"]["F_absence_away"]["source_tier"] == "unknown"      # 不在枚举 → unknown
    assert "club_official" in SOURCE_TIERS and "source_tier" in question_table()
    table = items_markdown()
    assert "| `F_absence_home` | fact | noul |" in table and "| r1 |" in table
