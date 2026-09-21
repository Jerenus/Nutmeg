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

from sqlalchemy import Connection, Engine, delete, func, insert, inspect, select, text
from sqlalchemy.schema import CreateIndex, CreateTable

from nutmeg.ontology.errors import MigrationDriftError
from nutmeg.ontology.identity.models import EntityType, TeamKind, mint_id
from nutmeg.ontology.repository import (
    schema,
    schema_capital,
    schema_context,
    schema_decision,
    schema_discovery,
    schema_discovery_generation,
    schema_discovery_promotion,
    schema_evidence,
    schema_finance,
    schema_identity,
    schema_market,
    schema_operator_decision,
    schema_operator_result,
    schema_operator_review,
    schema_operator_sale,
    schema_reliability,
    schema_rsi,
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


def _legacy_confirmation_conflict(detail: str) -> None:
    raise ValueError(f"legacy_confirmation_conflict: {detail}")


def _stable_migration_id(prefix: str, document: dict[str, object]) -> str:
    digest = hashlib.sha256(_canonical_json(document).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest}"


def _legacy_confirmation_action_ids(connection: Connection) -> dict[str, str]:
    result: dict[str, str] = {}
    rows = connection.execute(
        select(schema.actions.c.action_id, schema.actions.c.result_refs_json).where(
            schema.actions.c.action_type == "issue_ticket_confirmation",
            schema.actions.c.status == "committed",
        )
    ).mappings()
    for row in rows:
        try:
            refs = json.loads(str(row["result_refs_json"]))
        except (TypeError, json.JSONDecodeError):
            _legacy_confirmation_conflict("issue Action has malformed result refs")
        for ref in refs:
            if not isinstance(ref, dict) or ref.get("object_type") != "ticket_confirmation":
                continue
            confirmation_id = ref.get("object_id")
            if not isinstance(confirmation_id, str) or not confirmation_id:
                _legacy_confirmation_conflict("issue Action has an invalid confirmation ref")
            if confirmation_id in result:
                _legacy_confirmation_conflict(
                    f"confirmation {confirmation_id} has more than one issuing Action"
                )
            result[confirmation_id] = str(row["action_id"])
    return result


def _migration_datetime(value: object, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        _legacy_confirmation_conflict(f"{label} is not ISO 8601")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _legacy_confirmation_conflict(f"{label} is not timezone-aware")
    return parsed


def _legacy_artifact_binding(
    connection: Connection,
    ticket_artifact_id: str,
) -> dict[str, str]:
    row = connection.execute(
        text(
            "SELECT composition_hash, lineage_revision_id, frozen_deadline_at "
            "FROM operator_protected_artifact_bindings "
            "WHERE ticket_artifact_id = :ticket_artifact_id"
        ),
        {"ticket_artifact_id": ticket_artifact_id},
    ).mappings().one_or_none()
    if row is None:
        _legacy_confirmation_conflict(
            f"artifact {ticket_artifact_id} has no normalized binding"
        )
    return {name: str(row[name]) for name in row}


def _legacy_artifact_effective_cutoff(
    connection: Connection,
    ticket_artifact_id: str,
    binding: dict[str, str],
) -> str:
    source_offer_ids = tuple(
        connection.execute(
            text(
                "SELECT official_offer_revision_id "
                "FROM operator_protected_artifact_offer_revision_links "
                "WHERE ticket_artifact_id = :ticket_artifact_id ORDER BY offer_index"
            ),
            {"ticket_artifact_id": ticket_artifact_id},
        ).scalars()
    )
    if not source_offer_ids:
        _legacy_confirmation_conflict(
            f"artifact {ticket_artifact_id} has no normalized offer links"
        )

    cutoff_values = [binding["frozen_deadline_at"]]
    for source_offer_id in source_offer_ids:
        current = connection.execute(
            text(
                "SELECT current_offer.sale_deadline_at "
                "FROM official_offer_revisions AS source_offer "
                "JOIN official_offer_families AS family "
                "ON family.official_offer_family_id = "
                "source_offer.official_offer_family_id "
                "JOIN official_sale_slate_revisions AS current_slate "
                "ON current_slate.lane = family.lane "
                "AND current_slate.business_key = family.business_key "
                "JOIN official_offer_revisions AS current_offer "
                "ON current_offer.official_offer_family_id = "
                "family.official_offer_family_id "
                "AND current_offer.slate_revision_id = current_slate.slate_revision_id "
                "WHERE source_offer.official_offer_revision_id = :source_offer_id "
                "AND NOT EXISTS ("
                "SELECT 1 FROM official_sale_slate_revisions AS child "
                "WHERE child.supersedes_slate_revision_id = "
                "current_slate.slate_revision_id)"
            ),
            {"source_offer_id": source_offer_id},
        ).scalar_one_or_none()
        if current is None:
            _legacy_confirmation_conflict(
                f"offer {source_offer_id} has no current official revision"
            )
        cutoff_values.append(str(current))

    parsed = [
        (_migration_datetime(value, label="effective cutoff"), value)
        for value in cutoff_values
    ]
    return str(min(parsed, key=lambda item: item[0])[1])


def _legacy_terminal_source(
    connection: Connection,
    ticket_artifact_id: str,
    legacy_rows: list[dict[str, object]],
) -> tuple[str, str, str, str, str | None] | None:
    consumed = [
        row
        for row in legacy_rows
        if row["consumed_at"] is not None or row["consumed_by_action_id"] is not None
    ]
    if any(
        (row["consumed_at"] is None) != (row["consumed_by_action_id"] is None)
        for row in consumed
    ):
        _legacy_confirmation_conflict("legacy consumed fields are incomplete")
    if len(consumed) > 1:
        _legacy_confirmation_conflict(
            f"artifact {ticket_artifact_id} has more than one consumed challenge"
        )

    placement = connection.execute(
        text(
            "SELECT placed_at, action_id FROM ticket_placements "
            "WHERE ticket_artifact_id = :ticket_artifact_id"
        ),
        {"ticket_artifact_id": ticket_artifact_id},
    ).mappings().one_or_none()
    shadow = connection.execute(
        text(
            "SELECT confirmation_id, reason, marked_at, action_id "
            "FROM ticket_shadow_records "
            "WHERE ticket_artifact_id = :ticket_artifact_id"
        ),
        {"ticket_artifact_id": ticket_artifact_id},
    ).mappings().one_or_none()
    if placement is not None and shadow is not None:
        _legacy_confirmation_conflict(
            f"artifact {ticket_artifact_id} has both placement and shadow rows"
        )
    if placement is not None:
        if len(consumed) != 1:
            _legacy_confirmation_conflict(
                f"placed artifact {ticket_artifact_id} has no unique consumed challenge"
            )
        consumed_row = consumed[0]
        if consumed_row["consumed_by_action_id"] != placement["action_id"]:
            _legacy_confirmation_conflict(
                f"placed artifact {ticket_artifact_id} consumed by another Action"
            )
        return (
            "placed",
            "actual_placement_confirmed",
            str(placement["placed_at"]),
            str(placement["action_id"]),
            str(consumed_row["confirmation_id"]),
        )
    if shadow is not None:
        if consumed:
            _legacy_confirmation_conflict(
                f"shadow artifact {ticket_artifact_id} has a consumed challenge"
            )
        allowed_reasons = {
            "confirmation_not_requested",
            "deadline_unconfirmed",
            "human_no_ticket",
            "official_deadline_shortened",
            "official_offer_cancelled",
        }
        if shadow["reason"] not in allowed_reasons:
            _legacy_confirmation_conflict(
                f"shadow artifact {ticket_artifact_id} has an unknown reason"
            )
        return (
            "shadow",
            str(shadow["reason"]),
            str(shadow["marked_at"]),
            str(shadow["action_id"]),
            str(shadow["confirmation_id"]),
        )
    if consumed:
        _legacy_confirmation_conflict(
            f"artifact {ticket_artifact_id} consumed without a terminal row"
        )
    return None


def _legacy_confirmation_rows(
    connection: Connection,
) -> dict[str, list[dict[str, object]]]:
    legacy_by_artifact: dict[str, list[dict[str, object]]] = {}
    rows = connection.execute(
        select(schema_tickets.ticket_confirmation_challenges).order_by(
            schema_tickets.ticket_confirmation_challenges.c.ticket_artifact_id,
            schema_tickets.ticket_confirmation_challenges.c.issued_at,
            schema_tickets.ticket_confirmation_challenges.c.confirmation_id,
        )
    ).mappings()
    for row in rows:
        values = dict(row)
        legacy_by_artifact.setdefault(str(values["ticket_artifact_id"]), []).append(
            values
        )
    return legacy_by_artifact


def _preflight_legacy_confirmation_challenges(connection: Connection) -> None:
    legacy_by_artifact = _legacy_confirmation_rows(connection)
    if not legacy_by_artifact:
        return
    issuing_actions = _legacy_confirmation_action_ids(connection)
    for ticket_artifact_id, legacy_rows in legacy_by_artifact.items():
        existing_count = connection.execute(
            select(func.count())
            .select_from(schema_tickets.operator_confirmation_challenge_revisions)
            .where(
                schema_tickets.operator_confirmation_challenge_revisions.c.ticket_artifact_id
                == ticket_artifact_id
            )
        ).scalar_one()
        if existing_count:
            _legacy_confirmation_conflict(
                f"artifact {ticket_artifact_id} mixes legacy and revisioned challenges"
            )
        binding = _legacy_artifact_binding(connection, ticket_artifact_id)
        _legacy_artifact_effective_cutoff(connection, ticket_artifact_id, binding)
        for legacy in legacy_rows:
            legacy_id = str(legacy["confirmation_id"])
            if legacy_id not in issuing_actions:
                _legacy_confirmation_conflict(
                    f"confirmation {legacy_id} has no committed issuing Action"
                )
        terminal = _legacy_terminal_source(
            connection,
            ticket_artifact_id,
            legacy_rows,
        )
        existing_terminal = connection.execute(
            select(schema_tickets.operator_artifact_terminal_receipts).where(
                schema_tickets.operator_artifact_terminal_receipts.c.ticket_artifact_id
                == ticket_artifact_id
            )
        ).mappings().one_or_none()
        if terminal is None or existing_terminal is None:
            continue
        kind, reason, _at, action_id, _legacy_id = terminal
        if (
            existing_terminal["terminal_kind"] != kind
            or existing_terminal["terminal_reason"] != reason
            or existing_terminal["action_id"] != action_id
        ):
            _legacy_confirmation_conflict(
                f"artifact {ticket_artifact_id} has contradictory terminal evidence"
            )


def _reconcile_legacy_confirmation_challenges(connection: Connection) -> None:
    legacy_by_artifact = _legacy_confirmation_rows(connection)
    if not legacy_by_artifact:
        return

    issuing_actions = _legacy_confirmation_action_ids(connection)
    for ticket_artifact_id, legacy_rows in legacy_by_artifact.items():
        existing_count = connection.execute(
            select(func.count())
            .select_from(schema_tickets.operator_confirmation_challenge_revisions)
            .where(
                schema_tickets.operator_confirmation_challenge_revisions.c.ticket_artifact_id
                == ticket_artifact_id
            )
        ).scalar_one()
        if existing_count:
            _legacy_confirmation_conflict(
                f"artifact {ticket_artifact_id} mixes legacy and revisioned challenges"
            )
        binding = _legacy_artifact_binding(connection, ticket_artifact_id)
        effective_cutoff = _legacy_artifact_effective_cutoff(
            connection,
            ticket_artifact_id,
            binding,
        )
        family_id = _stable_migration_id(
            "challenge-family-legacy",
            {"ticket_artifact_id": ticket_artifact_id},
        )
        revision_by_legacy: dict[str, str] = {}
        predecessor: str | None = None
        for revision_no, legacy in enumerate(legacy_rows, start=1):
            legacy_id = str(legacy["confirmation_id"])
            action_id = issuing_actions.get(legacy_id)
            if action_id is None:
                _legacy_confirmation_conflict(
                    f"confirmation {legacy_id} has no committed issuing Action"
                )
            revision_id = _stable_migration_id(
                "challenge-revision-legacy",
                {"legacy_confirmation_id": legacy_id},
            )
            connection.execute(
                text(
                    "INSERT INTO operator_confirmation_challenge_revisions "
                    "(challenge_revision_id, challenge_family_id, "
                    "legacy_confirmation_id, revision_no, supersedes_revision_id, "
                    "ticket_artifact_id, artifact_composition_hash, "
                    "lineage_revision_id, nonce_hash, issued_at, effective_cutoff_at, "
                    "action_id, legacy_expires_at) VALUES "
                    "(:revision_id, :family_id, :legacy_id, :revision_no, "
                    ":predecessor, :artifact_id, :composition_hash, :lineage_id, "
                    ":nonce_hash, :issued_at, :effective_cutoff, :action_id, "
                    ":legacy_expires_at)"
                ),
                {
                    "revision_id": revision_id,
                    "family_id": family_id,
                    "legacy_id": legacy_id,
                    "revision_no": revision_no,
                    "predecessor": predecessor,
                    "artifact_id": ticket_artifact_id,
                    "composition_hash": binding["composition_hash"],
                    "lineage_id": binding["lineage_revision_id"],
                    "nonce_hash": legacy["nonce_hash"],
                    "issued_at": legacy["issued_at"],
                    "effective_cutoff": effective_cutoff,
                    "action_id": action_id,
                    "legacy_expires_at": legacy["expires_at"],
                },
            )
            revision_by_legacy[legacy_id] = revision_id
            predecessor = revision_id

        terminal = _legacy_terminal_source(
            connection,
            ticket_artifact_id,
            legacy_rows,
        )
        existing_terminal = connection.execute(
            select(schema_tickets.operator_artifact_terminal_receipts).where(
                schema_tickets.operator_artifact_terminal_receipts.c.ticket_artifact_id
                == ticket_artifact_id
            )
        ).mappings().one_or_none()
        if terminal is not None and existing_terminal is not None:
            kind, reason, _at, action_id, _legacy_id = terminal
            if (
                existing_terminal["terminal_kind"] != kind
                or existing_terminal["terminal_reason"] != reason
                or existing_terminal["action_id"] != action_id
            ):
                _legacy_confirmation_conflict(
                    f"artifact {ticket_artifact_id} has contradictory terminal evidence"
                )
        elif terminal is not None:
            kind, reason, terminal_at, action_id, terminal_legacy_id = terminal
            challenge_revision_id = (
                None
                if terminal_legacy_id is None
                else revision_by_legacy.get(terminal_legacy_id)
            )
            if terminal_legacy_id is not None and challenge_revision_id is None:
                _legacy_confirmation_conflict(
                    f"terminal artifact {ticket_artifact_id} references another challenge"
                )
            connection.execute(
                insert(schema_tickets.operator_artifact_terminal_receipts).values(
                    artifact_terminal_receipt_id=_stable_migration_id(
                        "artifact-terminal",
                        {"ticket_artifact_id": ticket_artifact_id, "state": "terminal"},
                    ),
                    ticket_artifact_id=ticket_artifact_id,
                    challenge_revision_id=challenge_revision_id,
                    terminal_kind=kind,
                    terminal_reason=reason,
                    effective_cutoff_at=effective_cutoff,
                    terminal_at=terminal_at,
                    action_id=action_id,
                )
            )

        if terminal is None and existing_terminal is None:
            latest = legacy_rows[-1]
            latest_legacy_id = str(latest["confirmation_id"])
            connection.execute(
                insert(schema_tickets.operator_confirmation_challenge_heads).values(
                    ticket_artifact_id=ticket_artifact_id,
                    challenge_revision_id=revision_by_legacy[latest_legacy_id],
                    challenge_family_id=family_id,
                    revision_no=len(legacy_rows),
                    updated_at=latest["issued_at"],
                )
            )


def _apply_operator_confirmation_ledger(connection: Connection) -> None:
    _preflight_legacy_confirmation_challenges(connection)
    challenge_columns = {
        str(row[1])
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(operator_confirmation_challenge_revisions)"
        ).fetchall()
    }
    if "legacy_expires_at" not in challenge_columns:
        connection.exec_driver_sql(
            "ALTER TABLE operator_confirmation_challenge_revisions "
            "ADD COLUMN legacy_expires_at TEXT"
        )

    _reconcile_legacy_confirmation_challenges(connection)

    connection.exec_driver_sql("DROP TRIGGER operator_artifact_terminal_typed_action")
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
                    OR (NEW.terminal_reason = 'deadline_unconfirmed'
                        AND action.action_type = 'confirm_ticket_placement'
                        AND action.actor_role = 'judge_operator')
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

    ticket_columns = {
        str(row[1])
        for row in connection.exec_driver_sql("PRAGMA table_info(tickets)").fetchall()
    }
    for name, ddl in (
        ("ticket_kind", "TEXT"),
        ("stake_minor", "INTEGER"),
        (
            "fixed_prize_policy_revision_id",
            "TEXT REFERENCES zucai_fixed_prize_policy_revisions"
            "(fixed_prize_policy_revision_id) ON DELETE RESTRICT",
        ),
    ):
        if name not in ticket_columns:
            connection.exec_driver_sql(f"ALTER TABLE tickets ADD COLUMN {name} {ddl}")

    cash_columns = {
        str(row[1])
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(cash_transactions)"
        ).fetchall()
    }
    for name, ddl in (("amount_minor", "INTEGER"), ("currency", "TEXT")):
        if name not in cash_columns:
            connection.exec_driver_sql(
                f"ALTER TABLE cash_transactions ADD COLUMN {name} {ddl}"
            )

    immutable_tables = (
        schema_operator_result.operator_ticket_notes,
        schema_operator_result.operator_ticket_note_legs,
        schema_operator_result.operator_placement_cash_links,
        schema_operator_result.operator_telegram_callback_attestations,
    )
    for table in (
        *immutable_tables,
        schema_operator_result.operator_telegram_owner_heartbeats,
    ):
        table.create(connection)

    for table in immutable_tables:
        for operation in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"""
                CREATE TRIGGER {table.name}_no_{operation.lower()}
                BEFORE {operation} ON {table.name}
                BEGIN
                  SELECT RAISE(ABORT, '{table.name} is append-only');
                END
                """
            )

    connection.exec_driver_sql(
        """
        CREATE TRIGGER tickets_v2_money_insert
        BEFORE INSERT ON tickets
        WHEN (NEW.ticket_kind IS NOT NULL OR NEW.stake_minor IS NOT NULL
              OR NEW.fixed_prize_policy_revision_id IS NOT NULL)
          AND NOT (
            NEW.ticket_kind IN ('jczq_pass', 'sfc', 'renjiu')
            AND NEW.stake_minor > 0
            AND CAST(ROUND(NEW.total_stake * 100) AS INTEGER) = NEW.stake_minor
            AND (
              (NEW.ticket_kind = 'jczq_pass'
               AND NEW.fixed_prize_policy_revision_id IS NULL)
              OR (NEW.ticket_kind IN ('sfc', 'renjiu')
                  AND NEW.fixed_prize_policy_revision_id IS NOT NULL)
            )
          )
        BEGIN
          SELECT RAISE(ABORT, 'v2 ticket minor-unit fields do not reconcile');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER cash_transactions_v2_money_insert
        BEFORE INSERT ON cash_transactions
        WHEN (NEW.amount_minor IS NOT NULL OR NEW.currency IS NOT NULL)
          AND NOT (
            NEW.amount_minor IS NOT NULL
            AND NEW.amount_minor != 0
            AND NEW.currency IS NOT NULL
            AND length(NEW.currency) = 3
            AND CAST(ROUND(NEW.amount * 100) AS INTEGER) = NEW.amount_minor
            AND EXISTS (
              SELECT 1 FROM cash_accounts AS account
              WHERE account.account_id = NEW.account_id
                AND account.currency = NEW.currency
            )
          )
        BEGIN
          SELECT RAISE(ABORT, 'v2 cash minor-unit fields do not reconcile');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_ticket_note_parent_consistency
        BEFORE INSERT ON operator_ticket_notes
        WHEN NOT EXISTS (
          SELECT 1
          FROM tickets AS ticket
          WHERE ticket.ticket_id = NEW.ticket_id
            AND ticket.ticket_kind = NEW.ticket_kind
            AND ticket.currency = NEW.currency
            AND ticket.fixed_prize_policy_revision_id
                IS NEW.fixed_prize_policy_revision_id
        )
        BEGIN
          SELECT RAISE(ABORT, 'ticket note policy or currency does not match ticket');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_ticket_note_fixed_policy
        BEFORE INSERT ON operator_ticket_notes
        WHEN NEW.fixed_prize_policy_revision_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1
            FROM zucai_fixed_prize_policy_revisions AS policy
            WHERE policy.fixed_prize_policy_revision_id =
                  NEW.fixed_prize_policy_revision_id
              AND policy.ticket_kind = NEW.ticket_kind
              AND policy.currency = NEW.currency
              AND policy.standard_unit_stake_minor = NEW.unit_stake_minor
          )
        BEGIN
          SELECT RAISE(ABORT, 'ticket note does not match fixed-prize policy');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_ticket_note_leg_parent_consistency
        BEFORE INSERT ON operator_ticket_note_legs
        WHEN NOT EXISTS (
          SELECT 1
          FROM operator_ticket_notes AS note
          WHERE note.ticket_note_id = NEW.ticket_note_id
            AND note.fixed_prize_policy_revision_id
                IS NEW.fixed_prize_policy_revision_id
            AND note.action_id = NEW.action_id
        )
        BEGIN
          SELECT RAISE(ABORT, 'ticket note leg policy or Action does not match note');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_placement_cash_link_reconciliation
        BEFORE INSERT ON operator_placement_cash_links
        WHEN NOT EXISTS (
          SELECT 1
          FROM tickets AS ticket
          JOIN cash_transactions AS cash
            ON cash.transaction_id = NEW.transaction_id
           AND cash.ticket_id = ticket.ticket_id
          JOIN ticket_placements AS placement
            ON placement.ticket_id = ticket.ticket_id
           AND placement.action_id = NEW.action_id
          WHERE ticket.ticket_id = NEW.ticket_id
            AND ticket.stake_minor = NEW.stake_minor
            AND ticket.currency = NEW.currency
            AND cash.kind = 'stake'
            AND cash.amount_minor = -NEW.stake_minor
            AND cash.currency = NEW.currency
            AND (
              SELECT COALESCE(SUM(note.stake_minor), 0)
              FROM operator_ticket_notes AS note
              WHERE note.ticket_id = ticket.ticket_id
            ) = NEW.stake_minor
            AND NOT EXISTS (
              SELECT 1
              FROM operator_ticket_notes AS note
              WHERE note.ticket_id = ticket.ticket_id
                AND (note.ticket_artifact_id != placement.ticket_artifact_id
                     OR note.action_id != NEW.action_id)
            )
        )
        BEGIN
          SELECT RAISE(ABORT, 'placement cash link does not reconcile');
        END
        """
    )

    connection.execute(
        insert(schema.action_permissions),
        {
            "policy_version_id": "governance-v1",
            "action_type": "register_telegram_update_owner",
            "actor_role": "deterministic_system",
        },
    )


