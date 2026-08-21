# 2026-27 英超开幕轮动态情报日志

**资料截止：** 2026-08-20（Asia/Shanghai）
**用途：** 记录开幕轮探索成熟度、待核问题与来源；不是 Team 画像副本，不是比赛 Read，
不产生自动方向、置信度或票面结论。可复用事实仍以 `League` / `Team.profile_notes` 为准，
当场因素必须在 Match/Snapshot/Read 链路中重新核验。

## 1. 已执行的原生记录

- `decision-am --run-date 2026-08-21` 已执行：体彩 20 场、国际欧赔 6 场，sense 入库 11 场，
  backfill 21 条市场基线 shadow。
- 英超当前只有 Arsenal-Coventry 进入体彩板面；实体别名命中，Match 已挂
  `eng-premier`、`eng-arsenal`、`eng-coventry-city`。
- 该场当前只有让球胜平负（Arsenal -2）、总进球和比分；没有普通胜平负，也没有国际欧赔
  fair 锚，因此不能由现有 Snapshot 推导完整 90 分钟方向先验。
- 已额外试跑 `2026-08-22`、`23`、`24`：三天均 sense `0` 场、欧赔 `0` 场，说明当前公开
  板面尚未发布其余 9 场；继续等待后续 `decision-am`，不提前造 Match。

### 运行时字段注意

当前 `decision-sense` 将 `Match.kickoff_at` 写成 Snapshot 的 `taken_at`，不是官方开球时间；
Arsenal-Coventry 在 store 中因此显示 `2026-08-20T14:42:08+08:00`，官方开球实际为
`2026-08-22 03:00` 北京时间。现阶段按 `match_id`、channel ref 与官方 fixture id 识别比赛，
不得用 `kickoff_at` 做赛程排序或发布时间判断。修正该字段属于决策代码任务，本次研究不越权改代码。

## 2. 官方开幕轮边界

来源：Premier League football API，competition `1`、season `841`、gameweek `1`。

| 北京时间 | 对阵 | 官方 fixture id |
|---|---|---:|
| 2026-08-22 03:00 | Arsenal - Coventry City | 128923 |
| 2026-08-22 19:30 | Hull City - Manchester United | 128926 |
| 2026-08-22 22:00 | Everton - Crystal Palace | 128925 |
| 2026-08-22 22:00 | Ipswich Town - Sunderland | 128927 |
| 2026-08-22 22:00 | Nottingham Forest - Leeds United | 128928 |
| 2026-08-23 00:30 | Brentford - Tottenham Hotspur | 128924 |
| 2026-08-23 21:00 | Brighton & Hove Albion - Aston Villa | 128929 |
| 2026-08-23 21:00 | Manchester City - Bournemouth | 128930 |
| 2026-08-23 23:30 | Newcastle United - Liverpool | 128931 |
| 2026-08-25 03:00 | Fulham - Chelsea | 128932 |

## 3. 情报覆盖成熟度

| 层 | 当前覆盖 | 判读含义 |
|---|---:|---|
| 官方赛程/20 队身份 | 10/10 场、20/20 队 | 已锁定 |
| 官方伤停汇总（更新 8/19） | 20/20 队 | 仍需赛前发布会区分 out/doubt/available |
| 确认转会追踪（更新 8/19） | 20/20 队 | 关窗前持续变化 |
| 全队赛季预览/媒体排序 | 20/20 队 | 只作舆论基线，不作事实裁决 |
| 可靠预计首发 | 7/20 队 | 其余球队不猜首发 |
| 升班马专项报道 | 3/3 队 | 已覆盖 Coventry/Ipswich/Hull |
| 体彩市场 | 1/10 场 | Arsenal-Coventry 仍缺 HAD |
| 国际欧赔 fair 锚 | 0/10 场 | 当前禁止声称完整市场共识 |
| 正式 2026-27 比赛样本 | 0/20 队 | 不用季前胜负替代正式样本 |

## 4. 舆论基线与偏差雷达

