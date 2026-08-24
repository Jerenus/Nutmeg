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
    from nutmeg.ontology.repository.context import ContextRepository
    from nutmeg.ontology.repository.decision import DecisionRepository
    from nutmeg.ontology.repository.evidence import EvidenceRepository
    from nutmeg.ontology.repository.finance import FinanceRepository
    from nutmeg.ontology.repository.identity import IdentityRepository
    from nutmeg.ontology.repository.market import MarketRepository
    from nutmeg.ontology.repository.outbox import OutboxRepository
    from nutmeg.ontology.repository.scoreboard import ScoreboardRepository
    from nutmeg.ontology.repository.tickets import TicketWorkbenchRepository
    from nutmeg.ontology.repository.workflow import WorkflowRepository


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

    @property
    def market(self) -> MarketRepository:
        from nutmeg.ontology.repository.market import MarketRepository

        return MarketRepository(self.connection)

    @property
    def context(self) -> ContextRepository:
        from nutmeg.ontology.repository.context import ContextRepository

        return ContextRepository(self.connection)

    @property
    def evidence(self) -> EvidenceRepository:
        from nutmeg.ontology.repository.evidence import EvidenceRepository

        return EvidenceRepository(self.connection)

    @property
    def decision(self) -> DecisionRepository:
        from nutmeg.ontology.repository.decision import DecisionRepository

        return DecisionRepository(self.connection)

    @property
    def finance(self) -> FinanceRepository:
        from nutmeg.ontology.repository.finance import FinanceRepository

        return FinanceRepository(self.connection)

    @property
    def workflow(self) -> WorkflowRepository:
        from nutmeg.ontology.repository.workflow import WorkflowRepository

        return WorkflowRepository(self.connection)

    @property
    def outbox(self) -> OutboxRepository:
        from nutmeg.ontology.repository.outbox import OutboxRepository

        return OutboxRepository(self.connection)

    @property
    def tickets(self) -> TicketWorkbenchRepository:
        from nutmeg.ontology.repository.tickets import TicketWorkbenchRepository

        return TicketWorkbenchRepository(self.connection)

    @property
    def scoreboard(self) -> ScoreboardRepository:
        from nutmeg.ontology.repository.scoreboard import ScoreboardRepository

        return ScoreboardRepository(self.connection)

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
