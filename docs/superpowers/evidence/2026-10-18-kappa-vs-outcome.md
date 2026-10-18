# 两读 κ 与赛果的关系（2026-10-18，Jun 追问；首次结账，n=183）

**问题**：读者 B 与分析员的逐项一致性 κ（RULEBOOK「九」两读）能不能预测研究/系统的判断对不对。

**样本**：竞彩板 2026-10-05 → 10-17 共 13 天、183 场——每场同时有：两读侧车 `daily/<日>/rubric-<code>.json`（κ、读者 B 整体概率）、`reads.json`（系统 belief 与市场 prior）、`research-<code>.json`（表态面）、`jc-results.json` 90' 赛果。足彩独有场次与 10-18 未开场未入。脚本见本文末。

| 分层 | n | 系统−市场 Brier（95% CI） | 读者 B Brier vs 市场 | 表态面命中 vs 市场覆盖 | 拨动 ≥3pp：向赛果方向均值 / 正占比 |
|---|---|---|---|---|---|
| 全部 | 183 | +0.0035 ±0.0065 | 0.568 vs 0.540 | 59.6% vs 52.6%（+6.9pp ±7.1） | −0.72pp / 34/71 |
| κ < 0.5 | 6 | −0.040 ±0.046 | 0.668 vs 0.640 | 33% vs 52%（n=6） | +9.4pp / 2/2 |
| 0.5 ≤ κ < 0.7 | 40 | +0.011 ±0.016 | 0.493 vs 0.493 | 65.0% vs 54.0%（+11.0 ±14.8） | −1.17pp / 7/18 |
| 0.7 ≤ κ < 0.9 | 109 | +0.004 ±0.008 | 0.597 vs 0.558 | 59.6% vs 52.3%（+7.3 ±9.2） | −1.31pp / 18/39 |
| κ ≥ 0.9 | 28 | −0.002 ±0.014 | 0.540 vs 0.514 | 57.1% vs 52.1%（+5.1 ±18.3） | +0.17pp / 7/12 |
| 拨动 ≥3pp ∧ κ < 0.7 | 20 | +0.000 ±0.035 | — | 65.0% vs 50.9% | −0.11pp / 9/20 |
| 拨动 ≥3pp ∧ κ ≥ 0.7 | 51 | +0.009 ±0.017 | — | 54.9% vs 54.3% | −0.96pp / 25/51 |

相关系数：corr(κ, 系统−市场 Brier) = 0.02；corr(κ, 表态面命中) = −0.03。读者 B 模态面 ≠ 系统模态面的 24 场：开系统模态 10、开 B 模态 6、都不开 8。

**结论（n=183，两周，所有 CI 都含 0 或接近 0）**
1. κ 与判断对错**没有可测关系**：各层 Brier 差、表态面命中差都在噪声里，相关系数 ≈ 0。κ 高的拨动（≥0.7，n=51）平均反而离赛果 −0.96pp，κ 低的（n=20）−0.11pp——「两读一致的拨动更可信」不成立。
2. κ 量的是**研究的可读性**（分析员的答案能否从他写的证据里读出来），不是预测力。它该用在 K1（问题表是否可稳定作答、哪些项要重写）上，不该进「把握排序」。§3d 里把 κ 列进排序表是过度使用，已在表后注明只作可读性参考。
3. 顺带复核三条旧结论仍成立：系统 Brier ≈ 市场（+0.0035）；读者 B 整体概率比市场差（+0.028）；研究表态面集合命中 +6.9pp（F14 方向同、幅度比 10-05 的 +10.1 小，CI 下界 −0.2）；≥3pp 拨动的方向无边（34/71）。
4. 决策表「一致性」列（同向 / 中性 / 打架）是散文，没有对象化，无法回测。要检验「打架场更易翻车」，需先把它编码成因子（候选：研究 `strength_balance.verdict` 的方向 vs 近 5 轮积分率方向），走 F 系列登记，不在本文里嘴算。

**脚本**（可复跑）：
```
python3 - <<'PY'
import json,glob,os,math,statistics as st
D='.nutmeg-data'; res_all=json.load(open(f'{D}/jczq/jc-results.json')); rows=[]
for dd in sorted(glob.glob(f'{D}/jczq/daily/2026-10-*')):
    day=os.path.basename(dd)
    if day>='2026-10-18' or not os.path.exists(f'{dd}/reads.json'): continue
    reads=json.load(open(f'{dd}/reads.json')); rl=reads['reads'] if isinstance(reads,dict) and 'reads' in reads else reads
    rmap={r['code']:r for r in (rl if isinstance(rl,list) else rl.values())}; res=res_all.get(day) or {}
    for sc in glob.glob(f'{dd}/rubric-*.json'):
        code=os.path.basename(sc)[7:-5]; doc=json.load(open(sc)); kk=(doc.get('kappa') or {}).get('kappa')
        rd=rmap.get(code); rs=res.get(code)
        if kk is None or not rd or not rs or rs.get('ft_home') is None or not rd.get('prior'): continue
        out='home' if rs['ft_home']>rs['ft_away'] else ('away' if rs['ft_away']>rs['ft_home'] else 'draw')
        rp=f'{dd}/research-{code}.json'; face=(json.load(open(rp)).get('stance') or {}).get('face') if os.path.exists(rp) else None
        rows.append(dict(k=kk,bel=rd['belief'],pri=rd['prior'],out=out,face=face,bb=(doc.get('b') or {}).get('belief')))
PY
```
（分层统计与 Brier 定义见会话脚本；Brier = Σ(p_f − 1{f=out})²。）
