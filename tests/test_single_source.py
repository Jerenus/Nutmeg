"""同一推导只许一处实现（2026-10-08 第二轮瘦身的守卫）。

第二轮瘦身发现同一件事各算一份的地方已经算出分歧：赛果六处（内核比 jc-results 少 27 场）、
channel-map 十处（10-05 修的两个缺口）、去水四处（一份遇 0 赔率除零）。B 波把它们收进下表的
「唯一实现」；这个测试让第七份副本在提交时就失败，而不是等复盘才发现。

范围：`nutmeg/`、`scripts/`、`experiments/` 里所有 import 了 nutmeg 的文件。不 import nutmeg 的脚本
（如 `scripts/jczq_result_backfill.py`）按设计自成一体——包坏了它们照样跑——不在守卫内。
撞上了：改用唯一实现；确有不同契约，在 ALLOWED 里写明理由。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNED = ("nutmeg", "scripts", "experiments")

# 规则名 → (唯一实现所在文件, 该用的名字)
HOMES = {
    "devig": ("nutmeg/data/prices.py", "devig / devig_rounded"),
    "outcome_90": ("nutmeg/decision/match_results.py", "outcome_90"),
    "brier": ("nutmeg/decision/scoring.py", "brier"),
    "read_json": ("nutmeg/decision/files.py", "read_json"),
    "channel_map": ("nutmeg/decision/zucai_identity.py", "load_channel_map"),
    "closing_issues": ("nutmeg/decision/zucai_identity.py", "closing_issues"),
    "beijing_tz": ("nutmeg/decision/bj_time.py", "BJ / aware / parse_bj"),
    "browser_ua": ("nutmeg/data/http.py", "BROWSER_UA / *_HEADERS"),
    "claude_cli": ("nutmeg/decision/claude_models.py", "claude 可执行文件解析"),
}

# 函数名规则：在唯一实现之外定义这些名字＝又写了一份
FUNCTION_NAMES = {
    "devig": {"devig", "_devig", "devig_rounded"},
    "outcome_90": {"outcome_90", "_outcome_90", "_result_code", "result_code"},
    "brier": {"brier", "_brier"},
    "read_json": {"read_json", "_read_json", "_load_json"},
    "channel_map": {"load_channel_map", "_load_channel_map", "_read_channel_map"},
    "closing_issues": {"closing_issues", "_closing_issues", "issues_closing_today"},
}

# 确有不同契约的例外：(规则, 文件) → 理由
ALLOWED = {
    ("brier", "nutmeg/analytics/scoring.py"):
        "内核 calibrate 的分布对分布 Brier（y 是分布），与对一个开出面打分的契约不同",
    ("channel_map", "nutmeg/decision/zucai_prep.py"):
        "备料是写 .auto 表的一方，对齐时只认人工表，不能读自己写出的 .auto",
}

_CHANNEL_MAP_FILE = re.compile(r"channel-map.*\.json")


def _files() -> list[Path]:
    out = []
    for top in SCANNED:
        for path in sorted((ROOT / top).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            out.append(path)
    return out


def _imports_nutmeg(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("nutmeg"):
            return True
        if isinstance(node, ast.Import) and any(a.name.startswith("nutmeg") for a in node.names):
            return True
    return False


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list):
            for stmt in body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                    ids.add(id(stmt.value))
    return ids


def _hits(path: Path, tree: ast.AST) -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    docstrings = _docstring_nodes(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for rule, names in FUNCTION_NAMES.items():
                if node.name in names:
                    hits.append((rule, node.lineno, f"def {node.name}"))
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            args = [a.value for a in node.args if isinstance(a, ast.Constant)]
            if name == "ZoneInfo" and "Asia/Shanghai" in args:
                hits.append(("beijing_tz", node.lineno, 'ZoneInfo("Asia/Shanghai")'))
            if name == "timedelta" and any(
                k.arg == "hours" and isinstance(k.value, ast.Constant) and k.value.value == 8
                for k in node.keywords
            ):
                hits.append(("beijing_tz", node.lineno, "timedelta(hours=8)"))
            if name == "which" and "claude" in args:
                hits.append(("claude_cli", node.lineno, 'which("claude")'))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings:
                continue
            if "Mozilla/5.0" in node.value:
                hits.append(("browser_ua", node.lineno, "Mozilla/5.0 UA literal"))
            if _CHANNEL_MAP_FILE.search(node.value):
                hits.append(("channel_map", node.lineno, f"path literal {node.value!r}"))
    return hits


def test_each_derivation_has_exactly_one_implementation() -> None:
    violations = []
    for path in _files():
        rel = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if not rel.startswith("nutmeg/") and not _imports_nutmeg(tree):
            continue  # 自成一体的脚本，见模块说明
        for rule, line, what in _hits(path, tree):
            home, name = HOMES[rule]
            if rel == home or (rule, rel) in ALLOWED:
                continue
            violations.append(f"{rel}:{line}: {what} — 改用 {home} 的 {name}"
                              "（确属不同契约就在 ALLOWED 写明理由）")
    assert not violations, "同一推导出现第二份实现：\n" + "\n".join(violations)


def test_every_home_still_holds_its_implementation() -> None:
    for rule, (home, _name) in HOMES.items():
        path = ROOT / home
        assert path.is_file(), f"{rule}: 唯一实现文件 {home} 不见了"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert rule in {hit[0] for hit in _hits(path, tree)}, f"{rule}: {home} 里已找不到它的实现"


def test_allowed_exceptions_are_still_needed() -> None:
    """例外表不许变成垃圾场：对应文件里已经没有那条命中了，就把例外删掉。"""
    for rule, rel in ALLOWED:
        path = ROOT / rel
        assert path.is_file(), f"ALLOWED 里的 {rel} 已不存在"
        rules = {hit[0] for hit in _hits(path, ast.parse(path.read_text(encoding="utf-8")))}
        assert rule in rules, f"ALLOWED[{rule}, {rel}] 已无命中，删掉这条例外"


def test_detector_flags_a_reintroduced_copy() -> None:
    source = '''
"""docstring mentioning 1-channel-map.json and Mozilla/5.0 is fine"""
from zoneinfo import ZoneInfo
def devig(odds):
    return odds
BJ = ZoneInfo("Asia/Shanghai")
UA = "Mozilla/5.0 (X11)"
PATH = "26135-channel-map.json"
'''
    rules = {hit[0] for hit in _hits(Path("x.py"), ast.parse(source))}
    assert rules == {"devig", "beijing_tz", "browser_ua", "channel_map"}
