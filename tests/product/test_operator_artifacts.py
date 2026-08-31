import json
from pathlib import Path

import pytest

from nutmeg.product.operator_artifacts import OperatorArtifactError, ZucaiArtifactRepository
from tests.product.operator_fixtures import write_26112_bundle


def _replace_json(path: Path, key: str, value: object) -> None:
    payload = json.loads(path.read_text("utf-8"))
    payload[key] = value
    path.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")


def _replace_nested_fair(path: Path, home: float) -> None:
    payload = json.loads(path.read_text("utf-8"))
    payload["legs"]["1"]["fair"]["home"] = home
    path.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")


def test_discovers_and_loads_strict_26112_bundle(tmp_path: Path) -> None:
    root = write_26112_bundle(tmp_path / "zucai")
    repository = ZucaiArtifactRepository(root)

    assert repository.discover_issues() == ["26112"]
    bundle = repository.load("26112")
    assert bundle.issue.issue_id == "26112"
    assert bundle.prep.records["1"].name == "水晶宫-曼彻斯特城"
    assert bundle.prep.captured_at.isoformat() == "2026-08-28T14:00:07+08:00"
    assert bundle.fallback_deadline().isoformat() == "2026-08-29T03:00:00+08:00"
    assert bundle.candidates[0].candidate_id == "R432"
    assert bundle.candidates[0].legs["1"].faces == "310"
    assert [item.candidate_id for item in bundle.candidates] == ["R432"]
    assert bundle.match_record(1) is bundle.prep.records["1"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda root: (root / "26112-rx.json").write_text("{", "utf-8"), "invalid"),
        (
            lambda root: _replace_json(root / "26112-rx.json", "issue", "26113"),
            "binding mismatch",
        ),
        (
            lambda root: _replace_json(root / "26112-issue.json", "unexpected", True),
            "invalid",
        ),
        (
            lambda root: _replace_nested_fair(root / "26112-legs-R432.json", 0.4),
            "sum to 1",
        ),
    ],
)
def test_rejects_malformed_or_misbound_bundle(tmp_path, mutation, message) -> None:
    root = write_26112_bundle(tmp_path / "zucai")
    mutation(root)
    with pytest.raises(OperatorArtifactError, match=message):
        ZucaiArtifactRepository(root).load("26112")


def test_rejects_issue_path_traversal(tmp_path: Path) -> None:
    repository = ZucaiArtifactRepository(write_26112_bundle(tmp_path / "zucai"))
    with pytest.raises(OperatorArtifactError, match="five digits"):
        repository.load("../26112")


def test_night_snapshot_is_summary_only(tmp_path: Path) -> None:
    root = write_26112_bundle(tmp_path / "zucai")
    (root / "26112-night-2026-08-29-af.json").write_text(
        json.dumps(
            {
                "issue": "26112",
                "source": "API-Football 90-minute fixture",
                "fetched_at": "2026-08-29T01:00:00+00:00",
                "results": {
                    "1": {
                        "code": "0",
                        "ft": "1-2",
                        "home": "水晶宫",
                        "away": "曼彻斯特城",
                        "status": "FT",
                    }
                },
                "skipped": [],
            },
            ensure_ascii=False,
        ),
        "utf-8",
    )
    bundle = ZucaiArtifactRepository(root).load("26112")
    assert bundle.night_snapshots[-1].results["1"].code == "0"
    assert not hasattr(bundle.night_snapshots[-1], "prediction_grade")


def test_candidate_identity_comes_from_filename_and_collisions_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = write_26112_bundle(tmp_path / "zucai")
    original = root / "26112-legs-R432.json"
    duplicate = root / "26112-legs-r432.json"
    duplicate.write_text(original.read_text("utf-8"), "utf-8")

    repository = ZucaiArtifactRepository(root)
    monkeypatch.setattr(repository, "_artifact_paths", lambda: [original, duplicate])

    with pytest.raises(OperatorArtifactError, match="candidate identity collision"):
        repository.load("26112")


def test_rx_ticket_version_prose_does_not_create_candidate(tmp_path: Path) -> None:
    root = write_26112_bundle(tmp_path / "zucai")
    _replace_json(root / "26112-rx.json", "ticket_versions", {"V288": "prose only"})

    candidates = ZucaiArtifactRepository(root).load("26112").candidates
    assert [candidate.candidate_id for candidate in candidates] == ["R432"]


def test_rejects_source_candidate_id_override(tmp_path: Path) -> None:
    root = write_26112_bundle(tmp_path / "zucai")
    _replace_json(root / "26112-legs-R432.json", "candidate_id", "forged")

    with pytest.raises(OperatorArtifactError, match="candidate_id"):
        ZucaiArtifactRepository(root).load("26112")


def test_probability_boundary_allows_exact_one_point_zero_zero_one(tmp_path: Path) -> None:
    root = write_26112_bundle(tmp_path / "zucai")
    path = root / "26112-legs-R432.json"
    payload = json.loads(path.read_text("utf-8"))
    payload["legs"]["1"]["fair"] = {"home": 0.333, "draw": 0.333, "away": 0.335}
    path.write_text(json.dumps(payload), "utf-8")

    assert ZucaiArtifactRepository(root).load("26112").candidates[0].candidate_id == "R432"


def test_prep_allows_explicitly_missing_official_anchor(tmp_path: Path) -> None:
    root = write_26112_bundle(tmp_path / "zucai")
    path = root / "26112-prep-afternoon.json"
    payload = json.loads(path.read_text("utf-8"))
    record = payload["records"]["1"]
    record["sporttery_match_num"] = None
    record["sporttery_had_date"] = None
    record["hhad_cover"] = None
    path.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")

    parsed = ZucaiArtifactRepository(root).load("26112").prep.records["1"]
    assert parsed.sporttery_match_num is None
    assert parsed.hhad_cover is None
