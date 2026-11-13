import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.decision.workbench import read_events
from nutmeg.decision.zucai_draft import (
    build_draft,
    load_board,
    maxp_reference,
    prescription_point,
    render_draft,
)
from nutmeg.interfaces.cli import app

ISSUE = "26135"
SINGLE_B = {"home": 0.70, "draw": 0.18, "away": 0.12}
SINGLE_M = {"home": 0.65, "draw": 0.20, "away": 0.15}
DOUBLE_B = {"home": 0.45, "draw": 0.30, "away": 0.25}
DOUBLE_M = {"home": 0.42, "draw": 0.30, "away": 0.28}
ALIVE = {f: {"state": "alive"} for f in ("home", "draw", "away")}


def _legs(faces_by_no: dict[str, str]) -> dict:
    return {no: {"name": f"m{no}", "faces": fs,
                 "belief": SINGLE_B if len(fs) == 1 else DOUBLE_B,
                 "market": SINGLE_M if len(fs) == 1 else DOUBLE_M,
                 "confidence": 3, "raw": {}}
            for no, fs in faces_by_no.items()}


FOUR_SINGLES_TEN_DOUBLES = {str(i): ("3" if i <= 4 else "31") for i in range(1, 15)}


def _data(tmp_path: Path, faces=FOUR_SINGLES_TEN_DOUBLES, *, model: bool = True) -> Path:
    data = tmp_path / "data"
    zdir = data / "zucai"
    zdir.mkdir(parents=True)
    (data / "jczq").mkdir()
    legs = {}
    for no, fs in faces.items():
        legs[no] = {"name": f"m{no}", "faces": fs, "confidence": 3,
                    "prior": SINGLE_M if len(fs) == 1 else DOUBLE_M,
                    "fair": SINGLE_B if len(fs) == 1 else DOUBLE_B,
                    "face_status": ALIVE, "license_questions": {}, "anchor_integrity": "pass",
                    "crash_markers": [], "_d3": {}}
    (zdir / f"{ISSUE}-legs-base.json").write_text(json.dumps(
        {"issue": ISSUE, "prescription": dict(faces), "legs": legs}), encoding="utf-8")
    (zdir / f"{ISSUE}-judgment-v1.json").write_text(json.dumps(
        {no: {"action": fs} for no, fs in faces.items()}), encoding="utf-8")
    (zdir / f"{ISSUE}-issue.json").write_text(json.dumps({"issue_id": ISSUE, "matches": [
        {"match_no": int(no), "home_team": "H", "away_team": "A",
         "kickoff_bj": "2026-10-04T22:00:00+08:00"} for no in faces]}), encoding="utf-8")
    if model:
        (zdir / "prize-model.json").write_text(json.dumps({"channels": {
            "renjiu": {"n": 41, "a": -5.2547, "b": 1.0, "resid_sd": 0.62, "prize_median": 3774},
            "shengfucai": {"n": 38, "a": -1.6487, "b": 1.13, "resid_sd": 0.83,
                           "prize_median": 662992}}}), encoding="utf-8")
    return data


def test_prescription_point_only_drops_matches_when_it_fits() -> None:
    legs = _legs(FOUR_SINGLES_TEN_DOUBLES)
    pt = prescription_point(legs, channel="renjiu", cap_yuan=400)
    # 200 注帽：7 双 + 2 单 = 128 注，P = 0.75^7 × 0.70^2；8 双 1 单 = 256 注装不下
    assert pt["downgrades"] == [] and pt["notes"] == 128 and pt["stake_yuan"] == 256
    assert sorted(len(f) for f in pt["faces"].values()) == [1, 1] + [2] * 7
    assert all(pt["faces"][no] == legs[no]["faces"] for no in pt["faces"])
    assert len(pt["dropped"]) == 5 and abs(pt["p_all"] - 0.75 ** 7 * 0.70 ** 2) < 1e-6


def test_prescription_point_downgrades_lowest_face_only_when_nothing_fits() -> None:
    legs = _legs({str(i): "31" for i in range(1, 15)})
    pt = prescription_point(legs, channel="renjiu", cap_yuan=100)
    # 50 注帽：9 双 = 512 注 → 砍 4 个平面（0.30 是票内最低面）→ 32 注 ¥64
    assert len(pt["downgrades"]) == 4 and pt["notes"] == 32 and pt["stake_yuan"] == 64
    assert {s["dropped"] for s in pt["downgrades"]} == {"1"}
    assert all(s["to"] == "3" and s["p"] == 0.30 for s in pt["downgrades"])
    assert pt["dropped"] == [] or len(pt["dropped"]) == 5


