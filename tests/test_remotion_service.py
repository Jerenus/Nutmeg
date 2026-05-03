from __future__ import annotations

from pathlib import Path


def test_remotion_workspace_contains_required_entrypoints() -> None:
    root = Path("video/remotion")

    assert (root / "package.json").exists()
    assert (root / "tsconfig.json").exists()
    assert (root / "src" / "index.tsx").exists()
    assert (root / "src" / "Root.tsx").exists()
    assert (root / "src" / "schema.ts").exists()


def test_remotion_entrypoint_registers_root_for_cli_render() -> None:
    entrypoint = Path("video/remotion/src/index.tsx").read_text(encoding="utf-8")

    assert "registerRoot" in entrypoint
    assert "registerRoot(RemotionRoot)" in entrypoint


def test_remotion_workspace_contains_tactical_components() -> None:
    root = Path("video/remotion/src/components")

    assert (root / "OpeningHook.tsx").exists()
    assert (root / "PitchMap.tsx").exists()
    assert (root / "MoodShotLayer.tsx").exists()
    assert (root / "CaptionTrack.tsx").exists()
    assert (root / "Disclaimer.tsx").exists()


def test_mood_shot_layer_uses_static_file_for_local_assets() -> None:
    component = Path("video/remotion/src/components/MoodShotLayer.tsx").read_text(
        encoding="utf-8"
    )

    assert "staticFile" in component
    assert "staticFile(src)" in component


def test_remotion_schema_accepts_narrative_segments() -> None:
    schema = Path("video/remotion/src/schema.ts").read_text(encoding="utf-8")

    assert "NarrativeSegmentSchema" in schema
    assert "narrativeSegments: z.array(NarrativeSegmentSchema)" in schema
    assert "screen_card_text: z.string()" in schema
    assert "subtitle_text: z.string()" in schema


def test_remotion_root_renders_text_from_narrative_segments() -> None:
    root = Path("video/remotion/src/Root.tsx").read_text(encoding="utf-8")

    assert "props.narrativeSegments" in root
    assert "screen_card_text" in root
    assert "subtitle_text" in root
    assert "重点看开局节奏、临场首发和第一粒进球。" not in root


def test_remotion_render_service_builds_local_render_command(tmp_path) -> None:
    from nutmeg.services.remotion import RemotionRenderService

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


def test_remotion_render_command_resolves_paths_for_npm_prefix() -> None:
    from nutmeg.services.remotion import RemotionRenderService

    service = RemotionRenderService(remotion_root=Path("video/remotion"))
    command = service.build_render_command(
        props_path=Path("tests/fixtures/video_production/sample_v2_timeline.json"),
        output_path=Path(".nutmeg-data/video-production-smoke/remotion-sample.mp4"),
    )

    assert str(Path("tests/fixtures/video_production/sample_v2_timeline.json").resolve()) in command
    assert str(Path(".nutmeg-data/video-production-smoke/remotion-sample.mp4").resolve()) in command


def test_remotion_render_service_uses_runner_and_requires_output(tmp_path) -> None:
    from nutmeg.services.remotion import RemotionRenderService

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


def test_remotion_douyin_safe_layout_keeps_text_out_of_app_chrome() -> None:
    safe_layout = Path("video/remotion/src/safeLayout.ts")
    caption = Path("video/remotion/src/components/CaptionTrack.tsx").read_text(
        encoding="utf-8"
    )
    screen_card = Path("video/remotion/src/components/ScreenCard.tsx").read_text(
        encoding="utf-8"
    )
    disclaimer = Path("video/remotion/src/components/Disclaimer.tsx").read_text(
        encoding="utf-8"
    )

    assert safe_layout.exists()
    source = safe_layout.read_text(encoding="utf-8")
    assert "captionBottom: 560" in source
    assert "disclaimerBottom: 500" in source
    assert "rightReserve: 220" in source
    assert "screenCardTop: 150" in source
    assert "left: douyinSafeLayout.left" in caption
    assert "right: douyinSafeLayout.rightReserve" in caption
    assert "bottom: douyinSafeLayout.captionBottom" in caption
    assert "top: douyinSafeLayout.screenCardTop" in screen_card
    assert "right: douyinSafeLayout.rightReserve" in screen_card
    assert "bottom: douyinSafeLayout.disclaimerBottom" in disclaimer
