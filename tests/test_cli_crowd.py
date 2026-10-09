import json
from pathlib import Path

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app
from nutmeg.interfaces.cli import crowd as crowd_cli
from tests.decision.crowd_fixtures import seed_history, zg_doc
from tests.decision.test_crowd_prereg import CR


def _setup(tmp_path: Path, *, n: int = 30) -> tuple[Path, Path]:
    data = tmp_path / "data"
    seed_history(data / "zucai", first=26001, n=n, gamma=-0.3)
    reg = tmp_path / "registry"
    reg.mkdir()
    doc = dict(CR, window={"issue_from": "26016", "issue_to": "26999"},
               replay_window={"issue_from": "26001", "issue_to": "26015"})
    (reg / "CR1.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    r = CliRunner().invoke(app, ["rsi", "register", "--by", "Jun", str(reg / "CR1.json"),
                                 "--data-dir", str(data)])
    assert r.exit_code == 0, r.output
    return data, reg


def test_rsi_grade_cr_replay_and_prospective(tmp_path):
    data, reg = _setup(tmp_path)
    for mode, n in (("replay", 15), ("prospective", 15)):
        r = CliRunner().invoke(app, ["rsi", "grade", "--exp", "CR1", "--mode", mode,
                                     "--registry-dir", str(reg), "--data-dir", str(data)])
        assert r.exit_code == 0, r.output
        assert f"CR1 [{mode}] n={n}" in r.output


def test_rsi_grade_cr_refuses_edited_registry_doc(tmp_path):
    data, reg = _setup(tmp_path)
    doc = json.loads((reg / "CR1.json").read_text("utf-8"))
    doc["trigger"] = {"field": "face", "op": "==", "v": "3"}
    (reg / "CR1.json").write_text(json.dumps(doc), encoding="utf-8")
    r = CliRunner().invoke(app, ["rsi", "grade", "--exp", "CR1", "--mode", "replay",
                                 "--registry-dir", str(reg), "--data-dir", str(data)])
    assert r.exit_code != 0 and "冻结指纹" in r.output

def test_fetch_scan_map_settle_round_trip(tmp_path, monkeypatch):
    data, reg = _setup(tmp_path)
    monkeypatch.setattr(crowd_cli, "_fetcher", lambda: (lambda url: zg_doc()))
    run = lambda *a: CliRunner().invoke(app, ["crowd", *a, "--data-dir", str(data)])  # noqa: E731
    r = run("fetch", "--issue", "26136")
    assert r.exit_code == 0, r.output
    r = run("scan", "--issue", "26136", "--registry-dir", str(reg))
    assert r.exit_code == 0 and "新线索 14 条" in r.output
    r = run("map", "--issue", "26136", "--registry-dir", str(reg))
    assert "## 人群地图" in r.output and "⚑" in r.output
    prizes = json.loads((data / "zucai" / "official-prizes.json").read_text("utf-8"))
    prizes["issues"]["26136"] = {"results": " ".join(["1"] * 14),
                                 "renjiu": {"stake_count": 1, "stake_amount": 10.0}}
    (data / "zucai" / "official-prizes.json").write_text(json.dumps(prizes), encoding="utf-8")
    monkeypatch.setattr(crowd_cli, "_refresh_prizes", lambda zdir: None)
    r = run("settle", "--pending")
    assert r.exit_code == 0 and "26136 结算 14 条" in r.output
    r = run("settle", "--pending")
    assert r.exit_code == 0 and "无待结算的期" in r.output


def test_fetch_failure_exits_nonzero(tmp_path, monkeypatch):
    def boom(url):
        raise OSError("timeout")
    monkeypatch.setattr(crowd_cli, "_fetcher", lambda: boom)
    r = CliRunner().invoke(app, ["crowd", "fetch", "--issue", "26136",
                                 "--data-dir", str(tmp_path)])
    assert r.exit_code == 1 and "timeout" in r.output


