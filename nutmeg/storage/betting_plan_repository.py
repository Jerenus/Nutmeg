from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from nutmeg.config.settings import AppSettings
from nutmeg.storage.duckdb_utils import connect_analytics_db


class DuckDbBettingPlanRepository:
    def __init__(self, settings: AppSettings) -> None:
        self._db_path = settings.analytics_db_path

    def record_jczq_report(self, report: Any) -> dict[str, Any]:
        payload = _to_payload(report)
        run_date = str(payload.get("run_date") or "")
        run_id = f"jczq:{run_date}:final"
        finalized_at = _parse_datetime(payload.get("generated_at"))
        artifacts = payload.get("artifacts") or {}
        artifact_path = artifacts.get("context_path") or artifacts.get("report_json_path")
        plans = list(payload.get("plans") or [])

        with connect_analytics_db(self._db_path) as connection:
            _delete_run(connection, run_id)
            connection.execute(
                """
                INSERT INTO betting_plan_runs (
                    run_id,
                    run_date,
                    game_type,
                    source,
                    strategy_version,
                    finalized_at,
                    artifact_path,
                    notes,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    run_id,
                    run_date,
                    "jczq",
                    "jczq-daily-advisor",
                    str((payload.get("revision") or {}).get("version") or "1"),
                    _to_storage_datetime(finalized_at),
                    str(artifact_path) if artifact_path else None,
                    str(payload.get("summary") or ""),
                    json.dumps(payload, ensure_ascii=False, default=str),
                ],
            )
            self._insert_plans(connection, run_id=run_id, plans=plans)
        return {"run_id": run_id, "plan_count": len(plans)}

    def record_zucai_report(self, report: Any) -> dict[str, Any]:
        payload = _to_payload(report)
        issue = payload.get("issue") or {}
        issue_id = str(issue.get("issue_id") or "")
        run_date = str(issue.get("draw_date") or issue.get("sale_stop") or issue_id)
        run_id = f"zucai:{issue_id}:final"
        finalized_at = _parse_datetime(payload.get("generated_at"))
        artifacts = payload.get("artifacts") or {}
        artifact_path = artifacts.get("report_json_path") or artifacts.get("markdown_path")
        plans = _zucai_plans_as_generic(payload)

        with connect_analytics_db(self._db_path) as connection:
            _delete_run(connection, run_id)
            connection.execute(
                """
                INSERT INTO betting_plan_runs (
                    run_id,
                    run_date,
                    game_type,
                    source,
                    strategy_version,
                    finalized_at,
                    artifact_path,
                    notes,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    run_id,
                    run_date,
                    "zucai",
                    "zucai-report",
                    "1",
                    _to_storage_datetime(finalized_at),
                    str(artifact_path) if artifact_path else None,
                    f"issue={issue_id}",
                    json.dumps(payload, ensure_ascii=False, default=str),
                ],
            )
            self._insert_plans(connection, run_id=run_id, plans=plans)
        return {"run_id": run_id, "plan_count": len(plans)}

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with connect_analytics_db(self._db_path) as connection:
            row = connection.execute(
                """
                SELECT
                    run_id,
                    run_date,
                    game_type,
                    source,
                    strategy_version,
                    finalized_at,
                    artifact_path,
                    notes
                FROM betting_plan_runs
                WHERE run_id = ?
                """,
                [run_id],
            ).fetchone()
            if row is None:
                return None
            plan_rows = connection.execute(
                """
                SELECT
                    plan_id,
                    plan_index,
                    name,
                    role,
                    strategy_kind,
                    target_odds_band,
                    total_odds,
                    stake_yuan,
                    expected_return_yuan,
                    risk_tier,
                    notes
                FROM betting_plans
                WHERE run_id = ?
                ORDER BY plan_index
                """,
                [run_id],
            ).fetchall()
            plans = []
            for plan in plan_rows:
                leg_rows = connection.execute(
                    """
                    SELECT
                        leg_index,
                        match_no,
                        league,
                        home_team,
                        away_team,
                        pool,
                        play,
                        pick,
                        odds,
                        goal_line,
                        logic,
                        odds_update
                    FROM betting_plan_legs
                    WHERE plan_id = ?
                    ORDER BY leg_index
                    """,
                    [plan[0]],
                ).fetchall()
                plans.append(
                    {
                        "plan_id": str(plan[0]),
                        "plan_index": int(plan[1]),
                        "name": str(plan[2]),
                        "role": str(plan[3]),
                        "strategy_kind": str(plan[4]),
                        "target_odds_band": plan[5],
                        "total_odds": _float_or_none(plan[6]),
                        "stake_yuan": _float_or_none(plan[7]),
                        "expected_return_yuan": _float_or_none(plan[8]),
                        "risk_tier": plan[9],
                        "notes": plan[10],
                        "legs": [_leg_row_to_dict(item) for item in leg_rows],
                    }
                )
        return {
            "run_id": str(row[0]),
            "run_date": str(row[1]),
            "game_type": str(row[2]),
            "source": str(row[3]),
            "strategy_version": str(row[4]),
            "finalized_at": _from_storage_datetime(row[5]).isoformat(),
            "artifact_path": row[6],
            "notes": row[7],
            "plans": plans,
        }

    def record_jczq_review(
        self,
        report: Any,
        *,
        results: dict[str, dict[str, Any]],
        review_date: str,
    ) -> list[dict[str, Any]]:
        payload = _to_payload(report)
        run_date = str(payload.get("run_date") or "")
        run_id = f"jczq:{run_date}:final"
        if self.get_run(run_id) is None:
            self.record_jczq_report(payload)

        reviews = _build_jczq_reviews(run_id, payload, results=results, review_date=review_date)
        with connect_analytics_db(self._db_path) as connection:
            connection.execute(
                """
                DELETE FROM betting_leg_reviews
                WHERE plan_id IN (SELECT plan_id FROM betting_plans WHERE run_id = ?)
                """,
                [run_id],
            )
            connection.execute(
                """
                DELETE FROM betting_plan_reviews
                WHERE plan_id IN (SELECT plan_id FROM betting_plans WHERE run_id = ?)
                """,
                [run_id],
            )
            for review in reviews:
                connection.execute(
                    """
                    INSERT INTO betting_plan_reviews (
                        review_id,
                        plan_id,
                        review_date,
                        hit_count,
                        leg_count,
                        all_hit,
                        settled_odds,
                        original_return_yuan,
                        oracle_same_play_odds,
                        oracle_return_yuan,
                        miss_reason,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        review["review_id"],
                        review["plan_id"],
                        review_date,
                        review["hit_count"],
                        review["leg_count"],
                        review["all_hit"],
                        review["settled_odds"],
                        review["original_return_yuan"],
                        review["oracle_same_play_odds"],
                        review["oracle_return_yuan"],
                        review["miss_reason"],
                        _to_storage_datetime(datetime.now(UTC)),
                    ],
                )
                for leg in review["legs"]:
                    connection.execute(
                        """
                        INSERT INTO betting_leg_reviews (
                            review_id,
                            plan_id,
                            leg_index,
                            match_no,
                            pool,
                            pick,
                            actual_pick,
                            hit,
                            original_odds,
                            actual_odds,
                            score,
                            half_score
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            review["review_id"],
                            review["plan_id"],
                            leg["leg_index"],
                            leg["match_no"],
                            leg["pool"],
                            leg["pick"],
                            leg["actual_pick"],
                            leg["hit"],
                            leg["original_odds"],
                            leg["actual_odds"],
                            leg["score"],
                            leg["half_score"],
                        ],
                    )
        return reviews

    def record_zucai_grade(
        self,
        report: Any,
        grade: Any,
        *,
        review_date: str,
    ) -> list[dict[str, Any]]:
        report_payload = _to_payload(report)
        grade_payload = _to_payload(grade)
        issue_id = str(
            report_payload.get("issue", {}).get("issue_id") or grade_payload.get("issue_id") or ""
        )
        run_id = f"zucai:{issue_id}:final"
        if self.get_run(run_id) is None:
            self.record_zucai_report(report_payload)

        reviews = _build_zucai_reviews(run_id, report_payload, grade_payload, review_date)
        with connect_analytics_db(self._db_path) as connection:
            connection.execute(
                """
                DELETE FROM betting_leg_reviews
                WHERE plan_id IN (SELECT plan_id FROM betting_plans WHERE run_id = ?)
                """,
                [run_id],
            )
            connection.execute(
                """
                DELETE FROM betting_plan_reviews
                WHERE plan_id IN (SELECT plan_id FROM betting_plans WHERE run_id = ?)
                """,
                [run_id],
            )
            for review in reviews:
                connection.execute(
                    """
                    INSERT INTO betting_plan_reviews (
                        review_id,
                        plan_id,
                        review_date,
                        hit_count,
                        leg_count,
                        all_hit,
                        settled_odds,
                        original_return_yuan,
                        oracle_same_play_odds,
                        oracle_return_yuan,
                        miss_reason,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        review["review_id"],
                        review["plan_id"],
                        review_date,
                        review["hit_count"],
                        review["leg_count"],
                        review["all_hit"],
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        review["miss_reason"],
                        _to_storage_datetime(datetime.now(UTC)),
                    ],
                )
                for leg in review["legs"]:
                    connection.execute(
                        """
                        INSERT INTO betting_leg_reviews (
                            review_id,
                            plan_id,
                            leg_index,
                            match_no,
                            pool,
                            pick,
                            actual_pick,
                            hit,
                            original_odds,
                            actual_odds,
                            score,
                            half_score
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            review["review_id"],
                            review["plan_id"],
                            leg["leg_index"],
                            leg["match_no"],
                            "sfc14",
                            leg["pick"],
                            leg["actual_pick"],
                            leg["hit"],
                            None,
                            None,
                            "",
                            "",
                        ],
                    )
        return reviews

    def list_plan_reviews(self, run_id: str) -> list[dict[str, Any]]:
        with connect_analytics_db(self._db_path) as connection:
            rows = connection.execute(
                """
                SELECT
                    review_id,
                    plan_id,
                    review_date,
                    hit_count,
                    leg_count,
                    all_hit,
                    settled_odds,
                    original_return_yuan,
                    oracle_same_play_odds,
                    oracle_return_yuan,
                    miss_reason
                FROM betting_plan_reviews
                WHERE plan_id IN (SELECT plan_id FROM betting_plans WHERE run_id = ?)
                ORDER BY plan_id
                """,
                [run_id],
            ).fetchall()
            reviews = []
            for row in rows:
                leg_rows = connection.execute(
                    """
                    SELECT
                        leg_index,
                        match_no,
                        pool,
                        pick,
                        actual_pick,
                        hit,
                        original_odds,
                        actual_odds,
                        score,
                        half_score
                    FROM betting_leg_reviews
                    WHERE review_id = ?
                    ORDER BY leg_index
                    """,
                    [row[0]],
                ).fetchall()
                reviews.append(
                    {
                        "review_id": str(row[0]),
                        "plan_id": str(row[1]),
                        "review_date": str(row[2]),
                        "hit_count": int(row[3]),
                        "leg_count": int(row[4]),
                        "all_hit": bool(row[5]),
                        "settled_odds": _float_or_zero(row[6]),
                        "original_return_yuan": _float_or_zero(row[7]),
                        "oracle_same_play_odds": _float_or_zero(row[8]),
                        "oracle_return_yuan": _float_or_zero(row[9]),
                        "miss_reason": str(row[10] or ""),
                        "legs": [
                            {
                                "leg_index": int(leg[0]),
                                "match_no": str(leg[1]),
                                "pool": str(leg[2] or ""),
                                "pick": str(leg[3] or ""),
                                "actual_pick": str(leg[4] or ""),
                                "hit": bool(leg[5]) if leg[5] is not None else None,
                                "original_odds": _float_or_none(leg[6]),
                                "actual_odds": _float_or_none(leg[7]),
                                "score": str(leg[8] or ""),
                                "half_score": str(leg[9] or ""),
                            }
                            for leg in leg_rows
                        ],
                    }
                )
        return reviews

    def _insert_plans(self, connection: Any, *, run_id: str, plans: list[dict[str, Any]]) -> None:
        for plan_index, plan in enumerate(plans, start=1):
            kind = str(plan.get("kind") or plan.get("plan_type") or "plan")
            plan_id = f"{run_id}:plan:{plan_index}:{_slug(kind)}"
            role = _plan_role(plan)
            total_odds = _float_or_none(plan.get("total_odds"))
            stake_yuan = _float_or_none(plan.get("stake_yuan")) or 2.0
            expected_return = _float_or_none(plan.get("two_yuan_return")) or (
                round(total_odds * stake_yuan, 2) if total_odds is not None else None
            )
            connection.execute(
                """
                INSERT INTO betting_plans (
                    plan_id,
                    run_id,
                    plan_index,
                    name,
                    role,
                    strategy_kind,
                    target_odds_band,
                    total_odds,
                    stake_yuan,
                    expected_return_yuan,
                    risk_tier,
                    notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    plan_id,
                    run_id,
                    plan_index,
                    str(plan.get("name") or f"plan-{plan_index}"),
                    role,
                    kind,
                    _target_odds_band(total_odds, role=role),
                    total_odds,
                    stake_yuan,
                    expected_return,
                    str(plan.get("risk_tier") or role),
                    str(plan.get("risk_note") or plan.get("note") or plan.get("description") or ""),
                ],
            )
            for leg_index, leg in enumerate(plan.get("legs") or [], start=1):
                connection.execute(
                    """
                    INSERT INTO betting_plan_legs (
                        plan_id,
                        leg_index,
                        match_no,
                        league,
                        home_team,
                        away_team,
                        pool,
                        play,
                        pick,
                        odds,
                        goal_line,
                        logic,
                        odds_update
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        plan_id,
                        leg_index,
                        str(leg.get("match_no") or ""),
                        str(leg.get("league") or ""),
                        str(leg.get("home_team") or ""),
                        str(leg.get("away_team") or ""),
                        str(leg.get("pool") or ""),
                        str(leg.get("play") or ""),
                        str(leg.get("pick") or ""),
                        _float_or_none(leg.get("odds")),
                        str(leg.get("goal_line") or ""),
                        str(leg.get("logic") or ""),
                        str(leg.get("odds_update") or ""),
                    ],
                )


