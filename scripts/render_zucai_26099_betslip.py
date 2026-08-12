"""渲染 26099 期传统足彩最终出票方案 PDF（用户授权版）。

内容源：.nutmeg-data/zucai/26099-tickets-user-approved.md + 26099-reads.json
概率均由 scripts/zucai_26099_sfc14_plan.py 的确定性算术产出，脚本内不做任何判断。
"""
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

ROOT = Path(__file__).parents[1]
OUT = ROOT / ".nutmeg-data/zucai/26099-betslip.pdf"

pdfmetrics.registerFont(TTFont("CJK", "/Library/Fonts/Arial Unicode.ttf"))
FONT = "CJK"

INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#6b6b6b")
RULE = colors.HexColor("#d8d8d8")
BAND = colors.HexColor("#f2f4f7")
ACCENT = colors.HexColor("#8c2f2f")
GOOD = colors.HexColor("#1f5c3a")

ss = getSampleStyleSheet()


def st(name, size, leading=None, color=INK, space_before=0, space_after=0, bold_color=None):
    return ParagraphStyle(name, parent=ss["Normal"], fontName=FONT, fontSize=size,
                          leading=leading or size * 1.45, textColor=color,
                          spaceBefore=space_before, spaceAfter=space_after, alignment=TA_LEFT)


H1 = st("H1", 17, 22, INK, 0, 2)
SUB = st("SUB", 8.5, 12, MUTED, 0, 10)
H2 = st("H2", 11.5, 15, INK, 11, 5)
BODY = st("BODY", 8.5, 12.5, INK, 0, 3)
SMALL = st("SMALL", 7.6, 11, MUTED, 0, 2)
CELL = st("CELL", 8, 10.5)
CELLM = st("CELLM", 7.3, 9.8, MUTED)
NOTE = st("NOTE", 7.6, 11, INK, 0, 2)

story = []

story.append(Paragraph("传统足彩 26099 期 · 最终出票方案", H1))
story.append(Paragraph(
    "销售截止 2026-08-02 19:30（北京）　·　开奖 2026-08-04　·　合计 ¥960"
    "　·　板面：瑞超 5 + 挪超 4 + 芬超 3 + 巴西杯首回合 2", SUB))

# ---------------------------------------------------------------- 票一
story.append(Paragraph("票一 · 任九主攻票　288 注 × ¥2 = ¥576", H2))

r9 = [
    ("1", "瑞超", "布鲁马 vs 马尔默", "3 1 0", "100.0%", "降格全包"),
    ("2", "瑞超", "哥德堡 vs 代格福什", "3 1", "79.6%", "跟市场·模态+旗面"),
    ("3", "瑞超", "AIK vs 厄尔格里特", "3", "66.9%", "裸单 · conf4 零无方向旗"),
    ("4", "瑞超", "佐加顿斯 vs 韦斯特罗斯", "3 1", "84.5%", "conf3 禁单选"),
    ("5", "瑞超", "哈尔姆斯塔德 vs 天狼星", "0", "67.9%", "裸单 · conf4 零旗 · 换锚国际盘"),
    ("6", "挪超", "奥勒松 vs 特罗姆瑟", "3 1 0", "100.0%", "两旗方向相反 → 全包"),
    ("7", "挪超", "KFUM奥斯陆 vs 克里斯蒂安松", "3 1", "80.7%", "跟市场·模态+旗面"),
    ("8", "挪超", "莫尔德 vs 萨尔普斯堡", "3 1", "80.4%", "降格场压缩两面"),
    ("14", "巴西杯", "巴拉纳竞技 vs 维多利亚", "3 1", "83.7%", "两方向性旗指平"),
]
data = [[Paragraph(f"<b>{h}</b>", CELL) for h in ("场", "赛事", "对阵", "投注", "盖率", "判决表落位")]]
for row in r9:
    data.append([Paragraph(row[0], CELL), Paragraph(row[1], CELLM), Paragraph(row[2], CELL),
                 Paragraph(f"<b>{row[3]}</b>", CELL), Paragraph(row[4], CELL), Paragraph(row[5], CELLM)])
