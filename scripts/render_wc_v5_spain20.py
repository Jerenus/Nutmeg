#!/usr/bin/env python3
"""v5 终票: 037西班牙2-0子盘已挂(@5.80), 接进高赔(≥10x)组合。手机PDF+bot推送。"""
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
HEAD=s("HEAD",11,colors.white,lead=14,sp=0); BODY=s("BODY",8.5,colors.black,lead=12.4,sp=3)
SMALL=s("SMALL",7.6,GREY,lead=10.8,sp=2); THEAD=s("TH",7.7,colors.white,lead=10.2)
TCELL=s("TC",7.5,colors.black,lead=10.2); TCB=s("TCB",7.5,NAVY,lead=10.2)
def P(t,st=BODY): return Paragraph(t,st)
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
        ("TOPPADDING",(0,0),(-1,-1),2.5),("BOTTOMPADDING",(0,0),(-1,-1),2.5)])); return t

flow=[]
flow+=[P("世界杯6/21 · v5 终票",H1),
       P("037 西班牙比分子盘已挂 · 接『西班牙 2-0 @5.80』进 ≥10x 组合",SUB)]
flow+=[box(P("✅ 037子盘已挂: <b>西班牙2-0 @5.80</b>(短于1-0@8.00、近3-0@5.50→市场也认同2-0比1-0更可能)。让球开-2(西-2主1.77)。下列为高方差彩票区, 每注小额、空仓也合法。",SMALL))]
flow+=[Spacer(1,5)]

flow+=[band("含『西班牙2-0』的 ≥10x 组合(命中优先)",GOLD),Spacer(1,3)]
flow+=[grid([
  ["组合","赔率","粗估命中"],
  ["🥇 西2-0 × 040 NZ+1","13.6x","≈8%"],
  ["🥈 西2-0 × 039 乌晚破dh","20.3x","≈5-6%"],
  ["🥉 西2-0 × 比胜 × 039dh","26.8x","≈4%"],
  ["彩票 西2-0 × 乌1-0 × 埃1-0","153x","≈1%"],
],[52*mm,18*mm,24*mm],hc=GOLD)]
flow+=[Spacer(1,4)]

flow+=[band("🥇 主推 西2-0 × 040 NZ+1 (13.6x)",GREEN),Spacer(1,3)]
flow+=[P("<b>西班牙 2-0 比分(5.80) × 新西兰+1 让球主胜(2.35)</b>",s('m',9,NAVY,lead=12,sp=3))]
flow+=[grid([
  ["腿","球理"],
  ["西班牙 2-0","今日最高信心比分。西必赢但进球荒+亚马尔仅45'+沙特门将Al-Owais火热(对乌9救)→小胜2-0封顶, 不开闸。市场同向(2-0短于1-0)"],
  ["040 NZ+1","埃及破低位铁桶是历史顽疾(AFCON 0球)+新西兰死守→埃及大概率赢不了2球。平局 or 新西兰偷分都吃, 是040最宽的命中窗口"],
],[18*mm,76*mm])]
flow+=[P("为何是它: 两腿都是『防守型对手把favorite摁住』的同一气质(西被摁成2-0、埃及被摁到破不开), 2腿=高赔里命中最高(~8%)。", s('w',7.8,GREEN,lead=11))]
flow+=[Spacer(1,4)]

flow+=[band("🥈 备选 西2-0 × 039 乌晚破dh (20.3x)",BLUE),Spacer(1,3)]
flow+=[P("西班牙2-0(5.80) × 乌拉圭半平/全主(3.50)。两个favorite都把铁桶磨穿小胜——西2-0、乌拉圭被佛得角顶住上半场、下半场凿门取胜。赔率更高、命中略低。",BODY)]
flow+=[Spacer(1,4)]

flow+=[box(P("<b>纪律</b>: ≥10x=高方差, 命中5-8%, 长期多输少赢, 娱乐预算极小额(主推≤¥10、彩票≤¥5), 别加注追。🥇(040铁桶守住)与🥈(乌铁桶被破)是不同方向, 选一个信的即可。命门仍是西班牙——若被沙特闷平, 含2-0的票全灭。", SMALL),bg=ROSE,edge=RED)]
flow+=[P("稳单底座(分开账): 西×比 2串1≈1.43x; 评判员¥15单关=比利时胜@1.32。", s('f',7.2,GREY,lead=10,al=1))]

out=Path(".nutmeg-data/jczq/daily/2026-06-21/wc-md2-v5-spain20-hi-odds-20260621.pdf")
SimpleDocTemplate(str(out),pagesize=(112*mm,200*mm),leftMargin=8*mm,rightMargin=8*mm,topMargin=8*mm,bottomMargin=7*mm,
    title="WC2026 6/21 v5终票 西班牙2-0高赔").build(flow)
print(f"PDF written: {out} ({out.stat().st_size} bytes)")
load_dotenv()
token=os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN")
ids=[int(x) for x in os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS","").split(",") if x.strip()]
from nutmeg.interfaces.bot.telegram import TelegramBotClient
client=TelegramBotClient(token=token)
cap=("🏆 v5终票 · 037子盘已挂, 接西班牙2-0(@5.80)进高赔\n"
     "🥇主推 西2-0 × 040 NZ+1 = 13.6x(高赔里命中最高~8%)\n"
     "🥈 西2-0 × 039乌晚破dh = 20.3x  🥉×比胜×039dh=26.8x  彩票153x\n"
     "高方差, 每注≤¥10。命门: 西若被沙特闷平整票全灭。")
for cid in ids:
    client.send_document(chat_id=cid,document_path=out,caption=cap); print(f"sent to {cid}")
print("DONE")
