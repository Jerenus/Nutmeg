from __future__ import annotations

import json
from typing import Any

import httpx

from nutmeg.config.settings import AppSettings


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
                            'You are Nutmeg, a private football betting operations bot. '
                            'Reply in the user language, be concise, and do not invent '
                            'live match facts. If the user asks for plans, explain how '
                            'to use `/jczq`, `/renjiu`, or the local `nutmeg today` / '
                            'decision-web surfaces. If a deterministic Nutmeg command '
                            'failed, explain the failure and give the next actionable '
                            'command.'
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
                '/jczq',
                '/jczq revise <想法>',
                '/renjiu',
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
    """Portkey chat-completions client.

    The v0 match-brief ``synthesize()`` path was retired on 2026-09-23; the
    class stays because ``services.psychology.io.PortkeyLLMCompleter`` reuses
    its configured ``_client`` / ``_api_key`` / ``_model`` / ``_extract_text``.
    """

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
