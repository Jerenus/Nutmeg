#!/usr/bin/env python3
"""2026-06-22(北京6/23凌晨) 世界杯四场 MD2 深研+混合投注组合。主题=大热不大胜。手机PDF+bot推送。"""
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
H1=s("H1",14,NAVY,lead=17,sp=2,al=1); SUB=s("SUB",8.2,GREY,lead=11.5,sp=4,al=1)
HEAD=s("HEAD",11,colors.white,lead=14,sp=0); BODY=s("BODY",8.3,colors.black,lead=12.2,sp=3)
SMALL=s("SMALL",7.5,GREY,lead=10.7,sp=2); THEAD=s("TH",7.5,colors.white,lead=10.1)
TCELL=s("TC",7.3,colors.black,lead=9.9); TCB=s("TCB",7.3,NAVY,lead=9.9)

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
flow+=[P("2026 世界杯 · 四场 MD2 深研 + 混合组合",H1),
       P("北京 6/23 凌晨~上午开球(美东 6/22)· 主题=<b>大热不大胜</b>",SUB)]
flow+=[box(P("<b>引擎层今日空仓(¥0)</b>——四场让球盘去水全场统一 −11.4%、零结构 edge。下列为<b>评判员判读/创作层</b>,与引擎注金分开记账。整票历史 <b>0/94</b>、组合纯高方差娱乐, 空仓永远合法。",SMALL),bg=ROSE,edge=RED)]
flow+=[Spacer(1,4)]

# 四场判读
flow+=[band("四场判读(verdict · 比分 · 最优玩法 · 信心)",NAVY),Spacer(1,3)]
flow+=[grid([
  ["场次","判 / 比分","最优玩法 · 信心"],
  ["041 阿根廷-奥地利","阿小胜 2-1","让球平(阿净胜1)@3.48 · ★★★"],
  ["042 法国-伊拉克","法赢不打穿 2-1","让负(法净胜≤2)@1.91 · ★★★★"],
  ["043 挪威-塞内加尔","平 1-1","挪让负(不胜)@1.64/平@3.30 · ★★★"],
  ["044 约旦-阿尔及利亚","阿尔小胜 0-1","约受让平(阿尔净胜1)@3.35 · ★★★"],
],[30*mm,21*mm,45*mm],hc=NAVY)]
flow+=[P("一句话主线: 阿根廷/法国/阿尔及利亚三大热, 市场都把『打穿大胜』定价偏高; 真模态是<b>赢但净胜不覆盖大让球</b>→价值落在让球『让负/让平』(历史最准 16% 玩法)。挪vs塞三分天下掷硬币→改赌总进球 2-3 球。",SMALL)]
flow+=[Spacer(1,5)]

# 评判员单关
flow+=[band("评判员单关 ¥15(信心最高·与组合分开账)",GREEN),Spacer(1,3)]
flow+=[P("<b>042 法国让负 @1.91 — 法国赢但净胜≤2球</b>",s('m',9,NAVY,lead=12,sp=3))]
flow+=[P("球理(敢偏离市场): 体彩只卖让球-3, 市场把法国净胜3+打穿定价过半(去水让负仅46%)。我反向——法国MD1真实xG仅1.89、上半场曾0.02xG打不开; 伊拉克主帅Arnold『去赢不去不输』+40年首进世界杯的围城心态→会主动拼、大概率进1球→<b>法国零封不稳、净胜3难</b>。2-1/2-0/3-1全覆盖。", BODY)]
flow+=[P("⚠️非锁: 伊拉克刚被挪威打1-4, 法国仍可能3-0/4-1打穿(让负即挂)。这是逆市场价值腿、不是高命中锁。", s('w',7.5,RED,lead=10.5))]
flow+=[Spacer(1,5)]

