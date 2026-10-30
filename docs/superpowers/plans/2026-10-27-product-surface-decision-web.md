# 产品形态落到 decision-web :8787 —— 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把设计画布（Artifact StZn5UR5pyiU7acHBGHpxo，V9）的七块板落进现有 decision-web：期页「表即票」+ 取证抽屉 + §3 桥 + 500 票面、竞彩当日板、今天、账房、实验室、手机，引擎一行不动。

**Architecture:** decision-web（`nutmeg/interfaces/decision_web.py`，FastAPI + Jinja 外壳 + `static/decision/*.js` 取 `/api/*` 渲染）已经有当日页 `/day`、实票页 `/betslips`、登记端点 `/action/register-betslip`。新页沿用同一模式。**界面里不做任何推导**：注数、P、V1–V5、刹车、止损、死法清单全部由服务端调用现有 `nutmeg/decision/*` 函数算好返回；JS 只负责渲染和把点击送回 `/api/precheck`。唯一的新写盘是桥记录（`zucai/<期>-bridge.jsonl`）和走现有 `register_slip` 的登记。

**Tech Stack:** Python 3.13 · FastAPI · Jinja2 · 原生 JS（无构建）· pytest + `fastapi.testclient` · uv。

---

## 0. 现状盘点（写计划前核过的事实）

| 画布上的东西 | 现在在哪 | 结论 |
|---|---|---|
| 审票（注数/P/V1–V5） | `decision/review.py: review()`、`review_runner.review_slip()` | 直接用 |
| 止损 / 期级刹车 / 日帽 | `decision/bankroll.py: brake_state / brake_check / day_cap_check / status_line` | 直接用 |
| **预审流水线**（建票→诊断→审票→纪律行→留痕） | **只在 CLI 私有函数里**：`interfaces/cli/betslip.py` 的 `_build_slip / _diagnose / _review / _issue_brake_line / _day_cap_line / _brake_line / _log_preview`，登记的纪律码拼装在 `betslip_register` 函数体里 | **必须先抽出来**（第 0 阶段）。web 的 `/action/register-betslip` 现在自己拼了半份：不记 STOP/BRAKE/DAYCAP 码、不收 deviation/prediction、拒竞彩 |
| 死法清单 | `decision/slip_group.py: death_list / death_list_lines / report_lines` | 直接用 |
| 票形「4单5双」 | `decision/choice_ledger.py: _shape`（私有） | 提升为公开名 `shape_of` |
| 位置式票面 | `decision/betslip.py: parse_faces_row`（只有解析） | 补逆函数 `format_faces_row` |
| §1c 反证矩阵 | `decision/counter_matrix.py: issue_matrices` | 直接用 |
| 足彩初稿 / 参考形 | `zucai/<期>-draft.json`（`judgment draft --write` 产出） | 读文件 |
| **§1 决策表的档 / 六条件 k/n / 默认 / 死门 / 停售前拿不到 / §1c / §1d / 主形 W4** | **只在 `zucai/<期>-packet.md` 散文表里**（`/zucai-packet` 会话产出；六条件计数代码里没有：`structure_tiers.license_score` 是四问旧口径） | **新增结构化旁车** `zucai/<期>-packet.json`，由 `/zucai-packet` 同步写；页面只读不算 |
| 竞彩板面 | `decision/board_rows.py: jczq_rows`（单一实现，受 `tests/test_single_source.py` 守）、`judgment_brief.jczq_brief`、`jczq/daily/<日>/sporttery_markets.json` + `data/sporttery_board.selling_rows` | 直接用 |
| 今天 | `/day/{date}` + `decision/day_view.day_view`（brief / decisions / timeline / retro / launchd） | 换皮 + 加刹车带 |
| 账房 | `decision/account.month_report`（含 `effective_room` 待结计入、deviation / vetoed / draft 三账）、`choice_ledger.build_choices` | 读；缺「逐日净值曲线」一个函数 |
| 实验室 | `account.experiment_board`、`rule_v3_board`、`/observe/*` 五页 | 读 + 链过去 |
| 推送 | `decision/day_broadcast.py`、`notifications/notify.py`、`lineup_watch.py` | 只加页面链接 |

**不做的事**（宪法与定位）：页面不跑抓取、研究、gym、结算；不替 Jun 下单；不产生新判断；否决不拦登记。

## 1. 每一步落在哪、调什么

| 阶段 | 路由（:8787） | 调用的 Python（唯一实现） | 等价的现有命令 | 写盘 |
|---|---|---|---|---|
| 0 预审抽取 | —（CLI 与 web 共用） | 新 `decision/precheck.py` | `betslip preview / preview-set / register` | 无（登记照旧写 `betslips.jsonl`） |
| 1 期页·表即票 | `GET /issue/{期}` `GET /api/issue/{期}` `POST /api/precheck` | `packet_doc.load_packet`、`review_runner.issue_market`、`counter_matrix.issue_matrices`、`bankroll.brake_state/issue_brake`、`precheck.precheck`、`slip_group.death_list` | `judgment brief --issue`、`judgment draft`、`judgment counter-matrix`、`betslip preview --channel renjiu` | 预审留痕（同 CLI，`log_preview`） |
| 2 取证抽屉 | 同上（数据已在 `/api/issue`） | `counter_matrix.issue_matrices` | `judgment counter-matrix --issue` | 无 |
| 3 §3 桥 + B1 | `POST /action/bridge` | 新 `decision/bridge.py`、`review.structure_notes`、`bankroll.brake_check`、`slip_group.death_list`、`precheck.register_reviewed` | `betslip preview-set --plan` → `betslip register --slip-id <期>-B1 --trial` | `zucai/<期>-bridge.jsonl`（追加）、`betslips.jsonl`（B1 试玩） |
| 4 实票 + 500 票面 | `POST /action/register-betslip`（改） | `precheck.register_reviewed`、`betslip.format_faces_row` | `betslip register --deviation … --prediction …` | `betslips.jsonl` |
| 5 竞彩当日板 | `GET /jczq/{日}` `GET /api/jczq/{日}`；复用 `POST /api/precheck` | `board_rows.jczq_rows`、`judgment_brief.jczq_brief`、`sporttery_board.selling_rows`、`precheck.*` | `judgment brief --day`、`betslip preview --channel jczq --legs-file` | 同 4 |
| 6 今天 | `GET /day/{日}`（改） | `day_view.day_view` + `account.month_report` 的 `effective_room` | `day run --job brief`、`account month` | 无 |
| 7 账房 | `GET /ledger/{月}` `GET /api/ledger/{月}` | `account.month_report`、`choice_ledger.build_choices`、新 `account.daily_curve`、`bridge.bridge_ledger` | `account month`、`account choices` | 无 |
| 8 实验室 | `GET /lab` `GET /api/lab` | `account.experiment_board`、`account.rule_v3_board`；链 `/observe/exp/{id}` | `rsi status`、`account month` | 无 |
| 9 口袋窗 | 全部页 ≤390px 可用；推送带链接 | `day_broadcast.render_broadcast`、`lineup_watch` | `day broadcast` | 无 |

**顺序理由**：0 先做，否则第 1 阶段会造出第三份预审拼装（`test_single_source.py` 的精神，也是 web 登记现在漏记止损码的原因）。1→4 是「表即票」主路，Jun 已确认方向。5 复用 0 和 1 的 `/api/precheck`。6–9 是读侧换皮，互不依赖，可并行。

## 2. 文件结构

| 文件 | 职责 | 阶段 |
|---|---|---|
| `nutmeg/decision/precheck.py`（新） | 建票、诊断、审票、纪律行、留痕、带审票登记——CLI 与 web 唯一入口 | 0 |
| `nutmeg/decision/betslip.py`（改） | 加 `format_faces_row` | 0 |
| `nutmeg/decision/choice_ledger.py`（改） | `_shape` → `shape_of` | 0 |
| `nutmeg/interfaces/cli/betslip.py`（改） | 私有 helper 改成调 `precheck` | 0 |
| `nutmeg/decision/packet_doc.py`（新） | 读、校验 `<期>-packet.json` 旁车 | 1 |
| `nutmeg/interfaces/decision_web_issue.py`（新） | 期页与竞彩板的路由注册（`register_issue_routes(app, templates)`），不再加长 515 行的主文件 | 1、5 |
| `nutmeg/interfaces/web/templates/decision/issue.html`（新） | 期页外壳 | 1 |
| `nutmeg/interfaces/web/static/decision/issue.js` `issue.css`（新） | 渲染决策表、草案卡、审票卡；点击送预审 | 1–4 |
| `nutmeg/decision/bridge.py`（新） | §3a 五条自检、§3b 差异格、桥记录读写、§5⑪ 计数 | 3 |
| `templates/decision/jczq.html` + `static/decision/jczq.js`（新） | 竞彩当日板 | 5 |
| `templates/decision/shell.html`（新） | 统一导航 + 刹车带（今天/期/竞彩/账房/实验室） | 6 |
| `templates/decision/ledger.html` `lab.html` + js（新） | 账房、实验室 | 7、8 |
| `.claude/commands/zucai-packet.md`（改） | A 三屏出齐时同写 `<期>-packet.json` | 1 |
| `docs/ARCHITECTURE.md`（改） | decision-web 一节加新路由（改结构同提交更新） | 1、5 |

测试：`tests/decision/test_precheck.py`、`tests/decision/test_packet_doc.py`、`tests/decision/test_bridge.py`、`tests/test_decision_web_issue.py`、`tests/test_decision_web_jczq.py`、`tests/test_decision_web_ledger.py`。

---

## 第 0 阶段：预审流水线抽成唯一实现

### Task 0.1：位置式票面的逆函数

**Files:**
- Modify: `nutmeg/decision/betslip.py`（`parse_faces_row` 之后）
- Test: `tests/decision/test_betslip_faces_row.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/decision/test_betslip_faces_row.py
from nutmeg.decision.betslip import format_faces_row, parse_faces_row

_ROW = "310 10 0 3 310 31 30 * 1 * * * 3 *"


def test_format_is_inverse_of_parse():
    assert format_faces_row(parse_faces_row(_ROW)) == _ROW


def test_format_normalises_face_order_and_marks_unpicked():
    assert format_faces_row({"2": "13", "14": "0"}) == "* 31 * * * * * * * * * * * 0"
```

- [ ] **Step 2: 跑，确认失败**

Run: `uv run pytest tests/decision/test_betslip_faces_row.py -q`
Expected: FAIL，`ImportError: cannot import name 'format_faces_row'`

- [ ] **Step 3: 实现**

```python
def format_faces_row(faces: dict[str, str], *, n_matches: int = SFC_MATCHES) -> str:
    """`{场次: 面集合}` → 位置式整行（500 方案页的写法，`*`＝未选）；`parse_faces_row` 的逆。
    500 app 照这一行逐格点，抄录不再靠人眼对位（26150 过程三失之一）。"""
    return " ".join(parse_faces(faces.get(str(i), "")) or "*" for i in range(1, n_matches + 1))
```

- [ ] **Step 4: 跑，确认通过**

Run: `uv run pytest tests/decision/test_betslip_faces_row.py -q`
Expected: `2 passed`

- [ ] **Step 5: 提交**（先跑 `/verify`）

```bash
git add nutmeg/decision/betslip.py tests/decision/test_betslip_faces_row.py
git commit -m "feat(betslip): format_faces_row —— 位置式票面的逆函数（500 抄录卡用）"
```

### Task 0.2：`shape_of` 公开

**Files:**
- Modify: `nutmeg/decision/choice_ledger.py:29`（`_shape` 改名 `shape_of`，`:125` 调用处同改）
- Test: `tests/decision/test_choice_ledger_shape.py`

- [ ] **Step 1: 写失败测试**

```python
from nutmeg.decision.choice_ledger import shape_of


def test_shape_of_counts_singles_doubles_triples():
    assert shape_of({"13": "3", "8": "3", "2": "31", "4": "10", "1": "310"}) == "2单2双1包"
    assert shape_of({}) == "—"
```

- [ ] **Step 2:** Run `uv run pytest tests/decision/test_choice_ledger_shape.py -q` → FAIL（ImportError）
- [ ] **Step 3:** 把 `def _shape(` 改成 `def shape_of(`，`issue_row`/`settle_form` 里 `_shape(form["faces"])` 改成 `shape_of(form["faces"])`。
- [ ] **Step 4:** Run `uv run pytest tests/decision/test_choice_ledger_shape.py tests/decision -q -k choice` → PASS
- [ ] **Step 5: 提交**

```bash
git add nutmeg/decision/choice_ledger.py tests/decision/test_choice_ledger_shape.py
git commit -m "refactor(choice-ledger): _shape → shape_of（期页草案卡复用）"
```

### Task 0.3：`decision/precheck.py`——从 CLI 搬出预审

**Files:**
- Create: `nutmeg/decision/precheck.py`
- Modify: `nutmeg/interfaces/cli/betslip.py`（`_build_slip` `_zucai_fair` `_diagnose` `_review` `_review_lines` `_issue_brake_line` `_day_cap_line` `_brake_line` `_log_preview` 删除，调用处改调 `precheck`；`betslip_register` 的纪律码拼装改调 `register_reviewed`）
- Test: `tests/decision/test_precheck.py`；回归：`tests/test_cli_betslip_preview.py`、`tests/decision/test_decision_web_betslips.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/decision/test_precheck.py
from nutmeg.decision.betslip import load_slips
from nutmeg.decision.precheck import build_slip, precheck, register_reviewed

_FAIR = {str(i): {"home": 0.5, "draw": 0.3, "away": 0.2} for i in range(1, 15)}


def _slip(faces, **kw):
    return build_slip(slip_id=kw.pop("slip_id", "preview"), channel="renjiu",
                      placed_at="2026-10-27", faces=faces, issue="26151", fair=_FAIR, **kw)


def test_precheck_reports_arithmetic_and_v4(tmp_path):
    ten = "3 3 3 3 3 3 3 3 3 3 * * * *"           # 任九 10 场 → V4 否决
    out = precheck(_slip(ten), tmp_path, log=False)
    assert out["notes"] == 1 and out["stake"] == 2
    assert out["vetoed"] is True
    assert any(v["code"] == "V4" and v["level"] == "veto" for v in out["verdicts"])
    assert out["brake_line"]                       # 月度止损状态行永远在


_NINE = "* 31 * 10 10 * 31 3 3 31 * 10 3 *"     # 3单6双：单 8/9/13，双 2/4/5/7/10/12


def test_precheck_nine_matches_has_p_and_no_v4(tmp_path):
    out = precheck(_slip(_NINE), tmp_path, log=False)
    assert out["notes"] == 64 and out["stake"] == 128
    # 面质量：「3」=0.5，「31」=0.8，「10」=0.5 → 0.5³ × 0.8³ × 0.5³
    assert round(out["p"], 6) == round(0.5 ** 3 * 0.8 ** 3 * 0.5 ** 3, 6)
    assert not any(v["code"] == "V4" for v in out["verdicts"])


def test_register_reviewed_keeps_deviation_and_review_record(tmp_path):
    nine = _NINE
    slip = _slip(nine, slip_id="26151-T1", deviation="fact_self_judged",
                 prediction="门兴 90 分钟赢不了")
    summary = register_reviewed(slip, tmp_path)
    assert "26151-T1" in summary["summary"]
    saved = load_slips(tmp_path, issue="26151")[0]
    assert saved.deviation == "fact_self_judged" and saved.prediction
    assert "review" in saved.diagnosis and "codes" in saved.diagnosis["review"]
```

