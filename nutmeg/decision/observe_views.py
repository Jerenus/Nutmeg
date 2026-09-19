"""RSI 观察台的只读视图整理。"""

from __future__ import annotations

import json
from pathlib import Path

_COLORS = {
    "registered": "registered",
    "observing": "observing",
    "graded": "graded",
    "falsified": "falsified",
    "survived": "survived",
    "inconclusive": "inconclusive",
    "deployed": "deployed",
    "held": "held",
    "retired": "retired",
    "extended": "extended",
}


def experiment_card(row: dict, falsifier: dict) -> dict:
    n_cum = int(row.get("n_cum") or 0)
    n_min = int(row.get("n_min") or 0)
    gaps = row.get("gaps") or []
    return {
        "exp_id": row["exp_id"],
        "claim": row.get("claim", ""),
        "status": row["status"],
        "color": _COLORS.get(row["status"], "registered"),
        "tier": row.get("tier"),
        "layer": row.get("layer"),
        "population": row.get("population"),
        "n_cum": n_cum,
        "n_min": n_min,
        "progress": (n_cum / n_min) if n_min else 0.0,
        "ci": row.get("ci"),
        "threshold_pp": float(falsifier.get("threshold_pp", 0.0)),
        "bound": falsifier.get("bound"),
        "direction": falsifier.get("direction"),
        "distance_to_falsifier_pp": row.get("distance_to_falsifier_pp"),
        "gaps": gaps,
        "gap_count": len(gaps),
        "verdict": row.get("verdict"),
        "deployment": row.get("deployment"),
        "registered_at": row.get("registered_at"),
    }


def candidate_dag(events: list[dict]) -> dict:
    candidates = [event for event in events if event.get("kind") == "candidate"]
    nodes = []
    ids = set()
    for event in candidates:
        payload = event.get("payload") or {}
        version = str(payload.get("version") or f"seq{event.get('seq')}")
        ids.add(version)
        nodes.append(
            {
                "id": version,
                "verdict": payload.get("verdict"),
                "notes": payload.get("notes"),
                "stake_yuan": payload.get("stake_yuan"),
                "p_all": payload.get("p_all"),
                "seq": event.get("seq"),
                "reason": payload.get("reason", ""),
            }
        )

    edges = []
    orphan_edges_dropped = 0
    for event in candidates:
        payload = event.get("payload") or {}
        parent = payload.get("parent_version")
        if not parent:
            continue
        if parent in ids:
            edges.append(
                {"source": parent, "target": str(payload.get("version"))}
            )
        else:
            orphan_edges_dropped += 1
    return {
        "nodes": nodes,
        "edges": edges,
        "orphan_edges_dropped": orphan_edges_dropped,
    }


def day_view(*, events: list[dict], plan: dict | None) -> dict:
    slips = [dict(event["payload"]) for event in events if event.get("kind") == "slip"]
    judgments = [
        {
            "obj_id": event.get("obj_id"),
            "match": (event.get("payload") or {}).get("match"),
            "market": (event.get("payload") or {}).get("market"),
        }
        for event in events
        if event.get("kind") == "judgment"
    ]
    return {
        "tree": candidate_dag(events),
        "plan": plan,
        "slips": slips,
        "judgments": judgments,
    }


def wind_for_day(zucai_dir: Path, issue: str | None) -> dict | None:
    if not issue:
        return None
    path = Path(zucai_dir) / f"{issue}-tiers.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("wind")
