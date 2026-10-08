"""`/observe/{rules,factors,trace}` 的只读数据（设计 §10）。

git 与文件读取可注入；缺数据返回空结构。
"""
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from nutmeg.decision.day_paths import BRIEF, day_dir
from nutmeg.decision.faces import FACE_OF
from nutmeg.decision.match_results import board_outcomes

Git = Callable[[list[str]], str]
TRACKED = ("docs/sop/RULEBOOK.md", "experiments/factors.json", "docs/sop/CONSTITUTION.md")


def run_git(args: list[str]) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout
    except OSError:
        return ""


def rule_changes(root: Path, *, git: Git = run_git, limit: int = 60) -> list[dict]:
    rows = []
    for rel in TRACKED:
        out = git(["-C", str(root), "log", f"-{limit}", "--date=iso-strict",
                    "--format=%h|%ad|%s", "--", rel])
        for line in out.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                rows.append({"file": rel, "sha": parts[0], "at": parts[1], "subject": parts[2]})
    return sorted(rows, key=lambda r: r["at"], reverse=True)


def parse_attempts(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = [p.strip() for p in line.split(" | ")]
        if len(parts) != 5:
            continue
        keys = ("ts", "experiment", "params", "result", "conclusion")
        rows.append(dict(zip(keys, parts, strict=True)))
    return rows


def factor_history(root: Path) -> dict:
    attempts = parse_attempts(root / "experiments" / "attempts.log")
    try:
        raw = (root / "experiments" / "factors.json").read_text(encoding="utf-8")
        factors = json.loads(raw).get("factors") or []
    except (FileNotFoundError, ValueError):
        factors = []
    used: set[int] = set()
    out = []
    for f in factors:
        fid = str(f.get("factor_id"))
        mine = []
        for i, a in enumerate(attempts):
            if fid and fid in a["experiment"] and i not in used:
                used.add(i)
                mine.append(a)
        out.append({"factor_id": fid, "layer": f.get("layer"),
                    "current_weight_pp": f.get("current_weight_pp"),
                    "rule_name": f.get("rule_name"), "attempts": mine})
    other = [a for i, a in enumerate(attempts) if i not in used]
    return {"factors": out, "other_attempts": other}


def _top(p: dict | None) -> str | None:
    if not p:
        return None
    return max(("home", "draw", "away"), key=lambda k: float(p.get(k, 0)))


def trace_day(data_dir: Path, date: str) -> dict:
    try:
        brief = json.loads((day_dir(data_dir, date) / BRIEF).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        brief = {"jczq": {"matches": []}}
    results = board_outcomes(data_dir, date)
    matches: list[dict] = []
    summary = {"graded": 0, "read_right": 0, "market_right": 0, "moved": 0, "moved_helped": 0}
    for m in brief.get("jczq", {}).get("matches", []):
        read = m.get("read") or {}
        outcome = FACE_OF.get(str((results.get(m["code"]) or {}).get("outcome_90")))
        prior_top, belief_top = _top(read.get("prior")), _top(read.get("belief"))
        moved = bool(read) and prior_top != belief_top
        row = {"code": m["code"], "name": m.get("name"), "ladder": m.get("ladder"),
               "judge": read.get("judge"), "prior_top": prior_top, "belief_top": belief_top,
               "outcome": outcome,
               "market_right": (prior_top == outcome) if outcome and prior_top else None,
               "read_right": (belief_top == outcome) if outcome and belief_top else None,
               "moved_helped": (((belief_top == outcome) if outcome else None)
                                 if moved else None)}
        matches.append(row)
        if outcome and read:
            summary["graded"] += 1
            summary["read_right"] += int(row["read_right"] is True)
            summary["market_right"] += int(row["market_right"] is True)
            summary["moved"] += int(moved)
            summary["moved_helped"] += int(row["moved_helped"] is True)
    try:
        loop_path = Path(data_dir) / "analytics" / "rsi-loop" / f"{date}.json"
        loop = json.loads(loop_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        loop = {}
    not_due = [{"exp": v["cmd"].split("--exp")[-1].split()[0], "line": v.get("line", "")}
               for v in loop.get("verdicts") or []
               if v.get("status") == "not_due" and "--exp" in v.get("cmd", "")]
    return {"date": date, "matches": matches, "not_due": not_due, "summary": summary}
