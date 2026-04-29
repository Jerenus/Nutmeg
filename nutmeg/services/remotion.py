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
        return {
            "output_path": self.output_path,
            "command": self.command,
            "returncode": self.returncode,
        }


class RemotionRenderService:
    def __init__(
        self,
        *,
        remotion_root: Path | str = Path("video/remotion"),
        runner: Callable[..., Any] | None = None,
    ) -> None:
        self._remotion_root = Path(remotion_root)
        self._runner = runner or subprocess.run

    def build_render_command(self, *, props_path: Path, output_path: Path) -> list[str]:
        resolved_props = props_path.resolve()
        resolved_output = output_path.resolve()
        return [
            "npm",
            "--prefix",
            str(self._remotion_root),
            "run",
            "render",
            "--",
            str(resolved_output),
            "--props",
            str(resolved_props),
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
