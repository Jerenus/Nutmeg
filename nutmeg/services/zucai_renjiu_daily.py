from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from nutmeg.domain.zucai import ZucaiIssue, ZucaiMatch, ZucaiOdds
from nutmeg.domain.zucai_renjiu import (
    RenjiuArtifacts,
    RenjiuDailyReport,
    RenjiuDispatch,
    RenjiuMatchAnalysis,
    RenjiuTicket,
)
from nutmeg.services.zucai import ZucaiWorkflowService
from nutmeg.services.zucai_value_bridge import ZucaiValueReport

logger = logging.getLogger(__name__)


class ZucaiRenjiuValidationError(ValueError):
    pass


class RenjiuDocumentSender(Protocol):
    def send_document(self, *, chat_id: int, document_path: Path, caption: str): ...


class RenjiuValueBridge(Protocol):
    """Anything that turns a Zucai issue into a per-match had conflict report.

    The production ``ZucaiValueBridge`` satisfies this; tests inject a stub so
    no network is touched. Wiring is optional — a missing/failing bridge just
    means the report renders without conflict annotations.
    """

    def evaluate_issue(self, issue) -> ZucaiValueReport: ...


PICK_ORDER = "310"
TICKET_LABELS = {
    "conservative": "保守票",
    "main": "主推票",
    "aggressive": "进攻票",
}


