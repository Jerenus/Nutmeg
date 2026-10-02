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
  ⑤ `zucai_judgment` —— 每期 `*-judgment.json` 的实际出手（call）、conf、note 与标签块。
     2026-09-22 接入：14 期文件五种形态（顶层数字键 / judgments / decisions / matches /
     picks），按已知键名提取，`board` 是散文的期直接跳过不猜。文件内自报的 `made_at`
     只作 `judged_at_declared` 信息位，**不参与 `provably_prospective`**（文件可改且多份
     在开球后被改过）。
  ⑥ `kernel_forecast` —— 内核 `forecast_revisions` × `match_outcomes`（缺时经外部标识回到
     文件赛果）× `market_quotes` 多源时序。见 `kernel_rows` 的说明。
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
from datetime import datetime

from nutmeg.decision.prospective import prospective_fields as _prospective_fields
from nutmeg.decision.research_intake import (
    HOLE_LOCATION_SIDES,
    HOLE_LOCATION_UNITS,
)

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
    return {
        m["match_no"]: m.get("match_date") or (m.get("kickoff_bj") or "")[:10]
        for m in doc.get("matches", [])
    }


def _issue_kickoffs(issue: str) -> dict[int, str | None]:
    doc = _load(f"{Z}/{issue}-issue.json", {}) or {}
    return {
        m["match_no"]: m.get("kickoff_bj")
        for m in doc.get("matches", [])
        if m.get("match_no") is not None
    }


def _calls_time_source(meta: object) -> tuple[object, str | None]:
    if not isinstance(meta, dict) or not meta.get("built_at"):
        return None, None
    source = str(meta.get("built_at_source") or "unknown")
    grade = str(meta.get("evidence_grade") or "unknown")
    return meta["built_at"], f"calls._meta.built_at:{source}:{grade}"


def _cross_ids(issue: str) -> dict[int, dict]:
    doc = _load(f"{Z}/{issue}-odds-intl.json", {}) or {}
    return {
        m["match_no"]: {
            "titan007_id": m.get("titan007_match_id"),
            "jczq_no": m.get("jczq_match_no"),
        }
        for m in doc.get("matches", [])
        if m.get("match_no")
    }


_JUDGMENT_CALL_KEYS = (
    "action", "ticket", "pick", "picks", "selection", "cover_hint", "prescription"
)
_JUDGMENT_CONF_KEYS = ("confidence", "conf")
_JUDGMENT_NOTE_KEYS = ("note", "reason")
_JUDGMENT_LABEL_KEYS = (
    "anchor_integrity",
    "directional_flags",
    "nondirectional_flags",
    "license_score",
    "license_questions",
    "proofs",
    "precedents",
    "crash_markers",
    "tracking_tags",
    "team_tags",
    "flags",
    "direction",
    "dir",
    "primary",
    "score",
    "cover",
    "coverage_prob",
)


def _match_no(entry: dict, fallback: object) -> int | None:
    for key in ("match_no", "m", "no"):
        if entry.get(key) is not None:
            try:
                return int(str(entry[key]))
            except ValueError:
                return None
    try:
        return int(str(fallback))
    except (TypeError, ValueError):
        return None


def _judgment_entries(doc: object) -> tuple[dict[int, dict], str | None]:
    """Locate the per-match block inside one `*-judgment.json`, whatever its era.

    Known shapes (2026-07 → 2026-09): top-level numeric keys; `judgments` dict;
    `picks` / `decisions` / `matches` lists; `belief` dict of 3-vectors. A file whose
    per-match block is prose (`board` as a string) yields nothing rather than a guess.
    """
    if not isinstance(doc, dict):
        return {}, None
    numeric = {k: v for k, v in doc.items() if str(k).isdigit() and isinstance(v, dict)}
    if numeric:
        return {int(k): v for k, v in numeric.items()}, "judgment[match_no]"
    for key in ("judgments", "decisions", "matches", "picks"):
        block = doc.get(key)
        if isinstance(block, dict) and block and all(isinstance(v, dict) for v in block.values()):
            return {
                n: v for k, v in block.items() if (n := _match_no(v, k)) is not None
            }, f"judgment.{key}"
        if isinstance(block, list) and block and all(isinstance(v, dict) for v in block):
            return {
                n: v for i, v in enumerate(block) if (n := _match_no(v, i + 1)) is not None
            }, f"judgment.{key}"
    return {}, None


