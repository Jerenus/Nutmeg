"""判断唯一事实 P0：内核投影 == 文件；改文件即分歧；重建换版本号不算分歧。"""
import json
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.decision.jczq_reads import build_jczq_reads
from nutmeg.decision.judgment_projection import (
    PROJECTED,
    REPORT,
    compare,
    project_board,
    run_projection,
    summary_line,
)
from nutmeg.decision.ontology_adapter import run_decision_am_v2, run_decision_read_v2
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
from nutmeg.ontology.wiring import build_ontology_kernel

DAY = "2026-07-19"
SPORTTERY = {"matchInfoList": [{"businessDate": DAY, "subMatchList": [
    {"matchStatus": "Selling", "businessDate": DAY, "matchNumStr": "周日001",
     "matchNum": 7001, "matchId": 2040001, "matchDate": DAY, "matchTime": "23:30:00",
     "homeTeamAbbName": "哈马比", "awayTeamAbbName": "AIK", "leagueAbbName": "瑞典超",
     "had": {"h": "2.10", "d": "3.30", "a": "3.10"}}]}]}
BOLD = {"周日001": {"match_winner": {"odds": {"home": 2.05, "draw": 3.40, "away": 3.20}}}}


def _board(tmp_path: Path):
    data_dir = tmp_path / "data"
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    jczq_dir = data_dir / "jczq"
    day_dir = jczq_dir / "daily" / DAY
    day_dir.mkdir(parents=True)
    (day_dir / "sporttery_markets.json").write_text(json.dumps(SPORTTERY), encoding="utf-8")
    (day_dir / "bold_odds.json").write_text(json.dumps(BOLD), encoding="utf-8")
    run_decision_am_v2(DAY, jczq_dir, kernel=kernel, fetch=False)
    with OntologyUnitOfWork(kernel.engine) as uow:
        [match_id] = uow.identity.all_match_ids()
    (day_dir / "jczq-legs-base.json").write_text(json.dumps({"day": DAY, "legs": {
        "周日001": {"match_id": match_id, "name": "哈马比-AIK", "competition": "瑞典超",
                  "kickoff_bj": f"{DAY}T23:30:00+08:00",
                  "fair": {"home": 0.45, "draw": 0.28, "away": 0.27}, "hhad_line": None,
                  "judgment_tier": "price_only", "faces": "310"}}}, ensure_ascii=False),
        encoding="utf-8")
    return kernel, data_dir, day_dir, match_id


def test_projection_equals_the_file_right_after_submission(tmp_path: Path) -> None:
    kernel, data_dir, day_dir, _ = _board(tmp_path)
    reads = build_jczq_reads(day=DAY, jczq_dir=data_dir / "jczq", made_at=f"{DAY}T10:00:00+08:00")
    assert "摄取 1/1" in run_decision_read_v2(day_dir / "reads.json", day_dir, kernel=kernel)

    assert project_board(kernel, f"jczq:{DAY}") == reads
    out = run_projection(data_dir, day=DAY, kernel=kernel, at="2026-07-19T10:01:00+08:00")
    assert out["result"]["identical"] == 1 and out["result"]["mismatch"] == []
    assert out["line"].startswith("投影 1 条｜文件 1 条｜一致 1")
    assert json.loads((day_dir / PROJECTED).read_text(encoding="utf-8")) == reads
    report = json.loads((day_dir / REPORT).read_text(encoding="utf-8"))
    assert report["board_key"] == f"jczq:{DAY}" and report["identical"] == 1


def test_rebuilt_file_with_same_judgment_is_a_new_version_not_a_mismatch(tmp_path: Path):
    kernel, data_dir, day_dir, _ = _board(tmp_path)
    build_jczq_reads(day=DAY, jczq_dir=data_dir / "jczq", made_at=f"{DAY}T10:00:00+08:00")
    run_decision_read_v2(day_dir / "reads.json", day_dir, kernel=kernel)
    # 定时重建换了 read_id 后缀、判断没变、还没交本体
    build_jczq_reads(day=DAY, jczq_dir=data_dir / "jczq", made_at=f"{DAY}T11:00:00+08:00")

    result = run_projection(data_dir, day=DAY, kernel=kernel, write=False)["result"]

    assert result["identical"] == 0 and result["mismatch"] == []
    [row] = result["same_judgment_new_version"]
    assert row["kernel"].endswith("-1000") and row["file"].endswith("-1100")