- [ ] **Step 2:** Run `uv run pytest tests/decision/test_precheck.py -q` → FAIL（`ModuleNotFoundError: nutmeg.decision.precheck`）

- [ ] **Step 3: 实现**（函数体是从 CLI 原样搬来的，只把文件参数换成数据参数）

```python
# nutmeg/decision/precheck.py
"""预审与带审票登记的唯一实现（2026-10-27 产品形态第 0 阶段）。

此前整条流水线只在 `interfaces/cli/betslip.py` 的私有函数里，decision-web 的登记端点自己
拼了半份（不记 STOP/BRAKE/DAYCAP、不收偏离理由）。CLI、期页、竞彩板现在都调这里。
登记是事实：审票与纪律只记录，从不拦登记。
"""
from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from pathlib import Path

from nutmeg.decision.betslip import (
    BetSlip,
    BetslipError,
    SlipLeg,
    first_kickoff,
    load_slips,
    parse_faces_row,
    register_slip,
)

_SEL = {"3": "home", "1": "draw", "0": "away"}


def build_slip(*, slip_id: str, channel: str, placed_at: str, faces: str | None = None,
               legs: list[dict] | None = None, fair: dict | None = None, combo: str | None = None,
               multiplier: int = 1, issue: str = "", scheme_no: str = "", trial: bool = False,
               note: str = "", deviation: str = "", prediction: str = "",
               data_dir: Path = Path(".nutmeg-data")) -> BetSlip:
    face_map: dict[str, str] = {}
    if channel == "jczq":
        if not legs:
            raise BetslipError("竞彩票须给腿（legs）")
        slip_legs = [SlipLeg(key=str(x["key"]), name=x.get("name", ""),
                             market=x.get("market", "had"), line=x.get("line"),
                             selections=tuple(x.get("selections", ())),
                             odds=tuple(x.get("odds", ())), fair=x.get("fair")) for x in legs]
    else:
        if not faces:
            raise BetslipError("足彩票须给票面（faces）")
        face_map = parse_faces_row(faces)
        board = fair if fair is not None else zucai_fair(data_dir, issue)
        slip_legs = [SlipLeg(key=no, market="had", selections=tuple(_SEL[c] for c in f),
                             fair=board.get(no))
                     for no, f in sorted(face_map.items(), key=lambda kv: int(kv[0]))]
    return BetSlip(slip_id=slip_id, channel=channel, placed_at=placed_at, legs=slip_legs,
                   multiplier=multiplier,
                   combo_sizes=tuple(int(c) for c in combo.split(",")) if combo else (),
                   issue=issue, scheme_no=scheme_no, purchased=not trial, note=note,
                   deviation=deviation, prediction=prediction, faces=face_map)


def zucai_fair(data_dir: Path, issue: str) -> dict[str, dict]:
    """足彩整板 fair：legs-base 的判断概率（与 CLI 不给 --fair-file 时同口径）。"""
    from nutmeg.decision.review_runner import issue_belief

    return issue_belief(data_dir, issue)


def diagnose_slip(slip: BetSlip, data_dir: Path, planned=()) -> dict:
    from nutmeg.decision.betslip_diagnosis import (
        DEVIATION_REASONS,
        cross_translators,
        diagnose,
        draft_faces_for,
        peers,
        prescription_for,
    )

    if slip.deviation and slip.deviation not in DEVIATION_REASONS:
        raise ValueError(f"deviation `{slip.deviation}` 不在 {DEVIATION_REASONS}")
    slips = [*load_slips(data_dir), *planned]
    cross = cross_translators(slip, slips, data_dir)
    return diagnose(slip, peers(slip, slips, cross), prescription_for(slip, data_dir), cross,
                    draft=draft_faces_for(slip, data_dir))


def review_verdict(slip: BetSlip, diagnosis: dict, data_dir: Path) -> dict:
    from nutmeg.decision.review import prize_model, review
    from nutmeg.decision.review_runner import issue_market

    market = issue_market(data_dir, slip.issue) if slip.channel != "jczq" else None
    return review(slip, diagnosis, prize_model=prize_model(data_dir), market=market)


def issue_brake_line(slip: BetSlip, data_dir: Path, *, extra_yuan: int = 0) -> str | None:
    if slip.channel == "jczq" or not slip.issue:
        return None
    from nutmeg.decision.bankroll import brake_check

    bought = sum(s.stake_yuan for s in load_slips(data_dir, issue=slip.issue)
                 if s.purchased and s.slip_id != slip.slip_id)
    return brake_check(data_dir, slip.issue, slip.stake_yuan, already_yuan=bought + extra_yuan)


def day_cap_line(slip: BetSlip, data_dir: Path, *, extra_yuan: int = 0) -> str | None:
    from nutmeg.decision.bankroll import day_cap_check

    day = str(slip.placed_at)[:10]
    bought = sum(s.stake_yuan for s in load_slips(data_dir)
                 if s.purchased and s.slip_id != slip.slip_id and str(s.placed_at)[:10] == day)
    return day_cap_check(day, slip.stake_yuan, already_yuan=bought + extra_yuan)


def brake_line(data_dir: Path, placed_at: str) -> str:
    from nutmeg.decision.bankroll import brake_state, status_line

    try:
        when = _date.fromisoformat(str(placed_at)[:10])
    except ValueError:
        when = _date.today()
    return status_line(brake_state(data_dir, when))


def log_preview_safe(data_dir: Path, slip: BetSlip, vetoed: bool) -> str | None:
    """预审留痕；失败返回告警文本（调用方负责让人看见），不抛。"""
    from nutmeg.decision.day_decisions import log_preview

    try:
        keys = [leg.key for leg in slip.legs] or list(slip.faces)
        log_preview(data_dir, placed_at=slip.placed_at, channel=slip.channel, issue=slip.issue,
                    keys=keys, stake=slip.stake_yuan, vetoed=vetoed,
                    now=datetime.now().astimezone(), faces=slip.faces or None,
                    p=slip.hit_probability)
        return None
    except Exception as exc:  # noqa: BLE001
        return f"⚠️预审留痕写入失败（截止播报不会提醒这张票）：{exc!r}"


def precheck(slip: BetSlip, data_dir: Path, *, planned=(), extra_issue_yuan: int = 0,
             extra_day_yuan: int = 0, log: bool = True) -> dict:
    """一张票的全部预审结果（CLI `betslip preview` 与 `/api/precheck` 同一份）。"""
    data_dir = Path(data_dir)
    diagnosis = diagnose_slip(slip, data_dir, planned)
    verdict = review_verdict(slip, diagnosis, data_dir)
    issue_brake = issue_brake_line(slip, data_dir, extra_yuan=extra_issue_yuan)
    day_cap = day_cap_line(slip, data_dir, extra_yuan=extra_day_yuan)
    brake = brake_line(data_dir, slip.placed_at)
    discipline = [x for x in (issue_brake, day_cap) if x]
    vetoed = bool(verdict["vetoed"] or brake.startswith("⛔") or discipline)
    warning = log_preview_safe(data_dir, slip, vetoed) if log else None
    return {"notes": slip.notes, "stake": slip.stake_yuan, "multiplier": slip.multiplier,
            "p": slip.hit_probability, "diagnosis": diagnosis,
            "diagnosis_lines": diagnosis.get("lines", []), "verdicts": verdict["verdicts"],
            "ratio": verdict["ratio"], "review_lines": verdict["lines"],
            "discipline": discipline, "brake_line": brake, "vetoed": vetoed,
            "log_warning": warning}


def register_reviewed(slip: BetSlip, data_dir: Path) -> dict:
    """带审票登记（宪法 §6：审票随票入账）。纪律否决记码不拦登记。"""
    from nutmeg.decision.review import review_record

    data_dir = Path(data_dir)
    slip.diagnosis = diagnose_slip(slip, data_dir)
    slip.first_kickoff = first_kickoff(slip, data_dir)
    try:
        verdict = review_verdict(slip, slip.diagnosis, data_dir)
        slip.diagnosis["review"] = review_record(verdict)
    except Exception as exc:  # noqa: BLE001
        verdict = {"lines": [f"审票失败：{exc!r}"[:160]]}
        slip.diagnosis["review"] = {"error": repr(exc)[:200]}
    brake = brake_line(data_dir, slip.placed_at)
    discipline = [x for x in (issue_brake_line(slip, data_dir), day_cap_line(slip, data_dir),
                              brake) if x and x.startswith("⛔")]
    if discipline and "error" not in slip.diagnosis["review"]:
        record = slip.diagnosis["review"]
        record["vetoed"] = True
        record["codes"] = [*record["codes"],
                           *(["BRAKE"] if any("刹车" in x for x in discipline) else []),
                           *(["DAYCAP"] if any("日帽" in x for x in discipline) else []),
                           *(["STOP"] if any("止损" in x or "已触发" in x
                                             for x in discipline) else [])]
    return {"summary": register_slip(data_dir, slip),
            "lines": [*slip.diagnosis.get("lines", []), *verdict["lines"],
                      *[x for x in discipline if "刹车" in x or "日帽" in x]],
            "after_kickoff": bool(slip.deviation_after_kickoff), "brake_line": brake}
```

CLI 侧：`_build_slip(...)` 的调用改成 `build_slip(...)`（`legs_file` 在 CLI 里先 `json.loads(Path(legs_file).read_text("utf-8"))` 再传 `legs=`，`fair_file` 同理读出再传 `fair=`）；`betslip_preview` 改成调 `precheck(slip, data_dir)` 后照原顺序 echo `diagnosis_lines` / `review_lines` / `brake_line` / `discipline`，`vetoed` 时 `Exit(1)`；`betslip_preview_set` 每张调 `precheck(slip, data_dir, planned=…, extra_issue_yuan=earlier, extra_day_yuan=same_day)`；`betslip_register` 调 `register_reviewed` 后 echo `summary` 与 `lines`，`after_kickoff` 打原来那行警告，最后 echo `brake_line`。

- [ ] **Step 4: 跑新测试 + 回归**

Run: `uv run pytest tests/decision/test_precheck.py tests/test_cli_betslip_preview.py tests/decision/test_decision_web_betslips.py tests/test_single_source.py -q`
Expected: 全 PASS（CLI 输出逐行不变——`test_cli_betslip_preview.py` 的 9 个用例就是这个保证）

- [ ] **Step 5: 提交**（先 `/verify`；pre-commit 跑数分钟，期间别让别的会话改文件）

```bash
git add nutmeg/decision/precheck.py nutmeg/interfaces/cli/betslip.py tests/decision/test_precheck.py
git commit -m "refactor(betslip): 预审流水线抽成 decision/precheck 唯一实现（CLI 与 web 共用）"
```

### Task 0.4：web 登记端点改走 `register_reviewed`

**Files:**
- Modify: `nutmeg/interfaces/decision_web.py:463-513`（`register_betslip`）
- Test: `tests/decision/test_decision_web_betslips.py`（加用例）

- [ ] **Step 1: 写失败测试**（加在现有文件末尾，沿用其 `client` fixture 与 `_register`）

```python
def test_register_keeps_deviation_and_prediction(client, tmp_path):
    r = _register(client, deviation="fact_self_judged", prediction="门兴赢不了")
    assert r.json()["ok"] is True
    row = json.loads((tmp_path / "betslips.jsonl").read_text("utf-8").splitlines()[-1])
    assert row["deviation"] == "fact_self_judged" and row["prediction"] == "门兴赢不了"
    assert "codes" in row["diagnosis"]["review"]


def test_register_jczq_with_structured_legs(client, tmp_path):
    legs = [{"key": "周日006", "market": "had", "selections": ["home"], "odds": [1.22],
             "fair": {"home": 0.702, "draw": 0.173, "away": 0.124}},
            {"key": "周日011", "market": "had", "selections": ["home"], "odds": [1.33],
             "fair": {"home": 0.622, "draw": 0.205, "away": 0.173}}]
    r = client.post("/action/register-betslip", json={
        "slip_id": "20261025-J1", "channel": "jczq", "placed_at": "2026-10-25",
        "legs": legs, "combo": "2", "multiplier": 5})
    assert r.json()["ok"] is True, r.json()
```

- [ ] **Step 2:** Run `uv run pytest tests/decision/test_decision_web_betslips.py -q` → 两条新用例 FAIL（deviation 丢失；竞彩被拒「请用 CLI」）

- [ ] **Step 3: 实现**——端点体换成：

```python
    @app.post("/action/register-betslip")
    def register_betslip(payload: dict = Body(...)) -> Any:  # noqa: B008
        from nutmeg.decision.betslip import BetslipError
        from nutmeg.decision.precheck import build_slip, register_reviewed

        try:
            channel = str(payload.get("channel") or "renjiu")
            if channel == "jczq" and not isinstance(payload.get("legs"), list):
                # 半张票入账比不入账更糟：竞彩必须带结构化腿（竞彩板生成），不接自由文本
                raise BetslipError("竞彩票须带结构化腿（legs 列表）")
            slip = build_slip(
                slip_id=str(payload.get("slip_id") or "").strip(), channel=channel,
                placed_at=str(payload.get("placed_at") or "").strip(),
                faces=payload.get("faces"), legs=payload.get("legs"),
                combo=(str(payload["combo"]) if payload.get("combo") else None),
                multiplier=int(payload.get("multiplier") or 1),
                issue=str(payload.get("issue") or "").strip(),
                scheme_no=str(payload.get("scheme_no") or "").strip(),
                trial=bool(payload.get("trial")), note=str(payload.get("note") or "").strip(),
                deviation=str(payload.get("deviation") or ""),
                prediction=str(payload.get("prediction") or ""), data_dir=_data_dir())
            return {"ok": True, **register_reviewed(slip, _data_dir())}
        except (BetslipError, KeyError, ValueError) as error:
            return {"ok": False, "error": str(error)}
```

注意：旧端点读 `<期>-prep-revision.json` 的 `fair_had`；新口径与 CLI 一致读 legs-base 判断概率（`zucai_fair`）。现有用例 fixture 只造了 prep-revision——把 fixture 补一份 `zucai/26122-legs-base.json`（`{"legs": {"1": {"fair": {...}}, …}}`），而不是保留两种口径。

- [ ] **Step 4:** Run `uv run pytest tests/decision/test_decision_web_betslips.py -q` → PASS
- [ ] **Step 5: 提交**

```bash
git add nutmeg/interfaces/decision_web.py tests/decision/test_decision_web_betslips.py
git commit -m "fix(decision-web): 登记端点走 precheck.register_reviewed（记止损/刹车码、收偏离理由、收竞彩结构化腿）"
```

---

## 第 1 阶段：期页·表即票（`/issue/{期}`）

### Task 1.1：分析包旁车 `<期>-packet.json` 与读取器

**旁车契约**（`/zucai-packet` 出 A 三屏时同写；页面只读，**不从散文反解析**）：

