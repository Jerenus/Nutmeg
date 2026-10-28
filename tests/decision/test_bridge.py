"""§3 桥（2026-10-28 产品形态第 3 阶段）：五条自检只读旁车与 precheck、差异格读数、只走一次。"""
import json

import pytest

from nutmeg.decision.betslip import BetSlip, register_slip
from nutmeg.decision.bridge import (
    BRIDGE_SUFFIX,
    BridgeError,
    append_bridge,
    bridge_ledger,
    bridge_record,
    cite_readout,
    diff_cells,
    opening_lines,
    self_checks,
)


def _row(no, tier, k=None, n=None, **over):
    return {"no": no, "tier": tier, "k": k, "n": n, "default": "3", **over}


def _packet(*rows, signed_bold=()):
    return {"by_no": {r["no"]: r for r in rows}, "signed_bold": list(signed_bold)}


PRE_CLEAN = {"verdicts": [{"code": "V1", "level": "info", "text": "期望回报率 0.80"}],
             "discipline": [], "brake_line": "✅止损余 ¥3,000"}


def _check(checks, i):
    return next(c for c in checks if c["id"] == i)


# ---------------------------------------------------------------- self_checks

def test_check1_d_tier_match_in_ticket_fails_and_lists_it():
    packet = _packet(_row("1", "D"), _row("2", "B", 5, 6))
    checks = self_checks(packet, {"1": "31", "2": "3"}, PRE_CLEAN)
    one = _check(checks, 1)
    assert one["ok"] is False
    assert "1" in one["detail"] and "31" in one["detail"]
    assert [c["id"] for c in checks] == [1, 2, 3, 4, 5]


def test_check1_passes_when_d_tier_dropped_and_says_c_without_mechanism_not_judged():
    packet = _packet(_row("1", "D"), _row("2", "B", 5, 6))
    one = _check(self_checks(packet, {"1": "", "2": "3"}, PRE_CLEAN), 1)
    assert one["ok"] is True
    assert "无机制 C 档" in one["detail"]


def test_check2_single_needs_five_of_six():
    four = _packet(_row("2", "B", 4, 6))
    assert _check(self_checks(four, {"2": "3"}, PRE_CLEAN), 2)["ok"] is False
    five = _packet(_row("2", "B", 5, 6))
    assert _check(self_checks(five, {"2": "3"}, PRE_CLEAN), 2)["ok"] is True


def test_check2_doubles_are_not_singles():
    packet = _packet(_row("2", "B", 2, 6))
    assert _check(self_checks(packet, {"2": "31"}, PRE_CLEAN), 2)["ok"] is True


def test_check2_signed_bold_c_single_passes_from_param_or_sidecar():
    packet = _packet(_row("9", "C", 4, 5))
    assert _check(self_checks(packet, {"9": "0"}, PRE_CLEAN), 2)["ok"] is False
    assert _check(self_checks(packet, {"9": "0"}, PRE_CLEAN, signed_bold=["9"]), 2)["ok"] is True
    sidecar = _packet(_row("9", "C", 4, 5), signed_bold=[{"no": "9", "face": "0"}])
    assert _check(self_checks(sidecar, {"9": "0"}, PRE_CLEAN), 2)["ok"] is True
    # 旁车签的是 0，单的却是 3：不算签过
    assert _check(self_checks(sidecar, {"9": "3"}, PRE_CLEAN), 2)["ok"] is False


def test_check2_signable_lists_singles_unlicensed_without_bridge_signature():
    packet = _packet(_row("2", "B", 5, 6), _row("4", "B", 4, 6), _row("9", "C", 4, 5),
                     _row("11", "C", 4, 5), signed_bold=[{"no": "11", "face": "0"}])
    faces = {"2": "3", "4": "3", "9": "0", "11": "0", "12": "31"}
    two = _check(self_checks(packet, faces, PRE_CLEAN), 2)
    assert two["signable"] == [{"no": "4", "face": "3"}, {"no": "9", "face": "0"}]
    # 桥上签了照样列（开关要留着才能撤签）
    signed = _check(self_checks(packet, faces, PRE_CLEAN, signed_bold=["4", "9"]), 2)
    assert signed["ok"] is True and signed["signable"] == two["signable"]
    assert all("signable" not in c for c in self_checks(packet, faces, PRE_CLEAN) if c["id"] != 2)


