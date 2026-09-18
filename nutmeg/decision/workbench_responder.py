"""追问线程的另一头 —— 把「页面提问 → 终端里有人看到 → 手写回复」这条人肉链换成进程。

出生事故 2026-09-18：用户在工作台问「这场是不是朗斯不败的逻辑更成立？」，`user_message`
落盘了，但 `agent_reply` 在代码里只有写入工具、没有任何进程监听——没反应。我在终端
手写了一条回进事件流（seq=2）。本模块让这件事不再依赖终端里有人。

⛔判断永不入脚本：应答器**只解释已落库的研究与判读**——不产生新的面集建议、不改 belief。
   这条既在 system prompt 里，也在测试里（回复含「建议买/应该排」即判违规）。
"""
from __future__ import annotations

from nutmeg.decision.workbench import read_events


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
