#!/usr/bin/env python3
"""2026-06-24 周三049-054 重做版(Dixon-Coles比分矩阵+6场深研+动机主轴)。手机PDF+bot推送。"""
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
H1=s("H1",13,NAVY,lead=16,sp=2,al=1);SUB=s("SUB",7.6,GREY,lead=10.4,sp=4,al=1);HEAD=s("HEAD",10,colors.white,lead=12.5)
SMALL=s("SMALL",7.0,GREY,lead=10.0,sp=2);THEAD=s("TH",6.8,colors.white,lead=9.3);TCELL=s("TC",6.7,colors.black,lead=9.1);TCB=s("TCB",6.7,NAVY,lead=9.1)
def P(t,st=SMALL): return Paragraph(t,st)
def band(t,c=BLUE): return Table([[Paragraph(t,HEAD)]],colWidths=[96*mm],style=TableStyle([("BACKGROUND",(0,0),(-1,-1),c),("LEFTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
def box(p,bg=WARM,edge=GOLD): return Table([[p]],colWidths=[96*mm],style=TableStyle([("BACKGROUND",(0,0),(-1,-1),bg),("BOX",(0,0),(-1,-1),0.5,edge),("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
def grid(rows,widths,hc=NAVY):
    data=[[P(c,THEAD if i==0 else (TCB if j==0 else TCELL)) for j,c in enumerate(r)] for i,r in enumerate(rows)]
    t=Table(data,colWidths=widths);t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),hc),("FONTNAME",(0,0),(-1,-1),"CJK"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,LITE]),("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#c8d2de")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),2.5),("RIGHTPADDING",(0,0),(-1,-1),2.5),("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2)]));return t
flow=[]
flow+=[P("世界杯周三 049-054 · 重做版",H1),P("北京6/25开球 · MD3收官轮 · Dixon-Coles比分矩阵 + 6场实时深研 · 主轴=动机/战意",SUB)]
flow+=[box(P("<b>今日主轴=热门'想不想赢'差别极大(收官轮,同组两场同时踢)。</b>★硬发现:比分矩阵显示<b>今天没有一场是干净的'热门让平'模态</b>——热门要么净胜2+(波黑/摩洛哥/巴西)、要么掷硬币(南非/瑞士)→<b>高赔组合没有模态锚,克制。</b>054墨西哥头名已锁·躺平轮换=<b>无动机短赔热门→fade(捷克+1/平),今日最高信心</b>。049双双出线但加拿大为断腿队友+队史淘汰赛主场死拼=<b>战意逆势,非君子局</b>。",SMALL),bg=ROSE,edge=RED)]
flow+=[Spacer(1,4),band("Dixon-Coles比分矩阵(拟合国际去水fair,禁嘴算)",NAVY),Spacer(1,3)]
flow+=[grid([
 ["场(主-客)","λ主","λ客","模态比分","净胜/让球结构","大小2.5"],
 ["049瑞-加","1.41","1.14","1-1(15%)","平30·瑞净2+ 21·加+1=59","小53%"],
 ["050波-卡","2.23","0.90","2-0/2-1","波净2+ 44·平20","大60%"],
 ["051苏-巴","0.68","2.03","0-2/0-1","巴净2+ 44·净1=25","51%硬币"],
 ["052摩-海","2.56","0.58","2-0/3-0","摩净3+ 36·海+2=41","大61%"],
 ["053南-韩","0.86","1.67","0-1/1-1","韩净2+ 31·南+1=44","小53%"],
 ["054捷-墨","1.13","1.65","1-1(12%)","墨净2+ 26·捷+1=51","小(借2.25)"],
],[15*mm,9*mm,9*mm,16*mm,30*mm,15*mm])]
flow+=[Spacer(1,4),band("建议比分 + 最优玩法 + 信心",GOLD),Spacer(1,3)]
flow+=[grid([
 ["场","建议比分","最优玩法(状态≠战意)","信心"],
 ["049瑞-加","1-1、1-0","加拿大+1@1.49/小2.5;避瑞士让胜","★★"],
 ["050波-卡","2-1、2-0","◎大球2.5(60%);波黑胜;比分2-1","★★★"],
 ["051苏-巴","0-2、0-1","巴西胜方向;让球分叉(苏压上→巴-1)","★★★"],
 ["052摩-海","2-0、3-0","摩洛哥胜;受让海地+2>让-2;比分2-0","★★★"],
 ["053南-韩","0-1、1-1","南非+1@2.22(44%)/小2.5;避韩-1.5","★★★"],
 ["054捷-墨","1-1、0-1","◎捷克+1@1.74/平@3.36;避墨胜","★★★★"],
],[14*mm,18*mm,50*mm,12*mm],hc=GOLD)]
flow+=[Spacer(1,3),box(P("<b>★评判员单关¥15 = 054 捷克+1 受让 @1.74</b>:墨西哥头名+晋级100%锁定、Aguirre称头名'无所谓'、measured轮换、零必胜压力;捷克为出线死拼+铁桶定位球。捷克+1覆盖'墨西哥不胜'全区(含1-1模态)≈51%,让球受让=实证最准玩法,fade无动机短赔热门=今日主轴。低赔低方差。<br/><b>⛔引擎A(巴西-1×墨胜)不建议买</b>:巴西-1是苏格兰压上/铁桶分叉、墨胜是无动机陷阱。<b>⛔引擎B(73.87x)不买</b>:含南非主胜@5.40胜平负冷门=0/23死亡档+3冷腿堆=0/38整票教训。<br/><b>纪律:整票0/20·hhad6%·crs0%(本窗口)。比分当彩票小额、空仓对引擎票=推荐。</b>",SMALL))]
out=Path(".nutmeg-data/jczq/daily/2026-06-24/wc-md3-FINAL-20260624.pdf")
SimpleDocTemplate(str(out),pagesize=(112*mm,272*mm),leftMargin=8*mm,rightMargin=8*mm,topMargin=8*mm,bottomMargin=7*mm,title="WC 6/24 049-054 重做版").build(flow)
print(f"PDF: {out} ({out.stat().st_size}B)")
load_dotenv();token=os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN");ids=[int(x) for x in os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS","").split(",") if x.strip()]
if token and ids:
    from nutmeg.interfaces.bot.telegram import TelegramBotClient
    c=TelegramBotClient(token=token)
    cap=("🏆 世界杯周三049-054 重做版(Dixon-Coles矩阵+6场深研)\n主轴=动机:fade无动机短赔热门(墨西哥头名已锁躺平)。\n★硬发现:今天无干净'热门让平'模态→高赔组合没锚,克制。\n★评判员单关=054 捷克+1受让@1.74(墨不胜≈51%)\n建议比分:049=1-1 050=2-1 051=0-2/0-1 052=2-0/3-0 053=0-1(韩) 054=1-1\n⛔引擎A/B均不建议买(A两腿陷阱/分叉,B含南非主胜冷门=0/23死亡档)。整票0/58全输,小额,空仓合法。")
    for cid in ids: c.send_document(chat_id=cid,document_path=out,caption=cap);print(f"sent {cid}")
    print("DONE")
else: print("⚠️无TG凭据")
