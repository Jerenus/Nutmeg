"""渲染 26102 期传统足彩「完整推理路径 + 决策」PDF（拼单共享版）。

内容源：26102-dcfit.json（DC 拟合 / 去水 fair）+ 26102-euro.json（国际开盘/即时）
        + 26102-rx.json（阶段①共振定面的面集合）+ sporttery_markets.json（体彩盘 / 陈盘时间戳）
所有概率均为确定性算术（去水 + Dixon-Coles），脚本内不做任何判断。
输出：.nutmeg-data/zucai/26102-dossier.pdf
"""
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

ROOT = Path(__file__).parents[1]
DATA = ROOT / ".nutmeg-data/zucai"
OUT = DATA / "26102-dossier.pdf"

pdfmetrics.registerFont(TTFont("CJK", "/Library/Fonts/Arial Unicode.ttf"))
F = "CJK"

INK = colors.HexColor("#141414")
MUTED = colors.HexColor("#6d6d6d")
RULE = colors.HexColor("#dcdcdc")
BAND = colors.HexColor("#eceff3")
PICK = colors.HexColor("#f6f1e6")
WARN = colors.HexColor("#fbeeee")
GOOD = colors.HexColor("#eef4ee")
ACC = colors.HexColor("#8c2f2f")

ss = getSampleStyleSheet()


def st(n, size, lead=None, color=INK, sb=0, sa=0, align=TA_LEFT):
    return ParagraphStyle(n, parent=ss["Normal"], fontName=F, fontSize=size,
                          leading=lead or size * 1.45, textColor=color,
                          spaceBefore=sb, spaceAfter=sa, alignment=align)


H1 = st("H1", 19, 24, INK, 0, 3)
SUB = st("SUB", 8.6, 12.5, MUTED, 0, 8)
H2 = st("H2", 12.5, 16, INK, 13, 5)
H3 = st("H3", 10, 13.5, ACC, 8, 3)
BIG = st("BIG", 14, 19, INK, 3, 4)
BODY = st("BODY", 8.6, 12.8, INK, 0, 4)
SMALL = st("SMALL", 7.4, 10.6, MUTED, 0, 3)
CELL = st("CELL", 7.8, 10.6)
CELLC = st("CELLC", 7.8, 10.6, align=TA_CENTER)
CELLM = st("CELLM", 7.2, 10, MUTED)
PICKC = st("PICKC", 11, 13, INK, align=TA_CENTER)

fit = json.loads((DATA / "26102-dcfit.json").read_text("utf-8"))
euro = json.loads((DATA / "26102-euro.json").read_text("utf-8"))
rx = {int(k): v for k, v in json.loads((DATA / "26102-rx.json").read_text("utf-8")).items()}

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
STALE = {1, 3, 4, 6}          # 体彩盘冻结在 2026-08-07
TICKET = {2: "01", 4: "31", 5: "3", 7: "01", 8: "310", 9: "01", 10: "30", 13: "31", 14: "310"}
FACE = {"3": "主", "1": "平", "0": "客"}

