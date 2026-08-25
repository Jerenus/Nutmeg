# 西甲、法乙、荷乙三场优先比赛深研

截止时间：2026-08-20 15:55（Asia/Shanghai）
比赛日口径：体彩 `2026-08-21` 板面，实际开球均为北京时间 2026-08-22。

## 判决摘要

| 场次 | canonical HAD prior | 动作 | conf | 尾巴旗 | 锚方完整度 | 判断密度 |
|---|---:|---|---:|---|---|---|
| 周五007 敦刻尔克 vs 蒙彼利埃 | 37.00 / 28.46 / 34.54 | 方向轴降格 | 2 | 无 | 非 clean PASS | TTG 2-3 球，仍跟市场 |
| 周五008 登博思 vs 埃因FC | 46.60 / 25.04 / 28.36 | 跟市场主 | 3 | 无 | 非 clean PASS | TTG 3 球、2-4 球带 |
| 周五011 贝蒂斯 vs 皇家社会 | 45.49 / 28.07 / 26.44 | 跟市场主 | 2 | 无 | 勉强 PASS，按 FAIL | HAD 主+平保护 |

三场都没有达到净偏移 `5pp` 的实名、未定价信息，因此全部 `belief=prior`、`factors=[]`。这不是没有判断，而是把市场锚、结构风险和表达边界分开：周五007的方向本身不可分，周五008和011只有边际主胜模态，三场均不具备裸单牌照。本轮只落 Read，不生成 legs、不运行 `decision-close`、不推送。

## 数据复核与传导

- 15:51 重跑 `decision-am` 后，三场 API-Football fair 与 14:42、15:21 两次抓取完全一致；当前没有可识别的同日方向钱流。
- 三场均未找到相同 `match_id` 的传统足彩 judgment 或既有真实 Read，因此没有必须继承的同场机理。
- 旧 `26104` 的 Montpellier 判断只作为待证伪假设：Tardieu 已恢复合练并具备进名单条件，Everson 已在客战 Nancy 进入替补席，“双后腰同时缺阵”的前提已失效。
- 修正两处早期备料中的主客比分方向：Montpellier 上轮是客场 `1:0` 胜 Nancy；FC Eindhoven 上轮是主场 `2:3` 负 MVV。
- `Match.kickoff_at` 仍错误沿用 Snapshot 的 `taken_at`；本报告只用体彩编号、原始赛程和外部 fixture/event ID 识别比赛。

## 统一状态比较

| 球队 | 当前正式赛骨架 | 可用性与磨合 | 攻击通路 | 防守/失控风险 |
|---|---|---|---|---|
| 敦刻尔克 | 前两轮首发重叠 10/11，连续 4-2-3-1 | 体系最连续；Nzonzi 尚未进入既有首发基线；Touré 8月17日刚加盟 | Robinet、Lebeau、Prutsev、Daho 与高位回收后的二次进攻 | 主帅公开承认防守协调仍需改善；若 Touré 直接首发，形成新组合 |
| 蒙彼利埃 | 前两轮首发重叠 9/11，4-3-3 转 4-4-2 | Tardieu 可回名单、Everson 已回替补；Chennahi、Mamadou Camara 缺阵 | 两轮累计 40 射；Nancy 一战已兑现抢断后纵深反击 | 中卫 Laporte-Mouanga 连续，主要不确定性在中场组合和前场终结 |
| 登博思 | 前两轮首发重叠 10/11 | 低注册连续率没有兑现成当期大轮换；Jack de Vries 待确认 | Monzialo 推进、Felida/De Corte 输送、Karlsson Grach 终结 | 客战 Heracles 被压出 30 射17正；仍是新帅、新控制中轴 |
| 埃因FC | 前两轮首发重叠 10/11，连续 4-4-2 | Poortvliet 与 Van Veen 的两场禁赛结束；Van Veen 是否出场待名单 | 封传球线后反击、双前锋/高点、定位球与二点 | 对 MVV 在 90'、90+3' 连丢两球；单场不足以挂结构旗 |
| 贝蒂斯 | 本季联赛首战，沿用上季主场强势骨架 | Bellerín 8月19日恢复合练；Abde 正常合练但无季前分钟；Ruibal缺阵，Lo Celso/Petit待名单 | Fornals/Isco 连接，边路宽度与 Cucho 禁区终结仍在 | 部分右路与轮换点状态不满，完整度只能给“勉强” |
| 皇家社会 | 本季联赛首战，主轴连续性高于贝蒂斯 | Guedes/Gorrotxategi 已恢复合练但当地记者预计不随队；Pacheco可能入选，非官宣 | Kubo、Barrenetxea 与 Oyarzabal/Óskarsson 保留转换和纵向攻击 | 上季客场 3-8-8，平局通道长期存在；当前最终名单仍未知 |