t = Table(data, colWidths=[11 * mm, 15 * mm, 56 * mm, 18 * mm, 16 * mm, 54 * mm], repeatRows=1)
t.setStyle(TableStyle([
    ("FONTNAME", (0, 0), (-1, -1), FONT),
    ("BACKGROUND", (0, 0), (-1, 0), BAND),
    ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
    ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING", (0, 0), (-1, -1), 3.5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#fdf6f2")),
    ("BACKGROUND", (0, 5), (-1, 5), colors.HexColor("#fdf6f2")),
]))
story.append(t)
story.append(Spacer(1, 5))
story.append(Paragraph(
    "<b>选 9 场：1 / 2 / 3 / 4 / 5 / 6 / 7 / 8 / 14　　丢 9 / 10 / 11 / 12 / 13</b>"
    "（丢的 5 场全是判决表判「降格全包」或「conf3 昂贵双选」的场次）", BODY))
story.append(Paragraph(
    "<b>P9 = 16.61%　|　期望断腿 1.56　|　回本门槛 ¥3,468</b>", BODY))
story.append(Paragraph(
    "结构校验：C(14,9) × 表达级别全枚举，此票同时是「市场口径」与「悲观口径」"
    "（场3 主胜按 55.7%、场5 客胜按 63.3%）下的最优解，两次重跑逐位相同。"
    "9 条腿中 7 条盖住平局，仅两个裸单未盖。", SMALL))

# ---------------------------------------------------------------- 票二
story.append(Paragraph("票二 · 胜负彩判断票　192 注 × ¥2 = ¥384", H2))
story.append(Paragraph(
    "用户 2026-08-02 授权：放开翻面与单押平，按最终结果判断构票。"
    "<b>此为彩票仓，不是判决表合规票。</b>", SMALL))

s1 = [
    ("1", "布鲁马 vs 马尔默", "0", "44.3%", "跟模态。原拟单平已撤：1:1 是模态比分不是模态方向，且弃模态面已三次归零"),
    ("2", "哥德堡 vs 代格福什", "3 1", "79.6%", "代格 4 场 0 进球+锋线卖空；哥德堡 7/30 塔林 120 分钟、4 天后打根特"),
    ("3", "AIK vs 厄尔格里特", "3", "66.9%", "三源盘口差 0.8pp；厄客场 1胜0平6负 3:21、连续 5 场挂零"),
    ("4", "佐加顿斯 vs 韦斯特罗斯", "3", "65.0%", "「客强」是积分幻觉：客场净胜球 −1，对榜前二客场 0 分净胜 −6"),
    ("5", "哈尔姆斯塔德 vs 天狼星", "0", "67.9%", "客场榜第1 vs 主场榜第15；剔除全部 xG 超额后客胜反升到 73.9%"),
    ("6", "奥勒松 vs 特罗姆瑟", "1", "26.0%", "★保留单平：球队级平局率 7平/14 p=0.047（方向级证据）+ 7/31 官宣卖第二中卫 + 12/14 家调水"),
    ("7", "KFUM vs 克里斯蒂安松", "3", "56.1%", "同档拆解：KFUM 主场对非前五 3胜1负；克松客场对非前五 0胜1平3负、7 战 0 零封"),
    ("8", "莫尔德 vs 萨尔普斯堡", "3 1", "80.4%", "萨堡中卫 Utvik 停赛 + Rosted 伤缺；但莫尔德近 5 次对萨堡 0 胜"),
    ("9", "布兰 vs 罗森博格", "3 0", "75.1%", "弃平：布兰 15 轮仅 1 平、主场 7 战 0 平"),
    ("10", "瓦萨 vs 图尔库", "1", "28.4%", "★保留单平：全板最平（35.7/28.4/35.9），仅 7.5pp「翻面」；1:1 是芬超最高频比分 17.1%"),
    ("11", "AC奥卢 vs 伊尔韦斯", "3 1 0", "100.0%", "全票唯一全包：live source_disagreement（体彩 41.8% vs 国际 38.0% 反向 3.7pp）"),
    ("12", "SJK vs 赫尔辛基", "0 3", "76.0%", "弃平：HJK 客场 8 场仅 2 平；总 λ 3.41 把平压到 23.5%"),
    ("13", "米拉索尔 vs 格雷米奥", "3 1", "77.0%", "格雷米奥巴甲客场 0 胜（0-4-6）、场均进 0.4 球、近 20 年最差"),
    ("14", "巴拉竞技 vs 维多利亚", "3 1", "83.7%", "维多利亚客场 0胜4平7负、2026 整年客场不胜；但巴竞技 5/14 同场杯赛 0:0 过不了"),
]
data = [[Paragraph(f"<b>{h}</b>", CELL) for h in ("场", "对阵", "投注", "面值", "判断依据")]]
for row in s1:
    data.append([Paragraph(row[0], CELL), Paragraph(row[1], CELL),
                 Paragraph(f"<b>{row[2]}</b>", CELL), Paragraph(row[3], CELL),
                 Paragraph(row[4], CELLM)])
