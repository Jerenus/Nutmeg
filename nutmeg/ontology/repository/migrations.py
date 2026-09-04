"""Explicit, numbered schema migrations with drift detection.

Migrations are ordinary Python callables carrying a stable ``fingerprint``. The
runner records a SHA-256 checksum of ``version:name:fingerprint`` per applied
migration and refuses to run again if a previously applied migration's checksum
changed — a change to already-shipped DDL is a drift bug, not a silent upgrade.
Each migration's schema/data change and its ``schema_migrations`` row commit in
one transaction, so a partially applied migration cannot survive a crash.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Connection, Engine, delete, func, insert, inspect, select

from nutmeg.ontology.errors import MigrationDriftError
from nutmeg.ontology.identity.models import EntityType, TeamKind, mint_id
from nutmeg.ontology.repository import (
    schema,
    schema_context,
    schema_decision,
    schema_evidence,
    schema_finance,
    schema_identity,
    schema_market,
    schema_operator_decision,
    schema_operator_result,
    schema_operator_sale,
    schema_reliability,
    schema_scoreboard,
    schema_tickets,
    schema_workflow,
)


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    fingerprint: str
    apply: Callable[[Connection], None]

    @property
    def checksum(self) -> str:
        material = f'{self.version}:{self.name}:{self.fingerprint}'
        return hashlib.sha256(material.encode('utf-8')).hexdigest()


@dataclass(frozen=True, slots=True)
class MigrationReport:
    applied_versions: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class MigrationStatus:
    current_version: int
    applied_versions: tuple[int, ...]


def _canonical_json(document: dict[str, object]) -> str:
    return json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _apply_governance_kernel(connection: Connection) -> None:
    # Foreign-key order: policy_versions before actions/action_permissions.
    schema.policy_versions.create(connection)
    schema.actions.create(connection)
    schema.action_permissions.create(connection)

    now = datetime.now(UTC).isoformat()
    connection.execute(
        insert(schema.policy_versions).values(
            policy_version_id='governance-v1',
            policy_kind='governance',
            version=1,
            payload_json=_canonical_json({'name': 'kernel-default'}),
            status='active',
            effective_at=now,
            created_at=now,
        )
    )
    # Seed after all three tables exist so action_permissions FK resolves.
    permissions = (
        ('ingest_artifact', 'connector'),
        ('ingest_artifact', 'judge_operator'),
        ('change_policy', 'judge_operator'),
    )
    connection.execute(
        insert(schema.action_permissions),
        [
            {
                'policy_version_id': 'governance-v1',
                'action_type': action_type,
                'actor_role': actor_role,
            }
            for action_type, actor_role in permissions
        ],
    )


def _apply_evidence_kernel(connection: Connection) -> None:
    # Foreign-key order: source_runs + source_artifacts before artifact_retrievals.
    schema.source_runs.create(connection)
    schema.source_artifacts.create(connection)
    schema.artifact_retrievals.create(connection)


def _load_team_alias_seed() -> dict[tuple[str, str], set[str]]:
    """Curated `{chinese_alias: english_canonical}` files -> {(canonical, kind): aliases}."""
    root = Path(__file__).resolve().parents[2] / 'data'
    seed: dict[tuple[str, str], set[str]] = {}
    for filename, kind in (
        ('jczq_club_team_aliases.json', TeamKind.CLUB.value),
        ('jczq_national_team_aliases.json', TeamKind.NATIONAL.value),
    ):
        raw = json.loads((root / filename).read_text(encoding='utf-8'))
        for alias, canonical in raw.items():
            if alias == '_comment' or not isinstance(canonical, str):
                continue
            aliases = seed.setdefault((canonical, kind), set())
            aliases.add(alias.strip().casefold())
            aliases.add(canonical.strip().casefold())
    return seed


_IDENTITY_ACTION_PERMISSIONS = (
    ('upsert_provisional_entity', 'connector'),
    ('upsert_provisional_entity', 'deterministic_system'),
    ('link_external_identifier', 'connector'),
    ('link_external_identifier', 'deterministic_system'),
    ('propose_identity_link', 'connector'),
    ('propose_identity_link', 'ai_extractor'),
    ('merge_entity', 'judge_operator'),
    ('record_match', 'connector'),
    ('record_match', 'deterministic_system'),
)


def _apply_football_identity(connection: Connection) -> None:
    # Foreign-key order.
    for table in (
        schema_identity.competitions,
        schema_identity.competition_editions,
        schema_identity.teams,
        schema_identity.venues,
        schema_identity.matches,
        schema_identity.match_revisions,
        schema_identity.team_appearances,
        schema_identity.external_identifiers,
        schema_identity.entity_aliases,
        schema_identity.entity_merges,
    ):
        table.create(connection)

    now = datetime.now(UTC).isoformat()
    team_rows: list[dict[str, object]] = []
    alias_rows: list[dict[str, object]] = []
    for (canonical, kind), aliases in _load_team_alias_seed().items():
        team_id = mint_id(EntityType.TEAM)
        team_rows.append({
            'team_id': team_id, 'team_kind': kind, 'canonical_name': canonical,
            'country': None, 'resolution_status': 'provisional', 'created_at': now,
        })
        for alias in sorted(aliases):
            alias_rows.append({
                'entity_id': team_id, 'entity_type': EntityType.TEAM.value,
                'normalized_alias': alias, 'language': None, 'provider': None,
            })
    if team_rows:
        connection.execute(insert(schema_identity.teams), team_rows)
    if alias_rows:
        connection.execute(insert(schema_identity.entity_aliases), alias_rows)

    connection.execute(
        insert(schema.action_permissions),
        [
            {
                'policy_version_id': 'governance-v1',
                'action_type': action_type,
                'actor_role': actor_role,
            }
            for action_type, actor_role in _IDENTITY_ACTION_PERMISSIONS
        ],
    )


_CRS_SELECTIONS: list[tuple[str, str, str | None]] = [
    (f'sel-crs-{home}-{away}', f'{home}:{away}', None)
    for home in range(4)
    for away in range(4)
] + [('sel-crs-other', 'other', None)]

_MARKET_SEED: dict[str, dict[str, object]] = {
    'md-had': {
        'market_kind': 'had', 'settlement_scope': 'regular_time', 'ordered': 0, 'line_schema': None,
        'selections': [
            ('sel-had-home', 'home', None),
            ('sel-had-draw', 'draw', None),
            ('sel-had-away', 'away', None),
        ],
    },
    'md-hhad': {
        'market_kind': 'hhad', 'settlement_scope': 'regular_time', 'ordered': 0,
        'line_schema': 'integer_handicap',
        'selections': [
            ('sel-hhad-home', 'home', None),
            ('sel-hhad-draw', 'draw', None),
            ('sel-hhad-away', 'away', None),
        ],
    },
    'md-ttg': {
        'market_kind': 'ttg', 'settlement_scope': 'regular_time', 'ordered': 1, 'line_schema': None,
        'selections': [(f'sel-ttg-{n}', f'total_{n}', None) for n in range(8)],
    },
    'md-crs': {
        'market_kind': 'crs', 'settlement_scope': 'regular_time', 'ordered': 0, 'line_schema': None,
        'selections': _CRS_SELECTIONS,
    },
}

_MARKET_ACTION_PERMISSIONS = (
    ('record_market_quote', 'connector'),
    ('build_market_snapshot', 'deterministic_system'),
)


def _apply_market(connection: Connection) -> None:
    for table in (
        schema_market.market_definitions,
        schema_market.selection_definitions,
        schema_market.market_quotes,
        schema_market.market_snapshots,
        schema_market.market_snapshot_quotes,
    ):
        table.create(connection)

    for market_definition_id, spec in _MARKET_SEED.items():
        connection.execute(
            insert(schema_market.market_definitions).values(
                market_definition_id=market_definition_id,
                market_kind=spec['market_kind'],
                settlement_scope=spec['settlement_scope'],
                ordered=spec['ordered'],
                line_schema=spec['line_schema'],
                outcome_schema_version='1',
            )
        )
        connection.execute(
            insert(schema_market.selection_definitions),
            [
                {
                    'selection_id': selection_id,
                    'market_definition_id': market_definition_id,
                    'outcome_key': outcome_key,
                    'line': line,
                }
                for selection_id, outcome_key, line in spec['selections']
            ],
        )

    connection.execute(
        insert(schema.action_permissions),
        [
            {
                'policy_version_id': 'governance-v1',
                'action_type': action_type,
                'actor_role': actor_role,
            }
            for action_type, actor_role in _MARKET_ACTION_PERMISSIONS
        ],
    )


def _apply_context(connection: Connection) -> None:
    for table in (
        schema_context.persons,
        schema_context.role_assignments,
        schema_context.person_match_statuses,
        schema_context.lineup_entries,
    ):
        table.create(connection)


# Graded write-back (design §2.4): AI extractors write only provisional claims and
# can never record a verified fact or adjudicate one.
_EVIDENCE_ACTION_PERMISSIONS = (
    ('upsert_person', 'connector'),
    ('upsert_person', 'deterministic_system'),
    ('record_observation', 'connector'),
    ('record_observation', 'deterministic_system'),
    ('record_person_match_status', 'connector'),
    ('record_person_match_status', 'deterministic_system'),
    ('record_lineup_entry', 'connector'),
    ('record_lineup_entry', 'deterministic_system'),
    ('extract_claim', 'ai_extractor'),
    ('verify_claim', 'deterministic_system'),
    ('verify_claim', 'judge_operator'),
    ('dispute_claim', 'judge_operator'),
    ('retract_claim', 'judge_operator'),
)


def _apply_evidence(connection: Connection) -> None:
    for table in (
        schema_evidence.claims,
        schema_evidence.claim_status_events,
        schema_evidence.claim_evidence_spans,
        schema_evidence.observations,
        schema_evidence.observation_sources,
        schema_evidence.observation_claims,
    ):
        table.create(connection)

    connection.execute(
        insert(schema.action_permissions),
        [
            {
                'policy_version_id': 'governance-v1',
                'action_type': action_type,
                'actor_role': actor_role,
            }
            for action_type, actor_role in _EVIDENCE_ACTION_PERMISSIONS
        ],
    )


_DECISION_ACTION_PERMISSIONS = (
    ('open_decision_session', 'judge_operator'),
    ('open_decision_session', 'deterministic_system'),
    ('freeze_evidence_bundle', 'deterministic_system'),
    ('draft_forecast', 'ai_analyst'),
    ('draft_forecast', 'judge_operator'),
    ('commit_forecast', 'judge_operator'),
    ('revise_forecast', 'judge_operator'),
    ('withdraw_forecast', 'judge_operator'),
    ('propose_factor_status', 'ai_analyst'),
    ('propose_factor_status', 'judge_operator'),
    ('apply_factor_status', 'judge_operator'),
)


def _apply_decision(connection: Connection) -> None:
    for table in (
        schema_decision.decision_sessions,
        schema_decision.evidence_bundles,
        schema_decision.evidence_bundle_items,
        schema_decision.forecast_series,
        schema_decision.factor_families,
        schema_decision.factor_definitions,
        schema_decision.forecast_revisions,
        schema_decision.factor_applications,
        schema_decision.scenarios,
    ):
        table.create(connection)

    connection.execute(
        insert(schema.action_permissions),
        [
            {
                'policy_version_id': 'governance-v1',
                'action_type': action_type,
                'actor_role': actor_role,
            }
            for action_type, actor_role in _DECISION_ACTION_PERMISSIONS
        ],
    )


_FINANCE_ACTION_PERMISSIONS = (
    ('change_budget_policy', 'judge_operator'),
    ('propose_ticket', 'ai_analyst'),
    ('propose_ticket', 'judge_operator'),
    ('approve_ticket', 'judge_operator'),
    ('record_cash_transaction', 'deterministic_system'),
    ('record_cash_transaction', 'judge_operator'),
    ('record_outcome', 'deterministic_system'),
    ('correct_outcome', 'deterministic_system'),
    ('settle_ticket', 'deterministic_system'),
)


def _apply_finance(connection: Connection) -> None:
    for table in (
        schema_finance.cash_accounts,
        schema_finance.budget_policies,
        schema_finance.ticket_proposals,
        schema_finance.tickets,
        schema_finance.bet_legs,
        schema_finance.cash_transactions,
        schema_finance.match_outcomes,
        schema_finance.bet_leg_settlements,
        schema_finance.ticket_settlements,
    ):
        table.create(connection)

    connection.execute(
        insert(schema.action_permissions),
        [
            {
                'policy_version_id': 'governance-v1',
                'action_type': action_type,
                'actor_role': actor_role,
            }
            for action_type, actor_role in _FINANCE_ACTION_PERMISSIONS
        ],
    )


def _apply_finance_entry_odds(connection: Connection) -> None:
    """Add ``bet_legs.entry_odds`` (booking-time decimal odds — the settlement price).

    Fresh databases already get the column from migration 8's ``table.create`` (the
    Table definition carries it), so this ALTER is guarded by a PRAGMA check and only
    fires when upgrading a store created before this migration.
    """
    columns = {
        row[1] for row in connection.exec_driver_sql('PRAGMA table_info(bet_legs)').fetchall()
    }
    if 'entry_odds' not in columns:
        connection.exec_driver_sql('ALTER TABLE bet_legs ADD COLUMN entry_odds REAL')


_WORKFLOW_ACTION_PERMISSIONS = (
    ('record_adjudication', 'judge_operator'),
    ('record_flag_instance', 'judge_operator'),
    ('record_flag_instance', 'deterministic_system'),
    ('register_prediction', 'ai_analyst'),
    ('register_prediction', 'judge_operator'),
    ('link_precedent', 'judge_operator'),
    ('link_precedent', 'deterministic_system'),
    ('create_agent_proposal', 'ai_analyst'),
    ('create_agent_proposal', 'judge_operator'),
    ('resolve_agent_proposal', 'judge_operator'),
)


def _apply_product_workflow(connection: Connection) -> None:
    for table in (
        schema_workflow.adjudications,
        schema_workflow.flag_instances,
        schema_workflow.predictions,
        schema_workflow.precedent_links,
        schema_workflow.agent_proposals,
        schema_workflow.outbox_events,
    ):
        table.create(connection)

    connection.execute(
        insert(schema.action_permissions),
        [
            {
                'policy_version_id': 'governance-v1',
                'action_type': action_type,
                'actor_role': actor_role,
            }
            for action_type, actor_role in _WORKFLOW_ACTION_PERMISSIONS
        ],
    )


def _apply_m3_proposal_citations(connection: Connection) -> None:
    columns = {
        row[1]
        for row in connection.exec_driver_sql(
            'PRAGMA table_info(agent_proposals)'
        ).fetchall()
    }
    if 'information_cutoff_at' not in columns:
        connection.exec_driver_sql(
            'ALTER TABLE agent_proposals ADD COLUMN information_cutoff_at TEXT'
        )
    if 'operator_prompt' not in columns:
        connection.exec_driver_sql(
            'ALTER TABLE agent_proposals ADD COLUMN operator_prompt TEXT'
        )
    connection.execute(
        delete(schema.action_permissions).where(
            schema.action_permissions.c.policy_version_id == 'governance-v1',
            schema.action_permissions.c.action_type == 'create_agent_proposal',
            schema.action_permissions.c.actor_role == 'judge_operator',
        )
    )


_PROTECTED_TICKET_PERMISSIONS = (
    ("create_ticket_batch", "judge_operator"),
    ("remove_ticket_leg", "judge_operator"),
    ("approve_ticket_batch", "judge_operator"),
    ("issue_ticket_confirmation", "judge_operator"),
    ("confirm_ticket_placement", "judge_operator"),
)


def _apply_protected_tickets(connection: Connection) -> None:
    for table in (
        schema_tickets.ticket_batch_revisions,
        schema_tickets.audited_ticket_artifacts,
        schema_tickets.ticket_confirmation_challenges,
        schema_tickets.ticket_placements,
    ):
        table.create(connection)
    connection.execute(
        insert(schema.action_permissions),
        [
            {
                "policy_version_id": "governance-v1",
                "action_type": action_type,
                "actor_role": actor_role,
            }
            for action_type, actor_role in _PROTECTED_TICKET_PERMISSIONS
        ],
    )


_SCOREBOARD_PERMISSIONS = (
    ("record_scoreboard_observation", "judge_operator"),
    ("approve_scoreboard_cutover", "judge_operator"),
    ("record_scoreboard_shadow_review", "deterministic_system"),
    ("record_scoreboard_export", "deterministic_system"),
)


def _apply_scoreboard_authority(connection: Connection) -> None:
    for table in (
        schema_scoreboard.scoreboard_observations,
        schema_scoreboard.scoreboard_shadow_reviews,
        schema_scoreboard.scoreboard_authority,
    ):
        table.create(connection)
    connection.execute(
        insert(schema_scoreboard.scoreboard_authority).values(
            authority_id="primary",
            state="legacy",
            projection_version=None,
            source_high_watermark=None,
            legacy_sha256=None,
            shadow_review_id=None,
            compatibility_export_sha256=None,
            approved_at=None,
            approved_by_action_id=None,
            version=1,
        )
    )
    connection.execute(
        insert(schema.action_permissions),
        [
            {
                "policy_version_id": "governance-v1",
                "action_type": action_type,
                "actor_role": actor_role,
            }
            for action_type, actor_role in _SCOREBOARD_PERMISSIONS
        ],
    )


_RELIABILITY_PERMISSIONS = (
    ("record_reliability_evidence", "deterministic_system"),
    ("record_reliability_evidence", "judge_operator"),
    ("approve_release", "judge_operator"),
)


def _apply_reliability_governance(connection: Connection) -> None:
    for table in (
        schema_reliability.reliability_evidence,
        schema_reliability.release_approvals,
    ):
        table.create(connection)
    connection.execute(
        insert(schema.action_permissions),
        [
            {
                "policy_version_id": "governance-v1",
                "action_type": action_type,
                "actor_role": actor_role,
            }
            for action_type, actor_role in _RELIABILITY_PERMISSIONS
        ],
    )


_PREDICTION_GRADE_PERMISSIONS = (
    ('grade_prediction', 'judge_operator'),
)


def _apply_prediction_subjects(connection: Connection) -> None:
    """Widen predictions to subject scope (issue-level rx predictions) + grade permission.

    Fresh databases already get ``subject_type``/``subject_id`` and the nullable
    ``match_id`` from migration 10's ``table.create`` (the Table definition carries
    them), so the rebuild is guarded by a PRAGMA check and only fires when upgrading
    a store created before this migration. SQLite cannot relax NOT NULL in place, so
    the upgrade path rebuilds the table (12-step simplified; pre-v15 production
    tables are empty or tiny). ``RENAME TO`` keeps the old table's indexes under
    their original names, so the stale index is dropped before ``create`` re-makes it.
    """
    cols = {row[1] for row in connection.exec_driver_sql('PRAGMA table_info(predictions)')}
    if 'subject_type' not in cols:
        connection.exec_driver_sql('ALTER TABLE predictions RENAME TO predictions_v14')
        connection.exec_driver_sql('DROP INDEX IF EXISTS ix_predictions_match_id')
        schema_workflow.predictions.create(connection)
        connection.exec_driver_sql(
            'INSERT INTO predictions (prediction_id, match_id, subject_type, subject_id,'
            ' claim, falsifier, status, outcome, registered_at, settled_at)'
            " SELECT prediction_id, match_id, 'match', match_id,"
            ' claim, falsifier, status, outcome, registered_at, settled_at'
            ' FROM predictions_v14'
        )
        connection.exec_driver_sql('DROP TABLE predictions_v14')
    # Permission insert sits outside the rebuild guard (fresh stores skip the rebuild
    # but still need the grant) behind its own COUNT guard so it lands exactly once.
    granted = connection.exec_driver_sql(
        "SELECT COUNT(*) FROM action_permissions WHERE action_type='grade_prediction'"
    ).scalar_one()
    if granted == 0:
        connection.execute(
            insert(schema.action_permissions),
            [
                {
                    'policy_version_id': 'governance-v1',
                    'action_type': action_type,
                    'actor_role': actor_role,
                }
                for action_type, actor_role in _PREDICTION_GRADE_PERMISSIONS
            ],
        )


def _apply_ticket_shadows(connection: Connection) -> None:
    schema_tickets.ticket_shadow_records.create(connection, checkfirst=True)
    granted = connection.execute(
        select(func.count())
        .select_from(schema.action_permissions)
        .where(
            schema.action_permissions.c.policy_version_id == "governance-v1",
            schema.action_permissions.c.action_type == "mark_ticket_shadow",
            schema.action_permissions.c.actor_role == "deterministic_system",
        )
    ).scalar_one()
    if granted == 0:
        connection.execute(
            insert(schema.action_permissions).values(
                policy_version_id="governance-v1",
                action_type="mark_ticket_shadow",
                actor_role="deterministic_system",
            )
        )


def _apply_operator_official_sale(connection: Connection) -> None:
    for table in (
        schema_operator_sale.official_sale_slate_revisions,
        schema_operator_sale.official_offer_families,
        schema_operator_sale.official_offer_revisions,
        schema_operator_sale.official_schedule_check_receipts,
    ):
        table.create(connection)
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_sale_single_root
        BEFORE INSERT ON official_sale_slate_revisions
        WHEN NEW.supersedes_slate_revision_id IS NULL
          AND EXISTS (
            SELECT 1
            FROM official_sale_slate_revisions
            WHERE slate_family_id = NEW.slate_family_id
              AND supersedes_slate_revision_id IS NULL
          )
        BEGIN
          SELECT RAISE(ABORT, 'slate_family_id already has a root revision');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_sale_root_revision_no
        BEFORE INSERT ON official_sale_slate_revisions
        WHEN NEW.supersedes_slate_revision_id IS NULL AND NEW.revision_no != 1
        BEGIN
          SELECT RAISE(ABORT, 'root revision_no must be 1');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_sale_linear_child
        BEFORE INSERT ON official_sale_slate_revisions
        WHEN NEW.supersedes_slate_revision_id IS NOT NULL
        BEGIN
          SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM official_sale_slate_revisions AS parent
            WHERE parent.slate_revision_id = NEW.supersedes_slate_revision_id
              AND parent.slate_family_id = NEW.slate_family_id
              AND parent.lane = NEW.lane
              AND parent.business_key = NEW.business_key
          ) THEN RAISE(ABORT, 'superseding revision must belong to same slate family') END;
          SELECT CASE WHEN NEW.revision_no != (
            SELECT parent.revision_no + 1
            FROM official_sale_slate_revisions AS parent
            WHERE parent.slate_revision_id = NEW.supersedes_slate_revision_id
          ) THEN RAISE(ABORT, 'revision_no must immediately follow parent') END;
        END
        """
    )
    connection.execute(
        insert(schema.action_permissions),
        [
            {
                "policy_version_id": "governance-v1",
                "action_type": action_type,
                "actor_role": "deterministic_system",
            }
            for action_type in (
                "import_official_sale_slate",
                "record_official_schedule_check",
            )
        ],
    )


