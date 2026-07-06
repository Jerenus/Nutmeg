#!/usr/bin/env python3
"""v10 状态+战意终判: 原判断(实力/战术)+状态(condition)+战意(will)三层重判四场。手机PDF+bot推送。"""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
for p in ["/System/Library/Fonts/Supplemental/Songti.ttc",
          "/System/Library/Fonts/STHeiti Light.ttc","/System/Library/Fonts/PingFang.ttc"]:
    if Path(p).exists():
        pdfmetrics.registerFont(TTFont("CJK",p,subfontIndex=0)); break
NAVY=colors.HexColor("#10243f"); BLUE=colors.HexColor("#1d4e79"); GOLD=colors.HexColor("#b8860b")
RED=colors.HexColor("#a01b1b"); GREEN=colors.HexColor("#1d6b3a"); GREY=colors.HexColor("#444444")
LITE=colors.HexColor("#eef2f7"); WARM=colors.HexColor("#fdf3e3"); ROSE=colors.HexColor("#f3e1e1")
def s(n,sz,c=colors.black,lead=None,sp=2,al=0):
    return ParagraphStyle(n,fontName="CJK",fontSize=sz,textColor=c,leading=lead or sz*1.4,spaceAfter=sp,alignment=al)
H1=s("H1",14.5,NAVY,lead=18,sp=2,al=1); SUB=s("SUB",8.3,GREY,lead=11.5,sp=4,al=1)
HEAD=s("HEAD",10.5,colors.white,lead=13.5,sp=0)
SMALL=s("SMALL",7.5,GREY,lead=10.6,sp=2); THEAD=s("TH",7.5,colors.white,lead=9.9)
TCELL=s("TC",7.3,colors.black,lead=9.7); TCB=s("TCB",7.3,NAVY,lead=9.7)
def P(t,st): return Paragraph(t,st)
def band(t,c=BLUE):
    return Table([[Paragraph(t,HEAD)]],colWidths=[96*mm],style=TableStyle([("BACKGROUND",(0,0),(-1,-1),c),
        ("LEFTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
def box(p,bg=WARM,edge=GOLD):
    return Table([[p]],colWidths=[96*mm],style=TableStyle([("BACKGROUND",(0,0),(-1,-1),bg),("BOX",(0,0),(-1,-1),0.5,edge),
        ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
def grid(rows,widths,hc=NAVY):
    data=[[P(c,THEAD if i==0 else (TCB if j==0 else TCELL)) for j,c in enumerate(r)] for i,r in enumerate(rows)]
    t=Table(data,colWidths=widths); t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),hc),("FONTNAME",(0,0),(-1,-1),"CJK"),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,LITE]),("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#c8d2de")),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3),
        ("TOPPADDING",(0,0),(-1,-1),2.3),("BOTTOMPADDING",(0,0),(-1,-1),2.3)])); return t

def card(title, rows, land, lc=GREEN):
    out=[band(title,BLUE),Spacer(1,2)]
    for lab,txt in rows:
        out.append(P(f"<b>{lab}</b> {txt}", s('cr',7.9,colors.black,lead=11,sp=2)))
    out.append(P(f"<b>▶ 落点:</b> {land}", s('cl',8,lc,lead=11.4,sp=1)))
    out.append(Spacer(1,4))
    return out

flow=[]
flow+=[P("6/21 四场 · 状态+战意 终判",H1),
       P("原判断(实力/战术) + 状态(condition) + 战意(will) 三层重判",SUB)]
flow+=[box(P("<b>方法</b>: 状态和战意常<b>方向相反</b>——这次政治『伤了伊朗状态、却点燃战意』; 旅行『累了新西兰、鲜活了埃及』。分开看才准。",SMALL),bg=ROSE,edge=RED)]
flow+=[Spacer(1,4)]

flow+=card("037 西班牙 vs 沙特",[
  ("原判断:","实力鸿沟(西87%), 西小胜、不打穿(进球荒+亚马尔限45'+沙门将热)"),
  ("状态:","西原地零旅行+闭顶空调舒适 | 沙轻度旅行+门将火热 → 双方都好"),
  ("战意:","西must-win(进球荒压力)动力强 | 沙士气正盛会死守拼反击 → 双方都高"),
],"双方战意高=沙特铁桶更顽固→压打穿。西小胜2-0(西胜稳/比分2-0博); 命门=进球荒被逼平尾部")