近两轮比分、排名和射门只用于识别机制，按 SOP 均为 `0pp`；战意也只是第3轮/揭幕战的正常联赛动力，没有 must-win、轮换或旅行差异。

## 周五007：敦刻尔克 vs 蒙彼利埃

### 实力、战术与状态

Dunkerque 连续两轮约六成控球，累计 32 射15正、19个角球，攻击并不只依赖单一中锋；但两场丢5球来自对手合计仅6次射正，高比分同时包含对手终结率放大，不能把 `4:2 / 3:3` 直接外推为必然大球。俱乐部长样本显示其此前22场仅2次零封，主帅又承认防守协调仍需改善，因此开放风险真实存在，但属于市场已知画像。

Montpellier 首轮对 Dijon 27射6正、1:1，次轮客战 Nancy 13射4正、1:0；Tardieu 与 Everson 的回归推翻旧“双后腰伤缺”假设，Laporte-Mouanga 门将/中卫骨架连续。Chennahi 和 Mamadou Camara 的缺阵会压缩中前场选择，但球队已有 Ayem、Meddah、Megnan、Issoufou 等替代通路，证据不足以把客队结构判死。

### 五玩法

| 玩法 | 判读 |
|---|---|
| HAD | top1 仅37.00%，主客只差2.46pp；方向轴降格，空仓或全包，不造伪方向 |
| HHAD(-1) | 让负59.82%为模态，即Dunkerque难以净胜2球；不等同于客队HAD不败的新信息 |
| 比分 | 1:1为模态11.67%；1:0、2:1、1:2均是相邻活分支 |
| TTG | 2球24.09%、3球22.46%，2-3球带46.55%；国际大2.5仅50.43%，不强判大小 |
| 半全场 | 主/主、客/客、平/平均无足够集中度，回避 |

尾巴旗为无。Dunkerque 没有既有防守中轴的实名缺阵，故不挂 `anchor_shield_out`；Touré 若立即首发只是临场新组合触发器。该场落 HAD 与 TTG 两条真实 Read，均不偏移。

## 周五008：登博思 vs 埃因FC

### 实力、战术与状态

上季 Den Bosch 主场 `8-6-5 / 35-27`，FC Eindhoven 客场 `5-2-12 / 18-39`，支持主队纸面略优。当前首发层却比注册名单 proxy 稳定得多：两队前两轮都只换1名首发，因此不能用“跨季名单连续率低”机械挂 `two_way_instability`。

FC Eindhoven 的公开禁赛信息是本场最关键的实名事实：俱乐部5月1日宣布 Kevin van Veen 缺席接下来两场、Jan Poortvliet 禁赛两场；8月10日又明确 Theo Lucius 只代班首两轮。因此本场主帅确定复位，Van Veen恢复资格但是否出场待确认。消息公开已久，能够解释国际锚比体彩少给主队4.32pp，却不构成新的未定价偏移。

战术上，Den Bosch 的主动进攻、边路推进和禁区终结面对 Eindhoven 的4-4-2封线与反击；反面是客队高点、传中和定位球正好质询主队上轮暴露的禁区保护。双方一周一赛，无体能或旅行差。

### 五玩法

| 玩法 | 判读 |
|---|---|
| HAD | 跟市场主46.60%，但 conf3、fair<60%、完整度非clean PASS，禁止单选；canonical第二面是客28.36%，不是平 |
| HHAD(-1) | 让负47.63%为模态，让平23.32%；让胜仅29.05%，不满足打穿共振 |
| 比分 | 2:1为模态9.96%，1:1和1:2是主要反分支 |
| TTG | 3球23.07%，2-4球带60.62%；国际大2.5 fair 62.31%，是本场较清晰的轴 |
| 半全场 | 胜/胜赔率2.72为市场模态，平/胜是迟破分支；无新增信息，不做单关 |

