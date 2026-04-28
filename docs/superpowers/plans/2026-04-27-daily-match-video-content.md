# Daily Match Video Content Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a review-first daily workflow that creates per-match analysis, public scripts, storyboards, Seedance manifests, and confirmed video task submission/poll/download commands.

**Architecture:** Add a focused daily-content layer over existing JCZQ and content services, plus a separate Seedance provider boundary. CLI and OpenClaw router remain thin adapters that call services and enforce confirmation gates.

**Tech Stack:** Python 3.12, dataclasses, Typer, httpx, reportlab, pytest, existing OpenClaw CLI provider patterns.

---

## File Structure

- Create `nutmeg/domain/daily_content.py`: immutable dataclasses for daily runs, match packs, scripts, storyboards, Seedance task specs, artifacts, and status records.
- Create `nutmeg/services/daily_content.py`: builds review packs from JCZQ calculator payloads, generates deterministic/openclaw-backed scripts, storyboards, prompts, and writes JSON/Markdown/PDF artifacts.
- Create `nutmeg/services/seedance.py`: Volcengine Ark Seedance API adapter plus local manifest submit/poll/download helpers; keeps API key handling and provider schema isolated.
- Modify `nutmeg/interfaces/cli.py`: add builders and commands `daily-content-pack`, `seedance-submit`, and `seedance-poll`.
- Modify `scripts/openclaw/nutmeg_command_router.py`: add allowlisted router actions and confirmation validation.
- Create tests `tests/test_daily_content_service.py` and `tests/test_seedance_service.py`.
- Modify existing tests `tests/test_cli.py` and `tests/test_openclaw_router.py` for CLI/router contracts.
- Update docs `docs/architecture/content-publisher.md`, `docs/architecture/jczq-mixed-report.md`, `README.md`, `feature-list.json`, and memory/verification notes after implementation.

## Task 1: Daily Content Domain Model

**Files:**
- Create: `nutmeg/domain/daily_content.py`
- Test: `tests/test_daily_content_service.py`

- [ ] **Step 1: Write the failing domain serialization test**

```python
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
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_daily_content_service.py::test_daily_content_domain_serializes_nested_match_pack -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'nutmeg.domain.daily_content'`.

- [ ] **Step 3: Implement the domain dataclasses**

Create `nutmeg/domain/daily_content.py` with frozen dataclasses and `to_dict()` methods for the classes named in the test. Use `dataclasses.asdict()` for leaf classes, and explicit nested serialization where lists/dicts contain dataclass objects.

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/test_daily_content_service.py::test_daily_content_domain_serializes_nested_match_pack -q`
Expected: PASS.

## Task 2: Daily Content Service Generates Review Pack

**Files:**
- Create: `nutmeg/services/daily_content.py`
- Modify: `tests/test_daily_content_service.py`

- [ ] **Step 1: Write failing service artifact test**

```python
from pathlib import Path
from nutmeg.services.daily_content import DailyContentService
from nutmeg.services.jczq import SampleJczqCalculatorProvider


def test_daily_content_service_builds_all_sample_matches_and_artifacts(tmp_path) -> None:
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
    assert run.artifacts.json_path and Path(run.artifacts.json_path).exists()
    assert run.artifacts.markdown_path and Path(run.artifacts.markdown_path).exists()
    assert run.artifacts.pdf_path and Path(run.artifacts.pdf_path).read_bytes().startswith(b"%PDF")
    assert run.artifacts.seedance_manifest_path and Path(run.artifacts.seedance_manifest_path).exists()
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_daily_content_service.py::test_daily_content_service_builds_all_sample_matches_and_artifacts -q`
Expected: FAIL because `DailyContentService` does not exist.

- [ ] **Step 3: Implement minimal service**

Implement `DailyContentService.build_run()` to:

- Fetch JCZQ calculator payload from the injected provider.
- Flatten all matches with `matchStatus == "Selling"`.
- Build one `MatchContentPack` per selling match.
- Assign focus level `focus` when the match is in a major league or has balanced/contradictory markets; otherwise `standard`.
- Use 6 segments for `focus`, 4 for `standard`.
- Generate deterministic internal analysis, public script, storyboard, and Seedance specs.
- Write JSON/Markdown/PDF plus `seedance-manifest.json` to a run directory under the given `output_dir`.

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/test_daily_content_service.py -q`
Expected: the domain and service tests pass.

## Task 3: Compliance Gate And Seedance Manifest Filtering

**Files:**
- Modify: `nutmeg/services/daily_content.py`
- Modify: `tests/test_daily_content_service.py`

- [ ] **Step 1: Write failing compliance/filtering tests**

