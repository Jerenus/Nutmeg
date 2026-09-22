"""会话入口读的上下文包 `session.md`（设计 §8）与讨论流 `discussion.jsonl`。"""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.day_paths import DISCUSSION, SESSION, day_dir

MAX_CHARS = 4000


def _hm(iso: str | None) -> str:
    return (iso or "")[11:16] or "—"


def render_session_md(brief: dict, decisions: list[dict], timeline: list[dict]) -> str:
    rule = "规则：不重跑已完成作业；先看失败；对话从待人决定开始；每轮末尾报最近截止与剩余分钟。"
    lines = [f"# 会话入口 · {brief['date']}", "", rule, "", "## 作业", ""]
    seen: dict[str, dict] = {}
    for job in timeline:
        seen[job["job"]] = job

    def _job_line(j: str, r: dict) -> str:
        ok = r.get("exit", 0) == 0
        status = "✓" if ok else "✗ " + str(r.get("summary", ""))[:80]
        return f"- {j} {status} @{_hm(r.get('finished_at'))}"

    lines += [_job_line(j, r) for j, r in seen.items()] or ["- 今日尚无作业记录"]
    lines += ["", "## 待人决定（从这里开始）", ""]
    open_rows = [d for d in decisions if d.get("status") == "open"]
    lines += [
        f"- [{d['id']}] {d['subject']} · 截止 {_hm(d.get('deadline'))} · 默认 {d['default_action']}"
        for d in open_rows
    ] or ["- 无"]
    c = brief["jczq"]["counts"]
    lines += ["", f"## 竞彩 {c.get('matches', 0)} 场（深研 {c.get('deep_research', 0)}）", ""]
    for m in brief["jczq"]["matches"]:
        read = m.get("read") or {}
        lines.append(
            f"- {m['code']} {m.get('name')} · {m.get('ladder')} · {read.get('moved_pp', 0)}pp · "
            f"{_hm(m.get('kickoff_bj'))} · 研究 {m['research']['status']} · "
            f"Read {read.get('judge') or '—'}/{read.get('status') or '—'}"
        )
    z = brief["zucai"]
    lines += [
        "",
        f"## 足彩 {z.get('issue') or '无在售期'}"
        + (f" · 截止 {_hm(z.get('sale_deadline'))}" if z.get("issue") else ""),
        "",
    ]
    if z.get("tiers"):
        lines.append(f"- 风向 {json.dumps(z['tiers'].get('wind'), ensure_ascii=False)}")
    for channel, doc in (z.get("frontier") or {}).items():
        lines.append(f"- {channel} 前沿 {len(doc.get('points') or [])} 点")
    rsi = brief.get("rsi") or {}
    rsi_lines = [f"- {a}" for a in rsi.get("human_actions") or []] or ["- 无待人决定"]
    lines += ["", "## RSI", ""] + rsi_lines
    text = "\n".join(lines) + "\n"
    if len(text) > MAX_CHARS:
        text = text[: MAX_CHARS - 40].rstrip() + "\n\n…（已截断，全文见 brief.md）\n"
    return text


def write_session(data_dir: Path | str, date: str, text: str) -> Path:
    out = day_dir(data_dir, date)
    out.mkdir(parents=True, exist_ok=True)
    path = out / SESSION
    path.write_text(text, encoding="utf-8")
    return path


def read_discussion(data_dir: Path | str, date: str) -> list[dict]:
    path = day_dir(data_dir, date) / DISCUSSION
    if not path.exists():
        return []
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            row = json.loads(line)
            row.setdefault("seq", i)
            rows.append(row)
    return rows


def append_discussion(
    data_dir: Path | str, date: str, *, who: str, text: str, obj: str = "", at: str
) -> Path:
    path = day_dir(data_dir, date) / DISCUSSION
    path.parent.mkdir(parents=True, exist_ok=True)
    seq = len(read_discussion(data_dir, date)) + 1
    row = {"seq": seq, "who": who, "obj": obj, "text": text, "at": at}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path
