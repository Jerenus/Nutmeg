"""登记原件（experiments/registry/<exp_id>.json）的加载与校验。

原件由人手写，`nutmeg rsi register` 摄入一次；之后内核是唯一权威，原件只是登记时的
文本。这里只做结构校验——判据的语义（CI 怎么判）在 nutmeg.ontology.rsi.models。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from nutmeg.ontology.rsi.models import Falsifier, JudgmentTier, Layer, Population, Tier

_REQUIRED = ("exp_id", "claim", "mechanism", "tier", "layer", "population", "min_tier",
             "window", "falsifier", "stop_rule", "quota_slot", "source_doc", "registered_at")
_DUTY_REQUIRED = ("name", "scope", "deadline_rule", "instrument", "artifact_glob")
_DEADLINE_RULES = ("earliest_kickoff", "match_kickoff")
_SCOPES = ("day", "match")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_registry_doc(path: Path) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in _REQUIRED if k not in doc]
    if missing:
        raise ValueError(f"登记原件缺字段: {missing}")
    Tier(doc["tier"])
    Layer(doc["layer"])
    Population(doc["population"])
    JudgmentTier(doc["min_tier"])
    Falsifier.from_dict(doc["falsifier"])
    w = doc["window"]
    if not isinstance(w, dict) or not (
        {"issue_from", "issue_to"} <= set(w) or {"date_from", "n_min"} <= set(w)
    ):
        raise ValueError("window 必须是 {issue_from, issue_to} 或 {date_from, n_min[, date_to]}")
    if not _DATE.match(str(doc["registered_at"])):
        raise ValueError("registered_at 必须是 YYYY-MM-DD（原登记日，不是摄入日）")
    for d in doc.get("duties") or []:
        for k in _DUTY_REQUIRED:
            if k not in d:
                raise ValueError(f"duty 缺字段 {k}")
        if d["deadline_rule"] not in _DEADLINE_RULES:
            raise ValueError(f"deadline_rule 必须是 {_DEADLINE_RULES}")
        if d["scope"] not in _SCOPES:
            raise ValueError(f"duty.scope 必须是 {_SCOPES}")
        if not d["instrument"] or not any("{issue}" in a or "{day}" in a for a in d["instrument"]):
            raise ValueError("instrument 必须含 {issue} 或 {day} 占位，否则每天跑的是同一条命令")
    return doc


def render_instrument(argv: list[str], *, issue: str | None, day: str) -> list[str]:
    out: list[str] = []
    for a in argv:
        if "{issue}" in a:
            if issue is None:
                raise ValueError("该 instrument 需要 issue，但当天没有足彩期")
            a = a.replace("{issue}", issue)
        out.append(a.replace("{day}", day))
    return out
