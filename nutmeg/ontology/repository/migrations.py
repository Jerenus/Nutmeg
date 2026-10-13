"""Kernel schema: one baseline migration plus the in-place rebase of the legacy chain.

2026-10-13 基线重排（Jun 裁定「清理删除」，推翻 10-03 §5「迁移链不压基线」）：2026-07 至
10 月累积的 47 步迁移链压成一条 ``baseline_2026_10_13``。链上 130 张从未有过一行数据的表
（operator_* 77、policy_* / discovery_* / exploration_* 20、claims / persons / 决策会话 /
可靠性 / 票据工作台等 33）连同 9 份 schema 模块一起删除；55 张表留下（44 张有数据、7 张有
现役写入路径、4 张被有数据表的外键指向）。旧链 47 条账本行留档在
``docs/superpowers/evidence/2026-10-13-kernel-schema-baseline.md``。

Fresh store: ``metadata.create_all`` + seeds (governance policy, action permissions,
market / selection definitions, team alias seed, scoreboard authority) + the guard
triggers the legacy chain had created on surviving tables.

Legacy store (ledger = versions 1..47 whose last checksum is ``LEGACY_FINAL_CHECKSUM``):
``run_migrations`` rebases in place — asserts every retired table is empty, drops the
retired tables and the ``actions`` triggers that referenced them, tops up the action
permissions the fresh path seeds, and replaces the ledger with the single baseline row.
No other data row is touched. Any other ledger
shape is drift and raises.

Drift detection stays as before: the runner records a SHA-256 of
``version:name:fingerprint`` per applied migration and refuses a changed fingerprint.
Each migration's schema/data change and its ``schema_migrations`` row commit in one
transaction.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Connection, Engine, delete, insert, inspect, select, text

from nutmeg.ontology.errors import MigrationDriftError
from nutmeg.ontology.identity.models import EntityType, TeamKind, mint_id
from nutmeg.ontology.repository import (  # noqa: F401  (every module registers its tables)
    schema,
    schema_capital,
    schema_decision,
    schema_evidence,
    schema_finance,
    schema_identity,
    schema_market,
    schema_rsi,
    schema_scoreboard,
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


# ── seeds ──────────────────────────────────────────────────────────────────────

GOVERNANCE_POLICY = 'governance-v1'

# 旧链 1..47 步在新建库上累计授出的 145 条 (action_type, actor_role)（golden 冻结件）。许多
# action_type 的实现已随操作台 / Dream 删除；行留着无害（权限只在提交 Action 时查）。生产库
# 只有其中 123 条——旧链里 replay_adjudicator / historical replay 的 22 条只在新建路径种下——
# 重排时补齐，让老库与新建库一致。
_ACTION_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ('apply_factor_status', 'judge_operator'),
    ('approve_jczq_ontology_cutover', 'judge_operator'),
    ('approve_pilot_scope_contract', 'judge_operator'),
    ('approve_policy_deployment', 'judge_operator'),
    ('approve_release', 'judge_operator'),
    ('approve_scoreboard_cutover', 'judge_operator'),
    ('approve_ticket_batch', 'judge_operator'),
    ('approve_ticket', 'judge_operator'),
    ('build_market_snapshot', 'deterministic_system'),
    ('build_market_snapshot', 'replay_adjudicator'),
    ('change_budget_policy', 'judge_operator'),
    ('change_policy', 'judge_operator'),
    ('commit_forecast', 'judge_operator'),
    ('commit_forecast', 'replay_adjudicator'),
    ('commit_operator_match_judgment', 'judge_operator'),
    ('commit_operator_match_judgment', 'replay_adjudicator'),
    ('complete_scoreboard_review', 'deterministic_system'),
    ('confirm_ticket_placement', 'judge_operator'),
    ('correct_outcome', 'deterministic_system'),
    ('create_agent_proposal', 'ai_analyst'),
    ('create_agent_proposal', 'replay_adjudicator'),
    ('create_discovery_world', 'deterministic_system'),
    ('create_discovery_world', 'judge_operator'),
    ('create_policy_tournament', 'judge_operator'),
    ('create_ticket_batch', 'judge_operator'),
    ('dispute_claim', 'judge_operator'),
    ('draft_forecast', 'ai_analyst'),
    ('draft_forecast', 'judge_operator'),
    ('extract_claim', 'ai_extractor'),
    ('finish_historical_replay', 'deterministic_system'),
    ('finish_policy_replay', 'deterministic_system'),
    ('finish_policy_tournament', 'deterministic_system'),
    ('freeze_evidence_bundle', 'deterministic_system'),
    ('freeze_evidence_bundle', 'replay_adjudicator'),
    ('freeze_judgment_prescription', 'judge_operator'),
    ('freeze_judgment_prescription', 'replay_adjudicator'),
    ('freeze_market_prior_baseline', 'deterministic_system'),
    ('generate_ticket_candidate_set', 'deterministic_system'),
    ('generate_ticket_candidate_set', 'replay_adjudicator'),
    ('grade_prediction', 'judge_operator'),
    ('grade_prediction', 'replay_adjudicator'),
    ('import_official_sale_slate', 'deterministic_system'),
    ('import_result_evidence_set', 'deterministic_system'),
    ('import_result_evidence_set', 'replay_adjudicator'),
    ('ingest_artifact', 'connector'),
    ('ingest_artifact', 'judge_operator'),
    ('ingest_artifact', 'replay_adjudicator'),
    ('ingest_operator_evidence_manifest', 'deterministic_system'),
    ('issue_ticket_confirmation', 'judge_operator'),
    ('link_external_identifier', 'connector'),
    ('link_external_identifier', 'deterministic_system'),
    ('link_operator_task_evidence_freeze', 'deterministic_system'),
    ('link_precedent', 'deterministic_system'),
    ('link_precedent', 'judge_operator'),
    ('mark_ticket_shadow', 'deterministic_system'),
    ('materialize_operator_review_item', 'deterministic_system'),
    ('merge_entity', 'judge_operator'),
    ('open_decision_session', 'deterministic_system'),
    ('open_decision_session', 'judge_operator'),
    ('preregister_policy_shadow_window', 'judge_operator'),
    ('propose_factor_status', 'ai_analyst'),
    ('propose_factor_status', 'judge_operator'),
    ('propose_identity_link', 'ai_extractor'),
    ('propose_identity_link', 'connector'),
    ('propose_ticket', 'ai_analyst'),
    ('propose_ticket', 'judge_operator'),
    ('reconcile_jczq_board_research', 'deterministic_system'),
    ('reconcile_jczq_board_research', 'replay_adjudicator'),
    ('record_adjudication', 'judge_operator'),
    ('record_adjudication', 'replay_adjudicator'),
    ('record_baseline_envelope', 'judge_operator'),
    ('record_baseline_envelope', 'replay_adjudicator'),
    ('record_cash_transaction', 'deterministic_system'),
    ('record_cash_transaction', 'judge_operator'),
    ('record_discovery_failure', 'deterministic_system'),
    ('record_discovery_node', 'deterministic_system'),
    ('record_flag_instance', 'deterministic_system'),
    ('record_flag_instance', 'judge_operator'),
    ('record_lineup_entry', 'connector'),
    ('record_lineup_entry', 'deterministic_system'),
    ('record_market_quote', 'connector'),
    ('record_match', 'connector'),
    ('record_match', 'deterministic_system'),
    ('record_no_ticket', 'judge_operator'),
    ('record_no_ticket', 'replay_adjudicator'),
    ('record_observation', 'connector'),
    ('record_observation', 'deterministic_system'),
    ('record_official_schedule_check', 'deterministic_system'),
    ('record_outcome', 'deterministic_system'),
    ('record_outcome', 'replay_adjudicator'),
    ('record_person_match_status', 'connector'),
    ('record_person_match_status', 'deterministic_system'),
    ('record_policy_generation_round', 'deterministic_system'),
    ('record_reliability_evidence', 'deterministic_system'),
    ('record_reliability_evidence', 'judge_operator'),
    ('record_scoreboard_effect_disposition', 'judge_operator'),
    ('record_scoreboard_export', 'deterministic_system'),
    ('record_scoreboard_observation', 'judge_operator'),
    ('record_scoreboard_shadow_review', 'deterministic_system'),
    ('record_ticket_audit_override', 'judge_operator'),
    ('register_policy_revision', 'judge_operator'),
    ('register_prediction', 'ai_analyst'),
    ('register_prediction', 'judge_operator'),
    ('register_prediction', 'replay_adjudicator'),
    ('register_telegram_update_owner', 'deterministic_system'),
    ('register_zucai_fixed_prize_policy', 'deterministic_system'),
    ('remove_ticket_leg', 'judge_operator'),
    ('request_candidate_generation', 'judge_operator'),
    ('request_candidate_generation', 'replay_adjudicator'),
    ('request_evidence_freeze', 'judge_operator'),
    ('request_evidence_freeze', 'replay_adjudicator'),
    ('request_scoreboard_review_completion', 'judge_operator'),
    ('request_settlement', 'judge_operator'),
    ('resolve_agent_proposal', 'judge_operator'),
    ('resolve_agent_proposal', 'replay_adjudicator'),
    ('retract_claim', 'judge_operator'),
    ('revise_forecast', 'judge_operator'),
    ('rsi_amend_experiment', 'judge_operator'),
    ('rsi_approve_deployment', 'judge_operator'),
    ('rsi_fulfill_duty', 'deterministic_system'),
    ('rsi_fulfill_duty', 'judge_operator'),
    ('rsi_grade_experiment', 'deterministic_system'),
    ('rsi_grade_experiment', 'judge_operator'),
    ('rsi_grade_experiment', 'replay_adjudicator'),
    ('rsi_record_verdict', 'deterministic_system'),
    ('rsi_register_experiment', 'judge_operator'),
    ('rsi_schedule_duties', 'deterministic_system'),
    ('rsi_schedule_duties', 'judge_operator'),
    ('seal_discovery_world', 'deterministic_system'),
    ('select_ticket_candidate', 'judge_operator'),
    ('settle_task', 'deterministic_system'),
    ('settle_ticket', 'deterministic_system'),
    ('start_discovery_run', 'deterministic_system'),
    ('start_historical_replay', 'deterministic_system'),
    ('start_policy_replay', 'deterministic_system'),
    ('supersede_no_ticket', 'judge_operator'),
    ('trip_policy_brake', 'deterministic_system'),
    ('upsert_person', 'connector'),
    ('upsert_person', 'deterministic_system'),
    ('upsert_provisional_entity', 'connector'),
    ('upsert_provisional_entity', 'deterministic_system'),
    ('verify_claim', 'deterministic_system'),
    ('verify_claim', 'judge_operator'),
    ('withdraw_forecast', 'judge_operator'),
    ('zucai_commit_capital_plan', 'judge_operator'),
)


def _seed_governance(connection: Connection) -> None:
    now = datetime.now(UTC).isoformat()
    connection.execute(
        insert(schema.policy_versions).values(
            policy_version_id=GOVERNANCE_POLICY,
            policy_kind='governance',
            version=1,
            payload_json=_canonical_json({'name': 'kernel-default'}),
            status='active',
            effective_at=now,
            created_at=now,
        )
    )
    connection.execute(
        insert(schema.action_permissions),
        [
            {'policy_version_id': GOVERNANCE_POLICY, 'action_type': a, 'actor_role': r}
            for a, r in _ACTION_PERMISSIONS
        ],
    )


_CRS_SELECTIONS: list[tuple[str, str, int]] = [
    (f'sel-crs-{home}-{away}', f'{home}:{away}', 1) for home in range(4) for away in range(4)
] + [
    # 2026-09-04（旧链 v21）：'other' 不可部署，拆成三个可部署的方向性 other
    ('sel-crs-other', 'other', 0),
    ('sel-crs-win-other', 'win_other', 1),
    ('sel-crs-draw-other', 'draw_other', 1),
    ('sel-crs-loss-other', 'loss_other', 1),
]
_MARKET_SEED: dict[str, dict[str, object]] = {
    'md-had': {
        'market_kind': 'had', 'settlement_scope': 'regular_time', 'ordered': 0, 'line_schema': None,
        'selections': [('sel-had-home', 'home', 1), ('sel-had-draw', 'draw', 1),
                       ('sel-had-away', 'away', 1)],
    },
    'md-hhad': {
        'market_kind': 'hhad', 'settlement_scope': 'regular_time', 'ordered': 0,
        'line_schema': 'integer_handicap',
        'selections': [('sel-hhad-home', 'home', 1), ('sel-hhad-draw', 'draw', 1),
                       ('sel-hhad-away', 'away', 1)],
    },
    'md-ttg': {
        'market_kind': 'ttg', 'settlement_scope': 'regular_time', 'ordered': 1, 'line_schema': None,
        'selections': [(f'sel-ttg-{n}', f'total_{n}', 1) for n in range(8)],
    },
    'md-crs': {
        'market_kind': 'crs', 'settlement_scope': 'regular_time', 'ordered': 0, 'line_schema': None,
        'selections': _CRS_SELECTIONS,
    },
}


def _seed_market(connection: Connection) -> None:
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
                    'line': None,
                    'deployable': deployable,
                }
                for selection_id, outcome_key, deployable in spec['selections']
            ],
        )


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


def _seed_team_aliases(connection: Connection) -> None:
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


def _seed_scoreboard_authority(connection: Connection) -> None:
    connection.execute(
        insert(schema_scoreboard.scoreboard_authority).values(
            authority_id='primary',
            state='legacy',
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


# ── guard triggers on surviving tables (SQL verbatim from the legacy chain) ─────

BASELINE_TRIGGERS: dict[str, str] = {
    'zucai_fixed_prize_policy_single_root': """
