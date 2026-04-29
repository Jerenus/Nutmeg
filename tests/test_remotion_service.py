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
