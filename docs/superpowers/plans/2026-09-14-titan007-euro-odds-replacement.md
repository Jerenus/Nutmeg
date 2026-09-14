# titan007 国际欧赔平替 API-Football 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用免费无配额的球探网 007（titan007）取代 API-Football 作为 jczq 国际欧赔主源，恢复恒为 0 的 drift/初赔信号，并把板面覆盖率从 60% 拉到 100%。

**Architecture:** 新增一个纯数据层客户端 `nutmeg/data/titan007.py`（抓取 + 解析，零业务语义）与一个服务层采集器 `nutmeg/services/jczq_titan007_odds.py`（板面对齐 + 组装 `MarketOdds`）。后者的签名与返回形状与现有 `collect_bold_odds_apifootball` **完全一致**，因此对判断层是 drop-in——只换数据源槽位。改造分三段推进：先建源（不接线）→ 再跑影子期对比（不改判断）→ 最后凭影子证据由用户决定是否切主源。

**Tech Stack:** Python 3.12 / httpx / pytest / 现有 `MarketOdds` + `_devig`（`nutmeg/data/fcom500.py`）

---

## 背景与实测证据（2026-09-14 实跑，非推断）

账号状态实测：

```
plan: Free | limit_day: 100 | current: 12
```

三条可量化的现状损失：

| 症状 | 实测 |
| --- | --- |
| 国际欧赔覆盖 | `bold_odds.json` 6 场 vs `sporttery_markets.json` 10 场 = **60%** |
| 初赔结构性缺失 | `jczq_apifootball_odds.py:224` 注释自陈：`基础 /odds 无开赛前 opening；drift 对这些场降级为 0` |
| 别名链路 | 中→英别名表（94.4% 覆盖）纯粹是 API-Football 这个源强加的成本 |

titan007 实跑验证：

| 验证项 | 结果 |
| --- | --- |
| `jc.titan007.com/xml/bf_jc.txt` | HTTP 200，UTF-8，2307 B，**24 字段 × 10 行稳定** |
| 竞彩编号对齐 | **10/10 逐字相同**（周一002…周一012），零别名、零 UTC 换算、零模糊匹配 |
| `1x2d.titan007.com/{id}.js` | HTTP 200，UTF-8+BOM，137 KB，**27 字段 × 152 行稳定** |
| 初赔 + 即时赔 | 152/152 行两者俱全 |
| devig 字段假设 | `fields[6:9] == devig(fields[3:6])` **152/152 验证通过** |
| 锐盘覆盖 | Pinnacle(177) / Crown(545) / Macauslot(80) / IBCBET(649) / Sbobet(474) / Bet365(281) 全在 |

drift 实例（`3085206` Pinnacle）：初赔 `2.07/3.37/3.54` → 即时 `1.71/3.81/5.10`，主胜大幅收缩。**这条信号现在在系统里恒等于 0。**

## 两个关键设计决定

### 决定一：共识盘取哪些书 — 由影子期定，不由我拍

152 家里尾部是 `Rodeoslot` / `Roobet` / `Spinaura` / `Roosterbet` 这类噪声盘。直接对 152 家取均赔，与现在对 API-Football ~10-20 家取均赔，**分布不同**——即便聚合规则一模一样。这是判断层输入的变更，按 SOP 不能默认切。

因此本计划实现三种共识口径并列，由影子期报告给出证据后再由用户裁定：

| 口径 | 定义 |
| --- | --- |
| `sharp` | 固定锐盘白名单（见 `_SHARP_COMPANY_IDS`），**本计划默认值** |
| `all` | 除排除名单外全部 152 家 |
| （对照） | API-Football 现值 |

### 决定二：竞彩官方（`Lottery Official`, id=1129）必须排除

它就是体彩盘本身。混进"国际共识"会让「国际 vs 体彩」的冲突信号变成拿体彩跟自己比——一个 API-Football 路径上不存在、titan007 路径上默认就会踩的自指陷阱。同理排除香港马会（id=432，彩池非庄家盘）与 Betfair（id=2，交易所，已含佣金口径）。

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `nutmeg/data/titan007.py`（新建） | HTTP 抓取 + UTF-8 解码 + 两个纯函数解析器 + 降级响应识别。**零业务语义** |
| `nutmeg/services/jczq_titan007_odds.py`（新建） | 竞彩号对齐 + 开球时间守卫 + 书目筛选 + 组装 `MarketOdds`。drop-in 于 `collect_bold_odds_apifootball` |
| `nutmeg/decision/odds_shadow.py`（新建） | 影子期：双源同抓、逐场逐路对比 fair、出报告 |
| `nutmeg/interfaces/cli/decision.py`（改） | 挂 `decision-odds-shadow` 子命令 |
| `nutmeg/decision/fetch.py`（改） | 加覆盖率地板守卫，堵部分降级覆盖完好快照 |
| `tests/test_titan007.py`（新建） | 数据层解析单测，离线 fixture |
| `tests/test_jczq_titan007_odds.py`（新建） | 服务层对齐/降级/组装单测 |
| `tests/fixtures/titan007/*`（新建） | 真实抓取的裁剪样本 |

---

## Task 1: titan007 板面解析（竞彩号 ↔ 007 id）

**Files:**
- Create: `tests/fixtures/titan007/bf_jc.txt`
- Create: `tests/test_titan007.py`
- Create: `nutmeg/data/titan007.py`

- [ ] **Step 1: 落真实板面 fixture**

`tests/fixtures/titan007/bf_jc.txt` —— 真实抓取裁剪为 3 场（保留联赛头 + `$` 分隔符 + `!` 行分隔，UTF-8 存盘，解析器负责 GBK 解码所以 fixture 直接喂已解码字符串）：

```
13^#003db9^2082^芬超,芬超^冠,冠^SubLeague.aspx?SclassID=13!34^#0088FF^2948^意甲,意甲^,^SubLeague.aspx?SclassID=34$3085206^2026,8,14,23,00,00^2026,8,14,23,00,00^0^周一002^13^2082^386^图尔库国际,英特杜古,国际图尔^2226^VPS瓦萨,VPS華沙,瓦萨^0^0^^^0^0^0^0^2^6^2026,8,14,00,00,00^0.75^0!2993786^2026,8,15,00,30,00^2026,8,15,00,30,00^0^周一003^34^2948^1397^科莫,科木,科莫^189^帕尔马,帕爾馬,帕尔马^0^0^^^0^0^0^0^8^16^2026,8,14,00,00,00^1.25^0!2993793^2026,8,15,00,30,00^2026,8,15,00,30,00^0^周一004^34^2948^558^都灵,拖連奴,都灵^174^罗马,羅馬,罗马^0^0^^^0^0^0^0^14^3^2026,8,14,00,00,00^-0.75^0
```

- [ ] **Step 2: 写失败测试**

`tests/test_titan007.py`：

```python
"""单测 titan007 数据层 —— 板面/欧赔解析、降级响应识别。全部离线 fixture。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from nutmeg.data.titan007 import (
    Titan007ParseError,
    parse_board,
)

FIXTURES = Path(__file__).parent / "fixtures" / "titan007"


def _board_text() -> str:
    return (FIXTURES / "bf_jc.txt").read_text(encoding="utf-8")


def test_parse_board_extracts_jc_number_and_titan_id():
    rows = parse_board(_board_text())
    assert [r.match_no for r in rows] == ["周一002", "周一003", "周一004"]
    assert [r.match_id for r in rows] == ["3085206", "2993786", "2993793"]


def test_parse_board_decodes_zero_indexed_month():
    """titan007 沿用 JS Date 月份口径（0 起），`2026,8,14` 是 9 月 14 日，不是 8 月。"""
    rows = parse_board(_board_text())
    assert rows[0].kickoff == datetime(2026, 9, 14, 23, 0, 0)
    assert rows[1].kickoff == datetime(2026, 9, 15, 0, 30, 0)


def test_parse_board_keeps_all_team_name_variants():
    rows = parse_board(_board_text())
    assert rows[0].home_names == ("图尔库国际", "英特杜古", "国际图尔")
    assert rows[0].away_names == ("VPS瓦萨", "VPS華沙", "瓦萨")


def test_parse_board_rejects_degraded_response():
    """WAF/错误页必须 raise，绝不返回空 list 冒充『今天没有盘』（2026-06 假空盘死法）。"""
    with pytest.raises(Titan007ParseError):
        parse_board("<html><title>404 - 找不到文件或目录。</title></html>")


def test_parse_board_rejects_empty_match_section():
    with pytest.raises(Titan007ParseError):
        parse_board("13^#003db9^2082^芬超,芬超^,^League.aspx?SclassID=13$")
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/test_titan007.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.data.titan007'`

