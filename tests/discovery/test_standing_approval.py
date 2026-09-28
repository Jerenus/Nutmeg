import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nutmeg.discovery.standing_approval import (
    StandingApprovalError,
    approval_references,
    authorize_nightly,
    days_left,
    load_standing_approval,
)

BJ = timezone(timedelta(hours=8))
CUT = datetime(2026, 9, 29, 20, 30, tzinfo=BJ)


def _standing(tmp_path: Path, *, scope: dict | None = None, **changes) -> Path:
    doc = {
        "approval_id": "standing-test",
        "kind": "standing",
        "approved_by": "op:jun",
        "approved_at": "2026-09-28T22:00:00+08:00",
        "valid_from": "2026-09-28T22:00:00+08:00",
        "valid_until": "2026-10-31T23:59:59+08:00",
        "revoked_at": None,
        "scope_template": {
            "source_kind": "day",
            "jczq_dir": str(tmp_path / "jczq"),
            "shadow_db": str(tmp_path / "shadow.db"),
            "policy_revision_id": "structural-baseline-v1",
            "generation_request_pattern": "day:{business_date}",
            "cutoff_window_bjt": ["20:00", "23:59"],
            "max_worlds_per_business_date": 1,
        },
        "note": "test",
    }
    doc["scope_template"].update(scope or {})
    doc.update(changes)
    path = tmp_path / "standing.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _authorize(tmp_path, path, *, cutoff=CUT, owner="op:jun", recorded=(), day=None):
    return authorize_nightly(
        load_standing_approval(path),
        business_date=day or cutoff.astimezone(BJ).date().isoformat(),
        cutoff=cutoff,
        jczq_dir=tmp_path / "jczq",
        shadow_db=tmp_path / "shadow.db",
        baseline_owner=owner,
        recorded_dates=set(recorded),
    )


def test_valid_standing_approval_derives_the_single_run_shape(tmp_path):
    approval = _authorize(tmp_path, _standing(tmp_path))
    assert approval["approval_id"] == "standing-test:2026-09-29"
    assert approval["approved_by"] == "op:jun"
    assert approval["scope"] == {
        "source_db": str((tmp_path / "jczq" / "daily" / "2026-09-29").resolve()),
        "shadow_db": str((tmp_path / "shadow.db").resolve()),
        "generation_request_id": "day:2026-09-29",
        "cutoff_at": CUT.isoformat(),
        "policy_revision_id": "structural-baseline-v1",
    }
    sha = approval["standing_approval"]["sha256"]
    assert approval["standing_approval"]["id"] == "standing-test" and len(sha) == 64
    assert approval_references(approval) == (
        {
            "kind": "approval",
            "id": "standing-test",
            "source_revision": sha,
            "captured_at": "2026-09-28T22:00:00+08:00",
        },
    )
    assert approval_references({"approval_id": "single-run"}) == ()


@pytest.mark.parametrize(
    ("changes", "cutoff", "reason"),
    [
        ({"revoked_at": "2026-10-01T00:00:00+08:00"}, CUT, "approval_revoked"),
        ({}, datetime(2026, 11, 1, 20, 30, tzinfo=BJ), "approval_expired"),
        ({"valid_from": "2026-09-30T00:00:00+08:00"}, CUT, "approval_not_yet_valid"),
        ({"approved_at": "2026-09-30T00:00:00+08:00"}, CUT, "approval_not_yet_valid"),
        ({}, datetime(2026, 9, 29, 12, 0, tzinfo=BJ), "outside_window"),
    ],
)
def test_standing_approval_refuses_with_a_named_reason(tmp_path, changes, cutoff, reason):
    with pytest.raises(StandingApprovalError) as err:
        _authorize(tmp_path, _standing(tmp_path, **changes), cutoff=cutoff)
    assert err.value.reason == reason


def test_scope_owner_business_date_and_one_world_per_day(tmp_path):
    path = _standing(tmp_path)
    cases = [
        ({"owner": "op:someone"}, "owner_mismatch"),
        ({"owner": None}, "owner_mismatch"),
        ({"recorded": ("2026-09-29",)}, "already_recorded"),
        ({"day": "2026-09-28"}, "outside_window"),
    ]
    for kwargs, reason in cases:
        with pytest.raises(StandingApprovalError) as err:
            _authorize(tmp_path, path, **kwargs)
        assert err.value.reason == reason
    other = _standing(tmp_path, scope={"shadow_db": str(tmp_path / "other.db")})
    with pytest.raises(StandingApprovalError) as err:
        _authorize(tmp_path, other)
    assert err.value.reason == "scope_mismatch"


def test_missing_or_malformed_file_is_a_named_reason(tmp_path):
    with pytest.raises(StandingApprovalError) as err:
        load_standing_approval(tmp_path / "nope.json")
    assert err.value.reason == "approval_missing"
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(StandingApprovalError) as err:
        load_standing_approval(bad)
    assert err.value.reason == "approval_unreadable"
    single = tmp_path / "single.json"
    single.write_text(json.dumps({"approval_id": "x", "kind": "single"}), encoding="utf-8")
    with pytest.raises(StandingApprovalError) as err:
        load_standing_approval(single)
    assert err.value.reason == "approval_unreadable"


def test_days_left_counts_beijing_calendar_days(tmp_path):
    standing = load_standing_approval(_standing(tmp_path))
    assert days_left(standing, datetime(2026, 10, 24, 21, 0, tzinfo=BJ)) == 7
    assert days_left(standing, datetime(2026, 10, 31, 23, 0, tzinfo=BJ)) == 0