CREATE TRIGGER zucai_fixed_prize_policy_single_root
            BEFORE INSERT ON zucai_fixed_prize_policy_revisions
            WHEN NEW.supersedes_revision_id IS NULL
              AND EXISTS (
                SELECT 1 FROM zucai_fixed_prize_policy_revisions
                WHERE fixed_prize_policy_family_id = NEW.fixed_prize_policy_family_id
                  AND supersedes_revision_id IS NULL
              )
            BEGIN
              SELECT RAISE(ABORT, 'fixed_prize_policy_family_id already has a root revision');
            END
""",
    'zucai_fixed_prize_policy_linear_revision': """
CREATE TRIGGER zucai_fixed_prize_policy_linear_revision
            BEFORE INSERT ON zucai_fixed_prize_policy_revisions
            WHEN (NEW.supersedes_revision_id IS NULL AND NEW.revision_no != 1)
              OR (NEW.supersedes_revision_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM zucai_fixed_prize_policy_revisions AS parent
                WHERE parent.fixed_prize_policy_revision_id = NEW.supersedes_revision_id
                  AND parent.fixed_prize_policy_family_id = NEW.fixed_prize_policy_family_id
                  AND NEW.revision_no = parent.revision_no + 1
              ))
            BEGIN
              SELECT RAISE(ABORT, 'revision must directly follow its family predecessor');
            END
