# 巴列卡诺 vs 阿拉维斯跨渠道深研

截止时间：2026-08-20 16:11（Asia/Shanghai）
比赛身份：体彩周四002；北京时间 2026-08-21 03:00；`M-2026-08-20-巴列卡诺-阿拉维斯`；API-Football fixture `1570351`。

## 判决摘要

| 轴 | canonical prior | 判决 | conf | 表达边界 |
|---|---:|---|---:|---|
| HAD | 主 41.519 / 平 31.439 / 客 27.043 | `belief=prior`，动作降格 | 2 | `venue_anomaly` 为无方向性旗，必须全包或丢；竞彩侧空仓 |
| TTG | 2球 27.228%，0-2球 62.656% | 真实 TTG Read，仍跟市场 | 3 | 2球模态；1-3球带 70.160%；不把小球等同于平局 |

当前没有达到净偏移 `5pp` 的未定价实名信息，故两条 Read 均为 `factors=[]`。最重要的新结论不是预测哪一面，而是确认普通主场先验失效：比赛在临时场地 Butarque 举行，Rayo 曾申请延期，客队球迷票也未能正常发放。该结构只证明结果更难测，不能替我们指定平或客。

本轮只落 Read，不创建 legs、不运行 `decision-close`、不推送。

## 跨渠道继承与冲突裁定

传统足彩 `26107` 场14已经判过同一场，但其旧 Match ID 为缩写身份 `M-2026-08-21-巴列卡-阿拉维`；竞彩 store 使用完整队名和体彩业务日。两者是同一 fixture，本场显式继承旧机理，避免两层独立判读。

| `26107` 机理 | 当前裁定 | 原因 |
|---|---|---|
| `venue_anomaly` | **继承并转强确证** | Rayo 官方确认 Vallecas 的许可被拒、若比赛举行则改到 Butarque；Leganés 官方确认只为这一个主场提供场地；Alavés 官方确认赛前仍未拿到客队球迷票 |
| `self_made_tail` | **撤销为 note，不再挂旗** | 旧低产/高平机制主要依赖 Vallecas 主场样本；本场不在 Vallecas，新帅第二场且后防拼接，不能把低分机制继续解释成指向平 |
| 锚方完整度 FAIL | **继承** | 首轮由 Balliu 客串左后卫、后腰 Ciss 客串中卫；Kumbulla 仍在恢复，主帅又公开把左后卫列为补强优先位 |
| Alavés 低产绞局 | **不继承** | 揭幕战 3:0 已强烈质询旧叙事；但对手 42 分钟红牌、两球出现在补时，也不能反向升级为高产因子 |

这个跨渠道链接目前依靠 fixture、队名和开球时间人工确认；缩写 Zucai Match ID 与竞彩 canonical Match ID 不同，属于后续身份治理需要持续审计的风险。

## 市场与钱流

16:11 的 14 家国际欧赔去水 fair 为主 `41.519%`、平 `31.439%`、客 `27.043%`；体彩为主 `43.640%`、平 `31.193%`、客 `25.167%`。两源同为主胜模态，最大差 `2.12pp`，低于反向 `3pp` 的 `source_disagreement` 门槛。

从 08:00 到 16:11：

- 国际主面 `-0.12pp`、客面 `+0.29pp`；
- 体彩主面 `-0.43pp`、客面 `+0.42pp`；
- 没有方向翻转，也没有与实名催化剂对应的急动。

因此，Butarque、Rayo 后防重组和 Alavés 阵容恢复均属于市场已经有机会定价的公开信息。它们决定保险结构，不授权移动 belief。

## 球队状态与磨合

### 巴列卡诺

- 首轮客场 1:2 负 Sevilla，51% 控球、6 射3正。两个失球均来自点球，不能把比分直接解释为开放防线；但仅6次射门也不足以把早段进球写成稳定攻击升级。
- 首发为 `Batalla；Ratiu、Lejeune、Ciss、Balliu；Valentín、Unai López；de Frutos、Isi、Álvaro García；Nteka`。Ciss 从后腰移到中卫、Balliu 从右侧移到左后卫，说明防线的当期连续性弱于纸面名单连续率。
- Beñat San José 赛前确认 Kumbulla 仍有不适，处于医疗、理疗和场地训练交替恢复；Tsitaishvili 接近进入名单。主帅同时明确左后卫仍是补强优先位。
- 旧 `26105` 的 Chavarría、Mendy 离队机理仍能解释为何首轮必须拼接防线，但这些转会已公开且已被首轮阵容验证，权重为 `0pp`。

### 阿拉维斯

- 首轮主场 3:0 胜 Getafe，18 射8正；Getafe 在42分钟被罚下一人，Alavés 的三个进球出现在73、90+1、90+4分钟。结果证明攻击通路活着，但不能把十打十一和补时反击机械外推到本场。
- 首发 3-5-2 的门将、中卫、后腰骨架为 `Sivera；Tenaglia、Koski、Jonny；Antonio Blanco、Pablo Ibáñez`，当前没有证据显示这条轴被击穿。
- Quique Sánchez Flores 确认 Boyé 是短期伤后恢复，Valentini 已可用但此前较长时间未跟队合练；球队有足够人员组成名单。Boyé、Mariano、Toni Martínez 的竞争提升了前锋选择，但首发与分钟仍待确认。
- `26105` 中“阿拉维斯锋线被掏空”的旧假设已被 Mariano 一球两助和 Mikel Rodríguez 替补破门反证；正确动作是撤销判死，而不是追一场 3:0 的 form。

## 场地异常

