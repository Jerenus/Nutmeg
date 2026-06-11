# fcom500 体彩备源（trade.500.com → sporttery 回退）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** sporttery webapi 被 WAF 拦截/降级时，jczq-today / jczq-tiered 自动回退到 trade.500.com 抓体彩盘面 + had/hhad 官方 sp 价，下游引擎零感知；同时修掉降级响应覆盖完好快照的数据丢失 bug。

**Architecture:** 数据层（`fcom500.py`）扩展现有 `parse_jczq_list` 抽 `<tr>` data 属性 + `data-sp` 赔率，并新增合成器产出 sporttery `getMatchCalculatorV1` 同形 `value` dict；服务层（`jczq_bold_combos.py`）加共享回退 helper 与快照防覆盖守卫；CLI 两个 live 命令换用 helper。spec: `docs/superpowers/specs/2026-06-11-fcom500-sporttery-fallback-design.md`。

**Tech Stack:** Python 3.13 / dataclasses / re / pytest（离线 HTML fixture，无网络）。运行命令一律 `uv run pytest ...`。

**背景知识（实现者必读）：**
- 体彩响应 shape：`value["matchInfoList"]` 是天组列表，每组 `{businessDate, subMatchList: [比赛...]}`；每场比赛 dict 的关键字段见 `nutmeg/services/jczq_bold_combos.py` 的 `bold_matches_from_sporttery`（约 :1972）与 `nutmeg/services/jczq_apifootball_odds.py` 的 `_board_matches`（:104）。
- trade.500.com 行结构（2026-06-11 实测）：每场一个 `<tr class="bet-tb-tr" data-...>`，tr 上自带 `data-matchnum/homesxname/awaysxname/matchdate/matchtime/rangqiu/processdate/isend/simpleleague`；行内 `data-type="nspf"`（胜平负）与 `data-type="spf"`（让球）各 3 个 `<p ... data-value="3|1|0" data-sp="X.XX">`。**注意 `data-awaysxname` 是缩写可能截断（如"名古屋鲸"），队名一律继续用现有 `team-l/r` title 解析出的 `home_team/away_team`。**
- 既有 fixture `tests/fixtures/fcom500/jczq-list.html`（2026-05-17，38 场，全部 `data-isend="1"` 已停售）也带全套属性，用作向后兼容测试。

---

### Task 1: 录制 2026-06-11 真实页面 fixture

**Files:**
- Create: `tests/fixtures/fcom500/jczq-list-20260611.html`

- [ ] **Step 1: 从已存页面截取两行真实 tr + 一行人工停售行**

`/tmp/trade500.html` 是 2026-06-11 抓的真实页面（gb18030）。若已不存在，先重抓：
`curl -s "https://trade.500.com/jczq/" -H "User-Agent: Mozilla/5.0" --max-time 30 -o /tmp/trade500.html`

```bash
python3 - <<'EOF'
import re
html = open('/tmp/trade500.html', encoding='gb18030', errors='ignore').read()
rows = []
for num in ('周四001', '周四002'):
    m = re.search(rf'<tr[^>]*data-matchnum="{num}".*?</tr>', html, re.S)
    assert m, num
    rows.append(m.group(0))
# 人工造一行停售场：复制周四002，改号/改 isend
stopped = rows[1].replace('data-matchnum="周四002"', 'data-matchnum="周四099"')
stopped = stopped.replace('data-isend="0"', 'data-isend="1"')
assert 'data-isend="1"' in stopped
out = ("<!doctype html><html><head><meta charset=\"gb2312\"></head><body><table>\n"
       + "\n".join(rows) + "\n" + stopped + "\n</table></body></html>\n")
open('tests/fixtures/fcom500/jczq-list-20260611.html', 'w', encoding='utf-8').write(out)
print('rows:', len(rows) + 1, 'bytes:', len(out))
EOF
```

- [ ] **Step 2: 烟测——现有解析器能吃这个 fixture（3 场都解析出来）**

