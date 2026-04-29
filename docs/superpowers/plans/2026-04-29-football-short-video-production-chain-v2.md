# Football Short Video Production Chain v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the full-AI-animation daily video path with a higher-quality sports explainer pipeline: short-video hooks, deterministic tactical motion graphics, Seedance mood shots, continuous TTS, final QC, and daily artifacts.

**Architecture:** Keep Python as the orchestration and content-analysis layer. Add a small Remotion workspace as the deterministic video rendering layer. Seedance becomes a mood-shot provider only; Remotion owns text, captions, tactical maps, timing, and final layout; FFmpeg handles mux/verification.

**Tech Stack:** Python 3.12, Typer, pytest, ruff, Volcengine Seedance 2.0, CosyVoice/FFmpeg, Node.js + Remotion + React + TypeScript.

---

## File Structure

### Python Domain and Services

- Modify: `nutmeg/domain/daily_content.py`
  - Add production-chain v2 dataclasses for hooks, director shots, mood-shot specs, Remotion timeline specs, and QC results.
- Create: `nutmeg/services/video_production.py`
  - Content Brain, Director, timeline artifact writer, and quality-report builder.
- Create: `nutmeg/services/remotion.py`
  - Python wrapper for invoking the Remotion CLI and validating rendered output.
- Modify: `nutmeg/services/seedance.py`
  - Keep current task submit/poll; add helper support for mood-shot-only manifests if not better housed in `video_production.py`.
- Modify: `nutmeg/services/daily_content.py`
  - Integrate production-chain v2 packet generation while keeping the existing daily content flow available.
- Modify: `nutmeg/interfaces/cli.py`
  - Add commands for production packet generation and Remotion render.
- Modify: `scripts/openclaw/nutmeg_command_router.py`
  - Add safe router actions for new commands, with confirmation gates for provider spend.

### Remotion Workspace

- Create: `video/remotion/package.json`
- Create: `video/remotion/tsconfig.json`
- Create: `video/remotion/src/index.tsx`
- Create: `video/remotion/src/Root.tsx`
- Create: `video/remotion/src/schema.ts`
- Create: `video/remotion/src/styles.ts`
- Create: `video/remotion/src/components/OpeningHook.tsx`
- Create: `video/remotion/src/components/PitchMap.tsx`
- Create: `video/remotion/src/components/MoodShotLayer.tsx`
- Create: `video/remotion/src/components/CaptionTrack.tsx`
- Create: `video/remotion/src/components/Disclaimer.tsx`

### Tests and Fixtures

- Create: `tests/test_video_production_service.py`
- Create: `tests/test_remotion_service.py`
- Modify: `tests/test_daily_content_service.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_openclaw_router.py`
- Create: `tests/fixtures/video_production/sample_v2_timeline.json`

### Docs and Scripts

- Modify: `docs/superpowers/specs/2026-04-29-football-short-video-production-chain-v2-design.md` only if implementation discovers a required design correction.
- Create: `docs/video-production-v2.md`
- Modify: `README.md` command list if the new commands become user-facing.

---

## Task 1: Add Production-Chain v2 Domain Models

**Files:**
- Modify: `nutmeg/domain/daily_content.py`
- Test: `tests/test_video_production_service.py`

- [ ] **Step 1: Write the failing serialization test**

Add `tests/test_video_production_service.py` with this initial test:

```python
from nutmeg.domain.daily_content import (
    DirectorShot,
    HookCandidate,
    MoodShotSpec,
    ProductionPacketV2,
    QualityGateResult,
    RemotionTimelineSpec,
    TacticalBeat,
)


def test_production_packet_v2_serializes_nested_video_plan() -> None:
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
    )

    payload = packet.to_dict()

    assert payload["match_id"] == "周二004"
    assert payload["hook_candidates"][0]["hook_type"] == "counterintuitive"
    assert payload["tactical_beats"][0]["arrows"][0]["kind"] == "press"
    assert payload["mood_shots"][0]["quality_constraints"] == ["no_text", "no_logo", "no_number"]
    assert payload["remotion_timeline"]["composition_id"] == "FootballExplainerV2"
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
uv run pytest tests/test_video_production_service.py::test_production_packet_v2_serializes_nested_video_plan -q
```

Expected: FAIL with an import error because these dataclasses do not exist.

- [ ] **Step 3: Add the minimal dataclasses**

Append these dataclasses to `nutmeg/domain/daily_content.py`:

```python
@dataclass(slots=True, frozen=True)
class HookCandidate:
    hook_type: str
    text: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class TacticalBeat:
    beat_id: str
    start_seconds: float
    end_seconds: float
    title: str
    explanation: str
    home_shape: list[str]
    away_shape: list[str]
    arrows: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class DirectorShot:
    shot_id: str
    visual_owner: str
    start_seconds: float
    end_seconds: float
    purpose: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class MoodShotSpec:
    task_key: str
    prompt: str
    duration: int
    placement_start_seconds: float
    placement_end_seconds: float
    quality_constraints: list[str]
    provider_task_id: str | None = None
    local_video_path: str | None = None
    status: str = "draft"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class RemotionTimelineSpec:
    composition_id: str
    fps: int
    width: int
    height: int
    duration_seconds: float
    props_path: str
    output_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class QualityGateResult:
    gate: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class ProductionPacketV2:
    match_id: str
    style_profile: str
    hook_candidates: list[HookCandidate]
    selected_hook: str
    main_contradiction: str
    voiceover_script: str
    tactical_beats: list[TacticalBeat]
    director_shots: list[DirectorShot]
    mood_shots: list[MoodShotSpec]
    remotion_timeline: RemotionTimelineSpec
    quality_gates: list[QualityGateResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "match_id": self.match_id,
            "style_profile": self.style_profile,
            "hook_candidates": [hook.to_dict() for hook in self.hook_candidates],
            "selected_hook": self.selected_hook,
            "main_contradiction": self.main_contradiction,
            "voiceover_script": self.voiceover_script,
            "tactical_beats": [beat.to_dict() for beat in self.tactical_beats],
            "director_shots": [shot.to_dict() for shot in self.director_shots],
            "mood_shots": [shot.to_dict() for shot in self.mood_shots],
            "remotion_timeline": self.remotion_timeline.to_dict(),
            "quality_gates": [gate.to_dict() for gate in self.quality_gates],
        }
```

