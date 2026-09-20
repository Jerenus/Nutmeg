"""RSI 实验对象表；无可改写 status，状态由事实记录投影。"""
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, PrimaryKeyConstraint, Table, Text

from nutmeg.ontology.repository.schema import metadata

rsi_experiments = Table(
    "rsi_experiments", metadata,
    Column("exp_id", Text, primary_key=True),
    Column("claim", Text, nullable=False),
    Column("mechanism", Text, nullable=False),
    Column("tier", Text, nullable=False),
    Column("layer", Text, nullable=False),
    Column("population", Text, nullable=False),
    Column("min_tier", Text, nullable=False),
    Column("window_json", Text, nullable=False),
    Column("falsifier_json", Text, nullable=False),
    Column("stop_rule", Text, nullable=False),
    Column("quota_slot", Integer, nullable=False),
    Column("buckets_json", Text, nullable=False),
    Column("rule_ids_json", Text, nullable=False),
    Column("replay_spec_json", Text, nullable=True),
    Column("dream_ref", Text, nullable=True),
    Column("variants_tried", Integer, nullable=True),
    Column("source_doc", Text, nullable=False),
    Column("registered_at", Text, nullable=False),      # 原登记日，不是摄入日
    Column("frozen_hash", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("acted_by", Text, nullable=False, server_default="unattributed"),
)

rsi_duties = Table(
    "rsi_duties", metadata,
    Column("duty_id", Text, primary_key=True),
    Column("exp_id", Text, ForeignKey("rsi_experiments.exp_id"), nullable=False, index=True),
    Column("recurrence", Text, nullable=False),          # per_day
    Column("scope", Text, nullable=False),               # day | match
    Column("deadline_rule", Text, nullable=False),       # earliest_kickoff | match_kickoff
    Column("instrument_json", Text, nullable=False),     # argv，{issue}/{day} 占位
    Column("artifact_glob", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="active"),
)

rsi_duty_instances = Table(
    "rsi_duty_instances", metadata,
    Column("duty_id", Text, ForeignKey("rsi_duties.duty_id"), nullable=False),
    Column("day", Text, nullable=False),
    Column("match_id", Text, nullable=False, server_default=""),
    Column("due_at", Text, nullable=False),
    Column("issue", Text, nullable=True),
    Column("fulfilled_at", Text, nullable=True),
    Column("artifact_path", Text, nullable=True),
    Column("artifact_hash", Text, nullable=True),
    PrimaryKeyConstraint("duty_id", "day", "match_id"),
)

rsi_observations = Table(
    "rsi_observations", metadata,
    Column("observation_id", Text, primary_key=True),
    Column("exp_id", Text, ForeignKey("rsi_experiments.exp_id"), nullable=False, index=True),
    Column("day", Text, nullable=False),
    Column("population_stratum", Text, nullable=False),
    Column("n_rows", Integer, nullable=False),
    Column("captured_at", Text, nullable=False),
    Column("prospective", Integer, nullable=False),
    Column("judgment_tier_hist_json", Text, nullable=False),
    Column("artifact_hash", Text, nullable=False),
)

rsi_grades = Table(
    "rsi_grades", metadata,
    Column("grade_id", Text, primary_key=True),
    Column("exp_id", Text, ForeignKey("rsi_experiments.exp_id"), nullable=False, index=True),
    Column("mode", Text, nullable=False),                # replay | prospective
    Column("stratum", Text, nullable=False),             # zucai | jczq | pooled
    Column("n_cum", Integer, nullable=False),
    Column("metric", Text, nullable=False),
    Column("metric_value_pp", Text, nullable=False),
    Column("ci_low_pp", Text, nullable=False),
    Column("ci_high_pp", Text, nullable=False),
    Column("distance_to_falsifier_pp", Text, nullable=False),
    Column("cost_axis_pp", Text, nullable=True),         # 独立轴，从不与 metric 合成
    Column("as_of_policy", Text, nullable=False),
    Column("computed_by", Text, nullable=False),
    Column("inputs_hash", Text, nullable=False),
    Column("graded_at", Text, nullable=False),
)

rsi_verdicts = Table(
    "rsi_verdicts", metadata,
    Column("verdict_id", Text, primary_key=True),
    Column("exp_id", Text, ForeignKey("rsi_experiments.exp_id"), nullable=False, index=True),
    Column("verdict", Text, nullable=False),
    Column("grade_id", Text, ForeignKey("rsi_grades.grade_id"), nullable=False),
    Column("criterion_snapshot_json", Text, nullable=False),
    Column("decided_at", Text, nullable=False),
)

rsi_deployments = Table(
    "rsi_deployments", metadata,
    Column("deployment_id", Text, primary_key=True),
    Column("exp_id", Text, ForeignKey("rsi_experiments.exp_id"), nullable=False, index=True),
    Column("decision", Text, nullable=False),
    Column("rule_id", Text, nullable=True),
    Column("reason", Text, nullable=False),
    Column("adjudication_ref", Text, nullable=True),
    Column("extend_to_exp_id", Text, nullable=True),
    Column("actor_id", Text, nullable=False),
    Column("decided_at", Text, nullable=False),
    Column("acted_by", Text, nullable=False, server_default="unattributed"),
)

rsi_amendments = Table(
    "rsi_amendments", metadata,
    Column("amendment_id", Text, primary_key=True),
    Column("exp_id", Text, ForeignKey("rsi_experiments.exp_id"), nullable=False, index=True),
    Column("what", Text, nullable=False),
    Column("why", Text, nullable=False),
    Column("rule_check", Text, nullable=False),
    Column("mechanism_note", Text, nullable=True),
    Column("amended_at", Text, nullable=False),
    Column("acted_by", Text, nullable=False, server_default="unattributed"),
)
