"""初判包（2026-10-01 定位：机器出初判与解读，不出票）。

每场一行：市场分布、判断分布、表态面、判断种类（研究/改判/市场）、大热标记、旗、一句话。
人看完出方案，机器再审票（RUNBOOK A4 → A4b）。只读文件，不碰内核、不写判断。
"""
from __future__ import annotations

import json
from pathlib import Path

FACES = ("home", "draw", "away")
CODE_OF = {"home": "3", "draw": "1", "away": "0"}
FAV = 0.70
_KIND = {"research": "研究", "override": "改判", "market": "市场", "manual": "人工"}
_STRUCT = {"single": "单", "double": "双", "full": "全包"}


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _dist(d: dict | None) -> str:
    if not d:
        return "—"
    return "/".join(f"{float(d.get(f, 0)) * 100:.0f}" for f in FACES)


def _first_sentence(text: str | None, limit: int = 40) -> str:
    s = (text or "").strip().replace("\n", " ")
    for sep in ("。", "；", "."):
        if sep in s:
            s = s.split(sep, 1)[0]
            break
    return s[:limit] + ("…" if len(s) > limit else "")


def _rubric_text(leg: dict, sidecar: dict | None) -> str:
    """判断 rubric r1 一格：事实/结构/弃权/预算 + 两读 κ（有侧车时）。"""
    from nutmeg.decision.rubric import rubric_summary

    rubric = leg.get("rubric")
    kappa = ((sidecar or {}).get("kappa") or {}).get("kappa")
    return rubric_summary(rubric, kappa=kappa) if rubric else "—"


def _stance_text(stance: dict | None) -> str:
    if not stance or not stance.get("face"):
        return "—"
    struct = _STRUCT.get(str(stance.get("structure") or ""), str(stance.get("structure") or ""))
    faces = str(stance.get("faces") or stance.get("face") or "")
    cover = stance.get("cover")
    text = f"{struct} {faces}"
    if cover and struct != "single" and str(cover) not in faces:
        text += f"+保{cover}"
    conf = stance.get("confidence")
    return text + (f"（信心{conf}）" if conf else "")


def jczq_brief(data_dir: Path, day: str) -> dict:
    data_dir = Path(data_dir)
    day_dir = data_dir / "jczq" / "daily" / day
    legs = (_read(day_dir / "jczq-legs-base.json", {}) or {}).get("legs") or {}
    reads = {r.get("match_id"): r for r in (_read(day_dir / "reads.json", []) or [])}
    closing = _read(day_dir / "closing_odds.json", {}) or {}
    singles: dict[str, bool] = {}
    try:
        from nutmeg.gym.board import load_jczq_board

        board = load_jczq_board(data_dir, day)
        singles = {code: m.single_allowed.get("had", False) for code, m in board.matches.items()}
    except Exception:  # noqa: BLE001 —— 快照缺失只影响"单关"一列
        singles = {}
    rows = []
    for code, leg in sorted(legs.items()):
        read = reads.get(leg.get("match_id")) or {}
        market = leg.get("fair") or read.get("prior")
        belief = read.get("belief")
        sharp = ((closing.get(code) or {}).get("sharp") or {}).get("fair_probability")
        fav_src = sharp or market or {}
        fav_p = max(fav_src.values()) if fav_src else 0.0
        fav_face = max(fav_src, key=fav_src.get) if fav_src else None
        kind = read.get("kind") or ("market" if read.get("judge", "").startswith("market") else
                                    ("research" if leg.get("judgment_tier") == "deep_research"
                                     else "market"))
        stance = read.get("stance") or leg.get("stance")
        flags = (list(leg.get("directional_flags") or [])
                 + list(leg.get("nondirectional_flags") or []))
        override = read.get("override") or {}
        note = override.get("note") if override else leg.get("note")
        sidecar = _read(day_dir / f"rubric-{code}.json", None)
        rows.append({
            "rubric": _rubric_text(leg, sidecar),
            "code": code,
            "name": leg.get("name") or f"{leg.get('home_team')}-{leg.get('away_team')}",
            "kickoff": str(leg.get("kickoff_bj") or "")[11:16],
            "market": _dist(market), "belief": _dist(belief),
            "same_as_market": bool(belief and market and all(
                abs(float(belief.get(f, 0)) - float(market.get(f, 0))) < 0.005 for f in FACES)),
            "stance": _stance_text(stance), "kind": _KIND.get(kind, kind),
            "fav": f"★{CODE_OF[fav_face]} {fav_p * 100:.0f}%" if fav_face and fav_p >= FAV else "",
            "single": singles.get(code), "flags": "、".join(flags) or "",
            "note": _first_sentence(note),
            "confidence": read.get("confidence") or leg.get("confidence"),
        })
    researched = sum(1 for r in rows if r["kind"] in ("研究", "改判"))
    favs = sum(1 for r in rows if r["fav"])
    return {"day": day, "rows": rows, "n": len(rows), "researched": researched, "favs": favs,
            "singles_open": sum(1 for r in rows if r["single"])}