- [ ] **Step 4: Run the test to verify GREEN**

Run:

```bash
uv run pytest tests/test_video_production_service.py::test_production_packet_v2_serializes_nested_video_plan -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/domain/daily_content.py tests/test_video_production_service.py
git commit -m "feat: add video production v2 domain models"
```

---

## Task 2: Build the Content Brain Service

**Files:**
- Create: `nutmeg/services/video_production.py`
- Test: `tests/test_video_production_service.py`

- [ ] **Step 1: Write the failing hook-generation test**

Append to `tests/test_video_production_service.py`:

```python
from nutmeg.domain.daily_content import InternalAnalysis, PublicScript
from nutmeg.services.video_production import VideoProductionService


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
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
uv run pytest tests/test_video_production_service.py::test_content_brain_prefers_counterintuitive_hook_for_normal_focus_match -q
```

Expected: FAIL because `nutmeg.services.video_production` does not exist.

- [ ] **Step 3: Implement minimal content brain**

Create `nutmeg/services/video_production.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from nutmeg.domain.daily_content import HookCandidate, InternalAnalysis, PublicScript
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


def _main_contradiction(home_team: str, away_team: str, analysis: InternalAnalysis) -> str:
    factors = "、".join(analysis.football_factors[:3]) or "节奏变量"
    return f"{home_team}能否把{factors}打出来，以及{away_team}如何反制。"


def _hook_candidates(
    home_team: str, away_team: str, main_contradiction: str, focus_level: str
) -> list[HookCandidate]:
    counter = HookCandidate(
        hook_type="counterintuitive",
        text=f"表面看是{home_team}对{away_team}的强强对话，其实真正决定比赛的是{main_contradiction}",
        rationale="默认用反常识型开头，兼顾吸引力和可信度。",
    )
    conflict = HookCandidate(
        hook_type="conflict",
        text=f"这场最大的危险，不是谁名气更大，而是{main_contradiction}",
        rationale="热门大战可用强冲突型增强停留。",
    )
    suspense = HookCandidate(
        hook_type="suspense",
        text=f"前15分钟先看一个问题：{main_contradiction}",
        rationale="更稳的体育栏目式开头。",
    )
    return [counter, conflict, suspense] if focus_level == "focus" else [counter, suspense, conflict]


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
    factors = internal_analysis.football_factors[:2] or public_script.body[:2]
    risks = internal_analysis.key_risks[:2] or ["临场首发", "第一粒进球"]
    lines = [
        selected_hook,
        f"这场{competition}，不要只看{home_team}和{away_team}谁纸面更强，要看比赛怎么被带进自己的节奏。",
        f"第一个变量是{factors[0]}，它会决定开局能不能把对手压到不舒服的位置。",
        f"第二个变量是{factors[-1]}，一旦这个环节断开，反击和身后空间就会被放大。",
        f"风险点看{risks[0]}和{risks[-1]}，它们会让赛前判断快速变形。",
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
```

- [ ] **Step 4: Run the test to verify GREEN**

Run:

```bash
uv run pytest tests/test_video_production_service.py::test_content_brain_prefers_counterintuitive_hook_for_normal_focus_match -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/video_production.py tests/test_video_production_service.py
git commit -m "feat: add short video content brain"
```

---

## Task 3: Build Director Shots, Tactical Beats, and Production Packet Writer

**Files:**
- Modify: `nutmeg/services/video_production.py`
- Test: `tests/test_video_production_service.py`

- [ ] **Step 1: Write the failing packet-writer test**

Append:

```python
from pathlib import Path
import json


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
    mood = json.loads(Path(paths["seedance_mood_manifest_path"]).read_text(encoding="utf-8"))
    assert len(mood["tasks"]) == 3
    assert all("no readable text" in task["content"][0]["text"].lower() for task in mood["tasks"])
```

- [ ] **Step 2: Run the test to verify RED**

```bash
uv run pytest tests/test_video_production_service.py::test_video_production_service_writes_v2_artifacts -q
```

Expected: FAIL because `build_production_packet()` and `write_production_artifacts()` do not exist.

- [ ] **Step 3: Implement packet builder and writer**

Extend `nutmeg/services/video_production.py` with imports and methods:

```python
import json
from pathlib import Path
from typing import Any

from nutmeg.domain.daily_content import (
    DirectorShot,
    MoodShotSpec,
    ProductionPacketV2,
    QualityGateResult,
    RemotionTimelineSpec,
    TacticalBeat,
)

# inside VideoProductionService
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
            voiceover_script=brain.voiceover_script,
            tactical_beats=tactical_beats,
            director_shots=director_shots,
            mood_shots=mood_shots,
            remotion_timeline=timeline,
            quality_gates=[QualityGateResult("content", "review", "Packet created for editorial review.")],
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
            "quality_report_path": match_dir / "quality-report.json",
        }
        _write_json(paths["content_brief_path"], packet.to_dict())
        _write_json(paths["hooks_path"], [hook.to_dict() for hook in packet.hook_candidates])
        paths["voiceover_script_path"].write_text(packet.voiceover_script + "\n", encoding="utf-8")
        _write_json(paths["director_shotlist_path"], [shot.to_dict() for shot in packet.director_shots])
        _write_json(paths["seedance_mood_manifest_path"], _seedance_mood_manifest(packet))
        _write_json(paths["remotion_timeline_path"], _remotion_props(packet))
        _write_json(paths["quality_report_path"], {"gates": [gate.to_dict() for gate in packet.quality_gates]})
        return {key: str(path) for key, path in paths.items()}
```

Add helper functions after the class:

