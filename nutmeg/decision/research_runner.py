"""Run headless per-match research with explicit budget and leakage guards."""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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


def _validate(text: str) -> dict:
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
    return doc


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
) -> dict:
    day_dir = Path(jczq_dir) / "daily" / day
    board_path = day_dir / "jczq-legs-base.json"
    board = json.loads(board_path.read_text(encoding="utf-8"))
    legs = board["legs"]
    order = sorted(legs, key=lambda value: (legs[value]["kickoff_bj"], value))
    if code is not None:
        order = [value for value in order if value == code]

    prompt = system_prompt()
    used = 0
    rows: list[dict] = []
    for board_code in order:
        leg = legs[board_code]
        output = day_dir / f"research-{board_code}.json"
        if output.exists():
            rows.append({"code": board_code, "status": "skipped_done"})
            continue
        if datetime.fromisoformat(leg["kickoff_bj"]) <= datetime.now(BJ):
            rows.append({"code": board_code, "status": "skipped_past_kickoff"})
            continue
        if used >= budget:
            rows.append({"code": board_code, "status": "skipped_budget"})
            continue

        used += 1
        brief = render_brief(
            code=board_code,
            leg=leg,
            profile_notes=profile(leg["match_id"]),
        )
        started = time.monotonic()
        status = "rejected"
        last_text = ""
        last_error = ""
        attempts = 0
        for _attempt in range(1, MAX_ATTEMPTS + 1):
            attempts += 1
            return_code, text = claude(prompt, brief)
            last_text = text
            try:
                if return_code != 0:
                    raise ValueError(f"claude 退出码 {return_code}")
                research = _validate(text)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                last_error = str(exc)
                continue
            research["captured_at"] = datetime.now(BJ).isoformat(timespec="seconds")
            output.write_text(
                json.dumps(research, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            leg["judgment_tier"] = "deep_research"
            status = "done"
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
            break

        if status == "rejected":
            rejected = {
                "code": board_code,
                "attempts": attempts,
                "error": last_error,
                "raw_output": last_text,
            }
            (day_dir / f"research-{board_code}.rejected.json").write_text(
                json.dumps(rejected, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        rows.append(
            {
                "code": board_code,
                "status": status,
                "seconds": round(time.monotonic() - started, 1),
                "attempts": attempts,
            }
        )

    board_path.write_text(
        json.dumps(board, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    report = {"day": day, "budget": budget, "matches": rows}
    (day_dir / f"research-run-{day}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return report
