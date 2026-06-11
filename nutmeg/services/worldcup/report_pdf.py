"""世界杯 PDF 日报排版(spec §5)— ReportLab + matplotlib PNG 嵌入。

七节版面:报头/今日主线/今日看点/投注决策/赛事预测/昨日战报/尾注。
缺哪节标注哪节,报告必须能出(spec §7)。字体注册复用 jczq_final_plan_pdf。
"""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from nutmeg.services.jczq_final_plan_pdf import _register_cjk_font, _xml

from .report_data import DailyReport

logger = logging.getLogger(__name__)

ACCENT = colors.HexColor("#1a6b54")
TIER_NOTE = "档位定性:A=唯一可能有结构 edge 的桶;B/D/E=纯方差娱乐,零 edge;空仓永远合法。"


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    body = ParagraphStyle("WcBody", parent=base["BodyText"],
                          fontName="NutmegCJK", fontSize=9.5, leading=14)
    return {
        "title": ParagraphStyle("WcTitle", parent=base["Title"],
                                fontName="NutmegCJK", fontSize=20, leading=26,
                                textColor=ACCENT, alignment=TA_CENTER),
        "h2": ParagraphStyle("WcH2", parent=base["Heading2"],
                             fontName="NutmegCJK", fontSize=13, leading=17,
                             textColor=ACCENT, spaceBefore=10, spaceAfter=4),
        "body": body,
        "narrative": ParagraphStyle("WcNarrative", parent=body, fontSize=10.5,
                                    leading=17, leftIndent=4 * mm,
                                    borderPadding=6),
        "small": ParagraphStyle("WcSmall", parent=body, fontSize=8, leading=11,
                                textColor=colors.grey),
        "mono": ParagraphStyle("WcMono", parent=body, fontSize=8.5, leading=12),
    }


def _packet_section(md: str, header_prefix: str) -> str:
    """从 today-packet.md 抽一节原文(如 '## A.'),抽不到返回空串。"""
    pattern = re.compile(
        rf"^{re.escape(header_prefix)}.*?(?=^## |\Z)", re.M | re.S
    )
    m = pattern.search(md)
    return m.group(0).strip() if m else ""


def _md_lines_to_flowables(md: str, st: dict) -> list:
    """决策包 markdown 简渲染:表格行进 Table,其余按段落。够用即可,不求全 md 语法。"""
    flow: list = []
    table_rows: list[list[str]] = []

    def flush_table() -> None:
        nonlocal table_rows
        if not table_rows:
            return
        data = [
            [Paragraph(_xml(c), st["mono"]) for c in row] for row in table_rows
        ]
        tb = Table(data)
        tb.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "NutmegCJK"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.93, 0.97, 0.95)),
        ]))
        flow.append(tb)
        flow.append(Spacer(1, 4))
        table_rows = []

    for line in md.splitlines():
        s = line.strip()
        if s.startswith("|") and not set(s) <= {"|", "-", " ", ":"}:
            table_rows.append([c.strip() for c in s.strip("|").split("|")])
            continue
        flush_table()
        if not s or set(s) <= {"|", "-", " ", ":"}:
            continue
        if s.startswith("#"):
            flow.append(Paragraph(_xml(s.lstrip("# ")), st["h2"]))
        else:
            flow.append(Paragraph(_xml(s.lstrip("> ")), st["body"]))
    flush_table()
    return flow


