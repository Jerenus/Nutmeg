import json

from nutmeg.decision.pool import zucai_pool_entries


def _issue(zdir, issue="26133", deadline="2026-09-26 20:30"):
    zdir.mkdir(parents=True, exist_ok=True)
    (zdir / f"{issue}-issue.json").write_text(json.dumps({
        "issue_id": issue, "sale_deadline": deadline,
        "matches": [
            {"match_no": 1, "competition": "友谊赛", "home_team": "中国", "away_team": "新西兰",
             "kickoff_bj": "2026-09-27 19:35"},
            {"match_no": 2, "competition": "欧国联", "home_team": "斯洛文", "away_team": "苏格兰",
             "kickoff_bj": "2026-09-26 21:00"},
        ]}, ensure_ascii=False), encoding="utf-8")
    (zdir / f"{issue}-store-ids.json").write_text(json.dumps({
        "1": {"match_no": 1, "match_id": "z-1", "fair": {"home": 0.36, "draw": 0.28, "away": 0.36}},
        "2": {"match_no": 2, "match_id": "z-2", "fair": {"home": 0.38, "draw": 0.30, "away": 0.32}},
    }), encoding="utf-8")


def test_pool_lists_the_days_zucai_matches_that_are_not_on_the_jczq_board(tmp_path):
    zdir = tmp_path / "zucai"
    _issue(zdir)
    (zdir / "26133-channel-map.auto.json").write_text(json.dumps({"jczq-008": 2}),
                                                      encoding="utf-8")

    entries = zucai_pool_entries(day="2026-09-26", data_dir=tmp_path)

    assert [e["key"] for e in entries] == ["足彩26133-01"]
    entry = entries[0]
    assert entry["leg"]["match_id"] == "z-1"
    assert entry["leg"]["kickoff_bj"] == "2026-09-27T19:35:00+08:00"
    assert entry["leg"]["fair"] == {"home": 0.36, "draw": 0.28, "away": 0.36}
    assert entry["output"] == zdir / "26133-research-m1.json"
    assert entry["rejected"] == zdir / "26133-research-m1.rejected.json"


def test_pool_only_takes_the_issue_that_closes_that_day(tmp_path):
    zdir = tmp_path / "zucai"
    _issue(zdir, issue="26132", deadline="2026-09-24 19:05")

    assert zucai_pool_entries(day="2026-09-26", data_dir=tmp_path) == []


def test_pool_skips_an_issue_without_store_ids(tmp_path):
    zdir = tmp_path / "zucai"
    _issue(zdir)
    (zdir / "26133-store-ids.json").unlink()

    assert zucai_pool_entries(day="2026-09-26", data_dir=tmp_path) == []
