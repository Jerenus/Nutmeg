"""渲染 26102 期胜负彩「14 场大胆方案」投注站交付单。

内容源：26102-dcfit.json（去水 fair / DC 拟合）。逐场判断由主循环给出，脚本只做确定性算术。
输出：.nutmeg-data/zucai/26102-bold-betslip.pdf
"""
import json
from functools import reduce
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

ROOT = Path(__file__).parents[1]
DATA = ROOT / ".nutmeg-data/zucai"
OUT = DATA / "26102-bold-v2-betslip.pdf"

pdfmetrics.registerFont(TTFont("CJK", "/Library/Fonts/Arial Unicode.ttf"))
F = "CJK"

INK = colors.HexColor("#141414")
MUTED = colors.HexColor("#6d6d6d")
RULE = colors.HexColor("#dcdcdc")
BAND = colors.HexColor("#eceff3")
PICK = colors.HexColor("#f6f1e6")
FLIP = colors.HexColor("#fdf2e6")
WARN = colors.HexColor("#fbeeee")
ACC = colors.HexColor("#8c2f2f")

ss = getSampleStyleSheet()


def st(n, size, lead=None, color=INK, sb=0, sa=0, align=TA_LEFT):
    return ParagraphStyle(n, parent=ss["Normal"], fontName=F, fontSize=size,
                          leading=lead or size * 1.45, textColor=color,
                          spaceBefore=sb, spaceAfter=sa, alignment=align)


H1 = st("H1", 18, 23, INK, 0, 3)
SUB = st("SUB", 8.4, 12.2, MUTED, 0, 8)
H2 = st("H2", 12, 15.5, INK, 12, 4)
BIG = st("BIG", 15, 20, INK, 3, 4)
CODE = st("CODE", 17, 23, INK, 4, 3)
BODY = st("BODY", 8.6, 12.8, INK, 0, 4)
SMALL = st("SMALL", 7.4, 10.6, MUTED, 0, 3)
CELL = st("CELL", 7.9, 10.8)
CELLC = st("CELLC", 7.9, 10.8, align=TA_CENTER)
CELLM = st("CELLM", 7.2, 10, MUTED)
PICKC = st("PICKC", 12, 14, INK, align=TA_CENTER)

fit = json.loads((DATA / "26102-dcfit.json").read_text("utf-8"))


def M(k):
    f = fit[str(k)]["fair_had_euro"]
    return {"3": f["home"], "1": f["draw"], "0": f["away"]}


META = {
    1: ("荷甲", "08-09 20:30", "格罗宁根", "乌德勒支"),
    2: ("荷甲", "08-09 20:30", "兹沃勒", "阿贾克斯"),
    3: ("荷甲", "08-09 22:45", "海伦芬", "特温特"),
    4: ("葡超", "08-10 01:00", "波尔图", "阿尔维卡"),
    5: ("葡超", "08-10 03:30", "本菲卡", "维塞乌"),
    6: ("葡超", "08-10 03:30", "吉维森特", "里奥阿维"),
    7: ("葡超", "08-10 03:30", "摩雷伦斯", "布拉加"),
    8: ("瑞超", "08-09 22:30", "哥德堡", "卡尔马"),
    9: ("瑞超", "08-09 22:30", "哈尔姆斯塔德", "盖斯"),
    10: ("挪超", "08-09 20:30", "利勒斯特罗姆", "罗森博格"),
    11: ("挪超", "08-09 23:00", "汉坎", "奥勒松"),
    12: ("挪超", "08-10 01:15", "克里斯蒂安松", "莫尔德"),
    13: ("芬超", "08-09 22:00", "国际图尔库", "拉赫蒂"),
    14: ("芬超", "08-10 00:00", "AC奥卢", "赫尔辛基"),
}
TK = {1: "30", 2: "10", 3: "10", 4: "3", 5: "3", 6: "13", 7: "10", 8: "13",
      9: "0", 10: "30", 11: "3", 12: "0", 13: "1", 14: "3"}
