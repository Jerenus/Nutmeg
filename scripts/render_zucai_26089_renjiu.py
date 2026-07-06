"""Render 任选九 (14选9) 第26089期 票面为手机版 PDF (112mm) + 推送 Telegram.

世界杯 R32 第二波 14 场。主循环 Claude 深研(4 路并行 agent web 检索 + 逐场
状态/凝聚力/教练/客观实力判读)定稿的"选9丢5"方案。判断不烤进脚本——脚本只渲染+推送。
字体/页型/推送复用 jczq_final_plan_pdf + render_zucai_26088 的成法。
"""
from __future__ import annotations

import os
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


def _load_dotenv() -> None:
    env = Path(".env")
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# 14 场: (场次, 对阵, 玩法, 勾选, 释义=决定性因素)
ROWS = [
    ("1", "巴西 vs 日本", "双", "胜+平", "日本攻核全缺·防磨平"),
    ("2", "德国 vs 巴拉圭", "双", "胜+平", "刚被同款打法绝杀·保平"),
    ("3", "荷兰 vs 摩洛哥", "丢", "—", "后防整条崩·掷硬币"),
    ("4", "科特迪瓦 vs 挪威", "双", "负+平", "挪威不败·低净胜"),
    ("5", "法国 vs 瑞典", "单", "胜", "四维碾压·铁腿"),
    ("6", "墨西哥 vs 厄瓜多尔", "丢", "—", "两堵铁墙·雷区"),
    ("7", "英格兰 vs 刚果金", "单", "胜", "实力断层·带雷铁腿"),
    ("8", "美国 vs 波黑", "单", "胜", "东道主+轮休·偏铁"),
    ("9", "西班牙 vs 奥地利", "单", "胜", "奥不摆桶·雷区证伪"),
    ("10", "葡萄牙 vs 克罗地亚", "丢", "—", "平被低估·真雷区"),
    ("11", "瑞士 vs 阿尔及利亚", "丢", "—", "P帅懂瑞士·掷硬币"),
    ("12", "澳大利亚 vs 埃及", "丢", "—", "萨拉赫伤·雷区第一"),
    ("13", "阿根廷 vs 佛得角", "单", "胜", "梅西·首席铁腿"),
    ("14", "哥伦比亚 vs 加纳", "单", "胜", "加纳缺双核·强铁腿"),
]


def build(pdf_path: Path) -> None:
    _register_cjk_font()
    W = 112 * mm
    doc = SimpleDocTemplate(
        str(pdf_path), pagesize=portrait((W, 250 * mm)),
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
    story.append(Paragraph("任选九 (14选9) · 世界杯R32", title))
    story.append(Paragraph("第 26089 期 · 销售截止 06-29 22:00", sub))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("8 注 = ¥16 · 选9丢5 · 整票命中率 ~8-9%", big))
    story.append(Paragraph("注数 = 1⁶(单) × 2³(双) = 8 ｜ 6 单 + 3 双 + 丢 5", sub))
    story.append(Spacer(1, 3 * mm))

    head = ["#", "对阵", "玩法", "勾选", "决定性因素"]
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
    tbl = Table(data, colWidths=[5.5 * mm, 30 * mm, 9 * mm, 13 * mm, 42 * mm], repeatRows=1)
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
    tbl.setStyle(TableStyle(style))
    story.append(tbl)
    story.append(Spacer(1, 3 * mm))

    story.append(Paragraph(
        "<b>释义</b>：胜=主队胜，负=客队胜，平=平局。"
        "<b>单</b>=6 条铁腿(法/英/美/西/阿根廷/哥伦比亚)走干净主胜；"
        "<b>双</b>=3 条强热门加注保平(巴西/德国/挪威不败)；<b>丢</b>=5 个 coinflip 雷区。", body))
    story.append(Spacer(1, 1.5 * mm))
    story.append(Paragraph(
        "<b>逻辑</b>：丢掉 5 个平局被合理定价/胜负开关未明的 coinflip(荷摩·墨厄·葡克·瑞阿·澳埃)，"
        "钱只花在有方向的 9 场。巴西/德国怕铁桶磨平、挪威是低净胜，三腿加平把单腿~55-70%抬到~80%——"
        "任九『加注只提命中率不提奖金』的正确用法。", body))
    story.append(Spacer(1, 1.5 * mm))
    story.append(Paragraph(
        "<b>注意</b>：① 9号西班牙是『强队打不开铁桶』陷阱的<b>证伪</b>——奥地利(Rangnick)高位对攻反喂西边路；"
        "② 12号萨拉赫腿筋伤出否=胜负开关，故直接丢；"
        "③ 想再提命中可把 7英/8美 也升双→32注¥64(奖金不变)。"
        "<b>空仓/减注永远合法，仅娱乐预算小额。</b>", body))
    story.append(Spacer(1, 1.5 * mm))
    story.append(Paragraph(
        "_引擎注金永不合账；本票=判读/创作层，长期为负抽水，仅供娱乐。_", sub))

    doc.build(story)
    print(f"WROTE {pdf_path} ({pdf_path.stat().st_size} bytes)")


def dispatch(pdf_path: Path) -> None:
    _load_dotenv()
    token = os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN")
    chat_raw = os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS")
    if not token or not chat_raw:
        print("SKIP dispatch: missing telegram env")
        return
    from nutmeg.interfaces.bot.telegram import TelegramBotClient
    client = TelegramBotClient(token=token)
    caption = ("任选九第26089期 · 世界杯R32 · 选9丢5 · 8注¥16 (6单3双)\n"
               "铁腿: 法/英/美/西/阿根廷/哥伦比亚 ｜ 保平: 巴西/德国/挪威不败\n"
               "丢: 荷摩·墨厄·葡克·瑞阿·澳埃(萨拉赫伤) ｜ 截止 06-29 22:00")
    for cid in [int(p.strip()) for p in chat_raw.split(",") if p.strip()]:
        client.send_document(chat_id=cid, document_path=pdf_path, caption=caption)
        print(f"SENT to chat {cid}")


if __name__ == "__main__":
    out_dir = Path(".nutmeg-data/zucai/daily/2026-06-29/renjiu")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "26089-renjiu-9pick-8notes.pdf"
    build(out)
    scratch = Path("/private/tmp/claude-501/-Users-jz71-Projects-Nutmeg/"
                   "76b82d12-a5c1-476d-82d2-8b6f17ba44c5/scratchpad/26089-renjiu-9pick-8notes.pdf")
    build(scratch)
    dispatch(out)