def _apply_operator_results_settlement(connection: Connection) -> None:
    tables = (
        schema_operator_result.operator_result_set_families,
        schema_operator_result.zucai_prize_table_revisions,
        schema_operator_result.zucai_prize_table_tiers,
        schema_operator_result.operator_result_set_revisions,
        schema_operator_result.operator_result_match_revisions,
        schema_operator_result.operator_result_source_receipts,
        schema_operator_result.operator_outcome_revisions,
        schema_operator_result.operator_settlement_requests,
        schema_operator_result.operator_task_settlement_runs,
        schema_operator_result.operator_task_settlement_skips,
        schema_operator_result.operator_ticket_settlement_revisions,
        schema_operator_result.operator_ticket_note_settlements,
        schema_operator_result.operator_ticket_note_leg_settlements,
        schema_operator_result.operator_settlement_cash_links,
    )
    for table in tables:
        table.create(connection)

    review_columns = {
        str(row[1])
        for row in connection.exec_driver_sql(
            "PRAGMA table_info(operator_review_eligibility_facts)"
        ).fetchall()
    }
    if "settlement_run_id" not in review_columns:
        for trigger_name in (
            "operator_review_eligibility_exact_source",
            "operator_review_eligibility_facts_no_update",
            "operator_review_eligibility_facts_no_delete",
        ):
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger_name}")
        for index_row in connection.exec_driver_sql(
            "PRAGMA index_list(operator_review_eligibility_facts)"
        ).fetchall():
            index_name = str(index_row[1])
            if not index_name.startswith("sqlite_autoindex_"):
                quoted_name = connection.dialect.identifier_preparer.quote(
                    index_name
                )
                connection.exec_driver_sql(f"DROP INDEX {quoted_name}")
        connection.exec_driver_sql(
            "ALTER TABLE operator_review_eligibility_facts "
            "RENAME TO operator_review_eligibility_facts_v23"
        )
        schema_operator_result.operator_review_eligibility_facts.create(connection)
        connection.exec_driver_sql(
            """
            INSERT INTO operator_review_eligibility_facts (
              review_eligibility_fact_id, action_id, fact_index, terminal_trigger,
              task_family_id, work_item_id, task_snapshot_hash,
              no_ticket_revision_id, artifact_terminal_receipt_id, settlement_run_id,
              market_prior_baseline_revision_id, review_kind, readiness_condition,
              content_hash, created_at
            )
            SELECT
              review_eligibility_fact_id, action_id, fact_index, terminal_trigger,
              task_family_id, work_item_id, task_snapshot_hash,
              no_ticket_revision_id, artifact_terminal_receipt_id, NULL,
              market_prior_baseline_revision_id, review_kind, readiness_condition,
              content_hash, created_at
            FROM operator_review_eligibility_facts_v23
            """
        )
        connection.exec_driver_sql(
            "DROP TABLE operator_review_eligibility_facts_v23"
        )

    connection.exec_driver_sql(
        "DROP TRIGGER IF EXISTS operator_review_eligibility_exact_source"
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
              OR (NEW.terminal_trigger = 'settlement'
                  AND action.action_type = 'settle_task'
                  AND action.actor_role = 'deterministic_system'
                  AND EXISTS (
                    SELECT 1
                    FROM operator_task_settlement_runs AS run
                    WHERE run.settlement_run_id = NEW.settlement_run_id
                      AND run.settle_action_id = NEW.action_id
                      AND run.task_family_id = NEW.task_family_id
                      AND run.work_item_id = NEW.work_item_id
                      AND run.work_item_snapshot_hash = NEW.task_snapshot_hash
                      AND run.settlement_state IN ('settled', 'corrected')
                      AND run.settled_ticket_count > 0
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
    for operation in ("UPDATE", "DELETE"):
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER IF NOT EXISTS
              operator_review_eligibility_facts_no_{operation.lower()}
            BEFORE {operation} ON operator_review_eligibility_facts
            BEGIN
              SELECT RAISE(
                ABORT,
                'operator_review_eligibility_facts is append-only'
              );
            END
            """
        )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER IF NOT EXISTS operator_review_eligibility_enqueue_materialization
        AFTER INSERT ON operator_review_eligibility_facts
        BEGIN
          INSERT INTO operator_worker_jobs (
            worker_job_id, job_kind, source_object_type, source_object_id, state,
            lease_owner, lease_expires_at, attempt_count, available_at,
            last_error_code, result_action_id, result_object_type, result_object_id,
            created_at, updated_at
          ) VALUES (
            'review-materialization:' || NEW.review_eligibility_fact_id,
            'review_materialization', 'operator_review_eligibility_fact',
            NEW.review_eligibility_fact_id, 'queued', NULL, NULL, 0,
            NEW.created_at, NULL, NULL, NULL, NULL, NEW.created_at, NEW.created_at
          );
        END
        """
    )
    connection.exec_driver_sql(
        """
        INSERT INTO operator_worker_jobs (
          worker_job_id, job_kind, source_object_type, source_object_id, state,
          lease_owner, lease_expires_at, attempt_count, available_at,
          last_error_code, result_action_id, result_object_type, result_object_id,
          created_at, updated_at
        )
        SELECT
          'review-materialization:' || fact.review_eligibility_fact_id,
          'review_materialization', 'operator_review_eligibility_fact',
          fact.review_eligibility_fact_id, 'queued', NULL, NULL, 0,
          fact.created_at, NULL, NULL, NULL, NULL, fact.created_at, fact.created_at
        FROM operator_review_eligibility_facts AS fact
        WHERE NOT EXISTS (
          SELECT 1 FROM operator_worker_jobs AS job
          WHERE job.job_kind = 'review_materialization'
            AND job.source_object_type = 'operator_review_eligibility_fact'
            AND job.source_object_id = fact.review_eligibility_fact_id
        )
        """
    )

    for table in tables:
        for operation in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"""
                CREATE TRIGGER {table.name}_no_{operation.lower()}
                BEFORE {operation} ON {table.name}
                BEGIN
                  SELECT RAISE(ABORT, '{table.name} is append-only');
                END
                """
            )

    linear_revisions = (
        (
            "operator_result_set",
            "operator_result_set_revisions",
            "result_set_revision_id",
            "result_set_family_id",
            "result_set_family_id = NEW.result_set_family_id "
            "AND lane = NEW.lane AND business_key = NEW.business_key "
            "AND task_family_id = NEW.task_family_id",
        ),
        (
            "operator_outcome",
            "operator_outcome_revisions",
            "outcome_revision_id",
            "outcome_family_id",
            "outcome_family_id = NEW.outcome_family_id "
            "AND match_id = NEW.match_id",
        ),
        (
            "zucai_prize_table",
            "zucai_prize_table_revisions",
            "prize_table_revision_id",
            "prize_table_family_id",
            "prize_table_family_id = NEW.prize_table_family_id "
            "AND issue = NEW.issue AND currency = NEW.currency",
        ),
        (
            "operator_ticket_settlement",
            "operator_ticket_settlement_revisions",
            "settlement_revision_id",
            "settlement_family_id",
            "settlement_family_id = NEW.settlement_family_id "
            "AND ticket_id = NEW.ticket_id",
        ),
    )
    for prefix, table_name, id_column, family_column, parent_scope in linear_revisions:
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
            CREATE TRIGGER {prefix}_root_revision_no
            BEFORE INSERT ON {table_name}
            WHEN NEW.supersedes_revision_id IS NULL AND NEW.revision_no != 1
            BEGIN
              SELECT RAISE(ABORT, 'root revision_no must be 1');
            END
            """
        )
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER {prefix}_linear_child
            BEFORE INSERT ON {table_name}
            WHEN NEW.supersedes_revision_id IS NOT NULL
            BEGIN
              SELECT CASE WHEN NOT EXISTS (
                SELECT 1 FROM {table_name} AS parent
                WHERE parent.{id_column} = NEW.supersedes_revision_id
                  AND parent.{parent_scope}
                  AND NEW.revision_no = parent.revision_no + 1
              ) THEN RAISE(ABORT, 'revision must directly follow its current family leaf') END;
              SELECT CASE WHEN EXISTS (
                SELECT 1 FROM {table_name} AS child
                WHERE child.supersedes_revision_id = NEW.supersedes_revision_id
              ) THEN RAISE(ABORT, 'revision predecessor already has a child') END;
            END
            """
        )

    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_result_set_typed_action
        BEFORE INSERT ON operator_result_set_revisions
        WHEN NOT EXISTS (
          SELECT 1 FROM actions AS action
          WHERE action.action_id = NEW.action_id
            AND action.action_type = 'import_result_evidence_set'
            AND action.actor_role = 'deterministic_system'
            AND action.status IN ('accepted', 'committed')
            AND (
              NEW.zucai_prize_table_revision_id IS NULL
              OR EXISTS (
                SELECT 1
                FROM zucai_prize_table_revisions AS prize
                WHERE prize.prize_table_revision_id =
                      NEW.zucai_prize_table_revision_id
                  AND prize.action_id = NEW.action_id
              )
            )
        )
        BEGIN
          SELECT RAISE(
            ABORT,
            'result set and prize table require the same import Action'
          );
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER zucai_prize_table_typed_action
        BEFORE INSERT ON zucai_prize_table_revisions
        WHEN NOT EXISTS (
          SELECT 1 FROM actions
          WHERE action_id = NEW.action_id
            AND action_type = 'import_result_evidence_set'
            AND actor_role = 'deterministic_system'
            AND status IN ('accepted', 'committed')
        )
        BEGIN
          SELECT RAISE(ABORT, 'prize table requires its deterministic import Action');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_outcome_typed_action
        BEFORE INSERT ON operator_outcome_revisions
        WHEN NOT EXISTS (
          SELECT 1 FROM actions AS action
          JOIN operator_result_set_revisions AS result_set
            ON result_set.result_set_revision_id = NEW.result_set_revision_id
          WHERE action.action_id = NEW.action_id
            AND action.action_type = 'import_result_evidence_set'
            AND action.actor_role = 'deterministic_system'
            AND action.status IN ('accepted', 'committed')
            AND result_set.action_id = NEW.action_id
        )
        BEGIN
          SELECT RAISE(ABORT, 'Outcome and result set require the same import Action');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_settlement_request_typed_action
        BEFORE INSERT ON operator_settlement_requests
        WHEN NOT EXISTS (
          SELECT 1 FROM actions
          WHERE action_id = NEW.action_id
            AND action_type = 'request_settlement'
            AND actor_role = 'judge_operator'
            AND status IN ('accepted', 'committed')
        )
        BEGIN
          SELECT RAISE(ABORT, 'settlement request requires its judge Action');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_settlement_request_action_exact_result
        BEFORE UPDATE OF status ON actions
        WHEN NEW.status = 'committed'
          AND NEW.action_type = 'request_settlement'
          AND NOT EXISTS (
            SELECT 1
            FROM operator_settlement_requests AS request
            WHERE request.action_id = NEW.action_id
              AND json_extract(
                    NEW.payload_json,
                    '$.result_set_revision_id'
                  ) = request.result_set_revision_id
              AND json_extract(
                    NEW.payload_json,
                    '$.expected_task_snapshot_hash'
                  ) = request.task_snapshot_hash
              AND json_array_length(NEW.result_refs_json) = 1
              AND json_extract(
                    NEW.result_refs_json,
                    '$[0].object_type'
                  ) = 'operator_settlement_request'
              AND json_extract(
                    NEW.result_refs_json,
                    '$[0].object_id'
                  ) = request.settlement_request_id
          )
        BEGIN
          SELECT RAISE(
            ABORT,
            'request Action requires its exact settlement request result ref'
          );
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_task_settlement_run_typed_action
        BEFORE INSERT ON operator_task_settlement_runs
        WHEN NOT EXISTS (
          SELECT 1
          FROM actions AS settle_action
          JOIN operator_settlement_requests AS request
            ON request.settlement_request_id = NEW.settlement_request_id
          JOIN actions AS request_action
            ON request_action.action_id = NEW.request_action_id
          WHERE settle_action.action_id = NEW.settle_action_id
            AND settle_action.action_type = 'settle_task'
            AND settle_action.actor_role = 'deterministic_system'
            AND settle_action.status IN ('accepted', 'committed')
            AND json_extract(
                  settle_action.payload_json,
                  '$.settlement_request_id'
                ) = NEW.settlement_request_id
            AND request.action_id = NEW.request_action_id
            AND request_action.action_type = 'request_settlement'
            AND request_action.actor_role = 'judge_operator'
            AND request_action.status = 'committed'
            AND json_array_length(request_action.result_refs_json) = 1
            AND json_extract(
                  request_action.result_refs_json,
                  '$[0].object_type'
                ) = 'operator_settlement_request'
            AND json_extract(
                  request_action.result_refs_json,
                  '$[0].object_id'
                ) = NEW.settlement_request_id
            AND request.task_family_id = NEW.task_family_id
            AND request.work_item_id = NEW.work_item_id
            AND request.task_snapshot_hash = NEW.work_item_snapshot_hash
            AND request.result_set_revision_id = NEW.result_set_revision_id
            AND request.prize_table_revision_id IS NEW.prize_table_revision_id
        )
        BEGIN
          SELECT RAISE(
            ABORT,
            'settlement run requires its exact settlement request and Actions'
          );
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_ticket_settlement_typed_action
        BEFORE INSERT ON operator_ticket_settlement_revisions
        WHEN NOT EXISTS (
          SELECT 1
          FROM actions AS action
          JOIN operator_task_settlement_runs AS run
            ON run.settlement_run_id = NEW.settlement_run_id
          WHERE action.action_id = NEW.action_id
            AND action.action_type = 'settle_task'
            AND action.actor_role = 'deterministic_system'
            AND action.status IN ('accepted', 'committed')
            AND run.settle_action_id = NEW.action_id
            AND run.result_set_revision_id = NEW.result_set_revision_id
            AND run.prize_table_revision_id IS NEW.prize_table_revision_id
        )
        BEGIN
          SELECT RAISE(
            ABORT,
            'ticket settlement requires its exact settlement run and Action'
          );
        END
        """
    )

    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_task_settlement_action_exact_result
        BEFORE UPDATE OF status ON actions
        WHEN NEW.status = 'committed'
          AND NEW.action_type = 'settle_task'
          AND NOT EXISTS (
            SELECT 1
            FROM operator_task_settlement_runs AS run
            WHERE run.settle_action_id = NEW.action_id
              AND json_array_length(NEW.result_refs_json) = 1
              AND json_extract(
                    NEW.result_refs_json,
                    '$[0].object_type'
                  ) = 'operator_task_settlement_run'
              AND json_extract(
                    NEW.result_refs_json,
                    '$[0].object_id'
                  ) = run.settlement_run_id
          )
        BEGIN
          SELECT RAISE(ABORT, 'settle Action requires its exact settlement run result ref');
        END
        """
    )

    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_result_set_complete_before_commit
        BEFORE UPDATE OF status ON actions
        WHEN NEW.status = 'committed'
          AND NEW.action_type = 'import_result_evidence_set'
          AND EXISTS (
            SELECT 1
            FROM operator_result_set_revisions AS result_set
            WHERE result_set.action_id = NEW.action_id
              AND (
                result_set.match_count != (
                  SELECT COUNT(*) FROM operator_result_match_revisions AS match_result
                  WHERE match_result.result_set_revision_id =
                        result_set.result_set_revision_id
                )
                OR result_set.source_receipt_count != (
                  SELECT COUNT(*)
                  FROM operator_result_source_receipts AS receipt
                  JOIN operator_result_match_revisions AS match_result
                    ON match_result.match_result_revision_id =
                       receipt.match_result_revision_id
                  WHERE match_result.result_set_revision_id =
                        result_set.result_set_revision_id
                )
                OR result_set.outcome_count != (
                  SELECT COUNT(*) FROM operator_outcome_revisions AS outcome
                  WHERE outcome.result_set_revision_id = result_set.result_set_revision_id
                )
              )
          )
        BEGIN
          SELECT RAISE(ABORT, 'result import child counts do not reconcile');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER zucai_prize_table_complete_before_commit
        BEFORE UPDATE OF status ON actions
        WHEN NEW.status = 'committed'
          AND NEW.action_type = 'import_result_evidence_set'
          AND EXISTS (
            SELECT 1
            FROM zucai_prize_table_revisions AS prize
            WHERE prize.action_id = NEW.action_id
              AND prize.tier_count != (
                SELECT COUNT(*) FROM zucai_prize_table_tiers AS tier
                WHERE tier.prize_table_revision_id = prize.prize_table_revision_id
              )
          )
        BEGIN
          SELECT RAISE(ABORT, 'prize-table tier counts do not reconcile');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_task_settlement_complete_before_commit
        BEFORE UPDATE OF status ON actions
        WHEN NEW.status = 'committed'
          AND NEW.action_type = 'settle_task'
          AND EXISTS (
            SELECT 1
            FROM operator_task_settlement_runs AS run
            WHERE run.settle_action_id = NEW.action_id
              AND (
                run.persisted_settlement_count != (
                  SELECT COUNT(*) FROM operator_ticket_settlement_revisions AS settlement
                  WHERE settlement.settlement_run_id = run.settlement_run_id
                )
                OR run.persisted_note_grade_count != (
                  SELECT COUNT(*)
                  FROM operator_ticket_note_settlements AS note
                  JOIN operator_ticket_settlement_revisions AS settlement
                    ON settlement.settlement_revision_id = note.settlement_revision_id
                  WHERE settlement.settlement_run_id = run.settlement_run_id
                )
                OR run.persisted_leg_grade_count != (
                  SELECT COUNT(*)
                  FROM operator_ticket_note_leg_settlements AS leg
                  JOIN operator_ticket_settlement_revisions AS settlement
                    ON settlement.settlement_revision_id = leg.settlement_revision_id
                  WHERE settlement.settlement_run_id = run.settlement_run_id
                )
                OR run.persisted_cash_count != (
                  SELECT COUNT(*)
                  FROM operator_settlement_cash_links AS cash
                  JOIN operator_ticket_settlement_revisions AS settlement
                    ON settlement.settlement_revision_id = cash.settlement_revision_id
                  WHERE settlement.settlement_run_id = run.settlement_run_id
                )
                OR (
                  run.settled_ticket_count > 0
                  AND 1 != (
                    SELECT COUNT(*)
                    FROM operator_review_eligibility_facts AS fact
                    WHERE fact.settlement_run_id = run.settlement_run_id
                  )
                )
                OR (
                  run.settled_ticket_count = 0
                  AND EXISTS (
                    SELECT 1
                    FROM operator_review_eligibility_facts AS fact
                    WHERE fact.settlement_run_id = run.settlement_run_id
                  )
                )
              )
          )
        BEGIN
          SELECT RAISE(
            ABORT,
            'settlement children or review eligibility do not reconcile'
          );
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_settlement_cash_exact_reversal
        BEFORE INSERT ON operator_settlement_cash_links
        WHEN NEW.transaction_kind = 'payout_reversal'
          AND NOT EXISTS (
            SELECT 1
            FROM operator_settlement_cash_links AS prior
            WHERE prior.transaction_id = NEW.reverses_transaction_id
              AND prior.transaction_kind = 'payout'
              AND prior.amount_minor = -NEW.amount_minor
              AND prior.currency = NEW.currency
              AND prior.settlement_revision_id = (
                SELECT settlement.supersedes_revision_id
                FROM operator_ticket_settlement_revisions AS settlement
                WHERE settlement.settlement_revision_id = NEW.settlement_revision_id
              )
          )
        BEGIN
          SELECT RAISE(ABORT, 'payout reversal must negate the direct predecessor payout');
        END
        """
    )

    connection.execute(
        insert(schema.action_permissions),
        [
            {
                "policy_version_id": "governance-v1",
                "action_type": action_type,
                "actor_role": actor_role,
            }
            for action_type, actor_role in (
                ("import_result_evidence_set", "deterministic_system"),
                ("request_settlement", "judge_operator"),
                ("settle_task", "deterministic_system"),
            )
        ],
    )


def _apply_operator_review_scoreboard(connection: Connection) -> None:
    tables = (
        schema_operator_review.operator_review_items,
        schema_operator_review.operator_scoreboard_effect_disposition_revisions,
        schema_operator_review.operator_scoreboard_review_observation_links,
        schema_operator_review.operator_scoreboard_review_completion_requests,
        schema_operator_review.operator_scoreboard_review_completion_receipts,
    )
    for table in tables:
        table.create(connection)

    for table in tables:
        for operation in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"""
                CREATE TRIGGER {table.name}_no_{operation.lower()}
                BEFORE {operation} ON {table.name}
                BEGIN
                  SELECT RAISE(ABORT, '{table.name} is append-only');
                END
                """
            )

    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_review_item_exact_materialization
        BEFORE INSERT ON operator_review_items
        WHEN NOT EXISTS (
          SELECT 1
          FROM operator_review_eligibility_facts AS fact
          JOIN actions AS action ON action.action_id = NEW.materialized_by_action_id
          WHERE fact.review_eligibility_fact_id = NEW.review_eligibility_fact_id
            AND action.action_type = 'materialize_operator_review_item'
            AND action.actor_role = 'deterministic_system'
            AND action.status IN ('accepted', 'committed')
            AND fact.task_family_id = NEW.task_family_id
            AND fact.work_item_id = NEW.work_item_id
            AND fact.task_snapshot_hash = NEW.task_snapshot_hash
            AND fact.review_kind = NEW.review_kind
            AND fact.market_prior_baseline_revision_id
                IS NEW.market_prior_baseline_revision_id
        )
        BEGIN
          SELECT RAISE(ABORT, 'review item must derive from its exact eligibility fact');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_scoreboard_disposition_single_root
        BEFORE INSERT ON operator_scoreboard_effect_disposition_revisions
        WHEN NEW.supersedes_revision_id IS NULL
          AND (
            NEW.revision_no != 1
            OR EXISTS (
              SELECT 1
              FROM operator_scoreboard_effect_disposition_revisions
              WHERE review_id = NEW.review_id
                AND supersedes_revision_id IS NULL
            )
          )
        BEGIN
          SELECT RAISE(ABORT, 'scoreboard disposition already has a root revision');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_scoreboard_disposition_linear_child
        BEFORE INSERT ON operator_scoreboard_effect_disposition_revisions
        WHEN NEW.supersedes_revision_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1
            FROM operator_scoreboard_effect_disposition_revisions AS parent
            WHERE parent.disposition_revision_id = NEW.supersedes_revision_id
              AND parent.family_id = NEW.family_id
              AND parent.review_id = NEW.review_id
              AND NEW.revision_no = parent.revision_no + 1
              AND NOT EXISTS (
                SELECT 1
                FROM operator_scoreboard_effect_disposition_revisions AS child
                WHERE child.supersedes_revision_id = parent.disposition_revision_id
              )
          )
        BEGIN
          SELECT RAISE(ABORT, 'scoreboard disposition must directly follow its current leaf');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_scoreboard_disposition_before_completion
        BEFORE INSERT ON operator_scoreboard_effect_disposition_revisions
        WHEN EXISTS (
          SELECT 1 FROM operator_scoreboard_review_completion_receipts
          WHERE review_id = NEW.review_id
        )
        BEGIN
          SELECT RAISE(ABORT, 'completed review disposition is terminal');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_scoreboard_disposition_typed_action
        BEFORE INSERT ON operator_scoreboard_effect_disposition_revisions
        WHEN NOT EXISTS (
          SELECT 1 FROM actions
          WHERE action_id = NEW.created_by_action_id
            AND action_type = 'record_scoreboard_effect_disposition'
            AND actor_role = 'judge_operator'
            AND status IN ('accepted', 'committed')
        )
        BEGIN
          SELECT RAISE(ABORT, 'scoreboard disposition requires its judge Action');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_scoreboard_review_observation_exact_action
        BEFORE INSERT ON operator_scoreboard_review_observation_links
        WHEN NOT EXISTS (
          SELECT 1
          FROM operator_scoreboard_effect_disposition_revisions AS disposition
          JOIN scoreboard_observations AS observation
            ON observation.scoreboard_observation_id = NEW.scoreboard_observation_id
          JOIN actions AS action ON action.action_id = NEW.observation_action_id
          WHERE disposition.disposition_revision_id = NEW.disposition_revision_id
            AND disposition.review_id = NEW.review_id
            AND disposition.disposition = 'effect_required'
            AND EXISTS (
              SELECT 1 FROM json_each(disposition.required_metric_keys_json)
              WHERE value = NEW.metric_key
            )
            AND NOT EXISTS (
              SELECT 1
              FROM operator_scoreboard_effect_disposition_revisions AS child
              WHERE child.supersedes_revision_id = disposition.disposition_revision_id
            )
            AND observation.action_id = NEW.observation_action_id
            AND observation.metric_key = NEW.metric_key
            AND action.action_type = 'record_scoreboard_observation'
            AND action.actor_role = 'judge_operator'
            AND action.status IN ('accepted', 'committed')
        )
        BEGIN
          SELECT RAISE(ABORT, 'review observation must bind its current effect disposition');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_scoreboard_review_observation_common_hash
        BEFORE INSERT ON operator_scoreboard_review_observation_links
        WHEN EXISTS (
          SELECT 1
          FROM operator_scoreboard_review_observation_links
          WHERE disposition_revision_id = NEW.disposition_revision_id
            AND observed_legacy_sha256 != NEW.observed_legacy_sha256
        )
        BEGIN
          SELECT RAISE(ABORT, 'review observations require one common post-update hash');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_scoreboard_review_observation_before_completion
        BEFORE INSERT ON operator_scoreboard_review_observation_links
        WHEN EXISTS (
          SELECT 1 FROM operator_scoreboard_review_completion_receipts
          WHERE review_id = NEW.review_id
        )
        BEGIN
          SELECT RAISE(ABORT, 'completed review cannot accept observations');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_scoreboard_completion_request_typed_action
        BEFORE INSERT ON operator_scoreboard_review_completion_requests
        WHEN NOT EXISTS (
          SELECT 1
          FROM operator_scoreboard_effect_disposition_revisions AS disposition
          JOIN actions AS action ON action.action_id = NEW.action_id
          WHERE disposition.disposition_revision_id = NEW.disposition_revision_id
            AND disposition.review_id = NEW.review_id
            AND disposition.disposition = 'effect_required'
            AND action.action_type = 'request_scoreboard_review_completion'
            AND action.actor_role = 'judge_operator'
            AND action.status IN ('accepted', 'committed')
            AND NOT EXISTS (
              SELECT 1
              FROM operator_scoreboard_effect_disposition_revisions AS child
              WHERE child.supersedes_revision_id = disposition.disposition_revision_id
            )
            AND NOT EXISTS (
              SELECT 1 FROM operator_scoreboard_review_completion_receipts
              WHERE review_id = NEW.review_id
            )
        )
        BEGIN
          SELECT RAISE(ABORT, 'completion request requires the current effect disposition');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_scoreboard_completion_receipt_exact_source
        BEFORE INSERT ON operator_scoreboard_review_completion_receipts
        WHEN NOT EXISTS (
          SELECT 1
          FROM operator_scoreboard_effect_disposition_revisions AS disposition
          JOIN actions AS action ON action.action_id = NEW.completed_by_action_id
          WHERE disposition.disposition_revision_id = NEW.disposition_revision_id
            AND disposition.review_id = NEW.review_id
            AND NOT EXISTS (
              SELECT 1
              FROM operator_scoreboard_effect_disposition_revisions AS child
              WHERE child.supersedes_revision_id = disposition.disposition_revision_id
            )
            AND (
              (
                disposition.disposition = 'no_effect'
                AND NEW.completion_request_id IS NULL
                AND action.action_id = disposition.created_by_action_id
                AND action.action_type = 'record_scoreboard_effect_disposition'
                AND action.actor_role = 'judge_operator'
                AND action.status IN ('accepted', 'committed')
              )
              OR (
                disposition.disposition = 'effect_required'
                AND NEW.completion_request_id IS NOT NULL
                AND action.action_type = 'complete_scoreboard_review'
                AND action.actor_role = 'deterministic_system'
                AND action.status IN ('accepted', 'committed')
                AND EXISTS (
                  SELECT 1
                  FROM operator_scoreboard_review_completion_requests AS request
                  WHERE request.completion_request_id = NEW.completion_request_id
                    AND request.review_id = NEW.review_id
                    AND request.disposition_revision_id = NEW.disposition_revision_id
                    AND request.shadow_review_id = NEW.shadow_review_id
                    AND request.shadow_source_high_watermark =
                        NEW.shadow_source_high_watermark
                    AND request.compared_legacy_sha256 =
                        NEW.post_update_legacy_sha256
                    AND request.observation_action_ids_json =
                        NEW.observation_action_ids_json
                )
              )
            )
        )
        BEGIN
          SELECT RAISE(ABORT, 'completion receipt does not match its typed source');
        END
        """
    )

    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_scoreboard_completion_request_enqueue
        AFTER INSERT ON operator_scoreboard_review_completion_requests
        BEGIN
          INSERT INTO operator_worker_jobs (
            worker_job_id, job_kind, source_object_type, source_object_id, state,
            lease_owner, lease_expires_at, attempt_count, available_at,
            last_error_code, result_action_id, result_object_type, result_object_id,
            created_at, updated_at
          ) VALUES (
            'scoreboard-review-completion:' || NEW.completion_request_id,
            'scoreboard_review_completion',
            'operator_scoreboard_review_completion_request',
            NEW.completion_request_id, 'queued', NULL, NULL, 0,
            NEW.requested_at, NULL, NULL, NULL, NULL,
            NEW.requested_at, NEW.requested_at
          );
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_review_worker_job_source
        BEFORE INSERT ON operator_worker_jobs
        WHEN NEW.job_kind = 'review_materialization'
          AND (
            NEW.source_object_type != 'operator_review_eligibility_fact'
            OR NOT EXISTS (
              SELECT 1 FROM operator_review_eligibility_facts
              WHERE review_eligibility_fact_id = NEW.source_object_id
            )
          )
        BEGIN
          SELECT RAISE(ABORT, 'review materialization job requires its eligibility fact');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER operator_scoreboard_completion_worker_job_source
        BEFORE INSERT ON operator_worker_jobs
        WHEN NEW.job_kind = 'scoreboard_review_completion'
          AND (
            NEW.source_object_type !=
                'operator_scoreboard_review_completion_request'
            OR NOT EXISTS (
              SELECT 1 FROM operator_scoreboard_review_completion_requests
              WHERE completion_request_id = NEW.source_object_id
            )
          )
        BEGIN
          SELECT RAISE(ABORT, 'scoreboard completion job requires its typed request');
        END
        """
    )
    worker_result_check = """
      SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM actions AS action
        WHERE action.action_id = NEW.result_action_id
          AND action.status IN ('accepted', 'committed')
          AND (
            (
              NEW.job_kind = 'review_materialization'
              AND action.action_type = 'materialize_operator_review_item'
              AND action.actor_role = 'deterministic_system'
              AND NEW.result_object_type = 'operator_review_item'
              AND EXISTS (
                SELECT 1 FROM operator_review_items AS review
                WHERE review.review_id = NEW.result_object_id
                  AND review.review_eligibility_fact_id = NEW.source_object_id
                  AND review.materialized_by_action_id = NEW.result_action_id
              )
            )
            OR (
              NEW.job_kind = 'scoreboard_review_completion'
              AND action.action_type = 'complete_scoreboard_review'
              AND action.actor_role = 'deterministic_system'
              AND NEW.result_object_type = 'scoreboard_review_completion_receipt'
              AND EXISTS (
                SELECT 1
                FROM operator_scoreboard_review_completion_receipts AS receipt
                WHERE receipt.completion_receipt_id = NEW.result_object_id
                  AND receipt.completion_request_id = NEW.source_object_id
                  AND receipt.completed_by_action_id = NEW.result_action_id
              )
            )
          )
      ) THEN RAISE(ABORT, 'review worker result does not match its typed Action') END;
    """
    for operation in ("INSERT", "UPDATE"):
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER operator_review_worker_result_{operation.lower()}
            BEFORE {operation} ON operator_worker_jobs
            WHEN NEW.state = 'completed'
              AND NEW.job_kind IN (
                'review_materialization', 'scoreboard_review_completion'
              )
            BEGIN
              {worker_result_check}
            END
            """
        )

    connection.execute(
        insert(schema.action_permissions),
        [
            {
                "policy_version_id": "governance-v1",
                "action_type": action_type,
                "actor_role": actor_role,
            }
            for action_type, actor_role in (
                ("materialize_operator_review_item", "deterministic_system"),
                ("record_scoreboard_effect_disposition", "judge_operator"),
                ("request_scoreboard_review_completion", "judge_operator"),
                ("complete_scoreboard_review", "deterministic_system"),
            )
        ],
    )