def test_nominate_writes_candidates_and_sign_registers(tmp_path):
    data = tmp_path / "data"
    seed_history(data / "zucai", first=26001, n=60, gamma=-0.4)
    reg, cand = tmp_path / "registry", tmp_path / "candidates"
    reg.mkdir()
    r = CliRunner().invoke(app, ["crowd", "nominate", "--from", "26001", "--to", "26060",
                                 "--write", "--registry-dir", str(reg),
                                 "--candidates-dir", str(cand), "--data-dir", str(data)])
    assert r.exit_code == 0, r.output
    draw = {"field": "face", "op": "==", "v": "1"}
    paths = [p for p in sorted(cand.glob("CR-cand-*.json"))
             if json.loads(p.read_text("utf-8"))["trigger"] == draw]
    assert paths, r.output
    path = paths[0]
    doc = json.loads(path.read_text("utf-8"))
    assert doc["crowd_bias"] == "over" and doc["mechanism"] == "" and doc["exp_id"] is None
    r = CliRunner().invoke(app, ["crowd", "sign", str(path), "--as", "CR1", "--by", "Jun",
                                 "--from-issue", "26061", "--replay-from", "26001",
                                 "--replay-to", "26030", "--registry-dir", str(reg),
                                 "--data-dir", str(data)])
    assert r.exit_code == 1 and "mechanism" in r.output and not (reg / "CR1.json").exists()
    doc["mechanism"] = "复式拿平局做保险"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    r = CliRunner().invoke(app, ["crowd", "sign", str(path), "--as", "CR1", "--by", "Jun",
                                 "--from-issue", "26061", "--replay-from", "26001",
                                 "--replay-to", "26030", "--registry-dir", str(reg),
                                 "--data-dir", str(data)])
    assert r.exit_code == 0, r.output
    signed = json.loads((reg / "CR1.json").read_text("utf-8"))
    assert signed["exp_id"] == "CR1" and signed["window"]["issue_from"] == "26061"
    assert "已登记 CR1" in r.output

def test_draft_crowd_section_degrades_without_market_base(tmp_path):
    from nutmeg.interfaces.cli.judgment import _crowd_section

    text = _crowd_section(tmp_path, "26999")
    assert text.startswith("## 人群地图") and "本期无市场底座" in text


def _pm_fake(url, params):
    if url.endswith("/sports"):
        return [{"sport": "bun", "series": "1"}]
    if url.endswith("/events"):
        if params.get("offset"):
            return []
        closed = params["closed"] == "true"
        return [{"id": "e1", "title": "BV Borussia 09 Dortmund vs. SV Werder Bremen",
                 "endDate": "2026-10-09T18:30:00Z", "volume": 123456.0 if closed else 80268.0,
                 "markets": [
                     {"question": "Will BV Borussia 09 Dortmund win on 2026-10-09?",
                      "bestBid": 0.74, "bestAsk": 0.75, "clobTokenIds": "[\"h\"]"},
                     {"question": ("Will BV Borussia 09 Dortmund vs. SV Werder Bremen "
                                   "end in a draw?"),
                      "bestBid": 0.16, "bestAsk": 0.17, "clobTokenIds": "[\"d\"]"},
                     {"question": "Will SV Werder Bremen win on 2026-10-09?",
                      "bestBid": 0.10, "bestAsk": 0.11, "clobTokenIds": "[\"a\"]"}]}]
    return {"history": [{"p": 0.70}, {"p": 0.745}]}


def _pm_issue(data: Path) -> None:
    zdir = data / "zucai"
    zdir.mkdir(parents=True, exist_ok=True)
    (zdir / "26136-issue.json").write_text(json.dumps({
        "issue_id": "26136", "sale_deadline": "2026-10-09 22:00", "matches": [
            {"match_no": 2, "home_team": "多特", "away_team": "不来梅",
             "kickoff_bj": "2026-10-10 02:30"}]}, ensure_ascii=False), encoding="utf-8")
    (zdir / "26136-store-ids.json").write_text(json.dumps({"2": {
        "match_id": "m2", "fair": {"home": 0.70, "draw": 0.17, "away": 0.13}}}), encoding="utf-8")


def test_crowd_polymarket_snapshots_an_issue_and_backfill_marks_the_source(tmp_path, monkeypatch):
    """Polymarket 关注度（2026-10-09）：取数换成假接口，队名走真实别名表（多特/不来梅都在表里）。"""
    import nutmeg.data.polymarket as pm

    monkeypatch.setattr(pm, "default_fetch", _pm_fake)
    _pm_issue(tmp_path)
    runner = CliRunner()
    out = runner.invoke(app, ["crowd", "polymarket", "--issue", "26136",
                              "--data-dir", str(tmp_path)])
    assert out.exit_code == 0, out.output
    assert "对上 1 场" in out.output
    doc = json.loads((tmp_path / "zucai" / "26136-polymarket.json").read_text("utf-8"))
    assert doc["snapshots"][-1]["rows"]["2"]["rank"] == 1

    back = runner.invoke(app, ["crowd", "polymarket-backfill", "--from", "26136", "--to", "26136",
                               "--data-dir", str(tmp_path)])
    assert back.exit_code == 0, back.output
    doc = json.loads((tmp_path / "zucai" / "26136-polymarket.json").read_text("utf-8"))
    assert doc["snapshots"][-1]["source"] == "closed_backfill"
