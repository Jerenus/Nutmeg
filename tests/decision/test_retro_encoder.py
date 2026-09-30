import json
from pathlib import Path

from nutmeg.decision.retro_encoder import (
    board_brier,
    encode_jczq_day,
    encode_zucai_issue,
    results_for_board,
)

DAY = "2026-09-28"


def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False) if not isinstance(doc, str) else doc,
                    encoding="utf-8")


def _fixture(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    _write(data / "daily" / "2026-09-29" / "results-90.json", {
        "周一004": {"outcome_90": "0", "goals_h": 1, "goals_a": 4},
        "周一007": {"outcome_90": "3", "goals_h": 3, "goals_a": 1},
    })
    _write(data / "jczq" / "daily" / DAY / "reads.json", [
        {"note": "[周一004|土耳其-意大利|deep_research] …", "judgment_tier": "deep_research",
         "prior": {"home": 0.357, "draw": 0.270, "away": 0.373},
         "belief": {"home": 0.377, "draw": 0.280, "away": 0.343}},
        {"note": "[周一007|瑞典-波兰|deep_research] …", "judgment_tier": "deep_research",
         "prior": {"home": 0.447, "draw": 0.261, "away": 0.292},
         "belief": {"home": 0.447, "draw": 0.261, "away": 0.292}},
    ])
    _write(data / "jczq" / "daily" / DAY / "overrides.jsonl", json.dumps({
        "research": "research-周一004.json",
        "research_belief": {"home": 0.386, "draw": 0.271, "away": 0.342},
    }) + "\n")
    _write(data / "betslips.jsonl", "\n".join(json.dumps(row) for row in [
        {"slip_id": "J4", "channel": "jczq", "placed_at": DAY, "multiplier": 25,
         "combo_sizes": [2], "purchased": True,
         "legs": [{"key": "周一004", "market": "had", "selections": ["home"], "odds": [2.58]},
                  {"key": "周一007", "market": "had", "selections": ["home"], "odds": [1.82]}]},
        {"slip_id": "J9", "channel": "jczq", "placed_at": DAY, "multiplier": 10,
         "combo_sizes": [2], "purchased": True,
         "legs": [{"key": "周一007", "market": "had", "selections": ["home"], "odds": [1.82]},
                  {"key": "周一009", "market": "had", "selections": ["home"], "odds": [1.5]}]},
        {"slip_id": "T", "channel": "jczq", "placed_at": DAY, "multiplier": 1,
         "combo_sizes": [2], "purchased": False, "legs": []},
    ]) + "\n")
    _write(data / "scoreboard.json", {
        "tickets": {f"jczq-{DAY}": {"key": "人写的判断，不许被覆盖", "stake": 999}},
        "balance_ledger": {}, "updated_at": "old",
    })
    return data


def test_encode_jczq_day_writes_facts_and_keeps_human_fields(tmp_path: Path):
    data = _fixture(tmp_path)
    summary = encode_jczq_day(data, DAY, now="2026-09-29T09:45:00+08:00")
    assert summary["slips"] == 2 and summary["n_matches"] == 2
    sb = json.loads((data / "scoreboard.json").read_text(encoding="utf-8"))
    ticket = sb["tickets"][f"jczq-{DAY}"]
    assert ticket["key"] == "人写的判断，不许被覆盖"
    assert ticket["draw"] == "0 3" and ticket["stake"] == 50 + 20
    by_id = {row["id"]: row for row in ticket["slips"]}
    assert by_id["J4"]["dead_legs"] == ["周一004"] and by_id["J4"]["payout"] == 0
    assert by_id["J9"]["pending_legs"] == ["周一009"] and by_id["J9"]["payout"] is None
    assert ticket["payout"] == 0 and ticket["net"] == -50          # 未结票不进净值
    ledger = sb["balance_ledger"][f"jczq-{DAY}"]
    assert ledger["n_matches"] == 2 and ledger["n_deep"] == 2 and ledger["n_moved_final"] == 1
    assert ledger["market_brier"] < ledger["final_brier"] < ledger["research_brier"]
    assert "per_match" not in ledger and sb["updated_at"] == "2026-09-29T09:45:00+08:00"
    again = encode_jczq_day(data, DAY, now="later")
    assert again == summary | {}  # 幂等：同输入同事实
    assert json.loads((data / "scoreboard.json").read_text(encoding="utf-8"))["tickets"][
        f"jczq-{DAY}"]["key"] == "人写的判断，不许被覆盖"


def test_encode_returns_none_without_results_and_falls_back_to_jc_results(tmp_path: Path):
    data = _fixture(tmp_path)
    (data / "daily" / "2026-09-29" / "results-90.json").unlink()
    assert results_for_board(data, DAY) is None and encode_jczq_day(data, DAY) is None
    _write(data / "jczq" / "jc-results.json",
           {DAY: {"周一004": {"ft_home": 1, "ft_away": 4},
                  "周一007": {"ft_home": 3, "ft_away": 1}}})
    assert results_for_board(data, DAY) == {
        "周一004": {"outcome_90": "0", "goals_h": 1, "goals_a": 4},
        "周一007": {"outcome_90": "3", "goals_h": 3, "goals_a": 1},
    }


def test_board_brier_uses_the_research_original_when_an_override_exists(tmp_path: Path):
    data = _fixture(tmp_path)
    out = board_brier(data, DAY, results_for_board(data, DAY))
    m4 = next(m for m in out["per_match"] if m["code"] == "周一004")
    assert m4["research"] != m4["final"] and m4["moved"] is True and m4["outcome"] == "0"
    m7 = next(m for m in out["per_match"] if m["code"] == "周一007")
    assert m7["research"] == m7["final"] == m7["market"] and m7["moved"] is False


def test_encode_zucai_issue_reads_the_official_draw_and_prescription(tmp_path: Path):
    data = tmp_path / "data"
    _write(data / "zucai" / "official-results.json", {"26134": "0 1 0 1 0 3 0 1 0 0 3 3 3 0"})
    _write(data / "zucai" / "26134-judgment-v1.json",
           {"1": {"action": "10"}, "2": {"action": "0"}, "3": {"action": "31"}})
    faces = {"1": "310", "2": "310", "3": "310", "4": "310", "8": "31",
             "9": "0", "11": "3", "12": "3", "13": "3"}
    sel = {"3": ["home"], "1": ["draw"], "0": ["away"], "31": ["home", "draw"],
           "310": ["home", "draw", "away"]}
    _write(data / "betslips.jsonl", json.dumps({
        "slip_id": "26134-R9-324", "channel": "renjiu", "placed_at": "2026-09-28",
        "issue": "26134", "purchased": True, "faces": faces,
        "legs": [{"key": k, "market": "had", "selections": sel[f]} for k, f in faces.items()],
    }) + "\n")
    _write(data / "scoreboard.json", {"tickets": {"26134": {"key": "人写"}}})
    summary = encode_zucai_issue(data, "26134", prize_per_note=217.0, now="t")
    assert summary["prescription"] == "1/3"        # 场2 处方 0 开平 ✗，场3 处方 31 开客 ✗
    sb = json.loads((data / "scoreboard.json").read_text(encoding="utf-8"))
    ticket = sb["tickets"]["26134"]
    assert ticket["key"] == "人写" and ticket["draw"].startswith("0 1 0 1")
    assert ticket["slips"][0]["payout"] == 217.0 and ticket["net"] == 217.0 - 324
    assert encode_zucai_issue(data, "26135") is None