def _judgment_calls(issue: str) -> tuple[dict[int, dict], dict]:
    doc = (
        _load(f"{Z}/{issue}-judgment.json", {})
        or _load(f"{Z}/{issue}-judgment-v1.json", {})
        or {}
    )
    entries, source = _judgment_entries(doc)
    meta = {
        "source": source,
        "made_at_declared": doc.get("made_at") if isinstance(doc, dict) else None,
    }
    out: dict[int, dict] = {}
    for n, entry in entries.items():
        call = next((entry[k] for k in _JUDGMENT_CALL_KEYS if entry.get(k) not in (None, "")), None)
        conf = next((entry[k] for k in _JUDGMENT_CONF_KEYS if entry.get(k) not in (None, "")), None)
        note = next((entry[k] for k in _JUDGMENT_NOTE_KEYS if entry.get(k)), "")
        labels = {k: entry[k] for k in _JUDGMENT_LABEL_KEYS if k in entry}
        fair = None
        anchor_fair = entry.get("anchor_fair_had")
        if isinstance(anchor_fair, dict) and {"3", "1", "0"} <= set(anchor_fair):
            fair = {"home": anchor_fair["3"], "draw": anchor_fair["1"], "away": anchor_fair["0"]}
        try:
            conf = int(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf = None
        out[n] = {
            "call": str(call) if call is not None else None,
            "conf": conf,
            "note": str(note),
            "labels": labels,
            "fair": fair,
        }
    return out, meta


def zucai_rows() -> list[dict]:
    results = _load(f"{Z}/official-results.json", {}) or {}
    reads_conf: dict[tuple[str, int], int] = {}
    reads_prior: dict[tuple[str, int], tuple[dict, dict]] = {}
    for p in sorted(glob.glob(f"{Z}/*-reads.json")):
        issue = re.match(r".*/(\d{5})-reads", p).group(1)
        doc = _load(p, [])
        if not isinstance(doc, list):
            continue
        # `<issue>-reads-fix.json`：同 read_id 的修正版覆盖原 Read（2026-09-22 接入）
        fixes = _load(f"{Z}/{issue}-reads-fix.json", []) or []
        if isinstance(fixes, list) and fixes:
            by_id = {r.get("read_id"): r for r in fixes if isinstance(r, dict)}
            doc = [by_id.get(r.get("read_id"), r) for r in doc]
        for i, r in enumerate(doc):
            m = re.search(r"-(\d{2})-had", r.get("read_id", "")) or re.search(
                r"场(\d+)", r.get("note", "")
            )
            n = int(m.group(1)) if m else i + 1
            if n > 14:
                continue
            if r.get("confidence") is not None:
                reads_conf[(issue, n)] = r["confidence"]
            if r.get("prior"):
                reads_prior[(issue, n)] = (r["prior"], r.get("belief") or r["prior"])

    rows: list[dict] = []
    issues = sorted(
        {re.match(r".*/(\d{5})-", p).group(1) for p in glob.glob(f"{Z}/*-legs-base.json")}
        | {
            m.group(1)
            for p in glob.glob(f"{Z}/*-judgment.json")
            if (m := re.match(r".*/(\d{5})-judgment", p))
        }
        | {i for i, _ in reads_conf}
        | {i for i, _ in reads_prior}
    )
    for issue in issues:
        if issue not in results:
            continue
        out = results[issue].split()
        postmortems = _load(f"{Z}/{issue}-postmortem.json", []) or []
        postmortem_by_match = {
            int(row["match_no"]): row
            for row in postmortems
            if isinstance(row, dict) and row.get("match_no") is not None
        }
        dates, kickoffs, xids = _issue_dates(issue), _issue_kickoffs(issue), _cross_ids(issue)
        legs = (_load(f"{Z}/{issue}-legs-base.json", {}) or {}).get("legs") or {}
        calls = _load(f"{Z}/{issue}-calls.json", {}) or {}
        calls_time, calls_source = _calls_time_source(calls.get("_meta"))
        judgments, judgment_meta = _judgment_calls(issue)
        closing_by_no = _load(f"{Z}/{issue}-closing-odds.json", {}) or {}
        for n in range(1, 15):
            lg = legs.get(str(n)) if isinstance(legs, dict) else None
            jd = judgments.get(n) or {}
            fair = (lg or {}).get("fair") or {}
            src = "legs-base"
            if not fair and (issue, n) in reads_prior:
                fair, src = reads_prior[(issue, n)][0], "reads.prior"
            if not fair and jd.get("fair"):
                fair, src = jd["fair"], "judgment.anchor_fair_had"
            if not fair or out[n - 1] not in ("3", "1", "0"):
                continue  # `*` = 该场作废/延期，官方串里留的占位
            prior, belief = reads_prior.get((issue, n), (fair, fair))
            row = dict(
                src="zucai",
                key=f"{issue}-{n}",
                issue=issue,
                match_no=n,
                date=dates.get(n),
                name=(lg or {}).get("name"),
                fair=fair,
                belief=belief,
                fair_source=src,
                actual=out[n - 1],
                conf=(lg or {}).get("confidence", reads_conf.get((issue, n), jd.get("conf"))),
                belief_moved=any(abs(prior.get(k, 0) - belief.get(k, 0)) > 1e-6 for k in prior),
                labels=None,
                call=jd.get("call"),
                note=jd.get("note") or "",
                fair_kind="read_time",
                closing=_closing_block(closing_by_no.get(str(n))),
            )
            row.update(xids.get(n, {}))
            judged_at = (lg or {}).get("judged_at") or calls_time
            judged_at_source = (
                "legs-base.legs[n].judged_at" if (lg or {}).get("judged_at") else calls_source
            )
            row.update(
                _prospective_fields(
                    judged_at=judged_at,
                    kickoff_bj=kickoffs.get(n),
                    judged_at_source=judged_at_source,
                )
            )
            if lg:
                row["labels"] = dict(
                    anchor_integrity=lg.get("anchor_integrity"),
                    directional_flags=[f[0] for f in (lg.get("directional_flags") or [])],
                    nondirectional_flags=lg.get("nondirectional_flags") or [],
                    license_questions=lg.get("license_questions") or {},
                    crash_markers=lg.get("crash_markers") or [],
                    tracking_tags=lg.get("tracking_tags") or [],
                    precedents=[[x[0], x[2]] for x in (lg.get("precedents") or []) if len(x) >= 3],
                )
            research = _load(f"{Z}/{issue}-research-m{n}.json", {}) or {}
            research_labels = _research_labels(research)
            if research_labels:
                research_labels["rubric_b"] = _rubric_sidecar(
                    f"{Z}/{issue}-rubric-m{n}.json", kickoff_bj=kickoffs.get(n))
                # 足彩逐场深研（`<issue>-research-m<n>.json`，2026-09-22 接入，7 期 91 份）：
                # 与竞彩深研同构。legs-base 的旗/完整度优先，research 补它没有的
                # 死亡三证 / 洞位 / anchor_side；`researched_at` 只存信息位，不进前瞻证明。
                base = row["labels"] or {}
                kept = {k: v for k, v in base.items() if v not in (None, [], {})}
                merged = {**research_labels, **kept}
                merged["label_source"] = "legs+research" if base else "research"
                merged["researched_at"] = research.get("researched_at")
                row["labels"] = merged
                if row.get("conf") is None and research.get("confidence") is not None:
                    row["conf"] = research.get("confidence")
            if jd:
                # Declared `made_at` is kept as information only. The file is mutable and
                # several were edited after kickoff, so it never feeds `provably_prospective`.
                row["labels"] = {
                    **(row["labels"] or {}),
                    "judgment": {**jd["labels"], "_source": judgment_meta["source"]},
                }
                row["judged_at_declared"] = judgment_meta["made_at_declared"]
            row["labels"] = _merge_postmortem(row["labels"], postmortem_by_match.get(n))
            rows.append(row)
    return rows


def _rubric_answers(rubric: dict | None) -> dict | None:
    """判断 rubric 的逐项答案 → {id: {answer, p}}（弃权项不进）；没有 rubric → None。"""
    if not isinstance(rubric, dict) or not isinstance(rubric.get("items"), dict):
        return None
    out = {}
    for item_id, row in rubric["items"].items():
        if isinstance(row, dict) and not row.get("abstain") and row.get("answer") is not None:
            out[item_id] = {"answer": row.get("answer"), "p": row.get("p")}
    return out


def _aware(value: str) -> datetime:
    """无时区一律按北京时间（足彩 kickoff_bj 是 `YYYY-MM-DD HH:MM`）。"""
    from datetime import timedelta, timezone

    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone(timedelta(hours=8)))


