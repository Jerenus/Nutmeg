"""手机友好评判员深研 PDF — 2026-07-04 全 11 场（世界杯 R16 两场 + 韩职三场 + 芬瑞六场）。
112mm 窄竖版。内容=主循环七阶段深研（DC 锚市场 scripts/jczq_20260704_dcfit.py + 11 个
jczq-match-analyst 并行 web 深研 + API-Football 深采 apifootball-deep.json）。
判读层¥40意见票（wc_jczq_20260704_combos.py 程序算）；引擎 A¥35/E¥10 建议整张不买。"""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

CJK=["/System/Library/Fonts/Supplemental/Songti.ttc","/System/Library/Fonts/STHeiti Light.ttc","/System/Library/Fonts/PingFang.ttc"]
for p in CJK:
    try: pdfmetrics.registerFont(TTFont("NutmegCJK",p,subfontIndex=0)); break
    except Exception: continue

def st(n,s,l,c="#111111",sp=2): return ParagraphStyle(n,fontName="NutmegCJK",fontSize=s,leading=l,textColor=colors.HexColor(c),spaceAfter=sp,alignment=TA_LEFT)
H1=st("H1",15,19,"#0b3d2e",3); H2=st("H2",11.5,15,"#0b3d2e",2)
BODY=st("BODY",8.6,12.2,"#1a1a1a",2); SMALL=st("SMALL",7.5,10.6,"#444444",1)
WHITE=st("WHITE",9,12,"#ffffff",0); ABIL=st("ABIL",8.2,11.2,"#0b3d2e",1)
WILL=st("WILL",8.2,11.2,"#7a0000",1); PLAY=st("PLAY",8.2,11.2,"#0a4a6e",1)

story=[]
story.append(Paragraph("竞彩全场深研 · 评判员判读",H1))
story.append(Paragraph("2026-07-04 · 世界杯R16两场(北京7-05凌晨01:00/05:00) + 韩职18:30 + 芬瑞20:00-23:00 · 11场",SMALL))
story.append(Paragraph("引擎A¥35(207 SJK胜1.61×209瓦萨让胜1.71@2.75,DC整票27.2%)与E¥10(5串1@3124,DC 0.02%)——A两腿深研均判偏贵、E五腿全踩各场最低概率档,<b>两张均建议整张不买</b>。本页意见票与引擎注金永不合账。",SMALL))
story.append(Spacer(1,3))

card=[[Paragraph("判读层意见票 · 总注 ¥40（娱乐预算 · 期望-3.9元程序算）",WHITE)],
 [Paragraph("① ¥15 评判员单关：<b>090 法国让+2「让平」@3.50</b>（判读0-2本体：满血法国 vs 巴拉圭铁桶,费城露天104°F压右尾→可控2球不是3-0血洗;当日最高信心4）",BODY)],
 [Paragraph("② ¥10：<b>089 加拿大让+1「让胜」@2.08</b>（判读1-1本体+覆盖爆冷：摩洛哥120分钟+点球旧腿+无正印9号,加拿大更鲜;DC 48.6%+疲劳上修≈51%,全日最接近公平价的一格）",BODY)],
 [Paragraph("③ ¥5：<b>201 安养让+1「让平」@3.75</b>（浦项恰净胜1=天克模板：近4交手3胜0平+李镐宰单核1-0+梅雨小球）",BODY)],
 [Paragraph("④ ¥10 2串1@2.38：<b>205 哈尔姆+1让胜@1.49 × 206 代格福什+1让胜@1.60</b>（北欧主队不败锚：死斗主场/换帅真空客队,两条客胜钱流均判过度反应;联合命中≈35%）",BODY)],
 [Paragraph("空仓场次：202(复赛首轮不确定)/203(全北Tiago伤缺=信息驱动重定价,硬币)/204(钱流vs基本面相反但主队攻哑)/207/208(跨源分歧:分析员小球vsAPI大球)/209(全部格子被压水)。<b>空仓永远合法。</b>",SMALL)]]
ct=Table(card,colWidths=[100*mm])
ct.setStyle(TableStyle([("BACKGROUND",(0,0),(0,0),colors.HexColor("#0b3d2e")),
 ("BACKGROUND",(0,1),(0,-1),colors.HexColor("#f4faf7")),("BOX",(0,0),(-1,-1),0.6,colors.HexColor("#0b3d2e")),
 ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),("LEFTPADDING",(0,0),(-1,-1),5)]))
story.append(ct); story.append(Spacer(1,4))

