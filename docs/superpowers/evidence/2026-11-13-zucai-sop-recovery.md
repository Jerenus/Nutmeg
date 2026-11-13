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

