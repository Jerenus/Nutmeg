#!/usr/bin/env python
"""统一语料 v2 —— 把两条泳道的「场次 × 去水价格 × 赛果（× 判读标签）」并成一份。

出生事故 2026-09-18（26128 复盘）：`zucai_loop corpus` 只吃 `*-reads.json`，
于是 26125/26127/26128 三期跳过 B4 就等于**判断没发生过**；而语料里 428 条 Read
只有 38 条 `belief≠prior`、最后一次移动停在 26110 —— loop 想测的「判读 vs 市场」
那条轴，我们从 26111 起就没往里写过东西。同时 C11（虚假方向带 n=18）与
C12（平局错价带 n=14）这两条**在跑的规则**，各自只有十几个样本。

本脚本因此换一个语料口径：
  ① `zucai_legs` —— 每期 `*-legs-base.json` 的 14 场（fair + 旗/完整度/牌照四问/
     先例/conf 等结构化标签）。**跳过 B4 也有**，只要 legs 落了盘。
  ② `zucai_read` —— `*-reads.json` 的 prior/belief（历史口径，仍收，用于判读移动分析）。
  ③ `jczq_board` —— 竞彩日板 `daily/<date>/bold_odds.json` 的去水 `fair_probability`
     × `jc-results.json`。**这批场次绝大多数我们从没下过注**，所以它是**无选择偏差**的
     价格校准样本，正是 C11/C12 这类「价格带」规则缺的东西。
  ④ `jczq_research` —— 竞彩逐场深研 `daily/<date>/research-<code>.json` 的结构化标签。
     2026-09-20 实测：语料 952 行只有 84 行带标签（8.8%），而 58 份 research 产物
     一份都没进来 —— **标签产能不是"比赛不够"，是没接线**。接上之后标签按 R0 的
     30 场/日增长，而不是 14 场/期。research 还独有两个 legs-base 没有的字段：
     `death_three_proofs`（逐面 a/b/c 三证 + proof_count + verdict）与
     `hole_location`（洞在进攻端还是防守端 —— 画像①判"能赢"vs"能进球"的那一格）。

⛔口径纪律：
  · 价格带类检验（top1 档 / 平局带 / gap12 带）可以吃全部行——它只问价格准不准。
  · 标签类检验（旗 / 完整度 / 牌照 / 先例）只能吃有标签的行（zucai_legs 子集）。
  · **前瞻预注册（F2/F3/F4）不得用本语料回补样本**——它们的窗与口径写死在 prereg 里，
    扩样本只服务于「未预注册的规则复检」和「新候选的发现」，发现之后仍须前瞻。
  · 两条泳道会重叠（26128 的 14 场里 10 场同时在 9/17 竞彩板上）。去重优先 titan007
    match_id（`<issue>-odds-intl.json` 带），其次按「同日 + fair 三元组 ≤1.5pp」判同场。

用法：
    uv run python experiments/corpus_build.py --out experiments/corpus-v2.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Z = os.path.join(ROOT, ".nutmeg-data", "zucai")
J = os.path.join(ROOT, ".nutmeg-data", "jczq")
KEY = {"home": "3", "draw": "1", "away": "0"}
_DUP_TOL = 0.015


def _load(path, default=None):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _issue_dates(issue: str) -> dict[int, str]:
    doc = _load(f"{Z}/{issue}-issue.json", {}) or {}
    return {m["match_no"]: m.get("match_date") or (m.get("kickoff_bj") or "")[:10]
            for m in doc.get("matches", [])}


def _cross_ids(issue: str) -> dict[int, dict]:
    doc = _load(f"{Z}/{issue}-odds-intl.json", {}) or {}
    return {m["match_no"]: {"titan007_id": m.get("titan007_match_id"),
                            "jczq_no": m.get("jczq_match_no")}
            for m in doc.get("matches", []) if m.get("match_no")}


def zucai_rows() -> list[dict]:
    results = _load(f"{Z}/official-results.json", {}) or {}
    reads_conf: dict[tuple[str, int], int] = {}
    reads_prior: dict[tuple[str, int], tuple[dict, dict]] = {}
    for p in sorted(glob.glob(f"{Z}/*-reads.json")):
        issue = re.match(r".*/(\d{5})-reads", p).group(1)
        doc = _load(p, [])
        if not isinstance(doc, list):
            continue
        for i, r in enumerate(doc):
            m = (re.search(r"-(\d{2})-had", r.get("read_id", ""))
                 or re.search(r"场(\d+)", r.get("note", "")))
            n = int(m.group(1)) if m else i + 1
            if n > 14:
                continue
            if r.get("confidence") is not None:
                reads_conf[(issue, n)] = r["confidence"]
            if r.get("prior"):
                reads_prior[(issue, n)] = (r["prior"], r.get("belief") or r["prior"])

    rows: list[dict] = []
    issues = sorted({re.match(r".*/(\d{5})-", p).group(1)
                     for p in glob.glob(f"{Z}/*-legs-base.json")}
                    | {i for i, _ in reads_conf} | {i for i, _ in reads_prior})
    for issue in issues:
        if issue not in results:
            continue
        out = results[issue].split()
        dates, xids = _issue_dates(issue), _cross_ids(issue)
        legs = (_load(f"{Z}/{issue}-legs-base.json", {}) or {}).get("legs") or {}
        for n in range(1, 15):
            lg = legs.get(str(n)) if isinstance(legs, dict) else None
            fair = (lg or {}).get("fair") or {}
            src = "legs-base"
            if not fair and (issue, n) in reads_prior:
                fair, src = reads_prior[(issue, n)][0], "reads.prior"
            if not fair or out[n - 1] not in ("3", "1", "0"):
                continue                      # `*` = 该场作废/延期，官方串里留的占位
            prior, belief = reads_prior.get((issue, n), (fair, fair))
            row = dict(
                src="zucai", key=f"{issue}-{n}", issue=issue, match_no=n,
                date=dates.get(n), name=(lg or {}).get("name"),
                fair=fair, belief=belief, fair_source=src, actual=out[n - 1],
                conf=(lg or {}).get("confidence", reads_conf.get((issue, n))),
                belief_moved=any(abs(prior.get(k, 0) - belief.get(k, 0)) > 1e-6 for k in prior),
                labels=None)
            row.update(xids.get(n, {}))
            if lg:
                row["labels"] = dict(
                    anchor_integrity=lg.get("anchor_integrity"),
                    directional_flags=[f[0] for f in (lg.get("directional_flags") or [])],
                    nondirectional_flags=lg.get("nondirectional_flags") or [],
                    license_questions=lg.get("license_questions") or {},
                    crash_markers=lg.get("crash_markers") or [],
                    tracking_tags=lg.get("tracking_tags") or [],
                    precedents=[[x[0], x[2]] for x in (lg.get("precedents") or []) if len(x) >= 3])
            rows.append(row)
    return rows


def _research_labels(doc: dict | None) -> dict | None:
    """竞彩逐场深研产物 → 与 zucai_legs 同构的标签块（多两个 research 独有字段）。

    出生事故 2026-09-20：R0 自 09-19 起每天产 30 份 `research-*.json`，字段比足彩
    `legs-base` 还全，而 `jczq_rows` 写死 `labels=None`，一份都没进语料。结果是
    「活面影响几度」「崩塌面是真信息还是噪音」这类问题的可用样本卡在 84 行。
    """
    if not isinstance(doc, dict) or not doc:
        return None
    return dict(
        anchor_integrity=doc.get("anchor_integrity"),
        directional_flags=[f[0] for f in (doc.get("directional_flags") or [])],
        nondirectional_flags=doc.get("nondirectional_flags") or [],
        license_questions=doc.get("license_questions") or {},
        crash_markers=doc.get("crash_markers") or [],
        tracking_tags=[],
        precedents=[[x[0], x[2]] for x in (doc.get("precedents") or []) if len(x) >= 3],
        # ↓ research 独有，legs-base 没有
        death_three_proofs={
            face: {
                "proof_count": (blk or {}).get("proof_count"),
                "verdict": (blk or {}).get("verdict"),
                "a": (blk or {}).get("a_no_scoring_mechanism"),
                "b": (blk or {}).get("b_precedent_carrier_gone"),
                "c": (blk or {}).get("c_anchor_pass"),
            }
            for face, blk in (doc.get("death_three_proofs") or {}).items()
        },
        # ⛔ hole_location 暂不入语料：2026-09-20 实测 55 份产物里出现 11 种以上不同
        # key 组合（最常见的 {anchor,detail,opponent} 只占 28/55），是自由散文不是变量。
        # 画像①判「能赢 vs 只能进球」全靠这一格，须先在 research_prompt 里给受控词典
        # （attack / defense / spine / goalkeeper / both）再接线，否则聚不成可统计量。
        anchor_side=doc.get("anchor_side"),
        label_source="research",
    )


def jczq_rows() -> list[dict]:
    results = _load(f"{J}/jc-results.json", {}) or {}
    rows: list[dict] = []
    for date in sorted(os.listdir(f"{J}/daily")):
        bold = _load(f"{J}/daily/{date}/bold_odds.json", {}) or {}
        day = results.get(date) or {}
        if not bold or not day:
            continue
        for jno, mk in bold.items():
            got = day.get(jno)
            mw = (mk or {}).get("match_winner") or {}
            fair = mw.get("fair_probability") or {}
            if not got or not fair or got.get("ft_home") is None:
                continue
            gh, ga = got["ft_home"], got["ft_away"]
            actual = "3" if gh > ga else ("0" if ga > gh else "1")
            research = _load(f"{J}/daily/{date}/research-{jno}.json", {}) or {}
            rows.append(dict(
                src="jczq", key=f"{date}-{jno}", issue=None, match_no=jno, date=date,
                name=None, fair=fair, belief=fair, fair_source="bold_odds", actual=actual,
                conf=research.get("confidence"), belief_moved=False,
                labels=_research_labels(research),
                titan007_id=str(got.get("match_id") or "") or None, jczq_no=jno,
                books=mw.get("bookmaker_count"), opening_odds=mw.get("opening_odds"),
                goals=[gh, ga], ht=[got.get("ht_home"), got.get("ht_away")]))
    return rows


def dedupe(zc: list[dict], jc: list[dict]) -> tuple[list[dict], int]:
    """同一场比赛两条泳道各有一行时保留足彩行（它带标签），竞彩行丢弃。"""
    zt = {r.get("titan007_id") for r in zc if r.get("titan007_id")}
    zbyday: dict[str, list[dict]] = {}
    for r in zc:
        if r.get("date"):
            zbyday.setdefault(r["date"], []).append(r)
    kept, dropped = [], 0
    for r in jc:
        if r.get("titan007_id") and r["titan007_id"] in zt:
            dropped += 1
            continue
        near = False
        for z in zbyday.get(r["date"], []):
            if all(abs(r["fair"].get(k, 0) - z["fair"].get(k, 0)) <= _DUP_TOL
                   for k in ("home", "draw", "away")):
                near = True
                break
        if near:
            dropped += 1
            continue
        kept.append(r)
    return zc + kept, dropped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "experiments", "corpus-v2.json"))
    args = ap.parse_args()
    zc, jc = zucai_rows(), jczq_rows()
    rows, dropped = dedupe(zc, jc)
    labeled = [r for r in rows if r.get("labels")]
    moved = [r for r in rows if r.get("belief_moved")]
    json.dump({"built_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
               "n": len(rows), "rows": rows}, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False)
    print(f"语料 v2：{len(rows)} 行  = 足彩 {len(zc)}（{len(set(r['issue'] for r in zc))} 期）"
          f" + 竞彩 {len(rows) - len(zc)}（去重丢弃 {dropped} 行重叠）")
    print(f"  带判读标签（旗/完整度/牌照/先例）：{len(labeled)} 行"
          f"（{len(set(r['issue'] for r in labeled))} 期）")
    print(f"  belief≠prior 的判读移动：{len(moved)} 行")
    print(f"  写入 {args.out}")


if __name__ == "__main__":
    main()
