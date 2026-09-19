"""Append-only Zucai capital plans."""
from __future__ import annotations

from sqlalchemy import Column, Integer, Table, Text

from nutmeg.ontology.repository.schema import metadata

zucai_capital_plans = Table(
    "zucai_capital_plans",
    metadata,
    Column("plan_id", Text, primary_key=True),
    Column("issue", Text, nullable=False, index=True),
    Column("day", Text, nullable=False),
    Column("supersedes", Text, nullable=True),
    Column("cap_source", Text, nullable=False),
    Column("adjudication_ref", Text, nullable=True),
    Column("caps_json", Text, nullable=False),
    Column("jczq_used_today", Integer, nullable=False),
    Column("frontier_refs_json", Text, nullable=False),
    Column("max_p_matrix", Text, nullable=True),
    Column("max_p_strict", Text, nullable=True),
    Column("chosen_p", Text, nullable=True),
    Column("gate_cost_pp", Text, nullable=True),
    Column("chosen_json", Text, nullable=False),
    Column("verdict_refs_json", Text, nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("committed_at", Text, nullable=False),
)
