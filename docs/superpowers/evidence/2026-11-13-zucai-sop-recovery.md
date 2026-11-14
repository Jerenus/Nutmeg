# 26164 SOP 恢复与验证

用户授权：修正相关问题，逐步完成完整 SOP。保留会话开始时所有已有改动，不提交、不推送。

## 修复

- 缺 fair/match_id/snapshot_id 逐场报告；其余场仍转录 Read。自动 legs-base 标注完整性，部分板不能冒充整期初稿。
- 历史死亡统计：full 正确覆盖 310，未知/残缺处方不作为双选；死亡率显示有效票形分母。
- 新 `judgment packet-check` 只读核核心结构；空 rows/重复场号/缺主形不再因 load_packet.errors=[] 被误当完成。它不证明事实正确、不构成投注门，也不证明桥或实购完成。
- 新 `.agents/skills/zucai-sop/SKILL.md` 指向现行 SOP / B5e，AGENTS 与 CLAUDE 增加同一入口；不复制规则。语法验证通过，独立行为验证见 `zucai/evidence/26164-skill-validation.md`。验证使用有历史上下文的独立执行者，不冒称盲测。

## 验证证据

- 先红灯：缺 fair 的 TypeError 和 full 被识别为 double 均被回归测试复现；空 packet 可绕过旧 loader 被新交付测试复现。
- 首轮针对性28例通过，扩展 draft 子集38例通过。本次修改文件 Ruff 通过。
- 全量 pytest 已执行，4处失败：crowd.sign 的 OptionInfo.read_text、day待办依赖当前日期、runs证据源未登记、counter_matrix重复channel-map读取。均在本轮未修改的路径；不声称全库通过。日志 `/tmp/nutmeg26164-pytest.log`。
- 全库 Ruff 350处失败，来自会话开始时已有的实验脚本，日志 `/tmp/nutmeg26164-ruff.log`；未为通过检查改写无关文件。
- 生产副本使用 SQLite backup 和 NUTMEG_DATA_DIR 双重隔离，位置见 `/tmp/nutmeg26164-sandbox.json`。refresh、verdict、day brief、历史票preview、settle dry-run、rsi status/loop均exit0。
- refresh业务：11条Read，投影11/文件11/一致11；8–10报缺，legs-base=partial。读者B旁路14份失败；单份复测返回读者退出码1，不冒称双读完成。
- gym verify exit1：记分牌覆盖期差+200，11月5日两张旧票unknown_leg；未改生产旧账。day brief仍有缺席输入1；exit0不代表输入全齐。
- 生产已执行同一期refresh与judgment brief/counter-matrix。完整draft明确报缺8/9/10，保留失败原因。

## 业务边界

14场研究已完成并再补核许可。合格市场11/14；8/9普通公司报价没有sharp入选，10主供应商404，500三场原始字段为空。辅助报价不替代基线。

条件参考票由现役函数及隔离preview-set计算，另存26164-conditional-*；不是正式整期主形，也不是用户预算承诺。两参考形同时组合被V2否决、增量0pp是有效审算结论，非程序失败。期前预算待用户确定，桥待用户草案，售日复核和赛后结算按时点等待。默认空仓。

补包又发现部分腿表使counter-matrix只遍历11场，新增回归复现后改为issue场号与腿表并集；14场证据恢复，缺价不影响取证展示。顺便改用现役load_channel_map，原single-source失败消除。counter-matrix和单一来源回归通过；最终全量重跑日志/tmp/nutmeg26164-pytest-final.log。

最终全量pytest完成：剩3处失败（crowd.sign、day待办日期、runs未登记源），single-source已恢复通过；没有本轮回归失败。原私有页面已用99项原子编辑更新，读回244块、41张表、14取证附录、14反证矩阵，§0–§5及子分表齐。所有可修旁车面格式已清，check_delivery仍因合格市场/正式主形/完整draft缺失而false，未虚报SOP全部完成。

## 完整终稿交付约定补强

基线失败是本会话上一轮实际行为：packet-check=false，仍以已更新分析页作为最终回复的主交付。即使文字标未完成，也不满足用户要求完整SOP。

