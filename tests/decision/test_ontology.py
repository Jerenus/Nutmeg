from nutmeg.decision.ontology import (
    Factor,
    FactorVerdict,
    MarketSnapshot,
    Match,
    Read,
    Settlement,
    Ticket,
)


def test_match_id_and_roundtrip():
    m = Match(
        match_id="M-2026-07-08-092",
        kickoff_at="2026-07-08T03:00:00+08:00",
        home="Mexico", away="England", competition="WC2026",
        channel_refs={"jczq_match_no": "周日092"},
    )
    assert m.id == "M-2026-07-08-092"
    assert Match.from_dict(m.to_dict()) == m


def test_snapshot_id_and_roundtrip():
    s = MarketSnapshot(
        snapshot_id="S-...-1", match_id="M-...", taken_at="2026-07-08T15:00:00+08:00",
        kind="read_time", source="sporttery",
        fair={"had": {"home": 0.46, "draw": 0.27, "away": 0.27}},
        raw_odds={"had": {"home": 2.03, "draw": 3.30, "away": 3.55}},
        lines={"hhad_line": -1.0, "ou_line": 2.5},
    )
    assert s.id == "S-...-1"
    assert MarketSnapshot.from_dict(s.to_dict()) == s
    assert s.kind in ("read_time", "closing")


def test_read_roundtrip_and_id():
    r = Read(
        read_id="R-2026-07-08-092", match_id="M-...", snapshot_id="S-...",
        made_at="2026-07-08T15:00:00+08:00", judge="claude", market="had",
        prior={"home": 0.46, "draw": 0.27, "away": 0.27},
        belief={"home": 0.40, "draw": 0.33, "away": 0.27},
        factors=[{"factor_id": "seeding_incentive", "direction": "draw",
                  "weight_pp": 6, "evidence": [{"url": "x", "quote": "y", "at": "z"}]}],
        scenarios=[{"story": "铁桶拖平", "weight": 0.33}],
        falsifier="若 X 首发则撤回", confidence=3, shadow=False, note="一句话",
    )
    assert r.id == "R-2026-07-08-092"
    assert Read.from_dict(r.to_dict()) == r


def test_factor_ticket_settlement_verdict_roundtrip():
    f = Factor(factor_id="seeding_incentive", name_zh="签位激励",
               definition="MD3 高名次碰强签→赢反而更糟", born_at="2026-06-27",
               born_from="071 实证", status="probation")
    assert f.id == "seeding_incentive" and Factor.from_dict(f.to_dict()) == f

    t = Ticket(ticket_id="T-1", channel="jczq", made_at="2026-07-08T15:00:00+08:00",
               legs=[{"match_id": "M-...", "read_id": "R-...", "market": "had",
                      "pick": "home", "line": None, "odds": 1.64}],
               structure="single", stake_yuan=15, computed_hit_prob=0.4,
               tag="had_modal", budget_bucket="had_modal")
    assert t.id == "T-1" and Ticket.from_dict(t.to_dict()) == t

    s = Settlement(settlement_id="SET-R-...", ref_type="read", ref_id="R-...",
                   settled_at="2026-07-09T08:00:00+08:00", outcome_90="draw",
                   score="1-1", closing_snapshot_id="S-close-...",
                   brier=0.18, clv_pp=0.02, hit=None, pnl_yuan=None)
    assert s.id == "SET-R-..." and Settlement.from_dict(s.to_dict()) == s

    v = FactorVerdict(factor_id="seeding_incentive", as_of="2026-07-20",
                      n_reads=31, brier_delta_vs_prior=-0.01, clv_hit_rate=0.58,
                      direction_hit_rate=0.55, recommendation="keep",
                      next_review_at="2026-08-20")
    assert v.id == "seeding_incentive" and FactorVerdict.from_dict(v.to_dict()) == v


def test_match_entity_refs_roundtrip_and_legacy_default():
    from nutmeg.decision.ontology import Match
    m = Match(match_id="M-x", kickoff_at="t", home="哈马比", away="卡尔马",
              competition="瑞超", home_team_id="swe-hammarby",
              away_team_id="swe-kalmar", competition_id="swe-allsvenskan")
    m2 = Match.from_dict(m.to_dict())
    assert (m2.home_team_id, m2.away_team_id, m2.competition_id) == (
        "swe-hammarby", "swe-kalmar", "swe-allsvenskan")
    # 旧 matches.jsonl 行(无新字段)→ None 默认,不炸
    legacy = Match.from_dict({"match_id": "M-y", "kickoff_at": "t",
                              "home": "a", "away": "b"})
    assert legacy.home_team_id is None and legacy.competition_id is None
