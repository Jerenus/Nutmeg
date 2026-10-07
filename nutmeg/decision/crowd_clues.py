"""人群线索：已登记 CR 假说在本期板面上的触发面（`<期>-clues.jsonl`，只追加、不进内核）。

行类型：scan（一次扫描的标记）/ clue（触发面）/ settle（赛后 outcome + acted）。
「最新线索」= 最后一次 scan 那张快照上的 clue 行；最后一次 scan 没触发就是没有线索。
"""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.crowd_source import load_board
from nutmeg.decision.crowd_trigger import fires

ROLE = {"under": "cover", "over": "fade"}
_CODE = {"home": "3", "draw": "1", "away": "0"}
_FACE_CN = {"3": "主胜", "1": "平", "0": "客胜"}


def clues_path(zdir: Path, issue: str) -> Path:
    return Path(zdir) / f"{issue}-clues.jsonl"


def read_rows(zdir: Path, issue: str) -> list[dict]:
    path = clues_path(zdir, issue)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def _append(zdir: Path, issue: str, rows: list[dict]) -> None:
    if not rows:
        return
    Path(zdir).mkdir(parents=True, exist_ok=True)
    with clues_path(zdir, issue).open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_registry(registry_dir: Path) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text("utf-8"))
            for p in sorted(Path(registry_dir).glob("CR*.json"))}


def scan(zdir: Path, issue: str, *, docs: dict[str, dict], deployed: set[str]) -> list[dict]:
    """对最后一张快照跑全部 CR 触发；同 (实验, 场, 面, 快照) 不重写。→ 新写的 clue 行。"""
    loaded = load_board(zdir, issue)
    if loaded is None:
        return []
    snapshot_at, board = loaded
    rows = read_rows(zdir, issue)
    seen = {(r["exp_id"], r["match_no"], r["face"], r["snapshot_at"])
            for r in rows if r.get("kind") == "clue"}
    by_no = {m.no: m for m in board}
    new = []
    for exp_id, doc in sorted(docs.items()):
        for no, face in fires(doc["trigger"], board):
            if (exp_id, no, face, snapshot_at) in seen:
                continue
            m = by_no[no]
            new.append({"kind": "clue", "issue": issue, "snapshot_at": snapshot_at,
                        "exp_id": exp_id, "label_cn": doc.get("label_cn", ""), "match_no": no,
                        "face": face, "p_face": round(100 * m.p[face], 1),
                        "home": m.home, "away": m.away, "crowd_bias": doc["crowd_bias"],
                        "role": ROLE[doc["crowd_bias"]], "advisory": exp_id not in deployed})
    _append(zdir, issue, [{"kind": "scan", "issue": issue, "snapshot_at": snapshot_at,
                           "n_registered": len(docs)}, *new])
    return new


def latest_clues(rows: list[dict]) -> list[dict]:
    scans = [r["snapshot_at"] for r in rows if r.get("kind") == "scan"]
    if not scans:
        return []
    last = max(scans)
    latest: dict[tuple, dict] = {}
    for r in rows:
        if r.get("kind") == "clue" and r["snapshot_at"] == last:
            latest[(r["exp_id"], r["match_no"], r["face"])] = r
    return list(latest.values())


def ticket_faces(betslips: Path, issue: str) -> list[dict[int, set[str]]]:
    """本期已实购的票 → 每张票 {场号: 盖住的面}。按 slip_id 去重，后写为准。"""
    path = Path(betslips)
    if not path.exists():
        return []
    slips: dict[str, dict] = {}
    for line in path.read_text("utf-8").splitlines():
        if line.strip():
            slip = json.loads(line)
            if str(slip.get("slip_id", "")).startswith(f"{issue}-"):
                slips[slip["slip_id"]] = slip
    return [{int(leg["key"]): {_CODE[s] for s in leg.get("selections") or [] if s in _CODE}
             for leg in slip.get("legs") or []}
            for slip in slips.values() if slip.get("purchased")]


def acted(clue: dict, tickets: list[dict[int, set[str]]]) -> str | None:
    if not tickets:
        return None
    covered = any(clue["face"] in t.get(clue["match_no"], set()) for t in tickets)
    if clue["role"] == "cover":
        return "followed" if covered else "ignored"
    return "ignored" if covered else "followed"


def settle(zdir: Path, issue: str, *, results: list[str] | None,
           tickets: list[dict[int, set[str]]]) -> list[dict]:
    """赛果已出才写；同 (实验, 场, 面) 只结一次。"""
    if results is None:
        return []
    rows = read_rows(zdir, issue)
    done = {(r["exp_id"], r["match_no"], r["face"]) for r in rows if r.get("kind") == "settle"}
    out = []
    for clue in latest_clues(rows):
        key = (clue["exp_id"], clue["match_no"], clue["face"])
        if key in done:
            continue
        code = results[clue["match_no"] - 1]
        outcome = "void" if code == "*" else ("hit" if code == clue["face"] else "miss")
        out.append({"kind": "settle", "issue": issue, "exp_id": clue["exp_id"],
                    "match_no": clue["match_no"], "face": clue["face"], "outcome": outcome,
                    "acted": acted(clue, tickets)})
    _append(zdir, issue, out)
    return out


def render_map(issue: str, rows: list[dict], readings: dict[str, str], *, has_board: bool,
               n_registered: int) -> str:
    lines = ["## 人群地图（官方奖金反推）", ""]
    if not has_board:
        return "\n".join([*lines, "本期无市场底座（zgzcw 未取到），无线索。", ""])
    clues = sorted(latest_clues(rows), key=lambda c: (c["match_no"], c["face"], c["exp_id"]))
    lines += ["> 线索 = 已登记 CR 假说在本期板面的触发面。⚑ advisory（未 deploy，只看不用）；"
              "● 约束（已 deploy）。", "> cover：全国人群少买这类面，盖它中了分得多；"
              "fade：人群多买，中了也分得少，别把全包名额花在它上面。", ""]
    if not clues:
        lines.append(f"本期无线索（已登记假说 {n_registered} 条，均未触发）。")
    else:
        lines += ["| 场 | 对阵 | 面 | 市场P | 假说 | 方向 | 状态 | 代价 |",
                  "|---|---|---|---|---|---|---|---|"]
        for c in clues:
            cost = (f"让掉此面：P −{c['p_face']:.1f}pp" if c["role"] == "fade"
                    else "盖上此面：该场多一个选项")
            lines.append(f"| {c['match_no']} | {c['home']}-{c['away']} | {_FACE_CN[c['face']]} | "
                         f"{c['p_face']:.1f}% | {c['exp_id']} {c['label_cn']} | {c['role']} | "
                         f"{'⚑' if c['advisory'] else '●'} | {cost} |")
    if readings:
        lines += ["", "### 各假说读数", ""]
        lines += [f"- {exp}：{text}" for exp, text in sorted(readings.items())]
    return "\n".join([*lines, ""])
