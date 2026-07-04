"""胜负彩 26090 期 14 场深研判定 — 手机版 PDF (112mm) + Telegram 推送.

内容 = 主循环七阶段深研（14 场并行 jczq-match-analyst web 深研 + 29家去水 fair 底座
+ 选9丢5 任九构造，算术见 zucai_26090_sfc14_plan.py）。判断不烤进脚本，脚本只渲染+推送。
"""
from __future__ import annotations
import json
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

for p in ["/System/Library/Fonts/Supplemental/Songti.ttc", "/System/Library/Fonts/STHeiti Light.ttc", "/System/Library/Fonts/PingFang.ttc"]:
    try:
        pdfmetrics.registerFont(TTFont("NutmegCJK", p, subfontIndex=0)); break
    except Exception:
        continue

ROOT = Path(__file__).parents[1]
J = json.loads((ROOT / ".nutmeg-data/zucai/26090-judgment.json").read_text())
B = json.loads((ROOT / ".nutmeg-data/zucai/26090-base.json").read_text())

def st(n, s, l, c="#111111", sp=2):
    return ParagraphStyle(n, fontName="NutmegCJK", fontSize=s, leading=l, textColor=colors.HexColor(c), spaceAfter=sp, alignment=TA_LEFT)

H1 = st("H1", 15, 19, "#0b3d2e", 3); H2 = st("H2", 11.5, 15, "#0b3d2e", 2)
BODY = st("BODY", 8.4, 11.8, "#1a1a1a", 2); SMALL = st("SMALL", 7.4, 10.4, "#444444", 1)
WHITE = st("WHITE", 9, 12, "#ffffff", 0)
CELL = st("CELL", 7.0, 9.4, "#1a1a1a", 0)

story = []
story.append(Paragraph("胜负彩 26090 · 14场深研判定", H1))
story.append(Paragraph("世界杯R16×8 + 欧冠资格×1 + 瑞超×5 · 今晚首场开球前停售（以体彩为准） · 开奖跨 7/5-7/8", SMALL))
story.append(Paragraph("方法：14场每场一个分析员并行web深研（实力/状态/战意分开判）+ 29家去水fair底座 + 选9丢5构造；概率均程序算（zucai_26090_sfc14_plan.py），禁嘴算。", SMALL))
story.append(Spacer(1, 3))

story.append(Paragraph("逐场判定（3=主胜 1=平 0=客胜）", H2))
rows = [["#", "对阵", "fair 主/平/客", "判定", "信心", "核心依据"]]
for no in map(str, range(1, 15)):
    j = J["judgments"][no]
    m = B[no]
    f = m["fair"]
    fs = "{:.0%}/{:.0%}/{:.0%}".format(*f) if f else "无盘"
    rows.append([no, Paragraph(m["match"], CELL), fs, j["picks"], str(j["confidence"]), Paragraph(j["reason"], CELL)])
t = Table(rows, colWidths=[5*mm, 20*mm, 15*mm, 9*mm, 6*mm, 45*mm])
ts = [("FONTNAME", (0, 0), (-1, -1), "NutmegCJK"), ("FONTSIZE", (0, 0), (-1, -1), 7.0),
      ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b3d2e")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
      ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
      ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]
for i, no in enumerate(map(str, range(1, 15)), 1):
    conf = J["judgments"][no]["confidence"]
    if conf >= 4:
        ts.append(("BACKGROUND", (4, i), (4, i), colors.HexColor("#fde7a0")))
    if J["judgments"][no]["picks"] == "3/1/0":
        ts.append(("TEXTCOLOR", (3, i), (3, i), colors.HexColor("#b58100")))
t.setStyle(TableStyle(ts))
story.append(t)
story.append(Spacer(1, 4))

rj = J["renjiu"]
card = [[Paragraph("【终版】任九·选9丢5 · 96注 ¥192 · 九场联合命中≈9.1%（程序算）", WHITE)],
 [Paragraph("<b>保留9场</b>：1(1/0) · 2(0)胆 · 3(3/1) · 5(0/1) · 7(3)胆 · 9(3/1) · 11(3)胆 · 12(0/1) · <b>13(3/1/0全包)</b>", BODY)],
 [Paragraph("<b>丢弃5场（平局/硬币雷区）</b>：4 墨英(海拔硬币) · 6 美比(35/28/37硬币) · 8 瑞哥(判读=平 vs 市场热门=哥,方向冲突即丢) · 10 哥德堡AIK(主场0胜的假热门) · 14 赫根佐加(底座方向存疑,市场实favor佐加顿斯)", BODY)],
 [Paragraph("瑞超专项修订：13 从(0/1)升三全包——格局组判盖斯43%客胜有水分(它的强是主场限定:主场只失2球/客场1-1-3) vs 单场组判Hansen停赛压死BP主胜,两组方向分歧→按纪律用钱包保护(+¥64买断唯一分歧腿)。三胆：2法国(80%真胆) · 7阿根廷(70%,接受~20%拖平暴露) · 11卡尔马(62%,专项后信心升4:热身两场2-0+零流失 vs 底层倒数第1+客场3-16)。", SMALL)]]
