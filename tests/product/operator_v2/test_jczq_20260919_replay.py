from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nutmeg.interfaces.cli import app
from nutmeg.product.jczq_replay import JczqReplayRunner, _load_board, _production_counts


def _write_source_day(root: Path, *, count: int = 30) -> None:
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
    (day_root / "research-周六001.json").write_text(
        json.dumps({"captured_at": "2026-09-19T11:03:42+08:00"}),
        encoding="utf-8",
    )
    (day_root / "research-周六002.rejected.json").write_text(
        json.dumps({"error": "canonical intake rejected"}),
        encoding="utf-8",
    )


def test_replay_refuses_the_production_ontology_path(tmp_path) -> None:
    source = tmp_path / "production"
    _write_source_day(source)
    (source / "ontology").mkdir()

    with pytest.raises(ValueError, match="isolated ontology path equals production"):
        JczqReplayRunner(source_root=source, isolated_root=source).run("2026-09-19")


def test_replay_materializes_all_board_terminals_but_blocks_missing_v2_lineage(
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
        "researched": 1,
        "rejected": 1,
        "price_only": 28,
    }
    assert report.missing_lineage == (
        "candidate_set_revisions",
        "candidate_audits",
        "terminal_decision",
    )
    assert report.odds_band_outcomes == ()
    assert report.terminal_kind == "missing"
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
        "researched": 1,
        "rejected": 1,
        "price_only": 28,
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
