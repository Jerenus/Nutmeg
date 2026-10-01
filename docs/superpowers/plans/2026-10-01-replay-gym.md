# Replay Gym Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `nutmeg gym run --policy …` 在 134 个竞彩板面日 + 42 期足彩上回放任意决策规则，按真实赛果与官方奖金精确结算，产出逐日 ¥ 账、CI、回撤、regret、regime 分桶；`gym verify` 复现 9 月真票净额 −¥4,721。

**Architecture:** 新包 `nutmeg/gym/`：`prizes`（官方奖金缓存）→ `board`（只装下单时刻可得信息的历史板面/期次）→ `payout`（竞彩复用 `settle_slip` + 过关方式合法性；足彩任九/胜负彩一二等奖 + 作废场）→ `policy`（协议 + 注册表）→ `policies/*`（基线与候选）→ `run`（循环、账、CI、regret）→ `report`；CLI `nutmeg interfaces/cli/gym.py`。spec：`docs/superpowers/specs/2026-10-01-replay-gym-design.md`。

**Tech Stack:** Python 3.13、typer、pytest；现有 `nutmeg/decision/betslip.py`、`structure_space.py`、`jczq_combos.py`、`dcfit.py`、`bankroll.py`、`nutmeg/ontology/ingest/sporttery.py`。

---

## File Structure

| 文件 | 责任 |
|---|---|
| `nutmeg/gym/__init__.py` | 空 |
| `nutmeg/gym/prizes.py` | `build_prize_cache(zucai_dir, *, fetcher, page_size)` → `zucai/official-prizes.json`；`load_prizes(zucai_dir)` |
| `nutmeg/gym/board.py` | `JczqBoard`、`ZucaiIssue`、`load_jczq_board(data_dir, day)`、`load_zucai_issue(data_dir, issue)`、`list_days/list_issues` |
| `nutmeg/gym/payout.py` | `check_jczq_legal(slip, board)`、`settle_jczq(slip, board)`、`zucai_winning_notes(faces, results, void)`、`settle_zucai(slip, issue)` |
| `nutmeg/gym/policy.py` | `Ctx`、`Policy` Protocol、`REGISTRY`、`register(name, version)`、`get(name)` |
| `nutmeg/gym/policies/{__init__,baseline,jczq,zucai,real}.py` | 策略 |
| `nutmeg/gym/run.py` | `run_gym(...)` → `GymResult`；`summarize(ledger)`；`bootstrap_days`、`max_drawdown`、`regime_of` |
| `nutmeg/gym/report.py` | `render(result) -> str` |
| `nutmeg/interfaces/cli/gym.py` | `nutmeg gym prizes-cache / verify / run` |
| tests | `tests/gym/test_prizes.py`、`test_board.py`、`test_payout.py`、`test_policies.py`、`test_run.py`、`tests/test_cli_gym.py` |

---

### Task 1: 官方奖金缓存

**Files:** Create `nutmeg/gym/__init__.py`, `nutmeg/gym/prizes.py`; Test `tests/gym/__init__.py`, `tests/gym/test_prizes.py`

- [ ] **Step 1: 失败测试**

```python
# tests/gym/test_prizes.py
import json
from pathlib import Path

from nutmeg.gym.prizes import build_prize_cache, load_prizes

ITEM = {"lotteryDrawNum": "26127", "lotteryDrawTime": "2026-09-18 21:00:00",
        "lotterySaleEndtime": "2026-09-16 17:30:00",
        "lotteryDrawResult": "3 3 0 0 3 3 1 3 3 0 3 0 3 *",
        "totalSaleAmount": "15,520,204", "totalSaleAmountRj": "13,999,718",
        "prizeLevelList": [{"prizeLevel": "一等奖", "stakeCount": "401", "stakeAmount": "17,339"},
                           {"prizeLevel": "二等奖", "stakeCount": "9,340", "stakeAmount": "319"}],
        "prizeLevelListRj": [{"prizeLevel": "任选9场", "stakeCount": "50,908", "stakeAmount": "176"}]}
BAD = {"lotteryDrawNum": "26135", "lotteryDrawResult": "", "prizeLevelList": [], "prizeLevelListRj": []}


def test_cache_parses_void_matches_and_comma_numbers(tmp_path: Path) -> None:
    zdir = tmp_path / "zucai"
    zdir.mkdir()
    path = build_prize_cache(zdir, fetcher=lambda url: {"value": {"list": [ITEM, BAD]}}, page_size=2)
    doc = json.loads(path.read_text(encoding="utf-8"))
    row = doc["issues"]["26127"]
    assert row["results"] == "3 3 0 0 3 3 1 3 3 0 3 0 3 *" and row["void_matches"] == [14]
    assert row["renjiu"] == {"stake_count": 50908, "stake_amount": 176.0}
    assert row["sfc_first"]["stake_amount"] == 17339.0 and row["sfc_second"]["stake_count"] == 9340
    assert row["sale_amount_rj"] == 13999718.0 and "26135" not in doc["issues"]   # 未开奖不入
    assert load_prizes(zdir)["26127"]["draw_date"] == "2026-09-18"


def test_cache_merges_incrementally(tmp_path: Path) -> None:
    zdir = tmp_path / "zucai"
    zdir.mkdir()
    build_prize_cache(zdir, fetcher=lambda url: {"value": {"list": [ITEM]}}, page_size=1)
    newer = {**ITEM, "lotteryDrawNum": "26128", "lotteryDrawResult": "3 1 0 3 1 0 3 1 0 3 1 0 3 1"}
    build_prize_cache(zdir, fetcher=lambda url: {"value": {"list": [newer]}}, page_size=1)
    assert set(load_prizes(zdir)) == {"26127", "26128"}
```