# One empty production v19 was initialized from a known pre-commit definition.
# Its exact schema is gated here and converged transactionally by migration 26.
_LEGACY_SCHEMA_19_CHECKSUM = (
    "0f9b22848b47a447e1a18edf03a5eed3a33af4d968c5031c5b7c443307cbe964"
)
_CURRENT_SCHEMA_19_CHECKSUM = (
    "b77216c4f5f250bd5dd2b2e240c31bb0fb262a5664192f37d205604b57e37673"
)
_LEGACY_V19_REPAIR_CONTEXT_KEY = "nutmeg_legacy_v19_repair_checksum"
_V19_TABLES = (
    schema_operator_decision.operator_evidence_freeze_requests,
    schema_operator_decision.operator_task_evidence_bundle_revisions,
    schema_operator_decision.operator_task_evidence_bundle_items,
    schema_operator_decision.operator_worker_jobs,
)
_LEGACY_V19_TRIGGERS = frozenset(
    {
        "operator_worker_job_immutable_source",
        "operator_worker_job_terminal_immutable",
        "task_evidence_bundle_linear_child",
        "task_evidence_bundle_root_revision_no",
        "task_evidence_bundle_single_root",
    }
)
_CURRENT_WORKER_RESULT_CHECK = (
    "CONSTRAINT ck_operator_worker_job_result_ref CHECK "
    "((state = 'completed' AND result_action_id IS NOT NULL "
    "AND result_object_type IS NOT NULL AND result_object_id IS NOT NULL) "
    "OR (state != 'completed' AND result_action_id IS NULL "
    "AND result_object_type IS NULL AND result_object_id IS NULL))"
)
_LEGACY_WORKER_RESULT_CHECK = (
    "CONSTRAINT ck_operator_worker_job_result_ref CHECK "
    "((result_object_type IS NULL) = (result_object_id IS NULL))"
)


