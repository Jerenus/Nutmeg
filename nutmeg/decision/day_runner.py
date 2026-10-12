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

from nutmeg.decision.day_brief import compile_brief, write_brief
from nutmeg.decision.day_decisions import build_decisions, write_decisions
from nutmeg.decision.day_paths import BRIEF, DECISIONS, RESULTS_90, RETRO, day_dir
from nutmeg.decision.day_session import render_session_md, write_session
from nutmeg.decision.day_timeline import JobRecord, append_job, read_timeline
from nutmeg.decision.files import read_json

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]
Now = Callable[[], datetime]
Claude = Callable[[str, str], tuple[int, str]]

JOBS = ("settle", "brief", "session", "results", "broadcast")
RESULTS_LOOKBACK_DAYS = 3  # 赛果桥追补：美洲晚场 09:45 常未封存，回看三天补缺（2026-09-30）


@dataclass
class DayContext:
    root: Path
    data_dir: Path
    date: str
    runner: Runner
    now: Now
    sender: Callable[[str], None] | None = None
    claude: Claude | None = None

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
    uv = ["uv", "run", "nutmeg"]
    if job != "settle":
        return []
    data = ["--data-dir", str(ctx.data_dir)]
    cmds = [[*uv, "workbench-export", "--date", _yesterday(ctx.date),
             "--output-dir", str(ctx.data_dir / "jczq"), "--out", str(ctx.out_dir / RETRO)]]
    results = ctx.out_dir / RESULTS_90
    if results.exists():
        cmds.append([*uv, "betslip", "settle", "--results-file", str(results), *data])
    # 人群线索赛后结算（2026-10-07）：扫所有有线索、赛果已出、尚未结算的期。
    cmds.append([*uv, "crowd", "settle", "--pending", *data])
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


def _encode_retro(ctx: DayContext, day: str) -> str:
    """复盘编码器（2026-09-30）：板面日 day 的实票与判断记分进 scoreboard；无赛果只留痕。"""
    from nutmeg.decision.retro_encoder import encode_jczq_day

    try:
        out = encode_jczq_day(ctx.data_dir, day, now=ctx.now().isoformat(timespec="seconds"))
    except Exception as exc:  # noqa: BLE001 — 只留痕不抛
        return f"｜复盘编码失败 {exc!r}"[:200]
    if out is None:
        return f"｜复盘编码 jczq-{day}：无赛果"
    return (f"｜复盘编码 jczq-{day}：{out['slips']} 票 净 {out['net']}，{out['n_matches']} 场 "
            f"Brier 市场 {out['market_brier']} / 终判 {out['final_brier']}")


def _brief_pipeline(ctx: DayContext, with_logic: bool = False) -> str:
    brief = compile_brief(data_dir=ctx.data_dir, date=ctx.date, root=ctx.root, now=ctx.now())
    if with_logic:
        from nutmeg.decision.brief_writer import _claude_cli, write_logic

        brief = write_logic(brief, claude=ctx.claude or _claude_cli)
    else:
        from nutmeg.decision.brief_writer import carry_logic

        previous = read_json(ctx.out_dir / BRIEF)
        brief = carry_logic(brief, previous if isinstance(previous, dict) else None)
    write_brief(ctx.data_dir, ctx.date, brief)
    timeline = read_timeline(ctx.data_dir, ctx.date)
    decisions = build_decisions(brief, timeline, data_dir=ctx.data_dir, now=ctx.now())
    write_decisions(ctx.data_dir, ctx.date, decisions)
    write_session(ctx.data_dir, ctx.date, render_session_md(brief, decisions, timeline))
    n_open = sum(1 for d in decisions if d["status"] == "open" and not d.get("auto_default"))
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


def run_job(ctx: DayContext, job: str, *, force: bool = False,
            with_logic: bool = False) -> JobRecord:
    if job not in JOBS:
        raise ValueError(f"unknown job {job!r}; JOBS={JOBS}")
    planned = ctx.now().isoformat(timespec="seconds")
    started_at = ctx.now().isoformat(timespec="seconds")
    commands: list[dict] = []
    evidence: str | None = None
    exit_code = 0
    if job == "settle":
        retro = ctx.out_dir / RETRO
        results = ctx.out_dir / RESULTS_90
        # 09:45 赛果常未封存：那次写出的底稿没有赛果，15:45 赛果到了必须重跑（2026-10-08）
        stale = (retro.exists() and results.exists()
                 and results.stat().st_mtime > retro.stat().st_mtime)
        if retro.exists() and not force and not stale:
            summary, exit_code = f"skipped: {RETRO} 已存在（--force 重跑）", 0
        else:
            commands, exit_code = _run_commands(ctx, planned_commands(ctx, "settle"))
            failed = [" ".join(c["cmd"].split(" ")[1:3]) for c in commands if c["exit"] != 0]
            summary = "settle 完成" if not failed else "失败: " + ", ".join(failed)
            summary += _encode_retro(ctx, _yesterday(ctx.date))
            evidence = str(retro) if retro.exists() else None
    elif job == "brief":
        try:
            summary, exit_code = _brief_pipeline(ctx, with_logic), 0
            evidence = str(ctx.out_dir / BRIEF)
        except Exception as exc:  # noqa: BLE001 — 只留痕不抛
            summary, exit_code = f"brief 异常: {exc!r}"[:300], 1
    elif job == "results":
        from nutmeg.decision.day_results import bridge_results

        parts: list[str] = []
        for back in range(1, RESULTS_LOOKBACK_DAYS + 1):
            target = (_date.fromisoformat(ctx.date) - timedelta(days=back - 1)).isoformat()
            if back > 1 and (day_dir(ctx.data_dir, target) / RESULTS_90).exists():
                continue  # 追补只补缺的
            report = bridge_results(data_dir=ctx.data_dir, date=target)
            if back > 1 and not report["written"] and not report.get("unsealed"):
                continue  # 更早的日子既无板也无赛果：不是问题
            line = (f"源 {report['source_day']} written={report['written']} "
                    f"missing={len(report['missing'])}")
            if report.get("unsealed"):
                # 回填要整板踢完才封存；缺一场这一天就进不了 results-90（2026-09-27 静默 0 场）。
                line += "｜⚠️源日有板但赛果未封存（jc-results 无此日），票与改判账未结"
                exit_code = 1
            if report["written"]:
                line += _encode_retro(ctx, report["source_day"])
                if back == 1:
                    evidence = str(ctx.out_dir / RESULTS_90)
            parts.append(line)
        summary = "results " + "；".join(parts)
    elif job == "broadcast":
        from nutmeg.decision.day_broadcast import send_all, telegram_sender
        from nutmeg.decision.day_decisions import broadcast_decisions

        decisions = broadcast_decisions(ctx.data_dir, ctx.date, now=ctx.now())
        try:
            sender = ctx.sender or telegram_sender()
            report = send_all(decisions, data_dir=ctx.data_dir, date=ctx.date, now=ctx.now(),
                              sender=sender)
            summary = f"broadcast sent={len(report['sent'])} failed={len(report['failed'])}"
            exit_code = 1 if report["failed"] else 0
        except RuntimeError as exc:  # telegram 未配置
            summary, exit_code = f"broadcast 未发：{exc}", 1
    else:
        summary, exit_code = _session_only(ctx)
    record = JobRecord(job=job, planned_at=planned, started_at=started_at,
                       finished_at=ctx.now().isoformat(timespec="seconds"), exit=exit_code,
                       summary=summary, evidence_path=evidence, commands=commands)
    append_job(ctx.data_dir, ctx.date, record)
    return record
