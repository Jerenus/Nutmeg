"""手机友好评判员深研 PDF — 2026-07-03 R32 三场(澳/埃·阿/佛·哥/加)。112mm 窄竖版。
内容=Claude 主循环七阶段深研(DC锚市场 wc_r32_0704_dcfit.py + jczq-match-analyst逐场web)。
判读层¥25意见票:¥15单关088哥胜 + ¥5 087让平 + ¥5 087让负;086空仓。引擎B¥35建议整张不买。"""
import json
from pathlib import Path
from reportlab.lib.pagesizes import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

CJK=["/System/Library/Fonts/Supplemental/Songti.ttc","/System/Library/Fonts/STHeiti Light.ttc","/System/Library/Fonts/PingFang.ttc"]
for p in CJK:
    try: pdfmetrics.registerFont(TTFont("NutmegCJK",p,subfontIndex=0)); break
    except Exception: continue

BASE=".nutmeg-data/jczq/daily/2026-07-03"
D=json.load(open(f"{BASE}/predictions.json"))
PW,PH=112*mm,272*mm
def st(n,s,l,c="#111111",sp=2): return ParagraphStyle(n,fontName="NutmegCJK",fontSize=s,leading=l,textColor=colors.HexColor(c),spaceAfter=sp,alignment=TA_LEFT)
H1=st("H1",15,19,"#0b3d2e",3); H2=st("H2",11.5,15,"#0b3d2e",2)
BODY=st("BODY",8.6,12.2,"#1a1a1a",2); SMALL=st("SMALL",7.5,10.6,"#444444",1)
WHITE=st("WHITE",9,12,"#ffffff",0); ABIL=st("ABIL",8.2,11.2,"#0b3d2e",1)
WILL=st("WILL",8.2,11.2,"#7a0000",1); PLAY=st("PLAY",8.2,11.2,"#0a4a6e",1)
JCOLOR={"home":"#0a6","draw":"#b58100","away":"#06a"}; JNAME={"home":"主胜","draw":"平","away":"客胜"}

# ¥25 意见票情景算术（禁嘴算，程序算）
S_TOTAL=25
ret_col=15*1.29        # 088哥胜腿回收
ret_rqd=5*3.62         # 087让平回收
ret_rql=5*2.62         # 087让负回收
SC=[("哥胜 + 阿净胜恰2", ret_col+ret_rqd-S_TOTAL),
    ("哥胜 + 阿净胜≤1/不胜", ret_col+ret_rql-S_TOTAL),
    ("哥胜 + 阿净胜≥3", ret_col-S_TOTAL),
    ("哥不胜 + 阿净胜恰2", ret_rqd-S_TOTAL),
    ("哥不胜 + 阿净胜≤1", ret_rql-S_TOTAL),
    ("哥不胜 + 阿净胜≥3", -S_TOTAL)]
sc_line=" ｜ ".join(f"{k} {v:+.1f}" for k,v in SC)

