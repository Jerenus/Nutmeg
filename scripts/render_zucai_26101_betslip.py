"""渲染 26101 期传统足彩投注站交付版 PDF。

内容源：.nutmeg-data/zucai/26101-tickets.json（票面）+ 26101-reads.json（盖率/信心）
        + 26101-issue.json（对阵/开球）。概率均为确定性算术，脚本内不做任何判断。
输出：.nutmeg-data/zucai/26101-betslip.pdf
"""
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

ROOT = Path(__file__).parents[1]
DATA = ROOT / ".nutmeg-data/zucai"
OUT = DATA / "26101-betslip.pdf"  # 终版:仅任选九场

pdfmetrics.registerFont(TTFont("CJK", "/Library/Fonts/Arial Unicode.ttf"))
FONT = "CJK"

INK = colors.HexColor("#111111")
MUTED = colors.HexColor("#6b6b6b")
RULE = colors.HexColor("#d8d8d8")
BAND = colors.HexColor("#eef1f5")
PICK = colors.HexColor("#f7f2e8")
ACCENT = colors.HexColor("#8c2f2f")

ss = getSampleStyleSheet()


def st(name, size, leading=None, color=INK, sb=0, sa=0, align=TA_LEFT):
    return ParagraphStyle(name, parent=ss["Normal"], fontName=FONT, fontSize=size,
                          leading=leading or size * 1.4, textColor=color,
                          spaceBefore=sb, spaceAfter=sa, alignment=align)


H1 = st("H1", 18, 23, INK, 0, 2)
SUB = st("SUB", 9, 13, MUTED, 0, 9)
H2 = st("H2", 13, 17, INK, 12, 4)
BIG = st("BIG", 15, 21, INK, 2, 4)
BODY = st("BODY", 9, 13, INK, 0, 3)
SMALL = st("SMALL", 7.8, 11, MUTED, 0, 2)
CELL = st("CELL", 9, 12)
CELLC = st("CELLC", 9, 12, align=TA_CENTER)
PICKC = st("PICKC", 13, 15, INK, align=TA_CENTER)
CELLM = st("CELLM", 8, 11, MUTED)

issue = json.loads((DATA / "26101-issue.json").read_text("utf-8"))
tk = json.loads((DATA / "26101-tickets.json").read_text("utf-8"))
M = {m["match_no"]: m for m in issue["matches"]}
R1, S1, S = tk["R1"], tk["S1"], tk["stats"]

story = []
story.append(Paragraph("传统足彩 第 26101 期 · 投注交付单", H1))
story.append(Paragraph(
    f"销售截止 <b>{issue['sale_deadline'][:16]}</b>（北京）　·　开奖 {issue['draw_date']}"
    f"　·　任选九场 <b>{S['R1_notes']} 注 / ¥{S['R1_notes'] * 2}</b>　·　全中概率 <b>{S['R1_p9']*100:.2f}%</b>"
    "　·　板面：英联杯 3 + 荷甲 4 + 葡超 3 + 瑞超 1 + 挪超 2 + 芬超 1", SUB))


def slip(title, code_map, note_count, amount, headline, rows, hi_rows, dim_rows=()):
    story.append(Paragraph(title, H2))
    story.append(Paragraph(headline, BODY))
    codeline = "　".join(code_map.get(str(i), "—") for i in range(1, 15))
    story.append(Paragraph(f"<b>{codeline}</b>", BIG))
    data = [[Paragraph(f"<b>{h}</b>", CELLC if h in ("场次", "选项") else CELL)
             for h in ("场次", "赛事", "对阵", "开球(北京)", "选项")]]
    for r in rows:
        data.append([Paragraph(f"<b>{r[0]}</b>", CELLC), Paragraph(r[1], CELLM),
                     Paragraph(r[2], CELL), Paragraph(r[3], CELLM),
                     Paragraph(f"<b>{r[4]}</b>", PICKC)])
    t = Table(data, colWidths=[14 * mm, 18 * mm, 62 * mm, 30 * mm, 26 * mm], repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("BACKGROUND", (0, 0), (-1, 0), BAND),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, RULE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
        ("BOX", (0, 0), (-1, -1), 0.6, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]
    for k in hi_rows:
        style.append(("BACKGROUND", (0, k), (-1, k), PICK))
    for k in dim_rows:
        style.append(("BACKGROUND", (0, k), (-1, k), colors.HexColor("#f5f5f5")))
        style.append(("TEXTCOLOR", (0, k), (-1, k), colors.HexColor("#9a9a9a")))
    t.setStyle(TableStyle(style))
    story.append(t)
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"<b>注数 {note_count} 注　×　每注 ¥2　×　倍数 1　=　合计 ¥{amount}</b>", BIG))