- [ ] **Step 4: 写实现**

`nutmeg/data/titan007.py`：

```python
"""球探网 007（titan007）数据源 —— 竞彩板面 + 国际欧赔。

退役背景：国际欧赔原走 API-Football（``services/jczq_apifootball_odds``）。该源
Free 档 100 次/天，2026-09-14 实测板面覆盖率仅 6/10；且其基础 ``/odds`` **不含开赛
前 opening 赔率**，故 drift 信号对全部场次恒为 0。

titan007 用两个免费无配额端点同时解掉三件事：

1. ``jc.titan007.com/xml/bf_jc.txt`` —— 当日竞彩板面，**自带竞彩编号 ↔ 007 match id**
   映射（2026-09-14 实测 10/10 逐字对齐）。因此本源**不需要任何中文→英文别名表**、
   不需要 UTC 跨日换算、不需要 fixture 池模糊匹配。
2. ``1x2d.titan007.com/{match_id}.js`` —— 该场 152 家博彩的 **初赔 + 即时赔**，含
   Pinnacle / Crown / Macauslot / IBCBET / Sbobet 等去水锚要的锐盘。

两个端点都是 **UTF-8**（欧赔 JS 带 BOM，板面不带）；欧赔 JS 另需欧指列表页 Referer
才正常返回。

> **实施期修正（2026-09-14）**：本计划初稿按站点 HTML 的 `<meta charset=gb2312>` 假设
> 了 GBK，**是错的**。两个数据端点实测 UTF-8 strict 可解；按 GBK + `errors="replace"`
> 解会在非法字节处错位，而 GBK 尾字节范围覆盖 `0x5E`（正是 `^` 分隔符），错位会凭空
> 吞掉或伪造字段边界——实测把板面 10 行整齐的 24 字段撕成 `{24:5, 23:4, 22:1}`，队名
> 全成乱码。客户端因此改为 **utf-8-sig → gb18030 双 strict**，绝不有损解码。Task 3 的
> 测试相应改用 UTF-8 编码，并新增 `test_client_rejects_an_undecodable_body`。

**绝不猜测 / 绝不假空盘**：解析拿不到最小规模数据一律 ``raise
Titan007ParseError``，由调用方决定降级——从不返回空值冒充「今天没有盘」。那正是
2026-06 WAF 降级响应覆盖完好快照的死法。

本模块零业务语义：不做去水、不判断哪些书可信、不碰体彩盘。那些住在
``services/jczq_titan007_odds``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

import httpx

__all__ = [
    "Titan007Client",
    "Titan007Error",
    "Titan007ParseError",
    "Titan007BoardRow",
    "Titan007BookQuote",
    "parse_board",
    "parse_euro_odds",
]

_BOARD_URL = "http://jc.titan007.com/xml/bf_jc.txt"
_EURO_URL_TEMPLATE = "http://1x2d.titan007.com/{match_id}.js"
_BOARD_REFERER = "http://jc.titan007.com/"
_EURO_REFERER = "http://odds.titan007.com/"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# 板面行实测恒 24 字段；欧赔行实测恒 27 字段。字段数不符 = 站点改版，宁可炸不可猜。
_BOARD_FIELD_COUNT = 24
_EURO_FIELD_COUNT = 27

# 解析结果低于此规模视为降级响应（WAF / 错误页 / 半截内容）。
_MIN_BOARD_ROWS = 1
_MIN_EURO_ROWS = 5

_RE_EURO_GAME_ARRAY = re.compile(r"game=Array\((.*?)\);", re.S)
_RE_EURO_ROW = re.compile(r'"([^"]*)"')


class Titan007Error(RuntimeError):
    """titan007 抓取失败（网络/HTTP）。"""


class Titan007ParseError(Titan007Error):
    """titan007 响应无法解析或规模不足——降级响应，绝不当作空盘。"""


@dataclass(frozen=True, slots=True)
class Titan007BoardRow:
    """板面一行：竞彩编号 ↔ titan007 match id 的权威映射。

    ``kickoff`` 是**北京时间 naive datetime**，与体彩 ``matchDate``+``matchTime``
    同一时区口径，可直接比对（对齐守卫用）。
    """

    match_id: str
    match_no: str
    kickoff: datetime
    home_names: tuple[str, ...]
    away_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Titan007BookQuote:
    """一家博彩对一场的报价：初赔 + 即时赔，键 ``home``/``draw``/``away``。"""

    company_id: str
    company_name: str
    opening: dict[str, float]
    current: dict[str, float]
    updated_at: datetime | None


def _parse_titan_datetime(raw: str) -> datetime | None:
    """解 titan007 的 JS Date 风格时间串。

    两种实测形态，月份都是 **0 起**（JS ``Date`` 口径）：

    - 开球：``2026,8,14,23,00,00``      → 2026-09-14 23:00:00
    - 更新：``2026,09-1,13,23,28,00``   → 2026-09-13 23:28:00

    第二种的月份位是字面量算式 ``09-1``，同样求值为 0 起月份。无法解析返回
    ``None``（调用方按缺失处理，绝不猜）。
    """
    parts = [p.strip() for p in (raw or "").split(",")]
    if len(parts) != 6:
        return None
    month_token = parts[1]
    try:
        if "-" in month_token:
            left, right = month_token.split("-", 1)
            month_zero_based = int(left) - int(right)
        else:
            month_zero_based = int(month_token)
        return datetime(
            year=int(parts[0]),
            month=month_zero_based + 1,
            day=int(parts[2]),
            hour=int(parts[3]),
            minute=int(parts[4]),
            second=int(parts[5]),
        )
    except (TypeError, ValueError):
        return None


def _names(raw: str) -> tuple[str, ...]:
    """``简,繁,别名`` → 去空去重（保序）的名字元组。"""
    seen: dict[str, None] = {}
    for part in (raw or "").split(","):
        name = part.strip()
        if name:
            seen.setdefault(name, None)
    return tuple(seen)


def parse_board(text: str) -> list[Titan007BoardRow]:
    """解 ``bf_jc.txt`` → 板面行。

    形状 ``<联赛块>$<场次>!<场次>!…``；场次 24 字段，关键位：

    ===== ==========================================
    下标   含义
    ===== ==========================================
    0      titan007 match id
    1      开球时间（北京，0 起月份）
    4      **竞彩编号**（``周一002``）
    8      主队名 ``简,繁,别名``
    10     客队名 ``简,繁,别名``
    ===== ==========================================

    降级响应（无 ``$``、场次段空、字段数不符）一律 raise。
    """
    if "$" not in (text or ""):
        raise Titan007ParseError(
            "titan007 板面响应无 `$` 分隔符——疑似 WAF/错误页，拒绝当作空盘"
        )
    _, _, match_section = text.partition("$")
    rows: list[Titan007BoardRow] = []
    for chunk in match_section.split("!"):
        if not chunk.strip():
            continue
        fields = chunk.split("^")
        if len(fields) != _BOARD_FIELD_COUNT:
            raise Titan007ParseError(
                f"titan007 板面行字段数 {len(fields)} != {_BOARD_FIELD_COUNT}——疑似站点改版"
            )
        kickoff = _parse_titan_datetime(fields[1])
        match_no = fields[4].strip()
        if kickoff is None or not match_no:
            continue
        rows.append(
            Titan007BoardRow(
                match_id=fields[0].strip(),
                match_no=match_no,
                kickoff=kickoff,
                home_names=_names(fields[8]),
                away_names=_names(fields[10]),
            )
        )
    if len(rows) < _MIN_BOARD_ROWS:
        raise Titan007ParseError("titan007 板面解出 0 场——降级响应，拒绝当作空盘")
    return rows
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_titan007.py -v`
Expected: PASS（5 passed）

- [ ] **Step 6: 提交**

```bash
git add nutmeg/data/titan007.py tests/test_titan007.py tests/fixtures/titan007/bf_jc.txt
git commit -m "feat(titan007): parse the JCZQ board, mapping 竞彩号 to titan007 match id

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SP8EoQijFxYgRxEaPkDSkJ"
```

---

## Task 2: titan007 欧赔解析（初赔 + 即时赔 × 152 家）

**Files:**
- Create: `tests/fixtures/titan007/euro_3085206.js`
- Modify: `tests/test_titan007.py`
- Modify: `nutmeg/data/titan007.py`

- [ ] **Step 1: 落真实欧赔 fixture**

