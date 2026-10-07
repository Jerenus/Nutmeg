import json
from datetime import datetime

from nutmeg.decision.crowd_clues import (
    acted,
    latest_clues,
    load_registry,
    read_rows,
    render_map,
    scan,
    settle,
    ticket_faces,
)
from nutmeg.decision.crowd_source import fetch_issue
from tests.decision.crowd_fixtures import zg_doc

DOCS = {"CR1": {"label_cn": "全国人群多买平局", "trigger": {"field": "face", "op": "==", "v": "1"},
                "crowd_bias": "over"}}


def _board(zdir, at="2026-10-08T09:00:00+08:00"):
    fetch_issue(zdir, "26136", fetcher=lambda url: zg_doc(), now=datetime.fromisoformat(at))


def test_scan_is_idempotent_per_snapshot_and_marks_advisory(tmp_path):
    _board(tmp_path)
    first = scan(tmp_path, "26136", docs=DOCS, deployed=set())
    assert len(first) == 14 and all(c["advisory"] and c["role"] == "fade" for c in first)
    assert scan(tmp_path, "26136", docs=DOCS, deployed=set()) == []
    _board(tmp_path, "2026-10-08T14:00:00+08:00")
    second = scan(tmp_path, "26136", docs=DOCS, deployed={"CR1"})
    assert len(second) == 14 and not any(c["advisory"] for c in second)
    latest = latest_clues(read_rows(tmp_path, "26136"))
    assert {c["snapshot_at"] for c in latest} == {"2026-10-08T14:00:00+08:00"}


def test_latest_clues_follows_last_scan_even_when_empty(tmp_path):
    _board(tmp_path)
    scan(tmp_path, "26136", docs=DOCS, deployed=set())
    _board(tmp_path, "2026-10-08T14:00:00+08:00")
    scan(tmp_path, "26136", docs={}, deployed=set())
    assert latest_clues(read_rows(tmp_path, "26136")) == []


def test_ticket_faces_and_acted(tmp_path):
    slips = tmp_path / "betslips.jsonl"
    slips.write_text("\n".join(json.dumps(s) for s in [
        {"slip_id": "26136-R9-1", "purchased": True,
         "legs": [{"key": "7", "selections": ["home", "draw"]}]},
        {"slip_id": "26135-R9-1", "purchased": True,
         "legs": [{"key": "7", "selections": ["draw"]}]},
        {"slip_id": "26136-T9", "purchased": False,
         "legs": [{"key": "8", "selections": ["draw"]}]},
    ]), encoding="utf-8")
    tickets = ticket_faces(slips, "26136")
    assert tickets == [{7: {"3", "1"}}]
    fade = {"match_no": 7, "face": "1", "role": "fade"}
    assert acted(fade, tickets) == "ignored"
    assert acted(dict(fade, match_no=8), tickets) == "followed"
    assert acted(dict(fade, role="cover"), tickets) == "followed"
    assert acted(fade, []) is None


def test_settle_writes_outcomes_once(tmp_path):
    _board(tmp_path)
    scan(tmp_path, "26136", docs=DOCS, deployed=set())
    results = ["1", "3", "*"] + ["0"] * 11
    rows = settle(tmp_path, "26136", results=results, tickets=[])
    by_no = {r["match_no"]: r["outcome"] for r in rows}
    assert by_no[1] == "hit" and by_no[2] == "miss" and by_no[3] == "void"
    assert settle(tmp_path, "26136", results=results, tickets=[]) == []
    assert settle(tmp_path, "26136", results=None, tickets=[]) == []


def test_render_map_states(tmp_path):
    assert "本期无市场底座" in render_map("26136", [], {}, has_board=False, n_registered=1)
    _board(tmp_path)
    assert "均未触发" in render_map("26136", [], {}, has_board=True, n_registered=1)
    scan(tmp_path, "26136", docs=DOCS, deployed=set())
    text = render_map("26136", read_rows(tmp_path, "26136"),
                      {"CR1": "replay n=55 +4.10% CI[+0.50, +7.70]"},
                      has_board=True, n_registered=1)
    assert "## 人群地图" in text and "⚑" in text and "fade" in text and "replay n=55" in text


def test_load_registry_only_reads_cr_docs(tmp_path):
    (tmp_path / "CR1.json").write_text(json.dumps(DOCS["CR1"]), encoding="utf-8")
    (tmp_path / "F10.json").write_text("{}", encoding="utf-8")
    assert list(load_registry(tmp_path)) == ["CR1"]
