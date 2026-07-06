#!/usr/bin/env python3
"""Morocco vs Haiti single-match deep research report (2026-06-24 #052). Phone PDF + bot push."""
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

for p in ["/System/Library/Fonts/Supplemental/Songti.ttc", "/System/Library/Fonts/STHeiti Light.ttc", "/System/Library/Fonts/PingFang.ttc"]:
    if Path(p).exists():
        pdfmetrics.registerFont(TTFont("CJK", p, subfontIndex=0)); break

NAVY=colors.HexColor("#10243f"); BLUE=colors.HexColor("#1d4e79"); GOLD=colors.HexColor("#b8860b")
RED=colors.HexColor("#a01b1b"); GREEN=colors.HexColor("#1d6b3a"); GREY=colors.HexColor("#444444")
LITE=colors.HexColor("#eef2f7"); WARM=colors.HexColor("#fdf3e3"); ROSE=colors.HexColor("#f3e1e1"); MINT=colors.HexColor("#e3f1e8")

def s(n,sz,c=colors.black,lead=None,sp=2,al=0): return ParagraphStyle(n,fontName="CJK",fontSize=sz,textColor=c,leading=lead or sz*1.4,spaceAfter=sp,alignment=al)
H1=s("H1",14,NAVY,lead=17,sp=2,al=1); SUB=s("SUB",7.8,GREY,lead=10.6,sp=4,al=1); HEAD=s("HEAD",10,colors.white,lead=12.5)
SMALL=s("SMALL",7.2,GREY,lead=10.4,sp=2); BODY=s("BODY",7.4,colors.black,lead=10.8,sp=2)
THEAD=s("TH",6.9,colors.white,lead=9.3); TCELL=s("TC",6.8,colors.black,lead=9.1); TCB=s("TCB",6.8,NAVY,lead=9.1)
def P(t,st=SMALL): return Paragraph(t,st)
def band(t,c=BLUE): return Table([[Paragraph(t,HEAD)]],colWidths=[96*mm],style=TableStyle([("BACKGROUND",(0,0),(-1,-1),c),("LEFTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
def box(p,bg=WARM,edge=GOLD): return Table([[p]],colWidths=[96*mm],style=TableStyle([("BACKGROUND",(0,0),(-1,-1),bg),("BOX",(0,0),(-1,-1),0.5,edge),("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
def grid(rows,widths,hc=NAVY):
    data=[[P(c,THEAD if i==0 else (TCB if j==0 else TCELL)) for j,c in enumerate(r)] for i,r in enumerate(rows)]
    t=Table(data,colWidths=widths); t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),hc),("FONTNAME",(0,0),(-1,-1),"CJK"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,LITE]),("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#c8d2de")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),2.5),("RIGHTPADDING",(0,0),(-1,-1),2.5),("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2)])); return t

flow=[]
flow+=[P("摩洛哥 vs 海地",H1),P("2026 世界杯 C 组收官战(MD3) · 北京 6/25 06:00 (美东 6/24) · 亚特兰大<br/>单场深度研究 · 主循环深研 + Dixon-Coles 比分矩阵(禁嘴算) · 2026-06-24",SUB)]
flow+=[box(P("<b>一句话:摩洛哥赢无悬念(80%),分歧全在『赢几个』。</b> 体彩只开让球盘-2、两端 2.25≈\2.35 对开 = 市场认『摩净胜≥3』与『净胜≤1』五五开。真正要研判的不是胜负,而是 <b>摩洛哥能否打穿海地铁桶 + 海地的战意(死守还是躺平)</b>。",BODY),bg=WARM,edge=GOLD)]

flow+=[Spacer(1,4),band("(1) 盘口底座 (国际去水 fair · 14 家庄)",NAVY),Spacer(1,2)]
flow+=[grid([
 ["盘口","读数","备注"],
 ["胜平负","摩 80.0% / 平 14.0% / 海 6.1%","Opta 81% 印证"],
 ["大小球 2.5","国际:大 60.8% / 博彩:小 ~58%","⚠两盘打架"],
 ["体彩(仅让球-2)","让胜2.25 / 走盘3.85 / 受让2.35","净≥3 与 净≤1 对开"],
],[20*mm,46*mm,30*mm])]

flow+=[Spacer(1,4),band("(2) 出线情境 (本场灵魂 · 决定战意)",BLUE),Spacer(1,2)]
flow+=[grid([
 ["名次","队","分","净","前两轮"],
 ["1","巴西","4","+3","1-1摩 / 3-0海"],
 ["2","摩洛哥","4","+1","1-1巴 / 1-0苏"],
 ["3","苏格兰","3","0","· / 0-1摩"],
 ["4","海地","0","-4","0-1苏 / 0-3巴 (已淘汰)"],
],[12*mm,18*mm,10*mm,12*mm,44*mm])]
flow+=[Spacer(1,2),box(P("摩洛哥几乎已锁出线 → <b>出线不是悬念,头名才是</b>。与巴西同积 4 分、<b>H2H 1-1 平局无法分胜负 → 直接比净胜球</b>(摩+1 落后巴+3 两个)。两场同时开球、互相看不到比分 → <b>摩洛哥只能『自己尽量多进』、全程不收脚</b>。头名奖励=R32 避开德国级硬签。海地已数学出局、世界杯首支被淘汰队、5 届 0 球 0 分。",SMALL))]

flow+=[Spacer(1,4),band("(3) 客观实力 · 矛盾点=钝刀 vs 铁桶",NAVY),Spacer(1,2)]
flow+=[box(P("<b>摩洛哥=控球碊压 + 转化钝刀(实锤):</b> vs巴西 14 射 xG 反超只 1-1;vs苏格兰 601 传球 xG0.97 只 1-0。<b>全队两球全靠 Saibari 一人、两助攻全靠 Brahim Diaz 一人</b>。防守极硬(近 11 场只丢 4)。",SMALL),bg=LITE,edge=BLUE)]
flow+=[Spacer(1,2),box(P("<b>海地=纪律铁桶,不是散沙:</b> vs苏格兰打出<b>队史世界杯最佳防守</b>(只丢1、只让射正2、5-4-1 把苏压到 0.54 xG)。3-0 输巴西是被维尼修斯/库尼亚<b>个人能力</b>打穿,非体系崩盘。",SMALL),bg=LITE,edge=BLUE)]

flow+=[Spacer(1,4),band("(4) 作战损耗 + 战斗意志 (状态≠战意)",BLUE),Spacer(1,2)]
flow+=[grid([
 ["维度","摩洛哥","海地"],
 ["状态/损耗","Ouahbi亲口『最强阵容、不轮换』","头号射手 Nazon 伤情存疑"],
 ["战意方向","↑ 刷净胜球争头名+避硬签","↓ 围城死守(为荣誉抢首分)"],
 ["净判","想拉开比分","想把比分焊死在小数字"],
],[16*mm,40*mm,40*mm],hc=BLUE)]
flow+=[Spacer(1,2),box(P("<b>关键:轮换稀释净胜球的最大下压变量被 Ouahbi 排除</b>(确认全力出战)。两股战意方向相反对撞 → <b>摩洛哥大概率赢、但赢得没有『净胜球叙事』那么大</b>(钝刀喂不出爆破手 + 海地越围攻越铁)。",SMALL))]

flow+=[Spacer(1,4),band("(5) 比分概率矩阵 (DC 拟合 λ搩2.56/λ海0.58 · 禁嘴算)",GOLD),Spacer(1,2)]
flow+=[grid([
 ["比分","概率","|","净胜分布","概率"],
 ["2-0 模态","14.2%","|","海地胜/平","20.1%"],
 ["3-0","12.1%","|","摩 胜1球","21.4%"],
 ["1-0","10.9%","|","摩 胜2球","22.6%"],
 ["2-1","8.2%","|","摩 胜3+球","36.0%"],
 ["0-0","4.5%","|","摩洛哥零封合计","56.0%"],
],[18*mm,14*mm,4*mm,24*mm,16*mm],hc=GOLD)]

flow+=[Spacer(1,4),band("(6) 小球三比分 0-0/1-0/2-0 · 两口径中奖率",NAVY),Spacer(1,2)]
flow+=[grid([
 ["口径","λ摩/λ海","0-0","1-0","2-0","中奖"],
 ["盘口(国际fair,偏大球)","2.56/0.58","4.6%","10.8%","14.2%","29.6%"],
 ["我的预估(钝刀+铁桶,偏小)","2.18/0.38","7.1%","17.5%","18.4%","43.0%"],
],[34*mm,16*mm,9*mm,9*mm,9*mm,11*mm])]
flow+=[Spacer(1,2),box(P("两数差 13pp,<b>全差在大小球分歧</b>:盘口押大球(60.8%)→小比分稀薄;我深研后认进球偏小(钝刀+铁桶+Nazon伤缺+博彩真金押Under)→小比分变厚。<b>你认小球,就是站在我这边对赌国际盘的大球。</b>三比分互斥、中奖=相加;体彩买不了比分,需去国际盘且抽水重。",SMALL))]

flow+=[Spacer(1,4),band("(7) 下注建议 (按你认小球的偏好)",GREEN),Spacer(1,2)]
flow+=[grid([
 ["载体","我预估命中","我预估EV","评级"],
 ["★受让海地+2 @2.35","45.6%","+7.2% 正","主推"],
 ["比分1-0/2-0(国际盘)","35.9%","看赔率>2.33","彩票点缀"],
 ["0-0(你的最爱·最虚)","7.1%","纯彩票","极小额"],
 ["走盘 净胜2 @3.85","24.0%","-7.6%","对冲"],
 ["摩-2 @2.25(押大胜)","30.4%","-31.6%","禁别碰"],
],[34*mm,17*mm,18*mm,16*mm],hc=GREEN)]
flow+=[Spacer(1,2),box(P("<b>★主推:受让海地+2 @2.35(\xa515)。</b> 它就是你『认小球』的最优让球表达——海地+2 赢 = 摩净胜≤1 = <b>1-0/0-0/平/海地爆冷全包</b>,命中最高(我预估 45.6%)、<b>全场唯一正 EV(+7.2%)</b>、低方差睡得着、体彩唯一能下。手祩博比分高赔 → 国际盘 1-0/2-0 各小额、0-0 点缀。",BODY),bg=MINT,edge=GREEN)]
flow+=[Spacer(1,2),box(P("<b>\U0001f6ab 红线:摩-2(押净胜≥3 大胜)我预估 -31.6% 最差、与你信念正相反;大球同理别碰。</b> 纪律:此为深研/娱乐小额票、与引擎注金永不合账;比分盘抽水重、下手前核对赔率;<b>整票失败教训本窗口 0/20+、空仓永远合法</b>。今天我信心最高的评判员单关其实是 054 捷克+1(非本场),052 给信心 3。",SMALL),bg=ROSE,edge=RED)]

out=Path("/Users/jz71/Projects/Nutmeg/.nutmeg-data/jczq/daily/2026-06-24/wc-morocco-haiti-20260624.pdf")
SimpleDocTemplate(str(out),pagesize=(112*mm,260*mm),leftMargin=8*mm,rightMargin=8*mm,topMargin=8*mm,bottomMargin=7*mm,title="Morocco vs Haiti deep research 6/24").build(flow)
print(f"PDF_OK: {out} ({out.stat().st_size}B)")

load_dotenv(); token=os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN"); ids=[int(x) for x in os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS","").split(",") if x.strip()]
if token and ids and os.environ.get("SEND")=="1":
    from nutmeg.interfaces.bot.telegram import TelegramBotClient
    c=TelegramBotClient(token=token)
    cap=("⚽ 摩洛哥 vs 海地 — 单场深度研究 (世界杯C组收官战 6/25 06:00)\n"
         "核心:摩胜无悬念(80%),分歧全在『赢几个』。体彩只开让球-2。\n"
         "比分概率:2-0=14% 1-0=11% 0-0=4.5% (DC禁嘴算)\n"
         "小球三比分0-0/1-0/2-0中奖:盘口29.6% / 我的预估43%(认小球)\n"
         "★下注建议:受让海地+2@2.35(我预估45.6%命中/EV+7.2%正/唯一能下)\n"
         "\U0001f6ab别碰摩-2(押大胜-31.6%)与大球。娱乐小额、空仓合法。")
    for cid in ids: c.send_document(chat_id=cid,document_path=out,caption=cap); print(f"sent {cid}")
    print("PUSH_DONE")
else: print("NO_TG_CREDS")
