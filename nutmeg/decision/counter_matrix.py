"""反证矩阵（ACH-lite，2026-10-27 探照灯 P3）：分析包 §1c 的机器底稿。

每场两个互斥假设——H1 锚方面、H2 翻车面——研究 JSON 里的每条证据按行对两者打 +/−/0；
**两列同号的证据没有区分力，不进表只计数**（竞争假说分析的核心规则）；按「不一致数最少」
排假设；末行写翻盘证据（研究 `stance.falsifier` + 停售前拿不到的信息）。

只由现有研究字段派生：不加 LLM 层（2609.12495：批评者/元代理层不增益）、不出概率、
不进任何否决；它回答的是「研究有没有漏看、Jun 读包时该盯哪一行」，不回答「会不会翻」。
验收读数在 §5⑪：桥后改动理由能指到矩阵某一行的比例。
"""
from __future__ import annotations

from pathlib import Path

from nutmeg.decision.faces import CODE_OF
from nutmeg.decision.files import read_json
from nutmeg.decision.research_sources import coverage_mark, extract_urls
from nutmeg.decision.rubric_items import ITEMS

FACES = ("3", "1", "0")
WIN_FACE = {"home": "3", "away": "0"}
OPPONENT = {"home": "away", "away": "home"}
MAX_DISTINGUISHING = 5       # 区分力行超过它＝打分偏松（ACH 只留有区分力的证据）
_SIGN = {1: "+", -1: "−", 0: "0", 2: "++", -2: "−−"}


def hypotheses(research: dict, fair: dict | None) -> tuple[str, str, str]:
    """(H1 锚方面, H2 翻车面, 锚方 side)。锚方＝研究 anchor_side，没有就按 fair 最大面；
    翻车面＝研究 double 的 cover → alt_face → 弱方胜面 → 平。"""
    anchor_side = str(research.get("anchor_side") or "")
    if anchor_side not in WIN_FACE:
        fav = max(fair, key=fair.get) if fair else "home"
        anchor_side = fav if fav in WIN_FACE else "home"
    h1 = WIN_FACE[anchor_side]
    stance = research.get("stance") or {}
    underdog = ((research.get("strength_balance") or {}).get("underdog_path") or {}).get("side")
    candidates = [
        stance.get("cover") if stance.get("structure") == "double" else None,
        stance.get("alt_face"),
        WIN_FACE.get(str(underdog)),
        "1",
    ]
    h2 = next(str(c) for c in candidates if c is not None and str(c) in FACES and str(c) != h1)
    return h1, h2, anchor_side


def _face_impact(side: str, direction: str, anchor_side: str) -> dict[str, int]:
    """一侧变弱/变强对三个面的方向：自家胜面同向，对家胜面反向；平局跟弱方走
    （锚方变弱 → 平更可能；弱方变弱 → 平更不可能）。"""
    unit = -1 if direction == "down" else 1
    if side == "both":
        return {"3": unit, "0": unit, "1": -unit}
    if side not in WIN_FACE:
        return {"3": 0, "1": 0, "0": 0}
    draw = -unit if side == anchor_side else unit
    return {WIN_FACE[side]: unit, WIN_FACE[OPPONENT[side]]: -unit, "1": draw}


def _row(evidence: str, kind: str, impact: dict[str, int], h1: str, h2: str, *,
         source: object = "", priced_in: object = None) -> dict:
    urls = extract_urls(source)
    s1, s2 = impact.get(h1, 0), impact.get(h2, 0)
    return {
        "evidence": str(evidence)[:60], "kind": kind,
        "source_url": urls[0] if urls else None,
        "source_text": "" if urls else str(source or "")[:40],
        "priced_in": priced_in if isinstance(priced_in, bool) else None,
        "h1": s1, "h2": s2,
        # 区分力：两列符号不同（含一边为 0 另一边非 0）；同号或双零＝无区分力
        "distinguishing": (s1 > 0) != (s2 > 0) or (s1 < 0) != (s2 < 0),
    }