def _apply_operator_evidence_intake(connection: Connection) -> None:
    for table in (
        schema_operator_decision.operator_evidence_intake_receipts,
        schema_operator_decision.operator_evidence_intake_objects,
        schema_operator_decision.operator_evidence_coverage_receipts,
    ):
        table.create(connection)
    connection.execute(
        insert(schema.action_permissions).values(
            policy_version_id="governance-v1",
            action_type="ingest_operator_evidence_manifest",
            actor_role="deterministic_system",
        )
    )


def _apply_operator_evidence_freeze(connection: Connection) -> None:
    for table in (
        schema_operator_decision.operator_evidence_freeze_requests,
        schema_operator_decision.operator_task_evidence_bundle_revisions,
        schema_operator_decision.operator_task_evidence_bundle_items,
        schema_operator_decision.operator_worker_jobs,
    ):
        table.create(connection)
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_evidence_freeze_request_action
        BEFORE INSERT ON operator_evidence_freeze_requests
        WHEN NOT EXISTS (
          SELECT 1
          FROM actions
          WHERE action_id = NEW.action_id
            AND action_type = 'request_evidence_freeze'
            AND actor_role = 'judge_operator'
            AND status IN ('accepted', 'committed')
        )
        BEGIN
          SELECT RAISE(ABORT, 'evidence freeze request requires its judge Action');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER task_evidence_bundle_single_root
        BEFORE INSERT ON operator_task_evidence_bundle_revisions
        WHEN NEW.supersedes_revision_id IS NULL
          AND EXISTS (
            SELECT 1
            FROM operator_task_evidence_bundle_revisions
            WHERE task_family_id = NEW.task_family_id
              AND supersedes_revision_id IS NULL
          )
        BEGIN
          SELECT RAISE(ABORT, 'task_family_id already has a root evidence bundle');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER task_evidence_bundle_root_revision_no
        BEFORE INSERT ON operator_task_evidence_bundle_revisions
        WHEN NEW.supersedes_revision_id IS NULL AND NEW.revision_no != 1
        BEGIN
          SELECT RAISE(ABORT, 'root evidence bundle revision_no must be 1');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER task_evidence_bundle_linear_child
        BEFORE INSERT ON operator_task_evidence_bundle_revisions
        WHEN NEW.supersedes_revision_id IS NOT NULL
        BEGIN
          SELECT CASE WHEN NOT EXISTS (
            SELECT 1
            FROM operator_task_evidence_bundle_revisions AS parent
            WHERE parent.task_evidence_bundle_revision_id = NEW.supersedes_revision_id
              AND parent.task_family_id = NEW.task_family_id
              AND parent.lane = NEW.lane
              AND parent.business_key = NEW.business_key
          ) THEN RAISE(ABORT, 'superseding evidence bundle must belong to same task family') END;
          SELECT CASE WHEN NEW.revision_no != (
            SELECT parent.revision_no + 1
            FROM operator_task_evidence_bundle_revisions AS parent
            WHERE parent.task_evidence_bundle_revision_id = NEW.supersedes_revision_id
          ) THEN RAISE(ABORT, 'evidence bundle revision_no must immediately follow parent') END;
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER task_evidence_bundle_counts_match_items
        BEFORE INSERT ON operator_task_evidence_bundle_revisions
        BEGIN
          SELECT CASE WHEN NEW.item_count != (
            SELECT COUNT(*)
            FROM operator_task_evidence_bundle_items AS item
            WHERE item.task_evidence_bundle_revision_id = NEW.task_evidence_bundle_revision_id
          ) OR NEW.bundle_count != (
            SELECT COUNT(DISTINCT item.evidence_bundle_id)
            FROM operator_task_evidence_bundle_items AS item
            WHERE item.task_evidence_bundle_revision_id = NEW.task_evidence_bundle_revision_id
          ) OR NEW.required_match_count != (
            SELECT COUNT(DISTINCT item.match_id)
            FROM operator_task_evidence_bundle_items AS item
            WHERE item.task_evidence_bundle_revision_id = NEW.task_evidence_bundle_revision_id
          ) THEN RAISE(ABORT, 'task evidence bundle declared counts do not match items') END;
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER task_evidence_bundle_item_freeze_action
        BEFORE INSERT ON operator_task_evidence_bundle_items
        WHEN NOT EXISTS (
          SELECT 1
          FROM actions
          WHERE action_id = NEW.freeze_bundle_action_id
            AND action_type = 'freeze_evidence_bundle'
            AND actor_role = 'deterministic_system'
            AND status = 'committed'
            AND json_array_length(result_refs_json) = 1
            AND json_extract(result_refs_json, '$[0].object_type') = 'evidence_bundle'
            AND json_extract(result_refs_json, '$[0].object_id') = NEW.evidence_bundle_id
        )
        BEGIN
          SELECT RAISE(ABORT, 'bundle item requires a freeze_evidence_bundle Action');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER task_evidence_bundle_item_after_finalize
        BEFORE INSERT ON operator_task_evidence_bundle_items
        WHEN EXISTS (
          SELECT 1
          FROM operator_task_evidence_bundle_revisions
          WHERE task_evidence_bundle_revision_id = NEW.task_evidence_bundle_revision_id
        )
        BEGIN
          SELECT RAISE(ABORT, 'finalized task evidence bundle items are immutable');
        END
        """
    )
    for operation in ("UPDATE", "DELETE"):
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER operator_evidence_freeze_request_no_{operation.lower()}
            BEFORE {operation} ON operator_evidence_freeze_requests
            BEGIN
              SELECT RAISE(ABORT, 'operator evidence freeze requests are append-only');
            END
            """
        )
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER task_evidence_bundle_item_no_{operation.lower()}
            BEFORE {operation} ON operator_task_evidence_bundle_items
            BEGIN
              SELECT RAISE(ABORT, 'task evidence bundle items are append-only');
            END
            """
        )
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER task_evidence_bundle_revision_no_{operation.lower()}
            BEFORE {operation} ON operator_task_evidence_bundle_revisions
            BEGIN
              SELECT RAISE(ABORT, 'task evidence bundle revisions are append-only');
            END
            """
        )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_worker_job_immutable_source
        BEFORE UPDATE ON operator_worker_jobs
        WHEN NEW.worker_job_id != OLD.worker_job_id
          OR NEW.job_kind != OLD.job_kind
          OR NEW.source_object_type != OLD.source_object_type
          OR NEW.source_object_id != OLD.source_object_id
          OR NEW.created_at != OLD.created_at
        BEGIN
          SELECT RAISE(ABORT, 'operator worker job source is immutable');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_worker_job_terminal_no_delete
        BEFORE DELETE ON operator_worker_jobs
        WHEN OLD.state IN ('completed', 'failed')
        BEGIN
          SELECT RAISE(ABORT, 'terminal operator worker job is immutable');
        END
        """
    )
    evidence_freeze_result_check = """
      SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM actions AS action
        JOIN operator_task_evidence_bundle_revisions AS revision
          ON revision.link_action_id = action.action_id
        WHERE action.action_id = NEW.result_action_id
          AND action.action_type = 'link_operator_task_evidence_freeze'
          AND action.actor_role = 'deterministic_system'
          AND NEW.source_object_type = 'operator_evidence_freeze_request'
          AND NEW.result_object_type = 'task_evidence_bundle_revision'
          AND revision.task_evidence_bundle_revision_id = NEW.result_object_id
          AND revision.evidence_freeze_request_id = NEW.source_object_id
      ) THEN RAISE(ABORT, 'evidence freeze job result does not match its link Action') END;
    """
    for operation in ("INSERT", "UPDATE"):
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER operator_worker_job_evidence_freeze_result_{operation.lower()}
            BEFORE {operation} ON operator_worker_jobs
            WHEN NEW.state = 'completed' AND NEW.job_kind = 'evidence_freeze'
            BEGIN
              {evidence_freeze_result_check}
            END
            """
        )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_worker_job_terminal_immutable
        BEFORE UPDATE ON operator_worker_jobs
        WHEN OLD.state IN ('completed', 'failed')
        BEGIN
          SELECT RAISE(ABORT, 'terminal operator worker job is immutable');
        END
        """
    )
    connection.execute(
        insert(schema.action_permissions),
        [
            {
                "policy_version_id": "governance-v1",
                "action_type": "request_evidence_freeze",
                "actor_role": "judge_operator",
            },
            {
                "policy_version_id": "governance-v1",
                "action_type": "link_operator_task_evidence_freeze",
                "actor_role": "deterministic_system",
            },
        ],
    )


def _apply_operator_judgment_baseline(connection: Connection) -> None:
    for table in (
        schema_operator_decision.operator_market_prior_baseline_revisions,
        schema_operator_decision.operator_market_prior_baseline_probabilities,
        schema_operator_decision.operator_baseline_envelope_revisions,
        schema_operator_decision.operator_baseline_envelope_offer_constraints,
        schema_operator_decision.operator_baseline_envelope_face_bundles,
        schema_operator_decision.operator_baseline_envelope_bundle_faces,
        schema_operator_decision.operator_baseline_envelope_structure_templates,
        schema_operator_decision.operator_baseline_envelope_template_offers,
        schema_operator_decision.operator_match_judgment_revisions,
        schema_operator_decision.operator_match_judgment_probabilities,
        schema_operator_decision.operator_match_judgment_factor_adjustments,
        schema_operator_decision.operator_match_judgment_factor_offsets,
        schema_operator_decision.operator_match_judgment_factor_evidence_refs,
        schema_operator_decision.operator_match_judgment_face_bundles,
        schema_operator_decision.operator_match_judgment_bundle_faces,
        schema_operator_decision.operator_match_judgment_rule_refs,
        schema_operator_decision.operator_match_judgment_evidence_refs,
        schema_operator_decision.operator_judgment_prescription_revisions,
        schema_operator_decision.operator_judgment_prescription_items,
    ):
        table.create(connection)
    revision_contracts = (
        (
            "operator_market_prior_baseline_revisions",
            "market_prior_baseline_revision_id",
            "market_prior_baseline_family_id",
            "market_prior_baseline",
            "freeze_market_prior_baseline",
            "deterministic_system",
        ),
        (
            "operator_baseline_envelope_revisions",
            "baseline_envelope_revision_id",
            "baseline_envelope_family_id",
            "baseline_envelope",
            "record_baseline_envelope",
            "judge_operator",
        ),
        (
            "operator_match_judgment_revisions",
            "operator_match_judgment_revision_id",
            "operator_match_judgment_family_id",
            "operator_match_judgment",
            "commit_operator_match_judgment",
            "judge_operator",
        ),
        (
            "operator_judgment_prescription_revisions",
            "judgment_prescription_revision_id",
            "judgment_prescription_family_id",
            "judgment_prescription",
            "freeze_judgment_prescription",
            "judge_operator",
        ),
    )
    for table_name, id_column, family_column, trigger_prefix, action_type, actor_role in (
        revision_contracts
    ):
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER {trigger_prefix}_single_root
            BEFORE INSERT ON {table_name}
            WHEN NEW.supersedes_revision_id IS NULL
              AND EXISTS (
                SELECT 1
                FROM {table_name}
                WHERE {family_column} = NEW.{family_column}
                  AND supersedes_revision_id IS NULL
              )
            BEGIN
              SELECT RAISE(ABORT, '{family_column} already has a root revision');
            END
            """
        )
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER {trigger_prefix}_root_revision_no
            BEFORE INSERT ON {table_name}
            WHEN NEW.supersedes_revision_id IS NULL AND NEW.revision_no != 1
            BEGIN
              SELECT RAISE(ABORT, 'root revision_no must be 1');
            END
            """
        )
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER {trigger_prefix}_linear_child
            BEFORE INSERT ON {table_name}
            WHEN NEW.supersedes_revision_id IS NOT NULL
            BEGIN
              SELECT CASE WHEN NOT EXISTS (
                SELECT 1
                FROM {table_name} AS parent
                WHERE parent.{id_column} = NEW.supersedes_revision_id
                  AND parent.{family_column} = NEW.{family_column}
              ) THEN RAISE(ABORT, 'superseding revision must belong to same family') END;
              SELECT CASE WHEN NEW.revision_no != (
                SELECT parent.revision_no + 1
                FROM {table_name} AS parent
                WHERE parent.{id_column} = NEW.supersedes_revision_id
              ) THEN RAISE(ABORT, 'revision_no must immediately follow parent') END;
            END
            """
        )
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER {trigger_prefix}_typed_action
            BEFORE INSERT ON {table_name}
            WHEN NOT EXISTS (
              SELECT 1
              FROM actions
              WHERE action_id = NEW.action_id
                AND action_type = '{action_type}'
                AND actor_role = '{actor_role}'
                AND status IN ('accepted', 'committed')
            )
            BEGIN
              SELECT RAISE(ABORT, '{table_name} requires its typed Action');
            END
            """
        )
        for operation in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"""
                CREATE TRIGGER {trigger_prefix}_no_{operation.lower()}
                BEFORE {operation} ON {table_name}
                BEGIN
                  SELECT RAISE(ABORT, '{table_name} is append-only');
                END
                """
            )
    child_revision_guards = (
        (
            "operator_market_prior_baseline_probabilities",
            "operator_market_prior_baseline_revisions AS revision "
            "ON revision.market_prior_baseline_revision_id = "
            "NEW.market_prior_baseline_revision_id",
        ),
        (
            "operator_baseline_envelope_offer_constraints",
            "operator_baseline_envelope_revisions AS revision "
            "ON revision.baseline_envelope_revision_id = "
            "NEW.baseline_envelope_revision_id",
        ),
        (
            "operator_baseline_envelope_face_bundles",
            "operator_baseline_envelope_offer_constraints AS child_parent "
            "ON child_parent.baseline_envelope_offer_constraint_id = "
            "NEW.baseline_envelope_offer_constraint_id "
            "JOIN operator_baseline_envelope_revisions AS revision "
            "ON revision.baseline_envelope_revision_id = "
            "child_parent.baseline_envelope_revision_id",
        ),
        (
            "operator_baseline_envelope_bundle_faces",
            "operator_baseline_envelope_face_bundles AS child_parent "
            "ON child_parent.baseline_envelope_face_bundle_id = "
            "NEW.baseline_envelope_face_bundle_id "
            "JOIN operator_baseline_envelope_offer_constraints AS offer_parent "
            "ON offer_parent.baseline_envelope_offer_constraint_id = "
            "child_parent.baseline_envelope_offer_constraint_id "
            "JOIN operator_baseline_envelope_revisions AS revision "
            "ON revision.baseline_envelope_revision_id = "
            "offer_parent.baseline_envelope_revision_id",
        ),
        (
            "operator_baseline_envelope_structure_templates",
            "operator_baseline_envelope_revisions AS revision "
            "ON revision.baseline_envelope_revision_id = "
            "NEW.baseline_envelope_revision_id",
        ),
        (
            "operator_baseline_envelope_template_offers",
            "operator_baseline_envelope_structure_templates AS child_parent "
            "ON child_parent.baseline_envelope_structure_template_id = "
            "NEW.baseline_envelope_structure_template_id "
            "JOIN operator_baseline_envelope_revisions AS revision "
            "ON revision.baseline_envelope_revision_id = "
            "child_parent.baseline_envelope_revision_id",
        ),
        (
            "operator_match_judgment_probabilities",
            "operator_match_judgment_revisions AS revision "
            "ON revision.operator_match_judgment_revision_id = "
            "NEW.operator_match_judgment_revision_id",
        ),
        (
            "operator_match_judgment_factor_adjustments",
            "operator_match_judgment_revisions AS revision "
            "ON revision.operator_match_judgment_revision_id = "
            "NEW.operator_match_judgment_revision_id",
        ),
        (
            "operator_match_judgment_factor_offsets",
            "operator_match_judgment_factor_adjustments AS child_parent "
            "ON child_parent.operator_match_judgment_factor_adjustment_id = "
            "NEW.operator_match_judgment_factor_adjustment_id "
            "JOIN operator_match_judgment_revisions AS revision "
            "ON revision.operator_match_judgment_revision_id = "
            "child_parent.operator_match_judgment_revision_id",
        ),
        (
            "operator_match_judgment_factor_evidence_refs",
            "operator_match_judgment_factor_adjustments AS child_parent "
            "ON child_parent.operator_match_judgment_factor_adjustment_id = "
            "NEW.operator_match_judgment_factor_adjustment_id "
            "JOIN operator_match_judgment_revisions AS revision "
            "ON revision.operator_match_judgment_revision_id = "
            "child_parent.operator_match_judgment_revision_id",
        ),
        (
            "operator_match_judgment_face_bundles",
            "operator_match_judgment_revisions AS revision "
            "ON revision.operator_match_judgment_revision_id = "
            "NEW.operator_match_judgment_revision_id",
        ),
        (
            "operator_match_judgment_bundle_faces",
            "operator_match_judgment_face_bundles AS child_parent "
            "ON child_parent.operator_match_judgment_face_bundle_id = "
            "NEW.operator_match_judgment_face_bundle_id "
            "JOIN operator_match_judgment_revisions AS revision "
            "ON revision.operator_match_judgment_revision_id = "
            "child_parent.operator_match_judgment_revision_id",
        ),
        (
            "operator_match_judgment_rule_refs",
            "operator_match_judgment_revisions AS revision "
            "ON revision.operator_match_judgment_revision_id = "
            "NEW.operator_match_judgment_revision_id",
        ),
        (
            "operator_match_judgment_evidence_refs",
            "operator_match_judgment_revisions AS revision "
            "ON revision.operator_match_judgment_revision_id = "
            "NEW.operator_match_judgment_revision_id",
        ),
        (
            "operator_judgment_prescription_items",
            "operator_judgment_prescription_revisions AS revision "
            "ON revision.judgment_prescription_revision_id = "
            "NEW.judgment_prescription_revision_id",
        ),
    )
    for table_name, revision_join in child_revision_guards:
        for operation in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"""
                CREATE TRIGGER {table_name}_no_{operation.lower()}
                BEFORE {operation} ON {table_name}
                BEGIN
                  SELECT RAISE(ABORT, '{table_name} is append-only');
                END
                """
            )
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER {table_name}_no_late_insert
            BEFORE INSERT ON {table_name}
            WHEN EXISTS (
              SELECT 1
              FROM actions AS action
              JOIN {revision_join}
              WHERE action.action_id = revision.action_id
                AND action.status = 'committed'
            )
            BEGIN
              SELECT RAISE(ABORT, '{table_name} is append-only after commit');
            END
            """
        )
    market_baseline_result_check = """
      SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM actions AS action
        JOIN operator_market_prior_baseline_revisions AS revision
          ON revision.action_id = action.action_id
        WHERE action.action_id = NEW.result_action_id
          AND action.action_type = 'freeze_market_prior_baseline'
          AND action.actor_role = 'deterministic_system'
          AND action.status IN ('accepted', 'committed')
          AND NEW.source_object_type = 'task_evidence_bundle_revision'
          AND NEW.result_object_type = 'market_prior_baseline_revision'
          AND revision.market_prior_baseline_revision_id = NEW.result_object_id
          AND revision.task_evidence_bundle_revision_id = NEW.source_object_id
      ) THEN RAISE(ABORT, 'market baseline job result does not match its typed Action') END;
    """
    for operation in ("INSERT", "UPDATE"):
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER operator_worker_job_market_baseline_result_{operation.lower()}
            BEFORE {operation} ON operator_worker_jobs
            WHEN NEW.state = 'completed' AND NEW.job_kind = 'market_baseline'
            BEGIN
              {market_baseline_result_check}
            END
            """
        )
    connection.execute(
        insert(schema.action_permissions),
        [
            {
                "policy_version_id": "governance-v1",
                "action_type": "freeze_market_prior_baseline",
                "actor_role": "deterministic_system",
            },
            {
                "policy_version_id": "governance-v1",
                "action_type": "record_baseline_envelope",
                "actor_role": "judge_operator",
            },
            {
                "policy_version_id": "governance-v1",
                "action_type": "commit_operator_match_judgment",
                "actor_role": "judge_operator",
            },
            {
                "policy_version_id": "governance-v1",
                "action_type": "freeze_judgment_prescription",
                "actor_role": "judge_operator",
            },
        ],
    )


def _apply_operator_candidate_comparison(connection: Connection) -> None:
    existing_quote_columns = {
        column["name"] for column in inspect(connection).get_columns("market_quotes")
    }
    if "settlement_parameter_decimal" not in existing_quote_columns:
        connection.exec_driver_sql(
            "ALTER TABLE market_quotes "
            "ADD COLUMN settlement_parameter_decimal TEXT NULL"
        )
    existing_baseline_columns = {
        column["name"]
        for column in inspect(connection).get_columns(
            "operator_market_prior_baseline_probabilities"
        )
    }
    requires_baseline_backfill = not {
        "booked_decimal_odds",
        "quote_captured_at",
    } <= existing_baseline_columns
    if requires_baseline_backfill:
        connection.exec_driver_sql(
            "DROP TRIGGER IF EXISTS "
            "operator_market_prior_baseline_probabilities_no_update"
        )
    if "settlement_parameter_decimal" not in existing_baseline_columns:
        connection.exec_driver_sql(
            "ALTER TABLE operator_market_prior_baseline_probabilities "
            "ADD COLUMN settlement_parameter_decimal TEXT NULL"
        )
    if "booked_decimal_odds" not in existing_baseline_columns:
        connection.exec_driver_sql(
            "ALTER TABLE operator_market_prior_baseline_probabilities "
            "ADD COLUMN booked_decimal_odds TEXT NULL"
        )
        connection.exec_driver_sql(
            "UPDATE operator_market_prior_baseline_probabilities "
            "SET booked_decimal_odds = printf('%.12f', ("
            "SELECT decimal_odds FROM market_quotes "
            "WHERE market_quotes.quote_id = "
            "operator_market_prior_baseline_probabilities.quote_id))"
        )
    if "quote_captured_at" not in existing_baseline_columns:
        connection.exec_driver_sql(
            "ALTER TABLE operator_market_prior_baseline_probabilities "
            "ADD COLUMN quote_captured_at TEXT NULL"
        )
        connection.exec_driver_sql(
            "UPDATE operator_market_prior_baseline_probabilities "
            "SET quote_captured_at = (SELECT captured_at FROM market_quotes "
            "WHERE market_quotes.quote_id = "
            "operator_market_prior_baseline_probabilities.quote_id)"
        )
    if requires_baseline_backfill:
        connection.exec_driver_sql(
            "CREATE TRIGGER operator_market_prior_baseline_probabilities_no_update "
            "BEFORE UPDATE ON operator_market_prior_baseline_probabilities "
            "BEGIN SELECT RAISE(ABORT, "
            "'operator_market_prior_baseline_probabilities is append-only'); END"
        )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_market_prior_booked_odds_required
        BEFORE INSERT ON operator_market_prior_baseline_probabilities
        WHEN NEW.booked_decimal_odds IS NULL
          OR typeof(NEW.booked_decimal_odds) != 'text'
          OR printf('%.12f', CAST(NEW.booked_decimal_odds AS REAL))
             != NEW.booked_decimal_odds
          OR CAST(NEW.booked_decimal_odds AS REAL) <= 1.0
        BEGIN
          SELECT RAISE(ABORT, 'baseline probability requires exact booked odds');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_market_prior_quote_capture_required
        BEFORE INSERT ON operator_market_prior_baseline_probabilities
        WHEN NEW.quote_captured_at IS NULL OR length(trim(NEW.quote_captured_at)) = 0
        BEGIN
          SELECT RAISE(ABORT, 'baseline probability requires Quote capture time');
        END
        """
    )
    existing_selection_columns = {
        column["name"] for column in inspect(connection).get_columns("selection_definitions")
    }
    if "deployable" not in existing_selection_columns:
        connection.exec_driver_sql(
            "ALTER TABLE selection_definitions "
            "ADD COLUMN deployable INTEGER NOT NULL DEFAULT 1"
        )
    connection.exec_driver_sql(
        "UPDATE selection_definitions SET deployable = 0 "
        "WHERE market_definition_id = 'md-crs' AND outcome_key = 'other'"
    )
    for selection_id, outcome_key in (
        ("sel-crs-win-other", "win_other"),
        ("sel-crs-draw-other", "draw_other"),
        ("sel-crs-loss-other", "loss_other"),
    ):
        connection.execute(
            insert(schema_market.selection_definitions).values(
                selection_id=selection_id,
                market_definition_id="md-crs",
                outcome_key=outcome_key,
                line=None,
                deployable=1,
            )
        )

    for table in (
        schema_operator_result.zucai_fixed_prize_policy_revisions,
        schema_operator_result.zucai_fixed_prize_policy_tiers,
        schema_operator_decision.operator_candidate_generation_requests,
        schema_operator_decision.operator_candidate_set_revisions,
        schema_operator_decision.operator_candidates,
        schema_operator_decision.operator_candidate_metrics,
        schema_operator_decision.operator_candidate_dead_faces,
        schema_operator_decision.operator_candidate_audit_findings,
        schema_operator_decision.operator_candidate_selections,
        schema_operator_result.operator_candidate_tickets,
        schema_operator_result.operator_candidate_ticket_legs,
    ):
        table.create(connection)

    revision_contracts = (
        (
            "zucai_fixed_prize_policy_revisions",
            "fixed_prize_policy_revision_id",
            "fixed_prize_policy_family_id",
            "zucai_fixed_prize_policy",
            "register_zucai_fixed_prize_policy",
            "deterministic_system",
        ),
        (
            "operator_candidate_set_revisions",
            "candidate_set_revision_id",
            "candidate_set_family_id",
            "operator_candidate_set",
            "generate_ticket_candidate_set",
            "deterministic_system",
        ),
        (
            "operator_candidate_selections",
            "candidate_selection_id",
            "candidate_selection_family_id",
            "candidate_selection",
            "select_ticket_candidate",
            "judge_operator",
        ),
    )
    for table_name, id_column, family_column, prefix, action_type, actor_role in (
        revision_contracts
    ):
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER {prefix}_single_root
            BEFORE INSERT ON {table_name}
            WHEN NEW.supersedes_revision_id IS NULL
              AND EXISTS (
                SELECT 1 FROM {table_name}
                WHERE {family_column} = NEW.{family_column}
                  AND supersedes_revision_id IS NULL
              )
            BEGIN
              SELECT RAISE(ABORT, '{family_column} already has a root revision');
            END
            """
        )
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER {prefix}_linear_revision
            BEFORE INSERT ON {table_name}
            WHEN (NEW.supersedes_revision_id IS NULL AND NEW.revision_no != 1)
              OR (NEW.supersedes_revision_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM {table_name} AS parent
                WHERE parent.{id_column} = NEW.supersedes_revision_id
                  AND parent.{family_column} = NEW.{family_column}
                  AND NEW.revision_no = parent.revision_no + 1
              ))
            BEGIN
              SELECT RAISE(ABORT, 'revision must directly follow its family predecessor');
            END
            """
        )
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER {prefix}_typed_action
            BEFORE INSERT ON {table_name}
            WHEN NOT EXISTS (
              SELECT 1 FROM actions
              WHERE action_id = NEW.action_id
                AND action_type = '{action_type}'
                AND actor_role = '{actor_role}'
                AND status IN ('accepted', 'committed')
            )
            BEGIN
              SELECT RAISE(ABORT, '{table_name} requires its typed Action');
            END
            """
        )

    connection.exec_driver_sql(
        """
        CREATE TRIGGER candidate_generation_request_typed_action
        BEFORE INSERT ON operator_candidate_generation_requests
        WHEN NOT EXISTS (
          SELECT 1 FROM actions
          WHERE action_id = NEW.action_id
            AND action_type IN (
              'request_candidate_generation',
              'record_ticket_audit_override'
            )
            AND actor_role = 'judge_operator'
            AND status IN ('accepted', 'committed')
        )
        BEGIN
          SELECT RAISE(
            ABORT,
            'operator_candidate_generation_requests requires its typed Action'
          );
        END
        """
    )

    immutable_tables = (
        "zucai_fixed_prize_policy_revisions",
        "zucai_fixed_prize_policy_tiers",
        "operator_candidate_generation_requests",
        "operator_candidate_set_revisions",
        "operator_candidates",
        "operator_candidate_tickets",
        "operator_candidate_ticket_legs",
        "operator_candidate_metrics",
        "operator_candidate_dead_faces",
        "operator_candidate_audit_findings",
        "operator_candidate_selections",
    )
    for table_name in immutable_tables:
        for operation in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"""
                CREATE TRIGGER {table_name}_no_{operation.lower()}
                BEFORE {operation} ON {table_name}
                BEGIN
                  SELECT RAISE(ABORT, '{table_name} is append-only');
                END
                """
            )

    child_revision_guards = (
        (
            "zucai_fixed_prize_policy_tiers",
            "zucai_fixed_prize_policy_revisions AS revision "
            "ON revision.fixed_prize_policy_revision_id = "
            "NEW.fixed_prize_policy_revision_id",
        ),
        (
            "operator_candidates",
            "operator_candidate_set_revisions AS revision "
            "ON revision.candidate_set_revision_id = NEW.candidate_set_revision_id",
        ),
        (
            "operator_candidate_metrics",
            "operator_candidates AS candidate "
            "ON candidate.candidate_revision_id = NEW.candidate_revision_id "
            "JOIN operator_candidate_set_revisions AS revision "
            "ON revision.candidate_set_revision_id = candidate.candidate_set_revision_id",
        ),
        (
            "operator_candidate_dead_faces",
            "operator_candidates AS candidate "
            "ON candidate.candidate_revision_id = NEW.candidate_revision_id "
            "JOIN operator_candidate_set_revisions AS revision "
            "ON revision.candidate_set_revision_id = candidate.candidate_set_revision_id",
        ),
        (
            "operator_candidate_audit_findings",
            "operator_candidates AS candidate "
            "ON candidate.candidate_revision_id = NEW.candidate_revision_id "
            "JOIN operator_candidate_set_revisions AS revision "
            "ON revision.candidate_set_revision_id = candidate.candidate_set_revision_id",
        ),
        (
            "operator_candidate_tickets",
            "operator_candidates AS candidate "
            "ON candidate.candidate_revision_id = NEW.candidate_revision_id "
            "JOIN operator_candidate_set_revisions AS revision "
            "ON revision.candidate_set_revision_id = candidate.candidate_set_revision_id",
        ),
        (
            "operator_candidate_ticket_legs",
            "operator_candidate_tickets AS ticket "
            "ON ticket.candidate_ticket_id = NEW.candidate_ticket_id "
            "JOIN operator_candidates AS candidate "
            "ON candidate.candidate_revision_id = ticket.candidate_revision_id "
            "JOIN operator_candidate_set_revisions AS revision "
            "ON revision.candidate_set_revision_id = candidate.candidate_set_revision_id",
        ),
    )
    for table_name, revision_join in child_revision_guards:
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER {table_name}_no_late_insert
            BEFORE INSERT ON {table_name}
            WHEN EXISTS (
              SELECT 1
              FROM actions AS action
              JOIN {revision_join}
              WHERE action.action_id = revision.action_id
                AND action.status = 'committed'
            )
            BEGIN
              SELECT RAISE(ABORT, '{table_name} is append-only after commit');
            END
            """
        )

    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_candidate_set_semantics
        BEFORE INSERT ON operator_candidates
        WHEN NOT EXISTS (
          SELECT 1
          FROM operator_candidate_set_revisions AS candidate_set
          WHERE candidate_set.candidate_set_revision_id = NEW.candidate_set_revision_id
            AND (
              (candidate_set.comparison_only = 1 AND NEW.deployable = 0)
              OR (
                candidate_set.comparison_only = 0
                AND NEW.deployable = NEW.eligible
              )
            )
        )
        BEGIN
          SELECT RAISE(ABORT, 'candidate deployability must match its candidate set');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_candidate_selection_exact_binding
        BEFORE INSERT ON operator_candidate_selections
        WHEN NOT EXISTS (
          SELECT 1
          FROM operator_candidates AS candidate
          JOIN operator_candidate_set_revisions AS candidate_set
            ON candidate_set.candidate_set_revision_id = candidate.candidate_set_revision_id
          WHERE candidate.candidate_revision_id = NEW.candidate_revision_id
            AND candidate_set.candidate_set_revision_id = NEW.candidate_set_revision_id
            AND candidate_set.set_kind = 'judgment_bound'
            AND candidate_set.comparison_only = 0
            AND candidate.partition IN ('eligible', 'audit_blocked')
        )
        BEGIN
          SELECT RAISE(ABORT, 'candidate selection requires a selectable judgment-bound row');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_candidate_generation_job_source
        BEFORE INSERT ON operator_worker_jobs
        WHEN NEW.job_kind = 'candidate_generation'
          AND (
            NEW.source_object_type != 'operator_candidate_generation_request'
            OR NOT EXISTS (
              SELECT 1
              FROM operator_candidate_generation_requests AS request
              JOIN actions AS action ON action.action_id = request.action_id
              WHERE request.generation_request_id = NEW.source_object_id
                AND action.action_type IN (
                  'request_candidate_generation',
                  'record_ticket_audit_override'
                )
                AND action.actor_role = 'judge_operator'
                AND action.status IN ('accepted', 'committed')
            )
          )
        BEGIN
          SELECT RAISE(ABORT, 'candidate generation job requires its typed request');
        END
        """
    )
    candidate_result_check = """
      SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM actions AS action
        JOIN operator_candidate_set_revisions AS candidate_set
          ON candidate_set.action_id = action.action_id
        WHERE action.action_id = NEW.result_action_id
          AND action.action_type = 'generate_ticket_candidate_set'
          AND action.actor_role = 'deterministic_system'
          AND action.status IN ('accepted', 'committed')
          AND NEW.source_object_type = 'operator_candidate_generation_request'
          AND NEW.result_object_type = 'ticket_candidate_set_revision'
          AND candidate_set.candidate_set_revision_id = NEW.result_object_id
          AND candidate_set.generation_request_id = NEW.source_object_id
      ) THEN RAISE(ABORT, 'candidate generation result does not match its typed Action') END;
    """
    for operation in ("INSERT", "UPDATE"):
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER operator_worker_job_candidate_result_{operation.lower()}
            BEFORE {operation} ON operator_worker_jobs
            WHEN NEW.state = 'completed' AND NEW.job_kind = 'candidate_generation'
            BEGIN
              {candidate_result_check}
            END
            """
        )

    connection.execute(
        insert(schema.action_permissions),
        [
            {
                "policy_version_id": "governance-v1",
                "action_type": "register_zucai_fixed_prize_policy",
                "actor_role": "deterministic_system",
            },
            {
                "policy_version_id": "governance-v1",
                "action_type": "request_candidate_generation",
                "actor_role": "judge_operator",
            },
            {
                "policy_version_id": "governance-v1",
                "action_type": "generate_ticket_candidate_set",
                "actor_role": "deterministic_system",
            },
            {
                "policy_version_id": "governance-v1",
                "action_type": "select_ticket_candidate",
                "actor_role": "judge_operator",
            },
        ],
    )


