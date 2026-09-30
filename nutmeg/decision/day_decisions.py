"""待人决定清单（设计 §4 `decisions.json`、§7「待人决定」块、§5 播报的输入）。

只列「系统做不了、只有人能做」的事，并给每条截止时间与默认动作（宪法：空仓是对着数字做的选择）。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.decision.day_paths import DECISIONS, day_dir, jczq_day_dir

DEFAULT_EMPTY = "空仓"
_BJ = timezone(timedelta(hours=8))


def _decided_reads(data_dir: Path, date: str) -> set[str]:
    path = jczq_day_dir(data_dir, date) / "decisions.jsonl"
    if not path.exists():
        return set()
    done: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("action") in ("approve_read", "reject_read"):
            done.add(str(row.get("obj_id")))
    return done


def _status(deadline: str | None, done: bool, now: datetime) -> str:
    if done:
        return "done"
    if deadline:
        try:
            parsed = datetime.fromisoformat(deadline)
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_BJ)
            if parsed <= now:
                return "expired"
    return "open"


def build_decisions(
    brief: dict, timeline: list[dict], *, data_dir: Path | str, now: datetime
) -> list[dict]:
    decided = _decided_reads(Path(data_dir), brief["date"])
    rows: list[dict] = []
    for m in brief.get("jczq", {}).get("matches", []):
        read = m.get("read")
        if not read or read.get("status") != "draft":
            continue
        rows.append({
            "id": f"read:{m['code']}", "kind": "approve_read",
            "subject": f"{m['code']} {m.get('name')}（{read.get('judge')} 草稿）",
            "deadline": m.get("kickoff_bj"), "default_action": "草稿不入库＝跟市场",
            "status": _status(m.get("kickoff_bj"), str(read.get("read_id")) in decided, now),
            "source": "reads.json",
            # 默认动作就是合法结局：不算「等人」（2026-09-30 降噪，此前每天 12–18 项待人）
            "auto_default": True,
        })
    z = brief.get("zucai") or {}
    if z.get("issue") and z.get("tiers") and z.get("plan") is None:
        # 实票已登记（betslip register）＝这期已经定了，不再播报「未定则空仓」
        from nutmeg.decision.betslip import load_slips

        purchased = bool(load_slips(Path(data_dir), issue=str(z["issue"])))
        rows.append({
            "id": f"plan:{z['issue']}", "kind": "plan_choose_commit",
            "subject": f"{z['issue']} 在前沿上选点并定案（plan choose → commit）",
            "deadline": z.get("sale_deadline"), "default_action": DEFAULT_EMPTY,
            "status": _status(z.get("sale_deadline"), purchased, now), "source": "zucai",
        })
    rsi = brief.get("rsi") or {}
    for i, action in enumerate(rsi.get("human_actions") or []):
        rows.append({"id": f"rsi:{i}", "kind": "rsi", "subject": action, "deadline": None,
                     "default_action": "不动（hold）", "status": "open", "source": "rsi-loop"})
    for step in rsi.get("failed_steps") or []:
        rows.append({
            "id": f"loop:{step}", "kind": "failed_step",
            "subject": f"rsi loop 步骤 {step} 失败",
            "deadline": None, "default_action": "看 latest.md 后决定是否 --force 重跑",
            "status": "open", "source": "rsi-loop",
        })
    latest_per_job: dict[str, dict] = {}
    for job in timeline:  # 只看每个作业最近一次；早先失败、后来成功的不再列
        latest_per_job[str(job.get("job"))] = job
    for job in latest_per_job.values():
        if job.get("exit", 0) != 0:
            rows.append({"id": f"job:{job['job']}", "kind": "failed_job",
                         "subject": f"day 作业 {job['job']} 失败：{job.get('summary', '')[:120]}",
                         "deadline": None, "default_action": "看 timeline.json 的 commands 尾行",
                         "status": "open", "source": "timeline"})
    return rows


def write_decisions(data_dir: Path | str, date: str, rows: list[dict]) -> Path:
    out = day_dir(data_dir, date)
    out.mkdir(parents=True, exist_ok=True)
    path = out / DECISIONS
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
