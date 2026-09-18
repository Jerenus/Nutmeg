"""追问线程的另一头 —— 把「页面提问 → 终端里有人看到 → 手写回复」这条人肉链换成进程。

出生事故 2026-09-18：用户在工作台问「这场是不是朗斯不败的逻辑更成立？」，`user_message`
落盘了，但 `agent_reply` 在代码里只有写入工具、没有任何进程监听——没反应。我在终端
手写了一条回进事件流（seq=2）。本模块让这件事不再依赖终端里有人。

⛔判断永不入脚本：应答器**只解释已落库的研究与判读**——不产生新的面集建议、不改 belief。
   这条既在 system prompt 里，也在测试里（回复含「建议买/应该排」即判违规）。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from nutmeg.decision.workbench import append_event, read_events


def pending_questions(output_dir, date: str) -> list[dict]:
    """同一 obj_id 上，最后一条 user_message 之后没有 agent_reply 的，就是待答。"""
    last_q: dict[str, dict] = {}
    answered: set[str] = set()
    for ev in read_events(output_dir, date):
        obj = ev.get("obj_id")
        if ev.get("kind") == "user_message":
            last_q[obj] = ev
            answered.discard(obj)
        elif ev.get("kind") == "agent_reply" and obj in last_q:
            answered.add(obj)
    return [q for obj, q in last_q.items() if obj not in answered]


_FORBIDDEN = ("建议买", "应该买", "应该排", "改成", "推荐买", "押")
_RESEARCH_FIELDS = (
    "match_no", "name", "summary", "anchor_side", "anchor_integrity", "hole_location",
    "license_questions", "death_three_proofs", "directional_flags",
    "nondirectional_flags", "precedents", "schedule", "market_snapshot",
)


def _find_research(issue: str, zucai_dir: Path, match_label: str) -> dict | None:
    """按对阵名匹配 <issue>-research-m<N>.json。

    judgment 的「主 vs 客」两队名都出现在研究 name 里即认定同一场。
    """
    home, _, away = match_label.partition(" vs ")
    for path in sorted(Path(zucai_dir).glob(f"{issue}-research-m*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        name = str(doc.get("name") or "")
        if home and away and home[:2] in name and away[:2] in name:
            return {k: doc.get(k) for k in _RESEARCH_FIELDS if k in doc}
    return None


def _find_leg(issue: str, zucai_dir: Path, match_no: int | None) -> dict | None:
    if match_no is None:
        return None
    try:
        raw = (Path(zucai_dir) / f"{issue}-legs-base.json").read_text(encoding="utf-8")
        legs = json.loads(raw)["legs"]
    except (OSError, ValueError, KeyError):
        return None
    lg = legs.get(str(match_no))
    if not lg:
        return None
    return {k: lg.get(k) for k in ("name", "faces", "confidence", "fair", "anchor_integrity",
                                   "directional_flags", "nondirectional_flags",
                                   "license_questions")}


def build_context(obj_id: str, *, judgments: dict[str, dict], issue: str, zucai_dir) -> dict:
    j = judgments.get(obj_id) or {}
    research = _find_research(issue, Path(zucai_dir), str(j.get("match") or ""))
    leg = _find_leg(issue, Path(zucai_dir), (research or {}).get("match_no"))
    return {"obj_id": obj_id, "issue": issue, "judgment": j,
            "research": research or {}, "leg": leg or {}}


def respond_pending(output_dir, date: str, *, provider, judgments: dict[str, dict],
                    issue: str, zucai_dir) -> int:
    """回答全部待答追问；返回成功写入的 agent_reply 数。违规回复不写正文，写拒答留痕。"""
    done = 0
    for q in pending_questions(output_dir, date):
        ctx = build_context(q["obj_id"], judgments=judgments, issue=issue, zucai_dir=zucai_dir)
        try:
            text = provider.answer(ctx, str(q.get("text") or ""))
        except Exception as exc:  # noqa: BLE001 — 不崩，留痕
            text, ok = f"应答器不可用：{exc}", False
        else:
            ok = not any(w in text for w in _FORBIDDEN)
            if not ok:
                text = ("应答器拒答：模型回复含面集建议（判断永不入脚本）。"
                        "请在终端里说「今天的方案」由主循环判读。")
        append_event(output_dir, date, {
            "kind": "agent_reply", "obj_id": q["obj_id"], "text": text,
            "agent": "workbench-responder", "in_reply_to": q.get("seq"),
            "at": datetime.now().astimezone().isoformat(timespec="seconds")})
        done += 1 if ok else 0
    return done
