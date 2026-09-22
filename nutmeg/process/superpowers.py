"""Superpowers skills presence check (the `workflow` block of `nutmeg doctor`).

2026-09-22: the Spec Kit bridge (`.specify/extensions/superb`, speckit.* hooks and
commands) was retired with the Spec Kit tree; only the skill presence check remains.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

REQUIRED_SKILLS = (
    'test-driven-development',
    'verification-before-completion',
)
OPTIONAL_SKILLS = (
    'systematic-debugging',
    'receiving-code-review',
    'finishing-a-development-branch',
)


@dataclass(slots=True, frozen=True)
class SkillStatus:
    name: str
    required: bool
    source: str
    path: str | None
    status: str


@dataclass(slots=True, frozen=True)
class BridgeReport:
    workspace_root: str
    global_root: str
    skills: list[SkillStatus]
    verdict: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def inspect_superpowers_bridge(
    project_root: Path,
    home_root: Path | None = None,
) -> BridgeReport:
    workspace_root = project_root / '.agents' / 'skills'
    global_root = (home_root or Path.home()) / '.agents' / 'skills'

    skills: list[SkillStatus] = []
    missing_required = False
    missing_optional = False
    for name in (*REQUIRED_SKILLS, *OPTIONAL_SKILLS):
        required = name in REQUIRED_SKILLS
        source = 'missing'
        resolved_path: Path | None = None
        for label, root in (('workspace', workspace_root), ('global', global_root)):
            candidate = root / name / 'SKILL.md'
            if candidate.exists() and candidate.is_file():
                source = label
                resolved_path = candidate
                break
        status = 'READY' if resolved_path else 'MISSING'
        missing_required |= status == 'MISSING' and required
        missing_optional |= status == 'MISSING' and not required
        skills.append(SkillStatus(name, required, source,
                                  str(resolved_path) if resolved_path else None, status))

    if missing_required:
        verdict = 'BLOCKED'
    elif missing_optional:
        verdict = 'DEGRADED'
    else:
        verdict = 'READY'
    return BridgeReport(str(workspace_root), str(global_root), skills, verdict)