# ---------------------------------------------------------------- 票一 任九
r1_rows, r1_hi = [], []
for i in range(1, 15):
    m = M[i]
    pick = R1.get(str(i))
    r1_rows.append((str(i), m["competition"], f"{m['home_team']} vs {m['away_team']}",
                    m["kickoff_bj"][5:], " ".join(pick) if pick else "不选"))
    if pick:
        r1_hi.append(i)
slip("票一 · 任选九场（主攻）　|　第 26101 期　|　截止 08-08 21:30",
     R1, S["R1_notes"], S["R1_notes"] * 2,
     f"选 <b>1 / 3 / 6 / 7 / 8 / 10 / 11 / 12 / 13</b> 九场　·　"
     f"不选 2 / 4 / 5 / 9 / 14　·　全中概率 <b>{S['R1_p9'] * 100:.2f}%</b>",
     r1_rows, r1_hi, dim_rows=[i for i in range(1, 15) if str(i) not in R1])
story.append(Paragraph(
    "填票要点：任九只勾选上表 9 个高亮场次，其余 5 场留空。场 7 为双选（3 和 1 都要勾），"
    "场 1 / 3 / 8 / 11 / 13 为三项全选，场 6 / 10 / 12 各只勾一项。", SMALL))

story.append(Spacer(1, 6))
story.append(Paragraph("选项对照：<b>3</b> = 主胜　<b>1</b> = 平局　<b>0</b> = 客胜", BODY))
story.append(Paragraph(
    "<b>本期只出这一张。</b>胜负彩 14 场票经平局覆盖审计后撤销："
    "¥500 帽内最优版一等奖概率仅 1.30%，且 87.7% 的死法是平局砸在未盖平的 9 场上；"
    "而任九丢掉的 5 场（2/4/5/9/14）平局面值 21.0–26.7%，正是最贵的一批。", SMALL))
story.append(Paragraph(
    "风险体检（信念口径，确定性算术）：期望断腿 0.91 条；平局期望出现 2.01 场、已盖 1.56、"
    "未盖 0.45（场 6/10/12），平局杀票概率 38.7%；客胜未盖 0.38，33.3%；主胜未盖 0.08，8.2%。", SMALL))
story.append(Paragraph(
    "预算依据：回本门槛（成本÷命中率）= ¥2,769。升到 729 注需门槛 ¥3,522、且该步独立盈亏平衡要求"
    "单注奖金 > ¥7,714；升到 972 注要求 > ¥15,677。历史参照 26093 ¥2,510 / 26096 ¥16,097。故不加档。", SMALL))
story.append(Paragraph(
    "概率口径：14-15 家国际公司即时欧赔去水 fair（2026-08-08 09:28 快照），确定性算术，"
    "非收益承诺。彩票有风险，量力而行。", SMALL))

SimpleDocTemplate(str(OUT), pagesize=A4,
                  leftMargin=14 * mm, rightMargin=14 * mm,
                  topMargin=13 * mm, bottomMargin=12 * mm,
                  title="传统足彩 26101 期投注交付单").build(story)
print(f"→ {OUT}")
