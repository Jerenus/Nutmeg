#!/usr/bin/env python3
"""2026-06-24 周三049-054终版(精确CRS+动机主轴)。手机PDF+bot推送。"""
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
    if Path(p).exists(): pdfmetrics.registerFont(TTFont("CJK",p,subfontIndex=0)); break
NAVY=colors.HexColor("#10243f");BLUE=colors.HexColor("#1d4e79");GOLD=colors.HexColor("#b8860b")
RED=colors.HexColor("#a01b1b");GREEN=colors.HexColor("#1d6b3a");GREY=colors.HexColor("#444444")
LITE=colors.HexColor("#eef2f7");WARM=colors.HexColor("#fdf3e3");ROSE=colors.HexColor("#f3e1e1")
def s(n,sz,c=colors.black,lead=None,sp=2,al=0): return ParagraphStyle(n,fontName="CJK",fontSize=sz,textColor=c,leading=lead or sz*1.4,spaceAfter=sp,alignment=al)
H1=s("H1",13,NAVY,lead=16,sp=2,al=1);SUB=s("SUB",7.8,GREY,lead=10.6,sp=4,al=1);HEAD=s("HEAD",10,colors.white,lead=12.5)
SMALL=s("SMALL",7.1,GREY,lead=10.1,sp=2);THEAD=s("TH",7,colors.white,lead=9.5);TCELL=s("TC",6.9,colors.black,lead=9.3);TCB=s("TCB",6.9,NAVY,lead=9.3)
def P(t,st=SMALL): return Paragraph(t,st)
def band(t,c=BLUE): return Table([[Paragraph(t,HEAD)]],colWidths=[96*mm],style=TableStyle([("BACKGROUND",(0,0),(-1,-1),c),("LEFTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
def box(p,bg=WARM,edge=GOLD): return Table([[p]],colWidths=[96*mm],style=TableStyle([("BACKGROUND",(0,0),(-1,-1),bg),("BOX",(0,0),(-1,-1),0.5,edge),("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
def grid(rows,widths,hc=NAVY):
    data=[[P(c,THEAD if i==0 else (TCB if j==0 else TCELL)) for j,c in enumerate(r)] for i,r in enumerate(rows)]
    t=Table(data,colWidths=widths);t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),hc),("FONTNAME",(0,0),(-1,-1),"CJK"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,LITE]),("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#c8d2de")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),2.5),("RIGHTPADDING",(0,0),(-1,-1),2.5),("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2)]));return t
flow=[]
flow+=[P("世界杯周三 049-054 终版",H1),P("北京6/25开球 · 精确CRS+6场深研 · 主轴=动机/战意",SUB)]
flow+=[box(P("<b>主轴:今天热门'想不想赢'差别极大。</b>049加拿大(平即头名·求稳)、054墨西哥(头名已锁·躺平轮换)=昨夜046英格兰式<b>无动机热门→易被冻平,fade它</b>(让平/受让/平/小球)。050生死战卡塔尔必搏(非铁桶)、051巴西/052摩洛哥有争头名动力。<b>纠错:CRS示巴西2.03/摩洛哥2.29打穿真live,别低估热门进球(昨夜045教训)。</b>",SMALL),bg=ROSE,edge=RED)]
flow+=[Spacer(1,4),band("精确逐队反推(现盘CRS,禁嘴算)",NAVY),Spacer(1,3)]
flow+=[grid([
 ["场","主期望","客期望","净胜结构","热门比分/总进球"],
 ["049瑞-加","瑞1.33","加1.09","平33/瑞39/加27","1-1;小/2球"],
 ["050波-卡","波1.91","卡0.92","波61/平19","2-1;模态3球"],
 ["051苏-巴","苏0.73","巴2.03","巴68","0-2/0-1;模态3"],
 ["052摩-海","摩2.29","海0.56","摩75","2-0/3-0;模态3"],
 ["053南-韩","南0.90","韩1.57","韩52/平26","1-1/0-1;小/2球"],
 ["054捷-墨","捷1.07","墨1.44","墨46/平25/捷28","1-1;模态2球"],
],[18*mm,16*mm,16*mm,24*mm,22*mm])]
flow+=[Spacer(1,4),band("建议比分 + 最优玩法 + 信心",GOLD),Spacer(1,3)]
flow+=[grid([
 ["场","建议比分","最优玩法","信心"],
 ["049瑞-加","1-1、1-0","总进球小/平;避加拿大主胜","★★"],
 ["050波-卡","2-1、2-0","比分2-1;避波黑让-1.5","★★★"],
 ["051苏-巴","0-1、0-2","巴西让平@3.63(0-2亦live)","★★★"],
 ["052摩-海","2-0、3-0","比分2-0/3-0;让-2硬币","★★★"],
 ["053南-韩","0-1(韩)、2-1","◎韩国让平(净1)@2.10","★★★★"],
 ["054捷-墨","1-1、0-1","◎捷克+1(让平)+小2.5","★★★"],
],[16*mm,20*mm,46*mm,14*mm],hc=GOLD)]
flow+=[Spacer(1,3),box(P("<b>评判员单关¥15 = 053 韩国让平(净胜1球)@2.10</b>——模态正中(两热门比分0-1/1-2全净1),韩主帅公开必胜不求平、南非双停瘫中场打不开。<b>次选 054 捷克+1(让平3.55)+小2.5</b>(fade躺平墨西哥)。<b>引擎A档(053韩×054墨)的054墨胜不建议照搬</b>(躺平、动机≈0)。比分当彩票小额、整票0/94、空仓合法。",SMALL))]
out=Path(".nutmeg-data/jczq/daily/2026-06-24/wc-md3-FINAL-20260624.pdf")
SimpleDocTemplate(str(out),pagesize=(112*mm,260*mm),leftMargin=8*mm,rightMargin=8*mm,topMargin=8*mm,bottomMargin=7*mm,title="WC 6/24 049-054 终版").build(flow)
print(f"PDF: {out} ({out.stat().st_size}B)")
load_dotenv();token=os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN");ids=[int(x) for x in os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS","").split(",") if x.strip()]
if token and ids:
    from nutmeg.interfaces.bot.telegram import TelegramBotClient
    c=TelegramBotClient(token=token)
    cap=("🏆 世界杯周三049-054终版(精确CRS+6场深研)\n主轴=动机:fade无动机热门(加拿大求稳/墨西哥躺平=昨夜046式)。\n★评判员单关=053韩国让平(净1)@2.10 ★次=054捷克+1+小2.5(fade墨)\n建议比分:049=1-1 050=2-1 051=0-1/0-2 052=2-0/3-0 053=0-1(韩) 054=1-1\n引擎A档054墨胜不建议照搬。整票0/94,小额,空仓合法。")
    for cid in ids: c.send_document(chat_id=cid,document_path=out,caption=cap);print(f"sent {cid}")
    print("DONE")
else: print("⚠️无TG凭据")