```python
def _tactical_beats(analysis: InternalAnalysis) -> list[TacticalBeat]:
    first = analysis.football_factors[0] if analysis.football_factors else "开局压迫"
    second = analysis.football_factors[1] if len(analysis.football_factors) > 1 else "反击线路"
    return [
        TacticalBeat("variable-1", 8, 25, first, f"核心变量：{first}", ["LW", "ST", "RW"], ["CB", "DM", "FB"], [{"from": [38, 42], "to": [68, 20], "kind": "press"}]),
        TacticalBeat("variable-2", 25, 40, second, f"反制变量：{second}", ["CM", "FB"], ["ST", "RW"], [{"from": [50, 50], "to": [78, 34], "kind": "run"}]),
    ]


def _director_shots() -> list[DirectorShot]:
    return [
        DirectorShot("hook-mood", "seedance", 0, 8, "opening_hook", "电影感眼神、球鞋或足球特写。"),
        DirectorShot("tactical-1", "remotion", 8, 25, "variable_explain", "战术图解释第一变量。"),
        DirectorShot("tactical-2", "remotion", 25, 40, "counter_explain", "战术图解释反制变量。"),
        DirectorShot("risk-mood", "seedance", 40, 52, "risk_shift", "冲刺、回追或节奏断档情绪镜头。"),
        DirectorShot("closing-mood", "seedance", 52, 60, "closing", "球场灯光和足球静物收尾。"),
    ]


def _mood_shots(*, match_no: str, home_team: str, away_team: str) -> list[MoodShotSpec]:
    base = "cinematic sports anime football mood shot, premium stadium lighting, no readable text, no letters, no numbers, no logos, no watermark"
    return [
        MoodShotSpec(f"{match_no}-mood-01", f"{base}, boots and ball closeup before {home_team} vs {away_team}", 4, 0, 8, ["no_text", "no_logo", "no_number"]),
        MoodShotSpec(f"{match_no}-mood-02", f"{base}, sprinting duel, no shirt front closeups", 4, 40, 52, ["no_text", "no_logo", "no_number"]),
        MoodShotSpec(f"{match_no}-mood-03", f"{base}, empty night stadium and ball on grass closing shot", 4, 52, 60, ["no_text", "no_logo", "no_number"]),
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
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run the test to verify GREEN**

```bash
uv run pytest tests/test_video_production_service.py::test_video_production_service_writes_v2_artifacts -q
```

Expected: PASS.

- [ ] **Step 5: Run ruff on the new service**

```bash
uv run ruff check nutmeg/services/video_production.py tests/test_video_production_service.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/services/video_production.py tests/test_video_production_service.py
git commit -m "feat: write video production v2 packets"
```

---

## Task 4: Integrate v2 Packet Generation into Daily Content Artifacts

**Files:**
- Modify: `nutmeg/services/daily_content.py`
- Modify: `tests/test_daily_content_service.py`

- [ ] **Step 1: Write the failing artifact integration test**

Append to `tests/test_daily_content_service.py`:

```python
def test_daily_content_writes_video_production_v2_artifacts(tmp_path) -> None:
    from nutmeg.services.daily_content import DailyContentService

    service = DailyContentService(jczq_provider=SampleJczqCalculatorProvider())

    run = service.build_run(run_date="2026-04-26", output_dir=tmp_path, provider_label="sample")

    assert run.artifacts.run_dir is not None
    first = run.matches[0]
    match_dir = Path(run.artifacts.run_dir) / "matches" / first.match_id.replace("/", "-").replace(" ", "_")
    production_dir = match_dir / "production-v2"

    assert (production_dir / "content-brief.json").exists()
    assert (production_dir / "director-shotlist.json").exists()
    assert (production_dir / "seedance-mood-manifest.json").exists()
    assert (production_dir / "remotion-timeline.json").exists()
    timeline = json.loads((production_dir / "remotion-timeline.json").read_text(encoding="utf-8"))
    assert timeline["compositionId"] == "FootballExplainerV2"
```

- [ ] **Step 2: Run the test to verify RED**

```bash
uv run pytest tests/test_daily_content_service.py::test_daily_content_writes_video_production_v2_artifacts -q
```

Expected: FAIL because `production-v2` artifacts are not written.

- [ ] **Step 3: Wire `VideoProductionService` into daily artifact writing**

In `nutmeg/services/daily_content.py`, add import:

```python
from nutmeg.services.video_production import VideoProductionService
```

In `DailyContentService.__init__`, add an optional dependency:

```python
        video_production_service: VideoProductionService | None = None,
```

Set:

```python
        self._video_production_service = video_production_service or VideoProductionService()
```

Inside `_write_match_artifacts()`, after `production-factors.json`, add:

```python
            packet = self._video_production_service.build_production_packet(
                match_id=match.match_id,
                match_no=match.match_no,
                competition=match.competition,
                home_team=match.home_team,
                away_team=match.away_team,
                focus_level=match.focus_level,
                internal_analysis=match.internal_analysis,
                public_script=match.public_script,
                run_dir=run_dir,
            )
            self._video_production_service.write_production_artifacts(
                packet,
                match_dir=match_dir / "production-v2",
            )
```

- [ ] **Step 4: Run the test to verify GREEN**

```bash
uv run pytest tests/test_daily_content_service.py::test_daily_content_writes_video_production_v2_artifacts -q
```

Expected: PASS.

- [ ] **Step 5: Run focused daily content tests**

```bash
uv run pytest tests/test_daily_content_service.py tests/test_video_production_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add nutmeg/services/daily_content.py tests/test_daily_content_service.py
git commit -m "feat: include video production v2 artifacts in daily packs"
```

---

## Task 5: Add CLI Command for Production Packet Generation

**Files:**
- Modify: `nutmeg/interfaces/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI test**

Append to `tests/test_cli.py` near daily-content tests:

```python
def test_video_production_packet_command_writes_artifacts(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner
    from nutmeg.interfaces.cli import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "video-production-packet",
            "--date",
            "2026-04-26",
            "--provider",
            "sample",
            "--output-dir",
            str(tmp_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["matches"] >= 1
    assert Path(payload["run_dir"]).exists()
    assert payload["production_profile"] == "cinematic-sports-anime-broadcast-v1"
```

- [ ] **Step 2: Run the test to verify RED**

```bash
uv run pytest tests/test_cli.py::test_video_production_packet_command_writes_artifacts -q
```

Expected: FAIL because the command does not exist.

- [ ] **Step 3: Add the CLI command**

In `nutmeg/interfaces/cli.py`, add after `daily-content-pack`:

```python
@app.command("video-production-packet")
def video_production_packet(
    date: str = DAILY_CONTENT_DATE_OPTION,
    provider: str = DAILY_CONTENT_PROVIDER_OPTION,
    output_dir: Path = DAILY_CONTENT_OUTPUT_DIR_OPTION,
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    try:
        service = build_daily_content_service(provider=provider)
        run = service.build_run(
            run_date=_resolve_daily_content_date(date),
            output_dir=output_dir,
            provider_label=provider,
            render_pdf=False,
        )
    except (ContentValidationError, JczqProviderError, JczqSelectionError) as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc

    payload = {
        "run_dir": run.artifacts.run_dir,
        "matches": len(run.matches),
        "production_profile": "cinematic-sports-anime-broadcast-v1",
    }
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(
        f"video-production-packet matches={payload['matches']} run_dir={payload['run_dir']}"
    )
```