```json
{
  "issue": "26151", "built_at": "2026-10-27T10:25:00+08:00",
  "default": {"action": "空仓", "reason": "许可证层：许可胆 0；账房越线 ¥690；刹车档"},
  "rows": [
    {"no": "13", "tier": "B", "k": 4, "n": 6, "flip": "卡利亚里·弱·价内 → 1(19)",
     "default": "31", "dead": "排0 · 10", "lineup_at": "02:45", "lineup_before_close": false,
     "unknowable": "首发 02:45（停售后 9 小时）；加斯佩里尼「会有调整」",
     "anchor": "门将 Svilar、后腰 Koné 缺；连续 8 个主场进 2+", "hole": "锚方 · 门将 · 价内",
     "c1": {"path": "卡利亚里·弱·价内 → 1(19)", "move": "低位反击、定位球", "q3a": "弱：8 轮 6 球",
            "fav": "罗马近 2 场失 7"},
     "d1": {"cell": "B·锚方·价内·弱·球员", "layer": "四维", "n": 20, "open": "16/2/2",
            "hot_pct": 80, "p1": 71, "diff": 9}}
  ],
  "main_shape": {"label": "W4 4单5双", "faces": {"13": "3", "8": "3", "10": "3", "2": "3",
                 "4": "10", "9": "31", "5": "10", "7": "31", "12": "10"}},
  "alternatives": [{"label": "W1 1单8双", "faces": {"13": "3", "2": "31"}}],
  "signed_bold": []
}
```

D 档行 `c1` 为 `null`；`main_shape` 在「机器默认空仓」时仍给字典主形（§3b 对照对象）。

**Files:**
- Create: `nutmeg/decision/packet_doc.py`
- Modify: `.claude/commands/zucai-packet.md`（A 三屏一节加：「出齐时用 Write 落 `zucai/<期>-packet.json`，字段见 `nutmeg/decision/packet_doc.py` 文档串；§1 表与旁车同源，改表必须同改旁车」）
- Test: `tests/decision/test_packet_doc.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/decision/test_packet_doc.py
import json

from nutmeg.decision.packet_doc import load_packet


def _write(tmp_path, doc):
    z = tmp_path / "zucai"
    z.mkdir(exist_ok=True)
    (z / "26151-packet.json").write_text(json.dumps(doc, ensure_ascii=False), "utf-8")


def test_missing_packet_is_reported_not_raised(tmp_path):
    out = load_packet(tmp_path, "26151")
    assert out["rows"] == [] and out["errors"] == ["缺 26151-packet.json（/zucai-packet 未出旁车）"]


def test_rows_keyed_and_bad_rows_named(tmp_path):
    _write(tmp_path, {"issue": "26151", "rows": [
        {"no": "13", "tier": "B", "k": 4, "n": 6, "default": "31"},
        {"no": "2", "tier": "B"}],
        "main_shape": {"label": "W4", "faces": {"13": "3"}}})
    out = load_packet(tmp_path, "26151")
    assert [r["no"] for r in out["rows"]] == ["2", "13"]          # 按场号排
    assert out["by_no"]["13"]["k"] == 4
    assert out["errors"] == ["场 2 缺字段：default、k、n"]
    assert out["main_shape"]["faces"] == {"13": "3"}
```

- [ ] **Step 2:** Run `uv run pytest tests/decision/test_packet_doc.py -q` → FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现**

```python
# nutmeg/decision/packet_doc.py
"""分析包旁车 `zucai/<期>-packet.json` 的读取（2026-10-27 产品形态第 1 阶段）。

§1 决策表的档 / 六条件 k/n / 默认 / 死门 / 停售前拿不到 / §1c / §1d 和 §2 主形只由
`/zucai-packet` 产出（六条件计数在代码里没有实现，页面绝不自算）；旁车是同一张表的结构化
副本。缺文件或缺字段写进 `errors` 让页面显示，从不抛——缺旁车不该让期页打不开。
"""
from __future__ import annotations

from pathlib import Path

from nutmeg.decision.files import read_json

REQUIRED = ("tier", "k", "n", "default")


def load_packet(data_dir: Path, issue: str) -> dict:
    name = f"{issue}-packet.json"
    doc = read_json(Path(data_dir) / "zucai" / name, None)
    if not isinstance(doc, dict):
        return {"issue": issue, "rows": [], "by_no": {}, "main_shape": None,
                "alternatives": [], "default": None, "signed_bold": [],
                "errors": [f"缺 {name}（/zucai-packet 未出旁车）"]}
    errors = []
    rows = sorted((r for r in doc.get("rows") or [] if isinstance(r, dict) and r.get("no")),
                  key=lambda r: int(r["no"]))
    for r in rows:
        missing = [k for k in sorted(REQUIRED) if r.get(k) is None]
        if missing:
            errors.append(f"场 {r['no']} 缺字段：{'、'.join(missing)}")
    return {"issue": issue, "rows": rows, "by_no": {r["no"]: r for r in rows},
            "main_shape": doc.get("main_shape"), "alternatives": doc.get("alternatives") or [],
            "default": doc.get("default"), "signed_bold": doc.get("signed_bold") or [],
            "built_at": doc.get("built_at"), "errors": errors}
```

（`REQUIRED` 排序后是 `default、k、n、tier`；第二个测试那行 `tier` 有值，所以报 `default、k、n`。）

- [ ] **Step 4:** Run `uv run pytest tests/decision/test_packet_doc.py tests/test_single_source.py -q` → PASS
- [ ] **Step 5: 提交**

```bash
git add nutmeg/decision/packet_doc.py tests/decision/test_packet_doc.py .claude/commands/zucai-packet.md
git commit -m "feat(packet): 分析包旁车 <期>-packet.json（期页唯一数据源，页面不自算六条件）"
```

### Task 1.2：`GET /api/issue/{期}`

**Files:**
- Create: `nutmeg/interfaces/decision_web_issue.py`
- Modify: `nutmeg/interfaces/decision_web.py`（`return app` 前加 `register_issue_routes(app, templates)`；`_assets` 列表加 `"issue.js", "issue.css"`）
- Test: `tests/test_decision_web_issue.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_decision_web_issue.py
import json
from pathlib import Path

from fastapi.testclient import TestClient

from nutmeg.interfaces.decision_web import create_decision_app


def _client(tmp_path: Path) -> TestClient:
    data = tmp_path / "data"
    z = data / "zucai"
    z.mkdir(parents=True)
    (data / "jczq").mkdir()
    legs = {str(i): {"name": f"甲{i}-乙{i}", "fair": {"home": 0.5, "draw": 0.3, "away": 0.2}}
            for i in range(1, 15)}
    (z / "26151-legs-base.json").write_text(json.dumps({"legs": legs}, ensure_ascii=False))
    (z / "26151-packet.json").write_text(json.dumps({
        "issue": "26151", "rows": [{"no": "13", "tier": "B", "k": 4, "n": 6, "default": "31"}],
        "main_shape": {"label": "W4", "faces": {"13": "3"}}}, ensure_ascii=False))
    app = create_decision_app(output_dir=data / "jczq", data_dir=data, launchctl=lambda: "")
    return TestClient(app)


def test_issue_api_joins_packet_market_and_brake(tmp_path):
    body = _client(tmp_path).get("/api/issue/26151").json()
    assert body["issue"] == "26151"
    assert len(body["matches"]) == 14
    m13 = body["matches"][12]
    assert m13["no"] == "13" and m13["packet"]["k"] == 4 and m13["fair"]["home"] == 0.5
    assert body["main_shape"]["label"] == "W4"
    assert "room" in body["brake"] and "line" in body["brake"]
    assert body["errors"] == [] or all(isinstance(e, str) for e in body["errors"])


def test_issue_page_shell(tmp_path):
    page = _client(tmp_path).get("/issue/26151")
    assert page.status_code == 200 and "/static/decision/issue.js" in page.text


def test_issue_rejects_bad_issue(tmp_path):
    assert _client(tmp_path).get("/api/issue/../x").status_code in (400, 404)
```

- [ ] **Step 2:** Run `uv run pytest tests/test_decision_web_issue.py -q` → FAIL（404）

- [ ] **Step 3: 实现**

```python
# nutmeg/interfaces/decision_web_issue.py
"""期页与竞彩当日板的路由（2026-10-27 产品形态）。只读组装 + 转调 precheck；不产生判断。"""
from __future__ import annotations

import re
from datetime import date as _date
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request

_ISSUE = re.compile(r"\d{5}")


def _check_issue(issue: str) -> str:
    if not _ISSUE.fullmatch(issue):
        raise HTTPException(status_code=400, detail="期号须为 5 位数字")
    return issue


def issue_payload(data_dir: Path, issue: str, *, today: _date) -> dict:
    from nutmeg.decision.bankroll import brake_state, issue_brake, status_line
    from nutmeg.decision.counter_matrix import issue_matrices
    from nutmeg.decision.files import read_json
    from nutmeg.decision.packet_doc import load_packet
    from nutmeg.decision.review_runner import issue_market

    errors: list[str] = []
    packet = load_packet(data_dir, issue)
    errors += packet["errors"]
    market = issue_market(data_dir, issue)
    try:
        matrices = {m["no"]: m for m in issue_matrices(data_dir, issue)}
    except Exception as exc:  # noqa: BLE001 —— 矩阵缺席要看得见，不能读成「没有证据」
        matrices = {}
        errors.append(f"反证矩阵失败：{exc!r}"[:200])
    draft = read_json(Path(data_dir) / "zucai" / f"{issue}-draft.json", None)
    if draft is None:
        errors.append(f"缺 {issue}-draft.json（judgment draft --write 未跑）")
    from nutmeg.decision.lineup_watch import issue_doc, match_names

    doc = issue_doc(data_dir, issue)
    names = {no: f"{t[0]}-{t[1]}" for no, t in match_names(doc).items()} if doc else {}
    state = brake_state(data_dir, today)
    matches = [{"no": str(no), "name": names.get(str(no), ""), "fair": market.get(str(no)),
                "packet": packet["by_no"].get(str(no)), "matrix": matrices.get(str(no))}
               for no in range(1, 15)]
    return {"issue": issue, "matches": matches, "default": packet["default"],
            "main_shape": packet["main_shape"], "alternatives": packet["alternatives"],
            "draft_candidates": (draft or {}).get("candidates") or [],
            "brake": {**state, "line": status_line(state), "issue": issue_brake(data_dir, issue)},
            "errors": errors}


def register_issue_routes(app: FastAPI, templates) -> None:
    @app.get("/issue/{issue}")
    def issue_page(request: Request, issue: str):
        return templates.TemplateResponse(request, "decision/issue.html",
                                          {"title": f"期 {_check_issue(issue)}", "issue": issue})

    @app.get("/api/issue/{issue}")
    def issue_api(issue: str) -> dict:
        return issue_payload(app.state.data_dir, _check_issue(issue), today=_date.today())
```

`issue_market` 返回 `{场号: 分布}`（legs-base 的 prior，缺则 fair）；场名用 `lineup_watch.issue_doc / match_names` 读 `<期>-issue.json`（开工时先确认 `match_names` 的元组前两项是主、客队名），不要再写一份读 issue.json 的代码。

模板 `templates/decision/issue.html`：

```html
{% extends "decision/layout.html" %}
{% block body %}
<link rel="stylesheet" href="/static/decision/issue.css?v={{ asset_v }}">
<main id="issue" data-issue="{{ issue }}" class="issue">
  <header class="issue-head"><h1>{{ issue }} 决策表</h1><p id="brake" class="brake"></p></header>
  <p id="errors" class="errors" hidden></p>
  <div class="issue-grid">
    <section class="board" aria-label="决策表"><div id="table" role="table"></div></section>
    <aside class="side"><div id="draft"></div><div id="review"></div><div id="actions"></div></aside>
  </div>
</main>
<script src="/static/decision/issue.js?v={{ asset_v }}"></script>
{% endblock %}
```

- [ ] **Step 4:** Run `uv run pytest tests/test_decision_web_issue.py tests/test_decision_web.py -q` → PASS
- [ ] **Step 5: 提交**

```bash
git add nutmeg/interfaces/decision_web_issue.py nutmeg/interfaces/decision_web.py \
  nutmeg/interfaces/web/templates/decision/issue.html tests/test_decision_web_issue.py
git commit -m "feat(decision-web): /issue/{期} 外壳 + /api/issue 组装（旁车+市场+矩阵+初稿+止损）"
```

### Task 1.3：`POST /api/precheck`

**Files:**
- Modify: `nutmeg/interfaces/decision_web_issue.py`
- Test: `tests/test_decision_web_issue.py`（加用例）

- [ ] **Step 1: 写失败测试**

```python
def test_precheck_returns_review_shape_row_and_gates(tmp_path):
    c = _client(tmp_path)
    body = c.post("/api/precheck", json={
        "channel": "renjiu", "issue": "26151", "placed_at": "2026-10-27",
        "faces": {"13": "3", "8": "3", "9": "3", "10": "31", "2": "31",
                  "4": "10", "5": "10", "7": "31", "12": "10"}}).json()
    assert body["ok"] is True
    assert body["notes"] == 64 and body["stake"] == 128
    assert body["shape"] == "3单6双"
    assert body["faces_row"].split()[12] == "3" and body["faces_row"].split()[0] == "*"
    assert body["mode"] == "任九"
    assert [g["no"] for g in body["gates"]][:1] and all("p" in g for g in body["gates"])
    assert isinstance(body["verdicts"], list) and "brake_line" in body


def test_precheck_bad_faces_is_an_error_not_500(tmp_path):
    r = _client(tmp_path).post("/api/precheck", json={
        "channel": "renjiu", "issue": "26151", "placed_at": "2026-10-27", "faces": {"1": "33"}})
    assert r.status_code == 200 and r.json()["ok"] is False
```

- [ ] **Step 2:** Run → FAIL（405/404）

- [ ] **Step 3: 实现**（加进 `register_issue_routes`）

```python
    @app.post("/api/precheck")
    def precheck_api(payload: dict = Body(...)) -> Any:  # noqa: B008
        from nutmeg.decision.betslip import BetslipError, format_faces_row
        from nutmeg.decision.choice_ledger import shape_of
        from nutmeg.decision.precheck import build_slip, precheck
        from nutmeg.decision.slip_group import death_list

        data_dir = app.state.data_dir
        try:
            channel = str(payload.get("channel") or "renjiu")
            faces = {str(k): str(v) for k, v in (payload.get("faces") or {}).items() if v}
            row = format_faces_row(faces) if channel != "jczq" else None
            slip = build_slip(slip_id="preview", channel=channel,
                              placed_at=str(payload.get("placed_at") or _date.today()),
                              faces=row, legs=payload.get("legs"),
                              combo=(str(payload["combo"]) if payload.get("combo") else None),
                              multiplier=int(payload.get("multiplier") or 1),
                              issue=str(payload.get("issue") or ""), data_dir=data_dir)
            out = precheck(slip, data_dir, log=bool(payload.get("log")))
            out.pop("diagnosis", None)
            gates = []
            if channel != "jczq":
                fair = {leg.key: leg.fair for leg in slip.legs if leg.fair}
                ordered, _ = death_list([slip.faces], fair, top=5)
                gates = [{"no": no, "face": f, "p": p} for no, f, p in ordered[:5]]
                n = len(slip.faces)
                out["mode"] = ("胜负彩" if n == 14 else "任九" if n == 9
                               else f"任九 · 还差 {9 - n} 场" if n < 9 else f"{n} 场 · 任九不可购")
                out["shape"] = shape_of(slip.faces)
            return {"ok": True, **out, "faces_row": row, "gates": gates}
        except (BetslipError, KeyError, ValueError) as error:
            return {"ok": False, "error": str(error)}
```

`log` 默认 False：每次点格都写预审留痕会把截止播报的「审过未登记」刷屏；只有点「审这张」或登记前那一次传 `log: true`。