def _normalized_schema_sql(value: str) -> str:
    return " ".join(value.strip().removesuffix(";").split())


def _compiled_table_sql(connection: Connection, table) -> str:
    return str(CreateTable(table).compile(connection))


def _replace_schema_fragment(value: str, old: str, new: str) -> str:
    if value.count(old) != 1:
        raise MigrationDriftError("legacy migration 19 repair definition drift")
    return value.replace(old, new)


def _legacy_v19_table_sql(connection: Connection) -> dict[str, str]:
    expected = {table.name: _compiled_table_sql(connection, table) for table in _V19_TABLES}
    item_name = schema_operator_decision.operator_task_evidence_bundle_items.name
    expected[item_name] = _replace_schema_fragment(
        expected[item_name],
        " ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED",
        " ON DELETE RESTRICT",
    )
    worker_name = schema_operator_decision.operator_worker_jobs.name
    expected[worker_name] = _replace_schema_fragment(
        expected[worker_name],
        _CURRENT_WORKER_RESULT_CHECK,
        _LEGACY_WORKER_RESULT_CHECK,
    )
    return {
        table_name: _normalized_schema_sql(sql) for table_name, sql in expected.items()
    }


def _current_v19_table_sql(connection: Connection) -> dict[str, str]:
    return {
        table.name: _normalized_schema_sql(_compiled_table_sql(connection, table))
        for table in _V19_TABLES
    }