`tests/fixtures/titan007/euro_3085206.js` —— 真实抓取裁剪为 6 家（含必须被排除的竞彩官方 + 香港马会，供服务层筛选测试用）：

```javascript
var ScheduleID=3085206;
var matchname_cn="芬超";
var game=Array("1129|157603168|Lottery Official|1.55|3.65|4.75|57.11|24.25|18.64|88.52|1.55|3.65|4.75|57.11|24.25|18.64|88.52|0.85|0.94|0.92|2026,09-1,12,01,46,00|竞彩官*|1|0|0.85|0.94|0.92","281|157499520|Bet 365|1.73|3.4|4.75|53.39|27.17|19.44|92.36|1.7|3.4|5.25|54.83|27.42|17.75|93.21|0.93|0.88|1.02|2026,09-1,13,20,11,00|36*(英国)|1|0|0.95|0.88|0.92","80|157501527|Macauslot|1.55|3.73|4.65|57.18|23.76|19.06|88.63|1.57|3.83|4.45|56.73|23.25|20.01|89.07|0.86|0.99|0.86|2026,09-1,13,07,22,00|澳*|1|0|0.85|0.96|0.90","432|157559900|HK Jockey Club|1.55|3.6|4.7|56.81|24.46|18.73|88.05|1.55|3.6|4.7|56.81|24.46|18.73|88.05|0.86|0.92|0.90|2026,09-1,13,13,58,00|香港马*(中国香港)|1|0|0.86|0.92|0.90","177|157470659|Pinnacle|2.07|3.37|3.54|45.48|27.93|26.59|94.13|1.71|3.81|5.1|56.05|25.16|18.79|95.85|0.94|0.98|0.99|2026,09-1,13,23,28,00|Pinna*(荷兰)|1|0|1.13|0.87|0.69","545|157502233|Crown|1.71|3.7|4.45|56.34|26.04|21.65|96.35|1.72|3.7|4.4|55.89|25.98|21.85|96.19|0.95|0.96|0.96|2026,09-1,13,13,43,00|Crow*|1|0|0.96|0.96|0.96");
var gOrder=Array();
```

- [ ] **Step 2: 写失败测试**

追加到 `tests/test_titan007.py`：

```python
from nutmeg.data.titan007 import parse_euro_odds


def _euro_text() -> str:
    return (FIXTURES / "euro_3085206.js").read_text(encoding="utf-8")


def test_parse_euro_odds_returns_every_book():
    quotes = parse_euro_odds(_euro_text())
    assert [q.company_name for q in quotes] == [
        "Lottery Official",
        "Bet 365",
        "Macauslot",
        "HK Jockey Club",
        "Pinnacle",
        "Crown",
    ]


def test_parse_euro_odds_splits_opening_from_current():
    """初赔与即时赔是两组独立字段——这正是 API-Football 结构性缺失的那一半。"""
    pinnacle = next(q for q in parse_euro_odds(_euro_text()) if q.company_id == "177")
    assert pinnacle.opening == {"home": 2.07, "draw": 3.37, "away": 3.54}
    assert pinnacle.current == {"home": 1.71, "draw": 3.81, "away": 5.1}


def test_parse_euro_odds_reads_update_time_with_arithmetic_month():
    pinnacle = next(q for q in parse_euro_odds(_euro_text()) if q.company_id == "177")
    assert pinnacle.updated_at == datetime(2026, 9, 13, 23, 28, 0)


def test_parse_euro_odds_rejects_degraded_response():
    with pytest.raises(Titan007ParseError):
        parse_euro_odds("<html><title>500 - 内部服务器错误。</title></html>")


def test_parse_euro_odds_rejects_too_few_books():
    """半截响应（书目过少）必须 raise，不能当作『这场没盘』。"""
    thin = 'var game=Array("177|1|Pinnacle|2.07|3.37|3.54|45|27|26|94|1.71|3.81|5.1|56|25|18|95|0.9|0.9|0.9|2026,09-1,13,23,28,00|P*|1|0|1.1|0.8|0.6");'
    with pytest.raises(Titan007ParseError):
        parse_euro_odds(thin)
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/test_titan007.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_euro_odds'`

- [ ] **Step 4: 写实现**

追加到 `nutmeg/data/titan007.py`：

```python
_OUTCOME_KEYS = ("home", "draw", "away")


def _odds_triplet(fields: list[str], start: int) -> dict[str, float] | None:
    """取 ``fields[start:start+3]`` 为 home/draw/away 十进制赔率；任一不合法返回 None。"""
    out: dict[str, float] = {}
    for offset, key in enumerate(_OUTCOME_KEYS):
        try:
            value = float(fields[start + offset])
        except (TypeError, ValueError, IndexError):
            return None
        if value <= 1.0:
            return None
        out[key] = value
    return out


def parse_euro_odds(text: str) -> list[Titan007BookQuote]:
    """解 ``1x2d.titan007.com/{id}.js`` 的 ``game=Array(...)`` → 各家报价。

    行 27 字段，实测布局（2026-09-14，152/152 行一致）：

    ====== ==========================================
    下标    含义
    ====== ==========================================
    0       公司 id（稳定，按 id 筛选而非按名字）
    2       公司英文名
    3-5     **初赔** 主/平/客
    6-8     初赔去水概率 %（站点自算；本仓不用，用自己的 ``_devig``）
    9       初赔返还率 %
    10-12   **即时赔** 主/平/客
    13-15   即时去水概率 %
    16      即时返还率 %
    20      更新时间
    21      公司中文名
    ====== ==========================================

    字段 6-8 与 ``_devig(字段 3-5)`` 的一致性已实测 152/152 通过——可作解析自检的
    旁证，但本仓一律用自己的 ``_devig`` 保持全局口径统一。

    初赔或即时赔任一不合法的行直接跳过（不猜）。解出书目 < ``_MIN_EURO_ROWS``
    视为降级响应 → raise。
    """
    match = _RE_EURO_GAME_ARRAY.search(text or "")
    if match is None:
        raise Titan007ParseError(
            "titan007 欧赔响应无 `game=Array(...)`——疑似 WAF/错误页，拒绝当作无盘"
        )
    quotes: list[Titan007BookQuote] = []
    for raw_row in _RE_EURO_ROW.findall(match.group(1)):
        fields = raw_row.split("|")
        if len(fields) != _EURO_FIELD_COUNT:
            continue
        opening = _odds_triplet(fields, 3)
        current = _odds_triplet(fields, 10)
        if opening is None or current is None:
            continue
        quotes.append(
            Titan007BookQuote(
                company_id=fields[0].strip(),
                company_name=fields[2].strip(),
                opening=opening,
                current=current,
                updated_at=_parse_titan_datetime(fields[20]),
            )
        )
    if len(quotes) < _MIN_EURO_ROWS:
        raise Titan007ParseError(
            f"titan007 欧赔仅解出 {len(quotes)} 家（< {_MIN_EURO_ROWS}）——降级响应，拒绝当作无盘"
        )
    return quotes
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_titan007.py -v`
Expected: PASS（10 passed）

- [ ] **Step 6: 提交**

```bash
git add nutmeg/data/titan007.py tests/test_titan007.py tests/fixtures/titan007/euro_3085206.js
git commit -m "feat(titan007): parse per-book European odds, opening and current

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SP8EoQijFxYgRxEaPkDSkJ"
```

---

## Task 3: HTTP 客户端（UTF-8 + 浏览器头 + Referer）

**Files:**
- Modify: `tests/test_titan007.py`
- Modify: `nutmeg/data/titan007.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_titan007.py`：

```python
import httpx

from nutmeg.data.titan007 import Titan007Client, Titan007Error


def _client_with(handler) -> Titan007Client:
    return Titan007Client(transport=httpx.MockTransport(handler))


def test_client_decodes_gbk_board():
    """titan007 全站 GBK 且不带 charset 头——必须显式解码，不能靠 httpx 猜。"""
    body = "13^x^y^芬超,芬超^,^z$3085206^2026,8,14,23,00,00^2026,8,14,23,00,00^0^周一002^13^2082^386^图尔库国际,英特杜古,国际图尔^2226^VPS瓦萨,VPS華沙,瓦萨^0^0^^^0^0^0^0^2^6^2026,8,14,00,00,00^0.75^0"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode("gbk"))

    with _client_with(handler) as client:
        rows = client.fetch_board()
    assert rows[0].home_names[0] == "图尔库国际"


def test_client_sends_browser_headers_and_referer():
    """欧赔 JS 不带欧指列表页 Referer 会被拒。"""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        rows = ",".join(
            f'"{i}|1|Book{i}|2.0|3.0|4.0|40|30|30|95|2.1|3.1|4.1|40|30|30|95|0.9|0.9|0.9|2026,09-1,13,23,28,00|B*|1|0|0.9|0.9|0.9"'
            for i in range(6)
        )
        return httpx.Response(200, content=f"var game=Array({rows});".encode("gbk"))

    with _client_with(handler) as client:
        client.fetch_euro_odds("3085206")
    assert "Chrome" in seen["user-agent"]
    assert seen["referer"] == "http://odds.titan007.com/"


def test_client_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"")

    with _client_with(handler) as client:
        with pytest.raises(Titan007Error):
            client.fetch_board()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_titan007.py -k client -v`
