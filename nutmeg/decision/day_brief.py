"""当日报告的事实层与判断层（设计 §6.1–6.2）。零 LLM；只读既有文件；每块独立降级。

⛔判断层只原样引用已有 Read 与标签，不在这里加任何看法；逻辑层（§6.3）在 P4。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.decision.day_audit import audit_defaults
from nutmeg.decision.day_paths import BRIEF, BRIEF_MD, day_dir, jczq_day_dir, zucai_dir

MOVE_EPS_PP = 0.05
"""与 F9 同一冻结常量：max|belief−prior| 超过它才算「拨动」。"""

BJ = timezone(timedelta(hours=8))
FACES = ("home", "draw", "away")


def _load(path: Path, errors: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"缺 {path.name}")
    except ValueError as exc:
        errors.append(f"{path.name} 不是合法 JSON: {exc}")
    return None


def _optional(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def _parse_dt(value) -> datetime | None:
    """ISO 8601 或旧格式 `YYYY-MM-DD HH:MM`；无时区一律按北京时间。"""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt.replace(tzinfo=BJ) if dt.tzinfo is None else dt


def _pp(a: dict | None, b: dict | None) -> float:
    if not a or not b:
        return 0.0
    return round(max(abs(float(a.get(k, 0)) - float(b.get(k, 0))) for k in FACES) * 100, 1)


def _drift_scalar(value) -> float | None:
    """price-band 的 drift_pp 实际是按面的 dict；取 |位移| 最大的那一面（保号）。"""
    if isinstance(value, dict):
        vals = [float(v) for v in value.values() if isinstance(v, (int, float))]
        return round(max(vals, key=abs), 1) if vals else None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _argmax(p: dict | None) -> str | None:
    if not p:
        return None
    return max(FACES, key=lambda k: float(p.get(k, 0)))


def _ladder(read: dict | None) -> str:
    """判决表阶梯位置，只从 belief/prior 算得出来的三档；降格需要 confidence 变化史，不在此推断。"""
    if read is None:
        return "未判"
    if read["moved_pp"] <= MOVE_EPS_PP:
        return "跟市场"
    return "翻面" if _argmax(read["belief"]) != _argmax(read["prior"]) else "偏移"


def _strength(teams: dict | None, name: str | None) -> dict | None:
    if not teams or not name or name not in teams:
        return None
    t = teams[name]
    return {k: t.get(k) for k in ("n", "record", "resid_shrunk", "market_strength", "last5_resid")}


def _research(day: Path, code: str, run_status: dict[str, str], kickoff: str | None) -> dict:
    doc = _optional(day / f"research-{code}.json")
    rejected = (day / f"research-{code}.rejected.json").exists()
    status = run_status.get(code) or ("rejected" if rejected else ("done" if doc else "none"))
    out = {"status": status, "captured_at": None, "summary": None, "anchor_side": None,
           "hole_location": None, "schedule": None, "prospective": None}
    if doc:
        out.update({k: doc.get(k) for k in
                    ("captured_at", "summary", "anchor_side", "hole_location", "schedule")})
        captured, kick = _parse_dt(doc.get("captured_at")), _parse_dt(kickoff)
        if captured and kick:
            out["prospective"] = captured < kick
    return out


LABEL_KEYS = ("judgment_tier", "face_status", "anchor_integrity", "license_questions", "_d3",
              "directional_flags", "nondirectional_flags", "crash_markers", "precedents",
              "team_tags", "tracking_tags", "confidence")


def _jczq(data_dir: Path, date: str, errors: list[str]) -> dict:
    day = jczq_day_dir(data_dir, date)
    board = _load(day / "jczq-legs-base.json", errors)
    legs: dict = (board or {}).get("legs") or {}
    reads = {r.get("match_id"): r for r in (_optional(day / "reads.json") or [])
             if isinstance(r, dict)}
    balance = {r.get("code"): r
               for r in ((_optional(day / "balance.json") or {}).get("rows") or [])}
    run = _optional(day / f"research-run-{date}.json") or {}
    run_status = {m.get("code"): m.get("status") for m in run.get("matches") or []}
    closing = _optional(day / "closing_odds.json") or {}
    teams = (_optional(data_dir / "analytics" / "team_strength.json") or {}).get("teams")
    cards = []
    for code, leg in sorted(legs.items(), key=lambda kv: str(kv[1].get("kickoff_bj") or "")):
        band = _optional(day / f"price-band-{code}.json") or {}
        close = closing.get(code) or {}
        raw_read = reads.get(leg.get("match_id"))
        read = None
        if raw_read:
            prior = raw_read.get("prior") or (balance.get(code) or {}).get("prior")
            belief = raw_read.get("belief") or (balance.get(code) or {}).get("belief")
            read = {
                "read_id": raw_read.get("read_id"), "judge": raw_read.get("judge"),
                "status": raw_read.get("status"), "judgment_tier": raw_read.get("judgment_tier"),
                "confidence": raw_read.get("confidence"), "prior": prior, "belief": belief,
                "moved_pp": _pp(prior, belief),
            }
        cards.append({
            "code": code, "name": leg.get("name"), "competition": leg.get("competition"),
            "kickoff_bj": leg.get("kickoff_bj"), "home_team": leg.get("home_team"),
            "away_team": leg.get("away_team"),
            "market": {
                "fair": leg.get("fair"), "hhad_line": leg.get("hhad_line"),
                "fair_open": band.get("fair_open"),
                "drift_pp": _drift_scalar(band.get("drift_pp")),
                "book_disagreement_pp": band.get("book_disagreement_pp"),
                "closing_books": close.get("book_count"),
                "closing_updated_at": close.get("updated_at_max"),
            },
            "strength": {"home": _strength(teams, leg.get("home_team")),
                         "away": _strength(teams, leg.get("away_team"))},
            "research": _research(day, code, run_status, leg.get("kickoff_bj")),
            "labels": {k: leg.get(k) for k in LABEL_KEYS},
            "read": read,
            "ladder": _ladder(read),
        })
        cards[-1]["audit"] = audit_defaults(cards[-1])
    counts = {
        "matches": len(cards),
        "deep_research": sum(1 for c in cards
                             if c["labels"]["judgment_tier"] == "deep_research"),
        "price_only": sum(1 for c in cards if c["labels"]["judgment_tier"] == "price_only"),
        "drafts": sum(1 for c in cards if c["read"] and c["read"]["status"] == "draft"),
    }
    return {"matches": cards, "counts": counts}


def current_issue(zdir: Path, *, now: datetime) -> str | None:
    """在售期：截止在 now 之后的最大期号；都过了就取最大期号；没有 issue 文件则 None。"""
    candidates: list[tuple[str, str | None]] = []
    for path in zdir.glob("*-issue.json"):
        doc = _optional(path) or {}
        issue = str(doc.get("issue_id") or path.name.split("-")[0])
        candidates.append((issue, doc.get("sale_deadline") or doc.get("sale_stop")))
    if not candidates:
        return None
    ahead = []
    for issue, deadline in candidates:
        parsed = _parse_dt(deadline)
        if parsed and parsed > now:
            ahead.append(issue)
    return max(ahead) if ahead else max(issue for issue, _ in candidates)


def _zucai(data_dir: Path, now: datetime) -> dict:
    zdir = zucai_dir(data_dir)
    issue = current_issue(zdir, now=now) if zdir.exists() else None
    out = {"issue": issue, "sale_deadline": None, "prep": {}, "tiers": None,
           "frontier": {}, "plan": None}
    if not issue:
        return out
    meta = _optional(zdir / f"{issue}-issue.json") or {}
    out["sale_deadline"] = meta.get("sale_deadline") or meta.get("sale_stop")
    for slot in ("morning", "afternoon", "revision"):
        doc = _optional(zdir / f"{issue}-prep-{slot}.json")
        if doc:
            out["prep"][slot] = {k: doc.get(k) for k in ("captured_at", "n_matches")}
    out["tiers"] = _optional(zdir / f"{issue}-tiers.json")
    for channel in ("renjiu", "shengfucai"):
        doc = _optional(zdir / f"{issue}-frontier-{channel}.json")
        if doc:
            out["frontier"][channel] = {
                "strict_max_p": doc.get("strict_max_p"),
                "points": [{k: p.get(k) for k in ("k", "p_all", "notes", "stake_yuan", "shape")}
                           | {"narrowings": len(p.get("narrowings") or [])}
                           for p in (doc.get("points") or [])[:8]],
            }
    return out


def _rsi(data_dir: Path, date: str) -> dict | None:
    doc = _optional(data_dir / "analytics" / "rsi-loop" / f"{date}.json")
    if not doc:
        return None
    return {k: doc.get(k)
            for k in ("human_actions", "proposals", "verdicts", "grades", "failed_steps")}


def _factors(root: Path, rsi: dict | None) -> list[dict]:
    doc = _optional(root / "experiments" / "factors.json") or {}
    decisions = {p.get("factor_id"): p.get("decision")
                 for p in ((rsi or {}).get("proposals") or [])}
    return [
        {"factor_id": f.get("factor_id"), "layer": f.get("layer"),
         "current_weight_pp": f.get("current_weight_pp"), "rule_name": f.get("rule_name"),
         "decision": decisions.get(f.get("factor_id"), "hold")}
        for f in doc.get("factors") or []
    ]


def compile_brief(*, data_dir: Path, date: str, root: Path, now: datetime) -> dict:
    errors: list[str] = []
    jczq = _jczq(Path(data_dir), date, errors)
    rsi = _rsi(Path(data_dir), date)
    return {
        "date": date,
        "generated_at": now.isoformat(timespec="seconds"),
        "jczq": jczq,
        "zucai": _zucai(Path(data_dir), now),
        "rsi": rsi,
        "factors": _factors(Path(root), rsi),
        "errors": errors,
    }


def _fmt_fair(fair: dict | None) -> str:
    if not fair:
        return "—"
    return "/".join(f"{float(fair.get(k, 0)) * 100:.0f}" for k in FACES)


def render_brief_md(brief: dict) -> str:
    lines = [f"# 当日报告 · {brief['date']}", "",
             f"生成 {brief['generated_at']} · 事实层与判断层为机器编译；"
             "本报告只解释已产生的判断，不产生新判断。", ""]
    c = brief["jczq"]["counts"]
    lines += [f"## 竞彩 {c['matches']} 场（深研 {c['deep_research']} / 跟市场 {c['price_only']}"
              f" / 草稿 Read {c['drafts']}）", "",
              "| 场 | 开球 | 对阵 | fair 3/1/0 | 位移pp | 研究 | Read | 阶梯 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for m in brief["jczq"]["matches"]:
        read = m["read"] or {}
        drift = m["market"]["drift_pp"]
        lines.append(
            f"| {m['code']} | {(m['kickoff_bj'] or '')[11:16]} | {m['name']} | "
            f"{_fmt_fair(m['market']['fair'])} | {drift if drift is not None else '—'} | "
            f"{m['research']['status']} | "
            f"{read.get('judge') or '—'}/{read.get('status') or '—'} | {m['ladder']} |"
        )
    z = brief["zucai"]
    lines += ["", f"## 传统足彩 {z['issue'] or '（无在售期）'}", ""]
    if z["issue"]:
        lines.append(f"- 截止 {z['sale_deadline'] or '未知'}；"
                     f"备料槽 {', '.join(z['prep']) or '无'}")
        if z["tiers"]:
            lines.append(f"- 风向 {json.dumps(z['tiers'].get('wind'), ensure_ascii=False)}；"
                         f"定级 hash {z['tiers'].get('tiers_hash')}")
        for channel, doc in z["frontier"].items():
            top = doc["points"][0] if doc["points"] else None
            lines.append(
                f"- {channel} 前沿 {len(doc['points'])} 点，strict 地板 P={doc['strict_max_p']}"
                + (f"；k0 P={top['p_all']} 注数 {top['notes']} ¥{top['stake_yuan']}"
                   if top else "")
            )
    lines += ["", "## RSI", ""]
    if brief["rsi"]:
        lines += [f"- {a}" for a in brief["rsi"]["human_actions"] or []] or ["- 无待人决定"]
        if brief["rsi"]["failed_steps"]:
            lines.append(f"- ⚠️闭环失败步骤：{', '.join(brief['rsi']['failed_steps'])}")
    else:
        lines.append("- 今日闭环报告缺席")
    if brief["errors"]:
        lines += ["", "## 缺席的输入", ""] + [f"- {e}" for e in brief["errors"]]
    return "\n".join(lines) + "\n"


def write_brief(data_dir: Path | str, date: str, brief: dict) -> Path:
    out = day_dir(data_dir, date)
    out.mkdir(parents=True, exist_ok=True)
    (out / BRIEF).write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / BRIEF_MD).write_text(render_brief_md(brief), encoding="utf-8")
    return out / BRIEF