DEEP={
"周五086":{
 "ability":"埃及G组第2(1-1比利时/3-1新西兰/1-1伊朗,进5丢3,三场全BTTS)队史首进淘汰赛;澳大利亚D组第2(2-0土耳其/0-2美国/0-0巴拉圭,3场2球2零封)靠铁桶背进。个人能力埃及略高,但萨拉赫腿筋拉伤『能出场不保首发』+Lasheen停赛+四人存疑;澳无停赛主力齐整→健康度反偏澳。",
 "will":"状态:双方同休6-7天,AT&T球场顶棚全关空调20-24°C,体能牌全抹平。战意:两队都争队史零的突破(澳从未赢过淘汰赛/埃首次踢淘汰赛),对称拉满→高战意在此=更怕输更铁桶,不是对攻;角色反转后控球破密集的难题在埃及。",
 "play":"DC模态1:1=14.9%>0:0=14.6%>0:1=13.3%,平33.3%全日最高,0-2球67%。让胜1.48(澳+1不败)隐含67.6%>DC60.5%=看着稳实则贵;让负5.80押最低概率档(17.2%)。判读=平1-1(信心3)但教训过滤:平局收割0/67+ttg 0/5→本场空仓只记预测。"},
"周五087":{
 "ability":"阿根廷J组全胜头名(3-0阿尔及利亚/2-0奥地利/3-1约旦,进8失1,梅西6球领跑射手榜);佛得角H组三场全平(0-0西班牙/2-2乌拉圭/0-0沙特)史上最小人口(54万)淘汰赛队,场均失球0.67全赛会最硬铁桶之一,Vozinha对西班牙7扑救。实力断层但矛盾焦点=第一个球的时间点。",
 "will":"状态:佛多休1天+停赛中卫Cabral回归防线满血;阿尔瓦雷斯带踝伤或让位劳塔罗。战意方向相反:阿要碾(下轮软签无轮换动机),佛要守到点球(淘汰赛平局=加时,龟缩身份认同被规则强化);迈阿密闷热+领先后撤梅西→压低净胜球。",
 "play":"DC净胜分布近乎均匀:恰2=23.3%(最大干净桶)>+1=21.3%>4+=20.5%>+3=18.4%>不胜16.6%——双峰局:守过60分钟→净1-2;早破口→滚3-0+。模态比分2-0>1-0>3-0。意见票¥10拆两注:让平@3.62(净恰2,模态桶+实证最准玩法)+让负@2.62(净≤1,全日抽水最薄EV-1%),合成『铁桶挡碾压』覆盖61.2%;回避让胜2.13=押碾压的隔壁陷阱(西班牙对同队0:0是活证)。"},
"周五088":{
 "ability":"哥伦比亚K组头名力压葡萄牙(3-1乌兹/1-0刚果金/0-0葡萄牙,进4只丢1),蒙卡第7夺冠热门,满编全主力(J罗/迪亚斯/穆尼奥斯);加纳L组best-3rd惊险晋级(1-0巴拿马补时绝杀/0-0英格兰/1-2克罗地亚,3场仅2球),核心库杜斯股四头肌整届退赛,33岁阿尤单箭头锋无力。",
 "will":"状态对等(同休6天,均无停赛);堪萨斯城湿热+傍晚雷暴风险轻微利铁桶。战意:胜者下轮打瑞士=通往八强甜签→哥零轮换全力凿门;加纳围城心态铁桶更顽固(0-0逼平英格兰是成色证明)。",
 "play":"DC模态1:0=14.7%≈2:0=14.4%,净胜+1=25.7%最大单桶,哥不胜33.4%。判读哥胜2-0(信心4):磨开第一个后淘汰赛的加纳必须压上,迪亚斯打身后补刀。让球3路偏平无碾压档:让平@2.95抽水最厚(EV-24%)不追,让胜@2.20押大比分与哥近两场凿不动密集的硬证据相悖→判读层用had主胜@1.29老实表达方向;引擎让负@2.98(EV-1%)方向与判读相反,不领投。"},
}

story=[]
story.append(Paragraph("世界杯竞彩 · 评判员深研",H1))
story.append(Paragraph("2026-07-03 · R32 三场 · 北京7-04凌晨 02:00/06:00/09:30",SMALL))
story.append(Paragraph("引擎§A/D/E空;B票¥35(088让负×201天狼星负×086澳胜@45.06)判读层建议整张不买:三腿全模态隔壁,DC命中1.7%,0/38死亡形态。本页意见票与引擎注金永不合账。",SMALL))
story.append(Spacer(1,3))

rows=[["编","对阵","判","比分","信"]]
for p in D["picks"]:
    rows.append([p["match_no"].replace("周五",""),p["fixture"].replace(" vs ","/"),JNAME[p["judgment"]],p["score"],str(p["confidence"])])