Rayo 官方称，马德里自治区在 8 月17日拒绝解除 Vallecas 的暂停措施，俱乐部随后正式向 LaLiga 申请延期；若被迫比赛，则启用与 Leganés 达成的 Butarque 协议。Leganés 官方也明确，这次借场只针对 Rayo 本季第一个联赛主场。Alavés 官方赛前仍在等待客队球迷票信息，Rayo 随后解释安全申报期限已使客队票无法正常发放。

这同时改变了四个普通主场条件：熟悉场地、固定入场流程、主客球迷构成、赛前准备稳定性。按 SOP 它属于无方向性 `venue_anomaly`：

- 不能把 Rayo 上季 Vallecas 主场 `7-10-2` 的高平样本平移到 Butarque；
- 也不能简单把失去主场等价为给 Alavés 加分，因为客队同样经历临时票务和赛程协调；
- 唯一强制动作是方向轴降格，全包或丢整场。

## 五玩法

| 玩法 | 判读 |
|---|---|
| HAD | 跟国际锚 `41.519 / 31.439 / 27.043`，但 top1<45% 且有无方向旗，动作必须降格；不得给主、平、客任何单选牌照 |
| HHAD(-1) | 体彩让负 `54.975%` 为模态，只说明 Rayo 净胜2球以上并不集中；不能把它改写成 Alavés HAD 不败判断 |
| TTG | 体彩2球 `27.228%` 为模态，1-2球 `50.620%`、0-2球 `62.656%`；11家国际小2.5为 `63.066%`，两源收敛 |
| 比分 | `1:0` 13.10%、`1:1` 12.45%、`0:0` 10.82%、`2:0` 9.34%、`0:1` 9.05%；只保留低比分簇，不署名单点 |
| 半全场 | 场地和方向不确定性会放大路径分叉，当前无足够集中面，回避 |

TTG 是相对清楚的轴，但仍只跟市场。支持小球的是两场揭幕战的名义比分都被点球/红牌/补时事件放大，且市场双源收敛；反证是 Rayo 拼接防线以及 Boyé 回归、Mariano 状态通路。两边机制都活，所以不移动 TTG 分布，只把 conf 定为3。

## 尾巴旗与动作

- **无方向旗：** `venue_anomaly`，确证；方向轴强制降格。
- **不挂 `source_disagreement`：** 两源同模态，最大差2.12pp。
- **不挂 `anchor_shield_out`：** Rayo 防线确实拼接，但尚无证据表明既有后腰屏障实名缺阵；Ciss 的位置移动进入完整度 FAIL，不伪装成指向平的旗。
- **不挂 `self_made_tail`：** 旧机制载体是 Vallecas，本场场地和教练 regime 都变了。
- **不额外挂 `two_way_instability`：** 当前已由更具体的场地异常覆盖不可测来源，避免对同一不确定性重复计数。
- **动作：** HAD `降格`；TTG `跟市场`。固定赔率渠道优先空仓，奖池均分渠道如必须纳入只能全包。

## 临场触发器

1. 若官方场地再次翻回 Vallecas，立即撤销 `venue_anomaly` 并重开 HAD；当前官方口径下不得提前假设翻转。
2. 若 Kumbulla 首发，Rayo 后防从“客串双点”转为“新援首次组合”，完整度仍不能直接升为 PASS；若 Ciss 继续中卫、Balliu继续左后卫，则 FAIL 维持。
3. 若 Boyé 与 Mariano 同时首发，或 Rayo 再新增后场缺阵，重新检验 TTG 的3球尾部；若 Alavés 只留单前锋且 Rayo 恢复自然中卫组合，小球结构加强。
4. 若名单公布后国际 HAD 任一面出现有实名催化剂的 `>=3pp` 移动，重开方向 Read；无催化剂不反市场。
5. 若国际小2.5从63.07%跌至55%以下，或体彩0-2球带明显失去一致性，撤销当前 TTG conf3。

## 主要证据

- Rayo 场地官方说明：<https://www.rayovallecano.es/noticias/comunicado-oficial-rayo-alaves>
- Rayo 客队票官方说明：<https://www.rayovallecano.es/noticias/comunicado-oficial-entradas-rayo-alaves>
- Leganés 借场官宣：<https://www.cdleganes.com/el-cd-leganes-cede-el-ontime-butarque-al-rayo-vallecano-para-su-primer-partido-de-liga-como-local>
- Alavés 最终客队票公告：<https://www.deportivoalaves.com/es/noticias/comunicado-oficial-deportivo-alaves-2>
- Alavés 官方赛前人员说明：<https://www.deportivoalaves.com/es/noticias/seguir-sumando-1>
- Rayo 主帅赛前发布会转录：<https://www.futbolfantasy.com/laliga/noticias/149253-benat-san-jose-lamenta-la-situacion-en-la-que-vive-el-club-y-habla-de-mariano-tsitaishvili-ku>
- Alavés 主帅赛前发布会转录：<https://www.futbolfantasy.com/laliga/noticias/149254-quique-explica-como-llega-el-equipo-y-habla-de-angel-perez-mariano-blanco-boye-mikel-rodrigue>
- Alavés 赛前训练与可用名单：<https://www.futbolfantasy.com/laliga/noticias/149257-boye-completa-otra-sesion-recuperado-antes-de-viajar-a-butarque>
- Sevilla vs Rayo 正式比赛数据：<https://site.api.espn.com/apis/site/v2/sports/soccer/esp.1/summary?event=401882918>
- Alavés vs Getafe 正式比赛数据：<https://site.api.espn.com/apis/site/v2/sports/soccer/esp.1/summary?event=401882926>

正式 Read 文件：`.nutmeg-data/jczq/daily/2026-08-20/rayo-alaves-reads.json`。