def test_check2_a_tier_single_is_not_licensed_and_detail_says_why():
    packet = _packet(_row("4", "A", 7, 7))
    two = _check(self_checks(packet, {"4": "3"}, PRE_CLEAN), 2)
    assert two["ok"] is False
    assert "A 档" in two["detail"]


def test_check3_reads_v5_line_verbatim_and_does_not_recompute():
    text = "博胆 2 条（3排3 60%、7排0 58%）：每票博胆 ≤1（§3a 第 3 条；26137–26147 n=5 全死）"
    pre = {**PRE_CLEAN, "verdicts": [*PRE_CLEAN["verdicts"],
                                     {"code": "V5", "level": "warn", "text": text}]}
    # 票面本身没有任何博胆：✗ 只能来自 V5 行
    packet = _packet(_row("2", "B", 5, 6))
    three = _check(self_checks(packet, {"2": "3"}, pre), 3)
    assert three["ok"] is False
    assert three["detail"] == text


def test_check3_passes_without_v5():
    assert _check(self_checks(_packet(), {}, PRE_CLEAN), 3)["ok"] is True


def test_check4_v2_line_fails():
    text = "与已购票共享裸单 1 条（2·3）：假分散——改双选或换场"
    pre = {**PRE_CLEAN, "verdicts": [{"code": "V2", "level": "veto", "text": text}]}
    four = _check(self_checks(_packet(), {}, pre), 4)
    assert four["ok"] is False
    assert text in four["detail"]
    clean = _check(self_checks(_packet(), {}, PRE_CLEAN), 4)
    assert clean["ok"] is True and "无跨票共享" in clean["detail"]


def test_check5_brake_or_day_cap_fails_but_month_stop_is_not_in_the_five():
    brake = {**PRE_CLEAN, "discipline": ["⛔刹车：连续两期全灭 → 本期复式 ≤¥400"]}
    assert _check(self_checks(_packet(), {}, brake), 5)["ok"] is False
    cap = {**PRE_CLEAN, "discipline": ["⛔日帽：2026-10-28 已买 ¥1,800 + 这张 ¥256"]}
    assert _check(self_checks(_packet(), {}, cap), 5)["ok"] is False
    stop = {**PRE_CLEAN, "brake_line": "⛔月度止损已触发"}
    assert _check(self_checks(_packet(), {}, stop), 5)["ok"] is True


# ---------------------------------------------------------------- opening_lines

def test_opening_lines_one_per_single_plus_first_gate_with_d_tag():
    packet = _packet(_row("2", "B", 5, 6, unknowable="名单 20:15 出，停售后"),
                     _row("5", "B", 5, 6, lineup_at="21:00", lineup_before_close=True),
                     _row("1", "D"))
    gates = [{"no": "1", "face": "0", "p": 0.35, "coin": True},
             {"no": "5", "face": "10", "p": 0.2, "coin": False}]
    lines = opening_lines(packet, {"2": "3", "5": "3", "1": "31"}, gates)
    assert len(lines) == 3
    assert "名单 20:15 出" in lines[0]["text"]
    assert "21:00" in lines[1]["text"] and "停售前" in lines[1]["text"]
    assert "1" in lines[2]["text"] and "35%" in lines[2]["text"] and "D档" in lines[2]["text"]


# ---------------------------------------------------------------- diff_cells

FAIR = {no: {"home": 0.5, "draw": 0.3, "away": 0.2} for no in ("9", "10", "13", "14")}
MATRICES = {"13": {"rows": [{"evidence": "第一行"}, {"evidence": "锚方门将停赛"}]}}


def test_diff_cells_compares_face_sets_and_drop_is_empty():
    diffs = diff_cells({"10": "10", "14": "丢"}, {"10": "10", "14": "31"}, FAIR, {}, {}, {})
    assert [d["no"] for d in diffs] == ["14"]
    d = diffs[0]
    assert d["mine"] == "" and d["main"] == "31"
    assert d["cover_main"] == pytest.approx(0.8) and d["excl_main"] == pytest.approx(0.2)
    assert d["reason"] is None


def test_diff_cells_order_insensitive_face_strings():
    assert diff_cells({"10": "01"}, {"10": "10"}, FAIR, {}, {}, {}) == []