CALL = {1: "3", 2: "1", 3: "1", 4: "3", 5: "3", 6: "1", 7: "1", 8: "1",
        9: "0", 10: "3", 11: "3", 12: "0", 13: "1", 14: "3"}
TYPE = {1: "正路", 2: "翻面", 3: "偏移", 4: "正路", 5: "正路", 6: "偏移", 7: "翻面",
        8: "偏移", 9: "正路", 10: "正路", 11: "正路", 12: "正路", 13: "偏移", 14: "翻面"}
WHY = {
 1: "格罗宁根主场全季仅 6 平/34（17.6%），是「赢或输」型主场；乌德勒支 6 人缺阵含后腰 Engwanda + 34 场主力 Jensen，且新帅首秀，破损更重",
 2: "阿贾克斯上季客场 17 场 10 平；同场地上季踢出 0:0（其客场唯二零进球之一）；卖 Steur(€27M)+Mannsverk 后至今未补 6 号位，8/08 俱乐部仍在公开找人",
 3: "DC 模态比分即 1:1；特温特一号中卫 Hilgers 膝伤缺阵、无他的三场共失 6 球；海伦芬季前 4 战 19:10，不会摆铁桶",
 4: "阿尔维卡从未击败波尔图；但波尔图对该对手上季 180 分钟仅进 2 球（1:0、1:1），且 Aghehowa 十字韧带至 10/31 —— 判低比分小胜",
 5: "全板最有把握：中轴 6/12–7/01 重建完毕并通过 5:0 与 6:1 两场正赛检验；对手 37 年首踢顶级、本赛季零正赛节奏；Betfair 交易所 87.4% 高于均值",
 6: "近 4 次正式交锋 0:0 / 2:2 / 1:1 / 1:1 —— 全部平局；两队上季各 11 平与 12 平（后者并列联赛最高）；葡超平局率四季上行至 27.1%",
 7: "布拉加 8/06 主场 1:0 明斯克、8/13 飞保加利亚决胜（悬置夹心，该档实证 3/4 未赢）；本季 3 场 6 球其中 3 个点球，16 球的 Zalazar 已卖、替代者 Wind 一球未踢、门将 8/03 €30.6M 卖纽卡",
 8: "H2H 近 5 次 1:1 / 1:1 / 0:1 / 2:0 / 2:0 —— 两平且总进球全部 ≤2，大 2.5 为 0/5；哥德堡主场 1.14 球/场、卡尔马客场 0.71 球/场，两队都低产",
 9: "盖斯欧战出局后首发全部解禁 + 10 天全休（上次 1:1 时其派的是 B 阵）；对手哈尔姆斯塔德 15 场仅 1 胜、主场 1 胜 2 平 5 负",
 10: "利勒斯特罗姆主场 4 胜 0 平 3 负 vs 罗森博格客场 1 胜 1 平 5 负（客场榜第 14，7 战 5 球）；挪超本季平局率仅 18.25%，低平 regime",
 11: "汉坎主场 5 胜 0 平 2 负（主场零平局）；奥勒松客场 1 胜 2 平 3 负，且全季 15 场 0 零封、场场失球",
 12: "莫尔德虽有洞（门将赛季报销 + 后腰伤 + 中卫售出），但克里斯蒂安松主场 1.14 球/场、近 5 场仅 3 球，DC 给其不进球 28.1%",
 13: "国际图尔库主场 9 场 4 平（44.4%）、射门数全联赛最多而命中率全联赛最低 7.58%；8/13 客场列支敦士登决胜仅领先 1 球，主帅原话「我们才踢到中场休息」",
 14: "AC 奥卢第 4（30 分）积分高于赫尔辛基第 6（28 分）；本季已两次击败 HJK；主场 6 胜 1 平 1 负、4 场零封、半场 0:0 有 6/8；HJK 客场对非垫底两队 5 场 0 胜共进 2 球",
}
CONV = {5: 9.2, 13: 8.5, 14: 8.2, 4: 7.5, 11: 7.0, 2: 6.5, 9: 6.2, 6: 5.8,
        7: 5.0, 10: 3.8, 1: 3.5, 8: 3.0, 12: 2.8, 3: 2.0}
