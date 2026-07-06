#!/usr/bin/env python3
"""2026-06-22 世界杯四场 MD2 终版判断(多轮深挖收敛)。手机PDF+bot推送。"""
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
H1=s("H1",13.5,NAVY,lead=16.5,sp=2,al=1); SUB=s("SUB",8,GREY,lead=11,sp=4,al=1)
HEAD=s("HEAD",10.5,colors.white,lead=13,sp=0); BODY=s("BODY",8.1,colors.black,lead=11.8,sp=3)
SMALL=s("SMALL",7.3,GREY,lead=10.4,sp=2); THEAD=s("TH",7.3,colors.white,lead=9.8)
TCELL=s("TC",7.1,colors.black,lead=9.6); TCB=s("TCB",7.1,NAVY,lead=9.6)

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
flow+=[P("世界杯四场 MD2 · 终版判断",H1),
       P("北京 6/23 开球 · 多轮深挖收敛(走势+边际反推+对位史)",SUB)]
flow+=[box(P("<b>引擎层空仓¥0</b>(零结构edge)。以下为评判员判读层,与引擎注金分开记账。整票历史0/94→小额娱乐,空仓亦合法。<b>主线=双峰:实力悬殊+真精英→押打穿/大球;势均或假热门→逆覆盖。</b>",SMALL),bg=ROSE,edge=RED)]
flow+=[Spacer(1,4)]

flow+=[band("四场判断总表",NAVY),Spacer(1,3)]
flow+=[grid([
  ["场次(北京)","判/比分","最优落点","信心"],
  ["041 阿根廷-奥地利 01:00","阿小胜 2-1","总进球2-3/2-1(奥进球);让球pass","★★★"],
  ["042 法国-伊拉克 05:00","法打穿 3-1","★总进球大(3-5球)","★★★★"],
  ["043 挪威-塞内加尔 08:00","平/微挪 1-1","★总进球2-3/双方都进","★★★"],
  ["044 约旦-阿尔 11:00","阿小胜 0-1","◎受让平@3.35/受让胜@2.46","★★★"],
],[30*mm,20*mm,32*mm,14*mm],hc=NAVY)]
flow+=[Spacer(1,4)]

# 逐场五市场
def matchcard(title,color,rows,note):
    out=[band(title,color),Spacer(1,2)]
    out+=[grid([["玩法","判断"]]+rows,[22*mm,74*mm],hc=color)]
    out+=[P(note,s('n',7.1,GREY,lead=10,sp=3))]
    out+=[Spacer(1,4)]
    return out

flow+=matchcard("041 阿根廷 vs 奥地利 (低信心场)",GREY,[
  ["胜平负","阿根廷胜—无价值;押平/奥=死亡陷阱"],
  ["让球-1","三方硬币(让胜40/平26/负34)→PASS"],
  ["半全场","胜胜@2.02不稳(奥早段高压可半场领先)→避"],
  ["比分","2-1(奥进球)>2-0,彩票"],
  ["总进球","2-3球(双方都进),模态"],
],"球理:奥地利高空/定位球(卡拉季奇首发,2022荷兰魏霍斯特绝平先例)撞阿根廷矮中卫+伤边卫→奥会进;梅西39岁被高压压制难复刻帽子戏法→阿磨小胜。边际:阿1.80/奥0.84。")

flow+=matchcard("042 法国 vs 伊拉克 (打穿场·最高信心)",GREEN,[
  ["胜平负","不卖(法国大热)"],
  ["让球-3","边界(让负45/让胜35),margin依赖→不主推"],
  ["半全场","胜胜@1.23避开(法MD1半场0-0)"],
  ["比分","市场3-0/2-0/4-0;我偏3-1/4-1(伊会进,少数派)"],
  ["总进球","★大球72%—全场最高信心(3-5球)"],
],"球理:八队最大实力差+本届打穿气氛(场均3.12/46%净胜≥3)。边际:法2.8+(52%进3+)/伊0.46(53%零封)。让球-3硬币不碰,总进球大才是铁信号。")

flow+=matchcard("043 挪威 vs 塞内加尔 (难啃骨头·硬币略偏挪)",BLUE,[
  ["胜平负","硬币,轻偏挪威(哈兰德王牌)"],
  ["让球-1","让负已撤(哈兰德威胁)、让胜净2+仅24%→PASS"],
  ["半全场","平平/客客,彩票"],
  ["比分","1-1模态/2-1(哈兰德)"],
  ["总进球","★2-3/双方都进(BTTS60%)—对胜负方免疫"],
],"球理:塞内加尔#15>挪威#31、控场掐哈兰德供给=难啃;但哈兰德对位顺(帽过尼亚卡特、库利巴利35岁大伤后第2场生疏)+塞压上送空间。能赢不能打穿(净2+仅24%)。边际:挪1.56/塞1.18,都1-2。")