def _stored_table_sql(connection: Connection, table_name: str) -> str | None:
    sql = connection.execute(
        text(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = :table_name"
        ),
        {"table_name": table_name},
    ).scalar_one_or_none()
    return None if sql is None else _normalized_schema_sql(str(sql))


def _explicit_index_sql(connection: Connection, table_name: str) -> frozenset[str]:
    values = connection.execute(
        text(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name = :table_name AND sql IS NOT NULL"
        ),
        {"table_name": table_name},
    ).scalars()
    return frozenset(_normalized_schema_sql(str(value)) for value in values)


def _expected_explicit_index_sql(connection: Connection, table) -> frozenset[str]:
    return frozenset(
        _normalized_schema_sql(str(CreateIndex(index).compile(connection)))
        for index in table.indexes
    )


def _v19_trigger_names(connection: Connection) -> frozenset[str]:
    table_names = tuple(table.name for table in _V19_TABLES)
    placeholders = ", ".join(f":table_{index}" for index in range(len(table_names)))
    rows = connection.execute(
        text(
            "SELECT name FROM sqlite_master "
            f"WHERE type = 'trigger' AND tbl_name IN ({placeholders})"
        ),
        {f"table_{index}": name for index, name in enumerate(table_names)},
    ).scalars()
    return frozenset(str(row) for row in rows)


