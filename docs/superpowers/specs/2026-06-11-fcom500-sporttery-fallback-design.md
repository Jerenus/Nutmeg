# fcom500 体彩备源 — trade.500.com data-sp 解析 + sporttery 回退（2026-06-11）

## 背景与动机

2026-06-11（世界杯揭幕日）`webapi.sporttery.cn` 的 `getMatchCalculatorV1.qry` 下午起被
WAF 拦截：先返回只含 `vtoolsConfig` 的空壳（`errorCode=0` 但无 `matchInfoList`），后直接
403。两个后果：

1. `jczq-today` 生成**假空盘**决策包（四档全空、¥0），空盘是数据假象而非引擎判断；
2. `persist_sporttery_snapshot` 无条件覆盖——12:00 的完好体彩快照（20 场）被降级响应
   （182 字节）冲掉，当日体彩赔率在磁盘上丢失。

同日实测：仓内已有的第二源 `trade.500.com/jczq/`（`fcom500.py`，5/17 落地）正常返回
200 + 24 场，且页面 HTML 内嵌体彩官方 sp 赔率（验证：胜平负三项倒数和 = 1.129，正好
是竞彩标准 ~13% 抽水）。但现有 `parse_jczq_list` 只抽对阵元数据、不抽赔率。

本设计把 500.com 升级为体彩盘面/赔率的**正式备源**：sporttery 挂掉或降级时自动回退，
下游（tiered 引擎、§29 gap、--replay、复盘）零感知。

## 范围决策（已与用户确认）

- **备源只抓 had/hhad 两个池**（trade 主列表页自带）。ttg/crs 不抓子页面——引擎
  spec §11.1 原生支持部分池缺失（fallback 日 ttg/crs 腿不生成，B 档已有 §27 ttg
  池空警示兜底）。诚实降级，解析面最小。
- 国际侧数据（fixture/欧赔/伤停/H2H）继续全走 API-Football（7500 次/天配额充裕，
  用户 6/11 钉死约定）；500.com 备源只补 API-Football 覆盖不了的体彩官方价
  （§29 体彩−欧赔 gap 的体彩一侧）。

## 组件设计

### 1. 解析器扩展 — `nutmeg/data/fcom500.py`

`Fcom500JczqMatch` 增加字段（保持 frozen dataclass）：

- `had_sp: dict[str, float]` — 胜平负 sp 价。来源：比赛行内 `data-type="nspf"` 的
  3 个 `<p class="betbtn" data-value="3|1|0" data-sp="X.XX">`；`data-value` 3/1/0 →
  home/draw/away。
- `hhad_sp: dict[str, float]` — 让球胜平负 sp 价。来源：`data-type="spf"` 同构三键。
- `hhad_line: float` — 让球线，直接读 `<tr>` 的 `data-rangqiu` 属性（实测
  周四001/002 均为 `-1`）；缺失/非数 → 0.0，不崩。
- `business_date: str` — 销售日，直接读 `data-processdate`（= sporttery
  `businessDate`，实测 2026-06-11；开赛日 `data-matchdate` 是 06-12，两者不同）。
- `match_date: str` / `match_time: str` — 开赛日期时间，直接读含年份的
  `data-matchdate` / `data-matchtime`。
- `is_selling: bool` — `data-isend="0"` 视为在售。

实现注记（2026-06-11 真实 HTML 验证）：`<tr class="bet-tb-tr">` 自带
`data-homesxname/awaysxname/matchdate/matchtime/rangqiu/processdate/matchnum/
simpleleague/isend` 全套干净属性——解析全部走属性、不碰内层标签结构（除 data-sp
三键）。解析失败的行照旧跳过（graceful degradation）。

### 2. 合成器 — `fcom500.py` 新函数 `sporttery_value_from_jczq_board(matches, run_date)`

把 `list[Fcom500JczqMatch]` 合成 sporttery `getMatchCalculatorV1` 同形 `value` dict：

```
{
  "nutmegSource": "fcom500-fallback",          # 数据来源标记，引擎忽略、复盘可见
  "matchInfoList": [
    {"businessDate": "YYYY-MM-DD",
     "subMatchList": [
       {"matchStatus": "Selling",
        "matchNumStr": "周四001",
        "businessDate": "YYYY-MM-DD",
        "homeTeamAbbName": "墨西哥", "awayTeamAbbName": "南非",
        "leagueAbbName": "...",
        "matchDate": "YYYY-MM-DD", "matchTime": "HH:MM",   # 截止时间推出
        "had":  {"h": 1.26, "d": 4.45, "a": 9.00},
        "hhad": {"h": 2.00, "d": 3.25, "a": 3.11, "goalLineValue": "-1"}}
     ]}
  ]
}
```

