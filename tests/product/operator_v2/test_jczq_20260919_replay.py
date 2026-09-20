from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nutmeg.interfaces.cli import app
from nutmeg.product.jczq_replay import JczqReplayRunner, _load_board, _production_counts


def _write_source_day(
    root: Path,
    *,
    count: int = 30,
    include_results: bool = False,
) -> None:
    day_root = root / "jczq" / "daily" / "2026-09-19"
    day_root.mkdir(parents=True)
    matches = []
    reads = []
    for index in range(1, count + 1):
        code = f"周六{index:03d}"
        matches.append(
            {
                "matchId": 2_000_000 + index,
                "matchNumStr": code,
                "matchDate": "2026-09-19",
                "matchTime": "23:00:00",
            }
        )
        reads.append(
            {
                "read_id": f"read-{index}",
                "match_id": f"legacy-match-{index}",
                "made_at": "2026-09-19T12:00:00+08:00",
                "status": "draft",
            }
        )
    (day_root / "sporttery_markets.json").write_text(
        json.dumps(
            {
                "lastUpdateTime": "2026-09-19 11:00:00",
                "matchInfoList": [
                    {
                        "businessDate": "2026-09-19",
                        "subMatchList": matches,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (day_root / "reads.json").write_text(json.dumps(reads), encoding="utf-8")
    accepted_indexes = tuple(index for index in range(1, count + 1) if index != 2)[:25]
    for index in accepted_indexes:
        (day_root / f"research-周六{index:03d}.json").write_text(
            json.dumps({"captured_at": "2026-09-19T11:03:42+08:00"}),
            encoding="utf-8",
        )
    (day_root / "research-周六002.rejected.json").write_text(
        json.dumps({"error": "canonical intake rejected"}),
        encoding="utf-8",
    )
    if include_results:
        (day_root / "results.json").write_text(
            json.dumps(
                {
                    "captured_at": "2026-09-20T12:00:00+08:00",
                    "results": [
                        {
                            "match_id": f"jczq-sporttery-{2_000_000 + index}",
                            "score_90": "0-1" if index == 1 else "2-1",
                            "status": "final",
                        }
                        for index in range(1, count + 1)
                    ],
                }
            ),
            encoding="utf-8",
        )


def test_replay_refuses_the_production_ontology_path(tmp_path) -> None:
    source = tmp_path / "production"
    _write_source_day(source)
    (source / "ontology").mkdir()

    with pytest.raises(ValueError, match="isolated ontology path equals production"):
        JczqReplayRunner(source_root=source, isolated_root=source).run("2026-09-19")


def test_replay_completes_a2_to_a6_but_blocks_missing_authoritative_results(
    tmp_path,
) -> None:
    source = tmp_path / "production"
    isolated = tmp_path / "isolated"
    _write_source_day(source)

    report = JczqReplayRunner(source_root=source, isolated_root=isolated).run(
        "2026-09-19"
    )

    assert report.board_count == 30
    assert report.research_terminal_count == 30
    assert report.research_status_counts == {
        "researched": 25,
        "rejected": 1,
        "price_only": 4,
    }
    assert report.missing_lineage == ()
    assert report.odds_band_outcomes == ("10x", "20x", "50x", "100x")
    assert report.terminal_kind == "no_ticket"
    assert report.run_status == "failed"
    assert report.authoritative_result_count == 0
    assert "authoritative_results_missing" in report.failures
    assert report.production_delta == {
        "objects": 0,
        "money_entries": 0,
        "dispatches": 0,
        "prospective_observations": 0,
    }
    assert report.accepted is False
    assert "research_capture_time_missing:周六002" not in report.failures
    assert len(report.report_sha256) == 64
    saved = json.loads(
        (isolated / "replay-2026-09-19.json").read_text(encoding="utf-8")
    )
    assert saved == report.to_dict()


def test_replay_finishes_accepted_from_derived_a2_to_a7_state(tmp_path) -> None:
    source = tmp_path / "production"
    isolated = tmp_path / "isolated"
    _write_source_day(source, include_results=True)

    report = JczqReplayRunner(source_root=source, isolated_root=isolated).run(
        "2026-09-19"
    )

    assert report.accepted is True
    assert report.run_status == "accepted"
    assert report.source_manifest_hash
    assert report.isolated_database_identity == str(
        (isolated / "ontology" / "ontology.db").resolve()
    )
    assert report.adjudication_branch_counts == {
        "approve": 28,
        "revise": 1,
        "reject": 1,
    }
    assert report.committed_forecast_count == 30
    assert report.evidence_lineage_count == 30
    assert set(report.candidate_set_revision_ids) == {
        "judgment_bound",
        "conditional_market_counterfactual",
    }
    assert len(report.structured_band_outcomes) == 8
    assert report.no_ticket_revision_id
    assert report.authoritative_result_count == 30
    assert report.replay_prediction_count == 30
    assert report.replay_score_count == 30
    assert report.rsi_statuses == {
        "R0": "replay_excluded",
        "F5": "replay_excluded",
        "F9": "replay_excluded",
    }
    assert report.quarantined_gaps == (
        "research-周六002.rejected.json:rejected_research_capture_time_missing",
    )
    assert report.failures == ()
    import sqlite3

    connection = sqlite3.connect(report.isolated_database_identity)
    try:
        published_at, retrieved_at = connection.execute(
            "SELECT published_at, retrieved_at FROM artifact_retrievals "
            "WHERE source_type = 'official_result'"
        ).fetchone()
    finally:
        connection.close()
    assert published_at is None
    assert retrieved_at == "2026-09-20T12:00:00+08:00"


def test_replay_cli_writes_report_and_fails_closed_on_incomplete_lineage(tmp_path) -> None:
    source = tmp_path / "production"
    isolated = tmp_path / "isolated"
    _write_source_day(source)

    result = CliRunner().invoke(
        app,
        [
            "workflow",
            "jczq-replay",
            "--day",
            "2026-09-19",
            "--isolated-root",
            str(isolated),
            "--data-dir",
            str(source),
        ],
    )

    assert result.exit_code == 1
    document = json.loads(result.stdout)
    assert document["accepted"] is False
    assert document["board_count"] == 30
    assert (isolated / "replay-2026-09-19.json").is_file()


def test_replay_selects_only_the_requested_business_date_group(tmp_path) -> None:
    source = tmp_path / "production"
    isolated = tmp_path / "isolated"
    _write_source_day(source)
    board_path = source / "jczq" / "daily" / "2026-09-19" / "sporttery_markets.json"
    document = json.loads(board_path.read_text(encoding="utf-8"))
    next_day = [
        {
            **row,
            "matchId": row["matchId"] + 100,
            "matchNumStr": row["matchNumStr"].replace("周六", "周日"),
            "businessDate": "2026-09-20",
            "matchDate": "2026-09-20",
        }
        for row in document["matchInfoList"][0]["subMatchList"]
    ]
    document["matchInfoList"].append(
        {"businessDate": "2026-09-20", "subMatchList": next_day}
    )
    board_path.write_text(json.dumps(document), encoding="utf-8")

    report = JczqReplayRunner(source_root=source, isolated_root=isolated).run(
        "2026-09-19"
    )

    assert report.board_count == 30
    assert report.research_terminal_count == 30
    assert report.research_status_counts == {
        "researched": 25,
        "rejected": 1,
        "price_only": 4,
    }


def test_production_count_snapshot_reads_money_dispatch_and_prospective_rows(
    tmp_path,
) -> None:
    database = tmp_path / "ontology" / "ontology.db"
    database.parent.mkdir()
    import sqlite3

    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            """
            CREATE TABLE objects (id INTEGER PRIMARY KEY);
            CREATE TABLE cash_transactions (id INTEGER PRIMARY KEY);
            CREATE TABLE outbox_events (id INTEGER PRIMARY KEY);
            CREATE TABLE rsi_observations (id INTEGER PRIMARY KEY, prospective INTEGER);
            INSERT INTO objects VALUES (1), (2);
            INSERT INTO cash_transactions VALUES (1);
            INSERT INTO outbox_events VALUES (1), (2), (3);
            INSERT INTO rsi_observations VALUES (1, 1), (2, 0);
            """
        )
        connection.commit()
    finally:
        connection.close()

    assert _production_counts(tmp_path / "ontology") == {
        "objects": 8,
        "money_entries": 1,
        "dispatches": 3,
        "prospective_observations": 1,
    }


def test_board_reuses_canonical_match_ids_from_legs_projection(tmp_path) -> None:
    source = tmp_path / "production"
    _write_source_day(source, count=1)
    day_root = source / "jczq" / "daily" / "2026-09-19"
    (day_root / "jczq-legs-base.json").write_text(
        json.dumps(
            {
                "day": "2026-09-19",
                "legs": {"周六001": {"match_id": "match-canonical-1"}},
            }
        ),
        encoding="utf-8",
    )

    board, failures = _load_board(
        day_root / "sporttery_markets.json",
        "2026-09-19",
        identity_path=day_root / "jczq-legs-base.json",
    )

    assert failures == ()
    assert board.matches[0].match_id == "match-canonical-1"
