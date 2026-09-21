"""Run headless per-match research with explicit budget and leakage guards."""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
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
Now = Callable[[], datetime]

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

    stripped = text.strip()
    if stripped.startswith("```"):
        # 模型偶尔把 JSON 包在 ```json 围栏里（周六007 因此整份被拒），剥掉围栏再解析
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped[3:]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3]
    doc = json.loads(stripped)
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


def _research_one(
    *,
    prompt: str,
    brief: str,
    leg: dict,
    claude: Claude,
    claim_attempt: Callable[[], bool],
    max_attempts: int = MAX_ATTEMPTS,
) -> dict:
    started = time.monotonic()
    last_text = ""
    last_error = ""
    attempts = 0
    error_signatures: list[str] = []
    permanent = False
    for _attempt in range(1, max_attempts + 1):
        if not claim_attempt():
            break
        attempts += 1
        try:
            return_code, text = claude(prompt, brief)
            last_text = text
            if return_code != 0:
                raise ValueError(f"claude 退出码 {return_code}")
            research = _validate(text, leg)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            error_signatures.append(f"{last_error}\n{last_text.strip()}")
            if "Reached max turns" in last_text:
                permanent = True
                break
            if (
                len(error_signatures) >= 2
                and error_signatures[-1] == error_signatures[-2]
                and "claude 退出码" in last_error
            ):
                permanent = True
                break
            continue
        return {
            "status": "done",
            "research": research,
            "seconds": round(time.monotonic() - started, 1),
            "attempts": attempts,
        }
    if attempts == 0:
        return {"status": "skipped_budget", "seconds": 0.0, "attempts": 0}
    return {
        "status": "rejected",
        "raw_output": last_text,
        "error": last_error,
        "seconds": round(time.monotonic() - started, 1),
        "attempts": attempts,
        "permanent": permanent,
        "attempt_errors": error_signatures,
    }


def _retry_after(last_attempt_at: datetime, attempts_total: int) -> datetime | None:
    if attempts_total == 1:
        return last_attempt_at + timedelta(hours=1)
    if attempts_total == 2:
        return last_attempt_at + timedelta(hours=4)
    return None


