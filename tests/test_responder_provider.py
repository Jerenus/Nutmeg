import json

import httpx

from nutmeg.agents.responder_provider import (
    RESPONDER_SYSTEM_PROMPT,
    ClaudeCliResponderProvider,
    PortkeyResponderProvider,
    ResponderUnavailableError,
    build_responder_provider,
)
from nutmeg.config.settings import AppSettings


def test_portkey_provider_posts_context_and_returns_text():
    seen = {}

    def handler(req: httpx.Request):
        seen["body"] = json.loads(req.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "解释：…"}}]}
        )

    client = httpx.Client(
        base_url="https://pk.test/v1", transport=httpx.MockTransport(handler)
    )
    p = PortkeyResponderProvider(
        base_url="https://pk.test/v1", api_key="k", model="m", client=client
    )
    out = p.answer({"match": "摩纳哥 vs 朗斯"}, "朗斯不败？")
    assert out == "解释：…"
    assert seen["body"]["messages"][0] == {
        "role": "system",
        "content": RESPONDER_SYSTEM_PROMPT,
    }
    assert "朗斯不败？" in seen["body"]["messages"][1]["content"]
    assert seen["body"]["temperature"] == 0


def test_build_returns_none_without_api_key(monkeypatch):
    """⚠️行为已变更（2026-09-18）：有本机 claude CLI 时走订阅，不再要求 key。
    「两者都没有才是 None」由 test_build_returns_none_when_neither_is_available 守。"""
    import nutmeg.agents.responder_provider as mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    assert build_responder_provider(AppSettings(portkey_api_key=None)) is None


def test_system_prompt_forbids_new_judgment():
    assert "不得给出任何新的面集建议" in RESPONDER_SYSTEM_PROMPT


# ── 订阅路径（本机 claude CLI）─────────────────────────────────────────
def test_cli_provider_builds_a_toolless_single_turn_call_and_feeds_context_on_stdin():
    seen = {}

    def fake_run(argv, stdin_text, timeout):
        seen["argv"], seen["stdin"] = argv, stdin_text
        return 0, "平局是研究点名最被支持的面。（依据：hole_location）", ""

    p = ClaudeCliResponderProvider(runner=fake_run)
    out = p.answer({"judgment": {"match": "摩纳哥 vs 朗斯"}}, "平局的载体在不在？")

    assert out == "平局是研究点名最被支持的面。（依据：hole_location）"
    assert seen["argv"][0] == "claude" and "-p" in seen["argv"]
    # 禁工具、单轮：应答器只许说话，不许在仓里翻东西
    assert "--allowedTools" in seen["argv"] and "--max-turns" in seen["argv"]
    assert seen["argv"][seen["argv"].index("--max-turns") + 1] == "1"
    # 宪法约束随 system prompt 下去
    assert RESPONDER_SYSTEM_PROMPT in seen["argv"]
    # 不传 --model＝继承用户 Claude Code 当前默认模型（不写死、不会过期）
    assert "--model" not in seen["argv"]
    # 上下文走 stdin，不塞 argv（深研 JSON 会超 ARG_MAX）
    assert "平局的载体在不在？" in seen["stdin"]
    assert "摩纳哥 vs 朗斯" in seen["stdin"]


def test_cli_provider_passes_model_only_when_configured():
    def fake_run(argv, stdin_text, timeout):
        return 0, "ok", ""

    p = ClaudeCliResponderProvider(model="claude-opus-5", runner=fake_run)
    seen = []
    p._runner = lambda argv, s, t: (seen.append(argv), (0, "ok", ""))[1]
    p.answer({}, "?")
    assert "--model" in seen[0] and seen[0][seen[0].index("--model") + 1] == "claude-opus-5"


def test_cli_provider_raises_when_the_cli_fails():
    def fake_run(argv, stdin_text, timeout):
        return 1, "", "Credit balance too low"

    p = ClaudeCliResponderProvider(runner=fake_run)
    try:
        p.answer({}, "?")
    except ResponderUnavailableError as exc:
        assert "Credit balance too low" in str(exc)
    else:
        raise AssertionError("应答器不可用时必须抛 ResponderUnavailableError")


def test_build_prefers_the_subscription_cli_over_portkey(monkeypatch):
    import nutmeg.agents.responder_provider as mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/local/bin/claude")
    got = build_responder_provider(AppSettings(portkey_api_key="k"))
    assert isinstance(got, ClaudeCliResponderProvider)


def test_build_falls_back_to_portkey_when_no_cli_but_a_key(monkeypatch):
    import nutmeg.agents.responder_provider as mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    got = build_responder_provider(AppSettings(portkey_api_key="k"))
    assert isinstance(got, PortkeyResponderProvider)


def test_build_returns_none_when_neither_is_available(monkeypatch):
    import nutmeg.agents.responder_provider as mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    assert build_responder_provider(AppSettings(portkey_api_key=None)) is None
