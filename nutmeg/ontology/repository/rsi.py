"""RSI 实验对象的仓库。只 insert + select；状态由 projection 函数从行里算。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from sqlalchemy import Connection, func, insert, select

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.repository import schema_rsi as sr
from nutmeg.ontology.rsi.models import window_contains


@dataclass(frozen=True, slots=True)
class ExperimentRow:
    exp_id: str
    claim: str
    mechanism: str
    tier: str
    layer: str
    population: str
    min_tier: str
    window: dict
    falsifier: dict
    stop_rule: str
    quota_slot: bool
    buckets: list
    rule_ids: list
    replay_spec: dict | None
    dream_ref: str | None
    variants_tried: int | None
    source_doc: str
    registered_at: str
    frozen_hash: str
    created_at: str


@dataclass(frozen=True, slots=True)
class DutyRow:
    duty_id: str
    exp_id: str
    recurrence: str
    scope: str
    deadline_rule: str
    instrument: list
    artifact_glob: str
    description: str


@dataclass(frozen=True, slots=True)
class DutyInstanceRow:
    duty_id: str
    day: str
    match_id: str
    issue: str | None
    due_at: str
    fulfilled_at: str | None
    artifact_path: str | None
    artifact_hash: str | None


@dataclass(frozen=True, slots=True)
class ObservationRow:
    observation_id: str
    exp_id: str
    day: str
    population_stratum: str
    n_rows: int
    captured_at: str
    prospective: bool
    judgment_tier_hist: dict
    artifact_hash: str


@dataclass(frozen=True, slots=True)
class GradeRow:
    grade_id: str
    exp_id: str
    mode: str
    stratum: str
    n_cum: int
    metric: str
    metric_value_pp: float
    ci_low_pp: float
    ci_high_pp: float
    distance_to_falsifier_pp: float
    cost_axis_pp: float | None
    as_of_policy: str
    computed_by: str
    inputs_hash: str
    graded_at: str


@dataclass(frozen=True, slots=True)
class VerdictRow:
    verdict_id: str
    exp_id: str
    verdict: str
    grade_id: str
    criterion_snapshot: dict
    decided_at: str


@dataclass(frozen=True, slots=True)
class DeploymentRow:
    deployment_id: str
    exp_id: str
    decision: str
    rule_id: str | None
    reason: str
    adjudication_ref: str | None
    extend_to_exp_id: str | None
    actor_id: str
    decided_at: str


@dataclass(frozen=True, slots=True)
class AmendmentRow:
    amendment_id: str
    exp_id: str
    what: str
    why: str
    rule_check: str
    mechanism_note: str | None
    amended_at: str


_GRADE_PP_FIELDS = ("metric_value_pp", "ci_low_pp", "ci_high_pp", "distance_to_falsifier_pp")


class RsiRepository:
    def __init__(self, connection: Connection) -> None:
        self._c = connection

    # ── experiments ──────────────────────────────────────────────
    def insert_experiment(self, row: ExperimentRow) -> None:
        v = asdict(row)
        v["window_json"] = canonical_json(v.pop("window"))
        v["falsifier_json"] = canonical_json(v.pop("falsifier"))
        v["buckets_json"] = canonical_json(v.pop("buckets"))
        v["rule_ids_json"] = canonical_json(v.pop("rule_ids"))
        rs = v.pop("replay_spec")
        v["replay_spec_json"] = None if rs is None else canonical_json(rs)
        v["quota_slot"] = 1 if v["quota_slot"] else 0
        self._c.execute(insert(sr.rsi_experiments).values(**v))

    def experiment(self, exp_id: str) -> ExperimentRow | None:
        t = sr.rsi_experiments
        r = self._c.execute(select(t).where(t.c.exp_id == exp_id)).mappings().first()
        return None if r is None else self._experiment_row(r)

    def experiments(self) -> list[ExperimentRow]:
        t = sr.rsi_experiments
        rows = (
            self._c.execute(select(t).order_by(t.c.registered_at, t.c.exp_id))
            .mappings()
            .all()
        )
        return [self._experiment_row(r) for r in rows]

    @staticmethod
    def _experiment_row(r) -> ExperimentRow:
        rs = r["replay_spec_json"]
        return ExperimentRow(
            exp_id=r["exp_id"],
            claim=r["claim"],
            mechanism=r["mechanism"],
            tier=r["tier"],
            layer=r["layer"],
            population=r["population"],
            min_tier=r["min_tier"],
            window=json.loads(r["window_json"]),
            falsifier=json.loads(r["falsifier_json"]),
            stop_rule=r["stop_rule"],
            quota_slot=bool(r["quota_slot"]),
            buckets=json.loads(r["buckets_json"]),
            rule_ids=json.loads(r["rule_ids_json"]),
            replay_spec=None if rs is None else json.loads(rs),
            dream_ref=r["dream_ref"],
            variants_tried=r["variants_tried"],
            source_doc=r["source_doc"],
            registered_at=r["registered_at"],
            frozen_hash=r["frozen_hash"],
            created_at=r["created_at"],
        )

    # ── duties ───────────────────────────────────────────────────
    def insert_duty(self, row: DutyRow) -> None:
        v = asdict(row)
        v["instrument_json"] = canonical_json(v.pop("instrument"))
        self._c.execute(insert(sr.rsi_duties).values(**v))

    def update_duty_definition(self, row: DutyRow) -> None:
        self._c.execute(
            sr.rsi_duties.update()
            .where(sr.rsi_duties.c.duty_id == row.duty_id)
            .values(
                recurrence=row.recurrence,
                scope=row.scope,
                deadline_rule=row.deadline_rule,
                instrument_json=canonical_json(row.instrument),
                artifact_glob=row.artifact_glob,
                description=row.description,
            )
        )

    def duties(self, exp_id: str) -> list[DutyRow]:
        t = sr.rsi_duties
        rows = (
            self._c.execute(select(t).where(t.c.exp_id == exp_id).order_by(t.c.duty_id))
            .mappings()
            .all()
        )
        return [
            DutyRow(
                duty_id=r["duty_id"],
                exp_id=r["exp_id"],
                recurrence=r["recurrence"],
                scope=r["scope"],
                deadline_rule=r["deadline_rule"],
                instrument=json.loads(r["instrument_json"]),
                artifact_glob=r["artifact_glob"],
                description=r["description"],
            )
            for r in rows
        ]

    def all_duties(self) -> list[DutyRow]:
        rows = self._c.execute(select(sr.rsi_duties.c.exp_id)).scalars().all()
        out: list[DutyRow] = []
        for exp_id in sorted(set(rows)):
            out.extend(self.duties(exp_id))
        return out

    def insert_duty_instance(self, row: DutyInstanceRow) -> None:
        self._c.execute(insert(sr.rsi_duty_instances).values(**asdict(row)))

    def duty_instance(
        self, duty_id: str, day: str, match_id: str = ""
    ) -> DutyInstanceRow | None:
        t = sr.rsi_duty_instances
        r = (
            self._c.execute(
                select(t).where(
                    t.c.duty_id == duty_id, t.c.day == day, t.c.match_id == match_id
                )
            )
            .mappings()
            .first()
        )
        return None if r is None else DutyInstanceRow(**dict(r))

    def mark_duty_fulfilled(
        self,
        duty_id: str,
        day: str,
        match_id: str,
        *,
        fulfilled_at: str,
        artifact_path: str,
        artifact_hash: str,
    ) -> None:
        # 唯一的 UPDATE：只填 instance 行上原本为空的 fulfilled_* 列（spec §4），
        # 其余八张表全部只追加。
        t = sr.rsi_duty_instances
        self._c.execute(
            t.update()
            .where(t.c.duty_id == duty_id, t.c.day == day, t.c.match_id == match_id)
            .values(
                fulfilled_at=fulfilled_at,
                artifact_path=artifact_path,
                artifact_hash=artifact_hash,
            )
        )

    def pending_duty_instances(self, *, day: str, now: str) -> list[DutyInstanceRow]:
        """当天还没落、且还没过期的义务。"""
        t = sr.rsi_duty_instances
        rows = (
            self._c.execute(
                select(t)
                .where(t.c.day == day, t.c.fulfilled_at.is_(None), t.c.due_at > now)
                .order_by(t.c.due_at, t.c.duty_id)
            )
            .mappings()
            .all()
        )
        return [DutyInstanceRow(**dict(r)) for r in rows]

    def duty_instances_for_day(self, duty_id: str, day: str) -> list[DutyInstanceRow]:
        t = sr.rsi_duty_instances
        rows = (
            self._c.execute(
                select(t)
                .where(t.c.duty_id == duty_id, t.c.day == day)
                .order_by(t.c.match_id)
            )
            .mappings()
            .all()
        )
        return [DutyInstanceRow(**dict(row)) for row in rows]

    def gaps(self, exp_id: str, *, now: str) -> list[str]:
        """过了 due_at 仍未落的日期——事实记录，不是罚分。"""
        t, d = sr.rsi_duty_instances, sr.rsi_duties
        experiment = self.experiment(exp_id)
        if experiment is None:
            return []
        rows = (
            self._c.execute(
                select(t)
                .select_from(t.join(d, t.c.duty_id == d.c.duty_id))
                .where(d.c.exp_id == exp_id, t.c.fulfilled_at.is_(None), t.c.due_at <= now)
                .order_by(t.c.day)
            )
            .mappings()
            .all()
        )
        return sorted(
            {
                row["day"]
                for row in rows
                if experiment.layer != "structural"
                or window_contains(
                    experiment.window,
                    issue=row["issue"],
                    day=row["day"],
                )
            }
        )

    # ── observations ─────────────────────────────────────────────
    def insert_observation(self, row: ObservationRow) -> None:
        v = asdict(row)
        v["judgment_tier_hist_json"] = canonical_json(v.pop("judgment_tier_hist"))
        v["prospective"] = 1 if v["prospective"] else 0
        self._c.execute(insert(sr.rsi_observations).values(**v))

    def observation(self, observation_id: str) -> ObservationRow | None:
        t = sr.rsi_observations
        r = (
            self._c.execute(select(t).where(t.c.observation_id == observation_id))
            .mappings()
            .first()
        )
        if r is None:
            return None
        d = dict(r)
        d["judgment_tier_hist"] = json.loads(d.pop("judgment_tier_hist_json"))
        d["prospective"] = bool(d["prospective"])
        return ObservationRow(**d)

    def observations(self, exp_id: str) -> list[ObservationRow]:
        t = sr.rsi_observations
        ids = (
            self._c.execute(
                select(t.c.observation_id).where(t.c.exp_id == exp_id).order_by(t.c.day)
            )
            .scalars()
            .all()
        )
        return [self.observation(i) for i in ids]  # type: ignore[misc]

    def count_observations(self, exp_id: str) -> int:
        t = sr.rsi_observations
        return int(
            self._c.execute(
                select(func.count()).select_from(t).where(t.c.exp_id == exp_id)
            ).scalar_one()
        )

    def prospective_n_rows(self, exp_id: str) -> int:
        t = sr.rsi_observations
        return int(
            self._c.execute(
                select(func.coalesce(func.sum(t.c.n_rows), 0)).where(
                    t.c.exp_id == exp_id, t.c.prospective == 1
                )
            ).scalar_one()
        )

    # ── grades / verdicts / deployments / amendments ─────────────
    def insert_grade(self, row: GradeRow) -> None:
        v = asdict(row)
        for k in _GRADE_PP_FIELDS:
            v[k] = repr(float(v[k]))
        v["cost_axis_pp"] = None if v["cost_axis_pp"] is None else repr(float(v["cost_axis_pp"]))
        self._c.execute(insert(sr.rsi_grades).values(**v))

    def grade(self, grade_id: str) -> GradeRow | None:
        t = sr.rsi_grades
        r = self._c.execute(select(t).where(t.c.grade_id == grade_id)).mappings().first()
        return None if r is None else self._grade_row(r)

    def latest_grade(self, exp_id: str, *, mode: str, stratum: str) -> GradeRow | None:
        t = sr.rsi_grades
        r = (
            self._c.execute(
                select(t)
                .where(t.c.exp_id == exp_id, t.c.mode == mode, t.c.stratum == stratum)
                .order_by(t.c.graded_at.desc(), t.c.grade_id.desc())
            )
            .mappings()
            .first()
        )
        return None if r is None else self._grade_row(r)

    @staticmethod
    def _grade_row(r) -> GradeRow:
        d = dict(r)
        for k in _GRADE_PP_FIELDS:
            d[k] = float(d[k])
        d["cost_axis_pp"] = None if d["cost_axis_pp"] is None else float(d["cost_axis_pp"])
        return GradeRow(**d)

    def insert_verdict(self, row: VerdictRow) -> None:
        v = asdict(row)
        v["criterion_snapshot_json"] = canonical_json(v.pop("criterion_snapshot"))
        self._c.execute(insert(sr.rsi_verdicts).values(**v))

    def latest_verdict(self, exp_id: str) -> VerdictRow | None:
        t = sr.rsi_verdicts
        r = (
            self._c.execute(
                select(t)
                .where(t.c.exp_id == exp_id)
                .order_by(t.c.decided_at.desc(), t.c.verdict_id.desc())
            )
            .mappings()
            .first()
        )
        if r is None:
            return None
        d = dict(r)
        d["criterion_snapshot"] = json.loads(d.pop("criterion_snapshot_json"))
        return VerdictRow(**d)

    def insert_deployment(self, row: DeploymentRow) -> None:
        self._c.execute(insert(sr.rsi_deployments).values(**asdict(row)))

    def latest_deployment(self, exp_id: str) -> DeploymentRow | None:
        t = sr.rsi_deployments
        r = (
            self._c.execute(
                select(t)
                .where(t.c.exp_id == exp_id)
                .order_by(t.c.decided_at.desc(), t.c.deployment_id.desc())
            )
            .mappings()
            .first()
        )
        return None if r is None else DeploymentRow(**dict(r))

    def insert_amendment(self, row: AmendmentRow) -> None:
        self._c.execute(insert(sr.rsi_amendments).values(**asdict(row)))

    def amendments(self, exp_id: str) -> list[AmendmentRow]:
        t = sr.rsi_amendments
        rows = (
            self._c.execute(select(t).where(t.c.exp_id == exp_id).order_by(t.c.amended_at))
            .mappings()
            .all()
        )
        return [AmendmentRow(**dict(r)) for r in rows]
