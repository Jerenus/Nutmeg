# Polymarket 关注度 · 设计（2026-10-09）

> Jun 2026-10-09：「只拉取有量的比赛来参考具备关注度的比赛，从而在其中找到人群去处，让模型辨识一些『名气』『热卖』，结合比赛实际内容判断，来找到一些规避场次」→「按这个顺序写设计稿、登记稿，然后完成开发工作」。
> 定位与损耗台账相同：**测量仪 + 预登记实验**，任何数字进 belief 或票面之前先过前瞻实证。

## 1. 事前证据与冲突（会话内，2026-10-09）

- 26136 逐场：12/14 场在 Polymarket 有盘；只有多特-不来梅（$80k）、布拉加-里斯本（$47k）、朗斯-里昂（$11k）有量，其余 $139–3.8k。归一价与我们的市场基线差 ≤4.3pp，规律是热门再高 3–4pp；一周走势与 titan007 开盘位移同向（基本是复制博彩公司）。
- **结果角度与 Jun 的直觉冲突**：jc-history 终盘热门 ≥60% × Polymarket 已结束对阵——高关注（≥$100k）n=181 实开 72.9% vs 终盘 69.4%（+3.5pp，CI[−2.9,+9.5]），与不在 Polymarket 的热门（+3.6pp）一样；全部热门 +5.2pp CI[+3.0,+7.3]。名气热门**不比**市场说的更容易翻车（同 F10、「大牌带洞 7/7」）。
- **奖池角度是成立的问题**：足彩奖池均分，人群去向决定「赢了分多少」而不是「谁赢」。首轮 CR「五大联赛大热」候选在未看过块翻号——缺的正是关注度变量。
- 覆盖：Polymarket 已结束足球对阵 2025-08 → 2026-09，英超/德甲/西甲/法甲/意甲/欧冠/欧联/荷甲/葡超/德乙/英冠等系列；大联赛单场成交中位 $6k–57k。

## 2. 第 1 步：关注度展示（只看不拨动）

### 2.1 数据（`nutmeg/data/polymarket.py`，只读公开接口，零鉴权）
- Gamma `/sports` → 足球联赛系列 id；`/events?series_id=&closed=&end_date_min=&end_date_max=` → 对阵事件（`title`、`volume`、`liquidity`、`volume24hr`、三个「X 胜 / 平」二元市场的 `bestBid`/`bestAsk`/`clobTokenIds`）；CLOB `/prices-history`（一周走势，只对 ≥$20k 的场调用）。
- 抓取件只做取数；网络失败只告警（与人群层同纪律）。

### 2.2 对号（`nutmeg/decision/crowd_polymarket.py`）
- 我方中文队名 → 英文：中译英别名表（`team_aliases.load_team_aliases`，竞彩国际赔率对号同一张）→ 种子实体 `name_en`/英文别名。
- 匹配 Polymarket 标题两侧：去重音、去 FC/SV/BV/AC 等词与数字后按词元比对（≥1 个 ≥3 字母词元重合），≤4 字母全大写别名按首字母缩写比（QPR ↔ Queens Park Rangers）；**两边都对上**、日期 ±1 天、且唯一才算；三向价格按市场问题里点名的球队归面。对不上＝如实缺失。
- 归一：三个中间价当概率，经 `devig(1/中间价)` 归一（单一来源的去水）。

### 2.3 落盘
- 竞彩 `jczq/daily/<日>/polymarket.json`、足彩 `zucai/<期>-polymarket.json`：`snapshots` 只追加（`fetched_at` + 逐场行：`event_id`/`title`/`volume`/`liquidity`/`volume24hr`/三向 bid-ask-mid/归一概率/与我方市场基线逐面差/`rank`（本板成交量名次）/一周走势）。
- 生成：`nutmeg crowd polymarket --day <日> | --issue <期>`；`after_prep`（足彩 11:00/14:00/18:30）与 `after_am`（竞彩入板）旁支自动跑，失败只告警。