已更新zucai-sop终稿验收、B5e正文、AGENTS/CLAUDE同一入口。必要输入/B4/B5/全分表与算术/预算/结构检查及人工页面核验共同完成后才交赛前终稿；缺输入仅报具体阻塞，不能主动交草稿代替完成。用户主动要草稿仍可提供。未来桥/实购/复盘按阶段验收，禁止虚称后台监控。

新上下文独立只读五场景验证：14研究但缺3fair/预算不交；仅结构通过不交；刷新失败仍有独立统计则继续；完整赛前验收而无用户草案可交赛前终稿；明确索要草稿可给未验收草稿并继续原任务。五项均符合约定，与现行SOP无直接冲突。这是行为场景检查，不是每次必然成功的统计保证。技能语法校验通过，两harness指针一致。26164最新packet-check仍明确未齐，不算终稿交付。

## 15:56–16:03 续做（Claude Code 会话）

- 8–10 报价复采（16:00）：500 `data-pjgl` 三场仍空；球探场 8 五家、场 9 七家均非白名单，场 10 欧赔接口仍 404。阻塞未解除，`judgment packet-check` 仍未齐全（缺项与 12:00 相同）。
- 读者 B 两读补齐：上午 14 份失败的根因是 `~/.config/nutmeg/claude-oauth-token` 被吊销（`claude-auth-check` 报 OAuth token revoked，文件 38 天前写入）；`NUTMEG_CLAUDE_TOKEN_FILE=/nonexistent` 改走会话认证重跑，读 14 · 失败 0，平均 κ 0.942（场 4 0.667 / 场 2 0.722 / 场 10 0.793）。**launchd 下的研究、读者 B、解读句仍会因该 token 失败，需 Jun 在普通终端 `claude setup-token` 重写该文件。**
- 人群复采 15:58：zgzcw 快照、Polymarket 带 flow（仍 0 场 ≥$2 万、无 money_to）、CR 扫描新增 CR2 ⚑ 三条（3/5/13 主胜，advisory）。
- `judgment brief --issue 26164 --write` 重写（rubric 列带 κ）；完整初稿仍因缺 8/9/10 拒出（退出码 1，属预期）。
- packet.md §0 / §1b / §2 胆表人群列 / 缺价段 / 复审边界 与 packet.json（rows 3/5/13 crowd、workflow_status）同次更新；`load_packet` errors 仍只有 8–10 三行。原 ChatGPT 页面本会话无法写入，未更新。
- 仍待：8–10 合格报价（售日 11:00 备料链会自动再抓）、期前预算 P-3a56d39e、完整初稿/主形/替代、桥、售日复核。
- 16:04 Jun 答复（AskUserQuestion）：期前预算「¥800 / ¥1,600」→ `account precommit --issue 26164 --slip-yuan 800 --issue-yuan 1600` 已写，P-3a56d39e 签并 done；缺价口径「等售日备料」→ 不改书目口径、不用辅助价，售日 11:00/14:00 备料后再出完整初稿，仍缺则如实报缺、按空仓读。packet.md / packet.json 同次改写预算与口径表述。
- `launchctl list`：`jczq.research`、`rsi.loop`、`rsi.sweep` 上次退出码 1（与 token 吊销同期，未逐个核因）。

## 22:02–22:25 整期重研与新版式重建（Claude Code 会话，Jun 要求）