FN = {"3": "主胜", "1": "平局", "0": "客胜"}
SH = {"3": "3", "1": "1", "0": "0"}

cov = {k: sum(M(k)[c] for c in set(v)) for k, v in TK.items()}
notes = reduce(lambda a, b: a * b, (len(set(v)) for v in TK.values()))
p14 = reduce(lambda a, b: a * b, cov.values())
p13 = sum((1 - cov[i]) * reduce(lambda a, b: a * b, [cov[j] for j in cov if j != i]) for i in cov)

story = []


def table(data, widths, hi=(), flip=(), head=True):
    t = Table(data, colWidths=widths, repeatRows=1 if head else 0)
    s = [("FONTNAME", (0, 0), (-1, -1), F), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
         ("TOPPADDING", (0, 0), (-1, -1), 3.4), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.4),
         ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
         ("BOX", (0, 0), (-1, -1), 0.5, RULE), ("LINEBELOW", (0, 0), (-1, -2), 0.25, RULE)]
    if head:
        s += [("BACKGROUND", (0, 0), (-1, 0), BAND), ("LINEBELOW", (0, 0), (-1, 0), 0.7, RULE)]
    for r in hi:
        s.append(("BACKGROUND", (0, r), (-1, r), PICK))
    for r in flip:
        s.append(("BACKGROUND", (0, r), (-1, r), FLIP))
    t.setStyle(TableStyle(s))
    story.append(t)


story.append(Paragraph("传统足彩 第 26102 期 · 胜负彩 14 场「大胆·承诺版」· 投注交付单", H1))
story.append(Paragraph(
    "销售截止 <b>2026-08-09 20:00</b>（北京）　·　开奖 2026-08-10　·　"
    "本票为<b>独立方案</b>，与任选九场分开记账　·　"
    "概率口径：国际即时均值去水 fair（快照 <b>2026-08-09 15:11</b>，已复核）", SUB))

story.append(Paragraph("票面", H2))
story.append(Paragraph("　".join(TK[i] for i in range(1, 15)), CODE))
story.append(Paragraph("　".join(f"<font size=7 color='#6d6d6d'>{i:>2}</font>" for i in range(1, 15)), SMALL))
story.append(Spacer(1, 4))
table([[Paragraph(f"<b>{h}</b>", CELLC) for h in ("玩法", "注数", "金额", "一等奖 14/14", "≥13 有奖", "结构")]] +
      [[Paragraph(x, CELLC) for x in ("胜负彩（复式）", f"{notes} 注", f"¥{notes*2}",
                                      f"{p14*100:.3f}%　(1/{round(1/p14)})",
                                      f"{(p14+p13)*100:.2f}%　(1/{round(1/(p14+p13))})",
                                      "7 单选 + 7 双选")]],
      [26 * mm, 20 * mm, 20 * mm, 34 * mm, 32 * mm, 30 * mm], hi=(1,))

story.append(Paragraph("逐场判断与依据", H2))
rows = [[Paragraph(f"<b>{h}</b>", CELLC) for h in ("场", "赛事", "对阵", "开球", "判断", "信心", "填法", "盖率", "类型", "依据")]]
flips = []
n = 0
for i in range(1, 15):
    n += 1
    lg, ko, h, a = META[i]
    m = M(i)
    mode = max(m, key=m.get)
    dev = CALL[i] != mode
    if dev:
        flips.append(n)
    rows.append([Paragraph(f"<b>{i}</b>", CELLC), Paragraph(lg, CELLM),
                 Paragraph(f"{h} vs {a}", CELL), Paragraph(ko, CELLM),
                 Paragraph(f"<b>{FN[CALL[i]]}</b>" + ("　★" if dev else ""), CELLC),
                 Paragraph(f"<b>{CONV[i]}</b>", CELLC),
                 Paragraph(f"<b>{' '.join(TK[i])}</b>", PICKC),
                 Paragraph(f"{cov[i]*100:.1f}%", CELLC),
                 Paragraph(TYPE[i], CELLC), Paragraph(WHY[i], CELLM)])
