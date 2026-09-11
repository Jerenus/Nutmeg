# tests/decision/test_scoreboard_settle_issue.py
"""记分牌一键镜像的规划逻辑（dry-run 层，不碰本体）。

治理动作本身不能比它要治理的事还费劲：26121 复盘改了 12 个指标，手工镜像跑了三轮才成
（先被 "must supersede the current leaf" 挡，再被失败尝试占住的幂等键挡）。
影子期双轨一旦比"只改 JSON"贵太多，就会退化成无声双权威，而那是 M5 明令禁止的。
"""
import json

from typer.testing import CliRunner

from nutmeg.config.settings import AppSettings
from nutmeg.interfaces.cli import app
from nutmeg.ontology.wiring import build_ontology_kernel

_BOARD = {
    "updated_at": "2026-09-11T11:05:00+08:00",
    "note": "记分牌单一事实源（非指标，必须被跳过）",
    "chains": {
        "excluded_face_streak": {
            "tally": "26112-26121 贯穿",
            "detail": "旧段落 ‖ 26121:无一被排面开出。",
            "status": "active",
        }
    },
    "tags": {
        "promoted_side": {"tally": "非模态 6/12", "detail": "只有一段", "status": "probation"}
    },
}


def _data_dir(tmp_path):
    data_dir = tmp_path / "data"
    build_ontology_kernel(AppSettings(data_dir=data_dir)).initialize()
    return data_dir


def _plan(tmp_path, *args):
    data_dir = _data_dir(tmp_path)
    board = tmp_path / "scoreboard.json"
    board.write_text(json.dumps(_BOARD, ensure_ascii=False), encoding="utf-8")
    result = CliRunner().invoke(app, [
        "scoreboard", "settle-issue",
        "--data-dir", str(data_dir), "--scoreboard-file", str(board),
        "--evidence-type", "official_draw", "--evidence-id", "26122",
        "--effective-at", "2026-09-11T12:00:00+08:00",
        "--requested-at", "2026-09-11T12:00:00+08:00",
        "--acknowledge-manual-source", *args,
    ])
    return result


def test_requires_manual_source_acknowledgement(tmp_path):
    """影子期手改是人工来源，必须显式承认——静默镜像等于伪装成自动事实。"""
    data_dir = _data_dir(tmp_path)
    board = tmp_path / "scoreboard.json"
    board.write_text(json.dumps(_BOARD, ensure_ascii=False), encoding="utf-8")
    result = CliRunner().invoke(app, [
        "scoreboard", "settle-issue",
        "--data-dir", str(data_dir), "--scoreboard-file", str(board),
        "--evidence-type", "official_draw", "--evidence-id", "26122",
        "--effective-at", "2026-09-11T12:00:00+08:00",
        "--requested-at", "2026-09-11T12:00:00+08:00",
    ])
    assert result.exit_code == 1
    assert "acknowledge-manual-source" in result.output


def test_dry_run_is_the_default_and_plans_only_metric_entries(tmp_path):
    """默认只出计划：`note`/`updated_at` 这类非指标键必须被跳过，不能当成指标镜像。"""
    result = _plan(tmp_path)
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["mode"] == "dry_run"
    keys = {(p["group_key"], p["metric_key"]) for p in payload["planned"]}
    assert keys == {("chains", "excluded_face_streak"), ("tags", "promoted_side")}


def test_plan_mirrors_only_the_latest_detail_segment(tmp_path):
    """只镜像最新一段 detail —— 整段重发会让观察越来越长，而观察的价值是"这一期改了什么"。"""
    payload = json.loads(_plan(tmp_path).output)
    chain = next(p for p in payload["planned"] if p["metric_key"] == "excluded_face_streak")
    assert chain["detail"] == "26121:无一被排面开出。"
    tag = next(p for p in payload["planned"] if p["metric_key"] == "promoted_side")
    assert tag["detail"] == "只有一段"


def test_metric_filter_narrows_the_plan(tmp_path):
    payload = json.loads(_plan(tmp_path, "--metric", "tags/promoted_side").output)
    assert [p["metric_key"] for p in payload["planned"]] == ["promoted_side"]


def test_first_observation_has_no_supersedes(tmp_path):
    """首次观察没有 leaf 可 supersede；自动填 None 而不是让用户去猜一个 id。"""
    payload = json.loads(_plan(tmp_path).output)
    assert all(p["supersedes"] is None for p in payload["planned"])
