from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from nutmeg.services.jczq_debate import JczqDebateWorkspaceService
from nutmeg.storage.jczq_web_repository import JczqWebRepository


class JczqWebValidationError(ValueError):
    def __init__(self, findings: list[dict[str, Any]]) -> None:
        super().__init__("JCZQ web ticket draft has blocking validation findings")
        self.findings = findings


class JczqWebCockpitService:
    def __init__(
        self,
        *,
        output_dir: Path | str = ".nutmeg-data/jczq",
        repository: JczqWebRepository | None = None,
        debate_service: JczqDebateWorkspaceService | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.repository = repository or JczqWebRepository(self.output_dir / "jczq-web.sqlite3")
        self.repository.initialize()
        self.debate_service = debate_service or JczqDebateWorkspaceService()

    def dashboard(self) -> dict[str, Any]:
        return {"days": self.repository.list_days(), "output_dir": str(self.output_dir)}

    def workspace(self, run_date: str) -> dict[str, Any]:
        day = self.repository.get_day(run_date) or {"run_date": run_date, "status": "empty"}
        versions = self.repository.list_ticket_versions(run_date)
        current_version = day.get("current_version")
        if current_version is None and versions:
            current_version = versions[0]["version"]
        reviews: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []
        if current_version:
            reviews = self.repository.list_reviews(run_date, int(current_version))
            findings = self.repository.list_validation_findings(run_date, int(current_version))
        return {
            "day": day,
            "matches": self.repository.list_matches(run_date),
            "candidate_legs": self.repository.list_candidate_legs(run_date),
            "analyses": {
                item["agent"]: item for item in self.repository.list_analyses(run_date)
            },
            "versions": versions,
            "reviews": reviews,
            "findings": findings,
            "artifacts": self._artifact_paths(run_date),
        }

    def load_brief(self, *, run_date: str, brief_text: str | None = None) -> dict[str, Any]:
        run_dir = self._run_dir(run_date)
        run_dir.mkdir(parents=True, exist_ok=True)
        brief_path = run_dir / "brief.md"
        if brief_text is None:
            if not brief_path.exists():
                raise FileNotFoundError(brief_path)
            brief_text = brief_path.read_text(encoding="utf-8")
        else:
            brief_path.write_text(brief_text, encoding="utf-8")

        self.repository.upsert_day(
            run_date=run_date,
            status="brief_generated",
            brief_path=str(brief_path),
        )
        for match in _parse_matches(brief_text):
            self.repository.upsert_match(run_date=run_date, **match)
        for leg in _parse_candidate_legs(brief_text):
            self.repository.upsert_candidate_leg(run_date=run_date, **leg)
        return {"run_date": run_date, "status": "brief_generated", "brief_path": str(brief_path)}

    def initialize_debate(self, run_date: str) -> dict[str, Any]:
        result = self.debate_service.initialize_workspace(
            run_date=run_date,
            output_dir=self.output_dir,
        )
        self.repository.upsert_day(
            run_date=run_date,
            status="workspace_initialized",
            debate_dir=result["debate_dir"],
        )
        return result

    def save_analysis(self, *, run_date: str, agent: str, content: str) -> dict[str, Any]:
        normalized_agent = agent.lower()
        artifact_path = self._analysis_artifact_path(run_date, normalized_agent)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(content, encoding="utf-8")
        brief_hash = self._shared_brief_hash(run_date)
        self.repository.save_analysis(
            run_date=run_date,
            agent=normalized_agent,
            content=content,
            artifact_path=str(artifact_path),
            brief_hash=brief_hash,
        )
        status = {
            "gpt": "gpt_submitted",
            "claude": "claude_submitted",
            "human": "human_discussing",
        }.get(normalized_agent, "human_discussing")
        self.repository.upsert_day(run_date=run_date, status=status)
        return {
            "run_date": run_date,
            "agent": normalized_agent,
            "artifact_path": str(artifact_path),
            "brief_hash": brief_hash,
        }

    def compare_debate(self, run_date: str) -> dict[str, Any]:
        result = self.debate_service.compare_workspace(
            run_date=run_date,
            output_dir=self.output_dir,
        )
        self.repository.upsert_day(run_date=run_date, status="compared")
        result["status"] = "compared"
        return result

    def draft_ticket_version(
        self,
        *,
        run_date: str,
        source: str,
        tickets: list[dict[str, Any]],
        best_pick: str | None = None,
    ) -> dict[str, Any]:
        enriched_tickets = self._enrich_tickets(run_date, tickets)
        findings = validate_tickets(
            tickets=enriched_tickets,
            matches=self.repository.list_matches(run_date),
        )
        blocking = [finding for finding in findings if finding["blocks_finalization"]]
        if blocking:
            raise JczqWebValidationError(blocking)

        version = self.repository.create_ticket_version(
            run_date=run_date,
            source=source,
            status="draft",
            best_pick=best_pick,
        )
        self.repository.replace_version_tickets(
            run_date=run_date,
            version=version,
            tickets=enriched_tickets,
        )
        self.repository.save_validation_findings(
            run_date=run_date,
            version=version,
            findings=findings,
        )
        payload = self.repository.get_ticket_version(run_date, version)
        payload["findings"] = findings
        return payload

    def finalize_version(self, run_date: str, version: int) -> dict[str, Any]:
        findings = self.repository.list_validation_findings(run_date, version)
        blocking = [finding for finding in findings if finding["blocks_finalization"]]
        if blocking:
            raise JczqWebValidationError(blocking)

        payload = self.repository.get_ticket_version(run_date, version)
        final_plan_path = self._debate_dir(run_date) / "final-plan.md"
        final_json_path = self._debate_dir(run_date) / "final-plan.json"
        final_plan_path.parent.mkdir(parents=True, exist_ok=True)
        final_plan_path.write_text(
            _render_final_markdown(run_date, payload, findings),
            encoding="utf-8",
        )
        final_payload = {
            "version": version,
            "run_date": run_date,
            "status": "finalized",
            "source": payload["source"],
            "best_pick": payload.get("best_pick"),
            "tickets": payload["tickets"],
            "validation_findings": findings,
            "final_plan_path": str(final_plan_path),
        }
        final_json_path.write_text(
            json.dumps(final_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.repository.update_ticket_version_status(
            run_date=run_date,
            version=version,
            status="finalized",
            best_pick=payload.get("best_pick"),
        )
        return {
            "run_date": run_date,
            "version": version,
            "status": "finalized",
            "final_plan_path": str(final_plan_path),
            "final_plan_json_path": str(final_json_path),
        }

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
    ) -> dict[str, Any]:
        self.repository.record_review(
            run_date=run_date,
            version=version,
            ticket_id=ticket_id,
            status=status,
            actual_return=actual_return,
            profit_loss=profit_loss,
            failed_leg=failed_leg,
            notes=notes,
            leg_reviews=leg_reviews,
        )
        self.repository.upsert_day(run_date=run_date, status="reviewed")
        return {
            "run_date": run_date,
            "version": version,
            "ticket_id": ticket_id,
            "status": "reviewed",
        }

    def _run_dir(self, run_date: str) -> Path:
        return self.output_dir / "daily" / run_date

    def _debate_dir(self, run_date: str) -> Path:
        return self._run_dir(run_date) / "debate"

    def _artifact_paths(self, run_date: str) -> dict[str, str]:
        debate_dir = self._debate_dir(run_date)
        return {
            "brief": str(self._run_dir(run_date) / "brief.md"),
            "shared_brief": str(debate_dir / "shared-brief.md"),
            "gpt_analysis": str(debate_dir / "gpt-analysis.md"),
            "claude_analysis": str(debate_dir / "claude-analysis.md"),
            "human_notes": str(debate_dir / "human-notes.md"),
            "disagreements": str(debate_dir / "disagreements.md"),
            "final_plan": str(debate_dir / "final-plan.md"),
            "final_plan_json": str(debate_dir / "final-plan.json"),
        }

    def _analysis_artifact_path(self, run_date: str, agent: str) -> Path:
        filename = {
            "gpt": "gpt-analysis.md",
            "claude": "claude-analysis.md",
            "human": "human-notes.md",
        }.get(agent, f"{agent}-analysis.md")
        return self._debate_dir(run_date) / filename

    def _shared_brief_hash(self, run_date: str) -> str:
        candidates = [
            self._debate_dir(run_date) / "shared-brief.md",
            self._run_dir(run_date) / "brief.md",
        ]
        for path in candidates:
            if path.exists():
                return hashlib.sha256(path.read_bytes()).hexdigest()
        return ""

    def _enrich_tickets(self, run_date: str, tickets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        matches = {match["match_no"]: match for match in self.repository.list_matches(run_date)}
        candidates = {
            (leg["match_no"], leg["pool"], leg["pick"]): leg
            for leg in self.repository.list_candidate_legs(run_date)
        }
        enriched: list[dict[str, Any]] = []
        for ticket in tickets:
            next_ticket = {**ticket, "legs": []}
            for leg in ticket.get("legs", []):
                match = matches.get(leg.get("match_no"), {})
                candidate = candidates.get(
                    (leg.get("match_no"), leg.get("pool"), leg.get("pick")),
                    {},
                )
                next_leg = {**match, **candidate, **leg}
                next_ticket["legs"].append(next_leg)
            enriched.append(next_ticket)
        return enriched


def validate_tickets(
    *,
    tickets: list[dict[str, Any]],
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    match_index = {match["match_no"]: match for match in matches}
    findings: list[dict[str, Any]] = []
    for ticket in tickets:
        ticket_id = str(ticket.get("ticket_id") or "")
        if not ticket_id:
            findings.append(
                _finding("error", ticket_id, "missing_ticket_id", "缺少 ticket id", True)
            )
        if float(ticket.get("stake") or 0) < 0:
            findings.append(_finding("error", ticket_id, "negative_stake", "注金不能为负", True))
        seen_same_pool: dict[tuple[str, str], str] = {}
        for leg in ticket.get("legs", []):
            match_no = str(leg.get("match_no") or "")
            pool = str(leg.get("pool") or "")
            pick = str(leg.get("pick") or "")
            odds = float(leg.get("odds") or 0)
            if not match_no or not pool or not pick or odds <= 0:
                findings.append(
                    _finding(
                        "error",
                        ticket_id,
                        "missing_leg_field",
                        "腿缺少场次/玩法/选项/赔率",
                        True,
                    )
                )
                continue
            same_pool_key = (match_no, pool)
            previous_pick = seen_same_pool.get(same_pool_key)
            if previous_pick and previous_pick != pick:
                findings.append(
                    _finding(
                        "error",
                        ticket_id,
                        "mutually_exclusive_same_pool",
                        f"{match_no} {pool} 同票出现互斥选项：{previous_pick} / {pick}",
                        True,
                    )
                )
            seen_same_pool[same_pool_key] = pick

            match = match_index.get(match_no, {})
            if pool == "had" and odds <= 1.40 and ticket_id in {"A", "B", "C"}:
                findings.append(
                    _finding(
                        "error",
                        ticket_id,
                        "had_banker_floor",
                        "A/B/C 禁用 HAD≤1.40",
                        True,
                    )
                )
            if (
                pool == "had"
                and ticket_id in {"A", "B", "C", "D"}
                and match.get("flags", {}).get("coinflip")
            ):
                findings.append(
                    _finding(
                        "error",
                        ticket_id,
                        "coinflip_had",
                        f"{match_no} coinflip 场禁用 HAD",
                        True,
                    )
                )
            if pool == "hhad" and leg.get("goal_line") is None:
                findings.append(
                    _finding(
                        "error",
                        ticket_id,
                        "missing_goal_line",
                        f"{match_no} hhad 缺少让球线",
                        True,
                    )
                )
            if pool == "hafu" and ticket_id in {"A", "B", "C", "D"}:
                findings.append(
                    _finding("error", ticket_id, "hafu_non_extreme", "A-D 禁用半全场", True)
                )
            edge = leg.get("poisson_edge")
            if edge is not None and float(edge) <= -0.20 and ticket_id in {"A", "B", "C", "D"}:
                findings.append(
                    _finding(
                        "error",
                        ticket_id,
                        "poisson_strong_oppose",
                        f"{match_no} Poisson 强反对",
                        True,
                    )
                )
            if edge is not None and -0.20 < float(edge) <= -0.15:
                findings.append(
                    _finding(
                        "warning",
                        ticket_id,
                        "poisson_soft_oppose",
                        f"{match_no} Poisson 中度反对",
                        False,
                    )
                )

        if ticket_id == "C" and len(ticket.get("legs", [])) > 1:
            findings.append(
                _finding(
                    "warning",
                    ticket_id,
                    "poisson_solo_dilution",
                    "C Poisson 单核被额外串关稀释",
                    False,
                )
            )
        if _dominant_zero_zero(ticket):
            findings.append(
                _finding(
                    "warning",
                    ticket_id,
                    "narrative_concentration",
                    "极限/娱乐票过度依赖 0:0 叙事",
                    False,
                )
            )
    return findings


def _parse_matches(brief_text: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for line in brief_text.splitlines():
        if not line.startswith("| 周"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 10:
            continue
        if " vs " not in cells[2]:
            continue
        home_team, away_team = [part.strip() for part in cells[2].split(" vs ", 1)]
        tags = []
        flags = {
            "strong_banker": bool(cells[6]),
            "comfort": bool(cells[7]),
            "draw": bool(cells[8]),
            "coinflip": "⚠" in cells[9],
            "high_volatility": len(cells) > 10 and "⚠" in cells[10],
        }
        for tag, enabled in flags.items():
            if enabled:
                tags.append(tag)
        matches.append(
            {
                "match_no": cells[0],
                "league": cells[1],
                "home_team": home_team,
                "away_team": away_team,
                "role": cells[5],
                "goal_line": _parse_goal_line(cells[4]),
                "tags": tags,
                "flags": flags,
            }
        )
    return matches


def _parse_candidate_legs(brief_text: str) -> list[dict[str, Any]]:
    legs: list[dict[str, Any]] = []
    in_section = False
    for line in brief_text.splitlines():
        if line.startswith("## 4. Poisson"):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section or not line.startswith("| 周"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        legs.append(
            {
                "match_no": cells[0],
                "pool": cells[1],
                "play": _play_name(cells[1]),
                "pick": cells[2],
                "odds": float(cells[3]),
                "poisson_edge": _parse_percent(cells[5]),
                "source": "brief_section_4",
                "tags": _leg_tags(cells[1], cells[2], _parse_percent(cells[5])),
            }
        )
    return legs


def _render_final_markdown(
    run_date: str,
    payload: dict[str, Any],
    findings: list[dict[str, Any]],
) -> str:
    lines = [
        f"# JCZQ Final Plan — {run_date}",
        "",
        f"**版本**：v{payload['version']}",
        f"**来源**：{payload['source']}",
        f"**最看好**：{payload.get('best_pick') or '未标记'}",
        "",
        "## Tickets",
        "",
    ]
    for ticket in payload["tickets"]:
        lines.extend(
            [
                f"### {ticket['ticket_id']} {ticket.get('name') or ticket['kind']} — "
                f"{ticket['stake']:.0f} 元，{ticket['total_odds']:.2f} 倍",
                "",
                "```",
                " × ".join(
                    f"{leg['match_no']} {leg.get('play') or leg['pool']}{leg['pick']} "
                    f"@ {leg['odds']:.2f}"
                    for leg in ticket["legs"]
                ),
                "```",
                "",
                f"- 理论返奖：{ticket['theoretical_return']:.2f} 元",
            ]
        )
        if ticket.get("rationale"):
            lines.append(f"- 理由：{ticket['rationale']}")
        lines.append("")
    if findings:
        lines.extend(["## Validation", ""])
        for finding in findings:
            lines.append(f"- {finding['severity']} {finding['code']}: {finding['message']}")
    return "\n".join(lines).rstrip() + "\n"


def _dominant_zero_zero(ticket: dict[str, Any]) -> bool:
    legs = ticket.get("legs", [])
    if len(legs) < 3:
        return False
    zero_zero_count = sum(1 for leg in legs if leg.get("pick") == "0:0")
    return zero_zero_count >= 3


def _finding(
    severity: str,
    ticket_id: str | None,
    code: str,
    message: str,
    blocks: bool,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "ticket_id": ticket_id,
        "code": code,
        "message": message,
        "blocks_finalization": blocks,
    }


def _parse_goal_line(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _parse_percent(value: str) -> float:
    cleaned = re.sub(r"[*%+]", "", value).strip()
    return round(float(cleaned) / 100, 3)


def _play_name(pool: str) -> str:
    return {
        "had": "胜平负",
        "hhad": "让球胜平负",
        "ttg": "总进球",
        "crs": "比分",
        "hafu": "半全场",
    }.get(pool, pool)


def _leg_tags(pool: str, pick: str, edge: float) -> list[str]:
    tags = []
    if edge >= 0.15:
        tags.append("poisson_alpha")
    if pool in {"crs", "ttg"} and pick in {"0:0", "0球", "1球", "2球"}:
        tags.append("low_goal")
    return tags
