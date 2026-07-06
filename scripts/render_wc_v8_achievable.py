#!/usr/bin/env python3
"""v8 可实现高赔版: 实力+人性(盘口=大众心理), 让平为核心, 而非纯数学。手机PDF+bot推送。"""
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
HEAD=s("HEAD",11,colors.white,lead=14,sp=0); BODY=s("BODY",8.4,colors.black,lead=12.2,sp=3)
SMALL=s("SMALL",7.5,GREY,lead=10.6,sp=2); THEAD=s("TH",7.6,colors.white,lead=10.0)
TCELL=s("TC",7.4,colors.black,lead=9.9); TCB=s("TCB",7.4,NAVY,lead=9.9)
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
        ("TOPPADDING",(0,0),(-1,-1),2.3),("BOTTOMPADDING",(0,0),(-1,-1),2.3)])); return t

flow=[]
flow+=[P("6/21 四场 · v8 可实现高赔版",H1),
       P("实力 + 人性(盘口=大众心理镜子) · 让平为核心 · 非纯数学堆命中",SUB)]
flow+=[box(P("<b>实证(最近大胆腿按玩法命中)</b>: 让球 <b>10/67=15%(最高,几乎全是『让平』)</b> · 比分 3/50(命中是<b>1:1闷平</b>) · <b>胜平负冷门 0/23=大众『爆冷梦』死亡陷阱</b> · 总进球 0/5。→ 高赔不是不能中, 而是要押『让平/闷平比分/晚破』这些被大众低估的, 别押冷门正路。",SMALL),bg=ROSE,edge=RED)]
flow+=[Spacer(1,4)]

flow+=[band("人性框架: 盘口反映的大众偏差",GREEN),Spacer(1,3)]
flow+=[grid([
  ["大众高估(别跟)","→ value在反面(可押)"],
  ["强队大胜/打穿(3-0/4-0)","强队净胜恰1-2球 = 让平"],
  ["强队早进球领先","上半平/下半破 = 半全场dh/da"],
  ["漂亮比分(2-1/3-0)","丑比分/闷平(1-0/1-1)"],
  ["弱队爆冷正路梦(胜平负)","❌死亡陷阱 0/23, 永远别碰"],
],[40*mm,56*mm],hc=GREEN)]
flow+=[Spacer(1,4)]

flow+=[band("四场『让平』模态比分(实力研判)",NAVY),Spacer(1,3)]
flow+=[grid([
  ["场","让平=净胜恰","模态比分","赔率","实力支撑"],
  ["037","西恰净胜2","西2-0","4.05","中:1-0/打穿也live"],
  ["038","比恰净胜1","比2-1","3.55","强:开放场by1很活"],
  ["040","埃恰净胜1","埃1-0","3.38","最强:破铁桶只能1-0"],
  ["039","乌恰净胜1","乌1-0","3.23","弱:酷热平局险"],
],[9*mm,21*mm,16*mm,13*mm,33*mm])]
flow+=[Spacer(1,4)]

flow+=[band("可实现高赔组合",GOLD),Spacer(1,3)]
flow+=[grid([
  ["#","组合","赔率","定位"],
  ["①🥇","038比让平 × 040埃让平","12.0x","两最干净『净胜1』模态"],
  ["②","037西让平(2-0) × 040埃让平","13.7x","西2-0吃大众打穿高估"],
  ["③","039乌晚破dh × 040埃晚破da","14.3x","人性:晚破被低估(半全场)"],
  ["④搏","037 × 038 × 040 三让平","48.6x","三强各净胜模态, 小额"],
],[14*mm,44*mm,15*mm,23*mm],hc=GOLD)]
flow+=[Spacer(1,3)]
flow+=[band("🥇 主推 ① 038比让平 × 040埃让平 (12.0x)",GREEN),Spacer(1,3)]
flow+=[P("<b>比利时让-1平(净胜1,3.55) × 埃及让+1平(净胜1,3.38)</b>", s('m',9,NAVY,lead=12,sp=3))]
flow+=[P("两腿都是『强队赢、但只赢 1 球』——让平是实证命中最高的高赔玩法(15%); 比利时开放场 2-1、埃及破铁桶 1-0 都是各自最可能比分。<b>人性</b>: 大众都在押比利时/埃及『赢』(让胜)或『大球』, 没人盯『净胜恰1』, 所以让平被低估。", BODY)]
flow+=[Spacer(1,4)]

flow+=[box(P("<b>诚实提醒</b>: 这仍是高赔区, 2串让平命中约个位数到~10%, 但<b>比『堆3条冷腿(0/38)』靠谱得多</b>——押的是『强队小胜』这个实力支撑的模态, 不是爆冷。命中%为研判粗估非保证。每注娱乐小额。④三让平=搏, ≤¥5。037 had体彩未挂、让-2平赔率以临场为准。", SMALL),bg=WARM,edge=GOLD)]
flow+=[P("对照: 想要稳=v7『西×比1.40x/57%』; 想要可实现高赔=本版让平12-14x。两条路按你偏好选。", s('f',7.2,GREY,lead=10,al=1))]

out=Path(".nutmeg-data/jczq/daily/2026-06-21/wc-md2-v8-achievable-hi-odds-20260621.pdf")
SimpleDocTemplate(str(out),pagesize=(112*mm,232*mm),leftMargin=8*mm,rightMargin=8*mm,topMargin=8*mm,bottomMargin=7*mm,
    title="WC2026 6/21 v8可实现高赔版").build(flow)
print(f"PDF written: {out} ({out.stat().st_size} bytes)")
load_dotenv()
token=os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN")
ids=[int(x) for x in os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS","").split(",") if x.strip()]
from nutmeg.interfaces.bot.telegram import TelegramBotClient
client=TelegramBotClient(token=token)
cap=("🏆 v8可实现高赔版 · 实力+人性(盘口=大众心理)\n"
     "实证: 让球15%(让平最准) vs 胜平负冷门0/23死亡陷阱。\n"
     "🥇① 038比让平×040埃让平=12.0x(两『净胜1』模态)\n"
     "② 037西让平2-0×040埃让平13.7x  ③半全场晚破14.3x  ④三让平48.6x\n"
     "押『强队小胜』模态, 不是爆冷; 仍高赔区, 小额。")
for cid in ids:
    client.send_document(chat_id=cid,document_path=out,caption=cap); print(f"sent to {cid}")
print("DONE")