def _rubric_sidecar(path: str, *, kickoff_bj: str | None) -> dict | None:
    """读者 B 的侧车（`rubric-<code>.json` / `<issue>-rubric-m<n>.json`）：
    只在 `at < kickoff` 时带入语料（前瞻），否则 None。"""
    doc = _load(path, {}) or {}
    b = doc.get("b")
    if not isinstance(b, dict):
        return None
    at, kick = doc.get("at"), kickoff_bj
    try:
        if at and kick and _aware(str(at)) >= _aware(str(kick).replace(" ", "T")):
            return None
    except ValueError:
        return None
    answers = _rubric_answers(b)
    return {"items": answers, "belief": b.get("belief"), "kappa": doc.get("kappa"),
            "model": doc.get("model")} if answers is not None else None


def _with_sidecar(labels: dict | None, sidecar: dict | None) -> dict | None:
    if labels is None:
        return None
    return {**labels, "rubric_b": sidecar}


def _research_labels(doc: dict | None) -> dict | None:
    """竞彩逐场深研产物 → 与 zucai_legs 同构的标签块（多两个 research 独有字段）。

    出生事故 2026-09-20：R0 自 09-19 起每天产 30 份 `research-*.json`，字段比足彩
    `legs-base` 还全，而 `jczq_rows` 写死 `labels=None`，一份都没进语料。结果是
    「活面影响几度」「崩塌面是真信息还是噪音」这类问题的可用样本卡在 84 行。
    """
    if not isinstance(doc, dict) or not doc:
        return None
    if not isinstance(doc.get("death_three_proofs"), dict):
        doc = {**doc, "death_three_proofs": {}}
    hole = doc.get("hole_location")
    if not isinstance(hole, dict):
        hole = {}
    controlled_hole = (
        {"unit", "side", "priced_in", "detail"} <= set(hole)
        and hole.get("unit") in HOLE_LOCATION_UNITS
        and hole.get("side") in HOLE_LOCATION_SIDES
        and isinstance(hole.get("priced_in"), bool)
    )
    return dict(
        anchor_integrity=doc.get("anchor_integrity"),
        directional_flags=[f[0] for f in (doc.get("directional_flags") or [])],
        nondirectional_flags=doc.get("nondirectional_flags") or [],
        license_questions=doc.get("license_questions") or {},
        crash_markers=doc.get("crash_markers") or [],
        precedents=[[x[0], x[2]] for x in (doc.get("precedents") or []) if len(x) >= 3],
        # ↓ research 独有，legs-base 没有
        death_three_proofs={
            face: {
                "proof_count": (
                    (blk or {}).get("proof_count")
                    if (blk or {}).get("proof_count") is not None
                    else (
                        f"{(blk or {}).get('proofs_met')}/3"
                        if isinstance((blk or {}).get("proofs_met"), int)
                        else None
                    )
                ),
                "verdict": (blk or {}).get("verdict"),
                "a": (blk or {}).get("a_no_scoring_mechanism"),
                "b": (blk or {}).get("b_precedent_carrier_gone"),
                "c": (blk or {}).get("c_anchor_pass"),
            }
            for face, blk in (doc.get("death_three_proofs") or {}).items()
            if isinstance(blk, dict)
        },
        hole_location_unit=hole.get("unit") if controlled_hole else None,
        hole_location_side=hole.get("side") if controlled_hole else None,
        hole_location_priced_in=hole.get("priced_in") if controlled_hole else None,
        anchor_side=doc.get("anchor_side"),
        # 情境/战意层（2026-09-22 接入，只转录不判断）：封闭词典的球队标签、追踪标签、
        # 轮换风险与休息天数。战意本身不是结构化字段，只以这些可观察代理进入。
        team_tags=_team_tags(doc.get("team_tags")),
        tracking_tags=[_tag_name(t) for t in (doc.get("tracking_tags") or []) if _tag_name(t)],
        rotation_risk=_schedule_field(doc, "rotation_risk"),
        rest_days=_schedule_field(doc, "rest_days"),
        # 研究表态（2026-09-27 接入，F11：研究的保险点名能否识别热门翻车）
        stance_face=(doc.get("stance") or {}).get("face"),
        stance_structure=(doc.get("stance") or {}).get("structure"),
        stance_cover=(doc.get("stance") or {}).get("cover"),
        # 判断 rubric r1（2026-10-02）：分析员（读者 A）的逐项答案；读者 B 由调用方按侧车补
        rubric=_rubric_answers(doc.get("rubric")),
        rubric_version=(doc.get("rubric") or {}).get("version") if isinstance(
            doc.get("rubric"), dict) else None,
        rubric_belief=(doc.get("rubric") or {}).get("belief") if isinstance(
            doc.get("rubric"), dict) else None,
        rubric_overridden=bool(doc.get("rubric_overridden")),
        label_source="research",
    )