def build_matrix(research: dict, *, fair: dict | None, name: str = "", no: str = "") -> dict:
    h1, h2, anchor = hypotheses(research, fair)
    underdog_side = OPPONENT[anchor]
    rows: list[dict] = []
    balance = research.get("strength_balance") or {}

    for event in balance.get("events") or []:
        if not isinstance(event, dict):
            continue
        rows.append(_row(event.get("event", ""), f"事件·{event.get('grade', '')}",
                         _face_impact(str(event.get("side")), str(event.get("direction")), anchor),
                         h1, h2, source=event.get("source"), priced_in=event.get("priced_in")))

    items = (research.get("rubric") or {}).get("items") or {}
    for item_id, raw in items.items():
        item = ITEMS.get(item_id)
        if item is None or not isinstance(raw, dict) or raw.get("abstain"):
            continue
        answer = raw.get("answer")
        active = ((item.type == "noul" and answer == "yes")
                  or (item.type == "choice" and answer in item.effect_options))
        label = f"{item_id}（p={raw.get('p')}）"
        if item_id == "S_spine_intact" and answer == "no":
            rows.append(_row("锚方中轴不完整 " + label, "rubric",
                             _face_impact(anchor, "down", anchor), h1, h2,
                             source=raw.get("source")))
        elif not active:
            continue
        elif item.effect == "down:home":
            rows.append(_row(label, "rubric", _face_impact("home", "down", anchor), h1, h2,
                             source=raw.get("source")))
        elif item.effect == "down:away":
            rows.append(_row(label, "rubric", _face_impact("away", "down", anchor), h1, h2,
                             source=raw.get("source")))
        elif item.effect == "down:side":
            rows.append(_row(f"{label} → {answer}", "rubric",
                             _face_impact(str(answer), "down", anchor), h1, h2,
                             source=raw.get("source")))
        elif item_id == "S_underdog_path":
            rows.append(_row("弱方有真实路径 " + label, "rubric",
                             _face_impact(underdog_side, "up", anchor), h1, h2))
        elif item_id == "S_crash_candidate":
            rows.append(_row("锚方是翻车候选 " + label, "rubric",
                             _face_impact(anchor, "down", anchor), h1, h2))
        elif item_id == "S_draw_mode":
            rows.append(_row("低比分平局是模态 " + label, "rubric", {"3": -1, "0": -1, "1": 1},
                             h1, h2))

    hole = research.get("hole_location") or {}
    if isinstance(hole, dict) and hole.get("unit") not in (None, "none") and hole.get("side") in (
            "home", "away", "both"):
        rows.append(_row(f"洞·{hole.get('unit')}@{hole.get('side')}：{hole.get('detail', '')}",
                         "完整度", _face_impact(str(hole["side"]), "down", anchor), h1, h2,
                         priced_in=hole.get("priced_in")))

    license_q = research.get("license_questions") or {}
    if license_q.get("q1_spine") is False:
        rows.append(_row("许可证①锚方中轴 ✗", "许可证", _face_impact(anchor, "down", anchor),
                         h1, h2))
    if license_q.get("q3a_opponent_scores") is False:
        rows.append(_row("许可证③a 对手进不了球", "许可证",
                         _face_impact(underdog_side, "down", anchor), h1, h2))

    for marker in research.get("crash_markers") or []:
        rows.append(_row(f"崩塌标记 {marker}", "标记", _face_impact(anchor, "down", anchor),
                         h1, h2))
    for flag in research.get("nondirectional_flags") or []:
        rows.append(_row(f"无方向旗 {flag}", "旗", {"3": -1, "1": -1, "0": -1}, h1, h2))

    for face, proofs in (research.get("death_three_proofs") or {}).items():
        if isinstance(proofs, dict) and str(proofs.get("verdict", "")).lower() == "dead":
            code = CODE_OF.get(face, face)
            rows.append(_row(f"三证 3/3 判死 {code}：{proofs.get('detail', '')}", "三证",
                             {code: -2}, h1, h2))

    shown = [r for r in rows if r["distinguishing"]]
    shown.sort(key=lambda r: (r["priced_in"] is not False, r["kind"]))     # 未价的先看
    stance = research.get("stance") or {}
    q5 = license_q.get("q5_no_rotation_window")
    return {
        "no": str(no), "name": name, "h1": h1, "h2": h2, "anchor_side": anchor,
        "rows": shown,
        "hidden": len(rows) - len(shown),
        "inconsistent": {"h1": sum(1 for r in shown if r["h1"] < 0),
                         "h2": sum(1 for r in shown if r["h2"] < 0)},
        "loose": len(shown) > MAX_DISTINGUISHING,
        "falsifier": str(stance.get("falsifier") or ""),
        "unknowable_before_close": ("名单窗开着（④ ?）" if q5 is None
                                    else "欧战/杯赛后 ≤4 天、名单停售前看不到" if q5 is False
                                    else "—"),
        "coverage": coverage_mark(research.get("coverage")),
        "stop_reason": (research.get("coverage") or {}).get("stop_reason"),
    }


def _cell(value: int) -> str:
    return _SIGN.get(value, str(value))


