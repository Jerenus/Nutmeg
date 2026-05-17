from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


class JczqDebateWorkspaceError(ValueError):
    pass


class JczqDebateWorkspaceService:
    def initialize_workspace(
        self,
        *,
        run_date: str | None = None,
        output_dir: Path | str = ".nutmeg-data/jczq",
        brief_text: str | None = None,
    ) -> dict[str, Any]:
        resolved_date = _normalize_run_date(run_date)
        root = Path(output_dir)
        run_dir = root / "daily" / resolved_date
        debate_dir = run_dir / "debate"
        debate_dir.mkdir(parents=True, exist_ok=True)

        if brief_text is None:
            brief_path = run_dir / "brief.md"
            if not brief_path.exists():
                raise JczqDebateWorkspaceError(f"brief not found: {brief_path}")
            brief_text = brief_path.read_text(encoding="utf-8")
        else:
            brief_path = run_dir / "brief.md"

        artifacts = _artifact_paths(debate_dir)
        artifacts["shared_brief_path"].write_text(brief_text, encoding="utf-8")
        _write_if_missing(artifacts["gpt_analysis_path"], _analysis_template("GPT", resolved_date))
        _write_if_missing(
            artifacts["claude_analysis_path"], _analysis_template("Claude", resolved_date)
        )
        _write_if_missing(artifacts["human_notes_path"], _human_notes_template(resolved_date))

        payload = {
            "version": 1,
            "run_date": resolved_date,
            "status": "initialized",
            "brief_path": str(brief_path),
            "debate_dir": str(debate_dir),
            "artifacts": _string_artifacts(artifacts),
            "events": [{"type": "initialized", "at": _now_iso()}],
        }
        artifacts["decision_log_path"].write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "run_date": resolved_date,
            "status": "initialized",
            "debate_dir": str(debate_dir),
            "artifacts": _string_artifacts(artifacts),
        }

    def compare_workspace(
        self,
        *,
        run_date: str | None = None,
        output_dir: Path | str = ".nutmeg-data/jczq",
    ) -> dict[str, Any]:
        resolved_date = _normalize_run_date(run_date)
        debate_dir = Path(output_dir) / "daily" / resolved_date / "debate"
        artifacts = _artifact_paths(debate_dir)
        gpt_text = _read_optional(artifacts["gpt_analysis_path"])
        claude_text = _read_optional(artifacts["claude_analysis_path"])
        semantic = _semantic_compare(gpt_text, claude_text)

        # Backward-compat string forms
        consensus_labels = [_structured_to_label(t) for t in semantic["consensus"]]
        gpt_only_labels = [_structured_to_label(t) for t in semantic["gpt_only"]]
        claude_only_labels = [_structured_to_label(t) for t in semantic["claude_only"]]

        # match-no level conflicts: any match where both sides bet but their
        # bet sets differ (covers same-pool互斥 AND different-pool divergence).
        gpt_match_uniques = {t[0] for t in semantic["gpt_only"]}
        claude_match_uniques = {t[0] for t in semantic["claude_only"]}
        real_pool_conflicts = {c[0] for c in semantic["conflicts"]}
        conflict_matches = sorted(
            real_pool_conflicts | (gpt_match_uniques & claude_match_uniques)
        )

        dropped_legs = _unique([*_extract_dropped(gpt_text), *_extract_dropped(claude_text)])
        payload = {
            "run_date": resolved_date,
            "status": "compared",
            "debate_dir": str(debate_dir),
            "consensus_legs": consensus_labels,
            "conflict_matches": conflict_matches,
            "gpt_only_legs": gpt_only_labels,
            "claude_only_legs": claude_only_labels,
            "dropped_legs": dropped_legs,
            "structured_consensus": [list(t) for t in semantic["consensus"]],
            "structured_conflicts": [list(c) for c in semantic["conflicts"]],
            "structured_gpt_only": [list(t) for t in semantic["gpt_only"]],
            "structured_claude_only": [list(t) for t in semantic["claude_only"]],
            "artifacts": _string_artifacts(artifacts),
        }
        artifacts["disagreements_path"].write_text(
            _render_disagreements(payload),
            encoding="utf-8",
        )
        _update_decision_log(artifacts["decision_log_path"], status="compared", event="compared")
        return payload

    def finalize_workspace(
        self,
        *,
        run_date: str | None = None,
        output_dir: Path | str = ".nutmeg-data/jczq",
    ) -> dict[str, Any]:
        resolved_date = _normalize_run_date(run_date)
        run_dir = Path(output_dir) / "daily" / resolved_date
        debate_dir = run_dir / "debate"
        artifacts = _artifact_paths(debate_dir)
        human_notes = _read_optional(artifacts["human_notes_path"])
        disagreements = _read_optional(artifacts["disagreements_path"])
        final_markdown = _render_final_plan(
            run_date=resolved_date,
            human_notes=human_notes,
            disagreements=disagreements,
            artifacts=artifacts,
        )
        artifacts["final_plan_path"].write_text(final_markdown, encoding="utf-8")

        # If the human authored a final-plan-input.json ticket skeleton, build
        # the PDF-ready structured final-plan.json by enriching legs from the
        # day's brief context.json. Otherwise fall back to the thin-metadata
        # stub (the workflow keeps running; the PDF just can't render yet).
        structured = _maybe_build_structured_plan(
            run_date=resolved_date,
            run_dir=run_dir,
            skeleton_path=artifacts["final_plan_input_path"],
        )
        if structured is not None:
            artifacts["final_plan_json_path"].write_text(
                json.dumps(structured, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            stub = {
                "run_date": resolved_date,
                "status": "finalized",
                "debate_dir": str(debate_dir),
                "human_notes_path": str(artifacts["human_notes_path"]),
                "final_plan_path": str(artifacts["final_plan_path"]),
                "artifacts": _string_artifacts(artifacts),
            }
            artifacts["final_plan_json_path"].write_text(
                json.dumps(stub, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        payload = {
            "run_date": resolved_date,
            "status": "finalized",
            "debate_dir": str(debate_dir),
            "human_notes_path": str(artifacts["human_notes_path"]),
            "final_plan_path": str(artifacts["final_plan_path"]),
            "structured_plan": structured is not None,
            "artifacts": _string_artifacts(artifacts),
        }
        _update_decision_log(
            artifacts["decision_log_path"],
            status="finalized",
            event="finalized",
            extra={
                "final_plan_path": str(artifacts["final_plan_path"]),
                "structured_plan": structured is not None,
            },
        )
        return payload


def _artifact_paths(debate_dir: Path) -> dict[str, Path]:
    return {
        "shared_brief_path": debate_dir / "shared-brief.md",
        "gpt_analysis_path": debate_dir / "gpt-analysis.md",
        "claude_analysis_path": debate_dir / "claude-analysis.md",
        "human_notes_path": debate_dir / "human-notes.md",
        "disagreements_path": debate_dir / "disagreements.md",
        "final_plan_path": debate_dir / "final-plan.md",
        "final_plan_input_path": debate_dir / "final-plan-input.json",
        "final_plan_json_path": debate_dir / "final-plan.json",
        "decision_log_path": debate_dir / "decision-log.json",
    }


def _maybe_build_structured_plan(
    *,
    run_date: str,
    run_dir: Path,
    skeleton_path: Path,
) -> dict[str, Any] | None:
    """Build the PDF-ready structured final-plan from a skeleton, if present.

    Returns ``None`` (caller falls back to the thin-metadata stub) when no
    ``final-plan-input.json`` skeleton was authored or the day's
    ``context.json`` is missing — finalize must never hard-fail just because
    the human hasn't filled the skeleton yet.
    """

    if not skeleton_path.exists():
        return None
    context_path = run_dir / "context.json"
    if not context_path.exists():
        return None

    # Imported lazily so the debate service has no hard dependency on the
    # PDF/builder stack when only init/compare are exercised.
    from nutmeg.services.jczq_final_plan_builder import build_structured_final_plan

    return build_structured_final_plan(
        run_date=run_date,
        context_path=context_path,
        skeleton_path=skeleton_path,
    )


def _analysis_template(model_name: str, run_date: str) -> str:
    return f"""# {model_name} Analysis — {run_date}

## 盘面总判断

## 最看重的3场

## 最想避开的3个陷阱

## Poisson信号是否采纳

## 与系统自动票的不同意见

## A-E投注方案

### A 稳健底仓

### B 主方案

### C Poisson 单核

### D 反大众

### E 极限娱乐

## 最想重仓的一张

## 明日复盘关注点
"""


def _human_notes_template(run_date: str) -> str:
    return f"""# Human Notes — {run_date}

## 人工裁决

## 删除/降权

## 最终票

## 明日复盘问题
"""


def _render_disagreements(payload: dict[str, Any]) -> str:
    lines = [
        f"# JCZQ Debate Disagreements — {payload['run_date']}",
        "",
        "> 语义级对齐（按 match_no/pool/pick 三元组），不是字符串匹配。",
        "",
        "## 共同认可（双方一致下注）",
    ]
    consensus = payload.get("structured_consensus") or []
    if consensus:
        lines.append("| 场 | 池 | 选项 |")
        lines.append("|---|---|---|")
        for triple in consensus:
            lines.append(f"| {triple[0]} | {triple[1]} | {triple[2]} |")
    else:
        lines.append("- 暂无共同腿。")

    lines += ["", "## 真分歧（同场同池但不同选项）"]
    conflicts = payload.get("structured_conflicts") or []
    if conflicts:
        lines.append("| 场 | 池 | GPT 选 | Claude 选 |")
        lines.append("|---|---|---|---|")
        for c in conflicts:
            lines.append(f"| {c[0]} | {c[1]} | {c[2]} | {c[3]} |")
    else:
        lines.append("- 暂无同场互斥分歧。")

    lines += ["", "## GPT 独有"]
    gpt_only = payload.get("structured_gpt_only") or []
    if gpt_only:
        lines.append("| 场 | 池 | 选项 |")
        lines.append("|---|---|---|")
        for t in gpt_only:
            lines.append(f"| {t[0]} | {t[1]} | {t[2]} |")
    else:
        lines.append("- 无")

    lines += ["", "## Claude 独有"]
    claude_only = payload.get("structured_claude_only") or []
    if claude_only:
        lines.append("| 场 | 池 | 选项 |")
        lines.append("|---|---|---|")
        for t in claude_only:
            lines.append(f"| {t[0]} | {t[1]} | {t[2]} |")
    else:
        lines.append("- 无")

    lines += ["", "## 删除/强反对腿（双方共识）"]
    dropped = payload.get("dropped_legs") or []
    if dropped:
        for item in dropped:
            lines.append(f"- {item}")
    else:
        lines.append("- 暂无。")

    return "\n".join(lines) + "\n"


def _render_final_plan(
    *,
    run_date: str,
    human_notes: str,
    disagreements: str,
    artifacts: dict[str, Path],
) -> str:
    return f"""# JCZQ Final Plan — {run_date}

## Data Snapshot
- shared brief: `{artifacts['shared_brief_path']}`
- GPT analysis: `{artifacts['gpt_analysis_path']}`
- Claude analysis: `{artifacts['claude_analysis_path']}`
- disagreements: `{artifacts['disagreements_path']}`

## Consensus And Conflicts

{disagreements.strip() or '尚未生成分歧表。'}

## Human Decision

{human_notes.strip() or '尚未填写人工裁决。'}
"""


_PLAY_TO_POOL = {
    "让球胜平负": "hhad",
    "胜平负": "had",
    "总进球": "ttg",
    "半全场": "hafu",
    "比分": "crs",
}
_PICK_PATTERN = (
    r"[胜平负]/[胜平负]"     # hafu picks like 平/平
    r"|让[胜平负]"            # hhad picks
    r"|[胜平负]"              # had picks
    r"|\d+\+?球"             # ttg picks
    r"|\d+:\d+"              # crs picks
)
_LEG_PATTERN = re.compile(
    r"(周[一二三四五六日]\d{3})\s*"
    r"(让球胜平负|胜平负|总进球|半全场|比分)?\s*"  # play optional
    r"(" + _PICK_PATTERN + r")"
    r"(?:\s*[@＠]\s*(\d+(?:\.\d+)?))?"
)


def _infer_pool(pick: str, explicit_play: str | None) -> str | None:
    """Resolve pool from explicit play if available, else from pick shape."""

    if explicit_play and explicit_play in _PLAY_TO_POOL:
        return _PLAY_TO_POOL[explicit_play]
    if pick in {"胜", "平", "负"}:
        return "had"
    if pick in {"让胜", "让平", "让负"}:
        return "hhad"
    if "/" in pick:
        return "hafu"
    if pick.endswith("球"):
        return "ttg"
    if ":" in pick:
        return "crs"
    return None


def _parse_structured_legs(text: str) -> list[tuple[str, str, str, float | None]]:
    """Extract (match_no, pool, pick, odds) tuples from analysis markdown.

    Replaces the prior string-extraction approach that produced 60% noise on
    2026-05-06's compare run (template lines / prose were getting picked up).
    """

    seen: set[tuple[str, str, str]] = set()
    out: list[tuple[str, str, str, float | None]] = []
    for match in _LEG_PATTERN.finditer(text):
        match_no, play, pick, odds_raw = match.groups()
        pool = _infer_pool(pick, play)
        if pool is None:
            continue
        key = (match_no, pool, pick)
        if key in seen:
            continue
        try:
            odds = float(odds_raw) if odds_raw else None
        except ValueError:
            odds = None
        seen.add(key)
        out.append((*key, odds))
    return out


def _structured_to_label(triple: tuple[str, str, str]) -> str:
    match_no, pool, pick = triple
    play = next((p for p, x in _PLAY_TO_POOL.items() if x == pool), pool)
    return f"{match_no}{play}{pick}"


def _extract_legs(text: str) -> list[str]:
    """Backward-compat string list (delegates to structured parser)."""

    return [_structured_to_label((mn, pool, pick))
            for (mn, pool, pick, _odds) in _parse_structured_legs(text)]


def _extract_dropped(text: str) -> list[str]:
    dropped: list[str] = []
    for line in text.splitlines():
        if not any(marker in line for marker in ("强反对", "删除", "Dropped")):
            continue
        match_no = _match_no(line)
        if not match_no:
            continue
        # Try to parse a structured leg from the line; fall back to
        # match-no level if no structured token survives.
        structured = _parse_structured_legs(line)
        if structured:
            dropped.append(_structured_to_label(structured[0][:3]))
        else:
            dropped.append(match_no)
    return _unique(dropped)


def _semantic_compare(
    gpt_text: str, claude_text: str
) -> dict[str, list]:
    """Tuple-aligned comparison; resolves the prior string-noise bug.

    Returns:
        consensus: same (match_no, pool, pick) on both sides
        conflicts: same match + same pool but different pick (real互斥分歧)
        gpt_only / claude_only: tuples present on one side only
    """

    gpt = _parse_structured_legs(gpt_text)
    claude = _parse_structured_legs(claude_text)
    gpt_keys = {triple[:3] for triple in gpt}
    claude_keys = {triple[:3] for triple in claude}
    consensus = sorted(gpt_keys & claude_keys)
    gpt_only = sorted(gpt_keys - claude_keys)
    claude_only = sorted(claude_keys - gpt_keys)

    # Real conflicts: same (match, pool) different pick — mutually-exclusive
    # outcomes (had三选, hhad三选). For cross-pool relations (e.g. crs 0:0 vs
    # had 平 = same outcome), we surface as gpt_only/claude_only and let the
    # human review.
    by_match_pool_gpt: dict[tuple[str, str], list[str]] = {}
    by_match_pool_claude: dict[tuple[str, str], list[str]] = {}
    for (mn, pool, pick) in gpt_keys:
        by_match_pool_gpt.setdefault((mn, pool), []).append(pick)
    for (mn, pool, pick) in claude_keys:
        by_match_pool_claude.setdefault((mn, pool), []).append(pick)
    conflicts: list[tuple[str, str, str, str]] = []
    for key in by_match_pool_gpt.keys() & by_match_pool_claude.keys():
        for gp in by_match_pool_gpt[key]:
            for cp in by_match_pool_claude[key]:
                if gp != cp:
                    conflicts.append((key[0], key[1], gp, cp))
    return {
        "consensus": consensus,
        "conflicts": conflicts,
        "gpt_only": gpt_only,
        "claude_only": claude_only,
    }


def _conflict_matches(gpt_legs: list[str], claude_legs: list[str]) -> list[str]:
    """Backward-compat: match_nos where the two sides disagree on at least
    one (pool, pick). Now derived from the structured comparison so it
    actually catches real互斥, not string-different formatting."""

    # gpt_legs / claude_legs come from `_extract_legs`; reparse from labels.
    def _re_extract(legs: list[str]) -> list[tuple[str, str, str]]:
        return [t[:3] for label in legs for t in _parse_structured_legs(label)]

    gpt = _re_extract(gpt_legs)
    claude = _re_extract(claude_legs)
    gpt_set = set(gpt)
    claude_set = set(claude)
    matches_gpt = {mn for (mn, _, _) in gpt}
    matches_claude = {mn for (mn, _, _) in claude}
    conflicts: list[str] = []
    for mn in sorted(matches_gpt & matches_claude):
        if {(p, k) for (m, p, k) in gpt_set if m == mn} != {
            (p, k) for (m, p, k) in claude_set if m == mn
        }:
            conflicts.append(mn)
    return conflicts


def _match_no(value: str) -> str | None:
    match = re.search(r"周[一二三四五六日]\d{3}", value)
    return match.group(0) if match else None


def _bullet_lines(items: list[str], *, empty: str) -> list[str]:
    if not items:
        return [f"- {empty}"]
    return [f"- {item}" for item in items]


def _ordered_intersection(first: list[str], second: list[str]) -> list[str]:
    second_set = set(second)
    return [item for item in first if item in second_set]


def _unique(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _write_if_missing(path: Path, text: str) -> None:
    if not path.exists():
        path.write_text(text, encoding="utf-8")


def _read_optional(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _string_artifacts(artifacts: dict[str, Path]) -> dict[str, str]:
    return {key: str(value) for key, value in artifacts.items()}


def _update_decision_log(
    path: Path,
    *,
    status: str,
    event: str,
    extra: dict[str, Any] | None = None,
) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {"version": 1, "events": []}
    payload["status"] = status
    payload.setdefault("events", []).append({"type": event, "at": _now_iso(), **(extra or {})})
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_run_date(value: str | None) -> str:
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if value is None or value == "today":
        return today.isoformat()
    if value == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    return value


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0).isoformat()
