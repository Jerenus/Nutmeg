import json
from pathlib import Path

import pytest

from nutmeg.discovery.day_inputs import (
    DayBoardTooSmall,
    day_fingerprint,
    day_source_identity,
    day_tickets,
    read_structural_input_from_day,
    tickets_digest,
)

DAY = "2026-09-23"
NEXT_DAY = "2026-09-24"


def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _day(
    tmp_path: Path,
    *,
    n: int = 3,
    day: str = DAY,
    made_at: str | None = None,
    quote_date: str | None = None,
    quote_time: str = "08:00:00",
    kickoff: str | None = None,
) -> Path:
    """Build `<tmp>/jczq/daily/<day>/` with reads made at 10:00+08 and quotes at 08:00+08.

    `day`, `made_at`, `quote_date` and `quote_time` let callers move the fixture to
    another business day (the CLI test uses today's date so its wall-clock checks pass).
    """
    from datetime import date as _date
    from datetime import timedelta as _timedelta

    jczq = tmp_path / "jczq"
    d = jczq / "daily" / day
    made_at = made_at or f"{day}T10:00:00+08:00"
    next_day = (_date.fromisoformat(day) + _timedelta(days=1)).isoformat()
    kickoff = kickoff or f"{next_day}T02:45:00+08:00"
    quote_date = quote_date or day
    codes = [f"周三{i:03d}" for i in range(1, n + 1)]
    legs = {}
    reads = []
    subs = []
    for i, code in enumerate(codes, start=1):
        legs[code] = {
            "match_id": f"m-{i}",
            "name": f"A{i}-B{i}",
            "kickoff_bj": kickoff,
            "fair": {"home": 0.5, "draw": 0.28, "away": 0.22},
            "faces": "31",
            "stance": {"face": "3", "structure": "double", "cover": "1", "faces": "31"},
            "anchor_integrity": "pass",
            "precedents": [["3", "2026-01 某场 2-1", "alive"]],
        }
        reads.append(
            {
                "read_id": f"R-ai-jczq-{day}-{code}-had-1000",
                "match_id": f"m-{i}",
                "status": "draft",
                "made_at": made_at,
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
                    "updateDate": quote_date,
                    "updateTime": quote_time,
                },
            }
        )
    _write(d / "jczq-legs-base.json", {"day": day, "legs": legs})
    _write(d / "reads.json", reads)
    _write(
        d / "sporttery_markets.json",
        {"matchInfoList": [{"businessDate": day, "subMatchList": subs}]},
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
    assert kinds == {"forecast", "prescription", "quote", "ticket"}
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


def test_matches_kicked_off_by_cutoff_are_excluded_and_recorded(tmp_path: Path):
    jczq = _day(tmp_path, n=4)
    board_path = jczq / "daily" / DAY / "jczq-legs-base.json"
    board = json.loads(board_path.read_text(encoding="utf-8"))
    board["legs"]["周三001"]["kickoff_bj"] = f"{DAY}T11:00:00+08:00"
    board_path.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    snap = read_structural_input_from_day(jczq, DAY, cutoff_at=f"{DAY}T12:00:00+08:00")
    codes = [offer.official_match_no for offer in snap.candidate_input.offers]
    assert codes == ["周三002", "周三003", "周三004"]
    excluded = [r for r in snap.references if r.kind == "excluded_started"]
    assert [(r.id, r.captured_at) for r in excluded] == [("周三001", f"{DAY}T11:00:00+08:00")]


def test_kickoff_falls_back_to_sporttery_time_and_unknown_is_excluded(tmp_path: Path):
    jczq = _day(tmp_path, n=4)
    d = jczq / "daily" / DAY
    board = json.loads((d / "jczq-legs-base.json").read_text(encoding="utf-8"))
    for leg in board["legs"].values():
        leg.pop("kickoff_bj")
    (d / "jczq-legs-base.json").write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    markets = json.loads((d / "sporttery_markets.json").read_text(encoding="utf-8"))
    subs = markets["matchInfoList"][0]["subMatchList"]
    for sub, clock in zip(subs[:3], ("11:30:00", "20:00:00", "21:00:00"), strict=True):
        sub["matchDate"], sub["matchTime"] = DAY, clock
    (d / "sporttery_markets.json").write_text(
        json.dumps(markets, ensure_ascii=False), encoding="utf-8"
    )
    snap = read_structural_input_from_day(jczq, DAY, cutoff_at=f"{DAY}T12:00:00+08:00")
    assert [o.official_match_no for o in snap.candidate_input.offers] == ["周三002", "周三003"]
    excluded = {r.id: r.source_revision for r in snap.references if r.kind == "excluded_started"}
    assert excluded == {"周三001": f"kickoff:{DAY}T11:30:00+08:00", "周三004": "kickoff:unknown"}


def test_fewer_than_two_unstarted_matches_is_a_named_skip(tmp_path: Path):
    jczq = _day(tmp_path, n=3)
    with pytest.raises(DayBoardTooSmall):
        read_structural_input_from_day(jczq, DAY, cutoff_at=f"{NEXT_DAY}T03:00:00+08:00")


CUT = f"{DAY}T12:00:00+08:00"


def test_ticket_reference_hashes_legs_file_and_same_day_jczq_slips(tmp_path: Path):
    jczq = _day(tmp_path)
    d = jczq / "daily" / DAY
    empty = read_structural_input_from_day(jczq, DAY, cutoff_at=CUT)
    (d / "legs.json").write_text("[]", encoding="utf-8")
    (tmp_path / "betslips.jsonl").write_text(
        json.dumps({"slip_id": "X", "channel": "jczq", "placed_at": DAY}) + "\n"
        + json.dumps({"slip_id": "Y", "channel": "jczq", "placed_at": "2026-09-22"}) + "\n"
        + json.dumps({"slip_id": "Z", "channel": "renjiu", "placed_at": DAY}) + "\n",
        encoding="utf-8",
    )
    snap = read_structural_input_from_day(jczq, DAY, cutoff_at=CUT)
    ref = next(r for r in snap.references if r.kind == "ticket")
    assert ref.id == f"{DAY}:tickets" and ref.captured_at == CUT
    assert ref.source_revision == tickets_digest(day_tickets(d))
    before = next(r for r in empty.references if r.kind == "ticket").source_revision
    assert ref.source_revision != before
    tickets = day_tickets(d)
    assert tickets["legs_json"] == [] and [s["slip_id"] for s in tickets["betslips"]] == ["X"]


def test_fingerprint_moves_with_same_day_jczq_slips_only(tmp_path: Path):
    jczq = _day(tmp_path)
    d = jczq / "daily" / DAY
    book = tmp_path / "betslips.jsonl"
    book.write_text(
        json.dumps({"slip_id": "Y", "channel": "jczq", "placed_at": "2026-09-22"}) + "\n",
        encoding="utf-8",
    )
    before = day_fingerprint(d)
    with book.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"slip_id": "W", "channel": "jczq", "placed_at": "2026-09-21"}) + "\n")
    assert day_fingerprint(d) == before
    with book.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"slip_id": "X", "channel": "jczq", "placed_at": DAY}) + "\n")
    assert day_fingerprint(d) != before


def test_extra_references_enter_the_manifest(tmp_path: Path):
    jczq = _day(tmp_path)
    extra = (
        {"kind": "approval", "id": "standing-x", "source_revision": "abc",
         "captured_at": f"{DAY}T09:00:00+08:00"},
    )
    with_ref = read_structural_input_from_day(jczq, DAY, cutoff_at=CUT, extra_references=extra)
    plain = read_structural_input_from_day(jczq, DAY, cutoff_at=CUT)
    assert any(r.kind == "approval" and r.id == "standing-x" for r in with_ref.references)
    assert with_ref.manifest_hash != plain.manifest_hash