# 逐场判读：旗 / 动作 / 共振级 / 双选逻辑档 / 一句话立论
READ = {
 1: ("two_way_instability(客队) · anchor_shield_out(条件)", "降格", "弱", "T3",
     "乌德勒支 6 人缺阵含后腰 Engwanda + 34 场主力 Jensen，双后腰由新援新队长+天生右后卫拼凑、新帅首秀；但格罗宁根自己也丢了 6 号主力中场 Resink(32 首发)与 9 助攻的 Taha。双方中轴对称破损，排除不掉任何一面。"),
 2: ("anchor_shield_out（强）", "偏移 −8.5pp", "反", "T1",
     "阿贾克斯卖 Steur(€27M→纽卡)+Mannsverk，Henderson 已走，未补 6 号位——8/08 荷媒明文俱乐部仍在找人；ter Stegen 未首秀、天价新援“需要耐心”。排除主：兹沃勒在 MAC³PARK 近三次对阿贾克斯 1:3/0:1/0:0 从未赢；包含平：同场地上季 0:0，且阿贾克斯上季客场 17 场 10 平。"),
 3: ("anchor_shield_out(半，已归零)", "跟市场", "散", "T4",
     "特温特一号中卫 Hilgers 膝伤（双源），但主帅 8/08 称阵容完整、后腰端反而加强（Zerrouki 回归首发进球）。逻辑指平 / 钱流指主 / 模态是客——三方各指一面，全板最弱腿。"),
 4: ("self_made_tail（强）· 翻车场候选", "跟市场", "反", "T1",
     "锚方结构完整：Bednarek(32 场·葡超赛季最佳阵)+Kiwior(€17M 转永久)双双在队、8 天前刚零封，中场 6 人齐，8 月零欧战。但破门手段缺：Aghehowa(上季 13 球)十字韧带至 10/31，季前 4 战 5 球，超级杯对葡甲队运动战 0 球。排除客：阿尔维卡从未击败波尔图；包含平：上季在阿尔维卡就是 1:1，且那是波尔图全季唯一的客场平局。"),
 5: ("空场 porta fechada（四源确证）", "跟市场", "★强", "T1",
     "中轴(Florentino/Kökçü/Otamendi/António Silva)确实卖光，但拆解在 6/12–7/01 完成，之后经完整季前 + 5:0 与 6:1 两场正赛压力测试，今日无一名防守中轴缺阵；欧战夹心 8/06 主场 6:1 已决 = 0pp。对手维塞乌 37 年首次踢顶级、7 名新援 8/03–8/07 到队（前锋赛前 48 小时）、本赛季零正赛节奏。Betfair 交易所 87.4% 高于 6 家均值——最聪明的钱没有 fade。"),
 6: ("league_draw_regime + self_made_tail（互相矛盾）", "降格", "✗互斥", "T4",
     "两条方向性旗都指平（葡超平局率四季上行至 27.1%；近 4 次正式交锋 0:0/2:2/1:1/1:1 全部平局），但今早国际盘钱流指客（−3.5pp 中 +2.6pp 流向客队）。旗面≠钱流面，双选盖不住，净效果等价于无方向。"),
 7: ("undecided_second_leg（悬置）+ self_made_tail", "降格→双选", "★同向", "T2",
     "布拉加 8/06 主场 1:0 迪纳摩明斯克（奥尔塔点球），8/13 客场保加利亚中立场决胜——悬置档，实证 3/4 未赢；对手主帅赛前公开预告“对面会有小的战术性变动”。本季 3 场进 6 球其中 3 个点球，卖掉 16 球的 Zalazar，替代者 Wind 一球未踢，门将 8/03 €30.6M 卖纽卡。▲出票前复核修正：09:18 时钱流完全静止（＝没人在买布拉加），据此定为★同向共振；15:11 复核发现客胜已被买高 +1.7pp，该依据失效，本场降级为「反」级（逻辑与钱流反向）。按共振表「反」级处方同为双选（模态+旗面），故票面不变，且盖率由 80.7% 升至 82.1%。"),
 8: ("悬置(争议) + dressing_room_turmoil + two_way_instability", "降格", "✗无", "T4",
     "四重触发：8/06 主场 0:1 负根特（8/13 客场决胜）、7/27 换帅+董事会公开承认“巨大的失望”、10 号 Lundqvist 无限期病休；客队卡尔马 10 天内卖走国脚中卫扬松、后防需 P19 青训小将首次首发。逻辑本身没有方向，而 top1 仅 39.0%——全板最冷，淘汰力第一。"),
 9: ("self_made_tail", "跟市场", "反", "T2",
     "盖斯客场 7 场 1 胜 5 分 7 球（1.00 球/场），全队最佳射手 3 球；近两年对哈尔姆斯塔德的 8 个进球中 6 球出自本场缺阵/疑似离队的三人（Diabate 4、Holmén 1、Lundgren 1）。排除主：哈尔姆斯塔德 15 场仅 1 胜、主场 1 胜 2 平 5 负。反向证据：盖斯欧战出局后首发解禁 + 10 天全休。"),
 10: ("transfer_breaker_out", "降格", "★同向", "T1",
      "利勒斯特罗姆 8/8 官宣卖出 Karlsbakk（71 场 39 球助、2025 双冠核心），无补强；钱流 −2.3pp 同向且时间对上官宣。排除平的证据是全板最硬的四条：LSK 主场 0 平/7、全季仅 1 平/15（全联赛最低）、罗森博格客场 1 平/7、挪超本季平局率仅 18.25%。▲ 该双选弃旗面取市场第 2 面，属一次面选偏离。"),
 11: ("top1 44.6% < 45%（差 0.4pp）", "降格", "弱", "T3",
      "汉坎左翼卫 Ekeroth（12 首发/1090 分钟）8/6 卖捷克、替补 8/7 才首练——但消息公开后钱流只走 −0.4pp，已定价。▲ 降格触发是 top1 44.6% 对 45.0% 门槛，差 0.4pp，而开盘时正好 45.0%（不触发）：它是盘口漂了 0.4pp 才掉进触发区的，全板最边缘的降格。"),
 12: ("two_way_instability", "降格", "★同向", "T3",
      "莫尔德被削在防守轴（主力门将赛季报销 + 后腰 Hoff 膝伤 + 中卫 Amundsen 7/27 售出），克里斯蒂安松被削在进攻轴（边锋 8/07 卖出、中场 Ødegård 8/01 转投对手）。▲ 双选逻辑反向：要排除的主胜在近 6 次正赛中发生过 3 次（含主场 2:1 半场落后逆转、杯赛 0:2→4:3），而要包含的平局在该对阵 6 战 0 次。"),
 13: ("undecided_second_leg（悬置）+ self_made_tail", "降格→双选", "★同向", "T1",
      "国际图尔库 8/06 主场 2:1 瓦杜兹，8/13 客场列支敦士登决胜仅领先 1 球，主帅原话“领先一个球，我们才踢到中场休息”；本季前两轮决胜回合都在主场，这是首次客场关门。排除客：拉赫蒂客场 8 场 0.75 球/场、3 场零进球，对国际图尔库近 5 战 0 胜其中 3 场零进球；包含平：主场 9 场 4 平(44.4%)、射门全联赛最多而命中率全联赛最低 7.58%。"),
 14: ("undecided_second_leg（悬置）", "降格", "反", "T4",
      "赫尔辛基 8/06 主场 1:1 马瑟韦尔，8/13 客场苏格兰决胜、总分全悬；客场对非垫底两队 5 场 0 胜 1 平 4 负共进 2 球。▲ 逻辑与市场模态相反：AC 奥卢第 4（30 分）积分高于 HJK 第 6（28 分），本季已两次击败 HJK，主场 6 胜 1 平 1 负 4 场零封。任何双选都自相矛盾（弃模态面被禁，排除主胜又与逻辑冲突）→ 全包是唯一诚实表达。"),
}

