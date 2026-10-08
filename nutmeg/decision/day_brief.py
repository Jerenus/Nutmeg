"""当日报告的事实层与判断层（设计 §6.1–6.2）。零 LLM；只读既有文件；每块独立降级。

⛔判断层只原样引用已有 Read 与标签，不在这里加任何看法；逻辑层（§6.3）在 P4。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from nutmeg.decision.bj_time import parse_bj
from nutmeg.decision.board_rows import fmt_stance, jczq_rows
from nutmeg.decision.day_paths import BRIEF, BRIEF_MD, day_dir, jczq_day_dir, zucai_dir
from nutmeg.decision.faces import FACES
from nutmeg.decision.files import read_json

MOVE_EPS_PP = 0.05
"""与 F9 同一冻结常量：max|belief−prior| 超过它才算「拨动」。"""



def _load(path: Path, errors: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"缺 {path.name}")
    except ValueError as exc:
        errors.append(f"{path.name} 不是合法 JSON: {exc}")
    return None


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
    """判决表阶梯位置，只从 belief/prior 算得出来的三档；降格需要 confidence 变化史，不在此推断。

    stance 存在且 why_not_market == "none" 且未拨（moved_pp <= MOVE_EPS_PP）时落在下面
    `moved_pp` 分支即得 "跟市场"——既有逻辑已覆盖，这里不需要额外读 stance。
    """
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


def _research(day: Path, code: str, doc: dict | None, run_status: dict[str, str],
              kickoff: str | None) -> dict:
    rejected = (day / f"research-{code}.rejected.json").exists()
    status = run_status.get(code) or ("rejected" if rejected else ("done" if doc else "none"))
    out = {"status": status, "captured_at": None, "summary": None, "anchor_side": None,
           "hole_location": None, "schedule": None, "prospective": None}
    if doc:
        out.update({k: doc.get(k) for k in
                    ("captured_at", "summary", "anchor_side", "hole_location", "schedule")})
        captured, kick = parse_bj(doc.get("captured_at")), parse_bj(kickoff)
        if captured and kick:
            out["prospective"] = captured < kick
    return out


LABEL_KEYS = ("judgment_tier", "face_status", "anchor_integrity", "license_questions", "_d3",
              "directional_flags", "nondirectional_flags", "crash_markers", "precedents",
              "team_tags", "tracking_tags", "confidence")


def _jczq(data_dir: Path, date: str, errors: list[str]) -> dict:
    day = jczq_day_dir(data_dir, date)
    board = _load(day / "jczq-legs-base.json", errors)
    rows = jczq_rows(data_dir, date, legs=(board or {}).get("legs") or {})
    balance = {r.get("code"): r
               for r in ((read_json(day / "balance.json") or {}).get("rows") or [])}
    run = read_json(day / f"research-run-{date}.json") or {}
    run_status = {m.get("code"): m.get("status") for m in run.get("matches") or []}
    teams = (read_json(data_dir / "analytics" / "team_strength.json") or {}).get("teams")
    cards = []
    for row in sorted(rows, key=lambda r: str(r["leg"].get("kickoff_bj") or "")):
        code, leg, band, close = row["code"], row["leg"], row["band"], row["closing"]
        raw_read = row["read"]
        read = None
        if raw_read:
            prior = raw_read.get("prior") or (balance.get(code) or {}).get("prior")
            belief = raw_read.get("belief") or (balance.get(code) or {}).get("belief")
            read = {
                "read_id": raw_read.get("read_id"), "judge": raw_read.get("judge"),
                "status": raw_read.get("status"), "judgment_tier": raw_read.get("judgment_tier"),
                "confidence": raw_read.get("confidence"), "prior": prior, "belief": belief,
                "moved_pp": _pp(prior, belief),
                "tiers": raw_read.get("adjustment_evidence_tiers") or [],
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
            "research": _research(day, code, row["research"], run_status, leg.get("kickoff_bj")),
            "labels": {k: leg.get(k) for k in LABEL_KEYS},
            "read": read,
            "stance": raw_read.get("stance") if raw_read else None,
            "ladder": _ladder(read),
        })
    counts = {
        "matches": len(cards),
        "deep_research": sum(1 for c in cards
                             if c["labels"]["judgment_tier"] == "deep_research"),
        "price_only": sum(1 for c in cards if c["labels"]["judgment_tier"] == "price_only"),
        "drafts": sum(1 for c in cards if c["read"] and c["read"]["status"] == "draft"),
    }
    brief_counts = None
    if board:
        try:
            from nutmeg.decision.judgment_brief import jczq_brief

            b = jczq_brief(data_dir, date, rows=rows)
            brief_counts = {k: b[k] for k in ("n", "researched", "favs", "singles_open")}
        except Exception:  # noqa: BLE001
            brief_counts = None
    return {"matches": cards, "counts": counts, "brief": brief_counts,
            "slips": _slips(data_dir, date=date)}


def _issue_candidates(zdir: Path) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = []
    for path in zdir.glob("*-issue.json"):
        doc = read_json(path) or {}
        issue = str(doc.get("issue_id") or path.name.split("-")[0])
        out.append((issue, doc.get("sale_deadline") or doc.get("sale_stop")))
    return out


def current_issue(zdir: Path, *, now: datetime) -> str | None:
    """在售期：截止在 now 之后的最大期号；没有在售期 → None。

    2026-10-01 修正：原先「都过了就取最大期号」让面板在假期里连续三天把已开奖的 26134
    当在售期展示（连前沿都照旧打印）。结算路径要的是「最近一期」，用 `latest_issue`。
    """
    ahead = [issue for issue, deadline in _issue_candidates(zdir)
             if (parsed := parse_bj(deadline)) and parsed > now]
    return max(ahead) if ahead else None


def latest_issue(zdir: Path) -> str | None:
    """最近一期（不管截没截止）：结算/grade-rx 用。"""
    candidates = _issue_candidates(zdir)
    return max(issue for issue, _ in candidates) if candidates else None


def _draft_doc(data_dir: Path, zdir: Path, issue: str, *, build: bool) -> dict | None:
    """`<期>-draft.json`；legs-base 比它新（或它不存在）且允许构建时现做一份（机器初稿不省略）。"""
    legs_base = zdir / f"{issue}-legs-base.json"
    draft = zdir / f"{issue}-draft.json"
    if not legs_base.exists():
        return None
    stale = not draft.exists() or draft.stat().st_mtime < legs_base.stat().st_mtime
    if stale and build:
        try:
            from nutmeg.decision.zucai_draft import build_draft

            return build_draft(data_dir, issue, write=True)
        except Exception:  # noqa: BLE001 —— 初稿失败只让这一块缺席
            return read_json(draft)
    return read_json(draft)


def _draft_summary(doc: dict | None) -> list[dict]:
    rows = []
    for c in (doc or {}).get("candidates") or []:
        if not c.get("faces"):
            continue
        rv = c.get("review") or {}
        detail = rv.get("detail") or {}
        rows.append({
            "label": c["label"], "channel": c["channel"], "cap_yuan": c.get("cap_yuan"),
            "stake_yuan": c["stake_yuan"], "notes": c["notes"], "p_all": c["p_all"],
            "ratio": rv.get("ratio"), "ratio_market": detail.get("ratio_market"),
            "premium": detail.get("premium"), "vetoed": bool(rv.get("vetoed")),
            "lines": rv.get("lines") or [],
            "faces": " ".join(f"{no}:{fs}" for no, fs in c["faces"].items()),
            "dropped": c.get("dropped") or [], "downgrades": len(c.get("downgrades") or []),
        })
    return rows


def _slips(data_dir: Path, *, issue: str | None = None, date: str | None = None) -> list[dict]:
    """已登记的票（实购优先排前）+ 审票行；登记簿缺失 → []。"""
    try:
        from nutmeg.decision.betslip import load_slips
        from nutmeg.decision.review import prize_model
        from nutmeg.decision.review_runner import slip_summary

        slips = load_slips(data_dir)
        picked = [s for s in slips if (issue and s.issue == issue)
                  or (date and s.channel == "jczq" and str(s.placed_at)[:10] == date)]
        model = prize_model(data_dir)
        return [slip_summary(s, data_dir, slips=slips, model=model)
                for s in sorted(picked, key=lambda s: (not s.purchased, s.placed_at))]
    except Exception:  # noqa: BLE001
        return []


def _zucai(data_dir: Path, now: datetime, *, build_draft: bool = True) -> dict:
    zdir = zucai_dir(data_dir)
    issue = current_issue(zdir, now=now) if zdir.exists() else None
    out = {"issue": issue, "sale_deadline": None, "prep": {}, "brief": None, "draft": [],
           "slips": []}
    if not issue:
        return out
    meta = read_json(zdir / f"{issue}-issue.json") or {}
    out["sale_deadline"] = meta.get("sale_deadline") or meta.get("sale_stop")
    for slot in ("morning", "afternoon", "revision"):
        doc = read_json(zdir / f"{issue}-prep-{slot}.json")
        if doc:
            out["prep"][slot] = {k: doc.get(k) for k in ("captured_at", "n_matches")}
    if (zdir / f"{issue}-legs-base.json").exists():
        try:
            from nutmeg.decision.judgment_brief import zucai_brief

            b = zucai_brief(data_dir, issue)
            out["brief"] = {"n": b["n"], "favs": b["favs"],
                            "stanced": sum(1 for r in b["rows"] if r["stance"] != "—"),
                            "faces": {r["no"]: r["faces"] for r in b["rows"]}}
        except Exception:  # noqa: BLE001
            out["brief"] = None
    out["draft"] = _draft_summary(_draft_doc(data_dir, zdir, issue, build=build_draft))
    out["slips"] = _slips(data_dir, issue=issue)
    return out


def _rsi(data_dir: Path, date: str) -> dict | None:
    doc = read_json(data_dir / "analytics" / "rsi-loop" / f"{date}.json")
    if not doc:
        return None
    return {k: doc.get(k)
            for k in ("human_actions", "proposals", "verdicts", "grades", "failed_steps")}


def _factors(root: Path, rsi: dict | None) -> list[dict]:
    doc = read_json(root / "experiments" / "factors.json") or {}
    decisions = {p.get("factor_id"): p.get("decision")
                 for p in ((rsi or {}).get("proposals") or [])}
    return [
        {"factor_id": f.get("factor_id"), "layer": f.get("layer"),
         "current_weight_pp": f.get("current_weight_pp"), "rule_name": f.get("rule_name"),
         "decision": decisions.get(f.get("factor_id"), "hold")}
        for f in doc.get("factors") or []
    ]


def _account(data_dir: Path, now: datetime) -> dict:
    """账房一行（宪法 §4 月度止损）：本月净 vs 空仓、止损余量；记分牌缺失 → 缺席。"""
    try:
        from nutmeg.decision.bankroll import brake_state, status_line

        state = brake_state(data_dir, now.date())
        return {"line": status_line(state), "net": state["net"], "tripped": state["tripped"],
                "month": state["month"]}
    except Exception as exc:  # noqa: BLE001
        return {"line": f"账房缺席：{exc!r}"[:120], "net": None, "tripped": None, "month": None}


def compile_brief(*, data_dir: Path, date: str, root: Path, now: datetime,
                  build_draft: bool = True) -> dict:
    errors: list[str] = []
    jczq = _jczq(Path(data_dir), date, errors)
    rsi = _rsi(Path(data_dir), date)
    return {
        "date": date,
        "generated_at": now.isoformat(timespec="seconds"),
        "account": _account(Path(data_dir), now),
        "jczq": jczq,
        "zucai": _zucai(Path(data_dir), now, build_draft=build_draft),
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
    account = brief.get("account") or {}
    if account.get("line"):
        lines += [f"**账房**：{account['line']}", ""]
    c = brief["jczq"]["counts"]
    lines += [f"## 竞彩 {c['matches']} 场（深研 {c['deep_research']} / 跟市场 {c['price_only']}"
              f" / 草稿 Read {c['drafts']}）", ""]
    jb = brief["jczq"].get("brief")
    if jb:
        lines += [f"初判包：研究/改判 {jb['researched']} · ≥0.70 大热 {jb['favs']} · 开单关 "
                  f"{jb['singles_open']}（`nutmeg judgment brief --day`；竞彩不出票，方案由人出）",
                  ""]
    lines += [
              "| 场 | 开球 | 对阵 | fair 3/1/0 | 位移pp | 研究 | Read | 表态 | 阶梯 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for m in brief["jczq"]["matches"]:
        read = m["read"] or {}
        drift = m["market"]["drift_pp"]
        lines.append(
            f"| {m['code']} | {(m['kickoff_bj'] or '')[11:16]} | {m['name']} | "
            f"{_fmt_fair(m['market']['fair'])} | {drift if drift is not None else '—'} | "
            f"{m['research']['status']} | "
            f"{read.get('judge') or '—'}/{read.get('status') or '—'} | "
            f"{fmt_stance(m.get('stance'))} | {m['ladder']} |"
        )
    logic_lines = [f"- **{m['code']}** {m['logic']['text']}" for m in brief["jczq"]["matches"]
                   if isinstance(m.get("logic"), dict) and m["logic"].get("status") == "ok"]
    if logic_lines:
        lines += ["", "### 为什么落在这一格（claude -p 撰稿，只解释不判断）", ""] + logic_lines
    lines += _slip_lines("已登记竞彩票", brief["jczq"].get("slips") or [])
    z = brief["zucai"]
    lines += ["", f"## 传统足彩 {z['issue'] or '（无在售期）'}", ""]
    if z["issue"]:
        lines.append(f"- 截止 {z['sale_deadline'] or '未知'}；"
                     f"备料槽 {', '.join(z['prep']) or '无'}")
        zb = z.get("brief")
        if zb:
            lines.append(f"- 初判：{zb['n']} 场｜≥0.70 大热 {zb['favs']}｜研究表态 {zb['stanced']}"
                         "（`nutmeg judgment brief --issue`）")
        for d in z.get("draft") or []:
            lines += _draft_lines(d)
        if not z.get("draft"):
            lines.append("- 初稿：未出（缺 legs-base，先跑 B4）" if not zb
                         else "- 初稿：未出（构建失败，手跑 `nutmeg judgment draft --issue`）")
        lines += _slip_lines("已登记足彩票", z.get("slips") or [], indent="- ")
    lines += ["", "## RSI", ""]
    if brief["rsi"]:
        lines += [f"- {a}" for a in brief["rsi"]["human_actions"] or []] or ["- 无待人决定"]
        if brief["rsi"]["failed_steps"]:
            lines.append(f"- ⚠️闭环失败步骤：{', '.join(brief['rsi']['failed_steps'])}")
        primary = [
            g["line"] for g in brief["rsi"].get("grades") or []
            if any(f"--exp {exp} " in str(g.get("cmd") or "") + " " for exp in ("F14", "F10"))
        ]
        if primary:
            lines += ["- 主指标：" + " ｜ ".join(primary)]
    else:
        lines.append("- 今日闭环报告缺席")
    if brief["errors"]:
        lines += ["", "## 缺席的输入", ""] + [f"- {e}" for e in brief["errors"]]
    return "\n".join(lines) + "\n"


def _draft_lines(d: dict) -> list[str]:
    ch = {"renjiu": "任九", "shengfucai": "胜负彩"}.get(d["channel"], d["channel"])
    head = (f"- **{d['label']}·{ch}** ¥{d['stake_yuan']:,}（{d['notes']} 注，帽 ¥{d['cap_yuan']}）"
            f"｜P(全对) {d['p_all'] * 100:.1f}%")
    if d.get("ratio") is not None:
        head += f"｜期望回报 {d['ratio']:.2f}"
        if d.get("ratio_market") is not None and d.get("premium") is not None:
            head += f"（市场 {d['ratio_market']:.2f} × 判断溢价 {d['premium']:.2f}）"
    head += "｜审票 " + ("⛔否决" if d["vetoed"] else "可出")
    out = [head, f"  票面 `{d['faces']}`"]
    if d.get("dropped"):
        out.append(f"  丢场 {'、'.join(d['dropped'])}" + (f"；降档 {d['downgrades']} 步"
                                                       if d.get("downgrades") else ""))
    elif d.get("downgrades"):
        out.append(f"  降档 {d['downgrades']} 步")
    out += [f"  {line}" for line in d.get("lines") or [] if line.startswith(("⛔", "⚠️"))]
    return out


def _slip_lines(title: str, slips: list[dict], *, indent: str = "- ") -> list[str]:
    if not slips:
        return []
    out = ["", f"### {title}", ""] if indent == "- " and title.startswith("已登记竞彩") else []
    for s in slips:
        tag = "" if s["purchased"] else "（试玩）"
        p = f"｜P {s['p_all'] * 100:.1f}%" if s.get("p_all") is not None else ""
        ratio = f"｜期望回报 {s['ratio']:.2f}" if s.get("ratio") is not None else ""
        out.append(f"{indent}{s['slip_id']}{tag} {s['channel']} ¥{s['stake_yuan']:,}"
                   f"{p}{ratio}｜审票 {'⛔否决' if s['vetoed'] else '可出'}｜`{s['text']}`")
        out += [f"  {line}" for line in s.get("lines") or [] if line.startswith(("⛔", "⚠️"))]
    return out


def write_brief(data_dir: Path | str, date: str, brief: dict) -> Path:
    out = day_dir(data_dir, date)
    out.mkdir(parents=True, exist_ok=True)
    (out / BRIEF).write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / BRIEF_MD).write_text(render_brief_md(brief), encoding="utf-8")
    return out / BRIEF