def _team_tags(tags: object) -> dict:
    if not isinstance(tags, dict):
        return {}
    return {
        side: [_tag_name(t) for t in (tags.get(side) or []) if _tag_name(t)]
        for side in ("home", "away")
    }


def _schedule_field(doc: dict, key: str):
    schedule = doc.get("schedule")
    return schedule.get(key) if isinstance(schedule, dict) else None


def _tag_name(tag: object) -> str | None:
    if isinstance(tag, str):
        return tag
    if isinstance(tag, dict):
        value = tag.get("tag") or tag.get("name")
        return str(value) if value else None
    if isinstance(tag, (list, tuple)) and tag and isinstance(tag[0], str):
        return tag[0]
    return None


def _merge_postmortem(labels: dict | None, postmortem: dict | None) -> dict | None:
    if not postmortem:
        return labels
    return {**(labels or {}), "postmortem": postmortem}


def _closing_block(entry: dict | None) -> dict | None:
    """Policy-visible summary of one `closing_odds.json` entry (titan007 history)."""
    if not isinstance(entry, dict) or entry.get("unavailable") or not entry.get("sharp"):
        return None
    sharp, every = entry["sharp"], entry.get("all") or {}
    return {
        "source": entry.get("source"),
        "fetched_at": entry.get("fetched_at"),
        "updated_at_min": entry.get("updated_at_min"),
        "updated_at_max": entry.get("updated_at_max"),
        "book_count": entry.get("book_count"),
        "sharp_fair": sharp.get("fair_probability"),
        "sharp_odds": sharp.get("odds"),
        "sharp_opening_odds": sharp.get("opening_odds"),
        "sharp_books": sharp.get("bookmaker_count"),
        "all_fair": every.get("fair_probability"),
        "all_books": every.get("bookmaker_count"),
    }