story = []


def hr(space=4):
    t = Table([[""]], colWidths=[182 * mm], rowHeights=[0.6])
    t.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.7, RULE)]))
    story.append(Spacer(1, space))
    story.append(t)
    story.append(Spacer(1, space))


def table(data, widths, hi=(), warn=(), good=(), head=True, fs=7.8):
    t = Table(data, colWidths=widths, repeatRows=1 if head else 0)
    style = [("FONTNAME", (0, 0), (-1, -1), F),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("TOPPADDING", (0, 0), (-1, -1), 3.2),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2),
             ("LEFTPADDING", (0, 0), (-1, -1), 4),
             ("RIGHTPADDING", (0, 0), (-1, -1), 4),
             ("BOX", (0, 0), (-1, -1), 0.5, RULE),
             ("LINEBELOW", (0, 0), (-1, -2), 0.25, RULE)]
    if head:
        style += [("BACKGROUND", (0, 0), (-1, 0), BAND),
                  ("LINEBELOW", (0, 0), (-1, 0), 0.7, RULE)]
    for r in hi:
        style.append(("BACKGROUND", (0, r), (-1, r), PICK))
    for r in warn:
        style.append(("BACKGROUND", (0, r), (-1, r), WARN))
    for r in good:
        style.append(("BACKGROUND", (0, r), (-1, r), GOOD))
    t.setStyle(TableStyle(style))
    story.append(t)


def P(txt, s=BODY):
    story.append(Paragraph(txt, s))


# ───────────────────────────── 封面 / 摘要
story.append(Paragraph("传统足彩 第 26102 期 · 完整推理路径与决策", H1))
story.append(Paragraph(
    "销售截止 <b>2026-08-09 20:00</b>（北京）　·　开奖 2026-08-10　·　"
    "板面：荷甲 3 + 葡超 4 + 瑞超 2 + 挪超 3 + 芬超 2　·　"
    "▲ 荷甲与葡超仍是第 1 轮，<b>7/14 场处于揭幕轮方差窗口</b>", SUB))

P("<b>结论先行</b>", H2)
codeline = "　".join(TICKET.get(i, "—") for i in range(1, 15))
P(f"<b>{codeline}</b>", BIG)
P("　".join(f"<font size=7 color='#6d6d6d'>{i}</font>" for i in range(1, 15)), SMALL)
story.append(Spacer(1, 3))
table([[Paragraph(f"<b>{h}</b>", CELLC) for h in ("玩法", "注数", "金额", "全中概率", "回本门槛", "结构")]] +
      [[Paragraph(x, CELLC) for x in ("任选九场", "576 注", "¥1,152", "24.75%", "¥4,654",
                                      "2 全包 + 6 双选 + 1 单胆 + 丢 5 场")]],
      [24 * mm, 22 * mm, 24 * mm, 26 * mm, 26 * mm, 60 * mm], hi=(1,))
story.append(Spacer(1, 4))
P("<b>回本门槛</b> = 成本 ÷ 全中概率，即「本期任九单注奖金需达到多少才不亏」。历史参照：26093 冷门度低 ¥2,510；"
  "26096 极难之夜 501 注 × ¥16,097。<b>本期板面偏难</b>——散户「挑最有把握的 9 场全部裸单」存活率仅 <b>0.83%</b>，"
  "14 场中市场模态面的期望命中数只有 7.45，故门槛具备兑现条件。<b>非收益承诺，彩票有风险。</b>", SMALL)

hr()
P("<b>本期板面的三个结构特征</b>", H2)
P("<b>① 四个悬置的欧战夹心——我做过的最集中的一次。</b> 全板 6/14 场的球队本周有欧战，其中 4 场落在「悬置」档："
  "布拉加（8/06 主场 1:0 明斯克 → 8/13 保加利亚中立场）、哥德堡（0:1 负根特 → 8/13 客场比利时）、"
  "国际图尔库（2:1 瓦杜兹 → 8/13 客场列支敦士登）、赫尔辛基（1:1 马瑟韦尔 → 8/13 客场苏格兰）。"
  "四条全部是「主场首回合 → 客场决胜」。该档历史实证 3/4 未赢。另有阿贾克斯（3:1）与特温特（6:0）属已决档，不计权重。")
