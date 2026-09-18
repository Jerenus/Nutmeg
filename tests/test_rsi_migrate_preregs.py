import json
from pathlib import Path

from nutmeg.decision.rsi_prereg import load_registry_doc

REG = Path("experiments/registry")


def test_all_five_registry_docs_load_and_keep_their_original_registration_dates():
    docs = {p.stem: load_registry_doc(p) for p in sorted(REG.glob("*.json"))}
    assert set(docs) == {"F1c", "F2", "F3", "F4", "F5"}
    assert docs["F2"]["registered_at"] == "2026-09-14"
    assert docs["F1c"]["registered_at"] == "2026-09-14"
    assert docs["F4"]["registered_at"] == "2026-09-18"
    assert docs["F5"]["registered_at"] == "2026-09-18"
    # 在跑的窗口不重新索引（U9-②）
    assert docs["F2"]["window"] == {"issue_from": "26126", "issue_to": "26137"}
    assert docs["F1c"]["window"] == {"issue_from": "26129", "issue_to": "26140"}
    # 每份都指回旧文件
    for d in docs.values():
        assert Path(d["source_doc"]).exists(), d["source_doc"]
    # F1c/F2 各带一条按日义务；F4/F5 是观察档、无采集义务
    assert [x["name"] for x in docs["F2"]["duties"]] == ["f2-observation"]
    assert [x["name"] for x in docs["F1c"]["duties"]] == ["dispersion-observation"]
    assert docs["F4"]["tier"] == "observation" and not docs["F4"].get("duties")


def test_migration_script_backfills_observations_and_marks_f1c_gaps(tmp_path, monkeypatch):
    import scripts.rsi_migrate_preregs as mig

    d = tmp_path / "data"
    (d / "zucai").mkdir(parents=True)
    for issue, ko in (("26126", "2026-09-16T02:00:00"), ("26127", "2026-09-17T02:00:00"),
                      ("26128", "2026-09-18T02:00:00"), ("26129", "2026-09-19T00:30:00")):
        (d / "zucai" / f"{issue}-issue.json").write_text(json.dumps(
            {"issue_id": issue, "matches": [{"match_no": 1, "kickoff_bj": ko}]}), encoding="utf-8")
    row = {"no": "1", "bucket": "向主 ≥+0.5", "fair": {"home": .5, "draw": .25, "away": .25},
           "moved_share": 1, "actual": "home"}
    ledger = {"issues": {i: {"prospective": True, "captured_at": f"2026-09-{15 + k}T19:30:05",
                             "rows": [row]}
                         for k, i in enumerate(("26126", "26127", "26128"))}}
    (tmp_path / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    (tmp_path / "t7-dispersion.json").write_text(json.dumps({"26129": {"1": {}}}), encoding="utf-8")
    report = mig.migrate(data_dir=d, registry_dir=REG, f2_ledger=tmp_path / "ledger.json",
                         dispersion_file=tmp_path / "t7-dispersion.json",
                         now="2026-09-18T20:00:00+08:00")
    assert report["registered"] == ["F1c", "F2", "F3", "F4", "F5"]
    assert report["F2"]["observations"] == 3
    assert report["F1c"]["observations"] == 1
    # 26125 没有 issue.json 时不造数据
    assert report["F1c"]["gaps"] == ["2026-09-16", "2026-09-17", "2026-09-18"]


def test_migration_ingests_an_ungraded_prospective_f2_observation_file(tmp_path):
    """26129 的 F2 观察单已在开球前落盘但尚未 grade 进 ledger——不该被记成 gap。"""
    import scripts.rsi_migrate_preregs as mig

    d = tmp_path / "data"
    (d / "zucai").mkdir(parents=True)
    (d / "zucai" / "26129-issue.json").write_text(json.dumps(
        {"issue_id": "26129", "matches": [{"match_no": 1, "kickoff_bj": "2026-09-19 00:30"}]}),
        encoding="utf-8")
    (d / "zucai" / "26129-f2-observation.json").write_text(json.dumps(
        {"issue": "26129", "captured_at": "2026-09-18T19:22:02", "prospective": True,
         "earliest_kickoff": "2026-09-19T00:30:00", "observations": {"1": {}, "2": {}}}),
        encoding="utf-8")
    (tmp_path / "ledger.json").write_text(json.dumps({"issues": {}}), encoding="utf-8")
    (tmp_path / "t7-dispersion.json").write_text(json.dumps({}), encoding="utf-8")
    report = mig.migrate(data_dir=d, registry_dir=REG, f2_ledger=tmp_path / "ledger.json",
                         dispersion_file=tmp_path / "t7-dispersion.json",
                         now="2026-09-19T12:00:00+08:00")
    assert report["F2"] == {"observations": 1, "gaps": []}
    assert report["F1c"]["gaps"] == ["2026-09-19"]