def test_diff_cells_matrix_cite_brings_evidence_and_out_brings_text():
    diffs = diff_cells({"13": "3", "9": "30"}, {"13": "31", "9": "31"}, FAIR,
                       {"13": 2, "9": "out"}, {"9": "主帅赛前说要轮换"}, MATRICES)
    by = {d["no"]: d for d in diffs}
    assert by["13"]["reason"] == {"kind": "matrix", "row": 2, "evidence": "锚方门将停赛"}
    assert by["9"]["reason"] == {"kind": "out", "text": "主帅赛前说要轮换"}


# ---------------------------------------------------------------- cite_readout

def test_cite_readout_counts():
    diffs = [{"reason": {"kind": "matrix", "row": 1, "evidence": "x"}},
             {"reason": {"kind": "out", "text": "y"}},
             {"reason": None}]
    assert cite_readout(diffs) == {"diffs": 3, "matrix": 1, "outside": 1, "blank": 1}


# ---------------------------------------------------------------- 记录与账

def test_append_bridge_twice_refused_and_record_reads_first(tmp_path):
    path = append_bridge(tmp_path, "26151", {"faces": {"1": "3"}, "draft0": {"1": "31"}})
    assert path == tmp_path / "zucai" / f"26151{BRIDGE_SUFFIX}"
    with pytest.raises(BridgeError):
        append_bridge(tmp_path, "26151", {"faces": {"1": "0"}})
    rec = bridge_record(tmp_path, "26151")
    assert rec["faces"] == {"1": "3"}
    assert rec["stage"] == "B1" and rec["at"]
    assert len(path.read_text("utf-8").splitlines()) == 1
    assert bridge_record(tmp_path, "26152") is None


B1 = {str(i): "3" for i in range(1, 10)}


def _slip(slip_id, faces, purchased, channel="renjiu"):
    return BetSlip(slip_id=slip_id, channel=channel, placed_at="2026-10-28", legs=[],
                   issue="26151", purchased=purchased, faces=faces)


def test_bridge_ledger_real_slip_changed_cells(tmp_path):
    diffs = [{"no": "10", "mine": "3", "main": "31",
              "reason": {"kind": "matrix", "row": 1, "evidence": "e"}}]
    append_bridge(tmp_path, "26151", {"faces": B1, "diffs": diffs})
    register_slip(tmp_path, _slip("26151-B1", B1, purchased=False))
    real = {**B1, "2": "31", "8": "10"}
    register_slip(tmp_path, _slip("26151-T1", real, purchased=True))
    sfc = {str(i): "3" for i in range(1, 15)}
    register_slip(tmp_path, _slip("26151-T3", sfc, purchased=True, channel="shengfucai"))
    ledger = bridge_ledger(tmp_path, "26151")
    assert ledger["walked"] is True
    assert ledger["b1_faces"] == B1
    assert ledger["readout"] == {"diffs": 1, "matrix": 1, "outside": 0, "blank": 0}
    assert [r["slip_id"] for r in ledger["real"]] == ["26151-T1"]
    assert ledger["real"][0]["changed"] == ["2", "8"]


def test_bridge_ledger_not_walked(tmp_path):
    ledger = bridge_ledger(tmp_path, "26151")
    assert ledger["walked"] is False and ledger["real"] == []


def test_bridge_file_is_jsonl(tmp_path):
    path = append_bridge(tmp_path, "26151", {"faces": {}})
    assert json.loads(path.read_text("utf-8").splitlines()[0])["issue"] == "26151"


def test_cli_judgment_bridge_prints_ledger(tmp_path):
    from typer.testing import CliRunner

    from nutmeg.interfaces.cli import app

    runner = CliRunner()
    args = ["judgment", "bridge", "--issue", "26151", "--data-dir", str(tmp_path)]
    assert "本期没走桥" in runner.invoke(app, args).output
    append_bridge(tmp_path, "26151", {
        "faces": B1, "main_label": "W4 4单5双",
        "diffs": [{"no": "10", "mine": "3", "main": "31",
                   "reason": {"kind": "matrix", "row": 2, "evidence": "锚方门将停赛"}},
                  {"no": "14", "mine": "", "main": "31", "reason": None}]})
    register_slip(tmp_path, _slip("26151-T1", {**B1, "2": "31"}, purchased=True))
    out = runner.invoke(app, args).output
    assert "W4 4单5双" in out and "矩阵行 2：锚方门将停赛" in out
    assert "| 14 | 丢 | 31 | 未写 |" in out
    assert "差异格 2 · 指到矩阵行 1 · 矩阵外 0 · 未写 1" in out
    assert "实票 26151-T1 vs B1：改 1 格（2）" in out