- [ ] **Step 4: Run the test to verify GREEN**

```bash
uv run pytest tests/test_cli.py::test_video_production_packet_command_writes_artifacts -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/interfaces/cli.py tests/test_cli.py
git commit -m "feat: add video production packet CLI"
```

---

## Task 6: Add OpenClaw Router Support for Packet Generation

**Files:**
- Modify: `scripts/openclaw/nutmeg_command_router.py`
- Modify: `tests/test_openclaw_router.py`

- [ ] **Step 1: Write failing router test**

Append to `tests/test_openclaw_router.py`:

```python
def test_router_builds_video_production_packet_command() -> None:
    result = run_router(
        [
            "video-production-packet",
            "--date",
            "2026-04-26",
            "--provider",
            "sample",
            "--output-dir",
            ".nutmeg-data/daily-content",
        ]
    )

    assert result["status"] == "ready"
    assert result["command"][:2] == ["nutmeg", "video-production-packet"]
    assert "--format" in result["command"]
    assert "json" in result["command"]
```

- [ ] **Step 2: Run the test to verify RED**

```bash
uv run pytest tests/test_openclaw_router.py::test_router_builds_video_production_packet_command -q
```

Expected: FAIL because the router does not recognize the action.

- [ ] **Step 3: Add router action**

In `scripts/openclaw/nutmeg_command_router.py`:

- add `"video-production-packet"` to the safe actions list near `daily-content-pack`;
- add parser arguments mirroring `daily-content-pack`;
- build command:

```python
if action == "video-production-packet":
    command = [
        "nutmeg",
        "video-production-packet",
        "--date",
        options.date,
        "--provider",
        options.provider,
        "--output-dir",
        options.output_dir,
        "--format",
        "json",
    ]
    return _ready(command)
```

Use the existing helper shape in the file rather than introducing a new routing pattern.

- [ ] **Step 4: Run the test to verify GREEN**

```bash
uv run pytest tests/test_openclaw_router.py::test_router_builds_video_production_packet_command -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/openclaw/nutmeg_command_router.py tests/test_openclaw_router.py
git commit -m "feat: route video production packet command"
```

---

## Task 7: Create the Remotion Workspace Skeleton

**Files:**
- Create: `video/remotion/package.json`
- Create: `video/remotion/tsconfig.json`
- Create: `video/remotion/src/index.tsx`
- Create: `video/remotion/src/Root.tsx`
- Create: `video/remotion/src/schema.ts`
- Create: `video/remotion/src/styles.ts`
- Test: `tests/test_remotion_service.py`

- [ ] **Step 1: Write failing filesystem test**

Create `tests/test_remotion_service.py`:

```python
from pathlib import Path


def test_remotion_workspace_contains_required_entrypoints() -> None:
    root = Path("video/remotion")

    assert (root / "package.json").exists()
    assert (root / "tsconfig.json").exists()
    assert (root / "src" / "index.tsx").exists()
    assert (root / "src" / "Root.tsx").exists()
    assert (root / "src" / "schema.ts").exists()
```

- [ ] **Step 2: Run the test to verify RED**

```bash
uv run pytest tests/test_remotion_service.py::test_remotion_workspace_contains_required_entrypoints -q
```

Expected: FAIL because the workspace does not exist.

- [ ] **Step 3: Add `package.json`**

Create `video/remotion/package.json`:

```json
{
  "name": "nutmeg-video-remotion",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "typecheck": "tsc --noEmit",
    "render": "remotion render src/index.tsx FootballExplainerV2",
    "preview": "remotion studio src/index.tsx"
  },
  "dependencies": {
    "@remotion/cli": "^4.0.0",
    "@remotion/media-utils": "^4.0.0",
    "@remotion/renderer": "^4.0.0",
    "@remotion/shapes": "^4.0.0",
    "@remotion/transitions": "^4.0.0",
    "remotion": "^4.0.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "zod": "^3.23.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "typescript": "^5.5.0"
  }
}
```

- [ ] **Step 4: Add `tsconfig.json`**

Create `video/remotion/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "noEmit": true
  },
  "include": ["src"]
}
```

- [ ] **Step 5: Add Remotion schema**

Create `video/remotion/src/schema.ts`:

```ts
import {z} from 'zod';

export const TacticalBeatSchema = z.object({
  beat_id: z.string(),
  start_seconds: z.number(),
  end_seconds: z.number(),
  title: z.string(),
  explanation: z.string(),
  home_shape: z.array(z.string()),
  away_shape: z.array(z.string()),
  arrows: z.array(z.object({from: z.tuple([z.number(), z.number()]), to: z.tuple([z.number(), z.number()]), kind: z.string()})),
});

export const MoodShotSchema = z.object({
  task_key: z.string(),
  prompt: z.string(),
  duration: z.number(),
  placement_start_seconds: z.number(),
  placement_end_seconds: z.number(),
  quality_constraints: z.array(z.string()),
  provider_task_id: z.string().nullable().optional(),
  local_video_path: z.string().nullable().optional(),
  status: z.string().optional(),
});

export const TimelineSchema = z.object({
  compositionId: z.string(),
  fps: z.number(),
  width: z.number(),
  height: z.number(),
  durationSeconds: z.number(),
  selectedHook: z.string(),
  mainContradiction: z.string(),
  voiceoverScript: z.string(),
  tacticalBeats: z.array(TacticalBeatSchema),
  moodShots: z.array(MoodShotSchema),
});

export type TimelineProps = z.infer<typeof TimelineSchema>;
```

- [ ] **Step 6: Add styles and root composition**

Create `video/remotion/src/styles.ts`:

```ts
export const palette = {
  grass: '#0f6b43',
  pitchLine: 'rgba(255,255,255,0.72)',
  navy: '#07111f',
  gold: '#f6d27a',
  red: '#db3340',
  cyan: '#65d6ff',
  white: '#f8fafc',
};
```

Create `video/remotion/src/Root.tsx`:

