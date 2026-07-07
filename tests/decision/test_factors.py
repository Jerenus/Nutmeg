# tests/decision/test_factors.py
from nutmeg.decision.factors import ACTIVE_CAP, active_factor_ids, load_seed_factors


def test_seed_has_six_probation_factors():
    seed = load_seed_factors()
    assert len(seed) == 6
    assert all(f.status == "probation" for f in seed)
    ids = {f.factor_id for f in seed}
    assert {"seeding_incentive", "bunker_profile", "lineup_news_gap",
            "league_bias", "market_line_error", "fatigue_discount"} <= ids


def test_seed_factors_carry_born_from():
    assert all(f.born_from for f in load_seed_factors())   # 出生证必填


def test_active_ids_filters_status():
    from nutmeg.decision.ontology import Factor
    factors = [
        Factor("a", "A", "d", "2026-07-06", "x", status="active"),
        Factor("b", "B", "d", "2026-07-06", "x", status="probation"),
        Factor("c", "C", "d", "2026-07-06", "x", status="retired"),
    ]
    assert active_factor_ids(factors) == {"a"}


def test_active_cap_is_twelve():
    assert ACTIVE_CAP == 12


def test_seed_factors_carry_scope():
    """种子词典的隐性多尺度显式化(提案 §P0 漏点2)。"""
    scopes = {f.factor_id: f.scope for f in load_seed_factors()}
    assert scopes == {
        "seeding_incentive": "pairing",
        "bunker_profile": "pairing",
        "lineup_news_gap": "appearance",
        "league_bias": "league",
        "market_line_error": "match",
        "fatigue_discount": "appearance",
    }


def test_factor_scope_defaults_to_match_for_legacy_rows():
    """旧 factors.jsonl 行无 scope → 加载默认 match(向后兼容,不炸 live store)。"""
    from nutmeg.decision.ontology import Factor
    f = Factor.from_dict({"factor_id": "x", "name_zh": "X", "definition": "d",
                          "born_at": "2026-07-07", "born_from": "test"})
    assert f.scope == "match"


def test_factor_scopes_map():
    from nutmeg.decision.factors import factor_scopes
    assert factor_scopes(load_seed_factors())["league_bias"] == "league"


def test_sync_factor_scopes_fixes_legacy_rows_and_is_idempotent(tmp_path):
    """M2 已落库的旧行无 scope → 默认 match 对 league_bias 是错的;sync 按种子纠偏,
    只改 scope 保留 status。幂等:第二次跑 0 变更。"""
    from nutmeg.decision.factors import sync_factor_scopes
    from nutmeg.decision.ontology import Factor
    from nutmeg.decision.store import DecisionStore
    store = DecisionStore(tmp_path)
    store.upsert(Factor.from_dict({
        "factor_id": "league_bias", "name_zh": "极端联赛画像", "definition": "d",
        "born_at": "2026-07-05", "born_from": "x", "status": "active"}))
    assert store.get(Factor, "league_bias").scope == "match"   # 旧行错误默认
    assert sync_factor_scopes(store) == 1
    fixed = store.get(Factor, "league_bias")
    assert fixed.scope == "league"
    assert fixed.status == "active"                            # 状态保留
    assert sync_factor_scopes(store) == 0                      # 幂等
