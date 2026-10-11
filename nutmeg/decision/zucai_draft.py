"""足彩初稿（2026-10-01 Jun：「传统足彩的初稿还是需要出的，这个不能省略」）。

B 泳道：机器出**首版票面初稿** → Jun 改 → 机器审票（V1/V2/V3）→ 讨论定案 → `betslip register`。

初稿规则 = **处方忠实**（不是帽内 max-P，那个形状 403 天回放 −58%）：
1. 面集合 = 处方面（legs-base `prescription` / 腿 `faces` / judgment-v1 action）——研究的结构判断；
2. 进帽只许丢场（任九 14 选 9）不许降档（8/08 铁律）；所有组合都装不下时才降档：
   每一步砍掉票内判断概率最低的那个面，降了几档逐条明写；
3. 同为最少降档的组合里取 P(全对) 最高，再取更便宜的；
4. 期望回报用奖金模型（`review.zucai_return`）：市场口径 × 判断溢价——钱只该押在判断与市场
   不同的面上，全包面的溢价恒为 1；
5. 初稿自己过审票；附刹车档（帽减半）与帽内 max-P 参考点（只作对照）。

产物：`<期>-draft.json` / `<期>-draft.md` / `<期>-legs-draft-<channel>.json`（可直接给
`decision-audit-legs --legs-file`），并作为 `draft@<hash>` 候选进工作台时间线（幂等）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

from nutmeg.decision.betslip import BetSlip, SlipLeg
from nutmeg.decision.faces import FACE_OF, FACES
from nutmeg.decision.files import read_json

RENJIU_PICK = 9
PRICE_PER_NOTE = 2
DEFAULT_CAP = 800        # 足彩单票复式基准（2026-10-12 Jun 400→800；bankroll.ZUCAI_SLIP_CAP_YUAN）
CHANNEL_CN = {"renjiu": "任九", "shengfucai": "胜负彩"}


def load_board(data_dir: Path, issue: str) -> dict:
    """legs-base（+judgment-v1 兜底）→ {no: {name, faces, belief, market, confidence, raw}}。"""
    zdir = Path(data_dir) / "zucai"
    doc = read_json(zdir / f"{issue}-legs-base.json", None)
    if not doc:
        raise FileNotFoundError(f"{issue}-legs-base.json 缺失：先跑 B4 zucai-build-reads")
    legs_raw = doc.get("legs") or {k: v for k, v in doc.items() if str(k).isdigit()}
    prescription = doc.get("prescription") or {}
    judgment = read_json(zdir / f"{issue}-judgment-v1.json", {}) or {}
    issue_doc = read_json(zdir / f"{issue}-issue.json", {}) or {}
    names = {str(m.get("match_no")): f"{m.get('home_team')}-{m.get('away_team')}"
             for m in issue_doc.get("matches") or []}
    legs: dict[str, dict] = {}
    for no in sorted(legs_raw, key=int):
        leg = legs_raw[no]
        faces = (str(prescription.get(no) or leg.get("faces")
                     or (judgment.get(no) or {}).get("action") or "310"))
        faces = "".join(d for d in "310" if d in faces) or "310"
        belief = leg.get("fair") or {}
        market = leg.get("prior") or belief
        if not belief:
            raise ValueError(f"场 {no} 无 fair：legs-base 不完整")
        legs[no] = {"name": leg.get("name") or names.get(no, ""), "faces": faces,
                    "belief": {f: float(belief[f]) for f in FACES},
                    "market": {f: float(market[f]) for f in FACES},
                    "confidence": leg.get("confidence"), "raw": leg}
    return legs


def _notes(faces: dict[str, str]) -> int:
    n = 1
    for fs in faces.values():
        n *= len(fs)
    return n


def _p_all(legs: dict[str, dict], faces: dict[str, str]) -> float:
    p = 1.0
    for no, fs in faces.items():
        p *= sum(legs[no]["belief"][FACE_OF[d]] for d in fs)
    return p


def prescription_point(legs: dict[str, dict], *, channel: str, cap_yuan: int) -> dict | None:
    """处方忠实点：最少降档 → P(全对) 最高 → 更便宜。装不下 → None。"""
    need = RENJIU_PICK if channel == "renjiu" else len(legs)
    cap_notes = cap_yuan // PRICE_PER_NOTE
    ordered = sorted(legs, key=int)
    if len(ordered) < need:
        return None
    best: dict | None = None
    for subset in combinations(ordered, need):
        faces = {no: legs[no]["faces"] for no in subset}
        steps: list[dict] = []
        while _notes(faces) > cap_notes:
            cands = [(legs[no]["belief"][FACE_OF[d]], no, d)
                     for no in subset if len(faces[no]) > 1 for d in faces[no]]
            if not cands:
                break
            p, no, d = min(cands)
            faces[no] = faces[no].replace(d, "")
            steps.append({"no": no, "dropped": d, "p": round(p, 4), "to": faces[no]})
        notes = _notes(faces)
        if notes > cap_notes:
            continue
        p_all = _p_all(legs, faces)
        key = (len(steps), -p_all, notes)
        if best is None or key < best["_key"]:
            best = {"_key": key, "faces": faces, "notes": notes,
                    "stake_yuan": notes * PRICE_PER_NOTE, "p_all": round(p_all, 6),
                    "downgrades": steps,
                    "dropped": [no for no in ordered if no not in subset]}
    if best:
        best.pop("_key")
    return best


def maxp_reference(legs_raw: dict[str, dict], *, channel: str, cap_yuan: int) -> dict | None:
    """帽内 max-P（`enumerate_frontier` belief 模式）——只作对照，403 天回放 −58%。"""
    from nutmeg.decision.structure_space import NoFaceStatusError, enumerate_frontier

    try:
        result = enumerate_frontier(legs_raw, channel=channel, cap_yuan=cap_yuan, mode="belief")
    except (NoFaceStatusError, KeyError, ValueError):
        return None
    points = [p for p in result.get("points") or [] if p["stake_yuan"] <= cap_yuan]
    if not points:
        return None
    pt = max(points, key=lambda p: (p["p_all"], -p["stake_yuan"]))
    faces = {str(k): str(v) for k, v in sorted(pt["faces"].items(), key=lambda kv: int(kv[0]))}
    return {"faces": faces, "notes": pt["notes"], "stake_yuan": pt["stake_yuan"],
            "p_all": round(pt["p_all"], 6)}


def to_slip(issue: str, legs: dict[str, dict], faces: dict[str, str], *, channel: str,
            slip_id: str, placed_at: str = "") -> BetSlip:
    slip_legs = [SlipLeg(key=no, name=legs[no]["name"], market="had",
                         selections=tuple(FACE_OF[d] for d in fs), fair=legs[no]["belief"])
                 for no, fs in sorted(faces.items(), key=lambda kv: int(kv[0]))]
    return BetSlip(slip_id=slip_id, channel=channel, placed_at=placed_at, legs=slip_legs,
                   issue=issue, purchased=False, faces=dict(faces))


def review_candidate(slip: BetSlip, data_dir: Path, *, model: dict, market: dict) -> dict:
    """同伴 = 本期已登记实购票（Jun 已买的）→ V2；V1 用奖金模型 + 市场分布。"""
    from nutmeg.decision.review_runner import review_slip

    out = review_slip(slip, data_dir, model=model, market=market)
    return {"ratio": out["ratio"], "detail": out["detail"], "vetoed": out["vetoed"],
            "lines": out["lines"], "shared_naked": out["diagnosis"].get("shared_naked") or []}


def _prescription_summary(legs: dict[str, dict]) -> dict:
    shape = {"singles": 0, "doubles": 0, "fulls": 0}
    for leg in legs.values():
        n = len(leg["faces"])
        shape["singles" if n == 1 else "doubles" if n == 2 else "fulls"] += 1
    sfc_notes = _notes({no: leg["faces"] for no, leg in legs.items()})
    return {"faces": {no: leg["faces"] for no, leg in legs.items()}, "shape": shape,
            "sfc_stake_yuan": sfc_notes * PRICE_PER_NOTE}


def build_draft(data_dir: Path, issue: str, *, cap_yuan: int = DEFAULT_CAP,
                channels: tuple[str, ...] = ("renjiu", "shengfucai"), write: bool = True,
                placed_at: str = "") -> dict:
    from nutmeg.decision.review import prize_model

    data_dir = Path(data_dir)
    legs = load_board(data_dir, issue)
    legs_raw = {no: leg["raw"] for no, leg in legs.items()}
    market = {no: leg["market"] for no, leg in legs.items()}
    model = prize_model(data_dir)
    candidates: list[dict] = []
    for channel in channels:
        for label, cap in (("初稿", cap_yuan), ("刹车档", cap_yuan // 2)):
            pt = prescription_point(legs, channel=channel, cap_yuan=cap)
            if not pt:
                candidates.append({"label": label, "channel": channel, "cap_yuan": cap,
                                   "faces": None, "note": "处方装不进帽（即使降档）"})
                continue
            candidates.append({"label": label, "channel": channel, "cap_yuan": cap, **pt,
                               "rule": "prescription"})
        ref = maxp_reference(legs_raw, channel=channel, cap_yuan=cap_yuan)
        if ref:
            candidates.append({"label": "参考·帽内max-P", "channel": channel,
                               "cap_yuan": cap_yuan, **ref, "rule": "max_p",
                               "dropped": [no for no in legs if no not in ref["faces"]],
                               "downgrades": []})
    for i, cand in enumerate(candidates):
        if not cand.get("faces"):
            continue
        slip = to_slip(issue, legs, cand["faces"], channel=cand["channel"],
                       slip_id=f"draft-{issue}-{i}", placed_at=placed_at)
        cand["review"] = review_candidate(slip, data_dir, model=model, market=market)
    doc = {"issue": issue, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "cap_yuan": cap_yuan, "rule": "prescription_faithful",
           "prescription": _prescription_summary(legs),
           "legs": {no: {"name": leg["name"], "faces": leg["faces"], "belief": leg["belief"],
                         "market": leg["market"], "confidence": leg["confidence"]}
                    for no, leg in legs.items()},
           "prize_model": {ch: {k: v for k, v in (model.get(ch) or {}).items()}
                           for ch in channels},
           "candidates": candidates}
    doc["hash"] = hashlib.sha256(json.dumps(
        [(c["channel"], c["label"], c.get("faces")) for c in candidates],
        sort_keys=True).encode()).hexdigest()[:12]
    if write:
        _write_outputs(data_dir, issue, doc, legs_raw)
    return doc


def _write_outputs(data_dir: Path, issue: str, doc: dict, legs_raw: dict) -> None:
    from nutmeg.decision.workbench import append_candidate

    zdir = data_dir / "zucai"
    zdir.mkdir(parents=True, exist_ok=True)
    (zdir / f"{issue}-draft.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    (zdir / f"{issue}-draft.md").write_text(render_draft(doc), encoding="utf-8")
    for cand in doc["candidates"]:
        if cand["label"] != "初稿" or not cand.get("faces"):
            continue
        legs_doc = _legs_file_from_faces(legs_raw, cand["faces"], issue, cand["channel"])
        legs_doc["draft"] = {"hash": doc["hash"], "rule": doc["rule"], "cap_yuan": cand["cap_yuan"]}
        (zdir / f"{issue}-legs-draft-{cand['channel']}.json").write_text(
            json.dumps(legs_doc, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        day = _day_of(issue, data_dir)
    except (OSError, ValueError, KeyError, IndexError):
        return
    existing = _candidate_versions(data_dir, day, issue)
    for cand in doc["candidates"]:
        if not cand.get("faces"):
            continue
        version = f"draft:{cand['channel']}:{cand['label']}@{doc['hash']}"
        if version in existing:
            continue
        vetoed = (cand.get("review") or {}).get("vetoed")
        reason = f"机器初稿 {cand['label']}（{cand.get('rule')}，帽 ¥{cand['cap_yuan']}）"
        append_candidate(data_dir / "jczq", day, obj_id=f"ticket:{issue}", version=version,
                         faces=cand["faces"], notes=cand["notes"], stake_yuan=cand["stake_yuan"],
                         p_all=cand["p_all"], verdict="rejected" if vetoed else "considered",
                         reason=reason + ("；审票否决" if vetoed else ""))


# ── 写出初稿时用的小工具（2026-10-03 自已删的 plan_flow 迁入）──



def _day_of(issue: str, data_dir: Path) -> str:
    """期次业务日 = 最早开球的北京日期。"""
    doc = json.loads((data_dir / "zucai" / f"{issue}-issue.json").read_text("utf-8"))
    kickoffs = sorted(str(m["kickoff_bj"]) for m in doc["matches"] if m.get("kickoff_bj"))
    return kickoffs[0][:10]


def _candidate_versions(data_dir: Path, day: str, issue: str) -> set[str]:
    from nutmeg.decision.workbench import read_events

    return {
        str(event["payload"]["version"])
        for event in read_events(data_dir / "jczq", day)
        if event.get("kind") == "candidate" and event.get("obj_id") == f"ticket:{issue}"
    }


def _legs_file_from_faces(legs: dict, faces: dict, issue: str, channel: str) -> dict:
    out = {}
    for match_no, face_string in faces.items():
        leg = legs[match_no]
        out[match_no] = {
            **{key: value for key, value in leg.items() if not key.startswith("_")},
            "faces": face_string,
            "selections": [FACE_OF[digit] for digit in face_string],
        }
    return {"issue": issue, "channel": channel, "legs": out}


def _dist(d: dict) -> str:
    return "/".join(f"{d[f] * 100:.0f}" for f in FACES)


def _cand_header(c: dict) -> str:
    ch = CHANNEL_CN[c["channel"]]
    if not c.get("faces"):
        return f"## {c['label']}·{ch}（帽 ¥{c['cap_yuan']}）：{c.get('note')}"
    rv = c.get("review") or {}
    detail = rv.get("detail") or {}
    ratio = rv.get("ratio")
    text = (f"## {c['label']}·{ch}：¥{c['stake_yuan']:,}（{c['notes']} 注，帽 ¥{c['cap_yuan']}）"
            f"｜P(全对) {c['p_all'] * 100:.1f}%")
    if ratio is not None:
        text += f"｜期望回报 {ratio:.2f}"
        if detail.get("basis") == "model":
            text += f"（市场 {detail['ratio_market']:.2f} × 判断溢价 {detail['premium']:.2f}）"
    return text


def render_draft(doc: dict) -> str:
    legs = doc["legs"]
    pres = doc["prescription"]
    shape = pres["shape"]
    lines = [f"# 足彩初稿 · {doc['issue']}（帽 ¥{doc['cap_yuan']}，规则：处方忠实）",
             f"处方 {len(legs)} 场：单 {shape['singles']} / 双 {shape['doubles']} / 全包 "
             f"{shape['fulls']}；处方原价胜负彩 ¥{pres['sfc_stake_yuan']:,}", "",
             "| 场 | 对阵 | 处方 | 判断 3/1/0 | 市场 3/1/0 | 信心 |", "|---|---|---|---|---|---|"]
    for no, leg in legs.items():
        lines.append(f"| {no} | {leg['name']} | {leg['faces']} | {_dist(leg['belief'])} "
                     f"| {_dist(leg['market'])} | {leg.get('confidence') or ''} |")
    for c in doc["candidates"]:
        lines += ["", _cand_header(c)]
        if not c.get("faces"):
            continue
        row = " ".join(f"{no}:{fs}" for no, fs in c["faces"].items())
        lines.append(f"票面：`{row}`")
        if c.get("dropped"):
            dropped = "、".join(f"{no}({legs[no]['faces']})" for no in c["dropped"])
            lines.append(f"丢场：{dropped}")
        if c.get("downgrades"):
            steps = "、".join(f"{s['no']} 砍{s['dropped']}({s['p'] * 100:.0f}%)→{s['to']}"
                             for s in c["downgrades"])
            lines.append(f"降档 {len(c['downgrades'])} 步：{steps}")
        if c["label"].startswith("参考"):
            lines.append("（帽内 max-P 形状 403 天回放 −58%，只作对照，不是建议）")
        for line in (c.get("review") or {}).get("lines") or []:
            lines.append(f"审票 {line}")
    lines += ["", "> 读法：初稿 = 处方面集合装进帽（只丢场不降档）；市场口径下任何形状的期望回报都"
                  "≈返奖率，差别只在判断溢价（钱押在判断≠市场的面上，全包面溢价恒为 1）。"
                  "Jun 改票后 `betslip preview --faces … --issue …` 再审，"
                  "定案 `betslip register`。"]
    return "\n".join(lines) + "\n"
