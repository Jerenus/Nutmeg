from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class JczqWebRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jczq_days (
                    run_date TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    brief_path TEXT,
                    debate_dir TEXT,
                    current_version INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS jczq_matches (
                    run_date TEXT NOT NULL,
                    match_no TEXT NOT NULL,
                    league TEXT,
                    home_team TEXT,
                    away_team TEXT,
                    role TEXT,
                    goal_line REAL,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    flags_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (run_date, match_no)
                );
                CREATE TABLE IF NOT EXISTS jczq_candidate_legs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_date TEXT NOT NULL,
                    match_no TEXT NOT NULL,
                    pool TEXT NOT NULL,
                    play TEXT,
                    pick TEXT NOT NULL,
                    odds REAL NOT NULL,
                    poisson_edge REAL,
                    source TEXT,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    UNIQUE (run_date, match_no, pool, pick, source)
                );
                CREATE TABLE IF NOT EXISTS jczq_analyses (
                    run_date TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    content TEXT NOT NULL,
                    artifact_path TEXT,
                    brief_hash TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (run_date, agent)
                );
                CREATE TABLE IF NOT EXISTS jczq_ticket_versions (
                    run_date TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    best_pick TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (run_date, version)
                );
                CREATE TABLE IF NOT EXISTS jczq_tickets (
                    run_date TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    ticket_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    name TEXT,
                    stake REAL NOT NULL,
                    total_odds REAL NOT NULL,
                    theoretical_return REAL NOT NULL,
                    is_best_pick INTEGER NOT NULL DEFAULT 0,
                    is_extra_budget INTEGER NOT NULL DEFAULT 0,
                    rationale TEXT,
                    PRIMARY KEY (run_date, version, ticket_id)
                );
                CREATE TABLE IF NOT EXISTS jczq_ticket_legs (
                    run_date TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    ticket_id TEXT NOT NULL,
                    leg_index INTEGER NOT NULL,
                    match_no TEXT NOT NULL,
                    league TEXT,
                    home_team TEXT,
                    away_team TEXT,
                    pool TEXT NOT NULL,
                    play TEXT,
                    pick TEXT NOT NULL,
                    odds REAL NOT NULL,
                    goal_line REAL,
                    poisson_edge REAL,
                    note TEXT,
                    PRIMARY KEY (run_date, version, ticket_id, leg_index)
                );
                CREATE TABLE IF NOT EXISTS jczq_validation_findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_date TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    severity TEXT NOT NULL,
                    ticket_id TEXT,
                    code TEXT NOT NULL,
                    message TEXT NOT NULL,
                    blocks_finalization INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS jczq_decision_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_date TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT,
                    detail TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS jczq_reviews (
                    run_date TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    ticket_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    actual_return REAL,
                    profit_loss REAL,
                    failed_leg TEXT,
                    notes TEXT,
                    PRIMARY KEY (run_date, version, ticket_id)
                );
                CREATE TABLE IF NOT EXISTS jczq_leg_reviews (
                    run_date TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    ticket_id TEXT NOT NULL,
                    leg_index INTEGER NOT NULL,
                    match_no TEXT NOT NULL,
                    pool TEXT NOT NULL,
                    pick TEXT NOT NULL,
                    status TEXT NOT NULL,
                    actual_result TEXT,
                    notes TEXT,
                    PRIMARY KEY (run_date, version, ticket_id, leg_index)
                );
                """
            )

    def upsert_day(
        self,
        *,
        run_date: str,
        status: str,
        brief_path: str | None = None,
        debate_dir: str | None = None,
        current_version: int | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jczq_days (run_date, status, brief_path, debate_dir, current_version)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_date) DO UPDATE SET
                    status=excluded.status,
                    brief_path=COALESCE(excluded.brief_path, jczq_days.brief_path),
                    debate_dir=COALESCE(excluded.debate_dir, jczq_days.debate_dir),
                    current_version=COALESCE(excluded.current_version, jczq_days.current_version),
                    updated_at=CURRENT_TIMESTAMP
                """,
                (run_date, status, brief_path, debate_dir, current_version),
            )

    def get_day(self, run_date: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jczq_days WHERE run_date = ?",
                (run_date,),
            ).fetchone()
        return _row_dict(row) if row else None

    def list_days(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jczq_days ORDER BY run_date DESC").fetchall()
        return [_row_dict(row) for row in rows]

    def upsert_match(
        self,
        *,
        run_date: str,
        match_no: str,
        league: str,
        home_team: str,
        away_team: str,
        role: str,
        goal_line: float | int | None,
        tags: list[str] | None = None,
        flags: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jczq_matches (
                    run_date, match_no, league, home_team, away_team, role, goal_line,
                    tags_json, flags_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_date, match_no) DO UPDATE SET
                    league=excluded.league,
                    home_team=excluded.home_team,
                    away_team=excluded.away_team,
                    role=excluded.role,
                    goal_line=excluded.goal_line,
                    tags_json=excluded.tags_json,
                    flags_json=excluded.flags_json
                """,
                (
                    run_date,
                    match_no,
                    league,
                    home_team,
                    away_team,
                    role,
                    goal_line,
                    _json(tags or []),
                    _json(flags or {}),
                ),
            )

    def list_matches(self, run_date: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jczq_matches WHERE run_date = ? ORDER BY match_no",
                (run_date,),
            ).fetchall()
        return [_decode_json_fields(_row_dict(row), "tags_json", "flags_json") for row in rows]

    def upsert_candidate_leg(
        self,
        *,
        run_date: str,
        match_no: str,
        pool: str,
        play: str,
        pick: str,
        odds: float,
        poisson_edge: float | None = None,
        source: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jczq_candidate_legs (
                    run_date, match_no, pool, play, pick, odds, poisson_edge, source, tags_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_date, match_no, pool, pick, source) DO UPDATE SET
                    play=excluded.play,
                    odds=excluded.odds,
                    poisson_edge=excluded.poisson_edge,
                    tags_json=excluded.tags_json
                """,
                (
                    run_date,
                    match_no,
                    pool,
                    play,
                    pick,
                    odds,
                    poisson_edge,
                    source,
                    _json(tags or []),
                ),
            )

    def list_candidate_legs(self, run_date: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM jczq_candidate_legs
                WHERE run_date = ?
                ORDER BY match_no, pool, pick
                """,
                (run_date,),
            ).fetchall()
        return [_decode_json_fields(_row_dict(row), "tags_json") for row in rows]

    def save_analysis(
        self,
        *,
        run_date: str,
        agent: str,
        content: str,
        artifact_path: str | None = None,
        brief_hash: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jczq_analyses (run_date, agent, content, artifact_path, brief_hash)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_date, agent) DO UPDATE SET
                    content=excluded.content,
                    artifact_path=excluded.artifact_path,
                    brief_hash=excluded.brief_hash,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (run_date, agent, content, artifact_path, brief_hash),
            )

    def get_analysis(self, run_date: str, agent: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jczq_analyses WHERE run_date = ? AND agent = ?",
                (run_date, agent),
            ).fetchone()
        return _row_dict(row) if row else None

    def list_analyses(self, run_date: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jczq_analyses WHERE run_date = ? ORDER BY agent",
                (run_date,),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def create_ticket_version(
        self,
        *,
        run_date: str,
        source: str,
        status: str,
        best_pick: str | None = None,
    ) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM jczq_ticket_versions "
                "WHERE run_date = ?",
                (run_date,),
            ).fetchone()
            version = int(row["next_version"])
            conn.execute(
                """
                INSERT INTO jczq_ticket_versions (run_date, version, source, status, best_pick)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_date, version, source, status, best_pick),
            )
        return version

    def update_ticket_version_status(
        self,
        *,
        run_date: str,
        version: int,
        status: str,
        best_pick: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jczq_ticket_versions
                SET status = ?, best_pick = COALESCE(?, best_pick)
                WHERE run_date = ? AND version = ?
                """,
                (status, best_pick, run_date, version),
            )
            if status == "finalized":
                conn.execute(
                    "UPDATE jczq_days SET current_version = ?, status = ? WHERE run_date = ?",
                    (version, "finalized", run_date),
                )

    def replace_version_tickets(
        self,
        *,
        run_date: str,
        version: int,
        tickets: list[dict[str, Any]],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM jczq_ticket_legs WHERE run_date = ? AND version = ?",
                (run_date, version),
            )
            conn.execute(
                "DELETE FROM jczq_tickets WHERE run_date = ? AND version = ?",
                (run_date, version),
            )
            for ticket in tickets:
                total_odds = _ticket_total_odds(ticket)
                stake = float(ticket["stake"])
                conn.execute(
                    """
                    INSERT INTO jczq_tickets (
                        run_date, version, ticket_id, kind, name, stake, total_odds,
                        theoretical_return, is_best_pick, is_extra_budget, rationale
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_date,
                        version,
                        ticket["ticket_id"],
                        ticket["kind"],
                        ticket.get("name"),
                        stake,
                        total_odds,
                        round(total_odds * stake, 2),
                        int(bool(ticket.get("is_best_pick"))),
                        int(bool(ticket.get("is_extra_budget"))),
                        ticket.get("rationale"),
                    ),
                )
                for index, leg in enumerate(ticket.get("legs", []), start=1):
                    conn.execute(
                        """
                        INSERT INTO jczq_ticket_legs (
                            run_date, version, ticket_id, leg_index, match_no, league,
                            home_team, away_team, pool, play, pick, odds, goal_line,
                            poisson_edge, note
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_date,
                            version,
                            ticket["ticket_id"],
                            index,
                            leg["match_no"],
                            leg.get("league"),
                            leg.get("home_team"),
                            leg.get("away_team"),
                            leg["pool"],
                            leg.get("play"),
                            leg["pick"],
                            float(leg["odds"]),
                            leg.get("goal_line"),
                            leg.get("poisson_edge"),
                            leg.get("note"),
                        ),
                    )

    def get_ticket_version(self, run_date: str, version: int) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM jczq_ticket_versions WHERE run_date = ? AND version = ?",
                (run_date, version),
            ).fetchone()
            if row is None:
                raise KeyError(f"ticket version not found: {run_date} v{version}")
            payload = _row_dict(row)
            ticket_rows = conn.execute(
                """
                SELECT * FROM jczq_tickets
                WHERE run_date = ? AND version = ?
                ORDER BY ticket_id
                """,
                (run_date, version),
            ).fetchall()
            tickets: list[dict[str, Any]] = []
            for ticket_row in ticket_rows:
                ticket = _row_dict(ticket_row)
                ticket["is_best_pick"] = bool(ticket["is_best_pick"])
                ticket["is_extra_budget"] = bool(ticket["is_extra_budget"])
                leg_rows = conn.execute(
                    """
                    SELECT * FROM jczq_ticket_legs
                    WHERE run_date = ? AND version = ? AND ticket_id = ?
                    ORDER BY leg_index
                    """,
                    (run_date, version, ticket["ticket_id"]),
                ).fetchall()
                ticket["legs"] = [_row_dict(leg_row) for leg_row in leg_rows]
                tickets.append(ticket)
            payload["tickets"] = tickets
        return payload

    def list_ticket_versions(self, run_date: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM jczq_ticket_versions
                WHERE run_date = ?
                ORDER BY version DESC
                """,
                (run_date,),
            ).fetchall()
        return [_row_dict(row) for row in rows]

    def save_validation_findings(
        self,
        *,
        run_date: str,
        version: int,
        findings: list[dict[str, Any]],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM jczq_validation_findings WHERE run_date = ? AND version = ?",
                (run_date, version),
            )
            for finding in findings:
                conn.execute(
                    """
                    INSERT INTO jczq_validation_findings (
                        run_date, version, severity, ticket_id, code, message, blocks_finalization
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_date,
                        version,
                        finding["severity"],
                        finding.get("ticket_id"),
                        finding["code"],
                        finding["message"],
                        int(bool(finding.get("blocks_finalization"))),
                    ),
                )

    def list_validation_findings(self, run_date: str, version: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM jczq_validation_findings
                WHERE run_date = ? AND version = ?
                ORDER BY id
                """,
                (run_date, version),
            ).fetchall()
        findings = [_row_dict(row) for row in rows]
        for finding in findings:
            finding["blocks_finalization"] = bool(finding["blocks_finalization"])
        return findings

    def record_review(
        self,
        *,
        run_date: str,
        version: int,
        ticket_id: str,
        status: str,
        actual_return: float | None,
        profit_loss: float | None,
        failed_leg: str | None,
        notes: str | None,
        leg_reviews: list[dict[str, Any]],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jczq_reviews (
                    run_date, version, ticket_id, status, actual_return, profit_loss,
                    failed_leg, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_date, version, ticket_id) DO UPDATE SET
                    status=excluded.status,
                    actual_return=excluded.actual_return,
                    profit_loss=excluded.profit_loss,
                    failed_leg=excluded.failed_leg,
                    notes=excluded.notes
                """,
                (
                    run_date,
                    version,
                    ticket_id,
                    status,
                    actual_return,
                    profit_loss,
                    failed_leg,
                    notes,
                ),
            )
            conn.execute(
                """
                DELETE FROM jczq_leg_reviews
                WHERE run_date = ? AND version = ? AND ticket_id = ?
                """,
                (run_date, version, ticket_id),
            )
            for leg in leg_reviews:
                conn.execute(
                    """
                    INSERT INTO jczq_leg_reviews (
                        run_date, version, ticket_id, leg_index, match_no, pool,
                        pick, status, actual_result, notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_date,
                        version,
                        ticket_id,
                        int(leg["leg_index"]),
                        leg["match_no"],
                        leg["pool"],
                        leg["pick"],
                        leg["status"],
                        leg.get("actual_result"),
                        leg.get("notes"),
                    ),
                )

    def list_reviews(self, run_date: str, version: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            review_rows = conn.execute(
                """
                SELECT * FROM jczq_reviews
                WHERE run_date = ? AND version = ?
                ORDER BY ticket_id
                """,
                (run_date, version),
            ).fetchall()
            reviews: list[dict[str, Any]] = []
            for review_row in review_rows:
                review = _row_dict(review_row)
                leg_rows = conn.execute(
                    """
                    SELECT * FROM jczq_leg_reviews
                    WHERE run_date = ? AND version = ? AND ticket_id = ?
                    ORDER BY leg_index
                    """,
                    (run_date, version, review["ticket_id"]),
                ).fetchall()
                review["leg_reviews"] = [_row_dict(row) for row in leg_rows]
                reviews.append(review)
        return reviews

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _decode_json_fields(row: dict[str, Any], *field_names: str) -> dict[str, Any]:
    for field_name in field_names:
        value = row.pop(field_name)
        target_name = field_name.removesuffix("_json")
        row[target_name] = json.loads(value)
    return row


def _ticket_total_odds(ticket: dict[str, Any]) -> float:
    total = 1.0
    for leg in ticket.get("legs", []):
        total *= float(leg["odds"])
    return round(total, 2)
