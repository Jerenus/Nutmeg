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
    instruction: str | None = None


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
            "Unsupported bot command. Try `/brief <fixture_id> <query>`."
        )

    command_name = parts[0].removeprefix("/").casefold()
    if command_name == "jczq":
        if len(parts) == 1:
            return BotCommand(
                name="jczq",
                fixture_id="",
                query="today",
                raw_text=raw_text,
            )
        subcommand = parts[1].strip().casefold()
        if subcommand == "final":
            return BotCommand(
                name="jczq",
                fixture_id="",
                query="final",
                raw_text=raw_text,
            )
        if subcommand == "revise" and len(parts) >= 3 and parts[2].strip():
            return BotCommand(
                name="jczq",
                fixture_id="",
                query="revise",
                raw_text=raw_text,
                instruction=parts[2].strip(),
            )
        raise UnsupportedBotCommandError(
            "`/jczq` supports `/jczq`, `/jczq final`, or `/jczq revise <想法>`."
        )

    if command_name != "brief":
        raise UnsupportedBotCommandError(
            "Unsupported bot command. Try `/brief <fixture_id> <query>`."
        )
    if len(parts) < 3 or not parts[1].strip() or not parts[2].strip():
        raise UnsupportedBotCommandError("`/brief` requires a fixture id and query.")

    return BotCommand(
        name="brief",
        fixture_id=parts[1].strip(),
        query=parts[2].strip(),
        raw_text=raw_text,
    )


class BotAdapter:
    def __init__(
        self,
        *,
        workflow,
        payload_builder=None,
        fallback_provider=None,
        jczq_workflow=None,
    ) -> None:
        self._workflow = workflow
        self._payload_builder = payload_builder or _default_payload_builder
        self._fallback_provider = fallback_provider
        self._jczq_workflow = jczq_workflow

    def handle_message(self, text: str) -> BotResponse:
        if _is_help_message(text):
            return BotResponse(
                status="succeeded",
                text=_help_text(),
                payload={"status": "succeeded", "mode": "help", "sections": {}},
            )

        try:
            command = parse_bot_message(text)
        except UnsupportedBotCommandError as exc:
            jczq_command = _parse_jczq_natural_language(text)
            if jczq_command is not None:
                return self._handle_jczq(jczq_command)
            if self._fallback_provider is not None:
                return self._fallback_response(text, error=str(exc))
            return BotResponse(
                status="failed",
                text=str(exc),
                payload={"status": "failed", "error": str(exc), "sections": {}},
                error=str(exc),
            )

        if command.name == "jczq":
            return self._handle_jczq(command)

        result = self._workflow.run(fixture_id=command.fixture_id, query=command.query)
        payload = self._payload_builder(result)
        if result.status == "failed":
            error = str(payload.get("error") or result.error or "Bot command failed.")
            if self._fallback_provider is not None:
                return self._fallback_response(command.raw_text, error=error)
            return BotResponse(status="failed", text=error, payload=payload, error=error)
        return BotResponse(status="succeeded", text=self._render_brief(payload), payload=payload)

    def _handle_jczq(self, command: BotCommand) -> BotResponse:
        if self._jczq_workflow is None:
            error = "JCZQ daily advisor is not configured for this bot."
            return BotResponse(
                status="failed",
                text=error,
                payload={"status": "failed", "mode": "jczq_daily", "error": error},
                error=error,
            )
        result = self._jczq_workflow.run(
            action=command.query,
            instruction=command.instruction,
        )
        status = str(result.get("status") or "succeeded")
        payload = dict(result.get("payload") or {})
        payload.setdefault("mode", "jczq_daily")
        text = str(result.get("text") or "")
        error = str(result.get("error") or "") or None
        return BotResponse(status=status, text=text, payload=payload, error=error)

    def _fallback_response(self, message: str, *, error: str) -> BotResponse:
        try:
            text = self._fallback_provider.respond(message, error=error)
        except Exception as exc:
            fallback_error = f"{error}\n\nLLM fallback is configured but failed: {exc}"
            return BotResponse(
                status="failed",
                text=fallback_error,
                payload={
                    "status": "failed",
                    "mode": "llm_fallback",
                    "error": error,
                    "fallback_error": str(exc),
                    "sections": {},
                },
                error=fallback_error,
            )
        return BotResponse(
            status="succeeded",
            text=text,
            payload={
                "status": "succeeded",
                "mode": "llm_fallback",
                "source_error": error,
                "sections": {},
            },
        )

    def _render_brief(self, payload: dict[str, Any]) -> str:
        fixture = payload.get("fixture") or {}
        judgment = payload.get("judgment") or {}
        sections = payload.get("sections") or {}
        agent = payload.get("agent") or {}
        lines = [
            f"Match Brief: {fixture.get('home_team')} vs {fixture.get('away_team')}",
            f"Verdict: {judgment.get('verdict')}",
            f"Confidence: {judgment.get('confidence')}",
        ]
        self._extend_section(lines, "Core reasons", sections.get("core_reasons") or [])
        self._extend_section(lines, "Tactical evidence", sections.get("tactical_evidence") or [])
        self._extend_section(lines, "Market evidence", sections.get("market_evidence") or [])
        self._extend_section(lines, "Caveats", sections.get("caveats") or [])
        if payload.get("generated_synthesis"):
            lines.extend(["Generated synthesis:", str(payload["generated_synthesis"])])
        nodes = agent.get("nodes") or []
        if nodes:
            lines.append(f"Agent nodes: {' -> '.join(nodes)}")
        return "\n".join(lines)

    def _extend_section(self, lines: list[str], title: str, items: list[str]) -> None:
        if not items:
            return
        lines.append(f"{title}:")
        lines.extend(f"- {item}" for item in items)


