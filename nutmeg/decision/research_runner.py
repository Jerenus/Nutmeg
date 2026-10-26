"""Run headless per-match research with explicit budget and leakage guards."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, Lock
from uuid import uuid4

from nutmeg.decision.bj_time import BJ
from nutmeg.decision.claude_models import (
    is_auth_failure,
    model_label,
    research_model,
    run_claude,
)
from nutmeg.decision.research_ledger import ResearchRunLedger
from nutmeg.decision.research_prompt import render_brief, system_prompt
from nutmeg.decision.rsi_wiring import _cli_invoke
from nutmeg.decision.stance import validate_stance

# 2026-10-25 Jun：40 → 10000（预算不再是进样瓶颈；只剩开球前能否研完）
RESEARCH_DAILY_BUDGET = 10000
MAX_ATTEMPTS = 2
RETRY_MARKER = "⚠️RETRY-AFTER-MAX-TURNS"
# 首轮轮数（2026-10-07）：10-06 起 18/18 场首轮都撞 12 轮上限、24 轮重试才成，
# 白烧一次尝试、40 次/日预算实际只够 20 场。首轮给 24，带标记重试放宽到 36。
FIRST_MAX_TURNS = "24"
RETRY_MAX_TURNS = "36"
RETRY_NOTE = (
    f"\n\n{RETRY_MARKER}：上一次在 {FIRST_MAX_TURNS} 轮内没有产出 JSON。"
    "这次：最多 4 次检索，然后必须输出契约 JSON；"
    "查不到的字段写「未证实」，不要继续搜。"
)

Claude = Callable[[str, str], tuple[int, str]]

# claude CLI 没登录/登录过期：环境问题，不是这场比赛的问题（2026-10-06 launchd 下 OAuth
# 过期，12 场各试 2 次、各记一份「永久拒绝」，烧掉 24 次预算）。撞到即停整轮，
# 不重试、不记拒绝、不占预算。
_is_auth_failure = is_auth_failure
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
    "stance",
)


def _claude_cli(prompt: str, brief: str) -> tuple[int, str]:
    return run_claude(prompt, brief, model=research_model(), allowed_tools="WebSearch,WebFetch",
                      max_turns=RETRY_MAX_TURNS if RETRY_MARKER in brief else FIRST_MAX_TURNS,
                      timeout=900)


def _empty_profile(_match_id: str) -> dict:
    return {}


def _validate(text: str, leg: dict) -> dict:
    from nutmeg.decision.research_intake import intake

    # 模型会在 JSON 前后加说明、围栏，偶尔输出两份（周六007/010/014 因此整份被拒）：
    # 取第一个完整 JSON 对象；找不到 `{` 时按原文解析以保留原报错
    start = text.find("{")
    if start < 0:
        doc = json.loads(text)
    else:
        doc, _end = json.JSONDecoder().raw_decode(text, start)
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
    # 判断 rubric r1（2026-10-02）：逐项校验（无来源的"是"强制弃权）→ 从答案派生 stance.tilt
    from nutmeg.decision.rubric import derive_stance, soften, validate_rubric

    softened, notes = soften(doc.get("rubric"))
    norm_rubric, rubric_issues = validate_rubric(softened, kickoff=leg.get("kickoff_bj"))
    if rubric_issues:                    # soften 之后仍不合法（理论上不会）：整块按弃权处理
        notes.append("rubric 校验失败 → 全部弃权：" + "; ".join(i.message for i in rubric_issues))
        norm_rubric, _ = validate_rubric({"version": softened["version"], "items": {}})
    if notes:
        doc["rubric_notes"] = notes
    doc["rubric_missing"] = not isinstance(doc.get("rubric"), dict)
    doc["rubric"] = norm_rubric
    doc["stance"] = derive_stance(doc.get("stance"), norm_rubric, leg.get("fair"))
    _norm, stance_issues = validate_stance(
        doc.get("stance"),
        confidence=doc.get("confidence"),
        death_three_proofs=doc.get("death_three_proofs") or {},
    )
    if stance_issues:
        raise ValueError("stance: " + "; ".join(i.message for i in stance_issues))
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
            if return_code != 0 and _is_auth_failure(text):
                return {
                    "status": "auth_failed",
                    "raw_output": text,
                    "error": f"claude 退出码 {return_code}",
                    "seconds": round(time.monotonic() - started, 1),
                    "attempts": attempts,
                }
            if return_code != 0:
                raise ValueError(f"claude 退出码 {return_code}")
            research = _validate(text, leg)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            error_signatures.append(f"{last_error}\n{last_text.strip()}")
            if "Reached max turns" in last_text:
                if RETRY_MARKER in brief:
                    # 带标记的重试仍撞 max turns → 永久
                    permanent = True
                    break
                # 第一次撞 max turns：带标记、放宽轮数再试一次
                brief = brief + RETRY_NOTE
                continue
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
    auth_only = bool(attempt_errors) and all(_is_auth_failure(e) for e in attempt_errors)
    if auth_only:
        # 修复前把认证失败记成了拒绝：按没试过处理
        permanent = False
    elif "Reached max turns" in str(document.get("raw_output", "")):
        # 旧记录里 attempts_total == 1 的 max-turns 拒绝仍允许带标记重试一次
        if attempts_total >= 2:
            permanent = True
    elif (
        len(attempt_errors) >= 2
        and attempt_errors[-1] == attempt_errors[-2]
        and "claude 退出码" in attempt_errors[-1]
    ):
        permanent = True
    next_retry = (None if permanent or auth_only
                  else _retry_after(last_attempt, attempts_total))
    normalized = {
        **document,
        **({"auth_only": True} if auth_only else {}),
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


def _auth_refund(path: Path) -> int:
    """修复前认证失败记成拒绝的尝试数（没调到模型，退回当天预算）。"""
    if not path.exists():
        return 0
    document = _load_rejected(path)
    if "auth_refund" in document:
        return int(document["auth_refund"])
    return int(document.get("attempts_total", 0)) if document.get("auth_only") else 0


def _used_attempts(run: dict) -> int:
    if "used_attempts" in run:
        return int(run["used_attempts"])
    return sum(int(row.get("attempts", 0)) for row in run.get("matches", []))


def _fulfill_research(fulfill: Fulfill, *, exp: str, stratum: str, day: str,
                      match_id: str, artifact: Path, data_dir: Path | str,
                      issue: str | None) -> None:
    fulfill([
        "rsi", "fulfill", "--exp", exp, "--duty", "match-research",
        "--day", day, "--match", match_id, "--artifact", str(artifact),
        "--n-rows", "1", "--stratum", stratum, "--data-dir", str(data_dir),
        # 足彩独有场次不在竞彩板上，rsi 只能凭期号查开球（2026-09-28 R1 全拒）
        *(["--issue", issue] if issue else []),
    ])


def _acquire_day_lock(day_dir: Path):
    """同日只许一轮研究在跑（2026-10-07：15:53 手动一轮未完，16:00 sweep 又起一轮，
    6 场研究两遍、多烧 12 次预算，第二轮还覆盖了读者 B 已读过的原件）。拿不到锁返回 None。"""
    import fcntl

    day_dir.mkdir(parents=True, exist_ok=True)
    handle = open(day_dir / ".research-run.lock", "w")  # noqa: SIM115 — 持有到本轮结束
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def run_day(
    *,
    day: str,
    jczq_dir: Path,
    data_dir: Path,
    claude: Claude = _claude_cli,
    fulfill: Fulfill = _cli_invoke,
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
    # 竞彩板没入库（08:00 WAF 降级）不该连带足彩并集池一场都研究不了（2026-09-28）。
    board = (json.loads(board_path.read_text(encoding="utf-8"))
             if board_path.exists() else None)
    legs = board["legs"] if board else {}
    order = sorted(legs, key=lambda value: (legs[value]["kickoff_bj"], value))
    if code is not None:
        order = [value for value in order if value == code]
    entries = [
        {"key": value, "leg": legs[value], "zucai": False,
         "output": day_dir / f"research-{value}.json",
         "rejected": day_dir / f"research-{value}.rejected.json"}
        for value in order
    ]
    # 并集样本池（Jun 2026-09-27）：当天截止足彩期次里不在竞彩板上的场次也研究，且优先
    from nutmeg.decision.pool import (
        reusable_zucai_research,
        zucai_overlap_match_ids,
        zucai_pool_entries,
    )

    # 竞彩板晚开售时对号表要在这里补生成，足彩池才能去掉重叠场次（2026-09-28）
    reusable = (reusable_zucai_research(day=day, data_dir=Path(data_dir),
                                        jczq_dir=Path(jczq_dir))
                if board is not None else {})
    overlap = zucai_overlap_match_ids(day=day, data_dir=Path(data_dir)) if board else set()
    for entry in entries:
        entry["zucai_overlap"] = str(entry["leg"].get("match_id")) in overlap
    # `--code` 同样点得到足彩独有场次（2026-09-28 前它会把整个足彩池跳过）
    entries += [
        {**entry, "zucai": True}
        for entry in sorted(
            zucai_pool_entries(day=day, data_dir=Path(data_dir)),
            key=lambda entry: (entry["leg"]["kickoff_bj"], entry["key"]),
        )
        if code is None or entry["key"] == code
    ]

    if concurrency < 1:
        raise ValueError("concurrency 必须 >= 1")
    day_lock = _acquire_day_lock(day_dir)
    if day_lock is None:
        return {
            "run_id": resolved_run_id, "day": day, "budget": budget,
            "used_attempts": 0, "written": 0, "auth_failed": False, "busy": True,
            "concurrency": concurrency,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": current_time().isoformat(timespec="seconds"),
            "matches": [{"code": entry["key"], "status": "skipped_busy"} for entry in entries],
        }
    prompt = system_prompt()
    ledger = ResearchRunLedger(day_dir)
    prior_used_attempts = max(0, sum(_used_attempts(run) for run in ledger.runs())
                              - sum(_auth_refund(entry["rejected"]) for entry in entries))
    available_attempts = max(0, budget - prior_used_attempts)
    used_attempts = 0
    extra_attempts_used = 0
    attempt_lock = Lock()
    auth_down = Event()

    def watched_claude(system: str, brief: str) -> tuple[int, str]:
        return_code, text = claude(system, brief)
        if return_code != 0 and _is_auth_failure(text):
            auth_down.set()
        return return_code, text

    def claim_extra_attempt() -> bool:
        nonlocal extra_attempts_used, used_attempts
        with attempt_lock:
            if auth_down.is_set():
                return False
            if extra_attempts_used >= extra_attempts_available:
                return False
            extra_attempts_used += 1
            used_attempts += 1
            return True

    rows_by_code: dict[str, dict] = {}
    pending: list[tuple[str, dict, str, int, dict]] = []
    for entry in entries:
        board_code, leg, output = entry["key"], entry["leg"], entry["output"]
        if output.exists():
            rows_by_code[board_code] = {"code": board_code, "status": "skipped_done"}
            continue
        reuse = None if entry["zucai"] else reusable.get(str(leg["match_id"]))
        if reuse is not None:
            research = json.loads(reuse.read_text(encoding="utf-8"))
            research["reused_from"] = str(reuse)
            output.write_text(json.dumps(research, ensure_ascii=False, indent=1),
                              encoding="utf-8")
            leg["judgment_tier"] = "deep_research"
            # 只补 R0：R1 并集池里这场已由足彩研究计过一次，再记就是重复计数
            _fulfill_research(fulfill, exp="R0", stratum="jczq", day=day,
                              match_id=leg["match_id"], artifact=output,
                              data_dir=data_dir, issue=None)
            rows_by_code[board_code] = {"code": board_code, "status": "reused_zucai"}
            continue
        rejected_path = entry["rejected"]
        attempts_total = 0
        rejected = _load_rejected(rejected_path) if rejected_path.exists() else None
        if rejected is not None and not rejected.get("auth_only"):
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
        pending.append((board_code, leg, brief, attempts_total, entry))

    # 预算先给今天还没试过的场次，再给重试（稳定排序：同类内仍按开球先后）；
    # 否则白天的格式重试会把晚上新上板的场次饿死（2026-09-26 024/025）
    # 足彩优先（Jun 2026-09-27）：同为未试过时足彩独有场次排在竞彩前
    pending.sort(key=lambda item: (item[3] > 0, not (item[4]["zucai"]
                                                       or item[4].get("zucai_overlap"))))
    runnable = pending[:available_attempts]
    for board_code, _leg, _brief, _attempts_total, _entry in pending[available_attempts:]:
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
                    if auth_down.is_set():
                        return False
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
                claude=watched_claude,
                claim_attempt=reserved_claim(),
                max_attempts=min(MAX_ATTEMPTS, 3 - attempts_total),
            )
            for _board_code, leg, brief, attempts_total, _entry in runnable
        ]
        results = [future.result() for future in futures]

    model_used = model_label(research_model() if claude is _claude_cli else None)
    written = 0
    for (board_code, leg, _brief, previous_attempts, entry), result in zip(
        runnable, results, strict=True
    ):
        output = entry["output"]
        if result["status"] == "auth_failed":
            used_attempts -= result["attempts"]     # 没调到模型，不占预算
            result = {**result, "attempts": 0}
        elif result["status"] == "skipped_budget" and auth_down.is_set():
            result = {**result, "status": "skipped_auth"}
        if result["status"] == "done":
            written += 1
            research = result.pop("research")
            research["captured_at"] = current_time().isoformat(timespec="seconds")
            # 证据时间由系统盖（2026-09-27）：研究员自填的采集时刻不可信（26133 场4 研究
            # 08:19 落盘，证据却写 12:00）；原值留在 captured_at_declared
            tilt = (research.get("stance") or {}).get("tilt")
            for evidence in (tilt or {}).get("evidence") or []:
                if isinstance(evidence, dict):
                    evidence["captured_at_declared"] = evidence.get("captured_at")
                    evidence["captured_at"] = research["captured_at"]
            for item in ((research.get("rubric") or {}).get("items") or {}).values():
                if isinstance(item, dict) and not item.get("abstain"):
                    item["captured_at_declared"] = item.get("captured_at")
                    item["captured_at"] = research["captured_at"]
            research["model"] = model_used
            output.write_text(
                json.dumps(research, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            leg["judgment_tier"] = "deep_research"
            # R0 冻结只量竞彩；R1 量并集池（足彩独有场次只有 R1）
            targets = [("R1", "pooled")] if entry["zucai"] else [("R0", "jczq"), ("R1", "pooled")]
            for exp, stratum in targets:
                _fulfill_research(fulfill, exp=exp, stratum=stratum, day=day,
                                  match_id=leg["match_id"], artifact=output,
                                  data_dir=data_dir,
                                  issue=entry["issue"] if entry["zucai"] else None)
        elif result["status"] == "rejected":
            last_attempt_at = current_time()
            attempts_total = previous_attempts + result["attempts"]
            rejected_path = entry["rejected"]
            previous_errors: list[str] = []
            auth_refund = _auth_refund(rejected_path)
            if rejected_path.exists():
                previous_document = json.loads(
                    rejected_path.read_text(encoding="utf-8")
                )
                previous_errors = [
                    error for error in previous_document.get("attempt_errors") or []
                    if not _is_auth_failure(error)
                ]
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
                **({"auth_refund": auth_refund} if auth_refund else {}),
            }
            rejected_path.write_text(
                json.dumps(rejected, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        rows_by_code[board_code] = {
            "code": board_code,
            "status": result["status"],
            "seconds": result["seconds"],
            "attempts": result["attempts"],
            "model": model_used,
        }

    if board is not None:
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
        "auth_failed": auth_down.is_set(),
        "concurrency": concurrency,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": current_time().isoformat(timespec="seconds"),
        "matches": [rows_by_code[entry["key"]] for entry in entries],
    }
    ledger.append(report)
    ledger.write_daily_projection(day_dir / f"research-run-{day}.json")
    day_lock.close()
    return report