```tsx
import React from 'react';
import {AbsoluteFill, Sequence, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {TimelineProps} from './schema';
import {palette} from './styles';

export const FootballExplainerV2: React.FC<TimelineProps> = ({selectedHook, mainContradiction}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const opacity = spring({frame, fps, config: {damping: 18}});
  return (
    <AbsoluteFill style={{background: palette.navy, color: palette.white, fontFamily: 'Arial, sans-serif'}}>
      <Sequence from={0} durationInFrames={90}>
        <div style={{padding: 80, opacity}}>
          <div style={{fontSize: 60, color: palette.gold, fontWeight: 800}}>一分钟赛前变量</div>
          <div style={{marginTop: 40, fontSize: 72, lineHeight: 1.14, fontWeight: 900}}>{selectedHook}</div>
        </div>
      </Sequence>
      <Sequence from={90}>
        <div style={{padding: 80, fontSize: 44, lineHeight: 1.25}}>{mainContradiction}</div>
      </Sequence>
    </AbsoluteFill>
  );
};
```

Create `video/remotion/src/index.tsx`:

```tsx
import React from 'react';
import {Composition} from 'remotion';
import {FootballExplainerV2} from './Root';
import {TimelineSchema} from './schema';

const defaultProps = {
  compositionId: 'FootballExplainerV2',
  fps: 30,
  width: 1080,
  height: 1920,
  durationSeconds: 60,
  selectedHook: '表面看是主场优势，其实关键是压迫会不会断档。',
  mainContradiction: '巴黎压迫持续性 vs 拜仁支点回撤后的肋部冲刺。',
  voiceoverScript: '这场表面看是主场优势，其实真正决定比赛的是压迫会不会断档。',
  tacticalBeats: [],
  moodShots: [],
};

export const RemotionRoot: React.FC = () => (
  <Composition
    id="FootballExplainerV2"
    component={FootballExplainerV2}
    durationInFrames={1800}
    fps={30}
    width={1080}
    height={1920}
    schema={TimelineSchema}
    defaultProps={defaultProps}
  />
);
```

- [ ] **Step 7: Run the filesystem test**

```bash
uv run pytest tests/test_remotion_service.py::test_remotion_workspace_contains_required_entrypoints -q
```

Expected: PASS.

- [ ] **Step 8: Install and typecheck Remotion workspace**

Run:

```bash
npm --prefix video/remotion install
npm --prefix video/remotion run typecheck
```

Expected: install succeeds and `tsc --noEmit` exits 0.

- [ ] **Step 9: Commit**

```bash
git add video/remotion tests/test_remotion_service.py
git commit -m "feat: scaffold remotion video workspace"
```

---

## Task 8: Build Remotion Tactical Components

**Files:**
- Create: `video/remotion/src/components/OpeningHook.tsx`
- Create: `video/remotion/src/components/PitchMap.tsx`
- Create: `video/remotion/src/components/MoodShotLayer.tsx`
- Create: `video/remotion/src/components/CaptionTrack.tsx`
- Create: `video/remotion/src/components/Disclaimer.tsx`
- Modify: `video/remotion/src/Root.tsx`
- Modify: `video/remotion/src/styles.ts`

- [ ] **Step 1: Add component smoke test to typecheck command**

No Python test is needed for visual internals. The verification is TypeScript compilation and a still render later. First create components with explicit props so `npm run typecheck` catches contract errors.

- [ ] **Step 2: Create `OpeningHook.tsx`**

```tsx
import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {palette} from '../styles';

export const OpeningHook: React.FC<{hook: string}> = ({hook}) => {
  const frame = useCurrentFrame();
  const y = interpolate(frame, [0, 18], [36, 0], {extrapolateRight: 'clamp'});
  return (
    <div style={{padding: 76, transform: `translateY(${y}px)`}}>
      <div style={{fontSize: 42, color: palette.gold, fontWeight: 900}}>一分钟赛前变量</div>
      <div style={{marginTop: 34, fontSize: 76, lineHeight: 1.1, fontWeight: 950}}>{hook}</div>
    </div>
  );
};
```

- [ ] **Step 3: Create `PitchMap.tsx`**

```tsx
import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import {palette} from '../styles';
import type {TimelineProps} from '../schema';

type Beat = TimelineProps['tacticalBeats'][number];

export const PitchMap: React.FC<{beat: Beat}> = ({beat}) => {
  const frame = useCurrentFrame();
  const progress = interpolate(frame, [0, 45], [0, 1], {extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', inset: 80, top: 260, bottom: 250}}>
      <div style={{fontSize: 48, fontWeight: 900, color: palette.gold}}>{beat.title}</div>
      <div style={{marginTop: 18, fontSize: 34, lineHeight: 1.25, color: palette.white}}>{beat.explanation}</div>
      <svg viewBox="0 0 100 100" style={{marginTop: 40, width: '100%', height: 920, background: palette.grass, borderRadius: 32}}>
        <rect x="5" y="5" width="90" height="90" fill="none" stroke={palette.pitchLine} strokeWidth="1.2" />
        <line x1="5" y1="50" x2="95" y2="50" stroke={palette.pitchLine} strokeWidth="1" />
        <circle cx="50" cy="50" r="9" fill="none" stroke={palette.pitchLine} strokeWidth="1" />
        {beat.arrows.map((arrow, index) => {
          const x2 = arrow.from[0] + (arrow.to[0] - arrow.from[0]) * progress;
          const y2 = arrow.from[1] + (arrow.to[1] - arrow.from[1]) * progress;
          return (
            <line key={index} x1={arrow.from[0]} y1={arrow.from[1]} x2={x2} y2={y2} stroke={arrow.kind === 'press' ? palette.red : palette.cyan} strokeWidth="2.2" strokeLinecap="round" />
          );
        })}
      </svg>
    </div>
  );
};
```

- [ ] **Step 4: Create lightweight remaining components**

Create `MoodShotLayer.tsx`:

```tsx
import React from 'react';
import {AbsoluteFill, OffthreadVideo} from 'remotion';

export const MoodShotLayer: React.FC<{src?: string | null}> = ({src}) => {
  if (!src) {
    return <AbsoluteFill style={{background: 'linear-gradient(145deg, #07111f, #103b52)'}} />;
  }
  return <OffthreadVideo src={src} style={{width: '100%', height: '100%', objectFit: 'cover'}} muted />;
};
```

