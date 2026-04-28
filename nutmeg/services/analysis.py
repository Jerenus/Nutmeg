from __future__ import annotations

from datetime import UTC, datetime

from nutmeg.agents.router import QueryIntent, classify_intent
from nutmeg.domain.analysis import AnalysisEvidenceSummary, AnalysisJudgment, FixtureAnalysisResult


class InsufficientEvidenceError(ValueError):
    pass


class AnalysisService:
    def __init__(self, *, snapshot_service, odds_service) -> None:
        self._snapshot_service = snapshot_service
        self._odds_service = odds_service

    def analyze_match(self, fixture_id: str, *, query: str) -> FixtureAnalysisResult:
        intent = classify_intent(query)
        if intent != QueryIntent.DECISIONAL:
            raise InsufficientEvidenceError('Not enough evidence for a direct call.')

        snapshot = self._snapshot_service.build_snapshot(fixture_id, recent_matches=5)
        odds = self._odds_service.build_snapshot(fixture_id, persist_history=False)

        tactical_summary = self._build_tactical_summary(snapshot)
        snapshot_summary = self._build_snapshot_summary(snapshot)
        odds_summary, market_favored = self._build_odds_summary(snapshot, odds)
        market_shape_summary = self._build_market_shape_summary(odds)
        caveats = self._build_caveats(
            tactical_summary,
            odds_summary,
            market_shape_summary,
            odds,
        )

        if not tactical_summary and not snapshot_summary and not odds_summary:
            raise InsufficientEvidenceError('Not enough evidence for a direct call.')

        context_favored = self._context_favored(snapshot)
        conflict_state = self._conflict_state(context_favored, market_favored)
        verdict, counterargument = self._build_verdict_and_counter(
            snapshot,
            context_favored=context_favored,
            market_favored=market_favored,
            conflict_state=conflict_state,
        )
        confidence = self._build_confidence(
            tactical_summary=tactical_summary,
            odds_summary=odds_summary,
            caveats=caveats,
            conflict_state=conflict_state,
        )

        core_reasons: list[str] = []
        for bucket in (
            tactical_summary,
            snapshot_summary,
            odds_summary,
            market_shape_summary,
            caveats,
        ):
            if bucket:
                core_reasons.append(bucket[0])
        core_reasons = core_reasons[:3]

        return FixtureAnalysisResult(
            fixture=snapshot.fixture,
            intent=intent,
            query=query,
            evidence=AnalysisEvidenceSummary(
                tactical_summary=tactical_summary,
                snapshot_summary=snapshot_summary,
                odds_summary=odds_summary,
                market_shape_summary=market_shape_summary,
                caveats=caveats,
            ),
            judgment=AnalysisJudgment(
                verdict=verdict,
                core_reasons=core_reasons,
                counterargument=counterargument,
                confidence=confidence,
            ),
            conflict_state=conflict_state,
            generated_at=datetime.now(UTC).replace(microsecond=0),
        )

    def _build_tactical_summary(self, snapshot) -> list[str]:
        tactical: list[str] = []
        home_lineup = snapshot.home.lineup
        away_lineup = snapshot.away.lineup
        if home_lineup and away_lineup and home_lineup.formation and away_lineup.formation:
            tactical.append(
                f'{snapshot.fixture.home_team} project a {home_lineup.formation} against '
                f"{snapshot.fixture.away_team}'s {away_lineup.formation} shape."
            )

        matchup = snapshot.matchup
        if matchup and matchup.home_trend and matchup.away_trend:
            home_xg = matchup.home_trend.xg_for_per_match
            away_xga = matchup.away_trend.xg_against_per_match
            if home_xg is not None and away_xga is not None and home_xg >= away_xga:
                tactical.append(
                    f'{snapshot.fixture.home_team} recent chance creation '
                    f'({home_xg:.2f} xG) matches up well against '
                    f"{snapshot.fixture.away_team}'s recent concession trend "
                    f'({away_xga:.2f} xGA).'
                )

        if snapshot.home.availability and snapshot.home.availability.bench_depth:
            bench = snapshot.home.availability.bench_depth
            if bench.label in {'strong', 'stable'}:
                tactical.append(
                    f'{snapshot.fixture.home_team} bench depth is rated {bench.label}, '
                    'which supports the game-plan floor.'
                )
        return tactical

    def _build_snapshot_summary(self, snapshot) -> list[str]:
        summary: list[str] = []
        if snapshot.home.market_value and snapshot.away.market_value:
            home_value = snapshot.home.market_value.total_market_value_eur or 0
            away_value = snapshot.away.market_value.total_market_value_eur or 0
            if home_value > away_value:
                summary.append(
                    f'{snapshot.fixture.home_team} carry the stronger squad value profile.'
                )
            elif away_value > home_value:
                summary.append(
                    f'{snapshot.fixture.away_team} carry the stronger squad value profile.'
                )

        if snapshot.home.availability and snapshot.home.availability.expected_absences_summary:
            summary.append(
                f"{snapshot.fixture.home_team} availability: "
                f"{snapshot.home.availability.expected_absences_summary}"
            )
        if snapshot.away.availability and snapshot.away.availability.expected_absences_summary:
            summary.append(
                f"{snapshot.fixture.away_team} availability: "
                f"{snapshot.away.availability.expected_absences_summary}"
            )
        return summary

    def _build_odds_summary(self, snapshot, odds) -> tuple[list[str], str | None]:
        summary: list[str] = []
        market = odds.markets.get('match_winner')
        home_prob = None
        away_prob = None
        if market and market.status == 'available':
            for outcome in market.outcomes:
                if outcome.outcome_key == 'home':
                    home_prob = outcome.fair_probability
                if outcome.outcome_key == 'away':
                    away_prob = outcome.fair_probability
            if home_prob is not None and away_prob is not None:
                favored = (
                    snapshot.fixture.home_team
                    if home_prob >= away_prob
                    else snapshot.fixture.away_team
                )
                edge = abs(home_prob - away_prob)
                summary.append(
                    f'Market fair view leans {favored} with a {edge:.1%} edge over the other side.'
                )
                movement_summary = self._market_movement_summary(odds, market)
                if movement_summary is not None:
                    summary.append(movement_summary)
                return summary, favored
        summary.append('No trustworthy market snapshot is available yet.')
        return summary, None

    def _market_movement_summary(self, odds, market) -> str | None:
        history = odds.history or {}
        market_history = history.get('match_winner')
        if not market_history or market_history.movement != 'moving':
            return None
        drift = market_history.drift_vs_current or {}
        if not drift:
            return None
        outcome_key, drift_value = max(drift.items(), key=lambda item: abs(item[1]))
        if abs(drift_value) < 0.03:
            return None
        direction = 'toward' if drift_value > 0 else 'away from'
        outcome_name = self._outcome_label(market, outcome_key)
        span = market_history.movement_span
        span_text = f' over a {span:.1%} span' if span is not None else ''
        return (
            f'Market movement is {direction} {outcome_name}: '
            f'drift {drift_value:+.1%}{span_text}.'
        )

    def _outcome_label(self, market, outcome_key: str) -> str:
        for outcome in market.outcomes:
            if outcome.outcome_key == outcome_key:
                return outcome.outcome_name.lower()
        return outcome_key

    def _build_market_shape_summary(self, odds) -> list[str]:
        summary: list[str] = []
        totals_market = odds.markets.get('totals_2_5')
        btts_market = odds.markets.get('btts')

        over_prob = self._probability_for(totals_market, 'over')
        yes_prob = self._probability_for(btts_market, 'yes')

        if over_prob is not None and yes_prob is not None:
            if over_prob >= 0.55 and yes_prob >= 0.55:
                summary.append(
                    'Market shape points to an open game with both scoring and total volume live.'
                )
            elif over_prob <= 0.45 and yes_prob <= 0.45:
                summary.append(
                    'Market shape points to a lower-event game with fewer '
                    'clean scoring sequences expected.'
                )
            else:
                summary.append(
                    'Market shape is mixed: totals and BTTS do not fully agree on game texture.'
                )

        handicap_pressure = self._handicap_pressure_summary(odds)
        if handicap_pressure is not None:
            summary.append(handicap_pressure)
        return summary

    def _handicap_pressure_summary(self, odds) -> str | None:
        strongest_line = 0.0
        strongest_market = None
        for market_key, market in odds.markets.items():
            if not market_key.startswith('asian_handicap_') or market.status != 'available':
                continue
            line = self._market_line_value(market)
            if line is None or line < 2.0 or line < strongest_line:
                continue
            home_prob = self._probability_for(market, 'home')
            away_prob = self._probability_for(market, 'away')
            if home_prob is None or away_prob is None:
                continue
            strongest_line = line
            strongest_market = market
        if strongest_market is None:
            return None
        return (
            f'Asian handicap pressure reaches {strongest_market.line}: the favorite is being '
            'priced to win by margin, not just edge the match.'
        )

    def _market_line_value(self, market) -> float | None:
        if market.line in (None, ''):
            return None
        try:
            return float(market.line)
        except (TypeError, ValueError):
            return None

    def _probability_for(self, market, outcome_key: str) -> float | None:
        if not market or market.status != 'available':
            return None
        for outcome in market.outcomes:
            if outcome.outcome_key == outcome_key:
                return outcome.fair_probability
        return None

    def _build_caveats(
        self,
        tactical_summary,
        odds_summary,
        market_shape_summary,
        odds,
    ) -> list[str]:
        caveats: list[str] = []
        tactical_text = ' '.join(tactical_summary).lower()
        has_shape_signal = 'project a' in tactical_text
        has_matchup_signal = 'chance creation' in tactical_text
        if not tactical_summary or (not has_shape_signal and not has_matchup_signal):
            caveats.append('Tactical evidence is limited, so the matchup read stays coarse.')
        market = odds.markets.get('match_winner')
        if not market or market.status != 'available':
            caveats.append('Odds context is unavailable, so market evidence is limited.')
        elif odds_summary and odds_summary[0].startswith('No trustworthy market snapshot'):
            caveats.append('Market pricing could not be trusted enough for a firm edge.')

        totals_market = odds.markets.get('totals_2_5')
        btts_market = odds.markets.get('btts')
        missing_market_shape = (
            not totals_market
            or totals_market.status != 'available'
            or not btts_market
            or btts_market.status != 'available'
        )
        if missing_market_shape and not market_shape_summary:
            caveats.append('Market shape is partial, so game-texture confidence stays limited.')
        disagreement = self._bookmaker_disagreement_summary(market)
        if disagreement is not None:
            caveats.append(disagreement)
        return caveats

    def _bookmaker_disagreement_summary(self, market) -> str | None:
        if not market or market.status != 'available':
            return None
        widest_outcome = None
        widest_ratio = 0.0
        for outcome in market.outcomes:
            prices = [quote.decimal_odds for quote in outcome.bookmaker_quotes]
            if len(prices) < 2:
                continue
            shortest = min(prices)
            if shortest <= 0:
                continue
            ratio = max(prices) / shortest
            if ratio > widest_ratio:
                widest_ratio = ratio
                widest_outcome = outcome.outcome_name.lower()
        if widest_ratio < 1.25 or widest_outcome is None:
            return None
        return (
            f'Bookmaker disagreement is elevated on {widest_outcome} pricing '
            f'(widest quote ratio {widest_ratio:.2f}), so market confidence is capped.'
        )

    def _context_favored(self, snapshot) -> str | None:
        score = 0
        if snapshot.home.market_value and snapshot.away.market_value:
            home_value = snapshot.home.market_value.total_market_value_eur or 0
            away_value = snapshot.away.market_value.total_market_value_eur or 0
            score += 1 if home_value > away_value else -1 if away_value > home_value else 0
        matchup = snapshot.matchup
        if matchup and matchup.home_trend and matchup.away_trend:
            home_xg = matchup.home_trend.xg_for_per_match or 0
            away_xga = matchup.away_trend.xg_against_per_match or 0
            score += 1 if home_xg >= away_xga else 0
        if snapshot.home.availability and snapshot.away.availability:
            home_abs = snapshot.home.availability.expected_absences_summary or ''
            away_abs = snapshot.away.availability.expected_absences_summary or ''
            if home_abs and not away_abs:
                score -= 1
            elif away_abs and not home_abs:
                score += 1
        if score > 0:
            return snapshot.fixture.home_team
        if score < 0:
            return snapshot.fixture.away_team
        return None

    def _conflict_state(self, context_favored: str | None, market_favored: str | None) -> str:
        if context_favored and market_favored and context_favored != market_favored:
            return 'conflicted'
        if context_favored or market_favored:
            return 'aligned'
        return 'insufficient'

    def _build_verdict_and_counter(
        self,
        snapshot,
        *,
        context_favored,
        market_favored,
        conflict_state,
    ):
        if conflict_state == 'conflicted':
            favored = context_favored or snapshot.fixture.home_team
            verdict = f'Lean {favored} only with caution; the signals are split.'
            counter = (
                'The market pushes against the team-context read, which lowers '
                'conviction and raises the risk of narrative overreach.'
            )
            return verdict, counter

        if market_favored == snapshot.fixture.away_team:
            verdict = (
                f'Avoid forcing a home-side position; '
                f'the market leans {snapshot.fixture.away_team}.'
            )
            counter = (
                f'{snapshot.fixture.home_team} still hold home-pitch leverage '
                f'and can outperform the price.'
            )
            return verdict, counter

        if (
            context_favored == snapshot.fixture.home_team
            or market_favored == snapshot.fixture.home_team
        ):
            verdict = f'Lean {snapshot.fixture.home_team} pre-match.'
            counter = (
                f'{snapshot.fixture.away_team} can still punish '
                f'transition moments if the match opens up.'
            )
            return verdict, counter

        verdict = (
            'Hold a cautious lean only; team context is stronger '
            'than market context here.'
        )
        counter = (
            'Without reliable odds confirmation, this read can drift '
            'into narrative bias.'
        )
        return verdict, counter

    def _build_confidence(self, *, tactical_summary, odds_summary, caveats, conflict_state) -> str:
        if conflict_state == 'conflicted':
            return 'low'
        has_bookmaker_disagreement = any(
            'bookmaker disagreement' in item.lower() for item in caveats
        )
        score = 0
        tactical_limited = any('tactical evidence is limited' in item.lower() for item in caveats)
        if tactical_summary and not tactical_limited:
            score += 1
        if odds_summary and not odds_summary[0].startswith('No trustworthy market snapshot'):
            score += 1
        confidence = 'high' if score == 2 else 'medium' if score == 1 else 'low'
        if has_bookmaker_disagreement and confidence == 'high':
            return 'medium'
        return confidence