- [ ] **Step 4:** Run `uv run pytest tests/test_decision_web_issue.py -q` → PASS（`死法清单` 的 `gates[].no` 是字符串场号）
- [ ] **Step 5: 提交**

```bash
git add nutmeg/interfaces/decision_web_issue.py tests/test_decision_web_issue.py
git commit -m "feat(decision-web): /api/precheck —— 点格即审，同一份 precheck + 死法清单"
```

### Task 1.4：`issue.js` 渲染决策表与审票卡

**Files:**
- Create: `nutmeg/interfaces/web/static/decision/issue.js`、`issue.css`
- Test: 手工验收（下面的 Step 3），外加 Task 1.2 的外壳测试已覆盖资源引用

- [ ] **Step 1: 写 JS**（全部 `textContent`，研究文本是不可信输入，不用 `innerHTML`）

```js
// static/decision/issue.js —— 期页：决策表即票。推导一律在服务端（/api/precheck），这里只渲染。
(() => {
  const root = document.getElementById("issue");
  const issue = root.dataset.issue;
  const FACES = ["3", "1", "0"], NAME = { 3: "胜", 1: "平", 0: "负" }, KEY = { 3: "home", 1: "draw", 0: "away" };
  const state = { data: null, picks: {}, open: null, review: null, seq: 0 };
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };

  async function load() {
    state.data = await (await fetch(`/api/issue/${issue}`)).json();
    document.getElementById("brake").textContent = state.data.brake.line;
    const errs = document.getElementById("errors");
    errs.hidden = !state.data.errors.length;
    errs.textContent = state.data.errors.join("；");
    render();
  }

  function toggle(no, k) {
    const cur = new Set(state.picks[no] || "");
    cur.has(k) ? cur.delete(k) : cur.add(k);
    state.picks[no] = FACES.filter((f) => cur.has(f)).join("");
    if (!state.picks[no]) delete state.picks[no];
    render(); review();
  }

  let timer = null;
  function review() {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const seq = ++state.seq;
      const r = await fetch("/api/precheck", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ channel: "renjiu", issue, faces: state.picks }) });
      const body = await r.json();
      if (seq === state.seq) { state.review = body; renderSide(); }
    }, 150);
  }

  function render() {
    const table = document.getElementById("table");
    table.replaceChildren();
    for (const m of state.data.matches) {
      const p = m.packet || {};
      const row = el("div", "row" + (state.open === m.no ? " open" : "") + (p.tier === "D" ? " coin" : ""));
      row.setAttribute("role", "row");
      row.append(el("span", "no", m.no));
      const name = el("button", "name", m.name || `场 ${m.no}`);
      name.type = "button"; name.setAttribute("aria-expanded", String(state.open === m.no));
      name.onclick = () => { state.open = state.open === m.no ? null : m.no; render(); };
      row.append(name, el("span", "tier tier-" + (p.tier || "?").charAt(0), p.tier || "?"));
      const cells = el("span", "cells");
      for (const k of FACES) {
        const on = (state.picks[m.no] || "").includes(k);
        const b = el("button", "cell" + (on ? " on" : ""));
        b.type = "button"; b.setAttribute("aria-pressed", String(on));
        const pct = m.fair ? Math.round(m.fair[KEY[k]] * 100) : "—";
        b.setAttribute("aria-label", `场 ${m.no} ${NAME[k]} ${pct}%`);
        b.append(el("small", null, k), el("b", null, String(pct)));
        b.onclick = () => toggle(m.no, k);
        cells.append(b);
      }
      row.append(cells, el("span", "cond", p.k != null ? `${p.k}/${p.n}` : "—"),
        el("span", "flip", p.flip || ""), el("span", "dflt", p.default || ""),
        el("span", "dead", p.dead || ""), el("span", "lineup" + (p.lineup_before_close ? " pre" : ""), p.lineup_at || ""));
      table.append(row);
      if (state.open === m.no && window.renderDrawer) table.append(window.renderDrawer(m, state));   // 第 2 阶段
    }
    renderSide();
  }

  function renderSide() {
    const draft = document.getElementById("draft"), rev = document.getElementById("review");
    draft.replaceChildren(); rev.replaceChildren();
    const r = state.review;
    if (!r) { draft.append(el("p", "muted", "点格出票；机器默认：" + ((state.data.default || {}).action || "—"))); return; }
    if (!r.ok) { draft.append(el("p", "error", r.error)); return; }
    draft.append(el("h2", null, `${r.shape} · ¥${r.stake} · ${r.mode}`),
      el("p", "mono", r.p != null ? `P 全对 ${(r.p * 100).toFixed(2)}%` : "P —"),
      el("code", "row500", r.faces_row));
    for (const v of r.verdicts) rev.append(el("p", "v v-" + v.level, `${v.code} ${v.text}`));
    for (const line of [...r.discipline, r.brake_line]) rev.append(el("p", "v" + (line.startsWith("⛔") ? " v-veto" : ""), line));
    const gates = el("ol", "gates");
    for (const g of r.gates) gates.append(el("li", g.p >= 0.3 ? "hot" : "", `${g.no} 开 ${g.face} ${(g.p * 100).toFixed(0)}%`));
    rev.append(el("h3", null, "死法清单"), gates);
  }

  load();
})();
```

`issue.css`：两栏 `flex-wrap`（表 `flex: 999 1 760px`、侧栏 `flex: 1 1 360px`）、表外框 `overflow-x: auto`、`.row` 用 `display: grid; grid-template-columns: 40px 160px 48px 164px 64px minmax(140px,1fr) 72px 80px 104px`、格子 `min-height: 44px`；配色照画布：墨 #15181B、底 #F3F4F1、否决朱 #B23A0E（实线框）、只展示灰虚线 #7A828A。

- [ ] **Step 2: 本地起一个不撞常驻进程的端口**

```bash
uv run nutmeg decision-web --port 8791
```

- [ ] **Step 3: 手工验收**（浏览器开 `http://127.0.0.1:8791/issue/26151`）
  - 表 14 行，档 / 条件 / 翻车面 / 默认 / 死门 / 首发来自 `26151-packet.json`；没旁车时顶部红字「缺 26151-packet.json」而不是空表静默。
  - 点 13 胜、8 胜、9 胜、10 胜平、2 胜平、4 平负、5 平负、7 胜平、12 平负 → 侧栏「3单6双 · ¥128 · 任九」，位置式 `* 31 * 10 10 * 31 3 3 31 * 10 3 *`，与 `uv run nutmeg betslip preview --channel renjiu --placed-at 2026-10-27 --issue 26151 --faces "* 31 * 10 10 * 31 3 3 31 * 10 3 *"` 的注数、P、V1、止损行逐字一致。
  - 窗口缩到 390px：表横向滚动，侧栏落到表下方。

- [ ] **Step 4: 改 `docs/ARCHITECTURE.md`** decision-web 一节：加 `/issue/{期}`、`/api/issue`、`/api/precheck`，写明「推导在 precheck，页面不算」。

- [ ] **Step 5: 提交**

```bash
git add nutmeg/interfaces/web/static/decision/issue.js nutmeg/interfaces/web/static/decision/issue.css docs/ARCHITECTURE.md
git commit -m "feat(decision-web): 期页表即票 —— 点格即审（注数/P/V1–V5/止损/刹车/死法清单都来自服务端）"
```

**第 1 阶段完成标准**：Jun 在 `/issue/<期>` 点出的票面与 CLI `betslip preview` 结果逐字一致；页面没有任何一处自己算 P 或否决。

---

## 第 2–9 阶段（每阶段开工时再按本文件格式写细到代码的 TDD 步骤）

> 依 writing-plans 的范围规则：这些阶段互相独立、各自可交付，开工时各写一份细计划，不在这里预写会过时的代码。下面写死的是**接口、数据来源、验收测试**，细计划不得偏离。

### 第 2 阶段：行内取证抽屉

- **前端**：`issue.js` 里实现 `window.renderDrawer(m, state)`；内容 = `m.matrix.rows`（证据 · 类 · 来源 · 价态 · H1 · H2，`priced_in === false` 标「未价」）+ `不一致数` + `loose` 提示 + `m.packet.unknowable` / `c1` / `d1`（d1 灰虚线框「只展示」）+ `m.matrix.falsifier`。
- **研究收敛标**：`m.matrix.coverage` 为空或「—」时写「引用制前落盘，只有来源名」；有 `source_url` 的行把来源渲染成 `<a rel="noopener noreferrer" target="_blank">`。
- **引用按钮**：只改前端 `state.cites[no] = k`，第 3 阶段随桥记录落盘。
- **验收**：`tests/test_decision_web_issue.py::test_issue_api_carries_matrix_rows`——造一份 `26151-research-m13.json`，断言 `/api/issue` 的 `matches[12].matrix.rows` 与 `counter_matrix.build_matrix` 的结果相等（同一函数，不另算）。

#### Task 2.1（细计划，2026-10-28 开工）：取证抽屉

**数据形状（已核实）**：`m.matrix` 来自 `counter_matrix.issue_matrices`——正常场 `{no, name, h1, h2, anchor_side, rows, hidden, inconsistent: {h1, h2}, loose, falsifier, unknowable_before_close, coverage, stop_reason}`，无研究场 `{no, name, missing}`；`rows[]` = `{evidence, kind, source_url, source_text, priced_in: true|false|null, h1, h2, distinguishing}`（`h1/h2` 为 −2…+2 的整数，只给有区分力的行）。`m.packet` 的抽屉字段：`unknowable`、`anchor`、`hole`、`watch`、`consistency`、`crowd`、`c1 {path, move, q3a, fav, weak_check?}`（D 档为 null）、`d1 {cell, layer, n, open, hot_pct, p1, diff}`。

**Files:**
- Modify: `nutmeg/interfaces/web/static/decision/issue.js`（实现 `window.renderDrawer(m, state)`；`state.cites` 初始化为 `{}`）
- Modify: `nutmeg/interfaces/web/static/decision/issue.css`（`.drawer` 样式，沿用画布：抽屉底 #F7F8F5 框 #C9CDC6，「未价」朱红加粗，d1 灰虚线框「只展示」，已引用行 #EEF2FD）
- Test: `tests/test_decision_web_issue.py`

- [ ] **Step 1: 写失败测试**——API 透传同一函数的结果，不另算：

```python
def test_issue_api_carries_matrix_rows(tmp_path):
    from nutmeg.decision.counter_matrix import issue_matrices

    client = _client(tmp_path)
    data = tmp_path / "data"
    (data / "zucai" / "26151-research-m13.json").write_text(json.dumps({
        "anchor_side": "home",
        "hole_location": {"unit": "goalkeeper", "side": "home", "priced_in": True,
                          "detail": "门将伤缺"},
        "strength_balance": {"events": [
            {"event": "门将伤缺", "side": "home", "direction": "down", "grade": "moderate",
             "priced_in": True, "source": "https://example.com/a 原句"}]},
        "stance": {"falsifier": "主队不胜"}}, ensure_ascii=False))
    body = client.get("/api/issue/26151").json()
    expected = {m["no"]: m for m in issue_matrices(data, "26151")}["13"]
    assert body["matches"][12]["matrix"] == expected
    assert expected["rows"], "造的研究件要至少产出一行有区分力的证据"
```

（字段按 `counter_matrix.build_matrix` 实际读的键补齐；断言的是「API = 同一函数结果」，不是某个具体行数。）

- [ ] **Step 2:** Run `uv run pytest tests/test_decision_web_issue.py -q -o addopts=""` → 新用例应**直接通过**（第 1 阶段已透传）；若失败说明 `issue_payload` 改写了矩阵，先修那里。这一步是钉住契约，不是 TDD 红灯。

- [ ] **Step 3: 实现抽屉**（全部 `textContent`；链接只放 `http(s)` 协议，研究件里的 URL 是不可信输入）：

```js
  const SIGN = (v) => (v > 0 ? "+" : v < 0 ? "−" : "·");
  const safeHref = (u) => { try { const x = new URL(u); return /^https?:$/.test(x.protocol) ? x.href : null; } catch { return null; } };

  window.renderDrawer = (m, state) => {
    const box = el("div", "drawer");
    const mx = m.matrix || {}, p = m.packet || {};
    const head = el("div", "drawer-head");
    head.append(el("strong", null, `取证 · 场 ${m.no} ${m.name || ""}`));
    if (mx.missing || !mx.rows) { head.append(el("span", "muted", "这场没有研究件")); box.append(head); return box; }
    head.append(el("span", null, `H1 锚方面 ${mx.h1} 对 H2 翻车面 ${mx.h2}`),
      el("span", "chip show", mx.coverage && mx.coverage !== "—" ? `研究收敛 ${mx.coverage}` : "引用制前落盘，只有来源名"));
    box.append(head);

    const grid = el("div", "drawer-grid");
    const table = el("div", "mx");
    table.append(...["行", "证据", "类", "来源", "价态", "H1", "H2", "引用"].map((t) => el("span", "mx-h", t)));
    mx.rows.forEach((r, i) => {
      const k = i + 1, on = state.cites[m.no] === k;
      const src = el("span", "mx-src");
      const href = r.source_url && safeHref(r.source_url);
      if (href) { const a = el("a", null, new URL(href).hostname); a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; src.append(a); }
      else src.textContent = r.source_text || "—";
      const price = el("span", r.priced_in === false ? "unpriced" : "", r.priced_in === null ? "—" : r.priced_in ? "价内" : "未价");
      const cite = el("button", "cite" + (on ? " on" : ""), on ? "已引用" : "引用");
      cite.type = "button"; cite.setAttribute("aria-pressed", String(on));
      cite.setAttribute("aria-label", `引用场 ${m.no} 矩阵行 ${k} 作为理由`);
      cite.onclick = () => { if (on) delete state.cites[m.no]; else state.cites[m.no] = k; render(); };
      const cells = [el("span", "mono", String(k)), el("span", null, r.evidence), el("span", "muted", r.kind), src, price,
        el("span", "mono", SIGN(r.h1)), el("span", "mono", SIGN(r.h2)), cite];
      cells.forEach((c) => { if (on) c.classList.add("cited"); table.append(c); });
    });
    const inc = mx.inconsistent || {};
    table.append(el("p", "mx-foot", `不一致数 H1 ${inc.h1 ?? "—"} · H2 ${inc.h2 ?? "—"}（少者为 ACH 首选，只排序不推概率）`
      + (mx.loose ? ` · 区分力行 ${mx.rows.length} > 5：打分偏松` : "") + ` · 无区分力 ${mx.hidden ?? 0} 条不显示`));

    const side = el("div", "drawer-side");
    const block = (label, ...lines) => { const b = el("div", "blk"); b.append(el("small", null, label)); lines.filter(Boolean).forEach((t) => b.append(el("span", null, t))); return b; };
    side.append(block("停售前拿不到", p.unknowable || (p.lineup_at ? `首发 ${p.lineup_at}${p.lineup_before_close ? "（停售前可见）" : "（停售后）"}` : "—")));
    side.append(p.c1 ? block("翻车面 · §1c", p.c1.path, `固定招：${p.c1.move || "—"}`, `弱方能进球：${p.c1.q3a || "—"}`, `热门零封：${p.c1.fav || "—"}`, p.c1.weak_check && `标弱加查：${p.c1.weak_check}`)
                     : block("翻车面 · §1c", "D 档硬币场：§1c 不列"));
    if (p.d1) { const d = block("历史同类格 · §1d · 只展示", p.d1.cell, `${p.d1.layer} · n=${p.d1.n} · 开 热/平/冷 ${p.d1.open} · 热门 ${p.d1.hot_pct}% 对市场 ${p.d1.p1} · 差 ${p.d1.diff}`); d.classList.add("show"); side.append(d); }
    side.append(block("翻盘证据（研究自己写的）", mx.falsifier || "（研究未写）"));
    side.append(block("锚方中轴 · 洞", p.anchor, p.hole));
    grid.append(table, side);
    box.append(grid);
    return box;
  };
```

