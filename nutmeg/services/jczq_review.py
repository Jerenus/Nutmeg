from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx

from nutmeg.services.jczq_daily import JczqTextSender, _report_from_dict
from nutmeg.services.jczq_review_explainer import (
    Completer,
    explain_missed_plans,
)
from nutmeg.services.jczq_strategy_memory import (
    render_decision_policy_notes,
    update_strategy_memory,
)


class JczqResultProvider(Protocol):
    source_page: str

    def fetch_results(self, run_date: str) -> dict[str, dict[str, str]]: ...


class OkoooJczqResultProvider:
    source_page = "https://m.okooo.com/kaijiang/sport.php"

    _POOL_TYPES = {
        "had": "SportteryNWDL",
        "hhad": "SportteryWDL",
        "crs": "SportteryScore",
        "ttg": "SportteryTotalGoals",
        "hafu": "SportteryHalfFull",
    }

    def __init__(self, *, timeout: float = 20.0) -> None:
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch_results(self, run_date: str) -> dict[str, dict[str, str]]:
        prefix = _weekday_prefix(run_date)
        results: dict[str, dict[str, str]] = {}
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 Mobile/15E148"
            )
        }
        for pool, lottery_type in self._POOL_TYPES.items():
            url = f"{self.source_page}?LotteryNo={run_date}&LotteryType={lottery_type}"
            response = self._client.get(url, headers=headers)
            response.raise_for_status()
            text = response.content.decode("gb18030", errors="replace")
            for cells in _parse_result_rows(text):
                match_no = f"{prefix}{cells[0]}"
                row = results.setdefault(match_no, {})
                score, half_score = _parse_score_cell(cells[4] if len(cells) > 4 else "")
                if score:
                    row["score"] = score
                if half_score:
                    row["half_score"] = half_score
                actual, odds = _parse_pool_result_and_odds(pool, cells[-1])
                row[pool] = actual
                if odds is not None:
                    row[f"{pool}_odds"] = f"{odds:.2f}"
        return results


