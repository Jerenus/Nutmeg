#!/usr/bin/env python3
"""v6 打穿版: 西班牙-2(赢3+,~50%)当锚 替代精确2-0, 接进≥10x组合。手机PDF+bot推送。"""
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
flow+=[P("世界杯6/21 · v6 打穿版",H1),
       P("西班牙 -2(赢3+, ~50%) 当锚 · 替代精确2-0 · 接进 ≥10x 组合",SUB)]
flow+=[box(P("市场让球开<b>西班牙-2</b>: 主1.77去水后<b>『西班牙赢3+(打穿)』≈50%</b>——是今日单一最可能结果(精确2-0仅~17-20%)。但1.77太短, 够10x要串窄比分腿或多串一腿, 命中被吃回一部分。",SMALL))]
flow+=[Spacer(1,5)]

# 取舍对照
flow+=[band("取舍对照: -2锚 vs 2-0锚",GOLD),Spacer(1,3)]
flow+=[grid([
  ["锚","组合","赔率","命中"],
  ["西-2(赢3+)","西-2×040埃1-0 ★","10.2x","~9%"],
  ["西-2(赢3+)","西-2×039乌dh×040NZ+1","14.6x","~6.2%"],
  ["西-2(赢3+)","西-2×比胜×040埃1-0","13.4x","~6.0%"],
  ["西2-0(对照)","西2-0×040NZ+1","13.6x","~7.4%"],
  ["西2-0(对照)","西2-0×039乌dh","20.3x","~5.4%"],
],[20*mm,40*mm,16*mm,18*mm],hc=GOLD)]
flow+=[P("换-2锚: ≥10x最高命中 7.4%→9%(真实但有限), 赔率 13.6→10.2x。本质=把『窄』从西班牙净胜球挪到埃及精确比分。",SMALL)]
flow+=[Spacer(1,5)]

# 主推
flow+=[band("🥇 主推 西-2 × 040埃1-0 (10.2x · ~9%)",GREEN),Spacer(1,3)]
flow+=[P("<b>西班牙赢3+(让-2主胜, 1.77) × 埃及1-0(040客1-0, 5.75)</b>",s('m',9,NAVY,lead=12,sp=3))]
flow+=[grid([
  ["腿","球理"],
  ["西-2 赢3+","实力23:1+市场让-2, 打穿≈50%。关键看首球: 30-40分钟内进球→沙特压出来追、西班牙质量收割→3-0/4-0。亚特兰大闭顶空调利传控提速"],
  ["040 埃及1-0","埃及高新西兰一档+旅行占优, 但破密防顽疾→不会大胜; 凿1球小胜(1-0)是中心剧本。硬防守(资格赛7零封)守得住"],
],[20*mm,74*mm])]
flow+=[P("内在一致: <b>差距越大越可能打穿</b>(西≫沙→爆; 埃及仅略强新→只能磨1-0)。两腿正贴各自gap。", s('w',7.8,GREEN,lead=11))]
flow+=[Spacer(1,4)]

# 备选
flow+=[band("🥈 备选 西-2 × 039乌dh × 040NZ+1 (14.6x · ~6.2%)",BLUE),Spacer(1,3)]
flow+=[P("西-2(1.77) × 乌拉圭半平/全主(3.50) × 新西兰+1(2.35)。三条宽腿、不靠精确比分: 西班牙打穿 + 乌拉圭下半场凿穿佛得角 + 埃及破不开新西兰(平/新偷分)。赔率更高、不押exact score。",BODY)]
flow+=[Spacer(1,4)]

flow+=[box(P("<b>-2锚的新风险</b>: 锚从『2-0精确』变成『西班牙必须赢3+』——西班牙若只赢1-0/2-0(进球荒+亚马尔45'很可能), 让-2即输。即把『猜对比分』的窄, 换成『赢得够不够大』的险, ~50%命中已含此险。<b>纪律</b>: ≥10x高方差, 每注≤¥10别追注; 选一版信的(打穿用本版, 摁小胜用v5的2-0版)。", SMALL),bg=ROSE,edge=RED)]
flow+=[P("稳单底座(分开账): 西×比 2串1≈1.43x; 评判员¥15单关=比利时胜@1.32。", s('f',7.2,GREY,lead=10,al=1))]

out=Path(".nutmeg-data/jczq/daily/2026-06-21/wc-md2-v6-spain-minus2-20260621.pdf")
SimpleDocTemplate(str(out),pagesize=(112*mm,205*mm),leftMargin=8*mm,rightMargin=8*mm,topMargin=8*mm,bottomMargin=7*mm,
    title="WC2026 6/21 v6 西班牙-2打穿版").build(flow)
print(f"PDF written: {out} ({out.stat().st_size} bytes)")
load_dotenv()
token=os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN")
ids=[int(x) for x in os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS","").split(",") if x.strip()]
from nutmeg.interfaces.bot.telegram import TelegramBotClient
client=TelegramBotClient(token=token)
cap=("🏆 v6打穿版 · 西班牙-2(赢3+,~50%)当锚\n"
     "🥇 西-2 × 040埃1-0 = 10.2x(≥10x里命中最高~9%)\n"
     "🥈 西-2 × 039乌dh × 040NZ+1 = 14.6x(宽腿不押比分)\n"
     "换-2锚: 命中7.4%→9%, 赔率13.6→10.2x, '窄'从西班牙margin挪到埃及比分。\n"
     "新险: 西若只赢1-2球(进球荒), 让-2即输。")
for cid in ids:
    client.send_document(chat_id=cid,document_path=out,caption=cap); print(f"sent to {cid}")
print("DONE")
