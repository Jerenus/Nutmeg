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
    assert out.exit_code == 1
    assert not (data / "betslips.jsonl").exists()      # 预审不登记


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