def _apply_operator_deployment_adjudication(connection: Connection) -> None:
    tables = (
        schema_operator_decision.operator_ticket_decision_lineage_revisions,
        schema_operator_decision.operator_ticket_decision_lineage_items,
        schema_operator_decision.operator_ticket_audit_override_receipts,
        schema_operator_decision.operator_candidate_generation_override_links,
        schema_operator_decision.operator_no_ticket_revisions,
        schema_operator_decision.operator_no_ticket_offer_scopes,
        schema_operator_decision.operator_no_ticket_artifact_scopes,
        schema_operator_decision.operator_no_ticket_command_receipts,
        schema_tickets.operator_artifact_work_item_links,
        schema_tickets.operator_protected_artifact_bindings,
        schema_tickets.operator_protected_artifact_offer_revision_links,
        schema_tickets.operator_confirmation_challenge_revisions,
        schema_tickets.operator_confirmation_challenge_heads,
        schema_tickets.operator_artifact_terminal_receipts,
        schema_operator_result.operator_review_eligibility_facts,
    )
    for table in tables:
        table.create(connection)

    revision_contracts = (
        (
            "operator_ticket_decision_lineage_revisions",
            "lineage_revision_id",
            "lineage_family_id",
            "operator_ticket_decision_lineage",
        ),
        (
            "operator_no_ticket_revisions",
            "no_ticket_revision_id",
            "no_ticket_family_id",
            "operator_no_ticket",
        ),
        (
            "operator_confirmation_challenge_revisions",
            "challenge_revision_id",
            "challenge_family_id",
            "operator_confirmation_challenge",
        ),
    )
    for table_name, id_column, family_column, prefix in revision_contracts:
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER {prefix}_single_root
            BEFORE INSERT ON {table_name}
            WHEN NEW.supersedes_revision_id IS NULL
              AND EXISTS (
                SELECT 1 FROM {table_name}
                WHERE {family_column} = NEW.{family_column}
                  AND supersedes_revision_id IS NULL
              )
            BEGIN
              SELECT RAISE(ABORT, '{family_column} already has a root revision');
            END
            """
        )
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER {prefix}_linear_revision
            BEFORE INSERT ON {table_name}
            WHEN (NEW.supersedes_revision_id IS NULL AND NEW.revision_no != 1)
              OR (NEW.supersedes_revision_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM {table_name} AS parent
                WHERE parent.{id_column} = NEW.supersedes_revision_id
                  AND parent.{family_column} = NEW.{family_column}
                  AND NEW.revision_no = parent.revision_no + 1
              ))
            BEGIN
              SELECT RAISE(ABORT, 'revision must directly follow its family predecessor');
            END
            """
        )

    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_ticket_decision_lineage_typed_action
        BEFORE INSERT ON operator_ticket_decision_lineage_revisions
        WHEN NOT EXISTS (
          SELECT 1 FROM actions
          WHERE action_id = NEW.action_id
            AND action_type IN ('create_ticket_batch', 'approve_ticket_batch')
            AND actor_role = 'judge_operator'
            AND status IN ('accepted', 'committed')
        )
        BEGIN
          SELECT RAISE(
            ABORT,
            'operator ticket decision lineage requires its typed Action'
          );
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_ticket_decision_lineage_exact_binding
        BEFORE INSERT ON operator_ticket_decision_lineage_revisions
        WHEN NOT EXISTS (
          SELECT 1
          FROM ticket_batch_revisions AS batch
          JOIN operator_candidate_set_revisions AS candidate_set
            ON candidate_set.candidate_set_revision_id = NEW.candidate_set_revision_id
          JOIN operator_candidates AS candidate
            ON candidate.candidate_revision_id = NEW.candidate_revision_id
           AND candidate.candidate_set_revision_id = candidate_set.candidate_set_revision_id
          JOIN operator_candidate_selections AS selection
            ON selection.candidate_selection_id = NEW.candidate_selection_id
           AND selection.candidate_set_revision_id = candidate_set.candidate_set_revision_id
           AND selection.candidate_revision_id = candidate.candidate_revision_id
          JOIN operator_judgment_prescription_revisions AS prescription
            ON prescription.judgment_prescription_revision_id =
               NEW.judgment_prescription_revision_id
          WHERE batch.ticket_batch_revision_id = NEW.ticket_batch_revision_id
            AND candidate_set.task_family_id = NEW.task_family_id
            AND candidate_set.work_item_id = NEW.work_item_id
            AND candidate_set.task_snapshot_hash = NEW.task_snapshot_hash
            AND candidate_set.slate_revision_id = NEW.slate_revision_id
            AND candidate_set.market_prior_baseline_revision_id =
                NEW.market_prior_baseline_revision_id
            AND candidate_set.baseline_envelope_revision_id =
                NEW.baseline_envelope_revision_id
            AND candidate_set.judgment_prescription_revision_id =
                NEW.judgment_prescription_revision_id
            AND selection.task_family_id = NEW.task_family_id
            AND selection.work_item_id = NEW.work_item_id
            AND selection.task_snapshot_hash = NEW.task_snapshot_hash
            AND selection.slate_revision_id = NEW.slate_revision_id
            AND prescription.task_evidence_bundle_revision_id =
                NEW.task_evidence_bundle_revision_id
            AND candidate_set.audit_policy_version = NEW.audit_policy_version
        )
        BEGIN
          SELECT RAISE(ABORT, 'ticket decision lineage bindings do not reconcile');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_ticket_decision_lineage_item_exact_binding
        BEFORE INSERT ON operator_ticket_decision_lineage_items
        WHEN NOT EXISTS (
          SELECT 1
          FROM operator_ticket_decision_lineage_revisions AS lineage
          JOIN operator_candidate_tickets AS ticket
            ON ticket.candidate_ticket_id = NEW.candidate_ticket_id
           AND ticket.candidate_revision_id = lineage.candidate_revision_id
           AND ticket.ticket_index = NEW.ticket_index
          JOIN operator_candidate_ticket_legs AS leg
            ON leg.candidate_ticket_leg_id = NEW.candidate_ticket_leg_id
           AND leg.candidate_ticket_id = ticket.candidate_ticket_id
           AND leg.leg_index = NEW.leg_index
           AND leg.official_offer_revision_id = NEW.official_offer_revision_id
           AND leg.match_id = NEW.match_id
           AND leg.market_definition_id = NEW.market_definition_id
           AND leg.selection_code = NEW.selection_code
          JOIN operator_market_prior_baseline_probabilities AS baseline
            ON baseline.market_prior_baseline_probability_id =
               NEW.market_prior_baseline_probability_id
           AND baseline.market_prior_baseline_revision_id =
               lineage.market_prior_baseline_revision_id
           AND baseline.official_offer_revision_id = NEW.official_offer_revision_id
           AND baseline.match_id = NEW.match_id
           AND baseline.market_definition_id = NEW.market_definition_id
           AND baseline.face_code = NEW.selection_code
          JOIN operator_match_judgment_revisions AS judgment
            ON judgment.operator_match_judgment_revision_id =
               NEW.operator_match_judgment_revision_id
           AND judgment.forecast_revision_id = NEW.forecast_revision_id
           AND judgment.match_id = NEW.match_id
           AND judgment.official_offer_revision_id = NEW.official_offer_revision_id
           AND judgment.market_definition_id = NEW.market_definition_id
          JOIN operator_judgment_prescription_items AS prescription_item
            ON prescription_item.judgment_prescription_revision_id =
               lineage.judgment_prescription_revision_id
           AND prescription_item.operator_match_judgment_revision_id =
               judgment.operator_match_judgment_revision_id
          WHERE lineage.lineage_revision_id = NEW.lineage_revision_id
        )
        BEGIN
          SELECT RAISE(ABORT, 'ticket decision lineage item does not match its source rows');
        END
        """
    )

    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_ticket_audit_override_typed_action
        BEFORE INSERT ON operator_ticket_audit_override_receipts
        WHEN NOT EXISTS (
          SELECT 1
          FROM actions AS action
          JOIN operator_ticket_decision_lineage_revisions AS lineage
            ON lineage.lineage_revision_id = NEW.lineage_revision_id
          JOIN operator_candidates AS candidate
            ON candidate.candidate_revision_id = NEW.candidate_revision_id
          JOIN operator_candidate_set_revisions AS candidate_set
            ON candidate_set.candidate_set_revision_id = candidate.candidate_set_revision_id
          JOIN operator_candidate_audit_findings AS finding
            ON finding.candidate_audit_finding_id = NEW.candidate_audit_finding_id
           AND finding.candidate_revision_id = candidate.candidate_revision_id
          JOIN adjudications AS adjudication
            ON adjudication.adjudication_id = NEW.adjudication_id
          WHERE action.action_id = NEW.action_id
            AND action.action_type = 'record_ticket_audit_override'
            AND action.actor_role = 'judge_operator'
            AND action.status IN ('accepted', 'committed')
            AND lineage.ticket_batch_revision_id = NEW.ticket_batch_revision_id
            AND lineage.candidate_revision_id = NEW.candidate_revision_id
            AND candidate.content_hash = NEW.candidate_content_hash
            AND candidate_set.audit_policy_version = NEW.audit_policy_version
            AND finding.finding_code = NEW.finding_code
            AND finding.severity = 'ERROR'
            AND adjudication.subject_type = 'ticket_audit_finding'
            AND adjudication.subject_id = NEW.candidate_audit_finding_id
            AND adjudication.decision = 'override'
        )
        BEGIN
          SELECT RAISE(ABORT, 'ticket audit override requires its exact typed Action');
        END
        """
    )

    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_no_ticket_typed_action
        BEFORE INSERT ON operator_no_ticket_revisions
        WHEN NOT EXISTS (
          SELECT 1 FROM actions
          WHERE action_id = NEW.action_id
            AND actor_role = 'judge_operator'
            AND status IN ('accepted', 'committed')
            AND (
              (NEW.supersedes_revision_id IS NULL
               AND action_type = 'record_no_ticket')
              OR (NEW.supersedes_revision_id IS NOT NULL
                  AND action_type = 'supersede_no_ticket')
            )
        )
        BEGIN
          SELECT RAISE(ABORT, 'operator no-ticket revision requires its typed Action');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_no_ticket_command_typed_action
        BEFORE INSERT ON operator_no_ticket_command_receipts
        WHEN NOT EXISTS (
          SELECT 1 FROM actions
          WHERE action_id = NEW.action_id
            AND action_type = NEW.command_kind
            AND actor_role = 'judge_operator'
            AND status IN ('accepted', 'committed')
        )
        BEGIN
          SELECT RAISE(ABORT, 'operator no-ticket receipt requires its typed Action');
        END
        """
    )

    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_artifact_work_item_link_exact_binding
        BEFORE INSERT ON operator_artifact_work_item_links
        WHEN NOT EXISTS (
          SELECT 1
          FROM actions AS action
          JOIN audited_ticket_artifacts AS artifact
            ON artifact.ticket_artifact_id = NEW.ticket_artifact_id
          WHERE action.action_id = NEW.action_id
            AND action.action_type = 'approve_ticket_batch'
            AND action.actor_role = 'judge_operator'
            AND action.status IN ('accepted', 'committed')
            AND artifact.approved_by_action_id = NEW.action_id
        )
        BEGIN
          SELECT RAISE(ABORT, 'artifact work-item link requires its approval Action');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_protected_artifact_exact_binding
        BEFORE INSERT ON operator_protected_artifact_bindings
        WHEN NOT EXISTS (
          SELECT 1
          FROM audited_ticket_artifacts AS artifact
          JOIN operator_ticket_decision_lineage_revisions AS lineage
            ON lineage.lineage_revision_id = NEW.lineage_revision_id
          JOIN operator_candidate_tickets AS ticket
            ON ticket.candidate_ticket_id = NEW.candidate_ticket_id
          WHERE artifact.ticket_artifact_id = NEW.ticket_artifact_id
            AND artifact.ticket_batch_revision_id = lineage.ticket_batch_revision_id
            AND artifact.ticket_index = NEW.ticket_index
            AND artifact.currency = NEW.currency
            AND CAST(ROUND(artifact.amount * 100) AS INTEGER) = NEW.stake_minor
            AND artifact.approved_by_action_id = NEW.action_id
            AND lineage.candidate_revision_id = NEW.candidate_revision_id
            AND ticket.candidate_revision_id = NEW.candidate_revision_id
            AND ticket.ticket_index = NEW.ticket_index
            AND ticket.ticket_kind = NEW.ticket_kind
            AND ticket.stake_minor = NEW.stake_minor
            AND ticket.currency = NEW.currency
            AND ticket.composition_hash = NEW.composition_hash
            AND ticket.fixed_prize_policy_revision_id IS
                NEW.fixed_prize_policy_revision_id
        )
        BEGIN
          SELECT RAISE(ABORT, 'protected artifact binding does not match source rows');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_protected_artifact_offer_exact_binding
        BEFORE INSERT ON operator_protected_artifact_offer_revision_links
        WHEN NOT EXISTS (
          SELECT 1
          FROM operator_protected_artifact_bindings AS binding
          JOIN operator_candidate_ticket_legs AS leg
            ON leg.candidate_ticket_id = binding.candidate_ticket_id
          WHERE binding.ticket_artifact_id = NEW.ticket_artifact_id
            AND leg.official_offer_revision_id = NEW.official_offer_revision_id
            AND NEW.offer_index = (
              SELECT COUNT(DISTINCT preceding.official_offer_revision_id)
              FROM operator_candidate_ticket_legs AS preceding
              WHERE preceding.candidate_ticket_id = binding.candidate_ticket_id
                AND preceding.leg_index < (
                  SELECT MIN(current_leg.leg_index)
                  FROM operator_candidate_ticket_legs AS current_leg
                  WHERE current_leg.candidate_ticket_id = binding.candidate_ticket_id
                    AND current_leg.official_offer_revision_id =
                        NEW.official_offer_revision_id
                )
            )
        )
        BEGIN
          SELECT RAISE(
            ABORT,
            'protected artifact offer is not its ordered candidate offer'
          );
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_protected_artifact_offer_complete
        BEFORE UPDATE OF status ON actions
        WHEN NEW.status = 'committed'
          AND NEW.action_type = 'approve_ticket_batch'
          AND EXISTS (
            SELECT 1
            FROM operator_protected_artifact_bindings AS binding
            WHERE binding.action_id = NEW.action_id
              AND (
                SELECT COUNT(*)
                FROM operator_protected_artifact_offer_revision_links AS link
                WHERE link.ticket_artifact_id = binding.ticket_artifact_id
              ) != (
                SELECT COUNT(DISTINCT leg.official_offer_revision_id)
                FROM operator_candidate_ticket_legs AS leg
                WHERE leg.candidate_ticket_id = binding.candidate_ticket_id
              )
          )
        BEGIN
          SELECT RAISE(
            ABORT,
            'protected artifact requires complete ordered offer coverage'
          );
        END
        """
    )

    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_confirmation_challenge_typed_binding
        BEFORE INSERT ON operator_confirmation_challenge_revisions
        WHEN NOT EXISTS (
          SELECT 1
          FROM actions AS action
          JOIN operator_protected_artifact_bindings AS binding
            ON binding.ticket_artifact_id = NEW.ticket_artifact_id
          WHERE action.action_id = NEW.action_id
            AND action.action_type = 'issue_ticket_confirmation'
            AND action.actor_role = 'judge_operator'
            AND action.status IN ('accepted', 'committed')
            AND binding.lineage_revision_id = NEW.lineage_revision_id
            AND binding.composition_hash = NEW.artifact_composition_hash
        )
        BEGIN
          SELECT RAISE(ABORT, 'confirmation challenge requires its exact typed binding');
        END
        """
    )
    challenge_head_check = """
      SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM operator_confirmation_challenge_revisions AS challenge
        WHERE challenge.challenge_revision_id = NEW.challenge_revision_id
          AND challenge.ticket_artifact_id = NEW.ticket_artifact_id
          AND challenge.challenge_family_id = NEW.challenge_family_id
          AND challenge.revision_no = NEW.revision_no
          AND NOT EXISTS (
            SELECT 1 FROM operator_confirmation_challenge_revisions AS child
            WHERE child.supersedes_revision_id = challenge.challenge_revision_id
          )
          AND NOT EXISTS (
            SELECT 1 FROM operator_artifact_terminal_receipts AS terminal
            WHERE terminal.ticket_artifact_id = NEW.ticket_artifact_id
          )
      ) THEN RAISE(ABORT, 'confirmation head must reference the current open leaf') END;
    """
    for operation in ("INSERT", "UPDATE"):
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER operator_confirmation_challenge_head_{operation.lower()}
            BEFORE {operation} ON operator_confirmation_challenge_heads
            BEGIN
              {challenge_head_check}
            END
            """
        )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_artifact_terminal_exact_challenge
        BEFORE INSERT ON operator_artifact_terminal_receipts
        WHEN NEW.challenge_revision_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM operator_confirmation_challenge_revisions
            WHERE challenge_revision_id = NEW.challenge_revision_id
              AND ticket_artifact_id = NEW.ticket_artifact_id
          )
        BEGIN
          SELECT RAISE(ABORT, 'artifact terminal challenge belongs to another artifact');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_artifact_terminal_typed_action
        BEFORE INSERT ON operator_artifact_terminal_receipts
        WHEN NOT EXISTS (
          SELECT 1
          FROM actions AS action
          WHERE action.action_id = NEW.action_id
            AND action.status IN ('accepted', 'committed')
            AND (
              (NEW.terminal_reason = 'actual_placement_confirmed'
               AND action.action_type = 'confirm_ticket_placement'
               AND action.actor_role = 'judge_operator')
              OR (NEW.terminal_reason = 'human_no_ticket'
                  AND action.action_type = 'record_no_ticket'
                  AND action.actor_role = 'judge_operator')
              OR (NEW.terminal_reason IN (
                    'confirmation_not_requested',
                    'deadline_unconfirmed'
                  )
                  AND (
                    (action.action_type = 'mark_ticket_shadow'
                     AND action.actor_role = 'deterministic_system')
                    OR (action.action_type IN (
                          'record_no_ticket',
                          'supersede_no_ticket'
                        )
                        AND action.actor_role = 'judge_operator')
                  ))
              OR (NEW.terminal_reason IN (
                    'official_deadline_shortened',
                    'official_offer_cancelled'
                  )
                  AND action.action_type = 'import_official_sale_slate'
                  AND action.actor_role = 'deterministic_system')
            )
        )
        BEGIN
          SELECT RAISE(ABORT, 'artifact terminal requires its exact typed Action');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_artifact_terminal_close_head
        AFTER INSERT ON operator_artifact_terminal_receipts
        BEGIN
          DELETE FROM operator_confirmation_challenge_heads
          WHERE ticket_artifact_id = NEW.ticket_artifact_id;
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_review_eligibility_exact_source
        BEFORE INSERT ON operator_review_eligibility_facts
        WHEN NOT EXISTS (
          SELECT 1
          FROM actions AS action
          WHERE action.action_id = NEW.action_id
            AND action.status IN ('accepted', 'committed')
            AND (
              (NEW.terminal_trigger = 'no_ticket'
               AND EXISTS (
                 SELECT 1
                 FROM operator_no_ticket_revisions AS no_ticket
                 WHERE no_ticket.no_ticket_revision_id = NEW.no_ticket_revision_id
                   AND no_ticket.action_id = NEW.action_id
                   AND no_ticket.task_family_id = NEW.task_family_id
                   AND no_ticket.work_item_id = NEW.work_item_id
                   AND no_ticket.task_snapshot_hash = NEW.task_snapshot_hash
               ))
              OR (NEW.terminal_trigger = 'artifact_terminal'
                  AND EXISTS (
                    SELECT 1
                    FROM operator_artifact_terminal_receipts AS terminal
                    JOIN operator_artifact_work_item_links AS work_link
                      ON work_link.ticket_artifact_id = terminal.ticket_artifact_id
                    WHERE terminal.artifact_terminal_receipt_id =
                          NEW.artifact_terminal_receipt_id
                      AND terminal.action_id = NEW.action_id
                      AND terminal.terminal_reason != 'official_offer_cancelled'
                      AND work_link.task_family_id = NEW.task_family_id
                      AND work_link.work_item_id = NEW.work_item_id
                      AND work_link.task_snapshot_hash = NEW.task_snapshot_hash
                  ))
              OR (NEW.terminal_trigger = 'official_cancellation'
                  AND EXISTS (
                    SELECT 1
                    FROM operator_artifact_terminal_receipts AS terminal
                    JOIN operator_artifact_work_item_links AS work_link
                      ON work_link.ticket_artifact_id = terminal.ticket_artifact_id
                    WHERE terminal.artifact_terminal_receipt_id =
                          NEW.artifact_terminal_receipt_id
                      AND terminal.action_id = NEW.action_id
                      AND terminal.terminal_reason = 'official_offer_cancelled'
                      AND work_link.task_family_id = NEW.task_family_id
                      AND work_link.work_item_id = NEW.work_item_id
                      AND work_link.task_snapshot_hash = NEW.task_snapshot_hash
                  ))
            )
        )
        BEGIN
          SELECT RAISE(
            ABORT,
            'review eligibility requires its exact creating Action and terminal source'
          );
        END
        """
    )

    immutable_tables = (
        "operator_ticket_decision_lineage_revisions",
        "operator_ticket_decision_lineage_items",
        "operator_ticket_audit_override_receipts",
        "operator_candidate_generation_override_links",
        "operator_no_ticket_revisions",
        "operator_no_ticket_offer_scopes",
        "operator_no_ticket_artifact_scopes",
        "operator_no_ticket_command_receipts",
        "operator_artifact_work_item_links",
        "operator_protected_artifact_bindings",
        "operator_protected_artifact_offer_revision_links",
        "operator_confirmation_challenge_revisions",
        "operator_artifact_terminal_receipts",
        "operator_review_eligibility_facts",
    )
    for table_name in immutable_tables:
        for operation in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"""
                CREATE TRIGGER {table_name}_no_{operation.lower()}
                BEFORE {operation} ON {table_name}
                BEGIN
                  SELECT RAISE(ABORT, '{table_name} is append-only');
                END
                """
            )

    child_revision_guards = (
        (
            "operator_ticket_decision_lineage_items",
            "operator_ticket_decision_lineage_revisions AS revision "
            "ON revision.lineage_revision_id = NEW.lineage_revision_id",
        ),
        (
            "operator_candidate_generation_override_links",
            "operator_ticket_audit_override_receipts AS revision "
            "ON revision.ticket_audit_override_receipt_id = "
            "NEW.override_receipt_id",
        ),
        (
            "operator_no_ticket_offer_scopes",
            "operator_no_ticket_revisions AS revision "
            "ON revision.no_ticket_revision_id = NEW.no_ticket_revision_id",
        ),
        (
            "operator_no_ticket_artifact_scopes",
            "operator_no_ticket_revisions AS revision "
            "ON revision.no_ticket_revision_id = NEW.no_ticket_revision_id",
        ),
        (
            "operator_protected_artifact_offer_revision_links",
            "operator_protected_artifact_bindings AS revision "
            "ON revision.ticket_artifact_id = NEW.ticket_artifact_id",
        ),
    )
    for table_name, revision_join in child_revision_guards:
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER {table_name}_no_late_insert
            BEFORE INSERT ON {table_name}
            WHEN EXISTS (
              SELECT 1
              FROM actions AS action
              JOIN {revision_join}
              WHERE action.action_id = revision.action_id
                AND action.status = 'committed'
            )
            BEGIN
              SELECT RAISE(ABORT, '{table_name} is append-only after commit');
            END
            """
        )

    connection.execute(
        insert(schema.action_permissions),
        [
            {
                "policy_version_id": "governance-v1",
                "action_type": action_type,
                "actor_role": "judge_operator",
            }
            for action_type in (
                "record_ticket_audit_override",
                "record_no_ticket",
                "supersede_no_ticket",
            )
        ],
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name='governance_kernel',
        fingerprint='policy_versions+actions+action_permissions+seed(governance-v1)',
        apply=_apply_governance_kernel,
    ),
    Migration(
        version=2,
        name='evidence_kernel',
        fingerprint='source_runs+source_artifacts+artifact_retrievals',
        apply=_apply_evidence_kernel,
    ),
    Migration(
        version=3,
        name='football_identity',
        fingerprint='competitions..entity_merges+team_alias_seed+identity_permissions',
        apply=_apply_football_identity,
    ),
    Migration(
        version=4,
        name='market_definitions',
        fingerprint='market_defs+selection_defs(had,hhad,ttg,crs)+market_permissions',
        apply=_apply_market,
    ),
    Migration(
        version=5,
        name='football_context',
        fingerprint='persons+role_assignments+person_match_statuses+lineup_entries',
        apply=_apply_context,
    ),
    Migration(
        version=6,
        name='football_evidence',
        fingerprint='claims..observation_claims+evidence_permissions',
        apply=_apply_evidence,
    ),
    Migration(
        version=7,
        name='decision',
        fingerprint='decision_sessions..scenarios+decision_permissions',
        apply=_apply_decision,
    ),
    Migration(
        version=8,
        name='finance',
        fingerprint='budget_policies..ticket_settlements+finance_permissions',
        apply=_apply_finance,
    ),
    Migration(
        version=9,
        name='finance_entry_odds',
        fingerprint='bet_legs+entry_odds(guarded_alter)',
        apply=_apply_finance_entry_odds,
    ),
    Migration(
        version=10,
        name='product_workflow',
        fingerprint=(
            'adjudications+flags+predictions+precedents+agent_proposals+'
            'outbox+workflow_permissions'
        ),
        apply=_apply_product_workflow,
    ),
    Migration(
        version=11,
        name='m3_proposal_citations',
        fingerprint='agent_proposals+cutoff+prompt+ai_only_create',
        apply=_apply_m3_proposal_citations,
    ),
    Migration(
        version=12,
        name="protected_ticket_workbench",
        fingerprint=(
            "ticket_batch_revisions+audited_ticket_artifacts+"
            "ticket_confirmation_challenges+ticket_placements+judge_only_permissions"
        ),
        apply=_apply_protected_tickets,
    ),
    Migration(
        version=13,
        name="scoreboard_authority",
        fingerprint=(
            "scoreboard_observations+scoreboard_shadow_reviews+"
            "scoreboard_authority+role_separated_permissions"
        ),
        apply=_apply_scoreboard_authority,
    ),
    Migration(
        version=14,
        name="reliability_governance",
        fingerprint=(
            "reliability_evidence+release_approvals+role_separated_permissions"
        ),
        apply=_apply_reliability_governance,
    ),
    Migration(
        version=15,
        name='prediction_subjects',
        fingerprint='predictions+subject_type+subject_id+match_nullable+grade_permission',
        apply=_apply_prediction_subjects,
    ),
    Migration(
        version=16,
        name="ticket_shadows",
        fingerprint="ticket_shadow_records+deterministic_system_permission",
        apply=_apply_ticket_shadows,
    ),
    Migration(
        version=17,
        name="operator_official_sale",
        fingerprint=(
            "official_sale_slate_revisions+official_offer_families+"
            "official_offer_revisions+official_schedule_check_receipts_v4+"
            "linear_revision_triggers+operator_sale_permissions"
        ),
        apply=_apply_operator_official_sale,
    ),
    Migration(
        version=18,
        name="operator_evidence_intake",
        fingerprint=(
            "operator_evidence_intake_receipts+operator_evidence_intake_objects+"
            "operator_evidence_coverage_receipts+strict_counts+deterministic_permission"
        ),
        apply=_apply_operator_evidence_intake,
    ),
    Migration(
        version=19,
        name="operator_evidence_freeze",
        fingerprint=(
            "operator_evidence_freeze_requests+operator_task_evidence_bundle_revisions+"
            "operator_task_evidence_bundle_items+operator_worker_jobs+linear_revision+"
            "atomic_item_counts+typed_result_actions+immutable_rows+role_separated_permissions"
        ),
        apply=_apply_operator_evidence_freeze,
    ),
    Migration(
        version=20,
        name="operator_judgment_baseline",
        fingerprint=(
            "market_prior_baseline+baseline_envelope+operator_match_judgment+"
            "judgment_prescription+normalized_children+canonical_decimal_text+"
            "linear_revision+complete_child_append_only+typed_result_actions+"
            "role_separated_permissions"
        ),
        apply=_apply_operator_judgment_baseline,
    ),
    Migration(
        version=21,
        name="operator_candidate_comparison",
        fingerprint=(
            "candidate_generation+candidate_sets+candidate_tickets+candidate_metrics+"
            "candidate_audits+revisioned_candidate_selection+zucai_fixed_prize_policy+"
            "directional_crs_aggregates+three_way_partitions+complete_child_append_only+"
            "typed_actions+worker_result_binding+exact_quote_bindings+audit_policy_version"
        ),
        apply=_apply_operator_candidate_comparison,
    ),
    Migration(
        version=22,
        name="operator_deployment_adjudication",
        fingerprint=(
            "ticket_decision_lineage+ticket_audit_override+candidate_override_links+"
            "no_ticket_revisions_and_scopes+protected_artifact_bindings+"
            "empty_confirmation_challenge_schema+artifact_terminal_receipts+"
            "review_eligibility_facts+typed_terminal_provenance+"
            "complete_ordered_offer_coverage+review_source_binding+"
            "approved_lineage_revision+linear_revision+append_only+judge_permissions"
        ),
        apply=_apply_operator_deployment_adjudication,
    ),
)