def _delete_run(connection: Any, run_id: str) -> None:
    connection.execute(
        """
        DELETE FROM betting_leg_reviews
        WHERE plan_id IN (SELECT plan_id FROM betting_plans WHERE run_id = ?)
        """,
        [run_id],
    )
    connection.execute(
        """
        DELETE FROM betting_plan_reviews
        WHERE plan_id IN (SELECT plan_id FROM betting_plans WHERE run_id = ?)
        """,
        [run_id],
    )
    connection.execute(
        """
        DELETE FROM betting_plan_legs
        WHERE plan_id IN (SELECT plan_id FROM betting_plans WHERE run_id = ?)
        """,
        [run_id],
    )
    connection.execute("DELETE FROM betting_plans WHERE run_id = ?", [run_id])
    connection.execute("DELETE FROM betting_plan_runs WHERE run_id = ?", [run_id])


def _to_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return dict(value)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value:
        text = str(value)
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _to_storage_datetime(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _from_storage_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC)


def _float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_zero(value: Any) -> float:
    parsed = _float_or_none(value)
    return 0.0 if parsed is None else parsed


def _leg_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "leg_index": int(row[0]),
        "match_no": str(row[1]),
        "league": str(row[2] or ""),
        "home_team": str(row[3] or ""),
        "away_team": str(row[4] or ""),
        "pool": str(row[5] or ""),
        "play": str(row[6] or ""),
        "pick": str(row[7] or ""),
        "odds": _float_or_none(row[8]),
        "goal_line": str(row[9] or ""),
        "logic": str(row[10] or ""),
        "odds_update": str(row[11] or ""),
    }


