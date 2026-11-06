"""账本读写：`jczq/arena/` 下的规则目录和只追加 jsonl。"""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.arena.rules import validate_rule

MAX_TRACKS = 40


def arena_dir(data_dir) -> Path:
    return Path(data_dir) / "jczq" / "arena"


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_rules(data_dir) -> list[dict]:
    """全部未退赛规则，带所属赛季。"""
    rules = []
    for path in sorted((arena_dir(data_dir) / "rules").glob("*/*.json")):
        rule = json.loads(path.read_text("utf-8"))
        if not rule.get("retired"):
            rules.append(rule | {"season": path.parent.name})
    return rules


def add_rule(data_dir, season: str, rule: dict) -> Path:
    """写入一条规则。规则入库后只读，改规则要换 id 算新赛道。"""
    errors = validate_rule(rule)
    if errors:
        raise ValueError("；".join(errors))
    if any(r["id"] == rule["id"] for r in load_rules(data_dir)):
        raise ValueError(f"规则 {rule['id']} 已存在")
    if len(load_rules(data_dir)) >= MAX_TRACKS:
        raise ValueError(f"活跃赛道已到上限 {MAX_TRACKS}")
    path = arena_dir(data_dir) / "rules" / season / f"{rule['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rule, ensure_ascii=False, indent=1) + "\n", "utf-8")
    return path
