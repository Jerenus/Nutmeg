"""手机友好评判员深研 PDF — 2026-07-01 R32 三场(英/刚·比/塞·美/波)。112mm 窄竖版。
内容=Claude 主循环七阶段深研(DC锚市场+jczq-match-analyst逐场web)。今日判读层单关空仓。"""
import json
from pathlib import Path
from reportlab.lib.pagesizes import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

CJK=["/System/Library/Fonts/Supplemental/Songti.ttc","/System/Library/Fonts/STHeiti Light.ttc","/System/Library/Fonts/PingFang.ttc"]
for p in CJK:
    try: pdfmetrics.registerFont(TTFont("NutmegCJK",p,subfontIndex=0)); break
    except Exception: continue

BASE=".nutmeg-data/jczq/daily/2026-07-01"
D=json.load(open(f"{BASE}/predictions.json"))
PW,PH=112*mm,255*mm
def st(n,s,l,c="#111111",sp=2): return ParagraphStyle(n,fontName="NutmegCJK",fontSize=s,leading=l,textColor=colors.HexColor(c),spaceAfter=sp,alignment=TA_LEFT)
H1=st("H1",15,19,"#0b3d2e",3); H2=st("H2",11.5,15,"#0b3d2e",2)
BODY=st("BODY",8.6,12.2,"#1a1a1a",2); SMALL=st("SMALL",7.5,10.6,"#444444",1)
WHITE=st("WHITE",9,12,"#ffffff",0); ABIL=st("ABIL",8.2,11.2,"#0b3d2e",1)
WILL=st("WILL",8.2,11.2,"#7a0000",1); PLAY=st("PLAY",8.2,11.2,"#0a4a6e",1)
JCOLOR={"home":"#0a6","draw":"#b58100","away":"#06a"}; JNAME={"home":"主胜","draw":"平","away":"客胜"}

DEEP={
"周三080":{
 "ability":"英格兰L组头名(4-2克罗地亚/0-0加纳/2-0巴拿马),晋级无悬念(fair74%)。刚果金K组最佳第三名(逼平葡萄牙、惜败哥伦比亚),队史首进淘汰赛、防守成色≥加纳,摆5-3-2低位铁桶。",
 "will":"状态:英两主力右后卫全伤(J.James/Quansah)、破铁桶最优边路被削+对面Wan-Bissaka锁边;Saka带伤限用。战意:刚果金零包袱围城死守(更顽固非更软)、英格兰保守DNA(0-0加纳=本届首场上半场零射正)→合力指向闷/窄胜。",
 "play":"DC模态1-0(其次2-0/2-1),小2.5=52%(§D小球错价成立)。★引擎'英-1让胜@1.65'=净胜边缘掷硬币(49%、深研45-50%<市场54%负价值),押模态隔壁。贴模态高赔=让平(英赢1)@3.65。避坑:胜平负押冷门0/23、别押0球长尾。"},
"周三081":{
 "ability":"低分掷硬币(市场=Opta比44/平29/塞27)。比利时黄金一代余晖、破组织防守是硬伤(1-1埃及0-0伊朗,只血洗弱旅);塞内加尔最佳第三名险出线、攻强守漏,门将门迪伤退→替补迪亚。",
 "will":"状态偏比利时(库尔图瓦回归vs塞门位掉档)、战意偏塞内加尔(无包袱、5-0找回强度)→抵消。淘汰赛90分钟'不输即理性'压制常规时间对攻→低分被低估(市场under2.5 -145)。",
 "play":"DC模态1-1(其次1-0/0-0),小2.5=54%。比至多小胜一球、平很活。让胜@4.15=死腿(净胜2+最低概率档)。最优:小球/让平(比赢1)@3.60。最大分叉=塞坐深(0-0/1-0)还是放开对攻(替补门将被罚2-1/3-1)。"},
"周三082":{
 "ability":"美国(东道主)五项全占优、赢面69%:小组进8球、末轮死局雪藏四累黄核心+Pulisic养伤→黄牌清零满血。波黑B组最佳第三名、丢球11/12场但锋线能进(哲科40岁支点)。",
 "will":"状态:美主场无旅行+满血;波黑跨境飞+深度浅。战意:美主场被点燃(4-1/2-0主场胜,非host paralysis);波黑搏命是'对攻放开'非'铁桶更硬'→利好进球数。状态战意同向利好美国+利好大球。",
 "play":"波黑打compact4-4-2非低位铁桶、离球松散→开放对攻局(规避打不开铁桶陷阱)。DC模态2-0≈1-0双峰,大2.5=52.6%。★引擎'美-1让胜@1.90'方向对(44.4%最大单档)但偏冒进掷硬币、价略贵;波黑大概率进1球把2-0拖成2-1。最优=大球(体彩无单腿)。"},
}

