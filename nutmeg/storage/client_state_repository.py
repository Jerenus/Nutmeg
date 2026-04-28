from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from nutmeg.domain.client import (
    Actionability,
    Alert,
    AnalysisAuditRecord,
    SubscriptionEntitlement,
    SubscriptionPlan,
    SubscriptionStatus,
    WatchlistItem,
)


class SqlAlchemyClientStateRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        statements = [
            '''
            CREATE TABLE IF NOT EXISTS client_entitlements (
                user_id TEXT PRIMARY KEY,
                plan TEXT NOT NULL,
                status TEXT NOT NULL,
                premium_match_detail_enabled INTEGER NOT NULL,
                alerts_enabled INTEGER NOT NULL,
                history_enabled INTEGER NOT NULL,
                valid_until TEXT,
                updated_at TEXT NOT NULL
            )
            ''',
            '''
            CREATE TABLE IF NOT EXISTS client_watchlist_items (
                watchlist_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                alert_preferences TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, target_type, target_id)
            )
            ''',
            '''
            CREATE TABLE IF NOT EXISTS client_alerts (
                alert_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                fixture_id TEXT NOT NULL,
                change_type TEXT NOT NULL,
                before_summary TEXT,
                after_summary TEXT NOT NULL,
                actionability_before TEXT,
                actionability_after TEXT,
                severity TEXT NOT NULL,
                group_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                read_at TEXT,
                UNIQUE(user_id, fixture_id, group_key)
            )
            ''',
            '''
            CREATE TABLE IF NOT EXISTS client_analysis_audits (
                audit_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                fixture_id TEXT NOT NULL,
                actionability TEXT NOT NULL,
                confidence TEXT NOT NULL,
                verdict TEXT NOT NULL,
                evidence_snapshot TEXT NOT NULL,
                generated_text TEXT,
                created_at TEXT NOT NULL
            )
            ''',
            '''
            CREATE TABLE IF NOT EXISTS client_conversation_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                fixture_id TEXT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                evidence_ids TEXT NOT NULL,
                verdict_alignment TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            ''',
        ]
        for statement in statements:
            self._session.execute(text(statement))
        self._session.commit()

    def upsert_entitlement(
        self,
        *,
        user_id: str,
        plan: SubscriptionPlan,
        status: SubscriptionStatus,
        premium_match_detail_enabled: bool,
        alerts_enabled: bool,
        history_enabled: bool,
        valid_until: datetime | None = None,
    ) -> None:
        now = _now_iso()
        self._session.execute(
            text(
                '''
                INSERT INTO client_entitlements (
                    user_id, plan, status, premium_match_detail_enabled, alerts_enabled,
                    history_enabled, valid_until, updated_at
                ) VALUES (
                    :user_id, :plan, :status, :premium, :alerts, :history,
                    :valid_until, :updated_at
                )
                ON CONFLICT(user_id) DO UPDATE SET
                    plan=excluded.plan,
                    status=excluded.status,
                    premium_match_detail_enabled=excluded.premium_match_detail_enabled,
                    alerts_enabled=excluded.alerts_enabled,
                    history_enabled=excluded.history_enabled,
                    valid_until=excluded.valid_until,
                    updated_at=excluded.updated_at
                '''
            ),
            {
                'user_id': user_id,
                'plan': plan.value,
                'status': status.value,
                'premium': int(premium_match_detail_enabled),
                'alerts': int(alerts_enabled),
                'history': int(history_enabled),
                'valid_until': _dt_to_iso(valid_until),
                'updated_at': now,
            },
        )
        self._session.commit()

    def get_entitlement(self, user_id: str) -> SubscriptionEntitlement:
        row = self._session.execute(
            text('SELECT * FROM client_entitlements WHERE user_id = :user_id'),
            {'user_id': user_id},
        ).mappings().first()
        if row is None:
            if user_id == 'owner':
                return SubscriptionEntitlement.owner(user_id)
            return SubscriptionEntitlement.free(user_id)
        return SubscriptionEntitlement(
            user_id=str(row['user_id']),
            plan=SubscriptionPlan(str(row['plan'])),
            status=SubscriptionStatus(str(row['status'])),
            premium_match_detail_enabled=bool(row['premium_match_detail_enabled']),
            alerts_enabled=bool(row['alerts_enabled']),
            history_enabled=bool(row['history_enabled']),
            valid_until=_parse_dt(row['valid_until']),
        )

    def upsert_watchlist_item(
        self,
        *,
        user_id: str,
        target_type: str,
        target_id: str,
        alert_preferences: list[str],
    ) -> str:
        now = _now_iso()
        existing = self._session.execute(
            text(
                '''
                SELECT watchlist_id, created_at FROM client_watchlist_items
                WHERE user_id = :user_id AND target_type = :target_type AND target_id = :target_id
                '''
            ),
            {'user_id': user_id, 'target_type': target_type, 'target_id': target_id},
        ).mappings().first()
        watchlist_id = str(existing['watchlist_id']) if existing else uuid4().hex
        created_at = str(existing['created_at']) if existing else now
        self._session.execute(
            text(
                '''
                INSERT INTO client_watchlist_items (
                    watchlist_id, user_id, target_type, target_id, alert_preferences,
                    created_at, updated_at
                ) VALUES (
                    :watchlist_id, :user_id, :target_type, :target_id, :alert_preferences,
                    :created_at, :updated_at
                )
                ON CONFLICT(user_id, target_type, target_id) DO UPDATE SET
                    alert_preferences=excluded.alert_preferences,
                    updated_at=excluded.updated_at
                '''
            ),
            {
                'watchlist_id': watchlist_id,
                'user_id': user_id,
                'target_type': target_type,
                'target_id': target_id,
                'alert_preferences': json.dumps(alert_preferences),
                'created_at': created_at,
                'updated_at': now,
            },
        )
        self._session.commit()
        return watchlist_id

    def list_watchlist(self, user_id: str) -> list[WatchlistItem]:
        rows = self._session.execute(
            text(
                '''
                SELECT * FROM client_watchlist_items
                WHERE user_id = :user_id
                ORDER BY created_at ASC
                '''
            ),
            {'user_id': user_id},
        ).mappings().all()
        return [
            WatchlistItem(
                watchlist_id=str(row['watchlist_id']),
                user_id=str(row['user_id']),
                target_type=str(row['target_type']),
                target_id=str(row['target_id']),
                alert_preferences=list(json.loads(str(row['alert_preferences']))),
                created_at=_parse_dt(str(row['created_at'])) or datetime.now(UTC),
                updated_at=_parse_dt(str(row['updated_at'])) or datetime.now(UTC),
            )
            for row in rows
        ]

    def create_alert(
        self,
        *,
        user_id: str,
        fixture_id: str,
        change_type: str,
        after_summary: str,
        severity: str,
        group_key: str,
        before_summary: str | None = None,
        actionability_before: Actionability | None = None,
        actionability_after: Actionability | None = None,
    ) -> str:
        now = _now_iso()
        existing = self._session.execute(
            text(
                '''
                SELECT alert_id, created_at FROM client_alerts
                WHERE user_id = :user_id AND fixture_id = :fixture_id AND group_key = :group_key
                '''
            ),
            {'user_id': user_id, 'fixture_id': fixture_id, 'group_key': group_key},
        ).mappings().first()
        alert_id = str(existing['alert_id']) if existing else uuid4().hex
        created_at = str(existing['created_at']) if existing else now
        self._session.execute(
            text(
                '''
                INSERT INTO client_alerts (
                    alert_id, user_id, fixture_id, change_type, before_summary, after_summary,
                    actionability_before, actionability_after, severity, group_key,
                    created_at, read_at
                ) VALUES (
                    :alert_id, :user_id, :fixture_id, :change_type, :before_summary,
                    :after_summary, :actionability_before, :actionability_after,
                    :severity, :group_key, :created_at, NULL
                )
                ON CONFLICT(user_id, fixture_id, group_key) DO UPDATE SET
                    change_type=excluded.change_type,
                    before_summary=excluded.before_summary,
                    after_summary=excluded.after_summary,
                    actionability_before=excluded.actionability_before,
                    actionability_after=excluded.actionability_after,
                    severity=excluded.severity
                '''
            ),
            {
                'alert_id': alert_id,
                'user_id': user_id,
                'fixture_id': fixture_id,
                'change_type': change_type,
                'before_summary': before_summary,
                'after_summary': after_summary,
                'actionability_before': _actionability_to_value(actionability_before),
                'actionability_after': _actionability_to_value(actionability_after),
                'severity': severity,
                'group_key': group_key,
                'created_at': created_at,
            },
        )
        self._session.commit()
        return alert_id

    def list_alerts(self, user_id: str) -> list[Alert]:
        rows = self._session.execute(
            text(
                '''
                SELECT * FROM client_alerts
                WHERE user_id = :user_id
                ORDER BY created_at DESC
                '''
            ),
            {'user_id': user_id},
        ).mappings().all()
        return [
            Alert(
                alert_id=str(row['alert_id']),
                user_id=str(row['user_id']),
                fixture_id=str(row['fixture_id']),
                change_type=str(row['change_type']),
                before_summary=row['before_summary'],
                after_summary=str(row['after_summary']),
                actionability_before=_parse_actionability(row['actionability_before']),
                actionability_after=_parse_actionability(row['actionability_after']),
                severity=str(row['severity']),
                group_key=str(row['group_key']),
                created_at=_parse_dt(str(row['created_at'])) or datetime.now(UTC),
                read_at=_parse_dt(row['read_at']),
            )
            for row in rows
        ]

    def insert_audit_record(
        self,
        *,
        user_id: str,
        fixture_id: str,
        actionability: Actionability,
        confidence: str,
        verdict: str,
        evidence_snapshot: dict[str, object],
        generated_text: str | None = None,
    ) -> str:
        audit_id = uuid4().hex
        now = _now_iso()
        self._session.execute(
            text(
                '''
                INSERT INTO client_analysis_audits (
                    audit_id, user_id, fixture_id, actionability, confidence, verdict,
                    evidence_snapshot, generated_text, created_at
                ) VALUES (
                    :audit_id, :user_id, :fixture_id, :actionability, :confidence,
                    :verdict, :evidence_snapshot, :generated_text, :created_at
                )
                '''
            ),
            {
                'audit_id': audit_id,
                'user_id': user_id,
                'fixture_id': fixture_id,
                'actionability': actionability.value,
                'confidence': confidence,
                'verdict': verdict,
                'evidence_snapshot': json.dumps(
                    _redact_secrets(evidence_snapshot),
                    sort_keys=True,
                ),
                'generated_text': generated_text,
                'created_at': now,
            },
        )
        self._session.commit()
        return audit_id

    def list_audit_records(self, user_id: str) -> list[AnalysisAuditRecord]:
        rows = self._session.execute(
            text(
                '''
                SELECT * FROM client_analysis_audits
                WHERE user_id = :user_id
                ORDER BY created_at ASC
                '''
            ),
            {'user_id': user_id},
        ).mappings().all()
        return [
            AnalysisAuditRecord(
                audit_id=str(row['audit_id']),
                user_id=str(row['user_id']),
                fixture_id=str(row['fixture_id']),
                actionability=Actionability(str(row['actionability'])),
                confidence=str(row['confidence']),
                verdict=str(row['verdict']),
                evidence_snapshot=dict(json.loads(str(row['evidence_snapshot']))),
                generated_text=row['generated_text'],
                created_at=_parse_dt(str(row['created_at'])) or datetime.now(UTC),
            )
            for row in rows
        ]

    def insert_conversation_session(
        self,
        *,
        user_id: str,
        fixture_id: str,
        question: str,
        answer: str,
        evidence_ids: list[str],
        verdict_alignment: str,
    ) -> str:
        session_id = uuid4().hex
        self._session.execute(
            text(
                '''
                INSERT INTO client_conversation_sessions (
                    session_id, user_id, fixture_id, question, answer, evidence_ids,
                    verdict_alignment, created_at
                ) VALUES (
                    :session_id, :user_id, :fixture_id, :question, :answer,
                    :evidence_ids, :verdict_alignment, :created_at
                )
                '''
            ),
            {
                'session_id': session_id,
                'user_id': user_id,
                'fixture_id': fixture_id,
                'question': question,
                'answer': answer,
                'evidence_ids': json.dumps(evidence_ids),
                'verdict_alignment': verdict_alignment,
                'created_at': _now_iso(),
            },
        )
        self._session.commit()
        return session_id


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _dt_to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_dt(value: object) -> datetime | None:
    if value in {None, ''}:
        return None
    return datetime.fromisoformat(str(value))


def _actionability_to_value(value: Actionability | None) -> str | None:
    return value.value if value is not None else None


def _parse_actionability(value: object) -> Actionability | None:
    if value in {None, ''}:
        return None
    return Actionability(str(value))


def _redact_secrets(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            lowered = str(key).casefold()
            if any(token in lowered for token in ('key', 'token', 'secret', 'password')):
                continue
            redacted[key] = _redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value