- [ ] **Step 2:** `uv run pytest tests/gym/test_prizes.py -q` → FAIL (ModuleNotFoundError)
- [ ] **Step 3: 实现**

```python
# nutmeg/gym/prizes.py
"""官方奖金缓存（gym 的派奖源）：gameNo=90 历史页一次抓 N 期，含作废场（*）与逗号数字。

磁盘上此前只有 26112 存过奖金；gym 结算足彩必须有当期每注奖金，缺就跳过不猜。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from nutmeg.decision.zucai_official import API_URL, _UA, _num

CACHE = "official-prizes.json"
VALID = {"3", "1", "0", "*"}


def _prize(rows, level=None):
    for p in rows or []:
        if level is None or p.get("prizeLevel") == level:
            count, amount = _num(p.get("stakeCount")), _num(p.get("stakeAmount"))
            if count is not None and amount is not None:
                return {"stake_count": int(count), "stake_amount": amount}
    return None


def parse_item(item: dict) -> tuple[str, dict] | None:
    codes = str(item.get("lotteryDrawResult") or "").split()
    if len(codes) != 14 or any(c not in VALID for c in codes):
        return None
    levels = item.get("prizeLevelList") or []
    return str(item.get("lotteryDrawNum")), {
        "draw_date": str(item.get("lotteryDrawTime") or "")[:10],
        "sale_end": item.get("lotterySaleEndtime"),
        "results": " ".join(codes),
        "void_matches": [i + 1 for i, c in enumerate(codes) if c == "*"],
        "renjiu": _prize(item.get("prizeLevelListRj")),
        "sfc_first": _prize(levels, "一等奖"),
        "sfc_second": _prize(levels, "二等奖"),
        "sale_amount_sfc": _num(item.get("totalSaleAmount")),
        "sale_amount_rj": _num(item.get("totalSaleAmountRj")),
    }


def _default_fetcher(url: str) -> dict:
    import httpx

    resp = httpx.get(url, headers={"User-Agent": _UA, "Referer": "https://www.sporttery.cn/"},
                     timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def load_prizes(zucai_dir: Path) -> dict[str, dict]:
    path = Path(zucai_dir) / CACHE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("issues") or {}


def build_prize_cache(zucai_dir: Path, *, fetcher=None, page_size: int = 130) -> Path:
    fetch = fetcher or _default_fetcher
    payload = fetch(API_URL.format(page_size=page_size))
    issues = load_prizes(zucai_dir)
    for item in (payload.get("value") or {}).get("list") or []:
        parsed = parse_item(item)
        if parsed:
            issues[parsed[0]] = parsed[1]
    path = Path(zucai_dir) / CACHE
    path.write_text(json.dumps({
        "source": f"sporttery gameNo=90 getHistoryPageListV1 (pageSize={page_size})",
        "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "note": "results 含 * 作废场；renjiu/sfc_* 为每注奖金(元)与中奖注数；sale_* 为销量(元)",
        "issues": dict(sorted(issues.items())),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
```

- [ ] **Step 4:** 测试绿。**Step 5:** `git add nutmeg/gym/__init__.py nutmeg/gym/prizes.py tests/gym/__init__.py tests/gym/test_prizes.py && git commit -m "feat(gym): official zucai prize cache (void matches, comma numbers, incremental)"`

### Task 2: 历史板面与期次

**Files:** Create `nutmeg/gym/board.py`; Test `tests/gym/test_board.py`

- [ ] **Step 1: 失败测试**（tmp 数据：一天 `sporttery_markets.json` 两场（其一 single=1）、`jc-results.json`、`closing_odds.json`；一期 `26127-issue.json`、`26127-odds.json`（原始均价 Σ1/x≈1.05）、`official-prizes.json`）

