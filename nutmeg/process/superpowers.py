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
class HookStatus:
    hook: str
    command: str
    status: str
    reason: str


@dataclass(slots=True, frozen=True)
class CommandStatus:
    command: str
    status: str
    reason: str


@dataclass(slots=True, frozen=True)
class BridgeReport:
    workspace_root: str
    global_root: str
    extension_installed: bool
    skills: list[SkillStatus]
    hooks: list[HookStatus]
    commands: list[CommandStatus]
    verdict: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def inspect_superpowers_bridge(
    project_root: Path,
    home_root: Path | None = None,
) -> BridgeReport:
    workspace_root = project_root / '.agents' / 'skills'
    global_root = (home_root or Path.home()) / '.agents' / 'skills'
    extension_installed = (project_root / '.specify' / 'extensions' / 'superb').exists()

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
        if status == 'MISSING' and required:
            missing_required = True
        if status == 'MISSING' and not required:
            missing_optional = True
        skills.append(
            SkillStatus(
                name=name,
                required=required,
                source=source,
                path=str(resolved_path) if resolved_path else None,
                status=status,
            )
            )

    required_ready = not missing_required and extension_installed
    debug_ready = any(
        skill.name == 'systematic-debugging' and skill.status == 'READY'
        for skill in skills
    )
    respond_ready = any(
        skill.name == 'receiving-code-review' and skill.status == 'READY'
        for skill in skills
    )
    finish_ready = any(
        skill.name == 'finishing-a-development-branch' and skill.status == 'READY'
        for skill in skills
    )

    hooks = [
        HookStatus(
            hook='before_implement',
            command='speckit.superb.tdd',
            status='READY' if required_ready else 'BLOCKED',
            reason=(
                'required skill present'
                if required_ready
                else 'missing required skill or extension'
            ),
        ),
        HookStatus(
            hook='after_implement',
            command='speckit.superb.verify',
            status='READY' if required_ready else 'BLOCKED',
            reason=(
                'required skill present'
                if required_ready
                else 'missing required skill or extension'
            ),
        ),
        HookStatus(
            hook='after_tasks',
            command='speckit.superb.review',
            status='READY' if extension_installed else 'BLOCKED',
            reason=(
                'bridge-native command available'
                if extension_installed
                else 'superpowers bridge extension missing'
            ),
        ),
    ]

    commands = [
        CommandStatus(
            command='speckit.superb.debug',
            status='READY' if debug_ready else 'UNAVAILABLE',
            reason=(
                'optional debugging skill installed'
                if debug_ready
                else 'systematic-debugging missing'
            ),
        ),
        CommandStatus(
            command='speckit.superb.respond',
            status='READY' if respond_ready else 'UNAVAILABLE',
            reason=(
                'optional review-response skill installed'
                if respond_ready
                else 'receiving-code-review missing'
            ),
        ),
        CommandStatus(
            command='speckit.superb.finish',
            status='READY' if finish_ready else 'UNAVAILABLE',
            reason=(
                'optional branch-finish skill installed'
                if finish_ready
                else 'finishing-a-development-branch missing'
            ),
        ),
        CommandStatus(
            command='speckit.superb.critique',
            status='READY' if extension_installed else 'BLOCKED',
            reason=(
                'bridge-native command available'
                if extension_installed
                else 'superpowers bridge extension missing'
            ),
        ),
    ]

    if not extension_installed or missing_required:
        verdict = 'BLOCKED'
    elif missing_optional:
        verdict = 'PARTIAL'
    else:
        verdict = 'READY'

    return BridgeReport(
        workspace_root=str(workspace_root),
        global_root=str(global_root),
        extension_installed=extension_installed,
        skills=skills,
        hooks=hooks,
        commands=commands,
        verdict=verdict,
    )
