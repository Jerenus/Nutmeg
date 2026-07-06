"""手机友好评判员深研 PDF — 2026-06-30 R32 三场(CIV/挪·法/瑞·墨/厄)。112mm 窄竖版。
内容=Claude 主循环七阶段深研(DC锚市场+jczq-match-analyst逐场web)。"""
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

BASE = ".nutmeg-data/jczq/daily/2026-06-30"
D = json.load(open(f"{BASE}/predictions.json"))
PW, PH = 112*mm, 250*mm
def st(name, size, lead, color="#111111", space=2):
    return ParagraphStyle(name, fontName="NutmegCJK", fontSize=size, leading=lead,
                          textColor=colors.HexColor(color), spaceAfter=space, alignment=TA_LEFT)
H1 = st("H1", 15, 19, "#0b3d2e", 3)
H2 = st("H2", 11.5, 15, "#0b3d2e", 2)
BODY = st("BODY", 8.6, 12.2, "#1a1a1a", 2)
SMALL = st("SMALL", 7.5, 10.6, "#444444", 1)
WHITE = st("WHITE", 9, 12, "#ffffff", 0)
ABIL = st("ABIL", 8.2, 11.2, "#0b3d2e", 1)
WILL = st("WILL", 8.2, 11.2, "#7a0000", 1)
PLAY = st("PLAY", 8.2, 11.2, "#0a4a6e", 1)

JCOLOR = {"home":"#0a6", "draw":"#b58100", "away":"#06a"}
JNAME = {"home":"主胜","draw":"平","away":"客胜"}

# 逐场深研内容(七阶段提炼)
DEEP = {
"周二077": {
 "ability":"挪威高一档:哈兰德首发健康(小组2场4球)+厄德高,资格赛8战全胜;但防守软(小组丢7)。科特迪瓦真铁桶:小组2场零封仅丢2、三场都先进球,队史首进淘汰赛。Opta挪56% vs 去水fair挪45%——市场更高看平局+科特迪瓦。",
 "will":"状态轻偏挪威(明星末轮整体轮休、腿更鲜;1-4负法国是主动轮换别当真)。战意两边拉满、方向不偏;科特迪瓦围城心态→进取型铁桶更顽固。",
 "play":"DC模态:挪威一球小胜(0-1/1-2),但单一最可能比分是1-1(13%)、平局簇28%。最稳=科特迪瓦+1让胜@1.78(fair54.7%、水最浅);高赔=让平(挪净胜1)@3.55。避坑:TTG=2押模态隔壁(2-1是3球)、平局被市场买贵别追、让负@3.50最低概率档。"},
"周二078": {
 "ability":"全场gap最大。法国本届夺冠头号热门(ESPN#1/+350)、姆巴佩健康满血、攻击深度恐怖、淘汰赛全主力。瑞典13场无零封、近10场丢22、最佳中卫Hien整届报销→35岁林德洛夫顶中卫扛姆巴佩=严重错配。",
 "will":"状态/战意净偏法国。瑞典无包袱搏命姿态=双向利好法国:既送进球机会、又把后场暴露给法国刷分。不存在'铁桶更顽固'剧本(瑞典本就不铁桶)。",
 "play":"DC模态3-1(簇2-0/3-0/2-1/4-1)。净胜2+约58%(市场隐含55%)→法国-1让胜@1.60为最优体彩腿、略偏value。唯一杀手=2-1(让平)~20%。别赌4-0+屠杀(瑞典几乎必进球)。★评判员单关取此腿。"},
"周二079": {
 "ability":"实力gap小。墨西哥小组3战全胜3零封但'高效非统治'、破不开低位铁桶是软肋。厄瓜多尔防守顶级(帕乔/因卡皮耶/凯塞多)但终结灾难(5.12xG仅1运动战进球)。海拔优势被基多出身的厄瓜多尔抵消。",
 "will":"状态≈平。战意反偏厄瓜多尔:墨西哥背东道主围城压力(host paralysis)+破不开铁桶;厄零包袱、刚掀翻德国、防反身份契合淘汰赛、逆境点燃。",
 "play":"教科书低分掷硬币局:DC小2.5=68%、0:0是第二可能比分(15%)、平局簇32.5%。最可信是低分而非谁赢。让胜墨-1@4.45是死腿(赢2+仅13%)。模态1-0墨,但与GPT判平分歧→高不确定、不出票。"},
}