def _legacy_v19_shape_is_exact(
    connection: Connection,
    existing: dict[int, str],
) -> bool:
    if tuple(sorted(existing)) != tuple(range(1, 20)):
        return False
    migration_name = connection.execute(
        select(schema.schema_migrations.c.name).where(
            schema.schema_migrations.c.version == 19
        )
    ).scalar_one_or_none()
    if migration_name != "operator_evidence_freeze":
        return False
    expected_tables = _legacy_v19_table_sql(connection)
    for table in _V19_TABLES:
        if _stored_table_sql(connection, table.name) != expected_tables[table.name]:
            return False
        if _explicit_index_sql(connection, table.name) != _expected_explicit_index_sql(
            connection,
            table,
        ):
            return False
        quoted_name = connection.dialect.identifier_preparer.quote(table.name)
        if connection.exec_driver_sql(f"SELECT COUNT(*) FROM {quoted_name}").scalar_one():
            return False

    permissions = frozenset(
        (
            str(row.policy_version_id),
            str(row.action_type),
            str(row.actor_role),
        )
        for row in connection.execute(
            select(
                schema.action_permissions.c.policy_version_id,
                schema.action_permissions.c.action_type,
                schema.action_permissions.c.actor_role,
            ).where(
                schema.action_permissions.c.action_type.in_(
                    (
                        "request_evidence_freeze",
                        "freeze_evidence_bundle",
                        "link_operator_task_evidence_freeze",
                    )
                )
            )
        )
    )
    expected_permissions = frozenset(
        {
            ("governance-v1", "request_evidence_freeze", "judge_operator"),
            ("governance-v1", "freeze_evidence_bundle", "deterministic_system"),
            (
                "governance-v1",
                "link_operator_task_evidence_freeze",
                "deterministic_system",
            ),
        }
    )
    return permissions == expected_permissions and _v19_trigger_names(
        connection
    ) == _LEGACY_V19_TRIGGERS


def _mark_exact_legacy_v19_for_repair(
    connection: Connection,
    migration: Migration,
    migrations: tuple[Migration, ...],
    existing: dict[int, str],
) -> bool:
    recorded = existing.get(19)
    if recorded != _LEGACY_SCHEMA_19_CHECKSUM or migration.version != 19:
        return False
    if migration.name != "operator_evidence_freeze":
        return False
    if migration.checksum != _CURRENT_SCHEMA_19_CHECKSUM:
        return False
    if len(migrations) < 26 or migrations[:26] != MIGRATIONS[:26]:
        return False
    if not _legacy_v19_shape_is_exact(connection, existing):
        return False

    connection.info[_LEGACY_V19_REPAIR_CONTEXT_KEY] = _LEGACY_SCHEMA_19_CHECKSUM
    connection.execute(
        text("UPDATE schema_migrations SET checksum = :checksum WHERE version = 19"),
        {"checksum": migration.checksum},
    )
    existing[19] = migration.checksum
    return True


def _rebuild_empty_v19_table(connection: Connection, table) -> None:
    quoted_name = connection.dialect.identifier_preparer.quote(table.name)
    if connection.exec_driver_sql(f"SELECT COUNT(*) FROM {quoted_name}").scalar_one():
        raise MigrationDriftError("migration 26 legacy table is not empty")
    trigger_sql = tuple(
        str(value)
        for value in connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'trigger' AND tbl_name = :table_name "
                "ORDER BY name"
            ),
            {"table_name": table.name},
        ).scalars()
    )
    connection.exec_driver_sql(f"DROP TABLE {quoted_name}")
    table.create(connection)
    for statement in trigger_sql:
        connection.exec_driver_sql(statement)


def _install_missing_v19_triggers(connection: Connection) -> None:
    connection.exec_driver_sql(
        """
        CREATE TRIGGER IF NOT EXISTS operator_evidence_freeze_request_action
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
        CREATE TRIGGER IF NOT EXISTS task_evidence_bundle_counts_match_items
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
        CREATE TRIGGER IF NOT EXISTS task_evidence_bundle_item_freeze_action
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
        CREATE TRIGGER IF NOT EXISTS task_evidence_bundle_item_after_finalize
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
            CREATE TRIGGER IF NOT EXISTS
              operator_evidence_freeze_request_no_{operation.lower()}
            BEFORE {operation} ON operator_evidence_freeze_requests
            BEGIN
              SELECT RAISE(ABORT, 'operator evidence freeze requests are append-only');
            END
            """
        )
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER IF NOT EXISTS task_evidence_bundle_item_no_{operation.lower()}
            BEFORE {operation} ON operator_task_evidence_bundle_items
            BEGIN
              SELECT RAISE(ABORT, 'task evidence bundle items are append-only');
            END
            """
        )
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER IF NOT EXISTS task_evidence_bundle_revision_no_{operation.lower()}
            BEFORE {operation} ON operator_task_evidence_bundle_revisions
            BEGIN
              SELECT RAISE(ABORT, 'task evidence bundle revisions are append-only');
            END
            """
        )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER IF NOT EXISTS operator_worker_job_terminal_no_delete
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
            CREATE TRIGGER IF NOT EXISTS
              operator_worker_job_evidence_freeze_result_{operation.lower()}
            BEFORE {operation} ON operator_worker_jobs
            WHEN NEW.state = 'completed' AND NEW.job_kind = 'evidence_freeze'
            BEGIN
              {evidence_freeze_result_check}
            END
            """
        )


def _apply_operator_evidence_freeze_contract_repair(connection: Connection) -> None:
    guard_checksum = connection.info.get(_LEGACY_V19_REPAIR_CONTEXT_KEY)
    if guard_checksum not in (None, _LEGACY_SCHEMA_19_CHECKSUM):
        raise MigrationDriftError("migration 26 legacy repair context drift")

    actual_tables = {table.name: _stored_table_sql(connection, table.name) for table in _V19_TABLES}
    current_tables = _current_v19_table_sql(connection)
    if guard_checksum is not None:
        if actual_tables != _legacy_v19_table_sql(connection):
            raise MigrationDriftError("migration 26 legacy schema changed after validation")
        _rebuild_empty_v19_table(
            connection,
            schema_operator_decision.operator_task_evidence_bundle_items,
        )
        _rebuild_empty_v19_table(
            connection,
            schema_operator_decision.operator_worker_jobs,
        )
        actual_tables = {
            table.name: _stored_table_sql(connection, table.name) for table in _V19_TABLES
        }
    if actual_tables != current_tables:
        raise MigrationDriftError("migration 26 evidence-freeze schema drift")

    _install_missing_v19_triggers(connection)


def _apply_operator_projection_cursors(connection: Connection) -> None:
    schema_workflow.operator_projection_cursors.create(connection)


def _apply_operator_judgment_structure_facts(connection: Connection) -> None:
    """Carry 锚方完整度 and 被排面先例生死 into the judgment layer (C5/C7/C13/C14)."""
    for table in (
        schema_operator_decision.operator_match_judgment_anchor_facts,
        schema_operator_decision.operator_match_judgment_face_precedents,
    ):
        table.create(connection)
    for table_name in (
        "operator_match_judgment_anchor_facts",
        "operator_match_judgment_face_precedents",
    ):
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
              JOIN operator_match_judgment_revisions AS revision
                ON revision.operator_match_judgment_revision_id =
                   NEW.operator_match_judgment_revision_id
              WHERE action.action_id = revision.action_id
                AND action.status = 'committed'
            )
            BEGIN
              SELECT RAISE(ABORT, '{table_name} is append-only after commit');
            END
            """
        )


# 宪法落权限表（不靠自律）：人不能替 falsifier 说话；代码不能把东西推进票面。
_RSI_PERMISSIONS = (
    ("rsi_register_experiment", "judge_operator"),
    ("rsi_schedule_duties", "judge_operator"),
    ("rsi_schedule_duties", "deterministic_system"),
    ("rsi_fulfill_duty", "judge_operator"),
    ("rsi_fulfill_duty", "deterministic_system"),
    ("rsi_grade_experiment", "judge_operator"),
    ("rsi_grade_experiment", "deterministic_system"),
    ("rsi_record_verdict", "deterministic_system"),
    ("rsi_approve_deployment", "judge_operator"),
    ("rsi_amend_experiment", "judge_operator"),
)


def _apply_rsi_experiments(connection: Connection) -> None:
    for table in (
        schema_rsi.rsi_experiments, schema_rsi.rsi_duties, schema_rsi.rsi_duty_instances,
        schema_rsi.rsi_observations, schema_rsi.rsi_grades, schema_rsi.rsi_verdicts,
        schema_rsi.rsi_deployments, schema_rsi.rsi_amendments,
    ):
        table.create(connection)
    connection.execute(
        insert(schema.action_permissions),
        [{"policy_version_id": "governance-v1", "action_type": a, "actor_role": r}
         for a, r in _RSI_PERMISSIONS],
    )


def _apply_rsi_pending_instruments(connection: Connection) -> None:
    columns = {column["name"] for column in inspect(connection).get_columns("rsi_duties")}
    if "status" not in columns:
        connection.exec_driver_sql(
            "ALTER TABLE rsi_duties ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
        )
    connection.exec_driver_sql(
        "UPDATE rsi_duties SET status='pending_instrument' "
        "WHERE duty_id='F5:price-band-observation'"
    )
    connection.exec_driver_sql(
        "DELETE FROM rsi_duty_instances "
        "WHERE duty_id='F5:price-band-observation' AND fulfilled_at IS NULL"
    )


def _apply_rsi_price_band_instrument(connection: Connection) -> None:
    connection.exec_driver_sql(
        "UPDATE rsi_duties SET status='active', "
        "instrument_json='[\"uv\",\"run\",\"nutmeg\",\"rsi\",\"price-band\","
        "\"--day\",\"{day}\"]' WHERE duty_id='F5:price-band-observation'"
    )