P("<b>② 零场取得单选许可。</b> 单选门槛为三条并列：零方向性旗 ∧ 去水 fair ≥60% ∧ 锚方结构完整度检验通过。"
  "全板 fair ≥60% 的只有 3 场（本菲卡 85.8%、波尔图 80.3%、阿贾克斯 64.0%），<b>三场全部带方向性旗</b>。"
  "本票唯一的单胆（本菲卡）是一次有明确理由的例外，见第 4 节。")
P("<b>③ 体彩盘全板不可作为概率输入——两种独立机制。</b>")
P("　• <b>陈盘</b>：场 1/3/4/6 的体彩五个池全部冻结在 <b>2026-08-07 09:35</b>（两天未动）。以场 6 为例，"
  "所谓「体彩比国际更挺主 3.7pp」经核算是伪矛盾——体彩去水 52.1% 与国际<b>开盘</b> 51.9% 只差 0.2pp，"
  "差的是时间不是观点。", SMALL)
P("　• <b>热门档单边砍价</b>：以「凯利指数 = 体彩赔率 × 国际去水 fair」扫描全板，体彩返还率稳定在 88.5–88.6%，"
  "若抽水均摊则三档凯利应都 ≈0.885。实际场 13 主档 <b>0.794</b>、场 14 客档 <b>0.788</b>、场 9 客档 <b>0.839</b>，"
  "而各自对面档凯利反而 &gt;1.0。<b>被砍的永远是散户会押的热门面</b>——这是抽水的不对称分配，不是信息。", SMALL)
P("　⇒ 本报告全部概率一律采用<b>国际 14–15 家即时均值去水 fair</b>（快照 2026-08-09 15:11），体彩盘仅贡献总进球分布形状。", SMALL)

story.append(PageBreak())

# ───────────────────────────── 逐场判读
P("1 · 逐场判读（14 场全览）", H2)
P("fair = 国际 14–15 家即时均值去水。<b>钱流</b> = 开盘→即时的位移。<b>动作</b>按四级阶梯：跟市场 / 偏移 / 降格 / 翻面。", SMALL)
story.append(Spacer(1, 3))
rows = [[Paragraph(f"<b>{h}</b>", CELLC) for h in ("场", "赛事", "对阵", "开球", "fair 主/平/客", "钱流Δpp", "尾巴旗", "动作")]]
warn_rows = []
for i in range(1, 15):
    lg, ko, h, a = META[i]
    f = fit[str(i)]["fair_had_euro"]
    o, l = euro[str(i)]["euro_open"], euro[str(i)]["euro_live"]
    dd = [(l[k] - o[k]) * 100 for k in ("home", "draw", "away")]
    flow = " / ".join(f"{x:+.1f}" for x in dd)
    if max(abs(x) for x in dd) < 1.0:
        flow = "静止"
    flag, act, res, tier, _ = READ[i]
    star = " †" if i in STALE else ""
    rows.append([Paragraph(f"<b>{i}</b>", CELLC), Paragraph(lg, CELLM),
                 Paragraph(f"{h} vs {a}{star}", CELL), Paragraph(ko, CELLM),
                 Paragraph(f"{f['home']*100:.1f} / {f['draw']*100:.1f} / {f['away']*100:.1f}", CELLC),
                 Paragraph(flow, CELLC), Paragraph(flag, CELLM), Paragraph(act, CELLC)])
    if i in TICKET:
        warn_rows.append(i)
table(rows, [8 * mm, 12 * mm, 38 * mm, 19 * mm, 28 * mm, 22 * mm, 42 * mm, 17 * mm], good=warn_rows)
P("† = 该场体彩盘冻结于 2026-08-07（陈盘）。<b>浅绿底 = 进入本票的 9 场。</b>", SMALL)

hr()
P("2 · 构票方法：两阶段（本期最重要的流程修正）", H2)
P("<b>错误的出发点</b>：判决表逐场跑完 → 若干场触发「降格」→ 默认它们是全包 → 在全包堆里做减法。"
  "这会把「判决表触发了防御规则」错当成「我没有判断」，从而掩盖那些逻辑与钱流同向的高质量双选。"
  "本期初稿正是这样判出了 9 场全包，票价虚高、覆盖虚低。")
P("<b>正确的出发点</b>：先对<b>每一场</b>（含被判降格的）做共振判定，由共振决定「双选选哪两面」；"
  "面集合定完之后，才用全中概率决定「留哪 9 场」。两阶段使用<b>不同的判据</b>，不可混用。")