```python
# tests/gym/test_board.py（节选，完整版含夹具函数 _jczq_day/_zucai_issue）
def test_jczq_board_only_exposes_pre_kickoff_information(tmp_path):
    data = _jczq_day(tmp_path, "2026-09-20")
    board = load_jczq_board(data, "2026-09-20")
    m = board.matches["周六001"]
    assert m.had == {"3": 1.85, "1": 3.4, "0": 3.9} and m.hhad["line"] == -1.0
    assert m.single_allowed["had"] is True and board.matches["周六002"].single_allowed["had"] is False
    assert board.results["周六001"] == {"outcome_90": "home", "goals_h": 2, "goals_a": 0}
    vis = board.visible()
    assert vis.results == {} and vis.matches["周六001"].closing_fair is not None
    assert vis.matches["周六001"].belief_market == pytest.approx({"home": 0.4878, "draw": 0.2654, "away": 0.2314}, abs=1e-3)

def test_zucai_issue_devigs_raw_odds_and_carries_prizes(tmp_path):
    data = _zucai_issue(tmp_path, "26127")
    issue = load_zucai_issue(data, "26127")
    assert abs(sum(issue.matches["1"].fair.values()) - 1) < 1e-9
    assert issue.results == "3 3 0 0 3 3 1 3 3 0 3 0 3 *" and issue.void == {14}
    assert issue.prizes["renjiu"]["stake_amount"] == 176.0
    assert issue.visible().prizes is None and issue.visible().results is None

def test_list_days_and_issues_skip_incomplete(tmp_path): ...   # 无 jc-results 的天不进 list_days；无奖金的期不进 list_issues
```

- [ ] **Step 2:** 红。 **Step 3: 实现**