table(rows, [7 * mm, 10 * mm, 28 * mm, 17 * mm, 15 * mm, 11 * mm, 14 * mm, 12 * mm, 10 * mm, 58 * mm], flip=flips)
story.append(Spacer(1, 3))
story.append(Paragraph(
    "<b>★ = 该场判断与市场模态面不同（全板 14 场中有 7 场，浅橙底）。</b>　"
    "选项对照：<b>3 = 主胜　1 = 平局　0 = 客胜</b>。", BODY))
story.append(Paragraph(
    "<b>填票要点</b>：场 <b>1 / 4 / 5 / 9 / 10 / 11 / 12</b> 各只勾一项（共 7 场单选）；"
    "场 <b>2 / 3 / 6 / 7 / 8 / 13 / 14</b> 各勾两项（共 7 场双选）。"
    f"<b>合计 {notes} 注 × 每注 ¥2 × 倍数 1 = ¥{notes*2}。</b>", BODY))

story.append(PageBreak())

story.append(Paragraph("本票的构造逻辑：按「信心」分配，而不是按「断腿概率」", H2))
story.append(Paragraph(
    "<b>本票与常规大胆版的关键差别在这里。</b>常规做法是把双选加在断腿概率最高的腿上——"
    "而本期断腿概率最高的 7 条恰好就是 7 条偏离市场模态的腿（79.8% 至 69.2%），"
    "于是「保护最需要保护的腿」等价于「把所有翻面都保起来」，那样其实不算大胆。", BODY))
story.append(Paragraph(
    "<b>本票改按信心分配</b>：<b>在我最有把握的判断上真正下注（裸押），把保险挪给我自己也说不清的腿。</b>"
    "关键事实是——<b>信心与断腿概率几乎不相关</b>：场 13（信心 8.5）与场 3（信心 2.0）的断腿概率同为 73–75%，"
    "但一个是有硬数据支撑的判断，另一个是三方各指一面的糊涂账。前者值得承诺，后者必须买保险。", BODY))
story.append(Spacer(1, 3))
table([[Paragraph(f"<b>{h}</b>", CELLC) for h in ("处理", "场次", "理由")]] +
      [[Paragraph("<b>裸押（单选）</b>", CELLC),
        Paragraph("<b>13 · 14</b>（信心 8.5 / 8.2，均为偏离腿）<br/>4 · 5 · 9 · 11 · 12（跟市场且信心尚可）", CELL),
        Paragraph("场 13、场 14 是全板信心最高的两条<b>逆向</b>判断，本票在这里真正承诺——"
                  "这是它「大胆」的实质。场 5 是全板最有把握的一腿。", CELLM)],
       [Paragraph("<b>加保（双选）</b>", CELLC),
        Paragraph("<b>1 · 10</b>（fair 仅 40%，纯抛硬币）<br/>2 · 3 · 6 · 7 · 8（信心 ≤6.5 的偏离腿）", CELL),
        Paragraph("场 1、场 10 的市场 fair 只有 40.5% / 40.1%，是方向抛硬币场，我的信心分也只有 3.5 / 3.8——"
                  "常规大胆版把它们裸押了，本票把保险挪到这里。", CELLM)]],
      [22 * mm, 62 * mm, 100 * mm])
story.append(Spacer(1, 4))
story.append(Paragraph(
    "<b>代价必须说清</b>：本票 P(14/14) = "
    f"<b>{p14*100:.4f}%（1/{round(1/p14):,}）</b>，而「把 7 条翻面全部加保」的常规版是 1/499。"
    "<b>承诺换来的是六倍的难度。</b>本票的价值只在于：若场 13、场 14 这两条逆向判断兑现，"
    "它们同时也是最能淘汰其他彩民的两条腿。", BODY))
story.append(Paragraph(
    "<b>本票的方向性</b>：14 场里判平 <b>6 场</b>，而 14 场平局面的 fair 合计期望只有 <b>3.27 场</b>——"
    "比期望多出 2.7 场。这是本票最大的系统性风险：<b>它押的是一个高平局之夜</b>。"
    "六条判平各有独立依据（场 6 的 H2H 四战全平、场 8 的 H2H 五战两平且全部 ≤2 球、场 13 的主场 44.4% 平率、"
    "场 3 的 DC 模态即 1:1、场 2 的客场 17 场 10 平、场 7 的悬置夹心+锋线塌陷），"
    "但它们共享同一个风险：<b>若今晚不是平局之夜，本票会碎得很快</b>。", BODY))