story.append(Paragraph("重点五场深研（实力 × 状态/战意 × 玩法）",H2))
DEEP=[
("089 加拿大 vs 摩洛哥","平 1-1 信心3","#b58100",
 "R16(双方均已过R32:加拿大1-0南非,摩洛哥点球淘汰荷兰)。fair摩胜51.4%只是软热。摩2022四强中轴剩9人(Bounou/Hakimi/Mazraoui)但大名单无正印9号;加拿大把握差(今夏错失11次重大机会),戴维斯大概率不首发。",
 "状态天平明显偏加拿大:多休一天+只踢90分钟 vs 摩洛哥120分钟+点球;NRG关棚恒温22°C抹掉高温牌;休斯顿≠加拿大主场,现场氛围反偏摩洛哥。战意双满,双低位转换型都不想先亮牌。",
 "DC模态1:1=13.2%>0:1=12.9%,平局带28.2%全日最厚,≤2球57%。意见票=让胜2.08(加不败48.6%,唯一近公平格);让平2.94(摩恰胜1)DC仅24.3%被压到34%→不追;加胜5.00=0/23死亡档;大3球=模态隔壁。"),
("090 巴拉圭 vs 法国","客胜 0-2 信心4","#06a",
 "法国4战全胜13球,唯一满血豪门(Mbappé本届6球);巴拉圭D组第3+点球掀翻德国,Gill+G.Gómez后五真铁桶(~300分钟丢1球),但Alderete膝伤缺=铁桶唯一裂口,Enciso存疑。",
 "费城露天104°F极端高温=主导变量:压制法国高压节奏、帮铁桶存活;巴拉圭多背30分钟+点球消耗→末段腿崩。战意双满无轮换。两条状态线收敛到『晚破』:上半场闷、下半场连破。",
 "DC净胜档:恰1=22.6%/恰2=23.0%/≥3=34.0%——无干净模态,体彩不开had是对的。判读0-2→让平3.50=比分本体;fade让负2.30(3+共识=高温盲区拥挤side);hafu平/客3.90同剧本备选;ttg 3球3.25比真模态高1球。"),
("201 安养 vs 浦项","客小胜 0-1 信心3","#06a",
 "安养15轮8平=全联赛平局机器,丢Motta后靠定位球;浦项防守+李镐宰单核(7球占全队近6成),赢球全是1-0/2-0模板。浦项=安养天克:2025年3战全胜进5失1,近4交手3胜0平。本季安养进球(19)反多于浦项(12)。",
 "梅雨:今晚安养大概率有雨→湿滑压节奏利定位球;浦项7月无亚冠分心;双方都争上组(前6),战意均衡;安养复仇心vs浦项心理压制,互相抵消。",
 "大小线开2球全日最低,DC:0-2球65.6%。意见票=让平3.75(浦项恰胜1,DC 21.8%+天克上修);稳腿备选安养+1让胜1.42(63%);E票201让负6.30(浦项净胜≥2,DC 14.9%)=全日最低概率档陷阱;ttg 1球3.70与2球3.05近并列,单押2球会被1-0劈死。"),
("202 大田 vs 富川","主小胜 1-0 信心2","#0a6",
 "叙事纠正:不是强弱局——第9(富川17分)vs第10(大田16分)只差1分的六分战,K1停摆7周后复赛首轮。大田停摆前4轮不胜、近4场只进1球(xGA 23.6);富川升班马3-4-3铁桶专治强队(0-0全北/2-0浦项/首回合1-1大田)。",
 "复赛首战双方生涩、进球预期再下修;富川围城心态铁桶更硬;大田主场+舆论压力但『必须回应』常把进攻越踢越紧。API-Football反向信号:form 36/64、def 25/75竟偏富川。",
 "DC模态1:0=14.5%>1:1=12.4%。体彩1.62大热被三源(深研/API/停摆前状态)共同降温→不上钱。若表达:让负2.02(大田不胜47.2%)>让平3.10(恰胜1,25.6%)>让胜3.22(净2+,27.3%但攻哑=陷阱);ttg 1-2球带。"),
("203 全北 vs 江原","主小胜/平 1-0或1-1 信心2","#b58100",
 "第3(26分)vs第4(24分)顶区对话。全北主场全联盟第1+近6轮不败,但头号射手Tiago确认伤缺,7/2刚租借196cm立陶宛前锋Paulauskas(零磨合);江原零封全联盟最多(8场),金大元当红(5球3助轮次MVP)。H2H近6场半数平,首回合1-1。",
 "欧赔向江原倾斜(主2.21→2.30/客3.24→3.16)=信息驱动(Tiago伤)非情绪,合理重定价;战意对称双高;新帅郑正溶+阵容重建期撞上联盟最强防线。",
 "over2.0 fair仅49.8%全日最低档;DC模态1:1=13.9%≈1:0=13.2%。胜负被伤讯拉成硬币→按纪律改赌总进球:1-2球带(2球3.10模态,1球3.80被低估邻档);方向性高赔=让平3.85(全北恰胜1=晚段绝杀模式);E票203让胜5.30(净2+,DC 17.4%)=最低概率档,别为大数字上头。"),
]
for title,verdict,color,abil,will,play in DEEP:
    story.append(Paragraph(f"<b>{title}</b>　{verdict}",ParagraphStyle("h",parent=BODY,textColor=colors.HexColor(color),fontSize=9.5,leading=12.5,spaceAfter=1)))
    story.append(Paragraph("【实力】"+abil,ABIL))
    story.append(Paragraph("【状态/战意】"+will,WILL))
    story.append(Paragraph("【玩法/DC】"+play,PLAY))
    story.append(Spacer(1,4))

