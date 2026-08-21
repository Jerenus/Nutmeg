# Research Knowledge Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give GPT/Codex and Claude one enforced, auditable catalog for discovering Nutmeg league, team, fixture and correction research across sessions.

**Architecture:** `docs/research/INDEX.md` is the only archive catalog. Identical marked blocks in `AGENTS.md` and `CLAUDE.md` route both harnesses to it, while a focused pytest contract verifies harness parity, complete archive registration, valid links and required correction semantics.

**Tech Stack:** Markdown, pytest, pathlib, regular expressions, pre-commit

---

## Operational Constraint

The root worktree already contains user-owned edits in `AGENTS.md` and `CLAUDE.md`, and the research archives being indexed are untracked there. Implementation therefore stays in the project root and adds only a small top-of-file block to each harness. Do not stage or commit unrelated harness hunks. No subagent is used because the repository contract for this session disallows unrequested delegation and the user selected inline completion.

## File Structure

- Create `docs/research/INDEX.md`: single research discovery catalog and maintenance contract.
- Create `tests/decision/test_research_index.py`: permanent parity, coverage, link and semantics checks.
- Modify `AGENTS.md`: add the GPT/Codex research-index discovery block after the current-plan block.
- Modify `CLAUDE.md`: add the identical Claude discovery block after the current-plan block.
- Modify `.pre-commit-config.yaml`: run the focused contract whenever an indexed archive, harness or test changes.

### Task 1: Write the failing discovery contract

**Files:**
- Create: `tests/decision/test_research_index.py`

- [ ] **Step 1: Add the complete contract test**

```python
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
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
uv run pytest tests/decision/test_research_index.py -q
```

Expected: failures because `docs/research/INDEX.md` and both marked harness blocks do not exist.

### Task 2: Create the single research catalog

**Files:**
- Create: `docs/research/INDEX.md`

- [ ] **Step 1: Add the usage and authority contract**

The opening must state that league, team, fixture, transfer, availability, cohesion and correction work reads this file before answering or mutating entity knowledge. It must list this authority order verbatim in meaning:

```text
1. live decision store and current canonical Match/Snapshot
2. newer official or primary-source evidence for the current window
3. nutmeg/data/decision_entities_seed.json
4. active indexed research archives
5. superseded or historical research
6. chat memory
```

It must also state that the index is a discovery layer, not a competing entity store.

- [ ] **Step 2: Register the active ontology archives**

Add a table with date, coverage, status, primary use and refresh trigger for:

```text
2026-08-20-la-liga-ligue-2-eerste-divisie-ontology-intelligence.md
2026-08-20-serie-a-bundesliga-bundesliga2-ontology-intelligence.md
```

Both use status `active`. Their refresh triggers are transfer-window closure, official lineup evidence, named availability changes and newly verified corrections.

- [ ] **Step 3: Register preparation queues and fixture research**

Add `time-bounded` entries for:

```text
2026-08-20-premier-league-mw1-intelligence.md
2026-08-20-la-liga-ligue-2-eerste-divisie-seven-day-prep-queue.md
2026-08-20-three-priority-fixtures-deep-read.md
```

Add `historical` entries for:

```text
2026-08-20-rayo-alaves-cross-channel-deep-read.md
2026-06-20-tunisia-vs-japan.md
```

Each row must explain that current injury, lineup and market facts need refresh before reuse.

- [ ] **Step 4: Add correction and registration rules**

Define all four statuses and the following rules:

```text
small correction -> update archive with dated correction note and evidence
material replacement -> create new dated archive, mark old entry superseded, cross-link
expired queue/deep read -> historical, never current availability or market evidence
structured Team/League correction -> decision-profile then decision-entities-sync --write-seed
new docs/research/*.md -> register here before completion
```

### Task 3: Wire both model harnesses and the permanent check

**Files:**
- Modify: `AGENTS.md` immediately after `<!-- SPECKIT END -->`
- Modify: `CLAUDE.md` immediately after `<!-- SPECKIT END -->`
- Modify: `.pre-commit-config.yaml`

- [ ] **Step 1: Insert the identical marked block in both harnesses**

```text
<!-- RESEARCH INDEX START -->
For league, team, fixture, transfer, availability, cohesion, or correction work,
read `docs/research/INDEX.md` before answering or mutating entity knowledge. Follow
its authority order and supersession rules; do not rely on chat memory as the
knowledge source.
<!-- RESEARCH INDEX END -->
```

Do not alter either current-plan block or any JCZQ rule text.

- [ ] **Step 2: Add the focused pre-commit hook**

Append this hook under the existing local hooks:

```yaml
      - id: pytest-research-index
        name: pytest (research index contract when touched)
        entry: bash -c 'uv run pytest tests/decision/test_research_index.py -q'
        language: system
        files: ^(AGENTS\.md|CLAUDE\.md|docs/research/.*\.md|tests/decision/test_research_index\.py)$
        pass_filenames: false
```

- [ ] **Step 3: Run the focused test and verify GREEN**

Run:

```bash
uv run pytest tests/decision/test_research_index.py -q
uv run pre-commit run pytest-research-index --all-files
```

Expected: 4 tests pass and the focused hook passes.

### Task 4: Verify adjacent behavior and inspect the exact delivery

**Files:**
- Verify: `docs/research/INDEX.md`
- Verify: `AGENTS.md`
- Verify: `CLAUDE.md`
- Verify: `.pre-commit-config.yaml`
- Verify: `tests/decision/test_research_index.py`

- [ ] **Step 1: Run adjacent decision regressions**

```bash
uv run pytest tests/decision/test_research_index.py \
  tests/decision/test_entities.py \
  tests/decision/test_alias_audit.py \
  tests/decision/test_read_validate.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Verify harness parity and complete catalog coverage independently**

```bash
uv run python - <<'PY'
from pathlib import Path

root = Path('.')
start = '<!-- RESEARCH INDEX START -->'
end = '<!-- RESEARCH INDEX END -->'
blocks = []
for name in ('AGENTS.md', 'CLAUDE.md'):
    text = (root / name).read_text(encoding='utf-8')
    blocks.append(text.split(start, 1)[1].split(end, 1)[0].strip())
assert blocks[0] == blocks[1]
index = (root / 'docs/research/INDEX.md').read_text(encoding='utf-8')
archives = [p for p in (root / 'docs/research').glob('*.md') if p.name != 'INDEX.md']
assert all(f']({p.name})' in index for p in archives)
print(f'harness_parity=yes indexed_archives={len(archives)}')
PY
```

Expected: `harness_parity=yes indexed_archives=7`.

- [ ] **Step 3: Verify formatting and no betting-side effects**

```bash
git diff --check -- AGENTS.md CLAUDE.md .pre-commit-config.yaml \
  docs/research/INDEX.md tests/decision/test_research_index.py
find .nutmeg-data/jczq/daily -type f -newermt '2026-08-21 00:00:00' \
  \( -name 'legs.json' -o -name '*ticket*.json' \) -print
git status --short
```

Expected: no whitespace errors; this task creates no legs or Ticket files. Existing unrelated dirty paths remain untouched.

- [ ] **Step 4: Commit only safely isolated implementation paths if possible**

Always inspect staged content first:

```bash
git diff --cached --check
git diff --cached --stat
```

The new index, test and pre-commit hook may be committed normally. `AGENTS.md` and `CLAUDE.md` may only be included if the staged diff contains the new research-index block and no pre-existing user-owned hunks. If safe partial staging cannot be proven, leave the implementation uncommitted and report that constraint rather than absorbing unrelated changes.