`el`、`render` 用 issue.js 里已有的；`render()` 重画后抽屉仍开（`state.open` 不变）、焦点回到同一个「引用」按钮（沿用表格格子保焦点的做法）。

- [ ] **Step 4: 验收**
  - `node --check nutmeg/interfaces/web/static/decision/issue.js`
  - `uv run pytest tests/test_decision_web_issue.py tests/test_decision_web.py -q -o addopts=""`
  - 沙盒浏览器（另起端口，不碰 :8787）：26151 点「罗马-卡利亚里」→ 抽屉 11 行，H1 3 对 H2 1，不一致数 H1 8 · H2 3，「区分力行 11 > 5：打分偏松」，Winks 那行标「未价」；点第 9 行「引用」→ 行底变蓝、按钮「已引用」，再点取消；26152 任一场来源若带 URL，显示为站点名链接、新标签打开。

- [ ] **Step 5: 提交**

```bash
git add nutmeg/interfaces/web/static/decision/issue.js nutmeg/interfaces/web/static/decision/issue.css tests/test_decision_web_issue.py
git commit -m "feat(decision-web): 期页行内取证抽屉（§1c 反证矩阵 + 翻车面 + §1d 格 + 引用按钮）"
```

### 第 3 阶段：§3 桥 + 桥后票 B1

- **新模块 `nutmeg/decision/bridge.py`**：
  - `self_checks(packet: dict, slip: BetSlip, precheck_out: dict, *, signed_bold: list[str]) -> list[dict]`：五条 `{id, ok, detail}`。① 票内 D 档场（`packet.by_no[no].tier == "D"`）；② 单选场里 `k < 5` 且不在 `signed_bold`；③ 直接读 `precheck_out["verdicts"]` 里 `review.structure_notes` 产出的 V5 行（博胆 >1 / 包非硬币），**不重算**；④ 单票写「无跨票」，多票读 `diagnosis.shared_naked/shared_excluded`；⑤ `precheck_out["discipline"]` 里有无刹车 ⛔。
  - `diff_cells(faces: dict, main: dict, cites: dict, outs: dict) -> list[dict]`：和主形不同的格 `{no, mine, main, reason}`，`reason` 是 `{"kind": "matrix", "row": k}`、`{"kind": "out", "text": …}` 或 `None`。
  - `append_bridge(data_dir, issue, record) -> Path`：追加 `zucai/<期>-bridge.jsonl`（`{at, stage: "B1", draft0, faces, diffs, whys, prediction, deviation}`）。
  - `bridge_ledger(data_dir, issue) -> dict`：§5⑪ 用——差异格数 / 指到矩阵行数 / 矩阵外数 / 未写数。
- **路由 `POST /action/bridge`**：body `{issue, draft0, faces, cites, outs, whys, deviation, prediction}` → `append_bridge` → `build_slip(slip_id=f"{issue}-B1", trial=True, …)` → `register_reviewed`。等价命令：`betslip preview-set --plan` + `betslip register --slip-id <期>-B1 --trial`。
- **前端**：桥面板（复述「停售前拿不到」/ 五条自检带「我为什么仍然这样」输入 / 差异格带「去取证抽屉引用」/ 死法清单）；「只走一次」由服务端保证：同期已有 B1 记录时 `/action/bridge` 返回 `{ok: false, error: "本期桥已走过（<时刻>）"}`。
- **SOP 同步**：RUNBOOK B5e 与 `.claude/commands/zucai-packet.md` §3 写明「桥在 `/issue/<期>` 走，B1 由页面登记」；retro §5⑪ 改读 `bridge_ledger`。
- **验收**：`tests/decision/test_bridge.py`——①–⑤ 各一个用例（③ 断言来源是 V5 行而非自算）；`test_bridge_twice_refused`；B1 落 `betslips.jsonl` 且 `purchased is False`。

#### 第 3 阶段细计划（2026-10-28 开工）

**勘察结论**：§5⑪（桥后改动账、理由引用矩阵行 k/n）至今全靠 retro 手数，代码里没有任何读桥的地方；停售播报（`day_decisions.live_register_decisions`）只认 `purchased` 实票，SOP 写的「桥后票 B1 未确认实购」从没实现。两件都在本阶段补。

**判定口径（写进 `bridge.py` 文档串）**：
- ① 硬币场：票内出现旁车 `tier == "D"` 的场 → ✗（列场号与面）。「无机制 C 档」旁车没有可机读字段，本阶段不判，detail 写明。
- ② 单的许可：单选场 `n == 6 and k >= 5` 才算许可；不在 `signed_bold`（旁车 + 桥上本次签的）里的其余单 → ✗。C 档（n=5）的单按定义是博胆；A 档七项口径未定，按不许可处理并在 detail 写明。
- ③ 博胆 ≤1 / 包只给硬币：**只读** `precheck` 的 `verdicts` 里 `code == "V5"` 的行（`review.structure_notes`），有就 ✗，detail 原样抄 V5 文字——不自算。
- ④ 跨票：读 `verdicts` 里 `code == "V2"` 的行（共享裸单 / 共享排除面，含与已购票）；无则「无跨票共享」✓。
- ⑤ 刹车档：`discipline` 里含「刹车」或「日帽」的 ⛔ 行 → ✗。月度止损不在五条里（审票卡已单独显示）。
- 开场复述：每条单一行 = 场号 · 旁车 `unknowable`（缺则 `首发 lineup_at（停售前/后）`）；外加死法清单第一门（`gates[0]`，带 ·D档）。

**Files:**
- Create: `nutmeg/decision/bridge.py`、`tests/decision/test_bridge.py`
- Modify: `nutmeg/interfaces/cli/judgment.py`（加 `judgment bridge --issue <期>`：打印 `bridge_ledger`，retro §5⑪ 用）
- Modify: `nutmeg/interfaces/decision_web_issue.py`（`POST /api/bridge/{期}/preview`、`POST /action/bridge`；`/api/issue` 加 `bridge` 字段）
- Modify: `nutmeg/decision/day_decisions.py`（无实票但有 `<期>-B1` 试玩票时，截止行主语改「桥后票 B1 已登记（试玩），未确认实购」）
- Modify: `nutmeg/interfaces/web/static/decision/issue.js` / `issue.css`（桥面板）
- Modify: `docs/sop/RUNBOOK.md` B5e、`.claude/commands/zucai-packet.md` §3（桥在 `/issue/<期>` 走；§5⑪ 读 `judgment bridge`）
- Test: `tests/test_decision_web_issue.py`、`tests/decision/test_day_decisions.py`（若无则新建）

##### Task 3.1：`decision/bridge.py`（纯函数 + 桥记录读写 + 账）

接口（全部同名用于 3.2/3.3）：

```python
BRIDGE_SUFFIX = "-bridge.jsonl"

def self_checks(packet: dict, faces: dict[str, str], pre: dict, *,
                signed_bold: list[str] = ()) -> list[dict]:
    """→ [{id: 1..5, ok: bool, title, detail}]。pre＝precheck() 的输出。"""

def opening_lines(packet: dict, faces: dict[str, str], gates: list[dict]) -> list[dict]:
    """→ [{label, text}]：每条单「靠什么成立、停售前拿不到什么」+ 死法清单第一门。"""

def diff_cells(faces: dict[str, str], main: dict[str, str], fair: dict[str, dict],
               cites: dict[str, int | str], outs: dict[str, str],
               matrices: dict[str, dict]) -> list[dict]:
    """和主形不同的格 → [{no, mine, main, cover_mine, cover_main, excl_mine, excl_main,
    reason: {kind: "matrix", row, evidence} | {kind: "out", text} | None}]；'丢' 记作空面。"""

def cite_readout(diffs: list[dict]) -> dict:
    """{diffs, matrix, outside, blank}——§5⑪「理由引用矩阵行」的读数。"""

def bridge_record(data_dir: Path, issue: str) -> dict | None:
    """本期已走过的桥（只走一次：有记录即返回第一条）。"""

def append_bridge(data_dir: Path, issue: str, record: dict) -> Path:
    """追加 zucai/<期>-bridge.jsonl；已有记录则抛 BridgeError（只走一次由服务端守）。"""

def bridge_ledger(data_dir: Path, issue: str) -> dict:
    """§5⑪：{walked, at, b1_faces, readout, real: [{slip_id, changed: [no…], alive_unknown}]}
    real＝本期实购票与 B1 的差异格（实票登记后才有）。"""
```

测试（`tests/decision/test_bridge.py`）至少覆盖：
- `self_checks`：①（票里有 D 档场 → ✗）、②（4/6 的单 → ✗；5/6 → ✓；`signed_bold` 里的 C 档单 → ✓）、③（`pre["verdicts"]` 放一条 V5 → ✗ 且 detail 等于那条文字；没有 V5 → ✓）、④（放一条 V2 → ✗）、⑤（`discipline` 含「⛔刹车」→ ✗）。
- `diff_cells`：相同面集（`"10"` vs `"10"`）不算差；`丢` vs `"31"` 算差；`cites={"13": 2}` 带出 `matrices["13"]["rows"][1]["evidence"]`；`cites={"9": "out"}` 带出 `outs["9"]`。
- `cite_readout`：3 格（1 矩阵 / 1 矩阵外 / 1 空）→ `{diffs:3, matrix:1, outside:1, blank:1}`。
- `append_bridge` 两次 → 第二次抛 `BridgeError`；`bridge_record` 读回第一条。
- `bridge_ledger`：写 B1 记录 + 一张 `purchased` 实票（与 B1 差 2 格）→ `real[0]["changed"] == [两格]`。

`judgment bridge --issue <期>` 输出一段 markdown（走过时刻、差异格与理由、读数 k/n、实票与 B1 差异格）；没走过打印「本期没走桥」。

##### Task 3.2：桥路由 + B1 登记 + 播报主语

- `POST /api/bridge/{期}/preview` body `{faces, cites, outs, signed_bold?}` → `precheck(..., log=False)` → `{ok, opening, checks, diffs, readout, gates, shape, stake, p}`。只读不写。
- `POST /action/bridge` body `{issue, draft0, faces, cites, outs, whys, deviation, prediction}`：
  1. `bridge_record` 已有 → `{ok: false, error: "本期桥已走过（HH:MM），再想改就照抄 §2 主形"}`。
  2. `build_slip(slip_id=f"{issue}-B1", channel=任九 9 场 / 胜负彩 14 场, trial=True, deviation, prediction)` → `register_reviewed`；失败直接返回错误、**不写桥记录**。
  3. `append_bridge`：`{issue, at, slip_id, draft0, faces, main_label, diffs（含 reason）, readout, checks（含 whys[id]）, deviation, prediction}`。
  4. 返回 `{ok, at, summary, lines, readout}`。
- `/api/issue` 加 `bridge: bridge_record(...)`（页面重载后直接进「已走桥」态）。
- `day_decisions.live_register_decisions`：无实票但 `load_slips` 里有 `slip_id == f"{issue}-B1"` 且 `purchased is False` → 主语「足彩 {期} 桥后票 B1 已登记（试玩），未确认实购」；状态仍按「未登记实票」算（B1 不是实票）。
- 测试：preview 不写任何文件；第一次 `/action/bridge` 成功且 `betslips.jsonl` 出现 `<期>-B1`、`purchased: false`；第二次被拒；B1 登记失败（如 >9 场任九被 V4 之外的解析错误拒）时没有 `-bridge.jsonl`；`live_register_decisions` 的主语断言。

##### Task 3.3：桥面板前端

- 状态：`draft`（默认）→ 点「带着这版走 §3 桥 →」记 `draft0 = picks`、进 `bridge` → 每次点格或改引用都调 `/api/bridge/{期}/preview`（防抖、丢旧响应）→ 「定稿 · 登记桥后票 B1（试玩）」调 `/action/bridge` → `walked`（显示记录：时刻、差异格与理由、读数、「B1 已登记（试玩），停售播报会报未确认实购」）。`/api/issue` 带 `bridge` 时直接进 `walked`。
- 面板位置：主行（表 + 侧栏）下方整宽；顺序 = 开场复述 → 五条自检（✗ 的带「我为什么仍然这样」输入，内容随定稿进 `whys`）→ 差异格表（每格「去取证」= 打开该场抽屉并滚过去；「矩阵外」= 切换并出一句输入框；抽屉里点「引用」即写入该格理由）→ 死法清单五门 → 读数行「差异格 n · 指到矩阵行 k · 矩阵外 m · 未写 b」。
- 偏离理由五选一 + 一句预测：放在桥面板底部、定稿按钮上方（`deviation` 用 `fact_self_judged | price_instinct | stake_allocation | structure_preference | other`，中文标签同画布）。
- 「再想改就照抄主形」按钮：把 `picks` 设成 `main_shape.faces`。
- 全部 `textContent`；按钮 ≥44px；375px 下面板单列。

##### Task 3.4：SOP 同步 + 浏览器验收 + 提交

- RUNBOOK B5e 与 zucai-packet.md「B 桥」段各加一句：桥在 `/issue/<期>` 走（页面登记 `<期>-B1` 试玩票并写 `zucai/<期>-bridge.jsonl`）；§5⑪ 用 `uv run nutmeg judgment bridge --issue <期>` 读。
- 沙盒浏览器：26151 点 W4 → 走桥 → 改 10 为 31 → 抽屉引用场 10 某行 → 定稿；`judgment bridge --issue 26151 --data-dir <沙盒>` 打印出同一读数；再点定稿被拒；`/api/issue` 重载进 walked 态。

### 第 4 阶段：实票登记 + 500 抄录卡

- **路由**：复用第 0 阶段改好的 `POST /action/register-betslip`（`slip_id=<期>-T1`、`deviation`、`prediction`）；返回里加 `faces_row`（`format_faces_row`）。
- **前端**：14 格抄录卡（照 500 次序）、位置式与点名式各一个复制按钮（`navigator.clipboard`，失败提示「手动选中」）、「500 确认页必须显示 N 注 · ¥X · 1 倍」、与 B1 差异格（读 `bridge_ledger`）、首发复核时刻（`packet.rows[].lineup_before_close` 为真的票内场）、随票入账的审票码（返回的 `diagnosis.review.codes`）。
- **不做**：截图回传仍走 Telegram / 会话（截图＝实购的规则在那边），页面不接上传。
- **验收**：`test_register_returns_faces_row`；`test_register_after_kickoff_flag`（`placed_at` 晚于 `first_kickoff` 时返回 `after_kickoff: true`，页面显示「补写」）。

#### 第 4 阶段细计划（2026-10-28 开工）