```python
# nutmeg/gym/board.py
"""历史板面/期次：只装"下单时刻可得"的信息；赛果与奖金只给结算器。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from nutmeg.gym.prizes import load_prizes
from nutmeg.ontology.ingest.sporttery import parse_sporttery_markets

FACES = ("home", "draw", "away")
CODE_OF = {"home": "3", "draw": "1", "away": "0"}
FACE_OF = {"3": "home", "1": "draw", "0": "away"}


def devig(odds: dict[str, float]) -> dict[str, float]:
    inv = {k: 1 / v for k, v in odds.items()}
    s = sum(inv.values())
    return {k: v / s for k, v in inv.items()}


@dataclass(frozen=True)
class JczqMatch:
    code: str
    name: str
    league: str
    kickoff_bj: str | None
    had: dict[str, float]                  # {"3","1","0"} 体彩赔率（17:00 快照）
    hhad: dict | None                      # {"line": float, "3","1","0"}
    ttg: dict[str, float] | None           # {"0".."7"}
    crs: dict[str, float] | None
    single_allowed: dict[str, bool]        # {"had": bool, "hhad": bool}
    closing_fair: dict[str, float] | None  # titan007 sharp_fair（开球时刻）
    read_belief: dict[str, float] | None   # 仅 provably_prospective 的研究 belief

    @property
    def belief_market(self) -> dict[str, float]:
        return {FACE_OF[k]: v for k, v in devig(self.had).items()}


@dataclass(frozen=True)
class JczqBoard:
    day: str
    matches: dict[str, JczqMatch]
    results: dict[str, dict] = field(default_factory=dict)   # {code: {outcome_90, goals_h, goals_a}}
    allup: dict[str, list[str]] = field(default_factory=dict)  # {pool: 允许的过关方式}

    def visible(self) -> JczqBoard:
        return replace(self, results={})


@dataclass(frozen=True)
class ZucaiMatch:
    no: str
    name: str
    kickoff_bj: str | None
    fair: dict[str, float]


@dataclass(frozen=True)
class ZucaiIssue:
    issue: str
    sale_deadline: str | None
    matches: dict[str, ZucaiMatch]
    results: str | None = None            # "3 1 0 … *"
    prizes: dict | None = None            # official-prizes 行

    @property
    def void(self) -> set[int]:
        return {i + 1 for i, c in enumerate((self.results or "").split()) if c == "*"}

    def visible(self) -> ZucaiIssue:
        return replace(self, results=None, prizes=None)


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _outcome(gh: int, ga: int) -> str:
    return "home" if gh > ga else ("draw" if gh == ga else "away")


def load_jczq_board(data_dir: Path, day: str, *, with_reads: bool = False) -> JczqBoard:
    data_dir = Path(data_dir)
    day_dir = data_dir / "jczq" / "daily" / day
    doc = _read(day_dir / "sporttery_markets.json", None)
    if doc is None:
        raise FileNotFoundError(f"{day} 无板面快照")
    closing = _read(day_dir / "closing_odds.json", {}) or {}
    results_raw = (_read(data_dir / "jczq" / "jc-results.json", {}) or {}).get(day) or {}
    raw_by_code = {r["matchNumStr"]: r for d in doc.get("matchInfoList") or []
                   for r in d.get("subMatchList") or [] if r.get("businessDate") == day}
    matches: dict[str, JczqMatch] = {}
    for m in parse_sporttery_markets(doc, business_date=day):
        if m.business_date != day:
            continue
        raw = raw_by_code.get(m.match_no) or {}
        had = {q.outcome_key: q.decimal_odds for q in m.quotes if q.market_kind == "had"}
        if len(had) != 3:
            continue
        hhad_q = {q.outcome_key: q.decimal_odds for q in m.quotes if q.market_kind == "hhad"}
        hhad_line = next((q.line for q in m.quotes if q.market_kind == "hhad"), None)
        pools = {p.get("poolCode", "").lower(): p for p in raw.get("poolList") or []}
        ttg_raw = raw.get("ttg") or {}
        crs_raw = raw.get("crs") or {}
        sharp = (closing.get(m.match_no) or {}).get("sharp") or {}
        matches[m.match_no] = JczqMatch(
            code=m.match_no, name=f"{m.home_name}-{m.away_name}", league=m.league_name,
            kickoff_bj=m.scheduled_at,
            had={CODE_OF[k]: v for k, v in had.items()},
            hhad=({"line": float(hhad_line), **{CODE_OF[k]: v for k, v in hhad_q.items()}}
                  if hhad_line not in (None, "") and len(hhad_q) == 3 else None),
            ttg={k[1:]: float(v) for k, v in ttg_raw.items() if k.startswith("s") and k[1:].isdigit()} or None,
            crs={k: float(v) for k, v in crs_raw.items() if k.startswith("s") and v} or None,
            single_allowed={"had": pools.get("had", {}).get("single") == 1,
                            "hhad": pools.get("hhad", {}).get("single") == 1},
            closing_fair=sharp.get("fair_probability"),
            read_belief=None,
        )
    results = {code: {"outcome_90": _outcome(int(r["ft_home"]), int(r["ft_away"])),
                      "goals_h": int(r["ft_home"]), "goals_a": int(r["ft_away"])}
               for code, r in results_raw.items()
               if r.get("ft_home") is not None and r.get("ft_away") is not None}
    allup = {str(p.get("poolCode", "")).lower(): list(p.get("allUp") or [])
             for d in doc.get("matchInfoList") or [] for r in d.get("subMatchList") or []
             for p in r.get("poolList") or []}
    return JczqBoard(day=day, matches=matches, results=results, allup=allup)


def load_zucai_issue(data_dir: Path, issue: str) -> ZucaiIssue:
    zdir = Path(data_dir) / "zucai"
    doc = _read(zdir / f"{issue}-issue.json", None)
    if doc is None:
        raise FileNotFoundError(f"{issue} 无 issue.json")
    odds = {str(m["match_no"]): m for m in (_read(zdir / f"{issue}-odds.json", {}) or {}).get("matches") or []}
    matches: dict[str, ZucaiMatch] = {}
    for m in doc.get("matches") or []:
        no = str(m["match_no"])
        row = odds.get(no)
        if not row:
            continue
        fair = devig({"home": float(row["home"]), "draw": float(row["draw"]), "away": float(row["away"])})
        matches[no] = ZucaiMatch(no=no, name=f"{m.get('home_team')}-{m.get('away_team')}",
                                 kickoff_bj=m.get("kickoff_bj"), fair=fair)
    prize = load_prizes(zdir).get(issue)
    return ZucaiIssue(issue=issue, sale_deadline=doc.get("sale_deadline") or doc.get("sale_stop"),
                      matches=matches, results=prize["results"] if prize else None, prizes=prize)


def list_days(data_dir: Path) -> list[str]:
    data_dir = Path(data_dir)
    results = _read(data_dir / "jczq" / "jc-results.json", {}) or {}
    return sorted(d.name for d in (data_dir / "jczq" / "daily").iterdir()
                  if (d / "sporttery_markets.json").exists() and d.name in results)


def list_issues(data_dir: Path) -> list[str]:
    zdir = Path(data_dir) / "zucai"
    prizes = load_prizes(zdir)
    return sorted(p.name.split("-")[0] for p in zdir.glob("*-issue.json")
                  if (zdir / f"{p.name.split('-')[0]}-odds.json").exists()
                  and p.name.split("-")[0] in prizes)
```

- [ ] **Step 4:** 绿；对生产跑 `python -c "from nutmeg.gym.board import *; print(len(list_days('.nutmeg-data')), len(list_issues('.nutmeg-data')))"` 期望 ≈ 132 / 42。 **Step 5:** commit `feat(gym): historical jczq boards and zucai issues with a visible()/settlement split`

### Task 3: 派奖

**Files:** Create `nutmeg/gym/payout.py`; Test `tests/gym/test_payout.py`

- [ ] **Step 1: 失败测试**