class ZucaiRenjiuDailyService:
    def __init__(
        self,
        *,
        telegram_sender: RenjiuDocumentSender | None = None,
        telegram_chat_ids: list[int] | None = None,
        registry_file: Path | str = Path(".nutmeg-data/zucai/issues.json"),
    ) -> None:
        self._telegram_sender = telegram_sender
        self._telegram_chat_ids = telegram_chat_ids or []
        self._registry_file = Path(registry_file)
        self._zucai = ZucaiWorkflowService()

    def build_report(
        self,
        *,
        run_date: str | None = None,
        issue_id: str | None = None,
        issue_file: Path | str | None = None,
        odds_file: Path | str | None = None,
        output_dir: Path | str,
        render_pdf: bool = False,
        dispatch_telegram: bool = False,
        dry_run: bool = True,
        value_bridge: RenjiuValueBridge | None = None,
    ) -> RenjiuDailyReport:
        resolved_date = _normalize_date(run_date)
        resolved_issue_file, resolved_odds_file = self._resolve_inputs(
            run_date=resolved_date,
            issue_id=issue_id,
            issue_file=Path(issue_file) if issue_file is not None else None,
            odds_file=Path(odds_file) if odds_file is not None else None,
            output_dir=Path(output_dir),
        )
        issue = self._load_issue(resolved_issue_file)
        odds_by_match, odds_payload = self._load_odds(resolved_odds_file)
        warnings: list[str] = []
        conflict_signals = self._evaluate_conflicts(issue, value_bridge, warnings)
        analyses = self._analyze_matches(issue, odds_by_match, conflict_signals)
        least_confident = [item.match_no for item in sorted(
            analyses, key=lambda item: item.uncertainty_score, reverse=True
        )[:5]]
        tickets = self._build_tickets(analyses, least_confident)
        generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        sources = [*issue.sources, *list(odds_payload.get("sources") or [])]
        report = RenjiuDailyReport(
            run_date=resolved_date,
            issue_id=issue.issue_id,
            generated_at=generated_at,
            sale_stop=issue.sale_stop,
            odds_captured_at=odds_payload.get("captured_at"),
            match_analysis=analyses,
            least_confident_matches=least_confident,
            tickets=tickets,
            recommended_ticket_id="main",
            artifacts=RenjiuArtifacts(),
            dispatch=RenjiuDispatch(status="skipped"),
            sources=sources,
            warnings=warnings,
        )
        artifacts = self._write_artifacts(
            report,
            output_dir=Path(output_dir),
            issue_path=resolved_issue_file,
            odds_path=resolved_odds_file,
            render_pdf=render_pdf or dispatch_telegram,
        )
        report = replace(report, artifacts=artifacts)
        if dispatch_telegram:
            dispatch = self._dispatch(report, dry_run=dry_run)
            report = replace(report, dispatch=dispatch)
            if artifacts.json_path:
                Path(artifacts.json_path).write_text(
                    json.dumps(report.to_dict(), ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
        return report

    def _resolve_inputs(
        self,
        *,
        run_date: str,
        issue_id: str | None,
        issue_file: Path | None,
        odds_file: Path | None,
        output_dir: Path,
    ) -> tuple[Path, Path]:
        if issue_file is not None and odds_file is not None:
            return issue_file, odds_file
        registry_entries = _load_registry_entries(self._registry_file)
        selected = None
        for entry in registry_entries:
            if issue_id and str(entry.get("issue_id")) != str(issue_id):
                continue
            if issue_id or run_date in [str(value) for value in entry.get("active_dates") or []]:
                selected = entry
                break
        if selected is None:
            raise ZucaiRenjiuValidationError(
                f"No active Zucai issue found for {run_date}; provide --issue-file and --odds-file."
            )
        base_dir = self._registry_file.parent if self._registry_file.exists() else output_dir
        resolved_issue = issue_file or base_dir / str(selected.get("issue_file") or "")
        odds_value = selected.get("revision_odds_file") or selected.get("odds_file")
        resolved_odds = odds_file or base_dir / str(odds_value or "")
        if not resolved_issue.exists():
            raise ZucaiRenjiuValidationError(f"issue file not found: {resolved_issue}")
        if not resolved_odds.exists():
            raise ZucaiRenjiuValidationError(f"odds file not found: {resolved_odds}")
        return resolved_issue, resolved_odds

    def _load_issue(self, issue_file: Path) -> ZucaiIssue:
        try:
            return self._zucai.load_issue(issue_file)
        except Exception as exc:
            raise ZucaiRenjiuValidationError(str(exc)) from exc

    def _load_odds(self, odds_file: Path) -> tuple[dict[int, ZucaiOdds], dict[str, Any]]:
        payload = _read_json(odds_file)
        rows = payload.get("matches") or []
        odds_by_match: dict[int, ZucaiOdds] = {}
        for row in rows:
            odds = ZucaiOdds(
                match_no=int(row["match_no"]),
                home=float(row["home"]),
                draw=float(row["draw"]),
                away=float(row["away"]),
                providers=list(row.get("providers") or []),
            )
            odds_by_match[odds.match_no] = odds
        if sorted(odds_by_match) != list(range(1, 15)):
            raise ZucaiRenjiuValidationError("Zucai odds must contain exactly 14 matches.")
        return odds_by_match, payload

    def _evaluate_conflicts(
        self,
        issue: ZucaiIssue,
        value_bridge: RenjiuValueBridge | None,
        warnings: list[str],
    ) -> dict[int, dict[str, Any]]:
        """Run the value bridge → {match_no: had-signal dict}.

        Graceful degradation is the contract: no bridge wired, or any failure
        evaluating it, yields an empty mapping — the report still renders, just
        without conflict annotations. The existing pick algorithm is untouched.
        """
        if value_bridge is None:
            return {}
        try:
            value_report = value_bridge.evaluate_issue(issue)
        except Exception as exc:  # noqa: BLE001 — degrade, never crash the report
            logger.warning("zucai value bridge failed — degrading: %s", exc)
            warnings.append(f"冲突引擎不可用，逐场注解已跳过：{exc}")
            return {}
        signals: dict[int, dict[str, Any]] = {}
        for entry in value_report.matches:
            if entry.had_signal is not None:
                signals[entry.match_no] = entry.had_signal.to_dict()
        return signals

    def _analyze_matches(
        self,
        issue: ZucaiIssue,
        odds_by_match: dict[int, ZucaiOdds],
        conflict_signals: dict[int, dict[str, Any]] | None = None,
    ) -> list[RenjiuMatchAnalysis]:
        conflict_signals = conflict_signals or {}
        analyses: list[RenjiuMatchAnalysis] = []
        for match in issue.matches:
            odds = odds_by_match.get(match.match_no)
            if odds is None or odds.to_code_dict() is None:
                raise ZucaiRenjiuValidationError(f"missing complete odds for match {match.match_no}")
            code_odds = odds.to_code_dict() or {}
            primary = min(code_odds, key=lambda code: code_odds[code])
            suggested = _double_pick(code_odds)
            score, labels = _uncertainty_score(code_odds)
            rationale = _rationale(primary, suggested, labels)
            analyses.append(
                RenjiuMatchAnalysis(
                    match_no=match.match_no,
                    competition=match.competition,
                    home_team=match.home_team,
                    away_team=match.away_team,
                    odds=code_odds,
                    primary_pick=primary,
                    suggested_pick=suggested,
                    uncertainty_score=score,
                    risk_labels=labels,
                    rationale=rationale,
                    conflict_signal=conflict_signals.get(match.match_no),
                )
            )
        return analyses

    def _build_tickets(
        self,
        analyses: list[RenjiuMatchAnalysis],
        least_confident: list[int],
    ) -> list[RenjiuTicket]:
        by_no = {item.match_no: item for item in analyses}
        omitted = set(least_confident)
        selected = [item.match_no for item in analyses if item.match_no not in omitted]
        selected_by_uncertainty = sorted(
            selected,
            key=lambda no: by_no[no].uncertainty_score,
            reverse=True,
        )
        return [
            self._ticket(
                ticket_id="conservative",
                selected=selected,
                coverage_matches=set(selected_by_uncertainty[:5]),
                triple_matches=set(),
                analyses=by_no,
                note="64元左右保守底仓：剔除最难5场，给5个保留场防平/防冷。",
            ),
            self._ticket(
                ticket_id="main",
                selected=selected,
                coverage_matches=set(selected_by_uncertainty[:6]),
                triple_matches=set(),
                analyses=by_no,
                note="100-200元主推：在保守票基础上增加一个关键保护点。",
            ),
            self._ticket(
                ticket_id="aggressive",
                selected=selected,
                coverage_matches=set(selected_by_uncertainty[:7]),
                triple_matches={selected_by_uncertainty[0]} if selected_by_uncertainty else set(),
                analyses=by_no,
                note="200-400元进攻票：主推结构不变，最有分歧的一场全包。",
            ),
        ]

    def _ticket(
        self,
        *,
        ticket_id: str,
        selected: list[int],
        coverage_matches: set[int],
        triple_matches: set[int],
        analyses: dict[int, RenjiuMatchAnalysis],
        note: str,
    ) -> RenjiuTicket:
        selected_set = set(selected)
        picks: list[str] = []
        for no in range(1, 15):
            if no not in selected_set:
                picks.append("-")
                continue
            analysis = analyses[no]
            if no in triple_matches:
                picks.append("310")
            elif no in coverage_matches:
                picks.append(analysis.suggested_pick)
            else:
                picks.append(analysis.primary_pick)
        stake_count = _stake_count(picks)
        return RenjiuTicket(
            ticket_id=ticket_id,
            name=TICKET_LABELS[ticket_id],
            picks=picks,
            omitted_matches=[no for no in range(1, 15) if no not in selected_set],
            stake_count=stake_count,
            cost_yuan=stake_count * 2,
            note=note,
        )

    def _write_artifacts(
        self,
        report: RenjiuDailyReport,
        *,
        output_dir: Path,
        issue_path: Path,
        odds_path: Path,
        render_pdf: bool,
    ) -> RenjiuArtifacts:
        run_dir = output_dir / "daily" / report.run_date / "renjiu"
        run_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = run_dir / "analysis.md"
        json_path = run_dir / "analysis.json"
        context_path = run_dir / "context.json"
        pdf_path = run_dir / "analysis.pdf"
        markdown_path.write_text(self.render_markdown(report), encoding="utf-8")
        context_path.write_text(
            json.dumps(
                {
                    "issue_path": str(issue_path),
                    "odds_path": str(odds_path),
                    "report": report.to_dict(),
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        artifacts = RenjiuArtifacts(
            markdown_path=str(markdown_path),
            json_path=str(json_path),
            pdf_path=str(pdf_path) if render_pdf else None,
            context_path=str(context_path),
        )
        enriched = replace(report, artifacts=artifacts)
        json_path.write_text(
            json.dumps(enriched.to_dict(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        if render_pdf:
            self.render_pdf(enriched, pdf_path=pdf_path)
        return artifacts

    def render_markdown(self, report: RenjiuDailyReport) -> str:
        lines = [
            f"# Nutmeg 任九日报 — 第{report.issue_id}期",
            "",
            f"- 日期：{report.run_date}",
            f"- 停售：{report.sale_stop or '未知'}",
            f"- 赔率快照：{report.odds_captured_at or '未知'}",
            "- 记号：3=主胜，1=平，0=客胜，-=任九剔除",
            "- 风险提示：娱乐型分析，不保证命中，不构成投注指令。",
            "",
            "## 三档方案",
        ]
        for ticket in report.tickets:
            marker = "（推荐）" if ticket.ticket_id == report.recommended_ticket_id else ""
            lines.extend(
                [
                    "",
                    f"### {ticket.name}{marker}",
                    f"`{ticket.code}`",
                    f"- {ticket.stake_count}注 / {ticket.cost_yuan}元",
                    f"- 剔除：{', '.join(str(no) for no in ticket.omitted_matches)}",
                    f"- {ticket.note}",
                ]
            )
        lines.extend(["", "## 最没把握的5场", ""])
        for no in report.least_confident_matches:
            item = next(match for match in report.match_analysis if match.match_no == no)
            lines.append(f"- {no}. {item.home_team} vs {item.away_team}：{item.rationale}")
        lines.extend(["", "## 逐场判断", ""])
        for item in report.match_analysis:
            lines.append(
                f"- {item.match_no}. {item.home_team} vs {item.away_team} "
                f"赔率3/1/0={item.odds['3']:.2f}/{item.odds['1']:.2f}/{item.odds['0']:.2f} "
                f"主选={item.primary_pick} 建议覆盖={item.suggested_pick} 风险={','.join(item.risk_labels) or '常规'}"
            )
            verdict = _conflict_verdict(item.conflict_signal)
            if verdict:
                lines.append(f"    - 冲突引擎：{verdict}")
        if any(item.conflict_signal for item in report.match_analysis):
            lines.append("")
            lines.append(
                "> 「冲突引擎」是 Dixon-Coles 模型 vs 国际市场赔率的逐场 1X2 对照，"
                "供人工/debate 额外权衡，不改变上方三档方案的选号。"
            )
        return "\n".join(lines) + "\n"

    def render_pdf(self, report: RenjiuDailyReport, *, pdf_path: Path) -> None:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        styles = getSampleStyleSheet()
        body = ParagraphStyle("RenjiuBody", parent=styles["Normal"], fontName="STSong-Light", fontSize=8.2, leading=10.5)
        title = ParagraphStyle("RenjiuTitle", parent=body, fontSize=16, leading=20, alignment=TA_CENTER, textColor=colors.HexColor("#4c3018"))
        h2 = ParagraphStyle("RenjiuH2", parent=body, fontSize=11.5, leading=14, textColor=colors.HexColor("#7a3f12"), spaceBefore=4 * mm)
        small = ParagraphStyle("RenjiuSmall", parent=body, fontSize=7, leading=9, textColor=colors.HexColor("#555555"))
        cell = ParagraphStyle("RenjiuCell", parent=body, fontSize=6.7, leading=8.4)

        def para(value: object, style=body) -> Paragraph:
            return Paragraph(escape(str(value)), style)

        story = [
            para(f"Nutmeg 任九日报 — 第{report.issue_id}期", title),
            para(
                f"日期：{report.run_date}；停售：{report.sale_stop or '未知'}；赔率：{report.odds_captured_at or '未知'}",
                small,
            ),
            para("娱乐型分析，不保证命中，不构成投注指令。", small),
            Spacer(1, 2 * mm),
            para("三档方案", h2),
        ]
        ticket_rows = [[para("票", cell), para("投注串", cell), para("金额", cell), para("剔除", cell), para("说明", cell)]]
        for ticket in report.tickets:
            name = ticket.name + ("（推荐）" if ticket.ticket_id == report.recommended_ticket_id else "")
            ticket_rows.append([
                para(name, cell),
                para(ticket.code, cell),
                para(f"{ticket.stake_count}注/{ticket.cost_yuan}元", cell),
                para(",".join(str(no) for no in ticket.omitted_matches), cell),
                para(ticket.note, cell),
            ])
        story.append(_table(ticket_rows, [22 * mm, 55 * mm, 24 * mm, 22 * mm, 55 * mm]))
        story.append(para("逐场判断", h2))
        rows = [[
            para("场", cell), para("对阵", cell), para("赔率3/1/0", cell),
            para("主选", cell), para("覆盖", cell), para("风险", cell),
            para("冲突引擎", cell),
        ]]
        for item in report.match_analysis:
            rows.append([
                para(item.match_no, cell),
                para(f"{item.home_team} vs {item.away_team}", cell),
                para(f"{item.odds['3']:.2f}/{item.odds['1']:.2f}/{item.odds['0']:.2f}", cell),
                para(item.primary_pick, cell),
                para(item.suggested_pick, cell),
                para(",".join(item.risk_labels) or "常规", cell),
                para(_conflict_verdict(item.conflict_signal) or "—", cell),
            ])
        story.append(_table(rows, [8 * mm, 38 * mm, 24 * mm, 11 * mm, 12 * mm, 38 * mm, 53 * mm]))
        SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            leftMargin=11 * mm,
            rightMargin=11 * mm,
            topMargin=11 * mm,
            bottomMargin=11 * mm,
        ).build(story)

    def _dispatch(self, report: RenjiuDailyReport, *, dry_run: bool) -> RenjiuDispatch:
        caption = (
            f"Nutmeg 任九第{report.issue_id}期三档方案。主推："
            f"{_ticket_by_id(report, report.recommended_ticket_id).code}。仅供娱乐参考。"
        )
        if not report.artifacts.pdf_path:
            return RenjiuDispatch(status="failed", caption=caption, error="PDF artifact missing")
        if dry_run:
            return RenjiuDispatch(
                status="dry_run",
                caption=caption,
                document_path=report.artifacts.pdf_path,
                chat_ids=list(self._telegram_chat_ids),
            )
        if self._telegram_sender is None or not self._telegram_chat_ids:
            return RenjiuDispatch(
                status="failed",
                caption=caption,
                document_path=report.artifacts.pdf_path,
                error="Telegram sender or chat ids unavailable",
            )
        try:
            for chat_id in self._telegram_chat_ids:
                self._telegram_sender.send_document(
                    chat_id=chat_id,
                    document_path=Path(report.artifacts.pdf_path),
                    caption=caption,
                )
        except Exception as exc:  # pragma: no cover - network seam
            return RenjiuDispatch(
                status="failed",
                caption=caption,
                document_path=report.artifacts.pdf_path,
                chat_ids=list(self._telegram_chat_ids),
                error=str(exc),
            )
        return RenjiuDispatch(
            status="sent",
            caption=caption,
            document_path=report.artifacts.pdf_path,
            chat_ids=list(self._telegram_chat_ids),
        )


class ZucaiRenjiuBotWorkflow:
    def __init__(
        self,
        *,
        service: ZucaiRenjiuDailyService,
        output_dir: Path = Path(".nutmeg-data/zucai"),
        dispatch_telegram: bool = True,
        dry_run: bool = False,
        value_bridge_factory: Any | None = None,
    ) -> None:
        self._service = service
        self._output_dir = output_dir
        self._dispatch_telegram = dispatch_telegram
        self._dry_run = dry_run
        # Optional callable(run_date) -> RenjiuValueBridge | None. The bot path
        # stays graceful: a missing factory or a None result just means the
        # dispatched report carries no per-match conflict annotations.
        self._value_bridge_factory = value_bridge_factory

    def run(self) -> dict[str, Any]:
        try:
            value_bridge = None
            if self._value_bridge_factory is not None:
                try:
                    value_bridge = self._value_bridge_factory("today")
                except Exception as exc:  # noqa: BLE001 — degrade, never crash
                    logger.warning("renjiu bot value bridge factory failed: %s", exc)
            report = self._service.build_report(
                run_date="today",
                output_dir=self._output_dir,
                dispatch_telegram=self._dispatch_telegram,
                dry_run=self._dry_run,
                value_bridge=value_bridge,
            )
        except ZucaiRenjiuValidationError as exc:
            return {
                "status": "failed",
                "text": str(exc),
                "payload": {"status": "failed", "error": str(exc)},
                "error": str(exc),
            }
        ticket = _ticket_by_id(report, report.recommended_ticket_id)
        text = "\n".join([
            f"任九第{report.issue_id}期三档方案已生成。",
            f"主推：{ticket.code}（{ticket.stake_count}注/{ticket.cost_yuan}元）",
            f"PDF：{report.artifacts.pdf_path}",
            f"dispatch={report.dispatch.status}",
        ])
        return {"status": "succeeded", "text": text, "payload": report.to_dict()}


def _table(rows: list[list[Paragraph]], widths: list[float]) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4ead8")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d5c3a8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.2),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
    ]))
    return table


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ZucaiRenjiuValidationError(f"unable to read JSON file {path}: {exc}") from exc


def _load_registry_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = _read_json(path)
    entries = payload.get("entries") or []
    return [dict(entry) for entry in entries if entry.get("enabled", True)]


def _normalize_date(value: str | None) -> str:
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if value is None or value == "today":
        return today.isoformat()
    if value == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    return value


def _uncertainty_score(odds: dict[str, float]) -> tuple[float, list[str]]:
    ordered = sorted(odds.items(), key=lambda item: item[1])
    minimum = ordered[0][1]
    second = ordered[1][1]
    spread = max(odds.values()) - minimum
    labels: list[str] = []
    score = 0.0
    if spread < 0.80:
        score += 3.0
        labels.append("三项接近")
    if second - minimum < 0.45:
        score += 2.0
        labels.append("热门不硬")
    if odds["1"] <= 3.20:
        score += 1.5
        labels.append("平局低位")
    if 1.75 <= minimum <= 2.05:
        score += 1.0
        labels.append("舒服盘")
    if minimum <= 1.55:
        score -= 0.8
        labels.append("低赔强势")
    return round(score, 3), labels or ["常规"]


def _double_pick(odds: dict[str, float]) -> str:
    primary = min(odds, key=lambda code: odds[code])
    if odds["1"] <= 3.25 and primary != "1":
        return _ordered_pick({primary, "1"})
    second = sorted(odds, key=lambda code: odds[code])[1]
    return _ordered_pick({primary, second})


def _ordered_pick(codes: set[str]) -> str:
    return "".join(code for code in PICK_ORDER if code in codes)


def _stake_count(picks: list[str]) -> int:
    stake = 1
    for pick in picks:
        if pick != "-":
            stake *= len(pick)
    return stake


def _rationale(primary: str, suggested: str, labels: list[str]) -> str:
    label_text = "、".join(labels)
    if suggested != primary:
        return f"主方向{primary}，但{label_text}，建议覆盖{suggested}。"
    return f"主方向{primary}，风险标签：{label_text}。"


def _conflict_verdict(signal: dict[str, Any] | None) -> str:
    """The had conflict signal's verdict string, or "" when there is no signal.

    The verdict is composed by ``ZucaiValueBridge`` (the signal's source of
    truth); callers that get "" render no annotation for that match.
    """
    if not signal:
        return ""
    return str(signal.get("verdict") or "").strip()


def _ticket_by_id(report: RenjiuDailyReport, ticket_id: str) -> RenjiuTicket:
    for ticket in report.tickets:
        if ticket.ticket_id == ticket_id:
            return ticket
    raise KeyError(ticket_id)
