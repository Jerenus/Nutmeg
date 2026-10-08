"""信号面板（Jun 2026-09-27）：一次完整分析后，把每场被捕捉到的信号摆给人工裁决。

「决策几乎没有大的方向改动，方向上的改动只能通过捕捉到的信号来帮助我做决策。」
所以面板只做搬运与算术，不做判断：
- 市场价与开盘→当前漂移（price-band）；
- 研究**原判**（改判账里的原拨动优先，其次研究文件本身）：拨动面与证据档、强弱天平、
  弱方路径强度、研究自标「未被定价」的事件、方向/无方向旗；
- 主循环**终判**与改判理由（被砍掉的信号单列置顶）；
- 同一场比赛另一渠道的研究（竞彩 ↔ 足彩，按对号表配对）与分歧；
- 有赛果时：研究原判与终判各自的 Brier（改判得失，正=改判帮了忙）。
"""
from __future__ import annotations

from pathlib import Path

from nutmeg.decision.board_rows import jczq_rows
from nutmeg.decision.faces import FACE_OF, SHORT_ZH
from nutmeg.decision.files import read_json
from nutmeg.decision.match_results import board_outcomes
from nutmeg.decision.overrides import load_overrides
from nutmeg.decision.scoring import brier
from nutmeg.decision.stance import research_belief
from nutmeg.decision.zucai_identity import closing_issues, load_channel_map


def _ruling_note(doc: dict | None) -> str | None:
    """main_loop_rulings 有对象与列表两种历史格式（26133 流程写成列表）。"""
    rulings = (doc or {}).get("main_loop_rulings")
    if isinstance(rulings, list):
        rulings = next((r for r in reversed(rulings) if isinstance(r, dict)), None)
    if not isinstance(rulings, dict):
        return None
    return (rulings.get("note") or rulings.get("why") or rulings.get("ruling")
            or rulings.get("summary"))


def _research_doc(path: Path) -> dict | None:
    """研究文件；旧格式（非对象）当作没有研究，不让面板整张崩掉。"""
    doc = read_json(path)
    return doc if isinstance(doc, dict) else None


def _shift_pp(belief: dict, prior: dict) -> dict:
    return {k: round((belief[k] - prior[k]) * 100, 1) for k in ("home", "draw", "away")}


def _research_view(doc: dict, prior: dict, ledger_row: dict | None) -> dict:
    stance = doc.get("stance") or {}
    original_tilt = ledger_row["original_tilt"] if ledger_row else stance.get("tilt")
    belief, _ = research_belief(prior, original_tilt)
    sb = doc.get("strength_balance") or {}
    tiers = [
        f"{e.get('tier')}:{e.get('kind')}{e.get('pp')}"
        for e in ((original_tilt or {}).get("evidence") or []) if isinstance(e, dict)
    ]
    return {
        "face": stance.get("face"),
        "structure": stance.get("structure"),
        "belief": belief,
        "shift": _shift_pp(belief, prior),
        "evidence": tiers,
        "verdict": sb.get("verdict"),
        "underdog": (sb.get("underdog_path") or {}).get("strength"),
        "unpriced": [e.get("event", "")[:40] for e in sb.get("events") or []
                     if isinstance(e, dict) and e.get("priced_in") is False],
        "flags": [f[0] if isinstance(f, list) else f for f in doc.get("directional_flags") or []]
        + list(doc.get("nondirectional_flags") or []),
        "summary": str(doc.get("summary") or "")[:260],
        "falsifier": stance.get("falsifier"),
        "routes": [str(x)[:40] for x in (sb.get("underdog_path") or {}).get("routes") or []][:3],
        "confidence": doc.get("confidence"),
    }


def _disagreement(a: dict, b: dict) -> list[str]:
    out = []
    if a["face"] and b["face"] and a["face"] != b["face"]:
        out.append(f"首选面 {a['face']} vs {b['face']}")
    if a["structure"] and b["structure"] and (a["structure"] == "single") != (
        b["structure"] == "single"
    ):
        out.append(f"结构 {a['structure']} vs {b['structure']}")
    for key in ("home", "draw", "away"):
        x, y = a["shift"][key], b["shift"][key]
        if abs(x - y) >= 3:
            out.append(f"{SHORT_ZH[key]}拨动 {x:+.1f} vs {y:+.1f}pp")
    return out


def _score(row: dict) -> float:
    research = row["research"]
    score = max(abs(v) for v in research["shift"].values()) if research else 0.0
    score += 3 * len(row["disagreement"])
    score += len(research["unpriced"]) if research else 0
    if row["override"]:
        score += max(abs(v) for v in _shift_pp(row["override"]["research_belief"],
                                               row["override"]["final_belief"]).values())
    return round(score, 1)


