#!/usr/bin/env python
"""因子 2 前瞻观察仪 —— 只登记，不改票面。

预注册见 ``experiments/prereg-26126-F1c-F2.json``（26126-26137，n≥140 结账）。

⛔**结构性隔离**：本脚本只读 issue/odds/结果，产出独立落在
``<issue>-f2-observation.json`` 与 ``experiments/prereg-26126-F2-ledger.json``。
它**不写 legs、不进 prep、不被任何判读或构票命令引用**——候选档因子不得以任何
形式影响票面，这条隔离是靠「没有调用边」保证的，不是靠自律。

两个子命令：
  ``record --issue 26126``  赛前跑：抓初盘/终盘让球线，按**预注册的分档**落一份
                             带采集时刻的观察单。开球后跑会被拒绝（泄漏闸）。
  ``grade  --issue 26126``  开奖后跑：用官方赛果判残差，追加进 ledger 并打印累计。

⚠️``record`` 必须在最早一场开球前跑完；任何一场已开球即整期拒收——事后补录的
观察单没有前瞻价值，与 26113「识别≠行动」同一类自欺。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

# 以 `python scripts/xxx.py` 直跑时 sys.path[0] 是 scripts/，兄弟模块要按包导入
# 就必须把仓根补进来；否则 `from scripts.zucai_handicap_line import ...` 会炸。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

Z = Path(".nutmeg-data/zucai")
LEDGER = Path("experiments/prereg-26126-F2-ledger.json")
FACE = {"3": "home", "1": "draw", "0": "away"}

BUCKETS = (
    ("向客 ≤-0.25", lambda x: x <= -0.25),
    ("不动 0", lambda x: x == 0.0),
    ("向主 +0.25", lambda x: 0.0 < x <= 0.25),
    ("向主 ≥+0.5", lambda x: x >= 0.5),
)
"""⛔预注册的分档，**结账前不得修改**（prereg-26126-F1c-F2.json）。"""

PRIMARY_CELL = "向主 ≥+0.5"
"""证伪判据挂在这一格：n≥140 时其主胜残差 95%CI 上界 <+2pp 即剔除 F2。"""


def _bucket(move: float) -> str:
    for name, fn in BUCKETS:
        if fn(move):
            return name
    return "其它"


def record(issue: str, *, allow_late: bool) -> None:
    import httpx

    from nutmeg.data.titan007 import Titan007Client
    from nutmeg.services.zucai_titan007_odds import align_zucai_to_titan007
    from scripts.zucai_handicap_line import HEADERS, URL, parse_handicap

    issue_doc = json.loads((Z / f"{issue}-issue.json").read_text("utf-8"))
    matches = issue_doc.get("matches") or []
    now = datetime.now()
    kickoffs = []
    for m in matches:
        try:
            kickoffs.append(datetime.fromisoformat(str(m["kickoff_bj"])))
        except (KeyError, TypeError, ValueError):
            continue
    if kickoffs and now >= min(kickoffs) and not allow_late:
        raise SystemExit(
            f"⛔泄漏闸：最早一场已于 {min(kickoffs)} 开球，现在 {now:%Y-%m-%d %H:%M}。"
            f"事后补录的观察单没有前瞻价值，整期拒收。")

    client = Titan007Client()
    try:
        board = list(client.fetch_board())
    finally:
        client.close()
    aligned = align_zucai_to_titan007(matches, board)
    print(f"板面对齐 {len(aligned)}/{len(matches)} 场")

    fair_path = Z / f"{issue}-prep-afternoon.json"
    fair = {}
    if fair_path.exists():
        for no, rec in json.loads(fair_path.read_text("utf-8")).get("records", {}).items():
            fair[str(no)] = rec.get("fair_blend") or rec.get("fair_had")

    http = httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True)
    obs: dict[str, dict] = {}
    try:
        for no, row in sorted(aligned.items(), key=lambda kv: kv[0]):
            try:
                resp = http.get(URL.format(mid=row.match_id))
                resp.raise_for_status()
                books = parse_handicap(resp.content.decode("utf-8", "replace"))
            except Exception as exc:      # noqa: BLE001 报告,不静默
                print(f"  ✗ 场{no}: {type(exc).__name__} {exc}")
                continue
            if len(books) < 8:
                print(f"  ✗ 场{no}: 仅解出 {len(books)} 家，丢弃")
                continue
            op = statistics.median(b["opening_goals"] for b in books)
            cl = statistics.median(b["closing_goals"] for b in books)
            move = round(cl - op, 3)
            obs[str(no)] = {
                "match_id": row.match_id, "n_books": len(books),
                "opening_median": op, "closing_median": cl, "line_move": move,
                "moved_share": sum(1 for b in books
                                   if b["closing_goals"] != b["opening_goals"]) / len(books),
                "bucket": _bucket(move),
                "fair": fair.get(str(no)),
            }
    finally:
        http.close()

    out = {
        "issue": issue, "captured_at": now.isoformat(timespec="seconds"),
        "earliest_kickoff": min(kickoffs).isoformat() if kickoffs else None,
        "prereg": "experiments/prereg-26126-F1c-F2.json",
        # ⚠️非前瞻样本必须留痕，否则回补的观察单与真前瞻单无法区分。
        "prospective": not allow_late,
        "buckets_frozen": [name for name, _ in BUCKETS],
        "note": "观察仪产物：只登记不改票面，禁止被判读/构票引用",
        "observations": obs,
    }
    path = Z / f"{issue}-f2-observation.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    print(f"观察单 {len(obs)} 场 → {path}")
    # RSI 接线（2026-09-18）：落盘即登记 F2 义务；失败只打印，不影响观察单。
    from nutmeg.decision.rsi_wiring import after_observation_artifact
    after_observation_artifact(exp="F2", duty="f2-observation", issue=issue,
                               day=(min(kickoffs).date().isoformat() if kickoffs
                                    else now.date().isoformat()),
                               artifact=path, n_rows=len(obs), data_dir=Z.parent)
    for name, _ in BUCKETS:
        hit = [n for n, v in obs.items() if v["bucket"] == name]
        if hit:
            print(f"  {name:14} 场{'/'.join(sorted(hit, key=int))}")


def grade(issue: str) -> None:
    path = Z / f"{issue}-f2-observation.json"
    if not path.exists():
        raise SystemExit(f"⛔无观察单 {path}——本期无前瞻登记，不得事后补")
    doc = json.loads(path.read_text("utf-8"))
    results = json.loads((Z / "official-results.json").read_text("utf-8"))
    if issue not in results:
        raise SystemExit(f"⛔{issue} 尚未开奖")
    outcomes = results[issue].split()
    if len(outcomes) != 14:
        raise SystemExit(f"⛔{issue} 赛果串长度 {len(outcomes)} ≠ 14")

    ledger = json.loads(LEDGER.read_text("utf-8")) if LEDGER.exists() else {"issues": {}}
    rows = []
    for no, v in doc["observations"].items():
        if not v.get("fair"):
            continue
        rows.append({"no": no, "bucket": v["bucket"], "fair": v["fair"],
                     "moved_share": v["moved_share"],
                     "actual": FACE[outcomes[int(no) - 1]]})
    if not doc.get("prospective", True):
        print(f"⚠️{issue} 是 --allow-late 回补的**非前瞻**观察单，"
              f"只入对照不入前瞻账。")
    ledger["issues"][issue] = {
        "prospective": bool(doc.get("prospective", True)),
        "captured_at": doc["captured_at"],
        "graded_at": datetime.now().isoformat(timespec="seconds"),
        "rows": rows,
    }
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), "utf-8")

    allrows = [r for v in ledger["issues"].values()
               if v.get("prospective", True) for r in v["rows"]]
    print(f"累计 n={len(allrows)}  期={len(ledger['issues'])}  "
          f"（结账线 n≥140）\n")
    print(f"{'档':16} {'n':>4} {'主胜期望':>9} {'主胜实开':>9} {'残差':>9}")
    for name, _ in BUCKETS:
        sub = [r for r in allrows if r["bucket"] == name]
        if not sub:
            continue
        exp = statistics.fmean(r["fair"]["home"] for r in sub)
        act = sum(1 for r in sub if r["actual"] == "home") / len(sub)
        mark = " ←证伪判据挂此格" if name == PRIMARY_CELL else ""
        print(f"{name:16} {len(sub):>4} {exp*100:>8.1f}% {act*100:>8.1f}% "
              f"{(act-exp)*100:>+8.1f}pp{mark}")
    n_primary = sum(1 for r in allrows if r["bucket"] == PRIMARY_CELL)
    print(f"\n⛔结账前不得调参、不得改分档、不得用于任何票面。"
          f"主格累计 n={n_primary}。")


WINDOW_LATE_MIN = 12
WINDOW_EARLY_MIN = 45
"""``auto`` 的登记窗：距最早开球 12-45 分钟之间才动手。

