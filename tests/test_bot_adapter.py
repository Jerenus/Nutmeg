from __future__ import annotations

import pytest

from nutmeg.interfaces.bot.adapter import (
    RETIRED_BRIEF_TEXT,
    BotAdapter,
    UnsupportedBotCommandError,
    parse_bot_message,
)


def test_parse_bot_message_supports_brief_command() -> None:
    command = parse_bot_message("/brief epl-001 Should I back Arsenal?")

    assert command.name == "brief"
    assert command.fixture_id == "epl-001"
    assert command.query == "Should I back Arsenal?"
    assert command.raw_text == "/brief epl-001 Should I back Arsenal?"


def test_parse_bot_message_supports_jczq_daily_commands() -> None:
    today = parse_bot_message("/jczq")
    final = parse_bot_message("/jczq final")
    revise = parse_bot_message("/jczq revise 规避大众盘口")

    assert today.name == "jczq"
    assert today.query == "today"
    assert final.name == "jczq"
    assert final.query == "final"
    assert revise.name == "jczq"
    assert revise.query == "revise"
    assert revise.instruction == "规避大众盘口"


def test_parse_bot_message_rejects_unsupported_or_incomplete_messages() -> None:
    with pytest.raises(UnsupportedBotCommandError, match="Unsupported bot command"):
        parse_bot_message("/odds epl-001")
    with pytest.raises(UnsupportedBotCommandError, match="requires a fixture id and query"):
        parse_bot_message("/brief epl-001")


def test_bot_adapter_answers_brief_with_retired_notice() -> None:
    response = BotAdapter().handle_message("/brief epl-001 Should I back Arsenal?")

    assert response.status == "succeeded"
    assert response.text == RETIRED_BRIEF_TEXT
    assert "已退役" in response.text
    assert response.payload["mode"] == "retired"
    assert response.payload["fixture_id"] == "epl-001"
    assert response.payload["sections"] == {}
    assert response.error is None


def test_bot_adapter_brief_does_not_invoke_fallback_provider() -> None:
    class StubFallback:
        def respond(self, message: str, *, error: str | None = None) -> str:  # pragma: no cover
            raise AssertionError("fallback should not run for a retired /brief")

    response = BotAdapter(fallback_provider=StubFallback()).handle_message(
        "/brief epl-001 Should I back Arsenal?"
    )

    assert response.payload["mode"] == "retired"


def test_bot_adapter_returns_failure_for_unsupported_without_fallback() -> None:
    response = BotAdapter().handle_message("/odds epl-001")

    assert response.status == "failed"
    assert response.error is not None
    assert "Unsupported bot command" in response.text
    assert response.payload["sections"] == {}


def test_bot_adapter_uses_fallback_for_unsupported_natural_language() -> None:
    class StubFallback:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def respond(self, message: str, *, error: str | None = None) -> str:
            self.calls.append((message, error))
            return "今晚优先看热门比赛列表，然后用 /renjiu 拿方案。"

    fallback = StubFallback()
    response = BotAdapter(fallback_provider=fallback).handle_message("今天有哪些热门比赛？")

    assert response.status == "succeeded"
    assert "热门比赛列表" in response.text
    assert response.payload["mode"] == "llm_fallback"
    assert fallback.calls == [
        (
            "今天有哪些热门比赛？",
            "Unsupported bot command. Try `/brief <fixture_id> <query>`.",
        )
    ]


def test_bot_adapter_start_returns_deterministic_help_without_fallback() -> None:
    response = BotAdapter().handle_message("/start")

    assert response.status == "succeeded"
    assert "/jczq" in response.text
    assert "/renjiu" in response.text
    assert "telegram-bot-run" in response.text
    assert "popular-matches" not in response.text
    assert response.payload["mode"] == "help"


def test_bot_adapter_reports_unconfigured_jczq_workflow() -> None:
    response = BotAdapter().handle_message("/jczq")

    assert response.status == "failed"
    assert response.payload["mode"] == "jczq_daily"
    assert "not configured" in response.text


def test_bot_adapter_routes_jczq_daily_revision_to_workflow() -> None:
    class StubJczqWorkflow:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def run(self, *, action: str, instruction: str | None = None):
            self.calls.append((action, instruction))
            return {
                "status": "succeeded",
                "text": f"竞彩足球已按要求重算：{instruction}",
                "payload": {"action": action, "instruction": instruction},
            }

    workflow = StubJczqWorkflow()
    response = BotAdapter(jczq_workflow=workflow).handle_message("/jczq revise 规避大众盘口")

    assert response.status == "succeeded"
    assert "规避大众盘口" in response.text
    assert response.payload["mode"] == "jczq_daily"
    assert workflow.calls == [("revise", "规避大众盘口")]


def test_bot_adapter_routes_jczq_natural_language_revision_to_workflow() -> None:
    class StubJczqWorkflow:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def run(self, *, action: str, instruction: str | None = None):
            self.calls.append((action, instruction))
            return {
                "status": "succeeded",
                "text": "已重算高赔率灵感票。",
                "payload": {"action": action, "instruction": instruction},
            }

    workflow = StubJczqWorkflow()
    response = BotAdapter(jczq_workflow=workflow).handle_message(
        "今天竞彩不要比分，提高到100倍，规避大众盘口"
    )

    assert response.status == "succeeded"
    assert response.payload["mode"] == "jczq_daily"
    assert workflow.calls == [("revise", "今天竞彩不要比分，提高到100倍，规避大众盘口")]


def test_bot_adapter_routes_jczq_natural_language_final_to_workflow() -> None:
    class StubJczqWorkflow:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None]] = []

        def run(self, *, action: str, instruction: str | None = None):
            self.calls.append((action, instruction))
            return {
                "status": "succeeded",
                "text": "今日最终方案已读取。",
                "payload": {"action": action},
            }

    workflow = StubJczqWorkflow()
    response = BotAdapter(jczq_workflow=workflow).handle_message("把今天竞彩足球最终方案发我")

    assert response.status == "succeeded"
    assert workflow.calls == [("final", None)]