story.append(Spacer(1, 3))
table([[Paragraph(f"<b>{h}</b>", CELLC) for h in ("共振级", "定义", "处方")]] +
      [[Paragraph(a, CELLC), Paragraph(b, CELL), Paragraph(c, CELL)] for a, b, c in [
          ("★同向", "逻辑方向与钱流方向指同一面（含「钱流静止＝没人在买逻辑要削的那一面」）", "双选：模态面 + 共振面"),
          ("反", "逻辑与钱流指相反面，但一个双选能同时盖住", "双选：模态面 + 旗面"),
          ("弱", "有方向但钱流无反应（消息已定价）／双方结构对称", "全包，或丢"),
          ("散", "逻辑、钱流、模态三者各指一面", "优先丢"),
          ("✗互斥", "逻辑与钱流指相反面且双选盖不住", "全包（真无方向）"),
      ]], [18 * mm, 92 * mm, 46 * mm])
P("<b>关键护栏一：共振强度 ≠ 覆盖率，禁止用共振级挑场次。</b> 本期反证：硬把 5 条 ★共振腿全留下 → 全中概率仅 30.7%；"
  "按覆盖率选（含两条「反共振」但覆盖 93.7%/84.2% 的腿）→ <b>44.4%</b>。", SMALL)
P("<b>关键护栏二：在奖池均分制里，全包不是「放弃判断」。</b> 它把「不可测」转化成「别人死我不死」——"
  "在 top1 越低的场次上全包，淘汰的对手越多而我恒活（本期场 8 的 top1 仅 39.0%，散户裸单 61% 死亡率）。"
  "故<b>同注数下全包场应优先选 top1 最低的几场</b>：这一步对我方命中率零影响、对期望奖金单调有利。"
  "但这不构成多留全包的理由——<b>全包只发给共振判定为「弱 / ✗互斥」的场次</b>。", SMALL)

story.append(PageBreak())

# ───────────────────────────── 翻车场
P("3 · 翻车场扫描", H2)
P("<b>机制</b>：市场给<b>纸面实力（存量）</b>定价，而结构漏洞（防守中轴缺阵、全新组合首秀、主力赛前 48 小时被卖）"
  "属于<b>流量</b>。弱队有洞不改变什么——它本来就要输；<b>强队有洞才是 80%→60% 的差</b>，但价格被「名字」锚住只小幅移动。"
  "⇒ 锚越强，未定价的结构漏洞越值钱。同时短赔看着「稳」，散户在强锚上几乎必然裸单不买保险。"
  "<b>最大定价误差 × 最大公众暴露落在同一场，两个机制复利。</b>")
P("<b>识别式</b>：fair top1 ≥70% 的强锚 ∧ 带任何方向性旗。本期符合的只有两场，且都在葡超第 1 轮、体彩都不开胜平负盘：")
story.append(Spacer(1, 3))
table([[Paragraph(f"<b>{h}</b>", CELLC) for h in ("场", "锚", "fair", "旗", "锚方结构完整度检验", "处置")]] +
      [[Paragraph("5", CELLC), Paragraph("本菲卡", CELL), Paragraph("85.8%", CELLC),
        Paragraph("空场（四源确证）", CELL),
        Paragraph("<b>✓ 通过</b>：中轴拆解于 6/12–7/01 完成，已过 5:0 与 6:1 两场正赛压力测试，今日无一名防守中轴缺阵", CELL),
        Paragraph("单胆", CELLC)],
       [Paragraph("4", CELLC), Paragraph("波尔图", CELL), Paragraph("80.3%", CELLC),
        Paragraph("self_made_tail", CELL),
        Paragraph("<b>✓ 通过</b>：Bednarek(32 场·赛季最佳阵)+Kiwior(€17M 转永久)双双在队、8 天前刚零封，中场 6 人齐，8 月零欧战", CELL),
        Paragraph("双选", CELLC)]],
      [8 * mm, 20 * mm, 16 * mm, 30 * mm, 76 * mm, 16 * mm], good=(1,), hi=(2,))
P("<b>前一期（26101）的对照</b>：当晚 fair ≥70% 的锚同样只有 2 个——埃因霍温 80.2%（双后腰齐缺：Veerman 停赛 + Schouten 十字韧带）"
  "与里斯本竞技 76.5%（队长后腰 €40M 卖马竞、替代双后腰正赛首秀）。<b>锚强度排名第 1 与第 2，两个都带方向性旗，两个都开【平】(2:2 / 2:2)</b>。"
  "<b>那两场都没有通过锚方结构完整度检验；本期两场都通过了。</b>同一个筛选器在两天里给出相反信号，说明它在分辨东西，不是在拟合。", SMALL)
P("<b>处置按渠道相反</b>：任选九场（奖池均分）→ 翻车场必须全包或双选，<b>绝不裸单</b>，目标是「别人死时我活」；"
  "竞彩／胜负彩固定赔率 → 翻车场<b>直接空仓</b>（没有奖池红利，只有风险）。", SMALL)

