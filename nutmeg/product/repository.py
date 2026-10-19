"""Read-only temporal queries over Ontology Kernel v2.

现役读者只有三处（2026-10-08 第二轮瘦身后缩到这个闭包）：
- decision-web 观察台：``experiments`` / ``experiment_timeline`` / ``duties_due`` /
  ``latest_capital_plan``；
- 工作台内核读侧（``decision_web_kernel``）：``board_matches`` / ``latest_snapshot`` /
  ``forecasts_for_match``；
- ``research`` 的当日板面：``board_matches``。
"""
from __future__ import annotations

import json
from collections.abc import Iterable

from sqlalchemy import Engine, and_, func, select

from nutmeg.ontology.repository import schema_decision as sd
from nutmeg.ontology.repository import schema_identity as si
from nutmeg.ontology.repository import schema_market as sm
from nutmeg.ontology.repository import schema_rsi as sr


class ProductReadRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ── RSI 实验（阶段②观察界面的读路径；与工作台同一 as_of 口径）──────────
    def experiments(self, *, as_of: str) -> list[dict]:
        from datetime import datetime

        from nutmeg.decision.bj_time import BJ
        from nutmeg.ontology.repository.rsi import RsiRepository
        from nutmeg.ontology.rsi.models import Falsifier, project_status

        # 按时刻比，不按字符串比：created_at 是 +08:00、as_of 常是 UTC——2026-10-19 前字符串比较
        # 让登记后 8 小时内的实验被当成「未来」跳过，gaps 也错位
        cutoff = datetime.fromisoformat(as_of).astimezone(BJ)
        as_of_bj = cutoff.isoformat(timespec="seconds")
        with self._engine.connect() as connection:
            repo = RsiRepository(connection)
            out: list[dict] = []
            for e in repo.experiments():
                if datetime.fromisoformat(e.created_at).astimezone(BJ) > cutoff:
                    continue
                f = Falsifier.from_dict(e.falsifier)
                g = repo.latest_grade(e.exp_id, mode="prospective", stratum=f.stratum)
                # n 与 `rsi status` 同源：有 grade 用 grade；没有 grade 的覆盖率实验（R0/R1）
                # 用前瞻观测行数（2026-10-19 前观察台显示 0，命令行 319）
                n_cum = g.n_cum if g else repo.prospective_n_rows(
                    e.exp_id, window=e.window, stratum=f.stratum)
                v = repo.latest_verdict(e.exp_id)
                d = repo.latest_deployment(e.exp_id)
                out.append(
                    {
                        "exp_id": e.exp_id,
                        "claim": e.claim,
                        "tier": e.tier,
                        "layer": e.layer,
                        "population": e.population,
                        "registered_at": e.registered_at,
                        "falsifier": e.falsifier,
                        "n_min": f.n_min,
                        "n_cum": n_cum,
                        "ci": [g.ci_low_pp, g.ci_high_pp] if g else None,
                        "distance_to_falsifier_pp": (
                            g.distance_to_falsifier_pp if g else None
                        ),
                        "verdict": v.verdict if v else None,
                        "deployment": d.decision if d else None,
                        "gaps": repo.gaps(e.exp_id, now=as_of_bj),
                        "status": project_status(
                            n_observations=repo.count_observations(e.exp_id),
                            latest_prospective_n=g.n_cum if g else 0,
                            n_min=f.n_min,
                            latest_verdict=v.verdict if v else None,
                            latest_deployment=d.decision if d else None,
                        ),
                    }
                )
            return out

    def latest_capital_plan(self, issue: str):
        """Return the latest append-only capital plan without opening a write UOW."""
        from nutmeg.ontology.repository.capital import CapitalRepository

        with self._engine.connect() as connection:
            return CapitalRepository(connection).latest_plan(issue)

    def experiment_timeline(self, exp_id: str, *, as_of: str) -> list[dict]:
        """一条实验的全部只追加记录，按时间排成时间线。"""
        with self._engine.connect() as connection:
            rows: list[dict] = []
            e = (
                connection.execute(
                    select(sr.rsi_experiments).where(
                        sr.rsi_experiments.c.exp_id == exp_id
                    )
                )
                .mappings()
                .first()
            )
            if e is None or e["created_at"] > as_of:
                return []
            rows.append(
                {
                    "kind": "registered",
                    "at": e["created_at"],
                    "claim": e["claim"],
                    "falsifier": json.loads(e["falsifier_json"]),
                    "frozen_hash": e["frozen_hash"],
                }
            )
            for t, kind, at in (
                (sr.rsi_observations, "observation", "captured_at"),
                (sr.rsi_grades, "grade", "graded_at"),
                (sr.rsi_verdicts, "verdict", "decided_at"),
                (sr.rsi_deployments, "deployment", "decided_at"),
                (sr.rsi_amendments, "amendment", "amended_at"),
            ):
                for r in (
                    connection.execute(
                        select(t).where(t.c.exp_id == exp_id, t.c[at] <= as_of)
                    )
                    .mappings()
                    .all()
                ):
                    rows.append(
                        {
                            "kind": kind,
                            "at": r[at],
                            **{k: v for k, v in r.items() if k != at},
                        }
                    )
            rows.sort(key=lambda r: (r["at"], r["kind"]))
            return rows

    def duties_due(self, day: str, *, now: str) -> list[dict]:
        with self._engine.connect() as connection:
            t = sr.rsi_duty_instances
            rows = (
                connection.execute(
                    select(t)
                    .where(
                        t.c.day == day,
                        t.c.fulfilled_at.is_(None),
                        t.c.due_at > now,
                    )
                    .order_by(t.c.due_at, t.c.duty_id)
                )
                .mappings()
                .all()
            )
            return [dict(r) for r in rows]


    def board_matches(self, start_at: str, end_at: str, as_of: str) -> list[dict]:
        # 按时刻比较，不按字符串：竞彩 scheduled_at 存成 +08:00，窗口边界是 UTC，字典序
        # 会把北京时间 16:00 后开球的场挤到第二天（2026-10-06 周二 19:00/19:35/22:00）
        scheduled = func.julianday(si.match_revisions.c.scheduled_at)
        statement = self._match_statement(as_of).where(
            scheduled >= func.julianday(start_at),
            scheduled < func.julianday(end_at),
        )
        with self._engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings().all()]


    @staticmethod
    def _match_statement(as_of: str):
        home_appearance = si.team_appearances.alias('home_appearance')
        away_appearance = si.team_appearances.alias('away_appearance')
        home_team = si.teams.alias('home_team')
        away_team = si.teams.alias('away_team')
        current_at_cutoff = (
            select(si.match_revisions.c.match_revision_id)
            .where(
                si.match_revisions.c.match_id == si.matches.c.match_id,
                si.match_revisions.c.recorded_at <= as_of,
            )
            .order_by(
                si.match_revisions.c.recorded_at.desc(),
                si.match_revisions.c.version.desc(),
            )
            .limit(1)
            .correlate(si.matches)
            .scalar_subquery()
        )
        return (
            select(
                si.matches.c.match_id,
                si.match_revisions.c.match_revision_id,
                si.match_revisions.c.scheduled_at,
                si.match_revisions.c.status,
                si.match_revisions.c.schedule_status,
                home_team.c.canonical_name.label('home_team'),
                away_team.c.canonical_name.label('away_team'),
                home_team.c.team_id.label('home_team_id'),
                away_team.c.team_id.label('away_team_id'),
                home_team.c.resolution_status.label('home_resolution_status'),
                away_team.c.resolution_status.label('away_resolution_status'),
                si.competitions.c.competition_id,
                si.competition_editions.c.competition_edition_id,
                si.competitions.c.name.label('competition'),
                si.match_revisions.c.round_label,
                si.match_revisions.c.venue_id,
            )
            .select_from(
                si.matches.join(
                    si.match_revisions,
                    si.match_revisions.c.match_revision_id == current_at_cutoff,
                )
                .join(
                    home_appearance,
                    and_(
                        home_appearance.c.match_id == si.matches.c.match_id,
                        home_appearance.c.side.in_(['home', 'neutral_designated_home']),
                    ),
                )
                .join(home_team, home_team.c.team_id == home_appearance.c.team_id)
                .join(
                    away_appearance,
                    and_(
                        away_appearance.c.match_id == si.matches.c.match_id,
                        away_appearance.c.side.in_(['away', 'neutral_designated_away']),
                    ),
                )
                .join(away_team, away_team.c.team_id == away_appearance.c.team_id)
                .outerjoin(
                    si.competition_editions,
                    si.competition_editions.c.competition_edition_id
                    == si.match_revisions.c.competition_edition_id,
                )
                .outerjoin(
                    si.competitions,
                    si.competitions.c.competition_id
                    == si.competition_editions.c.competition_id,
                )
            )
            .order_by(si.match_revisions.c.scheduled_at, si.matches.c.match_id)
        )

    def latest_snapshot(
        self, match_id: str, market_definition_id: str, as_of: str
    ) -> dict | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    select(sm.market_snapshots)
                    .where(
                        sm.market_snapshots.c.match_id == match_id,
                        sm.market_snapshots.c.market_definition_id
                        == market_definition_id,
                        func.julianday(sm.market_snapshots.c.as_of)
                        <= func.julianday(as_of),
                    )
                    .order_by(
                        func.julianday(sm.market_snapshots.c.as_of).desc(),
                        sm.market_snapshots.c.market_snapshot_id.desc(),
                    )
                    .limit(1)
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        result = dict(row)
        result['fair_distribution'] = json.loads(result.pop('fair_distribution_json'))
        return result


    def forecasts_for_match(self, match_id: str, as_of: str) -> list[dict]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    select(sd.forecast_revisions, sd.forecast_series.c.market_definition_id)
                    .select_from(
                        sd.forecast_revisions.join(
                            sd.forecast_series,
                            sd.forecast_revisions.c.forecast_series_id
                            == sd.forecast_series.c.forecast_series_id,
                        )
                    )
                    .where(
                        sd.forecast_series.c.match_id == match_id,
                        sd.forecast_revisions.c.made_at <= as_of,
                    )
                    .order_by(
                        sd.forecast_revisions.c.made_at,
                        sd.forecast_revisions.c.revision_no,
                    )
                )
                .mappings()
                .all()
            )
        return [
            self._decode_json(
                row, ('prior_distribution_json', 'belief_distribution_json')
            )
            for row in rows
        ]


    @staticmethod
    def _decode_json(row, columns: Iterable[str]) -> dict:
        result = dict(row)
        for column in columns:
            result[column.removesuffix('_json')] = json.loads(result.pop(column))
        return result
