import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app

runner = CliRunner()


def _legs(tmp_path: Path, name: str, legs: list[dict]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(legs), encoding="utf-8")
    return path


def test_preview_shows_the_diagnosis_without_registering(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    fair = {"home": 0.357, "draw": 0.270, "away": 0.373}
    turkey = {"key": "周一004", "market": "had", "selections": ["home"], "odds": [2.58],
              "fair": fair}
    first = _legs(tmp_path, "j1.json", [turkey, {"key": "周一007", "market": "had",
                                                  "selections": ["home"], "odds": [1.82]}])
    reg = runner.invoke(app, ["betslip", "register", "--slip-id", "J1", "--channel", "jczq",
                              "--placed-at", "2026-09-28", "--legs-file", str(first),
                              "--combo", "2", "--data-dir", str(data)])
    assert reg.exit_code == 0, reg.output
    second = _legs(tmp_path, "j2.json", [turkey, {"key": "周一005", "market": "had",
                                                   "selections": ["home"], "odds": [3.77]}])
    pre = runner.invoke(app, ["betslip", "preview", "--channel", "jczq",
                              "--placed-at", "2026-09-28", "--legs-file", str(second),
                              "--combo", "2", "--multiplier", "50", "--data-dir", str(data)])
    # 2026-10-01 审票：与已购票共享裸单 = V2 否决 → 退出码 1（改票后再审），仍不登记
    assert pre.exit_code == 1, pre.output
    assert "⛔V2" in pre.output and "审票结论：**否决**" in pre.output
    assert "预览 jczq 1 注 × 50 倍 = ¥100" in pre.output
    assert "共享裸单 1 条（周一0043）与 1 张票同押；这些票一起死 ≥64%" in pre.output
    rows = (data / "betslips.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 and json.loads(rows[0])["slip_id"] == "J1"
    # 预审留痕（2026-10-02）：截止播报据此提醒「审过但没登记」
    [log] = (data / "daily" / "2026-09-28" / "previews.jsonl").read_text("utf-8").splitlines()
    row = json.loads(log)
    assert row["channel"] == "jczq" and row["keys"] == ["周一004", "周一005"]
    assert row["vetoed"] is True and row["stake"] == 100


def test_preview_set_sees_shared_naked_legs_inside_the_plan(tmp_path: Path):
    # 10-05：三张足彩逐张预审都「可出」，登记第一张后才暴露三票同死；整组预审一次看全
    data = tmp_path / "data"
    data.mkdir()
    fair = {str(n): {"home": 0.5, "draw": 0.28, "away": 0.22} for n in range(1, 15)}
    (tmp_path / "fair.json").write_text(json.dumps(fair), encoding="utf-8")
    plan = [
        {"label": "R9-A", "channel": "renjiu", "placed_at": "2026-10-05", "issue": "26135",
         "faces": "1:3 2:31 3:3 4:10 5:3 6:3 7:1 8:3 9:30", "fair_file": "fair.json"},
        {"label": "R9-B", "channel": "renjiu", "placed_at": "2026-10-05", "issue": "26135",
         "faces": "6:31 7:1 8:3 9:3 10:0 11:3 12:1 13:3 14:31", "fair_file": "fair.json"},
        {"label": "J1", "channel": "jczq", "placed_at": "2026-10-05", "combo": "2",
         "legs_file": "j1.json"},
    ]
    _legs(tmp_path, "j1.json", [
        {"key": "周一001", "market": "had", "selections": ["home"], "odds": [1.9]},
        {"key": "周一002", "market": "had", "selections": ["away"], "odds": [2.4]}])
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")

    out = runner.invoke(app, ["betslip", "preview-set", "--plan", str(tmp_path / "plan.json"),
                              "--data-dir", str(data)])

    assert "【R9-A】renjiu" in out.output and "【J1】jczq" in out.output
    assert "⛔V2" in out.output                       # A 与 B 在场 7、8、9 共享裸单
    assert "整组 3 张" in out.output and "否决 2 张（R9-A、R9-B）" in out.output
    assert "整组共享裸单：" in out.output and "71 在 2 张票上" in out.output
    # 同伴是组内计划票，不是已购票（2026-10-08 前一律写「已购票」）
    assert "⛔V2 与同组计划票共享裸单" in out.output and "与已购票共享" not in out.output
    assert out.exit_code == 1
    assert not (data / "betslips.jsonl").exists()      # 预审不登记

    # 互斥备选（2026-10-08）：同一条裸单是同一判断的两种写法，不互审、不报整组总额
    alt = runner.invoke(app, ["betslip", "preview-set", "--plan", str(tmp_path / "plan.json"),
                              "--alternatives", "--data-dir", str(data)])
    assert alt.exit_code == 0, alt.output
    assert "互斥备选 3 张" in alt.output and "⛔V2" not in alt.output
    assert "备选 3 张｜否决 0 张" in alt.output and "整组" not in alt.output


def test_preview_set_rejects_an_invalid_plan_before_reporting_anything(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (tmp_path / "plan.json").write_text(json.dumps([
        {"channel": "renjiu", "placed_at": "2026-10-05", "issue": "26135",
         "faces": "1:3 2:3 3:3 4:3 5:3 6:3 7:3 8:3 9:3", "fair_file": "fair.json"},
        {"channel": "renjiu", "placed_at": "2026-10-05", "issue": "26135",
         "faces": "1:3 2:3", "fair_file": "fair.json"}]), encoding="utf-8")
    (tmp_path / "fair.json").write_text("{}", encoding="utf-8")
    out = runner.invoke(app, ["betslip", "preview-set", "--plan", str(tmp_path / "plan.json"),
                              "--data-dir", str(data)])
    assert out.exit_code == 1 and "任九至少选 9 场" in out.output and "【" not in out.output


def test_tripped_stop_loss_vetoes_the_preview_but_never_the_registration(tmp_path: Path):
    """月度止损触发＝预审否决（2026-10-06，宪法 §4「空仓到月底」）；登记是事实，照收。"""
    data = tmp_path / "data"
    data.mkdir()
    (data / "scoreboard.json").write_text(json.dumps({"tickets": {
        "jczq-20261003": {"net": -8200, "stake": 8200}}}), encoding="utf-8")   # 止损线 8,000
    legs = _legs(tmp_path, "j.json", [
        {"key": "周六001", "market": "had", "selections": ["home"], "odds": [1.5],
         "fair": {"home": 0.62, "draw": 0.22, "away": 0.16}},
        {"key": "周六002", "market": "had", "selections": ["home"], "odds": [1.6],
         "fair": {"home": 0.6, "draw": 0.24, "away": 0.16}}])
    args = ["--channel", "jczq", "--placed-at", "2026-10-06", "--legs-file", str(legs),
            "--combo", "2", "--data-dir", str(data)]
    pre = runner.invoke(app, ["betslip", "preview", *args])
    assert pre.exit_code == 1 and "已触发" in pre.output, pre.output
    reg = runner.invoke(app, ["betslip", "register", "--slip-id", "J9", *args])
    assert reg.exit_code == 0 and "已触发" in reg.output, reg.output
    [row] = [json.loads(x) for x in (data / "betslips.jsonl").read_text("utf-8").splitlines()]
    assert row["slip_id"] == "J9" and row["registered_at"] and "review" in row["diagnosis"]


def test_issue_brake_vetoes_a_zucai_preview_over_the_halved_cap(tmp_path: Path):
    """连续两期全灭后的这一期：已买 + 这张超 ¥800 合计帽 → 预审否决；登记照收并记 BRAKE。"""
    data = tmp_path / "data"
    (data / "zucai").mkdir(parents=True)
    (data / "scoreboard.json").write_text(json.dumps({"tickets": {
        "26131": {"stake": 310, "payout": 0, "net": -310},
        "26132": {"stake": 1362, "payout": 0, "net": -1362}}}), encoding="utf-8")
    (data / "zucai" / "26133-issue.json").write_text(json.dumps({
        "sale_deadline": "2026-09-26 20:30", "matches": [
            {"match_no": i, "kickoff_bj": "2026-09-27 02:45"} for i in range(1, 15)]}),
        encoding="utf-8")
    faces = "3 3 3 31 31 31 310 310 310 * * * * *"            # 2³×3³ = 216 注 ¥432
    args = ["--channel", "renjiu", "--placed-at", "2026-09-26", "--issue", "26133",
            "--faces", faces, "--data-dir", str(data)]
    pre = runner.invoke(app, ["betslip", "preview", *args])
    assert pre.exit_code == 1 and "⛔刹车：连续两期全灭（26131、26132）" in pre.output, pre.output
    reg = runner.invoke(app, ["betslip", "register", "--slip-id", "26133-R9", *args])
    assert reg.exit_code == 0 and "⛔刹车" in reg.output, reg.output
    [row] = [json.loads(x) for x in (data / "betslips.jsonl").read_text("utf-8").splitlines()]
    assert row["diagnosis"]["review"]["vetoed"] is True
    assert "BRAKE" in row["diagnosis"]["review"]["codes"]


def _zucai_plan(tmp_path: Path, rows: list[dict]) -> Path:
    fair = {str(n): {"home": 0.5, "draw": 0.28, "away": 0.22} for n in range(1, 15)}
    (tmp_path / "fair.json").write_text(json.dumps(fair), encoding="utf-8")
    plan = [{"channel": "renjiu", "placed_at": "2026-10-09", "issue": "26136",
             "fair_file": "fair.json", **row} for row in rows]
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return tmp_path / "plan.json"


MAIN = "1:3 2:31 3:30 4:31 5:310 6:3 7:3 8:3 9:3"
SUB = "1:31 2:3 3:3 4:30 5:10 6:31 10:3 11:3 12:3"


def test_preview_set_reports_group_coverage_co_death_and_pinned_results(tmp_path: Path):
    """26136（2026-10-09）：至少中一张、两两同死、钉住一场赛果后各票还剩多少——此前全靠手写脚本。"""
    from nutmeg.decision.slip_group import given, p_all, p_any

    data = tmp_path / "data"
    data.mkdir()
    plan = _zucai_plan(tmp_path, [{"label": "主", "faces": MAIN}, {"label": "副", "faces": SUB}])
    out = runner.invoke(app, ["betslip", "preview-set", "--plan", str(plan), "--given", "1:1",
                              "--data-dir", str(data)])
    fair = json.loads((tmp_path / "fair.json").read_text("utf-8"))
    main = dict(x.split(":") for x in MAIN.split())
    sub = dict(x.split(":") for x in SUB.split())
    union = p_any([main, sub], fair)
    assert f"整组算术（26136，计划 2 张）：至少中一张 {union * 100:.2f}%" in out.output, out.output
    assert "同死 主×副" in out.output and "（1开0、2开0、3开1、6开0）" in out.output
    pinned = given(fair, {"1": "1"})
    assert f"若 1开1：主 0.00%｜副 {p_all([sub], pinned) * 100:.2f}%" in out.output


def test_preview_set_alternatives_report_coverage_together_with_registered_tickets(
        tmp_path: Path):
    """比副单备选时真正要看的是它和已买主单合起来盖住多少，不是它自己的 P。"""
    data = tmp_path / "data"
    data.mkdir()
    plan = _zucai_plan(tmp_path, [{"label": "副A", "faces": SUB},
                                  {"label": "副B", "faces": "1:31 2:31 3:30 6:3 8:31 9:31 "
                                                            "10:3 13:3 14:310"}])
    reg = runner.invoke(app, ["betslip", "register", "--slip-id", "26136-R9-主", "--channel",
                              "renjiu", "--placed-at", "2026-10-09", "--issue", "26136",
                              "--faces", MAIN.replace(":", "·"),
                              "--fair-file", str(tmp_path / "fair.json"), "--data-dir", str(data)])
    assert reg.exit_code == 0, reg.output
    out = runner.invoke(app, ["betslip", "preview-set", "--plan", str(plan), "--alternatives",
                              "--data-dir", str(data)])
    assert "互斥备选与已登记实购合起来（26136，已登记 1 张" in out.output, out.output
    assert "【副A】至少中一张" in out.output and "与 26136-R9-主 同死" in out.output
    assert "【副B】至少中一张" in out.output


def test_complement_searches_a_ticket_that_maximises_coverage_with_the_base(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    plan = _zucai_plan(tmp_path, [{"label": "主", "faces": MAIN}])
    out = runner.invoke(app, ["betslip", "complement", "--plan", str(plan), "--max-notes", "8",
                              "--fix", "1:31", "--data-dir", str(data)])
    assert out.exit_code == 0, out.output
    assert "互补搜索（26136，基准 1 张" in out.output
    [best] = [line for line in out.output.splitlines() if line.startswith("最好的一张：")]
    faces = dict(x.split(":") for x in best.split("：", 1)[1].split("｜")[0].split())
    assert faces["1"] == "31" and len(faces) == 9
    assert not any(faces.get(no) == f for no, f in
                   (x.split(":") for x in MAIN.split()) if len(f) == 1)   # 不与主单共享裸单
    assert "合起来至少中一张" in out.output and "与 主 同死" in out.output
    assert not (data / "betslips.jsonl").exists()


def test_v5_warns_on_pack_in_non_coin_match_and_two_bold_picks(tmp_path: Path):
    """2026-10-23（26147 复盘）：包放在第三面 <25% 的场、一张票博胆 >1 → V5 只警告，不否决。"""
    data = tmp_path / "data"
    (data / "zucai").mkdir(parents=True)
    fair = {str(n): {"home": 0.62, "draw": 0.21, "away": 0.17} for n in range(1, 15)}
    fair["9"] = {"home": 0.35, "draw": 0.27, "away": 0.38}
    (tmp_path / "fair.json").write_text(json.dumps(fair), encoding="utf-8")
    # 1 包在 62/21/17 的场；2、3 排掉 62% 的主胜＝两条博胆；9 包在硬币场不警告
    faces = "310 10 10 3 3 3 3 3 310 * * * * *"
    pre = runner.invoke(app, ["betslip", "preview", "--channel", "renjiu", "--placed-at",
                              "2026-10-22", "--issue", "26147", "--faces", faces,
                              "--fair-file", str(tmp_path / "fair.json"),
                              "--data-dir", str(data)])
    assert pre.exit_code == 0, pre.output
    assert "⚠️V5 包放在非硬币场 1（0 只有 17%）" in pre.output
    assert "⚠️V5 博胆 2 条（2排3 62%、3排3 62%）" in pre.output
    assert "审票结论：可出" in pre.output
