import json

import httpx

from nutmeg.agents.responder_provider import (
    RESPONDER_SYSTEM_PROMPT,
    PortkeyResponderProvider,
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


def test_build_returns_none_without_api_key():
    assert build_responder_provider(AppSettings(portkey_api_key=None)) is None


def test_system_prompt_forbids_new_judgment():
    assert "不得给出任何新的面集建议" in RESPONDER_SYSTEM_PROMPT