flow+=card("038 比利时 vs 伊朗",[
  ("原判断:","比破不开#20组织铁桶(欧洲杯0-0乌克兰/MD1 1-1埃及), 赢不明确"),
  ("状态:","比~1500km+缺Debast | 伊备战灾难(营搬墨西哥/签证/缺人)、MD1丢2球欠火候 → 伊更差"),
  ("战意:","比must-win但换血受挫 | 伊围城心态点燃(拼出2-2/团结/侨民力挺) → 伊强不裂"),
],"伊满意志欠火候→怕定位球不怕围攻; 比利时被拖累。总进球2-3最稳; 让平>让胜, 平局是主对冲")

flow+=card("039 乌拉圭 vs 佛得角",[
  ("原判断:","乌破密防短板, 佛铁桶(0封西), 迈阿密酷热放大小球"),
  ("状态:","乌缺Arrascaeta+R阿劳霍恐缺+努涅斯存疑 | 佛连场死守+酷热体能隐患 → 双方隐患"),
  ("战意:","乌must-win动力高 | 佛零包袱但保守(满足偷分) → 佛偏保守死守"),
],"酷热+保守死守→小球最强信号; 乌1-0/闷平; 让球不追(coinflip)")

flow+=card("040 新西兰 vs 埃及",[
  ("原判断:","埃破密防顽疾原看小胜; 但#85弱新西兰, 市场偏埃净2+"),
  ("状态:","新1800km跨国疲劳+MD1被弱伊朗灌水(高估) | 埃230km最鲜活+萨拉赫满状态 → 埃全面占优"),
  ("战意:","新背水但平局基因(上限是平) | 埃求队史世界杯首胜+追纪录 → 埃极高"),
],"唯一推向大胜的场。埃及胜(62%)最稳; 让负(净2+)略优于让平; 新背水死守+平局基因留尾部",lc=GOLD)

flow+=[band("汇总: 状态/战意 → 净影响",NAVY),Spacer(1,2)]
flow+=[grid([
  ["场","状态","战意","落点"],
  ["037西沙","双好","双高","西小胜2-0, 不打穿"],
  ["038比伊","伊差","伊强","总进球2-3, 让平>让胜"],
  ["039乌佛","双隐患","佛保守","小球, 乌1-0/闷平"],
  ["040新埃","埃占优","埃极高","埃及胜/让负(净2+)"],
],[16*mm,16*mm,16*mm,48*mm])]
flow+=[Spacer(1,3)]
flow+=[box(P("<b>主线</b>: 状态+战意层<b>强化了037/038/039的低分·小胜·谨慎</b>; 唯<b>040被推向『埃及赢得舒服』</b>——唯一一场状态与战意同向(都利埃及)、对手又被高估。其余三场仍是『强队小胜/低进球/平局尾部要敬畏』。", SMALL))]
flow+=[P("注金: 娱乐小额、空仓合法; 高赔区命中个位~10%。让球/总进球赔率为本会话实盘缓存, 临场以体彩为准。", s('f',7,GREY,lead=9.6,al=1))]

out=Path(".nutmeg-data/jczq/daily/2026-06-21/wc-md2-v10-state-will-20260621.pdf")
SimpleDocTemplate(str(out),pagesize=(112*mm,250*mm),leftMargin=8*mm,rightMargin=8*mm,topMargin=8*mm,bottomMargin=7*mm,
    title="WC2026 6/21 v10状态战意终判").build(flow)
print(f"PDF written: {out} ({out.stat().st_size} bytes)")
load_dotenv()
token=os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN")
ids=[int(x) for x in os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS","").split(",") if x.strip()]
from nutmeg.interfaces.bot.telegram import TelegramBotClient
client=TelegramBotClient(token=token)
cap=("🏆 v10 状态+战意终判 · 四场重判\n"
     "方法: 状态≠战意(政治伤伊朗状态却点燃战意; 旅行累新西兰鲜活埃及)\n"
     "037西小胜不打穿 · 038总进球2-3(让平>让胜) · 039小球 · 040埃及胜/让负\n"
     "主线: 强化037/38/39低分小胜; 唯040推向埃及赢得舒服。")
for cid in ids:
    client.send_document(chat_id=cid,document_path=out,caption=cap); print(f"sent to {cid}")
print("DONE")