```bash
uv run python -c "
from nutmeg.data.fcom500 import parse_jczq_list
html = open('tests/fixtures/fcom500/jczq-list-20260611.html', encoding='utf-8').read()
ms = parse_jczq_list(html)
print([m.match_no for m in ms]); assert len(ms) == 3
"
```
Expected: `['周四001', '周四002', '周四099']`

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/fcom500/jczq-list-20260611.html
git commit -m "test(fcom500): 录制 2026-06-11 trade.500.com 真实行 fixture（含 data-sp 体彩价）"
```

---

### Task 2: 解析器扩展 — had/hhad sp 价 + tr data 属性

**Files:**
- Modify: `nutmeg/data/fcom500.py`（`Fcom500JczqMatch` ≈:120、正则区 ≈:138、`parse_jczq_list` ≈:149）
- Create: `tests/test_fcom500_jczq_board.py`

- [ ] **Step 1: 写失败测试**

```python
"""trade.500.com 体彩备源 — data-sp 解析 + sporttery value 合成 + 回退（spec 2026-06-11）。

离线 fixture：tests/fixtures/fcom500/jczq-list-20260611.html（真实页面截段，
周四001 墨西哥vs南非 / 周四002 韩国vs捷克 / 周四099 人工停售行）。
"""
from __future__ import annotations

from pathlib import Path

from nutmeg.data.fcom500 import parse_jczq_list

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "fcom500"


def _board_html() -> str:
    return (_FIXTURE_DIR / "jczq-list-20260611.html").read_text(encoding="utf-8")


def _board_by_no() -> dict:
    return {m.match_no: m for m in parse_jczq_list(_board_html())}


# ---------------------------------------------------------------------------
# 解析 — 体彩 sp 价 + tr data 属性
# ---------------------------------------------------------------------------


def test_parse_extracts_had_and_hhad_sp() -> None:
    m1 = _board_by_no()["周四001"]
    assert m1.had_sp == {"home": 1.26, "draw": 4.45, "away": 9.00}
    assert m1.hhad_sp == {"home": 2.00, "draw": 3.25, "away": 3.11}
    assert m1.hhad_line == -1.0


def test_parse_extracts_board_metadata() -> None:
    m1 = _board_by_no()["周四001"]
    assert m1.business_date == "2026-06-11"
    assert m1.match_date == "2026-06-12"
    assert m1.match_time == "03:00"
    assert m1.is_selling is True
    # 停售行（data-isend="1"）解析保留但标记不在售
    m99 = _board_by_no()["周四099"]
    assert m99.is_selling is False


def test_parse_old_fixture_backcompat() -> None:
    # 2026-05-17 旧 fixture：38 场不变，新字段也填上（全部已停售）
    html = (_FIXTURE_DIR / "jczq-list.html").read_text(encoding="utf-8")
    matches = parse_jczq_list(html)
    assert len(matches) == 38
    m1 = {m.match_no: m for m in matches}["周日001"]
    assert m1.is_selling is False
    assert m1.hhad_line == 1.0
    assert m1.business_date == "2026-05-17"


def test_parse_missing_sp_degrades_to_empty_dict() -> None:
    # 去掉所有 data-sp 的行 → had_sp/hhad_sp 为空 dict，不崩
    html = _board_html().replace("data-sp=", "data-xx=")
    matches = parse_jczq_list(html)
    assert matches and all(m.had_sp == {} and m.hhad_sp == {} for m in matches)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_fcom500_jczq_board.py -v`
Expected: 4 FAIL，错误形如 `AttributeError: ... no attribute 'had_sp'`

- [ ] **Step 3: 实现**

`nutmeg/data/fcom500.py` — `Fcom500JczqMatch` 末尾追加默认字段（frozen+slots 不变）：

```python
    match_no: str
    fid: str
    home_team: str
    away_team: str
    league: str
    league_short: str
    kickoff: str
    # 体彩备源扩展（spec 2026-06-11）：tr data 属性 + data-sp 官方价
    had_sp: dict[str, float] = field(default_factory=dict)
    hhad_sp: dict[str, float] = field(default_factory=dict)
    hhad_line: float = 0.0
    business_date: str = ""
    match_date: str = ""
    match_time: str = ""
    is_selling: bool = False