- Jun 22:00 前后要求「新版式重新跑一次 26164 的完整 SOP、逐场深研」。无人值守 token 当晚已重建，`research run` 可用。
- 旧研究 14 份与读者 B 侧车 14 份移到 `zucai/archive-rerun/26164-*.codex-1113.json`；V1 包备份为 `26164-packet.V1.md/.json`。
- 重研：`env -u CLAUDE_EFFORT NUTMEG_MODEL_RESEARCH=opus uv run nutmeg research run --day 2026-11-14 --concurrency 5`（22:05–22:15，11 场 11 次尝试 11 份，全部收敛）；场 8/9/10 无 match_id/fair 不在研究池，改由 `jczq-match-analyst` 分析员定义单独派发三份（22:10–22:45 采集），原件落 `26164-research-m{8,9,10}.json`，`market_snapshot.status=missing_market`。读者 B 按抽样只读了场 3（κ 0.73）。
- 刷新：Read 11 条入内核（同判断新版本 11，分歧 0），legs-base 仍为 partial；`judgment brief --write` 重写，整期初稿仍因缺 8/9/10 拒出；`counter-matrix --write`、`structure_align`、`dead_match_align` 重跑（样本表重建到 11-16，前瞻有赛果 781 行）；人群快照与 Polymarket 22:08 重拉（11 场，全部 <$2 万）。
- 研究处方 V1→V2 改写 10 格（收窄 9、换保险面 1），第一面 14 场不变；六条件按新研究重数，已知 11 场最高 3/6（3 挪威、12 克罗地亚），许可单 0，机器默认空仓不变。
- 包：`26164-packet.md`（V2，新版式：§1 主表六列 + 折叠取证附表）与 `26164-packet.json` 同次重写；`load_packet` errors 只有 8–10 三行；`judgment packet-check` 仍未齐全，缺项与此前相同（8–10 的档/条件/分表、字典主形、替代、draft.json、市场输入）。条件参考票形只含已知 11 场，`preview-set --alternatives` 22:20：W2 ¥256 10.92% / W1 ¥512 14.15% / 处方 D0 ¥16 3.17% / 9双 ¥1,024 16.79%（超期前定额）。
- 页面：Claude 侧新发一页 https://claude.ai/artifact/54LovQtaepZfD5ojyisfQr（仅本人可见，页首标「未验收草稿」）；记录在 `zucai/26164-page-claude.json`。本地校验 24 张表、16 个折叠块、标签闭合；没有做页面读回。ChatGPT 那页未动。
- **仍是草稿，不是赛前终稿。** 恢复条件：售日 11:00 / 14:00 备料链抓到 8/9/10 的合格报价 → `research refresh` → `judgment brief --issue 26164 --write`（整期初稿）→ 补三行与 §0 板型、§2 主形/替代/固定参考形、`preview-set` → `packet-check` → 页面读回。没有为此启动任何后台任务。


## 11-14 08:43–09:15 售日整期版与赛前分析包验收（Claude Code 会话）

- 起因：Jun 08:40 前后问「主攻 sfc 的你最有把握的方案目前是？」。08:44 只读抓官方在售页，`data-pjgl` 已有场 8/9/10（30.5/29.2/40.3、31.4/28.4/40.2、93.3/5.1/1.6），阻塞解除。场 1 中国主胜 54.6 → 63.0（只有 500 一个源）。
- 备料与入库：`zucai-prep --slot morning --issue 26164`（08:46，14 场；11:00 定时备料会再抓）→ `decision-am --run-date 2026-11-14 --issue 26164`（14 场 Match）→ `research refresh --day 2026-11-14`（足彩 Read 14 条，同判断新版本 14，分歧 0；legs-base 14 腿）→ `judgment brief --issue 26164 --write`（08:50，整期初稿任九与胜负彩都出）。
- 开球时间更正 C-6b153c0a：备料重抓把场 1 写回 00:00，已按同一条更正重贴 20:00 到 `26164-issue.json`。**11:00、14:00 备料还会再写回 00:00**，每次备料后要重贴；这条通路仍没有自动化。
- 场 8/9/10 的研究是 11-13 晚无报价时做的，今天没有重研；事实层照用，价内/未价按今早国际盘位移由主循环补判（8 +1.0 价内、9 缺阵早于开盘价内、10 无国际盘记「?」）。场 10 六条件由预读 3/6 改为 4/6（① 按研究里的小组数据补记），A 档 4/6 仍不算许可单。
- 分表：`counter-matrix --write`（09:02）、`decision_samples_build --to 2026-11-16` + `structure_align`（09:02）、`dead_match_align`（09:05；26163 后 8 场官方未开奖，赛果缺口 8 行）、`crowd fetch` + `polymarket --flow` + `scan`（09:03，0 场 ≥$2 万，CR2 ⚑ 5、6）。
- 板型与默认：nA 1 / nB 2 / nb 5 / nC 2 / nD 4，半热板；许可单 0（10 芬兰 4/6，3、12 各 3/6）→ 机器默认空仓。
- 预审：任九六形 `preview-set --alternatives`（字典主形 3单6双 ¥128 14.69%、2单7双 ¥256 19.05%、1单8双 ¥512 22.52%、D0 ¥384 11.82%、丢光 C ¥6 4.24%、max-P ¥648 34.29%；V1 0.82–0.85）；胜负彩八形（max-P 梯度 ¥108 0.74% 到 ¥648 2.37%，V1 0.43–0.47 全部 ⛔；D0 ¥384 1.10% V1 0.50 ⚠️；白防线 ¥256 0.85% ⛔）。max-P 梯度由按注数的动态规划求得，P 与 V1 与预审输出逐行一致。
- 胜负彩参考（Jun 问）：四包两双八单 `1:3 2:310 3:3 4:3 5:3 6:10 7:3 8:310 9:310 10:3 11:310 12:3 13:3 14:31`，324 注 ¥648，全中 2.37%，恰错一场 11.1%，V1 0.47 否决。滚存：26163 未开奖，26162 开奖后奖池余额 0。
- 包：`26164-packet.md`（V3）与 `26164-packet.json` 同次重写；V2 备份为 `26164-packet.V2.md/.json`。
- **验收（09:12）**：`judgment packet-check --issue 26164` → 核心结构齐全；人工读过头部、§0、14 行决策表、§1b/§1c/§1d/§1g 读法、§2、§2b；页面 https://claude.ai/artifact/54LovQtaepZfD5ojyisfQr 更新为版本 1794618688-41ac，读回第 49–56、68–82、417–441 行与本地一致（25 张表、16 个折叠块、标签闭合）。结论：**赛前分析包完成**。
- 未完成且不在本次验收内：11:00 / 14:00 售日复核（档位、许可、每条双的排除面、胜负彩 max-P 形是否变形）、26163 开奖后核奖池余额、Jun 的草案与桥、实购登记、赛后复盘。没有为这些启动后台任务。

