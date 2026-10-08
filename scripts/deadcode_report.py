"""死代码周报（2026-10-08，Jun：「做成每周一份报告，只报告、不拦截」）。

两轮瘦身（10-03 审计 −49%、10-08 第二轮 −18%）删的大头都是早就没人走的代码，
攒到上千行才被看见。这份周报每周一把候选列出来，在它们变成一座山之前处理：

1. 模块级可达性：从现役入口（`nutmeg.interfaces.cli`，以及 `scripts/`、`experiments/`
   下每个脚本）沿静态 import 图（含函数内的延迟导入与 `importlib.import_module("常量")`）
   走一遍，走不到的 `nutmeg` 模块＝死模块。
2. 名字级引用：可达模块里定义的函数 / 类 / 方法，名字在生产代码（`nutmeg/` `scripts/`
   `experiments/`、launchd plist、网页模板与脚本）里一次都没出现＝无引用；
   只在 `tests/` 出现＝只有测试在用。

按名字匹配是保守的近似：同名的另一个函数在用就算有引用（会漏报，不误报）；
被装饰器注册的函数（Typer 命令、FastAPI 路由、gym 策略）本身就是入口，不列。
候选≠一定该删——删之前照 2026-10-03 审计 §7 的做法 grep 延迟导入与字符串派发，
再跑全量测试与 `/verify`。
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT_MODULE = "nutmeg.interfaces.cli"
PLAIN_DECORATORS = {"staticmethod", "classmethod", "property", "cached_property", "lru_cache",
                    "cache", "dataclass", "abstractmethod", "override"}
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _module_name(path: Path, repo: Path) -> str:
    parts = list(path.relative_to(repo).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _imported(tree: ast.AST, known: set[str]) -> set[str]:
    """Every `nutmeg` module this file imports, at any nesting depth."""
    out: set[str] = set()

    def add(name: str) -> None:
        while name:
            if name in known:
                out.add(name)
            name = name.rpartition(".")[0]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            add(node.module)
            for alias in node.names:
                add(f"{node.module}.{alias.name}")
        elif (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "import_module"
              and node.args and isinstance(node.args[0], ast.Constant)
              and isinstance(node.args[0].value, str)):
            add(node.args[0].value)
    return out


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):  # Lambda / IfExp bodies are expressions
            continue
        for stmt in body:
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                ids.add(id(stmt.value))
    return ids


def _references(tree: ast.AST) -> set[str]:
    """Identifiers a file uses: names, attributes, imported names, words in non-doc strings."""
    docs = _docstring_ids(tree)
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docs:
                out.update(_IDENT.findall(node.value))
    return out


def _decorator_name(node: ast.expr) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute):
        return target.attr
    return getattr(target, "id", "")


def _definitions(tree: ast.AST) -> list[tuple[str, int, int]]:
    """(name, line, length) of module-level functions / classes and their methods."""
    out = []

    def visit(body, *, in_class: bool) -> None:
        for node in body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            name = node.name
            registered = any(_decorator_name(d) not in PLAIN_DECORATORS
                             for d in node.decorator_list)
            if not registered and not (name.startswith("__") and name.endswith("__")):
                if not (in_class and name.startswith("test")):
                    length = (node.end_lineno or node.lineno) - node.lineno + 1
                    out.append((name, node.lineno, length))
            if isinstance(node, ast.ClassDef):
                visit(node.body, in_class=True)

    visit(getattr(tree, "body", []), in_class=False)
    return out


def analyze(repo: Path = REPO) -> dict:
    package = repo / "nutmeg"
    modules = {_module_name(p, repo): p for p in package.rglob("*.py")
               if "__pycache__" not in p.parts}
    trees = {name: _parse(path) for name, path in modules.items()}
    known = set(modules)

    entry_files = [p for top in ("scripts", "experiments") for p in (repo / top).rglob("*.py")
                   if "__pycache__" not in p.parts]
    entry_trees = [t for t in (_parse(p) for p in entry_files) if t is not None]

    reachable: set[str] = set()
    frontier = {ROOT_MODULE} | {m for t in entry_trees for m in _imported(t, known)}
    while frontier:
        name = frontier.pop()
        if name in reachable or name not in known:
            continue
        reachable.add(name)
        parent = name.rpartition(".")[0]
        if parent:
            frontier.add(parent)  # importing a.b executes a/__init__
        tree = trees.get(name)
        if tree is not None:
            frontier |= _imported(tree, known) - reachable
    unreachable = sorted(
        m for m in known - reachable
        # 空 __init__ 只是给模板 / 静态文件目录占位，不是代码
        if trees.get(m) is not None and modules[m].read_text(encoding="utf-8").strip()
    )

    prod_refs: set[str] = set()
    for tree in [*(t for m, t in trees.items() if m in reachable and t is not None), *entry_trees]:
        prod_refs |= _references(tree)
    for pattern in ("ops/launchd/*.plist", "nutmeg/interfaces/web/**/*.html",
                    "nutmeg/interfaces/web/**/*.js"):
        for path in repo.glob(pattern):
            prod_refs.update(_IDENT.findall(path.read_text(encoding="utf-8", errors="ignore")))
    test_refs: set[str] = set()
    for path in (repo / "tests").rglob("*.py"):
        tree = _parse(path)
        if tree is not None:
            test_refs |= _references(tree)

    noref, testonly = [], []
    for name in sorted(reachable):
        tree = trees.get(name)
        if tree is None:
            continue
        rel = modules[name].relative_to(repo).as_posix()
        for symbol, line, length in _definitions(tree):
            if symbol in prod_refs:
                continue
            row = {"file": rel, "line": line, "name": symbol, "lines": length}
            (testonly if symbol in test_refs else noref).append(row)
    return {
        "unreachable_modules": [
            {"module": m, "file": modules[m].relative_to(repo).as_posix(),
             "lines": len(modules[m].read_text(encoding="utf-8").splitlines())}
            for m in unreachable
        ],
        "noref": noref,
        "testonly": testonly,
    }


def summarize(result: dict) -> dict:
    rows = [*result["unreachable_modules"], *result["noref"], *result["testonly"]]
    return {"candidates": len(rows), "lines": sum(r["lines"] for r in rows),
            "unreachable_modules": len(result["unreachable_modules"]),
            "noref": len(result["noref"]), "testonly": len(result["testonly"])}


def render(result: dict, day: str, previous: dict | None) -> str:
    s = summarize(result)
    trend = ""
    if previous:
        trend = (f"（上次 {previous.get('day')}：{previous.get('candidates')} 个 / "
                 f"{previous.get('lines')} 行）")
    out = [f"# 死代码周报 {day}", "",
           f"**候选 {s['candidates']} 个，约 {s['lines']} 行**{trend}："
           f"死模块 {s['unreachable_modules']}、无引用 {s['noref']}、"
           f"只有测试在用 {s['testonly']}。", "",
           "> 候选≠一定该删：删之前 grep 延迟导入、字符串派发、模板，"
           "再跑全量测试与 `/verify`。", ""]
    sections = (("死模块（从现役入口走不到）", result["unreachable_modules"],
                 lambda r: f"- `{r['file']}`（{r['lines']} 行）"),
                ("无引用（生产代码里一次都没出现）", result["noref"],
                 lambda r: f"- `{r['file']}:{r['line']}` `{r['name']}`（{r['lines']} 行）"),
                ("只有测试在用", result["testonly"],
                 lambda r: f"- `{r['file']}:{r['line']}` `{r['name']}`（{r['lines']} 行）"))
    for title, rows, fmt in sections:
        out += [f"## {title}：{len(rows)}", ""]
        out += [fmt(r) for r in sorted(rows, key=lambda r: -r["lines"])] or ["（无）"]
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--out", type=Path,
                        default=REPO / ".nutmeg-data" / "analytics" / "deadcode")
    parser.add_argument("--day", default=date.today().isoformat())
    args = parser.parse_args(argv)

    result = analyze(args.repo)
    latest = args.out / "latest.json"
    try:
        previous = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = None
    args.out.mkdir(parents=True, exist_ok=True)
    report = args.out / f"{args.day}.md"
    report.write_text(render(result, args.day, previous), encoding="utf-8")
    summary = {"day": args.day, "report": report.name, **summarize(result)}
    latest.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"deadcode {args.day}: {summary['candidates']} 个候选 / "
          f"{summary['lines']} 行 → {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