def test_shengfucai_keeps_all_fourteen_and_downgrades_into_cap() -> None:
    legs = _legs(FOUR_SINGLES_TEN_DOUBLES)
    pt = prescription_point(legs, channel="shengfucai", cap_yuan=400)
    # 处方 2^10 = 1024 注 ¥2,048 → 砍 3 个平面 → 128 注 ¥256
    assert len(pt["faces"]) == 14 and pt["dropped"] == []
    assert len(pt["downgrades"]) == 3 and pt["stake_yuan"] == 256
    # 全降到单也只要 1 注 ¥2；帽 ¥1（0 注）才装不下
    assert prescription_point(legs, channel="shengfucai", cap_yuan=20)["stake_yuan"] == 16
    assert prescription_point(legs, channel="shengfucai", cap_yuan=1) is None


def test_load_board_prefers_prescription_then_faces_then_judgment(tmp_path: Path) -> None:
    data = _data(tmp_path)
    doc = json.loads((data / "zucai" / f"{ISSUE}-legs-base.json").read_text("utf-8"))
    doc["prescription"]["1"] = "10"
    del doc["legs"]["2"]["faces"]
    doc["prescription"].pop("2")
    (data / "zucai" / f"{ISSUE}-legs-base.json").write_text(json.dumps(doc), encoding="utf-8")
    legs = load_board(data, ISSUE)
    assert legs["1"]["faces"] == "10" and legs["2"]["faces"] == "3"   # judgment-v1 action 兜底
    assert legs["1"]["belief"] == SINGLE_B and legs["1"]["market"] == SINGLE_M
    ref = maxp_reference({no: leg["raw"] for no, leg in legs.items()}, channel="renjiu",
                         cap_yuan=400)
    assert ref and ref["stake_yuan"] <= 400 and len(ref["faces"]) == 9


def test_build_draft_writes_files_reviews_and_registers_candidates_once(tmp_path: Path) -> None:
    data = _data(tmp_path)
    doc = build_draft(data, ISSUE, cap_yuan=400)
    drop_c = [c for c in doc["candidates"] if c["label"] == "参考·丢光C档形"]
    white = [c for c in doc["candidates"] if c["label"] == "参考·白防线形"]
    labels = [(c["channel"], c["label"]) for c in doc["candidates"]
              if c not in drop_c and c not in white]
    assert [c["channel"] for c in white] == ["renjiu", "shengfucai"]   # 2026-11-08 两渠道都出
    assert labels == [("renjiu", "初稿"), ("renjiu", "刹车档"), ("renjiu", "参考·帽内max-P"),
                      ("shengfucai", "初稿"), ("shengfucai", "刹车档"),
                      ("shengfucai", "参考·帽内max-P")]
    # 丢光 C 档形（2026-10-25）：只出任九、帽内、A/B/b 全单 + D 全包，有则带审票
    for c in drop_c:
        assert c["channel"] == "renjiu" and c["stake_yuan"] <= 400 and len(c["faces"]) == 9
        assert all(len(fs) in (1, 2, 3) for fs in c["faces"].values())   # 双＝帽压包或 C 档补位
        assert "review" in c
    draft = doc["candidates"][0]
    assert draft["stake_yuan"] == 256 and draft["review"]["detail"]["basis"] == "model"
    assert draft["review"]["detail"]["premium"] > 1.0          # 判断偏向所选面 → 溢价 > 1
    assert draft["review"]["vetoed"] is False
    brake = doc["candidates"][1]
    assert brake["cap_yuan"] == 200 and brake["stake_yuan"] <= 200
    zdir = data / "zucai"
    assert (zdir / f"{ISSUE}-draft.json").exists() and (zdir / f"{ISSUE}-draft.md").exists()
    legs_draft = json.loads((zdir / f"{ISSUE}-legs-draft-renjiu.json").read_text("utf-8"))
    assert len(legs_draft["legs"]) == 9 and legs_draft["draft"]["hash"] == doc["hash"]
    assert len(json.loads((zdir / f"{ISSUE}-legs-draft-shengfucai.json")
                          .read_text("utf-8"))["legs"]) == 14
    events = [e for e in read_events(data / "jczq", "2026-10-04") if e.get("kind") == "candidate"]
    assert len(events) == 9 and all(      # +丢光C档形（只出任九）+白防线形（两渠道，11-08）
        e["payload"]["version"].startswith("draft:") for e in events)
    build_draft(data, ISSUE, cap_yuan=400)                      # 幂等：同 hash 不重复登记
    events = [e for e in read_events(data / "jczq", "2026-10-04") if e.get("kind") == "candidate"]
    assert len(events) == 9                      # 幂等：第二次 build 不再追加
    text = render_draft(doc)
    assert "# 足彩初稿 · 26135（帽 ¥400，规则：处方忠实）" in text
    assert "## 初稿·任九：¥256（128 注，帽 ¥400）" in text and "丢场：" in text
    assert "判断溢价" in text and "审票 ℹ️V1" in text and "只作对照" in text
    assert "降档 3 步" in text                                     # 胜负彩初稿


