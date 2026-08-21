from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
RESEARCH_DIR = ROOT / "docs" / "research"
INDEX = RESEARCH_DIR / "INDEX.md"
START = "<!-- RESEARCH INDEX START -->"
END = "<!-- RESEARCH INDEX END -->"


def _harness_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert text.count(START) == 1
    assert text.count(END) == 1
    return text.split(START, 1)[1].split(END, 1)[0].strip()


def test_gpt_and_claude_share_one_research_discovery_contract() -> None:
    agents = _harness_block(ROOT / "AGENTS.md")
    claude = _harness_block(ROOT / "CLAUDE.md")
    assert agents == claude
    assert "docs/research/INDEX.md" in agents


def test_index_registers_every_research_archive() -> None:
    text = INDEX.read_text(encoding="utf-8")
    archives = sorted(
        path for path in RESEARCH_DIR.glob("*.md") if path.name != INDEX.name
    )
    assert archives
    for archive in archives:
        assert f"]({archive.name})" in text, archive.name


def test_index_local_markdown_links_resolve() -> None:
    text = INDEX.read_text(encoding="utf-8")
    targets = re.findall(r"\[[^]]+\]\(([^)]+\.md)\)", text)
    assert targets
    for target in targets:
        assert (INDEX.parent / target).resolve().is_file(), target


def test_index_defines_authority_status_and_correction_contracts() -> None:
    text = INDEX.read_text(encoding="utf-8")
    for required in (
        "live decision store",
        "`active`",
        "`time-bounded`",
        "`historical`",
        "`superseded`",
        "decision-profile",
        "decision-entities-sync",
        "chat memory",
    ):
        assert required in text