**顺序改正**：画布把 500 抄录卡画在登记之后，但真实顺序是 **先照卡在 500 app 下单 → 再登记实票**（登记＝「已经买了」，宪法 §6「没入账=没打」；先登记后不买会让账多一张）。所以：
- 抄录卡在票面成形（任九 9 场 / 胜负彩 14 场）时就显示，不等登记；
- 登记按钮写「我已在 500 下单 · 登记实票 <期>-T<n>」，登记后出回执。

**`register_slip` 是同 slip_id 覆盖**，所以票号必须服务端分配：`betslip.next_slip_id(data_dir, issue) -> "<期>-T<n>"`（n＝本期已有 `-T<k>` 的最大 k + 1，B1 不算）。

##### Task 4.1：登记路由 + 票号

- `nutmeg/decision/betslip.py`：`next_slip_id(data_dir, issue)`；测试：空登记簿 → `T1`；已有 T1、T3、B1 → `T4`。
- `nutmeg/interfaces/decision_web_issue.py`：`POST /action/issue/{期}/register` body `{faces, multiplier?, scheme_no?, deviation?, prediction?}`：
  1. 渠道按场数（9 → renjiu，14 → shengfucai，其它 → 错误「任九 9 场 / 胜负彩 14 场」）；
  2. `slip_id = next_slip_id(...)`，`build_slip(..., trial=False)` → `register_reviewed`；
  3. 返回 `{ok, slip_id, summary, lines, faces_row, notes, stake, multiplier, codes（diagnosis.review.codes）, vetoed, after_kickoff, brake_line, b1_changed}`，`b1_changed`＝本期有桥时 `bridge_ledger` 里这张票的改动格，否则 `null`；
  4. 偏离理由缺省时，若本期走过桥，沿用桥记录的 `deviation/prediction`（同一判断的延续），否则留空（账上记「偏离初稿未登记理由」）。
- `POST /api/issue/{期}/slip500` body `{faces, multiplier?}` → `{ok, faces_row, named, cells: [{no, name, token}], notes, stake}`：只算不写，抄录卡用（注数/金额与 `precheck` 同源，不另算）。
- 测试：登记两次得 T1、T2 且都 `purchased: true`；>9 / <9 场的任九报错不落盘；沿用桥理由；`slip500` 不写文件且 `faces_row` 与 `format_faces_row` 相同；`b1_changed` 与 `bridge_ledger` 一致。

##### Task 4.2：抄录卡 + 登记 + 回执（前端）

- 抄录卡（侧栏草案卡下方，或桥面板之后，票面成形时显示）：14 格（场号 · 简称 · 面，`*` 灰），位置式行 + 复制，点名式行 + 复制（`navigator.clipboard`，失败显示「手动选中」），「500 确认页必须显示 N 注 · ¥X · M 倍——对不上＝抄错了，别付款」，倍数输入（1–99，改了重算）。
- 登记块：方案号（选填）、偏离理由（桥走过时预填桥里的）、一句预测，按钮「我已在 500 下单 · 登记实票 <期>-T<n>」（按下后禁用防重复）。
- 回执：`summary`、审票码（⛔ 朱红；`STOP/BRAKE/DAYCAP/V*`）、`after_kickoff` → 「理由写于开球后：照记，不进理由净值」、与 B1 改了哪几格、首发复核（票内 `lineup_before_close` 的场）、「截图发回 → 记实购（截图＝实购）」。可以继续登记下一张（T<n+1>），每张一份回执。
- 全部 `textContent`；按钮 ≥44px；375px 单列，14 格在窄屏折成 7×2。

### 第 5 阶段：竞彩当日板 `/jczq/{日}`

- **数据**：`GET /api/jczq/{日}` = `jczq_brief(data_dir, day)` 的行（表态 / 旗 / 损耗 / 关注度 / 一句话）+ `jczq_rows` 的 `leg.fair` + `jczq/daily/<日>/sporttery_markets.json` 经 `sporttery_board.selling_rows` 取 had/hhad SP 与单关开否 + 开球时刻（已开球行禁点）。**不得**在路由里再读一遍 legs-base——`board_rows` 受单一实现守卫。
- **预审**：前端把选中腿组成 `legs=[{key, market:"had", selections, odds, fair}]` 送 `/api/precheck`（`channel: "jczq"`, `combo: n`）；V1 用的就是 `review.expected_return_ratio`。止损余量读 `month_report(...)["effective_room"]`（待结按全损计，10-18 的教训）。
- **登记**：`/action/register-betslip` 带结构化腿（第 0 阶段已放开）；返回后渲染 500 投注单逐条 + 过关/注数/倍数/金额。
- **历史账卡**：只读已落盘的 gym 产出（`.nutmeg-data/replay/` 下最近一次 `gym run` 结果）；没有就写「未跑」，**页面绝不触发 gym**。
- **验收**：`tests/test_decision_web_jczq.py`——板面行数 = legs-base 场数；已开球行 `selectable: false`；`had` 未开（SP 全空）的行 `selectable: false`；precheck 竞彩 2 串 1 的 `ratio` 与 CLI `betslip preview --channel jczq --legs-file` 一致。

#### 第 5 阶段细计划（2026-10-28 开工）

**勘察结论**：`gym.board.load_jczq_board(data_dir, day)` 已是体彩快照的唯一读法——每场 `had` SP、`hhad`（线 + SP）、`selling`、`kickoff_bj`、`single_allowed`，板级 `allup`（各玩法允许的过关方式）。`judgment_brief.jczq_brief` 给表态 / 旗 / 损耗 / 关注度 / rubric / 一句话 / 大热。两者合起来就是板面，**不再读 legs-base 或 sporttery 原件**。

**改正（相对上面第 5 阶段规格）**：腿由**服务端**按选择表组装（`{场次: 面集合}` → `SlipLeg(key, name, market="had", selections, odds=板面 SP, fair=legs-base 市场)`），页面不传赔率——赔率只有一个来源，页面也改不了它。竞彩票号 `<YYYYMMDD>-J<n>`（登记簿现行写法，如 `20261017-J1`），同样由服务端分配。

##### Task 5.1：竞彩板 API + 预审 + 登记

- `nutmeg/decision/betslip.py`：`next_slip_id` 加竞彩分支或新增 `next_jczq_slip_id(data_dir, day)`（同一私有 helper，不复制正则逻辑）。
- 新模块 `nutmeg/interfaces/decision_web_jczq.py`（`register_jczq_routes(app, templates)`，`decision_web.py` 调一次）：
  - `jczq_payload(data_dir, day, *, now)` → `{day, rows: [{code, name, kickoff, kicked, selectable, sp: {3,1,0}|null, fair: {3,1,0}, ret: {3,1,0}（fair×SP，每元回报）, single, hhad, stance, flags, load, attention, rubric, note, fav}], allup_had, brake: {line, room, tripped}, counts, errors}`。`selectable`＝在售且未开球且 `had` 齐全。
  - `GET /jczq` → 307 到今天；`GET /jczq/{day}`（模板外壳）；`GET /api/jczq/{day}`。
  - `POST /api/jczq/{day}/precheck` body `{picks: {code: "31"}, multiplier}` → 服务端组腿（拒不可选的场、拒单关未开时的 1 腿、拒 >8 腿、拒 `allup_had` 不含 `n×1` 的过关），`precheck(log=False)` → `{ok, combo, notes, stake, p, ratio, verdicts, discipline, brake_line, max_payout, legs: [{code, name, faces, odds}]}`。
  - `POST /action/jczq/{day}/register` body 同上 + `{scheme_no, deviation, prediction}` → `next_jczq_slip_id` → `build_slip(channel="jczq", legs=…, combo=str(n))` → `register_reviewed` → `{ok, slip_id, summary, codes, vetoed, after_kickoff, brake_line, slip_text}`；`slip_text`＝500 投注单逐腿「周三001 大阪钢巴-布里兰 胜平负 胜 @1.54」+ 「n串1 · N 注 · M 倍 · ¥X」。
  - 测试（`tests/test_decision_web_jczq.py`，用 tmp 造 `sporttery_markets.json` + `jczq-legs-base.json` 两三场）：行数与 selectable；`ret` = fair×SP；precheck 2 串 1 的 `ratio` 等于直接 `precheck(build_slip(...))`；单关未开的 1 腿被拒；已开球的场被拒；登记两次得 `J1`、`J2` 且 `purchased`；`slip_text` 每腿一行。

##### Task 5.2：竞彩板前端

- `templates/decision/jczq.html` + `static/decision/jczq.js` / `jczq.css`（沿用 issue.css 的色板与写法，可直接 import 公共变量或复制最小集合；不改 issue.*）。
- 页面：刹车带（`brake.line` + 余量）→ 头部计数（板面 / 研究 / 判断≠市场 / 单关开 / 机器不构票）→ 读法一行（虚线只展示）→ 筛选（全部 / 未开球 / 表态单 / 有旗 / 大热 ≥70 / PM ≥$2万，计数）→ 板面表（编号 · 开球 · 对阵 · 胜平负 SP 格（大字 SP、小字市场 %）· 让球 · 表态（虚线）· 旗·损耗 · 关注度；已开球/不可选行灰、不可点；点对阵展开：一句话、rubric、每元回报三格（≥0.9 加框）、让球 SP）。
- 侧栏「我的串」：腿列表（每腿可删）、过关显示（n串1；1 腿显示「单关」或「单关未开」）、倍数 ±（1–99）、金额 / P / 中了拿回 / V1，全部来自 `/api/jczq/{day}/precheck`；审票卡同期页样式；理由五选一 + 预测；「我已在 500 下单 · 登记」→ 回执（审票码、500 投注单文本 + 复制、开球后补写提示、截图回传提示、止损行）。
- 浏览器验收：今天板（10-28）或沙盒 10-25 板，点两场 2 串 1 → 与 `betslip preview --channel jczq` 同 ratio；已开球场不可点；375px 无整页横滚。

### 第 6 阶段：今天（`/day/{日}` 换皮）

- **新外壳 `templates/decision/shell.html`**：导航（今天 / 期 <在售期> / 竞彩 / 账房 / 实验室）+ 刹车带（`month_report.effective_net / effective_room / effective_tripped` + `bankroll.issue_brake`）。`/day` `/issue` `/jczq` `/ledger` `/lab` 都继承它。
- **在售期号**：`lineup_watch.active_issues(data_dir, now)`（已有，别再写一份探测）。
- **待你决定**：`decisions.json`（`day_decisions.build_decisions` 已产出）每行加链接到 `/issue/<期>` 或 `/jczq/<日>`；「登记空仓」按钮调第 4 阶段端点登记零注空仓记录——**先确认 `betslips.jsonl` 是否接受零注票**；不接受就改记 `daily/<日>/decisions` 的 `pass` 动作（开工前定，写进细计划）。
- **验收**：`test_decision_web_day.py` 加「刹车带文本 = `status_line`」与「在售期链接存在」两条。

#### 第 6 阶段细计划（2026-10-28 开工）

**Jun 定（10-28）**：空仓登记写当日 `daily/<日>/passes.jsonl`，**不进 `betslips.jsonl`**（零注票没有票面，账房 / 选择账 / retro 都得逐处排除）。pass 只做两件事：把「待你决定」那条登记截止标成 done，并在停售前留下理由与时间戳。

**改正（相对上面规格）**：
- 外壳不做成 Jinja 继承链。改为一段可 include 的导航 `decision/_nav.html`，数据来自 Jinja 全局函数 `shell()`。这样路由一条都不用改，`/day` `/issue` `/jczq` 只各加一行 include。
- 月度刹车只用 `precheck.month_brake` + `bankroll.status_line`。这和期页、竞彩页的止损块是同一份数；`month_report` 的 effective 口径是同一推导，不再读第二遍。
- 导航上的刹车只放一枚紧凑标记。大号刹车带只在今天页出现；期页、竞彩页头部已有各自的止损块，不重复。
- 账房、实验室链接在第 7、8 阶段落地前，先分别指向 `/betslips`、`/observe`。

##### Task 6.1：pass 记录 + 外壳数据 + 导航 + 今天页数据

- `nutmeg/decision/day_decisions.py`
  - 加 `PASSES = "passes.jsonl"`、`read_passes(data_dir, date)`、`append_pass(data_dir, date, *, channel, target, reason, at) -> (row, existed)`。同一天同 `channel+target` 已有记录就原样返回，不重写。
  - `live_register_decisions` 处理 pass：
    - 当日有该期（足彩）或该日（竞彩）的 pass，且没有实购票时，`status="done"`。
    - 主语改为「足彩 <期> 空仓·已登记 HH:MM」，行内带 `"pass": row`。
    - 有实购票时照旧。
- 新模块 `nutmeg/interfaces/decision_web_shell.py`
  - 入口是 `register_shell(app, templates)`，`decision_web.py` 调一次。
  - **`shell_state(data_dir, now)`**：返回
    - `today`
    - `issues: [{issue, deadline}]`：取自 `lineup_watch.active_issues` 与 `<期>-issue.json` 的 `sale_deadline`
    - `brake: {line, net, effective_net, stop_loss, room, tripped, pending}`：`month_brake` 加上 `status_line`
    - `issue_brake: {期: bankroll.issue_brake(...)}`
    - `errors`
    - 每块各自 try，失败只进 `errors`。
  - **`now` 的取法**：有 `app.state.now` 用它，否则用北京时间当前时刻。
  - **Jinja 全局 `shell()`**：调用 `shell_state`。
  - **`GET /api/shell`**：返回同一份 `shell_state`。
  - **`POST /action/pass`**
    - 请求体：`{channel: "zucai"|"jczq", target, reason}`。
    - 校验：`zucai` 的 target 必须是在售期，`jczq` 的 target 必须是 `YYYY-MM-DD`；不合格返回 400。
    - 理由为空时写「同意机器默认空仓」。
    - 写入 `append_pass(data_dir, today_bj(), ...)`，返回 `{ok, pass, existed}`。
  - **`today_extras(data_dir, date, now)`**：并进 `/api/day/{date}`，内容如下。
    - `shell`
    - `passes`：`read_passes(date)`
    - `glance`：每个在售期一份
      - 字段：`issue`、`deadline`、`default`、`tiers{A,B,b,C,D: 计数}`、`license_rows`、`main_shape{label, price, p, note}`、`alternatives[{label, role, price, p, note}]`、`errors`。
      - `default` 取自 `packet.default`。
      - `license_rows` 取 A/B/b 档行：`[{no, name, tier, k, n}]`，队名用 `decision_web_issue._names`。
      - 全部来自 `packet_doc.load_packet`，页面不计数。
    - `decisions` 每行补字段：
      - `href`：`register_zucai` 指向 `/issue/<期>`，`register_jczq` 指向 `/jczq/<日>`。
      - `pass_target{channel, target}`：仅登记类。
- 模板 `templates/decision/_nav.html` + `static/decision/shell.css`
  - 导航条依次为：NUTMEG · 今天 · 期 <n>（每个在售期一枚，带停售时刻）· 竞彩 · 账房 · 实验室。
  - 右侧是刹车标记：「⛔ 实质 −9,170 / 线 −8,000」或「余 ¥x」，`title` 放 `brake.line` 全文。
  - 当前页由 include 前的 `{% set nav_active = ... %}` 标明。
  - 配色是 issue.css 的同一组 token，写在 `.nm-nav` 下，含浅色和深色。
  - `day.html`、`issue.html`、`jczq.html` 各 include 一次。
