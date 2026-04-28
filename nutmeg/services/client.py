from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Protocol

from nutmeg.domain.client import (
    RESPONSIBLE_USE_COPY,
    Actionability,
    EvidenceItem,
    EvidenceStaleness,
    FreshnessHealth,
    FreshnessLedger,
)
from nutmeg.domain.fixtures import Fixture, FixtureStatus


class ClientStateRepository(Protocol):
    def get_entitlement(self, user_id: str):
        ...

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
        ...

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
        ...


class FixtureListService(Protocol):
    def list_upcoming(self, league: str, days: int, demo: bool = False):
        ...


class PopularityRanker(Protocol):
    def rank(self, fixtures: list[Fixture], *, limit: int | None = None):
        ...


class ValueBoardService(Protocol):
    def build_board(self, *, league: str, days: int, limit: int, min_edge: float):
        ...


class MatchBriefProvider(Protocol):
    def build_brief(self, fixture_id: str) -> dict[str, Any]:
        ...


class ClientService:
    def __init__(
        self,
        *,
        state_repository: ClientStateRepository,
        default_user_id: str = 'owner',
        fixture_service: FixtureListService | None = None,
        popularity_ranker: PopularityRanker | None = None,
        value_board_service: ValueBoardService | None = None,
        match_brief_provider: MatchBriefProvider | None = None,
        odds_provider: object | None = None,
        tactical_provider: object | None = None,
        player_provider: object | None = None,
        information_provider: object | None = None,
        prediction_repository: object | None = None,
    ) -> None:
        self._state_repository = state_repository
        self.default_user_id = default_user_id
        self._fixture_service = fixture_service
        self._popularity_ranker = popularity_ranker
        self._value_board_service = value_board_service
        self._match_brief_provider = match_brief_provider
        self._odds_provider = odds_provider
        self._tactical_provider = tactical_provider
        self._player_provider = player_provider
        self._information_provider = information_provider
        self._prediction_repository = prediction_repository

    def set_information_provider(self, provider: object) -> None:
        self._information_provider = provider

    def status(self, user_id: str | None = None) -> dict[str, object]:
        resolved_user_id = user_id or self.default_user_id
        entitlement = self._state_repository.get_entitlement(resolved_user_id)
        health = FreshnessLedger(
            health=FreshnessHealth.HEALTHY,
            blocking_reasons=[],
            analysis_generated_at=datetime.now(UTC).replace(microsecond=0),
        )
        return {
            'user_id': resolved_user_id,
            'health': health.to_dict(),
            'providers': {},
            'entitlements': entitlement.to_dict(),
            'responsible_use': RESPONSIBLE_USE_COPY,
        }

    def daily_feed(
        self,
        *,
        user_id: str | None = None,
        league: str = 'epl',
        days: int = 3,
        limit: int = 5,
        demo: bool = False,
    ) -> dict[str, object]:
        resolved_user_id = user_id or self.default_user_id
        generated_at = datetime.now(UTC).replace(microsecond=0)
        if self._fixture_service is None or self._popularity_ranker is None:
            ledger = FreshnessLedger(
                health=FreshnessHealth.PARTIAL,
                blocking_reasons=['client feed dependencies are not configured'],
                analysis_generated_at=generated_at,
            )
            return {
                'user_id': resolved_user_id,
                'league': league,
                'days': days,
                'generated_at': generated_at.isoformat(),
                'opportunities': [],
                'health': ledger.to_dict(),
                'responsible_use': RESPONSIBLE_USE_COPY,
            }

        fixtures = list(self._fixture_service.list_upcoming(league, days, demo=demo))
        ranked = self._popularity_ranker.rank(fixtures, limit=limit)
        value_by_fixture = self._value_candidates_by_fixture(
            league=league,
            days=days,
            limit=limit,
        )
        opportunities = [
            self._opportunity_payload(
                ranked_fixture=ranked_fixture,
                value_candidate=value_by_fixture.get(ranked_fixture.fixture.fixture_id),
                generated_at=generated_at,
            )
            for ranked_fixture in ranked
        ]
        blocking_reasons = [
            reason
            for opportunity in opportunities
            for reason in opportunity['freshness']['blocking_reasons']
        ]
        health = FreshnessHealth.PARTIAL if blocking_reasons else FreshnessHealth.HEALTHY
        ledger = FreshnessLedger(
            health=health,
            blocking_reasons=sorted(set(blocking_reasons)),
            analysis_generated_at=generated_at,
        )
        return {
            'user_id': resolved_user_id,
            'league': league,
            'days': days,
            'generated_at': generated_at.isoformat(),
            'opportunities': opportunities,
            'health': ledger.to_dict(),
            'responsible_use': RESPONSIBLE_USE_COPY,
        }

    def match_workspace(
        self,
        *,
        fixture_id: str,
        user_id: str | None = None,
    ) -> dict[str, object]:
        resolved_user_id = user_id or self.default_user_id
        entitlement = self._state_repository.get_entitlement(resolved_user_id)
        generated_at = datetime.now(UTC).replace(microsecond=0)
        brief = self._build_brief(fixture_id)
        fixture = dict(brief.get('fixture') or {'fixture_id': fixture_id, 'league_code': 'epl'})
        league = str(fixture.get('league_code') or fixture.get('league') or 'epl')
        judgment = dict(brief.get('judgment') or {})
        value_payload = self._value_payload(
            self._value_candidates_by_fixture(league=league, days=3, limit=10).get(fixture_id)
        )
        market = self._provider_payload(self._odds_provider, 'build_market', fixture_id)
        tactics = self._provider_payload(self._tactical_provider, 'build_tactics', fixture_id)
        players = self._provider_payload(self._player_provider, 'build_players', fixture_id)
        information = self._information_payload(fixture_id=fixture_id, fixture=fixture)
        caveats = list((brief.get('sections') or {}).get('caveats') or [])
        actionability = Actionability.VALUE if value_payload else Actionability.LEAN
        if brief.get('conflict_state') not in {None, '', 'aligned'}:
            actionability = Actionability.WATCH
            caveats.append('market/tactical conflict')
        premium_restricted = not entitlement.premium_match_detail_enabled
        if premium_restricted:
            actionability = Actionability.WATCH
            gated_payload = {
                'gated': True,
                'message': '升级后查看高级价值分析',
            }
            value_payload = gated_payload
            market = gated_payload
            tactics = gated_payload
            players = gated_payload
            information = gated_payload
        confidence = str(judgment.get('confidence') or 'low')
        verdict = str(judgment.get('verdict') or 'No grounded verdict available.')
        evidence = self._workspace_evidence(
            brief=brief,
            value_payload=value_payload,
            market=market,
            tactics=tactics,
            players=players,
            information=information,
            generated_at=generated_at,
        )
        freshness = FreshnessLedger(
            health=FreshnessHealth.HEALTHY,
            blocking_reasons=[],
            analysis_generated_at=generated_at,
        )
        evidence_snapshot = {
            'fixture_id': fixture_id,
            'actionability': actionability.value,
            'judgment': judgment,
            'value': value_payload,
            'market': market,
            'tactics': tactics,
            'players': players,
            'information': information,
            'freshness': freshness.to_dict(),
            'evidence': evidence,
        }
        audit_id = self._state_repository.insert_audit_record(
            user_id=resolved_user_id,
            fixture_id=fixture_id,
            actionability=actionability,
            confidence=confidence,
            verdict=verdict,
            evidence_snapshot=evidence_snapshot,
            generated_text=verdict,
        )
        return {
            'user_id': resolved_user_id,
            'fixture_id': fixture_id,
            'fixture': fixture,
            'actionability': actionability.value,
            'judgment': judgment,
            'value': value_payload,
            'market': market,
            'tactics': tactics,
            'players': players,
            'information': information,
            'evidence': evidence,
            'freshness': freshness.to_dict(),
            'caveats': caveats,
            'audit_id': audit_id,
            'entitlements': entitlement.to_dict(),
            'premium_restricted': premium_restricted,
            'responsible_use': RESPONSIBLE_USE_COPY,
        }

    def answer_question(
        self,
        *,
        fixture_id: str,
        question: str,
        user_id: str | None = None,
    ) -> dict[str, object]:
        resolved_user_id = user_id or self.default_user_id
        normalized = question.casefold()
        if any(token in normalized for token in ('place', 'guarantee', 'profit', '下注')):
            answer = '不能替你下注、保证盈利或连接投注平台；我只能基于现有证据做分析辅助。'
            payload = {
                'answer': answer,
                'confidence': 'none',
                'evidence': [],
                'refused': True,
                'refusal_reason': 'out_of_scope_betting_execution',
            }
            self._record_conversation(
                user_id=resolved_user_id,
                fixture_id=fixture_id,
                question=question,
                answer=answer,
                evidence=[],
                verdict_alignment='refused',
            )
            return payload

        workspace = self.match_workspace(fixture_id=fixture_id, user_id=resolved_user_id)
        judgment = workspace.get('judgment') or {}
        verdict = str(judgment.get('verdict') or 'No grounded verdict available.')
        confidence = str(judgment.get('confidence') or 'low')
        caveats = list(workspace.get('caveats') or [])
        caveat_text = f" 风险点：{'；'.join(caveats)}" if caveats else ''
        answer = (
            f'{verdict} 置信度：{confidence}。'
            f'结论只基于当前可见证据和 freshness ledger。{caveat_text}'
        )
        evidence = list(workspace.get('evidence') or [])
        self._record_conversation(
            user_id=resolved_user_id,
            fixture_id=fixture_id,
            question=question,
            answer=answer,
            evidence=evidence,
            verdict_alignment='deterministic',
        )
        return {
            'answer': answer,
            'confidence': confidence,
            'evidence': evidence,
            'refused': False,
            'refusal_reason': None,
        }

    def save_watchlist_item(
        self,
        *,
        user_id: str,
        target_type: str,
        target_id: str,
        alert_preferences: list[str] | None = None,
    ) -> dict[str, object]:
        watchlist_id = self._state_repository.upsert_watchlist_item(
            user_id=user_id,
            target_type=target_type,
            target_id=target_id,
            alert_preferences=alert_preferences or [],
        )
        return {
            'watchlist_id': watchlist_id,
            'user_id': user_id,
            'target_type': target_type,
            'target_id': target_id,
            'alert_preferences': alert_preferences or [],
        }

    def create_material_alert(
        self,
        *,
        user_id: str,
        fixture_id: str,
        change_type: str,
        before_summary: str,
        after_summary: str,
        actionability_before: str,
        actionability_after: str,
    ) -> dict[str, object]:
        alert_id = self._state_repository.create_alert(
            user_id=user_id,
            fixture_id=fixture_id,
            change_type=change_type,
            before_summary=before_summary,
            after_summary=after_summary,
            severity='important',
            group_key=f'{fixture_id}:{change_type}',
            actionability_before=Actionability(actionability_before),
            actionability_after=Actionability(actionability_after),
        )
        return {
            'alert_id': alert_id,
            'user_id': user_id,
            'fixture_id': fixture_id,
            'change_type': change_type,
            'before_summary': before_summary,
            'after_summary': after_summary,
            'actionability_before': actionability_before,
            'actionability_after': actionability_after,
            'severity': 'important',
            'why_it_matters': 'Material evidence changed and may alter actionability.',
        }

    def alerts(self, *, user_id: str) -> dict[str, object]:
        return {
            'alerts': [
                self._alert_to_dict(alert)
                for alert in self._state_repository.list_alerts(user_id)
            ]
        }

    def record_prediction(
        self,
        *,
        user_id: str,
        fixture_id: str,
        pick: str,
        source_audit_id: str | None = None,
        client_notes: str | None = None,
    ) -> dict[str, object]:
        notes = ' | '.join(
            item
            for item in [
                f'source_audit_id={source_audit_id}' if source_audit_id else None,
                client_notes,
            ]
            if item
        )
        prediction_id = None
        if self._prediction_repository is not None:
            prediction_id = self._prediction_repository.record_prediction(
                user_id=user_id,
                fixture_id=fixture_id,
                league='epl',
                home_team='home',
                away_team='away',
                probabilities={'home': 1 / 3, 'draw': 1 / 3, 'away': 1 / 3},
                picked_outcome=pick,
                notes=notes,
            )
        calibration_review = None
        if self._prediction_repository is not None and hasattr(
            self._prediction_repository,
            'review',
        ):
            review = self._prediction_repository.review(user_id=user_id)
            calibration_review = (
                asdict(review)
                if hasattr(review, '__dataclass_fields__')
                else dict(review)
            )
        return {
            'prediction_id': prediction_id,
            'fixture_id': fixture_id,
            'pick': pick,
            'source_audit_id': source_audit_id,
            'calibration_review': calibration_review,
            'status': 'recorded',
        }

    def _record_conversation(
        self,
        *,
        user_id: str,
        fixture_id: str,
        question: str,
        answer: str,
        evidence: list[dict[str, object]],
        verdict_alignment: str,
    ) -> None:
        evidence_ids = [
            str(item.get('evidence_id') or item.get('source_name') or index)
            for index, item in enumerate(evidence)
        ]
        self._state_repository.insert_conversation_session(
            user_id=user_id,
            fixture_id=fixture_id,
            question=question,
            answer=answer,
            evidence_ids=evidence_ids,
            verdict_alignment=verdict_alignment,
        )

    def _alert_to_dict(self, alert) -> dict[str, object]:
        return {
            'alert_id': alert.alert_id,
            'user_id': alert.user_id,
            'fixture_id': alert.fixture_id,
            'change_type': alert.change_type,
            'before_summary': alert.before_summary,
            'after_summary': alert.after_summary,
            'actionability_before': (
                alert.actionability_before.value if alert.actionability_before else None
            ),
            'actionability_after': (
                alert.actionability_after.value if alert.actionability_after else None
            ),
            'severity': alert.severity,
            'group_key': alert.group_key,
            'created_at': alert.created_at.isoformat(),
            'read_at': alert.read_at.isoformat() if alert.read_at else None,
        }

    def _value_candidates_by_fixture(
        self,
        *,
        league: str,
        days: int,
        limit: int,
    ) -> dict[str, object]:
        if self._value_board_service is None:
            return {}
        try:
            board = self._value_board_service.build_board(
                league=league,
                days=days,
                limit=limit,
                min_edge=0.03,
            )
        except Exception:
            return {}
        return {candidate.fixture_id: candidate for candidate in board.candidates}

    def _build_brief(self, fixture_id: str) -> dict[str, Any]:
        if self._match_brief_provider is None:
            return {
                'fixture_id': fixture_id,
                'fixture': {'fixture_id': fixture_id, 'league_code': 'epl'},
                'judgment': {
                    'verdict': 'No grounded verdict available.',
                    'confidence': 'low',
                    'core_reasons': [],
                    'counterargument': 'Match brief provider is unavailable.',
                },
                'sections': {'caveats': ['match brief provider unavailable']},
                'conflict_state': 'unknown',
            }
        return self._match_brief_provider.build_brief(fixture_id)

    def _provider_payload(self, provider: object | None, method_name: str, fixture_id: str):
        if provider is None:
            return {
                'source_name': 'Nutmeg',
                'summary': f'{method_name} unavailable',
                'staleness': EvidenceStaleness.UNAVAILABLE.value,
            }
        method = getattr(provider, method_name)
        return method(fixture_id)

    def _information_payload(
        self,
        *,
        fixture_id: str,
        fixture: dict[str, object],
    ) -> dict[str, object]:
        if self._information_provider is None:
            return {
                'fixture_id': fixture_id,
                'source_name': 'Nutmeg information provider',
                'summary': 'Information unavailable.',
                'staleness': EvidenceStaleness.UNAVAILABLE.value,
                'status': 'unavailable',
                'source_count': 0,
                'latest_published_at': None,
                'items': [],
                'warnings': ['information provider unavailable'],
            }
        method = self._information_provider.build_information
        try:
            return method(
                fixture_id,
                home_team=fixture.get('home_team'),
                away_team=fixture.get('away_team'),
            )
        except TypeError:
            return method(fixture_id)

    def _value_payload(self, value_candidate) -> dict[str, object] | None:
        if value_candidate is None:
            return None
        return {
            'outcome_key': value_candidate.outcome_key,
            'outcome_name': value_candidate.outcome_name,
            'model_probability': value_candidate.model_probability,
            'market_probability': value_candidate.market_probability,
            'edge': value_candidate.edge,
            'best_odds': value_candidate.best_odds,
            'expected_value': value_candidate.expected_value,
            'quarter_kelly_fraction': value_candidate.quarter_kelly_fraction,
            'rating': value_candidate.rating,
            'model_name': value_candidate.model_name,
            'source_notes': list(value_candidate.source_notes),
        }

    def _opportunity_payload(
        self,
        *,
        ranked_fixture,
        value_candidate,
        generated_at: datetime,
    ) -> dict[str, object]:
        fixture = ranked_fixture.fixture
        blocking_reasons: list[str] = []
        actionability = Actionability.WATCH
        edge_status = 'unavailable'
        suggested_action = 'refresh_or_wait'
        value_payload = None
        if value_candidate is None:
            blocking_reasons.append('odds/value evidence unavailable')
        else:
            actionability = Actionability.VALUE
            edge_status = 'positive_edge'
            suggested_action = 'inspect_match'
            value_payload = self._value_payload(value_candidate)

        if self._is_live_or_near_kickoff(fixture, generated_at):
            actionability = Actionability.WATCH
            suggested_action = 'wait_for_late_data'
            blocking_reasons.append('live or near kickoff risk')

        health = FreshnessHealth.PARTIAL if blocking_reasons else FreshnessHealth.HEALTHY
        freshness = FreshnessLedger(
            health=health,
            blocking_reasons=blocking_reasons,
            analysis_generated_at=generated_at,
        )
        return {
            'fixture_id': fixture.fixture_id,
            'league': fixture.league_code,
            'home_team': fixture.home_team,
            'away_team': fixture.away_team,
            'kickoff_at': fixture.kickoff_at.isoformat(),
            'status': fixture.status.value,
            'rank': ranked_fixture.rank,
            'score': ranked_fixture.popularity.score,
            'tier': ranked_fixture.popularity.tier,
            'actionability': actionability.value,
            'confidence': 'medium' if value_candidate is not None else 'low',
            'edge_status': edge_status,
            'reasons': [
                *list(ranked_fixture.popularity.reasons),
                *(value_payload['source_notes'] if value_payload else []),
            ],
            'freshness': freshness.to_dict(),
            'suggested_action': suggested_action,
            'value': value_payload,
            'fixture': asdict(fixture),
        }

    def _workspace_evidence(
        self,
        *,
        brief: dict[str, Any],
        value_payload: dict[str, object] | None,
        market,
        tactics,
        players,
        information,
        generated_at: datetime,
    ) -> list[dict[str, object]]:
        evidence = [
            self._evidence_dict(
                kind='brief',
                source_name='Nutmeg match brief',
                summary=str((brief.get('judgment') or {}).get('verdict') or 'No verdict'),
                retrieved_at=str(brief.get('generated_at') or generated_at.isoformat()),
            )
        ]
        if value_payload is not None and 'edge' in value_payload:
            evidence.append(
                self._evidence_dict(
                    kind='value',
                    source_name='Nutmeg value board',
                    summary=f"edge={value_payload['edge']}",
                    retrieved_at=generated_at.isoformat(),
                )
            )
        for kind, payload in [
            ('market', market),
            ('tactics', tactics),
            ('players', players),
            ('information', information),
        ]:
            if isinstance(payload, dict):
                evidence.append(
                    self._evidence_dict(
                        kind=kind,
                        source_name=str(payload.get('source_name') or 'Nutmeg'),
                        summary=str(payload.get('summary') or f'{kind} unavailable'),
                        retrieved_at=str(payload.get('retrieved_at') or generated_at.isoformat()),
                        staleness=str(payload.get('staleness') or EvidenceStaleness.FRESH.value),
                    )
                )
        return evidence

    def _evidence_dict(
        self,
        *,
        kind: str,
        source_name: str,
        summary: str,
        retrieved_at: str,
        staleness: str = 'fresh',
    ) -> dict[str, object]:
        item = EvidenceItem(
            kind=kind,
            source_name=source_name,
            summary=summary,
            staleness=EvidenceStaleness(staleness),
            retrieved_at=datetime.fromisoformat(retrieved_at),
        )
        return item.to_dict()

    def _is_live_or_near_kickoff(self, fixture: Fixture, now: datetime) -> bool:
        if fixture.status == FixtureStatus.LIVE:
            return True
        delta_hours = (fixture.kickoff_at - now).total_seconds() / 3600
        return -0.5 <= delta_hours <= 2
