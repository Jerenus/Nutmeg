from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from nutmeg.services.content import SHORT_VIDEO_DISCLAIMER

STYLE_PROFILE_V2 = "cinematic-sports-anime-broadcast-v1"
FORBIDDEN_PUBLIC_TERMS = ["稳赢", "必红", "红单", "上车", "跟我买", "私信拿单", "比分锁定"]


@dataclass(slots=True, frozen=True)
class ContentBrainResult:
    hook_candidates: list[HookCandidate]
    selected_hook: str
    main_contradiction: str
    voiceover_script: str

    def to_dict(self) -> dict[str, object]:
        return {
            "hook_candidates": [hook.to_dict() for hook in self.hook_candidates],
            "selected_hook": self.selected_hook,
            "main_contradiction": self.main_contradiction,
            "voiceover_script": self.voiceover_script,
        }


class VideoProductionService:
    def build_content_brain(
        self,
        *,
        match_id: str,
        competition: str,
        home_team: str,
        away_team: str,
        focus_level: str,
        internal_analysis: InternalAnalysis,
        public_script: PublicScript,
    ) -> ContentBrainResult:
        main_contradiction = _main_contradiction(home_team, away_team, internal_analysis)
        hook_candidates = _hook_candidates(home_team, away_team, main_contradiction, focus_level)
        selected_hook = hook_candidates[0].text
        voiceover_script = _voiceover_script(
            competition=competition,
            home_team=home_team,
            away_team=away_team,
            selected_hook=selected_hook,
            main_contradiction=main_contradiction,
            internal_analysis=internal_analysis,
            public_script=public_script,
        )
        return ContentBrainResult(
            hook_candidates=hook_candidates,
            selected_hook=selected_hook,
            main_contradiction=main_contradiction,
            voiceover_script=_sanitize_public_script(voiceover_script),
        )

    def build_production_packet(
        self,
        *,
        match_id: str,
        match_no: str,
        competition: str,
        home_team: str,
        away_team: str,
        focus_level: str,
        internal_analysis: InternalAnalysis,
        public_script: PublicScript,
        run_dir: Path,
    ) -> ProductionPacketV2:
        brain = self.build_content_brain(
            match_id=match_id,
            competition=competition,
            home_team=home_team,
            away_team=away_team,
            focus_level=focus_level,
            internal_analysis=internal_analysis,
            public_script=public_script,
        )
        tactical_beats = _tactical_beats(internal_analysis)
        narrative_timeline = _narrative_timeline(
            competition=competition,
            home_team=home_team,
            away_team=away_team,
            selected_hook=brain.selected_hook,
            internal_analysis=internal_analysis,
        )
        director_shots = _director_shots()
        mood_shots = _mood_shots(match_no=match_no, home_team=home_team, away_team=away_team)
        timeline = RemotionTimelineSpec(
            composition_id="FootballExplainerV2",
            fps=30,
            width=1080,
            height=1920,
            duration_seconds=60,
            props_path=str(run_dir / "matches" / match_id / "remotion-timeline.json"),
            output_path=str(run_dir / "matches" / match_id / "videos" / "final-master.mp4"),
        )
        return ProductionPacketV2(
            match_id=match_id,
            style_profile=STYLE_PROFILE_V2,
            hook_candidates=brain.hook_candidates,
            selected_hook=brain.selected_hook,
            main_contradiction=brain.main_contradiction,
            voiceover_script=_sanitize_public_script(narrative_timeline.voiceover_text()),
            tactical_beats=tactical_beats,
            director_shots=director_shots,
            mood_shots=mood_shots,
            narrative_timeline=narrative_timeline,
            remotion_timeline=timeline,
            quality_gates=[
                QualityGateResult("content", "review", "Packet created for editorial review.")
            ],
        )

    def write_production_artifacts(
        self, packet: ProductionPacketV2, *, match_dir: Path
    ) -> dict[str, str]:
        match_dir.mkdir(parents=True, exist_ok=True)
        (match_dir / "videos").mkdir(exist_ok=True)
        paths = {
            "content_brief_path": match_dir / "content-brief.json",
            "hooks_path": match_dir / "hooks.json",
            "voiceover_script_path": match_dir / "voiceover-script.md",
            "director_shotlist_path": match_dir / "director-shotlist.json",
            "seedance_mood_manifest_path": match_dir / "seedance-mood-manifest.json",
            "remotion_timeline_path": match_dir / "remotion-timeline.json",
            "narrative_timeline_path": match_dir / "narrative-timeline.json",
            "quality_report_path": match_dir / "quality-report.json",
        }
        _write_json(paths["content_brief_path"], packet.to_dict())
        _write_json(paths["hooks_path"], [hook.to_dict() for hook in packet.hook_candidates])
        paths["voiceover_script_path"].write_text(packet.voiceover_script + "\n", encoding="utf-8")
        _write_json(
            paths["director_shotlist_path"],
            [shot.to_dict() for shot in packet.director_shots],
        )
        _write_json(paths["seedance_mood_manifest_path"], _seedance_mood_manifest(packet))
        _write_json(paths["remotion_timeline_path"], _remotion_props(packet))
        _write_json(paths["narrative_timeline_path"], packet.narrative_timeline.to_dict())
        _write_json(
            paths["quality_report_path"],
            {"gates": [gate.to_dict() for gate in packet.quality_gates]},
        )
        return {key: str(path) for key, path in paths.items()}

    def build_quality_report(
        self,
        *,
        seedance_findings: list[dict[str, Any]],
        audio_findings: list[dict[str, Any]],
        content_findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        gates = [
            {
                "gate": "seedance_clean_plate",
                "status": "review" if seedance_findings else "pass",
                "findings": seedance_findings,
            },
            {
                "gate": "continuous_voiceover",
                "status": "review" if audio_findings else "pass",
                "findings": audio_findings,
            },
            {
                "gate": "content_hook",
                "status": "review" if content_findings else "pass",
                "findings": content_findings,
            },
        ]
        issue_count = sum(len(gate["findings"]) for gate in gates)
        return {
            "status": "pass" if issue_count == 0 else "review",
            "counts": {"issues": issue_count},
            "gates": gates,
        }


def _main_contradiction(home_team: str, away_team: str, analysis: InternalAnalysis) -> str:
    first, second = _core_variables(analysis)
    return f"{home_team}的{first}，能不能压住{away_team}的{second}。"


def _hook_candidates(
    home_team: str, away_team: str, main_contradiction: str, focus_level: str
) -> list[HookCandidate]:
    hook_variable = _hook_variable_from_contradiction(main_contradiction)
    counter = HookCandidate(
        hook_type="counterintuitive",
        text=f"表面看{home_team}有主场，其实先看{hook_variable.replace('压住', '锁住')}。",
        rationale="默认用反常识型开头，兼顾吸引力和可信度。",
    )
    conflict = HookCandidate(
        hook_type="conflict",
        text=f"这场最大的危险，不是谁名气更大，而是{hook_variable}。",
        rationale="热门大战可用强冲突型增强停留。",
    )
    suspense = HookCandidate(
        hook_type="suspense",
        text=f"前15分钟只看一件事：{hook_variable}。",
        rationale="更稳的体育栏目式开头。",
    )
    if focus_level == "focus":
        return [counter, conflict, suspense]
    return [counter, suspense, conflict]


def _voiceover_script(
    *,
    competition: str,
    home_team: str,
    away_team: str,
    selected_hook: str,
    main_contradiction: str,
    internal_analysis: InternalAnalysis,
    public_script: PublicScript,
) -> str:
    first, second = _core_variables(internal_analysis)
    risks = internal_analysis.key_risks[:2] or ["临场首发", "第一粒进球"]
    lines = [
        selected_hook,
        f"这场{competition}别急着看强弱，先看{home_team}前15分钟能不能把比赛压到前场。",
        f"如果{first}成立，{away_team}的第一脚出球会被迫加速，失误和二点球都会变多。",
        f"但只要{second}打出来，{home_team}身后的空间会立刻变成风险区。",
        f"所以临场重点看{risks[0]}和{risks[-1]}，尤其是第一粒进球前的节奏归属。",
        SHORT_VIDEO_DISCLAIMER,
    ]
    return "".join(lines)


def _sanitize_public_script(text: str) -> str:
    sanitized = text
    for term in FORBIDDEN_PUBLIC_TERMS:
        sanitized = sanitized.replace(term, "")
    if SHORT_VIDEO_DISCLAIMER not in sanitized:
        sanitized += SHORT_VIDEO_DISCLAIMER
    return sanitized


def _core_variables(analysis: InternalAnalysis) -> tuple[str, str]:
    factors = analysis.football_factors
    first = _compact_factor(factors[0] if factors else "开局压迫")
    second = _compact_factor(factors[1] if len(factors) > 1 else "反击速度")
    return first, second


def _compact_factor(value: str) -> str:
    if "压迫" in value:
        return "开局压迫"
    if "反击" in value:
        return "反击速度"
    if "支点" in value:
        return "支点回撤"
    if "肋部" in value:
        return "肋部冲刺"
    if "定位球" in value:
        return "定位球质量"
    if "首发" in value or "阵容" in value:
        return "临场首发"
    if "节奏" in value:
        return "节奏控制"
    return value[:8]


def _hook_variable_from_contradiction(main_contradiction: str) -> str:
    marker = "，能不能压住"
    if marker not in main_contradiction:
        return main_contradiction.rstrip("。")
    left, right = main_contradiction.rstrip("。").split(marker, 1)
    first = left.rsplit("的", 1)[-1]
    return f"{first}能不能压住{right}"


def _tactical_beats(analysis: InternalAnalysis) -> list[TacticalBeat]:
    first, second = _core_variables(analysis)
    return [
        TacticalBeat(
            "variable-1",
            8,
            25,
            first,
            f"核心变量：{first}",
            ["LW", "ST", "RW"],
            ["CB", "DM", "FB"],
            [{"from": [38, 42], "to": [68, 20], "kind": "press"}],
        ),
        TacticalBeat(
            "variable-2",
            25,
            40,
            second,
            f"反制变量：{second}",
            ["CM", "FB"],
            ["ST", "RW"],
            [{"from": [50, 50], "to": [78, 34], "kind": "run"}],
        ),
    ]


def _narrative_timeline(
    *,
    competition: str,
    home_team: str,
    away_team: str,
    selected_hook: str,
    internal_analysis: InternalAnalysis,
) -> NarrativeTimeline:
    first, second = _core_variables(internal_analysis)
    risks = internal_analysis.key_risks[:2] or ["临场首发", "第一粒进球"]
    first_risk = risks[0]
    second_risk = risks[-1]
    segments = [
        NarrativeSegment(
            segment_id="hook",
            start_seconds=0,
            end_seconds=6,
            scene_type="hook",
            voiceover_text=selected_hook,
            subtitle_text=selected_hook,
            screen_card_text="先别急着看强弱",
            visual_intent="用开场情绪镜头把观众注意力锁到隐藏变量。",
            tactical_focus=first,
            transition_to_next="把反常识开头落到第一观察点。",
        ),
        NarrativeSegment(
            segment_id="variable",
            start_seconds=6,
            end_seconds=16,
            scene_type="tactical_map",
            voiceover_text=(
                f"这场{competition}不要急着给结论，真正的第一变量，是{home_team}"
                f"前十五分钟能不能把比赛压到{away_team}半场。"
            ),
            subtitle_text=f"第一变量：{home_team}前15分钟能不能压到前场。",
            screen_card_text=f"第一变量：{first}",
            visual_intent="战术图展示主队压迫线和前场落点。",
            tactical_focus=first,
            transition_to_next="解释这个变量为什么会改变出球质量。",
        ),
        NarrativeSegment(
            segment_id="why",
            start_seconds=16,
            end_seconds=28,
            scene_type="tactical_map",
            voiceover_text=(
                f"如果{first}成立，{away_team}的第一脚出球会被迫提前，"
                "二点球和边路失误就会变多。"
            ),
            subtitle_text=f"压迫成立，{away_team}第一脚出球会被迫提前。",
            screen_card_text="第一脚出球会变急",
            visual_intent="战术图突出第一脚出球、二点球和边路压力。",
            tactical_focus="第一脚出球",
            transition_to_next="从压迫收益切到客队反制路径。",
        ),
        NarrativeSegment(
            segment_id="counter",
            start_seconds=28,
            end_seconds=40,
            scene_type="counter",
            voiceover_text=(
                f"反过来，只要{away_team}能把第一脚传出来，{home_team}"
                "身后的空间会立刻变成反击通道。"
            ),
            subtitle_text=f"{away_team}传出第一脚，身后空间就是反击通道。",
            screen_card_text=f"反制点：{second}",
            visual_intent="用反击箭头展示客队穿过第一层压迫后的纵深。",
            tactical_focus=second,
            transition_to_next="把战术反制落到临场观察信号。",
        ),
        NarrativeSegment(
            segment_id="risk",
            start_seconds=40,
            end_seconds=52,
            scene_type="risk",
            voiceover_text=(
                f"临场再看两个风险：{first_risk}，以及{second_risk}。"
                "早进球会把原本的节奏判断全部改写。"
            ),
            subtitle_text=f"临场重点看：{first_risk}和{second_risk}。",
            screen_card_text="临场风险会改写节奏",
            visual_intent="情绪镜头表现冲刺、回追和节奏突变。",
            tactical_focus=f"{first_risk} / {second_risk}",
            transition_to_next="收束成观众应该带走的单一判断框架。",
        ),
        NarrativeSegment(
            segment_id="closing",
            start_seconds=52,
            end_seconds=60,
            scene_type="closing",
            voiceover_text=(
                "所以这场最值得盯的，不是最终比分，而是谁先把比赛带进自己的节奏。"
                f"{SHORT_VIDEO_DISCLAIMER}"
            ),
            subtitle_text="重点不是比分，而是谁先掌控节奏。",
            screen_card_text="谁先掌控节奏？",
            visual_intent="收尾镜头给出最终观察框架，不制造投注暗示。",
            tactical_focus="节奏归属",
            transition_to_next="结束。",
        ),
    ]
    return NarrativeTimeline(duration_seconds=60, segments=segments)


def _director_shots() -> list[DirectorShot]:
    return [
        DirectorShot("hook-mood", "seedance", 0, 8, "opening_hook", "电影感眼神、球鞋或足球特写。"),
        DirectorShot("tactical-1", "remotion", 8, 25, "variable_explain", "战术图解释第一变量。"),
        DirectorShot("tactical-2", "remotion", 25, 40, "counter_explain", "战术图解释反制变量。"),
        DirectorShot(
            "risk-mood",
            "seedance",
            40,
            52,
            "risk_shift",
            "冲刺、回追或节奏断档情绪镜头。",
        ),
        DirectorShot("closing-mood", "seedance", 52, 60, "closing", "球场灯光和足球静物收尾。"),
    ]


def _mood_shots(*, match_no: str, home_team: str, away_team: str) -> list[MoodShotSpec]:
    base = (
        "cinematic sports anime football mood shot, premium stadium lighting, "
        "no readable text, no letters, no numbers, no logos, no watermark"
    )
    return [
        MoodShotSpec(
            f"{match_no}-mood-01",
            f"{base}, boots and ball closeup before {home_team} vs {away_team}",
            4,
            0,
            8,
            ["no_text", "no_logo", "no_number"],
        ),
        MoodShotSpec(
            f"{match_no}-mood-02",
            f"{base}, sprinting duel, no shirt front closeups",
            4,
            40,
            52,
            ["no_text", "no_logo", "no_number"],
        ),
        MoodShotSpec(
            f"{match_no}-mood-03",
            f"{base}, empty night stadium and ball on grass closing shot",
            4,
            52,
            60,
            ["no_text", "no_logo", "no_number"],
        ),
    ]


def _seedance_mood_manifest(packet: ProductionPacketV2) -> dict[str, Any]:
    return {
        "match_id": packet.match_id,
        "style_profile": packet.style_profile,
        "tasks": [
            {
                "task_key": shot.task_key,
                "provider": "volcengine-ark",
                "model": "doubao-seedance-2-0-260128",
                "content": [{"type": "text", "text": shot.prompt}],
                "resolution": "720p",
                "ratio": "9:16",
                "duration": shot.duration,
                "seed": abs(hash(shot.task_key)) % (2**31),
                "camera_fixed": False,
                "watermark": False,
                "generate_audio": False,
                "safety_identifier": "nutmeg-owner-local",
                "status": shot.status,
                "quality_constraints": shot.quality_constraints,
            }
            for shot in packet.mood_shots
        ],
    }


def _remotion_props(packet: ProductionPacketV2) -> dict[str, Any]:
    return {
        "compositionId": packet.remotion_timeline.composition_id,
        "fps": packet.remotion_timeline.fps,
        "width": packet.remotion_timeline.width,
        "height": packet.remotion_timeline.height,
        "durationSeconds": packet.remotion_timeline.duration_seconds,
        "selectedHook": packet.selected_hook,
        "mainContradiction": packet.main_contradiction,
        "voiceoverScript": packet.voiceover_script,
        "tacticalBeats": [beat.to_dict() for beat in packet.tactical_beats],
        "directorShots": [shot.to_dict() for shot in packet.director_shots],
        "moodShots": [shot.to_dict() for shot in packet.mood_shots],
        "narrativeSegments": [
            segment.to_dict() for segment in packet.narrative_timeline.segments
        ],
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