Create `CaptionTrack.tsx`:

```tsx
import React from 'react';

export const CaptionTrack: React.FC<{text: string}> = ({text}) => (
  <div style={{position: 'absolute', left: 64, right: 64, bottom: 120, fontSize: 42, lineHeight: 1.25, fontWeight: 800, color: 'white', textShadow: '0 4px 18px rgba(0,0,0,0.9)'}}>
    {text}
  </div>
);
```

Create `Disclaimer.tsx`:

```tsx
import React from 'react';

export const Disclaimer: React.FC = () => (
  <div style={{position: 'absolute', left: 64, right: 64, bottom: 64, fontSize: 28, color: 'rgba(255,255,255,0.78)'}}>
    赛前数据观察，不构成任何投注建议
  </div>
);
```

- [ ] **Step 5: Wire components into `Root.tsx`**

Replace the minimal `Root.tsx` body with sequences:

```tsx
import React from 'react';
import {AbsoluteFill, Sequence, useVideoConfig} from 'remotion';
import type {TimelineProps} from './schema';
import {palette} from './styles';
import {OpeningHook} from './components/OpeningHook';
import {PitchMap} from './components/PitchMap';
import {CaptionTrack} from './components/CaptionTrack';
import {Disclaimer} from './components/Disclaimer';
import {MoodShotLayer} from './components/MoodShotLayer';

export const FootballExplainerV2: React.FC<TimelineProps> = (props) => {
  const {fps} = useVideoConfig();
  const firstBeat = props.tacticalBeats[0];
  const secondBeat = props.tacticalBeats[1] ?? props.tacticalBeats[0];
  const firstMood = props.moodShots[0]?.local_video_path;
  const riskMood = props.moodShots[1]?.local_video_path;
  const closingMood = props.moodShots[2]?.local_video_path;
  return (
    <AbsoluteFill style={{background: palette.navy, color: palette.white, fontFamily: 'Arial, sans-serif'}}>
      <Sequence from={0} durationInFrames={8 * fps}>
        <MoodShotLayer src={firstMood} />
        <OpeningHook hook={props.selectedHook} />
      </Sequence>
      {firstBeat ? <Sequence from={8 * fps} durationInFrames={17 * fps}><PitchMap beat={firstBeat} /></Sequence> : null}
      {secondBeat ? <Sequence from={25 * fps} durationInFrames={15 * fps}><PitchMap beat={secondBeat} /></Sequence> : null}
      <Sequence from={40 * fps} durationInFrames={12 * fps}>
        <MoodShotLayer src={riskMood} />
        <CaptionTrack text={props.mainContradiction} />
      </Sequence>
      <Sequence from={52 * fps} durationInFrames={8 * fps}>
        <MoodShotLayer src={closingMood} />
        <CaptionTrack text="重点看开局节奏、临场首发和第一粒进球。" />
        <Disclaimer />
      </Sequence>
    </AbsoluteFill>
  );
};
```

- [ ] **Step 6: Run Remotion typecheck**

```bash
npm --prefix video/remotion run typecheck
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add video/remotion/src
git commit -m "feat: add remotion football explainer components"
```

---

## Task 9: Add Python Remotion Renderer Wrapper

**Files:**
- Create: `nutmeg/services/remotion.py`
- Modify: `tests/test_remotion_service.py`

- [ ] **Step 1: Write failing command-building test**

Append:

```python
from nutmeg.services.remotion import RemotionRenderService


def test_remotion_render_service_builds_local_render_command(tmp_path) -> None:
    props = tmp_path / "remotion-timeline.json"
    props.write_text('{"compositionId":"FootballExplainerV2"}', encoding="utf-8")
    output = tmp_path / "final.mp4"

    service = RemotionRenderService(remotion_root=Path("video/remotion"))
    command = service.build_render_command(props_path=props, output_path=output)

    assert command[:4] == ["npm", "--prefix", "video/remotion", "run"]
    assert "render" in command
    assert "--props" in command
    assert str(props) in command
    assert str(output) in command
```

- [ ] **Step 2: Run the test to verify RED**

```bash
uv run pytest tests/test_remotion_service.py::test_remotion_render_service_builds_local_render_command -q
```

Expected: FAIL because `nutmeg.services.remotion` does not exist.

- [ ] **Step 3: Implement `RemotionRenderService`**

Create `nutmeg/services/remotion.py`:

```python
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class RemotionRenderError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class RemotionRenderResult:
    output_path: str
    command: list[str]
    returncode: int

    def to_dict(self) -> dict[str, Any]:
        return {"output_path": self.output_path, "command": self.command, "returncode": self.returncode}


class RemotionRenderService:
    def __init__(self, *, remotion_root: Path | str = Path("video/remotion"), runner: Callable[..., Any] | None = None) -> None:
        self._remotion_root = Path(remotion_root)
        self._runner = runner or subprocess.run

    def build_render_command(self, *, props_path: Path, output_path: Path) -> list[str]:
        return [
            "npm",
            "--prefix",
            str(self._remotion_root),
            "run",
            "render",
            "--",
            str(output_path),
            "--props",
            str(props_path),
            "--codec",
            "h264",
        ]

    def render(self, *, props_path: Path, output_path: Path) -> RemotionRenderResult:
        if not props_path.exists():
            raise RemotionRenderError(f"Remotion props file not found: {props_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = self.build_render_command(props_path=props_path, output_path=output_path)
        result = self._runner(command, capture_output=True, text=True, check=False)
        returncode = int(getattr(result, "returncode", 1))
        if returncode != 0:
            stderr = str(getattr(result, "stderr", ""))
            raise RemotionRenderError(f"Remotion render failed: {stderr}")
        if not output_path.exists():
            raise RemotionRenderError(f"Remotion render did not create output: {output_path}")
        return RemotionRenderResult(str(output_path), command, returncode)
```

- [ ] **Step 4: Run the command-building test**

```bash
uv run pytest tests/test_remotion_service.py::test_remotion_render_service_builds_local_render_command -q
```

Expected: PASS.

- [ ] **Step 5: Add fake-runner render success test**

Append:

