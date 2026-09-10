"""Fail-closed runtime identity, mode validation, and local process leases."""
from __future__ import annotations

import errno
import fcntl
import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

from nutmeg.config.settings import (
    AppSettings,
    OperatorRuntimeScope,
    OperatorSurfaceMode,
)
from nutmeg.ontology.actions.models import canonical_json

_FULL_COMMIT = re.compile(r'[0-9a-f]{40}')
_MAX_PROBE_OUTPUT = 65_536
_SOURCE_ROOT = Path(__file__).resolve().parents[2]


class OperatorRuntimeError(RuntimeError):
    """Stable runtime failure safe for a local CLI response."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f'{code}: {message}')
        self.code = code


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    running_commit: str
    dirty: bool
    resolved: bool


@dataclass(frozen=True, slots=True)
class OperatorRuntimeConfig:
    surface_mode: OperatorSurfaceMode
    runtime_scope: OperatorRuntimeScope
    data_dir: Path
    production_data_dir: Path
    running_commit: str

    @property
    def mutations_enabled(self) -> bool:
        return self.surface_mode is OperatorSurfaceMode.ACTIVE


def validate_operator_runtime(
    settings: AppSettings,
    *,
    running_commit: str,
    dirty: bool,
    data_dir_was_explicit: bool = False,
) -> OperatorRuntimeConfig:
    """Validate the closed scope/mode matrix before constructing services."""
    data_dir_input = settings.data_dir
    data_dir = data_dir_input.resolve()
    production_dir = settings.production_data_dir.resolve()
    pair = (settings.operator_runtime_scope, settings.operator_surface_mode)
    legal_pairs = {
        (OperatorRuntimeScope.PRODUCTION, OperatorSurfaceMode.LEGACY_READ_ONLY),
        (OperatorRuntimeScope.PRODUCTION, OperatorSurfaceMode.SHADOW),
        (OperatorRuntimeScope.PRODUCTION, OperatorSurfaceMode.ACTIVE),
        (OperatorRuntimeScope.ISOLATED_CANDIDATE, OperatorSurfaceMode.ACTIVE),
    }
    if pair not in legal_pairs:
        raise ValueError('illegal operator runtime scope/mode')
    if settings.operator_runtime_scope is OperatorRuntimeScope.PRODUCTION:
        if data_dir != production_dir:
            raise ValueError('production data directory must match configured production path')
    else:
        if not data_dir_was_explicit:
            raise ValueError('isolated candidate requires explicit --data-dir')
        if not data_dir_input.is_absolute():
            raise ValueError('isolated candidate data directory must be absolute')
        if data_dir == production_dir:
            raise ValueError('isolated candidate data directory must differ from production')
        if settings.telegram_bot_token or settings.operator_scheduler_enabled:
            raise ValueError('isolated candidate side effects must be disabled')

    if settings.operator_surface_mode is OperatorSurfaceMode.ACTIVE:
        signing_key = settings.operator_token_signing_key
        if signing_key is None or len(signing_key.encode('utf-8')) < 32:
            raise ValueError('operator token signing key must contain at least 32 bytes')

    if pair == (OperatorRuntimeScope.PRODUCTION, OperatorSurfaceMode.ACTIVE):
        commits = (
            settings.operator_accepted_commit,
            settings.candidate_commit,
            running_commit,
        )
        if (
            dirty
            or not all(_FULL_COMMIT.fullmatch(value or '') for value in commits)
            or len(set(commits)) != 1
        ):
            raise ValueError('accepted, candidate, and running commits must match cleanly')

    return OperatorRuntimeConfig(
        surface_mode=settings.operator_surface_mode,
        runtime_scope=settings.operator_runtime_scope,
        data_dir=data_dir,
        production_data_dir=production_dir,
        running_commit=running_commit,
    )


def _default_runner(argv: list[str], **kwargs: object):
    return subprocess.run(argv, **kwargs)  # noqa: S603 - argv is fixed by this module


def probe_source_identity(
    repo_root: Path | None = None,
    *,
    runner: Callable[..., object] = _default_runner,
) -> SourceIdentity:
    """Read the installed checkout identity with fixed argv and fail closed."""
    root = (repo_root or _SOURCE_ROOT).resolve()
    commands = (
        ['git', '-C', str(root), 'rev-parse', '--verify', 'HEAD'],
        [
            'git',
            '-C',
            str(root),
            'status',
            '--porcelain=v1',
            '--untracked-files=normal',
        ],
    )
    outputs: list[str] = []
    try:
        for argv in commands:
            completed = runner(
                argv,
                capture_output=True,
                check=False,
                shell=False,
                timeout=5,
            )
            if getattr(completed, 'returncode', 1) != 0:
                raise ValueError('git probe failed')
            stdout = getattr(completed, 'stdout', b'')
            stderr = getattr(completed, 'stderr', b'')
            if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
                raise ValueError('git probe returned non-byte output')
            if len(stdout) > _MAX_PROBE_OUTPUT or len(stderr) > _MAX_PROBE_OUTPUT:
                raise ValueError('git probe output exceeded limit')
            outputs.append(stdout.decode('ascii'))
        commit = outputs[0].strip()
        if _FULL_COMMIT.fullmatch(commit) is None:
            raise ValueError('git probe returned invalid revision')
        return SourceIdentity(
            running_commit=commit,
            dirty=bool(outputs[1]),
            resolved=True,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
        return SourceIdentity(running_commit='unresolved', dirty=True, resolved=False)


class ApplicationInstanceLease:
    """One live Application owner for a resolved data directory."""

    def __init__(
        self,
        data_dir: Path,
        *,
        host: str,
        port: int,
        pid: int | None = None,
        started_at: datetime | None = None,
    ) -> None:
        self.data_dir = data_dir.resolve()
        self.path = self.data_dir / 'state' / 'operator-app.lock'
        self.host = host
        self.port = port
        self.pid = pid or os.getpid()
        self.started_at = started_at or datetime.now(UTC)
        self._handle = None
        self._record: dict[str, object] | None = None

    def acquire(self) -> ApplicationInstanceLease:
        if self._handle is not None:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        created = False
        try:
            descriptor = os.open(
                self.path,
                os.O_RDWR | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            created = True
        except FileExistsError:
            descriptor = os.open(self.path, os.O_RDWR)
        handle = os.fdopen(descriptor, 'r+', encoding='utf-8')
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            if not created:
                self._validate_stale_record(handle)
            record: dict[str, object] = {
                'bind': self.host,
                'data_dir': str(self.data_dir),
                'lease_state': 'held',
                'pid': self.pid,
                'port': self.port,
                'started_at': self.started_at.astimezone(UTC).isoformat(),
            }
            self._write_record(handle, record)
        except (BlockingIOError, OSError, ValueError, json.JSONDecodeError) as error:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            handle.close()
            raise OperatorRuntimeError(
                'app_instance_conflict',
                'another Application owns this data directory or its owner cannot be verified',
            ) from error
        self._handle = handle
        self._record = record
        return self

    @staticmethod
    def _write_record(handle, record: dict[str, object]) -> None:
        handle.seek(0)
        handle.truncate()
        handle.write(canonical_json(record))
        handle.flush()
        os.fsync(handle.fileno())

    def _validate_stale_record(self, handle) -> None:
        handle.seek(0)
        raw = handle.read(_MAX_PROBE_OUTPUT + 1)
        if not raw or len(raw) > _MAX_PROBE_OUTPUT:
            raise ValueError('invalid owner record')
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError('invalid owner record')
        if document.get('data_dir') != str(self.data_dir):
            raise ValueError('owner data directory mismatch')
        pid = document.get('pid')
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise ValueError('invalid owner pid')
        lease_state = document.get('lease_state')
        if lease_state == 'released':
            released_at = document.get('released_at')
            if not isinstance(released_at, str) or not released_at:
                raise ValueError('invalid release record')
            return
        if lease_state != 'held':
            raise ValueError('invalid lease state')
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError as error:
            raise ValueError('owner process exists') from error
        except OSError as error:
            if error.errno == errno.ESRCH:
                return
            raise ValueError('owner process cannot be verified') from error
        raise ValueError('owner process exists')

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        record = self._record
        self._record = None
        if handle is None:
            return
        try:
            if record is not None:
                released = {
                    **record,
                    'lease_state': 'released',
                    'released_at': datetime.now(UTC).isoformat(),
                }
                self._write_record(handle, released)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def __enter__(self) -> ApplicationInstanceLease:
        return self.acquire()

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.release()


class OntologyWriterLease:
    """Shared normal-writer or exclusive maintenance lease."""

    def __init__(self, data_dir: Path, *, exclusive: bool) -> None:
        self.data_dir = data_dir.resolve()
        self.path = self.data_dir / 'state' / 'ontology-writer.lock'
        self.is_exclusive = exclusive
        self._handle = None

    @classmethod
    def shared(cls, data_dir: Path) -> OntologyWriterLease:
        return cls(data_dir, exclusive=False)

    @classmethod
    def exclusive(cls, data_dir: Path) -> OntologyWriterLease:
        return cls(data_dir, exclusive=True)

    def acquire(self) -> OntologyWriterLease:
        if self._handle is not None:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open('a+', encoding='utf-8')
        mode = fcntl.LOCK_EX if self.is_exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(handle.fileno(), mode | fcntl.LOCK_NB)
        except BlockingIOError as error:
            handle.close()
            raise OperatorRuntimeError(
                'ontology_maintenance_conflict',
                'ontology maintenance overlaps an active writer',
            ) from error
        self._handle = handle
        return self

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()

    def __enter__(self) -> OntologyWriterLease:
        return self.acquire()

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.release()


__all__ = [
    'ApplicationInstanceLease',
    'OntologyWriterLease',
    'OperatorRuntimeConfig',
    'OperatorRuntimeError',
    'OperatorRuntimeScope',
    'OperatorSurfaceMode',
    'SourceIdentity',
    'probe_source_identity',
    'validate_operator_runtime',
]
