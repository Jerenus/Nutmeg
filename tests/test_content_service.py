from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

SAMPLE_REPORT = Path("nutmeg/content/samples/26068-content-report.json")


class FakeLlmProvider:
    provider_label = "fake:gpt"

    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.text


def test_compliance_checker_classifies_prd_risk_levels() -> None:
    from nutmeg.services.content import ContentComplianceChecker

    checker = ContentComplianceChecker()
    safe = checker.assess(
        titles=["赛前观察：这场比赛的变量在中场"],
        short_video_script="这场值得看的是节奏和中场对抗。以上只是赛前数据观察，不构成任何投注建议，理性看球。",
        long_article="本文讨论公开数据、赛程和阵容变量。本文仅基于公开信息进行足球赛事数据分析和规则科普，不构成任何投注建议，也不引导任何形式的下注。比赛结果具有不确定性，请理性看待。",
    )
    medium = checker.assess(
        titles=["市场预期对主队更积极，但风险不能忽略"],
        short_video_script="从赛前数据看，市场预期对主队更积极，但这不等于结果确定。以上只是赛前数据观察，不构成任何投注建议，理性看球。",
        long_article="赔率和盘口变化显示主队关注度更高，同时客队反击仍是变量。本文仅基于公开信息进行足球赛事数据分析和规则科普，不构成任何投注建议，也不引导任何形式的下注。比赛结果具有不确定性，请理性看待。",
    )
    high = checker.assess(
        titles=["这场确定性很强"],
        short_video_script="这场稳了，确定性很强。以上只是赛前数据观察，不构成任何投注建议，理性看球。",
        long_article="这场稳了，确定性很强。本文仅基于公开信息进行足球赛事数据分析和规则科普，不构成任何投注建议，也不引导任何形式的下注。比赛结果具有不确定性，请理性看待。",
    )
    blocked = checker.assess(
        titles=["今晚买主胜"],
        short_video_script="买主胜，私信拿单。以上只是赛前数据观察，不构成任何投注建议，理性看球。",
        long_article="买主胜，私信拿单。本文仅基于公开信息进行足球赛事数据分析和规则科普，不构成任何投注建议，也不引导任何形式的下注。比赛结果具有不确定性，请理性看待。",
    )

    assert safe.risk_level == "LOW"
    assert safe.publish_recommendation == "publish"
    assert medium.risk_level == "MEDIUM"
    assert medium.publish_recommendation == "review"
    assert high.risk_level == "HIGH"
    assert high.publish_recommendation == "skip"
    assert blocked.risk_level == "BLOCKED"
    assert blocked.publish_recommendation == "skip"


def test_content_service_scores_zucai_report_candidates() -> None:
    from nutmeg.services.content import ContentPublisherService

    service = ContentPublisherService(llm_provider=FakeLlmProvider("{}"))

    candidates = service.select_candidates_from_report(SAMPLE_REPORT, limit=3)

    assert len(candidates) == 3
    assert candidates == sorted(
        candidates,
        key=lambda item: item.final_content_priority,
        reverse=True,
    )
    assert all(candidate.match_id.startswith("zucai:26068:") for candidate in candidates)
    assert all(0 <= candidate.attention_score <= 100 for candidate in candidates)
    assert all(0 <= candidate.content_score <= 100 for candidate in candidates)
    assert all(0 <= candidate.model_stability_score <= 100 for candidate in candidates)
    assert all(0 <= candidate.compliance_score <= 100 for candidate in candidates)
    assert all(candidate.selection_reason for candidate in candidates)


def test_content_service_generates_structured_pack_and_enforces_disclaimers() -> None:
    from nutmeg.services.content import (
        LONG_FORM_DISCLAIMER,
        SHORT_VIDEO_DISCLAIMER,
        ContentPublisherService,
    )

    fake = FakeLlmProvider(
        json.dumps(
            {
                "titles": ["焦点战的关键变量", "中场对抗值得看"],
                "short_video_script": "这场比赛值得关注的是节奏变化和阵容完整度。",
                "long_article": "一、为什么值得关注\\n这场的核心不是结论，而是双方状态差异。",
                "key_observation_points": ["主队压迫效率", "客队反击速度"],
                "uncertainty_factors": ["临场阵容", "杯赛节奏"],
            },
            ensure_ascii=False,
        )
    )
    service = ContentPublisherService(llm_provider=fake)

    batch = service.generate_from_report(report_file=SAMPLE_REPORT, limit=1, output_dir=None)
    pack = batch.packs[0]

    assert len(pack.titles) == 5
    assert SHORT_VIDEO_DISCLAIMER in pack.short_video_script
    assert LONG_FORM_DISCLAIMER in pack.long_article
    assert pack.key_observation_points
    assert pack.uncertainty_factors
    assert pack.llm_status == "generated"
    assert fake.prompts and "不要输出下注指令" in fake.prompts[0]