# 混合组合阶梯
flow+=[band("混合投注组合阶梯(命中×赔率, 禁嘴算)",GOLD),Spacer(1,3)]
flow+=[grid([
  ["组合(主题=大热不大胜)","赔率","命中","EV"],
  ["命中优先 042法让负×043塞受让","3.13x","≈25%","−21%"],
  ["★主推 042法让负×044阿尔受让平","6.40x","≈12%","−21%"],
  ["双让平彩票 041阿让平×044阿尔受让平","11.7x","≈7%","−22%"],
  ["主题3串 042法让负×044受让胜×041阿让平","16.0x","≈4%","−31%"],
],[52*mm,15*mm,14*mm,15*mm],hc=GOLD)]
flow+=[P("命中为体彩去水估算(真实让球/让平市场抽水大→略高)。每加一腿多叠一层抽水, 命中暴跌、EV更负——<b>这就是整票0/94的数学根源</b>。",SMALL)]
flow+=[Spacer(1,4)]

# 主推组合
flow+=[band("★主推组合 ②(2串1 · 6.40x · ≈¥5彩票)",BLUE),Spacer(1,3)]
flow+=[P("<b>042 法国让负(1.91) × 044 约旦受让平(3.35)</b>",s('m',9,NAVY,lead=12,sp=3))]
flow+=[grid([
  ["腿","球理"],
  ["042 法让负","法国赢但净胜≤2(轮换+真实xG低+伊拉克会拼进球)→不打穿-3"],
  ["044 阿尔受让平","阿尔及利亚召回Mahrez+Amoura赢球, 但约旦围城死磕铁桶顽固+反击→净胜恰1(1-2/0-1), 净胜2+被高估"],
],[20*mm,74*mm])]
flow+=[P("两腿同一主题=<b>大热小胜不打穿</b>, 同押让球(历史最准)、同押模态。风险: 法国打穿/阿尔净胜2+/约旦逼平任一发生即挂。命中~12%, 纯彩票, ≤¥5。",s('w',7.5,RED,lead=10.5))]
flow+=[Spacer(1,3)]
flow+=[box(P("<b>纪律</b>: 引擎空仓¥0是合法且最优输出。想参与就<b>评判员单关¥15(法国让负)为底</b>+主推组合≤¥5当彩票, 二选一即可, 别堆冷腿别加注追。冠军pick=阿根廷(蒙卡19.6%榜首, 梅西火热, 与昨日一致)。", SMALL))]
flow+=[P("⚠️四场均北京6/23开球(美东6/22), 体彩挂『周一041-044』, 以开球前售卖为准; 临场复核首发(阿根廷Scaloni轮换/Tagliafico伤、约旦Nasib伤、阿尔Amoura+Mahrez是否首发)。", s('f',7.1,GREY,lead=9.8,al=1))]

out=Path(".nutmeg-data/jczq/daily/2026-06-22/wc-md2-mixed-bets-20260622.pdf")
SimpleDocTemplate(str(out),pagesize=(112*mm,250*mm),leftMargin=8*mm,rightMargin=8*mm,topMargin=8*mm,bottomMargin=7*mm,
    title="WC2026 6/22 MD2 深研+混合组合").build(flow)
print(f"PDF written: {out} ({out.stat().st_size} bytes)")

load_dotenv()
token=os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN")
ids=[int(x) for x in os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS","").split(",") if x.strip()]
if not token or not ids:
    print("⚠️ Telegram env 未配置, 仅生成PDF未推送"); raise SystemExit
from nutmeg.interfaces.bot.telegram import TelegramBotClient
client=TelegramBotClient(token=token)
cap=("🏆 世界杯四场 MD2 深研+混合组合(北京6/23开球)\n"
     "引擎空仓¥0(零edge)。主题=大热不大胜:阿/法/阿尔三热市场高估打穿,真模态赢但净胜不覆盖大让球→让球让负/让平。\n"
     "★评判员单关¥15: 042法国让负@1.91(法赢但净胜≤2,逆市场价值腿)\n"
     "★主推组合: 042法让负×044阿尔受让平=6.40x(≈¥5彩票)\n"
     "整票历史0/94, 高方差娱乐, 空仓亦合法。")
for cid in ids:
    client.send_document(chat_id=cid,document_path=out,caption=cap); print(f"sent to {cid}")
print("DONE")
