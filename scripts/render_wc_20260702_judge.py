"""手机友好评判员深研 PDF — 2026-07-02 R32 三场(西/奥·葡/克·瑞/阿)。112mm 窄竖版。
内容=Claude 主循环七阶段深研(DC锚市场 wc_r32_0703_dcfit.py + jczq-match-analyst逐场web)。
判读层¥30意见票:¥15单关083让胜 + ¥10二串一083主胜×085主胜 + ¥5对冲083让平;084空仓。"""
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

BASE=".nutmeg-data/jczq/daily/2026-07-02"
D=json.load(open(f"{BASE}/predictions.json"))
PW,PH=112*mm,272*mm
def st(n,s,l,c="#111111",sp=2): return ParagraphStyle(n,fontName="NutmegCJK",fontSize=s,leading=l,textColor=colors.HexColor(c),spaceAfter=sp,alignment=TA_LEFT)
H1=st("H1",15,19,"#0b3d2e",3); H2=st("H2",11.5,15,"#0b3d2e",2)
BODY=st("BODY",8.6,12.2,"#1a1a1a",2); SMALL=st("SMALL",7.5,10.6,"#444444",1)
WHITE=st("WHITE",9,12,"#ffffff",0); ABIL=st("ABIL",8.2,11.2,"#0b3d2e",1)
WILL=st("WILL",8.2,11.2,"#7a0000",1); PLAY=st("PLAY",8.2,11.2,"#0a4a6e",1)
JCOLOR={"home":"#0a6","draw":"#b58100","away":"#06a"}; JNAME={"home":"主胜","draw":"平","away":"客胜"}

DEEP={
"周四083":{
 "ability":"西班牙H组7分头名一球未失(0-0佛得角/4-0沙特/1-0乌拉圭),欧洲杯卫冕冠军,Rodri/Pedri/Yamal齐整;但缺Nico Williams+Pino两个边路突破手,破铁桶只剩Yamal单点。奥地利J组第2、72年首进淘汰赛(96分钟绝平阿尔及利亚出线),攻火爆(小组进6)守极漏(近12场世界杯零封挂零)。",
 "will":"状态:西休5-6天略优,SoFi顶棚temperate正午场利传控。战意:奥围城心态铁桶更顽固+西2010后世界杯淘汰赛一场未赢的心魔→两股力都压窄净胜球,别重仓大比分。",
 "play":"DC模态2:0=14.3%>1:0=13.0%>3:0=10.2%;让胜(净胜2+)47.8%最大单桶vs让平24.4%/让负27.8%。总进球众数=2球(24%)非3球,买3球=押众数隔壁。意见票:让胜@1.85为主+让平@3.55对冲,双向覆盖净胜幅度;西不胜(27.8%)则全灭。"},
"周四084":{
 "ability":"葡萄牙K组第2(1-1刚果金/5-0乌兹/0-0哥伦比亚),对纪律防线两场合计xG1.58攻坚崩塌,C罗淘汰赛历来低效。克罗地亚L组第2(2-4英格兰/1-0巴拿马/2-1加纳),中场控场仍在但防线被速度撕(英格兰4球)。首次世界杯交锋,近8次葡6胜1平1负。",
 "will":"状态中性:休息同5天,克飞多伦多短+BMO踢过(熟悉度),葡年轻腿热浪下半场续航优。战意双满;心理面偏克(2018亚军/2022季军,点球4-0;葡2022负摩洛哥出局)。⚠克'拖平DNA'兑现在120分钟,90分钟他们常是一球输家——用点球队招牌买90分钟平局=押模态隔壁。",
 "play":"DC模态1:1=12.7%>1:0=11.1%>2:0=10.5%;让负(克不败)45.7%最大桶。★体彩让平@3.12定价全场最差(DC fair23.7%,EV-26%)——两个方向都不干净→判读层本场空仓,只出预测(葡2-1,信心3)。回避:让胜3.11(葡赢2+被高估)。"},
"周四085":{
 "ability":"瑞士B组头名不败7分(1-1卡塔尔/4-1波黑/2-1加拿大),无伤停,Manzambi(3球1助)后段爆点;阿尔及利亚J组最佳第三(0-3阿根廷/2-1约旦/3-3奥地利),Mahrez灵但Amoura伤缺、3场丢7防线极脆。双方小组赛均零封挂零。",
 "will":"★状态一边倒偏瑞士:休8天+末轮就在BC Place原地(准主场) vs 阿5天短休+堪萨斯城跨1900mi倒2时区+3-3透支。战意反向:阿首进淘汰赛求队史首胜+主帅Petkovic(前瑞士主帅)复仇→铁不了桶但会卖命,大概率偷回一球。",
 "play":"DC模态1:1=13.8%>1:0=11.3%>0:0=10.0%,小2.5=56%;让负52.9%全场定价最优单腿(EV-5%)但与判读(瑞胜)矛盾→不下反自己的腿。意见票用主胜@1.80进二串一吃状态边际(override后52%);回避让胜3.73(最低概率档)与阿冷胜4.06(0/23死亡陷阱)。"},
}

