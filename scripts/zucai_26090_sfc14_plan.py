"""胜负彩 26090 判定汇总 + 任九选9丢5构造算术（禁嘴算, Phase 5）.

判定来自主循环 Claude 汇总 12 场并行 jczq-match-analyst 深研 + 2 场当日已研
（加摩/巴法），概率底座 = 26090-base.json（29家去水 fair / 500avg 去水）。
脚本只做确定性算术：组合数、注金、联合命中率。判断不烤进脚本。
"""
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
BASE = json.loads((ROOT / ".nutmeg-data/zucai/26090-base.json").read_text())

# (场次, 判定picks, 覆盖概率(fair口径,场9无盘用深研估75%), 信心, 一句依据)
# picks: '3'=主胜 '1'=平 '0'=客胜
JUDGMENTS = {
 1:  ("1/0", 0.282+0.514, 3, "摩洛哥120min旧腿+无正印9号,判1-1;丢加拿大爆冷(20.5%)"),
 2:  ("0",   0.796,       4, "法国满血4连胜13球,高温只压净胜球不压胜负"),
 3:  ("3/1", 0.519+0.257, 3, "巴西缺拉菲尼亚+帕奎塔,湿热+雷暴,挪威亢奋收反击→平被上调"),
 4:  ("3/1/0", 1.0,       2, "阿兹特克2240米海拔+墨四战全胜零封,英39%被环境重折→真硬币全包"),
 5:  ("0/1", 0.496+0.265, 4, "西班牙不足五成(对佛得角27射0进),葡守平拖加时是最优路径"),
 6:  ("3/1/0", 1.0,       2, "美缺Balogun停赛vs比利时124分钟旧腿,35/28/37诚实硬币全包"),
 7:  ("3",   0.703,       3, "阿根廷70%但埃及刚验证拖点球剧本;接受~20%平局暴露作胆"),
 8:  ("0/1", 0.429+0.295, 3, "哥伦比亚统治但低效+跨大陆飞行;瑞士原地温哥华——丢瑞士冷胜"),
 9:  ("3/1", 0.75,        3, "赛季中冰岛冠军伏击季前杰尔(新帅3周);首回合客队求平即达标"),
 10: ("3/1/0", 1.0,       2, "哥德堡本季主场0胜+最烂防线,42%是主场标签虚抬→真硬币全包"),
 11: ("3",   0.620,       3, "卡尔马主场堡垒vs厄格里特客场9场不胜漏成筛;中等胆"),
 12: ("0/1", 0.484+0.257, 4, "埃尔夫斯堡缺头号中锋Frick+中卫停赛,但它是平局机器→哈胜或平"),
 13: ("0/1", 0.432+0.275, 4, "BP头号射手Hansen停赛,薄锋线啃最稳防线→盖斯胜或平"),
 14: ("1/0", 0.256+0.360, 3, "赫根门将+主力中卫双伤+对佐6战0胜+50%平局率→非主胜"),
}

print("== 胜负彩26090 · 14场判定 ==")
for no, (picks, p, conf, why) in JUDGMENTS.items():
    m = BASE[str(no)]
    f = m['fair']
    fs = "主{:.0%}/平{:.0%}/客{:.0%}".format(*f) if f else "无盘"
    print(f" {no:>2} {m['match']:<14s} [{fs}] → {picks:<6s} 覆盖{p:.0%} 信心{conf} | {why}")

# ---- 任九 选9丢5 ----
DROP = [4, 6, 10, 8, 14]  # 丢:三场真硬币全包场+瑞哥(判读与市场热门方向冲突=分歧即丢)+赫根(硬币)
KEEP = [n for n in JUDGMENTS if n not in DROP]
combos = 1
p_joint = 1.0
for n in KEEP:
    picks, p, _, _ = JUDGMENTS[n]
    k = len(picks.split("/"))
    combos *= k
    p_joint *= p
stake = combos * 2
print(f"\n== 任九·选9丢5 ==")
print(f" 保留: {KEEP}")
print(f" 丢弃: {DROP}（三场真硬币 + 瑞哥判读与市场方向冲突 + 赫根硬币）")
print(f" 注数 {combos} 注 × ¥2 = ¥{stake} | 九场联合命中率(程序算) {p_joint:.1%}")

# ---- 14场单式 评判员票 ¥2 ----
SINGLE14 = {1:"1",2:"0",3:"3",4:"3",5:"0",6:"1",7:"3",8:"1",9:"3",10:"0",11:"3",12:"1",13:"0",14:"1"}
p14 = 1.0
probmap = {"3":0, "1":1, "0":2}
for n, pick in SINGLE14.items():
    f = BASE[str(n)]['fair']
    p14 *= (f[probmap[pick]] if f else 0.40)
print(f"\n== 14场单式·评判员纯判读票 ¥2 ==")
print(" 票面: " + " ".join(f"{n}:{p}" for n, p in SINGLE14.items()))
print(f" 全中概率(fair口径,场9按40%) {p14:.6%} —— 纯彩票,博一等奖叙事")

out = {"issue": "26090", "judgments": {str(k): {"picks": v[0], "cover": v[1], "confidence": v[2], "reason": v[3]} for k, v in JUDGMENTS.items()},
       "renjiu": {"keep": KEEP, "drop": DROP, "combos": combos, "stake": stake, "p_joint": round(p_joint, 4)},
       "single14": SINGLE14}
(ROOT / ".nutmeg-data/zucai/26090-judgment.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("\nWROTE .nutmeg-data/zucai/26090-judgment.json")
