"""事件流 → Markdown 复盘底稿。只排版,不总结(总结是判断,归主循环)。

出生事故 2026-09-18 的 26129:SFC-B→C→D→E 四轮票面迭代、「平局是不是太少」的
曲线、「全是 3」的分散代价表,全部只存在于聊天窗口,仓库里只剩终版文件——第二天
在 app 里什么都看不到。本模块把当天事件流排成一份可以直接贴进复盘的底稿。
"""
from __future__ import annotations

from nutmeg.decision.workbench import read_events

_VERDICT_ZH = {"rejected": "已否决", "chosen": "已选", "considered": "考虑过"}


def events_to_markdown(output_dir, date: str) -> str:
    """当天事件流 → Markdown。事件缺可选键、p_all 为 None 都不许抛。"""
    evs = read_events(output_dir, date)
    tasks: list[str] = []
    thread: list[str] = []
    cands: list[str] = []
    notes: list[str] = []
    slips: list[str] = []
    for e in evs:
        k = e.get("kind")
        if k in ("task_done", "task_failed"):
            mark = "✓" if k == "task_done" else "✗"
            tasks.append(f"- {mark} {e.get('label')} · exit={e.get('exit_code')}")
        elif k == "user_message":
            thread.append(f"- **你**（{e.get('obj_id')}）：{e.get('text')}")
        elif k == "agent_reply":
            thread.append(f"  - **判**：{e.get('text')}")
        elif k == "candidate":
            p = e.get("payload") or {}
            pa = p.get("p_all")
            verdict = p.get("verdict")
            row = (f"- {p.get('version')} · {_VERDICT_ZH.get(verdict, verdict)}"
                   f" · {p.get('notes')} 注 ¥{p.get('stake_yuan')}")
            if pa is not None:
                row += f" · P {pa * 100:.2f}%"
            if p.get("reason"):
                row += f" — {p.get('reason')}"
            cands.append(row)
        elif k == "note":
            notes.append(f"- {e.get('text')}")
        elif k == "slip":
            p = e.get("payload") or {}
            slips.append(f"- {p.get('slip_id')} · {p.get('notes')} 注 ¥{p.get('stake_yuan')}")
    out = [f"# {date} 过程回放", ""]
    for title, rows in (("任务", tasks), ("追问", thread), ("候选票面", cands),
                        ("实票", slips), ("手记", notes)):
        out += [f"## {title}", *(rows or ["（无）"]), ""]
    return "\n".join(out)