def _slug(value: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in value.lower()).strip("-")
    return slug or "plan"


def _plan_role(plan: dict[str, Any]) -> str:
    kind = str(plan.get("kind") or plan.get("plan_type") or "").casefold()
    name = str(plan.get("name") or "")
    if kind in {"stable_base", "stable"} or "稳健" in name or "主攻" in name:
        return "stable_base"
    if kind in {"balanced", "balance"} or "变量" in name:
        return "balanced"
    if kind in {"extreme"} or "极限" in name:
        return "extreme"
    if kind in {"inspiration", "contrarian", "false_signal", "opportunity"}:
        return "opportunity"
    if kind == "main":
        return "stable_base"
    if "冷门" in name or "机会" in name:
        return "opportunity"
    return "balanced"


def _target_odds_band(total_odds: float | None, *, role: str) -> str:
    if total_odds is None:
        return role
    if total_odds < 25:
        return "8-25"
    if total_odds < 80:
        return "25-80"
    if total_odds < 250:
        return "80-250"
    if total_odds < 500:
        return "250-500"
    return "500+"


def _build_jczq_reviews(
    run_id: str,
    payload: dict[str, Any],
    *,
    results: dict[str, dict[str, Any]],
    review_date: str,
) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for plan_index, plan in enumerate(payload.get("plans") or [], start=1):
        kind = str(plan.get("kind") or "plan")
        plan_id = f"{run_id}:plan:{plan_index}:{_slug(kind)}"
        hit_count = 0
        leg_count = 0
        oracle_product = 1.0
        oracle_complete = True
        leg_reviews = []
        misses = []
        for leg_index, leg in enumerate(plan.get("legs") or [], start=1):
            leg_count += 1
            match_no = str(leg.get("match_no") or "")
            pool = str(leg.get("pool") or "")
            result = results.get(match_no) or {}
            actual_pick = result.get(pool)
            actual_odds = _float_or_none(result.get(f"{pool}_odds"))
            hit = actual_pick == leg.get("pick") if actual_pick is not None else None
            if hit is True:
                hit_count += 1
            elif hit is False:
                misses.append(f"{match_no}{pool}{leg.get('pick')}->{actual_pick}")
            if actual_odds is None:
                oracle_complete = False
            else:
                oracle_product *= actual_odds
            leg_reviews.append(
                {
                    "leg_index": leg_index,
                    "match_no": match_no,
                    "pool": pool,
                    "pick": str(leg.get("pick") or ""),
                    "actual_pick": str(actual_pick or ""),
                    "hit": hit,
                    "original_odds": _float_or_none(leg.get("odds")),
                    "actual_odds": actual_odds,
                    "score": str(result.get("score") or ""),
                    "half_score": str(result.get("half_score") or ""),
                }
            )
        all_hit = bool(leg_count and hit_count == leg_count)
        settled_odds = _float_or_none(plan.get("total_odds")) if all_hit else 0.0
        settled_odds = round(float(settled_odds or 0.0), 2)
        oracle_odds = round(oracle_product, 2) if oracle_complete and leg_count else 0.0
        reviews.append(
            {
                "review_id": f"{plan_id}:{review_date}",
                "plan_id": plan_id,
                "plan_name": str(plan.get("name") or ""),
                "hit_count": hit_count,
                "leg_count": leg_count,
                "all_hit": all_hit,
                "settled_odds": settled_odds,
                "original_return_yuan": round(settled_odds * 2, 2),
                "oracle_same_play_odds": oracle_odds,
                "oracle_return_yuan": round(oracle_odds * 2, 2),
                "miss_reason": "；".join(misses),
                "legs": leg_reviews,
            }
        )
    return reviews


