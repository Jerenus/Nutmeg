"""渲染 26102 期「投注站出票精简单」——单页，只含填票所需信息，无推理内容。

内容源：26102-dcfit.json（盖率/概率，确定性算术）。
输出：.nutmeg-data/zucai/26102-slip.pdf
"""
import json
from functools import reduce
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).parents[1]
DATA = ROOT / ".nutmeg-data/zucai"
OUT = DATA / "26102-slip.pdf"

pdfmetrics.registerFont(TTFont("CJK", "/Library/Fonts/Arial Unicode.ttf"))
F = "CJK"

INK = colors.HexColor("#111111")
MUTED = colors.HexColor("#666666")
RULE = colors.HexColor("#c8c8c8")
BAND = colors.HexColor("#e8ebef")
SEL = colors.HexColor("#fdf6e3")
DIM = colors.HexColor("#f4f4f4")
GREY = colors.HexColor("#9a9a9a")

ss = getSampleStyleSheet()


def st(n, size, lead=None, color=INK, sb=0, sa=0, align=TA_LEFT):
    return ParagraphStyle(n, parent=ss["Normal"], fontName=F, fontSize=size,
                          leading=lead or size * 1.4, textColor=color,
                          spaceBefore=sb, spaceAfter=sa, alignment=align)


H1 = st("H1", 17, 21, INK, 0, 2)
SUB = st("SUB", 8.5, 12, MUTED, 0, 6)
H2 = st("H2", 12.5, 16, INK, 8, 3)
CODE = st("CODE", 19, 25, INK, 3, 2)
IDX = st("IDX", 7.5, 10, GREY, 0, 4)
AMT = st("AMT", 13, 17, INK, 2, 3)
BODY = st("BODY", 8.6, 12.4, INK, 0, 3)
SMALL = st("SMALL", 7.5, 10.5, MUTED, 0, 2)
C = st("C", 9, 12, align=TA_CENTER)
CL = st("CL", 9, 12)
CM = st("CM", 8, 11, MUTED)
PK = st("PK", 13, 15, INK, align=TA_CENTER)

fit = json.loads((DATA / "26102-dcfit.json").read_text("utf-8"))
META = {
    1: ("荷甲", "08-09 20:30", "格罗宁根", "乌德勒支"),
    2: ("荷甲", "08-09 20:30", "兹沃勒", "阿贾克斯"),
    3: ("荷甲", "08-09 22:45", "海伦芬", "特温特"),
    4: ("葡超", "08-10 01:00", "波尔图", "阿尔维卡"),
    5: ("葡超", "08-10 03:30", "本菲卡", "维塞乌"),
    6: ("葡超", "08-10 03:30", "吉维森特", "里奥阿维"),
    7: ("葡超", "08-10 03:30", "摩雷伦斯", "布拉加"),
    8: ("瑞超", "08-09 22:30", "哥德堡", "卡尔马"),
    9: ("瑞超", "08-09 22:30", "哈尔姆斯塔德", "盖斯"),
    10: ("挪超", "08-09 20:30", "利勒斯特罗姆", "罗森博格"),
    11: ("挪超", "08-09 23:00", "汉坎", "奥勒松"),
    12: ("挪超", "08-10 01:15", "克里斯蒂安松", "莫尔德"),
    13: ("芬超", "08-09 22:00", "国际图尔库", "拉赫蒂"),
    14: ("芬超", "08-10 00:00", "AC奥卢", "赫尔辛基"),
}
R9 = {2: "01", 4: "31", 5: "3", 7: "01", 8: "310", 9: "01", 10: "30", 13: "31", 14: "310"}
S14 = {1: "30", 2: "10", 3: "10", 4: "3", 5: "3", 6: "13", 7: "10", 8: "13",
       9: "0", 10: "30", 11: "3", 12: "0", 13: "1", 14: "3"}

story = []