story=[]
story.append(Paragraph("世界杯竞彩 · 评判员深研",H1))
story.append(Paragraph("2026-07-02 · R32 三场 · 北京7-03凌晨 03:00/07:00/11:00",SMALL))
story.append(Paragraph("引擎§A今日四档全空(¥0)→照单空仓;本页为判读层意见票,与引擎注金永不合账。",SMALL))
story.append(Spacer(1,3))

rows=[["编","对阵","判","比分","信"]]
for p in D["picks"]:
    rows.append([p["match_no"].replace("周四",""),p["fixture"].replace(" vs ","/"),JNAME[p["judgment"]],p["score"],str(p["confidence"])])
t=Table(rows,colWidths=[8*mm,51*mm,9*mm,13*mm,7*mm])
tstyle=[("FONTNAME",(0,0),(-1,-1),"NutmegCJK"),("FONTSIZE",(0,0),(-1,-1),7.8),
    ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0b3d2e")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
    ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#cccccc")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2)]
for i,p in enumerate(D["picks"],1):
    tstyle.append(("TEXTCOLOR",(2,i),(2,i),colors.HexColor(JCOLOR[p["judgment"]])))
    if p["confidence"]>=4: tstyle.append(("BACKGROUND",(4,i),(4,i),colors.HexColor("#fde7a0")))
t.setStyle(TableStyle(tstyle)); story.append(t); story.append(Spacer(1,4))

# 意见票卡（¥30 三票）
card=[[Paragraph("判读层意见票 · 总注 ¥30（娱乐预算）",WHITE)],
      [Paragraph("① ¥15 评判员单关：<b>083 西班牙让球-1「让胜」@1.85</b>（净胜2+，DC最大单桶47.8%；奥地利12场世界杯零封挂零+先丢必追）",BODY)],
      [Paragraph("② ¥10 二串一：<b>083主胜1.23 × 085瑞士主胜1.80 = @2.21</b>（吃瑞士休8天+BC Place原地准主场的状态边际，override命中≈37.5%）",BODY)],
      [Paragraph("③ ¥5 对冲彩票：<b>083「让平」@3.55</b>（西恰胜1球=1-0/2-1；与①合成对西班牙赢球的双向净胜覆盖）",BODY)],
      [Paragraph("情景：西胜2+且瑞胜 +19.9 ｜ 西恰胜1且瑞胜 +9.9 ｜ 西胜2+瑞不胜 -2.3 ｜ <b>西不胜(27.8%)全灭 -30</b>。084葡/克两个方向都不干净→本场空仓不上钱。",SMALL)]]
ct=Table(card,colWidths=[100*mm])
ct.setStyle(TableStyle([("BACKGROUND",(0,0),(0,0),colors.HexColor("#0b3d2e")),
    ("BACKGROUND",(0,1),(0,-1),colors.HexColor("#f4faf7")),("BOX",(0,0),(-1,-1),0.6,colors.HexColor("#0b3d2e")),
    ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),("LEFTPADDING",(0,0),(-1,-1),5)]))
story.append(ct); story.append(Spacer(1,4))

story.append(Paragraph("逐场深研（实力 × 状态/战意 × 玩法）",H2))
for p in D["picks"]:
    dd=DEEP[p["match_no"]]
    head=f"<b>{p['match_no'].replace('周四','')} {p['fixture']}</b>　{JNAME[p['judgment']]} {p['score']} 信心{p['confidence']}"
    story.append(Paragraph(head,ParagraphStyle("h",parent=BODY,textColor=colors.HexColor(JCOLOR[p['judgment']]),fontSize=9.5,leading=12.5,spaceAfter=1)))
    story.append(Paragraph("【实力】"+dd["ability"],ABIL))
    story.append(Paragraph("【状态/战意】"+dd["will"],WILL))
    story.append(Paragraph("【玩法/DC】"+dd["play"],PLAY))
    story.append(Spacer(1,4))

story.append(Spacer(1,2))
story.append(Paragraph("纪律 & 冠军",H2))
story.append(Paragraph("数据纪律:概率来自国际去水fair拟合Dixon-Coles(loss~1e-7全复现市场,scripts/wc_r32_0703_dcfit.py)+体彩子盘;组合算术scripts/wc_r32_0703_combos.py,禁嘴算。失败教训:高赔串整票0/128全输、ttg腿0/11、crs 5%、hhad 12%→命中优先;记分牌警示:判定53%<基线62%→只在有球面理由处偏离(今日三场方向全随市场,偏离只在幅度/状态边际)。",SMALL))
story.append(Paragraph(f"冠军pick(维持)：{D['champion_pick']['team']} — 本地蒙卡20.8%仍居首(阿根廷19.5%),无换pick的球面理由。",SMALL))

out=Path(f"{BASE}/wc-judge-deepdive.pdf")
SimpleDocTemplate(str(out),pagesize=(PW,PH),topMargin=6*mm,bottomMargin=6*mm,leftMargin=6*mm,rightMargin=6*mm).build(story)
print("Wrote",out)