```python
from nutmeg.gym.payout import zucai_winning_notes, check_jczq_legal, settle_jczq, settle_zucai

def test_zucai_winning_notes_first_and_second_prize_with_void():
    faces = {"1": "31", "2": "3", "3": "310"}          # 2×1×3 = 6 注
    results = {"1": "3", "2": "3", "3": "0"}
    assert zucai_winning_notes(faces, results, void=set()) == (1, 3)   # 一等 1 注；二等：场1另1面×1×1 + 场3另2面 = 3
    results_miss = {"1": "0", "2": "3", "3": "0"}                        # 场1 没中
    assert zucai_winning_notes(faces, results_miss, void=set()) == (0, 2)  # 二等：场1的2个面 × 1 × 1
    assert zucai_winning_notes(faces, {"1": "*", "2": "3", "3": "0"}, void={1}) == (2, 2)  # 作废场每面都算中

def test_jczq_legality_requires_two_legs_unless_single_open(board_two_matches):
    single = _slip([("周六001", "3")], combo=(1,))
    assert check_jczq_legal(single, board_two_matches) is None            # 周六001 开单关
    bad = _slip([("周六002", "3")], combo=(1,))
    assert check_jczq_legal(bad, board_two_matches) == "single_not_allowed:周六002"

def test_settle_jczq_uses_board_results_and_settle_zucai_pays_official_prize(...): ...
```

- [ ] **Step 2:** 红。 **Step 3: 实现**

```python
# nutmeg/gym/payout.py
from __future__ import annotations

from itertools import combinations

from nutmeg.decision.betslip import BetSlip, SlipSettlement, settle_slip
from nutmeg.gym.board import JczqBoard, ZucaiIssue


def check_jczq_legal(slip: BetSlip, board: JczqBoard) -> str | None:
    """None=合法；否则原因。单关只在 poolList.single==1 的场允许；串关 2–8 腿。"""
    for leg in slip.legs:
        if leg.key not in board.matches:
            return f"unknown_leg:{leg.key}"
    sizes = tuple(slip.combo_sizes or (len(slip.legs),))
    if any(m > 8 or m < 1 for m in sizes):
        return "bad_combo_size"
    if 1 in sizes:
        for leg in slip.legs:
            if not board.matches[leg.key].single_allowed.get(leg.market, False):
                return f"single_not_allowed:{leg.key}"
    return None


def settle_jczq(slip: BetSlip, board: JczqBoard) -> SlipSettlement:
    return settle_slip(slip, board.results)


def zucai_winning_notes(faces: dict[str, str], results: dict[str, str], *, void: set[int]) -> tuple[int, int]:
    """复式票 → (一等/全对 中奖注数, 二等/13 中 注数)。作废场每个面都算中。"""
    winners, losers = [], []
    for no, chosen in faces.items():
        k = len(chosen)
        if int(no) in void:
            w = k
        else:
            w = 1 if results.get(no) in chosen else 0
        winners.append(w)
        losers.append(k - w)
    first = 1
    for w in winners:
        first *= w
    second = 0
    for j, lose in enumerate(losers):
        rest = 1
        for i, w in enumerate(winners):
            if i != j:
                rest *= w
        second += lose * rest
    return first, second


def settle_zucai(slip: BetSlip, issue: ZucaiIssue) -> dict:
    """{stake, payout, first_notes, second_notes, skipped_reason}。缺奖金 → skipped。"""
    if not issue.prizes or not issue.results:
        return {"stake": slip.stake_yuan, "payout": None, "skipped_reason": "no_official_prize"}
    results = {str(i + 1): c for i, c in enumerate(issue.results.split())}
    faces = {str(k): str(v) for k, v in slip.faces.items()}
    first, second = zucai_winning_notes(faces, results, void=issue.void)
    if slip.channel == "renjiu":
        per = (issue.prizes.get("renjiu") or {}).get("stake_amount")
        payout = first * per * slip.multiplier if per is not None else None
        return {"stake": slip.stake_yuan, "payout": payout, "first_notes": first, "second_notes": 0}
    p1 = (issue.prizes.get("sfc_first") or {}).get("stake_amount") or 0.0
    p2 = (issue.prizes.get("sfc_second") or {}).get("stake_amount") or 0.0
    return {"stake": slip.stake_yuan, "payout": (first * p1 + second * p2) * slip.multiplier,
            "first_notes": first, "second_notes": second}
```

- [ ] **Step 4:** 绿。**Step 5:** commit `feat(gym): exact payouts — jczq legality + settle_slip, zucai first/second prize with void matches`

### Task 4: 策略协议、注册表与首批策略

**Files:** Create `nutmeg/gym/policy.py`, `nutmeg/gym/policies/__init__.py`, `baseline.py`, `jczq.py`, `zucai.py`, `real.py`; Test `tests/gym/test_policies.py`

- [ ] **Step 1: 失败测试**：`flat` 返回 []；`jczq_max_p` 在两场板上返回一张 2 串 1、stake ≤ 400、legs 的 key 在板上、非法票为 0；`jczq_fav_pairs` 只在两场终盘 ≥0.70 时出票；`zucai_max_p` 在 14 场假期次上返回一张 renjiu 复式、notes×2 ≤ 400；`real` 按 placed_at 日取 `betslips.jsonl` 的实票。
- [ ] **Step 2:** 红。 **Step 3: 实现**