ESPN 8/19 的单一媒体排序为：Arsenal、Manchester City、Chelsea、Liverpool、
Manchester United、Brighton、Tottenham、Brentford、Aston Villa/Newcastle、Bournemouth、
Nottingham Forest、Everton、Leeds、Crystal Palace、Fulham、Sunderland、Coventry、Ipswich、Hull。

与 2025-26 联赛名次比较，最明显的叙事变化是：

- **上调最大：** Tottenham `17 -> 7`、Chelsea `10 -> 3`、Forest `16 -> 12`、
  Newcastle `12 -> 并列9`。共同风险是换帅、换轴或核心离队，属于“人才/投入乐观先于协同证据”。
- **下调最大：** Sunderland `7 -> 17`、Villa `4 -> 并列9`、Bournemouth `6 -> 11`、
  Fulham `11 -> 16`。主要理由分别是过程回归、阵容缺口、主帅流失和高龄重构。
- **排序稳定：** Arsenal、Manchester City、Everton、Leeds、Crystal Palace。

这是媒体分析师的一份排序，不是市场共识。正确用途是定位“公众叙事最拥挤”的球队，随后用
首发、结构完整度与 closing money flow 质询；不得直接反买或追买。

## 5. 十场结构探索

| 对阵 | 当前结构证据 | 开赛前必须核验 |
|---|---|---|
| Arsenal-Coventry | Arsenal 稳定冠军框架，但 Saliba/Timber 伤缺、Bruno 大腿待核；Coventry 升级体系延续但 Wright 缺阵，至少 7 名新援竞争首发 | Arsenal 中卫组合与 Bruno 状态；Coventry 直线出口和中锋人选；补齐 HAD/国际 fair 锚 |
| Hull-Man United | Hull 11 人换血，Butland/Gelhardt/Morita/Hughes/Matazo 多层缺口；United 保留 Carrick-Bruno 主轴，但 Sesko/De Ligt/Mount/Ugarte 状态未定 | 两队门将/中锋最终名单；United 唯一自然 6 号 Santos 的首发与负荷 |
| Everton-Crystal Palace | Everton 缺 Branthwaite/Garner；Palace 缺 Wharton，且新帅、核心中卫与攻击线同时变化 | 三名中轴球员能否首发；Palace 谁承担推进；两队是否形成低创造对局 |
| Ipswich-Sunderland | Ipswich 官方伤停表为空，但新帅+12 笔主要引援；Sunderland 主帅和主轴延续，过程指标却远弱于第7名赛果，后场三人带伤疑问 | O'Neil 的第一套固定阵型；Mukiele/Alderete/Meunier可用性；Ipswich 新后腰与高压中锋是否同链 |
| Forest-Leeds | Forest 换 Glasner并失去 Anderson 的全能职责；Leeds 延续直接推进+选择性压迫，仅门将/中卫局部换血 | Forest 中场如何拆 Anderson 工作量；Leeds 新后轴；Gruev 是否可用 |
| Brentford-Tottenham | Brentford 主帅与直接/定位球机制延续；Tottenham 是媒体上调最大的球队之一，但新中卫/中场和多名攻击伤员同时存在 | Spurs 四名官方伤员、Solanke与van de Ven；新中卫对；媒体乐观是否得到首发完整度支持 |
| Brighton-Villa | Brighton 主帅体系延续但 Minteh/Mitoma/Tzimas 伤缺；Villa 上季第4却出现中场双核流失、多人伤缺/晚归 | 双方边路可用性；Villa 门将去留、Watkins/Konsa负荷；Brighton 新中卫组合 |
| Man City-Bournemouth | City 纸面仍争冠，但主帅、Rodri 与多名资深中卫离开，社区盾转型生硬；Bournemouth 换帅但拟延续高节奏纵向体系 | City 单后腰与中卫保护；Bournemouth 是否保留原压迫速度；双方丢球转换 |
| Newcastle-Liverpool | Newcastle 新帅+年轻化，Isak/Bruno/Tonali/Gordon/Trippier等原指标领跑者离开；Liverpool 新帅、Salah/Konate/Robertson离队且有5名伤员 | Newcastle 成熟终结点与Livramento；Liverpool中卫搭档、Bradley/Ekitike状态及替补深度 |
| Fulham-Chelsea | 两队均换帅；Fulham 中锋/组织/中卫重做且两名膝伤，Chelsea 被媒体从第10上调至第3但三中卫和11名引援仍在装配 | Fulham 新中锋与压迫；Chelsea 三中卫、Fofana停赛替代、世界杯晚归球员负荷 |

