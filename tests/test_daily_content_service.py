from __future__ import annotations

import json
from pathlib import Path

from nutmeg.domain.daily_content import (
    DailyContentArtifacts,
    DailyContentRun,
    InternalAnalysis,
    MatchContentPack,
    PublicScript,
    SeedanceTaskSpec,
    VideoSegment,
    VideoStoryboard,
)
from nutmeg.services.jczq import SampleJczqCalculatorProvider


def test_daily_content_domain_serializes_nested_match_pack() -> None:
    task = SeedanceTaskSpec(
        task_key="001-vertical-segment-01",
        provider="volcengine-ark",
        model="doubao-seedance-2-0-260128",
        content=[{"type": "text", "text": "原创热血足球动画"}],
        resolution="720p",
        ratio="9:16",
        duration=15,
        seed=101,
        camera_fixed=False,
        watermark=True,
        generate_audio=False,
        safety_identifier="owner-hash",
    )
    pack = MatchContentPack(
        match_id="周一001",
        match_no="周一001",
        competition="意甲",
        home_team="卡利亚里",
        away_team="亚特兰大",
        kickoff_time="2026-04-27 18:30",
        popularity_score=82.0,
        focus_level="focus",
        internal_analysis=InternalAnalysis(
            opening_read="强弱差明确，但客队赛程压力需要防范。",
            football_factors=["主队保级压力", "客队周中消耗"],
            market_factors=["客胜热度高", "让球盘提醒防穿盘风险"],
            key_risks=["临场轮换", "早段进球改变节奏"],
            internal_lean="客队不败，防让球风险",
            confidence="medium",
            responsible_use_note="内部判断不是投注指令。",
        ),
        public_script=PublicScript(
            title_candidates=["这场意甲，看点不只是强弱"],
            hook="这场球的火药味，在于强队能不能压住节奏。",
            body=["先看状态，再看市场预期。"],
            closing="以上只是赛前数据观察，不构成任何投注建议，理性看球。",
            voiceover_text="这场球的火药味，在于强队能不能压住节奏。以上只是赛前数据观察，不构成任何投注建议，理性看球。",
            forbidden_terms_removed=[],
        ),
        storyboard=VideoStoryboard(
            style_profile_id="original-hotblood-tactical-manga-v1",
            ratio_primary="9:16",
            ratio_secondary="16:9",
            segment_count=1,
            segments=[
                VideoSegment(
                    segment_no=1,
                    duration_seconds=15,
                    narration="强队压上，弱队反击。",
                    visual_direction="原创少年球员冲刺，草皮出现火焰速度线。",
                    camera_direction="低机位推镜到战术蓝图。",
                    tactical_overlay="客队压迫箭头，主队反击通道。",
                    subtitle_text="强弱不是唯一变量",
                    seedance_prompt_zh="原创热血足球番，战术数据漫画浮层。",
                )
            ],
        ),
        seedance_specs={"vertical": [task], "horizontal": []},
        compliance={"risk_level": "MEDIUM", "publish_recommendation": "review"},
        evidence={"official_last_update": "2026-04-26 22:37:49"},
        warnings=[],
    )
    run = DailyContentRun(
        run_id="daily-content-20260427-120000",
        run_date="2026-04-27",
        generated_at="2026-04-27T12:00:00+00:00",
        provider="sample",
        scope="popular-all",
        style_profile="original-hotblood-tactical-manga-v1",
        matches=[pack],
        artifacts=DailyContentArtifacts(),
        warnings=[],
    )

    payload = run.to_dict()

    assert payload["matches"][0]["seedance_specs"]["vertical"][0]["ratio"] == "9:16"
    assert payload["matches"][0]["storyboard"]["segments"][0]["duration_seconds"] == 15


def test_daily_content_service_builds_all_sample_matches_and_artifacts(tmp_path) -> None:
    from nutmeg.services.daily_content import DailyContentService

    service = DailyContentService(jczq_provider=SampleJczqCalculatorProvider())

    run = service.build_run(
        run_date="2026-04-26",
        output_dir=tmp_path,
        provider_label="sample",
        render_pdf=True,
    )

    assert run.scope == "popular-all"
    assert len(run.matches) >= 8
    assert all(match.public_script.voiceover_text for match in run.matches)
    assert all(match.storyboard.segment_count in {4, 6} for match in run.matches)
    assert run.artifacts.json_path is not None
    assert run.artifacts.markdown_path is not None
    assert run.artifacts.pdf_path is not None
    assert run.artifacts.seedance_manifest_path is not None
    assert run.artifacts.json_path.endswith(".json")
    assert run.artifacts.markdown_path.endswith(".md")
    assert run.artifacts.pdf_path.endswith(".pdf")
    assert run.artifacts.seedance_manifest_path.endswith("seedance-manifest.json")
    assert Path(run.artifacts.json_path).exists()
    assert Path(run.artifacts.markdown_path).exists()
    assert Path(run.artifacts.pdf_path).read_bytes().startswith(b"%PDF")
    assert Path(run.artifacts.seedance_manifest_path).exists()