""",
    'zucai_fixed_prize_policy_typed_action': """
CREATE TRIGGER zucai_fixed_prize_policy_typed_action
            BEFORE INSERT ON zucai_fixed_prize_policy_revisions
            WHEN NOT EXISTS (
              SELECT 1 FROM actions
              WHERE action_id = NEW.action_id
                AND action_type = 'register_zucai_fixed_prize_policy'
                AND actor_role = 'deterministic_system'
                AND status IN ('accepted', 'committed')
            )
            BEGIN
              SELECT RAISE(ABORT, 'zucai_fixed_prize_policy_revisions requires its typed Action');
            END
""",
    'zucai_fixed_prize_policy_revisions_no_update': """
CREATE TRIGGER zucai_fixed_prize_policy_revisions_no_update
                BEFORE UPDATE ON zucai_fixed_prize_policy_revisions
                BEGIN
                  SELECT RAISE(ABORT, 'zucai_fixed_prize_policy_revisions is append-only');
                END
""",
    'zucai_fixed_prize_policy_revisions_no_delete': """
CREATE TRIGGER zucai_fixed_prize_policy_revisions_no_delete
                BEFORE DELETE ON zucai_fixed_prize_policy_revisions
                BEGIN
                  SELECT RAISE(ABORT, 'zucai_fixed_prize_policy_revisions is append-only');
                END