Expected: FAIL — `ImportError: cannot import name 'Titan007Client'`

- [ ] **Step 3: 写实现**

追加到 `nutmeg/data/titan007.py`：

```python
class Titan007Client:
    """titan007 抓取器。GBK 解码 + 浏览器 UA + 各端点自己的 Referer。

    ``transport`` 注入用于测试（``httpx.MockTransport``），生产留空走真网络。
    """

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )

    def __enter__(self) -> "Titan007Client":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _get_text(self, url: str, *, referer: str) -> str:
        """抓一个端点并按 GBK 解码。

        titan007 不发 charset 头，httpx 会猜成 latin-1 把中文变成乱码——必须显式
        ``decode('gbk')``；少数页面混入非法字节，用 ``errors='replace'`` 容忍（解析
        器的字段数守卫会兜住真正的坏响应）。
        """
        try:
            response = self._client.get(url, headers={"Referer": referer})
        except httpx.HTTPError as exc:
            raise Titan007Error(f"titan007 抓取失败 {url}: {exc}") from exc
        if response.status_code != 200:
            raise Titan007Error(
                f"titan007 抓取失败 {url}: HTTP {response.status_code}"
            )
        return response.content.decode("gbk", errors="replace")

    def fetch_board(self) -> list[Titan007BoardRow]:
        """当日竞彩板面（竞彩号 ↔ 007 id）。"""
        return parse_board(self._get_text(_BOARD_URL, referer=_BOARD_REFERER))

    def fetch_euro_odds(self, match_id: str) -> list[Titan007BookQuote]:
        """某场各家国际欧赔（初赔 + 即时赔）。"""
        url = _EURO_URL_TEMPLATE.format(match_id=match_id)
        return parse_euro_odds(self._get_text(url, referer=_EURO_REFERER))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_titan007.py -v`
Expected: PASS（13 passed）

- [ ] **Step 5: 真网络冒烟（一次性，不入测试套）**

```bash
uv run python -c "
from nutmeg.data.titan007 import Titan007Client
with Titan007Client() as c:
    board = c.fetch_board()
    print('板面', len(board), '场;', board[0].match_no, board[0].match_id, board[0].kickoff)
    q = c.fetch_euro_odds(board[0].match_id)
    print('欧赔', len(q), '家;', [x.company_name for x in q if x.company_id in ('177','545','1129')])
"
```
Expected: 板面 ≥1 场，欧赔 ≥100 家，且列出 Pinnacle/Crown/Lottery Official

- [ ] **Step 6: 提交**

```bash
git add nutmeg/data/titan007.py tests/test_titan007.py
git commit -m "feat(titan007): add the GBK HTTP client with per-endpoint referers

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SP8EoQijFxYgRxEaPkDSkJ"
```

---

## Task 4: 板面对齐 + MarketOdds 组装（drop-in 采集器）

**Files:**
- Create: `tests/test_jczq_titan007_odds.py`
- Create: `nutmeg/services/jczq_titan007_odds.py`

- [ ] **Step 1: 写失败测试**

`tests/test_jczq_titan007_odds.py`：

```python
"""单测 ``jczq_titan007_odds`` —— 竞彩号对齐、开球守卫、书目筛选、MarketOdds 组装。

全部注入假 fetcher，无网络。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from nutmeg.data.titan007 import Titan007BoardRow, Titan007BookQuote, Titan007ParseError
from nutmeg.services.jczq_titan007_odds import (
    ALL_BOOKS,
    SHARP_BOOKS,
    collect_bold_odds_titan007,
)


def _sporttery(*rows: tuple[str, str, str, str, str]) -> dict:
    """构造 getMatchCalculatorV1 形状：(竞彩号, 主, 客, matchDate, matchTime)。"""
    return {
        "matchInfoList": [
            {
                "businessDate": "2026-09-14",
                "subMatchList": [
                    {
                        "matchNumStr": no,
                        "homeTeamAbbName": home,
                        "awayTeamAbbName": away,
                        "matchDate": date,
                        "matchTime": time,
                        "matchStatus": "Selling",
                        "businessDate": "2026-09-14",
                    }
                    for no, home, away, date, time in rows
                ],
            }
        ]
    }


def _board_row(no: str, mid: str, kickoff: str) -> Titan007BoardRow:
    return Titan007BoardRow(
        match_id=mid,
        match_no=no,
        kickoff=datetime.fromisoformat(kickoff),
        home_names=("主队",),
        away_names=("客队",),
    )


def _quote(cid: str, name: str, opening: list[float], current: list[float]):
    keys = ("home", "draw", "away")
    return Titan007BookQuote(
        company_id=cid,
        company_name=name,
        opening=dict(zip(keys, opening)),
        current=dict(zip(keys, current)),
        updated_at=datetime(2026, 9, 13, 23, 28),
    )


# 锐盘 3 家（恰好触到 _MIN_CONSENSUS_BOOKS）+ 2 家必排除 + 1 家噪声盘。
_QUOTES = [
    _quote("1129", "Lottery Official", [1.55, 3.65, 4.75], [1.55, 3.65, 4.75]),
    _quote("432", "HK Jockey Club", [1.55, 3.6, 4.7], [1.55, 3.6, 4.7]),
    _quote("177", "Pinnacle", [2.0, 3.4, 3.6], [1.7, 3.8, 5.0]),
    _quote("545", "Crown", [1.8, 3.6, 4.4], [1.8, 3.6, 4.4]),
    _quote("281", "Bet 365", [1.9, 3.5, 4.0], [1.75, 3.7, 4.6]),
    _quote("9999", "Rodeoslot", [9.0, 9.0, 9.0], [9.0, 9.0, 9.0]),
]


def test_aligns_by_jc_number_without_any_alias_table():
    """竞彩号是板面自带的权威键——不经任何中文→英文别名。"""
    value = _sporttery(("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00"))
    out = collect_bold_odds_titan007(
        value,
        run_date="2026-09-14",
        board_fetcher=lambda: [_board_row("周一002", "3085206", "2026-09-14T23:00:00")],
        odds_fetcher=lambda mid: _QUOTES,
    )
    assert set(out) == {"周一002"}
    assert "match_winner" in out["周一002"]


def test_excludes_lottery_official_from_the_international_consensus():
    """竞彩官方就是体彩盘本身；混进来会让『国际 vs 体彩』变成体彩跟自己比。"""
    value = _sporttery(("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00"))
    out = collect_bold_odds_titan007(
        value,
        run_date="2026-09-14",
        board_fetcher=lambda: [_board_row("周一002", "3085206", "2026-09-14T23:00:00")],
        odds_fetcher=lambda mid: _QUOTES,
        books=SHARP_BOOKS,
    )
    market = out["周一002"]["match_winner"]
    # 锐盘白名单只留 Pinnacle + Crown + Bet365；竞彩官方/香港马会/噪声盘全落选
    assert market.bookmaker_count == 3
    assert market.odds["home"] == pytest.approx(1.75, abs=1e-4)  # (1.7+1.8+1.75)/3


def test_populates_opening_odds_the_signal_apifootball_could_never_give():
    value = _sporttery(("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00"))
    out = collect_bold_odds_titan007(
        value,
        run_date="2026-09-14",
        board_fetcher=lambda: [_board_row("周一002", "3085206", "2026-09-14T23:00:00")],
        odds_fetcher=lambda mid: _QUOTES,
        books=SHARP_BOOKS,
    )
    market = out["周一002"]["match_winner"]
    assert market.opening_odds["home"] == pytest.approx(1.9, abs=1e-4)  # (2.0+1.8+1.9)/3
    assert market.opening_odds != market.odds  # drift 不再恒为 0


def test_all_books_mode_keeps_the_noise_but_still_drops_the_excluded():
    value = _sporttery(("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00"))
    out = collect_bold_odds_titan007(
        value,
        run_date="2026-09-14",
        board_fetcher=lambda: [_board_row("周一002", "3085206", "2026-09-14T23:00:00")],
        odds_fetcher=lambda mid: _QUOTES,
        books=ALL_BOOKS,
    )
    # 6 家里排除竞彩官方 + 香港马会，剩 Pinnacle/Crown/Bet365/Rodeoslot
    assert out["周一002"]["match_winner"].bookmaker_count == 4


def test_kickoff_mismatch_skips_the_match():
    """竞彩号每周复用；开球时间不符 = 对到了别的一期，宁可丢场不可错配。"""
    value = _sporttery(("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00"))
    out = collect_bold_odds_titan007(
        value,
        run_date="2026-09-14",
        board_fetcher=lambda: [_board_row("周一002", "3085206", "2026-09-07T23:00:00")],
        odds_fetcher=lambda mid: _QUOTES,
    )
    assert out == {}


def test_match_absent_from_titan_board_degrades_silently():
    value = _sporttery(("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00"))
    out = collect_bold_odds_titan007(
        value,
        run_date="2026-09-14",
        board_fetcher=lambda: [],
        odds_fetcher=lambda mid: _QUOTES,
    )
    assert out == {}


def test_per_match_odds_failure_degrades_only_that_match():
    value = _sporttery(
        ("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00"),
        ("周一003", "科莫", "帕尔马", "2026-09-15", "00:30:00"),
    )

    def flaky(match_id: str):
        if match_id == "3085206":
            raise Titan007ParseError("degraded")
        return _QUOTES

    out = collect_bold_odds_titan007(
        value,
        run_date="2026-09-14",
        board_fetcher=lambda: [
            _board_row("周一002", "3085206", "2026-09-14T23:00:00"),
            _board_row("周一003", "2993786", "2026-09-15T00:30:00"),
        ],
        odds_fetcher=flaky,
    )
    assert set(out) == {"周一003"}


def test_board_fetch_failure_returns_empty_never_raises():
    """板面抓不到 → 空 dict，由 fetch_day 决定不落盘（不覆盖完好快照）。"""

    def boom():
        raise Titan007ParseError("WAF")

    out = collect_bold_odds_titan007(
        _sporttery(("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00")),
        run_date="2026-09-14",
        board_fetcher=boom,
        odds_fetcher=lambda mid: _QUOTES,
    )
    assert out == {}


def test_fair_probability_sums_to_one():
    value = _sporttery(("周一002", "国际图尔", "瓦萨", "2026-09-14", "23:00:00"))
    out = collect_bold_odds_titan007(
        value,
        run_date="2026-09-14",
        board_fetcher=lambda: [_board_row("周一002", "3085206", "2026-09-14T23:00:00")],
        odds_fetcher=lambda mid: _QUOTES,
        books=SHARP_BOOKS,
    )
    fair = out["周一002"]["match_winner"].fair_probability
    assert sum(fair.values()) == pytest.approx(1.0, abs=1e-6)
    assert out["周一002"]["match_winner"].independent is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_jczq_titan007_odds.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.services.jczq_titan007_odds'`

