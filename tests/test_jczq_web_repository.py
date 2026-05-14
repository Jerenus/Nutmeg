from __future__ import annotations

from pathlib import Path

from nutmeg.storage.jczq_web_repository import JczqWebRepository


def test_repository_initializes_and_persists_day_match_and_candidate_leg(tmp_path: Path) -> None:
    repo = JczqWebRepository(tmp_path / "cockpit.sqlite3")
    repo.initialize()

    repo.upsert_day(run_date="2026-05-06", status="brief_generated", brief_path="brief.md")
    repo.upsert_match(
        run_date="2026-05-06",
        match_no="周三003",
        league="日职",
        home_team="川崎前锋",
        away_team="东京绿茵",
        role="均衡分歧场",
        goal_line=-1,
        tags=["comfort", "poisson_alpha"],
        flags={"coinflip": False, "comfort": True},
    )
    repo.upsert_candidate_leg(
        run_date="2026-05-06",
        match_no="周三003",
        pool="crs",
        play="比分",
        pick="0:0",
        odds=11.0,
        poisson_edge=0.219,
        source="brief_section_4",
        tags=["poisson_alpha", "low_goal"],
    )

    assert repo.get_day("2026-05-06")["status"] == "brief_generated"
    assert repo.list_days()[0]["run_date"] == "2026-05-06"
    assert repo.list_matches("2026-05-06") == [
        {
            "run_date": "2026-05-06",
            "match_no": "周三003",
            "league": "日职",
            "home_team": "川崎前锋",
            "away_team": "东京绿茵",
            "role": "均衡分歧场",
            "goal_line": -1.0,
            "tags": ["comfort", "poisson_alpha"],
            "flags": {"coinflip": False, "comfort": True},
        }
    ]
    assert repo.list_candidate_legs("2026-05-06")[0]["poisson_edge"] == 0.219


def test_repository_saves_analysis_ticket_version_findings_and_review(tmp_path: Path) -> None:
    repo = JczqWebRepository(tmp_path / "cockpit.sqlite3")
    repo.initialize()
    repo.upsert_day(run_date="2026-05-06", status="workspace_initialized")

    repo.save_analysis(
        run_date="2026-05-06",
        agent="claude",
        content="# Claude\n分析内容",
        artifact_path="debate/claude-analysis.md",
        brief_hash="abc123",
    )
    version = repo.create_ticket_version(
        run_date="2026-05-06",
        source="human",
        status="draft",
        best_pick="C",
    )
    repo.replace_version_tickets(
        run_date="2026-05-06",
        version=version,
        tickets=[
            {
                "ticket_id": "C",
                "kind": "poisson_solo",
                "name": "Poisson 单核",
                "stake": 25,
                "is_best_pick": True,
                "is_extra_budget": False,
                "rationale": "今日最高 Poisson edge",
                "legs": [
                    {
                        "match_no": "周三003",
                        "league": "日职",
                        "home_team": "川崎前锋",
                        "away_team": "东京绿茵",
                        "pool": "crs",
                        "play": "比分",
                        "pick": "0:0",
                        "odds": 11.0,
                        "goal_line": None,
                        "poisson_edge": 0.219,
                        "note": "Rule A",
                    }
                ],
            }
        ],
    )
    repo.save_validation_findings(
        run_date="2026-05-06",
        version=version,
        findings=[
            {
                "severity": "warning",
                "ticket_id": "C",
                "code": "poisson_solo_dilution",
                "message": "C 单核被额外串关稀释",
                "blocks_finalization": False,
            }
        ],
    )
    repo.record_review(
        run_date="2026-05-06",
        version=version,
        ticket_id="C",
        status="hit",
        actual_return=275.0,
        profit_loss=250.0,
        failed_leg=None,
        notes="0:0 命中",
        leg_reviews=[
            {
                "leg_index": 1,
                "match_no": "周三003",
                "pool": "crs",
                "pick": "0:0",
                "status": "hit",
                "actual_result": "0:0",
                "notes": "Poisson 单核兑现",
            }
        ],
    )

    assert repo.get_analysis("2026-05-06", "claude")["brief_hash"] == "abc123"
    stored_version = repo.get_ticket_version("2026-05-06", version)
    assert stored_version["best_pick"] == "C"
    assert stored_version["tickets"][0]["total_odds"] == 11.0
    assert stored_version["tickets"][0]["theoretical_return"] == 275.0
    assert stored_version["tickets"][0]["legs"][0]["pick"] == "0:0"
    assert (
        repo.list_validation_findings("2026-05-06", version)[0]["code"]
        == "poisson_solo_dilution"
    )
    assert repo.list_reviews("2026-05-06", version)[0]["leg_reviews"][0]["status"] == "hit"