flow+=matchcard("044 约旦 vs 阿尔及利亚 (fade假热门打穿)",GOLD,[
  ["胜平负","阿尔胜—无价值;押约/平=死亡陷阱"],
  ["让球阿尔-1","◎fade打穿→受让平(阿净1)@3.35/受让胜(约不败)@2.46"],
  ["半全场","平客@3.85(晚破)>客客@2.05"],
  ["比分","0-1模态/1-1(约守住);fade被高估0-2/0-3"],
  ["总进球","偏小/2球"],
],"球理:盘口给零创造的阿尔及利亚(MD1进0球)按阿根廷级打穿定价(受让负被加注2.42→2.36),逆它。约旦综合反超(5.23>4.98)、对奥地利不怵。边际:阿尔1.78/约0.81(42%零封)。")

flow+=[band("信心最高的决策(排序)",GOLD),Spacer(1,3)]
flow+=[grid([
  ["#","决策","依据"],
  ["①","42 总进球大(3-5球)","fair72%,最高;体彩band需国际O/U表达"],
  ["②","43 总进球2-3/双方都进","BTTS60%,对胜负方免疫,最稳健"],
  ["③","44 受让平@3.35/受让胜@2.46","fade假热门打穿,clean让球单关"],
  ["④","41 总进球2-3/2-1","让球pass,低信心场"],
],[8*mm,40*mm,48*mm],hc=GOLD)]
flow+=[Spacer(1,3)]
flow+=[box(P("<b>评判员单关¥15</b> = 044 受让平@3.35(阿尔净胜恰1球,逆被高估的打穿)。<b>纪律</b>:让球(历史最准16%)/总进球为主,比分半全场只当彩票;整票0/94→小额、别堆冷腿、空仓合法。冠军pick=阿根廷。⚠️开球前复核首发(阿根廷轮换/边卫伤、塞内加尔库利巴利体能、阿尔Mahrez+Amoura)。",SMALL))]

# 附栏:043/044 投注偏好 + 组合账
flow+=[Spacer(1,5)]
flow+=[band("附栏 · 043/044 投注偏好 + 组合账",BLUE),Spacer(1,3)]
flow+=[grid([
  ["选项","赔率","命中","EV"],
  ["043双方都进(国际盘,估)","~1.55","60%","−7% ←最优单"],
  ["044约旦不败(让球胜)@2.46","2.46","36%","−11%"],
  ["★2串1 043都进×044约旦不败","3.81","21.5%","−18%"],
  ["2串1 043挪威胜×044约旦不败","4.70","16%","−23%"],
  ["3串1 +042总进球大","5.07","15.5%","−21%"],
  ["✗总进球窄band凑串","8.7+","6-8%","−29%"],
],[40*mm,14*mm,13*mm,29*mm],hc=BLUE)]
flow+=[P("<b>核心</b>:单关 >> 串——每加一腿多叠一层抽水、命中暴跌。<b>宁可把'043双方都进+044约旦不败'当两张独立单关打,也别串成一张</b>(同样两判断,串起来EV从−7%/−11%翻倍成−18%、命中砍到21%)。想串图乐趣就一张 <b>043都进×044约旦不败@3.81x、≤¥5</b>;<b>千万别用总进球窄band凑串(−29%)</b>。'双方都进'体彩不卖须走国际盘;只玩体彩则取单关 <b>044约旦不败@2.46</b>。",SMALL)]
flow+=[P("043偏好:双方都进/总进球2-3(主,对胜负方免疫)+挪威胜小额(次)+让球pass | 044偏好:约旦不败@2.46或让球平@3.35(fade打穿),避阿尔净胜2+@2.36",s('ap',7.0,GREY,lead=9.8,sp=2))]

out=Path(".nutmeg-data/jczq/daily/2026-06-22/wc-md2-FINAL-20260622.pdf")
SimpleDocTemplate(str(out),pagesize=(112*mm,360*mm),leftMargin=8*mm,rightMargin=8*mm,topMargin=8*mm,bottomMargin=7*mm,
    title="WC2026 6/22 MD2 终版判断").build(flow)
print(f"PDF written: {out} ({out.stat().st_size} bytes)")

load_dotenv()
token=os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN")
ids=[int(x) for x in os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS","").split(",") if x.strip()]
if not token or not ids:
    print("⚠️ Telegram env 未配置,仅生成PDF未推送"); raise SystemExit
from nutmeg.interfaces.bot.telegram import TelegramBotClient
client=TelegramBotClient(token=token)
cap=("🏆 世界杯四场 MD2 · 终版判断(多轮深挖收敛)+ 043/044投注组合附栏\n"
     "引擎空仓¥0。主线=双峰:悬殊场押打穿/大球、势均/假热门逆覆盖。\n"
     "①42总进球大(3-5球)fair72%最高信心 ②43总进球2-3/都进球(难啃骨头) ③44受让平@3.35(fade阿尔打穿) ④41总进球2-3(让球pass)\n"
     "附栏:单关>>串;想串=043都进×044约旦不败@3.81x≤¥5。整票0/94,小额娱乐,空仓亦合法。")
for cid in ids:
    client.send_document(chat_id=cid,document_path=out,caption=cap); print(f"sent to {cid}")
print("DONE")
