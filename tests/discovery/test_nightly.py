import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.discovery.nightly import run_nightly
from tests.discovery.test_day_inputs import _day
from tests.discovery.test_standing_approval import _standing

BJ = timezone(timedelta(hours=8))
DAY = "2026-09-23"
NOW = datetime(2026, 9, 23, 20, 30, tzinfo=BJ)


class _Recorded:
    world_id = "discovery-world-test"
    sealed_manifest_hash = "sealed"
    selected_node_ids = ()


def _setup(tmp_path: Path):
    jczq = _day(tmp_path, n=3)
    shadow = tmp_path / "shadow.db"
    shadow.write_bytes(b"")
    standing = _standing(
        tmp_path,
        valid_from="2026-09-23T00:00:00+08:00",
        approved_at="2026-09-23T00:00:00+08:00",
    )
    return jczq, shadow, standing


def _run(tmp_path, jczq, shadow, standing, **kwargs):
    calls: list = []

    def record(snapshot, **kw):
        calls.append((snapshot, kw))
        failure = kwargs.get("fail_first")
        if failure and len(calls) == 1:
            raise ValueError(failure)
        return _Recorded()

    result = run_nightly(
        day=DAY,
        jczq_dir=jczq,
        shadow_db=shadow,
        standing_path=standing,
        reports_dir=tmp_path / "reports",
        tickets_dir=tmp_path / "tickets",
        now=kwargs.get("now", lambda: NOW),
        dry_run=kwargs.get("dry_run", False),
        record_fn=record,
        owner_fn=lambda _db: kwargs.get("owner", "op:jun"),
        shard_fn=lambda _db, _world: [{"template": "pass-2-1", "status": "complete"}],
        engine_fn=lambda _db: None,
        sleep=lambda _seconds: None,
    )
    return result, calls


def test_recorded_night_writes_report_with_comparison_material(tmp_path):
    jczq, shadow, standing = _setup(tmp_path)
    result, calls = _run(tmp_path, jczq, shadow, standing)
    assert result.status == "recorded" and result.exit_code == 0
    snapshot, kw = calls[0]
    assert kw["approval"]["standing_approval"]["id"] == "standing-test"
    assert any(r.kind == "approval" for r in snapshot.references)
    report = json.loads((tmp_path / "reports" / f"{DAY}.json").read_text(encoding="utf-8"))
    assert report["status"] == "recorded" and report["world_id"] == "discovery-world-test"
    assert set(report["offer_book"]) == {"周三001", "周三002", "周三003"}
    assert report["decision_rule_best"] is None or report["decision_rule_best"]["notes"] <= 4
    assert "band_best" in report and report["shards"][0]["template"] == "pass-2-1"
    snap_path = Path(report["ticket_snapshot_path"])
    assert snap_path.exists() and report["ticket_snapshot"]["day"] == DAY
    expected_left = (datetime(2026, 10, 31).date() - NOW.date()).days
    assert report["standing_approval"]["days_left"] == expected_left


def test_second_run_same_day_is_skipped(tmp_path):
    jczq, shadow, standing = _setup(tmp_path)
    _run(tmp_path, jczq, shadow, standing)
    again, calls = _run(tmp_path, jczq, shadow, standing)
    assert again.status == "skipped" and again.reason == "already_recorded" and not calls
    assert again.exit_code == 0


def test_named_skips_do_not_record(tmp_path):
    jczq, shadow, standing = _setup(tmp_path)
    late, calls = _run(
        tmp_path, jczq, shadow, standing, now=lambda: datetime(2026, 9, 24, 3, 0, tzinfo=BJ)
    )
    assert late.status == "skipped" and late.reason == "outside_window" and not calls
    other, calls = _run(tmp_path, jczq, shadow, standing, owner="op:else")
    assert other.reason == "owner_mismatch" and not calls


def test_board_too_small_is_skipped(tmp_path):
    jczq, shadow, standing = _setup(tmp_path)
    board = jczq / "daily" / DAY / "jczq-legs-base.json"
    doc = json.loads(board.read_text(encoding="utf-8"))
    for leg in doc["legs"].values():
        leg["kickoff_bj"] = f"{DAY}T19:00:00+08:00"
    board.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    result, calls = _run(tmp_path, jczq, shadow, standing)
    assert result.status == "skipped" and result.reason == "board_too_small" and not calls


def test_protected_change_retries_once_then_records(tmp_path):
    jczq, shadow, standing = _setup(tmp_path)
    result, calls = _run(
        tmp_path, jczq, shadow, standing,
        fail_first="protected source changed during shadow recording; sealing blocked",
    )
    assert result.status == "recorded" and len(calls) == 2


def test_dry_run_writes_nothing(tmp_path):
    jczq, shadow, standing = _setup(tmp_path)
    result, calls = _run(tmp_path, jczq, shadow, standing, dry_run=True)
    assert result.status == "dry_run" and not calls
    assert result.payload["offers"] == ["周三001", "周三002", "周三003"]
    assert not (tmp_path / "reports").exists() and not (tmp_path / "tickets").exists()


def test_missing_shadow_store_is_an_infrastructure_failure(tmp_path):
    jczq, shadow, standing = _setup(tmp_path)
    shadow.unlink()
    result, _calls = _run(tmp_path, jczq, shadow, standing)
    assert result.status == "failed" and result.exit_code == 1