""",
    'tickets_v2_money_insert': """
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
""",
    'cash_transactions_v2_money_insert': """
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
""",
    'actions_historical_replay_pair_insert': """
CREATE TRIGGER actions_historical_replay_pair_insert
            BEFORE INSERT ON actions
            WHEN NOT (
              (NEW.historical_replay = 0 AND NEW.replay_run_id IS NULL) OR
              (NEW.historical_replay = 1 AND NEW.replay_run_id IS NOT NULL)
            )
            BEGIN
              SELECT RAISE(ABORT, 'historical replay provenance pair is invalid');
            END
""",
    'actions_historical_replay_pair_update': """
CREATE TRIGGER actions_historical_replay_pair_update
            BEFORE UPDATE ON actions
            WHEN NOT (
              (NEW.historical_replay = 0 AND NEW.replay_run_id IS NULL) OR
              (NEW.historical_replay = 1 AND NEW.replay_run_id IS NOT NULL)
            )
            BEGIN
              SELECT RAISE(ABORT, 'historical replay provenance pair is invalid');
            END
""",
    'historical_replay_runs_no_delete': """
CREATE TRIGGER historical_replay_runs_no_delete
        BEFORE DELETE ON historical_replay_runs
        BEGIN
          SELECT RAISE(ABORT, 'historical replay runs are append-only');
        END
