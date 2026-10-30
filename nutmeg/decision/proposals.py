"""待签收件箱（2026-10-30 产品形态第 10 阶段 Task 10.3）。

会话里机器把编号提案列在聊天里，Jun 回「1，可以。2，可以」，没答的几天后又列一遍（K1 修正案问了
5 次）；答案只活在聊天与记忆里。这里是提案的唯一一本只追加的账，`/inbox` 页与
`nutmeg inbox …` 只读写它；Jun 的原话随答复入账。签了才执行，执行结果回挂（`done`）。

存储：`<data_dir>/proposals.jsonl`，只追加事件、从不改写：
- 新建 `{"op":"create","id","at","title","body","blocks","deadline","source","ref"}`
  （种子带 `asked` 的另记 `asked_base`）；
  id = `P-` + sha1(source|title|at)[:8]，同一条再建不重写；
- 又被提起 `{"op":"ask","id","at","where"}`（问过次数 +1）；
- 答复 `{"op":"answer","id","at","verdict","words","by","batch"}`——一句话答了几条（「全部解决」）
  写成每条一个事件、共用一个 `batch`，覆盖了哪些一目了然；`modify` 必须带原话；
- 已执行 `{"op":"done","id","at","result"}`——只许在签 / 改之后。

RSI 闭环的待人决定（`analytics/rsi-loop/inbox.json` 的开着的项，原文在当日报告
`analytics/rsi-loop/<日>.json` 的 `inbox`）也进这个收件箱：id 就是 `RSI-xxxxxx`；
第一次答复时先补一条 `source="rsi"` 的建条事件，之后与会话提案同一套折叠。闭环那边只读、不写。
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date as _date
from datetime import datetime
from pathlib import Path

from nutmeg.decision.files import read_json

LEDGER = "proposals.jsonl"

# 存键、显示标签（页面拿 labels 显示中文，不在 JS 里写死）
VERDICTS = {"sign": "签", "modify": "改", "reject": "否", "stale": "已过时"}
STATUSES = {"pending": "待签", **VERDICTS, "done": "已执行"}
EXECUTABLE = ("sign", "modify")
"""签 / 改之后才许标「已执行」。"""
NAG_ASKED = 3
NAG_DAYS = 7
"""问过 ≥3 次或积压 ≥7 天 → `overdue`（页面用否决色）。"""

SEED = Path(__file__).resolve().parents[2] / "docs" / "superpowers" / "evidence" / \
    "2026-10-30-proposals-seed.json"
SEED_SOURCE = "seed:2026-10-30"
RSI_SOURCE = "rsi"
RSI_DIR = Path("analytics") / "rsi-loop"


def labels() -> dict:
    return {"verdicts": VERDICTS, "statuses": STATUSES}


def _now() -> datetime:
    from nutmeg.decision.bj_time import BJ

    return datetime.now(BJ)


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


def _events(data_dir: Path | str) -> list[dict]:
    path = Path(data_dir) / LEDGER
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("id"):
            out.append(row)
    return out


def _append(data_dir: Path | str, row: dict) -> None:
    path = Path(data_dir) / LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def proposal_id(source: str, title: str, at: str) -> str:
    return "P-" + hashlib.sha1(f"{source}|{title}|{at}".encode()).hexdigest()[:8]


def _created(data_dir: Path | str) -> set[str]:
    return {e["id"] for e in _events(data_dir) if e.get("op") == "create"}


def _create(data_dir: Path | str, *, title: str, body: str, blocks: str, deadline: str | None,
            source: str, ref: str, at: str | None, asked_base: int | None = None,
            pid: str | None = None) -> tuple[str, bool]:
    """→ (id, 是否新写)。同 id 已在账上就不再写（种子可反复跑）。"""
    from nutmeg.decision.bj_time import parse_bj

    if not str(title).strip():
        raise ValueError("title 不能为空")
    if deadline and parse_bj(deadline) is None:
        raise ValueError("deadline 须为 ISO 时刻，如 2026-11-01T21:00:00+08:00"
                         f"（收到 {deadline!r}）")
    at = at or _iso(_now())
    if parse_bj(at) is None:
        raise ValueError(f"at 须为 ISO 时刻（收到 {at!r}）")
    pid = pid or proposal_id(source, title, at)
    if pid in _created(data_dir):
        return pid, False
    row = {"op": "create", "id": pid, "at": at, "title": title, "body": body, "blocks": blocks,
           "deadline": deadline or None, "source": source, "ref": ref}
    if asked_base:
        row["asked_base"] = int(asked_base)
    _append(data_dir, row)
    return pid, True


def propose(data_dir: Path | str, *, title: str, body: str = "", blocks: str = "",
            deadline: str | None = None, ref: str = "", source: str = "session",
            at: str | None = None) -> str:
    """起草一条待签提案 → id。同一条（同 source/标题/时刻）已在账上就原样返回 id、不重写。"""
    pid, _ = _create(data_dir, title=title, body=body, blocks=blocks, deadline=deadline,
                     source=source, ref=ref, at=at)
    return pid


# ---- RSI 闭环的待人决定 --------------------------------------------------

def _rsi_at(first_seen: str) -> str:
    return f"{first_seen}T00:00:00+08:00"


def rsi_items(data_dir: Path | str, *, today: str | None = None) -> list[dict]:
    """闭环收件箱里还开着的项（没有 `closed_at`）→ 与账行同形的行（`source="rsi"`、待签）。
    原文取 `last_seen` 那天报告的 `inbox`；报告缺了也照列（标题退回 key），不吞掉待办。"""
    rsi_dir = Path(data_dir) / RSI_DIR
    state = read_json(rsi_dir / "inbox.json", {})
    if not isinstance(state, dict):
        return []
    today = today or _now().date().isoformat()
    out = []
    for key, entry in sorted(state.items()):
        if not isinstance(entry, dict) or entry.get("closed_at") or not entry.get("id"):
            continue
        first_seen = str(entry.get("first_seen") or today)
        report = read_json(rsi_dir / f"{entry.get('last_seen') or first_seen}.json", {}) or {}
        item = next((i for i in report.get("inbox") or []
                     if isinstance(i, dict) and (i.get("key") == key
                                                 or i.get("id") == entry["id"])), None)
        if item:
            title = str(item.get("text") or key)
            body = "默认：" + str(item.get("default") or "（报告没写）")
            if item.get("command"):
                body += f"（`{item['command']}`）"
        else:
            title, body = key, "（当日闭环报告里找不到这条的原文）"
        # 账上的 id 带起始日：同一 key 关了又开，闭环给的 RSI id 不变（key 的哈希），
        # 但这是新的一轮待办，不能沿用上一轮的回答
        out.append(_fold_row({"id": f"{entry['id']}@{first_seen}", "at": _rsi_at(first_seen),
                              "title": title,
                              "body": body, "blocks": "", "deadline": None,
                              "source": RSI_SOURCE, "ref": f"rsi-loop {key}",
                              "asked_base": _days(first_seen, today) + 1}, [], today))
    return out


def _ensure(data_dir: Path | str, pid: str) -> None:
    """账上有 → 不动；是开着的 RSI 项 → 补一条 rsi 建条事件；都不是 → KeyError。"""
    if pid in _created(data_dir):
        return
    for row in rsi_items(data_dir):
        if row["id"] == pid:
            _create(data_dir, title=row["title"], body=row["body"], blocks="", deadline=None,
                    source=RSI_SOURCE, ref=row["ref"], at=row["at"],
                    asked_base=row["asked_count"], pid=pid)
            return
    raise KeyError(pid)


# ---- 事件 ----------------------------------------------------------------

def ask(data_dir: Path | str, pid: str, *, where: str = "", at: str | None = None) -> dict:
    """又被提起了一次（问过 +1）→ 该事件。不认识的 id 抛 KeyError。"""
    _ensure(data_dir, pid)
    event = {"op": "ask", "id": pid, "at": at or _iso(_now()), "where": where}
    _append(data_dir, event)
    return event


def answer(data_dir: Path | str, pids: list[str] | str, verdict: str, *, words: str = "",
           by: str = "jun", at: str | None = None) -> list[dict]:
    """答复一条或几条 → 写下的事件。几条＝一批（共用 `batch`）。
    verdict 不在 VERDICTS、`modify` 没带原话 → ValueError；
    有不认识的 id → KeyError（一条都不写）。"""
    ids = [pids] if isinstance(pids, str) else list(dict.fromkeys(pids))
    if not ids:
        raise ValueError("至少答一条")
    if verdict not in VERDICTS:
        raise ValueError(f"verdict 须为 {' / '.join(VERDICTS)} 之一（收到 {verdict!r}）")
    words = str(words or "").strip()
    if verdict == "modify" and not words:
        raise ValueError("「改」要写改成什么（words 不能为空）")
    for pid in ids:
        _ensure(data_dir, pid)
    at = at or _iso(_now())
    batch = ("B-" + hashlib.sha1(f"{'|'.join(ids)}|{at}".encode()).hexdigest()[:8]
             if len(ids) > 1 else "")
    events = [{"op": "answer", "id": pid, "at": at, "verdict": verdict, "words": words, "by": by,
               "batch": batch} for pid in ids]
    for event in events:
        _append(data_dir, event)
    return events


def done(data_dir: Path | str, pid: str, *, result: str, at: str | None = None) -> dict:
    """签 / 改过的提案执行完了 → 该事件。没答或答的是否 / 已过时 → ValueError。"""
    if not str(result).strip():
        raise ValueError("result 不能为空：写执行了什么（commit、命令、文件）")
    _ensure(data_dir, pid)
    row = next(r for r in load(data_dir) if r["id"] == pid)
    if row.get("verdict") not in EXECUTABLE:
        raise ValueError(f"{pid} 当前是「{STATUSES[row['status']]}」，只有签 / 改过的才能标已执行")
    event = {"op": "done", "id": pid, "at": at or _iso(_now()), "result": str(result).strip()}
    _append(data_dir, event)
    return event


# ---- 折叠 ----------------------------------------------------------------

def _days(start: str, today: str) -> int:
    try:
        return max((_date.fromisoformat(today) - _date.fromisoformat(start[:10])).days, 0)
    except ValueError:
        return 0


def _fold_row(base: dict, history: list[dict], today: str) -> dict:
    row = {k: v for k, v in base.items() if k != "op"}
    asks = [h for h in history if h["op"] == "ask"]
    answered = [i for i, h in enumerate(history) if h["op"] == "answer"]
    last = history[answered[-1]] if answered else None
    # 账只追加：排在最近一次答复之后的 done 才算（改答之后旧的执行不再算数）
    executed = [h for h in history[answered[-1] + 1:] if h["op"] == "done"] if answered else []
    row["status"] = "done" if executed else (last["verdict"] if last else "pending")
    row["asked_count"] = int(base.get("asked_base") or 1) + len(asks)
    row["age_days"] = _days(str(base.get("at") or today), today)
    row["overdue"] = row["status"] == "pending" and (
        row["asked_count"] >= NAG_ASKED or row["age_days"] >= NAG_DAYS)
    row["verdict"] = last["verdict"] if last else None
    row["words"] = last.get("words", "") if last else ""
    row["by"] = last.get("by") if last else None
    row["answered_at"] = last["at"] if last else None
    row["batch"] = last.get("batch", "") if last else ""
    row["result"] = executed[-1]["result"] if executed else ""
    row["done_at"] = executed[-1]["at"] if executed else None
    row["history"] = [{k: v for k, v in h.items() if k != "id"} for h in history]
    return row


def _ts(value) -> float:
    from nutmeg.decision.bj_time import parse_bj

    at = parse_bj(value)
    return at.timestamp() if at else float("-inf")


def _order(rows: list[dict]) -> list[dict]:
    """待签在前（提出时刻新的在前），其余按最近一次答复 / 执行新的在前。"""
    pending = sorted((r for r in rows if r["status"] == "pending"), key=lambda r: _ts(r["at"]),
                     reverse=True)
    rest = sorted((r for r in rows if r["status"] != "pending"),
                  key=lambda r: _ts(r.get("done_at") or r.get("answered_at") or r["at"]),
                  reverse=True)
    return pending + rest


def load(data_dir: Path | str, *, today: str | None = None) -> list[dict]:
    """按 id 折叠账：状态＝没答「待签」/ 最近一次答复的 verdict / 答复之后有 done「已执行」；
    问过次数＝起始次数（种子的 `asked`，缺省 1）+ ask 事件数；`batch_size` 是同批条数。
    没有账 → []。"""
    today = today or _now().date().isoformat()
    bases: dict[str, dict] = {}
    history: dict[str, list[dict]] = {}
    for event in _events(data_dir):
        pid, op = event["id"], event.get("op")
        if op == "create":
            bases.setdefault(pid, event)
            history.setdefault(pid, [])
        elif op in ("ask", "answer", "done") and event.get("at"):
            history.setdefault(pid, []).append(event)
    rows = [_fold_row(bases[pid], history[pid], today) for pid in bases]
    batches = Counter(r["batch"] for r in rows if r["batch"])
    for r in rows:
        r["batch_size"] = batches.get(r["batch"], 1) if r["batch"] else 1
    return _order(rows)


def inbox(data_dir: Path | str, *, today: str | None = None) -> list[dict]:
    """账 + 闭环里还开着、账上还没有的 RSI 项。"""
    rows = load(data_dir, today=today)
    known = {r["id"] for r in rows}
    return _order(rows + [r for r in rsi_items(data_dir, today=today) if r["id"] not in known])


def summary(rows: list[dict]) -> dict:
    """{pending, overdue, by_status, total}。"""
    by_status = Counter(r.get("status") for r in rows)
    return {"pending": by_status.get("pending", 0),
            "overdue": sum(bool(r.get("overdue")) for r in rows),
            "by_status": dict(by_status), "total": len(rows)}


def pending_count(data_dir: Path | str) -> int:
    """导航角标：待签数（账 + 开着的 RSI 项，只读）。"""
    return summary(inbox(data_dir))["pending"]


# ---- 回填 ----------------------------------------------------------------

def seed(data_dir: Path | str, path: Path | str = SEED) -> dict:
    """种子文件（会话摘要与记忆里挑出的待签提案，见其 `_about`）→ {added, skipped}；可反复跑。"""
    added = skipped = 0
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    for row in doc.get("rows") or []:
        at = str(row["at"])
        _, new = _create(data_dir, title=row["title"], body=row.get("body", ""),
                         blocks=row.get("blocks", ""), deadline=row.get("deadline"),
                         source=SEED_SOURCE, ref=row.get("ref", ""),
                         at=at + "T12:00:00+08:00" if len(at) == 10 else at,
                         asked_base=row.get("asked"))
        added += new
        skipped += not new
    return {"added": added, "skipped": skipped}