- [ ] **Step 3: 写实现**

`nutmeg/services/jczq_titan007_odds.py`：

```python
"""titan007 国际欧赔采集 → jczq-today 的 ``bold_odds`` 形状。

与 ``jczq_apifootball_odds.collect_bold_odds_apifootball`` **同签名同返回形状**::

    {match_no: {"match_winner": MarketOdds}}

因此对判断层是 drop-in——只换数据源槽位，不动任何选腿逻辑。

相对 API-Football 路径的三点结构性差异：

1. **零别名**。titan007 板面自带竞彩编号，对齐是查表不是匹配。``_utc_date`` /
   ``_resolve`` / ``_find_fixture`` / 两张别名 JSON 在本路径上全部不需要，
   「别名未命中 → 丢国际锚 prior 静默退化」这个失败模式随之消失。
2. **有初赔**。``MarketOdds.opening_odds`` 真正被填上，drift 信号不再恒为 0。
3. **必须筛书**。152 家里既有 Pinnacle/Crown 这样的锐盘，也有 ``Rodeoslot``
   这类噪声盘，更有 **竞彩官方（id 1129）——它就是体彩盘本身**。不排除它，
   「国际 vs 体彩」的冲突信号会变成体彩跟自己比。

本模块只出 ``match_winner``。大小球/亚盘住在另外两个 AES 加密的端点，属后续阶段；
在此之前由 ``merge_bold_odds`` 用 API-Football/500.com 兜底补 ``over_under``。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from nutmeg.data.fcom500 import MarketOdds, _devig
from nutmeg.data.titan007 import Titan007BoardRow, Titan007BookQuote

logger = logging.getLogger(__name__)

__all__ = [
    "ALL_BOOKS",
    "SHARP_BOOKS",
    "BookSelection",
    "collect_bold_odds_titan007",
    "collect_bold_odds_titan007_live",
]

_OUTCOME_KEYS = ("home", "draw", "away")

# 竞彩官方 = 体彩盘本身（自指）；香港马会 = 彩池非庄家盘；Betfair = 交易所（佣金口径
# 不同）。三者一律不进「国际共识」，与口径无关。
_EXCLUDED_COMPANY_IDS = frozenset({"1129", "432", "2"})

# 锐盘白名单（公司 id 稳定，按 id 不按名字）。规模（~16 家）刻意贴近 API-Football
# 原本给到的书目量级，使切源时共识口径的变化尽量只来自「书更好」而非「书更多」。
_SHARP_COMPANY_IDS = frozenset(
    {
        "177",  # Pinnacle
        "545",  # Crown 皇冠
        "80",   # Macauslot 澳门
        "649",  # IBCBET
        "474",  # Sbobet
        "281",  # Bet 365
        "115",  # William Hill
        "82",   # Ladbrokes
        "81",   # Vcbet
        "90",   # Easybets
        "104",  # Interwetten
        "16",   # 10BET
        "18",   # 12bet
        "976",  # 18Bet
        "255",  # Bwin
    }
)

# 竞彩号每周复用（周一002 每周都有）。对齐时除竞彩号外再验开球时间，超出此容差
# 即判为对到了别的一期 → 丢场。体彩与 titan007 实测逐分钟一致，容差留给临时改期。
_KICKOFF_TOLERANCE = timedelta(minutes=30)

# 共识至少要这么多家才算数；不足视为该场无信号（宁可缺席不可用单家冒充共识）。
_MIN_CONSENSUS_BOOKS = 3


@dataclass(frozen=True, slots=True)
class BookSelection:
    """一种共识口径：名字 + 判定某家是否入选。"""

    name: str
    include_ids: frozenset[str] | None  # None = 除排除名单外全收

    def accepts(self, quote: Titan007BookQuote) -> bool:
        if quote.company_id in _EXCLUDED_COMPANY_IDS:
            return False
        if self.include_ids is None:
            return True
        return quote.company_id in self.include_ids


SHARP_BOOKS = BookSelection(name="sharp", include_ids=_SHARP_COMPANY_IDS)
ALL_BOOKS = BookSelection(name="all", include_ids=None)


def _avg(values: list[float]) -> float:
    """跨家均赔。沿用 ``jczq_apifootball_odds._avg`` 的 4 位小数口径——切源时聚合
    规则保持不变，使影子期看到的差异只来自书目集合本身。"""
    return round(sum(values) / len(values), 4)


def _board_matches(value: dict, run_date: str) -> list[tuple[str, datetime]]:
    """从 Sporttery 响应抽 (竞彩号, 北京开球时间)。无法解时间的场直接丢（不猜）。"""
    out: list[tuple[str, datetime]] = []
    for day in value.get("matchInfoList") or []:
        for raw in day.get("subMatchList") or []:
            if str(raw.get("matchStatus") or "").casefold() != "selling":
                continue
            business_date = str(raw.get("businessDate") or day.get("businessDate") or "")
            if run_date and business_date and business_date != run_date:
                continue
            match_no = str(raw.get("matchNumStr") or "")
            kickoff_date = str(raw.get("matchDate") or business_date or "")
            kickoff_time = str(raw.get("matchTime") or "").strip()
            if not (match_no and kickoff_date and kickoff_time):
                continue
            try:
                kickoff = datetime.fromisoformat(f"{kickoff_date}T{kickoff_time}")
            except ValueError:
                continue
            out.append((match_no, kickoff))
    return out


def _consensus_market(
    quotes: Iterable[Titan007BookQuote], selection: BookSelection
) -> MarketOdds | None:
    """入选书目 → ``MarketOdds``（即时赔为主盘、初赔入 ``opening_odds``）。

    三路任一缺失、或入选不足 ``_MIN_CONSENSUS_BOOKS`` 家 → ``None``（该场无信号）。
    """
    chosen = [q for q in quotes if selection.accepts(q)]
    if len(chosen) < _MIN_CONSENSUS_BOOKS:
        return None

    per_book: dict[str, list[float]] = {k: [] for k in _OUTCOME_KEYS}
    opening_book: dict[str, list[float]] = {k: [] for k in _OUTCOME_KEYS}
    for quote in chosen:
        for key in _OUTCOME_KEYS:
            per_book[key].append(quote.current[key])
            opening_book[key].append(quote.opening[key])

    if not all(per_book[k] for k in _OUTCOME_KEYS):
        return None

    odds = {key: _avg(values) for key, values in per_book.items()}
    opening = {key: _avg(values) for key, values in opening_book.items()}
    return MarketOdds(
        odds=odds,
        fair_probability=_devig(odds),
        independent=True,
        bookmaker_count=len(chosen),
        opening_odds=opening,
        per_book_odds=per_book,
    )


def collect_bold_odds_titan007(
    value: dict,
    *,
    run_date: str,
    board_fetcher: Callable[[], Iterable[Titan007BoardRow]],
    odds_fetcher: Callable[[str], Iterable[Titan007BookQuote]],
    books: BookSelection = SHARP_BOOKS,
) -> dict[str, dict[str, MarketOdds]]:
    """采集体彩盘各场的 titan007 国际欧赔，键到体彩竞彩号。

    ``board_fetcher()`` 返回 titan007 当日板面（生产包 ``Titan007Client.fetch_board``）；
    ``odds_fetcher(match_id)`` 返回该场各家报价（包 ``fetch_euro_odds``）。两个
    fetcher 注入以便测试无网络。

    返回 ``{match_no: {"match_winner": MarketOdds}}``。板面抓取失败 → 返回空 dict
    （由 ``fetch_day`` 决定不落盘，保住上一版完好快照）；单场失败 → 仅该场缺席。
    **从不崩。**
    """
    board = _board_matches(value, run_date)
    if not board:
        return {}

    try:
        titan_rows = list(board_fetcher())
    except Exception:  # noqa: BLE001 — 降级，从不崩
        logger.warning("titan007-odds: 板面抓取失败，本轮无国际欧赔", exc_info=True)
        return {}

    by_no: dict[str, Titan007BoardRow] = {row.match_no: row for row in titan_rows}

    result: dict[str, dict[str, MarketOdds]] = {}
    for match_no, kickoff in board:
        row = by_no.get(match_no)
        if row is None:
            logger.info("titan007-odds skip %s: titan007 板面无此竞彩号", match_no)
            continue
        drift = abs(row.kickoff - kickoff)
        if drift > _KICKOFF_TOLERANCE:
            logger.warning(
                "titan007-odds skip %s: 开球时间不符（体彩 %s vs 007 %s）——疑似对到别期",
                match_no, kickoff, row.kickoff,
            )
            continue
        try:
            quotes = list(odds_fetcher(row.match_id))
        except Exception:  # noqa: BLE001 — 降级，从不崩
            logger.warning(
                "titan007-odds: 欧赔抓取失败 match_id=%s (%s)",
                row.match_id, match_no, exc_info=True,
            )
            continue
        market = _consensus_market(quotes, books)
        if market is None:
            logger.info(
                "titan007-odds skip %s: %s 口径下入选书目不足", match_no, books.name
            )
            continue
        logger.info(
            "titan007-odds %s → 007=%s (%s 家 %s 口径, drift=%s)",
            match_no, row.match_id, market.bookmaker_count, books.name,
            {k: round(market.odds[k] - market.opening_odds[k], 3) for k in _OUTCOME_KEYS},
        )
        result[match_no] = {"match_winner": market}
    return result


def collect_bold_odds_titan007_live(
    value: dict,
    *,
    run_date: str,
    books: BookSelection = SHARP_BOOKS,
) -> dict[str, dict[str, MarketOdds]]:
    """生产入口：装配真 ``Titan007Client`` 并采集。无 key、无配额。"""
    from nutmeg.data.titan007 import Titan007Client

    client = Titan007Client()
    try:
        return collect_bold_odds_titan007(
            value,
            run_date=run_date,
            board_fetcher=client.fetch_board,
            odds_fetcher=client.fetch_euro_odds,
            books=books,
        )
    finally:
        client.close()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_jczq_titan007_odds.py -v`
