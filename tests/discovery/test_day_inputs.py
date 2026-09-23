import json
from pathlib import Path

import pytest

from nutmeg.discovery.day_inputs import (
    day_fingerprint,
    day_source_identity,
    read_structural_input_from_day,
)

DAY = "2026-09-23"


def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _day(tmp_path: Path, *, n: int = 3) -> Path:
    jczq = tmp_path / "jczq"
    d = jczq / "daily" / DAY
    codes = [f"周三{i:03d}" for i in range(1, n + 1)]
    legs = {}
    reads = []
    subs = []
    for i, code in enumerate(codes, start=1):
        legs[code] = {
            "match_id": f"m-{i}",
            "name": f"A{i}-B{i}",
            "kickoff_bj": f"{DAY}T19:30:00+08:00",
            "fair": {"home": 0.5, "draw": 0.28, "away": 0.22},
            "faces": "31",
            "stance": {"face": "3", "structure": "double", "cover": "1", "faces": "31"},
            "anchor_integrity": "pass",
            "precedents": [["3", "2026-01 某场 2-1", "alive"]],
        }
        reads.append(
            {
                "read_id": f"R-ai-jczq-{DAY}-{code}-had-1000",
                "match_id": f"m-{i}",
                "status": "draft",
                "made_at": f"{DAY}T10:00:00+08:00",
                "prior": {"home": 0.5, "draw": 0.28, "away": 0.22},
                "belief": {"home": 0.56, "draw": 0.26, "away": 0.18},
            }
        )
        subs.append(
            {
                "matchNumStr": code,
                "matchId": 1000 + i,
                "had": {
                    "h": "1.95",
                    "d": "2.90",
                    "a": "3.68",
                    "updateDate": DAY,
                    "updateTime": "08:00:00",
                },
            }
        )
    _write(d / "jczq-legs-base.json", {"day": DAY, "legs": legs})
    _write(d / "reads.json", reads)
    _write(
        d / "sporttery_markets.json",
        {"matchInfoList": [{"businessDate": DAY, "subMatchList": subs}]},
    )
    return jczq


def test_snapshot_maps_board_reads_and_quotes(tmp_path: Path):
    jczq = _day(tmp_path)
    snap = read_structural_input_from_day(jczq, DAY, cutoff_at=f"{DAY}T12:00:00+08:00")
    ci = snap.candidate_input
    assert ci.lane == "jczq" and ci.ticket_kind == "jczq_pass"
    assert len(ci.offers) == 3 and ci.offers[0].official_match_no == "周三001"
    assert ci.offers[0].booked_decimal_odds_by_face and ci.offers[0].quote_ids_by_face
    assert {b.bundle_code for b in ci.offers[0].allowed_face_bundles} >= {"31"}
    assert snap.template_ids == ("pass-2-1", "pass-3-1")  # 3 场 → N=2..3
    kinds = {r.kind for r in snap.references}
    assert kinds == {"forecast", "prescription", "quote"}
    assert sum(1 for r in snap.references if r.kind == "forecast") == 3
    assert snap.business_date == DAY and snap.slate_revision_id.startswith(f"day:{DAY}:")
    assert snap.source_identity == day_source_identity(jczq, DAY)
    assert len(snap.audit_offers) == 3 and snap.audit_offers[0].anchor_integrity == "pass"
    assert snap.manifest_hash and len(snap.task_snapshot_hash) == 64


def test_templates_are_capped_and_matches_without_reads_are_skipped(tmp_path: Path):
    jczq = _day(tmp_path, n=7)
    reads = json.loads((jczq / "daily" / DAY / "reads.json").read_text(encoding="utf-8"))
    (jczq / "daily" / DAY / "reads.json").write_text(json.dumps(reads[:5]), encoding="utf-8")
    snap = read_structural_input_from_day(
        jczq, DAY, cutoff_at=f"{DAY}T12:00:00+08:00", max_templates=4
    )
    assert len(snap.candidate_input.offers) == 5
    assert snap.template_ids == ("pass-2-1", "pass-3-1", "pass-4-1", "pass-5-1")


def test_reference_after_cutoff_is_rejected(tmp_path: Path):
    jczq = _day(tmp_path)
    with pytest.raises(ValueError, match="cutoff"):
        read_structural_input_from_day(jczq, DAY, cutoff_at=f"{DAY}T07:00:00+08:00")


def test_fingerprint_changes_when_any_source_file_changes(tmp_path: Path):
    jczq = _day(tmp_path)
    before = day_fingerprint(jczq / "daily" / DAY)
    p = jczq / "daily" / DAY / "reads.json"
    p.write_text(p.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert day_fingerprint(jczq / "daily" / DAY) != before


def test_audit_offers_prescribe_bundle_singles_and_omission_with_a_named_rule(tmp_path: Path):
    jczq = _day(tmp_path)
    snap = read_structural_input_from_day(jczq, DAY, cutoff_at=f"{DAY}T12:00:00+08:00")
    offer = snap.audit_offers[0]
    expected = {frozenset("31"), frozenset(), frozenset("3"), frozenset("1")}
    assert set(offer.prescribed_face_bundles) == expected
    assert offer.rule_ids == ("stance",)
