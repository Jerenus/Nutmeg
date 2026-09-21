"""Select only a registered hard invariant from committed external facts."""

from __future__ import annotations


def brake_condition(deployment, committed_facts: dict[str, str], *, already_braked: bool):
    if already_braked:
        return None
    registered = deployment.brake_conditions.get("conditions", ())
    for code in registered:
        evidence_hash = committed_facts.get(code)
        if evidence_hash:
            return code, evidence_hash
    return None