Expected: PASS（9 passed）

- [ ] **Step 5: 全套回归 + lint**

Run: `uv run pytest -q && uv run ruff check nutmeg tests`
Expected: 全绿，无新增 failure

- [ ] **Step 6: 提交**

```bash
git add nutmeg/services/jczq_titan007_odds.py tests/test_jczq_titan007_odds.py
git commit -m "feat(titan007): assemble bold_odds from titan007, keyed by 竞彩号

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SP8EoQijFxYgRxEaPkDSkJ"
```

---

## Task 5: 影子期对比命令（判断层不动，只出证据）

**Files:**
- Create: `tests/decision/test_odds_shadow.py`
- Create: `nutmeg/decision/odds_shadow.py`

- [ ] **Step 1: 写失败测试**

`tests/decision/test_odds_shadow.py`：

```python
"""单测影子期对比 —— 逐场逐路比 fair，出可读报告。无网络。"""

from __future__ import annotations

import pytest

from nutmeg.data.fcom500 import MarketOdds
from nutmeg.decision.odds_shadow import compare_sources, render_report


def _market(odds: dict[str, float], *, opening: dict[str, float] | None = None, books: int = 10):
    fair_total = sum(1 / v for v in odds.values())
    return MarketOdds(
        odds=odds,
        fair_probability={k: round((1 / v) / fair_total, 6) for k, v in odds.items()},
        independent=True,
        bookmaker_count=books,
        opening_odds=opening or {},
    )


def test_compare_reports_coverage_of_each_source():
    board = ["周一002", "周一003", "周一004"]
    rows = compare_sources(
        board,
        {"周一002": {"match_winner": _market({"home": 1.7, "draw": 3.8, "away": 5.0})}},
        {
            "周一002": {"match_winner": _market({"home": 1.72, "draw": 3.75, "away": 4.9})},
            "周一003": {"match_winner": _market({"home": 2.1, "draw": 3.3, "away": 3.5})},
        },
    )
    assert [r.match_no for r in rows] == board
    assert rows[0].baseline_fair is not None and rows[0].candidate_fair is not None
    assert rows[1].baseline_fair is None and rows[1].candidate_fair is not None
    assert rows[2].baseline_fair is None and rows[2].candidate_fair is None


def test_compare_computes_max_absolute_fair_delta_in_pp():
    rows = compare_sources(
        ["周一002"],
        {"周一002": {"match_winner": _market({"home": 2.0, "draw": 4.0, "away": 4.0})}},
        {"周一002": {"match_winner": _market({"home": 2.5, "draw": 4.0, "away": 4.0})}},
    )
    # baseline fair home = .5, candidate fair home = .4444 → 5.6pp
    assert rows[0].max_delta_pp == pytest.approx(5.56, abs=0.05)


def test_report_names_both_coverage_counts_and_the_drift_capability():
    rows = compare_sources(
        ["周一002", "周一003"],
        {"周一002": {"match_winner": _market({"home": 1.7, "draw": 3.8, "away": 5.0})}},
        {
            "周一002": {
                "match_winner": _market(
                    {"home": 1.72, "draw": 3.75, "away": 4.9},
                    opening={"home": 2.0, "draw": 3.4, "away": 3.6},
                )
            },
            "周一003": {
                "match_winner": _market(
                    {"home": 2.1, "draw": 3.3, "away": 3.5},
                    opening={"home": 2.2, "draw": 3.3, "away": 3.3},
                )
            },
        },
    )
    report = render_report("2026-09-14", rows)
    assert "1/2" in report  # baseline 覆盖
    assert "2/2" in report  # candidate 覆盖
    assert "初赔" in report

```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/decision/test_odds_shadow.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nutmeg.decision.odds_shadow'`

- [ ] **Step 3: 写实现**

`nutmeg/decision/odds_shadow.py`：