### 2.4 展示
- 初判包加一列「关注度」，**只对成交 ≥ $20k 的场**显示：`PM$80k 73/16/10 主+3`（成交量、三向归一价、与我方市场基线差最大的一面）。读法写明：只看不拨动；名气热门历史上不比市场更易翻车。

## 3. 第 2 步：人群假说的关注度字段 + 候选 CR-cand-4（奖池角度）

- `crowd_trigger.FIELDS` 加 `pm_volume_k`（成交量，千美元）与 `pm_rank`（本期 14 场里按成交量的名次，1＝最受关注；未上 Polymarket＝空）。**空值的叶子一律为假**（不猜）。
- `CrowdMatch` 加两个可空字段；`load_board` 读 `<期>-polymarket.json` 最后一张快照并入。
- 回补：`nutmeg crowd polymarket-backfill --from <期> --to <期>`——按系列拉已结束对阵（缓存 `zucai/polymarket-closed.json`），按 zgzcw 快照的中文全称对号，写一张 `source=closed_backfill` 的快照（成交量＝**终场总成交**，与前瞻的赛前成交不同口径——所以触发条件用**期内名次** `pm_rank` 而不是绝对额）。
- **候选（判据在此冻结，回补后才跑回放）**：`CR-cand-4`「高关注大热被全国人群多买」——`all[is_fav == true, p_face >= 50, pm_rank <= 3]`，`crowd_bias=over`（γ<0：这些面开出时任九奖金低于市场意外度预期），role＝fade（别把覆盖花在它上面；**不是**丢场理由）。机制：名气球队被大量单选/串关追买，开出时中奖注偏多。
- 回放窗口：Polymarket 覆盖到的全部已结期次（结果只作签字依据；判决只认前瞻，按 RULEBOOK「十」）。**签字只许人**：Jun 2026-10-09 批准，签为 **CR2**（前瞻 26137 起；回放 26035–26135 +21.8% CI[−1.55,+48.42]，两块不一致，见证据文档）。

## 4. 第 3 步：F17 证伪实验（结果角度，`experiments/registry/F17.json`，Jun 2026-10-09 批准登记，窗口 2026-10-10 起）

- 主张（Jun 的直觉，事前证据偏向否定）：开球前 Polymarket 成交 ≥ $50k 的场里，市场模态面 ≥60% 的热门实开率低于市场概率（名气热卖被高估）。
- 指标 `hyped_fav_resid_pp` ＝ 1{模态面开出} − fair[模态面]；n_min 120；CI 上界 > 0 即证伪。
- 样本：并集池；语料行顶层 `polymarket`（开球前最后一张快照的该场行，`fetched_at < kickoff`）；无义务（同 F10，靠快照自动积累）。
- 结账 `rsi_grading.grade_f17_prospective`（已进 `PROSPECTIVE_ADAPTERS` 与 `rsi_loop.GRADED_EXPERIMENTS`）。
- 口径注意：会话粗测用的是终场成交 ≥$100k；赛前成交约为终场的一半上下，故阈值取 $50k，登记后不改。

## 5. 非目标与治理
- 不改 rubric/belief/票面；不在 Polymarket 下单（只读数据，平台在部分地区受限）。
- 任一实验 survived 后要接判断：证据文档 → RULEBOOK「十」或 rubric 治理流程。

## 6. 实施清单
1. `nutmeg/data/polymarket.py`（取数，注入式 fetcher 便于测试）。
2. `crowd_polymarket.py`：英文名解析、标题匹配、快照行、落盘、回补、语料挂载（TDD）。
3. `crowd_trigger`/`crowd_source`：两个可空字段与空值语义（TDD）。
4. CLI `crowd polymarket` / `crowd polymarket-backfill`；`after_prep`/`after_am` 旁支。
5. 初判包「关注度」列。
6. 回补 + CR-cand-4 回放读数 → `docs/superpowers/evidence/2026-10-09-polymarket-attention.md`；`_draft_F17.json` + `grade_f17_prospective`。
7. RUNBOOK B5d/A4、RULEBOOK「十」字段表、ARCHITECTURE 模块行。