def test_draft_shares_naked_leg_with_registered_ticket_is_vetoed(tmp_path: Path) -> None:
    data = _data(tmp_path)
    faces_row = " ".join("3" if i <= 4 else "31" for i in range(1, 15))
    result = CliRunner().invoke(app, ["betslip", "register", "--slip-id", "J1", "--channel",
                                      "shengfucai", "--placed-at", "2026-10-04", "--faces",
                                      faces_row, "--issue", ISSUE, "--data-dir", str(data)])
    assert result.exit_code == 0, result.output
    assert "判断溢价" in result.output                             # legs-base fair 自动兜底
    doc = build_draft(data, ISSUE, cap_yuan=400, write=False)
    sfc_draft = next(c for c in doc["candidates"]
                     if c["channel"] == "shengfucai" and c["label"] == "初稿")
    assert sfc_draft["review"]["vetoed"] is True
    assert any(line.startswith("⛔V2") for line in sfc_draft["review"]["lines"])


def test_cli_draft_and_brief_include_the_draft(tmp_path: Path) -> None:
    data = _data(tmp_path)
    result = CliRunner().invoke(app, ["judgment", "draft", "--issue", ISSUE, "--cap", "200",
                                      "--data-dir", str(data)])
    assert result.exit_code == 0, result.output
    assert "足彩初稿 · 26135（帽 ¥200" in result.output and "## 刹车档·任九" in result.output
    brief = CliRunner().invoke(app, ["judgment", "brief", "--issue", ISSUE, "--data-dir",
                                     str(data), "--write"])
    assert brief.exit_code == 0, brief.output
    assert "初判与解读 · 足彩 26135" in brief.output and "# 足彩初稿 · 26135" in brief.output
    assert (data / "zucai" / f"{ISSUE}-judgment-brief.md").read_text("utf-8").count("初稿") >= 2
    missing = CliRunner().invoke(app, ["judgment", "draft", "--issue", "26999", "--data-dir",
                                       str(data)])
    assert missing.exit_code == 0 and "未出" in missing.output


def test_build_draft_adds_the_white_line_reference_for_both_channels(tmp_path: Path):
    """白防线形（2026-11-08 Jun 批）：全单起步，按一赔条件从低到高补双到帽满，只作并排。"""
    doc = build_draft(_data(tmp_path), ISSUE, write=False)
    refs = {c["channel"]: c for c in doc["candidates"] if c["label"] == "参考·白防线形"}
    assert set(refs) == {"renjiu", "shengfucai"}
    rj = refs["renjiu"]
    assert rj["rule"] == "white_line" and rj["alerts"] == []
    # 预算＝¥256（字典冷板默认价），不是 ¥800 帽：
    # 5–9 双 0.60 最低先补，再补 1、2（0.795），3、4 留单
    assert rj["cap_yuan"] == 256
    assert rj["faces"] == {"1": "31", "2": "31", "3": "3", "4": "3",
                           **{str(n): "31" for n in range(5, 10)}}
    assert rj["stake_yuan"] == 256 and rj["note"] == "帽满：线下 2 场留单（场 3、4）"
    assert "review" in rj
    assert "白防线形" in render_draft(doc)


def test_white_line_reference_follows_a_lower_precommit(tmp_path: Path):
    from nutmeg.decision.bankroll import write_precommit

    data = _data(tmp_path)
    write_precommit(data, ISSUE, slip_yuan=128, issue_yuan=128, now="2026-10-03T10:00:00+08:00")
    doc = build_draft(data, ISSUE, write=False)
    rj = next(c for c in doc["candidates"]
              if c["label"] == "参考·白防线形" and c["channel"] == "renjiu")
    assert rj["cap_yuan"] == 128 and rj["stake_yuan"] == 128