def notes(tk):
    return reduce(lambda a, b: a * b, (len(set(v)) for v in tk.values()))


def slip(title, tk, extra):
    n = notes(tk)
    story.append(Paragraph(title, H2))
    story.append(Paragraph("　".join(tk.get(i, "—") for i in range(1, 15)), CODE))
    story.append(Paragraph("　　".join(f"{i}" for i in range(1, 15)), IDX))
    rows = [[Paragraph(f"<b>{h}</b>", C) for h in ("场", "赛事", "对阵", "开球(北京)", "勾选")]]
    sel, dim = [], []
    for i in range(1, 15):
        p = tk.get(i)
        lg, ko, h, a = META[i]
        rows.append([Paragraph(f"<b>{i}</b>", C), Paragraph(lg, CM),
                     Paragraph(f"{h} — {a}", CL), Paragraph(ko, CM),
                     Paragraph(f"<b>{'  '.join(p)}</b>" if p else "不选", PK)])
        (sel if p else dim).append(i)
    t = Table(rows, colWidths=[10 * mm, 14 * mm, 66 * mm, 26 * mm, 30 * mm], repeatRows=1)
    s = [("FONTNAME", (0, 0), (-1, -1), F), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
         ("TOPPADDING", (0, 0), (-1, -1), 3.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.6),
         ("LEFTPADDING", (0, 0), (-1, -1), 5),
         ("BACKGROUND", (0, 0), (-1, 0), BAND), ("LINEBELOW", (0, 0), (-1, 0), 0.8, RULE),
         ("BOX", (0, 0), (-1, -1), 0.6, RULE), ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE)]
    for r in sel:
        s.append(("BACKGROUND", (0, r), (-1, r), SEL))
    for r in dim:
        s.append(("BACKGROUND", (0, r), (-1, r), DIM))
        s.append(("TEXTCOLOR", (0, r), (-1, r), GREY))
    t.setStyle(TableStyle(s))
    story.append(t)
    story.append(Spacer(1, 3))
    story.append(Paragraph(f"<b>{n} 注　×　每注 ¥2　×　倍数 1　＝　合计 ¥{n * 2:,}</b>", AMT))
    story.append(Paragraph(extra, SMALL))


story.append(Paragraph("传统足彩 第 26102 期 · 出票单", H1))
story.append(Paragraph(
    "销售截止 <b>2026-08-09 20:00</b>（北京）　·　开奖 2026-08-10　·　"
    "两票<b>分开出</b>，玩法不同　·　选项：<b>3 = 主胜　1 = 平局　0 = 客胜</b>", SUB))

slip("票一　任选九场（复式）", R9,
     "只勾上表 9 个高亮场次，其余 5 场（1 / 3 / 6 / 11 / 12）留空不选。"
     "其中场 8、14 为三项全选；场 2、4、7、9、10、13 各勾两项；场 5 只勾「3」。")

story.append(Spacer(1, 8))

slip("票二　胜负彩 14 场（复式）", S14,
     "14 场全选，无留空。场 4、5、9、11、12、13、14 各只勾一项；"
     "场 1、2、3、6、7、8、10 各勾两项。")

story.append(Spacer(1, 8))
tot = notes(R9) * 2 + notes(S14) * 2
story.append(Paragraph(f"<b>两票合计　¥{tot:,}</b>", AMT))
story.append(Paragraph(
    "出票后请核对小票上的场次与选项是否与本单一致，并保留小票。"
    "彩票有风险，请理性投注；未满 18 周岁不得购买。", SMALL))

SimpleDocTemplate(str(OUT), pagesize=A4,
                  leftMargin=14 * mm, rightMargin=14 * mm,
                  topMargin=12 * mm, bottomMargin=10 * mm,
                  title="传统足彩 26102 期 出票单").build(story)
print(f"→ {OUT}  任九 {notes(R9)}注 / 胜负彩 {notes(S14)}注 / 合计 ¥{tot:,}")
