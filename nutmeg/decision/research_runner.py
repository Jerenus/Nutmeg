"""Run headless per-match research with explicit budget and leakage guards."""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from nutmeg.decision.research_ledger import ResearchRunLedger
from nutmeg.decision.research_prompt import render_brief, system_prompt

BJ = ZoneInfo("Asia/Shanghai")
RESEARCH_DAILY_BUDGET = 40
MAX_ATTEMPTS = 2

Claude = Callable[[str, str], tuple[int, str]]
Fulfill = Callable[[list[str]], tuple[int, str]]
Profile = Callable[[str], dict]

_REQUIRED = (
    "name",
    "summary",
    "confidence",
    "anchor_integrity",
    "license_questions",
    "death_three_proofs",
    "directional_flags",
    "nondirectional_flags",
    "crash_markers",
    "precedents",
)


def _claude_cli(prompt: str, brief: str) -> tuple[int, str]:
    argv = [
        "claude",
        "-p",
        "--system-prompt",
        prompt,
        "--allowedTools",
        "WebSearch,WebFetch",
        "--max-turns",
        "12",
        "--output-format",
        "text",
    ]
    with tempfile.TemporaryDirectory() as neutral:
        process = subprocess.run(
            argv,
            input=brief,
            capture_output=True,
            text=True,
            timeout=900,
            cwd=neutral,
            check=False,
        )
    return process.returncode, process.stdout


def _cli_fulfill(argv: list[str]) -> tuple[int, str]:
    from nutmeg.decision.rsi_wiring import _cli_invoke

    return _cli_invoke(argv)


def _empty_profile(_match_id: str) -> dict:
    return {}


def _validate(text: str, leg: dict) -> dict:
    from nutmeg.decision.research_intake import intake

    doc = json.loads(text)
    if not isinstance(doc, dict):
        raise ValueError("research output must be a JSON object")
    missing = [key for key in _REQUIRED if key not in doc]
    if missing:
        raise ValueError(f"缺字段 {missing}")
    if not 1 <= int(doc["confidence"]) <= 5:
        raise ValueError("confidence 不在 1-5")
    for face, proofs in (doc.get("death_three_proofs") or {}).items():
        if str(proofs.get("verdict", "alive")).lower() != "dead":
            continue
        count = sum(
            bool(proofs.get(key))
            for key in (
                "a_no_scoring_mechanism",
                "b_precedent_carrier_gone",
                "c_anchor_pass",
            )
        )
        if count < 3:
            raise ValueError(f"{face} 宣告 dead 但三证 {count}/3")
    intake_result = intake(doc, dict(leg))
    errors = [issue.message for issue in intake_result.issues if issue.level == "ERROR"]
    if errors:
        raise ValueError("research intake ERROR: " + "; ".join(errors))
    return doc


def _research_one(*, prompt: str, brief: str, leg: dict, claude: Claude) -> dict:
    started = time.monotonic()
    last_text = ""
    last_error = ""
    attempts = 0
    for _attempt in range(1, MAX_ATTEMPTS + 1):
        attempts += 1
        try:
            return_code, text = claude(prompt, brief)
            last_text = text
            if return_code != 0:
                raise ValueError(f"claude 退出码 {return_code}")
            research = _validate(text, leg)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            continue
        return {
            "status": "done",
            "research": research,
            "seconds": round(time.monotonic() - started, 1),
            "attempts": attempts,
        }
    return {
        "status": "rejected",
        "raw_output": last_text,
        "error": last_error,
        "seconds": round(time.monotonic() - started, 1),
        "attempts": attempts,
    }


def run_day(
    *,
    day: str,
    jczq_dir: Path,
    data_dir: Path,
    claude: Claude = _claude_cli,
    fulfill: Fulfill = _cli_fulfill,
    profile: Profile = _empty_profile,
    budget: int = RESEARCH_DAILY_BUDGET,
    code: str | None = None,
    concurrency: int = 2,
    run_id: str | None = None,
) -> dict:
    started_at = datetime.now(BJ)
    resolved_run_id = run_id or f"rr-{uuid4().hex}"
    day_dir = Path(jczq_dir) / "daily" / day
    board_path = day_dir / "jczq-legs-base.json"
    board = json.loads(board_path.read_text(encoding="utf-8"))
    legs = board["legs"]
    order = sorted(legs, key=lambda value: (legs[value]["kickoff_bj"], value))
    if code is not None:
        order = [value for value in order if value == code]

    if concurrency < 1:
        raise ValueError("concurrency 必须 >= 1")
    prompt = system_prompt()
    used = 0
    rows_by_code: dict[str, dict] = {}
    pending: list[tuple[str, dict, str]] = []
    for board_code in order:
        leg = legs[board_code]
        output = day_dir / f"research-{board_code}.json"
        if output.exists():
            rows_by_code[board_code] = {"code": board_code, "status": "skipped_done"}
            continue
        if datetime.fromisoformat(leg["kickoff_bj"]) <= datetime.now(BJ):
            rows_by_code[board_code] = {
                "code": board_code,
                "status": "skipped_past_kickoff",
            }
            continue
        if used >= budget:
            rows_by_code[board_code] = {"code": board_code, "status": "skipped_budget"}
            continue

        used += 1
        brief = render_brief(
            code=board_code,
            leg=leg,
            profile_notes=profile(leg["match_id"]),
        )
        pending.append((board_code, leg, brief))

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(_research_one, prompt=prompt, brief=brief, leg=leg, claude=claude)
            for _board_code, leg, brief in pending
        ]
        results = [future.result() for future in futures]

    for (board_code, leg, _brief), result in zip(pending, results, strict=True):
        output = day_dir / f"research-{board_code}.json"
        if result["status"] == "done":
            research = result.pop("research")
            research["captured_at"] = datetime.now(BJ).isoformat(timespec="seconds")
            output.write_text(
                json.dumps(research, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            leg["judgment_tier"] = "deep_research"
            fulfill(
                [
                    "rsi",
                    "fulfill",
                    "--exp",
                    "R0",
                    "--duty",
                    "match-research",
                    "--day",
                    day,
                    "--match",
                    leg["match_id"],
                    "--artifact",
                    str(output),
                    "--n-rows",
                    "1",
                    "--stratum",
                    "jczq",
                    "--data-dir",
                    str(data_dir),
                ]
            )
        else:
            rejected = {
                "code": board_code,
                "attempts": result["attempts"],
                "error": result["error"],
                "raw_output": result["raw_output"],
            }
            (day_dir / f"research-{board_code}.rejected.json").write_text(
                json.dumps(rejected, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        rows_by_code[board_code] = {
            "code": board_code,
            "status": result["status"],
            "seconds": result["seconds"],
            "attempts": result["attempts"],
        }

    board_path.write_text(
        json.dumps(board, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    report = {
        "run_id": resolved_run_id,
        "idempotency_key": f"research-run:{day}:{resolved_run_id}",
        "day": day,
        "budget": budget,
        "concurrency": concurrency,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": datetime.now(BJ).isoformat(timespec="seconds"),
        "matches": [rows_by_code[board_code] for board_code in order],
    }
    ledger = ResearchRunLedger(day_dir)
    ledger.append(report)
    ledger.write_daily_projection(day_dir / f"research-run-{day}.json")
    return report