def test_changed_belief_in_the_file_is_a_mismatch_and_started_reads_only_in_file(tmp_path):
    kernel, data_dir, day_dir, match_id = _board(tmp_path)
    build_jczq_reads(day=DAY, jczq_dir=data_dir / "jczq", made_at=f"{DAY}T10:00:00+08:00")
    run_decision_read_v2(day_dir / "reads.json", day_dir, kernel=kernel)
    reads = json.loads((day_dir / "reads.json").read_text(encoding="utf-8"))
    reads[0]["belief"] = {"home": 0.6, "draw": 0.2, "away": 0.2}
    reads.append({**reads[0], "match_id": "match-never-submitted", "code": "周日002",
                  "read_id": "R-x"})
    (day_dir / "reads.json").write_text(json.dumps(reads, ensure_ascii=False), encoding="utf-8")

    result = run_projection(data_dir, day=DAY, kernel=kernel, write=False)["result"]

    [row] = result["mismatch"]
    assert row["match_id"] == match_id and row["file"]["belief"]["home"] == 0.6
    assert result["only_in_file"] == ["match-never-submitted"]
    assert "分歧 1" in summary_line(result) and "仅文件 1" in summary_line(result)


def test_compare_skips_channel_mapped_matches() -> None:
    projected = [{"match_id": "z-2", "code": "2", "read_id": "k2", "belief": {}},
                 {"match_id": "z-1", "code": "1", "read_id": "k1", "belief": {}}]
    file_reads = [{"match_id": "z-1", "code": "1", "read_id": "k1", "belief": {}},
                  {"match_id": "z-9", "code": "9", "read_id": "f9", "belief": {}}]
    result = compare(projected, file_reads, skip_match_ids=["z-9"])
    assert result["identical"] == 1 and result["only_in_kernel"] == ["z-2"]
    assert result["only_in_file"] == [] and result["skipped_mapped"] == ["z-9"]


def test_materialize_overwrites_the_file_with_the_projection(tmp_path: Path) -> None:
    kernel, data_dir, day_dir, _ = _board(tmp_path)
    build_jczq_reads(day=DAY, jczq_dir=data_dir / "jczq", made_at=f"{DAY}T10:00:00+08:00")
    run_decision_read_v2(day_dir / "reads.json", day_dir, kernel=kernel)
    reads = json.loads((day_dir / "reads.json").read_text(encoding="utf-8"))
    reads[0]["belief"] = {"home": 0.9, "draw": 0.05, "away": 0.05}        # 文件被人改坏
    (day_dir / "reads.json").write_text(json.dumps(reads), encoding="utf-8")

    out = run_projection(data_dir, day=DAY, kernel=kernel, write=False, materialize=True)

    assert out["materialized"] is True and "已落盘为投影" in out["line"]
    restored = json.loads((day_dir / "reads.json").read_text(encoding="utf-8"))
    assert restored[0]["belief"]["home"] != 0.9 and restored == out["projected"]


def test_materialize_keeps_the_file_when_the_projection_is_empty(tmp_path: Path) -> None:
    kernel, data_dir, day_dir, _ = _board(tmp_path)
    reads = build_jczq_reads(day=DAY, jczq_dir=data_dir / "jczq", made_at=f"{DAY}T10:00:00+08:00")
    # 没交本体 → 投影为空 → 不覆盖、标 degraded
    out = run_projection(data_dir, day=DAY, kernel=kernel, write=False, materialize=True)
    assert out["materialized"] is False and out["degraded"] is True
    assert json.loads((day_dir / "reads.json").read_text(encoding="utf-8")) == reads
