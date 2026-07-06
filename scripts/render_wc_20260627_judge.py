"""手机友好评判员深研 PDF — 2026-06-27 L/K/J 组 MD3 收官轮。112mm 窄竖版。"""
import json
from pathlib import Path
from reportlab.lib.pagesizes import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

CJK = ["/System/Library/Fonts/Supplemental/Songti.ttc",
       "/System/Library/Fonts/STHeiti Light.ttc",
       "/System/Library/Fonts/PingFang.ttc"]
for p in CJK:
    try:
        pdfmetrics.registerFont(TTFont("NutmegCJK", p, subfontIndex=0)); break
    except Exception: continue

D = json.load(open(".nutmeg-data/jczq/daily/2026-06-27/predictions.json"))
PW = 112*mm
PH = 250*mm
def st(name, size, lead, color="#111111", bold=False, space=2):
    return ParagraphStyle(name, fontName="NutmegCJK", fontSize=size, leading=lead,
                          textColor=colors.HexColor(color), spaceAfter=space, alignment=TA_LEFT)
H1 = st("H1", 15, 19, "#0b3d2e", space=3)
H2 = st("H2", 11.5, 15, "#0b3d2e", space=2)
BODY = st("BODY", 8.6, 12.2, "#1a1a1a", space=2)
SMALL = st("SMALL", 7.6, 10.6, "#444444", space=1)
TAG = st("TAG", 8.2, 11, "#7a0000", space=1)
WHITE = st("WHITE", 9, 12, "#ffffff", space=0)
ABIL = st("ABIL", 8.2, 11.2, "#0b3d2e", space=1)
WILL = st("WILL", 8.2, 11.2, "#7a0000", space=1)

JCOLOR = {"home":"#0a6", "draw":"#b58100", "away":"#06a"}
JNAME = {"home":"主胜","draw":"平","away":"客胜"}

story = []
story.append(Paragraph("世界杯竞彩 · 评判员深研", H1))
story.append(Paragraph("2026-06-27 · L/K/J 组 MD3 收官轮 · 美东今晚 / 北京6-28凌晨", SMALL))
story.append(Spacer(1, 3))

# 表头：六场走向一览
rows=[["编", "对阵", "判", "比分", "信"]]
for p in D["picks"]:
    no = p["match_no"].replace("周六","")
    fx = p["fixture"].replace(" vs ", "/")
    rows.append([no, fx, JNAME[p["judgment"]], p["score"], str(p["confidence"])])
t = Table(rows, colWidths=[8*mm, 47*mm, 9*mm, 13*mm, 7*mm])
ts=[("FONTNAME",(0,0),(-1,-1),"NutmegCJK"),("FONTSIZE",(0,0),(-1,-1),7.8),
    ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0b3d2e")),
    ("TEXTCOLOR",(0,0),(-1,0),colors.white),
    ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#cccccc")),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2)]
for i,p in enumerate(D["picks"],1):
    ts.append(("TEXTCOLOR",(2,i),(2,i),colors.HexColor(JCOLOR[p["judgment"]])))
    if p["confidence"]>=4:
        ts.append(("BACKGROUND",(4,i),(4,i),colors.HexColor("#fde7a0")))
t.setStyle(TableStyle(ts))
story.append(t)
story.append(Spacer(1, 4))

# 评判员单关 + 引擎票（高亮卡）
ot = D["opinion_ticket"]
card=[[Paragraph(f"★评判员单关 ¥{ot['stake_yuan']}", WHITE)],
      [Paragraph(f"{ot['fixture']} — <b>{JNAME.get(ot['pick'],ot['pick'])}</b> @{ot['odds']} (信心4·全天最高)", BODY)]]
ct=Table(card, colWidths=[100*mm])
ct.setStyle(TableStyle([("BACKGROUND",(0,0),(0,0),colors.HexColor("#b58100")),
    ("BACKGROUND",(0,1),(0,1),colors.HexColor("#fff6df")),
    ("BOX",(0,0),(-1,-1),0.6,colors.HexColor("#b58100")),
    ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
    ("LEFTPADDING",(0,0),(-1,-1),5)]))
story.append(ct)
story.append(Spacer(1,2))
story.append(Paragraph("引擎A底仓 2串1 @3.44 ¥35：070刚果金胜@1.63 + 071阿尔及利亚平@2.11（两腿皆模态方向，命中约22%；与单关同向交叉确认。娱乐预算小额，空仓亦合法）", SMALL))
story.append(Spacer(1, 4))

# R32 签位地图
story.append(Paragraph("R32 签位地图（名次→对手→软硬）", H2))
seed=[["组","第1名","第2名","第3名"],
      ["J","佛得角(最软)","西班牙(死)","美国·3分多半出局"],
      ["K","最佳第三+R16瑞士","2L+R16西班牙","刚果金抢才有"],
      ["L","最佳第三(塞内加尔)最软","2K+R16西班牙","K组头名(最硬)"]]
stb=Table(seed, colWidths=[7*mm,31*mm,31*mm,31*mm])
stb.setStyle(TableStyle([("FONTNAME",(0,0),(-1,-1),"NutmegCJK"),("FONTSIZE",(0,0),(-1,-1),6.8),
    ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0b3d2e")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
    ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#cccccc")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2)]))
story.append(stb)
story.append(Paragraph("2K与2L在R32直接对碰、赢家R16撞西班牙。J组='赢球被惩罚'V形倒挂→默契平；K组=葡攻哥守不对称；L组=名次越高签越软的纯正向梯度→都想赢。", SMALL))
story.append(Paragraph("中立实力排序：阿根廷&gt;&gt;英格兰&gt;葡萄牙&gt;克罗地亚≈哥伦比亚&gt;奥地利≈阿尔及利亚&gt;加纳&gt;刚果金&gt;乌兹别克≈约旦≈巴拿马。", SMALL))
story.append(Spacer(1, 5))

# 逐场详读：能力×战意×走向
story.append(Paragraph("逐场完整评估（客观能力 × 战意签位 → 走向）", H2))
for p in D["picks"]:
    no=p["match_no"].replace("周六","")
    head=f"<b>{no} {p['fixture']}</b>　{JNAME[p['judgment']]} {p['score']}（备{p['score_alt']}）信心{p['confidence']}"
    story.append(Paragraph(head, ParagraphStyle("h",parent=BODY,textColor=colors.HexColor(JCOLOR[p['judgment']]),fontSize=9.5,leading=12.5,spaceAfter=1)))
    story.append(Paragraph("【能力】"+p["ability"], ABIL))
    story.append(Paragraph("【战意/签位】"+p["will"], WILL))
    story.append(Paragraph("【合成】"+p["reason"], BODY))
    story.append(Spacer(1,4))

story.append(Spacer(1,2))
story.append(Paragraph("纪律", H2))
story.append(Paragraph(D["data_note"], SMALL))
story.append(Paragraph(f"冠军pick：{D['champion_pick']['team']}（{D['champion_pick']['reason']}）", SMALL))

out = Path(".nutmeg-data/jczq/daily/2026-06-27/wc-judge-deepdive.pdf")
SimpleDocTemplate(str(out), pagesize=(PW,PH), topMargin=6*mm, bottomMargin=6*mm,
                  leftMargin=6*mm, rightMargin=6*mm).build(story)
print("Wrote", out)