def jczq_rows() -> list[dict]:
    """竞彩日板：以 `jc-results.json`（已结算场次）为主键，价格按优先级挂上。

    价格来源两档，行上用 `fair_kind` 区分，价格带检验按需筛：
      · `read_time`  —— 当日 `bold_odds.json`（API-Football/titan 读时盘），原口径；
      · `closing`    —— `closing_odds.json`（titan007 历史终盘，sharp 口径），2026-09-22
        接入，只在该场没有读时盘时才充当 `fair`；有读时盘时只作 `closing` 附加块。
    体彩按业务日归组、titan 按开球历日归组，所以同一竞彩号可能只在次日目录有盘，
    这里对 `date` 与前一日目录都找一遍。
    """
    results = _load(f"{J}/jc-results.json", {}) or {}
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def _day_files(date: str) -> tuple[dict, dict, dict]:
        day_dir = f"{J}/daily/{date}"
        bold = _load(f"{day_dir}/bold_odds.json", {}) or {}
        board = _load(f"{day_dir}/jczq-legs-base.json", {}) or {}
        closing = _load(f"{day_dir}/closing_odds.json", {}) or {}
        return bold, (board.get("legs") if isinstance(board, dict) else {}) or {}, closing

    def _day_reads(date: str) -> dict[str, dict]:
        """`reads.json` + `judgment-reads.json`（2026-09-22 接入）：按竞彩号取最晚一条 had Read。"""
        out: dict[str, dict] = {}
        for name in ("reads.json", "judgment-reads.json"):
            for r in _load(f"{J}/daily/{date}/{name}", []) or []:
                if not isinstance(r, dict) or not r.get("prior"):
                    continue
                if r.get("market") not in (None, "had") and "had" not in str(r.get("read_id", "")):
                    continue
                m = re.search(r"(周[一二三四五六日]\d{3})", str(r.get("read_id", "")))
                if not m:
                    continue
                code = m.group(1)
                newer = str(r.get("made_at") or "") > str(out.get(code, {}).get("made_at") or "")
                if code not in out or newer:
                    out[code] = r
        return out

    for date in sorted(results):
        day = results.get(date) or {}
        if not day:
            continue
        bold, board_legs, closing = _day_files(date)
        reads = _day_reads(date)
        prev = (
            __import__("datetime").date.fromisoformat(date) - __import__("datetime").timedelta(1)
        ).isoformat()
        prev_bold, prev_legs, prev_closing = _day_files(prev)
        day_dir = f"{J}/daily/{date}"
        for jno, got in day.items():
            if not got or got.get("ft_home") is None or (date, jno) in seen:
                continue
            mk = bold.get(jno) or prev_bold.get(jno) or {}
            mw = (mk or {}).get("match_winner") or {}
            read_fair = mw.get("fair_probability") or {}
            close_entry = closing.get(jno) or prev_closing.get(jno)
            close = _closing_block(close_entry)
            if read_fair:
                fair, fair_source, fair_kind = read_fair, "bold_odds", "read_time"
            elif close and close.get("sharp_fair"):
                fair, fair_source, fair_kind = close["sharp_fair"], "titan007_closing", "closing"
            else:
                continue
            seen.add((date, jno))
            gh, ga = got["ft_home"], got["ft_away"]
            actual = "3" if gh > ga else ("0" if ga > gh else "1")
            research = _load(f"{day_dir}/research-{jno}.json", {}) or {}
            postmortem = _load(f"{day_dir}/postmortem-{jno}.json", {}) or {}
            leg = board_legs.get(jno) or prev_legs.get(jno) or {}
            read = reads.get(jno) or {}
            belief = read.get("belief") or fair
            if len(belief) != 3:
                belief = fair
            row = dict(
                src="jczq",
                key=f"{date}-{jno}",
                issue=None,
                match_no=jno,
                date=date,
                name=None,
                fair=fair,
                belief=belief,
                fair_source=fair_source,
                fair_kind=fair_kind,
                actual=actual,
                conf=research.get("confidence", read.get("confidence")),
                belief_moved=any(abs(fair.get(k, 0) - belief.get(k, 0)) > 1e-6 for k in fair),
                note=str(read.get("note") or ""),
                read_id=read.get("read_id"),
                read_made_at=read.get("made_at"),
                labels=_merge_postmortem(_with_sidecar(
                    _research_labels(research),
                    _rubric_sidecar(f"{day_dir}/rubric-{jno}.json",
                                    kickoff_bj=leg.get("kickoff_bj"))), postmortem),
                titan007_id=str(got.get("match_id") or "") or None,
                jczq_no=jno,
                books=mw.get("bookmaker_count"),
                opening_odds=mw.get("opening_odds"),
                closing=close,
                goals=[gh, ga],
                ht=[got.get("ht_home"), got.get("ht_away")],
            )
            judged_at = research.get("captured_at") or leg.get("judged_at")
            source = (
                "research.captured_at"
                if research.get("captured_at")
                else "legs-base.legs[n].judged_at"
                if leg.get("judged_at")
                else None
            )
            row.update(
                _prospective_fields(
                    judged_at=judged_at,
                    kickoff_bj=research.get("kickoff_bj") or leg.get("kickoff_bj"),
                    judged_at_source=source,
                )
            )
            rows.append(row)
    return rows


ONTOLOGY_DB = os.path.join(ROOT, ".nutmeg-data", "ontology", "ontology.db")


