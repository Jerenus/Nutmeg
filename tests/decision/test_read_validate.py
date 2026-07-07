# tests/decision/test_read_validate.py
from nutmeg.decision.ontology import Read
from nutmeg.decision.read_validate import validate_read


def _read(**kw):
    base = dict(read_id="R-1", match_id="M-1", snapshot_id="S-1", made_at="t",
                judge="claude", market="had",
                prior={"home": 0.46, "draw": 0.27, "away": 0.27},
                belief={"home": 0.40, "draw": 0.33, "away": 0.27},
                factors=[{"factor_id": "seeding_incentive", "direction": "draw",
                          "weight_pp": 6,
                          "evidence": [{"url": "u", "quote": "q", "at": "a"}]}],
                confidence=3, shadow=False)
    base.update(kw)
    return Read(**base)


ALLOWED = {"seeding_incentive"}


def test_valid_read_passes():
    assert validate_read(_read(), allowed_factors=ALLOWED) == []


def test_belief_must_normalize():
    bad = _read(belief={"home": 0.5, "draw": 0.3, "away": 0.3})   # sum 1.1
    errs = validate_read(bad, allowed_factors=ALLOWED)
    assert any("归一" in e for e in errs)


def test_factor_must_be_in_dictionary():
    bad = _read(factors=[{"factor_id": "made_up", "direction": "draw",
                          "weight_pp": 6, "evidence": [{"url": "u"}]}])
    errs = validate_read(bad, allowed_factors=ALLOWED)
    assert any("词典" in e for e in errs)


def test_non_shadow_factor_needs_evidence():
    bad = _read(factors=[{"factor_id": "seeding_incentive", "direction": "draw",
                          "weight_pp": 6, "evidence": []}])
    errs = validate_read(bad, allowed_factors=ALLOWED)
    assert any("证据" in e for e in errs)


def test_shadow_read_needs_belief_equals_prior_and_no_factors():
    ok = _read(shadow=True, factors=[],
               belief={"home": 0.46, "draw": 0.27, "away": 0.27})
    assert validate_read(ok, allowed_factors=ALLOWED) == []
    bad = _read(shadow=True, factors=[],
                belief={"home": 0.40, "draw": 0.33, "away": 0.27})
    assert any("shadow" in e for e in validate_read(bad, allowed_factors=ALLOWED))


def test_conf5_only_for_90min_direction():
    # conf5 允许(had 方向)
    assert validate_read(_read(confidence=5), allowed_factors=ALLOWED) == []
    # conf5 + crs(比分)非方向 → 拒绝
    bad = _read(confidence=5, market="crs",
                prior={"1-1": 0.5, "0-0": 0.5}, belief={"1-1": 0.5, "0-0": 0.5},
                factors=[])
    assert any("conf5" in e for e in validate_read(bad, allowed_factors=ALLOWED))


def _mk_scoped_read(factors):
    """weight_pp=4 与 belief−prior 偏移 4pp 一致(校验既有规则)。"""
    from nutmeg.decision.ontology import Read
    return Read(
        read_id="R-scope", match_id="M-1", snapshot_id="S-1",
        made_at="t", judge="claude", market="had",
        prior={"home": 0.46, "draw": 0.27, "away": 0.27},
        belief={"home": 0.42, "draw": 0.31, "away": 0.27},
        factors=factors, confidence=3, shadow=False)


def test_league_scope_factor_requires_scope_key():
    from nutmeg.decision.read_validate import validate_read
    read = _mk_scoped_read([{"factor_id": "league_bias", "direction": "draw",
                             "weight_pp": 4, "evidence": [{"url": "u"}]}])
    errs = validate_read(read, allowed_factors={"league_bias"},
                         factor_scopes={"league_bias": "league"})
    assert any("scope_key" in e for e in errs)


def test_league_scope_factor_with_scope_key_passes():
    from nutmeg.decision.read_validate import validate_read
    read = _mk_scoped_read([{"factor_id": "league_bias", "direction": "draw",
                             "weight_pp": 4, "scope_key": "swe-allsvenskan",
                             "evidence": [{"url": "u"}]}])
    assert validate_read(read, allowed_factors={"league_bias"},
                         factor_scopes={"league_bias": "league"}) == []


def test_factor_scopes_omitted_keeps_backward_compat():
    """不传 factor_scopes(旧调用面)→ 不做 scope 校验,行为不变。"""
    from nutmeg.decision.read_validate import validate_read
    read = _mk_scoped_read([{"factor_id": "league_bias", "direction": "draw",
                             "weight_pp": 4, "evidence": [{"url": "u"}]}])
    assert validate_read(read, allowed_factors={"league_bias"}) == []
