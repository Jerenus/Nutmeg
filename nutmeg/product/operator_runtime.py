"""Local ontology writer leases shared by the CLI and worker lanes."""
from __future__ import annotations

import fcntl
from pathlib import Path
from types import TracebackType


class OperatorRuntimeError(RuntimeError):
    """Stable runtime failure safe for a local CLI response."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f'{code}: {message}')
        self.code = code


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
    'OntologyWriterLease',
    'OperatorRuntimeError',
]