t2 = Table(data, colWidths=[10 * mm, 44 * mm, 16 * mm, 14 * mm, 86 * mm], repeatRows=1)
t2.setStyle(TableStyle([
    ("FONTNAME", (0, 0), (-1, -1), FONT),
    ("BACKGROUND", (0, 0), (-1, 0), BAND),
    ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
    ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 3.5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ("BACKGROUND", (0, 6), (-1, 6), colors.HexColor("#f1f7f2")),
    ("BACKGROUND", (0, 10), (-1, 10), colors.HexColor("#f1f7f2")),
]))
story.append(t2)
story.append(Spacer(1, 5))
story.append(Paragraph(
    "<b>一等 P14 = 0.128%　|　二等 P(≥13) = 1.477%　|　期望断腿 4.73　|　回本门槛 ¥300,294</b>", BODY))
story.append(Paragraph(
    "嵌套性质：票二在 9 场重叠上完全被票一覆盖 → <b>票二若中，票一必中</b>。"
    "两票同岸相关方向相反：票二靠两个 26–28% 的单平取胜，命中之夜必是冷门夜 → 一等奖落高档"
    "（近 5 期 ¥645,797–¥5,000,000）；票一命中之夜偏热门夜 → 单注奖金落低档。回款分布互补。", SMALL))

story.append(PageBreak())

# ---------------------------------------------------------------- 复核
story.append(Paragraph("售前复核触发（截止 19:30）", H2))
story.append(Paragraph(
    "<b>重要：按赛前 60 分钟出首发估算，截止前能看到首发的只有 20:00 开球的场1 / 场2 / 场10。</b>"
    "场3 首发晚 1 小时，场5 晚 28 小时（8/04 01:00 才开球）—— 两个裸单的阵容 falsifier 都查不到。"
    "因此截止前的复核手段是<b>新闻与钱流，不是阵容</b>。", BODY))

chk = [
    ("全天滚动", "Ure 转会官宣（Lecce / Arsenal / Nice 任一落地，或俱乐部宣布保护性雪藏）",
     "票一+票二 场5 由裸单 0 改双选 0 1"),
    ("全天滚动", "AIK 官方伤情更新出现 Johan Hove（队内唯一稳定得分点，4 球）",
     "票一+票二 场3 由裸单 3 改双选 3 1"),
    ("19:20", "天狼星国际盘由 1.32–1.38 反弹到 ≥1.45（fair 跌破 63%）且查无新闻",
     "视为知情资金 → 场5 改双选"),
    ("19:20", "AIK 国际盘由 1.42 漂到 ≥1.55（fair 跌破 61%）",
     "场3 改双选（该场判读区间本就是 55.7%–65.8%，非标称 66.9%）"),
    ("19:00", "场2 哥德堡首发较 7/30 塔林改动 ≥4 人，或 Bergmark Wiberg / Heintz / S.Larsson ≥2 人不首发",
     "判为「为 8/6 根特留力」→ 票一场2 升 3 1 0"),
    ("19:00", "场1 / 场10 首发（唯一真能看的两场判断腿）",
     "影响票二场10 单平；场1 已改跟模态，敏感度下降"),
    ("19:20", "任一场体彩 SP 与国际盘反向 ≥3pp 且查无催化剂",
     "该场升全包，或通知重排"),
]
data = [[Paragraph(f"<b>{h}</b>", CELL) for h in ("时点", "检查项", "触发动作")]]
for a, b, c in chk:
    data.append([Paragraph(a, CELL), Paragraph(b, CELLM), Paragraph(c, CELL)])