def render_matrix(matrix: dict) -> str:
    h1, h2 = matrix["h1"], matrix["h2"]
    head = (f"### 场 {matrix['no']} {matrix['name']}｜H1 锚方面 {h1} vs H2 翻车面 {h2}"
            f"｜研究收敛 {matrix['coverage']}")
    if matrix["stop_reason"] and matrix["stop_reason"] != "coverage":
        head += f"（{matrix['stop_reason']}）"
    lines = [head, "", f"| 证据 | 类 | 来源 | 价内 | H1 {h1} | H2 {h2} |",
             "|---|---|---|---|---|---|"]
    for r in matrix["rows"]:
        src = f"[链接]({r['source_url']})" if r["source_url"] else (r["source_text"] or "—")
        priced = "—" if r["priced_in"] is None else ("价内" if r["priced_in"] else "**未价**")
        lines.append(f"| {r['evidence']} | {r['kind']} | {src} | {priced} "
                     f"| {_cell(r['h1'])} | {_cell(r['h2'])} |")
    if not matrix["rows"]:
        lines.append("| （研究没有一条有区分力的证据） | | | | | |")
    inc = matrix["inconsistent"]
    tail = (f"不一致数：H1 {inc['h1']} · H2 {inc['h2']}（少者为 ACH 首选，只排序不推概率）；"
            f"无区分力证据 {matrix['hidden']} 条不显示")
    if matrix["loose"]:
        tail += f"；**区分力行 {len(matrix['rows'])} > {MAX_DISTINGUISHING}：打分偏松**"
    lines += ["", tail,
              f"翻盘证据：{matrix['falsifier'] or '（研究未写 falsifier）'}｜"
              f"停售前拿不到：{matrix['unknowable_before_close']}"]
    return "\n".join(lines)


def _jczq_twins(data_dir: Path, issue: str, issue_doc: dict) -> dict[int, Path]:
    """竞彩重叠场没有 m 文件：按身份脊柱 `<期>-channel-map(.auto).json`（match_id → 场号）
    到板面日 `jczq/daily/<日>/reads.json`（match_id → 竞彩编号）找 `research-<编号>.json`。
    只走别名表，不按队名或 fair 值反查（RULEBOOK g-scope）。"""
    import datetime as _dt
    zdir = data_dir / "zucai"
    cmap = (read_json(zdir / f"{issue}-channel-map.json", None)
            or read_json(zdir / f"{issue}-channel-map.auto.json", None) or {})
    by_id = {str(k): int(v) for k, v in cmap.items() if str(v).isdigit() or isinstance(v, int)}
    if not by_id:
        return {}
    days: set[str] = set()
    for m in issue_doc.get("matches") or []:
        d = str(m.get("match_date") or "")[:10]
        if len(d) != 10:
            continue
        days.add(d)
        try:
            days.add((_dt.date.fromisoformat(d) - _dt.timedelta(days=1)).isoformat())
        except ValueError:
            pass
    out: dict[int, Path] = {}
    for day in sorted(days):
        ddir = data_dir / "jczq" / "daily" / day
        reads = read_json(ddir / "reads.json", None)
        if not isinstance(reads, list):
            continue
        for r in reads:
            mid, code = str(r.get("match_id") or ""), str(r.get("code") or "")
            if mid in by_id and code and (ddir / f"research-{code}.json").exists():
                out.setdefault(by_id[mid], ddir / f"research-{code}.json")
    return out


def issue_matrices(data_dir: Path, issue: str) -> list[dict]:
    """一期 14 场：legs-base 给 fair 与名字，研究原件 `<期>-research-m<N>.json` 给证据。"""
    zdir = Path(data_dir) / "zucai"
    legs_doc = read_json(zdir / f"{issue}-legs-base.json", {}) or {}
    legs = legs_doc.get("legs") or {k: v for k, v in legs_doc.items() if str(k).isdigit()}
    issue_doc = read_json(zdir / f"{issue}-issue.json", {}) or {}
    names = {str(m["match_no"]): f"{m.get('home_team')}-{m.get('away_team')}"
             for m in issue_doc.get("matches") or []}
    out = []
    twins = _jczq_twins(Path(data_dir), issue, issue_doc)
    for no in sorted(legs, key=lambda k: int(k)):
        leg = legs[no]
        research = read_json(zdir / f"{issue}-research-m{int(no)}.json", None)
        if not isinstance(research, dict) and twins.get(int(no)):
            research = read_json(twins[int(no)], None)
        name = leg.get("name") or names.get(no, "")
        if not isinstance(research, dict):
            out.append({"no": no, "name": name, "missing": True})
            continue
        out.append(build_matrix(research, fair=leg.get("prior") or leg.get("fair"),
                                name=name, no=no))
    return out


def render_issue(issue: str, matrices: list[dict]) -> str:
    lines = [f"## §1c 反证矩阵 · 足彩 {issue}（ACH-lite，由研究 JSON 派生，不出概率）", ""]
    for m in matrices:
        if m.get("missing"):
            lines += [f"### 场 {m['no']} {m['name']}｜无研究原件", ""]
            continue
        lines += [render_matrix(m), ""]
    lines.append("> 读法：H1/H2 是互斥假设，一行证据对两者符号不同才有区分力；"
                 "「价内」＝研究自己说市场已吸收。它只回答「研究有没有漏看、该盯哪一行」，"
                 "不回答「会不会翻」（n=90 翻车面标签与翻车无可测相关）。"
                 "桥后改动的理由请指到行（§5⑪ 计数）。")
    return "\n".join(lines) + "\n"
