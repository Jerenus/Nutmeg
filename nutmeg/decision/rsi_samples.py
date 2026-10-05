"""样本账：预登记实验的前瞻样本只增不减（2026-10-05）。

语料 v2 每天全量重建，同一场比赛的行会变：足彩期结算后，竞彩行被足彩孪生行替换（价格与 belief
换了一个来源）；读时盘被 17:15 刷新抹掉后改用终盘；Read 被重写……这些都会让已经结过账的样本
悄悄换值或消失（F9 09-27 8→2、F5 10-01 39→37，见 evidence/2026-10-05-sample-ledger.md）。

规则：
- 一场比赛第一次被某实验的适配器选中，就把当时的整行冻结为该实验的成员。
- 之后的结账 = 冻结成员 + 语料里尚未入账的行；同一场比赛的孪生行（同 titan id、或被去重吸收的
  竞彩键 ``twin_keys``）不再重复入账。
- 成员在语料里换值 / 换泳道 / 消失 / 不再被选中，只记事件、不改样本。唯一例外是同键的赛果更正
  （事实，不是判断）：照改并记事件。
- 剔除只能由人显式 retract（带理由），留痕。
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path

from nutmeg.decision.rsi_grading import GradeResult

_RESULTS = ("3", "1", "0")


def empty() -> dict:
    return {"version": 1, "rows": {}, "experiments": {}, "events": []}


def load(path: Path) -> dict:
    if not Path(path).exists():
        return empty()
    doc = json.loads(Path(path).read_text("utf-8"))
    for name, value in empty().items():
        doc.setdefault(name, value)
    return doc


def save(path: Path, ledger: dict) -> None:
    Path(path).write_text(
        json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=1) + "\n", "utf-8")


def row_hash(row: dict) -> str:
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def identity(row: dict) -> str:
    """一场比赛的身份：titan id > 内核 match_id > 语料键。"""
    if row.get("titan007_id"):
        return f"t:{row['titan007_id']}"
    match_id = (row.get("kernel") or {}).get("match_id")
    if match_id:
        return f"m:{match_id}"
    return f"k:{row.get('key')}"


def aliases(row: dict) -> list[str]:
    out = [identity(row), f"k:{row.get('key')}"]
    match_id = (row.get("kernel") or {}).get("match_id")
    if match_id:
        out.append(f"m:{match_id}")
    out.extend(f"k:{key}" for key in row.get("twin_keys") or [])
    return sorted(set(out))


def _exp(ledger: dict, exp: str) -> dict:
    entry = ledger["experiments"].setdefault(exp, {})
    entry.setdefault("members", {})
    entry.setdefault("retracted", {})
    return entry


def _fingerprint(event: dict) -> str:
    return json.dumps([event["exp"], event["identity"], event["kind"], event.get("detail")],
                      ensure_ascii=False, sort_keys=True)


def _log(ledger: dict, event: dict, seen: set[str] | None = None) -> dict | None:
    """同一 (实验, 身份, 类别, 细节) 只记一次——每天重跑不刷屏。"""
    if seen is None:
        seen = {_fingerprint(e) for e in ledger["events"]}
    fingerprint = _fingerprint(event)
    if fingerprint in seen:
        return None
    seen.add(fingerprint)
    ledger["events"].append(event)
    return event


def admit(ledger: dict, exp: str, row: dict, *, at: str, source: str,
          proof: str | None = None) -> bool:
    """冻结一行为成员；已是成员（任一别名命中）或已剔除则不动，返回 False。"""
    entry = _exp(ledger, exp)
    known = {a for m in entry["members"].values() for a in m["aliases"]}
    known |= {a for m in entry["retracted"].values() for a in m.get("aliases", [])}
    if known & set(aliases(row)):
        return False
    digest = row_hash(row)
    ledger["rows"][digest] = row
    entry["members"][identity(row)] = {
        "key": row.get("key"), "row": digest, "aliases": aliases(row),
        "admitted_at": at, "source": source, **({"proof": proof} if proof else {}),
    }
    return True


# 记账字段：语料去重时补上的孪生键，不是比赛数据，变化不算漂移
_BOOKKEEPING = frozenset({"twin_keys"})


def _content(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in _BOOKKEEPING}


def _changed_fields(frozen: dict, current: dict) -> list[str]:
    return sorted(k for k in (set(frozen) | set(current)) - _BOOKKEEPING
                  if frozen.get(k) != current.get(k))


def grade(ledger: dict, exp: str, corpus_rows: Sequence[dict],
          adapter: Callable[..., GradeResult], *, window: dict,
          at: str) -> tuple[GradeResult, list[dict]]:
    """冻结成员 + 未入账的语料行一起交给适配器；新入选的行入账，成员漂移记事件。"""
    entry = _exp(ledger, exp)
    owner: dict[str, str] = {}
    for ident, member in entry["members"].items():
        for alias in member["aliases"]:
            owner[alias] = ident
    retracted = {a for m in entry["retracted"].values() for a in m.get("aliases", [])}

    events: list[dict] = []
    seen = {_fingerprint(e) for e in ledger["events"]}

    def log(ident: str, key: str | None, kind: str, detail: object = None) -> None:
        event = _log(ledger, {"at": at, "exp": exp, "identity": ident, "key": key,
                              "kind": kind, "detail": detail}, seen)
        if event:
            events.append(event)

    current: dict[str, dict] = {}
    candidates: list[dict] = []
    candidate_ids: set[str] = set()
    for row in corpus_rows:
        names = aliases(row)
        if retracted & set(names):
            continue
        hit = next((owner[a] for a in names if a in owner), None)
        if hit is not None:
            current.setdefault(hit, row)
            continue
        ident = identity(row)
        if ident in candidate_ids:
            log(ident, row.get("key"), "duplicate_in_corpus")
            continue
        candidate_ids.add(ident)
        candidates.append(row)

    for ident, member in entry["members"].items():
        frozen = ledger["rows"][member["row"]]
        row = current.get(ident)
        if row is None:
            log(ident, member["key"], "missing")
            continue
        if row.get("key") != member["key"]:
            log(ident, member["key"], "superseded", {"current_key": row.get("key")})
            continue
        if row.get("actual") in _RESULTS and row.get("actual") != frozen.get("actual"):
            fixed = {**frozen, "actual": row["actual"]}
            ledger["rows"][row_hash(fixed)] = fixed
            member["row"] = row_hash(fixed)
            log(ident, member["key"], "actual_corrected",
                {"from": frozen.get("actual"), "to": row["actual"]})
            frozen = fixed
        if row_hash(_content(row)) != row_hash(_content(frozen)):
            log(ident, member["key"], "changed",
                {"fields": _changed_fields(frozen, row), "current_row": row_hash(row)})

    frozen_rows = [ledger["rows"][m["row"]] for m in entry["members"].values()]
    result = adapter([*frozen_rows, *candidates], window=window)
    selected = set(result.selected_keys)
    for ident, member in entry["members"].items():
        if member["key"] not in selected:
            log(ident, member["key"], "deselected")
    for row in candidates:
        if row.get("key") in selected and admit(ledger, exp, row, at=at, source="grade"):
            log(identity(row), row.get("key"), "admitted")
    _prune_rows(ledger)
    return result, events


def retract(ledger: dict, exp: str, key: str, *, reason: str, by: str, at: str) -> dict:
    """人显式剔除一个成员（按语料键或身份）；剔除后不再入账，事件留痕。"""
    entry = _exp(ledger, exp)
    ident = next((i for i, m in entry["members"].items()
                  if key in (i, m["key"]) or f"k:{key}" in m["aliases"]), None)
    if ident is None:
        raise KeyError(f"{exp} 没有成员 {key}")
    member = entry["members"].pop(ident)
    entry["retracted"][ident] = {**member, "reason": reason, "by": by, "retracted_at": at}
    _log(ledger, {"at": at, "exp": exp, "identity": ident, "key": member["key"],
                  "kind": "retracted", "detail": {"reason": reason, "by": by}})
    _prune_rows(ledger)
    return entry["retracted"][ident]


def _prune_rows(ledger: dict) -> None:
    used = {m["row"] for e in ledger["experiments"].values()
            for group in ("members", "retracted") for m in e.get(group, {}).values()}
    for digest in [d for d in ledger["rows"] if d not in used]:
        del ledger["rows"][digest]


def summary(ledger: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for exp, entry in sorted(ledger["experiments"].items()):
        kinds: dict[str, int] = {}
        for event in ledger["events"]:
            if event["exp"] == exp:
                kinds[event["kind"]] = kinds.get(event["kind"], 0) + 1
        out[exp] = {"members": len(entry.get("members", {})),
                    "retracted": len(entry.get("retracted", {})), "events": kinds}
    return out
