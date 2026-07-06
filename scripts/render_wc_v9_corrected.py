#!/usr/bin/env python3
"""v9 修正版: 砍比利时让平(挖到破organized队净胜不足), 040埃让平为核心+比利时改总进球。手机PDF+bot推送。"""
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
flow+=[P("6/21 四场 · v9 修正版",H1),
       P("砍比利时让平(挖到破organized队净胜不足) · 040埃让平为核心 · 比利时改总进球",SUB)]
flow+=[box(P("<b>修正依据(挖出来的硬数据)</b>: 伊朗FIFA第20、组织防守型。当前比利时(加西亚)<b>破不开这类队</b>: 欧洲杯0-1斯洛伐克/0-0乌克兰, 世预赛北马1-1+0-0, <b>本届MD1 1-1埃及(落后到66')</b>; 缺Debast后防漏。→ <b>比利时连『赢』都不稳, 让-1平不支持, 砍掉。</b>",SMALL),bg=ROSE,edge=RED)]
flow+=[Spacer(1,4)]

flow+=[band("比利时改走『总进球』怎么选",GREEN),Spacer(1,3)]
flow+=[P("逻辑逆转: 比利时<b>胜负是掷硬币</b>(可能被伊朗逼平)——但<b>进球总数更可预测</b>。破不开organized队(压低进球) + 双方后防都漏(比缺Debast、伊非铁桶有塔雷米反击) = <b>中等进球、双方进球, 不是0-0也不是大胜</b>。", BODY)]
flow+=[grid([
  ["总进球","赔率","判断"],
  ["0球","13.0","❌太低(双方都会进)"],
  ["1球","5.40","❌偏低"],
  ["2球","3.65","✅模态(1-1平/2-0)"],
  ["3球","3.40","✅模态(2-1/1-2,双进+分胜负)"],
  ["4球+","4.90","❌太高(比利时大胜不了)"],
],[16*mm,16*mm,62*mm],hc=GREEN)]
flow+=[P("<b>推荐: 总进球(2或3球)复式</b>≈1.76x覆盖~57% | 想要高赔单选<b>3球@3.40</b>(双方进球+比利时险胜的2-1带)。比赌『比利时赢』靠谱得多。",SMALL)]
flow+=[Spacer(1,4)]

flow+=[band("修正后高赔组合(让平核心 = 037西+040埃)",GOLD),Spacer(1,3)]
flow+=[grid([
  ["#","组合","赔率","说明"],
  ["①🥇","037西让平(2-0) × 040埃让平(埃1-0)","13.7x","Belgium-free核心, 两最干净让平"],
  ["②","040埃让平 × 038总进球3球","11.5x","比利时改总进球表达"],
  ["③搏","037西让平 × 040埃让平 × 038总进球3球","46.5x","3串, ≤¥5"],
  ["参","040埃让平 × 038总进球(2-3复式)","5.9x","<10x但窗口更宽更稳"],
],[12*mm,48*mm,15*mm,21*mm],hc=GOLD)]
flow+=[Spacer(1,3)]
flow+=[band("🥇 主推 ① 037西让平 × 040埃让平 (13.7x)",GREEN),Spacer(1,3)]
flow+=[P("<b>西班牙让-2平(西2-0, 4.05) × 埃及让+1平(埃1-0, 3.38)</b>", s('m',9,NAVY,lead=12,sp=3))]
flow+=[P("两腿都是『强队赢、恰好那个净胜』的让平(实证命中最高的高赔玩法)。西2-0=对沙特铁桶的模态(吃大众打穿高估); 埃1-0=破新西兰铁桶的最强模态。<b>都不碰比利时这个最不可靠的腿。</b>", BODY)]
flow+=[Spacer(1,4)]

flow+=[box(P("<b>诚实提醒</b>: ①仍高赔区(2串让平命中个位~10%), 但押的是『强队小胜模态』, 不是爆冷; 砍掉比利时后更干净。<b>命门</b>: 西若被沙特闷平(~13%)、埃及被新西兰逼平, 各自让平即输。每注娱乐小额; ③≤¥5。让平/总进球赔率为本会话实盘缓存, WAF限流, 临场以体彩为准。", SMALL),bg=WARM,edge=GOLD)]
flow+=[P("对照稳单: v7 西×比1.40x/57%(但比利时胜也已降级,可靠性打折)。比利时这场最务实=总进球2-3球, 而非押胜负。", s('f',7.2,GREY,lead=10,al=1))]

out=Path(".nutmeg-data/jczq/daily/2026-06-21/wc-md2-v9-corrected-20260621.pdf")
SimpleDocTemplate(str(out),pagesize=(112*mm,232*mm),leftMargin=8*mm,rightMargin=8*mm,topMargin=8*mm,bottomMargin=7*mm,
    title="WC2026 6/21 v9修正版").build(flow)
print(f"PDF written: {out} ({out.stat().st_size} bytes)")
load_dotenv()
token=os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN")
ids=[int(x) for x in os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS","").split(",") if x.strip()]
from nutmeg.interfaces.bot.telegram import TelegramBotClient
client=TelegramBotClient(token=token)
cap=("🏆 v9修正版 · 砍比利时让平(挖到破organized队净胜不足)\n"
     "比利时改总进球: 选2-3球(双方进球无大胜), 单选3球@3.40; 比赌它赢靠谱。\n"
     "🥇① 037西让平×040埃让平=13.7x(Belgium-free核心)\n"
     "② 040埃让平×038总进球3球=11.5x  ③三串46.5x\n"
     "命门: 西/埃各自让平需favorite小胜, 被逼平即输。")
for cid in ids:
    client.send_document(chat_id=cid,document_path=out,caption=cap); print(f"sent to {cid}")
print("DONE")
