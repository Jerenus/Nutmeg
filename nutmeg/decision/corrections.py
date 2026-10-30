"""纠正账（2026-10-30 产品形态第 10 阶段 Task 10.2）。

任何对象上的一个数 / 一句判断被改，都记成一条「纠正」：旧 → 新、类型、谁发现、证据、回写到哪、
状态。此前这些散在复盘页、记分牌备注、改判账、证据文档、记忆五处；这里是唯一一本只追加的账，
`/corrections` 页与 `nutmeg correction …` 只读写它。纠正对象只记账与路由——真正的回写仍走现有
命令（`research override`、`zucai-premise-corrections --apply`、记分牌写入），回写完再由 CLI
标「已回写」。

存储：`<data_dir>/corrections.jsonl`，只追加事件、从不改写：
- 新建 `{"op":"create","id","at","obj","old","new","kind","found_by","evidence","dest","status",
  "pile","note","source"}`；
- 改状态 `{"op":"status","id","at","status","note","by"}`。
`load` 按 id 折叠（最新状态为准，状态事件留在 `history`）。

`obj` 命名（前缀即层级，`for_obj` 按前缀取一个对象及其下属）：
- `issue:<期>` 一期；`issue:<期>/m<N>` 该期第 N 场；`issue:<期>/m<N>/<格>` 该场某格（如 `q4`）；
  `issue:<期>/§0` 分析包某节；
- `slip:<slip_id>` 一张票（`slip:26150-T2`）；
  `jczq:<日>/<编号>` 竞彩一场（`jczq:2026-09-26/周六003`）；
- `ledger:<YYYY-MM>` 月账；`rule:<名>` 一条规则 / SOP；`experiment:<名>` 一个实验。
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

LEDGER = "corrections.jsonl"

# 存键、显示标签（页面拿 labels 显示中文，不在 JS 里写死）
KINDS = {"data": "数据·账目", "transcription": "抄录", "premise": "研究前提",
         "self": "机器自纠", "overrule": "你改判"}
FOUND_BY = {"jun": "你", "machine": "机器", "result": "赛果", "official": "官方"}
DESTS = {"scoreboard": "记分牌", "betslips": "登记簿", "override": "研究改判",
         "premise": "球队画像（前提纠正）", "rulebook": "RULEBOOK/SOP", "memory": "记忆",
         "code": "代码", "page": "页面", "none": "无处可写"}
STATUSES = {"draft": "草稿·待你确认", "confirmed": "已确认·待回写", "written": "已回写",
            "dismissed": "不改·记一笔", "nowhere": "无处可写"}
CLOSED = ("written", "dismissed", "nowhere")
"""不再待办的状态；其余（草稿、已确认）计入堆的 `open`。"""

SEED = Path(__file__).resolve().parents[2] / "docs" / "superpowers" / "evidence" / \
    "2026-10-30-corrections-seed.json"
SEED_SOURCE = "seed:2026-10-30"
_ZUCAI_RESEARCH = re.compile(r"(\d{5})-research-m(\d+)\.json$")
_JCZQ_RESEARCH = re.compile(r"research-(.+)\.json$")
_SIDE = {"3": "主", "1": "平", "0": "客"}


def labels() -> dict:
    return {"kinds": KINDS, "found_by": FOUND_BY, "dests": DESTS, "statuses": STATUSES}


def _now() -> str:
    from nutmeg.decision.bj_time import BJ

    return datetime.now(BJ).isoformat(timespec="seconds")


def _check(name: str, value: str, allowed: dict) -> None:
    if value not in allowed:
        raise ValueError(f"{name} 须为 {' / '.join(allowed)} 之一（收到 {value!r}）")


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


def correction_id(source: str, obj: str, old: str, new: str, at: str) -> str:
    return "C-" + hashlib.sha1(f"{source}|{obj}|{old}|{new}|{at}".encode()).hexdigest()[:8]


def _create(data_dir: Path | str, *, obj: str, old: str, new: str, kind: str, found_by: str,
            evidence: str, dest: str, status: str, pile: str, note: str, at: str | None,
            source: str) -> tuple[str, bool]:
    """→ (id, 是否新写)。同 id 已在账上就不再写（回填可反复跑）。"""
    _check("kind", kind, KINDS)
    _check("found_by", found_by, FOUND_BY)
    _check("dest", dest, DESTS)
    _check("status", status, STATUSES)
    if not str(obj).strip():
        raise ValueError("obj 不能为空")
    at = at or _now()
    cid = correction_id(source, obj, old, new, at)
    if any(e["id"] == cid and e.get("op") == "create" for e in _events(data_dir)):
        return cid, False
    _append(data_dir, {"op": "create", "id": cid, "at": at, "obj": obj, "old": old, "new": new,
                       "kind": kind, "found_by": found_by, "evidence": evidence, "dest": dest,
                       "status": status, "pile": pile, "note": note, "source": source})
    return cid, True


def record(data_dir: Path | str, *, obj: str, old: str, new: str, kind: str, found_by: str,
           evidence: str = "", dest: str = "none", status: str = "draft", pile: str = "",
           note: str = "", at: str | None = None, source: str = "cli") -> str:
    """记一条纠正 → id。取值不在枚举里抛 ValueError（列出允许值）；
    同一条（同 source/obj/旧/新/时刻）已在账上就原样返回 id、不重写。`at` 缺省＝北京时间现在。"""
    cid, _ = _create(data_dir, obj=obj, old=old, new=new, kind=kind, found_by=found_by,
                     evidence=evidence, dest=dest, status=status, pile=pile, note=note, at=at,
                     source=source)
    return cid


def set_status(data_dir: Path | str, cid: str, status: str, *, note: str = "", by: str = "jun",
               at: str | None = None) -> dict:
    """追加一条状态事件 → 该事件。账上没有这个 id 抛 KeyError。"""
    _check("status", status, STATUSES)
    if not any(e["id"] == cid and e.get("op") == "create" for e in _events(data_dir)):
        raise KeyError(cid)
    event = {"op": "status", "id": cid, "at": at or _now(), "status": status, "note": note,
             "by": by}
    _append(data_dir, event)
    return event


def _sort_key(row: dict) -> float:
    from nutmeg.decision.bj_time import parse_bj

    at = parse_bj(row.get("at"))
    return at.timestamp() if at else float("-inf")


def load(data_dir: Path | str) -> list[dict]:
    """按 id 折叠：建条事件为底，状态取最新一条状态事件，`history` 留全部状态事件；
    按 `at` 新的在前。没有账 → []。"""
    rows: dict[str, dict] = {}
    for event in _events(data_dir):
        cid = event["id"]
        if event.get("op") == "create":
            if cid not in rows:
                rows[cid] = {k: v for k, v in event.items() if k != "op"} | {"history": []}
        elif event.get("op") == "status" and cid in rows:
            rows[cid]["history"].append({k: v for k, v in event.items() if k not in ("op", "id")})
            rows[cid]["status"] = event.get("status")
    return sorted(rows.values(), key=_sort_key, reverse=True)


def summary(rows: list[dict]) -> dict:
    """{piles:[{pile, n, dates, open}]（n 多的在前）, by_kind, by_status, drafts}。"""
    piles: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("pile"):
            piles.setdefault(row["pile"], []).append(row)
    out = [{"pile": name, "n": len(group),
            "dates": sorted({str(r.get("at") or "")[:10] for r in group if r.get("at")}),
            "open": sum(r.get("status") not in CLOSED for r in group)}
           for name, group in piles.items()]
    out.sort(key=lambda p: (-p["n"], p["pile"]))
    by_status = Counter(r.get("status") for r in rows)
    return {"piles": out, "by_kind": dict(Counter(r.get("kind") for r in rows)),
            "by_status": dict(by_status), "drafts": by_status.get("draft", 0)}


def for_obj(rows: list[dict], prefix: str) -> list[dict]:
    """该对象本身及其下属（`issue:26151` 取到 `issue:26151/m3/q4`，取不到 `issue:261510`）。"""
    return [r for r in rows if r.get("obj") == prefix or str(r.get("obj") or "").startswith(
        prefix + "/")]


def draft_count(data_dir: Path | str) -> int:
    """导航角标：草稿数（只读这本账）。"""
    return summary(load(data_dir))["drafts"]


# ---- 回填 ----------------------------------------------------------------

def _tilt_text(tilt: dict | None) -> str:
    """{face, shift} → 「表态 1 · 主+2 平+2 客−4」；没有可写的 → 空串。"""
    if not isinstance(tilt, dict):
        return ""
    parts = []
    if tilt.get("face"):
        parts.append(f"表态 {tilt['face']}")
    shift = tilt.get("shift") or {}
    moved = [f"{_SIDE[k]}{float(shift[k]):+g}".replace("-", "−")
             for k in ("3", "1", "0") if shift.get(k)]
    if moved:
        parts.append(" ".join(moved))
    return " · ".join(parts)


def _override_obj(path: Path, row: dict, data_dir: Path) -> str | None:
    research = str(row.get("research") or "")
    if path.parent == Path(data_dir) / "zucai":
        m = _ZUCAI_RESEARCH.search(research)
        return f"issue:{m.group(1)}/m{int(m.group(2))}" if m else None
    m = _JCZQ_RESEARCH.search(research)
    # 编号优先取研究文件名（research-周六003.json）；有的 match 串开头不是编号（「罗达JC vs …」）
    no = m.group(1) if m else (str(row.get("match") or "").split() or [""])[0]
    return f"jczq:{path.parent.name}/{no}" if no else None


def _override_fields(row: dict) -> tuple[str, str, str]:
    """改判行 → (old, new, evidence)。"""
    original = _tilt_text(row.get("original_tilt"))
    old = f"原判 {original}" if original else "研究原判（不拨）"
    if row.get("to_market"):
        new = "回市场"
    else:
        new = _tilt_text(row.get("tilt")) or "撤拨（不拨）"
        if row.get("items"):
            new += " · 改项 " + "、".join(row["items"])
    evidence = str(row.get("note") or "")[:300]
    if row.get("reason"):
        evidence += f" · 理由 {row['reason']}"
    return old, new, evidence


def _override_files(data_dir: Path) -> list[Path]:
    from nutmeg.decision.overrides import LEDGER as OVERRIDES

    files = [data_dir / "zucai" / OVERRIDES]
    files += sorted((data_dir / "jczq" / "daily").glob(f"*/{OVERRIDES}"))
    return [f for f in files if f.exists()]


def backfill(data_dir: Path | str, seed_path: Path | str = SEED) -> dict:
    """一次性回填（可反复跑，已在账上的不再写）→ {added, skipped}。
    (a) 种子文件（会话摘要里挑出的纠正，见其 `_about`）；(b) 主循环改判账 `overrides.jsonl`
    （足彩 `zucai/` 与竞彩 `jczq/daily/<日>/`）——机器自纠、已回写到研究改判。"""
    data_dir = Path(data_dir)
    added = skipped = 0

    def _one(**kw) -> None:
        nonlocal added, skipped
        _, new = _create(data_dir, **kw)
        added += new
        skipped += not new

    seed = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    for row in seed.get("rows") or []:
        at = str(row["at"])
        _one(obj=row["obj"], old=row.get("old", ""), new=row.get("new", ""), kind=row["kind"],
             found_by=row["found_by"], evidence=row.get("evidence", ""),
             dest=row.get("dest", "none"), status=row.get("status", "draft"),
             pile=row.get("pile", ""), note=row.get("note", ""),
             at=at + "T12:00:00+08:00" if len(at) == 10 else at, source=SEED_SOURCE)
    for path in _override_files(data_dir):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict) or not row.get("at"):
                continue          # 没有时刻的行算不出稳定 id，回填不收
            obj = _override_obj(path, row, data_dir)
            if obj is None:
                continue
            old, new, evidence = _override_fields(row)
            _one(obj=obj, old=old, new=new, kind="self", found_by="machine", evidence=evidence,
                 dest="override", status="written", pile="", note=str(row.get("research") or ""),
                 at=row.get("at"), source="overrides")
    return {"added": added, "skipped": skipped}