```python
def test_daily_content_public_script_removes_betting_action_language(tmp_path) -> None:
    service = DailyContentService(jczq_provider=SampleJczqCalculatorProvider())

    run = service.build_run(run_date="2026-04-26", output_dir=tmp_path, provider_label="sample")

    forbidden = ["买主胜", "跟我买", "上车", "稳赚", "红单", "私信拿单"]
    for match in run.matches:
        text = match.public_script.voiceover_text
        assert "不构成任何投注建议" in text
        assert not any(term in text for term in forbidden)
        assert match.compliance["risk_level"] in {"LOW", "MEDIUM"}


def test_daily_content_manifest_excludes_blocked_public_scripts(tmp_path) -> None:
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
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_daily_content_service.py::test_daily_content_public_script_removes_betting_action_language tests/test_daily_content_service.py::test_daily_content_manifest_excludes_blocked_public_scripts -q`
Expected: FAIL because override/filtering behavior is missing.

- [ ] **Step 3: Implement compliance integration**

Use existing `ContentComplianceChecker` and `SHORT_VIDEO_DISCLAIMER` from `nutmeg.services.content`. Always append the short disclaimer to public scripts. If compliance is `HIGH` or `BLOCKED`, keep internal analysis but return empty `seedance_specs` for that match and add a warning.

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/test_daily_content_service.py -q`
Expected: all daily content tests pass.

## Task 4: Seedance Provider Boundary

**Files:**
- Create: `nutmeg/services/seedance.py`
- Test: `tests/test_seedance_service.py`

- [ ] **Step 1: Write failing Seedance service tests**

```python
import json
from pathlib import Path

import pytest

from nutmeg.domain.daily_content import SeedanceTaskSpec
from nutmeg.services.seedance import SeedanceService, SeedanceValidationError


def _task() -> SeedanceTaskSpec:
    return SeedanceTaskSpec(
        task_key="001-vertical-segment-01",
        provider="volcengine-ark",
        model="doubao-seedance-2-0-260128",
        content=[{"type": "text", "text": "原创热血足球动画"}],
        resolution="720p",
        ratio="9:16",
        duration=15,
        seed=11,
        camera_fixed=False,
        watermark=True,
        generate_audio=False,
        safety_identifier="owner-hash",
    )


class FakeClient:
    def __init__(self) -> None:
        self.created = []

    def create_task(self, spec: SeedanceTaskSpec) -> dict:
        self.created.append(spec.task_key)
        return {"id": "cgt-001", "status": "queued"}

    def get_task(self, task_id: str) -> dict:
        return {
            "id": task_id,
            "status": "succeeded",
            "content": {"video_url": "https://example.test/video.mp4"},
            "seed": 11,
            "resolution": "720p",
            "ratio": "9:16",
            "duration": 15,
        }