def _apply_rsi_human_attribution(connection: Connection) -> None:
    for table_name in ("rsi_experiments", "rsi_amendments", "rsi_deployments"):
        columns = {column["name"] for column in inspect(connection).get_columns(table_name)}
        if "acted_by" not in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE {table_name} ADD COLUMN acted_by TEXT NOT NULL "
                "DEFAULT 'unattributed'"
            )


def _apply_rsi_observation_stratum_labels(connection: Connection) -> None:
    """Correct observation labels from frozen experiment falsifiers.

    This is a label correction, not an observation rewrite: only
    ``population_stratum`` changes, and only when it disagrees with the registered
    experiment. Row count and every measured field remain untouched.
    """
    experiments = connection.execute(
        select(
            schema_rsi.rsi_experiments.c.exp_id,
            schema_rsi.rsi_experiments.c.falsifier_json,
        )
    ).all()
    for exp_id, falsifier_json in experiments:
        expected = json.loads(falsifier_json).get("stratum")
        if expected is None:
            continue
        connection.execute(
            schema_rsi.rsi_observations.update()
            .where(
                schema_rsi.rsi_observations.c.exp_id == exp_id,
                schema_rsi.rsi_observations.c.population_stratum != expected,
            )
            .values(population_stratum=expected)
        )


_CAPITAL_PERMISSIONS = (("zucai_commit_capital_plan", "judge_operator"),)


def _apply_capital_plans(connection: Connection) -> None:
    schema_capital.zucai_capital_plans.create(connection)
    connection.execute(
        insert(schema.action_permissions),
        [
            {
                "policy_version_id": "governance-v1",
                "action_type": action_type,
                "actor_role": actor_role,
            }
            for action_type, actor_role in _CAPITAL_PERMISSIONS
        ],
    )


def _apply_jczq_candidate_bands(connection: Connection) -> None:
    columns = {
        column["name"]
        for column in inspect(connection).get_columns("operator_candidates")
    }
    additions = {
        "odds_band": "TEXT NULL",
        "target_odds_min_decimal": "TEXT NULL",
        "target_odds_max_decimal": "TEXT NULL",
        "combined_decimal_odds": "TEXT NULL",
        "parent_candidate_revision_id": "TEXT NULL",
        "delta_reason": "TEXT NULL",
    }
    for name, declaration in additions.items():
        if name not in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE operator_candidates ADD COLUMN {name} {declaration}"
            )
    schema_operator_decision.operator_candidate_band_outcomes.create(
        connection, checkfirst=True
    )
    for operation in ("UPDATE", "DELETE"):
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER IF NOT EXISTS
              operator_candidate_band_outcomes_no_{operation.lower()}
            BEFORE {operation} ON operator_candidate_band_outcomes
            BEGIN
              SELECT RAISE(ABORT, 'operator_candidate_band_outcomes is append-only');
            END
            """
        )


def _apply_jczq_board_research_states(connection: Connection) -> None:
    schema_operator_decision.operator_jczq_board_research_states.create(
        connection,
        checkfirst=True,
    )
    for operation in ("UPDATE", "DELETE"):
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER IF NOT EXISTS
              operator_jczq_board_research_states_no_{operation.lower()}
            BEFORE {operation} ON operator_jczq_board_research_states
            BEGIN
              SELECT RAISE(ABORT, 'operator_jczq_board_research_states is append-only');
            END
            """
        )
    connection.execute(
        insert(schema.action_permissions),
        {
            "policy_version_id": "governance-v1",
            "action_type": "reconcile_jczq_board_research",
            "actor_role": "deterministic_system",
        },
    )


def _apply_jczq_dream_rsi_alignment(connection: Connection) -> None:
    columns = {
        column["name"]
        for column in inspect(connection).get_columns("operator_candidate_set_revisions")
    }
    additions = {
        "change_delta_json": "TEXT NULL",
        "rationale": "TEXT NULL",
    }
    for name, declaration in additions.items():
        if name not in columns:
            connection.exec_driver_sql(
                f"ALTER TABLE operator_candidate_set_revisions "
                f"ADD COLUMN {name} {declaration}"
            )
    schema_operator_decision.operator_jczq_board_research_state_revisions.create(
        connection,
        checkfirst=True,
    )
    revision_table = (
        schema_operator_decision.operator_jczq_board_research_state_revisions
    )
    old_states = connection.execute(
        select(schema_operator_decision.operator_jczq_board_research_states)
    ).mappings()
    for old_state in old_states:
        state_id = str(old_state["board_research_state_id"])
        exists_in_revisions = connection.scalar(
            select(func.count())
            .select_from(revision_table)
            .where(revision_table.c.board_research_state_id == state_id)
        )
        if exists_in_revisions:
            continue
        family_material = json.dumps(
            [old_state["business_date"], old_state["match_id"]],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        family_id = "jczq-board-research-family-" + hashlib.sha256(
            family_material.encode("utf-8")
        ).hexdigest()
        connection.execute(
            insert(revision_table).values(
                board_research_state_id=state_id,
                board_research_family_id=family_id,
                revision_no=1,
                supersedes_revision_id=None,
                business_date=old_state["business_date"],
                match_id=old_state["match_id"],
                official_match_no=old_state["official_match_no"],
                status=old_state["status"],
                source_run_id=old_state["source_run_id"],
                artifact_id=old_state["artifact_id"],
                captured_at=old_state["captured_at"],
                kickoff_at=old_state["kickoff_at"],
                historical_replay=old_state["historical_replay"],
                action_id=old_state["action_id"],
                created_at=old_state["created_at"],
            )
        )
    for operation in ("UPDATE", "DELETE"):
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER IF NOT EXISTS
              operator_jczq_board_research_state_revisions_no_{operation.lower()}
            BEFORE {operation} ON operator_jczq_board_research_state_revisions
            BEGIN
              SELECT RAISE(
                ABORT,
                'operator_jczq_board_research_state_revisions is append-only'
              );
            END
            """
        )


def _apply_jczq_ontology_cutover(connection: Connection) -> None:
    connection.execute(
        insert(schema.action_permissions),
        {
            "policy_version_id": "governance-v1",
            "action_type": "approve_jczq_ontology_cutover",
            "actor_role": "judge_operator",
        },
    )


def _apply_historical_replay_authority(connection: Connection) -> None:
    schema.historical_replay_runs.create(connection, checkfirst=True)
    replay_action_types = (
        "build_market_snapshot",
        "commit_operator_match_judgment",
        "commit_forecast",
        "create_agent_proposal",
        "freeze_evidence_bundle",
        "freeze_judgment_prescription",
        "generate_ticket_candidate_set",
        "grade_prediction",
        "import_result_evidence_set",
        "ingest_artifact",
        "reconcile_jczq_board_research",
        "record_adjudication",
        "record_baseline_envelope",
        "record_no_ticket",
        "record_outcome",
        "register_prediction",
        "request_candidate_generation",
        "request_evidence_freeze",
        "resolve_agent_proposal",
        "rsi_grade_experiment",
    )
    connection.execute(
        insert(schema.action_permissions),
        [
            {
                "policy_version_id": "governance-v1",
                "action_type": action_type,
                "actor_role": "replay_adjudicator",
            }
            for action_type in replay_action_types
        ],
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
                "start_historical_replay",
                "finish_historical_replay",
            )
        ],
    )
    action_columns = {
        column['name'] for column in inspect(connection).get_columns('actions')
    }
    if 'historical_replay' not in action_columns:
        connection.exec_driver_sql(
            "ALTER TABLE actions ADD COLUMN historical_replay "
            "INTEGER NOT NULL DEFAULT 0"
        )
    if 'replay_run_id' not in action_columns:
        connection.exec_driver_sql(
            "ALTER TABLE actions ADD COLUMN replay_run_id TEXT NULL "
            "REFERENCES historical_replay_runs(replay_run_id) ON DELETE RESTRICT"
        )

    replay_judge_condition = """
      (
        actor_role = 'judge_operator' OR
        (
          actor_role = 'replay_adjudicator' AND
          historical_replay = 1 AND
          replay_run_id IS NOT NULL
        )
      )
    """
    replay_judgment_triggers = (
        (
            "operator_evidence_freeze_request_action",
            "operator_evidence_freeze_requests",
            "action_type = 'request_evidence_freeze'",
            "evidence freeze request requires its judge Action",
        ),
        (
            "baseline_envelope_typed_action",
            "operator_baseline_envelope_revisions",
            "action_type = 'record_baseline_envelope'",
            "operator_baseline_envelope_revisions requires its typed Action",
        ),
        (
            "operator_match_judgment_typed_action",
            "operator_match_judgment_revisions",
            "action_type = 'commit_operator_match_judgment'",
            "operator_match_judgment_revisions requires its typed Action",
        ),
        (
            "judgment_prescription_typed_action",
            "operator_judgment_prescription_revisions",
            "action_type = 'freeze_judgment_prescription'",
            "operator_judgment_prescription_revisions requires its typed Action",
        ),
        (
            "candidate_generation_request_typed_action",
            "operator_candidate_generation_requests",
            "action_type IN ('request_candidate_generation', 'record_ticket_audit_override')",
            "operator_candidate_generation_requests requires its typed Action",
        ),
    )
    for trigger_name, table_name, action_check, error_message in (
        replay_judgment_triggers
    ):
        connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {trigger_name}")
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE INSERT ON {table_name}
            WHEN NOT EXISTS (
              SELECT 1 FROM actions
              WHERE action_id = NEW.action_id
                AND {action_check}
                AND {replay_judge_condition}
                AND status IN ('accepted', 'committed')
            )
            BEGIN
              SELECT RAISE(ABORT, '{error_message}');
            END
            """
        )

    connection.exec_driver_sql("DROP TRIGGER IF EXISTS operator_no_ticket_typed_action")
    connection.exec_driver_sql(
        f"""
        CREATE TRIGGER operator_no_ticket_typed_action
        BEFORE INSERT ON operator_no_ticket_revisions
        WHEN NOT EXISTS (
          SELECT 1 FROM actions
          WHERE action_id = NEW.action_id
            AND {replay_judge_condition}
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
        "DROP TRIGGER IF EXISTS operator_no_ticket_command_typed_action"
    )
    connection.exec_driver_sql(
        f"""
        CREATE TRIGGER operator_no_ticket_command_typed_action
        BEFORE INSERT ON operator_no_ticket_command_receipts
        WHEN NOT EXISTS (
          SELECT 1 FROM actions
          WHERE action_id = NEW.action_id
            AND action_type = NEW.command_kind
            AND {replay_judge_condition}
            AND status IN ('accepted', 'committed')
        )
        BEGIN
          SELECT RAISE(ABORT, 'operator no-ticket receipt requires its typed Action');
        END
        """
    )
    connection.exec_driver_sql(
        "DROP TRIGGER IF EXISTS operator_candidate_generation_job_source"
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
                AND (
                  action.actor_role = 'judge_operator' OR
                  (
                    action.actor_role = 'replay_adjudicator' AND
                    action.historical_replay = 1 AND
                    action.replay_run_id IS NOT NULL
                  )
                )
                AND action.status IN ('accepted', 'committed')
            )
          )
        BEGIN
          SELECT RAISE(ABORT, 'candidate generation job requires its typed request');
        END
        """
    )

    for operation in ('INSERT', 'UPDATE'):
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER IF NOT EXISTS actions_historical_replay_pair_{operation.lower()}
            BEFORE {operation} ON actions
            WHEN NOT (
              (NEW.historical_replay = 0 AND NEW.replay_run_id IS NULL) OR
              (NEW.historical_replay = 1 AND NEW.replay_run_id IS NOT NULL)
            )
            BEGIN
              SELECT RAISE(ABORT, 'historical replay provenance pair is invalid');
            END
            """
        )
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER IF NOT EXISTS actions_replay_run_reference_{operation.lower()}
            BEFORE {operation} ON actions
            WHEN NEW.replay_run_id IS NOT NULL AND NOT EXISTS (
              SELECT 1 FROM historical_replay_runs
              WHERE replay_run_id = NEW.replay_run_id
            )
            BEGIN
              SELECT RAISE(ABORT, 'historical replay run does not exist');
            END
            """
        )

    connection.exec_driver_sql(
        """
        CREATE TRIGGER IF NOT EXISTS historical_replay_runs_no_delete
        BEFORE DELETE ON historical_replay_runs
        BEGIN
          SELECT RAISE(ABORT, 'historical replay runs are append-only');
        END
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TRIGGER IF NOT EXISTS historical_replay_runs_guard_update
        BEFORE UPDATE ON historical_replay_runs
        WHEN NOT (
          OLD.status = 'running' AND
          NEW.status IN ('accepted', 'failed') AND
          NEW.replay_run_id = OLD.replay_run_id AND
          NEW.business_date = OLD.business_date AND
          NEW.source_root_fingerprint = OLD.source_root_fingerprint AND
          NEW.source_manifest_hash = OLD.source_manifest_hash AND
          NEW.isolated_database_identity = OLD.isolated_database_identity AND
          NEW.schema_version = OLD.schema_version AND
          NEW.started_at = OLD.started_at AND
          NEW.production_before_json = OLD.production_before_json AND
          OLD.finished_at IS NULL AND
          OLD.production_after_json IS NULL AND
          OLD.report_sha256 IS NULL
        )
        BEGIN
          SELECT RAISE(ABORT, 'historical replay run transition is invalid');
        END
        """
    )