```python
"""国际欧赔换源影子期 —— 双源同抓、逐场比 fair、出证据，**判断层一行不动**。

按 SOP，换数据源改变判断层输入的分布，属判据变更，须先跑影子期出证据再由用户裁定。
本模块只回答三个问题：

1. 覆盖率各是多少（API-Football 受配额所限实测 6/10）。
2. 同一场两源去水 fair 差多少 pp（决定切源是否会翻动既有判读）。
3. 新源的初赔带来多大 drift（这条信号在旧源上恒为 0）。

不写任何 ``bold_odds.json``，不进 sense/构票链路。
"""

from __future__ import annotations

from dataclasses import dataclass

from nutmeg.data.fcom500 import MarketOdds

__all__ = ["ShadowRow", "compare_sources", "render_report", "run_shadow"]

_OUTCOME_KEYS = ("home", "draw", "away")


@dataclass(frozen=True, slots=True)
class ShadowRow:
    """一场在两源下的对照。``None`` 表示该源没盖到这场。"""

    match_no: str
    baseline_fair: dict[str, float] | None
    candidate_fair: dict[str, float] | None
    max_delta_pp: float | None
    candidate_drift_pp: float | None
    candidate_books: int | None


def _fair(markets: dict[str, MarketOdds] | None) -> dict[str, float] | None:
    if not markets:
        return None
    market = markets.get("match_winner")
    if market is None or not market.fair_probability:
        return None
    return dict(market.fair_probability)


def _devig_local(odds: dict[str, float]) -> dict[str, float]:
    inverse = {k: 1.0 / v for k, v in odds.items() if v and v > 0}
    total = sum(inverse.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in inverse.items()}


def _drift_pp(markets: dict[str, MarketOdds] | None) -> float | None:
    """初赔 fair → 即时 fair 的最大单路位移（pp）。无初赔返回 ``None``。"""
    if not markets:
        return None
    market = markets.get("match_winner")
    if market is None or not market.opening_odds or not market.fair_probability:
        return None
    opening_fair = _devig_local(market.opening_odds)
    if not opening_fair:
        return None
    return round(
        max(
            abs(market.fair_probability.get(k, 0.0) - opening_fair.get(k, 0.0))
            for k in _OUTCOME_KEYS
        )
        * 100,
        2,
    )


def compare_sources(
    board: list[str],
    baseline: dict[str, dict[str, MarketOdds]],
    candidate: dict[str, dict[str, MarketOdds]],
) -> list[ShadowRow]:
    """按体彩板面顺序逐场对照两源。``board`` 是竞彩号全集（覆盖率的分母）。"""
    rows: list[ShadowRow] = []
    for match_no in board:
        base_fair = _fair(baseline.get(match_no))
        cand_markets = candidate.get(match_no)
        cand_fair = _fair(cand_markets)
        max_delta = None
        if base_fair and cand_fair:
            max_delta = round(
                max(
                    abs(base_fair.get(k, 0.0) - cand_fair.get(k, 0.0))
                    for k in _OUTCOME_KEYS
                )
                * 100,
                2,
            )
        books = None
        if cand_markets and cand_markets.get("match_winner") is not None:
            books = cand_markets["match_winner"].bookmaker_count
        rows.append(
            ShadowRow(
                match_no=match_no,
                baseline_fair=base_fair,
                candidate_fair=cand_fair,
                max_delta_pp=max_delta,
                candidate_drift_pp=_drift_pp(cand_markets),
                candidate_books=books,
            )
        )
    return rows


def render_report(run_date: str, rows: list[ShadowRow]) -> str:
    """出人读的 Markdown 报告。"""
    total = len(rows)
    base_n = sum(1 for r in rows if r.baseline_fair)
    cand_n = sum(1 for r in rows if r.candidate_fair)
    both = [r for r in rows if r.max_delta_pp is not None]
    drifts = [r.candidate_drift_pp for r in rows if r.candidate_drift_pp is not None]

    lines = [
        f"# 国际欧赔换源影子期 · {run_date}",
        "",
        f"- 板面场数：**{total}**",
        f"- API-Football 覆盖：**{base_n}/{total}**",
        f"- titan007 覆盖：**{cand_n}/{total}**",
    ]
    if both:
        deltas = sorted(r.max_delta_pp for r in both)
        median = deltas[len(deltas) // 2]
        lines += [
            f"- 双源同覆盖 {len(both)} 场，fair 最大单路差：中位 **{median}pp**，"
            f"最大 **{max(deltas)}pp**",
        ]
    else:
        lines.append("- 双源无共同覆盖场次，无法比 fair")
    if drifts:
        lines.append(
            f"- titan007 **初赔→即时 drift**：中位 **{sorted(drifts)[len(drifts) // 2]}pp**，"
            f"最大 **{max(drifts)}pp**（此信号在 API-Football 上恒为 0）"
        )
    else:
        lines.append("- titan007 无初赔数据（异常，应排查）")

    lines += [
        "",
        "| 竞彩号 | AF fair (主/平/客) | 007 fair (主/平/客) | 最大差 pp | 007 drift pp | 007 家数 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    def _fmt(fair: dict[str, float] | None) -> str:
        if not fair:
            return "—"
        return "/".join(f"{fair.get(k, 0.0) * 100:.1f}" for k in _OUTCOME_KEYS)

    for row in rows:
        lines.append(
            f"| {row.match_no} | {_fmt(row.baseline_fair)} | {_fmt(row.candidate_fair)} "
            f"| {row.max_delta_pp if row.max_delta_pp is not None else '—'} "
            f"| {row.candidate_drift_pp if row.candidate_drift_pp is not None else '—'} "
            f"| {row.candidate_books if row.candidate_books is not None else '—'} |"
        )
    return "\n".join(lines) + "\n"


def run_shadow(run_date: str, output_dir) -> str:
    """生产入口：抓体彩板面 → 两源各采一次 → 写报告。返回报告路径。"""
    from pathlib import Path

    from nutmeg.decision.market_data import fetch_sporttery_value_with_fallback
    from nutmeg.services.jczq_apifootball_odds import (
        collect_bold_odds_apifootball_live,
    )
    from nutmeg.services.jczq_titan007_odds import (
        ALL_BOOKS,
        SHARP_BOOKS,
        collect_bold_odds_titan007_live,
    )

    value, _ = fetch_sporttery_value_with_fallback()
    board = [
        str(raw.get("matchNumStr") or "")
        for day in (value.get("matchInfoList") or [])
        for raw in (day.get("subMatchList") or [])
        if str(raw.get("matchStatus") or "").casefold() == "selling"
        and str(raw.get("businessDate") or day.get("businessDate") or "") == run_date
    ]
    board = [no for no in board if no]

    baseline = collect_bold_odds_apifootball_live(value, run_date=run_date)
    sharp = collect_bold_odds_titan007_live(value, run_date=run_date, books=SHARP_BOOKS)
    every = collect_bold_odds_titan007_live(value, run_date=run_date, books=ALL_BOOKS)

    report = render_report(run_date, compare_sources(board, baseline, sharp))
    report += "\n## 口径对照：sharp vs all\n\n"
    report += render_report(run_date, compare_sources(board, sharp, every)).split("\n", 2)[2]

    path = Path(output_dir) / "daily" / run_date / "odds_shadow.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    return str(path)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/decision/test_odds_shadow.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add nutmeg/decision/odds_shadow.py tests/decision/test_odds_shadow.py
git commit -m "feat(shadow): compare API-Football and titan007 fair without touching judgment

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SP8EoQijFxYgRxEaPkDSkJ"
```

---

## Task 6: 挂 CLI 子命令 `decision-odds-shadow`

**Files:**
- Modify: `nutmeg/interfaces/cli/decision.py`

- [ ] **Step 1: 加 `decision-odds-shadow` 子命令**

该文件用 typer（非 argparse），`_OUTPUT_DIR_OPTION` 是既有的共享 Option 常量。在
`nutmeg/interfaces/cli/decision.py` 的 `decision_fetch`（`:41-48`）之后插入：

```python
@_cli.app.command("decision-odds-shadow")
def decision_odds_shadow(
    run_date: str = _cli.typer.Option(..., "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
) -> None:
    """决策本体 · 影子期:API-Football vs titan007 国际欧赔对照报告(judgment 不动)。"""
    from nutmeg.decision.odds_shadow import run_shadow
    _cli.typer.echo(run_shadow(run_date, output_dir))
```

- [ ] **Step 2: 冒烟**

```bash
uv run nutmeg decision-odds-shadow --run-date 2026-09-14
```
Expected: 打印报告路径；`cat` 该文件可见两源覆盖率对照表

- [ ] **Step 3: 回归**

Run: `uv run pytest -q && uv run ruff check nutmeg tests`
Expected: 全绿

- [ ] **Step 4: 提交**

```bash
git add nutmeg/interfaces/cli/decision.py
git commit -m "feat(cli): expose decision-odds-shadow

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SP8EoQijFxYgRxEaPkDSkJ"
```

