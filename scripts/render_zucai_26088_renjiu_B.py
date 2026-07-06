"""Render 任选九 (14选9) 第26088期 方案B 票面为手机版 PDF (112mm).

一次性脚本：把 Claude 深研+迭代定稿的方案 B 渲染成手机宽 PDF，
保存到 zucai daily 目录 + scratchpad。字体复用 jczq_final_plan_pdf 的 CJK 注册法。
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import portrait
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_CJK_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]


def _register_cjk_font() -> None:
    if "NutmegCJK" in pdfmetrics.getRegisteredFontNames():
        return
    last_err = None
    for path in _CJK_FONT_CANDIDATES:
        try:
            pdfmetrics.registerFont(TTFont("NutmegCJK", path, subfontIndex=0))
            return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise RuntimeError(f"No CJK font; last error: {last_err}")


# 14 场: (场次, 对阵, 玩法, 勾选, 释义)
ROWS = [
    ("1", "瑞士 vs 加拿大", "丢", "—", "争头名磨平·雷区"),
    ("2", "苏格兰 vs 巴西", "双", "负+平", "巴西胜或平(不败)"),
    ("3", "捷克 vs 墨西哥", "丢", "—", "墨大轮换·雷区"),
    ("4", "南非 vs 韩国", "双", "负+平", "韩国胜或平(不败)"),
    ("5", "厄瓜多尔 vs 德国", "全包", "胜平负", "德轮换·冷活口大"),
    ("6", "日本 vs 瑞典", "丢", "—", "战意倒挂·雷区"),
    ("7", "突尼斯 vs 荷兰", "单", "负", "荷兰胜(铁腿)"),
    ("8", "土耳其 vs 美国", "全包", "胜平负", "美轮换·翻盘0.27"),
    ("9", "挪威 vs 法国", "丢", "—", "争头名·雷区"),
    ("10", "乌拉圭 vs 西班牙", "全包", "胜平负", "西轮换·乌死拼"),
    ("11", "克罗地亚 vs 加纳", "双", "胜+平", "克胜或平(不败)"),
    ("12", "巴拿马 vs 英格兰", "单", "负", "英格兰胜(铁腿)"),
    ("13", "哥伦比亚 vs 葡萄牙", "丢", "—", "强强争头名·雷区"),
    ("14", "约旦 vs 阿根廷", "单", "负", "阿根廷胜(铁腿)"),
]

PLAY_COLOR = {
    "单": colors.HexColor("#1d6f42"),
    "双": colors.HexColor("#b8860b"),
    "全包": colors.HexColor("#1f4e8c"),
    "丢": colors.HexColor("#999999"),
}


def build(pdf_path: Path) -> None:
    _register_cjk_font()
    W = 112 * mm
    doc = SimpleDocTemplate(
        str(pdf_path), pagesize=portrait((W, 230 * mm)),
        leftMargin=6 * mm, rightMargin=6 * mm, topMargin=7 * mm, bottomMargin=7 * mm,
    )
    title = ParagraphStyle("t", fontName="NutmegCJK", fontSize=15, leading=19,
                           alignment=TA_CENTER, textColor=colors.HexColor("#1f4e8c"))
    sub = ParagraphStyle("s", fontName="NutmegCJK", fontSize=8.5, leading=12,
                         alignment=TA_CENTER, textColor=colors.HexColor("#555555"))
    big = ParagraphStyle("b", fontName="NutmegCJK", fontSize=11, leading=15,
                         alignment=TA_CENTER, textColor=colors.HexColor("#c0392b"))
    body = ParagraphStyle("body", fontName="NutmegCJK", fontSize=8, leading=12,
                          alignment=TA_LEFT, textColor=colors.HexColor("#333333"))
    cell = ParagraphStyle("c", fontName="NutmegCJK", fontSize=7.6, leading=9.5,
                          alignment=TA_LEFT)

    story = []
    story.append(Paragraph("任选九 (14选9) · 方案B", title))
    story.append(Paragraph("第 26088 期 · 销售截止 06-24 22:00 · 06-28 开奖", sub))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("216 注 = ¥432 · 估计命中率 ~29%", big))
    story.append(Paragraph("选 9 丢 5 ｜ 注数 = 1³(单) × 2³(双) × 3³(全包) = 8×27 = 216", sub))
    story.append(Spacer(1, 3 * mm))

    head = ["#", "对阵", "玩法", "勾选", "释义"]
    data = [[Paragraph(f"<b>{h}</b>", cell) for h in head]]
    for no, vs, play, pick, note in ROWS:
        pick_p = Paragraph(f"<b>{pick}</b>" if play != "丢" else pick, cell)
        data.append([
            Paragraph(no, cell),
            Paragraph(vs, cell),
            Paragraph(f'<b>{play}</b>', cell),
            pick_p,
            Paragraph(note, cell),
        ])
    tbl = Table(data, colWidths=[6 * mm, 33 * mm, 11 * mm, 15 * mm, 35 * mm], repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "NutmegCJK"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.6),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e8c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
    ]
    for i, (no, vs, play, pick, note) in enumerate(ROWS, start=1):
        if play == "丢":
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f2f2f2")))
            style.append(("TEXTCOLOR", (0, i), (-1, i), colors.HexColor("#999999")))
        elif play == "单":
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#eaf5ee")))
        elif play == "双":
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fbf3e0")))
        elif play == "全包":
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#e8eef7")))
    tbl.setStyle(TableStyle(style))
    story.append(tbl)
    story.append(Spacer(1, 3 * mm))

    story.append(Paragraph(
        "<b>释义</b>：负=客队胜，胜=主队胜，平=平局。"
        "<b>单选</b>3 条铁腿(荷兰/英格兰/阿根廷)；<b>双选</b>3 场打不败(巴西/韩国/克罗地亚)；"
        "<b>全包</b>3 场最易翻盘(德/美/西)。", body))
    story.append(Spacer(1, 1.5 * mm))
    story.append(Paragraph(
        "<b>逻辑</b>：丢掉 5 个平局雷区(双方已出线/dead rubber)，"
        "钱只花在有方向的 9 场；铁腿单选、折价热门按翻盘风险升双或全包。"
        "巴西加平堵住苏格兰摆大巴的冷平漏点。", body))
    story.append(Spacer(1, 1.5 * mm))
    story.append(Paragraph(
        "<b>注意</b>：西班牙/阿根廷/克罗地亚临场首发名单(轮换深度)是唯一能证伪判读的硬信息，"
        "22:00 截止前可再扫一眼官方 XI。空仓/减注永远合法。", body))

    doc.build(story)
    print(f"WROTE {pdf_path} ({pdf_path.stat().st_size} bytes)")


if __name__ == "__main__":
    out_dir = Path(".nutmeg-data/zucai/daily/2026-06-24/renjiu")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "26088-renjiu-planB-432.pdf"
    build(out)
    scratch = Path("/private/tmp/claude-501/-Users-jz71-Projects-Nutmeg/74706ccf-b1aa-4348-8733-379e277d1ba8/scratchpad/26088-renjiu-planB-432.pdf")
    build(scratch)
