from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Protocol

import httpx

from nutmeg.domain.daily_content import SeedanceTaskSpec

CREATE_TASK_URL = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
GET_TASK_URL = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks/{task_id}"


class SeedanceValidationError(ValueError):
    pass


class SeedanceProviderError(RuntimeError):
    pass


class SeedanceClient(Protocol):
    def create_task(self, spec: SeedanceTaskSpec) -> dict[str, Any]: ...

    def get_task(self, task_id: str) -> dict[str, Any]: ...


class VolcengineSeedanceClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key or _seedance_api_key()
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client

    def create_task(self, spec: SeedanceTaskSpec) -> dict[str, Any]:
        payload = {
            "model": spec.model,
            "content": spec.content,
            "resolution": spec.resolution,
            "ratio": spec.ratio,
            "duration": spec.duration,
            "seed": spec.seed,
            "camera_fixed": spec.camera_fixed,
            "watermark": spec.watermark,
            "generate_audio": spec.generate_audio,
            "safety_identifier": spec.safety_identifier,
        }
        return self._request("POST", CREATE_TASK_URL, json_payload=payload)

    def get_task(self, task_id: str) -> dict[str, Any]:
        return self._request("GET", GET_TASK_URL.format(task_id=task_id))

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise SeedanceValidationError(
                "Seedance submission requires VOLCENGINE_ARK_API_KEY or ARK_API_KEY."
            )
        client = self._http_client or httpx.Client(timeout=self._timeout_seconds)
        close_client = self._http_client is None
        try:
            response = client.request(
                method,
                url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=json_payload,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SeedanceProviderError(f"Seedance API request failed: {exc}") from exc
        finally:
            if close_client:
                client.close()
        if not isinstance(payload, dict):
            raise SeedanceProviderError("Seedance API returned a non-object response.")
        return payload


class SeedanceService:
    def __init__(
        self,
        *,
        client: SeedanceClient | None = None,
        concat_runner: Callable[..., Any] | None = None,
    ) -> None:
        self._client = client or VolcengineSeedanceClient()
        self._concat_runner = concat_runner or subprocess.run

    def submit_manifest(
        self,
        *,
        manifest_path: Path | str | None = None,
        run_dir: Path | str | None = None,
        confirm: bool,
        match_id: str | None = None,
        task_key: str | None = None,
        ratio_key: str = "vertical",
        max_concurrency: int = 2,
    ) -> dict[str, Any]:
        if not confirm:
            raise SeedanceValidationError(
                "Seedance video generation may incur cost; rerun with --confirm to submit."
            )
        if max_concurrency < 1:
            raise SeedanceValidationError("max-concurrency must be at least 1.")
        path = _resolve_manifest_path(manifest_path=manifest_path, run_dir=run_dir)
        manifest = _load_manifest(path)
        submitted = 0
        skipped = 0
        for task in manifest.get("tasks") or []:
            if not _task_matches(
                task,
                match_id=match_id,
                task_key=task_key,
                ratio_key=ratio_key,
            ):
                skipped += 1
                continue
            if task.get("provider_task_id"):
                skipped += 1
                continue
            spec = _task_spec_from_dict(task)
            result = self._client.create_task(spec)
            task["provider_task_id"] = str(result.get("id") or "")
            task["provider_initial_status"] = str(result.get("status") or "submitted")
            task["status"] = "submitted"
            submitted += 1
        _write_manifest(path, manifest)
        _write_status(path, manifest)
        return {
            "manifest_path": str(path),
            "submitted": submitted,
            "skipped": skipped,
            "ratio_key": ratio_key,
            "max_concurrency": max_concurrency,
        }

    def poll_manifest(
        self,
        *,
        manifest_path: Path | str | None = None,
        run_dir: Path | str | None = None,
        download: bool = False,
        output_dir: Path | str | None = None,
        ratio_key: str = "vertical",
        concat: bool = False,
    ) -> dict[str, Any]:
        path = _resolve_manifest_path(manifest_path=manifest_path, run_dir=run_dir)
        manifest = _load_manifest(path)
        counts = {"queued": 0, "running": 0, "succeeded": 0, "failed": 0, "other": 0}
        for task in manifest.get("tasks") or []:
            if not _task_matches(task, match_id=None, task_key=None, ratio_key=ratio_key):
                continue
            provider_task_id = task.get("provider_task_id")
            if not provider_task_id:
                counts["other"] += 1
                continue
            result = self._client.get_task(str(provider_task_id))
            status = str(result.get("status") or "other")
            task["status"] = status
            task["output_video_url"] = (result.get("content") or {}).get("video_url")
            task["seed"] = result.get("seed", task.get("seed"))
            task["resolution"] = result.get("resolution", task.get("resolution"))
            task["ratio"] = result.get("ratio", task.get("ratio"))
            task["duration"] = result.get("duration", task.get("duration"))
            if result.get("error"):
                task["error"] = result["error"]
            if download and status == "succeeded" and task.get("output_video_url"):
                task["local_video_path"] = _download_video(
                    str(task["output_video_url"]),
                    task=task,
                    manifest_path=path,
                    output_dir=Path(output_dir) if output_dir else None,
                )
            if status in counts:
                counts[status] += 1
            else:
                counts["other"] += 1
        _write_manifest(path, manifest)
        concatenated = self._concat_manifest(path, manifest, ratio_key=ratio_key) if concat else 0
        _write_status(path, manifest)
        return {"manifest_path": str(path), **counts, "concatenated": concatenated}

    def _concat_manifest(
        self,
        manifest_path: Path,
        manifest: dict[str, Any],
        *,
        ratio_key: str,
    ) -> int:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for task in manifest.get("tasks") or []:
            if not _task_matches(task, match_id=None, task_key=None, ratio_key=ratio_key):
                continue
            if task.get("status") != "succeeded" or not task.get("local_video_path"):
                continue
            grouped.setdefault(str(task.get("match_id") or "unknown"), []).append(task)
        concatenated = 0
        for match_id, tasks in grouped.items():
            if len(tasks) < 2:
                continue
            tasks = sorted(tasks, key=lambda item: str(item.get("task_key") or ""))
            output_path = (
                Path(str(manifest.get("run_dir") or manifest_path.parent))
                / "matches"
                / _safe_path_part(match_id)
                / "videos"
                / f"final-{ratio_key}.mp4"
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if _concat_videos(tasks, output_path=output_path, runner=self._concat_runner):
                for task in tasks:
                    task["final_video_path"] = str(output_path)
                concatenated += 1
        return concatenated


def _seedance_api_key() -> str | None:
    return os.environ.get("VOLCENGINE_ARK_API_KEY") or os.environ.get("ARK_API_KEY")


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SeedanceValidationError(f"Seedance manifest not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SeedanceValidationError(f"Seedance manifest is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise SeedanceValidationError("Seedance manifest must contain a JSON object.")
    if not isinstance(payload.get("tasks"), list):
        raise SeedanceValidationError("Seedance manifest missing tasks list.")
    return payload


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_status(path: Path, manifest: dict[str, Any]) -> None:
    counts: dict[str, int] = {}
    for task in manifest.get("tasks") or []:
        status = str(task.get("status") or "draft")
        counts[status] = counts.get(status, 0) + 1
    status_path = Path(str(manifest.get("status_path") or path.with_name("seedance-status.json")))
    status_path.write_text(
        json.dumps(
            {
                "run_id": manifest.get("run_id"),
                "manifest_path": str(path),
                "counts": counts,
                "tasks": [
                    {
                        "task_key": task.get("task_key"),
                        "match_id": task.get("match_id"),
                        "ratio_key": task.get("ratio_key"),
                        "status": task.get("status"),
                        "provider_task_id": task.get("provider_task_id"),
                        "local_video_path": task.get("local_video_path"),
                        "final_video_path": task.get("final_video_path"),
                        "error": task.get("error"),
                    }
                    for task in manifest.get("tasks") or []
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _resolve_manifest_path(
    *,
    manifest_path: Path | str | None,
    run_dir: Path | str | None,
) -> Path:
    if manifest_path is not None:
        return Path(manifest_path)
    if run_dir is not None:
        return Path(run_dir) / "seedance-manifest.json"
    raise SeedanceValidationError("Seedance manifest requires --manifest or --run-dir.")


def _task_matches(
    task: dict[str, Any],
    *,
    match_id: str | None,
    task_key: str | None,
    ratio_key: str = "all",
) -> bool:
    if match_id is not None and task.get("match_id") != match_id:
        return False
    if task_key is not None and task.get("task_key") != task_key:
        return False
    task_ratio_key = task.get("ratio_key") or ("vertical" if task.get("ratio") == "9:16" else None)
    if ratio_key != "all" and task_ratio_key != ratio_key:
        return False
    return True


def _task_spec_from_dict(task: dict[str, Any]) -> SeedanceTaskSpec:
    return SeedanceTaskSpec(
        task_key=str(task["task_key"]),
        provider=str(task.get("provider") or "volcengine-ark"),
        model=str(task.get("model") or "doubao-seedance-2-0-260128"),
        content=list(task.get("content") or []),
        resolution=str(task.get("resolution") or "720p"),
        ratio=str(task.get("ratio") or "9:16"),
        duration=int(task.get("duration") or 15),
        seed=int(task.get("seed") or 0),
        camera_fixed=bool(task.get("camera_fixed", False)),
        watermark=bool(task.get("watermark", True)),
        generate_audio=bool(task.get("generate_audio", False)),
        safety_identifier=str(task.get("safety_identifier") or "nutmeg-owner-local"),
        status=str(task.get("status") or "draft"),
        provider_task_id=task.get("provider_task_id"),
        output_video_url=task.get("output_video_url"),
        local_video_path=task.get("local_video_path"),
        error=task.get("error"),
    )


def _download_video(
    url: str,
    *,
    task: dict[str, Any],
    manifest_path: Path,
    output_dir: Path | None,
) -> str:
    target_dir = (
        output_dir
        or manifest_path.parent / "videos" / str(task.get("match_id") or "unknown")
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{task.get('task_key') or 'segment'}.mp4"
    with httpx.stream("GET", url, timeout=60.0) as response:
        response.raise_for_status()
        with target.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)
    return str(target)


def _concat_videos(
    tasks: list[dict[str, Any]],
    *,
    output_path: Path,
    runner: Callable[..., Any],
) -> bool:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
        list_path = Path(handle.name)
        for task in tasks:
            handle.write(f"file '{Path(str(task['local_video_path'])).as_posix()}'\n")
    try:
        result = runner(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    finally:
        list_path.unlink(missing_ok=True)
    return getattr(result, "returncode", 1) == 0 and output_path.exists()


def _safe_path_part(value: str) -> str:
    return value.replace("/", "-").replace(" ", "_")