def render_jczq(brief: dict) -> str:
    lines = [f"# 初判与解读 · 竞彩 {brief['day']}",
             f"板面 {brief['n']} 场｜研究/改判 {brief['researched']}｜≥0.70 大热 {brief['favs']}"
             f"｜开单关 {brief['singles_open']}",
             "",
             "| 编号 | 对阵 | 开球 | 市场 3/1/0 | 判断 3/1/0 | 表态 | rubric | 种类 | 大热 | 单关 "
             "| 旗 | 一句话 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in brief["rows"]:
        belief = "跟市场" if r["same_as_market"] else r["belief"]
        single = "" if r["single"] is None else ("开" if r["single"] else "不开")
        lines.append(f"| {r['code']} | {r['name']} | {r['kickoff']} | {r['market']} | {belief} "
                     f"| {r['stance']} | {r.get('rubric', '—')} | {r['kind']} | {r['fav']} "
                     f"| {single} | {r['flags']} | {r['note']} |")
    lines += ["",
              "> 读法：判断=跟市场 ＝ 研究没给出可用拨动（F9：belief≈市场）；"
              "表态面是研究的结构判断（F14 在量化）；"
              "大热 ≥0.70 比终盘多中约 +5pp（样本外）但体彩价上无钱边；"
              "帽内 max-P 形状 403 天回放 −20%。"
              "**本包不含票面**——方案由人出，机器审票（`betslip preview`）。"]
    return "\n".join(lines) + "\n"


def zucai_brief(data_dir: Path, issue: str) -> dict:
    zdir = Path(data_dir) / "zucai"
    legs_doc = _read(zdir / f"{issue}-legs-base.json", {}) or {}
    legs = legs_doc.get("legs") or {k: v for k, v in legs_doc.items() if str(k).isdigit()}
    judgment = _read(zdir / f"{issue}-judgment-v1.json", {}) or {}
    issue_doc = _read(zdir / f"{issue}-issue.json", {}) or {}
    names = {str(m["match_no"]): f"{m.get('home_team')}-{m.get('away_team')}"
             for m in issue_doc.get("matches") or []}
    rows = []
    for no in sorted(legs, key=lambda k: int(k)):
        leg = legs[no]
        fair = leg.get("prior") or leg.get("fair")
        belief = leg.get("fair") if leg.get("prior") else None
        j = judgment.get(no) or {}
        stance = leg.get("stance") or leg.get("research_stance")
        fav_p = max(fair.values()) if fair else 0.0
        fav_face = max(fair, key=fair.get) if fair else None
        sidecar = _read(zdir / f"{issue}-rubric-m{int(no)}.json", None)
        rows.append({
            "rubric": _rubric_text(leg, sidecar),
            "no": no, "name": leg.get("name") or names.get(no, ""),
            "market": _dist(fair), "belief": _dist(belief) if belief else "—",
            "faces": leg.get("faces") or "", "action": j.get("action") or "",
            "stance": _stance_text(stance),
            "fav": f"★{CODE_OF[fav_face]} {fav_p * 100:.0f}%" if fav_face and fav_p >= FAV else "",
            # 方向性旗是 [旗名, 面] 二元组（research_intake 归一后），无方向旗是裸名
            "flags": "、".join(
                [f"{f[0]}→{f[1]}" if isinstance(f, list | tuple) else str(f)
                 for f in leg.get("directional_flags") or []]
                + [str(f) for f in leg.get("nondirectional_flags") or []]),
            "note": _first_sentence(j.get("note") or leg.get("note")),
        })
    return {"issue": issue, "rows": rows, "n": len(rows),
            "favs": sum(1 for r in rows if r["fav"])}


def render_zucai(brief: dict) -> str:
    lines = [f"# 初判与解读 · 足彩 {brief['issue']}",
             f"{brief['n']} 场｜≥0.70 大热 {brief['favs']}", "",
             "| 场 | 对阵 | 市场 3/1/0 | 判断 3/1/0 | 处方面 | judgment-v1 | 表态 | rubric | 大热 "
             "| 旗 | 一句话 |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in brief["rows"]:
        lines.append(f"| {r['no']} | {r['name']} | {r['market']} | {r['belief']} | {r['faces']} "
                     f"| {r['action']} | {r['stance']} | {r.get('rubric', '—')} | {r['fav']} "
                     f"| {r['flags']} | {r['note']} |")
    lines += ["", "> 处方面 = 机器的判断面集合；**足彩初稿不省略**（Jun 2026-10-01）：机器按"
                  "处方忠实规则出首版票面（见下「足彩初稿」，`nutmeg judgment draft --issue`），"
                  "Jun 改票 → `betslip preview --faces … --issue …` 审票 → 讨论定案 → 登记。"
                  "帽内 max-P 形状 403 天回放 −58%，只作对照。"]
    return "\n".join(lines) + "\n"