def build_signals(*, day: str, data_dir: Path) -> list[dict]:
    data_dir = Path(data_dir)
    day_dir = data_dir / "jczq" / "daily" / day
    ledger = {r["research"]: r for r in load_overrides(day_dir)}
    results = board_outcomes(data_dir, day)
    rows: list[dict] = []
    by_match_id: dict[str, dict] = {}
    for match in sorted(jczq_rows(data_dir, day), key=lambda r: r["code"]):
        code, leg, read, doc, band = (match["code"], match["leg"], match["read"],
                                      match["research"], match["band"])
        ledger_row = ledger.get(f"research-{code}.json")
        prior = dict(read.get("prior") or leg["fair"])
        outcome = (results.get(code) or {}).get("outcome_90")
        row = {
            "key": code, "name": leg.get("name"), "kickoff": leg.get("kickoff_bj"),
            "prior": prior, "drift": band.get("drift_pp"),
            "research": _research_view(doc, prior, ledger_row) if doc else None,
            "final": read.get("belief"),
            "override": ledger_row,
            "note": _ruling_note(doc) if not ledger_row else ledger_row["note"],
            "paired": None, "disagreement": [], "outcome": outcome,
        }
        rows.append(row)
        by_match_id[leg["match_id"]] = row
    zucai_dir = data_dir / "zucai"
    for issue, _issue_doc in closing_issues(zucai_dir, day):
        store = read_json(zucai_dir / f"{issue}-store-ids.json", {}) or {}
        by_no = {no: mid for mid, no in load_channel_map(zucai_dir, issue).items()}
        official = str((read_json(zucai_dir / "official-results.json", {}) or {}).get(issue)
                       or "").split()
        zreads = {r.get("match_id"): r
                  for r in read_json(zucai_dir / f"{issue}-reads.json", []) or []}
        # 足彩独有场次的主循环改判记在 zucai/overrides.jsonl（2026-09-28 起进面板与改判账）
        zledger = {r["research"]: r for r in load_overrides(zucai_dir)}
        for no, ids in sorted(store.items(), key=lambda kv: int(kv[0])):
            prior = dict(ids.get("fair") or {})
            doc = _research_doc(zucai_dir / f"{issue}-research-m{no}.json")
            if not prior or len(prior) < 3:
                continue
            zrow = zledger.get(f"{issue}-research-m{no}.json")
            view = _research_view(doc, prior, zrow) if doc else None
            jczq_row = by_match_id.get(by_no.get(int(no), ""))
            if jczq_row is not None:
                jczq_row["paired"] = {"key": f"足彩{issue}-{int(no):02d}", "research": view}
                if view and jczq_row["research"]:
                    jczq_row["disagreement"] = _disagreement(jczq_row["research"], view)
                continue
            read = zreads.get(ids.get("match_id")) or {}
            rows.append({
                "key": f"足彩{issue}-{int(no):02d}", "name": ids.get("name"), "kickoff": None,
                "prior": prior, "drift": None, "research": view,
                "final": read.get("belief"), "override": zrow,
                "note": zrow["note"] if zrow else _ruling_note(doc),
                "paired": None, "disagreement": [],
                "outcome": official[int(no) - 1] if len(official) >= int(no) else None,
            })
    for row in rows:
        row["score"] = _score(row)
        if row["outcome"] in FACE_OF and row["research"] and row["final"]:
            row["brier_research"] = round(brier(row["research"]["belief"], row["outcome"]), 4)
            row["brier_final"] = round(brier(row["final"], row["outcome"]), 4)
            row["brier_market"] = round(brier(row["prior"], row["outcome"]), 4)
    rows.sort(key=lambda r: -r["score"])
    return rows


def _pct(dist: dict | None) -> str:
    if not dist:
        return "—"
    return "/".join(f"{dist[k] * 100:.1f}" for k in ("home", "draw", "away"))


def _shift_text(shift: dict) -> str:
    moved = [f"{SHORT_ZH[k]}{v:+.1f}" for k, v in shift.items() if abs(v) >= 0.05]
    return " ".join(moved) or "不拨"


def render_signals(rows: list[dict], *, day: str) -> str:
    lines = [f"# 信号面板 {day}（主/平/客 %，只搬运不判断）", ""]
    cut = [r for r in rows if r["override"]]
    if cut:
        lines += ["## 主循环改判了研究的信号（人工裁决优先看这里）", "",
                  "| 场次 | 市场 | 研究原判 | 主循环终判 | 理由 | 赛果 | 改判得失 |",
                  "|---|---|---|---|---|---|---|"]
        for r in cut:
            gain = ("—" if "brier_research" not in r
                    else f"{(r['brier_research'] - r['brier_final']) * 100:+.1f}")
            lines.append(
                f"| {r['key']} {r['name']} | {_pct(r['prior'])} | "
                f"{_pct(r['override']['research_belief'])} | {_pct(r['override']['final_belief'])} "
                f"| {r['note'] or ''} | {r['outcome'] or '待'} | {gain} |")
        lines.append("")
    split = [r for r in rows if r["disagreement"]]
    if split:
        lines += ["## 同场两份研究打架", ""]
        for r in split:
            lines.append(f"- **{r['key']} {r['name']}** ↔ {r['paired']['key']}：" + "；".join(
                r["disagreement"]))
        lines.append("")
    lines += ["## 全部场次（按信号强度）", "",
              "| 场次 | 强度 | 市场 | 漂移 | 研究拨动 | 证据 | 天平/弱方 | 未定价事件 | 旗 "
              "| 终判 | 赛果 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        research = r["research"] or {}
        drift = r["drift"] or {}
        drift_text = " ".join(f"{SHORT_ZH[k]}{v:+.1f}" for k, v in drift.items()
                              if abs(v) >= 0.5) or "—"
        lines.append(
            f"| {r['key']} {r['name'] or ''} | {r['score']} | {_pct(r['prior'])} | {drift_text} | "
            f"{_shift_text(research['shift']) if research else '无研究'} | "
            f"{' '.join(research.get('evidence') or []) or '—'} | "
            f"{research.get('verdict') or '—'}/{research.get('underdog') or '—'} | "
            f"{'；'.join(research.get('unpriced') or []) or '—'} | "
            f"{' '.join(research.get('flags') or []) or '—'} | {_pct(r['final'])} | "
            f"{r['outcome'] or '待'} |")
    return "\n".join(lines) + "\n"


def write_signals(*, day: str, data_dir: Path) -> Path:
    rows = build_signals(day=day, data_dir=data_dir)
    path = Path(data_dir) / "jczq" / "daily" / day / "signals.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_signals(rows, day=day), encoding="utf-8")
    return path