def test_daily_content_public_script_removes_betting_action_language(tmp_path) -> None:
    from nutmeg.services.daily_content import DailyContentService

    service = DailyContentService(jczq_provider=SampleJczqCalculatorProvider())

    run = service.build_run(run_date="2026-04-26", output_dir=tmp_path, provider_label="sample")

    forbidden = ["买主胜", "跟我买", "上车", "稳赚", "红单", "私信拿单"]
    for match in run.matches:
        text = match.public_script.voiceover_text
        assert "不构成任何投注建议" in text
        assert not any(term in text for term in forbidden)
        assert match.compliance["risk_level"] in {"LOW", "MEDIUM"}


def test_daily_content_manifest_excludes_blocked_public_scripts(tmp_path) -> None:
    from nutmeg.services.daily_content import DailyContentService

    service = DailyContentService(jczq_provider=SampleJczqCalculatorProvider())
    blocked_text = "买主胜，私信拿单，稳赚。"

    run = service.build_run(
        run_date="2026-04-26",
        output_dir=tmp_path,
        provider_label="sample",
        public_script_override=blocked_text,
    )

    assert run.matches[0].compliance["risk_level"] == "BLOCKED"
    assert run.matches[0].seedance_specs["vertical"] == []


def test_daily_content_service_writes_per_match_artifacts(tmp_path) -> None:
    from nutmeg.services.daily_content import DailyContentService

    service = DailyContentService(jczq_provider=SampleJczqCalculatorProvider())

    run = service.build_run(run_date="2026-04-26", output_dir=tmp_path, provider_label="sample")
    first = run.matches[0]
    assert run.artifacts.run_dir is not None
    match_dir = (
        Path(run.artifacts.run_dir)
        / "matches"
        / first.match_id.replace("/", "-").replace(" ", "_")
    )

    assert (match_dir / "analysis.json").exists()
    assert (match_dir / "public-script.md").read_text(encoding="utf-8").startswith("# ")
    assert (match_dir / "storyboard.md").exists()
    assert (match_dir / "seedance-vertical.json").exists()
    assert (match_dir / "seedance-horizontal.json").exists()
    assert (match_dir / "compliance.json").exists()
    assert (match_dir / "videos").is_dir()

    assert run.artifacts.seedance_manifest_path is not None
    manifest = json.loads(Path(run.artifacts.seedance_manifest_path).read_text(encoding="utf-8"))
    assert manifest["run_dir"] == run.artifacts.run_dir
    assert any(task["ratio_key"] == "vertical" for task in manifest["tasks"])
    assert any(task["ratio_key"] == "horizontal" for task in manifest["tasks"])


def test_daily_content_v31_production_factors_drive_manifest_and_prompts(tmp_path) -> None:
    from nutmeg.services.daily_content import DailyContentService

    service = DailyContentService(jczq_provider=SampleJczqCalculatorProvider())

    run = service.build_run(run_date="2026-04-26", output_dir=tmp_path, provider_label="sample")

    assert run.style_profile == "retro-football-manga-v3.1"
    assert run.artifacts.seedance_manifest_path is not None
    manifest = json.loads(Path(run.artifacts.seedance_manifest_path).read_text(encoding="utf-8"))

    assert "前2秒强钩子" in manifest["production_factors"]["platform_retention"]
    assert "固定栏目包装" in manifest["production_factors"]["series_packaging"]
    assert "精修赛璐璐动画" in manifest["quality_gates"]["visual_craft"]
    assert manifest["platform_outputs"]["douyin"] == "60秒竖屏短视频"
    assert manifest["platform_outputs"]["xiaohongshu"] == "视频封面 + 3-5张战术漫画图文卡"

    first_prompt = manifest["tasks"][0]["content"][0]["text"]
    assert "原创80年代复古少年足球漫画动画" in first_prompt
    assert "前2秒强钩子" in first_prompt
    assert "固定栏目包装" in first_prompt
    assert "精修赛璐璐动画" in first_prompt

    assert run.artifacts.run_dir is not None
    first = run.matches[0]
    match_dir = (
        Path(run.artifacts.run_dir)
        / "matches"
        / first.match_id.replace("/", "-").replace(" ", "_")
    )
    factors = json.loads((match_dir / "production-factors.json").read_text(encoding="utf-8"))
    assert factors["style_profile"] == "retro-football-manga-v3.1"
