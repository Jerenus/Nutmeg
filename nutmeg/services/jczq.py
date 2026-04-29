from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import httpx
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from nutmeg.domain.jczq import (
    JczqMixedReport,
    JczqReportArtifacts,
    JczqReportCombination,
    JczqReportDispatch,
    JczqReportLeg,
)

if TYPE_CHECKING:
    from nutmeg.services.psychology.engine import PsychologyEngine
    from nutmeg.services.psychology.reconciliator import Reconciliator
    from nutmeg.services.psychology.schemas import DualSchemeReport, InspirationNote

SPORTTERY_JCZQ_PAGE = "https://www.sporttery.cn/jc/jsq/zqspf/"
SPORTTERY_JCZQ_API = (
    "https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry"
    "?channel=c&poolCode=had,hhad,ttg,crs,hafu"
)


class JczqReportError(ValueError):
    pass


class JczqProviderError(JczqReportError):
    pass


class JczqSelectionError(JczqReportError):
    pass


class JczqCalculatorProvider(Protocol):
    source_api: str
    source_page: str

    def fetch(self) -> dict[str, Any]: ...


class JczqDocumentSender(Protocol):
    def send_document(self, *, chat_id: int, document_path: Path, caption: str): ...


@dataclass(slots=True, frozen=True)
class PsychologyJczqMixedReport(JczqMixedReport):
    psychology_reports: dict[str, "DualSchemeReport"] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["psychology_reports"] = {
            name: asdict(report) for name, report in self.psychology_reports.items()
        }
        return data


class SportteryJczqCalculatorProvider:
    source_api = SPORTTERY_JCZQ_API
    source_page = SPORTTERY_JCZQ_PAGE

    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        self._timeout_seconds = timeout_seconds

    def fetch(self) -> dict[str, Any]:
        try:
            response = httpx.get(
                self.source_api,
                headers={"Referer": self.source_page, "User-Agent": "Nutmeg/0.2"},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise JczqProviderError(f"Sporttery JCZQ fetch failed: {exc}") from exc
        if str(payload.get("errorCode")) != "0":
            raise JczqProviderError(
                f"Sporttery JCZQ API error: {payload.get('errorCode')} "
                f"{payload.get('errorMessage')}"
            )
        value = payload.get("value")
        if not isinstance(value, dict):
            raise JczqProviderError("Sporttery JCZQ API response missing value object.")
        return value


class SampleJczqCalculatorProvider:
    source_api = "sample://nutmeg/jczq/mixed-calculator-20260426.json"
    source_page = SPORTTERY_JCZQ_PAGE

    def __init__(self, sample_file: Path | None = None) -> None:
        self._sample_file = (
            sample_file
            or Path(__file__).parents[1] / "jczq" / "samples" / "mixed-calculator-20260426.json"
        )

    def fetch(self) -> dict[str, Any]:
        return json.loads(self._sample_file.read_text(encoding="utf-8"))


PROFILE_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "组合A：强队客胜剧本 + 意甲焦点平局",
        "risk": "高赔进取型；主要押强队客胜的细分路径和焦点战平局。",
        "legs": [
            {
                "match_no": "周日020",
                "pool": "hafu",
                "key": "da",
                "play": "半全场",
                "pick": "平/负",
                "logic": "国米客胜热，但都灵主场抗压，半场不败、下半场被拉开更符合赔率结构。",
            },
            {
                "match_no": "周日023",
                "pool": "crs",
                "key": "s00s02",
                "play": "比分",
                "pick": "0:2",
                "logic": "波尔图强弱差明显，直接客胜赔太低，用客队赢两球抬赔率。",
            },
            {
                "match_no": "周日025",
                "pool": "crs",
                "key": "s01s01",
                "play": "比分",
                "pick": "1:1",
                "logic": "AC米兰 vs 尤文三项赔率接近，低比分平局是更稳的高赔入口。",
            },
            {
                "match_no": "周日028",
                "pool": "hhad",
                "key": "d",
                "play": "让球胜平负",
                "pick": "主队+2 让平",
                "logic": "里斯本竞技实力占优，但让平对应客队正好赢2球，赔率比客胜更有弹性。",
            },
        ],
    },
    {
        "name": "组合B：高进球节奏 + 美职拉锯平局",
        "risk": "更激进；用总进球和半全场放大赔率，波动显著高于组合A。",
        "legs": [
            {
                "match_no": "周日012",
                "pool": "ttg",
                "key": "s4",
                "play": "总进球数",
                "pick": "4球",
                "logic": "斯图加特主胜热且德甲节奏偏开放，4球位于进球赔率甜点区。",
            },
            {
                "match_no": "周日019",
                "pool": "ttg",
                "key": "s4",
                "play": "总进球数",
                "pick": "4球",
                "logic": "多特主场进攻强，弗赖堡也有进球能力，4球比单买胜负更有高赔空间。",
            },
            {
                "match_no": "周日024",
                "pool": "ttg",
                "key": "s5",
                "play": "总进球数",
                "pick": "5球",
                "logic": "博德闪耀客场强势，盘口给出明显大球结构，搏高比分节奏。",
            },
            {
                "match_no": "周日029",
                "pool": "hafu",
                "key": "dd",
                "play": "半全场",
                "pick": "平/平",
                "logic": "美职攻防波动大，双方拉锯后平局收场；半全场平/平比胜平负平局赔率更高。",
            },
        ],
    },
]


