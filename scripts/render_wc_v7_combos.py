#!/usr/bin/env python3
"""v7 终极组合版: 结合0/38失败教训, 命中优先+换玩法逆转, 4组2串+2组3串+1组4串。手机PDF+bot推送。"""
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
flow+=[P("6/21 四场 · v7 终极组合版",H1),
       P("结合 0/38 失败教训 · 命中优先 + 换玩法逆转 · 4×2串 + 2×3串 + 1×4串",SUB)]
flow+=[box(P("<b>失败教训(硬数据)</b>: 近期大胆/高赔串 <b>整票 0/38 全输</b>, 大胆腿命中仅 14%; 平局收割0/47、黑马让球0/20、冷门比分0/16 四主题全灭。<b>结论: 『3条冷腿堆100x+』必死。本版反着来——压赔率、抬命中。</b>",SMALL),bg=ROSE,edge=RED)]
flow+=[Spacer(1,4)]

flow+=[band("换玩法逆转(同场换玩法救命中)",GREEN),Spacer(1,3)]
flow+=[grid([
  ["场","逆转: 弃→选","为什么救"],
  ["037","让球-2/比分2-0 → 胜平负西胜","命中 40%/17% → 87%(最大逆转)"],
  ["039","乌拉圭胜 → 总进球小(1-2球)","酷热闷平时小球照赢, 乌胜输"],
  ["040","埃及胜 → NZ+1让球","埃及被逼平时NZ+1照赢, 埃胜输; 且期望最高"],
],[10*mm,40*mm,46*mm],hc=GREEN)]
flow+=[Spacer(1,4)]

flow+=[band("候选腿(已剔除冷腿/黑马/冷门比分)",NAVY),Spacer(1,3)]
flow+=[grid([
  ["腿","赔率","命中","备注"],
  ["A 西班牙胜","~1.08","87%","锚, 但~13%平/负=命门"],
  ["B 比利时胜","1.30","66%","非锚最可靠"],
  ["C 乌拉圭胜","1.30","62%","酷热下调, 平局风险"],
  ["D 埃及胜","1.44","59%","旅行占优但封顶"],
  ["D' NZ+1让球","2.35","41%","逆转腿:吃平局,期望最高0.91"],
],[20*mm,15*mm,12*mm,49*mm])]
flow+=[Spacer(1,4)]

flow+=[band("4 组 2串1",GOLD),Spacer(1,3)]
flow+=[grid([
  ["#","组合","赔率","命中"],
  ["①🛡最稳","西胜 × 比胜","1.40x","~57%"],
  ["②","西胜 × 埃胜","1.56x","~51%"],
  ["③去西","比胜 × 埃胜","1.87x","~39%"],
  ["④逆转","西胜 × NZ+1","2.54x","~36%"],
],[16*mm,42*mm,17*mm,17*mm],hc=GOLD)]
flow+=[P("①最高命中; ③不含西班牙=对冲『西班牙闷平』命门; ④用040让球逆转,赔率最高且期望值最优。",SMALL)]
flow+=[Spacer(1,3)]

flow+=[band("2 组 3串1",GOLD),Spacer(1,3)]
flow+=[grid([
  ["#","组合","赔率","命中"],
  ["⑤正路","西胜 × 比胜 × 埃胜","2.02x","~34%"],
  ["⑥逆转","西胜 × 比胜 × NZ+1","3.30x","~24%"],
],[16*mm,46*mm,16*mm,14*mm],hc=GOLD)]
flow+=[P("⑤三favorite正路命中最高; ⑥把040换NZ+1, 赔率3.3x且期望更优、吃平局。",SMALL)]
flow+=[Spacer(1,3)]

flow+=[band("1 组 4串1",GOLD),Spacer(1,3)]
flow+=[grid([
  ["#","组合","赔率","命中"],
  ["⑦全包","西胜 × 比胜 × 乌胜 × 埃胜","2.63x","~21%"],
],[16*mm,52*mm,14*mm,12*mm],hc=GOLD)]
flow+=[P("四favorite全包=最稳4串(对比0/38的100x+冷串)。想加赔率可把埃胜换NZ+1(→4.29x但命中降到15%)。",SMALL)]
flow+=[Spacer(1,4)]

flow+=[box(P("<b>命门(必读)</b>: ①②④⑤⑥⑦ <b>都含西班牙</b>——若西班牙被沙特闷平(~13%), 这6张一起死。<b>③(比×埃)是唯一不含西班牙的对冲票</b>。建议: 主下①②③中的一两张, 别7张全买(高度相关、会一起赢输)。", SMALL),bg=WARM,edge=GOLD)]
flow+=[P("纪律: 期望回收均<1(抽水), 长期娱乐; 命中优先版已最大化胜率。每注娱乐预算小额, 空仓也合法。赔率为体彩当前实盘(037 had体彩未挂,西胜用~1.08近似,临场以实盘为准)。", s('f',7,GREY,lead=9.6,al=1))]

out=Path(".nutmeg-data/jczq/daily/2026-06-21/wc-md2-v7-combos-20260621.pdf")
SimpleDocTemplate(str(out),pagesize=(112*mm,250*mm),leftMargin=8*mm,rightMargin=8*mm,topMargin=8*mm,bottomMargin=7*mm,
    title="WC2026 6/21 v7终极组合版").build(flow)
print(f"PDF written: {out} ({out.stat().st_size} bytes)")
load_dotenv()
token=os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN")
ids=[int(x) for x in os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS","").split(",") if x.strip()]
from nutmeg.interfaces.bot.telegram import TelegramBotClient
client=TelegramBotClient(token=token)
cap=("🏆 v7终极组合版 · 4×2串+2×3串+1×4串\n"
     "结合0/38失败教训(高赔冷串必死)→命中优先+换玩法逆转。\n"
     "2串: ①西×比1.40x ②西×埃 ③比×埃(去西对冲) ④西×NZ+1(逆转)\n"
     "3串: ⑤西比埃2.02x ⑥西比×NZ+1 3.30x  4串: ⑦四favorite2.63x\n"
     "命门: 6/7含西班牙, 西若闷平一起死; ③是唯一对冲票。")
for cid in ids:
    client.send_document(chat_id=cid,document_path=out,caption=cap); print(f"sent to {cid}")
print("DONE")
