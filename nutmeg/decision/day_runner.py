"""`nutmeg day run --job …`：把一天的自动作业落到 daily/<日>/（设计 §4–§5）。

与 rsi_loop 同一纪律：子进程编排、可注入 runner/now、只追加、失败只记一行不抛。
⛔不 approve Read、不 choose/commit、不 register/deploy、不登记实票、不推送购买。
"""
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, timedelta
from pathlib import Path

from nutmeg.decision.day_brief import compile_brief, current_issue, write_brief
from nutmeg.decision.day_decisions import build_decisions, write_decisions
from nutmeg.decision.day_paths import BRIEF, DECISIONS, RESULTS_90, RETRO, day_dir, zucai_dir
from nutmeg.decision.day_session import render_session_md, write_session
from nutmeg.decision.day_timeline import JobRecord, append_job, read_timeline

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]
Now = Callable[[], datetime]

JOBS = ("settle", "brief", "session")


@dataclass
class DayContext:
    root: Path
    data_dir: Path
    date: str
    runner: Runner
    now: Now

    @property
    def out_dir(self) -> Path:
        return day_dir(self.data_dir, self.date)


def default_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, check=False)


def _yesterday(date: str) -> str:
    return (_date.fromisoformat(date) - timedelta(days=1)).isoformat()


def _tail(text: str, lines: int = 3) -> str:
    chunks = [line for line in (text or "").strip().splitlines() if line.strip()]
    return " / ".join(chunks[-lines:])[:600]


def planned_commands(ctx: DayContext, job: str) -> list[list[str]]:
    if job != "settle":
        return []
    uv = ["uv", "run", "nutmeg"]
    data = ["--data-dir", str(ctx.data_dir)]
    cmds = [[*uv, "workbench-export", "--date", _yesterday(ctx.date),
             "--output-dir", str(ctx.data_dir / "jczq"), "--out", str(ctx.out_dir / RETRO)]]
    results = ctx.out_dir / RESULTS_90
    if results.exists():
        cmds.append([*uv, "betslip", "settle", "--results-file", str(results), *data])
    zdir = zucai_dir(ctx.data_dir)
    issue = current_issue(zdir, now=ctx.now()) if zdir.exists() else None
    if issue and (zdir / f"{issue}-rx.json").exists():
        cmds.append([*uv, "workflow", "grade-rx", "--rx-file", str(zdir / f"{issue}-rx.json"),
                     "--issue", issue, *data])
    return cmds


def _run_commands(ctx: DayContext, cmds: list[list[str]]) -> tuple[list[dict], int]:
    rows, exit_code = [], 0
    for cmd in cmds:
        proc = ctx.runner(cmd)
        text = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        rows.append({"cmd": " ".join(cmd[2:]), "exit": proc.returncode, "tail": _tail(text)})
        if proc.returncode != 0:
            exit_code = 1
    return rows, exit_code


def _brief_pipeline(ctx: DayContext) -> str:
    brief = compile_brief(data_dir=ctx.data_dir, date=ctx.date, root=ctx.root, now=ctx.now())
    write_brief(ctx.data_dir, ctx.date, brief)
    timeline = read_timeline(ctx.data_dir, ctx.date)
    decisions = build_decisions(brief, timeline, data_dir=ctx.data_dir, now=ctx.now())
    write_decisions(ctx.data_dir, ctx.date, decisions)
    write_session(ctx.data_dir, ctx.date, render_session_md(brief, decisions, timeline))
    n_open = sum(1 for d in decisions if d["status"] == "open")
    return (f"brief {brief['jczq']['counts']['matches']} 场 · 待人 {n_open} · "
            f"缺席输入 {len(brief['errors'])}")


def _session_only(ctx: DayContext) -> tuple[str, int]:
    brief_path = ctx.out_dir / BRIEF
    if not brief_path.exists():
        return f"缺 {BRIEF}：先跑 --job brief", 1
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    dec_path = ctx.out_dir / DECISIONS
    decisions = json.loads(dec_path.read_text(encoding="utf-8")) if dec_path.exists() else []
    timeline = read_timeline(ctx.data_dir, ctx.date)
    write_session(ctx.data_dir, ctx.date, render_session_md(brief, decisions, timeline))
    return "session.md 重渲染", 0


def run_job(ctx: DayContext, job: str, *, force: bool = False) -> JobRecord:
    if job not in JOBS:
        raise ValueError(f"unknown job {job!r}; JOBS={JOBS}")
    planned = ctx.now().isoformat(timespec="seconds")
    started_at = ctx.now().isoformat(timespec="seconds")
    commands: list[dict] = []
    evidence: str | None = None
    if job == "settle":
        retro = ctx.out_dir / RETRO
        if retro.exists() and not force:
            summary, exit_code = f"skipped: {RETRO} 已存在（--force 重跑）", 0
        else:
            commands, exit_code = _run_commands(ctx, planned_commands(ctx, "settle"))
            failed = [" ".join(c["cmd"].split(" ")[1:3]) for c in commands if c["exit"] != 0]
            summary = "settle 完成" if not failed else "失败: " + ", ".join(failed)
            evidence = str(retro) if retro.exists() else None
    elif job == "brief":
        try:
            summary, exit_code = _brief_pipeline(ctx), 0
            evidence = str(ctx.out_dir / BRIEF)
        except Exception as exc:  # noqa: BLE001 — 只留痕不抛
            summary, exit_code = f"brief 异常: {exc!r}"[:300], 1
    else:
        summary, exit_code = _session_only(ctx)
    record = JobRecord(job=job, planned_at=planned, started_at=started_at,
                       finished_at=ctx.now().isoformat(timespec="seconds"), exit=exit_code,
                       summary=summary, evidence_path=evidence, commands=commands)
    append_job(ctx.data_dir, ctx.date, record)
    return record