- 测试：
  - `tests/decision/test_day_decisions.py`：pass 把登记截止置为 done；`append_pass` 幂等。
  - `tests/test_decision_web_day.py`：
    - `/day`、`/issue/<期>`、`/jczq/<日>` 三页都有导航，且在售期链接存在。
    - 刹车标记的 `title` 等于 `status_line(month_brake(...))`。
    - `/action/pass` 写一次，第二次返回 `existed`。
    - 非在售期返回 400。
    - `/api/day` 的 decisions 带 `href` 和 `pass_target`。
    - glance 的档计数与旁车一致。

##### Task 6.2：今天页换皮（按画布 Today 板）

- `day.html` 改为继承 `decision/layout.html`，不再加载 echarts。仍挂 `day.js` 和 `Day.mount`。
- 页面自上而下：
  - **刹车带**
    - 大数字依次是本月实质、止损线、越线或余量、刹车档（`issue_brake`），下接 `brake.line` 全文。
    - 按钮「登记本期空仓」只在有在售期、登记截止未 done 时出现。点开是理由输入框，预填 `glance.default.reason`，确认后调 `/action/pass`。
    - 另有「看账房」按钮。
  - **两栏**
    - 左栏：
      - 今日时间轴：已跑作业、各截止、首场开球、「现在」，只做排序。
      - 待你决定：卡片显示截止倒计时和机器默认，带 `href` 按钮与「同意空仓并登记」；已 done 的显示「空仓·已登记 HH:MM」。
    - 右栏：
      - 期一眼：档计数、A/B/b 行 k/n 小条、主形和并排参考形（¥ / P）、默认动作与理由、链接到期页。
      - 竞彩一行：场数，链接到竞彩页。
      - 运维一行：告警数，链接 `/runs/<日>`。
  - **折叠区**：竞彩卡、昨日、RSI、会话入口、讨论五块原样保留。讨论输入保持可用。
- 视觉：与 issue.css 同一套 token；只用 `textContent`；每 60 秒刷新；390px 无整页横滚。
- 浏览器验收在沙盒 10-28 做：
  - 刹车带数字与 `status_line` 一致。
  - 点「登记本期空仓」后，待你决定变为 done，`passes.jsonl` 多一行。
  - 导航在三页都能互相跳转。
  - 浅色、深色都要看。

### 第 7 阶段：账房 `/ledger/{月}`

- **数据**：`account.month_report(data_dir, month)`（净、注金、分渠道、待结、理由账、否决仍买、初稿账）+ `choice_ledger.build_choices(data_dir, start=…)`（选择账）+ `bridge.bridge_ledger`（桥后改动账）。
- **新函数 `account.daily_curve(data_dir, month) -> list[{day, net, line}]`**：按结算日累计 `month_net` 的 entries，`line` 取当日生效的止损线（−3,000 → 10-11 −6,000 → 10-18 −8,000 的历史要在函数里写成常量表并注明出处 `design_series` 第 ⑦ 条）。机器初稿线用 `draft_board` 的逐期结果累计。
- **验收**：`test_daily_curve_matches_month_net`（曲线末点 = `month_net.net`）；`test_ledger_api_has_three_ledgers`。

#### 第 7 阶段细计划（2026-10-28 开工）

**勘察结论**：
- `month_report` 每次跑两遍 gym 回放（`out_dir=None`，不写盘）：沙盒 10 月整份 6.4 s，其中规则 v3 5.8 s、初稿账约 0.2 s（Task 7.1 实测）。主页面不能等它，所以 `month_report` 加 `with_draft` / `with_rule_v3` 两个开关。
- 记分牌 tickets 只记了 `encoded_at`，没有结算日。足彩期按 `sale_deadline` 归日，竞彩按键里的日期归日，和 `ticket_month` 的归月口径一致。

**改正（相对上面规格）**：
- **初稿账单独接口，按需加载。** `month_report` 加 `with_draft=True` 参数。主接口传 False，初稿账走 `/api/ledger/{月}/draft`，进程内按（月，scoreboard 与 betslips 的 mtime）缓存。
- **机器初稿线这轮不画。** `draft_board` 只有月合计，没有逐期结果。初稿账以三列数字卡出现。逐期曲线需要 gym 的 per-issue 输出，等以后再接。
- **止损线历史写成常量表，放在 `bankroll.py` 的 `MONTHLY_STOP_LOSS_YUAN` 旁边，不放在 account 里。** 那段 docstring 本来就记着这段历史。表的最后一项必须等于 `MONTHLY_STOP_LOSS_YUAN`，由测试守。

##### Task 7.1：曲线 + 账房接口

- `nutmeg/decision/bankroll.py`
  - 加 `STOP_LOSS_HISTORY = (("2026-10-01", 3000), ("2026-10-11", 6000), ("2026-10-18", 8000))` 与 `stop_loss_on(day) -> int`，出处是 `design_series` 第 ⑦ 条。
  - 加 `ticket_day(key, data_dir) -> str | None`：`jczq-YYYYMMDD` 取那一天；足彩期号取 `sale_deadline[:10]`。`ticket_month` 改为基于它实现，口径只有一处。
- `nutmeg/decision/account.py`
  - `daily_curve(data_dir, month) -> {"points": [{day, net, line}], "moves": [{day, from, to}], "effective": {day, net} | None}`。
    - `points` 按 `ticket_day` 汇总当天净值并累计，每一步一点，`line` 取 `stop_loss_on(day)`。
    - `moves` 是当月内止损线的变动。
    - `effective` 是今天的「实质」点：已结净值减去待结注金，取 `pending_ledger`。
  - `month_report` 加 `with_draft` 参数，默认 True，CLI 行为不变。
- 新模块 `nutmeg/interfaces/decision_web_ledger.py`：入口 `register_ledger_routes(app, templates)`，由 `decision_web.py` 调用一次。
  - `ledger_payload(data_dir, month)` 返回：
    - `month`、`months`：记分牌里出现过的月份，降序。
    - `report`：`month_report(with_draft=False)` 里可 JSON 化的部分。
    - `curve`：`daily_curve` 的结果。
    - `issues`：本月足彩逐期 `[{issue, stake, payout, net, slips}]`，来自记分牌 tickets。
    - `jczq_days`：本月有票的竞彩日 `[{day, stake, net}]`。
    - `choices`：`build_choices`，期范围取本月各期的最小与最大期号。
    - `bridges`：`[bridge_ledger(期)]`，只列走过桥的期。
    - `errors`：每块各自 try，失败只进这里。
  - 路由：
    - `GET /ledger`：307 到当月。
    - `GET /ledger/{月}`：页面外壳，`nav_active = "ledger"`。
    - `GET /api/ledger/{月}`：返回 `ledger_payload`。
    - `GET /api/ledger/{月}/draft`：返回 `draft_board`，带缓存。
    - 月份格式不是 `YYYY-MM` 时返回 400。
  - `_nav.html` 的「账房」链接改为 `/ledger`，并加上 `aria-current`。今天页的「看账房」也改指 `/ledger`。
- 测试：
  - `tests/decision/test_account_curve.py`：
    - 曲线末点等于 `month_net.net`。
    - 线在 10-11 和 10-18 换档。
    - `STOP_LOSS_HISTORY` 最后一项等于 `MONTHLY_STOP_LOSS_YUAN`。
    - `ticket_month` 的结果不变（对照现有用例）。
  - `tests/test_decision_web_ledger.py`：
    - 主接口不调用 gym（monkeypatch `draft_board` 为抛错，主接口仍 200）。
    - 三本账字段都在。
    - 坏月份返回 400。
    - `/draft` 第二次调用命中缓存。

##### Task 7.2：账房页前端（按画布 Ledger 板）

- 新增 `templates/decision/ledger.html`、`static/decision/ledger.js`、`static/decision/ledger.css`。沿用 issue 与 today 的同一套 token，浅色、深色都要做。
- 页面自上而下：
  1. **月份切换**：取 `months`。
  2. **四块数字**：
     - 净值 vs 空仓。
     - 投入 / 返奖 / 回收率。
     - 足彩 N 期净值，含中奖期。
     - 竞彩 N 个出票日净值。
     - 实质余量一行，取 `report.pending`、`effective_net`、`effective_room`。
  3. **曲线**：内联 SVG，阶梯折线。
     - 画三样：实际净值、0 线（空仓）、止损线。止损线是阶梯，`moves` 处要标注，且不能隐藏。
     - 今天的实质点画成虚线。
     - 只画服务端给的点，页面不累计。
  4. **足彩逐期表**：每期的投入、返奖、净值，每期链到 `/issue/<期>`。
  5. **理由账**：
     - 按理由列出张数、投入、净值、待结数。
     - 开球后才写理由的单列。
     - 审票否决仍买的单列，含否决码计数。
  6. **初稿账**：懒加载 `/draft`，三列分别是实际出票、机器初稿、空仓。加载中显示「回放中…」。
  7. **选择账**：每期列 Jun 的票形与净值、机器形的净值、丢光 C 档形的净值。
  8. **桥后改动账**：每期列 B1 与实票的差异格。
- 只用 `textContent`；390px 宽时整页不横滚（表格在自己的容器里横滑）。
- 浏览器验收在沙盒做：
  - 10 月曲线末点 = −9,170 与记分牌一致，两次换线的标注可见。
  - 初稿账能加载出来。
  - 浅色、深色都要看。

### 第 8 阶段：实验室 `/lab`

- **数据**：`account.experiment_board(data_dir)`（各实验 n / n_min / verdict）、`account.rule_v3_board`；每行链 `/observe/exp/{id}`（已有页，不重做）；否决清单写死在模板里并注明来源（RULEBOOK「〇」：只有 V1/V2 有实证，止损/刹车是 Jun 签的线）。
- **研究消费读数**：`bridge_ledger` 跨期汇总「理由指到矩阵行 / 差异格」——这是画布上 `[k / n]` 的真实来源，第 3 阶段落盘后才有数。
- **验收**：`test_lab_api_lists_live_experiments`（退役实验不出现在活跃表）。

#### 第 8 阶段细计划（2026-10-28 开工）

**勘察结论**：
- 画布上「它量什么 / 在表上是哪一列 / 状态」三列分别取自三处：
  - 登记原件 `experiments/registry/<id>.json` 的 `claim`。
  - `exits` 里的 `packet_column:<列>`。
  - 实证标签。实证 / 已证伪 / 测不出 / 未证 n/n_min / 退役 这套标签现在**只在 CLI**：`interfaces/cli/rsi.py` 的 `_evidence_label` 和 `rsi columns` 命令体。
- `account.experiment_board` 已经给出 n / n_min / metric / CI / verdict，但不读登记原件，也不管退役。

**改正（相对上面规格）**：
- **实证标签搬出 CLI**，成为唯一实现。`rsi columns` 改调它，输出逐字不变。这一条与第 0 阶段搬预审同理：否则会造出第二份标签逻辑。
- **规则 v3 回放不进实验室页。** 它要跑 gym 5.8 s，`nutmeg account month` 里照旧有，页面只链过去。
- **gym 403 天结论卡写死在页面里**，注明出处为 `evidence/2026-10-01-replay-gym.md` 与 `2026-10-01-history-expansion.md`。理由同否决清单：这是常驻结论，不是每次现算。

##### Task 8.1：实验室接口

- 新模块 `nutmeg/decision/lab.py`：
  - `evidence_label(e, v, d, g, f)`：从 CLI 原样搬来。CLI 的 `_evidence_label` 删掉，改从这里 import。
  - `registry_docs(registry_dir) -> {exp_id: doc}`：跳过 `_draft_*`，用 `rsi_prereg.load_registry_doc` 读。
  - `lab_board(data_dir, registry_dir) -> {"live": [...], "settled": [...], "errors": [...]}`：
    - 每行字段：`{exp_id, claim, layer, tier, n, n_min, metric_pp, ci, label, verdict, columns:[列], window, source_doc}`。
    - 判决与退役从内核读，读法同 `rsi columns`。
    - 进 `settled` 的行：已结账（协议 v2）、退役或到期。其余进 `live`。
    - 内核读不出时只进 `errors`。
  - `columns_line(board)`：`rsi columns` 的那一行文本由它生成，CLI 打印它。
- `nutmeg/decision/bridge.py`：
  - 新增 `cite_totals(data_dir) -> {issues, diffs, matrix, outside, blank}`。
  - 做法：汇总所有 `zucai/*-bridge.jsonl` 的首条记录，各取 `cite_readout(rec["diffs"])` 相加。
- 新模块 `nutmeg/interfaces/decision_web_lab.py`：
  - 入口：`register_lab_routes(app, templates)`。
  - `lab_payload(data_dir, registry_dir, *, launchd)` 返回：
    - `board`：`lab_board`。
    - `cites`：`cite_totals`。
    - `ops`：`{jobs, alarms:[label], failed_runs}`，其中 `jobs` 和 `alarms` 来自 `day_ops.launchd_rows`，`failed_runs` 是今日 runs 里 exit≠0 的段数（读取方式与 `/runs` 页同源）。
    - `errors`。
  - 每块各自 try，失败只进 `errors`。
  - 路由：
    - `GET /lab`：页面外壳 `templates/decision/lab.html`，含 `nav_active = "lab"` 和 nav include。`lab.js` 与 `lab.css` 先放占位文件。
    - `GET /api/lab`。
  - `registry_dir` 默认取仓内 `experiments/registry`，与 CLI 默认一致。
  - `_nav.html` 的「实验室」链接改为 `/lab`，并加 `aria-current`。
- 测试：
  - `tests/decision/test_lab.py`：
    - `evidence_label` 五种结果各一例。
    - `rsi columns` 在一个沙盒库上改前改后输出一致。
    - `cite_totals` 跨两期相加。
  - `tests/test_decision_web_lab.py`：
    - 退役实验不出现在 `live`（`test_lab_api_lists_live_experiments`）。
    - `/api/lab` 在内核不可达时仍返回 200 并带 `errors`。
    - 导航指向 `/lab`。

##### Task 8.2：实验室页前端（按画布 Lab 板）

- 新增 `templates/decision/lab.html`，以及 `static/decision/lab.js`、`lab.css`。沿用 ledger / day 的同一套 token，class 加 `lab-` 前缀，浅色、深色都要做。
- 页面自上而下：
  1. **「哪条规则有资格拦你」**：写死三张卡。
     - V1 期望回报率 < 0.5。
     - V2 共享裸单，例证 26122 73.8%。
     - 宪法纪律：止损 / 刹车档 / 日帽。这是你签的线，不是实证规则；预审标 ⛔，登记不受限。
     - 三张卡都注明出处 RULEBOOK「〇」。
  2. **「决策表上的列 · 离判决还有多远」**：`live` 表，每行列编号（链 `/observe/exp/<id>`）、它量什么（`claim` 首句）、`n / n_min` 小进度条、状态（`label`）、在表上是哪一列。表下注一行：「一列只有过了登记的 bound 才有资格变成否决；在那之前，它在决策表上永远是虚线框。」
  3. **gym 结论卡**：写死，注明出处。
  4. **「已判决 · 退役」**：`settled` 每行列编号、`label` 与 `claim` 首句。
  5. **「研究层消费量」**：`[matrix / diffs]`，另列矩阵外与空白的计数。`diffs` 为 0 时写「还没有桥后改动」。
  6. **运维一行**：作业数、告警、失败段数，链 `/runs/<今天>`。
- 只用 `textContent`；`errors` 要看得见；390px 宽时整页不横滚。
- 浏览器验收在沙盒做：
  - live / settled 的行数与 `nutmeg rsi status` 一致。
  - 浅色、深色都要看。
  - 375px 宽时检查横滚。

