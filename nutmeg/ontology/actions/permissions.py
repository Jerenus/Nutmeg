"""Deny-by-default, database-backed permission guard.

An actor role may execute an action type only when an explicit
``action_permissions`` row exists under an **active** policy version. There is
no fallback to another policy or role, and an unknown or inactive policy denies.
Permissions are read live from the transaction's connection — no caching — so a
future Policy Action becomes visible to the very next transaction.
"""
from __future__ import annotations

from sqlalchemy import Connection, select

from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.errors import PermissionDeniedError
from nutmeg.ontology.repository import schema


class PermissionGuard:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def is_allowed(
        self,
        policy_version_id: str,
        action_type: str,
        actor_role: ActorRole,
    ) -> bool:
        permissions = schema.action_permissions
        policies = schema.policy_versions
        stmt = (
            select(permissions.c.action_type)
            .select_from(
                permissions.join(
                    policies,
                    permissions.c.policy_version_id == policies.c.policy_version_id,
                )
            )
            .where(
                policies.c.policy_version_id == policy_version_id,
                policies.c.status == 'active',
                permissions.c.action_type == action_type,
                permissions.c.actor_role == actor_role.value,
            )
            .limit(1)
        )
        return self._connection.execute(stmt).first() is not None

    def assert_allowed(
        self,
        policy_version_id: str,
        action_type: str,
        actor_role: ActorRole,
    ) -> None:
        if not self.is_allowed(policy_version_id, action_type, actor_role):
            raise PermissionDeniedError(
                f'actor role {actor_role.value} is not allowed to execute '
                f'{action_type} under {policy_version_id}'
            )