_DISCOVERY_PERMISSIONS = (
    ("create_discovery_world", "judge_operator"),
    ("create_discovery_world", "deterministic_system"),
    ("start_discovery_run", "deterministic_system"),
    ("record_discovery_node", "deterministic_system"),
    ("record_discovery_failure", "deterministic_system"),
    ("seal_discovery_world", "deterministic_system"),
    ("register_policy_revision", "judge_operator"),
    ("start_policy_replay", "deterministic_system"),
    ("finish_policy_replay", "deterministic_system"),
    ("create_policy_tournament", "judge_operator"),
    ("finish_policy_tournament", "deterministic_system"),
    ("approve_policy_deployment", "judge_operator"),
    ("trip_policy_brake", "deterministic_system"),
)


def _apply_discovery_foundation(connection: Connection) -> None:
    for name in schema_discovery.TABLE_KEYS:
        table = getattr(schema_discovery, name)
        table.create(connection)
        for operation in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"CREATE TRIGGER {name}_no_{operation.lower()} "
                f"BEFORE {operation} ON {name} BEGIN "
                f"SELECT RAISE(ABORT, '{name} is append-only'); END"
            )
    connection.execute(
        insert(schema.action_permissions),
        [
            {"policy_version_id": "governance-v1", "action_type": action, "actor_role": role}
            for action, role in _DISCOVERY_PERMISSIONS
        ],
    )


def _apply_discovery_generation(connection: Connection) -> None:
    table = schema_discovery_generation.policy_generation_rounds
    table.create(connection)
    for operation in ("UPDATE", "DELETE"):
        connection.exec_driver_sql(
            f"CREATE TRIGGER policy_generation_rounds_no_{operation.lower()} "
            f"BEFORE {operation} ON policy_generation_rounds BEGIN "
            "SELECT RAISE(ABORT, 'policy_generation_rounds is append-only'); END"
        )
    connection.execute(
        insert(schema.action_permissions).values(
            policy_version_id="governance-v1",
            action_type="record_policy_generation_round",
            actor_role="deterministic_system",
        )
    )


def _apply_discovery_promotion(connection: Connection) -> None:
    table = schema_discovery_promotion.policy_shadow_windows
    table.create(connection)
    for operation in ("UPDATE", "DELETE"):
        connection.exec_driver_sql(
            f"CREATE TRIGGER policy_shadow_windows_no_{operation.lower()} "
            f"BEFORE {operation} ON policy_shadow_windows BEGIN "
            "SELECT RAISE(ABORT, 'policy_shadow_windows is append-only'); END"
        )
    connection.execute(insert(schema.action_permissions).values(
        policy_version_id="governance-v1",
        action_type="preregister_policy_shadow_window",
        actor_role="judge_operator",
    ))


def _apply_discovery_receipts(connection: Connection) -> None:
    table = schema_discovery_promotion.protected_shadow_receipts
    table.create(connection)
    for operation in ("UPDATE", "DELETE"):
        connection.exec_driver_sql(
            f"CREATE TRIGGER protected_shadow_receipts_no_{operation.lower()} "
            f"BEFORE {operation} ON protected_shadow_receipts BEGIN "
            "SELECT RAISE(ABORT, 'protected_shadow_receipts is append-only'); END"
        )


def _apply_discovery_scope_reviews(connection: Connection) -> None:
    table = schema_discovery_promotion.policy_scope_reviews
    table.create(connection)
    for operation in ("UPDATE", "DELETE"):
        connection.exec_driver_sql(
            f"CREATE TRIGGER policy_scope_reviews_no_{operation.lower()} "
            f"BEFORE {operation} ON policy_scope_reviews BEGIN "
            "SELECT RAISE(ABORT, 'policy_scope_reviews is append-only'); END"
        )
    connection.execute(insert(schema.action_permissions).values(
        policy_version_id="governance-v1",
        action_type="approve_pilot_scope_contract",
        actor_role="judge_operator",
    ))


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
    Migration(
        version=23,
        name="operator_confirmation_ledger",
        fingerprint=(
            "ticket_notes+ticket_note_legs+placement_cash_links+"
            "telegram_owner_heartbeat_lease+telegram_callback_attestations+"
            "legacy_challenge_reconciliation+integer_money_authority+"
            "append_only_business_rows+deterministic_owner_registration+"
            "late_callback_terminal_authority"
        ),
        apply=_apply_operator_confirmation_ledger,
    ),
    Migration(
        version=24,
        name="operator_results_settlement",
        fingerprint=(
            "three_source_result_revisions+outcomes+official_prize_tables+"
            "queued_task_settlement+normalized_note_and_leg_grades+"
            "direct_predecessor_cash_corrections+append_only_business_rows+"
            "settlement_review_eligibility+atomic_review_queue+"
            "exact_child_count_reconciliation+exact_parent_action_bindings+"
            "role_separated_permissions"
        ),
        apply=_apply_operator_results_settlement,
    ),
    Migration(
        version=25,
        name="operator_review_scoreboard",
        fingerprint=(
            "review_items+scoreboard_effect_dispositions+observation_links+"
            "explicit_completion_requests_and_receipts+"
            "exact_shadow_selection+append_only_rows+role_separated_permissions"
        ),
        apply=_apply_operator_review_scoreboard,
    ),
    Migration(
        version=26,
        name="operator_evidence_freeze_contract_repair",
        fingerprint=(
            "exact_legacy_v19_checksum_and_schema_gate+"
            "deferred_bundle_item_fk+strict_worker_result_refs+"
            "missing_v19_triggers+transactional_guard"
        ),
        apply=_apply_operator_evidence_freeze_contract_repair,
    ),
    Migration(
        version=27,
        name="operator_projection_cursors",
        fingerprint=(
            "independent_monotonic_outbox_delivery_and_read_model_invalidation_cursors"
        ),
        apply=_apply_operator_projection_cursors,
    ),
    Migration(
        version=28,
        name="operator_judgment_structure_facts",
        fingerprint=(
            "judgment_anchor_integrity+judgment_face_precedents+"
            "closed_vocabularies+append_only_children"
        ),
        apply=_apply_operator_judgment_structure_facts,
    ),
    Migration(
        version=29,
        name="rsi_experiments",
        fingerprint=(
            "experiments+duties+duty_instances+observations+grades+verdicts+"
            "deployments+amendments+verdict_system_only+deploy_human_only"
        ),
        apply=_apply_rsi_experiments,
    ),
    Migration(
        version=30,
        name="zucai_capital_plans",
        fingerprint="capital_plans+gate_cost+commit_human_only",
        apply=_apply_capital_plans,
    ),
    Migration(
        version=31,
        name="jczq_candidate_bands",
        fingerprint=(
            "candidate_odds_band+target_interval+combined_odds+"
            "parent_delta_lineage+four_band_outcomes+append_only"
        ),
        apply=_apply_jczq_candidate_bands,
    ),
    Migration(
        version=32,
        name="jczq_board_research_states",
        fingerprint="explicit_board_terminal_states+append_only+replay_semantics",
        apply=_apply_jczq_board_research_states,
    ),
    Migration(
        version=33,
        name="jczq_dream_rsi_alignment",
        fingerprint=(
            "candidate_set_change_delta+rationale+revisioned_board_research+"
            "typed_rsi_fulfillment"
        ),
        apply=_apply_jczq_dream_rsi_alignment,
    ),
    Migration(
        version=34,
        name="jczq_ontology_cutover",
        fingerprint="accepted_replay_hash+zero_side_effect_gate+judge_only_authority",
        apply=_apply_jczq_ontology_cutover,
    ),
    Migration(
        version=35,
        name="historical_replay_authority",
        fingerprint=(
            "historical_replay_runs+action_replay_pair+append_only_run_transition"
        ),
        apply=_apply_historical_replay_authority,
    ),
    Migration(
        version=36,
        name="rsi_pending_instruments",
        fingerprint="duty_status+pending_schedule_exclusion+preserve_fulfilled_cleanup",
        apply=_apply_rsi_pending_instruments,
    ),
    Migration(
        version=37,
        name="rsi_price_band_instrument",
        fingerprint="activate_f5_price_band_instrument+preserve_duty_instances",
        apply=_apply_rsi_price_band_instrument,
    ),
    Migration(
        version=38,
        name="rsi_human_attribution",
        fingerprint="acted_by_on_register_amend_deploy+historical_unattributed",
        apply=_apply_rsi_human_attribution,
    ),
    Migration(
        version=39,
        name="rsi_observation_stratum_labels",
        fingerprint=(
            "correct_mismatched_observation_stratum_from_frozen_falsifier+"
            "labels_only+preserve_observation_rows_and_measurements"
        ),
        apply=_apply_rsi_observation_stratum_labels,
    ),
    Migration(
        version=40,
        name="discovery_foundation",
        fingerprint=(
            "discovery_six_families+append_only_events+holdout_exposure+"
            "role_separated_permissions"
        ),
        apply=_apply_discovery_foundation,
    ),
    Migration(
        version=41,
        name="discovery_generation_rounds",
        fingerprint="append_only_round_receipts+deterministic_recorder_permission",
        apply=_apply_discovery_generation,
    ),
    Migration(
        version=42,
        name="discovery_prospective_shadow_windows",
        fingerprint="append_only_preregistered_windows+human_only",
        apply=_apply_discovery_promotion,
    ),
    Migration(
        version=43,
        name="discovery_protected_shadow_receipts",
        fingerprint="append_only_seal_action_protected_before_after_receipts",
        apply=_apply_discovery_receipts,
    ),
    Migration(
        version=44,
        name="discovery_reviewed_pilot_scopes",
        fingerprint="human_only_immutable_external_reviewed_scope_contracts",
        apply=_apply_discovery_scope_reviews,
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
        connection.info.pop(_LEGACY_V19_REPAIR_CONTEXT_KEY, None)
        try:
            schema.schema_migrations.create(connection, checkfirst=True)
            existing = _applied_checksums(connection)
            for migration in migrations:
                recorded = existing.get(migration.version)
                if recorded is not None:
                    if recorded != migration.checksum:
                        if _mark_exact_legacy_v19_for_repair(
                            connection,
                            migration,
                            migrations,
                            existing,
                        ):
                            continue
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
        finally:
            connection.info.pop(_LEGACY_V19_REPAIR_CONTEXT_KEY, None)
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