def _default_payload_builder(result) -> dict[str, Any]:
    from nutmeg.interfaces.cli import build_match_brief_payload

    return build_match_brief_payload(result)


def _is_help_message(text: str) -> bool:
    normalized = text.strip().casefold()
    return normalized in {"/start", "start", "/help", "help"}


def _parse_jczq_natural_language(text: str) -> BotCommand | None:
    raw_text = text.strip()
    normalized = raw_text.casefold()
    if not _looks_like_jczq_message(normalized):
        return None
    if any(word in normalized for word in ["最终", "final", "发我", "发送"]):
        return BotCommand(
            name="jczq",
            fixture_id="",
            query="final",
            raw_text=raw_text,
        )
    if any(word in normalized for word in ["状态", "status", "生成了吗", "有没有生成"]):
        return BotCommand(
            name="jczq",
            fixture_id="",
            query="status",
            raw_text=raw_text,
        )
    if any(
        word in normalized
        for word in [
            "修正",
            "重算",
            "不要",
            "规避",
            "保留",
            "剔除",
            "提高",
            "降低",
            "激进",
            "稳",
            "高赔",
            "灵感",
            "比分",
            "总进球",
            "半全场",
            "让球",
            "盘口",
        ]
    ):
        return BotCommand(
            name="jczq",
            fixture_id="",
            query="revise",
            raw_text=raw_text,
            instruction=raw_text,
        )
    return BotCommand(
        name="jczq",
        fixture_id="",
        query="today",
        raw_text=raw_text,
    )


def _looks_like_jczq_message(normalized: str) -> bool:
    return any(
        keyword in normalized
        for keyword in [
            "jczq",
            "竞彩",
            "竞彩足球",
            "混合过关",
            "高赔率灵感票",
        ]
    )


def _help_text() -> str:
    return "\n".join(
        [
            "Nutmeg bot is online.",
            "Use `/brief <fixture_id> <query>` for a match brief.",
            "Use `/jczq` for today’s dynamic竞彩足球 plan, `/jczq revise <想法>` to recalc.",
            "Find candidates locally with `popular-matches --league epl --days 3`.",
            "For ranked daily candidates use `today-briefs --sort popularity`.",
            "This bot replies only when `telegram-bot-run` is running locally.",
        ]
    )