def _build_daily_story(report: DailyReport) -> list:
    _register_cjk_font()
    st = _styles()
    story: list = []
    # 1 报头(🏆 emoji 在 NutmegCJK 缺字形渲染为空白,改纯文字——视觉抽查 2026-06-11)
    story.append(Paragraph(f"世界杯日报 · {report.run_date}", st["title"]))
    story.append(Paragraph(
        _xml(f"{report.stage_label} · 引擎确定性产出 · 仅供娱乐,空仓合法"),
        ParagraphStyle("c", parent=st["small"], alignment=TA_CENTER)))
    story.append(HRFlowable(width="100%", thickness=1.2, color=ACCENT,
                            spaceBefore=4, spaceAfter=8))
    # 2 今日主线
    story.append(Paragraph("今日主线", st["h2"]))
    story.append(Paragraph(_xml(report.narrative), st["narrative"]))
    # 3+4 今日看点 / 投注决策(从决策包抽 §B1 热度表 + §A 票面 + §C)
    if report.packet_md:
        for header, title in (("## B", "今日看点(盘面底座)"),
                              ("## A", "投注决策(引擎票面,勿改腿)")):
            section = _packet_section(report.packet_md, header)
            if section:
                story.append(Paragraph(title, st["h2"]))
                story.extend(_md_lines_to_flowables(
                    "\n".join(section.splitlines()[1:]), st))
        story.append(Paragraph(_xml(TIER_NOTE), st["small"]))
    else:
        story.append(Paragraph("投注决策", st["h2"]))
        story.append(Paragraph("(当日决策包缺失——今日未出包或路径异常)", st["body"]))
    # 裁量结论
    story.append(Paragraph("裁量结论(§C)", st["h2"]))
    if report.answers is None:
        story.append(Paragraph("裁量未作答 — 本报告为兜底自动生成。", st["body"]))
    else:
        for a in report.answers.answers:
            # ⚠️/• 同样缺字形 — 用 [分歧] 与 · 替代
            mark = " [分歧]" if a.divergent else ""
            story.append(Paragraph(
                _xml(f"· {a.q_id}:{a.decision}(信心 {a.confidence}/5)— "
                     f"{a.reason}{mark}"), st["body"]))
        if report.answers.final_note:
            story.append(Paragraph(_xml("一句话:" + report.answers.final_note),
                                   st["narrative"]))
    # 5 赛事预测(图表)
    story.append(Paragraph("赛事预测(蒙特卡洛)", st["h2"]))
    if report.sim is None:
        story.append(Paragraph("(模拟数据缺失,本节降级跳过)", st["body"]))
    else:
        from .tournament import load_tournament

        try:
            t = load_tournament()
            from .charts import champion_bar_png, champion_trend_png

            story.append(_img(champion_bar_png(t, report.sim, report.sim_prev)))
            if len(report.sim_history) >= 2:
                story.append(_img(champion_trend_png(t, report.sim_history)))
            story.append(Paragraph(
                _xml(f"模拟 N={report.sim.n_sims:,} · seed={report.sim.seed} · "
                     f"市场锚定 {len(report.sim.anchored)} 场"), st["small"]))
        except Exception:  # noqa: BLE001 — 图表失败降级文本(spec §7)
            logger.warning("PDF: 图表生成失败,降级文本", exc_info=True)
            top = sorted(report.sim.probs.items(),
                         key=lambda kv: kv[1]["champion"], reverse=True)[:10]
            for team, p in top:
                story.append(Paragraph(
                    _xml(f"· {team}: 夺冠 {p['champion']:.1%}"), st["body"]))
    if report.calibration_note:
        story.append(Paragraph(_xml(report.calibration_note), st["body"]))
    # 6 昨日战报
    story.append(Paragraph("昨日战报", st["h2"]))
    if report.review is None:
        story.append(Paragraph("(昨日复盘待出 — 08:00 任务生成后可重渲)", st["body"]))
    else:
        story.append(Paragraph(
            _xml(f"注金 {report.review.get('total_stake', '?')} 元 → 回收 "
                 f"{report.review.get('total_return', '?')} 元"), st["body"]))
    # 7 尾注
    story.append(HRFlowable(width="100%", thickness=0.6, color=colors.lightgrey,
                            spaceBefore=10, spaceAfter=4))
    story.append(Paragraph(_xml(
        "数据:体彩竞彩 + API-Football(主)/500.com(备) · 模拟可复现"
        f"(seed={report.sim.seed if report.sim else '—'}) · "
        "娱乐预算纪律:B/D/E 零 edge,-13% 抽水下正 EV 无意义"), st["small"]))
    return story


def _img(png: bytes, width_mm: float = 165) -> Image:
    img = Image(io.BytesIO(png))
    ratio = img.imageHeight / img.imageWidth
    img.drawWidth = width_mm * mm
    img.drawHeight = width_mm * ratio * mm
    return img


def render_daily_pdf(report: DailyReport, pdf_path: Path) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4,
                            leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm)
    doc.build(_build_daily_story(report))


def render_review_pdf(report: DailyReport, pdf_path: Path) -> None:
    """迷你战报(--review-pdf,spec §5.1):报头 + 昨日战报 + 概率变动。"""
    _register_cjk_font()
    st = _styles()
    story: list = [
        Paragraph(f"世界杯战报 · {report.run_date}", st["title"]),
        HRFlowable(width="100%", thickness=1.2, color=ACCENT,
                   spaceBefore=4, spaceAfter=8),
        Paragraph("昨日票面", st["h2"]),
    ]
    if report.review is None:
        story.append(Paragraph("(复盘数据缺失)", st["body"]))
    else:
        story.append(Paragraph(
            _xml(f"注金 {report.review.get('total_stake', '?')} 元 → 回收 "
                 f"{report.review.get('total_return', '?')} 元"), st["body"]))
    story.append(Paragraph("夺冠概率变动", st["h2"]))
    if report.sim and report.sim_prev:
        deltas = sorted(
            ((t, p["champion"] - report.sim_prev.probs.get(t, p)["champion"])
             for t, p in report.sim.probs.items()),
            key=lambda kv: abs(kv[1]), reverse=True,
        )[:8]
        for team, d in deltas:
            story.append(Paragraph(_xml(f"· {team}: {d * 100:+.1f}pp"), st["body"]))
    else:
        story.append(Paragraph("(无对比数据)", st["body"]))
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4,
                            leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm)
    doc.build(story)
