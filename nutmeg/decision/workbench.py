"""Workshop 握手协议(spec §3/§3.5)——终端 agent 与浏览器共享的事件流。

daily/<date>/workbench.jsonl:append-only 事件流(agent 事件 + 浏览器 user_message、手记、候选)。
纯文件 IO,无 web 依赖、无判断——判断在终端 Claude 推理里产生并写事件,本模块只搬运。
(2026-10-08:批准 Read 时用的 decisions.jsonl 裁决留痕与追问蒸馏随批准路由退役。)
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def _daily_dir(output_dir, date: str) -> Path:
    return Path(output_dir) / "daily" / date


def _wb_path(output_dir, date: str) -> Path:
    return _daily_dir(output_dir, date) / "workbench.jsonl"


def append_event(output_dir, date: str, event: dict) -> int:
    """追加一个协议事件,自动打 seq(自增行号)。返回该事件 seq。"""
    path = _wb_path(output_dir, date)
    path.parent.mkdir(parents=True, exist_ok=True)
    seq = len(read_events(output_dir, date)) + 1
    event = {**event, "seq": seq}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return seq


def append_user_message(output_dir, date: str, *, obj_id: str, text: str,
                        at: str = "") -> int:
    """§3.5:浏览器追问 → 同一事件流的 user_message(obj_id 锚定)。"""
    return append_event(output_dir, date, {
        "kind": "user_message", "obj_id": obj_id, "text": text, "at": at})


def read_events(output_dir, date: str, *, since: int = 0) -> list[dict]:
    """读事件流;since>0 时只返回 seq>since 的新事件(SSE tail)。"""
    path = _wb_path(output_dir, date)
    if not path.exists():
        return []
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        ev = json.loads(line)
        ev.setdefault("seq", i)
        if ev["seq"] > since:
            out.append(ev)
    return out


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def append_note(output_dir, date: str, *, obj_id: str, text: str) -> int:
    """人写手记(裁决理由、否决原因、临场观察)——今天说过的话明天还在。"""
    return append_event(output_dir, date, {
        "kind": "note", "obj_id": obj_id, "text": text, "at": _now()})


def append_candidate(output_dir, date: str, *, obj_id: str, version: str, faces: dict,
                     notes: int, stake_yuan: int, p_all: float | None,
                     verdict: str, reason: str = "",
                     parent_version: str | None = None) -> int:
    """被考虑过的票面(含被否掉的)。verdict ∈ {considered, rejected, chosen}。

    出生事故 2026-09-18 的 26129:SFC-B→C→D→E 四轮票面迭代只活在聊天窗口,
    仓库里只剩终版文件,第二天在 app 里什么都看不到。

    parent_version 把候选串成树(SFC-C ← SFC-B):一天的票面迭代才能按边重走,
    而不是一张平铺清单。根候选留 None。
    """
    return append_event(output_dir, date, {
        "kind": "candidate", "obj_id": obj_id,
        "payload": {"version": version, "parent_version": parent_version,
                    "faces": faces, "notes": notes,
                    "stake_yuan": stake_yuan, "p_all": p_all,
                    "verdict": verdict, "reason": reason},
        "at": _now()})