def _build_zucai_reviews(
    run_id: str,
    report_payload: dict[str, Any],
    grade_payload: dict[str, Any],
    review_date: str,
) -> list[dict[str, Any]]:
    match_results = {
        int(item["match_no"]): item for item in (grade_payload.get("match_results") or [])
    }
    reviews: list[dict[str, Any]] = []
    for plan_index, plan in enumerate(report_payload.get("plans") or [], start=1):
        kind = str(plan.get("plan_type") or "plan")
        plan_id = f"{run_id}:plan:{plan_index}:{_slug(kind)}"
        legs = []
        misses = []
        hit_count = 0
        for leg_index, token in enumerate(str(plan.get("code") or "").split(), start=1):
            if token == "-":
                continue
            result = match_results.get(leg_index) or {}
            actual = result.get("result")
            hit = bool(actual and str(actual) in token)
            if hit:
                hit_count += 1
            else:
                misses.append(f"{leg_index}{token}->{actual or '未开奖'}")
            legs.append(
                {
                    "leg_index": leg_index,
                    "match_no": str(leg_index),
                    "pick": token,
                    "actual_pick": str(actual or ""),
                    "hit": hit,
                }
            )
        leg_count = len(legs)
        all_hit = bool(leg_count and hit_count == leg_count)
        review_id = f"{plan_id}:{review_date}"
        reviews.append(
            {
                "review_id": review_id,
                "plan_id": plan_id,
                "plan_name": str(plan.get("name") or ""),
                "hit_count": hit_count,
                "leg_count": leg_count,
                "all_hit": all_hit,
                "miss_reason": "；".join(misses),
                "legs": legs,
            }
        )
    return reviews


def _zucai_plans_as_generic(payload: dict[str, Any]) -> list[dict[str, Any]]:
    issue_matches = {
        int(match.get("match_no")): match for match in (payload.get("issue", {}).get("matches") or [])
    }
    plans = []
    for plan in payload.get("plans") or []:
        legs = []
        for index, token in enumerate(str(plan.get("code") or "").split(), start=1):
            if token == "-":
                continue
            match = issue_matches.get(index) or {}
            legs.append(
                {
                    "match_no": str(index),
                    "league": str(match.get("competition") or ""),
                    "home_team": str(match.get("home_team") or ""),
                    "away_team": str(match.get("away_team") or ""),
                    "pool": "sfc14",
                    "play": "胜负彩",
                    "pick": token,
                    "odds": None,
                    "logic": str(plan.get("note") or ""),
                    "goal_line": "",
                    "odds_update": "",
                }
            )
        plans.append(
            {
                "name": plan.get("name"),
                "kind": plan.get("plan_type"),
                "risk_note": plan.get("note"),
                "stake_yuan": plan.get("cost_yuan"),
                "legs": legs,
            }
        )
    return plans
