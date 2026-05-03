from __future__ import annotations

import json
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any, Protocol

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from nutmeg.domain.zucai import (
    ZucaiArtifacts,
    ZucaiDispatch,
    ZucaiGradeReport,
    ZucaiIssue,
    ZucaiMatch,
    ZucaiMatchGrade,
    ZucaiOdds,
    ZucaiPlan,
    ZucaiPlanGrade,
    ZucaiRecommendation,
    ZucaiReport,
)


class ZucaiValidationError(ValueError):
    pass


class ZucaiDocumentSender(Protocol):
    def send_document(self, *, chat_id: int, document_path: Path, caption: str): ...


VALID_CODES = {"3", "1", "0"}
RISKY_FLAGS = {
    "manager_change",
    "cup_semifinal",
    "injuries",
    "draw_risk",
    "balanced_odds",
    "big_match",
    "relegation_pressure",
    "shallow_handicap",
    "home_form",
    "fixture_congestion",
    "information_bias",
    "narrative_trap",
}
BIAS_METADATA_FIELDS = {
    "public_pick",
    "value_pick",
    "narrative_bias",
    "information_bias",
}
HARD_STRENGTH_FAV_ODDS = 1.45
MAX_VALUE_COUNTER_ODDS = 4.80
MAX_VALUE_COUNTER_RATIO = 2.60