- 下界 12 分：留出抓取时间，且不贴着泄漏闸的边（闸本身在开球时刻）
- 上界 45 分：**要的是终盘线**，太早抓到的是半程盘
窗宽 33 分 > launchd 的 15 分钟节拍 → 任何开球时刻都必被命中一次。
"""


def auto() -> None:
    """launchd 入口：自己找当期、自己判窗口，不在窗口内就安静退出。

    足彩每期最早开球时刻不同（26124 是 21:00、26125 是 18:00），固定时刻的定时器
    要么抓到半程盘、要么撞上泄漏闸——所以判窗口这件事必须在运行时做。
    """
    now = datetime.now()
    best = None
    for path in sorted(Z.glob("*-issue.json")):
        try:
            doc = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        issue = str(doc.get("issue_id") or path.name[:5])
        kicks = []
        for m in doc.get("matches") or []:
            try:
                kicks.append(datetime.fromisoformat(str(m["kickoff_bj"])))
            except (KeyError, TypeError, ValueError):
                continue
        if not kicks:
            continue
        earliest = min(kicks)
        if earliest <= now:
            continue                      # 已开赛，泄漏闸会拒收
        if best is None or earliest < best[1]:
            best = (issue, earliest)
    if best is None:
        print(f"[{now:%Y-%m-%d %H:%M}] 无未开赛期次，退出")
        return
    issue, earliest = best
    if (Z / f"{issue}-f2-observation.json").exists():
        print(f"[{now:%Y-%m-%d %H:%M}] {issue} 已登记，退出")
        return
    minutes = (earliest - now).total_seconds() / 60.0
    if not (WINDOW_LATE_MIN <= minutes <= WINDOW_EARLY_MIN):
        print(f"[{now:%Y-%m-%d %H:%M}] {issue} 距最早开球 {minutes:.0f} 分，"
              f"不在登记窗 [{WINDOW_LATE_MIN},{WINDOW_EARLY_MIN}]，退出")
        return
    print(f"[{now:%Y-%m-%d %H:%M}] {issue} 距最早开球 {minutes:.0f} 分，开始登记")
    record(issue, allow_late=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="赛前登记（开球后拒收）")
    r.add_argument("--issue", required=True)
    r.add_argument("--allow-late", action="store_true",
                   help="⚠️仅用于回补历史期作对照，登记为非前瞻样本")
    g = sub.add_parser("grade", help="开奖后判分并累计")
    g.add_argument("--issue", required=True)
    sub.add_parser("auto", help="launchd 入口：自找当期+自判窗口，不在窗口就退出")
    a = ap.parse_args()
    if a.cmd == "record":
        record(a.issue, allow_late=a.allow_late)
    elif a.cmd == "auto":
        auto()
    else:
        grade(a.issue)


if __name__ == "__main__":
    main()