class JczqMixedReportService:
    def __init__(
        self,
        *,
        provider: JczqCalculatorProvider | None = None,
        telegram_sender: JczqDocumentSender | None = None,
        telegram_chat_ids: list[int] | None = None,
        psychology_engine: "PsychologyEngine | None" = None,
        reconciliator: "Reconciliator | None" = None,
        psychology_inspiration: "InspirationNote | None" = None,
    ) -> None:
        self._provider = provider or SportteryJczqCalculatorProvider()
        self._telegram_sender = telegram_sender
        self._telegram_chat_ids = telegram_chat_ids or []
        self._psychology_engine = psychology_engine
        self._reconciliator = reconciliator
        self._psychology_inspiration = psychology_inspiration

    def build_report(
        self,
        *,
        output_dir: Path | str | None = None,
        render_pdf: bool = False,
        dispatch_telegram: bool = False,
        dry_run: bool = True,
    ) -> JczqMixedReport:
        value = self._provider.fetch()
        combinations = self._build_combinations(value)
        psychology_reports: dict[str, "DualSchemeReport"] = {}
        if self._psychology_engine and self._reconciliator:
            from nutmeg.services.psychology.jczq_adapter import (
                apply_final_scheme_to_combination,
                combination_to_data_scheme,
            )
            from nutmeg.services.psychology.signals.base import SignalContext

            updated_combinations = []
            for combo in combinations:
                data_scheme = combination_to_data_scheme(combo)
                fixtures = [
                    {
                        "id": f"{leg.match_no}:{leg.home_team}:{leg.away_team}",
                        "home_team_name": leg.home_team,
                        "away_team_name": leg.away_team,
                        "competition_code": leg.league,
                    }
                    for leg in combo.legs
                ]
                ctx = SignalContext(
                    date=datetime.now(UTC).date().isoformat(),
                    fixtures=fixtures,
                    snapshots={},
                    odds={},
                )
                data_picks = {leg.fixture_id: {leg.market: leg.outcome} for leg in data_scheme.legs}
                verdicts = self._psychology_engine.evaluate(ctx=ctx, data_picks=data_picks)
                dual = self._reconciliator.reconcile(
                    data_scheme=data_scheme,
                    psychology_verdicts=verdicts,
                    inspiration=self._psychology_inspiration,
                )
                psychology_reports[combo.name] = dual
                updated_combinations.append(
                    apply_final_scheme_to_combination(combo, dual.final_scheme)
                )
            combinations = updated_combinations
        generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        report = self._build_report_model(
            generated_at=generated_at,
            official_last_update=value.get("lastUpdateTime"),
            source_page=self._provider.source_page,
            source_api=self._provider.source_api,
            combinations=combinations,
            psychology_reports=psychology_reports,
        )
        if output_dir is not None:
            artifacts = self.write_artifacts(
                report, output_dir=Path(output_dir), render_pdf=render_pdf or dispatch_telegram
            )
            report = self._replace_report(report, artifacts=artifacts)
        if dispatch_telegram:
            dispatch = self._dispatch(report, dry_run=dry_run)
            report = self._replace_report(report, dispatch=dispatch)
            if report.artifacts.report_json_path:
                Path(report.artifacts.report_json_path).write_text(
                    json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        return report

    def write_artifacts(
        self, report: JczqMixedReport, *, output_dir: Path, render_pdf: bool
    ) -> JczqReportArtifacts:
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        stem = f"jczq-4leg-high-odds-{stamp}"
        markdown_path = output_dir / f"{stem}.md"
        json_path = output_dir / f"{stem}.json"
        pdf_path = output_dir / f"{stem}.pdf"
        markdown_path.write_text(self.render_markdown(report), encoding="utf-8")
        artifacts = JczqReportArtifacts(
            markdown_path=str(markdown_path),
            pdf_path=str(pdf_path) if render_pdf else None,
            report_json_path=str(json_path),
        )
        enriched = self._replace_report(report, artifacts=artifacts)
        json_path.write_text(
            json.dumps(enriched.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if render_pdf:
            self.render_pdf(report, pdf_path=pdf_path)
        return artifacts

    def render_markdown(self, report: JczqMixedReport) -> str:
        lines = [
            "# 今日竞彩足球4关高赔混合投注筛选",
            "",
            f"- 生成时间：{report.generated_at}",
            f"- 官方赔率更新时间：{report.official_last_update}",
            f"- 数据源：中国竞彩网计算器页 {report.source_page}",
            f"- 官方接口：{report.source_api}",
            "- 说明：仅供小注娱乐参考，不保证命中，不构成投注指令。"
            "下单前必须以竞彩终端实时赔率和销售状态为准。",
            "",
        ]
        for combo in report.combinations:
            lines.extend([f"## {combo.name}", "", combo.risk, ""])
            for idx, leg in enumerate(combo.legs, 1):
                goal_line = f"（{leg.goal_line}）" if leg.goal_line else ""
                lines.append(
                    f"{idx}. {leg.match_no} {leg.league} {leg.match_date} {leg.match_time} "
                    f"{leg.home_team} vs {leg.away_team} | {leg.play}{goal_line}："
                    f"{leg.pick} | 赔率 {leg.odds:.2f} | 更新 {leg.odds_update}"
                )
                lines.append(f"   - 逻辑：{leg.logic}")
            lines.extend(
                [
                    "",
                    f"- 估算总赔率：{combo.total_odds:.2f}",
                    f"- 2元理论返奖：{combo.two_yuan_return:.2f}元",
                    "",
                ]
            )
            psychology_reports = getattr(report, "psychology_reports", {})
            psychology_dual = psychology_reports.get(combo.name) if psychology_reports else None
            if psychology_dual:
                lines.extend(
                    [
                        "",
                        "### 三栏诊断板",
                        "",
                        "| 比赛 | 数据 | 心理 | 冲突 | 最终 | 信心 |",
                        "|---|---|---|---|---|---|",
                    ]
                )
                for row in psychology_dual.dashboard_rows:
                    conflict = "✓" if row.conflict else "·"
                    lines.append(
                        f"| {row.fixture_id} | {row.data_pick} | {row.psych_pick or '—'} | "
                        f"{conflict} | {row.final_pick} | {row.conviction:.2f} |"
                    )
                lines.extend(["", "### 数据驱动方案", ""])
                for leg in psychology_dual.data_scheme.legs:
                    lines.append(
                        f"- {leg.fixture_id}: {leg.market} → {leg.outcome} @ {leg.odds:.2f}"
                    )
                lines.extend(["", "### 心理博弈方案", ""])
                for leg in psychology_dual.psychology_scheme.legs:
                    lines.append(
                        f"- {leg.fixture_id}: {leg.market} → {leg.outcome} @ {leg.odds:.2f}"
                    )
                lines.extend(["", "### 当日决策", ""])
                for leg in psychology_dual.final_scheme.legs:
                    lines.append(
                        f"- {leg.fixture_id}: {leg.market} → {leg.outcome} @ {leg.odds:.2f} "
                        f"(来源: {leg.provenance})"
                    )
                lines.append(f"- 信心: {psychology_dual.final_scheme.confidence}")
                lines.append(f"- guardrail: {psychology_dual.guardrail.guardrail_state}")
                if psychology_dual.guardrail.rejected:
                    lines.append("- 拒绝的反转候选:")
                    for cand, reason in psychology_dual.guardrail.rejected:
                        lines.append(
                            f"  - {cand.fixture_id} {cand.from_outcome}→{cand.to_outcome}: {reason}"
                        )
                if psychology_dual.inspiration:
                    tags = psychology_dual.inspiration.parsed_tags
                    lines.append(f"- 灵感笔记: lean={tags.lean}, focus={tags.focus}")
        lines.append("风险提示：4关高赔命中率天然较低，请勿追损或加倍。")
        return "\n".join(lines)

    def render_pdf(self, report: JczqMixedReport, *, pdf_path: Path) -> None:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=16 * mm,
            bottomMargin=14 * mm,
        )
        styles = getSampleStyleSheet()
        title = ParagraphStyle(
            "JczqTitle",
            parent=styles["Title"],
            fontName="STSong-Light",
            fontSize=18,
            leading=24,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#7a1f12"),
        )
        h2 = ParagraphStyle(
            "JczqH2",
            parent=styles["Heading2"],
            fontName="STSong-Light",
            fontSize=13,
            leading=18,
            textColor=colors.HexColor("#0f5132"),
            spaceBefore=8,
        )
        body = ParagraphStyle(
            "JczqBody", parent=styles["BodyText"], fontName="STSong-Light", fontSize=9.5, leading=14
        )
        small = ParagraphStyle(
            "JczqSmall",
            parent=body,
            fontSize=8.2,
            leading=12,
            textColor=colors.HexColor("#555555"),
        )
        cell = ParagraphStyle("JczqCell", parent=body, fontSize=8.5, leading=11)
        story = [
            Paragraph("今日竞彩足球4关高赔混合投注筛选", title),
            Spacer(1, 5 * mm),
            Paragraph(
                f"官方赔率更新时间：{_esc(report.official_last_update)}；定位：两组4关高赔混合过关，小注娱乐参考。",
                body,
            ),
            Paragraph(
                "不保证命中，不构成投注指令；下单前以竞彩终端实时赔率和销售状态为准。",
                body,
            ),
            Paragraph(
                f"数据源：{_esc(report.source_page)}；接口：{_esc(report.source_api)}",
                small,
            ),
            Spacer(1, 4 * mm),
        ]
        for combo in report.combinations:
            story.append(Paragraph(_esc(combo.name), h2))
            story.append(Paragraph(_esc(combo.risk), body))
            data = [
                [
                    Paragraph("场次", cell),
                    Paragraph("赛事/对阵", cell),
                    Paragraph("玩法", cell),
                    Paragraph("选择", cell),
                    Paragraph("赔率", cell),
                    Paragraph("逻辑", cell),
                ]
            ]
            for leg in combo.legs:
                data.append(
                    [
                        Paragraph(_esc(f"{leg.match_no}\n{leg.match_date} {leg.match_time}"), cell),
                        Paragraph(_esc(f"{leg.league}\n{leg.home_team} vs {leg.away_team}"), cell),
                        Paragraph(_esc(f"{leg.play} {leg.goal_line}".strip()), cell),
                        Paragraph(_esc(leg.pick), cell),
                        Paragraph(f"{leg.odds:.2f}", cell),
                        Paragraph(_esc(leg.logic), cell),
                    ]
                )
            table = Table(
                data,
                colWidths=[23 * mm, 33 * mm, 25 * mm, 22 * mm, 16 * mm, 61 * mm],
                repeatRows=1,
            )
            table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3ead7")),
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d7cab0")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(table)
            story.append(Spacer(1, 2 * mm))
            story.append(
                Paragraph(
                    f"估算总赔率：{combo.total_odds:.2f}；2元理论返奖：{combo.two_yuan_return:.2f}元",
                    body,
                )
            )
            story.append(Spacer(1, 5 * mm))
        story.append(Paragraph("风险提示：4关高赔命中率天然较低，请勿追损或加倍。", small))
        doc.build(story)

    def _build_combinations(self, value: dict[str, Any]) -> list[JczqReportCombination]:
        matches = _flatten_matches(value)
        combinations = []
        for profile in PROFILE_DEFINITIONS:
            legs = [
                self._build_leg(matches=matches, definition=definition)
                for definition in profile["legs"]
            ]
            product = 1.0
            for leg in legs:
                product *= leg.odds
            combinations.append(
                JczqReportCombination(
                    name=profile["name"],
                    risk=profile["risk"],
                    legs=legs,
                    total_odds=round(product, 2),
                    two_yuan_return=round(product * 2, 2),
                )
            )
        return combinations

    def _build_leg(
        self, *, matches: dict[str, dict[str, Any]], definition: dict[str, str]
    ) -> JczqReportLeg:
        match_no = definition["match_no"]
        match = matches.get(match_no)
        if not match:
            raise JczqSelectionError(f"JCZQ match not found: {match_no}")
        if match.get("matchStatus") != "Selling":
            raise JczqSelectionError(f"JCZQ match is not selling: {match_no}")
        pool = definition["pool"]
        status = _pool_status(match, pool)
        if status.get("poolStatus") != "Selling":
            raise JczqSelectionError(f"JCZQ pool is not selling: {match_no} {pool}")
        pool_payload = match.get(pool) or {}
        raw_odds = pool_payload.get(definition["key"])
        if raw_odds in (None, ""):
            raise JczqSelectionError(f"JCZQ odds missing: {match_no} {pool}.{definition['key']}")
        odds = round(float(raw_odds), 2)
        odds_update = " ".join(
            item
            for item in [pool_payload.get("updateDate"), pool_payload.get("updateTime")]
            if item
        )
        return JczqReportLeg(
            match_no=match_no,
            match_date=str(match.get("matchDate") or ""),
            match_time=str(match.get("matchTime") or "")[:5],
            league=str(match.get("leagueAbbName") or ""),
            home_team=str(match.get("homeTeamAbbName") or ""),
            away_team=str(match.get("awayTeamAbbName") or ""),
            pool=pool,
            play=definition["play"],
            pick=definition["pick"],
            odds=odds,
            logic=definition["logic"],
            goal_line=str(pool_payload.get("goalLine") or ""),
            single=_optional_int(status.get("single")),
            all_up=_optional_int(status.get("allUp")),
            odds_update=odds_update,
        )

    def _dispatch(self, report: JczqMixedReport, *, dry_run: bool) -> JczqReportDispatch:
        caption = (
            "今日竞彩足球4关高赔混合投注筛选 PDF。仅供小注娱乐参考，不保证命中；"
            "下单前请以竞彩终端实时赔率为准。"
        )
        if not report.artifacts.pdf_path:
            return JczqReportDispatch(
                status="failed", caption=caption, error="PDF artifact missing"
            )
        if dry_run:
            return JczqReportDispatch(
                status="dry_run", caption=caption, chat_ids=list(self._telegram_chat_ids)
            )
        if self._telegram_sender is None or not self._telegram_chat_ids:
            return JczqReportDispatch(
                status="failed",
                caption=caption,
                error="Telegram sender or allowed chat ids are unavailable",
            )
        try:
            for chat_id in self._telegram_chat_ids:
                self._telegram_sender.send_document(
                    chat_id=chat_id, document_path=Path(report.artifacts.pdf_path), caption=caption
                )
        except Exception as exc:  # pragma: no cover - defensive external boundary
            return JczqReportDispatch(status="failed", caption=caption, error=str(exc))
        return JczqReportDispatch(
            status="sent", caption=caption, chat_ids=list(self._telegram_chat_ids)
        )

    def _replace_report(
        self,
        report: JczqMixedReport,
        *,
        artifacts: JczqReportArtifacts | None = None,
        dispatch: JczqReportDispatch | None = None,
    ) -> JczqMixedReport:
        return self._build_report_model(
            generated_at=report.generated_at,
            official_last_update=report.official_last_update,
            source_page=report.source_page,
            source_api=report.source_api,
            combinations=report.combinations,
            artifacts=artifacts or report.artifacts,
            dispatch=dispatch or report.dispatch,
            warnings=report.warnings,
            psychology_reports=getattr(report, "psychology_reports", {}),
        )

    def _build_report_model(
        self,
        *,
        generated_at: str,
        official_last_update: str | None,
        source_page: str,
        source_api: str,
        combinations: list[JczqReportCombination],
        artifacts: JczqReportArtifacts | None = None,
        dispatch: JczqReportDispatch | None = None,
        warnings: list[str] | None = None,
        psychology_reports: dict[str, "DualSchemeReport"] | None = None,
    ) -> JczqMixedReport:
        common = {
            "generated_at": generated_at,
            "official_last_update": official_last_update,
            "source_page": source_page,
            "source_api": source_api,
            "combinations": combinations,
            "artifacts": artifacts or JczqReportArtifacts(),
            "dispatch": dispatch or JczqReportDispatch(),
            "warnings": warnings or [],
        }
        if psychology_reports:
            return PsychologyJczqMixedReport(
                **common,
                psychology_reports=psychology_reports,
            )
        return JczqMixedReport(**common)


def _flatten_matches(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    matches: dict[str, dict[str, Any]] = {}
    for group in value.get("matchInfoList") or []:
        for match in group.get("subMatchList") or []:
            match_no = match.get("matchNumStr")
            if match_no:
                matches[str(match_no)] = match
    return matches


def _pool_status(match: dict[str, Any], pool: str) -> dict[str, Any]:
    code = pool.upper()
    for item in match.get("poolList") or []:
        if item.get("poolCode") == code:
            return item
    return {}


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _esc(value: Any) -> str:
    return escape(str(value), quote=False)
