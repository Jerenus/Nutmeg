import json

from nutmeg.decision.workbench import read_events


def test_backfill_writes_tree_plan_and_two_adjudications(tmp_path):
    import scripts.plan_backfill_26129 as backfill_module

    data_dir = tmp_path
    (data_dir / "zucai").mkdir()
    (data_dir / "jczq").mkdir()
    (data_dir / "zucai" / "26129-issue.json").write_text(
        json.dumps(
            {
                "issue_id": "26129",
                "matches": [{"match_no": 1, "kickoff_bj": "2026-09-19 00:30"}],
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "betslips.jsonl").write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {
                    "slip_id": "26129-RJ9",
                    "channel": "renjiu",
                    "issue": "26129",
                    "notes": 384,
                    "stake_yuan": 768,
                    "hit_probability": 0.161188,
                    "placed_at": "2026-09-18T20:00:00+08:00",
                    "scheme_no": None,
                },
                {
                    "slip_id": "26129-SFC",
                    "channel": "shengfucai",
                    "issue": "26129",
                    "notes": 128,
                    "stake_yuan": 256,
                    "hit_probability": 0.001271,
                    "placed_at": "2026-09-18T20:00:00+08:00",
                    "scheme_no": None,
                },
                {
                    "slip_id": "26129-JC-A4",
                    "channel": "jczq",
                    "stake_yuan": 40,
                    "placed_at": "2026-09-18T20:00:00+08:00",
                },
                {
                    "slip_id": "26129-JC-B3",
                    "channel": "jczq",
                    "stake_yuan": 100,
                    "placed_at": "2026-09-18T20:00:00+08:00",
                },
                {
                    "slip_id": "26128-JC-OLD",
                    "channel": "jczq",
                    "stake_yuan": 600,
                    "placed_at": "2026-09-17T20:00:00+08:00",
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    report = backfill_module.backfill(data_dir=data_dir)
    events = [
        event
        for event in read_events(data_dir / "jczq", "2026-09-19")
        if event["kind"] == "candidate"
    ]
    versions = [event["payload"]["version"] for event in events]
    assert versions[:4] == ["SFC-B", "SFC-C", "SFC-D", "SFC-E"]
    parents = {
        event["payload"]["version"]: event["payload"]["parent_version"]
        for event in events
    }
    assert parents["SFC-C"] == "SFC-B" and parents["SFC-E"] == "SFC-D"
    assert parents["SFC-B"] is None
    assert report["plan"]["cap_source"] == "override"
    assert report["plan"]["caps"]["renjiu"] == 1000
    assert report["adjudications"] == [
        "override-renjiu-1000-26129",
        "standing-renjiu-1200",
    ]
    assert report["plan"]["chosen"][0]["slip_id"] == "26129-RJ9"