def _sporttery_index() -> tuple[dict, dict]:
    """来自每日 `sporttery_markets.json` 的两张索引：
    sporttery matchId → (businessDate, 竞彩号)；(开球日, 主, 客) → (businessDate, 竞彩号)。"""
    by_id: dict[str, tuple[str, str]] = {}
    by_name: dict[tuple[str, str, str], tuple[str, str]] = {}
    daily = f"{J}/daily"
    if not os.path.isdir(daily):
        return by_id, by_name
    for date in sorted(os.listdir(daily)):
        doc = _load(f"{daily}/{date}/sporttery_markets.json", {}) or {}
        for group in doc.get("matchInfoList") or []:
            for sub in (group or {}).get("subMatchList") or []:
                code = sub.get("matchNumStr")
                if not code:
                    continue
                business = sub.get("businessDate") or date
                if sub.get("matchId"):
                    by_id.setdefault(str(sub["matchId"]), (business, code))
                key = (sub.get("matchDate"), sub.get("homeTeamAbbName"), sub.get("awayTeamAbbName"))
                if all(key):
                    by_name.setdefault(key, (business, code))
    return by_id, by_name


def _zucai_name_index() -> dict[tuple[str, str, str], tuple[str, int]]:
    """(match_date, home, away) → (issue, match_no)，来自每期 `*-issue.json`。"""
    index: dict[tuple[str, str, str], tuple[str, int]] = {}
    for path in sorted(glob.glob(f"{Z}/*-issue.json")):
        issue = os.path.basename(path)[:5]
        for m in (_load(path, {}) or {}).get("matches") or []:
            try:
                n = int(str(m.get("match_no")))
            except (TypeError, ValueError):
                continue
            key = (
                m.get("match_date") or (m.get("kickoff_bj") or "")[:10],
                m.get("home_team"),
                m.get("away_team"),
            )
            if all(key):
                index.setdefault(key, (issue, n))
    return index


def _parse_canonical_id(external_id: str) -> tuple[str, str, str] | None:
    parts = external_id.split("-")
    if len(parts) != 6 or parts[0] != "M":
        return None
    return "-".join(parts[1:4]), parts[4], parts[5]


def _kernel_outcome(
    externals: list[tuple[str, str]],
    *,
    score_90: str | None,
    jc_results: dict,
    official: dict,
    sp_index: dict,
    z_index: dict,
) -> tuple[str | None, str | None, list | None, dict]:
    """赛果优先读内核 `match_outcomes`；缺时经外部标识回到文件赛果（只读）。"""
    refs: dict = {}
    sp_by_id, sp_by_name = sp_index
    for provider, ext in externals:
        if provider == "sporttery" and ext in sp_by_id:
            refs = {"jczq_date": sp_by_id[ext][0], "jczq_no": sp_by_id[ext][1]}
        else:
            parsed = _parse_canonical_id(ext)
            if parsed and parsed in z_index:
                refs = {"issue": z_index[parsed][0], "match_no": z_index[parsed][1]}
            elif parsed and parsed in sp_by_name:
                refs = {"jczq_date": sp_by_name[parsed][0], "jczq_no": sp_by_name[parsed][1]}
        if refs:
            break
    if score_90 and "-" in score_90:
        gh, ga = (int(x) for x in score_90.split("-", 1))
        return ("3" if gh > ga else "0" if ga > gh else "1"), "match_outcomes", [gh, ga], refs

    def _jczq(date: str, code: str):
        found = {"jczq_date": date, "jczq_no": code}
        got = (jc_results.get(date) or {}).get(code) or {}
        if got.get("ft_home") is not None:
            gh, ga = got["ft_home"], got["ft_away"]
            found["titan007_id"] = str(got.get("match_id") or "") or None
            return ("3" if gh > ga else "0" if ga > gh else "1"), "jc-results", [gh, ga], found
        return None, None, None, found

    for provider, ext in externals:
        if provider == "sporttery" and ext in sp_by_id:
            actual, source, goals, refs = _jczq(*sp_by_id[ext])
            if actual is not None:
                return actual, source, goals, refs
        elif provider in ("zucai-canonical", "import"):
            parsed = _parse_canonical_id(ext)
            if parsed is None:
                continue
            if parsed in z_index:
                issue, n = z_index[parsed]
                refs = {"issue": issue, "match_no": n}
                out = (official.get(issue) or "").split()
                if len(out) >= n and out[n - 1] in ("3", "1", "0"):
                    return out[n - 1], "official-results", None, refs
            if parsed in sp_by_name:
                actual, source, goals, found = _jczq(*sp_by_name[parsed])
                refs = {**refs, **found}
                if actual is not None:
                    return actual, source, goals, refs
    return None, None, None, refs


