from __future__ import annotations

import json
from pathlib import Path

from nutmeg.domain.daily_content import (
    DirectorShot,
    HookCandidate,
    InternalAnalysis,
    MoodShotSpec,
    NarrativeSegment,
    NarrativeTimeline,
    ProductionPacketV2,
    PublicScript,
    QualityGateResult,
    RemotionTimelineSpec,
    TacticalBeat,
)
from nutmeg.services.video_production import VideoProductionService


def test_narrative_timeline_serializes_locked_voice_subtitle_and_visuals() -> None:
    timeline = NarrativeTimeline(
        duration_seconds=60,
        segments=[
            NarrativeSegment(
                segment_id="hook",
                start_seconds=0,
                end_seconds=6,
                scene_type="hook",
                voiceover_text="表面看是主场优势，其实先看压迫。",
                subtitle_text="表面看是主场优势，其实先看压迫。",
                screen_card_text="先看压迫",
                visual_intent="用开场情绪镜头建立隐藏变量。",
                tactical_focus="开局压迫",
                transition_to_next="从隐藏变量进入第一观察点。",
            )
        ],
    )

    payload = timeline.to_dict()

    assert payload["duration_seconds"] == 60
    assert payload["segments"][0]["segment_id"] == "hook"
    assert payload["segments"][0]["subtitle_text"] in payload["segments"][0]["voiceover_text"]
    assert payload["segments"][0]["screen_card_text"] == "先看压迫"


def test_production_packet_v2_serializes_nested_video_plan() -> None:
    narrative_timeline = NarrativeTimeline(
        duration_seconds=60,
        segments=[
            NarrativeSegment(
                segment_id="hook",
                start_seconds=0,
                end_seconds=6,
                scene_type="hook",
                voiceover_text="这场表面看是主场优势，其实真正决定比赛的是压迫会不会断档。",
                subtitle_text="真正决定比赛的是压迫会不会断档。",
                screen_card_text="关键不是主场",
                visual_intent="开场把观众注意力锁到主矛盾。",
                tactical_focus="压迫断档",
                transition_to_next="进入第一变量解释。",
            )
        ],
    )
    packet = ProductionPacketV2(
        match_id="周二004",
        style_profile="cinematic-sports-anime-broadcast-v1",
        hook_candidates=[
            HookCandidate(
                hook_type="counterintuitive",
                text="表面看是主场优势，其实关键是压迫会不会断档。",
                rationale="反常识表达更适合常规热门比赛。",
            )
        ],
        selected_hook="表面看是主场优势，其实关键是压迫会不会断档。",
        main_contradiction="巴黎压迫持续性 vs 拜仁支点回撤后的肋部冲刺。",
        voiceover_script="这场表面看是主场优势，其实真正决定比赛的是压迫会不会断档。",
        tactical_beats=[
            TacticalBeat(
                beat_id="pressing-lock",
                start_seconds=8.0,
                end_seconds=25.0,
                title="锁边压迫",
                explanation="巴黎三人压迫把出球赶到边线。",
                home_shape=["LW", "ST", "RW"],
                away_shape=["CB", "DM", "FB"],
                arrows=[{"from": [42, 38], "to": [70, 18], "kind": "press"}],
            )
        ],
        director_shots=[
            DirectorShot(
                shot_id="hook-01",
                visual_owner="seedance",
                start_seconds=0.0,
                end_seconds=3.0,
                purpose="opening_hook",
                description="低机位足球特写，球场灯光打开。",
            )
        ],
        mood_shots=[
            MoodShotSpec(
                task_key="周二004-mood-01",
                prompt="cinematic football boot and ball closeup, no text",
                duration=4,
                placement_start_seconds=0.0,
                placement_end_seconds=4.0,
                quality_constraints=["no_text", "no_logo", "no_number"],
            )
        ],
        remotion_timeline=RemotionTimelineSpec(
            composition_id="FootballExplainerV2",
            fps=30,
            width=1080,
            height=1920,
            duration_seconds=60.0,
            props_path="matches/周二004/remotion-timeline.json",
            output_path="matches/周二004/videos/final-master.mp4",
        ),
        quality_gates=[
            QualityGateResult(gate="hook", status="pass", detail="3秒内明确主矛盾。")
        ],
        narrative_timeline=narrative_timeline,
    )

    payload = packet.to_dict()

    assert payload["match_id"] == "周二004"
    assert payload["hook_candidates"][0]["hook_type"] == "counterintuitive"
    assert payload["tactical_beats"][0]["arrows"][0]["kind"] == "press"
    assert payload["mood_shots"][0]["quality_constraints"] == [
        "no_text",
        "no_logo",
        "no_number",
    ]
    assert payload["narrative_timeline"]["segments"][0]["screen_card_text"] == "关键不是主场"
    assert payload["remotion_timeline"]["composition_id"] == "FootballExplainerV2"


def test_content_brain_prefers_counterintuitive_hook_for_normal_focus_match() -> None:
    service = VideoProductionService()
    analysis = InternalAnalysis(
        opening_read="巴黎主场面对拜仁，关键在高位压迫是否持续。",
        football_factors=["巴黎前场压迫", "拜仁支点回撤", "肋部冲刺"],
        market_factors=["市场支持巴黎主场优势，但不支持大胜"],
        key_risks=["压迫断档", "早段进球"],
        internal_lean="巴黎主场不败倾向，但需防反击。",
        confidence="medium",
        responsible_use_note="内部判断不是投注指令。",
    )
    public_script = PublicScript(
        title_candidates=["巴黎vs拜仁：关键不是控球"],
        hook="这场看点不是一句强弱能讲完。",
        body=["巴黎压迫和拜仁反击是主矛盾。"],
        closing="以上只是赛前数据观察，不构成任何投注建议，理性看球。",
        voiceover_text="这场看点不是一句强弱能讲完。巴黎压迫和拜仁反击是主矛盾。",
    )

    result = service.build_content_brain(
        match_id="周二004",
        competition="欧冠",
        home_team="巴黎",
        away_team="拜仁",
        focus_level="focus",
        internal_analysis=analysis,
        public_script=public_script,
    )

    assert result.selected_hook.startswith("表面看")
    assert result.hook_candidates[0].hook_type == "counterintuitive"
    assert "压迫" in result.main_contradiction
    assert "拜仁" in result.voiceover_script
    assert "不构成任何投注建议" in result.voiceover_script
    assert "稳赢" not in result.voiceover_script


