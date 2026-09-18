"""判读工作台的**内核读侧** —— 让页面看见 `decision-read` 写进 ForecastRevision 的判断。

出生事故 2026-09-18：`decision-read` 在 `NUTMEG_ONTOLOGY_V2=1` 下把 Read 提交成内核
ForecastRevision，而 `decision_web.py` 仍读旧 `DecisionStore`（reads.jsonl 最后一条 2026-08-24）。
于是 26129 当天 14/14 条 Read 入了内核，工作台照样「今日 agent 尚未开工」——不是裁决完了，
是读侧没跟着写侧切换。

本模块只做**转录**：把内核三张查询（当日场次 / 最新 read_time 快照 / 已提交 forecast）
搬成旧模板与 `/api/workbench` 已经消费的形状，并为每条已提交 Read 合成一条 `attention`
议程事件。**不产生判断、不写任何东西。**

日界与 `ProductQueryService.board()` 同口径：按上海日 [00:00, 24:00) 切成 UTC 区间。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, time, timedelta
from datetime import date as _date
from typing import Any, Protocol
from zoneinfo import ZoneInfo

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_DEFAULT_MARKET = "md-had"
_MARKET_LEGACY = {"md-had": "had", "md-hhad": "hhad", "md-ttg": "ttg", "md-crs": "crs"}


class KernelReadRepository(Protocol):
    """`ProductReadRepository` 里本模块用到的三个查询（便于测试注入假仓库）。"""

    def board_matches(self, start_at: str, end_at: str, as_of: str) -> list[dict]: ...
    def latest_snapshot(
        self, match_id: str, market_definition_id: str, as_of: str
    ) -> dict | None: ...
    def forecasts_for_match(self, match_id: str, as_of: str) -> list[dict]: ...


def _day_window_utc(day: str) -> tuple[str, str]:
    d = _date.fromisoformat(day)
    start = datetime.combine(d, time.min, tzinfo=_SHANGHAI).astimezone(UTC)
    return start.isoformat(), (start + timedelta(days=1)).isoformat()


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return {}
    return value if value is not None else {}


def _match_dict(row: dict) -> dict:
    return {
        "match_id": row["match_id"],
        "home": row.get("home_team") or "",
        "away": row.get("away_team") or "",
        "competition": row.get("competition") or "",
        "kickoff_at": str(row.get("scheduled_at") or ""),
        "status": row.get("status"),
    }


def _snapshot_dict(row: dict, market: str) -> dict:
    coverage = _json(row.get("source_coverage_json"))
    return {
        "snapshot_id": row.get("market_snapshot_id"),
        "match_id": row["match_id"],
        "taken_at": str(row.get("as_of") or ""),
        "kind": row.get("snapshot_kind") or "read_time",
        "source": (coverage.get("provider") if isinstance(coverage, dict) else None)
        or row.get("devig_method") or "kernel",
        "fair": {_MARKET_LEGACY.get(market, market): _json(row.get("fair_distribution_json"))},
    }


def _read_dict(row: dict, match_id: str) -> dict:
    return {
        "read_id": row["forecast_revision_id"],
        "match_id": match_id,
        "market": _MARKET_LEGACY.get(row.get("market_definition_id"), "had"),
        "made_at": str(row.get("made_at") or ""),
        "prior": _json(row.get("prior_distribution")),
        "belief": _json(row.get("belief_distribution")),
        "actor_id": row.get("actor_id"),
        "commitment_tier": row.get("commitment_tier"),
        "status": row.get("status"),
    }


def slips_for_date(data_dir, zucai_dir, day: str) -> list:
    """当日**已登记实票**：凡 `<issue>-issue.json` 里有比赛落在这一天的期次，其票全部算当日方案。

    右栏「我的方案」的数据源就是 betslips 登记簿——没入账＝没打，页面同样不显示。
    竞彩票也带 `issue`（登记时按同期足彩期号挂），故一并带出。
    """
    import glob
    import os

    from nutmeg.decision.betslip import load_slips

    issues: list[str] = []
    for path in sorted(glob.glob(os.path.join(str(zucai_dir), "*-issue.json"))):
        try:
            doc = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        dates = {str(m.get("match_date") or "")[:10] for m in doc.get("matches", [])}
        if day in dates:
            issue_id = doc.get("issue_id") or os.path.basename(path)[:5]
            issues.append(str(issue_id))
    out = []
    for issue in issues:
        out.extend(load_slips(data_dir, issue=issue))
    return out


def _slip_event(slip) -> dict:
    return {
        "kind": "slip",
        "id": slip.slip_id,
        "obj_id": slip.slip_id,
        "payload": {
            "slip_id": slip.slip_id,
            "channel": slip.channel,
            "issue": slip.issue,
            "purchased": slip.purchased,
            "notes": slip.notes,
            "multiplier": slip.multiplier,
            "stake_yuan": slip.stake_yuan,
            "hit_probability": slip.hit_probability,
            "scheme_no": slip.scheme_no,
            "combo_sizes": list(slip.combo_sizes),
            "legs": [
                {"key": lg.key, "name": lg.name, "market": lg.market,
                 "line": lg.line, "selections": list(lg.selections),
                 "coverage": lg.coverage}
                for lg in slip.legs
            ],
            "faces": dict(slip.faces),
            "note": slip.note,
        },
    }


def kernel_day_state(
    repository: KernelReadRepository, day: str, *, as_of: datetime, slips=None
) -> dict[str, Any]:
    """→ {matches, snapshots, reads, events}。matches/snapshots/reads 来自内核；
    events = 每条已提交 Read 的 attention+judgment，
    外加每张已登记实票的 `slip`（右栏「我的方案」）。"""
    cutoff = as_of.isoformat()
    start_at, end_at = _day_window_utc(day)
    matches: list[dict] = []
    snapshots: list[dict] = []
    reads: list[dict] = []
    events: list[dict] = []
    for row in repository.board_matches(start_at, end_at, cutoff):
        m = _match_dict(row)
        matches.append(m)
        snap = repository.latest_snapshot(m["match_id"], _DEFAULT_MARKET, cutoff)
        if snap:
            snapshots.append(_snapshot_dict(snap, _DEFAULT_MARKET))
        for f in repository.forecasts_for_match(m["match_id"], cutoff):
            if f.get("status") != "committed":
                continue
            r = _read_dict(f, m["match_id"])
            reads.append(r)
            label = f"{m['home']} vs {m['away']}"
            # 左栏议程项。已提交的内核 Read 不是「草稿」——不合成 read_draft 卡，
            # 右栏「待裁决」只留给真正待批的草稿；点开后中栏以「已落库判读」渲染。
            events.append({
                "kind": "attention",
                "id": r["read_id"],
                "obj_id": r["read_id"],
                "group": "内核判读 · 已落库",
                "match": label,
                "note": f"{r['market']} · {r['made_at'][:16]}",
                "market": r["market"],
                "made_at": r["made_at"],
            })
            # 中栏舞台：app.js `judgment` 事件 → judgments[obj_id] → renderStageJudgment。
            events.append({
                "kind": "judgment",
                "obj_id": r["read_id"],
                "payload": {
                    "match": label,
                    "competition": m["competition"],
                    "market": r["market"],
                    "prior": r["prior"],
                    "belief": r["belief"],
                    "factors": [],            # 内核偏移因子另有 factor_applications，本刀不搬
                    "note": f.get("falsifier") or "",
                    "made_at": r["made_at"],
                    "actor_id": r["actor_id"],
                },
            })
    for slip in slips or []:
        events.append(_slip_event(slip))
    return {"matches": matches, "snapshots": snapshots, "reads": reads, "events": events}
