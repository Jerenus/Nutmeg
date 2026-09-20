"""SQLAlchemy Core table declarations for the ontology kernel.

Package 1 declares only the governance and evidence-kernel tables. Domain
objects (Match/Team/Person/Forecast/Ticket) arrive in later packages against the
same ``MetaData``. Tables are typed relational — no generic object/link/payload
EAV store. Timestamps are stored as ISO-8601 UTC ``TEXT``; JSON columns carry an
application-validated document with its own ``schema_version`` where relevant.
"""
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)

metadata = MetaData()

# Bootstrap table owned by the migration runner itself.
schema_migrations = Table(
    'schema_migrations',
    metadata,
    Column('version', Integer, primary_key=True),
    Column('name', Text, nullable=False),
    Column('checksum', Text, nullable=False),
    Column('applied_at', Text, nullable=False),
)

policy_versions = Table(
    'policy_versions',
    metadata,
    Column('policy_version_id', Text, primary_key=True),
    Column('policy_kind', Text, nullable=False),
    Column('version', Integer, nullable=False),
    Column('payload_json', Text, nullable=False),
    Column('status', Text, nullable=False),
    Column('effective_at', Text, nullable=False),
    Column('created_at', Text, nullable=False),
    UniqueConstraint('policy_kind', 'version', name='uq_policy_versions_kind_version'),
)

actions = Table(
    'actions',
    metadata,
    Column('action_id', Text, primary_key=True),
    Column('action_type', Text, nullable=False, index=True),
    Column('actor_id', Text, nullable=False),
    Column('actor_role', Text, nullable=False, index=True),
    Column('requested_at', Text, nullable=False),
    Column('idempotency_key', Text, nullable=False, unique=True),
    Column('request_hash', Text, nullable=False),
    Column('expected_versions_json', Text, nullable=False, server_default=text("'{}'")),
    Column('payload_json', Text, nullable=False),
    Column(
        'policy_version',
        Text,
        ForeignKey('policy_versions.policy_version_id', ondelete='RESTRICT'),
        nullable=False,
    ),
    Column('status', Text, nullable=False, index=True),
    Column('result_refs_json', Text, nullable=False, server_default=text("'[]'")),
    Column('error_code', Text, nullable=True),
    Column('error_detail', Text, nullable=True),
    Column('committed_at', Text, nullable=True),
    Column(
        'historical_replay',
        Integer,
        nullable=False,
        server_default=text('0'),
    ),
    Column(
        'replay_run_id',
        Text,
        nullable=True,
    ),
    CheckConstraint(
        "(historical_replay = 0 AND replay_run_id IS NULL) OR "
        "(historical_replay = 1 AND replay_run_id IS NOT NULL)",
        name='ck_actions_historical_replay_pair',
    ),
)

action_permissions = Table(
    'action_permissions',
    metadata,
    Column(
        'policy_version_id',
        Text,
        ForeignKey('policy_versions.policy_version_id', ondelete='CASCADE'),
        nullable=False,
    ),
    Column('action_type', Text, nullable=False),
    Column('actor_role', Text, nullable=False),
    PrimaryKeyConstraint('policy_version_id', 'action_type', 'actor_role'),
)

historical_replay_runs = Table(
    'historical_replay_runs',
    metadata,
    Column('replay_run_id', Text, primary_key=True),
    Column('business_date', Text, nullable=False),
    Column('source_root_fingerprint', Text, nullable=False),
    Column('source_manifest_hash', Text, nullable=False),
    Column('isolated_database_identity', Text, nullable=False),
    Column('schema_version', Integer, nullable=False),
    Column('status', Text, nullable=False),
    Column('started_at', Text, nullable=False),
    Column('finished_at', Text, nullable=True),
    Column('production_before_json', Text, nullable=False),
    Column('production_after_json', Text, nullable=True),
    Column('report_sha256', Text, nullable=True),
    Column('failure_codes_json', Text, nullable=False, server_default=text("'[]'")),
    CheckConstraint(
        "status IN ('running', 'accepted', 'failed')",
        name='ck_historical_replay_runs_status',
    ),
    CheckConstraint('schema_version >= 1', name='ck_historical_replay_schema_version'),
    UniqueConstraint(
        'business_date',
        'source_manifest_hash',
        'isolated_database_identity',
        name='uq_historical_replay_identity',
    ),
)

source_runs = Table(
    'source_runs',
    metadata,
    Column('source_run_id', Text, primary_key=True),
    Column('source_name', Text, nullable=False),
    Column('source_type', Text, nullable=False),
    Column('started_at', Text, nullable=False),
    Column('finished_at', Text, nullable=True),
    Column('status', Text, nullable=False),
    Column('error_code', Text, nullable=True),
    Column('error_detail', Text, nullable=True),
)

source_artifacts = Table(
    'source_artifacts',
    metadata,
    Column('artifact_id', Text, primary_key=True),
    Column('first_recorded_at', Text, nullable=False),
    Column('content_type', Text, nullable=False),
    Column('storage_path', Text, nullable=False, unique=True),
    Column('byte_size', Integer, nullable=False),
    Column('content_hash', Text, nullable=False, unique=True),
    CheckConstraint('byte_size >= 0', name='ck_source_artifacts_byte_size'),
)

artifact_retrievals = Table(
    'artifact_retrievals',
    metadata,
    Column('artifact_retrieval_id', Text, primary_key=True),
    Column(
        'artifact_id',
        Text,
        ForeignKey('source_artifacts.artifact_id', ondelete='RESTRICT'),
        nullable=False,
    ),
    Column(
        'source_run_id',
        Text,
        ForeignKey('source_runs.source_run_id', ondelete='RESTRICT'),
        nullable=True,
    ),
    Column('source_name', Text, nullable=False),
    Column('source_type', Text, nullable=False),
    Column('reported_content_type', Text, nullable=False),
    Column('canonical_url', Text, nullable=True),
    Column('requested_url', Text, nullable=True),
    Column('published_at', Text, nullable=True),
    Column('retrieved_at', Text, nullable=False),
    Column('status', Text, nullable=False),
)