## 6. Arsenal-Coventry 当前市场记录

体彩截至 2026-08-20 14:42（北京时间）的可用市场：

- `HHAD -2` 去水 fair：让胜 `39.75%`、让平 `23.32%`、让负 `36.93%`；三面接近，
  只说明“净胜 3+”没有压倒性优势，不能替代普通胜平负方向。
- 总进球模态为 `3球 22.76%`，其次 `2球 20.77%`、`4球 17.31%`。
- 比分单点最高为 `2:0 14.94%`、`3:0 13.58%`、`1:0 10.67%`。
- 当前无 HAD、无国际欧赔 fair、无 opening-to-current 变化序列；因此不生成偏移 Read。

## 7. 转会与可用性重点队列

### 立即盯到赛前发布会

- Arsenal：Bruno、Saliba、Timber。
- Aston Villa：Martinez 去留、Watkins/Konsa 世界杯后负荷、Onana 与多名中场伤缺。
- Hull：Butland、Gelhardt、Morita、Hughes、Matazo。
- Liverpool：Bradley、Ekitike、Jacquet负荷与锋线补强。
- Manchester United：Sesko、De Ligt、Mount、Ugarte。
- Sunderland：Mukiele、Alderete、Meunier。
- Tottenham：Simons、Kudus、Odobert、Kulusevski、Solanke、van de Ven。

### 盯到转会窗关闭

- Manchester City：是否补第二中场/后腰。
- Newcastle：是否补成熟中锋和成熟中场。
- Liverpool：是否补边锋与替补深度。
- Sunderland：是否补中锋与欧战轮换。
- Hull：门将层与受伤中轴的短期替代。
- Chelsea/Ipswich/Tottenham：大规模引援后的最终注册名单与首发拥挤。

## 8. 下一轮采集纪律

1. 每次板面更新先跑 `decision-am`，只接受真实 Match/Snapshot，不手工造市场。
2. 每场赛前发布会后更新 Team `availability`；若只是当场轮换，写入 Read factor，不改永久画像。
3. 转会只在官宣后更新 `summer_window`；谈判与记者消息保留在 watchlist。
4. 舆论只生成核查问题；没有实名事实、时间戳和可证伪机制，不移动 belief。
5. MW3 只复核阵型、首发连续性和结构洞；MW5 才开始更新攻防机制，且不覆盖上季完整基线。

## 9. 来源

- Premier League official season 841 fixtures API:
  https://footballapi.pulselive.com/football/fixtures?page=0&pageSize=500&comp=1&compSeasons=841&altIds=true
- Premier League official injuries, updated 2026-08-19:
  https://www.premierleague.com/en/news/4450606/latest-premier-league-player-injuries-club-by-club-news
- ESPN 20-team season preview, published 2026-08-19:
  https://www.espn.com/soccer/story/_/id/49644584/premier-league-2026-2027-preview-offseason-moves-stats-analysis-predictions-teams
- ESPN confirmed summer transfers, modified 2026-08-19:
  https://www.espn.com/soccer/story/_/id/48955344/premier-league-2026-summer-transfers-all-confirmed-ins-outs-every-club
- ESPN projected opening XIs, published 2026-08-18:
  https://www.espn.com/soccer/story/_/id/49626572/premier-league-week-1-starting-lineups-man-united-man-city-liverpool-arsenal
- BBC promoted-club review, published 2026-08-19:
  https://www.bbc.com/sport/football/articles/ckgvl3qnv29o