class JczqDailyReviewService:
    def __init__(
        self,
        *,
        result_provider: JczqResultProvider | None = None,
        telegram_sender: JczqTextSender | None = None,
        telegram_chat_ids: list[int] | None = None,
        betting_repository: Any | None = None,
        explanation_completer: Completer | None = None,
    ) -> None:
        self._result_provider = result_provider or OkoooJczqResultProvider()
        self._telegram_sender = telegram_sender
        self._telegram_chat_ids = telegram_chat_ids or []
        self._betting_repository = betting_repository
        self._explanation_completer = explanation_completer

    def build_review(
        self,
        *,
        run_date: str | None = None,
        output_dir: Path | str = ".nutmeg-data/jczq",
        dispatch_telegram: bool = False,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        resolved_date = _normalize_review_date(run_date)
        out = Path(output_dir)
        context_path = out / "daily" / resolved_date / "context.json"
        if not context_path.exists():
            report: dict[str, Any] = {
                "run_date": resolved_date,
                "generated_at": _now_iso(),
                "source_page": getattr(self._result_provider, "source_page", "unknown"),
                "results": {},
                "graded_legs": [],
                "plan_summaries": [],
                "message": (
                    f"【Nutmeg｜{resolved_date} 竞彩足球赛后复盘】\n"
                    f"未找到赛前上下文：{context_path}"
                ),
                "artifacts": {},
                "dispatch": {"status": "skipped"},
                "betting_db": {"status": "skipped"},
                "warnings": [f"missing context: {context_path}"],
            }
            report = self._write_artifacts(report, out)
            if dispatch_telegram:
                report["dispatch"] = self._dispatch(report["message"], dry_run=dry_run)
                self._rewrite_json(report)
            return report

        context = _report_from_dict(json.loads(context_path.read_text(encoding="utf-8")))
        results = self._result_provider.fetch_results(resolved_date)
        context_payload = context.to_dict()
        graded_legs = _grade_legs(context_payload["plans"], results)
        graded_legs = enrich_graded_legs(
            graded_legs,
            matches=context_payload.get("matches") or [],
            results=results,
        )
        plan_summaries = _summarize_plans(context_payload["plans"], graded_legs)
        betting_db = self._record_betting_review(
            context_payload,
            results=results,
            review_date=_today_iso(),
        )
        strategy_memory = update_strategy_memory(
            output_dir=out,
            run_date=resolved_date,
            context=context_payload,
            results=results,
            graded_legs=graded_legs,
            plan_summaries=plan_summaries,
        )
        message = self._render_message(
            run_date=resolved_date,
            context=context_payload,
            results=results,
            graded_legs=graded_legs,
            plan_summaries=plan_summaries,
            strategy_memory=strategy_memory,
            betting_db=betting_db,
        )
        explanations = explain_missed_plans(
            plan_reviews=betting_db.get("plan_reviews") or [],
            results=results,
            completer=self._explanation_completer,
        )
        report = {
            "run_date": resolved_date,
            "generated_at": _now_iso(),
            "source_page": getattr(self._result_provider, "source_page", "unknown"),
            "results": results,
            "graded_legs": graded_legs,
            "plan_summaries": plan_summaries,
            "strategy_memory": {
                "path": str(out / "memory" / "strategy-memory.json"),
                "insights": strategy_memory.get("insights") or [],
                "decision_policy": strategy_memory.get("decision_policy") or {},
                "pattern_buckets_count": len(strategy_memory.get("pattern_buckets") or {}),
                "oracle_learnings_count": len(strategy_memory.get("oracle_learnings") or []),
            },
            "explanations": [
                {
                    "plan_kind": item.plan_kind,
                    "plan_name": item.plan_name,
                    "miss_reason": item.miss_reason,
                    "killer_legs": list(item.killer_legs),
                    "oracle_pick_diffs": list(item.oracle_pick_diffs),
                    "extracted_rules": list(item.extracted_rules),
                    "narrative": item.narrative,
                }
                for item in explanations
            ],
            "betting_db": betting_db,
            "message": message,
            "artifacts": {},
            "dispatch": {"status": "skipped"},
            "warnings": [],
        }
        report = self._write_artifacts(report, out)
        if dispatch_telegram:
            report["dispatch"] = self._dispatch(message, dry_run=dry_run)
            self._rewrite_json(report)
        return report

    def _record_betting_review(
        self,
        context: dict[str, Any],
        *,
        results: dict[str, dict[str, str]],
        review_date: str,
    ) -> dict[str, Any]:
        if self._betting_repository is None:
            return {"status": "skipped"}
        plan_reviews = self._betting_repository.record_jczq_review(
            context,
            results=results,
            review_date=review_date,
        )
        return {
            "status": "recorded",
            "run_id": f"jczq:{context.get('run_date')}:final",
            "plan_reviews": plan_reviews,
        }

    def _render_message(
        self,
        *,
        run_date: str,
        context: dict[str, Any],
        results: dict[str, dict[str, str]],
        graded_legs: list[dict[str, Any]],
        plan_summaries: list[dict[str, Any]],
        strategy_memory: dict[str, Any] | None = None,
        betting_db: dict[str, Any] | None = None,
    ) -> str:
        lines = [
            f"【Nutmeg｜{run_date} 竞彩足球赛后复盘】",
            "仅做赛后回测和策略校准，不代表任何稳定收益或保证命中。",
            "",
            "最终赛果：",
        ]
        for match in context.get("matches") or []:
            result = results.get(match.get("match_no") or "") or {}
            if not result:
                continue
            lines.append(
                f"- {match['match_no']} {match['home_team']} vs {match['away_team']}："
                f"{result.get('score', '未知')}，半场{result.get('half_score', '未知')}，"
                f"胜平负{result.get('had', '未知')}"
            )
        lines.extend(["", "方案回测："])
        for summary in plan_summaries:
            lines.append(
                f"- {summary['name']}：{summary['hits']}/{summary['total']} 命中；"
                f"{'整票命中' if summary['all_hit'] else '整票未中'}"
            )
        plan_reviews = (betting_db or {}).get("plan_reviews") or []
        if plan_reviews:
            lines.extend(["", "赔率回测（同场次同玩法改正确）："])
            for review in plan_reviews:
                lines.append(
                    f"- {review.get('plan_name') or review.get('plan_id')}："
                    f"同玩法正确赔率{review['oracle_same_play_odds']:.2f}倍；"
                    f"2元理论返奖{review['oracle_return_yuan']:.2f}元"
                )
        lines.extend(["", "关键策略校准："])
        if any(
            item["match_no"].endswith("003")
            and item["pool"] == "hafu"
            and item["pick"] == "平/负"
            and item["hit"]
            for item in graded_legs
        ):
            lines.append("- 003修正为平/负命中：用户修正信号应进入最终排序，而不是只作为备注。")
        comfort_matches = [
            match
            for match in context.get("matches") or []
            if "舒服盘" in str(match.get("confidence_note") or "")
        ]
        for match in comfort_matches:
            actual = (results.get(match.get("match_no") or "") or {}).get("had")
            favorite = _favorite_from_hot_direction(str(match.get("hot_direction") or ""))
            if favorite in {"胜", "负"} and actual in {"胜", "平", "负"} and actual != favorite:
                lines.append(
                    f"- {match['match_no']}舒服盘风险兑现：实际{actual}，后续必须防平防冷，"
                    "不能让同一热门假设拖累多张串。"
                )
        if not comfort_matches:
            lines.append("- 舒服盘审问继续保留：1.75-2.05的非强胆热门不能作为隐形胆。")
        lines.append("- 强胆场优先考虑胜/让胜/总进球表达；变量场优先防平，舒服盘同步防冷。")
        if strategy_memory:
            insights = strategy_memory.get("insights") or []
            if insights:
                lines.extend(["", "策略记忆已更新："])
                lines.extend(f"- {item}" for item in insights[:3])
            policy_notes = render_decision_policy_notes(strategy_memory)
            if policy_notes:
                lines.extend(["", "策略迭代规则："])
                lines.extend(f"- {item}" for item in policy_notes)
        return "\n".join(lines)

    def _write_artifacts(self, report: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        run_dir = output_dir / "daily" / str(report["run_date"])
        run_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = run_dir / "review.md"
        json_path = run_dir / "review.json"
        report["artifacts"] = {"markdown_path": str(markdown_path), "json_path": str(json_path)}
        markdown_path.write_text(str(report["message"]), encoding="utf-8")
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        latest_path = output_dir / "latest-review-result.json"
        latest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    def _rewrite_json(self, report: dict[str, Any]) -> None:
        json_path = report.get("artifacts", {}).get("json_path")
        if json_path:
            Path(str(json_path)).write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def _dispatch(self, message: str, *, dry_run: bool) -> dict[str, Any]:
        if dry_run:
            return {"status": "dry_run", "chat_ids": list(self._telegram_chat_ids)}
        if self._telegram_sender is None or not self._telegram_chat_ids:
            return {
                "status": "skipped",
                "chat_ids": list(self._telegram_chat_ids),
                "error": "telegram not configured",
            }
        try:
            chunks = _telegram_chunks(message)
            for chat_id in self._telegram_chat_ids:
                for chunk in chunks:
                    self._telegram_sender.send_message(chat_id=chat_id, text=chunk)
        except Exception as exc:  # pragma: no cover - defensive network seam
            return {
                "status": "failed",
                "chat_ids": list(self._telegram_chat_ids),
                "error": str(exc),
            }
        return {"status": "sent", "chat_ids": list(self._telegram_chat_ids)}


def _grade_legs(
    plans: list[dict[str, Any]], results: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    graded: list[dict[str, Any]] = []
    for plan in plans:
        for leg in plan.get("legs") or []:
            actual = (results.get(leg.get("match_no") or "") or {}).get(leg.get("pool") or "")
            actual_odds = (results.get(leg.get("match_no") or "") or {}).get(
                f"{leg.get('pool')}_odds"
            )
            hit = actual == leg.get("pick") if actual is not None else None
            graded.append(
                {
                    "plan_kind": plan.get("kind"),
                    "plan_name": plan.get("name"),
                    "match_no": leg.get("match_no"),
                    "league": leg.get("league"),
                    "home_team": leg.get("home_team"),
                    "away_team": leg.get("away_team"),
                    "pool": leg.get("pool"),
                    "play": leg.get("play"),
                    "pick": leg.get("pick"),
                    "odds": leg.get("odds"),
                    "actual": actual,
                    "actual_odds": actual_odds,
                    "hit": hit,
                }
            )
    return graded


# R8 (5/08 落库): narrative tagging mirrors jczq_diagnostics.classify_leg
# semantics so per-leg narrative ROI becomes computable across days.
_HIGH_GOAL_PICKS: frozenset[str] = frozenset({"3球", "4球", "5球", "6球", "7+球"})
_LOW_GOAL_PICKS: frozenset[str] = frozenset({"0球", "1球", "2球"})


def _classify_leg_narrative(pool: str, pick: str) -> str:
    """Map a (pool, pick) to a coarse narrative bucket for ROI analysis."""

    if pool == "crs":
        return "score_picks"
    if pool == "hafu":
        return "hafu"
    if pool == "ttg":
        if pick in _LOW_GOAL_PICKS:
            return "low_goals"
        if pick in _HIGH_GOAL_PICKS:
            return "high_goals"
        return "other"
    if pool in {"had", "hhad"}:
        if pick in {"平", "让平"}:
            return "draw"
        if pick in {"负", "让负"}:
            return "cold_reverse"
        if pick in {"胜", "让胜"}:
            return "chalk_favorite"
    return "other"


def _realized_goals_from_score(score: str | None) -> int | None:
    """Parse '2:1' / '0:0' → 3 / 0; return None on parse failure."""

    if not score:
        return None
    try:
        home, away = score.split(":")
        return int(home.strip()) + int(away.strip())
    except (ValueError, AttributeError):
        return None


def _fit_poisson_for_match(
    match: dict[str, Any],
):
    """Fit Poisson lambdas from a context match's had odds. Returns None
    when had pool is incomplete (rare, but happens for pre-sale matches).
    """

    from nutmeg.services.jczq_poisson import fit_lambdas_from_market

    candidates = match.get("candidates") or []
    had = {
        leg["pick"]: float(leg["odds"])
        for leg in candidates
        if leg.get("pool") == "had" and leg.get("odds")
    }
    if not all(pick in had for pick in ("胜", "平", "负")):
        return None
    try:
        return fit_lambdas_from_market(
            had["胜"], had["平"], had["负"], max_lambda=3.5, step=0.1
        )
    except Exception:  # pragma: no cover - defensive against degenerate odds
        return None


def enrich_graded_legs(
    graded_legs: list[dict[str, Any]],
    *,
    matches: list[dict[str, Any]],
    results: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """Annotate each graded leg with R8 fields:

    - `narrative_tag`: coarse bucket (low_goals / draw / chalk_favorite / ...)
    - `expected_edge`: Poisson model edge at the time of generation,
      recomputed from context's had odds. None for hhad (no Poisson price).
    - `expected_goals`: home_lambda + away_lambda from the Poisson fit.
    - `realized_goals`: total goals scored from results['score'] when known.
    - `goal_residual`: realized - expected (positive = model under-priced
      goals; this is the signal R1's λ-calibration loop consumes).

    Pure function: no I/O. Returns a new list; input is not mutated.
    """

    from nutmeg.services.jczq_poisson import edge_vs_market

    match_index = {str(m.get("match_no") or ""): m for m in matches}
    fit_cache: dict[str, Any] = {}

    out: list[dict[str, Any]] = []
    for leg in graded_legs:
        match_no = str(leg.get("match_no") or "")
        pool = str(leg.get("pool") or "")
        pick = str(leg.get("pick") or "")
        odds_value = leg.get("odds")
        try:
            odds = float(odds_value) if odds_value is not None else None
        except (TypeError, ValueError):
            odds = None

        match = match_index.get(match_no)
        if match_no not in fit_cache:
            fit_cache[match_no] = _fit_poisson_for_match(match) if match else None
        fit = fit_cache[match_no]

        expected_edge: float | None = None
        if fit is not None and odds is not None and pool != "hhad":
            expected_edge = edge_vs_market(fit, pool=pool, pick=pick, market_odd=odds)

        expected_goals: float | None = None
        if fit is not None:
            expected_goals = round(float(fit.home_lambda) + float(fit.away_lambda), 2)

        realized_goals = _realized_goals_from_score((results.get(match_no) or {}).get("score"))

        goal_residual: float | None = None
        if expected_goals is not None and realized_goals is not None:
            goal_residual = round(realized_goals - expected_goals, 2)

        enriched = dict(leg)
        enriched["narrative_tag"] = _classify_leg_narrative(pool, pick)
        enriched["expected_edge"] = expected_edge
        enriched["expected_goals"] = expected_goals
        enriched["realized_goals"] = realized_goals
        enriched["goal_residual"] = goal_residual
        out.append(enriched)
    return out


def _summarize_plans(
    plans: list[dict[str, Any]], graded_legs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    summaries = []
    for plan in plans:
        plan_items = [item for item in graded_legs if item.get("plan_kind") == plan.get("kind")]
        hits = sum(1 for item in plan_items if item.get("hit") is True)
        total = len(plan_items)
        summaries.append(
            {
                "kind": plan.get("kind"),
                "name": plan.get("name"),
                "hits": hits,
                "total": total,
                "misses": sum(1 for item in plan_items if item.get("hit") is False),
                "pending": sum(1 for item in plan_items if item.get("hit") is None),
                "all_hit": bool(total and hits == total),
                "total_odds": plan.get("total_odds"),
            }
        )
    return summaries


def _parse_result_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.S | re.I):
        cells = [
            _clean_html(cell)
            for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, flags=re.S | re.I)
        ]
        if cells and cells[0].isdigit():
            rows.append(cells)
    return rows


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    return " ".join(unescape(text).split())


def _parse_score_cell(value: str) -> tuple[str, str]:
    score_match = re.search(r"(\d+\s*:\s*\d+)", value)
    half_match = re.search(r"半场\s*(\d+\s*:\s*\d+)", value)
    score = score_match.group(1).replace(" ", "") if score_match else ""
    half_score = half_match.group(1).replace(" ", "") if half_match else ""
    return score, half_score


def _parse_pool_result(pool: str, value: str) -> str:
    return _parse_pool_result_and_odds(pool, value)[0]


def _parse_pool_result_and_odds(pool: str, value: str) -> tuple[str, float | None]:
    token = value.split()[0] if value.split() else value.strip()
    odds = None
    for part in value.split()[1:]:
        try:
            odds = float(part)
            break
        except ValueError:
            continue
    if pool == "had":
        return {"主": "胜", "平": "平", "客": "负"}.get(token, token), odds
    if pool == "hhad":
        return {"主": "让胜", "平": "让平", "客": "让负"}.get(token, token), odds
    if pool == "hafu":
        parts = token.split("-")
        label = {"3": "胜", "1": "平", "0": "负"}
        if len(parts) == 2:
            return f"{label.get(parts[0], parts[0])}/{label.get(parts[1], parts[1])}", odds
    return token, odds


def _favorite_from_hot_direction(value: str) -> str | None:
    if "主胜" in value:
        return "胜"
    if "客胜" in value:
        return "负"
    if "平局" in value:
        return "平"
    return None


def _weekday_prefix(value: str) -> str:
    day = date.fromisoformat(value)
    return ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][day.weekday()]


def _normalize_review_date(value: str | None) -> str:
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if value is None or value == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    if value == "today":
        return today.isoformat()
    return value


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0).isoformat()


def _today_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def _telegram_chunks(message: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    for paragraph in message.split("\n\n"):
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) > 3500:
            if current:
                chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [message]
