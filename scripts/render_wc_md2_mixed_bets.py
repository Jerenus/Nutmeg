#!/usr/bin/env python3
"""v4 高赔版(≥10x专版): 2026-06-21 世界杯 MD2——稳单逻辑作底座, 只列≥10倍组合, 每注标球理。手机PDF+bot推送。"""
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
HEAD=s("HEAD",11,colors.white,lead=14,sp=0); BODY=s("BODY",8.4,colors.black,lead=12.3,sp=3)
SMALL=s("SMALL",7.6,GREY,lead=10.8,sp=2); THEAD=s("TH",7.6,colors.white,lead=10.2)
TCELL=s("TC",7.4,colors.black,lead=10.0); TCB=s("TCB",7.4,NAVY,lead=10.0)

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
flow+=[P("2026 世界杯 · 6/21 四场 MD2",H1),
       P("<b>v4 高赔版 · 只列 ≥10 倍组合</b> · 稳单逻辑作底座, 进入高方差彩票区",SUB)]
flow+=[box(P("引擎层<b>今日空仓</b>。稳单(西×比 2串1 ≈1.43x)作底座保留, 本版按新规<b>只列 ≥10x</b>。提醒: 四场favorites全胜也仅2.73x → 必须用比分/半全场/让球平抬赔率, <b>命中率必然降到 5-9%</b>。娱乐预算小额、空仓也合法。",SMALL),bg=ROSE,edge=RED)]
flow+=[Spacer(1,4)]

# 阶梯
flow+=[band("≥10x 组合阶梯(按命中粗排)",GOLD),Spacer(1,3)]
flow+=[grid([
  ["组合","赔率","粗估命中"],
  ["① 两强净胜恰1球: 038比净1×040埃净1","11.9x","≈8.4%"],
  ["② 净1+晚破: 038比净1×039晚破dh","12.3x","≈8.2%"],
  ["③ 双铁桶晚破: 039晚破dh×040晚破da ★","14.4x","≈7.0%"],
  ["④ 锚+两情景4串: 西×比×039dh×040NZ+1","11.5x","≈6.8%"],
  ["⑤ 双铁桶守住(双平): 039平×040平","14.9x","≈5.5%"],
  ["⑥ 双低分比分: 039乌1-0×040埃1-0","26.5x","≈3.8%"],
  ["⑦ 净1×3(搏): 038比净1×040埃净1×039dh","41.7x","≈2.4%"],
],[57*mm,16*mm,21*mm],hc=GOLD)]
flow+=[P("命中为体彩含抽水粗估, <b>真实略高</b>(让球平/半全场单市场抽水大)。1X2/平用去水fair。",SMALL)]
flow+=[Spacer(1,5)]

# 主推
flow+=[band("主推 ③ 双铁桶晚破 (2串1 · 14.4x)",GREEN),Spacer(1,3)]
flow+=[P("<b>039 半平/全主 dh(3.50) × 040 半平/全客 da(4.10)</b>",s('m',9,NAVY,lead=12,sp=3))]
flow+=[P("一句话球理: <b>两场都是『铁桶被强队下半场凿穿』</b>——上半被顶住打平、下半favorite破门取胜。这是研究对两个铁桶场最一致的读法, 且用半全场避开了让球平的过拟合。", BODY)]
flow+=[grid([
  ["腿","球理底座"],
  ["039 乌晚破 dh","佛得角铁桶(0封西)+迈阿密酷热压节奏→不会早丢; 乌缺Arrascaeta慢热, 多半下半场才凿穿。半平全主正贴此形态"],
  ["040 埃晚破 da","埃及破密防顽疾(AFCON 0球)+旅行占优体能足→大概率僵到下半场, 靠萨拉赫/定位球凿1球。半平全客正贴"],
],[20*mm,74*mm])]
flow+=[P("⚠️ 风险: 若favorite上半场就进球(变hh/aa)或铁桶守满全场(变平), 该腿即挂。", s('w',7.6,RED,lead=10.6))]
flow+=[Spacer(1,5)]

# 备选
flow+=[band("备选(不同球理, 同样 ≥10x)",BLUE),Spacer(1,3)]
def alt(tag,title,detail,color):
    h=Table([[P(f"<b>{tag}</b> {title}",s('at',8.6,colors.white,lead=11.5))]],colWidths=[96*mm],style=TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),color),("LEFTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
    b=Table([[P(detail,s('ad',7.8,colors.black,lead=11))]],colWidths=[96*mm],style=TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),colors.white),("BOX",(0,0),(-1,-1),0.5,color),("LEFTPADDING",(0,0),(-1,-1),6),
        ("RIGHTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
    return [h,b,Spacer(1,3)]
flow+=alt("①最高命中","两强净胜恰1球 (11.9x · ≈8.4%)",
  "038比净1(3.50)×040埃净1(3.40)。两强各赢恰1球(比2-1/埃1-0)。⚠️038是开放场, 比利时也可能2-0(净2)→该腿比'晚破'略脆, 但命中数字最高。",GOLD)
flow+=alt("⑤最敢偏离","双铁桶守住·双平 (14.9x · 真实~7%)",
  "039平(4.00)×040平(3.72)。赌两个铁桶都守满全场。两场平局fair本就抬升(酷热/破密防顽疾), 且平赔抽水低=价值好。最contrarian。",BLUE)
flow+=alt("⑥搏最大","双低分比分串 (26.5x · ≈3.8%)",
  "039乌1-0(4.60)×040埃1-0(5.75)。两场都打favorite 1-0小胜的精确比分。赔率最大、命中最低, ≤¥10当彩票。",GREY)
flow+=[Spacer(1,2)]
flow+=[box(P("<b>纪律</b>: ≥10x=高方差, 命中5-9%, 长期多输少赢的彩票区, 只用娱乐预算极小额(建议每注≤¥10), 别加注追。多张不同球理的票(③晚破/⑤守住)互斥, 选一个信的方向即可。若037西班牙比分子盘临场挂出, '西班牙2-0'是今日最高信心比分腿, 可替换抬赔。", SMALL))]
flow+=[P("评判员¥15单关(稳单)=比利时胜@1.32, 与高赔票分开账。⚠️038开球或落北京6/22凌晨, 以体彩'周日038'售卖为准。", s('f',7.2,GREY,lead=10,al=1))]

out=Path(".nutmeg-data/jczq/daily/2026-06-21/wc-md2-mixed-bets-v4-hi-odds-20260621.pdf")
SimpleDocTemplate(str(out),pagesize=(112*mm,235*mm),leftMargin=8*mm,rightMargin=8*mm,topMargin=8*mm,bottomMargin=7*mm,
    title="WC2026 6/21 MD2 高赔版v4").build(flow)
print(f"PDF written: {out} ({out.stat().st_size} bytes)")

load_dotenv()
token=os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN")
ids=[int(x) for x in os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS","").split(",") if x.strip()]
from nutmeg.interfaces.bot.telegram import TelegramBotClient
client=TelegramBotClient(token=token)
cap=("🏆 世界杯6/21 MD2 · v4高赔版(≥10x专版)\n"
     "稳单逻辑作底座; 四强全胜仅2.73x→须用比分/半全场抬赔, 命中降5-9%。\n"
     "★主推③ 双铁桶晚破 039dh(3.5)×040da(4.1)=14.4x\n"
     "备选①两强净胜1球11.9x(命中最高) ⑤双平14.9x(最敢偏离) ⑥双低分比分26.5x\n"
     "高方差彩票区, 每注≤¥10。")
for cid in ids:
    client.send_document(chat_id=cid,document_path=out,caption=cap); print(f"sent to {cid}")
print("DONE")
