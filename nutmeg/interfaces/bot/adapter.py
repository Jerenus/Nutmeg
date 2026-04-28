from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class UnsupportedBotCommandError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class BotCommand:
    name: str
    fixture_id: str
    query: str
    raw_text: str


@dataclass(slots=True, frozen=True)
class BotResponse:
    status: str
    text: str
    payload: dict[str, Any]
    error: str | None = None


def parse_bot_message(text: str) -> BotCommand:
    raw_text = text.strip()
    parts = raw_text.split(maxsplit=2)
    if not parts:
        raise UnsupportedBotCommandError(
            'Unsupported bot command. Try `/brief <fixture_id> <query>`.'
        )

    command_name = parts[0].removeprefix('/').casefold()
    if command_name != 'brief':
        raise UnsupportedBotCommandError(
            'Unsupported bot command. Try `/brief <fixture_id> <query>`.'
        )
    if len(parts) < 3 or not parts[1].strip() or not parts[2].strip():
        raise UnsupportedBotCommandError('`/brief` requires a fixture id and query.')

    return BotCommand(
        name='brief',
        fixture_id=parts[1].strip(),
        query=parts[2].strip(),
        raw_text=raw_text,
    )


class BotAdapter:
    def __init__(self, *, workflow, payload_builder=None, fallback_provider=None) -> None:
        self._workflow = workflow
        self._payload_builder = payload_builder or _default_payload_builder
        self._fallback_provider = fallback_provider

    def handle_message(self, text: str) -> BotResponse:
        if _is_help_message(text):
            return BotResponse(
                status='succeeded',
                text=_help_text(),
                payload={'status': 'succeeded', 'mode': 'help', 'sections': {}},
            )

        try:
            command = parse_bot_message(text)
        except UnsupportedBotCommandError as exc:
            if self._fallback_provider is not None:
                return self._fallback_response(text, error=str(exc))
            return BotResponse(
                status='failed',
                text=str(exc),
                payload={'status': 'failed', 'error': str(exc), 'sections': {}},
                error=str(exc),
            )

        result = self._workflow.run(fixture_id=command.fixture_id, query=command.query)
        payload = self._payload_builder(result)
        if result.status == 'failed':
            error = str(payload.get('error') or result.error or 'Bot command failed.')
            if self._fallback_provider is not None:
                return self._fallback_response(command.raw_text, error=error)
            return BotResponse(status='failed', text=error, payload=payload, error=error)
        return BotResponse(status='succeeded', text=self._render_brief(payload), payload=payload)

    def _fallback_response(self, message: str, *, error: str) -> BotResponse:
        try:
            text = self._fallback_provider.respond(message, error=error)
        except Exception as exc:
            fallback_error = (
                f'{error}\n\nLLM fallback is configured but failed: {exc}'
            )
            return BotResponse(
                status='failed',
                text=fallback_error,
                payload={
                    'status': 'failed',
                    'mode': 'llm_fallback',
                    'error': error,
                    'fallback_error': str(exc),
                    'sections': {},
                },
                error=fallback_error,
            )
        return BotResponse(
            status='succeeded',
            text=text,
            payload={
                'status': 'succeeded',
                'mode': 'llm_fallback',
                'source_error': error,
                'sections': {},
            },
        )

    def _render_brief(self, payload: dict[str, Any]) -> str:
        fixture = payload.get('fixture') or {}
        judgment = payload.get('judgment') or {}
        sections = payload.get('sections') or {}
        agent = payload.get('agent') or {}
        lines = [
            f"Match Brief: {fixture.get('home_team')} vs {fixture.get('away_team')}",
            f"Verdict: {judgment.get('verdict')}",
            f"Confidence: {judgment.get('confidence')}",
        ]
        self._extend_section(lines, 'Core reasons', sections.get('core_reasons') or [])
        self._extend_section(lines, 'Tactical evidence', sections.get('tactical_evidence') or [])
        self._extend_section(lines, 'Market evidence', sections.get('market_evidence') or [])
        self._extend_section(lines, 'Caveats', sections.get('caveats') or [])
        if payload.get('generated_synthesis'):
            lines.extend(['Generated synthesis:', str(payload['generated_synthesis'])])
        nodes = agent.get('nodes') or []
        if nodes:
            lines.append(f"Agent nodes: {' -> '.join(nodes)}")
        return '\n'.join(lines)

    def _extend_section(self, lines: list[str], title: str, items: list[str]) -> None:
        if not items:
            return
        lines.append(f'{title}:')
        lines.extend(f'- {item}' for item in items)


def _default_payload_builder(result) -> dict[str, Any]:
    from nutmeg.interfaces.cli import build_match_brief_payload

    return build_match_brief_payload(result)


def _is_help_message(text: str) -> bool:
    normalized = text.strip().casefold()
    return normalized in {'/start', 'start', '/help', 'help'}


def _help_text() -> str:
    return '\n'.join(
        [
            'Nutmeg bot is online.',
            'Use `/brief <fixture_id> <query>` for a match brief.',
            'Find candidates locally with `popular-matches --league epl --days 3`.',
            'For ranked daily candidates use `today-briefs --sort popularity`.',
            'This bot replies only when `telegram-bot-run` is running locally.',
        ]
    )