def test_seedance_submit_requires_confirmation(tmp_path) -> None:
    manifest = tmp_path / "seedance-manifest.json"
    manifest.write_text(json.dumps({"tasks": [_task().to_dict()]}, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(SeedanceValidationError, match="--confirm"):
        SeedanceService(client=FakeClient()).submit_manifest(manifest_path=manifest, confirm=False)


def test_seedance_submit_and_poll_updates_manifest(tmp_path) -> None:
    manifest = tmp_path / "seedance-manifest.json"
    manifest.write_text(json.dumps({"tasks": [_task().to_dict()]}, ensure_ascii=False), encoding="utf-8")
    service = SeedanceService(client=FakeClient())

    submitted = service.submit_manifest(manifest_path=manifest, confirm=True)
    polled = service.poll_manifest(manifest_path=manifest, download=False)

    assert submitted["submitted"] == 1
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert saved["tasks"][0]["provider_task_id"] == "cgt-001"
    assert polled["succeeded"] == 1
    assert saved["tasks"][0]["status"] in {"submitted", "succeeded"}
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_seedance_service.py -q`
Expected: FAIL because `nutmeg.services.seedance` does not exist.

- [ ] **Step 3: Implement SeedanceService and Volcengine client shell**

Implement:

- `SeedanceValidationError`.
- `SeedanceService.submit_manifest(manifest_path, confirm, match_id=None, task_key=None)`.
- `SeedanceService.poll_manifest(manifest_path, download=False, output_dir=None)`.
- `VolcengineSeedanceClient` with `create_task()` and `get_task()` using `httpx` and bearer API key from `VOLCENGINE_ARK_API_KEY` then `ARK_API_KEY`.

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/test_seedance_service.py -q`
Expected: PASS.

## Task 5: CLI Commands

**Files:**
- Modify: `nutmeg/interfaces/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

```python
def test_daily_content_pack_command_generates_review_artifacts(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "daily-content-pack",
            "--date",
            "2026-04-26",
            "--provider",
            "sample",
            "--output-dir",
            str(tmp_path),
            "--pdf",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["scope"] == "popular-all"
    assert len(payload["matches"]) >= 8
    assert Path(payload["artifacts"]["seedance_manifest_path"]).exists()


def test_seedance_submit_command_refuses_without_confirm(tmp_path) -> None:
    manifest = tmp_path / "seedance-manifest.json"
    manifest.write_text(json.dumps({"tasks": []}), encoding="utf-8")

    result = runner.invoke(app, ["seedance-submit", "--manifest", str(manifest), "--format", "json"])

    assert result.exit_code == 2
    assert "--confirm" in result.stdout
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_cli.py::test_daily_content_pack_command_generates_review_artifacts tests/test_cli.py::test_seedance_submit_command_refuses_without_confirm -q`
Expected: FAIL because commands do not exist.

- [ ] **Step 3: Add CLI builders and commands**

Add imports for daily content and seedance services. Add constants for default output dir. Implement:

- `build_daily_content_service(provider="live")` using `SportteryJczqCalculatorProvider` or `SampleJczqCalculatorProvider`.
- `daily_content_pack()` command.
- `seedance_submit()` command.
- `seedance_poll()` command.

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/test_cli.py::test_daily_content_pack_command_generates_review_artifacts tests/test_cli.py::test_seedance_submit_command_refuses_without_confirm -q`
Expected: PASS.

## Task 6: OpenClaw Router Actions

**Files:**
- Modify: `scripts/openclaw/nutmeg_command_router.py`
- Modify: `tests/test_openclaw_router.py`

- [ ] **Step 1: Write failing router tests**

```python
def test_router_builds_daily_content_pack_command() -> None:
    router = _load_router()

    request = router.parse_request([
        "daily-content-pack",
        "--date",
        "2026-04-26",
        "--provider",
        "sample",
        "--output-dir",
        ".nutmeg-data/daily-content",
        "--pdf",
    ])

    assert router.build_command(request) == [
        "uv", "run", "nutmeg", "daily-content-pack",
        "--date", "2026-04-26",
        "--provider", "sample",
        "--output-dir", ".nutmeg-data/daily-content",
        "--pdf",
        "--format", "json",
    ]


def test_router_requires_confirmation_for_seedance_submit() -> None:
    router = _load_router()

    with pytest.raises(router.RouterError, match="--confirm-submit"):
        router.parse_request(["seedance-submit", "--manifest", ".nutmeg-data/run/seedance-manifest.json"])
```

- [ ] **Step 2: Run RED**

Run: `uv run pytest tests/test_openclaw_router.py::test_router_builds_daily_content_pack_command tests/test_openclaw_router.py::test_router_requires_confirmation_for_seedance_submit -q`
Expected: FAIL because actions are unsupported.

- [ ] **Step 3: Implement router support**

Add actions to `SUPPORTED_ACTIONS`, parser subcommands, command builders, text validation attrs, and confirmation guard requiring `--confirm-submit` for `seedance-submit`.

- [ ] **Step 4: Run GREEN**

Run: `uv run pytest tests/test_openclaw_router.py::test_router_builds_daily_content_pack_command tests/test_openclaw_router.py::test_router_requires_confirmation_for_seedance_submit -q`
Expected: PASS.

## Task 7: Documentation And Registry

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture/content-publisher.md`
- Modify: `docs/architecture/jczq-mixed-report.md`
- Modify: `feature-list.json`
- Modify: `memory/2026-04-27.md`

- [ ] **Step 1: Add operator docs**

Document commands:

```bash
uv run nutmeg daily-content-pack --date today --provider live --pdf --format json
uv run nutmeg seedance-submit --manifest <path>/seedance-manifest.json --confirm --format json
uv run nutmeg seedance-poll --manifest <path>/seedance-manifest.json --download --format json
```

- [ ] **Step 2: Add feature registry entry**

Add a new registry item named `047-daily-match-video-content-v0` with status `pass` only after verification is complete; until then keep status text factual in progress notes.

- [ ] **Step 3: Keep memory updated**

Append the implementation decisions, verification evidence, and any Seedance setup caveats to `memory/2026-04-27.md`.

## Task 8: Final Verification

**Files:**
- All touched files

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run pytest tests/test_daily_content_service.py tests/test_seedance_service.py tests/test_cli.py::test_daily_content_pack_command_generates_review_artifacts tests/test_cli.py::test_seedance_submit_command_refuses_without_confirm tests/test_openclaw_router.py::test_router_builds_daily_content_pack_command tests/test_openclaw_router.py::test_router_requires_confirmation_for_seedance_submit -q
```

Expected: all listed tests pass.

- [ ] **Step 2: Run lint and compile**

Run:

```bash
uv run ruff check .
python3 -m compileall nutmeg scripts/openclaw
```

Expected: ruff exits 0 and compileall exits 0.

- [ ] **Step 3: Run full repository verification**

Run:

```bash
bash scripts/verify.sh
```

Expected: full test suite passes.

- [ ] **Step 4: Optional live dry-run smoke**

Run only if API/network conditions are acceptable:

```bash
uv run nutmeg daily-content-pack --date today --provider live --pdf --format json
```

Expected: a review pack is generated and no Seedance tasks are submitted.

## Self-Review

- Spec coverage: covers daily all-popular match packs, A+B style, semi-auto Seedance submission, vertical-first + horizontal prompts, hybrid segmentation, layered compliance, artifacts, CLI, router gates, and verification.
- Placeholder scan: checked for placeholder markers and vague deferred-work phrases; none remain in actionable task steps.
- Type consistency: task names and dataclass names match the design spec; CLI names match router names; Seedance manifest fields match `SeedanceTaskSpec`.