hr()
P("4 · 唯一单胆：场 5 本菲卡（含一次规则例外的说明）", H2)
P("<b>常规规则要求</b>：任何方向性旗一律升双选，fair 高低不得覆盖旗——这条是前一期用 −¥972 的实亏换来的。"
  "本场带「空场」旗，按字面应升双选。<b>本票做了例外，理由不是「fair 高」，而是「旗的幅度被实测过」：</b>")
P("对空场削主场优势做了 8 情景敏感性扫描——放大到「重度削 + 轮换」主胜仍 <b>73.6%</b>，"
  "放大到荒谬的「极端悲观」（把本菲卡当中游球队）仍 <b>65.6%</b>，<b>模态方向在全部 8 个情景里从未翻转</b>；"
  "崩掉的是净胜分（让球 −2 的让胜档从 45.6% 掉到 20.5%），不是方向。"
  "前一期我说的是「已被盘口定价所以免疫」——那是<b>断言</b>；本期是把参数扫了一遍看模态翻不翻——这是<b>测量</b>。两者不同。")
P("<b>另一条支持</b>：同一 tie 上 Betfair 交易所（最 sharp 的源）给 87.4%，<b>高于</b> 6 家均值 85.8%——聪明钱没有在 fade。")
P("<b>落库的证伪条件</b>：若本场开出非本菲卡胜，「旗幅度可测就能发胆」这条<b>立即作废</b>，退回严格版本。"
  "残余风险：中卫只剩 Araújo + Lenglet 两名成年主力，第三选项是 18 岁新援与一名中场改造——"
  "一旦赛中伤退或红牌即退化成前一期的形态，但这是赛中不可预知的尾部风险，不是赛前已知的洞。", SMALL)

story.append(PageBreak())

# ───────────────────────────── 双选逻辑分档
P("5 · 双选的逻辑分档（判据 = 排除第三面的把握）", H2)
P("单选问「我知道是哪一面」；<b>双选问「我有没有把握排除第三面」</b>——这是两个不同的判据。"
  "按后者重排，结果与覆盖率排序差异很大，而差异本身就是信息。", SMALL)
story.append(Spacer(1, 3))
T = {5: 1, 4: 1, 2: 1, 13: 1, 10: 1, 9: 2, 7: 2, 12: 3, 11: 3, 1: 3, 6: 4, 8: 4, 14: 4, 3: 4}
DB = {5: ("主平", "客 4.3%"), 4: ("主平", "客 6.3%"), 2: ("客平", "主 15.8%"), 13: ("主平", "客 23.7%"),
      10: ("主客", "平 26.3%"), 9: ("客平", "主 18.8%"), 7: ("客平", "主 19.3%"), 12: ("客平", "主 21.2%"),
      11: ("主平", "客 30.1%"), 1: ("主平", "客 32.3%"), 6: ("主平", "客 24.5%"), 8: ("主客", "平 26.8%"),
      14: ("客平", "主 30.8%"), 3: ("客平", "主 32.7%")}
REASON = {
 5: "维塞乌 37 年首踢顶级、零正赛节奏、7 名新援赛前一周到队 ／ 第二面：空场削主场优势（已量化）",
 4: "阿尔维卡从未击败波尔图，波尔图防线完整刚零封 ／ 第二面：<b>上季在阿尔维卡就是 1:1</b>，全板最具体",
 2: "兹沃勒在 MAC³PARK 近三次 1:3 / 0:1 / 0:0 从未赢 ／ 第二面：<b>同场地上季 0:0</b> + 客场 17 场 10 平 + 无 6 号位",
 13: "拉赫蒂客场 0.75 球/场、3 场零进球，对该对手近 5 战 0 胜 3 场零进球 ／ 第二面：<b>主场 4/9 平 = 44.4%</b>",
 10: "<b>排除平的证据全板最硬</b>：主场 0 平/7 + 全季 1 平/15（全联赛最低）+ 对手客场 1 平/7 + 挪超本季 18.25%，四条独立",
 9: "哈尔姆斯塔德 15 场仅 1 胜、主场 1 胜 2 平 5 负 ／ 第二面中等：盖斯客场 1.00 球/场",
 7: "近 6 次交锋布拉加 6 胜 0 平 0 负，摩雷伦斯从未赢 ／ ▲ 但该对阵 6 战 0 平，包含的「平」面没有先例",
 12: "▲ 要排除的主胜在近 6 次正赛发生过 3 次（含主场 2:1 半场落后逆转）；▲ 要包含的平在该对阵 6 战 0 次",
 11: "奥勒松客场 1 胜 2 平 3 负；Ekeroth 卖出但钱流无反应＝已定价",
 1: "▲ 排除不掉客——乌德勒支上季高 5 分、近 4 次交锋 3 胜",
 6: "▲ 自相矛盾：要排除的客胜正是钱流流入的一面（+2.6pp）",
 8: "无排除理由（四重触发，逻辑本身没有方向）",
 14: "▲ 自相矛盾：逻辑恰恰说 AC 奥卢该赢（第 4 名积分高于 HJK 第 6 名、本季两胜 HJK）",
 3: "散：逻辑指平 / 钱流指主 / 模态是客，三方各指一面",
}
rows = [[Paragraph(f"<b>{h}</b>", CELLC) for h in ("档", "场", "对阵", "双选", "盖率", "排除面", "排除理由 ／ 第二面理由")]]
gr, wr = [], []
n = 0
for k in sorted(T, key=lambda x: (T[x], -sum(fit[str(x)]["fair_had_euro"][c] for c in
                                             {"主": ["home"], "客": ["away"], "平": ["draw"]}[DB[x][0][0]]))):
    n += 1
    m = fit[str(k)]["fair_had_euro"]
    mm_ = {"3": m["home"], "1": m["draw"], "0": m["away"]}
    fs = rx[k] or "310"
    cov = sum(mm_[c] for c in dict.fromkeys(DB[k][0].translate(str.maketrans("主平客", "310"))))
    rows.append([Paragraph(f"<b>T{T[k]}</b>", CELLC), Paragraph(f"<b>{k}</b>", CELLC),
                 Paragraph(f"{META[k][2]} vs {META[k][3]}", CELL), Paragraph(DB[k][0], CELLC),
                 Paragraph(f"{cov*100:.1f}%", CELLC), Paragraph(DB[k][1], CELLC),
                 Paragraph(REASON[k], CELLM)])
    if T[k] == 1:
        gr.append(n)
    if T[k] >= 3:
        wr.append(n)