story.append(Paragraph("芬瑞六场速判",H2))
rows=[["场","判读","要点/最优玩法"],
 ["204","主不败偏平 1-1","钱流追Gnistan热手=情绪(拉赫蒂反回血2停赛主力);但主队近9轮1胜攻哑→不上钱;若表达=让平3.75(恰胜1)"],
 ["205","平/主 1-1","降级区死斗主场vs升班马,两条最漏防线互喂;意见票④腿=+1让胜1.49;客胜2.36被钱流压短=过度反应"],
 ["206","平/客小胜 1-1","马尔默临时教练带队+核心三缺,H2H 9-2-0是唯一托底;意见票④腿=+1让胜1.60;让负4.20(净2+)=陷阱"],
 ["207","主小胜/平 1-0","SJK第10主场1胜,热门靠TPS射手Tsirigotis伤缺撑;A票胜1.61偏短;真模态=让负2.04(SJK不胜44.7%)"],
 ["208","低分 1-1/0-1","雅罗保级围城+Ilves无欲无求330km客场;分析员判2球模态vs API-Football判大球→跨源分歧=不上钱"],
 ["209","主小胜 2-0/1-0","玛丽港0胜垫底但历史对瓦萨专摆铁桶(近三客0-0/5-1/0-0);A票让胜1.71要58.5%命中vs拟合46-51%=偏贵"]]
t=Table(rows,colWidths=[9*mm,25*mm,66*mm])
t.setStyle(TableStyle([("FONTNAME",(0,0),(-1,-1),"NutmegCJK"),("FONTSIZE",(0,0),(-1,-1),7.2),
 ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0b3d2e")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
 ("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#cccccc")),("VALIGN",(0,0),(-1,-1),"TOP"),
 ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2)]))
story.append(t); story.append(Spacer(1,4))

story.append(Paragraph("纪律 & 冠军",H2))
story.append(Paragraph("数据纪律:体彩全池=WAF绕过实采(浏览器UA);国际=API-Football 29家去水fair+predictions/injuries深采;概率=Dixon-Coles拟合(scripts/jczq_20260704_dcfit.py,loss≈0)+11场并行web深研;组合算术scripts/wc_jczq_20260704_combos.py,禁嘴算。教训过滤:让球平>比分>胜平负冷门;0/38高赔串禁形态;分歧场(208)不上钱;比分只作彩票。",SMALL))
story.append(Paragraph("冠军pick(维持)：Spain — 4场0失球+3-0碾奥地利未被新证据推翻;蒙卡阿根廷20.9%vs西20.6%并列=模拟噪音,不构成球面换pick理由。",SMALL))

out=Path(".nutmeg-data/jczq/daily/2026-07-04/wc-judge-deepdive.pdf")
SimpleDocTemplate(str(out),pagesize=(112*mm,290*mm),topMargin=6*mm,bottomMargin=6*mm,leftMargin=6*mm,rightMargin=6*mm,title="WC+竞彩 7/4 评判员深研").build(story)
print(f"PDF: {out} ({out.stat().st_size}B)")

load_dotenv()
token=os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN");ids=[int(x) for x in os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS","").split(",") if x.strip()]
if token and ids:
    from nutmeg.interfaces.bot.telegram import TelegramBotClient
    c=TelegramBotClient(token=token)
    cap=("🏆 7/4 全11场深研判读（WC R16×2+韩职×3+芬瑞×6）\n"
         "意见票¥40：①090法国让平@3.50×15（0-2可控胜,高温压右尾） ②089加拿大+1让胜@2.08×10（摩洛哥120min旧腿,判读1-1） "
         "③201安养让平@3.75×5（浦项天克1-0） ④205×206主队+1让胜2串1@2.38×10（北欧不败锚）\n"
         "引擎A¥35(DC 27.2%)与E¥10(DC 0.02%)两张均建议整张不买——A两腿偏贵、E五腿全踩最低概率档。\n"
         "冠军pick维持Spain。空仓合法,小额娱乐。")
    for cid in ids: c.send_document(chat_id=cid,document_path=out,caption=cap);print(f"sent {cid}")
    print("DONE")
else: print("⚠️无TG凭据")
