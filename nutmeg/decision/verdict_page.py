"""当日判决参考页（Jun 2026-09-27）：当天分析任务完成后生成一张静态页，供人工最终裁决。

主版 12:30（08:00 入板 + 上午研究 + 足彩截止日 11:00 备料后的足彩研究都已落）；
晚版 18:45（17:15 加场 + 18:00 研究 + 18:30 足彩复核之后，赶在 19:00 后主要开球与足彩停售前）。
只搬运与算术，不做判断：研究原判、主循环终判与改判、两渠道研究分歧、判断腿组合、判断力账本。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from nutmeg.decision.overrides import LEDGER
from nutmeg.decision.signals import build_signals

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "interfaces" / "web" / "templates" / "decision"


def _edition(now: datetime) -> str:
    return "主版" if now.hour < 15 else "晚版"


def _ledger_totals(data_dir: Path) -> dict:
    """全部日期的改判账：已开赛场次的改判得失（研究原判 Brier − 终判 Brier，×100）。"""
    days = sorted(p.parent.name for p in (Path(data_dir) / "jczq" / "daily").glob(f"*/{LEDGER}"))
    scored, gain, pending, worst = 0, 0.0, 0, None
    by_reason: dict[str, dict] = {}
    for day in days:
        for row in build_signals(day=day, data_dir=data_dir):
            if not row["override"]:
                continue
            reason = str(row["override"].get("reason") or "legacy_tilt")
            bucket = by_reason.setdefault(reason, {"scored": 0, "gain": 0.0, "pending": 0})
            if "brier_research" not in row:
                pending += 1
                bucket["pending"] += 1
                continue
            delta = (row["brier_research"] - row["brier_final"]) * 100
            scored += 1
            gain += delta
            bucket["scored"] += 1
            bucket["gain"] = round(bucket["gain"] + delta, 2)
            if worst is None or delta < worst[1]:
                worst = (f"{day} {row['key']} {row['name']}", delta)
    return {"days": len(days), "scored": scored, "gain": round(gain, 2), "pending": pending,
            "worst": worst, "by_reason": by_reason}


def _experiments(invoke) -> list[str]:
    code, output = invoke(["rsi", "status"])
    if code != 0:
        return []
    keep = ("F9 ", "F10", "F11", "R1 ")
    return [line.strip() for line in output.splitlines() if line.startswith(keep)]


def _brake_line(data_dir: Path, now: datetime) -> str:
    try:   # 实质余量（含待结票），与预审、各页同一个 month_brake（2026-10-30 Task 10.1）
        from nutmeg.decision.precheck import brake_line

        return brake_line(data_dir, now.date().isoformat())
    except Exception as exc:  # noqa: BLE001
        return f"账房缺席：{exc!r}"[:120]


def _zucai_panel(data_dir: Path, now: datetime, errors: list[str]) -> dict:
    """在售期的初稿摘要 + 已登记足彩票（都带审票行）；没有在售期 → {}。"""
    from nutmeg.decision.day_brief import _draft_doc, _draft_summary, _slips, current_issue

    zdir = data_dir / "zucai"
    issue = current_issue(zdir, now=now) if zdir.exists() else None
    if not issue:
        return {}
    return {"issue": issue,
            "draft": _draft_summary(_draft_doc(data_dir, zdir, issue, errors, build=True)),
            "slips": _slips(data_dir, errors, issue=issue)}


def build_verdict(*, day: str, data_dir: Path, now: datetime, invoke=None) -> dict:
    from nutmeg.decision.day_brief import _slips
    from nutmeg.decision.jczq_combos import enumerate_combos, judgment_legs
    from nutmeg.decision.review import VETO_RATIO

    data_dir = Path(data_dir)
    rows = build_signals(day=day, data_dir=data_dir)
    upcoming = [r for r in rows if not r["kickoff"] or r["kickoff"] > now.isoformat()]
    jczq_rows = [r for r in rows if not r["key"].startswith("足彩")]
    zucai_rows = [r for r in rows if r["key"].startswith("足彩")]
    try:
        legs = judgment_legs(day=day, jczq_dir=data_dir / "jczq", now=now.isoformat())
        # 周末 23 场板全枚举会被 SIGKILL（10-25）→ 裁腿
        combos = enumerate_combos(legs, top=5, max_pool=12)
    except (OSError, ValueError, KeyError):
        legs, combos = [], []
    for c in combos:
        c["veto"] = c.get("return_per_yuan") is not None and c["return_per_yuan"] < VETO_RATIO
    moved = [r for r in rows if r["final"] and max(
        abs(r["final"][k] - r["prior"][k]) for k in r["prior"]) >= 0.02]
    errors: list[str] = []
    return {
        "brake": _brake_line(data_dir, now),
        "jczq_slips": _slips(data_dir, errors, date=day),
        "zucai_panel": _zucai_panel(data_dir, now, errors),
        "errors": errors,
        "day": day,
        "edition": _edition(now),
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
        "counts": {
            "matches": len(rows), "upcoming": len(upcoming),
            "researched": sum(1 for r in rows if r["research"]),
            "moved": len(moved), "overrides": sum(1 for r in rows if r["override"]),
            "disagreements": sum(1 for r in rows if r["disagreement"]),
        },
        "review": [r for r in rows if r["override"] or r["disagreement"]],
        "jczq": sorted(jczq_rows, key=lambda r: r["kickoff"] or ""),
        "zucai": zucai_rows,
        "legs": legs,
        "combos": combos,
        "no_edge": bool(legs) and not any(
            max(abs(leg["belief"][k] - leg["prior"][k]) for k in leg["belief"]) >= 0.005
            for leg in legs),
        "ledger": _ledger_totals(data_dir),
        "experiments": _experiments(invoke) if invoke else [],
    }


def render_verdict(data: dict) -> str:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)),
                      autoescape=select_autoescape(["html"]))

    def pct(dist, key):
        return f"{dist[key] * 100:.1f}" if dist else "—"

    env.filters["pct"] = pct
    return env.get_template("verdict.html").render(**data)


def write_verdict(*, day: str, data_dir: Path, now: datetime | None = None, invoke=None) -> Path:
    now = now or datetime.now().astimezone()
    data = build_verdict(day=day, data_dir=data_dir, now=now, invoke=invoke)
    day_dir = Path(data_dir) / "jczq" / "daily" / day
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / "verdict.html"
    path.write_text(render_verdict(data), encoding="utf-8")
    with (day_dir / "verdict-log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": data["generated_at"], "edition": data["edition"],
                             **data["counts"]}, ensure_ascii=False) + "\n")
    return path