国际和体彩均以主胜为模态，因此4.32pp差不是 `source_disagreement`；Poortvliet/Van Veen恢复又是可命名催化剂。尾巴旗为无，动作是跟市场，不翻面。落 HAD 与 TTG 两条真实 Read，均保留 prior。

## 周五011：贝蒂斯 vs 皇家社会

### 实力、战术与状态

Betis 上季西甲第5且主场 `10-6-3 / 34-19`，Real Sociedad第10且客场 `3-8-8 / 22-30`，所以主胜是合理模态；但45.49%离单选很远，Sociedad 的8个客场平局又让1:1机制保持活性。

Betis 8月19日训练信息确认 Bellerín 回归合练、Abde连续正常训练但没有季前分钟，Lo Celso、Petit、Conde、Ruibal 当天仍单独训练；API-Football将 Conde、Ruibal列为缺阵，Lo Celso、Petit列为存疑。主力门将、中卫、后腰、连接与终结链目前没有被证实同时断裂，因此不挂结构旗，但完整度只能是“勉强 PASS”，按单选规则视同 FAIL。

Sociedad 侧的 Guedes、Gorrotxategi 已恢复合练，但当地记者预计二人不随队，Pacheco有入选可能；这些不是官方名单，不能当既成事实。对 Chelsea 的友谊赛 17射4正只说明低控球下的直接攻击机制仍活，仍是 `0pp` form。La Cartuja 自2025-26起就是 Betis 的长期临时主场，不是本场临时改场，故不挂 `venue_anomaly`。

### 五玩法

| 玩法 | 判读 |
|---|---|
| HAD | 跟市场主45.49%；若仅描述防守结构，主+平73.56%，不裸主 |
| HHAD(-1) | 让负54.66%为模态；让胜21.08%，明确禁止打穿表达 |
| 比分 | 1:1为联合模态11.50%，主胜分支2:1、1:0 |
| TTG | 2球23.73%、3球22.75%，国际小2.5 fair 52.53%；只保留市场shadow，不造真偏移 |
| 半全场 | 胜/胜原始赔率3.25为模态，平/胜5.20是迟破分支；conf2不进入表达 |

尾巴旗为无；动作跟市场，`belief=prior`。只落 HAD Read，TTG 继续保留 shadow。

## 对抗验证后的最终边界

1. **周五007最弱的是方向本身。** 主客锚接近且大小球也五五开；正确动作是承认不可分，而不是把Dunkerque两场高比分升级成大球因子。
2. **周五008最容易误读4.32pp跨源差。** 两源没有反向，而且存在主帅/中锋禁赛结束的公开催化剂；不能挂无方向性分歧旗，也不能假装成临场钱流。
3. **周五011最容易把“Betis主场更强”写成胆。** 45.49%主锚、Sociedad客场高平和Betis若干恢复/存疑点共同否决裸主，但没有一条达到5pp的未定价证据许可翻面。
4. 三场均没有达到 `fair>=60% + 零方向旗 + 锚方clean PASS` 的单选三条件；也没有 `fair>=70% + 方向旗` 的翻车场候选。
5. 当前没有 legs。若之后要出票，必须先按最新名单重跑市场、更新 Read，再单独执行 `decision-audit-legs`；本报告不能直接充当票面授权。

## 截止前触发器

- 敦刻尔克：Nzonzi是否意外首发；Touré是否直接进入后防；Montpellier的Tardieu/Everson是否同时首发，Chennahi/Mamadou之外是否再减员。
- 登博思：Van Veen是否进入名单/首发；Jack de Vries是否回归；Den Bosch门将、中卫、后腰是否新增缺阵；国际锚是否出现主客模态翻转。
- 贝蒂斯：Bellerín能否入选；Lo Celso/Petit最终状态；Betis防守/出球中轴是否新增缺阵；Sociedad的Guedes/Gorrotxategi/Pacheco官方名单。
- 所有比赛：若名单发布后国际 fair 有实名催化剂驱动的 `>=3pp` 移动，重开相应 Read；未验证的首发通道不能当免费保险。

## 主要证据