```python
# nutmeg/gym/policy.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from nutmeg.decision.betslip import BetSlip
from nutmeg.gym.board import JczqBoard, ZucaiIssue


@dataclass(frozen=True)
class Ctx:
    cap_jczq_day: int = 400
    cap_zucai_slip: int = 400
    cap_day_total: int = 2000
    belief_source: str = "market"        # market | closing | read
    seed: int = 7
    brake_tripped: bool = False          # run 负责算（gym 自己的月账），策略必须空仓
    extra: dict = field(default_factory=dict)


class Policy(Protocol):
    name: str
    version: str
    channels: tuple[str, ...]

    def decide(self, board: JczqBoard | ZucaiIssue, ctx: Ctx) -> list[BetSlip]: ...


REGISTRY: dict[str, Policy] = {}


def register(policy: Policy) -> Policy:
    REGISTRY[policy.name] = policy
    return policy


def get(name: str) -> Policy:
    import nutmeg.gym.policies  # noqa: F401 —— 触发注册

    try:
        return REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"unknown policy {name}; known: {sorted(REGISTRY)}") from exc
```

```python
# nutmeg/gym/policies/jczq.py（核心：板面 → combos 腿 → enumerate_combos → 帽内挑）
from nutmeg.decision.betslip import BetSlip, SlipLeg
from nutmeg.decision.jczq_combos import enumerate_combos
from nutmeg.gym.board import CODE_OF, FACES, JczqBoard
from nutmeg.gym.policy import Ctx, register

def belief_of(m, ctx: Ctx) -> dict[str, float]:
    if ctx.belief_source == "closing" and m.closing_fair:
        return dict(m.closing_fair)
    if ctx.belief_source == "read" and m.read_belief:
        return dict(m.read_belief)
    return m.belief_market

def combo_legs(board: JczqBoard, ctx: Ctx, *, faces_filter=None) -> list[dict]:
    legs = []
    for code, m in sorted(board.matches.items()):
        belief = belief_of(m, ctx)
        options = []
        for faces in ("3", "1", "0", "31", "30", "10"):
            if faces_filter and not faces_filter(m, faces, belief):
                continue
            p = sum(belief[FACE_OF[f]] for f in faces)
            odds = [m.had[f] for f in faces]
            options.append({"market": "had", "faces": faces, "p": p, "odds": odds,
                            "modal_odds": m.had[max(faces, key=lambda f: belief[FACE_OF[f]])]})
        legs.append({"code": code, "name": m.name, "kickoff": m.kickoff_bj, "belief": belief,
                     "prior": m.belief_market, "options": options})
    return legs

def to_slip(day: str, combo: dict, *, tag: str) -> BetSlip:
    legs = [SlipLeg(key=l["code"], name=l["name"], market="had", line=None,
                    selections=tuple(l["faces"]), odds=tuple(l["odds"]), fair=None) for l in combo["legs"]]
    return BetSlip(slip_id=f"gym-{tag}-{day}-{len(legs)}x{combo['notes']}", channel="jczq",
                   placed_at=day, legs=legs, multiplier=1, combo_sizes=(len(legs),))

@register
class JczqMaxP:
    name, version, channels = "jczq_max_p", "v1", ("jczq",)
    def decide(self, board, ctx):
        legs = combo_legs(board.visible(), ctx)
        if len(legs) < 2:
            return []
        picks, spent = [], 0
        for combo in enumerate_combos(legs, max_legs=4, max_notes=4, top=20):
            slip = to_slip(board.day, combo, tag="maxp")
            if spent + slip.stake_yuan > ctx.cap_jczq_day:
                continue
            picks.append(slip); spent += slip.stake_yuan
            if len(picks) >= 3:
                break
        return picks
```
（`jczq_ev_filter`：`faces_filter` 只留 `closing_fair[f]×had[f] > 1` 的单面；`jczq_fav_pairs`：只取 `closing_fair` 最大面 ≥0.70 的场，两两 2 串 1 直到帽；`zucai_max_p`：把 `ZucaiIssue.matches` 转成 `{no: {"fair": fair, "face_status": {f: {"state": "alive"}}}}` 喂 `enumerate_frontier(channel="renjiu", cap_yuan=ctx.cap_zucai_slip, mode="belief")`，取 `max_p` 点生成 `BetSlip(channel="renjiu", faces=point["faces"])`；`zucai_fav_single`：先对 fair≥0.70 的场把 face_status 只留该面、fair<0.20 的面标 `dead`，再同上；`zucai_prescription`：读 `<issue>-final-tickets.json`/`judgment-v1`，无则 []；`real`：`betslips.jsonl` 里 `placed_at==day`（竞彩）或 `issue==issue`（足彩）且 `purchased` 的票原样返回。每条策略 20–40 行，照上面的形状写。）

- [ ] **Step 4:** 绿。**Step 5:** commit `feat(gym): policy protocol + registry; baseline, jczq, zucai and real-ticket policies`