table(rows, [9 * mm, 8 * mm, 36 * mm, 13 * mm, 13 * mm, 15 * mm, 88 * mm], good=gr, warn=wr)
P("绿底 = T1（两个面都有具体机制，第三面有正面排除理由）；红底 = T3/T4（有自相矛盾，不该双选，应全包或丢）。", SMALL)

story.append(PageBreak())

# ───────────────────────────── 逐场裁决
P("6 · 最终裁决：按「排除证据」选腿", H2)
P("<b>关键判据的修正</b>：双选赌的不是「哪一面会开」，而是<b>「哪一面不会开」</b>。"
  "因此选腿的标准不是覆盖率（那是市场衍生量），而是<b>被排除那一面的证据强度</b>。按此重排：")
story.append(Spacer(1, 3))
table([[Paragraph(f"<b>{h}</b>", CELLC) for h in ("等级", "定义", "本期场次")]] +
      [[Paragraph(a, CELLC), Paragraph(b, CELL), Paragraph(c, CELL)] for a, b, c in [
          ("A", "排除面在该对阵／该赛季<b>从未发生或极少发生</b>", "场 4 · 场 2 · 场 9 · 场 7 · 场 13 · 场 5"),
          ("B", "排除面有<b>多条独立基础率</b>证据", "场 10"),
          ("C", "排除面证据中等", "场 11"),
          ("D", "排除面证据<b>反向或缺失</b>——不可作为暴露腿", "场 12 · 场 6 · 场 3（及三条无方向的全包场 1 / 8 / 14）"),
      ]], [14 * mm, 82 * mm, 86 * mm], good=(1, 2), warn=(4,))
story.append(Spacer(1, 4))
P("<b>本票的构成原则：所有有敞口的腿必须是 A 或 B 级；说不出方向的场次用全包（无敞口，等级不适用）。</b>"
  "A 级 6 条 + B 级 1 条 = 7 条，补满 9 场需再加 2 个全包，<b>这直接决定了注数下限 576 注</b>。")
story.append(Spacer(1, 3))
table([[Paragraph(f"<b>{h}</b>", CELLC) for h in ("版本", "注数 / 金额", "全中概率", "回本门槛", "暴露腿最差等级")]] +
      [[Paragraph(a, CELL), Paragraph(b, CELLC), Paragraph(c, CELLC), Paragraph(dd, CELLC), Paragraph(e, CELLC)]
       for a, b, c, dd, e in [
           ("更省（384 注）", "384 注 / ¥768", "17.44%", "¥4,405", "<b>C</b>（含场 11）"),
           ("<b>本票</b>", "<b>576 注 / ¥1,152</b>", "<b>24.75%</b>", "<b>¥4,654</b>", "<b>全部 A / B</b>"),
           ("更稳（864 注）", "864 注 / ¥1,728", "33.85%", "¥5,105", "全部 A"),
       ]], [28 * mm, 32 * mm, 24 * mm, 24 * mm, 74 * mm], hi=(2,))
P("本票是<b>「每条暴露腿的排除证据都过硬」这个约束下的最省方案</b>。再往下砍到 384 注，必须让场 11 上场当第 8 条暴露腿，"
  "其排除证据（奥勒松客场 1 胜 2 平 3 负）只有 C 级；往上加到 864 注则用第三个全包换 9pp 命中率，但回本门槛升到 ¥5,105。", SMALL)
P("<b>EV 交叉点</b>：单注奖金 &gt; ¥5,119 时 576 注版优于 384 注版；&gt; ¥6,466 时 864 注版优于本票。", SMALL)