ct = Table(card, colWidths=[100*mm])
ct.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#0b3d2e")),
 ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#f4faf7")), ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#0b3d2e")),
 ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LEFTPADDING", (0, 0), (-1, -1), 5)]))
story.append(ct)
story.append(Spacer(1, 4))

story.append(Paragraph("14场方案（彩票层，二选一）", H2))
s14 = J["single14"]
story.append(Paragraph("<b>A. ¥2 单式·评判员纯判读票</b>：" + "　".join(f"{n}:<b>{p}</b>" for n, p in s14.items()), BODY))
story.append(Paragraph("纯判读表达（含 1判平/4判墨西哥/8判平/10判AIK 四个反市场点），全中约十万分之0.26，一等奖叙事，别加倍。", SMALL))
fp = J.get("final_plans", {}).get("sfc14_optional", {})
if fp:
    story.append(Paragraph("<b>B. ¥128 优化复式（64注,联合≈0.10%）</b>：双选放覆盖增益最大的6场——4(0/1) 6(0/1) 8(0/1) 9(3/1) 13(0/1) 14(3/1)；单选 1(0) 2(0) 3(3) 5(0) 7(3) 10(3) 11(3) 12(0)。仍是彩票性质，预算充裕才上；两者不叠加。", BODY))
story.append(Spacer(1, 4))

story.append(Paragraph("五场硬币局为什么丢（深研结论速记）", H2))
for line in [
 "4 墨英：阿兹特克2240米海拔，图赫尔原话『四天不可能适应』；墨四战全胜零封+全国动力峰值 vs 英格兰天赋——环境把20pp天赋差抹平。",
 "6 美比：美国折停赛的头号射手Balogun，比利时刚踢满124分钟且DDB/卢卡库/多库全存疑——两坑相抵的诚实硬币。",
 "8 瑞哥：哥伦比亚统治但低效(20射1球+0-0葡萄牙)+跨大陆飞行少休一天 vs 瑞士原地温哥华多休一天——分析员判读倾向平，与市场热门方向冲突→按分歧纪律丢弃。",
 "10 哥德堡AIK：哥德堡本季主场0胜+全联盟最烂防线，42%热门是主场标签虚抬；AIK带7人伤停——双残硬币。",
 "14 赫根佐加：赫根门将+主力中卫双伤+近6次对佐加顿斯0胜+自身50%平局率——非主胜方向清楚，但平/客二选一仍是硬币，任九口径下丢弃。"]:
    story.append(Paragraph("· " + line, SMALL))
story.append(Spacer(1, 3))
story.append(Paragraph("纪律：胜负彩=90分钟口径；任九不追加注（加注只提命中率不提奖金）；−13%抽水娱乐预算小额；空仓永远合法。数据：体彩全池WAF绕过实采+API-Football 29家fair+500.com补底；场9无盘为深研估值已如实标注。", SMALL))

out = ROOT / ".nutmeg-data/zucai/daily/2026-07-04/26090-sfc14-judgment.pdf"
out.parent.mkdir(parents=True, exist_ok=True)
SimpleDocTemplate(str(out), pagesize=(112*mm, 300*mm), topMargin=6*mm, bottomMargin=6*mm, leftMargin=6*mm, rightMargin=6*mm, title="胜负彩26090深研").build(story)
print(f"PDF: {out} ({out.stat().st_size}B)")

load_dotenv(ROOT / ".env")
token = os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN")
ids = [int(x) for x in os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "").split(",") if x.strip()]
if token and ids:
    from nutmeg.interfaces.bot.telegram import TelegramBotClient
    c = TelegramBotClient(token=token)
    cap = ("⚽【终版】胜负彩26090 · 瑞超专项修订后（今晚停售）\n"
           "主力任九：96注¥192，三胆=法国/阿根廷/卡尔马(专项后升信心4)，13 BP盖斯升三全包(两组分歧腿用钱包保护)，联合命中≈9.1%\n"
           "14场彩票层二选一：¥2单式纯判读票 或 ¥128优化复式(64注,≈0.10%)\n"
           "瑞超专项要点：主客分裂极端化禁用通用主场加成；哈马比换帅Rydström首秀；夏窗7/8后才开=本轮阵容零扰动。小额娱乐，空仓合法。")
    for cid in ids:
        c.send_document(chat_id=cid, document_path=out, caption=cap)
        print(f"sent {cid}")
    print("DONE")
else:
    print("⚠️无TG凭据")