story=[]
story.append(Paragraph("世界杯竞彩 · 评判员深研",H1))
story.append(Paragraph("2026-07-01 · R32 三场 · 北京7-02凌晨 00:00/04:00/08:00",SMALL))
story.append(Paragraph("引擎§A出A档2串1(¥35);本页为判读层,与引擎注金永不合账。",SMALL))
story.append(Spacer(1,3))

rows=[["编","对阵","判","比分","信"]]
for p in D["picks"]:
    rows.append([p["match_no"].replace("周三",""),p["fixture"].replace(" vs ","/"),JNAME[p["judgment"]],p["score"],str(p["confidence"])])
t=Table(rows,colWidths=[8*mm,51*mm,9*mm,13*mm,7*mm])
tstyle=[("FONTNAME",(0,0),(-1,-1),"NutmegCJK"),("FONTSIZE",(0,0),(-1,-1),7.8),
    ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0b3d2e")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
    ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#cccccc")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2)]
for i,p in enumerate(D["picks"],1):
    tstyle.append(("TEXTCOLOR",(2,i),(2,i),colors.HexColor(JCOLOR[p["judgment"]])))
    if p["confidence"]>=4: tstyle.append(("BACKGROUND",(4,i),(4,i),colors.HexColor("#fde7a0")))
t.setStyle(TableStyle(tstyle)); story.append(t); story.append(Spacer(1,4))

# 单关空仓卡 + 引擎A档提醒
card=[[Paragraph("评判员单关：今日空仓",WHITE)],
      [Paragraph("三个热门都在<b>净胜边缘掷硬币</b>(英49%/美44%)或整场掷硬币(比/塞),无昨日法国那种基本面错配的干净高信心票→判读层不出票(空仓永远合法)。",SMALL)]]
ct=Table(card,colWidths=[100*mm])
ct.setStyle(TableStyle([("BACKGROUND",(0,0),(0,0),colors.HexColor("#6b6b6b")),
    ("BACKGROUND",(0,1),(0,1),colors.HexColor("#f0f0f0")),("BOX",(0,0),(-1,-1),0.6,colors.HexColor("#6b6b6b")),
    ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),("LEFTPADDING",(0,0),(-1,-1),5)]))
story.append(ct); story.append(Spacer(1,3))
story.append(Paragraph("⚠️引擎A档2串1(080英让胜@1.65 × 082美让胜@1.90,¥35):DC显示两腿=净胜边缘掷硬币(49%/44%),联合命中≈21%。§A勿改腿,但建议小额或整张跳过——两腿都是净胜'隔壁'风险。若押让球方向,让平比让胜更贴模态。",SMALL))
story.append(Spacer(1,4))

story.append(Paragraph("逐场深研（实力 × 状态/战意 × 玩法）",H2))
for p in D["picks"]:
    dd=DEEP[p["match_no"]]
    head=f"<b>{p['match_no'].replace('周三','')} {p['fixture']}</b>　{JNAME[p['judgment']]} {p['score']} 信心{p['confidence']}"
    story.append(Paragraph(head,ParagraphStyle("h",parent=BODY,textColor=colors.HexColor(JCOLOR[p['judgment']]),fontSize=9.5,leading=12.5,spaceAfter=1)))
    story.append(Paragraph("【实力】"+dd["ability"],ABIL))
    story.append(Paragraph("【状态/战意】"+dd["will"],WILL))
    story.append(Paragraph("【玩法/DC】"+dd["play"],PLAY))
    story.append(Spacer(1,4))

story.append(Spacer(1,2))
story.append(Paragraph("纪律 & 冠军",H2))
story.append(Paragraph("数据纪律:概率来自国际去水fair拟合Dixon-Coles(loss~1e-7全复现市场)+体彩子盘,禁嘴算。失败教训:大胆高赔串整票0/124全输、ttg腿0/11、hhad12%→命中优先、无干净edge则空仓。昨日复盘:078法国-1让胜单关命中+¥9、077走向命中。",SMALL))
story.append(Paragraph(f"冠军pick(改判)：{D['champion_pick']['team']} — 本地蒙卡今日反超居首(法21.3%>阿根廷19.8%)+昨日3-0完胜,方法论=跟随模型。",SMALL))

out=Path(f"{BASE}/wc-judge-deepdive.pdf")
SimpleDocTemplate(str(out),pagesize=(PW,PH),topMargin=6*mm,bottomMargin=6*mm,leftMargin=6*mm,rightMargin=6*mm).build(story)
print("Wrote",out)
