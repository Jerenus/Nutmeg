"""File and candidate-tree orchestration for tiers, frontier, and choice."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nutmeg.decision.structure_space import enumerate_frontier
from nutmeg.decision.structure_tiers import board_wind, tier_of
from nutmeg.decision.workbench import append_candidate, read_events

DIGIT_FACE = {"3": "home", "1": "draw", "0": "away"}


def _zucai(data_dir: Path) -> Path:
    return Path(data_dir) / "zucai"


def _day_of(issue: str, data_dir: Path) -> str:
    doc = json.loads((_zucai(data_dir) / f"{issue}-issue.json").read_text("utf-8"))
    kickoffs = sorted(
        str(match["kickoff_bj"])
        for match in doc["matches"]
        if match.get("kickoff_bj")
    )
    return kickoffs[0][:10]


def _legs(issue: str, data_dir: Path) -> dict:
    path = _zucai(data_dir) / f"{issue}-legs-base.json"
    return json.loads(path.read_text("utf-8"))["legs"]


def run_tiers(*, issue: str, data_dir: Path) -> dict:
    legs = _legs(issue, data_dir)
    tiers = {match_no: tier_of(leg) for match_no, leg in legs.items()}
    wind = board_wind(legs)
    doc = {"issue": issue, "tiers": tiers, "wind": wind}
    raw = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    tiers_hash = hashlib.sha256(raw.encode()).hexdigest()[:12]
    doc["tiers_hash"] = tiers_hash
    (_zucai(data_dir) / f"{issue}-tiers.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    append_candidate(
        Path(data_dir) / "jczq",
        _day_of(issue, data_dir),
        obj_id=f"ticket:{issue}",
        version=f"tiers@{tiers_hash}",
        faces={},
        notes=0,
        stake_yuan=0,
        p_all=None,
        verdict="considered",
        reason=f"wind {wind['regime']} · {wind['tiers']}",
    )
    return doc


def run_frontier(*, issue: str, channel: str, cap_yuan: int, data_dir: Path) -> dict:
    tiers_path = _zucai(data_dir) / f"{issue}-tiers.json"
    if not tiers_path.exists():
        raise FileNotFoundError(f"{tiers_path.name} is missing; run plan tiers first")
    tiers_hash = json.loads(tiers_path.read_text("utf-8"))["tiers_hash"]
    legs = _legs(issue, data_dir)
    frontier = enumerate_frontier(
        legs, channel=channel, cap_yuan=cap_yuan, mode="matrix"
    )
    strict = enumerate_frontier(legs, channel=channel, cap_yuan=cap_yuan, mode="strict")
    frontier["strict_max_p"] = strict["max_p"]
    frontier["tiers_hash"] = tiers_hash
    (_zucai(data_dir) / f"{issue}-frontier-{channel}.json").write_text(
        json.dumps(frontier, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    day = _day_of(issue, data_dir)
    for point in frontier["points"]:
        append_candidate(
            Path(data_dir) / "jczq",
            day,
            obj_id=f"ticket:{issue}",
            version=f"frontier#{point['k']}@¥{cap_yuan}",
            parent_version=f"tiers@{tiers_hash}",
            faces=point["faces"],
            notes=point["notes"],
            stake_yuan=point["stake_yuan"],
            p_all=point["p_all"],
            verdict="considered",
            reason=(
                f"{channel} frontier · shape {point['shape']} · "
                f"narrowings {len(point['narrowings'])}"
            ),
        )
    return frontier


def _legs_file_from_faces(legs: dict, faces: dict, issue: str, channel: str) -> dict:
    out = {}
    for match_no, face_string in faces.items():
        leg = legs[match_no]
        out[match_no] = {
            **{key: value for key, value in leg.items() if not key.startswith("_")},
            "faces": face_string,
            "selections": [DIGIT_FACE[digit] for digit in face_string],
        }
    return {"issue": issue, "channel": channel, "legs": out}


def run_choose(
    *,
    issue: str,
    channel: str,
    point: int,
    data_dir: Path,
    edit_file: Path | None = None,
) -> dict:
    frontier_path = _zucai(data_dir) / f"{issue}-frontier-{channel}.json"
    frontier = json.loads(frontier_path.read_text("utf-8"))
    selected = next(item for item in frontier["points"] if item["k"] == point)
    legs = _legs(issue, data_dir)
    day = _day_of(issue, data_dir)
    parent = f"frontier#{point}@¥{frontier['cap_yuan']}"
    if edit_file is None:
        faces = selected["faces"]
        version = f"chosen#{point}@{channel}"
    else:
        faces = json.loads(Path(edit_file).read_text("utf-8"))
        edit_count = 1 + sum(
            1
            for event in read_events(Path(data_dir) / "jczq", day)
            if event.get("kind") == "candidate"
            and str(event["payload"].get("version", "")).startswith("edit#")
            and str(event["payload"].get("version", "")).endswith(f"@{channel}")
        )
        version = f"edit#{edit_count}@{channel}"
    notes = 1
    for face_string in faces.values():
        notes *= len(face_string)
    probability = 1.0
    for match_no, face_string in faces.items():
        probability *= sum(
            float(legs[match_no]["fair"][DIGIT_FACE[digit]]) for digit in face_string
        )
    doc = _legs_file_from_faces(legs, faces, issue, channel)
    legs_path = _zucai(data_dir) / f"{issue}-legs-{channel}.json"
    legs_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    append_candidate(
        Path(data_dir) / "jczq",
        day,
        obj_id=f"ticket:{issue}",
        version=version,
        parent_version=parent,
        faces=faces,
        notes=notes,
        stake_yuan=notes * 2,
        p_all=probability,
        verdict="chosen",
        reason=(
            "human chose frontier point"
            if edit_file is None
            else f"human edit based on {parent}"
        ),
    )
    return {
        "candidate_node": version,
        "parent": parent,
        "notes": notes,
        "stake_yuan": notes * 2,
        "p_all": probability,
        "legs_file": str(legs_path),
    }