def _validate_sequence(migrations: tuple[Migration, ...]) -> None:
    versions = [migration.version for migration in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationDriftError(
            f'migration versions must be a gap-free ascending sequence from 1, got {versions}'
        )


def _applied_checksums(connection: Connection) -> dict[int, str]:
    rows = connection.execute(
        select(schema.schema_migrations.c.version, schema.schema_migrations.c.checksum)
    ).all()
    return {row.version: row.checksum for row in rows}


def run_migrations(
    engine: Engine,
    migrations: tuple[Migration, ...] = MIGRATIONS,
) -> MigrationReport:
    _validate_sequence(migrations)
    applied: list[int] = []
    with engine.begin() as connection:
        schema.schema_migrations.create(connection, checkfirst=True)
        existing = _applied_checksums(connection)
        for migration in migrations:
            recorded = existing.get(migration.version)
            if recorded is not None:
                if recorded != migration.checksum:
                    raise MigrationDriftError(
                        f'migration {migration.version} checksum drift'
                    )
                continue
            migration.apply(connection)
            connection.execute(
                insert(schema.schema_migrations).values(
                    version=migration.version,
                    name=migration.name,
                    checksum=migration.checksum,
                    applied_at=datetime.now(UTC).isoformat(),
                )
            )
            applied.append(migration.version)
    return MigrationReport(applied_versions=tuple(applied))


def migration_status(engine: Engine) -> MigrationStatus:
    if not inspect(engine).has_table('schema_migrations'):
        return MigrationStatus(current_version=0, applied_versions=())
    with engine.connect() as connection:
        versions = tuple(
            sorted(connection.execute(select(schema.schema_migrations.c.version)).scalars().all())
        )
    current = versions[-1] if versions else 0
    return MigrationStatus(current_version=current, applied_versions=versions)