t3 = Table(data, colWidths=[20 * mm, 88 * mm, 62 * mm], repeatRows=1)
t3.setStyle(TableStyle([
    ("FONTNAME", (0, 0), (-1, -1), FONT),
    ("BACKGROUND", (0, 0), (-1, 0), BAND),
    ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
    ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 3.5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ("LEFTPADDING", (0, 0), (-1, -1), 5),
]))
story.append(t3)
story.append(Spacer(1, 4))
story.append(Paragraph(
    "场4 / 场12 / 场14 在停售后开赛（8/04），截止时首发不可观测 —— <b>未知首发不得当作已确认信息</b>。", SMALL))

# ---------------------------------------------------------------- 决策依据
story.append(Paragraph("本期决策依据摘要", H2))
facts = [
    ("胜负彩为何不做合规票",
     "判决表最低合规级别（每场取本场允许的最窄表达）= 4,096 注 = ¥8,192；处方级 31,104 注 = ¥62,208，"
     "期望断腿 2.12 > 2.0 红线 → 分流规则判「只打任九或空仓」。预算内任何 S1 都要放 ≥8 个违规裸单。"),
    ("为何不升档",
     "任九 288 注 ¥576 回本门槛 ¥3,468 是全阶梯最优价；576 注 ¥1,152 门槛升至 ¥5,404，"
     "768 注零裸单 ¥1,536 门槛 ¥7,338。近 20 期任九单注中位 ¥2,156（近 5 期同类板面 ¥2,510–¥30,607）。"),
    ("平局假说已被否",
     "官方近 20 期 280 场实测：主胜 46.1% / 平 25.0% / 客胜 28.6%；本期市场隐含平局均值 24.2% —— "
     "无系统性错价。26098 的 8 平（62%）是方差不是 regime，不得据此系统性加买平局。"),
    ("球队级平局率显著性",
     "14 场逐场二项检验，仅场6（7平/14 vs 市场 26.0%，p=0.047）通过 p<0.05；场3 边缘（13 场零平，p=0.065，"
     "方向是支撑主面）。其余全为噪音，按 §30（n<30 只攒不改模型）不据此调整任何面。"),
    ("今日无任何偏移",
     "14 场净偏移全部 <5pp 归零 —— 没有一条「晚于盘口且够 5pp」的信息面 gap。"
     "任九是纯结构票，不含 edge 主张；票二的两个单平是全天唯一的判断内容。"),
    ("昨日教训的传导",
     "26098 死于「低产旗被主动划掉的偏移裸单」。今日无任何偏移裸单；唯一同构是场3 的 self_made_tail 被降权，"
     "已用悲观口径重跑全枚举验证票面不变，并落入 19:20 钱流触发。"),
]
for k, v in facts:
    story.append(Paragraph(f"<b>{k}</b>　{v}", NOTE))

story.append(Spacer(1, 8))
story.append(Paragraph(
    "本文件为分析与票面记录，不代表已购买。真实购买后必须把 "
    "{issue, kind, stake_yuan, tickets, order_no, purchased_at} 追加到 "
    ".nutmeg-data/zucai/zucai-ledger.jsonl —— 没入账 = 没打。", SMALL))
story.append(Paragraph(
    "生成于 2026-08-02 · Nutmeg 决策本体 · 概率由 scripts/zucai_26099_sfc14_plan.py 确定性算术产出", SMALL))


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(FONT, 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 12 * mm, "传统足彩 26099 · 截止 2026-08-02 19:30 · 合计 ¥960")
    canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


doc = SimpleDocTemplate(str(OUT), pagesize=A4,
                        leftMargin=18 * mm, rightMargin=18 * mm,
                        topMargin=16 * mm, bottomMargin=18 * mm,
                        title="传统足彩 26099 期最终出票方案", author="Nutmeg")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