story = []
story.append(Paragraph("世界杯竞彩 · 评判员深研", H1))
story.append(Paragraph("2026-06-30 · R32 三场 · 北京7-01凌晨 01:00/05:00/09:00", SMALL))
story.append(Paragraph("引擎§A空仓(四档候选不足);本页为判读层,与引擎注金永不合账。", SMALL))
story.append(Spacer(1, 3))

# 走向一览
rows=[["编", "对阵", "判", "比分", "信"]]
for p in D["picks"]:
    no = p["match_no"].replace("周二","")
    fx = p["fixture"].replace(" vs ", "/")
    rows.append([no, fx, JNAME[p["judgment"]], p["score"], str(p["confidence"])])
t = Table(rows, colWidths=[8*mm, 51*mm, 9*mm, 13*mm, 7*mm])
ts=[("FONTNAME",(0,0),(-1,-1),"NutmegCJK"),("FONTSIZE",(0,0),(-1,-1),7.8),
    ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0b3d2e")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
    ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#cccccc")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2)]
for i,p in enumerate(D["picks"],1):
    ts.append(("TEXTCOLOR",(2,i),(2,i),colors.HexColor(JCOLOR[p["judgment"]])))
    if p["confidence"]>=4: ts.append(("BACKGROUND",(4,i),(4,i),colors.HexColor("#fde7a0")))
t.setStyle(TableStyle(ts)); story.append(t); story.append(Spacer(1, 4))

# 评判员单关卡
ot = D["opinion_ticket"]
card=[[Paragraph(f"★评判员单关 ¥{ot['stake_yuan']}（全天唯一·信心4）", WHITE)],
      [Paragraph(f"078 法国 vs 瑞典 — <b>法国-1让胜(净胜2+)</b> @{ot['odds']}", BODY)],
      [Paragraph("GPT晨版+Claude深研双判一致(低分歧);基本面~58%略高于市场隐含~55%、对应3-1模态。唯一杀手2-1让平(~20%)。", SMALL)]]
ct=Table(card, colWidths=[100*mm])
ct.setStyle(TableStyle([("BACKGROUND",(0,0),(0,0),colors.HexColor("#b58100")),
    ("BACKGROUND",(0,1),(0,2),colors.HexColor("#fff6df")),("BOX",(0,0),(-1,-1),0.6,colors.HexColor("#b58100")),
    ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),("LEFTPADDING",(0,0),(-1,-1),5)]))
story.append(ct); story.append(Spacer(1,3))
story.append(Paragraph("其余两场不出票:077市场/Opta分歧大(挪威45%vs56%)降确定性;079墨/厄Claude判墨小胜 vs GPT判平→分歧、高不确定。空仓合法;高赔=高方差,娱乐预算小额。", SMALL))
story.append(Spacer(1, 4))

# 逐场深研
story.append(Paragraph("逐场深研（实力 × 状态/战意 × 玩法）", H2))
for p in D["picks"]:
    no=p["match_no"].replace("周二","")
    dd=DEEP[p["match_no"]]
    head=f"<b>{no} {p['fixture']}</b>　{JNAME[p['judgment']]} {p['score']} 信心{p['confidence']}"
    story.append(Paragraph(head, ParagraphStyle("h",parent=BODY,textColor=colors.HexColor(JCOLOR[p['judgment']]),fontSize=9.5,leading=12.5,spaceAfter=1)))
    story.append(Paragraph("【实力】"+dd["ability"], ABIL))
    story.append(Paragraph("【状态/战意】"+dd["will"], WILL))
    story.append(Paragraph("【玩法/DC】"+dd["play"], PLAY))
    story.append(Spacer(1,4))

story.append(Spacer(1,2))
story.append(Paragraph("纪律 & 冠军", H2))
story.append(Paragraph("数据纪律:所有概率/edge来自国际去水fair拟合Dixon-Coles(loss~1e-7全复现市场)与体彩子盘,禁嘴算。失败教训:大胆高赔串整票0/124全输、ttg腿0/11、hhad12%→只出单关、命中优先。", SMALL))
story.append(Paragraph(f"冠军pick：{D['champion_pick']['team']}（{D['champion_pick']['reason']}）", SMALL))

out = Path(f"{BASE}/wc-judge-deepdive.pdf")
SimpleDocTemplate(str(out), pagesize=(PW,PH), topMargin=6*mm, bottomMargin=6*mm,
                  leftMargin=6*mm, rightMargin=6*mm).build(story)
print("Wrote", out)