def _kernel_quotes(connection) -> dict[str, dict[str, list[tuple[str, dict]]]]:
    """match_id → provider → [(captured_at, {home,draw,away})] 按 captured_at 升序。"""
    sql = (
        "select match_id, provider, captured_at, selection_id, decimal_odds "
        "from market_quotes where market_definition_id='md-had' and quote_status='active' "
        "order by match_id, provider, captured_at"
    )
    grouped: dict[tuple[str, str, str], dict] = {}
    for match_id, provider, captured_at, selection, odds in connection.execute(sql):
        key = selection.rsplit("-", 1)[-1]
        if key in ("home", "draw", "away") and odds:
            grouped.setdefault((match_id, provider, captured_at), {})[key] = float(odds)
    out: dict[str, dict[str, list[tuple[str, dict]]]] = {}
    for (match_id, provider, captured_at), triplet in sorted(grouped.items()):
        if len(triplet) == 3:
            out.setdefault(match_id, {}).setdefault(provider, []).append((captured_at, triplet))
    return out


def _quote_summary(series: dict[str, list[tuple[str, dict]]], kickoff: str | None) -> dict:
    from datetime import datetime

    def _ts(value: str):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo:
            return parsed
        return parsed.replace(tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Shanghai"))

    kick = _ts(kickoff) if kickoff else None
    summary: dict = {}
    for provider, points in series.items():
        pre = [(at, odds) for at, odds in points if kick is None or _ts(at) < kick]
        if not pre:
            continue
        stamps = sorted({at for at, _ in pre})
        first, last = pre[0], pre[-1]
        summary[provider] = {
            "opening": {**first[1], "captured_at": first[0]},
            "closing": {**last[1], "captured_at": last[0]},
            "n_snapshots": len(stamps),
            "span_hours": round((_ts(stamps[-1]) - _ts(stamps[0])).total_seconds() / 3600, 2),
        }
    return summary


def kernel_rows(database: str | None = None) -> list[dict]:
    """⑥ `kernel_forecast` —— 内核 `forecast_revisions`（committed，每场取最新修订）。

    2026-09-22 接入。这是最大的 A 类判读来源（1,393 条 forecast），且内核是只追加
    账本：`made_at` 由 typed Action 写入，不可事后改，因此这一 lane 的
    `provably_prospective` 可以合法地为 true/false，而不是像文件产物那样只能是 null。
    赛果优先读 `match_outcomes`；结算链只认 sporttery 标识，zucai-canonical 的 221 场
    在内核里没有赛果，这里经 `*-issue.json` 的（日期,主,客）回到 `official-results.json`。
    多源赔率时序（`market_quotes`，captured_at < 开球）按 provider 摘成 opening/closing。
    """
    import sqlite3

    path = database or ONTOLOGY_DB
    if not os.path.exists(path):
        return []
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        forecasts = connection.execute(
            "select fr.forecast_revision_id, fs.match_id, fr.made_at, fr.information_cutoff_at, "
            "fr.prior_distribution_json, fr.belief_distribution_json, fr.commitment_tier, "
            "fr.actor_id, fr.model_name, fr.evidence_coverage, fr.evidence_quality, fr.falsifier, "
            "fr.revision_no, mr.scheduled_at, mo.score_90 "
            "from forecast_revisions fr "
            "join forecast_series fs on fs.forecast_series_id=fr.forecast_series_id "
            "and fs.market_definition_id='md-had' "
            "join matches m on m.match_id=fs.match_id "
            "left join match_revisions mr on mr.match_revision_id=m.current_revision_id "
            "left join match_outcomes mo on mo.match_id=fs.match_id and mo.status='final' "
            "where fr.status='committed' order by fs.match_id, fr.revision_no desc"
        ).fetchall()
        externals: dict[str, list[tuple[str, str]]] = {}
        for entity_id, provider, ext in connection.execute(
            "select entity_id, provider, external_id from external_identifiers "
            "where entity_type='match'"
        ):
            externals.setdefault(entity_id, []).append((provider, ext))
        quotes = _kernel_quotes(connection)
    finally:
        connection.close()

    jc_results = _load(f"{J}/jc-results.json", {}) or {}
    official = _load(f"{Z}/official-results.json", {}) or {}
    sp_index, z_index = _sporttery_index(), _zucai_name_index()
    rows: list[dict] = []
    done: set[str] = set()
    for (
        revision_id, match_id, made_at, cutoff_at, prior_json, belief_json, tier, actor,
        model, coverage, quality, falsifier, revision_no, scheduled_at, score_90,
    ) in forecasts:
        if match_id in done or not scheduled_at:
            continue
        done.add(match_id)
        prior = json.loads(prior_json or "{}") or {}
        belief = json.loads(belief_json or "{}") or prior
        if not {"home", "draw", "away"} <= set(prior):
            continue
        ext = externals.get(match_id, [])
        actual, outcome_source, goals, refs = _kernel_outcome(
            ext, score_90=score_90, jc_results=jc_results, official=official,
            sp_index=sp_index, z_index=z_index,
        )
        if actual is None:
            continue
        name = None
        for provider, value in ext:
            parsed = _parse_canonical_id(value) if provider != "sporttery" else None
            if parsed:
                name = f"{parsed[1]} vs {parsed[2]}"
                break
        row = dict(
            src="kernel",
            key=f"kernel-{match_id}",
            issue=refs.get("issue"),
            match_no=refs.get("match_no") or refs.get("jczq_no"),
            date=str(scheduled_at)[:10],
            name=name,
            fair=prior,
            belief=belief,
            fair_source="kernel.prior_distribution",
            fair_kind="read_time",
            actual=actual,
            conf=None,
            belief_moved=any(abs(prior.get(k, 0) - belief.get(k, 0)) > 1e-6 for k in prior),
            labels=None,
            titan007_id=refs.get("titan007_id"),
            jczq_no=refs.get("jczq_no"),
            jczq_date=refs.get("jczq_date"),
            goals=goals,
            kernel=dict(
                match_id=match_id,
                forecast_revision_id=revision_id,
                revision_no=revision_no,
                made_at=made_at,
                information_cutoff_at=cutoff_at,
                scheduled_at=scheduled_at,
                commitment_tier=tier,
                actor_id=actor,
                model_name=model,
                evidence_coverage=coverage,
                evidence_quality=quality,
                falsifier=falsifier,
                providers=sorted({p for p, _ in ext}),
                outcome_source=outcome_source,
            ),
            quotes=_quote_summary(quotes.get(match_id, {}), scheduled_at),
        )
        row.update(
            _prospective_fields(
                judged_at=made_at,
                kickoff_bj=scheduled_at,
                judged_at_source="ontology.forecast_revisions.made_at",
            )
        )
        rows.append(row)
    return rows


def attach_kernel(rows: list[dict], kernel: list[dict]) -> tuple[list[dict], int]:
    """内核行能对上已有行（足彩 issue+场次 / 竞彩 date+竞彩号 / 同日 fair≤1.5pp）时，
    只把 `kernel`/`quotes` 挂到已有行上；对不上的作为独立 `src=kernel` 行追加。"""
    by_key = {r["key"]: r for r in rows}
    by_day: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("date"):
            by_day.setdefault(r["date"], []).append(r)
    attached = 0
    extra: list[dict] = []
    for k in kernel:
        target = None
        if k.get("issue") and k.get("match_no"):
            target = by_key.get(f"{k['issue']}-{k['match_no']}")
        if target is None and k.get("jczq_no"):
            # 竞彩行按业务日建键；内核 date 是开球历日，深夜场差一天
            target = by_key.get(f"{k.get('jczq_date') or k['date']}-{k['jczq_no']}")
        if target is None:
            day = __import__("datetime").date.fromisoformat(k["date"])
            candidates = [
                r
                for delta in (0, -1, 1)
                for r in by_day.get(
                    (day + __import__("datetime").timedelta(delta)).isoformat(), []
                )
            ]
            for r in candidates:
                if all(
                    abs(k["fair"].get(x, 0) - r["fair"].get(x, 0)) <= _DUP_TOL
                    for x in ("home", "draw", "away")
                ):
                    target = r
                    break
        if target is not None and not target.get("kernel"):
            target["kernel"] = k["kernel"]
            target["quotes"] = k["quotes"]
            target["kernel_belief"] = k["belief"]
            target["kernel_provably_prospective"] = k["provably_prospective"]
            attached += 1
        elif target is None:
            extra.append(k)
    return rows + extra, attached


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
            if all(
                abs(r["fair"].get(k, 0) - z["fair"].get(k, 0)) <= _DUP_TOL
                for k in ("home", "draw", "away")
            ):
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
    kc = kernel_rows()
    rows, attached = attach_kernel(rows, kc)
    labeled = [r for r in rows if r.get("labels")]
    moved = [r for r in rows if r.get("belief_moved")]
    closing_priced = [r for r in rows if r.get("fair_kind") == "closing"]
    provable = [r for r in rows if r.get("provably_prospective") is True]
    json.dump(
        {
            "built_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "n": len(rows),
            "rows": rows,
        },
        open(args.out, "w", encoding="utf-8"),
        ensure_ascii=False,
    )
    print(
        f"语料 v2：{len(rows)} 行  = 足彩 {len(zc)}（{len(set(r['issue'] for r in zc))} 期）"
        f" + 竞彩 {sum(1 for r in rows if r['src'] == 'jczq')}（去重丢弃 {dropped} 行重叠）"
        f" + 内核独立 {sum(1 for r in rows if r['src'] == 'kernel')}"
    )
    print(
        f"  带判读标签（旗/完整度/牌照/先例）：{len(labeled)} 行"
        f"（{len(set(r['issue'] for r in labeled))} 期）"
    )
    print(f"  belief≠prior 的判读移动：{len(moved)} 行")
    print(
        f"  内核 forecast：{len(kc)} 场，挂到已有行 {attached}，"
        f"独立追加 {sum(1 for r in rows if r['src'] == 'kernel')}"
    )
    print(
        f"  以终盘作价的竞彩行：{len(closing_priced)}；"
        f"provably_prospective=true：{len(provable)}"
    )
    print(f"  写入 {args.out}")


if __name__ == "__main__":
    main()
