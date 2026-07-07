from nutmeg.decision.ontology import Factor, MarketSnapshot, Read
from nutmeg.decision.read_ingest import backfill_shadows, ingest_reads
from nutmeg.decision.store import DecisionStore


def _factors():
    return [Factor("seeding_incentive", "签位", "d", "2026-06-27", "071", status="probation")]


def _valid_read_payload():
    return {
        "read_id": "R-1", "match_id": "M-2026-07-08-周日092", "snapshot_id": "S-1",
        "made_at": "t", "judge": "claude", "market": "had",
        "prior": {"home": 0.42, "draw": 0.28, "away": 0.30},
        "belief": {"home": 0.36, "draw": 0.34, "away": 0.30},
        "factors": [{"factor_id": "seeding_incentive", "direction": "draw",
                     "weight_pp": 6, "evidence": [{"url": "u", "quote": "q", "at": "a"}]}],
        "confidence": 3, "shadow": False,
    }


def test_ingest_valid_read_persists(tmp_path):
    store = DecisionStore(tmp_path)
    errs = ingest_reads([_valid_read_payload()], store=store, factors=_factors())
    assert errs == []
    assert store.get(Read, "R-1") is not None


def test_ingest_rejects_invalid_read_no_persist(tmp_path):
    store = DecisionStore(tmp_path)
    bad = _valid_read_payload()
    bad["belief"] = {"home": 0.5, "draw": 0.3, "away": 0.3}   # sum 1.1
    errs = ingest_reads([bad], store=store, factors=_factors())
    assert errs and "R-1" in errs[0]
    assert store.get(Read, "R-1") is None                    # 未落库


def test_backfill_shadows_creates_shadow_for_unjudged(tmp_path):
    store = DecisionStore(tmp_path)
    # 两场读时欧赔快照,只有第一场有非 shadow Read
    for mno in ("周日092", "周日091"):
        store.upsert(MarketSnapshot(
            snapshot_id=f"S-{mno}", match_id=f"M-2026-07-08-{mno}",
            taken_at="2026-07-08T15:00:00+08:00", kind="read_time", source="apifootball",
            fair={"had": {"home": 0.45, "draw": 0.28, "away": 0.27}}))
    ingest_reads([_valid_read_payload()], store=store, factors=_factors())  # 092 已判
    n = backfill_shadows(store, run_date="2026-07-08",
                         made_at="2026-07-08T15:30:00+08:00")
    assert n == 1                                            # 只给 091 补 shadow
    shadows = [r for r in store.load(Read) if r.shadow]
    assert len(shadows) == 1 and shadows[0].match_id.endswith("周日091")
    assert shadows[0].belief == shadows[0].prior            # shadow: belief==prior


def test_backfill_shadows_idempotent(tmp_path):
    store = DecisionStore(tmp_path)
    store.upsert(MarketSnapshot(
        snapshot_id="S-091", match_id="M-2026-07-08-周日091", taken_at="t",
        kind="read_time", source="apifootball",
        fair={"had": {"home": 0.45, "draw": 0.28, "away": 0.27}}))
    backfill_shadows(store, run_date="2026-07-08", made_at="t2")
    n2 = backfill_shadows(store, run_date="2026-07-08", made_at="t3")
    assert n2 == 0                                           # 重跑不重复


def test_ingest_rejects_league_factor_without_scope_key(tmp_path):
    """ingest 用词典 scope 自动强制 scope_key(种子 league_bias=league scope)。"""
    from nutmeg.decision.factors import load_seed_factors
    from nutmeg.decision.read_ingest import ingest_reads
    from nutmeg.decision.store import DecisionStore
    payload = {
        "read_id": "R-x", "match_id": "M-1", "snapshot_id": "S-1",
        "made_at": "t", "judge": "claude", "market": "had",
        "prior": {"home": 0.46, "draw": 0.27, "away": 0.27},
        "belief": {"home": 0.42, "draw": 0.31, "away": 0.27},
        "factors": [{"factor_id": "league_bias", "direction": "draw",
                     "weight_pp": 4, "evidence": [{"url": "u"}]}],
        "confidence": 3, "shadow": False}
    store = DecisionStore(tmp_path)
    errors = ingest_reads([payload], store=store, factors=load_seed_factors())
    assert errors and "scope_key" in errors[0]