story.append(PageBreak())

# ───────────────────────────── 票面
P("7 · 票面与填票说明", H2)
P(f"<b>{codeline}</b>", BIG)
rows = [[Paragraph(f"<b>{h}</b>", CELLC) for h in ("场", "赛事", "对阵", "开球(北京)", "选项", "盖率", "角色")]]
hi = []
ROLE = {2: "偏移双选 −8.5pp", 4: "翻车场保险", 5: "★ 唯一单胆",
        7: "★共振双选（悬置夹心）", 8: "全包（top1 39.0%，全板最冷）", 9: "自产尾巴双选",
        10: "★共振双选（排除平有四证）", 13: "★共振双选（悬置夹心，风险包在双选内）",
        14: "全包（逻辑与模态相反）"}
for i in range(1, 15):
    lg, ko, h, a = META[i]
    pick = TICKET.get(i)
    if pick:
        m = fit[str(i)]["fair_had_euro"]
        mm_ = {"3": m["home"], "1": m["draw"], "0": m["away"]}
        cov = f"{sum(mm_[c] for c in dict.fromkeys(pick))*100:.1f}%"
        hi.append(i)
    else:
        cov = "—"
    rows.append([Paragraph(f"<b>{i}</b>", CELLC), Paragraph(lg, CELLM),
                 Paragraph(f"{h} vs {a}", CELL), Paragraph(ko, CELLM),
                 Paragraph(f"<b>{' '.join(pick)}</b>" if pick else "不选", PICKC),
                 Paragraph(cov, CELLC), Paragraph(ROLE.get(i, ""), CELLM)])
table(rows, [9 * mm, 13 * mm, 42 * mm, 22 * mm, 22 * mm, 15 * mm, 59 * mm], hi=hi)
story.append(Spacer(1, 4))
P("<b>选项对照：3 = 主胜　1 = 平局　0 = 客胜。</b>　任选九场只勾选上表 9 个高亮场次，其余 5 场留空。", BODY)
P("其中 <b>场 8 / 14 为三项全选</b>；<b>场 2 / 4 / 7 / 9 / 10 / 13 各勾两项</b>；<b>场 5 只勾「3」</b>。", BODY)
P("<b>合计 576 注 × 每注 ¥2 × 倍数 1 = ¥1,152。</b>", BIG)

hr()
P("8 · 风险、证伪条件与纪律声明", H2)
P("<b>本票最可能的死法</b>：① <b>场 5 单胆断腿</b>（本菲卡未取胜）——这是全票唯一没有结构保险的腿，"
  "且它是一次规则例外的产物（见第 4 节），风险最集中；② 六条双选中排除面最厚的是 <b>场 13（排除客胜 23.7%）</b>"
  "与 <b>场 10（排除平局 26.3%）</b>，两者的排除证据虽硬但概率质量最大；"
  "③ <b>三个悬置夹心（场 7、13、14）同时兑现「不可测」</b>——这是本期板面的系统性风险，四条悬置腿里本票占了三条。")
P("<b>出票前应复核</b>：本报告的盘口快照为 <b>2026-08-09 15:11</b>（09:18 首版已复核更新）。<b>复核结果</b>：六小时内经两种口径交叉验证、确认的位移仅 4 条——场 7 客胜 +1.7pp、场 14 客胜 +1.5pp、场 4 主胜 −1.4pp（跌破 80% 但未达 ≥2pp 重估阈值）、场 6 主胜 −1.0pp（加强其「互斥」判定，确认丢弃正确）。本票命中率由 24.93% 微调至 24.75%，<b>结构无需改动</b>。"
  "另注：荷兰、葡萄牙、北欧各联赛的官方首发普遍在开球前约 1 小时公布，<b>均晚于 20:00 截止</b>——"
  "该信息通道在出票前不可得，因此不得以「届时再看首发」为由压缩结构保险。")
P("<b>数据纪律</b>：本报告所有概率均来自国际 14–15 家即时均值去水 fair 与 Dixon-Coles 拟合（从去水 fair 反推 λ/ρ），"
  "为确定性算术，无口算成分；体彩盘因陈盘与单边砍价两项已排除在概率输入之外，仅用于总进球分布形状。"
  "赛果与结算只认官方开奖公告（lottery.gov.cn）、okooo 与 API-Football 交叉核验。", SMALL)
P("<b>免责声明</b>：以上为概率与结构分析，不构成收益承诺。任选九场为奖池均分制，单注奖金取决于当期中奖注数，"
  "事前不可知。彩票有风险，请量力而行、理性投注。", SMALL)

SimpleDocTemplate(str(OUT), pagesize=A4,
                  leftMargin=14 * mm, rightMargin=14 * mm,
                  topMargin=13 * mm, bottomMargin=12 * mm,
                  title="传统足彩 26102 期 · 完整推理路径与决策",
                  author="Nutmeg 决策本体").build(story)
print(f"→ {OUT}")
