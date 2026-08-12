"""规则/证伪登记表 —— 预登记的证伪条件由机器核验（Roadmap A1，本体提案 §5 最小版）。

**Why**：Factor 有 probation→active→retired 的自动生死，但判决表条款与预登记证伪条件
（本项目真正的护城河）活在散文里，核验靠"我记得去核"。26103 落了四条预登记，
**核验它们是纯确定性算术**——本模块把它做成机器动作。

**设计红线**：check 是一个**封闭的小谓词词典**，不是表达式求值——规则可以说的话
被限制在"赛果/比分能机械判定"的范围内。判断进不来，这是刻意的。

check 词典（全部作用于官方 90' 口径数据）：
- ``outcome_eq``    {matches: {"2":"1",...}, mode: "all"|"any"}      赛果等于
- ``outcome_count`` {targets: [{no, codes}], op: ">="|"<=", k}       命中计数
- ``margin``        {no, side: "home"|"away", op: ">="|"<=", k}      净胜球(需 czScore)
"""
from __future__ import annotations

import json
from pathlib import Path

RULES_FILE = "rules.jsonl"


def _eval_outcome_eq(params: dict, results: dict, _scores) -> tuple[bool | None, str]:
    matches = params.get("matches") or {}
    got = {no: results.get(str(no)) for no in matches}
    if any(v is None for v in got.values()):
        return None, f"赛果缺失: {[no for no, v in got.items() if v is None]}"
    hits = {no: (got[no] == code) for no, code in matches.items()}
    ok = all(hits.values()) if params.get("mode", "all") == "all" else any(hits.values())
    return ok, " ".join(f"场{no}:{results[str(no)]}{'✓' if h else '✗'}"
                        for no, h in hits.items())


def _eval_outcome_count(params: dict, results: dict, _scores) -> tuple[bool | None, str]:
    targets = params.get("targets") or []
    vals = [(t["no"], results.get(str(t["no"])), set(str(t["codes"]))) for t in targets]
    if any(v is None for _, v, _c in vals):
        return None, "赛果缺失"
    n = sum(1 for _, v, c in vals if v in c)
    op, k = params.get("op", ">="), int(params.get("k", 1))
    ok = n >= k if op == ">=" else n <= k
    return ok, f"命中 {n}/{len(vals)} (要求 {op}{k}): " + \
        " ".join(f"场{no}:{v}{'∈' if v in c else '∉'}{''.join(sorted(c))}" for no, v, c in vals)


def _eval_margin(params: dict, _results, scores: dict | None) -> tuple[bool | None, str]:
    no = str(params["no"])
    sc = (scores or {}).get(no)
    if sc is None:
        return None, f"场{no} 无 90' 比分数据"
    h, a = sc
    margin = (h - a) if params.get("side", "home") == "home" else (a - h)
    op, k = params.get("op", ">="), int(params.get("k", 2))
    ok = margin >= k if op == ">=" else margin <= k
    return ok, f"场{no} 比分 {h}:{a} → {params.get('side')}净胜 {margin} (要求 {op}{k})"


_CHECKS = {"outcome_eq": _eval_outcome_eq,
           "outcome_count": _eval_outcome_count,
           "margin": _eval_margin}


def load_rules(store_dir) -> list[dict]:
    path = Path(store_dir) / RULES_FILE
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text("utf-8").splitlines() if ln.strip()]


def save_rules(store_dir, rules: list[dict]) -> None:
    path = Path(store_dir) / RULES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rules) + "\n",
                    "utf-8")


def verify_issue(store_dir, issue: str, results: dict, scores: dict | None,
                 *, verified_at: str) -> list[str]:
    """核验指定期次的全部 pending falsifier。幂等：非 pending 的不重判。

    每条 falsifier: {id, issue, description, on_true, check{kind,...},
                     outcome: pending|confirmed|refuted, detail?, verified_at?}
    语义：check 为真 ⇒ outcome=confirmed(条件兑现)；为假 ⇒ refuted。
    `on_true` 记录"条件兑现意味着什么"（如"该偏移记为失败"），供复盘直接引用。
    """
    rules = load_rules(store_dir)
    lines: list[str] = []
    changed = False
    for r in rules:
        for f in r.get("falsifiers") or []:
            if str(f.get("issue")) != str(issue) or f.get("outcome") != "pending":
                continue
            kind = (f.get("check") or {}).get("kind")
            fn = _CHECKS.get(kind)
            if fn is None:
                lines.append(f"⚠️ {f.get('id')}: 未知 check.kind={kind!r},跳过")
                continue
            ok, detail = fn(f["check"], results, scores)
            if ok is None:
                lines.append(f"⏳ {f.get('id')}: 数据不足({detail}),保持 pending")
                continue
            f["outcome"] = "confirmed" if ok else "refuted"
            f["verified_at"] = verified_at
            f["detail"] = detail
            changed = True
            mark = "✅兑现" if ok else "❌未兑现"
            lines.append(f"{mark} {f.get('id')}: {detail}"
                         + (f"\n    ⇒ {f.get('on_true')}" if ok and f.get("on_true") else ""))
    if changed:
        save_rules(store_dir, rules)
    return lines or [f"{issue}: 无 pending falsifier"]


def format_rules(rules: list[dict]) -> str:
    if not rules:
        return "(规则表为空)"
    out = []
    for r in rules:
        fs = r.get("falsifiers") or []
        n_p = sum(1 for f in fs if f.get("outcome") == "pending")
        n_c = sum(1 for f in fs if f.get("outcome") == "confirmed")
        n_r = sum(1 for f in fs if f.get("outcome") == "refuted")
        out.append(f"{r.get('rule_id')} [{r.get('status','active')}] "
                   f"falsifiers: {n_p} pending / {n_c} confirmed / {n_r} refuted")
        for f in fs:
            icon = {"pending": "⏳", "confirmed": "✅", "refuted": "❌"}.get(f.get("outcome"), "?")
            out.append(f"  {icon} {f.get('id')} ({f.get('issue')}): {f.get('description')}")
            if f.get("detail"):
                out.append(f"      {f['detail']}")
    return "\n".join(out)