story.append(Paragraph("风险与最可能的死法", H2))
rows = [[Paragraph(f"<b>{h}</b>", CELLC) for h in ("场", "对阵", "盖率", "断腿概率", "漏掉的面")]]
for k in sorted(cov, key=lambda x: cov[x])[:6]:
    miss = "".join(FN[c][0] for c in "310" if c not in TK[k])
    rows.append([Paragraph(f"<b>{k}</b>", CELLC), Paragraph(f"{META[k][2]} vs {META[k][3]}", CELL),
                 Paragraph(f"{cov[k]*100:.1f}%", CELLC),
                 Paragraph(f"<b>{(1-cov[k])*100:.1f}%</b>", CELLC), Paragraph(miss, CELLC)])
table(rows, [10 * mm, 62 * mm, 20 * mm, 24 * mm, 24 * mm])
story.append(Spacer(1, 3))
story.append(Paragraph(
    f"<b>期望断腿数 = {sum(1-c for c in cov.values()):.2f} 条。</b>　"
    "本票最脆的两条是 <b>场 13（裸押平局，26.7%）与场 14（裸押主胜，30.8%）</b>——"
    "这是承诺的代价，也是设计意图：它们正是全票信心最高、且最能淘汰其他彩民的两条判断。"
    "<b>如果这两条中任意一条断掉，一等奖即刻出局</b>（二等奖仍可保）。", BODY))

story.append(Paragraph("必须知道的历史记录", H2))
story.append(Paragraph(
    "本决策体系的既往实证中：<b>胜平负押冷门 0/23</b>；<b>翻面（押非市场模态面）0/42</b>。"
    "本票含 3 条明确翻面（场 2、场 7、场 14）与 3 条朝平偏移（场 3、场 6、场 8、场 13）。"
    "这些记录不构成否决——本票是被明确要求的「大胆方案」，其价值在于低概率高赔付的敞口，"
    "而非稳健命中——但<b>购买前应知晓该体系在这一类表达上尚无正样本</b>。", BODY))
story.append(Paragraph(
    f"<b>回本门槛</b>：一等奖口径 ¥{notes*2/p14:,.0f}（胜负彩一等奖常在数十万至数百万元区间，取决于当期中奖注数）；"
    f"计入二等奖后的 ≥13 口径 ¥{notes*2/(p14+p13):,.0f}。<b>均为概率算术，非收益承诺。</b>", SMALL))
story.append(Paragraph(
    "<b>出票前复核（15:11）</b>：场 14 客胜（赫尔辛基）六小时内被买高 <b>+1.5pp</b>（42.6%→44.1%），"
    "而本票在该场<b>裸押 AC 奥卢主胜</b>。翻面纪律要求「收盘未朝相反方向移动 ≥2pp」，现为 1.5pp，"
    "<b>接近但未破门槛，故保留裸押</b>；若截止前扩大至 ≥2pp，按纪律应放弃该条翻面。"
    "同期场 7 客胜 +1.7pp、场 4 主胜 −1.4pp，均已计入上表盖率。", BODY))
story.append(Paragraph(
    "<b>其他提示</b>：各联赛官方首发普遍在开球前约 1 小时公布，"
    "均晚于 20:00 销售截止，该信息通道在出票前不可得。彩票有风险，请量力而行、理性投注。", SMALL))

SimpleDocTemplate(str(OUT), pagesize=A4,
                  leftMargin=13 * mm, rightMargin=13 * mm,
                  topMargin=13 * mm, bottomMargin=12 * mm,
                  title="传统足彩 26102 期 · 胜负彩大胆方案交付单",
                  author="Nutmeg 决策本体").build(story)
print(f"→ {OUT}  ({notes} 注 ¥{notes*2}, P14={p14*100:.4f}%)")