```python
def test_remotion_render_service_uses_runner_and_requires_output(tmp_path) -> None:
    props = tmp_path / "props.json"
    props.write_text("{}", encoding="utf-8")
    output = tmp_path / "final.mp4"

    class Result:
        returncode = 0
        stderr = ""

    def fake_runner(command, capture_output, text, check):
        output.write_bytes(b"mp4")
        return Result()

    service = RemotionRenderService(remotion_root=Path("video/remotion"), runner=fake_runner)
    result = service.render(props_path=props, output_path=output)

    assert result.output_path == str(output)
    assert output.read_bytes() == b"mp4"
```

- [ ] **Step 6: Run Remotion service tests**

```bash
uv run pytest tests/test_remotion_service.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add nutmeg/services/remotion.py tests/test_remotion_service.py
git commit -m "feat: add remotion render service"
```

---

## Task 10: Add CLI Command for Remotion Rendering

**Files:**
- Modify: `nutmeg/interfaces/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI test with fake service**

Append:

```python
def test_video_render_command_invokes_remotion_service(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner
    from nutmeg.interfaces.cli import app

    props = tmp_path / "remotion-timeline.json"
    props.write_text("{}", encoding="utf-8")
    output = tmp_path / "final.mp4"

    class FakeRemotionService:
        def render(self, *, props_path, output_path):
            output_path.write_bytes(b"mp4")
            return type("Result", (), {"to_dict": lambda self: {"output_path": str(output_path), "returncode": 0}})()

    monkeypatch.setattr("nutmeg.interfaces.cli.build_remotion_render_service", lambda: FakeRemotionService())

    result = CliRunner().invoke(
        app,
        ["video-render", "--props", str(props), "--output", str(output), "--format", "json"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["output_path"] == str(output)
```

- [ ] **Step 2: Run the test to verify RED**

```bash
uv run pytest tests/test_cli.py::test_video_render_command_invokes_remotion_service -q
```

Expected: FAIL because the builder/command is missing.

- [ ] **Step 3: Add builder and command**

In `nutmeg/interfaces/cli.py`, import:

```python
from nutmeg.services.remotion import RemotionRenderError, RemotionRenderService
```

Add builder near service builders:

```python
def build_remotion_render_service() -> RemotionRenderService:
    return RemotionRenderService()
```

Add command near video commands:

```python
@app.command("video-render")
def video_render(
    props: Path = typer.Option(..., "--props"),
    output: Path = typer.Option(..., "--output"),
    format: str = typer.Option("text", "--format", help="text or json"),
) -> None:
    try:
        result = build_remotion_render_service().render(props_path=props, output_path=output)
    except RemotionRenderError as exc:
        console.print(str(exc))
        raise typer.Exit(code=2) from exc
    payload = result.to_dict()
    if format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    console.print(f"video-render output={payload['output_path']}")
```

- [ ] **Step 4: Run the test to verify GREEN**

```bash
uv run pytest tests/test_cli.py::test_video_render_command_invokes_remotion_service -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/interfaces/cli.py tests/test_cli.py
git commit -m "feat: add remotion video render CLI"
```

---

## Task 11: Add Quality Report Builder

**Files:**
- Modify: `nutmeg/services/video_production.py`
- Modify: `tests/test_video_production_service.py`

- [ ] **Step 1: Write failing quality-gate test**

Append:

```python
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
```

- [ ] **Step 2: Run the test to verify RED**

```bash
uv run pytest tests/test_video_production_service.py::test_quality_report_flags_text_artifacts_and_audio_gaps -q
```

Expected: FAIL because `build_quality_report()` does not exist.

- [ ] **Step 3: Implement quality report method**

Add to `VideoProductionService`:

```python
    def build_quality_report(
        self,
        *,
        seedance_findings: list[dict[str, Any]],
        audio_findings: list[dict[str, Any]],
        content_findings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        gates = []
        if seedance_findings:
            gates.append({"gate": "seedance_clean_plate", "status": "review", "findings": seedance_findings})
        else:
            gates.append({"gate": "seedance_clean_plate", "status": "pass", "findings": []})
        if audio_findings:
            gates.append({"gate": "continuous_voiceover", "status": "review", "findings": audio_findings})
        else:
            gates.append({"gate": "continuous_voiceover", "status": "pass", "findings": []})
        if content_findings:
            gates.append({"gate": "content_hook", "status": "review", "findings": content_findings})
        else:
            gates.append({"gate": "content_hook", "status": "pass", "findings": []})
        issue_count = sum(len(gate["findings"]) for gate in gates)
        return {
            "status": "pass" if issue_count == 0 else "review",
            "counts": {"issues": issue_count},
            "gates": gates,
        }
```

- [ ] **Step 4: Run the test to verify GREEN**

```bash
uv run pytest tests/test_video_production_service.py::test_quality_report_flags_text_artifacts_and_audio_gaps -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/video_production.py tests/test_video_production_service.py
git commit -m "feat: add video production quality reports"
```

---

## Task 12: End-to-End Local Smoke Without Provider Spend

**Files:**
- Modify: `tests/test_cli.py`
- Create: `tests/fixtures/video_production/sample_v2_timeline.json`
- Modify: `docs/video-production-v2.md`

- [ ] **Step 1: Add sample timeline fixture**

Create `tests/fixtures/video_production/sample_v2_timeline.json`:

```json
{
  "compositionId": "FootballExplainerV2",
  "fps": 30,
  "width": 1080,
  "height": 1920,
  "durationSeconds": 60,
  "selectedHook": "表面看是主场优势，其实关键是压迫会不会断档。",
  "mainContradiction": "巴黎压迫持续性 vs 拜仁支点回撤后的肋部冲刺。",
  "voiceoverScript": "这场表面看是主场优势，其实真正决定比赛的是压迫会不会断档。以上只是赛前数据观察，不构成任何投注建议，理性看球。",
  "tacticalBeats": [
    {
      "beat_id": "variable-1",
      "start_seconds": 8,
      "end_seconds": 25,
      "title": "锁边压迫",
      "explanation": "巴黎三人压迫把出球赶到边线。",
      "home_shape": ["LW", "ST", "RW"],
      "away_shape": ["CB", "DM", "FB"],
      "arrows": [{"from": [38, 42], "to": [68, 20], "kind": "press"}]
    },
    {
      "beat_id": "variable-2",
      "start_seconds": 25,
      "end_seconds": 40,
      "title": "支点回撤",
      "explanation": "拜仁支点回撤后，肋部冲刺会攻击身后空间。",
      "home_shape": ["CM", "FB"],
      "away_shape": ["ST", "RW"],
      "arrows": [{"from": [50, 50], "to": [78, 34], "kind": "run"}]
    }
  ],
  "directorShots": [],
  "moodShots": []
}
```

- [ ] **Step 2: Render a local Remotion sample**

Run after `npm install` has completed:

```bash
mkdir -p .nutmeg-data/video-production-smoke
npm --prefix video/remotion run render -- .nutmeg-data/video-production-smoke/remotion-sample.mp4 --props tests/fixtures/video_production/sample_v2_timeline.json
ffprobe -v error -show_entries format=duration:stream=codec_type,codec_name,width,height -of default=nw=1 .nutmeg-data/video-production-smoke/remotion-sample.mp4
```

Expected: Remotion creates an MP4 and ffprobe shows a video stream. If Remotion CLI argument parsing rejects the script shape, update `video/remotion/package.json` script to:

```json
"render": "remotion render src/index.tsx FootballExplainerV2"
```

and keep the command shape as:

```bash
npm --prefix video/remotion run render -- .nutmeg-data/video-production-smoke/remotion-sample.mp4 --props tests/fixtures/video_production/sample_v2_timeline.json
```

- [ ] **Step 3: Document the local workflow**

Create `docs/video-production-v2.md`:

```markdown
# Video Production v2

Nutmeg v2 short-video production uses Python for content packets, Seedance for mood shots, Remotion for deterministic tactical graphics, and FFmpeg for final verification.

## Local No-Spend Smoke

```bash
nutmeg video-production-packet --date 2026-04-26 --provider sample --output-dir .nutmeg-data/daily-content-smoke --format json
npm --prefix video/remotion install
npm --prefix video/remotion run render -- .nutmeg-data/video-production-smoke/remotion-sample.mp4 --props tests/fixtures/video_production/sample_v2_timeline.json
ffmpeg -v error -i .nutmeg-data/video-production-smoke/remotion-sample.mp4 -f null -
```

## Provider Spend Boundary

Seedance mood-shot submission remains behind explicit confirmation. Do not submit provider tasks from tests.
```
```

- [ ] **Step 4: Run full focused verification**

```bash
uv run pytest tests/test_video_production_service.py tests/test_remotion_service.py tests/test_daily_content_service.py -q
uv run ruff check nutmeg/domain/daily_content.py nutmeg/services/video_production.py nutmeg/services/remotion.py nutmeg/services/daily_content.py tests/test_video_production_service.py tests/test_remotion_service.py tests/test_daily_content_service.py
npm --prefix video/remotion run typecheck
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/video_production/sample_v2_timeline.json docs/video-production-v2.md video/remotion package.json package-lock.json
git commit -m "docs: document video production v2 smoke workflow"
```

Only add `package-lock.json` if `npm install` creates it under `video/remotion/package-lock.json`; use the exact path in the actual command.

---

## Task 13: Final Verification and Graph Refresh

**Files:**
- Modify: `graphify-out/GRAPH_REPORT.md`
- Modify: `graphify-out/graph.json`
- Modify: `memory/2026-04-29.md`

- [ ] **Step 1: Run full Python verification**

```bash
uv run ruff check .
uv run pytest -q
python3 -m compileall nutmeg scripts/openclaw
```

Expected: ruff passes, pytest passes, compileall exits 0.

- [ ] **Step 2: Run Remotion verification**

```bash
npm --prefix video/remotion run typecheck
```

Expected: typecheck exits 0.

- [ ] **Step 3: Run local no-spend render smoke if Node dependencies are installed**

```bash
mkdir -p .nutmeg-data/video-production-smoke
npm --prefix video/remotion run render -- .nutmeg-data/video-production-smoke/remotion-sample.mp4 --props tests/fixtures/video_production/sample_v2_timeline.json
ffmpeg -v error -i .nutmeg-data/video-production-smoke/remotion-sample.mp4 -f null -
```

Expected: render succeeds and ffmpeg decode passes. If Node dependencies are not installed in the environment, state that this verification is blocked by missing install and provide the install command.

- [ ] **Step 4: Refresh graph assets**

```bash
make graph
```

Expected: `graphify-out/GRAPH_REPORT.md` and `graphify-out/graph.json` update with new Python modules.

- [ ] **Step 5: Record memory**

Append to `memory/2026-04-29.md`:

```markdown
- Implemented football short-video production chain v2: content brain, production packets, Seedance mood-shot manifests, Remotion timeline specs, Remotion workspace, CLI/router commands, and QC reports. Verification: ruff, pytest, compileall, Remotion typecheck, and graph refresh status recorded in final response.
```

- [ ] **Step 6: Commit final verification assets**

```bash
git add graphify-out/GRAPH_REPORT.md graphify-out/graph.json memory/2026-04-29.md
git commit -m "chore: verify video production v2 workflow"
```

---

## Execution Order

1. Task 1: Domain models
2. Task 2: Content Brain
3. Task 3: Director packet writer
4. Task 4: Daily content integration
5. Task 5: CLI packet command
6. Task 6: OpenClaw router support
7. Task 7: Remotion workspace
8. Task 8: Remotion components
9. Task 9: Python Remotion wrapper
10. Task 10: CLI render command
11. Task 11: QC report builder
12. Task 12: End-to-end no-spend smoke
13. Task 13: Final verification and graph refresh

## Spec Coverage Checklist

- 2+1 mixed positioning: Tasks 2, 3, 12
- Counterintuitive default hooks and conflict alternates: Task 2
- Seedance mood-shot-only role: Tasks 3, 4
- No text/no logo/no number constraints: Tasks 3, 11
- Remotion tactical explainer: Tasks 7, 8, 9, 10, 12
- Continuous voiceover support in data artifacts: Tasks 3, 12
- Daily output artifacts: Tasks 3, 4, 5
- Quality gates: Task 11
- Safe provider-spend boundary: Tasks 3, 6, 12
- Full verification and graph-native refresh: Task 13

## Known Constraints

- Remotion introduces a Node toolchain under `video/remotion`; Python remains the orchestration layer.
- Seedance provider calls must never run in tests.
- First production rollout should target one premium match per day before scaling to multiple matches.
- The existing full-Seedance daily manifest flow remains as fallback until v2 is proven by a real match.