### Task 5: 运行器、账与报告

**Files:** Create `nutmeg/gym/run.py`, `nutmeg/gym/report.py`; Test `tests/gym/test_run.py`

- [ ] **Step 1: 失败测试**：两天板 + 一期足彩的 tmp 数据，跑 `flat` 与 `jczq_max_p` → `GymResult.per_policy["flat"].net == 0`；ledger 每行有 `day/issue, policy, slip_id, stake, payout, net, legal`；`summarize` 的 `max_drawdown ≤ 0`、`ci` 二元；`regret_vs["flat"]` 定义正确；`brake`：构造前三天亏 −3,000 后第四天策略被强制空仓（ledger 行 `forced_flat=True`）。
- [ ] **Step 2:** 红。 **Step 3: 实现**

```python
# nutmeg/gym/run.py
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from nutmeg.decision.bankroll import MONTHLY_STOP_LOSS_YUAN
from nutmeg.gym.board import list_days, list_issues, load_jczq_board, load_zucai_issue
from nutmeg.gym.payout import check_jczq_legal, settle_jczq, settle_zucai
from nutmeg.gym.policy import Ctx, get


@dataclass
class GymResult:
    run_id: str
    policies: list[str]
    ledger: list[dict] = field(default_factory=list)
    per_policy: dict[str, dict] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)


def _month(key: str) -> str:
    return key[:7]


def run_gym(*, data_dir: Path, policies: list[str], days: list[str] | None = None,
            issues: list[str] | None = None, ctx: Ctx = Ctx(), out_dir: Path | None = None,
            run_id: str = "gym") -> GymResult:
    data_dir = Path(data_dir)
    days = days if days is not None else list_days(data_dir)
    issues = issues if issues is not None else list_issues(data_dir)
    result = GymResult(run_id=run_id, policies=list(policies))
    month_net: dict[tuple[str, str], float] = {}     # (policy, month) → 净额，用于止损

    def tripped(policy: str, key: str) -> bool:
        return month_net.get((policy, _month(key)), 0.0) <= -MONTHLY_STOP_LOSS_YUAN

    for day in days:
        try:
            board = load_jczq_board(data_dir, day)
        except FileNotFoundError:
            result.skipped["jczq_no_board"] = result.skipped.get("jczq_no_board", 0) + 1
            continue
        for name in policies:
            pol = get(name)
            if "jczq" not in pol.channels:
                continue
            forced = tripped(name, day)
            slips = [] if forced else pol.decide(board.visible(), ctx)
            for slip in slips:
                reason = check_jczq_legal(slip, board)
                if reason:
                    result.ledger.append({"key": day, "channel": "jczq", "policy": name,
                                          "slip_id": slip.slip_id, "stake": slip.stake_yuan,
                                          "payout": 0.0, "net": 0.0, "legal": reason})
                    continue
                s = settle_jczq(slip, board)
                payout = s.payout_yuan if s.payout_yuan is not None else None
                net = (payout - slip.stake_yuan) if payout is not None else None
                result.ledger.append({"key": day, "channel": "jczq", "policy": name,
                                      "slip_id": slip.slip_id, "stake": slip.stake_yuan,
                                      "payout": payout, "net": net, "legal": None,
                                      "pending_legs": s.pending_legs, "forced_flat": forced})
                if net is not None:
                    month_net[(name, _month(day))] = month_net.get((name, _month(day)), 0.0) + net
    for issue in issues:
        try:
            zi = load_zucai_issue(data_dir, issue)
        except FileNotFoundError:
            result.skipped["zucai_no_issue"] = result.skipped.get("zucai_no_issue", 0) + 1
            continue
        key = (zi.sale_deadline or issue)[:10]
        for name in policies:
            pol = get(name)
            if not ({"renjiu", "shengfucai"} & set(pol.channels)):
                continue
            forced = tripped(name, key)
            slips = [] if forced else pol.decide(zi.visible(), ctx)
            for slip in slips:
                s = settle_zucai(slip, zi)
                net = (s["payout"] - s["stake"]) if s.get("payout") is not None else None
                result.ledger.append({"key": key, "issue": issue, "channel": slip.channel, "policy": name,
                                      "slip_id": slip.slip_id, "stake": s["stake"], "payout": s.get("payout"),
                                      "net": net, "legal": None, "skipped": s.get("skipped_reason"),
                                      "forced_flat": forced})
                if net is not None:
                    month_net[(name, _month(key))] = month_net.get((name, _month(key)), 0.0) + net
    for name in policies:
        result.per_policy[name] = summarize([r for r in result.ledger if r["policy"] == name])
    flat = result.per_policy.get("flat", {"net": 0.0})
    best = max((p["net"] for p in result.per_policy.values()), default=0.0)
    for name, summary in result.per_policy.items():
        summary["regret_vs_flat"] = summary["net"] - flat["net"]
        summary["regret_vs_best"] = summary["net"] - best
    if out_dir:
        out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "ledger.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in result.ledger), encoding="utf-8")
        (out_dir / "summary.json").write_text(
            json.dumps({"run_id": run_id, "policies": result.per_policy, "skipped": result.skipped},
                       ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def summarize(rows: list[dict], *, boots: int = 2000, seed: int = 7) -> dict:
    settled = [r for r in rows if r.get("net") is not None]
    by_day: dict[str, float] = {}
    for r in settled:
        by_day[r["key"]] = by_day.get(r["key"], 0.0) + r["net"]
    daily = [by_day[k] for k in sorted(by_day)]
    stake = sum(r["stake"] for r in settled)
    net = sum(daily)
    rng = random.Random(seed)
    cis = sorted(sum(rng.choice(daily) for _ in daily) for _ in range(boots)) if daily else [0.0]
    return {
        "slips": len(rows), "settled": len(settled), "stake": stake, "net": net,
        "roi": (net / stake) if stake else 0.0, "days": len(daily),
        "ci": [cis[int(0.025 * len(cis))], cis[int(0.975 * len(cis)) - 1]],
        "p_positive": sum(1 for c in cis if c > 0) / len(cis),
        "max_drawdown": max_drawdown(daily),
        "illegal": sum(1 for r in rows if r.get("legal")),
        "pending": sum(1 for r in rows if r.get("net") is None and not r.get("legal")),
    }


def max_drawdown(daily: list[float]) -> float:
    peak = cum = 0.0
    worst = 0.0
    for x in daily:
        cum += x
        peak = max(peak, cum)
        worst = min(worst, cum - peak)
    return worst
```
`report.render(result)`：一张表（策略 | 天/期 | 投入 | 净 | ROI | 回撤 | CI | P(净>0) | 相对空仓 | 相对最优 | 非法 | 未结）+ 每策略 regime 分桶（竞彩按当日 ≥0.70 热门场数 0/1/2+；足彩按任九奖金三分位）。

