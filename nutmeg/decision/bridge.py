"""§3 桥（2026-10-28 产品形态第 3 阶段）：五条自检、开场复述、差异格与理由读数、桥记录与桥后改动账。

Jun 拿 A 三屏出一版草案，机器对照一次，他改一次，登记桥后票 B1（试玩）——**只走一次**，
由 `append_bridge` 守（同期已有记录即抛 `BridgeError`）。散文规则以
`.claude/commands/zucai-packet.md`「B 桥」为准，这里只把它能机读的部分编成代码；
面一律按集合比（`parse_faces` 的 `310` 顺序），任九「丢」记作空面。只记录不拦登记。

判定口径（§3a 五条）：
- ① 硬币场：票内出现旁车 `tier == "D"` 的场 → ✗（列场号与面）。「无机制 C 档」旁车没有可机读
  字段，本阶段不判，detail 写明。
- ② 单的许可：单选场 `n == 6 and k >= 5` 才算许可；不在 `signed_bold`（旁车 + 桥上本次签的）里
  的其余单 → ✗。C 档（n=5）的单按定义是博胆；A 档七项口径未定，按不许可处理并在 detail 写明。
- ③ 博胆 ≤1 / 包只给硬币：**只读** `precheck` 的 `verdicts` 里 `code == "V5"` 的行
  （`review.structure_notes`），有就 ✗，detail 原样抄 V5 文字——不自算。
- ④ 跨票：读 `verdicts` 里 `code == "V2"` 的行（共享裸单 / 共享排除面，含与已购票）；
  无则「无跨票共享」✓。
- ⑤ 刹车档：`discipline` 里含「刹车」或「日帽」的 ⛔ 行 → ✗。月度止损不在五条里
  （审票卡已单独显示）。
- 开场复述：每条单一行 = 场号 · 旁车 `unknowable`（缺则 `首发 lineup_at（停售前/后）`）；外加死法
  清单第一门（`gates[0]`，带 ·D档）。

差异格的理由（§3b，§5⑪ 计数）：`cites[no]` 为矩阵行号 k（1 起）→ `{kind: "matrix", row, evidence}`；
为 `"out"` 且 `outs[no]` 有字 → `{kind: "out", text}`；其余 → `None`（未写）。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from nutmeg.decision.betslip import load_slips, parse_faces
from nutmeg.decision.bj_time import BJ, parse_bj
from nutmeg.decision.faces import FACE_OF

BRIDGE_SUFFIX = "-bridge.jsonl"
LICENSE_N, LICENSE_K = 6, 5
TITLES = {
    1: "硬币场：任九丢了没有",
    2: "每条单有许可（≥5/6 或签过的博胆）",
    3: "博胆 ≤1 · 包只给硬币场",
    4: "跨票共享裸单 / 排除面",
    5: "刹车档内（复式 ≤帽、合计 ≤帽）",
}


class BridgeError(ValueError):
    """桥的结构性错误（本期已走过桥）。"""


def _face(value) -> str:
    """面 → 规范面集合；「丢」/空 → 空面。"""
    if value is None or str(value).strip() == "丢":
        return ""
    return parse_faces(str(value))


def _ticket(faces: dict[str, str]) -> dict[str, str]:
    """票内场（丢的场不算）。"""
    return {str(no): f for no, raw in faces.items() if (f := _face(raw))}


def _rows(packet: dict) -> dict:
    return packet.get("by_no") or {str(r.get("no")): r for r in packet.get("rows") or []}


def _signed(packet: dict, signed_bold) -> set[tuple[str, str | None]]:
    """签过的博胆 → {(场号, 面 或 None＝该场任意面)}。"""
    out = {(str(no), None) for no in signed_bold}
    for x in packet.get("signed_bold") or []:
        if isinstance(x, dict) and x.get("no") is not None:
            out.add((str(x["no"]), _face(x["face"]) if x.get("face") else None))
    return out


def _license(row: dict | None, no: str, face: str, signed) -> tuple[bool, str]:
    label = f"{no}·{face}"
    if (no, None) in signed or (no, face) in signed:
        return True, f"{label} 签过的博胆"
    if row is None:
        return False, f"{label} 旁车无此场"
    tier, k, n = row.get("tier"), row.get("k"), row.get("n")
    kn = f"{k}/{n}" if k is not None and n is not None else "—"
    if n == LICENSE_N and k is not None and k >= LICENSE_K:
        return True, f"{label}（{tier} {kn}）"
    if tier == "A":
        return False, f"{label}（A 档 {kn}：七项口径未定，按不许可）"
    if tier == "C":
        return False, f"{label}（C 档 {kn}：单是博胆，未签）"
    return False, f"{label}（{tier} {kn}）"


def self_checks(packet: dict, faces: dict[str, str], pre: dict, *,
                signed_bold: list[str] = ()) -> list[dict]:
    """→ [{id: 1..5, ok: bool, title, detail}]。pre＝precheck() 的输出。"""
    rows, ticket = _rows(packet), _ticket(faces)
    order = sorted(ticket, key=int)

    coins = [f"{no}·{ticket[no]}" for no in order if (rows.get(no) or {}).get("tier") == "D"]
    note = "「无机制 C 档」旁车无可机读字段，本条不判"
    one = (not coins, ("票内 D 档：" + "、".join(coins) if coins else "票内无 D 档") + f"；{note}")

    signed = _signed(packet, signed_bold)
    singles = [_license(rows.get(no), no, ticket[no], signed) for no in order
               if len(ticket[no]) == 1]
    bad = [text for ok, text in singles if not ok]
    two = (not bad, ("不许可的单：" + "、".join(bad)) if bad
           else ("单都有许可：" + "、".join(t for _, t in singles) if singles else "票内无单"))

    verdicts = pre.get("verdicts") or []
    v5 = [v["text"] for v in verdicts if v.get("code") == "V5"]
    three = (not v5, "；".join(v5) if v5 else "V5 未点名（博胆 ≤1，包只在硬币场）")

    v2 = [v["text"] for v in verdicts if v.get("code") == "V2"]
    four = (not v2, "；".join(v2) if v2 else "无跨票共享")

    brakes = [x for x in pre.get("discipline") or []
              if str(x).startswith("⛔") and ("刹车" in x or "日帽" in x)]
    five = (not brakes, "；".join(brakes) if brakes else "帽内")

    return [{"id": i, "ok": ok, "title": TITLES[i], "detail": detail}
            for i, (ok, detail) in enumerate((one, two, three, four, five), start=1)]


def opening_lines(packet: dict, faces: dict[str, str], gates: list[dict]) -> list[dict]:
    """→ [{label, text}]：每条单「靠什么成立、停售前拿不到什么」+ 死法清单第一门。"""
    rows, ticket = _rows(packet), _ticket(faces)
    out = []
    for no in sorted(ticket, key=int):
        if len(ticket[no]) != 1:
            continue
        row = rows.get(no) or {}
        text = row.get("unknowable")
        if not text:
            at, before = row.get("lineup_at"), row.get("lineup_before_close")
            when = {True: "停售前", False: "停售后"}.get(before, "停售前后未知")
            text = f"首发 {at}（{when}）" if at else "旁车未写停售前拿不到的信息"
        out.append({"label": f"场 {no}·{ticket[no]}", "text": str(text)})
    if gates:
        g = gates[0]
        text = f"{g['no']} 开 {g['face']} {float(g['p']) * 100:.0f}%"
        if g.get("coin"):
            text += "·D档——这场为什么不直接丢"
        out.append({"label": "死法清单第一门", "text": text})
    else:
        out.append({"label": "死法清单第一门", "text": "无被排面"})
    return out


def _cover(fair: dict[str, dict], no: str, face: str) -> float | None:
    """这一格盖住的概率；丢＝这场不计＝1。缺 fair → None。"""
    if not face:
        return 1.0
    probs = fair.get(no)
    if not probs:
        return None
    return round(sum(float(probs[FACE_OF[c]]) for c in face), 4)


def _reason(no: str, cites: dict, outs: dict, matrices: dict) -> dict | None:
    cite = cites.get(no)
    if cite == "out":
        text = str(outs.get(no) or "").strip()
        return {"kind": "out", "text": text} if text else None
    if isinstance(cite, int) or (isinstance(cite, str) and cite.isdigit()):
        row = int(cite)
        rows = (matrices.get(no) or {}).get("rows") or []
        evidence = rows[row - 1].get("evidence") if 1 <= row <= len(rows) else None
        return {"kind": "matrix", "row": row, "evidence": evidence}
    return None


def diff_cells(faces: dict[str, str], main: dict[str, str], fair: dict[str, dict],
               cites: dict[str, int | str], outs: dict[str, str],
               matrices: dict[str, dict]) -> list[dict]:
    """和主形不同的格 → [{no, mine, main, cover_mine, cover_main, excl_mine, excl_main,
    reason: {kind: "matrix", row, evidence} | {kind: "out", text} | None}]；'丢' 记作空面。"""
    out = []
    for no in sorted({*map(str, faces), *map(str, main)}, key=int):
        mine, theirs = _face(faces.get(no)), _face(main.get(no))
        if mine == theirs:
            continue
        cm, ct = _cover(fair, no, mine), _cover(fair, no, theirs)
        out.append({"no": no, "mine": mine, "main": theirs,
                    "cover_mine": cm, "cover_main": ct,
                    "excl_mine": None if cm is None else round(1 - cm, 4),
                    "excl_main": None if ct is None else round(1 - ct, 4),
                    "reason": _reason(no, cites, outs, matrices)})
    return out


def cite_readout(diffs: list[dict]) -> dict:
    """{diffs, matrix, outside, blank}——§5⑪「理由引用矩阵行」的读数。"""
    kinds = [(d.get("reason") or {}).get("kind") for d in diffs]
    return {"diffs": len(diffs), "matrix": kinds.count("matrix"),
            "outside": kinds.count("out"), "blank": kinds.count(None)}


def _path(data_dir: Path, issue: str) -> Path:
    return Path(data_dir) / "zucai" / f"{issue}{BRIDGE_SUFFIX}"


def bridge_record(data_dir: Path, issue: str) -> dict | None:
    """本期已走过的桥（只走一次：有记录即返回第一条）。"""
    path = _path(data_dir, issue)
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            return json.loads(line)
    return None


def append_bridge(data_dir: Path, issue: str, record: dict) -> Path:
    """追加 zucai/<期>-bridge.jsonl；已有记录则抛 BridgeError（只走一次由服务端守）。"""
    old = bridge_record(data_dir, issue)
    if old is not None:
        at = parse_bj(old.get("at"))
        raise BridgeError(f"本期桥已走过（{at.strftime('%H:%M') if at else '时刻不明'}）")
    row = {"issue": str(issue), "stage": "B1",
           "at": datetime.now(BJ).isoformat(timespec="seconds"), **record}
    path = _path(data_dir, issue)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def bridge_ledger(data_dir: Path, issue: str) -> dict:
    """§5⑪：{walked, at, b1_faces, readout, real: [{slip_id, changed: [no…], alive_unknown}]}
    real＝本期实购票与 B1 的差异格（实票登记后才有）。改的格活/死要赛果，本模块不读赛果：
    `alive_unknown` 恒为 True，retro 按开奖串手填。"""
    rec = bridge_record(data_dir, issue)
    if rec is None:
        return {"walked": False, "at": None, "b1_faces": None, "readout": None, "real": []}
    b1 = {str(k): v for k, v in (rec.get("faces") or {}).items()}
    b1_id = rec.get("slip_id") or f"{issue}-B1"
    slips = load_slips(data_dir, issue=str(issue))
    # 只和同渠道的实票比：胜负彩 14 场对任九 9 场的 B1，丢掉的 5 场全会被记成「改了」
    channel = rec.get("channel") or next(
        (s.channel for s in slips if s.slip_id == b1_id),
        "shengfucai" if len(b1) == 14 else "renjiu")
    real = []
    for slip in slips:
        if not slip.purchased or slip.slip_id == b1_id or slip.channel != channel:
            continue
        nos = {*map(str, slip.faces), *b1}
        changed = [no for no in sorted(nos, key=int)
                   if _face(slip.faces.get(no)) != _face(b1.get(no))]
        real.append({"slip_id": slip.slip_id, "changed": changed, "alive_unknown": True})
    return {"walked": True, "at": rec.get("at"), "b1_faces": b1,
            "readout": cite_readout(rec.get("diffs") or []), "real": real}