- `businessDate`：直接用 `data-processdate`（无需周X映射推断）；按其分组产出
  `matchInfoList` 天组。
- `matchDate/matchTime`：直接用含年份的 `data-matchdate` / `data-matchtime`
  （真实开赛时间，无需截止时间/年份推断，UTC 日对齐无边界问题）。
- `matchStatus`：`is_selling=True`（`data-isend="0"`）→ `"Selling"`，否则跳过。
- 池缺失语义：某场 had/hhad 任一池解析不到 → 该池键值缺省（`_had_from_pool` 产出
  不足 3 项时引擎按既有规则处理）；两池全缺 → 该场被引擎 §11.1 跳过。
- 顶层 `nutmegSource` 标记随快照落盘，复盘时可见当天数据来源。

### 3. CLI 回退触发 — `nutmeg/interfaces/cli/jczq.py`

两个 live 命令（`jczq-today` / `jczq-tiered`）的体彩抓取收敛到一个共享 helper：

```
fetch_sporttery_value_with_fallback() -> tuple[value, source]
  1. 试 SportteryJczqCalculatorProvider.fetch()
  2. 触发回退的两种情形：
     a. 抛 JczqProviderError（403/网络/errorCode≠0）
     b. 返回的 value 无非空 matchInfoList（6/11 的空壳降级形态）
  3. 回退：Fcom500Client 抓 trade.500.com/jczq/ → parse_jczq_list →
     sporttery_value_from_jczq_board → 返回 (value, "fcom500-fallback")
  4. 回退也失败/解析 0 场 → 原样抛出主源的错误（绝不猜测、绝不静默空盘）
```

回退发生时打印醒目警告（`⚠️ sporttery 主源不可用，已回退 500.com 备源（仅
had/hhad 池）`）。

### 4. 快照防覆盖守卫 — `persist_sporttery_snapshot`

写盘前检查：新 `value` 无非空 `matchInfoList` **且**磁盘已有含非空 `matchInfoList`
的快照 → 跳过写入 + log warning。首次写入、或新数据非空 → 照常覆盖。修掉 6/11
数据丢失 bug（与 v2.2 修过的 `--replay` 覆盖派发文件 bug 同族）。

## 测试计划 — `tests/test_fcom500_jczq_board.py`

风格对齐 `tests/test_jczq_apifootball_odds.py`（16 个，纯离线 fixture）：

1. **解析**：真实 HTML 截段 fixture（含 周四001/002 行）→ had_sp/hhad_sp 数值、
   让球线、截止时间、坏行跳过、无 data-sp 行降级为空 dict。
2. **合成**：shape 与 `_had_from_pool` / `_board_matches` round-trip（合成 value 喂
   `bold_matches_from_sporttery` 能产出 BoldMatch，had/hhad 数值一致、ttg/crs 为空）；
   businessDate 分组（多销售日混排）；停售场（`data-isend≠"0"`）被排除。
3. **回退触发**：主源抛错 → 走备源；主源返回空壳 → 走备源；备源也 0 场 → 抛主源错误。
4. **守卫**：空覆盖非空被拒；首次写入放行；非空覆盖非空放行。

## 风险与已知局限

- trade.500.com 页面结构变化 → 解析 0 场 → 回退失败时抛主源错误并 log，绝不静默
  出假空盘（与 6/11 教训对齐）。
- 备源日无 ttg/crs：D 档 Poisson edge 过滤（§27）等依赖盘面赔率的规则在缺池处
  自然失效为"不生成该类腿"，属设计内诚实降级。

## 关联

- spec §11.1（部分池缺失加载语义）、§27（ttg 池空警示）、§29（体彩−欧赔 gap）、
  §32（jczq-today 单一入口）
- `docs/superpowers/specs/2026-05-17-fcom500-data-collector-design.md`（fcom500 初版）
- 6/11 事故记录：memory `jczq_2026_06_wc_gap_empty_board`（WAF 降级覆盖快照教训）