## 11-14 11:12 与 14:12 两次售日复核（V4，读判冻结）

- **11:00 备料后**（11:12 起做，未做完被中断，结果并入 14:12 这次）：12 克罗地亚主胜 67.0→62.8（B→b）、13 西班牙 59.1→55.1（b→C），500 报价向国际盘靠拢；板型半热板→冷板；胜负彩帽内 max-P 形换两格（11 全包→双 30、14 双 31→全包）；26163 官方已开奖，`poolBalanceAfterdraw` 0。场 1 开球被备料写回 00:00，按 C-6b153c0a 重贴 20:00。
- **14:00 备料后**（14:12–14:23）：7 瑞典 62.5→65.3（b→B，过线 0.3pp；一次检索没找到新的伤停或名单消息），1 中国 63.0→61.3（下午有了国际盘 60.4）；板型回到半热板，字典主形 3单6双 ¥128 的第三条单从 12 换成 7；许可单仍 0，机器默认空仓。14:00 备料写出的场 1 开球已是 20:00，没有再贴。
- **工具数字（市场 14:00）**：任九 3单6双 13.60%、2单7双 ¥256 17.89%（V1 0.84，估派 ¥390，不回本 38%）、D0 ¥384 11.70%；互补票 A ¥216 → 合计 ¥472 至少中一张 26.57%，B ¥128 → ¥384 23.98%；胜负彩帽内 max-P ¥648 2.11% V1 0.48 否决，08:46 那张 2.08%。Polymarket 两场过 $2 万（5 葡萄牙 $46.3k 钱→主、3 挪威 $23.2k 钱→主），都在热门一边。
- **产物**：`26164-packet.md/.json` 重建为 V4（V3 备份在 `26164-packet.V3.*`），`judgment packet-check` 核心结构齐全；页面同一链接第 4 版 `1794637363-e0d6`，读回第 49–56、413–418 行一致。样本表按 14:00 档位重建（26163 后 8 场赛果仍未入样）。
- **没做的**：今天没有重研；7 瑞典位移原因没查到；26163 五张待结票没有结账（官方任九单注 ¥129、一等奖 ¥6,241、二等奖 ¥166），结账后止损余量与「中奖后不加码」的线会重算。
