#!/usr/bin/env python3
"""2026-06-23 周二045-048 终版(精确CRS+盘面走势+纠错)。手机PDF+bot推送。"""
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

for p in ["/System/Library/Fonts/Supplemental/Songti.ttc","/System/Library/Fonts/STHeiti Light.ttc","/System/Library/Fonts/PingFang.ttc"]:
    if Path(p).exists():
        pdfmetrics.registerFont(TTFont("CJK",p,subfontIndex=0)); break
NAVY=colors.HexColor("#10243f");BLUE=colors.HexColor("#1d4e79");GOLD=colors.HexColor("#b8860b")
RED=colors.HexColor("#a01b1b");GREEN=colors.HexColor("#1d6b3a");GREY=colors.HexColor("#444444")
LITE=colors.HexColor("#eef2f7");WARM=colors.HexColor("#fdf3e3");ROSE=colors.HexColor("#f3e1e1")
def s(n,sz,c=colors.black,lead=None,sp=2,al=0):
    return ParagraphStyle(n,fontName="CJK",fontSize=sz,textColor=c,leading=lead or sz*1.4,spaceAfter=sp,alignment=al)
H1=s("H1",13.5,NAVY,lead=17,sp=2,al=1);SUB=s("SUB",8,GREY,lead=11,sp=4,al=1)
HEAD=s("HEAD",10.5,colors.white,lead=13);BODY=s("BODY",8.1,colors.black,lead=11.8,sp=3)
SMALL=s("SMALL",7.3,GREY,lead=10.4,sp=2);THEAD=s("TH",7.2,colors.white,lead=9.8);TCELL=s("TC",7.1,colors.black,lead=9.6);TCB=s("TCB",7.1,NAVY,lead=9.6)
def P(t,st=BODY):return Paragraph(t,st)
def band(t,c=BLUE):
    return Table([[Paragraph(t,HEAD)]],colWidths=[96*mm],style=TableStyle([("BACKGROUND",(0,0),(-1,-1),c),("LEFTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
def box(p,bg=WARM,edge=GOLD):
    return Table([[p]],colWidths=[96*mm],style=TableStyle([("BACKGROUND",(0,0),(-1,-1),bg),("BOX",(0,0),(-1,-1),0.5,edge),("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
def grid(rows,widths,hc=NAVY):
    data=[[P(c,THEAD if i==0 else (TCB if j==0 else TCELL)) for j,c in enumerate(r)] for i,r in enumerate(rows)]
    t=Table(data,colWidths=widths);t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),hc),("FONTNAME",(0,0),(-1,-1),"CJK"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,LITE]),("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#c8d2de")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3),("TOPPADDING",(0,0),(-1,-1),2.5),("BOTTOMPADDING",(0,0),(-1,-1),2.5)]));return t
flow=[]
flow+=[P("周二045-048 终版 · 精确CRS+盘面走势",H1),P("北京6/24开球 · 大转折:纠正早先'小球/窄胜'低估",SUB)]
flow+=[box(P("<b>引擎空仓¥0</b>。<b>盘面走势(终于到手)四场让球全向'热门覆盖'移动</b>(045让胜2.28→1.98、047受让负2.32→2.11猛缩);<b>精确CRS逐队反推</b>一致指向<b>热门进球更多/偏大</b>——我纠正自己'晚破窄胜/小球'的系统性低估(第二次)。方向信心高、texture以走势+CRS为准。",SMALL),bg=ROSE,edge=RED)]
flow+=[Spacer(1,4),band("精确逐队反推(现盘CRS,禁嘴算)",NAVY),Spacer(1,3)]
flow+=[grid([
 ["场","主队期望","客队期望","总进球","热门比分"],
 ["045 葡-乌","2.42(打穿36%)","乌0.55","3-4球","3-0/2-0"],
 ["046 英-加","2.34(最打穿)","加0.60","3-4球","2-0/3-0/1-0"],
 ["047 巴-克","巴0.82","克1.94(能进2)","2-3球","0-2/0-1/1-2"],
 ["048 哥-刚","1.88","刚0.72","2-3边界","1-0/2-1(平21%)"],
],[26*mm,24*mm,20*mm,16*mm,16*mm])]
flow+=[Spacer(1,4),band("建议比分(终版) + 玩法",GOLD),Spacer(1,3)]
flow+=[grid([
 ["场","建议比分(主→次)","玩法"],
 ["045 葡-乌","3-0、2-0→2-1","偏大球/让胜(净3+)可博"],
 ["046 英-加","2-0、3-0→2-1","大球/3-0;★让胜@2.25(单关)"],
 ["047 巴-克","0-2、0-1→1-2","克让平+受让负(净2+)双向live"],
 ["048 哥-刚","1-0、2-1→2-0、1-1","哥让平/2-1;平21%/刚进球"],
],[24*mm,34*mm,38*mm],hc=GOLD)]
flow+=[Spacer(1,3),box(P("<b>评判员单关¥15 = 046 英格兰让胜(净3+)@2.25</b>——今天最打穿场(英期望2.34/净3+ 33%/让胜资金缩),加纳进攻废给不了反扑。<b>纠错点名</b>:045我早先押小球=错,葡期望2.42、3-0头号、让胜猛缩→打穿/大球才对(用户直觉对)。<b>纪律</b>:比分当彩票小额、空仓合法;整票0/94。",SMALL))]
out=Path(".nutmeg-data/jczq/daily/2026-06-23/wc-md2-FINAL-20260623.pdf")
SimpleDocTemplate(str(out),pagesize=(112*mm,250*mm),leftMargin=8*mm,rightMargin=8*mm,topMargin=8*mm,bottomMargin=7*mm,title="WC 6/23 045-048 终版").build(flow)
print(f"PDF: {out} ({out.stat().st_size}B)")
load_dotenv()
token=os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN");ids=[int(x) for x in os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS","").split(",") if x.strip()]
if token and ids:
    from nutmeg.interfaces.bot.telegram import TelegramBotClient
    c=TelegramBotClient(token=token)
    cap=("🏆 周二045-048 终版(精确CRS+盘面走势)\n大转折:走势+CRS一致指向热门进球更多/偏大,我纠正早先'小球/窄胜'低估。\n建议比分:045=3-0/2-0(打穿) 046=2-0/3-0(最打穿) 047=0-2/0-1(克赢1-2) 048=1-0/2-1(开放平21%)\n评判员单关=046英格兰让胜@2.25。整票0/94,小额,空仓合法。")
    for cid in ids: c.send_document(chat_id=cid,document_path=out,caption=cap);print(f"sent {cid}")
    print("DONE")
else: print("⚠️无TG凭据")