- [ ] **Step 4:** 绿。**Step 5:** commit `feat(gym): runner with exact accounting, monthly brake, bootstrap CI, drawdown, regret`

### Task 6: CLI + verify

**Files:** Create `nutmeg/interfaces/cli/gym.py`，register in `nutmeg/interfaces/cli/__init__.py`（紧跟 `discovery` 行后）；Test `tests/test_cli_gym.py`

- `nutmeg gym prizes-cache [--page-size 130]` → `build_prize_cache`。
- `nutmeg gym verify`：读 `betslips.jsonl` 全部 `purchased` 票；竞彩按 `placed_at` 日（找不到 leg 的 code 则试次日板）结算；足彩按 `issue` 结算；打印逐票 net 与合计，并与 `scoreboard.json tickets` 的同键 net 并排；两张 hafu 票标 `unsupported`。退出码：合计差 > ¥1（排除 unsupported）则 1。
- `nutmeg gym run --policy a,b --from 2026-05-18 --to 2026-09-30 [--belief closing] [--out .nutmeg-data/analytics/gym/<run_id>]` → 打印 `report.render`。
- [ ] 测试：CliRunner 跑 `gym run --policy flat` 在 tmp 数据上出表；`gym verify` 在 tmp 上合计相等退出 0。
- [ ] commit `feat(gym): CLI prizes-cache / verify / run`

### Task 7: 验收与证据

- [ ] `uv run nutmeg gym verify` 对生产：合计须 = −¥4,721（9 月记分牌）± hafu 两票的说明。不等 → 先修结算再往下。
- [ ] `uv run nutmeg gym run --policy flat,jczq_max_p,jczq_ev_filter,jczq_fav_pairs,zucai_max_p,zucai_fav_single,zucai_prescription,real --out .nutmeg-data/analytics/gym/2026-10-01-tournament`（含 `--belief closing` 一次对照）。
- [ ] 证据 `docs/superpowers/evidence/2026-10-01-replay-gym.md`：verify 结果、八策略表、regime 分桶、训练/测试窗（测试窗＝最近 30 天）、策略数与期望最大 |z|、结论；RUNBOOK 加一行指针（B9 旁：「出票前可用 `gym run --from <30 天前>` 看同一规则最近 30 天的账」）。
- [ ] commit docs。

## Self-Review
- spec §3.1–3.4 → Task 2/3/5；§5 策略 → Task 4；§6 验收 1–3 → Task 6/7；验收 4（<5 分钟）由 Task 7 实测记录。
- 类型一致：`JczqBoard.matches[code].had` 用 "3/1/0" 键（与 `SlipLeg.selections` 同码）；`belief_market` 用 home/draw/away（与 `enumerate_combos`/`dcfit` 同）；`FACE_OF/CODE_OF` 在 board.py 定义、policies 引用。
- 无占位符；`zucai_fav_single`/`real` 等的实现形状已在 Task 4 括号里给出。
