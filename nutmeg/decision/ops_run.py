"""launchd 作业包装：逐段执行、逐段记账、末行带时间戳的 NUTMEG_OK / NUTMEG_FAILED。

**Why（2026-10-12 运维体检）**：`day.settle` / `jczq.research` / `day.verdict` / `day.brief`
四份 plist 用 `;` 串多条命令，launchctl 只记最后一段的退出码——当天 `results` 段两次 exit 1
（「源日有板但赛果未封存」），launchctl 与 ops-status 都显示 day.settle 成功。再加上
`NUTMEG_OK` 行不带时间戳，状态页只能靠文件 mtime 猜。

本模块只做三件事：按顺序跑每段、把每段的结局追加到 `logs/runs.jsonl`、末行打带时间戳的标记。
任一段失败 → 继续跑完剩下的段（结算段不该因前段失败而不跑），最后退出 1。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

RUNS_LEDGER = "runs.jsonl"
"""`<data-dir>/logs/runs.jsonl`：每段一行 {ts, label, step, n, cmd, exit, secs, tail}。"""
OK_MARK = "NUTMEG_OK"
FAILED_MARK = "NUTMEG_FAILED"

Runner = Callable[[str], subprocess.CompletedProcess]


@dataclass(frozen=True)
class SegmentResult:
    ts: str
    label: str
    step: int
    n: int
    cmd: str
    exit: int
    secs: float
    tail: str


def _default_runner(cwd: Path) -> Runner:
    def run(cmd: str) -> subprocess.CompletedProcess:
        return subprocess.run(["/bin/zsh", "-lc", cmd], cwd=cwd, capture_output=True, text=True)

    return run


def _tail(text: str, limit: int = 300) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return " / ".join(lines[-3:])[-limit:]


def run_job(
    label: str,
    commands: list[str],
    *,
    data_dir: Path,
    cwd: Path,
    now: Callable[[], datetime] | None = None,
    runner: Runner | None = None,
    echo: Callable[[str], None] = print,
    echo_err: Callable[[str], None] | None = None,
) -> int:
    """跑完所有段，返回进程退出码（0 全成功 / 1 有段失败）。"""
    now = now or (lambda: datetime.now().astimezone())
    runner = runner or _default_runner(cwd)
    echo_err = echo_err or (lambda text: print(text, file=sys.stderr))
    ledger = Path(data_dir) / "logs" / RUNS_LEDGER
    ledger.parent.mkdir(parents=True, exist_ok=True)
    results: list[SegmentResult] = []
    for step, cmd in enumerate(commands, 1):
        started = time.monotonic()
        try:
            proc = runner(cmd)
            code, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""
        except OSError as exc:  # 连 shell 都起不来：记成失败而不是让包装器自己炸
            code, out, err = 127, "", f"{type(exc).__name__}: {exc}"
        if out:
            echo(out.rstrip("\n"))
        if err:
            echo_err(err.rstrip("\n"))
        result = SegmentResult(
            ts=now().isoformat(timespec="seconds"), label=label, step=step, n=len(commands),
            cmd=cmd, exit=int(code), secs=round(time.monotonic() - started, 1),
            tail=_tail(err if code else out),
        )
        results.append(result)
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
    failed = [r for r in results if r.exit != 0]
    stamp = now().isoformat(timespec="seconds")
    if failed:
        first = failed[0]
        echo(f"{FAILED_MARK} {label} step={first.step}/{first.n} exit={first.exit} {stamp}")
        return 1
    echo(f"{OK_MARK} {label} {stamp}")
    return 0


def read_ledger(data_dir: Path, *, day: str) -> list[dict]:
    """当天的分段账（按文件顺序）。文件缺失 / 坏行 → 跳过，不炸状态页。"""
    path = Path(data_dir) / "logs" / RUNS_LEDGER
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if str(row.get("ts", ""))[:10] == day:
                rows.append(row)
    except OSError:
        return []
    return rows


def failed_segments(data_dir: Path, *, day: str) -> dict[str, list[str]]:
    """{label: [「HH:MM step i/n exit=c cmd — tail」…]}，只列当天失败的段。"""
    out: dict[str, list[str]] = {}
    for row in read_ledger(data_dir, day=day):
        if int(row.get("exit") or 0) == 0:
            continue
        when = str(row.get("ts", ""))[11:16]
        cmd = str(row.get("cmd", ""))
        text = (
            f"{when} 段 {row.get('step')}/{row.get('n')} exit={row.get('exit')} "
            f"{cmd[:80]} — {str(row.get('tail', ''))[:120]}"
        )
        out.setdefault(str(row.get("label", "")), []).append(text)
    return out
