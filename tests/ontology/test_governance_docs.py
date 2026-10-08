"""文档契约：SOP 与 harness 里写到的 `nutmeg …` 命令都存在；两份 harness 的共享指针逐字一致。"""
import re
from pathlib import Path

import click
import typer.main

ROOT = Path(__file__).parents[2]
DOCS = (
    ROOT / "CLAUDE.md",
    ROOT / "AGENTS.md",
    *sorted((ROOT / "docs" / "sop").glob("*.md")),
)
COMMAND = re.compile(r"(?<![\w./-])nutmeg((?:[ \t]+[a-z][a-z0-9-]*)+)")
RETIRED: frozenset[str] = frozenset()
"""文档里明写「已退役」而仍提到的命令（如 `day status`）才进这里；能删提法就删提法。"""
SHARED_POINTER_PREFIXES = (
    "1. `docs/sop/CONSTITUTION.md`",
    "2. `docs/sop/RUNBOOK.md`",
    "3. `docs/sop/RULEBOOK.md`",
    "**记分牌单一事实源**",
    "**出票硬门**",
    '- "今天的 jczq 方案',
    '- "胜负彩 / 任九',
    '- "深度分析 / 混合投注',
)


def _resolve(root: click.Command, tokens: list[str]) -> bool:
    cmd = root
    for token in tokens:
        if not isinstance(cmd, click.Group):
            return True                      # 叶子命令之后是参数
        sub = cmd.commands.get(token)
        if sub is None:
            return False
        cmd = sub
    return True


def test_every_documented_nutmeg_command_resolves_to_a_real_typer_command() -> None:
    from nutmeg.interfaces.cli import app

    root = typer.main.get_command(app)
    seen, unresolved = 0, []
    for path in DOCS:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in COMMAND.finditer(line):
                tokens = match.group(1).split()
                seen += 1
                retired = any(" ".join(tokens[:n]) in RETIRED for n in (1, 2))
                if not retired and not _resolve(root, tokens):
                    where = f"{path.relative_to(ROOT)}:{lineno}"
                    unresolved.append(f"{where}: nutmeg {' '.join(tokens)}")
    assert seen > 50, "命令提取正则失效"
    assert not unresolved, "文档里的命令不存在：\n" + "\n".join(unresolved)


def _line(text: str, prefix: str) -> str:
    hits = [line for line in text.splitlines() if line.startswith(prefix)]
    assert len(hits) == 1, (prefix, len(hits))
    return hits[0]


def test_claude_and_agents_share_the_sop_pointer_word_for_word() -> None:
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for prefix in SHARED_POINTER_PREFIXES:
        assert _line(claude, prefix) == _line(agents, prefix), prefix


def test_scoreboard_single_source_statement_survives_in_the_sop() -> None:
    for name in ("CLAUDE.md", "AGENTS.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "**记分牌单一事实源** = `.nutmeg-data/scoreboard.json`" in text, name
    constitution = (ROOT / "docs/sop/CONSTITUTION.md").read_text(encoding="utf-8")
    assert "记分牌单一事实源 = `.nutmeg-data/scoreboard.json`" in constitution
    rulebook = (ROOT / "docs/sop/RULEBOOK.md").read_text(encoding="utf-8")
    assert "唯一事实源是 `.nutmeg-data/scoreboard.json`" in rulebook


def test_operations_doc_names_non_mutating_status_contract() -> None:
    text = (ROOT / "docs/ontology-kernel-operations.md").read_text(encoding="utf-8")
    assert "uv run nutmeg ontology guarded-init" in text
    assert "uv run nutmeg ontology status --format json" in text
    assert "status never initializes or migrates the database" in text