class ZucaiWorkflowService:
    def __init__(
        self,
        *,
        telegram_sender: ZucaiDocumentSender | None = None,
        telegram_chat_ids: list[int] | None = None,
        sample_dir: Path | None = None,
        betting_repository: Any | None = None,
    ) -> None:
        self._telegram_sender = telegram_sender
        self._telegram_chat_ids = telegram_chat_ids or []
        self._sample_dir = sample_dir or Path(__file__).parents[1] / "zucai" / "samples"
        self._betting_repository = betting_repository

    def build_report(
        self,
        *,
        issue_id: str | None = None,
        issue_file: Path | str | None = None,
        odds_file: Path | str | None = None,
        overrides_file: Path | str | None = None,
        output_dir: Path | str | None = None,
        render_pdf: bool = False,
        dispatch_telegram: bool = False,
        dry_run: bool = True,
        dispatch_caption: str | None = None,
        record_final: bool = False,
    ) -> ZucaiReport:
        resolved_issue_file = self._resolve_file(issue_file, issue_id, "issue")
        resolved_issue_id = issue_id or self._issue_id_from_path(resolved_issue_file)
        resolved_odds_file = self._resolve_optional_file(odds_file, resolved_issue_id, "odds")
        resolved_overrides_file = self._resolve_optional_file(
            overrides_file, resolved_issue_id, "overrides"
        )

        warnings: list[str] = []
        issue = self.load_issue(resolved_issue_file)
        odds_by_match, odds_sources = self.load_odds(resolved_odds_file, warnings=warnings)
        overrides, override_plans = self.load_overrides(resolved_overrides_file, warnings=warnings)
        recommendations = self._build_recommendations(
            issue=issue,
            odds_by_match=odds_by_match,
            overrides=overrides,
            warnings=warnings,
        )
        plans = self._build_plans(recommendations, override_plans)
        sources = [*issue.sources, *odds_sources]
        generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        artifacts = ZucaiArtifacts()
        dispatch = ZucaiDispatch(status="skipped")
        report = ZucaiReport(
            issue=issue,
            generated_at=generated_at,
            recommendations=recommendations,
            plans=plans,
            artifacts=artifacts,
            dispatch=dispatch,
            warnings=warnings,
            sources=sources,
        )
        if output_dir is not None:
            artifacts = self.write_artifacts(
                report, output_dir=Path(output_dir), render_pdf=render_pdf
            )
            report = ZucaiReport(
                issue=issue,
                generated_at=generated_at,
                recommendations=recommendations,
                plans=plans,
                artifacts=artifacts,
                dispatch=dispatch,
                warnings=warnings,
                sources=sources,
            )
        if dispatch_telegram:
            dispatch = self._dispatch(report, dry_run=dry_run, caption=dispatch_caption)
            report = ZucaiReport(
                issue=issue,
                generated_at=generated_at,
                recommendations=recommendations,
                plans=plans,
                artifacts=artifacts,
                dispatch=dispatch,
                warnings=warnings,
                sources=sources,
            )
            if artifacts.report_json_path:
                Path(artifacts.report_json_path).write_text(
                    json.dumps(report.to_dict(), ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
        if record_final and self._betting_repository is not None:
            self._betting_repository.record_zucai_report(report)
        return report

    def load_issue(self, issue_file: Path | str) -> ZucaiIssue:
        payload = _read_json(Path(issue_file))
        matches = [self._match_from_payload(item) for item in payload.get("matches") or []]
        match_numbers = [match.match_no for match in matches]
        if len(matches) != 14:
            raise ZucaiValidationError("Zucai issue must contain exactly 14 matches.")
        if sorted(match_numbers) != list(range(1, 15)):
            raise ZucaiValidationError("Zucai issue match_no values must be exactly 1 through 14.")
        return ZucaiIssue(
            issue_id=str(payload.get("issue_id") or ""),
            game_type=str(payload.get("game_type") or "sfc14"),
            sale_start=payload.get("sale_start"),
            sale_stop=payload.get("sale_stop"),
            draw_date=payload.get("draw_date"),
            sources=list(payload.get("sources") or []),
            matches=sorted(matches, key=lambda match: match.match_no),
        )

    def load_odds(
        self, odds_file: Path | str | None, *, warnings: list[str]
    ) -> tuple[dict[int, ZucaiOdds], list[dict[str, Any]]]:
        if odds_file is None:
            warnings.append("odds snapshot missing; recommendations use low-confidence baseline")
            return {}, []
        payload = _read_json(Path(odds_file))
        odds: dict[int, ZucaiOdds] = {}
        for item in payload.get("matches") or []:
            try:
                match_no = int(item.get("match_no"))
            except (TypeError, ValueError):
                warnings.append("odds row missing valid match_no")
                continue
            odds[match_no] = ZucaiOdds(
                match_no=match_no,
                home=_positive_float(item.get("home")),
                draw=_positive_float(item.get("draw")),
                away=_positive_float(item.get("away")),
                providers=list(item.get("providers") or []),
            )
        return odds, list(payload.get("sources") or [])

    def load_overrides(
        self,
        overrides_file: Path | str | None,
        *,
        warnings: list[str],
    ) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
        if overrides_file is None:
            return {}, []
        payload = _read_json(Path(overrides_file))
        overrides: dict[int, dict[str, Any]] = {}
        for item in payload.get("matches") or []:
            try:
                match_no = int(item.get("match_no"))
            except (TypeError, ValueError):
                warnings.append("override row missing valid match_no")
                continue
            overrides[match_no] = dict(item)
        return overrides, list(payload.get("plans") or [])

    def write_artifacts(
        self,
        report: ZucaiReport,
        *,
        output_dir: Path,
        render_pdf: bool,
    ) -> ZucaiArtifacts:
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = f"zucai-{report.issue.issue_id}"
        markdown_path = output_dir / f"{stem}-report.md"
        report_json_path = output_dir / f"{stem}-report.json"
        pdf_path = output_dir / f"{stem}-report.pdf"
        markdown_path.write_text(self.render_markdown(report), encoding="utf-8")
        temp_report = ZucaiReport(
            issue=report.issue,
            generated_at=report.generated_at,
            recommendations=report.recommendations,
            plans=report.plans,
            artifacts=ZucaiArtifacts(
                markdown_path=str(markdown_path),
                pdf_path=str(pdf_path) if render_pdf else None,
                report_json_path=str(report_json_path),
            ),
            dispatch=report.dispatch,
            warnings=report.warnings,
            sources=report.sources,
        )
        if render_pdf:
            try:
                self.render_pdf(temp_report, pdf_path)
            except Exception as exc:
                report.warnings.append(f"pdf render failed: {exc}")
                temp_report = ZucaiReport(
                    issue=temp_report.issue,
                    generated_at=temp_report.generated_at,
                    recommendations=temp_report.recommendations,
                    plans=temp_report.plans,
                    artifacts=ZucaiArtifacts(
                        markdown_path=str(markdown_path),
                        pdf_path=None,
                        report_json_path=str(report_json_path),
                    ),
                    dispatch=temp_report.dispatch,
                    warnings=temp_report.warnings,
                    sources=temp_report.sources,
                )
        report_json_path.write_text(
            json.dumps(temp_report.to_dict(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return temp_report.artifacts

    def render_markdown(self, report: ZucaiReport) -> str:
        lines = [
            f"# Nutmeg 足彩第{report.issue.issue_id}期14场报告",
            "",
            f"- 生成时间：{report.generated_at}",
            f"- 停售时间：{report.issue.sale_stop or '未知'}",
            "- 记号：3=主胜，1=平，0=客胜",
            "- 风险提示：分析辅助，不保证命中，不构成投注指令。",
            "",
            "## 方案",
        ]
        for plan in report.plans:
            plan_size = f"{plan.stake_count}注 / {plan.cost_yuan}元"
            lines.append(f"- {plan.name}: `{plan.code}` ({plan_size}) - {plan.note}")
        lines.extend(["", "## 逐场建议"])
        match_by_no = {match.match_no: match for match in report.issue.matches}
        for rec in report.recommendations:
            match = match_by_no[rec.match_no]
            odds = ""
            if rec.odds_average:
                odds = (
                    f" | 均赔 {rec.odds_average['3']:.2f}/"
                    f"{rec.odds_average['1']:.2f}/{rec.odds_average['0']:.2f}"
                )
            lines.append(
                f"{rec.match_no}. {match.home_team} vs {match.away_team} ({match.competition})"
                f"{odds} | 建议 `{rec.pick}` | {rec.risk_tier} | {rec.rationale}"
            )
        if report.warnings:
            lines.extend(["", "## Warnings", *[f"- {warning}" for warning in report.warnings]])
        lines.extend(["", "## Sources"])
        for source in report.sources:
            source_label = source.get('label') or source.get('source_name') or 'source'
            lines.append(f"- {source_label}: {source.get('url') or '-'}")
        return "\n".join(lines) + "\n"

    def render_pdf(self, report: ZucaiReport, pdf_path: Path) -> None:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        styles = getSampleStyleSheet()
        title = ParagraphStyle(
            "ZucaiTitle",
            parent=styles["Title"],
            fontName="STSong-Light",
            fontSize=18,
            leading=24,
            alignment=TA_CENTER,
        )
        body = ParagraphStyle(
            "ZucaiBody",
            parent=styles["BodyText"],
            fontName="STSong-Light",
            fontSize=8.5,
            leading=12,
        )
        small = ParagraphStyle("ZucaiSmall", parent=body, fontSize=7.4, leading=10)
        story = [
            Paragraph(_xml(f"Nutmeg 足彩第{report.issue.issue_id}期14场报告"), title),
            Paragraph(_xml(f"停售：{report.issue.sale_stop or '未知'}　3=主胜 1=平 0=客胜"), body),
            Spacer(1, 5),
            Paragraph(_xml("分析辅助，不保证命中，不构成投注指令。"), body),
            Spacer(1, 8),
        ]
        plan_rows = [
            [
                Paragraph(_xml("方案"), small),
                Paragraph(_xml("投注串"), small),
                Paragraph(_xml("规模"), small),
            ]
        ]
        for plan in report.plans:
            plan_rows.append(
                [
                    Paragraph(_xml(plan.name), small),
                    Paragraph(_xml(plan.code), small),
                    Paragraph(_xml(f"{plan.stake_count}注/{plan.cost_yuan}元"), small),
                ]
            )
        story.append(_table(plan_rows, [32 * mm, 105 * mm, 34 * mm]))
        story.append(Spacer(1, 8))
        match_by_no = {match.match_no: match for match in report.issue.matches}
        rows = [
            [
                Paragraph(_xml("场"), small),
                Paragraph(_xml("对阵"), small),
                Paragraph(_xml("均赔"), small),
                Paragraph(_xml("建议"), small),
                Paragraph(_xml("风险/理由"), small),
            ]
        ]
        for rec in report.recommendations:
            match = match_by_no[rec.match_no]
            odds_text = "-"
            if rec.odds_average:
                odds_text = (
                    f"{rec.odds_average['3']:.2f}/"
                    f"{rec.odds_average['1']:.2f}/{rec.odds_average['0']:.2f}"
                )
            rows.append(
                [
                    Paragraph(str(rec.match_no), small),
                    Paragraph(
                        _xml(f"{match.home_team} vs {match.away_team}<br/>{match.competition}"),
                        small,
                    ),
                    Paragraph(_xml(odds_text), small),
                    Paragraph(_xml(rec.pick), small),
                    Paragraph(_xml(f"{rec.risk_tier}: {rec.rationale}"), small),
                ]
            )
        story.append(_table(rows, [9 * mm, 43 * mm, 25 * mm, 17 * mm, 78 * mm]))
        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            leftMargin=13 * mm,
            rightMargin=13 * mm,
            topMargin=13 * mm,
            bottomMargin=13 * mm,
        )
        doc.build(story)

    def grade_report(
        self,
        *,
        report_file: Path | str,
        outcomes_file: Path | str,
        record_db: bool = False,
    ) -> ZucaiGradeReport:
        report_payload = _read_json(Path(report_file))
        outcome_payload = _read_json(Path(outcomes_file))
        issue_id = str(
            report_payload.get("issue", {}).get("issue_id") or outcome_payload.get("issue_id") or ""
        )
        results = {
            int(k): str(v)
            for k, v in (outcome_payload.get("results") or {}).items()
            if str(v) in VALID_CODES
        }
        recommendations = report_payload.get("recommendations") or []
        warnings: list[str] = []
        match_results: list[ZucaiMatchGrade] = []
        pick_by_match: dict[int, str] = {}
        for rec in recommendations:
            match_no = int(rec["match_no"])
            pick = str(rec["pick"])
            result = results.get(match_no)
            unresolved = result is None
            if unresolved:
                warnings.append(f"missing outcome for match {match_no}")
            match_results.append(
                ZucaiMatchGrade(
                    match_no=match_no,
                    pick=pick,
                    result=result,
                    hit=bool(result and result in pick),
                    unresolved=unresolved,
                )
            )
            pick_by_match[match_no] = pick
        plan_results: list[ZucaiPlanGrade] = []
        for plan in report_payload.get("plans") or []:
            tokens = str(plan["code"]).split()
            selected = [idx for idx, token in enumerate(tokens, start=1) if token != "-"]
            hit_count = sum(
                1
                for idx in selected
                if results.get(idx) is not None and results[idx] in tokens[idx - 1]
            )
            covered = bool(selected) and hit_count == len(selected)
            if any(idx not in results for idx in selected):
                covered = False
            plan_results.append(
                ZucaiPlanGrade(
                    name=str(plan["name"]),
                    plan_type=str(plan.get("plan_type") or "full14"),
                    selected_count=len(selected),
                    hit_count=hit_count,
                    covered=covered,
                )
            )
        grade = ZucaiGradeReport(
            issue_id=issue_id,
            match_results=match_results,
            plan_results=plan_results,
            warnings=warnings,
        )
        if record_db and self._betting_repository is not None:
            self._betting_repository.record_zucai_grade(
                report_payload,
                grade,
                review_date=datetime.now(UTC).date().isoformat(),
            )
        return grade

    def _build_recommendations(
        self,
        *,
        issue: ZucaiIssue,
        odds_by_match: dict[int, ZucaiOdds],
        overrides: dict[int, dict[str, Any]],
        warnings: list[str],
    ) -> list[ZucaiRecommendation]:
        recs: list[ZucaiRecommendation] = []
        for match in issue.matches:
            odds = odds_by_match.get(match.match_no)
            rec = self._baseline_recommendation(match, odds)
            override = overrides.get(match.match_no)
            if override is not None:
                raw_pick = str(override.get("pick") or "").strip()
                if raw_pick:
                    pick = normalize_pick(raw_pick)
                else:
                    pick = ""
                if raw_pick and not pick:
                    warnings.append(
                        f"invalid override pick for match {match.match_no}: {override.get('pick')}"
                    )
                elif pick:
                    primary = str(override.get("primary") or pick[0])
                    if primary not in pick:
                        primary = pick[0]
                    rationale = str(override.get("rationale") or rec.rationale)
                    rec_warnings = rec.warnings
                    if _has_bias_metadata(override):
                        narrative = str(
                            override.get("narrative_bias")
                            or override.get("information_bias")
                            or ""
                        ).strip()
                        if narrative and "信息理解偏差" not in rationale:
                            rationale = f"{rationale} 信息理解偏差：{narrative}"
                        rec_warnings = [*rec_warnings, "information_bias_check"]
                    rec = ZucaiRecommendation(
                        match_no=match.match_no,
                        pick=pick,
                        primary=primary,
                        confidence=float(override.get("confidence") or rec.confidence),
                        risk_tier=str(override.get("risk_tier") or rec.risk_tier),
                        rationale=rationale,
                        odds_average=rec.odds_average,
                        override_applied=True,
                        warnings=rec_warnings,
                    )
                elif _has_bias_metadata(override):
                    rec = self._apply_information_bias_adjustment(rec, override)
                else:
                    warnings.append(f"override for match {match.match_no} missing pick")
            recs.append(rec)
        return recs

    def _apply_information_bias_adjustment(
        self, rec: ZucaiRecommendation, override: dict[str, Any]
    ) -> ZucaiRecommendation:
        odds_average = rec.odds_average
        if odds_average is None:
            return rec
        fav_odds = odds_average[rec.primary]
        if fav_odds <= HARD_STRENGTH_FAV_ODDS:
            return rec
        value_pick = normalize_pick(str(override.get("value_pick") or ""))
        public_pick = normalize_pick(str(override.get("public_pick") or rec.primary))
        if not value_pick:
            return rec
        value_odds = min((odds_average[pick] for pick in value_pick), default=999.0)
        if value_odds > MAX_VALUE_COUNTER_ODDS and value_odds / fav_odds > MAX_VALUE_COUNTER_RATIO:
            return rec
        adjusted_pick = normalize_pick(f"{rec.pick}{public_pick}{value_pick}")
        if not adjusted_pick or adjusted_pick == rec.pick:
            return rec
        narrative = str(
            override.get("narrative_bias") or override.get("information_bias") or "大众合理方向过热"
        ).strip()
        rationale = (
            f"信息理解偏差检查：{narrative}；大众方向{public_pick or rec.primary}可能被叙事放大，"
            f"加入价值方向{value_pick}，避免把“合理信息”直接当作真实赛果结论。原始判断：{rec.rationale}"
        )
        return ZucaiRecommendation(
            match_no=rec.match_no,
            pick=adjusted_pick,
            primary=rec.primary,
            confidence=min(rec.confidence, 0.53),
            risk_tier="bias_adjusted",
            rationale=rationale,
            odds_average=rec.odds_average,
            override_applied=True,
            warnings=[*rec.warnings, "information_bias_check"],
        )

    def _baseline_recommendation(
        self, match: ZucaiMatch, odds: ZucaiOdds | None
    ) -> ZucaiRecommendation:
        rec_warnings: list[str] = []
        odds_average = odds.to_code_dict() if odds is not None else None
        if odds_average is None:
            rec_warnings.append("missing odds")
            primary = "3"
            pick = "31" if any(flag in RISKY_FLAGS for flag in match.risk_flags) else "3"
            return ZucaiRecommendation(
                match_no=match.match_no,
                pick=pick,
                primary=primary,
                confidence=0.4,
                risk_tier="cover" if len(pick) > 1 else "lean",
                rationale="缺少赔率快照，按主场与风险标记给出低信心基线。",
                odds_average=None,
                warnings=rec_warnings,
            )
        primary = min(odds_average, key=odds_average.get)
        fav = odds_average[primary]
        risky = any(flag in RISKY_FLAGS for flag in match.risk_flags)
        if fav <= 1.45 and not risky:
            pick, tier, conf = primary, "banker", 0.74
        elif fav <= 1.62 and not risky:
            pick, tier, conf = primary, "lean", 0.66
        elif fav <= 1.70 and risky:
            pick, tier, conf = normalize_pick(primary + "1"), "cover", 0.61
        elif fav <= 2.05:
            pick, tier, conf = normalize_pick(primary + "1"), "cover", 0.56
        else:
            ordered = sorted(odds_average, key=odds_average.get)[:2]
            pick, tier, conf = normalize_pick("".join(ordered)), "volatile", 0.48
        rationale = (
            f"赔率最低方向为{primary}，结合风险标记：{', '.join(match.risk_flags) or '无'}。"
        )
        return ZucaiRecommendation(
            match_no=match.match_no,
            pick=pick,
            primary=primary,
            confidence=conf,
            risk_tier=tier,
            rationale=rationale,
            odds_average=odds_average,
            warnings=rec_warnings,
        )

    def _build_plans(
        self,
        recommendations: list[ZucaiRecommendation],
        override_plans: list[dict[str, Any]],
    ) -> list[ZucaiPlan]:
        if override_plans:
            return [self._plan_from_code(plan) for plan in override_plans]
        full_code = " ".join(rec.pick for rec in recommendations)
        sorted_for_renjiu = sorted(
            recommendations, key=lambda rec: (-rec.confidence, len(rec.pick))
        )[:9]
        selected = {rec.match_no for rec in sorted_for_renjiu}
        renjiu_code = " ".join(
            rec.pick if rec.match_no in selected else "-" for rec in recommendations
        )
        return [
            self._plan_from_code(
                {
                    "name": "自动均衡14场",
                    "plan_type": "full14",
                    "code": full_code,
                    "note": "按逐场建议生成的全14场复式。",
                }
            ),
            self._plan_from_code(
                {
                    "name": "自动任九",
                    "plan_type": "renjiu",
                    "code": renjiu_code,
                    "note": "按信心排序保留9场。",
                }
            ),
        ]

    def _plan_from_code(self, payload: dict[str, Any]) -> ZucaiPlan:
        code = " ".join(str(payload.get("code") or "").split())
        tokens = code.split()
        selected = [idx for idx, token in enumerate(tokens, start=1) if token != "-"]
        stake_count = 1
        for token in tokens:
            if token == "-":
                continue
            normalized = normalize_pick(token)
            if not normalized:
                normalized = "3"
            stake_count *= len(normalized)
        return ZucaiPlan(
            name=str(payload.get("name") or "Zucai plan"),
            plan_type=str(payload.get("plan_type") or "full14"),
            code=code,
            stake_count=stake_count,
            cost_yuan=stake_count * 2,
            selected_matches=selected,
            note=str(payload.get("note") or ""),
        )

    def _dispatch(
        self, report: ZucaiReport, *, dry_run: bool, caption: str | None = None
    ) -> ZucaiDispatch:
        document_path = report.artifacts.pdf_path
        caption = caption or (
            f"Nutmeg 足彩第{report.issue.issue_id}期14场报告（分析辅助，不保证命中）"
        )
        if not document_path:
            return ZucaiDispatch(
                status="failed", caption=caption, error="PDF artifact is unavailable"
            )
        if dry_run:
            return ZucaiDispatch(
                status="dry_run",
                caption=caption,
                document_path=document_path,
                chat_ids=self._telegram_chat_ids,
            )
        if self._telegram_sender is None or not self._telegram_chat_ids:
            return ZucaiDispatch(
                status="config_missing",
                caption=caption,
                document_path=document_path,
                chat_ids=self._telegram_chat_ids,
            )
        try:
            for chat_id in self._telegram_chat_ids:
                self._telegram_sender.send_document(
                    chat_id=chat_id,
                    document_path=Path(document_path),
                    caption=caption,
                )
        except Exception as exc:
            return ZucaiDispatch(
                status="failed",
                caption=caption,
                document_path=document_path,
                chat_ids=self._telegram_chat_ids,
                error=str(exc),
            )
        return ZucaiDispatch(
            status="sent",
            caption=caption,
            document_path=document_path,
            chat_ids=self._telegram_chat_ids,
        )

    def _resolve_file(self, explicit: Path | str | None, issue_id: str | None, kind: str) -> Path:
        if explicit is not None:
            return Path(explicit)
        if not issue_id:
            raise ZucaiValidationError(f"{kind} file or --issue-id is required")
        candidate = self._sample_dir / f"{issue_id}-{kind}.json"
        if not candidate.exists():
            raise ZucaiValidationError(f"No bundled {kind} sample for issue {issue_id}.")
        return candidate

    def _resolve_optional_file(
        self, explicit: Path | str | None, issue_id: str, kind: str
    ) -> Path | None:
        if explicit is not None:
            return Path(explicit)
        candidate = self._sample_dir / f"{issue_id}-{kind}.json"
        return candidate if candidate.exists() else None

    def _issue_id_from_path(self, issue_file: Path) -> str:
        return issue_file.name.split("-", 1)[0]

    def _match_from_payload(self, item: dict[str, Any]) -> ZucaiMatch:
        try:
            match_no = int(item.get("match_no"))
        except (TypeError, ValueError) as exc:
            raise ZucaiValidationError("match_no must be an integer") from exc
        home = str(item.get("home_team") or "").strip()
        away = str(item.get("away_team") or "").strip()
        if not home or not away:
            raise ZucaiValidationError(f"match {match_no} must include home_team and away_team")
        return ZucaiMatch(
            match_no=match_no,
            competition=str(item.get("competition") or ""),
            home_team=home,
            away_team=away,
            match_date=item.get("match_date"),
            notes=[str(note) for note in item.get("notes") or []],
            risk_flags=[str(flag) for flag in item.get("risk_flags") or []],
        )


def normalize_pick(raw: str) -> str:
    order = ["3", "1", "0"]
    seen = {ch for ch in raw if ch in VALID_CODES}
    if any(ch not in VALID_CODES for ch in raw.strip()):
        return ""
    return "".join(ch for ch in order if ch in seen)


def _has_bias_metadata(payload: dict[str, Any]) -> bool:
    return any(str(payload.get(field) or "").strip() for field in BIAS_METADATA_FIELDS)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ZucaiValidationError(f"Unable to read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ZucaiValidationError(f"Malformed JSON in {path}: {exc}") from exc


def _positive_float(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _xml(text: str) -> str:
    return escape(text).replace("&lt;br/&gt;", "<br/>")


def _table(rows, widths):
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#ccd6e0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table
