"""Transaction boundary for the ontology kernel.

A Unit of Work owns exactly one SQLAlchemy connection and one transaction. It
commits on a clean exit, rolls back on any exception, and always closes the
connection. Repositories are exposed on an *active* Unit of Work so every
business write shares the same transaction as its Action-log row.
"""
from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING

from sqlalchemy import Connection, Engine

if TYPE_CHECKING:
    from nutmeg.ontology.repository.actions import ActionRepository
    from nutmeg.ontology.repository.artifacts import ArtifactRepository
    from nutmeg.ontology.repository.identity import IdentityRepository


class OntologyUnitOfWork:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._connection: Connection | None = None

    @property
    def connection(self) -> Connection:
        if self._connection is None:
            raise RuntimeError('unit of work is not active')
        return self._connection

    @property
    def actions(self) -> ActionRepository:
        from nutmeg.ontology.repository.actions import ActionRepository

        return ActionRepository(self.connection)

    @property
    def artifacts(self) -> ArtifactRepository:
        from nutmeg.ontology.repository.artifacts import ArtifactRepository

        return ArtifactRepository(self.connection)

    @property
    def identity(self) -> IdentityRepository:
        from nutmeg.ontology.repository.identity import IdentityRepository

        return IdentityRepository(self.connection)

    def __enter__(self) -> OntologyUnitOfWork:
        self._connection = self._engine.connect()
        self._connection.begin()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            if exc_type is None:
                connection.commit()
            else:
                connection.rollback()
        finally:
            connection.close()
