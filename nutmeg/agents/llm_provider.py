from __future__ import annotations

import json
from typing import Any

import httpx

from nutmeg.config.settings import AppSettings
from nutmeg.domain.analysis import FixtureAnalysisResult


class PortkeySynthesisError(RuntimeError):
    pass


class OpenAiBotFallbackError(RuntimeError):
    pass


class OpenAiBotFallbackProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def respond(self, message: str, *, error: str | None = None) -> str:
        response = self._client.post(
            '/responses',
            headers={
                'authorization': f'Bearer {self._api_key}',
                'content-type': 'application/json',
            },
            json={
                'model': self._model,
                'input': [
                    {
                        'role': 'system',
                        'content': (
                            'You are Nutmeg, a private football analysis bot. '
                            'Reply in the user language, be concise, and do not invent '
                            'live match facts. If the user asks for matches, explain how '
                            'to use `popular-matches` and `/brief <fixture_id> <query>`. '
                            'If a deterministic Nutmeg command failed, explain the failure '
                            'and give the next actionable command.'
                        ),
                    },
                    {
                        'role': 'user',
                        'content': self._fallback_prompt(message=message, error=error),
                    },
                ],
            },
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise OpenAiBotFallbackError(
                f'OpenAI bot fallback request failed ({response.status_code}).'
            ) from exc
        text = self._extract_text(response.json())
        if not text:
            raise OpenAiBotFallbackError('OpenAI did not return fallback text.')
        return text

    def _fallback_prompt(self, *, message: str, error: str | None) -> str:
        payload = {
            'operator_message': message,
            'deterministic_error': error,
            'available_commands': [
                'popular-matches --league epl --days 3',
                '/brief <fixture_id> <query>',
                'today-briefs --sort popularity',
            ],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _extract_text(self, payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        output_text = payload.get('output_text')
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()
        output = payload.get('output')
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get('content')
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    text = block.get('text')
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            if parts:
                return '\n'.join(parts)
        return None


class PortkeySynthesisProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _complete_raw(self, *, system: str, user: str) -> str:
        response = self._client.post(
            '/chat/completions',
            headers={
                'authorization': f'Bearer {self._api_key}',
                'content-type': 'application/json',
            },
            json={
                'model': self._model,
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': user},
                ],
                'temperature': 0.2,
            },
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PortkeySynthesisError(
                f'Portkey synthesis request failed ({response.status_code}).'
            ) from exc
        text = self._extract_text(response.json())
        if not text:
            raise PortkeySynthesisError('Portkey did not return synthesis text.')
        return text

    def synthesize(self, analysis: FixtureAnalysisResult) -> str:
        response = self._client.post(
            '/chat/completions',
            headers={
                'authorization': f'Bearer {self._api_key}',
                'content-type': 'application/json',
            },
            json={
                'model': self._model,
                'messages': [
                    {
                        'role': 'system',
                        'content': (
                            'You are Nutmeg. Write concise football analysis grounded only '
                            'in the provided deterministic evidence. You must mention the '
                            'deterministic verdict and confidence exactly.'
                        ),
                    },
                    {
                        'role': 'user',
                        'content': self._analysis_prompt(analysis),
                    },
                ],
                'temperature': 0.2,
            },
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PortkeySynthesisError(
                f'Portkey synthesis request failed ({response.status_code}).'
            ) from exc
        text = self._extract_text(response.json())
        if not text:
            raise PortkeySynthesisError('Portkey did not return synthesis text.')
        return text

    def _analysis_prompt(self, analysis: FixtureAnalysisResult) -> str:
        payload: dict[str, Any] = {
            'fixture': {
                'fixture_id': analysis.fixture.fixture_id,
                'home_team': analysis.fixture.home_team,
                'away_team': analysis.fixture.away_team,
            },
            'query': analysis.query,
            'verdict': analysis.judgment.verdict,
            'confidence': analysis.judgment.confidence,
            'core_reasons': analysis.judgment.core_reasons,
            'counterargument': analysis.judgment.counterargument,
            'evidence': {
                'tactical': analysis.evidence.tactical_summary,
                'snapshot': analysis.evidence.snapshot_summary,
                'odds': analysis.evidence.odds_summary,
                'market_shape': analysis.evidence.market_shape_summary,
                'caveats': analysis.evidence.caveats,
            },
        }
        return json.dumps(payload, ensure_ascii=True, sort_keys=True)

    def _extract_text(self, payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        choices = payload.get('choices')
        if not isinstance(choices, list) or not choices:
            return None
        first = choices[0]
        if not isinstance(first, dict):
            return None
        message = first.get('message')
        if isinstance(message, dict) and message.get('content'):
            return str(message['content']).strip()
        if first.get('text'):
            return str(first['text']).strip()
        return None


def build_synthesis_provider(settings: AppSettings) -> PortkeySynthesisProvider | None:
    if not settings.agent_synthesis_enabled or not settings.portkey_api_key:
        return None
    return PortkeySynthesisProvider(
        base_url=settings.portkey_base_url,
        api_key=settings.portkey_api_key,
        model=settings.anthropic_model,
    )


def build_bot_fallback_provider(settings: AppSettings) -> OpenAiBotFallbackProvider | None:
    if not settings.bot_llm_fallback_enabled or not settings.openai_api_key:
        return None
    return OpenAiBotFallbackProvider(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        model=settings.bot_llm_fallback_model,
    )
