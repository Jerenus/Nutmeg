"""One-shot: render today's debate final-plan.json to PDF and dispatch via Nutmeg Telegram bot.

Usage:
    uv run python scripts/jczq_final_plan_pdf_dispatch.py --date 2026-05-11
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date as date_cls
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from nutmeg.interfaces.bot.telegram import TelegramBotClient


def _xml(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


_CJK_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]


def _register_cjk_font() -> None:
    if "NutmegCJK" in pdfmetrics.getRegisteredFontNames():
        return
    last_err: Exception | None = None
    for path in _CJK_FONT_CANDIDATES:
        try:
            pdfmetrics.registerFont(TTFont("NutmegCJK", path, subfontIndex=0))
            return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue
    raise RuntimeError(f"No CJK font found from candidates: {_CJK_FONT_CANDIDATES}; last error: {last_err}")


def render_pdf(plan: dict, pdf_path: Path) -> None:
    _register_cjk_font()
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "Title",
        parent=styles["Title"],
        fontName="NutmegCJK",
        fontSize=18,
        leading=24,
        alignment=TA_CENTER,
    )
    h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontName="NutmegCJK",
        fontSize=12,
        leading=16,
        spaceBefore=8,
        spaceAfter=4,
    )
    body = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="NutmegCJK",
        fontSize=9,
        leading=13,
    )
    small = ParagraphStyle(
        "Small",
        parent=body,
        fontSize=8,
        leading=11,
    )
    leg = ParagraphStyle(
        "Leg",
        parent=small,
        fontSize=8.5,
        leading=12,
    )

    story: list = []
    story.append(Paragraph(_xml(f"JCZQ Final Plan — {plan['run_date']}"), title))
    story.append(
        Paragraph(
            _xml(
                f"预算 {plan['budget_total']} 元 / 5 张票 / 规则环境："
                + ", ".join(plan.get("rule_environment", []))
            ),
            body,
        )
    )
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            _xml(
                "配置变体：" + plan.get("config_variant", "?")
                + " — "
                + plan.get("config_variant_note", "")
            ),
            small,
        )
    )
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(_xml("仅供娱乐分析，不保证命中，下单前以竞彩终端实时赔率为准。"), small)
    )
    story.append(Spacer(1, 8))

    metrics = plan.get("portfolio_metrics", {})
    cmp_ = metrics.get("comparison", {})
    story.append(Paragraph("Portfolio 摘要", h2))
    story.append(
        Paragraph(
            _xml(
                f"总注金 {metrics.get('total_stake', '?')} 元 ｜ 已知部分 EV {metrics.get('total_expected_value_known', '?')} 元 ｜ "
                f"SOP 默认版 EV {cmp_.get('sop_default_variant_ev', '?')} ｜ "
                f"实验折中版 EV {cmp_.get('experimental_blended_variant_ev', '?')} ｜ "
                f"差 +{cmp_.get('ev_uplift_vs_sop', '?')} 元"
            ),
            small,
        )
    )
    story.append(Spacer(1, 6))

    summary_rows = [
        [
            Paragraph(_xml("票"), small),
            Paragraph(_xml("注金"), small),
            Paragraph(_xml("赔率"), small),
            Paragraph(_xml("理论返奖"), small),
            Paragraph(_xml("命中率"), small),
            Paragraph(_xml("EV"), small),
            Paragraph(_xml("备注"), small),
        ]
    ]
    for t in plan["tickets"]:
        favorite_mark = " ⭐" if t.get("favorite") else ""
        summary_rows.append(
            [
                Paragraph(_xml(f"{t['id']} {t['name']}{favorite_mark}"), small),
                Paragraph(_xml(f"{t['stake']} 元"), small),
                Paragraph(_xml(f"{t['total_odds']}x"), small),
                Paragraph(_xml(f"{t['theoretical_payout']:.0f}"), small),
                Paragraph(_xml(f"{t['hit_probability']*100:.2f}%"), small),
                Paragraph(_xml(f"{t['expected_value']:+.2f}"), small),
                Paragraph(_xml(t.get("variant_note") or t.get("favorite_reason") or ""), small),
            ]
        )
    summary_table = Table(
        summary_rows,
        colWidths=[28 * mm, 16 * mm, 18 * mm, 22 * mm, 16 * mm, 16 * mm, 60 * mm],
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "NutmegCJK"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 10))

    # Detailed tickets
    story.append(Paragraph("5 张票腿位明细", h2))
    for t in plan["tickets"]:
        favorite_mark = " ⭐" if t.get("favorite") else ""
        story.append(
            Paragraph(
                _xml(
                    f"{t['id']} {t['name']}{favorite_mark} — {t['stake']} 元 / {t['total_odds']}x"
                ),
                h2,
            )
        )
        for L in t["legs"]:
            line = (
                f"• {L['match_no']} {L['league']} {L['home']} vs {L['away']} ｜ "
                f"{L['pool']} {L['pick']} @ {L['odds']}"
            )
            edge = L.get("poisson_edge")
            if edge is not None:
                line += f" ｜ Poisson edge {edge*100:+.1f}%"
            goal_line = L.get("goal_line")
            if goal_line:
                line += f" ｜ 让球 {goal_line}"
            story.append(Paragraph(_xml(line), leg))
            logic = L.get("logic")
            if logic:
                story.append(Paragraph(_xml(f"  逻辑：{logic}"), small))
        if t.get("variant_note"):
            story.append(Paragraph(_xml("变体说明：" + t["variant_note"]), small))
        if t.get("favorite_reason"):
            story.append(Paragraph(_xml("最看好理由：" + t["favorite_reason"]), small))
        story.append(Spacer(1, 6))

    # Excluded
    if plan.get("excluded_matches"):
        story.append(Paragraph("整场不入票的场次", h2))
        for ex in plan["excluded_matches"]:
            story.append(
                Paragraph(_xml(f"• {ex['match_no']} — {ex['reason']}"), small)
            )
        story.append(Spacer(1, 6))

    # Concentration
    audit = plan.get("concentration_audit", {})
    shared = audit.get("shared_matches", [])
    if shared:
        story.append(Paragraph("集中度（Rule L）", h2))
        for s in shared:
            story.append(
                Paragraph(
                    _xml(
                        f"• {s['match_no']}：{len(s['tickets'])} 票 ({'/'.join(s['tickets'])})、暴露 {s['stake_at_risk']} 元 — "
                        f"{s.get('narrative_diversification', '')}"
                    ),
                    small,
                )
            )
        story.append(Spacer(1, 4))

    # Rule check status
    rule_lines = [
        f"Rule O 同票同场不同 pool 违规：{audit.get('rule_o_violations', '?')}",
        f"Rule B had ≤ 1.50 违规：{audit.get('rule_b_floor_violations', '?')}",
        f"Rule R9 extreme crs 跨场质量门：{audit.get('rule_r9_extreme_crs_quality_gate', '?')}",
        f"Rule R10 hi-vol ttg ≤ 2 球 in main/contrarian：{audit.get('rule_r10_hivol_ttg_low_in_main_violations', '?')}",
        f"Rule R13 poisson_solo expected_goals 一致性：{audit.get('rule_r13_poisson_solo_expected_goals_consistency', '?')}",
    ]
    story.append(Paragraph("Rule 校验", h2))
    for ln in rule_lines:
        story.append(Paragraph(_xml(f"• {ln}"), small))

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    doc.build(story)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="today")
    parser.add_argument("--dispatch", action="store_true", help="actually send via telegram")
    args = parser.parse_args()

    run_date = (
        date_cls.today().isoformat() if args.date == "today" else args.date
    )
    base = Path(".nutmeg-data/jczq/daily") / run_date
    plan_json = base / "debate" / "final-plan.json"
    pdf_out = base / f"final-value-plan-{run_date.replace('-', '')}.pdf"

    plan = json.loads(plan_json.read_text())
    render_pdf(plan, pdf_out)
    print(f"Wrote PDF: {pdf_out} ({pdf_out.stat().st_size} bytes)")

    if not args.dispatch:
        print("(--dispatch not set; not sending to telegram)")
        return

    token = os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN")
    chat_ids = os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS")
    if not token or not chat_ids:
        raise SystemExit("Missing NUTMEG_TELEGRAM_BOT_TOKEN / NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS")

    client = TelegramBotClient(token=token)
    favorite = next((t for t in plan["tickets"] if t.get("favorite")), None)
    cap_lines = [
        f"JCZQ Final Plan — {plan['run_date']}",
        f"5 张票 / 预算 {plan['budget_total']} 元 / 已知部分 EV {plan['portfolio_metrics']['total_expected_value_known']:+.2f} 元",
    ]
    if favorite:
        cap_lines.append(
            f"最看好：{favorite['id']} {favorite['name']} {favorite['stake']} 元 / {favorite['total_odds']}x"
        )
    caption = "\n".join(cap_lines)

    for chat_id_str in chat_ids.split(","):
        chat_id = int(chat_id_str.strip())
        if not chat_id:
            continue
        client.send_document(chat_id=chat_id, document_path=pdf_out, caption=caption)
        print(f"Dispatched PDF to chat_id={chat_id}")


if __name__ == "__main__":
    main()