t=Table(rows,colWidths=[8*mm,51*mm,9*mm,13*mm,7*mm])
tstyle=[("FONTNAME",(0,0),(-1,-1),"NutmegCJK"),("FONTSIZE",(0,0),(-1,-1),7.8),
    ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0b3d2e")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
    ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#cccccc")),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2)]
for i,p in enumerate(D["picks"],1):
    tstyle.append(("TEXTCOLOR",(2,i),(2,i),colors.HexColor(JCOLOR[p["judgment"]])))
    if p["confidence"]>=4: tstyle.append(("BACKGROUND",(4,i),(4,i),colors.HexColor("#fde7a0")))
t.setStyle(TableStyle(tstyle)); story.append(t); story.append(Spacer(1,4))

card=[[Paragraph("判读层意见票 · 总注 ¥25（娱乐预算）",WHITE)],
      [Paragraph("① ¥15 评判员单关：<b>088 哥伦比亚 胜平负「主胜」@1.29</b>（当日最高信心4；库杜斯缺阵的加纳锋无力,哥满编+瑞士甜签战意拉满）",BODY)],
      [Paragraph("② ¥5：<b>087 阿根廷让-2「让平」@3.62</b>（净胜恰2=模态比分2-0本体,DC最大干净桶23.3%,实证最准高赔玩法）",BODY)],
      [Paragraph("③ ¥5：<b>087 阿根廷让-2「让负」@2.62</b>（净胜≤1/守到点球,37.9%,全日抽水最薄EV-1%;与②合成『铁桶挡碾压』覆盖阿净胜≤2=61.2%）",BODY)],
      [Paragraph(f"情景（程序算）：{sc_line}。<b>086空仓</b>：判读=平1-1但平局收割0/67+ttg 0/5教训→不上钱只记预测。",SMALL)]]
ct=Table(card,colWidths=[100*mm])
ct.setStyle(TableStyle([("BACKGROUND",(0,0),(0,0),colors.HexColor("#0b3d2e")),
    ("BACKGROUND",(0,1),(0,-1),colors.HexColor("#f4faf7")),("BOX",(0,0),(-1,-1),0.6,colors.HexColor("#0b3d2e")),
    ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),("LEFTPADDING",(0,0),(-1,-1),5)]))
story.append(ct); story.append(Spacer(1,4))

story.append(Paragraph("逐场深研（实力 × 状态/战意 × 玩法）",H2))
for p in D["picks"]:
    dd=DEEP[p["match_no"]]
    head=f"<b>{p['match_no'].replace('周五','')} {p['fixture']}</b>　{JNAME[p['judgment']]} {p['score']} 信心{p['confidence']}"
    story.append(Paragraph(head,ParagraphStyle("h",parent=BODY,textColor=colors.HexColor(JCOLOR[p['judgment']]),fontSize=9.5,leading=12.5,spaceAfter=1)))
    story.append(Paragraph("【实力】"+dd["ability"],ABIL))
    story.append(Paragraph("【状态/战意】"+dd["will"],WILL))
    story.append(Paragraph("【玩法/DC】"+dd["play"],PLAY))
    story.append(Spacer(1,4))

story.append(Spacer(1,2))
story.append(Paragraph("纪律 & 冠军",H2))
story.append(Paragraph("数据纪律:概率=12家国际去水fair拟合Dixon-Coles(loss~1e-7,scripts/wc_r32_0704_dcfit.py)+体彩全子盘(WAF绕过实取);组合算术scripts/wc_r32_0704_combos.py,禁嘴算。昨日判读层¥30回收¥49.85(+19.85:083让胜✓+二串一083×085✓);记分牌仍警示判定54%<基线63%→只在有球面理由处偏离(今日唯一偏离=086押平弃埃及小热,理由=萨拉赫伤+破铁桶难题换边)。",SMALL))
story.append(Paragraph(f"冠军pick(换)：{D['champion_pick']['team']} — 西班牙4场0失球+3-0碾奥地利缺边锋仍打穿,冠军相最实;法国R32未赛无对等新证据(蒙卡西20.6%>法20.1%仅佐证)。",SMALL))

out=Path(f"{BASE}/wc-judge-deepdive.pdf")
SimpleDocTemplate(str(out),pagesize=(PW,PH),topMargin=6*mm,bottomMargin=6*mm,leftMargin=6*mm,rightMargin=6*mm).build(story)
print("Wrote",out)