```

正则区（`_RE_KICKOFF` 之后）加：

```python
_RE_SP = re.compile(
    r'data-type="(nspf|spf)"\s+data-value="(\d)"\s+data-sp="([\d.]+)"'
)
_SP_OUTCOME = {"3": "home", "1": "draw", "0": "away"}
_RE_RANGQIU = re.compile(r'data-rangqiu="(-?\d+(?:\.\d+)?)"')
_RE_PROCESSDATE = re.compile(r'data-processdate="(\d{4}-\d{2}-\d{2})"')
_RE_MATCHDATE = re.compile(r'data-matchdate="(\d{4}-\d{2}-\d{2})"')
_RE_MATCHTIME = re.compile(r'data-matchtime="(\d{2}:\d{2})"')
_RE_ISEND = re.compile(r'data-isend="(\d+)"')
```

`parse_jczq_list` 的循环内、构造 `Fcom500JczqMatch(` 之前加：

```python
        had_sp: dict[str, float] = {}
        hhad_sp: dict[str, float] = {}
        for market, value_key, sp in _RE_SP.findall(block):
            outcome = _SP_OUTCOME.get(value_key)
            if outcome is None:
                continue
            (had_sp if market == "nspf" else hhad_sp)[outcome] = float(sp)
        rangqiu_m = _RE_RANGQIU.search(block)
        isend_m = _RE_ISEND.search(block)
```

构造调用追加入参：

```python
                had_sp=had_sp,
                hhad_sp=hhad_sp,
                hhad_line=float(rangqiu_m.group(1)) if rangqiu_m else 0.0,
                business_date=(
                    m.group(1) if (m := _RE_PROCESSDATE.search(block)) else ""
                ),
                match_date=(
                    m.group(1) if (m := _RE_MATCHDATE.search(block)) else ""
                ),
                match_time=(
                    m.group(1) if (m := _RE_MATCHTIME.search(block)) else ""
                ),
                is_selling=bool(isend_m and isend_m.group(1) == "0"),
```

⚠️ 循环里已有变量名 `match_no_m`/`fid_m` 等；walrus 的 `m` 别撞名——若该作用域已用 `m`，换 `attr_m`。

- [ ] **Step 4: 跑测试确认通过 + 老解析测试不回归**

Run: `uv run pytest tests/test_fcom500_jczq_board.py tests/test_fcom500.py -v`
Expected: 新 4 个 PASS；`test_fcom500.py` 全部 PASS（38 场计数等不变）

- [ ] **Step 5: Commit**

```bash
git add nutmeg/data/fcom500.py tests/test_fcom500_jczq_board.py
git commit -m "feat(fcom500): parse_jczq_list 抽体彩 had/hhad sp 价 + tr data 属性（让球线/销售日/在售态）"
```

---

### Task 3: 合成器 — `sporttery_value_from_jczq_board`

**Files:**
- Modify: `nutmeg/data/fcom500.py`（`parse_jczq_list` 之后新增函数）
- Modify: `tests/test_fcom500_jczq_board.py`

- [ ] **Step 1: 写失败测试（追加到 test 文件）**

```python
from nutmeg.data.fcom500 import Fcom500JczqMatch, sporttery_value_from_jczq_board
from nutmeg.services.jczq_bold_combos import bold_matches_from_sporttery


def _synth_value() -> dict:
    return sporttery_value_from_jczq_board(parse_jczq_list(_board_html()))


# ---------------------------------------------------------------------------
# 合成 — sporttery getMatchCalculatorV1 同形 value dict
# ---------------------------------------------------------------------------


def test_synth_value_shape() -> None:
    value = _synth_value()
    assert value["nutmegSource"] == "fcom500-fallback"
    (day,) = value["matchInfoList"]
    assert day["businessDate"] == "2026-06-11"
    subs = {s["matchNumStr"]: s for s in day["subMatchList"]}
    s1 = subs["周四001"]
    assert s1["matchStatus"] == "Selling"
    assert s1["homeTeamAbbName"] == "墨西哥"
    assert s1["awayTeamAbbName"] == "南非"
    assert s1["matchDate"] == "2026-06-12"
    assert s1["matchTime"] == "03:00"
    assert s1["had"] == {"h": 1.26, "d": 4.45, "a": 9.00}
    assert s1["hhad"] == {"h": 2.00, "d": 3.25, "a": 3.11, "goalLineValue": "-1"}


def test_synth_excludes_not_selling() -> None:
    (day,) = _synth_value()["matchInfoList"]
    nums = [s["matchNumStr"] for s in day["subMatchList"]]
    assert nums == ["周四001", "周四002"]  # 周四099 停售被排除


def test_synth_groups_by_business_date() -> None:
    def mk(no: str, bdate: str) -> Fcom500JczqMatch:
        return Fcom500JczqMatch(
            match_no=no, fid="1", home_team="甲", away_team="乙",
            league="", league_short="测试", kickoff="",
            had_sp={"home": 2.0, "draw": 3.0, "away": 4.0},
            hhad_sp={}, hhad_line=0.0, business_date=bdate,
            match_date=bdate, match_time="20:00", is_selling=True,
        )

    value = sporttery_value_from_jczq_board(
        [mk("周四001", "2026-06-11"), mk("周五003", "2026-06-12")]
    )
    days = value["matchInfoList"]
    assert [d["businessDate"] for d in days] == ["2026-06-11", "2026-06-12"]
    assert all(len(d["subMatchList"]) == 1 for d in days)


def test_synth_skips_match_with_no_pools_and_empty_input() -> None:
    no_pools = Fcom500JczqMatch(
        match_no="周四050", fid="1", home_team="甲", away_team="乙",
        league="", league_short="", kickoff="",
        business_date="2026-06-11", match_date="2026-06-11",
        match_time="20:00", is_selling=True,
    )
    assert sporttery_value_from_jczq_board([no_pools])["matchInfoList"] == []
    assert sporttery_value_from_jczq_board([])["matchInfoList"] == []


def test_synth_roundtrip_into_bold_matches() -> None:
    # 合成 value 直接喂引擎入口 → BoldMatch，had/hhad 数值一致、ttg/crs 缺省为空
    matches = bold_matches_from_sporttery(
        _synth_value(), run_date="2026-06-11", bold_odds={}
    )
    by_no = {m.match_no: m for m in matches}
    assert set(by_no) == {"周四001", "周四002"}
    m1 = by_no["周四001"]
    assert m1.home == "墨西哥" and m1.away == "南非"
    assert m1.tc_odds == {"home": 1.26, "draw": 4.45, "away": 9.00}
    assert m1.hhad_odds == {"home": 2.00, "draw": 3.25, "away": 3.11}
    assert m1.hhad_line == -1.0
    assert m1.ttg_odds == {} and m1.crs_odds == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_fcom500_jczq_board.py -v`
Expected: 新 5 个 FAIL（`ImportError: cannot import name 'sporttery_value_from_jczq_board'`）

- [ ] **Step 3: 实现（`fcom500.py`，放在 `parse_jczq_list` 之后）**

```python
def sporttery_value_from_jczq_board(
    matches: list[Fcom500JczqMatch],
) -> dict:
    """500.com 竞彩列表 → sporttery ``getMatchCalculatorV1`` 同形 ``value`` dict。

    体彩备源（spec 2026-06-11）：sporttery webapi 被 WAF 拦截/降级时，由
    trade.500.com 的体彩 sp 价合成引擎可直接消费的 value——下游
    （``bold_matches_from_sporttery`` / ``_board_matches`` / 快照 / --replay）
    零感知。只有 had/hhad 两池（trade 列表页所带）；ttg/crs 缺省，引擎
    spec §11.1 原生支持缺池。停售/缺 businessDate/两池全缺的场被排除——
    绝不猜测。顶层 ``nutmegSource`` 标记数据来源，引擎忽略、复盘可见。
    """
    by_date: dict[str, list[dict]] = {}
    for m in matches:
        if not m.is_selling:
            continue
        if not (m.business_date and m.match_date):
            continue
        sub: dict[str, object] = {
            "matchStatus": "Selling",
            "matchNumStr": m.match_no,
            "businessDate": m.business_date,
            "homeTeamAbbName": m.home_team,
            "awayTeamAbbName": m.away_team,
            "leagueAbbName": m.league_short,
            "matchDate": m.match_date,
            "matchTime": m.match_time,
        }
        if len(m.had_sp) == 3:
            sub["had"] = {
                "h": m.had_sp["home"],
                "d": m.had_sp["draw"],
                "a": m.had_sp["away"],
            }
        if len(m.hhad_sp) == 3:
            sub["hhad"] = {
                "h": m.hhad_sp["home"],
                "d": m.hhad_sp["draw"],
                "a": m.hhad_sp["away"],
                "goalLineValue": f"{m.hhad_line:+g}".replace("+", "")
                if m.hhad_line < 0
                else f"{m.hhad_line:g}",
            }
        if "had" not in sub and "hhad" not in sub:
            continue
        by_date.setdefault(m.business_date, []).append(sub)
    return {
        "nutmegSource": "fcom500-fallback",
        "matchInfoList": [
            {"businessDate": business_date, "subMatchList": subs}
            for business_date, subs in sorted(by_date.items())
        ],
    }
```

注：`goalLineValue` 期望字符串 `"-1"`（负带号、正不带号，与 sporttery 原样一致；
`_signed_float` 两种都吃）。`f"{-1.0:+g}".replace("+", "")` 产出 `"-1"`，
`f"{1.0:g}"` 产出 `"1"`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_fcom500_jczq_board.py -v`
Expected: 9 个全 PASS

- [ ] **Step 5: Commit**

```bash
git add nutmeg/data/fcom500.py tests/test_fcom500_jczq_board.py
git commit -m "feat(fcom500): sporttery_value_from_jczq_board 合成器——500.com 板转 getMatchCalculatorV1 同形 value"
```

---

### Task 4: 回退 helper — `fetch_sporttery_value_with_fallback`

**Files:**
- Modify: `nutmeg/services/jczq_bold_combos.py`（`persist_sporttery_snapshot` 附近）
- Modify: `tests/test_fcom500_jczq_board.py`

- [ ] **Step 1: 写失败测试（追加）**

```python
import pytest

from nutmeg.services import jczq_bold_combos
from nutmeg.services.jczq import JczqProviderError


class _StubProvider:
    """SportteryJczqCalculatorProvider 替身：按构造参数返回/抛错。"""

    def __init__(self, *, value=None, error: Exception | None = None):
        self._value = value
        self._error = error

    def fetch(self) -> dict:
        if self._error is not None:
            raise self._error
        return self._value


class _StubFcomClient:
    """Fcom500Client 替身：get() 永远返回 2026-06-11 fixture HTML。"""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url: str) -> str:
        return _board_html()


def _patch_fallback_deps(monkeypatch, *, provider, fcom_client=_StubFcomClient):
    monkeypatch.setattr(
        "nutmeg.services.jczq.SportteryJczqCalculatorProvider",
        lambda: provider,
    )
    monkeypatch.setattr("nutmeg.data.fcom500.Fcom500Client", fcom_client)


# ---------------------------------------------------------------------------
# 回退 helper
# ---------------------------------------------------------------------------


def test_fallback_passthrough_when_primary_healthy(monkeypatch) -> None:
    healthy = {"matchInfoList": [{"businessDate": "2026-06-11", "subMatchList": []}]}
    _patch_fallback_deps(monkeypatch, provider=_StubProvider(value=healthy))
    value, source = jczq_bold_combos.fetch_sporttery_value_with_fallback()
    assert source == "sporttery"
    assert value == healthy


def test_fallback_on_provider_error(monkeypatch) -> None:
    _patch_fallback_deps(
        monkeypatch, provider=_StubProvider(error=JczqProviderError("403"))
    )
    value, source = jczq_bold_combos.fetch_sporttery_value_with_fallback()
    assert source == "fcom500-fallback"
    nums = [
        s["matchNumStr"]
        for day in value["matchInfoList"]
        for s in day["subMatchList"]
    ]
    assert nums == ["周四001", "周四002"]


def test_fallback_on_degraded_empty_value(monkeypatch) -> None:
    # 6/11 形态：errorCode=0 但只有 vtoolsConfig、无 matchInfoList
    _patch_fallback_deps(
        monkeypatch, provider=_StubProvider(value={"vtoolsConfig": {}})
    )
    value, source = jczq_bold_combos.fetch_sporttery_value_with_fallback()
    assert source == "fcom500-fallback"
    assert value["nutmegSource"] == "fcom500-fallback"


def test_fallback_failure_reraises_primary_error(monkeypatch) -> None:
    class _DeadFcomClient(_StubFcomClient):
        def get(self, url: str) -> str:
            raise RuntimeError("market degraded")

    _patch_fallback_deps(
        monkeypatch,
        provider=_StubProvider(error=JczqProviderError("403 primary")),
        fcom_client=_DeadFcomClient,
    )
    with pytest.raises(JczqProviderError, match="403 primary"):
        jczq_bold_combos.fetch_sporttery_value_with_fallback()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_fcom500_jczq_board.py -v -k fallback`
Expected: 4 FAIL（`AttributeError: ... no attribute 'fetch_sporttery_value_with_fallback'`）

- [ ] **Step 3: 实现（`jczq_bold_combos.py`，放在 `persist_sporttery_snapshot` 之前）**

```python
def fetch_sporttery_value_with_fallback() -> tuple[dict, str]:
    """体彩盘面抓取：sporttery 主源 → trade.500.com 备源（spec 2026-06-11）。

    返回 ``(value, source)``；``source`` ∈ {"sporttery", "fcom500-fallback"}。
    回退触发两种情形：主源抛 ``JczqProviderError``（403/网络/errorCode≠0），或
    返回的 value 无非空 ``matchInfoList``（2026-06-11 WAF 降级空壳形态）。备源
    只有 had/hhad 两池。备源也失败/解析 0 场 → 原样抛出主源错误——绝不静默
    出假空盘。
    """
    import logging

    import nutmeg.services.jczq as jczq_service

    logger = logging.getLogger(__name__)
    primary_error: Exception
    try:
        fetched = jczq_service.SportteryJczqCalculatorProvider().fetch()
        value = fetched.get("value") if "value" in fetched else fetched
        if value.get("matchInfoList"):
            return value, "sporttery"
        primary_error = jczq_service.JczqProviderError(
            "Sporttery returned no matchInfoList (degraded/WAF response)"
        )
        logger.warning("sporttery 主源返回空壳（无 matchInfoList），尝试 500.com 备源")
    except jczq_service.JczqProviderError as exc:
        primary_error = exc
        logger.warning("sporttery 主源失败（%s），尝试 500.com 备源", exc)

    try:
        import nutmeg.data.fcom500 as fcom500

        with fcom500.Fcom500Client() as client:
            html = client.get("https://trade.500.com/jczq/")
        board = fcom500.parse_jczq_list(html)
        value = fcom500.sporttery_value_from_jczq_board(board)
        if value.get("matchInfoList"):
            return value, "fcom500-fallback"
        logger.warning("500.com 备源解析 0 场在售比赛")
    except Exception:  # noqa: BLE001 — 备源失败不掩盖主源错误
        logger.warning("500.com 备源也失败", exc_info=True)
    raise primary_error
```

注：`import nutmeg.services.jczq as jczq_service` / `import nutmeg.data.fcom500 as fcom500`
用模块属性访问（而非 `from ... import`），让测试的
`monkeypatch.setattr("nutmeg.services.jczq.SportteryJczqCalculatorProvider", ...)` 生效。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_fcom500_jczq_board.py -v`
Expected: 13 个全 PASS

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/jczq_bold_combos.py tests/test_fcom500_jczq_board.py
git commit -m "feat(jczq): fetch_sporttery_value_with_fallback——sporttery 403/降级自动回退 500.com 备源"
```

---

### Task 5: 快照防覆盖守卫

**Files:**
- Modify: `nutmeg/services/jczq_bold_combos.py`（`persist_sporttery_snapshot` ≈:2042）
- Modify: `tests/test_fcom500_jczq_board.py`

- [ ] **Step 1: 写失败测试（追加）**

```python
# ---------------------------------------------------------------------------
# 快照防覆盖守卫（6/11 数据丢失 bug）
# ---------------------------------------------------------------------------

_NONEMPTY = {"matchInfoList": [{"businessDate": "2026-06-11", "subMatchList": [{"matchNumStr": "周四001"}]}]}
_EMPTY = {"vtoolsConfig": {"offLineSaleStatus": 1}}


def _read_snapshot(tmp_path):
    import json

    path = tmp_path / "daily" / "2026-06-11" / "sporttery_markets.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_guard_refuses_empty_over_nonempty(tmp_path) -> None:
    jczq_bold_combos.persist_sporttery_snapshot("2026-06-11", tmp_path, _NONEMPTY)
    jczq_bold_combos.persist_sporttery_snapshot("2026-06-11", tmp_path, _EMPTY)
    assert _read_snapshot(tmp_path) == _NONEMPTY  # 完好快照未被降级响应冲掉


def test_guard_allows_first_write_even_empty(tmp_path) -> None:
    jczq_bold_combos.persist_sporttery_snapshot("2026-06-11", tmp_path, _EMPTY)
    assert _read_snapshot(tmp_path) == _EMPTY


def test_guard_allows_nonempty_over_anything(tmp_path) -> None:
    jczq_bold_combos.persist_sporttery_snapshot("2026-06-11", tmp_path, _EMPTY)
    jczq_bold_combos.persist_sporttery_snapshot("2026-06-11", tmp_path, _NONEMPTY)
    assert _read_snapshot(tmp_path) == _NONEMPTY


def test_guard_survives_corrupt_existing_snapshot(tmp_path) -> None:
    path = tmp_path / "daily" / "2026-06-11" / "sporttery_markets.json"
    path.parent.mkdir(parents=True)
    path.write_text("not-json", encoding="utf-8")
    jczq_bold_combos.persist_sporttery_snapshot("2026-06-11", tmp_path, _EMPTY)
    assert _read_snapshot(tmp_path) == _EMPTY  # 坏快照可被覆盖、不崩
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_fcom500_jczq_board.py -v -k guard`
Expected: `test_guard_refuses_empty_over_nonempty` FAIL（被覆盖成 _EMPTY）；其余 3 个本来就 PASS（现状行为）

- [ ] **Step 3: 实现——替换 `persist_sporttery_snapshot` 整个函数体**

```python
def persist_sporttery_snapshot(run_date: str, output_dir, value: dict) -> None:
    """Write the Sporttery response to ``<output_dir>/daily/<run_date>/
    sporttery_markets.json`` so ``--replay`` is reproducible.

    守卫（spec 2026-06-11）：新 ``value`` 无非空 ``matchInfoList`` 且磁盘已有
    含非空 ``matchInfoList`` 的快照 → 拒绝覆盖。修 2026-06-11 数据丢失 bug——
    WAF 降级空壳把当天 12:00 的完好 20 场快照冲掉（与 v2.2 修过的 ``--replay``
    覆盖派发文件 bug 同族）。
    """
    import json
    import logging
    from pathlib import Path

    path = Path(output_dir) / "daily" / run_date / "sporttery_markets.json"
    if not value.get("matchInfoList") and path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            existing = {}
        if isinstance(existing, dict) and existing.get("matchInfoList"):
            logging.getLogger(__name__).warning(
                "sporttery snapshot guard: 拒绝用空盘响应覆盖 %s 的非空快照",
                run_date,
            )
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
```

- [ ] **Step 4: 跑测试确认通过 + 既有快照测试不回归**

Run: `uv run pytest tests/test_fcom500_jczq_board.py -v && uv run pytest tests/ -k "snapshot or persist" -q`
Expected: 17 个全 PASS；既有 snapshot/persist 相关测试无回归

- [ ] **Step 5: Commit**

```bash
git add nutmeg/services/jczq_bold_combos.py tests/test_fcom500_jczq_board.py
git commit -m "fix(jczq): persist_sporttery_snapshot 防覆盖守卫——空盘响应不再冲掉非空快照"
```

---

### Task 6: CLI 接线（jczq-today + jczq-tiered）+ 实机验证

**Files:**
- Modify: `nutmeg/interfaces/cli/jczq.py`（两处 live 分支，≈:566-570 与 ≈:676-680）

- [ ] **Step 1: 改 jczq-tiered live 分支**

现状（≈:565-570）：

```python
        from nutmeg.services.jczq import SportteryJczqCalculatorProvider

        fetched = SportteryJczqCalculatorProvider().fetch()
        value = fetched.get("value") if "value" in fetched else fetched
        persist_sporttery_snapshot(target_date, output_dir, value)
```

改为（`fetch_sporttery_value_with_fallback` 加进文件顶部已有的
`from nutmeg.services.jczq_bold_combos import (...)` 列表）：

```python
        value, board_source = fetch_sporttery_value_with_fallback()
        if board_source != "sporttery":
            _cli.console.print(
                "⚠️ sporttery 主源不可用，已回退 500.com 备源（仅 had/hhad 池）"
            )
        persist_sporttery_snapshot(target_date, output_dir, value)
```

- [ ] **Step 2: 改 jczq-today live 分支（同样改法，≈:676-680）**

同 Step 1 的替换，注意该命令自己的 import 列表也要加
`fetch_sporttery_value_with_fallback`。

- [ ] **Step 3: 全量测试**

Run: `uv run pytest tests/ -q`
Expected: 全 PASS（基线 700+，无回归）

- [ ] **Step 4: 实机端到端验证（sporttery 此刻仍 403 = 天然实验场）**

```bash
uv run nutmeg jczq-today --write .nutmeg-data/jczq/daily/$(date +%Y-%m-%d)/today-packet.md
```

Expected：
- 打印 `⚠️ sporttery 主源不可用，已回退 500.com 备源（仅 had/hhad 池）`
- 不再抛 `JczqProviderError`；决策包 §B1 出现 周四001/002（墨西哥/南非、韩国/捷克）
- `sporttery_markets.json` 顶层带 `"nutmegSource": "fcom500-fallback"` 且含 matchInfoList
- 用 Read 工具读 today-packet.md 确认 §A/§C 基于真实盘面（届时 §29 gap 有体彩价可算）

若 sporttery 已解封：打印无警告、走主源——同样算通过（fallback 不触发是主源健康的正确行为；此时可用单测覆盖的回退路径背书）。

- [ ] **Step 5: Commit**

```bash
git add nutmeg/interfaces/cli/jczq.py
git commit -m "feat(jczq): jczq-today/jczq-tiered 接入体彩备源回退——sporttery 挂掉不再假空盘"
```

---

### Task 7: 收尾

- [ ] **Step 1: 全量回归 + 静态检查**

Run: `uv run pytest tests/ -q && uv run ruff check nutmeg/ tests/`
Expected: 全 PASS、ruff 无新告警

- [ ] **Step 2: 把 memory 里的"该修的 bug"标记为已修**

更新 `~/.claude/projects/-Users-jz71-Projects-Nutmeg/memory/jczq_2026_06_wc_gap_empty_board.md`
第 3 节："该修的 bug"句子改为"已修（2026-06-11 spec fcom500-sporttery-fallback：
persist 守卫 + 500.com 备源回退落地）"。

- [ ] **Step 3: 最终提交（若有散件）+ 汇报**

```bash
git status --short   # 确认无遗漏
git log --oneline -6 # 应见本计划 5-6 个 commit
```