def test_content_service_uses_safe_fallback_when_llm_output_is_invalid() -> None:
    from nutmeg.services.content import ContentPublisherService

    service = ContentPublisherService(llm_provider=FakeLlmProvider("not-json"))

    batch = service.generate_from_report(report_file=SAMPLE_REPORT, limit=1, output_dir=None)
    pack = batch.packs[0]

    assert pack.llm_status == "fallback"
    assert len(pack.titles) == 5
    assert any("LLM output invalid" in warning for warning in pack.warnings)
    assert pack.publish_recommendation in {"publish", "review", "skip"}


def test_openclaw_content_provider_extracts_model_output() -> None:
    from nutmeg.services.content import OpenClawContentLlmProvider

    calls: list[list[str]] = []

    def runner(cmd, *, capture_output, text, timeout, check):
        calls.append(cmd)
        assert capture_output is True
        assert text is True
        assert timeout == 42
        assert check is False
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "outputs": [{"text": "{\"titles\": [\"A\"]}"}],
                    "provider": "nyu-openai-chat",
                    "model": "gpt-5.5",
                }
            ),
            stderr="",
        )

    provider = OpenClawContentLlmProvider(
        model="nyu-openai-chat/gpt-5.5",
        timeout_seconds=42,
        command="openclaw",
        runner=runner,
    )

    text = provider.generate("prompt")

    assert text == '{"titles": ["A"]}'
    assert calls[0][:5] == ["openclaw", "infer", "model", "run", "--json"]
    assert "--prompt" in calls[0]


def test_openclaw_content_provider_reports_attempted_cli_path() -> None:
    from nutmeg.services.content import ContentLlmError, OpenClawContentLlmProvider

    def runner(cmd, *, capture_output, text, timeout, check):
        raise FileNotFoundError(cmd[0])

    provider = OpenClawContentLlmProvider(
        model="nyu-openai-chat/gpt-5.5",
        command="/missing/openclaw",
        runner=runner,
    )

    with pytest.raises(ContentLlmError, match="/missing/openclaw"):
        provider.generate("prompt")


def test_openclaw_content_provider_prefers_modern_cli_path(tmp_path, monkeypatch) -> None:
    from nutmeg.services.content import default_openclaw_command

    fake_home = tmp_path / "home"
    modern = fake_home / ".nvm" / "versions" / "node" / "v22.22.1" / "bin" / "openclaw"
    modern.parent.mkdir(parents=True)
    modern.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("NUTMEG_OPENCLAW_CLI", raising=False)
    monkeypatch.delenv("OPENCLAW_CLI", raising=False)

    assert default_openclaw_command() == str(modern)


def test_openclaw_content_provider_ignores_boolean_openclaw_cli_env(tmp_path, monkeypatch) -> None:
    from nutmeg.services.content import default_openclaw_command

    fake_home = tmp_path / "home"
    modern = fake_home / ".nvm" / "versions" / "node" / "v22.22.1" / "bin" / "openclaw"
    modern.parent.mkdir(parents=True)
    modern.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("NUTMEG_OPENCLAW_CLI", raising=False)
    monkeypatch.setenv("OPENCLAW_CLI", "1")

    assert default_openclaw_command() == str(modern)


def test_content_service_writes_json_and_markdown_artifacts(tmp_path) -> None:
    from nutmeg.services.content import ContentPublisherService

    fake = FakeLlmProvider(
        json.dumps(
            {
                "titles": ["赛前观察：强强对话看两个变量"] * 5,
                "short_video_script": "这场看点在中场和边路。",
                "long_article": "这是一篇赛前观察长文。",
                "key_observation_points": ["中场压迫", "边路效率"],
                "uncertainty_factors": ["临场伤停"],
            },
            ensure_ascii=False,
        )
    )
    service = ContentPublisherService(llm_provider=fake)

    batch = service.generate_from_report(
        report_file=SAMPLE_REPORT,
        limit=1,
        output_dir=tmp_path,
    )

    assert batch.artifacts.json_path is not None
    assert batch.artifacts.markdown_path is not None
    saved = json.loads(Path(batch.artifacts.json_path).read_text(encoding="utf-8"))
    markdown = Path(batch.artifacts.markdown_path).read_text(encoding="utf-8")
    assert saved["packs"][0]["match_id"] == batch.packs[0].match_id
    assert "## 抖音 60 秒口播稿" in markdown
    assert "## 合规风险检查清单" in markdown


def test_content_service_rejects_invalid_report_path(tmp_path) -> None:
    from nutmeg.services.content import ContentPublisherService, ContentValidationError

    service = ContentPublisherService(llm_provider=FakeLlmProvider("{}"))

    with pytest.raises(ContentValidationError, match="report file not found"):
        service.generate_from_report(report_file=tmp_path / "missing.json", limit=1)
