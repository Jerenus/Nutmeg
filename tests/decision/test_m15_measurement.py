"""M1 度量完成:shadow/real 去重守卫 + 参与精度(判读 vs 市场基线)。"""
from nutmeg.decision.calibrate import participation_precision
from nutmeg.decision.ontology import Match, Read, Settlement
from nutmeg.decision.read_ingest import ingest_reads
from nutmeg.decision.store import DecisionStore


def test_store_remove(tmp_path):
    s = DecisionStore(tmp_path)
    s.upsert(Match(match_id="M-1", kickoff_at="t", home="A", away="B"))
    assert s.remove(Match, "M-1") is True
    assert s.load(Match) == []
    assert s.remove(Match, "M-1") is False


def test_real_read_supersedes_shadow(tmp_path):
    s = DecisionStore(tmp_path)
    # 先有 shadow(顺序颠倒的坏情况),再来真判读→shadow 应被删,一场只留一条
    s.upsert(Read(read_id="R-shadow-M-1", match_id="M-1", snapshot_id="S", made_at="t",
                  judge="shadow", market="had",
                  prior={"home": 0.4, "draw": 0.3, "away": 0.3},
                  belief={"home": 0.4, "draw": 0.3, "away": 0.3}, shadow=True))
    ingest_reads([{"read_id": "R-real", "match_id": "M-1", "snapshot_id": "S",
                   "made_at": "t2", "judge": "claude", "market": "had",
                   "prior": {"home": 0.4, "draw": 0.3, "away": 0.3},
                   "belief": {"home": 0.5, "draw": 0.25, "away": 0.25},
                   "factors": [], "confidence": 3, "shadow": False}],
                 store=s, factors=[])
    reads = s.load(Read)
    assert len(reads) == 1 and reads[0].read_id == "R-real"


def _read(rid, shadow, factored, prior, belief):
    return Read(read_id=rid, match_id=f"M-{rid}", snapshot_id="S", made_at="t",
                judge="shadow" if shadow else "claude", market="had",
                prior=prior, belief=belief,
                factors=[{"factor_id": "seeding_incentive"}] if factored else [],
                shadow=shadow)


def test_participation_precision_splits_divergent_vs_shadow(tmp_path):
    s = DecisionStore(tmp_path)
    p = {"home": 0.42, "draw": 0.28, "away": 0.30}
    # divergent: 偏平且 CLV 命中
    s.upsert(_read("d1", False, True, p, {"home": 0.36, "draw": 0.34, "away": 0.30}))
    s.upsert(Settlement(settlement_id="SET-read-d1", ref_type="read", ref_id="d1",
                        settled_at="t", outcome_90="draw", brier=0.5, clv_pp=0.01))
    # shadow: 跟市场
    s.upsert(_read("s1", True, False, p, p))
    s.upsert(Settlement(settlement_id="SET-read-s1", ref_type="read", ref_id="s1",
                        settled_at="t", outcome_90="draw", brier=0.6, clv_pp=None))
    pp = participation_precision(s)
    assert pp["divergent"]["n"] == 1 and pp["divergent"]["clv_hit_rate"] == 1.0
    assert pp["shadow"]["n"] == 1 and pp["shadow"]["clv_hit_rate"] is None