---

## Task 7: 覆盖率地板守卫（堵部分降级覆盖完好快照）

**背景：** `fetch.py` 现在是 `if bold_odds: persist_bold_odds_snapshot(...)`。空 dict 不落盘（对），但**部分降级会落盘**——早上抓到 10 场、晚上只抓到 2 场，2 场会覆盖 10 场。这是 2026-06「WAF 降级响应覆盖完好快照」的同类死法，换源后书目/端点更多，触发面更大。

**Files:**
- Modify: `tests/decision/test_fetch.py`（若不存在则新建）
- Modify: `nutmeg/decision/fetch.py`

- [ ] **Step 1: 确认现有测试文件位置**

Run: `ls tests/decision/ | grep -i fetch || echo "无 — 新建 tests/decision/test_fetch.py"`
Expected: 输出文件名或 "无"

- [ ] **Step 2: 写失败测试**

追加（或新建）到 `tests/decision/test_fetch.py`：

```python
def test_partial_coverage_does_not_overwrite_a_richer_snapshot(tmp_path):
    """晚间只抓到 2 场，不得覆盖早间已落的 10 场——部分降级是假空盘的变体。"""
    import json

    from nutmeg.decision.fetch import fetch_day

    run_date = "2026-09-14"
    value = {
        "matchInfoList": [
            {
                "businessDate": run_date,
                "subMatchList": [
                    {
                        "matchNumStr": f"周一{i:03d}",
                        "matchStatus": "Selling",
                        "businessDate": run_date,
                    }
                    for i in range(1, 11)
                ],
            }
        ]
    }
    rich = {f"周一{i:03d}": {"match_winner": {}} for i in range(1, 11)}
    path = tmp_path / "daily" / run_date / "bold_odds.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rich, ensure_ascii=False), encoding="utf-8")

    fetch_day(
        run_date,
        tmp_path,
        sporttery_fetcher=lambda: (value, "sporttery"),
        euro_fetcher=lambda v, d: {"周一002": {"match_winner": {}}},
    )

    kept = json.loads(path.read_text(encoding="utf-8"))
    assert len(kept) == 10, "部分降级不得覆盖更完整的快照"
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/decision/test_fetch.py -k partial_coverage -v`
Expected: FAIL — `assert 1 == 10`

- [ ] **Step 4: 写实现**

在 `nutmeg/decision/fetch.py` 中，把落盘那段从 `if bold_odds:` 改为带地板守卫。在 `fetch_day` 内、`persist_bold_odds_snapshot` 调用之前插入：

```python
def _existing_bold_odds_count(run_date: str, output_dir) -> int:
    """已落 ``bold_odds.json`` 的场数；无文件/坏文件按 0（不挡首次落盘）。"""
    import json
    from pathlib import Path

    path = Path(output_dir) / "daily" / run_date / "bold_odds.json"
    if not path.exists():
        return 0
    try:
        return len(json.loads(path.read_text(encoding="utf-8")) or {})
    except (OSError, ValueError):
        return 0
```

并把落盘分支改成：

```python
    if bold_odds:
        previous = _existing_bold_odds_count(run_date, output_dir)
        if len(bold_odds) < previous:
            # 部分降级：本轮拿到的比上一版还少。宁可留旧快照也不覆盖——这是
            # 2026-06「WAF 降级响应覆盖完好快照」的同类死法。
            logger.warning(
                "decision-fetch %s: 本轮国际欧赔 %d 场 < 已存 %d 场,拒绝覆盖快照",
                run_date, len(bold_odds), previous,
            )
        else:
            persist_bold_odds_snapshot(run_date, output_dir, bold_odds)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/decision/test_fetch.py -v`
Expected: PASS

- [ ] **Step 6: 回归 + 提交**

```bash
uv run pytest -q && uv run ruff check nutmeg tests
git add nutmeg/decision/fetch.py tests/decision/test_fetch.py
git commit -m "fix(fetch): refuse to overwrite a richer bold_odds snapshot

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SP8EoQijFxYgRxEaPkDSkJ"
```

---

## Task 8（用户裁决门 · 不得自行执行）: 切主源

**前置条件——三条全部满足方可执行，缺一即停并回报用户：**

1. 影子期已连跑 **≥ 3 个板面日**，`odds_shadow.md` 报告齐备。
2. titan007 覆盖率每日 **≥ API-Football**，且无「开球时间不符」告警。
3. 用户看过报告并**显式批准**切源，包括在 `sharp` 与 `all` 两种口径中选定一种。

**⛔ 这一步改变判断层输入分布，属判据变更。执行体不得自行决定，必须由 Jun 拍板。**

**Files:**
- Modify: `nutmeg/decision/fetch.py:32-39`（`_default_euro_fetcher`）
- Modify: `nutmeg/decision/closing.py:36`（收盘链同源）

- [ ] **Step 1: 改主源，API-Football 退备源**

把 `_default_euro_fetcher` 改为 titan007 主、API-Football 备，用既有的 `merge_bold_odds` 合并（primary 优先、fallback 补缺，语义现成）：

```python
def _default_euro_fetcher(value: dict, run_date: str) -> dict:
    """生产默认:titan007 国际欧赔主源,API-Football 补缺(含 over_under)。

    titan007 免费无配额、自带竞彩号对齐、带初赔;API-Football Free 档 100 次/天
    仅作兜底,并补 titan007 本阶段不出的 ``over_under`` 盘口。两源都空 → 只落体彩
    快照(优雅降级,与换源前行为一致)。
    """
    from nutmeg.services.jczq_apifootball_odds import (
        collect_bold_odds_apifootball_live,
        merge_bold_odds,
    )
    from nutmeg.services.jczq_titan007_odds import (
        collect_bold_odds_titan007_live,
    )

    primary = collect_bold_odds_titan007_live(value, run_date=run_date)
    try:
        fallback = collect_bold_odds_apifootball_live(value, run_date=run_date)
    except Exception:  # noqa: BLE001 — 备源失败不拖累主源
        logger.warning("decision-fetch: API-Football 备源失败,仅用 titan007", exc_info=True)
        fallback = {}
    return merge_bold_odds(primary, fallback)
```

- [ ] **Step 2: 同样改收盘链**

`nutmeg/decision/closing.py:36` 处的 `collect_bold_odds_apifootball_live` 换成同一个合并入口，避免开盘用 007、收盘用 AF 造成 CLV 轴两端不同源。**先读该文件确认调用点上下文再改。**

- [ ] **Step 3: 回归 + 真链路验证**

```bash
uv run pytest -q && uv run ruff check nutmeg tests
uv run nutmeg decision-fetch --run-date $(date +%F)
python3 -c "
import json,glob
p=sorted(glob.glob('.nutmeg-data/jczq/daily/*/bold_odds.json'))[-1]
d=json.load(open(p))
print(p, len(d), '场')
k=next(iter(d)); m=d[k]['match_winner']
print('样本', k, 'odds', m['odds'], 'opening', m['opening_odds'], 'books', m['bookmaker_count'])
"
```
Expected: 覆盖场数 = 板面场数；`opening_odds` **非空**（换源前恒为 `{}`）

- [ ] **Step 4: 按 skills/verify 配方跑端到端**

Run: `uv run nutmeg decision-am --run-date $(date +%F)` 后人工核对判读是否与影子期报告预期一致

- [ ] **Step 5: 提交**

```bash
git add nutmeg/decision/fetch.py nutmeg/decision/closing.py
git commit -m "feat(odds): promote titan007 to primary, API-Football to fallback

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SP8EoQijFxYgRxEaPkDSkJ"
```

---

## 后续阶段（不在本计划内）

| 项 | 说明 |
| --- | --- |
| 亚盘 / 大小球 | `vip.titan007.com/AsianOdds_n.aspx`、`OverDown_n.aspx`。两页都加载 `/js/aes.js`，数据疑似 AES 加密，难度与欧赔完全不同量级——需独立勘察后另立计划 |
| football-data.co.uk 历史收盘 | 免费 CSV，含 Pinnacle 收盘 + 亚盘（`PAHH`/`PAHA`），2000/01→今。`soccerdata.MatchHistory` 直读，给 CLV 轴真基准。与本计划完全正交，可并行 |
| 别名链路退役 | 切源稳定后，`jczq_national_team_aliases.json` / `jczq_club_team_aliases.json` / `alias_audit` / `alias_propose` 在欧赔路径上失去唯一用途；退役前须确认 `jczq_match_align` / `sync` 等其他消费者 |