def test_content_brain_keeps_jleague_case_hook_short_and_specific() -> None:
    service = VideoProductionService()
    analysis = InternalAnalysis(
        opening_read="神户胜利 对 大阪樱花 这场的内容重点，不是简单给结论。",
        football_factors=[
            "神户胜利主场节奏与开局压迫",
            "大阪樱花客场反击和阵容完整度",
            "临场首发会显著影响比赛结构",
        ],
        market_factors=["赔率只作为市场预期观察，不等于比赛答案"],
        key_risks=["临场轮换", "早段进球"],
        internal_lean="内部只做观察。",
        confidence="medium",
        responsible_use_note="内部判断不是投注指令。",
    )
    public_script = PublicScript(
        title_candidates=["神户胜利vs大阪樱花"],
        hook="这场不只看强弱。",
        body=["压迫和反击决定节奏。"],
        closing="以上只是赛前数据观察，不构成任何投注建议，理性看球。",
        voiceover_text="这场不只看强弱。压迫和反击决定节奏。",
    )

    result = service.build_content_brain(
        match_id="周三001",
        competition="日职",
        home_team="神户胜利",
        away_team="大阪樱花",
        focus_level="focus",
        internal_analysis=analysis,
        public_script=public_script,
    )

    assert len(result.selected_hook) <= 44
    assert (
        result.selected_hook
        == "表面看神户胜利有主场，其实先看开局压迫能不能锁住大阪樱花的反击速度。"
    )
    assert result.main_contradiction == "神户胜利的开局压迫，能不能压住大阪樱花的反击速度。"
    assert "阵容完整度、临场首发" not in result.selected_hook
    assert len(result.voiceover_script) <= 260


def test_video_production_service_writes_v2_artifacts(tmp_path) -> None:
    service = VideoProductionService()
    packet = service.build_production_packet(
        match_id="周二004",
        match_no="周二004",
        competition="欧冠",
        home_team="巴黎",
        away_team="拜仁",
        focus_level="focus",
        internal_analysis=InternalAnalysis(
            opening_read="巴黎高位压迫对拜仁纵向反击。",
            football_factors=["高位压迫", "支点回撤", "肋部冲刺"],
            market_factors=["主场优势存在但不支持大胜"],
            key_risks=["压迫断档", "首发变化"],
            internal_lean="观察巴黎压迫持续性。",
            confidence="medium",
            responsible_use_note="内部判断不是投注指令。",
        ),
        public_script=PublicScript(
            title_candidates=["巴黎vs拜仁：真正变量"],
            hook="这场不只看强弱。",
            body=["压迫和反击决定节奏。"],
            closing="以上只是赛前数据观察，不构成任何投注建议，理性看球。",
            voiceover_text="这场不只看强弱。压迫和反击决定节奏。",
        ),
        run_dir=tmp_path,
    )
    paths = service.write_production_artifacts(packet, match_dir=tmp_path / "matches" / "周二004")

    assert Path(paths["content_brief_path"]).exists()
    assert Path(paths["director_shotlist_path"]).exists()
    assert Path(paths["remotion_timeline_path"]).exists()
    assert Path(paths["seedance_mood_manifest_path"]).exists()
    timeline = json.loads(Path(paths["remotion_timeline_path"]).read_text(encoding="utf-8"))
    assert timeline["compositionId"] == "FootballExplainerV2"
    assert timeline["durationSeconds"] == 60
    assert len(timeline["tacticalBeats"]) == 2
    assert len(timeline["narrativeSegments"]) == 6
    assert timeline["voiceoverScript"] == "".join(
        segment["voiceover_text"] for segment in timeline["narrativeSegments"]
    )
    assert timeline["narrativeSegments"][0]["scene_type"] == "hook"
    assert timeline["narrativeSegments"][0]["subtitle_text"] in timeline["voiceoverScript"]
    narrative_path = Path(paths["narrative_timeline_path"])
    assert narrative_path.exists()
    narrative = json.loads(narrative_path.read_text(encoding="utf-8"))
    assert narrative["segments"][3]["scene_type"] == "counter"
    mood = json.loads(Path(paths["seedance_mood_manifest_path"]).read_text(encoding="utf-8"))
    assert len(mood["tasks"]) == 3
    assert all("no readable text" in task["content"][0]["text"].lower() for task in mood["tasks"])


def test_quality_report_flags_text_artifacts_and_audio_gaps() -> None:
    service = VideoProductionService()

    report = service.build_quality_report(
        seedance_findings=[
            {"task_key": "mood-01", "issue": "text_artifact", "detail": "fake jersey text"},
        ],
        audio_findings=[
            {"issue": "long_silence", "start": 10.0, "duration": 2.0},
        ],
        content_findings=[],
    )

    assert report["status"] == "review"
    assert report["counts"]["issues"] == 2
    assert any(item["gate"] == "seedance_clean_plate" for item in report["gates"])
    assert any(item["gate"] == "continuous_voiceover" for item in report["gates"])