- Dunkerque vs Grenoble：<https://site.api.espn.com/apis/site/v2/sports/soccer/fra.2/summary?event=401876797>
- Reims vs Dunkerque：<https://site.api.espn.com/apis/site/v2/sports/soccer/fra.2/summary?event=401876783>
- Nancy vs Montpellier：<https://site.api.espn.com/apis/site/v2/sports/soccer/fra.2/summary?event=401876785>
- Montpellier 赛前人员与 Tardieu：<https://www.midilibre.fr/2026/08/19/dunkerque-mhsc-un-adversaire-redoutable-un-style-qui-commence-a-etre-reconnu-zoumana-camara-sattend-a-un-match-difficile-dans-le-nord-13514785.php>
- Dunkerque 官宣 Touré：<https://www.usldunkerque.com/ousmane-toure-rejoint-lusl-dunkerque-en-pret/>
- Den Bosch vs Almere：<https://site.api.espn.com/apis/site/v2/sports/soccer/ned.2/summary?event=401875989>
- Heracles vs Den Bosch：<https://site.api.espn.com/apis/site/v2/sports/soccer/ned.2/summary?event=401875982>
- Eindhoven vs MVV：<https://site.api.espn.com/apis/site/v2/sports/soccer/ned.2/summary?event=401875983>
- Eindhoven 禁赛官宣：<https://fc-eindhoven.nl/schorsingen-voor-van-veen-en-poortvliet-na-derby/>
- Eindhoven 首两轮代班确认：<https://fc-eindhoven.nl/theo-lucius-hoofdtrainer-bij-eerste-competitieduels/>
- Betis 8月19日训练：<https://www.futbolfantasy.com/laliga/noticias/149230-bellerin-vuelve-al-grupo-y-abde-repite-con-normalidad>
- Sociedad 8月19日人员报道：<https://www.futbolfantasy.com/laliga/noticias/149287-noticias-de-gipuzkoa-cree-que-guedes-y-gorrotxategi-no-iran-convocados>
- Sociedad vs Chelsea：<https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary?event=401900324>
- Betis La Cartuja 官方说明：<https://www.realbetisbalompie.es/club/la-cartuja>

正式 Read 文件：`.nutmeg-data/jczq/daily/2026-08-21/judgment-reads.json`。

## 纠错说明（2026-08-21）

本档案原文两处需更正，均在 26108 逐场深研中被独立复核推翻：

1. **敦刻尔克失球数据（承重）**：原文「本季 5 个失球来自对手仅 6 次射正」**错误**。实测为 **12 次射正丢 5 球（41.7% 转化）**——原数字把单场射正数（6）与两场进球总数（5）配成了一对。该更正改变归因方向：83% 的转化率会指向「门将崩了或极端霉运」，41.7% 只是略高于联赛均值（30-33%），归因是**结构性**（禁区盯人 / 定位球二点球 / 转换防守），不是门将。MD1 对格勒诺布尔是 0.61 xG 打进 2 球（方差，不构成结构证据），MD2 对兰斯是 3 次绝佳机会进 3 球（真实）。来源：footmercato MD1/MD2 逐场数据、fotmob matchfacts。
2. **埃因FC 补时失球定性**：原文判「对 MVV 在 90'、90+3' 连丢两球，单场不足以挂结构旗」**已被推翻**。用 ESPN 逐场事件重算 2025-26 全季 38 场后：埃因 **63.6% 的失球集中在下半场（42/66）、90'+ 补时失 9 进 3（净 −6）**，而登博思上下半场几乎对半、补时净 **+1**；且 Poortvliet 自 2025 年 10 月接手后带完整季并续约至 2027，样本大部分在现任教练治下，画像可传导。⇒ 属**结构，非单场事故**。

另补两条截止前已兑现的触发器：Poortvliet 主帅确定复位（官方原文 Lucius 只带 "vanavond en vrijdag" 两场；8/20 15:22 官方前瞻已改写为 "De ploeg van Jan Poortvliet"）；Van Veen 解禁归队（ED.nl 8/20 14:30）。登博思 Jack de Vries 8/08 第 33 分钟伤退、MD2 首发与替补席全无、无复出公告。

本档案状态自 2026-08-22 赛后起转为 `historical`。