### 第 9 阶段：口袋窗

- **页面**：所有新页在 390px 宽可用（表横滚、侧栏下沉、按钮 ≥44px），不另做 app。
- **推送**：`day_broadcast.render_broadcast` 与 `lineup_watch` 的推送文本末尾带页面链接（`/issue/<期>`、`/jczq/<日>`）。**链接能不能在手机上打开取决于 Jun 的决定**：decision-web 现在只绑 127.0.0.1（`_warn_if_exposed` 明说无鉴权）。三选一——不加链接 / 局域网绑定 / 隧道加鉴权——开工前由 Jun 定，计划默认「不加链接」。
- **验收**：`test_broadcast_link_off_by_default`。

**勘察结论（2026-10-29，沙盒 390×844 实测）**

- 今天 / 期 / 竞彩 / 账房 / 实验室 五页静态态：`scrollWidth == 390`，无越界元素，页内按钮全 ≥44px（第 1–8 阶段各页已带 `max-width:600px` 断点）。期页开抽屉后同样无越界。
- 真问题有三处：
  1. **表横滚把票藏起来了**：期页 `#table`（min-width 960）与竞彩 `.tbl`（min-width 1040）在 390 宽只露出 场·对阵·档，3/1/0 格与 SP 格要横滑才看得到——「表即票」在手机上不成立。
  2. 共享导航 `.nm-nav` 的链接高 32px（<44）。
  3. 旧页 `/runs` 的筛选 chip 高 30px（`/observe` 顶栏链接 20px，旧页，不在本阶段）。
- 推送：`day_broadcast.render_group` 末行写死「打开 /day 处理」（相对路径，手机上点不了）；`lineup_watch` 三类推送（zucai.lineup / countdown / shift）不带链接。

**改正**：「表横滚」改为「≤600px 行折成两行卡片」：第一行 场/编号·对阵·档（竞彩加开球），第二行 3/1/0 或 SP 格占满宽；其余列（标签、人群、死门等）留在行内抽屉或下沉为第三行小字，不再横滑。

**Jun 的三选一按默认「不加链接」落地**：推送链接做成配置项，未配置＝不加（现状），配置了才加；绑定地址不动（仍 127.0.0.1）。哪天选局域网或隧道，只需设 `NUTMEG_DECISION_WEB_URL` 并另行处理绑定/鉴权——那一步是对外暴露，单独定。

#### Task 9.1：推送带页面链接（默认关）

- `Settings` 加 `decision_web_url: str = ""`（env `NUTMEG_DECISION_WEB_URL`）。
- 纯函数只收参数：`render_group(group, *, base_url="")`；有 base_url 时末行换成 `打开 {base}/issue/<期>` 或 `{base}/jczq/<日>` 或 `{base}/day/<日>`（路径取自第 6 阶段给决定配 href 的同一处实现，不另推导）；无 base_url 时输出与现在逐字一致。
- `lineup_watch` 的三类推送同样在文本末尾加 `{base}/issue/<期>`（仅配置时）；指纹 `_fp` 对加链接前的正文算，配置改动不重发。
- 调用方（broadcast 作业、lineup 作业）从 settings 读出传入。
- 测试：`test_broadcast_link_off_by_default`（未配置逐字不变）、配置后带链接且去尾斜杠、lineup 三类同理、指纹不随 base_url 变。

#### Task 9.2：390px 收尾

- 期页、竞彩页：≤600px 行折成卡片（见「改正」），格子 ≥44px，点格入串/切换与桌面同一套 JS 事件（只改 CSS，必要时给行加 class，不改数据流）。
- `shell.css`：≤600px 导航链接 ≥44px，横滑保留。
- `runs.css`：≤560px chip ≥44px。
- 验收：沙盒 390×844 下五页 + 期页抽屉/§3 桥展开 + 竞彩入两腿后，`scrollWidth == innerWidth`，3/1/0 与 SP 格在不横滑时可见，桌面 1440 宽外观不变。

#### Task 9.3：装到手机主屏幕 + Tailscale（2026-10-29 Jun 定：不做微信小程序，走「网页装成 App」）

**为什么不是小程序**：彩票类上架审核不过（2018 十二部门禁止擅自利用互联网销售彩票，页上有登记/审票）；个人主体类目受限；要备案域名的公网 HTTPS 与鉴权；四页要用 WXML 重写＝两套前端，违背「数字只有一处」。

- 页头：`_pwa_head.html`（manifest、图标、iOS 全屏、theme-color 明暗两档、`pwa.js`），由 `layout` / `observe/layout` / `runs` 三个服务端模板 include；`verdict.html` 是落盘独立文件，不挂。
- `/manifest.webmanifest`：`start_url=/day`、`display=standalone`、`scope=/`；图标 `static/decision/icons/`（`icon.svg` 为源，`rsvg-convert` 出 180/192/512）。
- `pwa.js`：只在全屏模式生效——切走超过 5 分钟、页上没有未提交输入时，切回前台重载一次（全屏没有下拉刷新，停售倒计时/刹车/首发会停在旧数）。不加 service worker：决策页不该离线显示旧数。
- 写入同源守卫：带 `Origin` 的非 GET 请求必须与 `Host`（或 `X-Forwarded-Host`）同源，否则 403；无 Origin（CLI/测试/curl）放行。有了真域名后，别的站点里的表单打不进账本。
- 发布：`scripts/phone_access.sh on|off|status`——`tailscale serve --bg 8787`（只到自己的 tailnet，服务仍绑 127.0.0.1），并把 `https://<机器>.<tailnet>.ts.net` 写进 `.env` 的 `NUTMEG_DECISION_WEB_URL`（Task 9.1 的推送链接就此打开）；`off` 撤发布、删该行。
- Jun 本人做：Mac 与 iPhone 装 Tailscale、同一账号登录；跑 `on`（首次按提示在后台开 HTTPS 证书）；iPhone Safari 打开 → 分享 → 添加到主屏幕。Mac 睡眠时手机打不开（launchd 作业本来也要求醒着）。
- 测试：`test_manifest_and_icons_for_home_screen`、`test_cross_site_writes_are_refused`。

#### Task 9.4：改走校园网 + 密码门（2026-10-30 Jun 定，Task 9.3 的 Tailscale 发布暂停）

**为什么换**：iOS 同一时间只能开一个 VPN，Tailscale 与 Jun 日常用的学校 VPN 不能共存；手机连学校 VPN 本来就进校园网，能直接到 Mac（`10.209.80.225`，`dynapool.shanghai.nyu.edu` 动态地址池）。代价：校园网上任何人都能连到这台 Mac（防火墙关），所以必须有密码；校园网内段是明文 http。

- `decision_web_auth.register_password_gate`：非本机（127.0.0.1 / ::1 之外）访问先过 `/login`，成功发 180 天 cookie（值＝密码的 HMAC，改密码即全部失效）；页面跳登录、接口 401；manifest 与图标不设门；同 IP 连错 5 次锁 15 分钟；`next` 只许站内路径。
- CLI：绑非本机地址而 `NUTMEG_DECISION_WEB_PASSWORD` 未设 → 拒绝启动（exit 2），fail-closed。
- launchd `decision.web`：`--host 0.0.0.0 --port 8787`。
- 推送链接：`NUTMEG_DECISION_WEB_URL=lan:8787` → `settings.decision_web_base_url()` 每次发送取默认路由出口 IP，拼 `http://<IP>:8787`；IP 变了推送照样对，主屏幕图标需重加。
- 测试：`test_non_loopback_host_needs_password`、`test_password_gate_for_other_machines`、`test_password_gate_locks_after_five_misses_and_spares_localhost`、`test_push_link_base_follows_lan_ip`。

---

### 追加 Task 7.3：账房曲线加「足彩换成机器初稿」线（2026-10-29）

**勘察**：第 7 阶段说「初稿线需要 gym 的 per-issue 输出」——其实已有：`run_gym(...).ledger` 每行带 `key`（业务日＝`ticket_day`）、`issue`、`policy`、`net`。沙盒 10 月 16 期逐期核对：`real` 策略逐期净 == 记分牌 `tickets[<期>].net`（无票期两边都是 0/缺）。

**画什么**：不是「机器初稿单独一条」（它只有足彩，和含竞彩的实际线比会误导），而是**反事实线**：竞彩照实际，足彩每期把实际净换成机器初稿回放净。
`cf(d) = actual(d) + Σ_{期日 ≤ d} (draft_net(期) − real_net(期))`，只计两边都已结算的期。两条线竞彩部分相同，差距全来自足彩票面。不套止损（与初稿账一致：比票面，不比止损）。

**落点**
- `account.draft_board` 结果加 `by_issue:[{issue, day, real, draft}]` 与 `curve:[{day, net}]`（反事实累计，日子＝实际曲线点日 ∪ 期日）；计算只在 account.py 一处。仍走懒加载 `/api/ledger/{月}/draft`，主接口不变。
- `ledger.js`：初稿账加载完成后在同一张阶梯图上叠一条虚线（独立颜色 token、明暗两套），图例写「足彩换成机器初稿（竞彩照实际·不套止损）」，末点标数；`_error` 或无 curve 时不画。
- 测试：monkeypatch `run_gym` 的单元测试（有待结期、无票期、竞彩日）；web 测试 `/draft` 带 `curve`。

### 第 10 阶段：对话与纠正（2026-10-30 设计，画布第四行，未开工）

**依据**：06-13→10-30 共 40 个会话、Jun 约 560 句话分四段并读。约 235 次追问（选面/票形 ≈55、单场深挖 ≈25、统计样本 ≈25、进度状态 ≈25、要不要补跑 ≈10）；约 105 次纠正，记录散在复盘页、记分牌、改判账、证据文档、记忆五处；复发最多：止损余量不含待结票 ≥6 次、截图抄录 ≥8 次、实票开球后登记 ≥5 次、研究前提错且无自纠通路 4 次；同一提案被重复问 3–5 次（K1 修正案、足彩机器 Read 归属、判死面清零口径、26147 三提案）。

**四个新对象**（都只追加、不改原件；页面不推导）
- 线程 `thread`：锚定 `obj`（`issue:26153/m7/q4`、`ticket:26153-T1`、`ledger:2026-10/26152`、`rule:六条件④`）的问答，复用 `day_session` 的 discussion 记录加 `obj` 与 `reply_to`。
- 纠正 `correction`：`obj`、`old`、`new`、`kind`（数据·账目｜抄录｜研究前提｜机器自纠｜你改判）、`found_by`、`evidence`（URL/原句/官方）、`dest`（scoreboard｜research override｜premise→store 画像｜RULEBOOK｜无处可写）、`status`（草稿→已确认→已回写）、`recurs_of`。回写复用现有命令（`research override`、`zucai-premise-corrections --apply`、记分牌写入），纠正对象只记账与路由。
- 提案 `proposal`：编号、正文、拦住了什么、截止、`asked_count`、`status`（待签｜签｜改｜否）＋你的原话；笼统批准展开成覆盖清单。签了才执行，执行结果回挂。
- 票据收件 `intake`：截图 → 识别格 → 逐格确认（底部注数/金额对上才放行）→ 已购/试玩 → 理由与预测 → `betslip preview` → 登记；开球后提交标「开球后写入」。

**应答员**：页面提问进队列，后台 worker 用 Claude 无头会话（读该对象的研究原件、市场、票、SOP 三件套）作答，写回同一线程，并同步到 Telegram；会改表的回答只能产出纠正草稿或提案草稿。待定：用 `claude -p`（launchd 下登录过期风险，见运维记忆）还是 OpenClaw nutmegbot 的 agent 通道。

**建议顺序**（先做复发最多、最不依赖应答员的）
1. Task 10.1 各页统一「实质余量」（含待结票）——同一个数只算一处（`account.pending_ledger`），今天/期页/审票/账房都读它。
   **已做（2026-10-30）**：推导收进 `bankroll.with_pending`（`brake_state`、账房月报、账房曲线实质点都走它），带登记簿的完整状态统一 `precheck.month_brake`；当日报告账房行与判决页原先不含待结票，已改；账房月报 `tripped`/`room` 只剩实质口径（删 `effective_room`/`effective_tripped`），`account month` 首行不再打已结口径的「余」；单一来源守卫加 `effective_room` 规则（AST：减待结票 stake 的表达式只许在 bankroll.py）。生产数据核对：预审、各页、月报、当日报告、判决页同为实质 −9,685（待结 3 张 ¥944）。
2. Task 10.2 纠正对象 + `/corrections` 纠正账 + 格子「修 HH:MM」与「自你上次看过改了 N 处」；旧记录（复盘页、记分牌备注、改判账、证据文档、记忆）做一次回填。
   **已做（2026-10-30）**：`corrections.py`（只追加事件账 `corrections.jsonl`、按 id 折叠、复发堆 `pile`）、CLI `nutmeg correction add/list/status/backfill`、`/corrections` 页（类型筛选、复发堆、草稿可「确认 / 不改·记一笔」）、导航草稿角标、期页场行「修」标记（当天写时刻、更早写日期）与「自你上次看过改了 N 处」（localStorage）。回填：会话种子 34 条（`evidence/2026-10-30-corrections-seed.json`）+ 主循环改判 31 条；研究员 `premise_corrections` 约 1,500 条是例行前提卡修正，不逐条进账。RUNBOOK 加「纠正一律进账」。
3. Task 10.3 待签收件箱 `/inbox`（今天页与手机底栏带角标）；CLI `nutmeg inbox propose` 供会话起草。
4. Task 10.4 应答员 + 行内追问（期页、竞彩板、账房行），快捷问法：要防平吗／钱往哪边／和哪场死法像／要补跑吗／只能单选呢。
5. Task 10.5 票据收件（截图识别走应答员的看图能力）。

画布：Dialog（蓝图）、AskPhone、IntakePhone、SignPhone、Corrections 五板。

## 3. 需要 Jun 定的三件事（不定也能做到第 5 阶段）

1. **旁车由谁写**：计划默认 `/zucai-packet` 会话同写 `<期>-packet.json`（Task 1.1 改命令文件）。替代是把六条件计数做成代码——那是规则定义，要走 RULEBOOK「〇」两段式，不该夹在界面工程里。
2. **空仓登记落在哪**：`betslips.jsonl` 零注记录 vs `decisions` 的 `pass` 动作（第 6 阶段开工前）。
3. **手机怎么打开页面**：不加链接 / 局域网 / 隧道加鉴权（第 9 阶段开工前）。

## 4. 自检（写完后对着画布逐板核）

- 画布七块板 → 阶段：期页表即票（1）、取证抽屉（2）、§3 桥（3）、500 票面（4）、竞彩当日板（5）、今天（6）、账房（7）、实验室（8）、手机（9）、蓝图（不落地，是说明页）。无遗漏。
- 「否决不拦登记」：第 0 阶段 `register_reviewed` 只记码；第 3、4、5 阶段都走它。
- 「界面不推导」：P / 注数 / V 码 / 刹车 / 死法清单只在 `precheck`、`review`、`bankroll`、`slip_group`；六条件只在旁车；`board_rows` 守卫不破。
- 命名一致：`build_slip / precheck / register_reviewed / format_faces_row / shape_of / load_packet / issue_payload / self_checks / diff_cells / append_bridge / bridge_ledger / daily_curve` 在各阶段引用处同名。