def _load_rejected(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    attempts_total = int(document.get("attempts_total", document.get("attempts", 0)))
    last_attempt_at = document.get("last_attempt_at")
    if not last_attempt_at:
        last_attempt_at = datetime.fromtimestamp(path.stat().st_mtime, tz=BJ).isoformat(
            timespec="seconds"
        )
    last_attempt = datetime.fromisoformat(last_attempt_at)
    if last_attempt.tzinfo is None:
        last_attempt = last_attempt.replace(tzinfo=BJ)
    permanent = bool(document.get("permanent", False))
    attempt_errors = list(document.get("attempt_errors") or [])
    if "Reached max turns" in str(document.get("raw_output", "")):
        permanent = True
    elif (
        len(attempt_errors) >= 2
        and attempt_errors[-1] == attempt_errors[-2]
        and "claude 退出码" in attempt_errors[-1]
    ):
        permanent = True
    next_retry = None if permanent else _retry_after(last_attempt, attempts_total)
    normalized = {
        **document,
        "attempts_total": attempts_total,
        "last_attempt_at": last_attempt.isoformat(timespec="seconds"),
        "next_retry_after": (
            next_retry.isoformat(timespec="seconds") if next_retry is not None else None
        ),
        "permanent": permanent,
    }
    if normalized != document:
        path.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return normalized


def _used_attempts(run: dict) -> int:
    if "used_attempts" in run:
        return int(run["used_attempts"])
    return sum(int(row.get("attempts", 0)) for row in run.get("matches", []))


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
    now: Now | None = None,
) -> dict:
    current_time = now or (lambda: datetime.now(BJ))
    started_at = current_time()
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
    ledger = ResearchRunLedger(day_dir)
    prior_used_attempts = sum(_used_attempts(run) for run in ledger.runs())
    available_attempts = max(0, budget - prior_used_attempts)
    used_attempts = 0
    extra_attempts_used = 0
    attempt_lock = Lock()

    def claim_extra_attempt() -> bool:
        nonlocal extra_attempts_used, used_attempts
        with attempt_lock:
            if extra_attempts_used >= extra_attempts_available:
                return False
            extra_attempts_used += 1
            used_attempts += 1
            return True

    rows_by_code: dict[str, dict] = {}
    pending: list[tuple[str, dict, str, int]] = []
    for board_code in order:
        leg = legs[board_code]
        output = day_dir / f"research-{board_code}.json"
        if output.exists():
            rows_by_code[board_code] = {"code": board_code, "status": "skipped_done"}
            continue
        rejected_path = day_dir / f"research-{board_code}.rejected.json"
        attempts_total = 0
        if rejected_path.exists():
            rejected = _load_rejected(rejected_path)
            attempts_total = int(rejected["attempts_total"])
            if rejected["permanent"]:
                rows_by_code[board_code] = {
                    "code": board_code,
                    "status": "skipped_permanent",
                }
                continue
            if attempts_total >= 3:
                rows_by_code[board_code] = {
                    "code": board_code,
                    "status": "skipped_retry_limit",
                }
                continue
            next_retry_after = rejected.get("next_retry_after")
            if next_retry_after and datetime.fromisoformat(next_retry_after) > started_at:
                rows_by_code[board_code] = {
                    "code": board_code,
                    "status": "skipped_backoff",
                }
                continue
        if datetime.fromisoformat(leg["kickoff_bj"]) <= started_at:
            rows_by_code[board_code] = {
                "code": board_code,
                "status": "skipped_past_kickoff",
            }
            continue
        if available_attempts <= 0:
            rows_by_code[board_code] = {"code": board_code, "status": "skipped_budget"}
            continue

        brief = render_brief(
            code=board_code,
            leg=leg,
            profile_notes=profile(leg["match_id"]),
        )
        pending.append((board_code, leg, brief, attempts_total))

    runnable = pending[:available_attempts]
    for board_code, _leg, _brief, _attempts_total in pending[available_attempts:]:
        rows_by_code[board_code] = {"code": board_code, "status": "skipped_budget"}

    reserved_attempts = len(runnable)
    extra_attempts_available = available_attempts - reserved_attempts

    def reserved_claim() -> Callable[[], bool]:
        first = True

        def claim() -> bool:
            nonlocal first, used_attempts
            if first:
                first = False
                with attempt_lock:
                    used_attempts += 1
                return True
            return claim_extra_attempt()

        return claim

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(
                _research_one,
                prompt=prompt,
                brief=brief,
                leg=leg,
                claude=claude,
                claim_attempt=reserved_claim(),
                max_attempts=min(MAX_ATTEMPTS, 3 - attempts_total),
            )
            for _board_code, leg, brief, attempts_total in runnable
        ]
        results = [future.result() for future in futures]

    written = 0
    for (board_code, leg, _brief, previous_attempts), result in zip(
        runnable, results, strict=True
    ):
        output = day_dir / f"research-{board_code}.json"
        if result["status"] == "done":
            written += 1
            research = result.pop("research")
            research["captured_at"] = current_time().isoformat(timespec="seconds")
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
        elif result["status"] == "rejected":
            last_attempt_at = current_time()
            attempts_total = previous_attempts + result["attempts"]
            rejected_path = day_dir / f"research-{board_code}.rejected.json"
            previous_errors: list[str] = []
            if rejected_path.exists():
                previous_document = json.loads(
                    rejected_path.read_text(encoding="utf-8")
                )
                previous_errors = list(previous_document.get("attempt_errors") or [])
            attempt_errors = previous_errors + result["attempt_errors"]
            permanent = bool(result["permanent"]) or (
                len(attempt_errors) >= 2
                and attempt_errors[-1] == attempt_errors[-2]
                and "claude 退出码" in attempt_errors[-1]
            )
            next_retry_after = (
                None
                if permanent
                else _retry_after(last_attempt_at, attempts_total)
            )
            rejected = {
                "code": board_code,
                "attempts": result["attempts"],
                "attempts_total": attempts_total,
                "last_attempt_at": last_attempt_at.isoformat(timespec="seconds"),
                "next_retry_after": (
                    next_retry_after.isoformat(timespec="seconds")
                    if next_retry_after is not None
                    else None
                ),
                "permanent": permanent,
                "attempt_errors": attempt_errors,
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
        "used_attempts": used_attempts,
        "written": written,
        "concurrency": concurrency,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": current_time().isoformat(timespec="seconds"),
        "matches": [rows_by_code[board_code] for board_code in order],
    }
    ledger.append(report)
    ledger.write_daily_projection(day_dir / f"research-run-{day}.json")
    return report