""",
    'historical_replay_runs_guard_update': """
CREATE TRIGGER historical_replay_runs_guard_update
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
""",
}


def _create_guard_triggers(connection: Connection) -> None:
    for sql in BASELINE_TRIGGERS.values():
        connection.exec_driver_sql(sql)


# ── baseline ───────────────────────────────────────────────────────────────────

def _apply_baseline(connection: Connection) -> None:
    schema.metadata.create_all(connection)
    _seed_governance(connection)
    _seed_market(connection)
    _seed_team_aliases(connection)
    _seed_scoreboard_authority(connection)
    _create_guard_triggers(connection)


BASELINE = Migration(
    version=1,
    name='baseline_2026_10_13',
    fingerprint=(
        'kernel_baseline(55 tables)+seeds(governance-v1,market,team_alias,'
        'scoreboard_authority)+guard_triggers'
    ),
    apply=_apply_baseline,
)

MIGRATIONS: tuple[Migration, ...] = (BASELINE,)


# ── legacy chain rebase ────────────────────────────────────────────────────────

LEGACY_CHAIN_LENGTH = 47
# `47:forecast_judgment_payload:<fingerprint>` — the last row every pre-baseline store carries.
LEGACY_FINAL_CHECKSUM = '69084dca52c0857724aba52cb04bc1091fd387421004aff11bb1ca3e69ce436f'

# 130 张被删的表（全部 0 行；证据见 evidence/2026-10-13-kernel-schema-baseline.md）
RETIRED_TABLES: frozenset[str] = frozenset({
    'agent_proposals',
    'audited_ticket_artifacts',
    'budget_policies',
    'claim_evidence_spans',
    'claim_status_events',
    'claims',
    'decision_sessions',
    'discovery_node_evaluations',
    'discovery_nodes',
    'discovery_runs',
    'discovery_world_events',
    'discovery_worlds',
    'entity_merges',
    'evidence_bundle_items',
    'exploration_policy_parent_links',
    'exploration_policy_revisions',
    'lineup_entries',
    'observation_claims',
    'observation_sources',
    'official_offer_families',
    'official_offer_revisions',
    'official_sale_slate_revisions',
    'official_schedule_check_receipts',
    'operator_artifact_terminal_receipts',
    'operator_artifact_work_item_links',
    'operator_baseline_envelope_bundle_faces',
    'operator_baseline_envelope_face_bundles',
    'operator_baseline_envelope_offer_constraints',
    'operator_baseline_envelope_revisions',
    'operator_baseline_envelope_structure_templates',
    'operator_baseline_envelope_template_offers',
    'operator_candidate_audit_findings',
    'operator_candidate_band_outcomes',
    'operator_candidate_dead_faces',
    'operator_candidate_generation_override_links',
    'operator_candidate_generation_requests',
    'operator_candidate_metrics',
    'operator_candidate_selections',
    'operator_candidate_set_revisions',
    'operator_candidate_ticket_legs',
    'operator_candidate_tickets',
    'operator_candidates',
    'operator_confirmation_challenge_heads',
    'operator_confirmation_challenge_revisions',
    'operator_evidence_coverage_receipts',
    'operator_evidence_freeze_requests',
    'operator_evidence_intake_objects',
    'operator_evidence_intake_receipts',
    'operator_jczq_board_research_state_revisions',
    'operator_jczq_board_research_states',
    'operator_judgment_prescription_items',
    'operator_judgment_prescription_revisions',
    'operator_market_prior_baseline_probabilities',
    'operator_market_prior_baseline_revisions',
    'operator_match_judgment_anchor_facts',
    'operator_match_judgment_bundle_faces',
    'operator_match_judgment_evidence_refs',
    'operator_match_judgment_face_bundles',
    'operator_match_judgment_face_precedents',
    'operator_match_judgment_factor_adjustments',
    'operator_match_judgment_factor_evidence_refs',
    'operator_match_judgment_factor_offsets',
    'operator_match_judgment_probabilities',
    'operator_match_judgment_revisions',
    'operator_match_judgment_rule_refs',
    'operator_no_ticket_artifact_scopes',
    'operator_no_ticket_command_receipts',
    'operator_no_ticket_offer_scopes',
    'operator_no_ticket_revisions',
    'operator_outcome_revisions',
    'operator_placement_cash_links',
    'operator_protected_artifact_bindings',
    'operator_protected_artifact_offer_revision_links',
    'operator_result_match_revisions',
    'operator_result_set_families',
    'operator_result_set_revisions',
    'operator_result_source_receipts',
    'operator_review_eligibility_facts',
    'operator_review_items',
    'operator_scoreboard_effect_disposition_revisions',
    'operator_scoreboard_review_completion_receipts',
    'operator_scoreboard_review_completion_requests',
    'operator_scoreboard_review_observation_links',
    'operator_settlement_cash_links',
    'operator_settlement_requests',
    'operator_task_evidence_bundle_items',
    'operator_task_evidence_bundle_revisions',
    'operator_task_settlement_runs',
    'operator_task_settlement_skips',
    'operator_telegram_callback_attestations',
    'operator_telegram_owner_heartbeats',
    'operator_ticket_audit_override_receipts',
    'operator_ticket_decision_lineage_items',
    'operator_ticket_decision_lineage_revisions',
    'operator_ticket_note_leg_settlements',
    'operator_ticket_note_legs',
    'operator_ticket_note_settlements',
    'operator_ticket_notes',
    'operator_ticket_settlement_revisions',
    'operator_worker_jobs',
    'person_match_statuses',
    'persons',
    'policy_archive_decisions',
    'policy_brake_events',
    'policy_deployments',
    'policy_generation_rounds',
    'policy_holdout_exposures',
    'policy_replay_completions',
    'policy_replay_rounds',
    'policy_replay_runs',
    'policy_scope_reviews',
    'policy_shadow_windows',
    'policy_tournament_candidates',
    'policy_tournament_completions',
    'policy_tournament_results',
    'policy_tournament_worlds',
    'policy_tournaments',
    'precedent_links',
    'protected_shadow_receipts',
    'release_approvals',
    'reliability_evidence',
    'role_assignments',
    'scenarios',
    'ticket_batch_revisions',
    'ticket_confirmation_challenges',
    'ticket_placements',
    'ticket_shadow_records',
    'zucai_fixed_prize_policy_tiers',
    'zucai_prize_table_revisions',
    'zucai_prize_table_tiers',
})


def _rebase_legacy_chain(connection: Connection) -> bool:
    """Turn a sealed legacy store (ledger 1..47) into the baseline store, in place."""
    existing = _applied_checksums(connection)
    if not existing or existing == {BASELINE.version: BASELINE.checksum}:
        return False
    if (
        sorted(existing) != list(range(1, LEGACY_CHAIN_LENGTH + 1))
        or existing[LEGACY_CHAIN_LENGTH] != LEGACY_FINAL_CHECKSUM
    ):
        raise MigrationDriftError(
            'schema_migrations ledger is neither the baseline nor the sealed legacy chain '
            f'(1..{LEGACY_CHAIN_LENGTH}); refusing to rebase'
        )
    present = set(inspect(connection).get_table_names())
    for name in RETIRED_TABLES:
        if name not in present:
            continue
        rows = connection.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar_one()
        if rows:
            raise MigrationDriftError(f'retired table {name} holds {rows} rows; refusing to drop')
    triggers = connection.execute(
        text("SELECT name, tbl_name FROM sqlite_master WHERE type = 'trigger'")
    ).all()
    for name, table_name in triggers:
        if table_name not in RETIRED_TABLES and name not in BASELINE_TRIGGERS:
            connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS "{name}"')
    for name in RETIRED_TABLES:
        if name in present:
            connection.exec_driver_sql(f'DROP TABLE "{name}"')
    granted = {
        (row.action_type, row.actor_role)
        for row in connection.execute(
            select(schema.action_permissions.c.action_type, schema.action_permissions.c.actor_role)
            .where(schema.action_permissions.c.policy_version_id == GOVERNANCE_POLICY)
        ).all()
    }
    missing = [pair for pair in _ACTION_PERMISSIONS if pair not in granted]
    if missing:
        connection.execute(
            insert(schema.action_permissions),
            [
                {'policy_version_id': GOVERNANCE_POLICY, 'action_type': a, 'actor_role': r}
                for a, r in missing
            ],
        )
    connection.execute(delete(schema.schema_migrations))
    connection.execute(
        insert(schema.schema_migrations).values(
            version=BASELINE.version,
            name=BASELINE.name,
            checksum=BASELINE.checksum,
            applied_at=datetime.now(UTC).isoformat(),
        )
    )
    return True


# ── runner ─────────────────────────────────────────────────────────────────────

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
        if migrations and migrations[0] is BASELINE:
            _rebase_legacy_chain(connection)
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
