# Dream 夜间录制 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每晚 20:30 在常设批准（至 2026-10-31）下自动录一个 Dream 世界（只收未开球场次、冻结当时的实际票面），次日 10:45 把「实际出票 / 决策规则最优 / 世界各档最优 / 空仓」对着 90 分钟赛果记账。

**Architecture:** 先修两处让真实世界必败的问题——生成器物化循环（P0）与评估器 v1 的每档 20 上限整片判失败（Jun 2026-09-28 批评估器 v2）。day 源加开球过滤与票面引用（P1）；常设批准模块派生现有录制器认的单次批准（P2）；`discovery nightly` 录制并写仓外报告，报告里预先算好两种对照票面（P3）；`discovery compare` 次日按赛果记账，挂进 `rsi loop`（P4）。

**Tech Stack:** Python 3.13、typer、pytest、SQLite 影子库（`~/nutmeg-shadow`）、launchd。

**Spec:** `docs/superpowers/specs/2026-09-28-dream-nightly-recording-design.md`（本计划 Task 12 追加评估器 v2 与「对照料在录制时算」两处修订）。

**工作区：** 在 worktree 里做，避免 launchd（`day.broadcast` 每 10 分钟、`rsi.sweep` 每小时）在迁移中途导入半成品代码（2026-09-23 事故）：

```bash
cd /Users/jz71/Projects/Nutmeg
git worktree add ../Nutmeg-dream-nightly -b feat/dream-nightly
cd ../Nutmeg-dream-nightly && uv sync
```

以下所有路径都相对 worktree 根目录；测试一律 `uv run pytest …`。提交只用显式路径 `git add <path>`（绝不 `-A`/`-u`）。

---

## 文件结构

| 文件 | 责任 |
|---|---|
| `nutmeg/discovery/candidates.py`（改） | 物化只走计数门算的那个空间；批次数对账 |
| `nutmeg/discovery/contracts.py`（改） | `EVALUATOR_REVISION` 常量与 v2 字面量 |
| `nutmeg/discovery/selection_contract.py`、`world_pool.py`（改） | 跟随评估器 v2 |
| `experiments/discovery/structural-{candidate,selection}-v1.contract.json`（改） | 评估器 v2 重冻结 |
| `nutmeg/discovery/online_adapter.py`（改） | 评估器 v2：每档超上限不判失败；抽出分片枚举；`best_candidates_by_band` |
| `nutmeg/discovery/day_inputs.py`（改） | 开球过滤、`DayBoardTooSmall`、票面引用、指纹含票面、`extra_references` |
| `nutmeg/discovery/standing_approval.py`（新） | 读常设批准、逐条校验、派生单次批准、批准引用、到期天数 |
| `nutmeg/discovery/online_recorder.py`（改） | 独立复核时带上批准引用 |
| `nutmeg/discovery/dream_compare.py`（新） | 对照料（决策规则最优、各档最优、赔率簿）与次日记账、累计汇总 |
| `nutmeg/discovery/nightly.py`（新） | 一晚一个世界的编排：批准→快照→录制→报告 |
| `nutmeg/interfaces/cli/discovery.py`（改） | `discovery nightly`、`discovery compare` |
| `nutmeg/decision/day_runner.py`、`nutmeg/interfaces/cli/day.py`（改） | `day run --job dream` |
| `ops/launchd/com.nutmeg.day.dream.plist`（新） | 每天 20:30 |
| `nutmeg/decision/rsi_loop.py`（改） | `dream_compare` 步骤与报告节 |
| `experiments/discovery/approvals/standing-dream-nightly-2026-10.json`（新，主会话落） | 常设批准 |

---

### Task 1: 生成器物化只走计数门算的空间（P0）

**Files:**
- Modify: `nutmeg/discovery/candidates.py`（`enumerate_candidates` 物化段约 503–510 行；删 `_batch_respects_group_limits` 约 681–692 行；新增 `_limited_batches`）
- Test: `tests/discovery/test_candidates.py`

- [ ] **Step 1: 写失败测试**（追加到 `tests/discovery/test_candidates.py` 末尾）

```python
def _reference_batches(inputs: CandidateGenerationInput) -> list[tuple[str, ...]]:
    """2026-09-28 之前的物化：先 combinations(全部原子票) 再按模板组数过滤。"""
    from itertools import combinations as _combinations

    from nutmeg.discovery.candidates import _enumerate_atomic_tickets

    by_number = {offer.official_match_no: offer for offer in inputs.offers}
    atomic = _enumerate_atomic_tickets(inputs, by_number)
    limits = {template.structure_code: template.maximum_groups for template in inputs.templates}
    batches: list[tuple[str, ...]] = []
    for size in range(1, min(inputs.maximum_ticket_count, len(atomic)) + 1):
        for batch in _combinations(atomic, size):
            counts: dict[str, int] = {}
            for ticket in batch:
                counts[ticket.structure_code] = counts.get(ticket.structure_code, 0) + 1
            if all(counts[code] <= limits[code] for code in counts):
                batches.append(tuple(ticket.composition_hash for ticket in batch))
    return sorted(batches)


def _two_template_inputs(*, groups: int, tickets: int) -> CandidateGenerationInput:
    offers = tuple(
        _offer(str(index), ("31", ("3", "1")), ("3", ("3",)), omission_allowed=True)
        for index in range(1, 4)
    )
    templates = tuple(
        CandidateStructureTemplate(
            kind="jczq_pass",
            structure_code=f"pass-{size}-1",
            eligible_official_match_nos=("1", "2", "3"),
            required_offer_count=size,
            maximum_groups=groups,
            pass_size=size,
        )
        for size in (2, 3)
    )
    return _generation_input(
        lane="jczq",
        ticket_kind="jczq_pass",
        offers=offers,
        templates=templates,
        capital_cap_minor=1_000_000,
        maximum_ticket_count=tickets,
        maximum_exhaustive_candidate_count=100_000,
    )


@pytest.mark.parametrize(("groups", "tickets"), [(1, 1), (1, 2), (2, 2), (2, 3)])
def test_materialized_batches_equal_the_filter_after_reference(groups, tickets) -> None:
    inputs = _two_template_inputs(groups=groups, tickets=tickets)
    result = enumerate_candidates(inputs)
    produced = sorted(
        tuple(ticket.composition_hash for ticket in candidate.tickets)
        for candidate in result.candidates
    )
    assert produced == _reference_batches(inputs)
    assert len(produced) == result.calculated_candidate_count


def test_real_board_shape_materializes_without_walking_every_combination() -> None:
    """2026-09-28：7 场、pass-2-1、maximum_ticket_count=20 → 207 个候选；旧循环永远跑不完。"""
    import time

    faces = ("30", "10", "310", "30", "31", "31", "10")
    offers = tuple(
        _offer(
            str(index),
            (code, tuple(code)),
            *((face, (face,)) for face in code),
            omission_allowed=True,
        )
        for index, code in enumerate(faces, start=1)
    )
    template = CandidateStructureTemplate(
        kind="jczq_pass",
        structure_code="pass-2-1",
        eligible_official_match_nos=tuple(str(index) for index in range(1, 8)),
        required_offer_count=2,
        maximum_groups=1,
        pass_size=2,
    )
    inputs = _generation_input(
        lane="jczq",
        ticket_kind="jczq_pass",
        offers=offers,
        templates=(template,),
        capital_cap_minor=200_000,
        maximum_ticket_count=20,
        maximum_exhaustive_candidate_count=50_000,
    )
    started = time.monotonic()
    result = enumerate_candidates(inputs)
    assert result.calculated_candidate_count == 207
    assert len(result.candidates) == 207
    assert time.monotonic() - started < 10
```

- [ ] **Step 2: 确认失败**

Run: `perl -e 'alarm 30; exec @ARGV' uv run pytest tests/discovery/test_candidates.py -k "real_board_shape or filter_after_reference" -q`
Expected: 四个参数化用例 PASS（旧实现与参照相同），`test_real_board_shape…` 卡死被 `alarm` 杀掉（输出 `Alarm clock`）。

- [ ] **Step 3: 实现**

`enumerate_candidates` 里把

```python
    drafts = tuple(
        _candidate_draft(batch)
        for size in range(1, maximum_batch_size + 1)
        for batch in combinations(atomic, size)
        if _batch_respects_group_limits(batch, inputs.templates)
    )
```

换成

```python
    drafts = tuple(
        _candidate_draft(batch)
        for batch in _limited_batches(atomic, inputs.templates, maximum_batch_size)
    )
    if len(drafts) != calculated_count:
        raise RuntimeError("candidate batch count did not reconcile")
```

删除 `_batch_respects_group_limits`，在原位置新增：

```python
def _limited_batches(
    atomic: Sequence[CandidateTicket],
    templates: Sequence[CandidateStructureTemplate],
    maximum_batch_size: int,
) -> Iterator[tuple[CandidateTicket, ...]]:
    """只物化 `_calculated_candidate_count` 数过的那个空间。

    每个模板贡献自己原子票里的 0…maximum_groups 张；批内保持全局原子序，草稿与哈希
    与旧的「先全组合再过滤」逐字相同。2026-09-28 出生事故：旧循环对 207 张原子票做
    combinations(≤20) 再过滤，首个真实世界四个分片全部超时。
    """
    limits = {template.structure_code: template.maximum_groups for template in templates}
    position = {ticket.composition_hash: index for index, ticket in enumerate(atomic)}
    buckets: dict[str, list[CandidateTicket]] = {}
    for ticket in atomic:
        buckets.setdefault(ticket.structure_code, []).append(ticket)
    choices = [
        [
            chosen
            for size in range(min(limits[code], len(bucket)) + 1)
            for chosen in combinations(bucket, size)
        ]
        for code, bucket in buckets.items()
    ]
    for parts in product(*choices):
        batch = [ticket for part in parts for ticket in part]
        if 1 <= len(batch) <= maximum_batch_size:
            yield tuple(sorted(batch, key=lambda ticket: position[ticket.composition_hash]))
```

文件顶部 import 改为 `from collections.abc import Callable, Iterator, Mapping, Sequence`。

- [ ] **Step 4: 确认通过**

Run: `uv run pytest tests/discovery/test_candidates.py tests/discovery/test_candidate_bands.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add nutmeg/discovery/candidates.py tests/discovery/test_candidates.py
git commit -m "fix(discovery): materialize only the batch space the count guard counted"
```

---

### Task 2: 评估器 v2——每档超上限不再整片判失败（Jun 2026-09-28 批）

**Files:**
- Modify: `nutmeg/discovery/contracts.py:31-35`、`nutmeg/discovery/selection_contract.py:34`、`nutmeg/discovery/world_pool.py:133-138`、`nutmeg/discovery/online_adapter.py:96-134`
- Modify: `experiments/discovery/structural-candidate-v1.contract.json:29`、`experiments/discovery/structural-selection-v1.contract.json:4`
- Test: `tests/discovery/test_online_adapter.py`、`tests/discovery/test_contracts.py`，以及 v1 字样的夹具：`tests/discovery/test_world_pool.py`、`tests/discovery/test_selection_contract.py`、`tests/ontology/test_discovery_governance_actions.py`、`tests/ontology/test_discovery_policy_actions.py`、`tests/ontology/test_discovery_repository.py`

- [ ] **Step 1: 写失败测试**

`tests/discovery/test_online_adapter.py`：删除 `test_over_cap_is_explicit_failure_with_cost`，换成

```python
def test_band_over_cap_is_evaluated_not_failed_under_evaluator_v2():
    """v2（Jun 2026-09-28）：每档候选超过上限不再整片判 over_cap；质量字段只看有效候选的
    最高 P、有候选的档数、按上限封顶的计数，与 v1 数值相同。"""

    def too_many(inputs, **kwargs):
        result = enumerate_band_candidates(inputs, **kwargs)
        band = result.by_band["10x"]
        many = replace(band, candidates=band.candidates * 21)
        return replace(result, by_band={**result.by_band, "10x": many})

    plain = execute_template_shard(_snapshot(), ("1x1",))
    result = execute_template_shard(_snapshot(), ("1x1",), enumerate_fn=too_many)
    assert "over_cap" not in result.diagnostic_codes
    assert result.status == plain.status
    assert result.evaluation == plain.evaluation
    counts = result.artifact_manifest["band_candidate_counts"]
    assert counts["10x"] == 21 * plain.artifact_manifest["band_candidate_counts"]["10x"] > 0
```

`tests/discovery/test_contracts.py` 末尾追加：

```python
def test_shipped_pilot_and_selection_contracts_use_evaluator_v2():
    from nutmeg.discovery.contracts import EVALUATOR_REVISION
    from nutmeg.discovery.selection_contract import load_selection_contract

    root = Path(__file__).resolve().parents[2] / "experiments/discovery"
    pilot = load_pilot_contract(root / "structural-candidate-v1.contract.json")
    selection = load_selection_contract(root / "structural-selection-v1.contract.json", pilot)
    assert EVALUATOR_REVISION == "structural-candidate-evaluator-v2"
    assert pilot.evaluator.revision == EVALUATOR_REVISION
    assert selection.evaluator_revision == EVALUATOR_REVISION
```

（若该文件尚未 import `Path`/`load_pilot_contract`，在文件头补 `from pathlib import Path` 与 `from nutmeg.discovery.contracts import load_pilot_contract`。）

- [ ] **Step 2: 确认失败**

Run: `uv run pytest tests/discovery/test_online_adapter.py tests/discovery/test_contracts.py -q`
Expected: 两个新测试 FAIL（`over_cap` 仍在 / `ImportError: EVALUATOR_REVISION`）。

- [ ] **Step 3: 实现**

`nutmeg/discovery/contracts.py`，在 `class OperatorSpec` 之前加：

```python
EVALUATOR_REVISION = "structural-candidate-evaluator-v2"
"""v2（Jun 2026-09-28）：每档候选超过 `candidate_count_cap_per_band` 不再整片判 over_cap
失败。三个质量字段只看有效候选的最高 P、有候选的档数、按上限封顶的计数，数值与 v1 相同；
v1 让每个真实 day 源世界（每档几百个候选）都成了失败世界。"""
```

并把 `EvaluatorContract.revision` 的类型改为 `Literal["structural-candidate-evaluator-v2"]`。

`nutmeg/discovery/selection_contract.py`：`evaluator_revision: Literal["structural-candidate-evaluator-v2"]`。

`nutmeg/discovery/world_pool.py`：文件头 `from nutmeg.discovery.contracts import EVALUATOR_REVISION`，过滤条件改为 `or world.evaluator_revision != EVALUATOR_REVISION`。

两个契约 JSON 里 `"structural-candidate-evaluator-v1"` → `"structural-candidate-evaluator-v2"`。

`nutmeg/discovery/online_adapter.py`，把

```python
        generated_count = result.calculated_candidate_count
        if any(
            len(band.candidates) > contract.evaluator.candidate_count_cap_per_band
            for band in result.by_band.values()
        ):
            status, diagnostics = "failed", ("over_cap",)
        else:
            selectable_candidates = tuple(
```

换成（`else:` 下面原有代码整体左移一级）：

```python
        generated_count = result.calculated_candidate_count
        # 评估器 v2（Jun 2026-09-28）：每档超过上限只记数，不再整片判 over_cap。
        payload["band_candidate_counts"] = {
            band: len(outcome.candidates) for band, outcome in sorted(result.by_band.items())
        }
        selectable_candidates = tuple(
```

v1 字样的测试夹具统一换成 v2：

```bash
sed -i '' 's/structural-candidate-evaluator-v1/structural-candidate-evaluator-v2/g' \
  tests/discovery/test_contracts.py tests/discovery/test_world_pool.py \
  tests/discovery/test_selection_contract.py tests/ontology/test_discovery_governance_actions.py \
  tests/ontology/test_discovery_policy_actions.py tests/ontology/test_discovery_repository.py
```

- [ ] **Step 4: 确认通过**

Run: `uv run pytest tests/discovery tests/ontology -q -k "discovery or contract or world_pool or selection or online"`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add nutmeg/discovery/contracts.py nutmeg/discovery/selection_contract.py \
  nutmeg/discovery/world_pool.py nutmeg/discovery/online_adapter.py \
  experiments/discovery/structural-candidate-v1.contract.json \
  experiments/discovery/structural-selection-v1.contract.json \
  tests/discovery/test_online_adapter.py tests/discovery/test_contracts.py \
  tests/discovery/test_world_pool.py tests/discovery/test_selection_contract.py \
  tests/ontology/test_discovery_governance_actions.py \
  tests/ontology/test_discovery_policy_actions.py tests/ontology/test_discovery_repository.py
git commit -m "feat(discovery): evaluator v2 counts over-cap bands instead of failing the shard"
```

---

### Task 3: 分片枚举抽出 + 各档最优候选（给对照料用）

**Files:**
- Modify: `nutmeg/discovery/online_adapter.py`
- Test: `tests/discovery/test_online_adapter.py`

- [ ] **Step 1: 写失败测试**

```python
def test_best_candidates_by_band_match_the_shard_evaluation():
    from decimal import Decimal

    from nutmeg.discovery.contracts import load_pilot_contract
    from nutmeg.discovery.online_adapter import best_candidates_by_band

    pilot = load_pilot_contract(
        __import__("pathlib").Path(__file__).resolve().parents[2]
        / "experiments/discovery/structural-candidate-v1.contract.json"
    )
    snapshot = _snapshot()
    shard = execute_template_shard(snapshot, ("1x1",), pilot=pilot)
    best = best_candidates_by_band(snapshot, pilot=pilot)
    expected = {
        band: value
        for band, value in (shard.evaluation or {}).get(
            "best_objective_probability_by_band", {}
        ).items()
        if value is not None
    }
    assert set(best) == set(expected)
    for band, candidate in best.items():
        assert Decimal(candidate.objective_probability_decimal) == Decimal(expected[band])
        assert candidate.deployable
```

- [ ] **Step 2: 确认失败**

Run: `uv run pytest tests/discovery/test_online_adapter.py -k best_candidates -q`
Expected: FAIL，`ImportError: cannot import name 'best_candidates_by_band'`。

- [ ] **Step 3: 实现**

`nutmeg/discovery/online_adapter.py`：文件头加 `from decimal import Decimal`；在 `execute_template_shard` 之前新增

```python
def _shard_inputs(snapshot, template_ids, contract, candidate_count_limit):
    return replace(
        snapshot.candidate_input,
        templates=tuple(
            template
            for template in snapshot.candidate_input.templates
            if template.structure_code in template_ids
        ),
        maximum_exhaustive_candidate_count=min(
            snapshot.candidate_input.maximum_exhaustive_candidate_count,
            contract.budgets.max_candidate_generation_count,
            candidate_count_limit or contract.budgets.max_candidate_generation_count,
        ),
    )


def _enumerate_shard(snapshot, inputs, enumerate_fn):
    return enumerate_fn(
        inputs,
        set_kind="judgment_bound",
        generator_version="operator-candidate-v2-bands",
        audit_candidate=lambda draft: _audit_candidate(
            draft,
            lane=inputs.lane,
            offers=snapshot.audit_offers,
            capital_cap_minor=inputs.capital_cap_minor,
        ),
    )


def _valid(candidate) -> bool:
    return candidate.deployable and not any(
        finding.severity == "ERROR" for finding in candidate.audit_findings
    )


def _rank_key(candidate) -> tuple:
    return (
        -Decimal(candidate.objective_probability_decimal),
        candidate.stake_minor,
        candidate.content_hash,
    )


def best_candidates_by_band(snapshot: StructuralInputSnapshot, *, pilot: PilotContract) -> dict:
    """每个赔率档里 P 最高的有效候选：与分片同一枚举、同一审计、同一分片预算。

    世界只存候选哈希；夜间报告用它给次日对照留下「世界各档最优」的票面内容。
    超过分片预算的模板跳过（与分片 `candidate_space_over_cap` 同口径）。
    """
    limit = pilot.budgets.max_candidate_generation_count // len(snapshot.template_ids)
    best: dict[str, object] = {}
    for template_id in snapshot.template_ids:
        inputs = _shard_inputs(snapshot, (template_id,), pilot, limit)
        try:
            result = _enumerate_shard(snapshot, inputs, enumerate_band_candidates)
        except CandidateSpaceLimitError:
            continue
        for band, outcome in result.by_band.items():
            for candidate in outcome.candidates:
                if _valid(candidate) and (
                    band not in best or _rank_key(candidate) < _rank_key(best[band])
                ):
                    best[band] = candidate
    return dict(sorted(best.items()))
```

`execute_template_shard` 里用上这些帮手：`inputs = replace(…)` 那段换成 `inputs = _shard_inputs(snapshot, template_ids, contract, candidate_count_limit)`；`result = enumerate_fn(…)` 那段换成 `result = _enumerate_shard(snapshot, inputs, enumerate_fn)`；`selectable_candidates` 的生成器条件换成 `if _valid(item)`。

- [ ] **Step 4: 确认通过**

Run: `uv run pytest tests/discovery/test_online_adapter.py tests/discovery/test_online_recorder.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add nutmeg/discovery/online_adapter.py tests/discovery/test_online_adapter.py
git commit -m "refactor(discovery): share shard enumeration and expose best candidate per band"
```

---

### Task 4: day 源开球过滤（P1a）

**Files:**
- Modify: `nutmeg/discovery/day_inputs.py`
- Test: `tests/discovery/test_day_inputs.py`

- [ ] **Step 1: 改夹具并写失败测试**

`_day` 夹具签名加 `kickoff: str | None = None`，函数体开头加：

```python
    from datetime import date as _date
    from datetime import timedelta as _timedelta

    next_day = (_date.fromisoformat(day) + _timedelta(days=1)).isoformat()
    kickoff = kickoff or f"{next_day}T02:45:00+08:00"
```

并把 `"kickoff_bj": f"{day}T19:30:00+08:00",` 改成 `"kickoff_bj": kickoff,`。文件头 import 增加 `DayBoardTooSmall`，常量区加 `NEXT_DAY = "2026-09-24"`。追加测试：

```python
def test_matches_kicked_off_by_cutoff_are_excluded_and_recorded(tmp_path: Path):
    jczq = _day(tmp_path, n=4)
    board_path = jczq / "daily" / DAY / "jczq-legs-base.json"
    board = json.loads(board_path.read_text(encoding="utf-8"))
    board["legs"]["周三001"]["kickoff_bj"] = f"{DAY}T11:00:00+08:00"
    board_path.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    snap = read_structural_input_from_day(jczq, DAY, cutoff_at=f"{DAY}T12:00:00+08:00")
    codes = [offer.official_match_no for offer in snap.candidate_input.offers]
    assert codes == ["周三002", "周三003", "周三004"]
    excluded = [r for r in snap.references if r.kind == "excluded_started"]
    assert [(r.id, r.captured_at) for r in excluded] == [("周三001", f"{DAY}T11:00:00+08:00")]


def test_kickoff_falls_back_to_sporttery_time_and_unknown_is_excluded(tmp_path: Path):
    jczq = _day(tmp_path, n=4)
    d = jczq / "daily" / DAY
    board = json.loads((d / "jczq-legs-base.json").read_text(encoding="utf-8"))
    for leg in board["legs"].values():
        leg.pop("kickoff_bj")
    (d / "jczq-legs-base.json").write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    markets = json.loads((d / "sporttery_markets.json").read_text(encoding="utf-8"))
    subs = markets["matchInfoList"][0]["subMatchList"]
    for sub, clock in zip(subs[:3], ("11:30:00", "20:00:00", "21:00:00"), strict=True):
        sub["matchDate"], sub["matchTime"] = DAY, clock
    (d / "sporttery_markets.json").write_text(json.dumps(markets, ensure_ascii=False), encoding="utf-8")
    snap = read_structural_input_from_day(jczq, DAY, cutoff_at=f"{DAY}T12:00:00+08:00")
    assert [o.official_match_no for o in snap.candidate_input.offers] == ["周三002", "周三003"]
    excluded = {r.id: r.source_revision for r in snap.references if r.kind == "excluded_started"}
    assert excluded == {"周三001": f"kickoff:{DAY}T11:30:00+08:00", "周三004": "kickoff:unknown"}


def test_fewer_than_two_unstarted_matches_is_a_named_skip(tmp_path: Path):
    jczq = _day(tmp_path, n=3)
    with pytest.raises(DayBoardTooSmall):
        read_structural_input_from_day(jczq, DAY, cutoff_at=f"{NEXT_DAY}T03:00:00+08:00")
```

- [ ] **Step 2: 确认失败**

Run: `uv run pytest tests/discovery/test_day_inputs.py -q`
Expected: 新增三个 FAIL（`ImportError: DayBoardTooSmall`）。

- [ ] **Step 3: 实现**

`nutmeg/discovery/day_inputs.py`：`from datetime import datetime, timedelta, timezone`；删除 `_had_quotes`，新增

```python
class DayBoardTooSmall(ValueError):
    """截止时刻未开球、且同时有 Read 与体彩 had 报价的场次不足两场（夜间作业记为跳过）。"""


def _market_rows(markets: dict) -> dict[str, dict]:
    return {
        sub["matchNumStr"]: sub
        for block in markets.get("matchInfoList") or []
        for sub in block.get("subMatchList") or []
        if sub.get("matchNumStr")
    }


def _kickoff_at(leg: dict, row: dict) -> datetime | None:
    """板面 `kickoff_bj` 优先，其次体彩 matchDate+matchTime；都没有 → None（按已开球排除）。"""
    if leg.get("kickoff_bj"):
        return datetime.fromisoformat(str(leg["kickoff_bj"]))
    if row.get("matchDate") and row.get("matchTime"):
        return datetime.fromisoformat(f"{row['matchDate']}T{row['matchTime']}+08:00")
    return None
```

`read_structural_input_from_day` 里：

```python
    cutoff = datetime.fromisoformat(cutoff_at)
    rows = _market_rows(json.loads(markets_bytes))
```

循环开头改为：

```python
    for code, leg in sorted(legs.items()):
        read = reads.get(leg.get("match_id"))
        row = rows.get(code) or {}
        had = row.get("had") or {}
        if not read or not had.get("h"):
            continue
        kickoff = _kickoff_at(leg, row)
        if kickoff is None or kickoff <= cutoff:
            # 前瞻纪律：截止时已开球（或开球时刻不明）的场不进世界，留引用说明为什么少了
            refs.append(
                {
                    "kind": "excluded_started",
                    "id": code,
                    "source_revision": f"kickoff:{kickoff.isoformat() if kickoff else 'unknown'}",
                    "captured_at": (kickoff or cutoff).isoformat(),
                }
            )
            continue
```

（`kickoff` 若为 None 或 ≤ cutoff，`captured_at` 都 ≤ cutoff，能过 `freeze_structural_input` 的引用校验。）循环后两处报错改为：

```python
    if not offers:
        raise DayBoardTooSmall("day source has no unstarted match with both a Read and sporttery odds")
```

```python
    if not templates:
        raise DayBoardTooSmall("day source needs at least two unstarted matches for a pass template")
```

- [ ] **Step 4: 确认通过**

Run: `uv run pytest tests/discovery/test_day_inputs.py tests/test_cli_discovery.py -q`
Expected: 全部 PASS（CLI 的前瞻夹具现在开球在次日 02:45，任何时刻跑都不会被过滤光）。

- [ ] **Step 5: 提交**

```bash
git add nutmeg/discovery/day_inputs.py tests/discovery/test_day_inputs.py
git commit -m "feat(discovery): day worlds only take matches that have not kicked off by cutoff"
```

---

### Task 5: 票面引用 + 指纹含票面 + 额外引用（P1b）

**Files:**
- Modify: `nutmeg/discovery/day_inputs.py`
- Test: `tests/discovery/test_day_inputs.py`

- [ ] **Step 1: 写失败测试**

import 增加 `day_tickets, tickets_digest`；`test_snapshot_maps_board_reads_and_quotes` 里的 `assert kinds == {"forecast", "prescription", "quote"}` 改成 `assert kinds == {"forecast", "prescription", "quote", "ticket"}`。追加：

```python
CUT = f"{DAY}T12:00:00+08:00"


def test_ticket_reference_hashes_legs_file_and_same_day_jczq_slips(tmp_path: Path):
    jczq = _day(tmp_path)
    d = jczq / "daily" / DAY
    empty = read_structural_input_from_day(jczq, DAY, cutoff_at=CUT)
    (d / "legs.json").write_text("[]", encoding="utf-8")
    (tmp_path / "betslips.jsonl").write_text(
        json.dumps({"slip_id": "X", "channel": "jczq", "placed_at": DAY}) + "\n"
        + json.dumps({"slip_id": "Y", "channel": "jczq", "placed_at": "2026-09-22"}) + "\n"
        + json.dumps({"slip_id": "Z", "channel": "renjiu", "placed_at": DAY}) + "\n",
        encoding="utf-8",
    )
    snap = read_structural_input_from_day(jczq, DAY, cutoff_at=CUT)
    ref = next(r for r in snap.references if r.kind == "ticket")
    assert ref.id == f"{DAY}:tickets" and ref.captured_at == CUT
    assert ref.source_revision == tickets_digest(day_tickets(d))
    assert ref.source_revision != next(r for r in empty.references if r.kind == "ticket").source_revision
    tickets = day_tickets(d)
    assert tickets["legs_json"] == [] and [s["slip_id"] for s in tickets["betslips"]] == ["X"]


def test_fingerprint_moves_with_same_day_jczq_slips_only(tmp_path: Path):
    jczq = _day(tmp_path)
    d = jczq / "daily" / DAY
    book = tmp_path / "betslips.jsonl"
    book.write_text(json.dumps({"slip_id": "Y", "channel": "jczq", "placed_at": "2026-09-22"}) + "\n",
                    encoding="utf-8")
    before = day_fingerprint(d)
    with book.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"slip_id": "W", "channel": "jczq", "placed_at": "2026-09-21"}) + "\n")
    assert day_fingerprint(d) == before
    with book.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"slip_id": "X", "channel": "jczq", "placed_at": DAY}) + "\n")
    assert day_fingerprint(d) != before


def test_extra_references_enter_the_manifest(tmp_path: Path):
    jczq = _day(tmp_path)
    extra = ({"kind": "approval", "id": "standing-x", "source_revision": "abc",
              "captured_at": f"{DAY}T09:00:00+08:00"},)
    with_ref = read_structural_input_from_day(jczq, DAY, cutoff_at=CUT, extra_references=extra)
    plain = read_structural_input_from_day(jczq, DAY, cutoff_at=CUT)
    assert any(r.kind == "approval" and r.id == "standing-x" for r in with_ref.references)
    assert with_ref.manifest_hash != plain.manifest_hash
```

- [ ] **Step 2: 确认失败**

Run: `uv run pytest tests/discovery/test_day_inputs.py -q`
Expected: FAIL，`ImportError: cannot import name 'day_tickets'`。

- [ ] **Step 3: 实现**

`nutmeg/discovery/day_inputs.py` 新增（放在 `day_fingerprint` 之前）：

```python
def _betslips_path(day_dir: Path) -> Path:
    """`<data>/jczq/daily/<日>` → `<data>/betslips.jsonl`（实票登记簿，全渠道单一文件）。"""
    return Path(day_dir).resolve().parents[2] / "betslips.jsonl"


def day_tickets(day_dir: Path) -> dict:
    """截止时刻的当天实际票面：主循环出票文件 legs.json + 登记簿里当天的竞彩实票。"""
    day_dir = Path(day_dir)
    legs_path = day_dir / "legs.json"
    legs = json.loads(legs_path.read_text(encoding="utf-8")) if legs_path.exists() else None
    slips: list[dict] = []
    book = _betslips_path(day_dir)
    if book.exists():
        for line in book.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("channel") == "jczq" and str(row.get("placed_at") or "")[:10] == day_dir.name:
                slips.append(row)
    slips.sort(key=lambda row: str(row.get("slip_id")))
    return {"day": day_dir.name, "legs_json": legs, "betslips": slips}


def tickets_digest(tickets: dict) -> str:
    return _sha(json.dumps(tickets, sort_keys=True, ensure_ascii=False).encode("utf-8"))
```

`day_fingerprint` 在 `for` 循环之后、`return` 之前加：

```python
    h.update(b"tickets")
    h.update(tickets_digest(day_tickets(day_dir)).encode())
```

（`_sha` 定义在 `day_fingerprint` 之后没关系——调用发生在运行时。）`read_structural_input_from_day` 签名加 `extra_references: tuple[dict, ...] = (),`；在 `refs.append({... "kind": "prescription" ...})` 之后加：

```python
    tickets = day_tickets(day_dir)
    refs.append(
        {
            "kind": "ticket",
            "id": f"{day}:tickets",
            "source_revision": tickets_digest(tickets),
            "captured_at": cutoff_at,
        }
    )
    refs.extend(dict(reference) for reference in extra_references)
```

- [ ] **Step 4: 确认通过**

Run: `uv run pytest tests/discovery/test_day_inputs.py tests/discovery/test_replay_runner.py tests/test_cli_discovery.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add nutmeg/discovery/day_inputs.py tests/discovery/test_day_inputs.py
git commit -m "feat(discovery): freeze the day's actual tickets into every day-source world"
```

---

### Task 6: 常设批准模块 + 录制器复核带上批准引用（P2）

**Files:**
- Create: `nutmeg/discovery/standing_approval.py`
- Modify: `nutmeg/discovery/online_recorder.py`（`_validate_recording` 的独立复核段约 300–304 行）
- Test: `tests/discovery/test_standing_approval.py`

- [ ] **Step 1: 写失败测试** `tests/discovery/test_standing_approval.py`

```python
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nutmeg.discovery.standing_approval import (
    StandingApprovalError,
    approval_references,
    authorize_nightly,
    days_left,
    load_standing_approval,
)

BJ = timezone(timedelta(hours=8))
CUT = datetime(2026, 9, 29, 20, 30, tzinfo=BJ)


def _standing(tmp_path: Path, *, scope: dict | None = None, **changes) -> Path:
    doc = {
        "approval_id": "standing-test",
        "kind": "standing",
        "approved_by": "op:jun",
        "approved_at": "2026-09-28T22:00:00+08:00",
        "valid_from": "2026-09-28T22:00:00+08:00",
        "valid_until": "2026-10-31T23:59:59+08:00",
        "revoked_at": None,
        "scope_template": {
            "source_kind": "day",
            "jczq_dir": str(tmp_path / "jczq"),
            "shadow_db": str(tmp_path / "shadow.db"),
            "policy_revision_id": "structural-baseline-v1",
            "generation_request_pattern": "day:{business_date}",
            "cutoff_window_bjt": ["20:00", "23:59"],
            "max_worlds_per_business_date": 1,
        },
        "note": "test",
    }
    doc["scope_template"].update(scope or {})
    doc.update(changes)
    path = tmp_path / "standing.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _authorize(tmp_path, path, *, cutoff=CUT, owner="op:jun", recorded=(), day=None):
    return authorize_nightly(
        load_standing_approval(path),
        business_date=day or cutoff.astimezone(BJ).date().isoformat(),
        cutoff=cutoff,
        jczq_dir=tmp_path / "jczq",
        shadow_db=tmp_path / "shadow.db",
        baseline_owner=owner,
        recorded_dates=set(recorded),
    )


def test_valid_standing_approval_derives_the_single_run_shape(tmp_path):
    approval = _authorize(tmp_path, _standing(tmp_path))
    assert approval["approval_id"] == "standing-test:2026-09-29"
    assert approval["approved_by"] == "op:jun"
    assert approval["scope"] == {
        "source_db": str((tmp_path / "jczq" / "daily" / "2026-09-29").resolve()),
        "shadow_db": str((tmp_path / "shadow.db").resolve()),
        "generation_request_id": "day:2026-09-29",
        "cutoff_at": CUT.isoformat(),
        "policy_revision_id": "structural-baseline-v1",
    }
    sha = approval["standing_approval"]["sha256"]
    assert approval["standing_approval"]["id"] == "standing-test" and len(sha) == 64
    assert approval_references(approval) == (
        {"kind": "approval", "id": "standing-test", "source_revision": sha,
         "captured_at": "2026-09-28T22:00:00+08:00"},
    )
    assert approval_references({"approval_id": "single-run"}) == ()


@pytest.mark.parametrize(
    ("changes", "cutoff", "reason"),
    [
        ({"revoked_at": "2026-10-01T00:00:00+08:00"}, CUT, "approval_revoked"),
        ({}, datetime(2026, 11, 1, 20, 30, tzinfo=BJ), "approval_expired"),
        ({"valid_from": "2026-09-30T00:00:00+08:00"}, CUT, "approval_not_yet_valid"),
        ({"approved_at": "2026-09-30T00:00:00+08:00"}, CUT, "approval_not_yet_valid"),
        ({}, datetime(2026, 9, 29, 12, 0, tzinfo=BJ), "outside_window"),
    ],
)
def test_standing_approval_refuses_with_a_named_reason(tmp_path, changes, cutoff, reason):
    with pytest.raises(StandingApprovalError) as err:
        _authorize(tmp_path, _standing(tmp_path, **changes), cutoff=cutoff)
    assert err.value.reason == reason


def test_scope_owner_business_date_and_one_world_per_day(tmp_path):
    path = _standing(tmp_path)
    cases = [
        ({"owner": "op:someone"}, "owner_mismatch"),
        ({"owner": None}, "owner_mismatch"),
        ({"recorded": ("2026-09-29",)}, "already_recorded"),
        ({"day": "2026-09-28"}, "outside_window"),
    ]
    for kwargs, reason in cases:
        with pytest.raises(StandingApprovalError) as err:
            _authorize(tmp_path, path, **kwargs)
        assert err.value.reason == reason
    other = _standing(tmp_path, scope={"shadow_db": str(tmp_path / "other.db")})
    with pytest.raises(StandingApprovalError) as err:
        _authorize(tmp_path, other)
    assert err.value.reason == "scope_mismatch"


def test_missing_or_malformed_file_is_a_named_reason(tmp_path):
    with pytest.raises(StandingApprovalError) as err:
        load_standing_approval(tmp_path / "nope.json")
    assert err.value.reason == "approval_missing"
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(StandingApprovalError) as err:
        load_standing_approval(bad)
    assert err.value.reason == "approval_unreadable"
    single = tmp_path / "single.json"
    single.write_text(json.dumps({"approval_id": "x", "kind": "single"}), encoding="utf-8")
    with pytest.raises(StandingApprovalError) as err:
        load_standing_approval(single)
    assert err.value.reason == "approval_unreadable"


def test_days_left_counts_beijing_calendar_days(tmp_path):
    standing = load_standing_approval(_standing(tmp_path))
    assert days_left(standing, datetime(2026, 10, 24, 21, 0, tzinfo=BJ)) == 7
    assert days_left(standing, datetime(2026, 10, 31, 23, 0, tzinfo=BJ)) == 0
```

- [ ] **Step 2: 确认失败**

Run: `uv run pytest tests/discovery/test_standing_approval.py -q`
Expected: FAIL，`ModuleNotFoundError: nutmeg.discovery.standing_approval`。

- [ ] **Step 3: 实现** `nutmeg/discovery/standing_approval.py`

```python
"""常设批准（Jun 2026-09-28，至 2026-10-31）：一次签字覆盖一段日期的夜间 Dream 录制。

设计：docs/superpowers/specs/2026-09-28-dream-nightly-recording-design.md §3.3。
⛔程序只读批准文件；校验通过后派生的单次批准只在内存里交给现有 `_validate_recording`，
每个世界都带一条 `kind="approval"` 引用，回溯到签字文件与它当时的字节。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

BJ = timezone(timedelta(hours=8))
POLICY_REVISION_ID = "structural-baseline-v1"
DEFAULT_STANDING_PATH = (
    Path(__file__).resolve().parents[2]
    / "experiments/discovery/approvals/standing-dream-nightly-2026-10.json"
)
_REQUIRED = ("approval_id", "approved_by", "approved_at", "valid_from", "valid_until",
             "scope_template")


class StandingApprovalError(ValueError):
    """这份批准不能用于这一次录制；`reason` 是写进夜间报告的机器可读原因。"""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


@dataclass(frozen=True)
class StandingApproval:
    document: dict
    sha256: str

    @property
    def approval_id(self) -> str:
        return str(self.document["approval_id"])

    @property
    def approved_by(self) -> str:
        return str(self.document["approved_by"])

    @property
    def valid_until(self) -> datetime:
        return datetime.fromisoformat(str(self.document["valid_until"]))


def load_standing_approval(path: Path) -> StandingApproval:
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError as exc:
        raise StandingApprovalError("approval_missing", str(path)) from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StandingApprovalError("approval_unreadable", str(exc)) from exc
    missing = [key for key in _REQUIRED if not document.get(key)]
    if missing or document.get("kind") != "standing":
        raise StandingApprovalError(
            "approval_unreadable", f"missing={missing} kind={document.get('kind')!r}"
        )
    return StandingApproval(document, hashlib.sha256(raw).hexdigest())


def authorize_nightly(
    standing: StandingApproval,
    *,
    business_date: str,
    cutoff: datetime,
    jczq_dir: Path,
    shadow_db: Path,
    baseline_owner: str | None,
    recorded_dates: set[str],
) -> dict:
    """逐条校验，通过则返回现有 `_validate_recording` 认的单次批准字典。"""
    doc = standing.document
    scope = doc["scope_template"]
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise StandingApprovalError("approval_unreadable", "cutoff must be timezone-aware")
    if doc.get("revoked_at"):
        raise StandingApprovalError("approval_revoked", str(doc["revoked_at"]))
    approved_at = datetime.fromisoformat(str(doc["approved_at"]))
    if cutoff < datetime.fromisoformat(str(doc["valid_from"])) or approved_at > cutoff:
        raise StandingApprovalError("approval_not_yet_valid", cutoff.isoformat())
    if cutoff > standing.valid_until:
        raise StandingApprovalError("approval_expired", str(doc["valid_until"]))
    local = cutoff.astimezone(BJ)
    start, end = (time.fromisoformat(value) for value in scope["cutoff_window_bjt"])
    if not start <= local.time().replace(second=0, microsecond=0) <= end:
        raise StandingApprovalError("outside_window", local.isoformat())
    if local.date().isoformat() != business_date:
        raise StandingApprovalError("outside_window", f"{business_date} != {local.date()}")
    if (
        scope.get("source_kind") != "day"
        or scope.get("policy_revision_id") != POLICY_REVISION_ID
        or Path(scope["jczq_dir"]).resolve() != Path(jczq_dir).resolve()
        or Path(scope["shadow_db"]).resolve() != Path(shadow_db).resolve()
    ):
        raise StandingApprovalError("scope_mismatch", json.dumps(scope, ensure_ascii=False))
    if baseline_owner != standing.approved_by:
        raise StandingApprovalError("owner_mismatch", f"baseline owner {baseline_owner!r}")
    if business_date in recorded_dates:
        raise StandingApprovalError("already_recorded", business_date)
    return {
        "approval_id": f"{standing.approval_id}:{business_date}",
        "approved_by": standing.approved_by,
        "approved_at": str(doc["approved_at"]),
        "standing_approval": {"id": standing.approval_id, "sha256": standing.sha256},
        "scope": {
            "source_db": str((Path(jczq_dir) / "daily" / business_date).resolve()),
            "shadow_db": str(Path(shadow_db).resolve()),
            "generation_request_id": f"day:{business_date}",
            "cutoff_at": cutoff.isoformat(),
            "policy_revision_id": POLICY_REVISION_ID,
        },
    }


def approval_references(approval: Mapping) -> tuple[dict, ...]:
    """派生批准 → 世界 manifest 里的一条 `approval` 引用；单次批准 → 空。"""
    standing = approval.get("standing_approval")
    if not standing:
        return ()
    return (
        {
            "kind": "approval",
            "id": str(standing["id"]),
            "source_revision": str(standing["sha256"]),
            "captured_at": str(approval["approved_at"]),
        },
    )


def days_left(standing: StandingApproval, now: datetime) -> int:
    return (standing.valid_until.astimezone(BJ).date() - now.astimezone(BJ).date()).days
```

`nutmeg/discovery/online_recorder.py`：文件头加 `from nutmeg.discovery.standing_approval import approval_references`；`_validate_recording` 独立复核处改为

```python
            verified = read_structural_input_from_day(
                source_database.parent.parent,
                source_database.name,
                cutoff_at=snapshot.cutoff_at,
                extra_references=approval_references(approval or {}),
            )
```

- [ ] **Step 4: 确认通过**

Run: `uv run pytest tests/discovery/test_standing_approval.py tests/discovery/test_online_recorder.py tests/test_cli_discovery.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add nutmeg/discovery/standing_approval.py nutmeg/discovery/online_recorder.py \
  tests/discovery/test_standing_approval.py
git commit -m "feat(discovery): standing approval for nightly day-source worlds"
```

---

### Task 7: 对照料与次日记账库（P4 核心）

**Files:**
- Create: `nutmeg/discovery/dream_compare.py`
- Test: `tests/discovery/test_dream_compare.py`

- [ ] **Step 1: 写失败测试** `tests/discovery/test_dream_compare.py`

```python
from nutmeg.decision.betslip import BetSlip, SlipLeg
from nutmeg.discovery.dream_compare import (
    compare_day,
    decision_rule_best,
    score_tickets,
    summarize,
)

BOOK = {
    "A": {"belief": {"3": 0.5, "1": 0.3, "0": 0.2}, "odds": {"3": 1.8, "1": 3.2, "0": 4.5}},
    "B": {"belief": {"3": 0.4, "1": 0.3, "0": 0.3}, "odds": {"3": 2.3, "1": 3.1, "0": 2.9}},
    "C": {"belief": {"3": 0.7, "1": 0.2, "0": 0.1}, "odds": {"3": 1.3, "1": 4.6, "0": 8.0}},
}
RESULTS = {"A": {"outcome_90": "3"}, "B": {"outcome_90": "1"}, "C": {"outcome_90": "3"}}


def test_decision_rule_best_is_max_p_among_combos_that_pay_back_on_a_hit():
    best = decision_rule_best(BOOK)
    assert best is not None and best["modal_return_per_yuan"] > 1
    assert 2 <= len(best["legs"]) <= 4 and best["notes"] <= 4
    assert all(set(leg["faces"]) <= {"3", "1", "0"} for leg in best["legs"])


def test_score_tickets_handles_hit_miss_pending_and_void():
    hit = score_tickets([[{"code": "A", "faces": "3"}, {"code": "B", "faces": "10"}]], BOOK, RESULTS)
    assert hit == {"status": "settled", "hit": True, "return_per_yuan": round(1.8 * 3.1 / 2, 4)}
    miss = score_tickets([[{"code": "A", "faces": "0"}, {"code": "X", "faces": "3"}]], BOOK, RESULTS)
    assert miss == {"status": "settled", "hit": False, "return_per_yuan": 0.0}
    pending = score_tickets([[{"code": "A", "faces": "3"}, {"code": "X", "faces": "3"}]], BOOK, RESULTS)
    assert pending == {"status": "pending"}
    void = score_tickets([[{"code": "A", "faces": "3"}, {"code": "V", "faces": "0"}]], BOOK,
                         {**RESULTS, "V": {"void": True}})
    assert void["hit"] is True and void["return_per_yuan"] == round(1.8 / 1, 4)


def _report():
    return {
        "day": "2026-09-29", "status": "recorded", "world_id": "w", "manifest_hash": "m",
        "offer_book": BOOK,
        "decision_rule_best": {"legs": [{"code": "A", "faces": "3"}, {"code": "C", "faces": "3"}],
                               "p_belief": 0.35, "notes": 1, "modal_return_per_yuan": 2.34},
        "band_best": {"10x": {"tickets": [[{"code": "A", "faces": "3"}, {"code": "B", "faces": "0"}]],
                              "p_belief": "0.06", "combined_odds": "5.22", "stake_minor": 200}},
        "ticket_snapshot": {"betslips": [{"slip_id": "S1"}]},
    }


def test_compare_day_scores_four_row_kinds():
    slip = BetSlip(slip_id="S1", channel="jczq", placed_at="2026-09-29", multiplier=10,
                   legs=[SlipLeg(key="A", market="had", selections=("home",), odds=(1.8,)),
                         SlipLeg(key="C", market="had", selections=("home",), odds=(1.3,))])
    late = BetSlip(slip_id="S2", channel="jczq", placed_at="2026-09-29",
                   legs=[SlipLeg(key="B", market="hhad", line=-1.0, selections=("away",), odds=(1.5,)),
                         SlipLeg(key="C", market="had", selections=("home",), odds=(1.3,))])
    out = compare_day(_report(), RESULTS, [slip, late])
    rows = {(r["kind"], r.get("id")): r for r in out["rows"]}
    s1 = rows[("actual", "S1")]
    assert s1["in_world"] and s1["frozen_at_cutoff"] and abs(s1["p_belief"] - 0.35) < 1e-9
    assert s1["hit"] is True and s1["pnl_per_yuan"] == round(1.8 * 1.3 - 1, 4)
    s2 = rows[("actual", "S2")]
    assert s2["in_world"] is False and s2["p_belief"] is None and s2["frozen_at_cutoff"] is False
    assert rows[("decision_rule", None)]["hit"] is True
    assert rows[("band", "10x")]["hit"] is False and rows[("band", "10x")]["pnl_per_yuan"] == -1.0
    assert rows[("empty", None)]["pnl_per_yuan"] == 0.0


def test_summarize_reports_means_and_withholds_ci_below_twenty_days():
    days = [{"day": f"d{i}", "rows": [
        {"kind": "actual", "status": "settled", "stake_yuan": 20, "pnl_yuan": -20.0,
         "pnl_per_yuan": -1.0, "p_belief": 0.3, "hit": False},
        {"kind": "decision_rule", "status": "settled", "pnl_per_yuan": 0.5, "p_belief": 0.4, "hit": True},
        {"kind": "empty", "status": "settled", "pnl_per_yuan": 0.0},
    ]} for i in range(3)]
    summary = summarize(days)
    assert summary["n_days"] == 3
    assert summary["kinds"]["decision_rule"]["hit_rate"] == 1.0
    assert summary["actual_minus_rule"]["mean"] == -1.5
    assert summary["actual_minus_rule"]["ci95"] is None
```

- [ ] **Step 2: 确认失败**

Run: `uv run pytest tests/discovery/test_dream_compare.py -q`
Expected: FAIL，`ModuleNotFoundError: nutmeg.discovery.dream_compare`。

- [ ] **Step 3: 实现** `nutmeg/discovery/dream_compare.py`

```python
"""Dream 对照：实际出票 / 决策规则最优 / 世界各档最优 / 空仓（Jun 2026-09-28）。

设计：docs/superpowers/specs/2026-09-28-dream-nightly-recording-design.md §3.5。
对照料在录制时用冻结快照算好写进夜间报告（`offer_book`、`decision_rule_best`、
`band_best`），次日只拿赛果与实票记账。⛔只报告：不改票面、不改权重、不登记实验。
"""

from __future__ import annotations

import random
from statistics import mean

from nutmeg.decision.betslip import BetSlip, settle_slip
from nutmeg.decision.jczq_combos import enumerate_combos

FACE_SETS = ("3", "1", "0", "31", "30", "10")
_SELECTION_FACE = {"home": "3", "draw": "1", "away": "0", "3": "3", "1": "1", "0": "0"}
KINDS = ("actual", "decision_rule", "band", "empty")


def offer_book(snapshot) -> dict:
    """冻结快照 → {场次: {belief, prior, odds}}（面码 3/1/0，浮点）。"""
    priors = {audit.official_match_no: dict(audit.prior) for audit in snapshot.audit_offers}
    return {
        offer.official_match_no: {
            "belief": {face: float(value) for face, value in offer.probabilities},
            "prior": {face: float(value) for face, value in priors.get(offer.official_match_no, ())},
            "odds": {face: float(value) for face, value in offer.booked_decimal_odds_by_face},
        }
        for offer in snapshot.candidate_input.offers
    }


def decision_rule_best(book: dict, *, max_legs: int = 4, max_notes: int = 4) -> dict | None:
    """与 `jczq-combos` 同一算术：胜平负 2–4 串、≤4 注，全中每元回报 >1 的组合里 P 最大者。"""
    legs = []
    for code, row in sorted(book.items()):
        belief, odds = row["belief"], row["odds"]
        options = []
        for faces in FACE_SETS:
            modal = max(faces, key=lambda face: belief[face])
            options.append({"market": "had", "faces": faces,
                            "p": sum(belief[face] for face in faces),
                            "odds": [odds[face] for face in faces], "modal_odds": odds[modal]})
        legs.append({"code": code, "name": code, "options": options})
    if len(legs) < 2:
        return None
    for combo in enumerate_combos(legs, max_legs=max_legs, max_notes=max_notes, top=10**9):
        if combo["return_per_yuan"] > 1:
            return {"legs": [{"code": leg["code"], "faces": leg["faces"]} for leg in combo["legs"]],
                    "p_belief": round(combo["p"], 6), "notes": combo["notes"],
                    "modal_return_per_yuan": round(combo["return_per_yuan"], 4)}
    return None


def candidate_tickets(candidate) -> list[list[dict]]:
    return [
        [{"code": leg.official_match_no, "faces": "".join(leg.selection_codes)} for leg in ticket.legs]
        for ticket in candidate.tickets
    ]


def score_tickets(tickets: list[list[dict]], book: dict, results: dict) -> dict:
    """一组串关票（每腿一个面集合，全中才中）→ 命中与每元回报；缺赛果且未确定 → pending。"""
    notes = 0
    units = 0.0
    pending = False
    any_hit = False
    for ticket in tickets:
        ticket_notes = 1
        won = 1.0
        missed = False
        unknown = False
        for leg in ticket:
            ticket_notes *= len(leg["faces"])
            result = results.get(leg["code"])
            if not result:
                unknown = True
                continue
            if result.get("void"):
                continue
            outcome = str(result.get("outcome_90"))
            if outcome not in leg["faces"]:
                missed = True
            else:
                won *= float(book[leg["code"]]["odds"][outcome])
        notes += ticket_notes
        if missed:
            continue
        if unknown:
            pending = True
            continue
        any_hit = True
        units += won
    if pending:
        return {"status": "pending"}
    return {"status": "settled", "hit": any_hit,
            "return_per_yuan": round(units / notes, 4) if any_hit else 0.0}


def _settled_row(kind: str, row_id: str | None, p_belief, score: dict, **extra) -> dict:
    row = {"kind": kind, "id": row_id, "p_belief": p_belief, **extra, **score}
    if score.get("status") == "settled":
        row["pnl_per_yuan"] = round(score["return_per_yuan"] - 1, 4)
    return row


def _slip_row(slip: BetSlip, book: dict, results: dict, frozen_ids: set[str]) -> dict:
    settlement = settle_slip(slip, results)
    in_world = (
        all(leg.market == "had" and leg.key in book for leg in slip.legs)
        and tuple(slip.combo_sizes or ()) in ((), (len(slip.legs),))
    )
    p_belief = None
    if in_world:
        p_belief = 1.0
        for leg in slip.legs:
            faces = {_SELECTION_FACE.get(str(s)) for s in leg.selections}
            p_belief *= sum(book[leg.key]["belief"][face] for face in faces if face)
    row = {"kind": "actual", "id": slip.slip_id, "p_belief": p_belief, "in_world": in_world,
           "frozen_at_cutoff": slip.slip_id in frozen_ids, "stake_yuan": slip.stake_yuan}
    if settlement.payout_yuan is None:
        return {**row, "status": "pending"}
    return {**row, "status": "settled", "hit": settlement.combos_won > 0,
            "pnl_yuan": settlement.pnl_yuan,
            "pnl_per_yuan": round(settlement.pnl_yuan / slip.stake_yuan, 4)}


def compare_day(report: dict, results: dict, slips: list[BetSlip]) -> dict:
    """一个录制日的四行记账。`slips` 只传该业务日已买（purchased）的竞彩票。"""
    book = report["offer_book"]
    frozen = {str(row.get("slip_id")) for row in (report.get("ticket_snapshot") or {}).get("betslips", [])}
    rows = [_slip_row(slip, book, results, frozen) for slip in slips]
    rule = report.get("decision_rule_best")
    if rule:
        rows.append(_settled_row("decision_rule", None, rule["p_belief"],
                                 score_tickets([rule["legs"]], book, results)))
    for band, best in sorted((report.get("band_best") or {}).items()):
        rows.append(_settled_row("band", band, float(best["p_belief"]),
                                 score_tickets(best["tickets"], book, results)))
    rows.append({"kind": "empty", "id": None, "status": "settled", "pnl_per_yuan": 0.0})
    status = "pending" if any(r["status"] == "pending" for r in rows) else "settled"
    return {"day": report["day"], "status": status, "world_id": report.get("world_id"),
            "manifest_hash": report.get("manifest_hash"), "rows": rows}


def _actual_pnl_per_yuan(rows: list[dict]) -> float:
    actual = [r for r in rows if r["kind"] == "actual" and r["status"] == "settled"]
    stake = sum(r["stake_yuan"] for r in actual)
    return round(sum(r["pnl_yuan"] for r in actual) / stake, 4) if stake else 0.0


def _bootstrap_ci(values: list[float], *, seed: int = 20260928, draws: int = 2000) -> list[float]:
    rng = random.Random(seed)
    means = sorted(mean(rng.choices(values, k=len(values))) for _ in range(draws))
    return [round(means[int(0.025 * draws)], 4), round(means[int(0.975 * draws) - 1], 4)]


def summarize(days: list[dict], *, min_days_for_ci: int = 20) -> dict:
    """累计：各行平均 P、命中率、平均每元盈亏；实际−规则最优的日均差（n≥20 才给 CI）。"""
    kinds = {}
    for kind in KINDS:
        rows = [r for day in days for r in day["rows"]
                if r["kind"] == kind and r.get("status") == "settled"]
        ps = [r["p_belief"] for r in rows if r.get("p_belief") is not None]
        hits = [1.0 if r.get("hit") else 0.0 for r in rows if "hit" in r]
        kinds[kind] = {
            "n": len(rows),
            "mean_p": round(mean(ps), 4) if ps else None,
            "hit_rate": round(mean(hits), 4) if hits else None,
            "mean_pnl_per_yuan": round(mean(r["pnl_per_yuan"] for r in rows), 4) if rows else None,
        }
    diffs = []
    for day in days:
        rule = [r for r in day["rows"] if r["kind"] == "decision_rule" and r.get("status") == "settled"]
        if rule:
            diffs.append(_actual_pnl_per_yuan(day["rows"]) - rule[0]["pnl_per_yuan"])
    return {
        "n_days": len(days),
        "kinds": kinds,
        "actual_minus_rule": {
            "n": len(diffs),
            "mean": round(mean(diffs), 4) if diffs else None,
            "ci95": _bootstrap_ci(diffs) if len(diffs) >= min_days_for_ci else None,
        },
    }
```

- [ ] **Step 4: 确认通过**

Run: `uv run pytest tests/discovery/test_dream_compare.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add nutmeg/discovery/dream_compare.py tests/discovery/test_dream_compare.py
git commit -m "feat(discovery): score actual tickets against the rule best, band best and staying out"
```

---

### Task 8: 夜间编排 `run_nightly`（P3 核心）

**Files:**
- Create: `nutmeg/discovery/nightly.py`
- Test: `tests/discovery/test_nightly.py`

- [ ] **Step 1: 写失败测试** `tests/discovery/test_nightly.py`

```python
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.discovery.nightly import run_nightly
from tests.discovery.test_day_inputs import _day
from tests.discovery.test_standing_approval import _standing

BJ = timezone(timedelta(hours=8))
DAY = "2026-09-23"
NOW = datetime(2026, 9, 23, 20, 30, tzinfo=BJ)


class _Recorded:
    world_id = "discovery-world-test"
    sealed_manifest_hash = "sealed"
    selected_node_ids = ()


def _setup(tmp_path: Path):
    jczq = _day(tmp_path, n=3)
    shadow = tmp_path / "shadow.db"
    shadow.write_bytes(b"")
    standing = _standing(tmp_path, valid_from="2026-09-23T00:00:00+08:00",
                         approved_at="2026-09-23T00:00:00+08:00")
    return jczq, shadow, standing


def _run(tmp_path, jczq, shadow, standing, **kwargs):
    calls = kwargs.pop("calls", [])

    def record(snapshot, **kw):
        calls.append((snapshot, kw))
        failure = kwargs.get("fail_first")
        if failure and len(calls) == 1:
            raise ValueError(failure)
        return _Recorded()

    return run_nightly(
        day=DAY, jczq_dir=jczq, shadow_db=shadow, standing_path=standing,
        reports_dir=tmp_path / "reports", tickets_dir=tmp_path / "tickets",
        now=kwargs.get("now", lambda: NOW), dry_run=kwargs.get("dry_run", False),
        record_fn=record, owner_fn=lambda _db: kwargs.get("owner", "op:jun"),
        shard_fn=lambda _db, _world: [{"template": "pass-2-1", "status": "complete"}],
        engine_fn=lambda _db: None, sleep=lambda _s: None,
    ), calls


def test_recorded_night_writes_report_with_comparison_material(tmp_path):
    jczq, shadow, standing = _setup(tmp_path)
    result, calls = _run(tmp_path, jczq, shadow, standing)
    assert result.status == "recorded" and result.exit_code == 0
    snapshot, kw = calls[0]
    assert kw["approval"]["standing_approval"]["id"] == "standing-test"
    assert any(r.kind == "approval" for r in snapshot.references)
    report = json.loads((tmp_path / "reports" / f"{DAY}.json").read_text(encoding="utf-8"))
    assert report["status"] == "recorded" and report["world_id"] == "discovery-world-test"
    assert set(report["offer_book"]) == {"周三001", "周三002", "周三003"}
    assert report["decision_rule_best"] is None or report["decision_rule_best"]["notes"] <= 4
    assert "band_best" in report and report["shards"][0]["template"] == "pass-2-1"
    snap_path = Path(report["ticket_snapshot_path"])
    assert snap_path.exists() and report["ticket_snapshot"]["day"] == DAY
    assert report["standing_approval"]["days_left"] == (datetime(2026, 10, 31).date() - NOW.date()).days


def test_second_run_same_day_is_skipped(tmp_path):
    jczq, shadow, standing = _setup(tmp_path)
    _run(tmp_path, jczq, shadow, standing)
    again, calls = _run(tmp_path, jczq, shadow, standing)
    assert again.status == "skipped" and again.reason == "already_recorded" and not calls
    assert again.exit_code == 0


def test_named_skips_do_not_record(tmp_path):
    jczq, shadow, standing = _setup(tmp_path)
    late, calls = _run(tmp_path, jczq, shadow, standing,
                       now=lambda: datetime(2026, 9, 24, 3, 0, tzinfo=BJ))
    assert late.status == "skipped" and late.reason == "outside_window" and not calls
    other, calls = _run(tmp_path, jczq, shadow, standing, owner="op:else")
    assert other.reason == "owner_mismatch" and not calls


def test_board_too_small_is_skipped(tmp_path):
    jczq, shadow, standing = _setup(tmp_path)
    board = jczq / "daily" / DAY / "jczq-legs-base.json"
    doc = json.loads(board.read_text(encoding="utf-8"))
    for leg in doc["legs"].values():
        leg["kickoff_bj"] = f"{DAY}T19:00:00+08:00"
    board.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    result, calls = _run(tmp_path, jczq, shadow, standing)
    assert result.status == "skipped" and result.reason == "board_too_small" and not calls


def test_protected_change_retries_once_then_records(tmp_path):
    jczq, shadow, standing = _setup(tmp_path)
    result, calls = _run(tmp_path, jczq, shadow, standing,
                         fail_first="protected source changed during shadow recording")
    assert result.status == "recorded" and len(calls) == 2


def test_dry_run_writes_nothing(tmp_path):
    jczq, shadow, standing = _setup(tmp_path)
    result, calls = _run(tmp_path, jczq, shadow, standing, dry_run=True)
    assert result.status == "dry_run" and not calls
    assert result.payload["offers"] == ["周三001", "周三002", "周三003"]
    assert not (tmp_path / "reports").exists() and not (tmp_path / "tickets").exists()


def test_missing_shadow_store_is_an_infrastructure_failure(tmp_path):
    jczq, shadow, standing = _setup(tmp_path)
    shadow.unlink()
    result, _calls = _run(tmp_path, jczq, shadow, standing)
    assert result.status == "failed" and result.exit_code == 1
```

- [ ] **Step 2: 确认失败**

Run: `uv run pytest tests/discovery/test_nightly.py -q`
Expected: FAIL，`ModuleNotFoundError: nutmeg.discovery.nightly`。

- [ ] **Step 3: 实现** `nutmeg/discovery/nightly.py`

```python
"""夜间 Dream 录制（Jun 2026-09-28，常设批准至 2026-10-31）。

一晚一个世界：常设批准校验 → day 源（开球过滤 + 票面引用）→ 录制并封存 → 报告。
报告顺带用同一冻结快照算好次日对照料（赔率簿、决策规则最优、世界各档最优）。
⛔不写批准文件、不写生产目录、不跑锦标赛/晋级/部署。
设计：docs/superpowers/specs/2026-09-28-dream-nightly-recording-design.md §3.4。
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from nutmeg.discovery.contracts import load_pilot_contract
from nutmeg.discovery.day_inputs import (
    DayBoardTooSmall,
    day_tickets,
    read_structural_input_from_day,
    tickets_digest,
)
from nutmeg.discovery.dream_compare import candidate_tickets, decision_rule_best, offer_book
from nutmeg.discovery.online_adapter import best_candidates_by_band
from nutmeg.discovery.standing_approval import (
    BJ,
    POLICY_REVISION_ID,
    StandingApprovalError,
    approval_references,
    authorize_nightly,
    days_left,
    load_standing_approval,
)

PILOT_PATH = (
    Path(__file__).resolve().parents[2]
    / "experiments/discovery/structural-candidate-v1.contract.json"
)
RETRY_MARKERS = ("protected source changed",)
UNSEALED_MARKERS = ("sealing blocked", "remains unsealed")


@dataclass
class NightlyResult:
    status: str  # recorded | skipped | unsealed | dry_run | failed
    reason: str | None = None
    report_path: Path | None = None
    payload: dict = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return 1 if self.status == "failed" else 0


def _read_only_engine(shadow_db: Path):
    from sqlalchemy import create_engine

    uri = f"file:{quote(str(shadow_db), safe='/')}?mode=ro"
    return create_engine("sqlite+pysqlite://", creator=lambda: sqlite3.connect(uri, uri=True))


def baseline_owner(shadow_db: Path) -> str | None:
    from nutmeg.ontology.discovery.read_service import DiscoveryReadService

    engine = _read_only_engine(shadow_db)
    try:
        return DiscoveryReadService(engine).policy_lineage(POLICY_REVISION_ID)["policy"]["created_by"]
    except KeyError:
        return None
    finally:
        engine.dispose()


def shard_summary(shadow_db: Path, world_id: str) -> list[dict]:
    from nutmeg.ontology.discovery.read_service import DiscoveryReadService

    engine = _read_only_engine(shadow_db)
    try:
        detail = DiscoveryReadService(engine).world_detail(world_id)
    finally:
        engine.dispose()
    rows = []
    for node in detail.get("nodes", []):
        manifest = node.get("artifact_manifest") or {}
        if not manifest.get("template_ids") or ":attempt:" not in str(node.get("node_id")):
            continue
        rows.append({
            "template": manifest["template_ids"][0],
            "status": node.get("execution_status"),
            "diagnostics": list(node.get("diagnostic_codes") or []),
            "wall_ms": (node.get("resource_cost") or {}).get("wall_ms"),
            "band_candidate_counts": manifest.get("band_candidate_counts"),
        })
    return rows


def _recorded_dates(reports_dir: Path, standing_id: str) -> set[str]:
    dates: set[str] = set()
    for path in reports_dir.glob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("status") == "recorded" and (doc.get("standing_approval") or {}).get("id") == standing_id:
            dates.add(str(doc["day"]))
    return dates


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _band_best(snapshot, pilot) -> dict:
    return {
        band: {"tickets": candidate_tickets(candidate),
               "p_belief": candidate.objective_probability_decimal,
               "combined_odds": candidate.combined_decimal_odds,
               "stake_minor": candidate.stake_minor}
        for band, candidate in best_candidates_by_band(snapshot, pilot=pilot).items()
    }


def run_nightly(
    *,
    day: str,
    jczq_dir: Path,
    shadow_db: Path,
    standing_path: Path,
    reports_dir: Path,
    tickets_dir: Path,
    now: Callable[[], datetime],
    dry_run: bool = False,
    record_fn: Callable | None = None,
    owner_fn: Callable[[Path], str | None] = baseline_owner,
    shard_fn: Callable[[Path, str], list[dict]] = shard_summary,
    engine_fn: Callable | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> NightlyResult:
    if record_fn is None:
        from nutmeg.discovery.online_recorder import record_shadow_world as record_fn
    if engine_fn is None:
        from nutmeg.ontology.repository.connection import build_ontology_engine as engine_fn
    source = Path(jczq_dir) / "daily" / day
    base = {"day": day, "shadow_db": str(Path(shadow_db).resolve())}
    try:
        standing = load_standing_approval(standing_path)
    except StandingApprovalError as exc:
        return NightlyResult("skipped", exc.reason, payload={**base, "detail": str(exc)})
    base["standing_approval"] = {"id": standing.approval_id, "sha256": standing.sha256,
                                 "days_left": days_left(standing, now())}
    if not Path(shadow_db).is_file():
        return NightlyResult("failed", "shadow_store_missing", payload=base)
    owner = owner_fn(Path(shadow_db))
    pilot = load_pilot_contract(PILOT_PATH)

    def prepare():
        cutoff = now().astimezone(BJ).replace(microsecond=0)
        approval = authorize_nightly(
            standing, business_date=day, cutoff=cutoff, jczq_dir=Path(jczq_dir),
            shadow_db=Path(shadow_db), baseline_owner=owner,
            recorded_dates=_recorded_dates(Path(reports_dir), standing.approval_id),
        )
        snapshot = read_structural_input_from_day(
            jczq_dir, day, cutoff_at=cutoff.isoformat(),
            extra_references=approval_references(approval),
        )
        return approval, snapshot

    try:
        approval, snapshot = prepare()
    except StandingApprovalError as exc:
        return NightlyResult("skipped", exc.reason, payload={**base, "detail": str(exc)})
    except DayBoardTooSmall as exc:
        return NightlyResult("skipped", "board_too_small", payload={**base, "detail": str(exc)})

    offers = [offer.official_match_no for offer in snapshot.candidate_input.offers]
    excluded = [{"code": r.id, "kickoff": r.source_revision.removeprefix("kickoff:")}
                for r in snapshot.references if r.kind == "excluded_started"]
    if dry_run:
        return NightlyResult("dry_run", payload={**base, "cutoff_at": snapshot.cutoff_at,
                                                 "offers": offers, "excluded": excluded,
                                                 "templates": list(snapshot.template_ids)})

    recorded = None
    for attempt in range(2):
        engine = engine_fn(Path(shadow_db))
        try:
            recorded = record_fn(
                snapshot, engine=engine, shadow_database=Path(shadow_db), source_database=source,
                policy_revision_id=POLICY_REVISION_ID, generation_request_id=f"day:{day}",
                requested_at=datetime.now(UTC), approval=approval,
            )
            break
        except ValueError as exc:
            message = str(exc)
            if attempt == 0 and any(marker in message for marker in RETRY_MARKERS):
                sleep(60)
                try:
                    approval, snapshot = prepare()
                except (StandingApprovalError, DayBoardTooSmall) as again:
                    return NightlyResult("skipped", getattr(again, "reason", "board_too_small"),
                                         payload={**base, "detail": str(again)})
                continue
            status = "unsealed" if any(m in message for m in UNSEALED_MARKERS + RETRY_MARKERS) else "failed"
            payload = {**base, "status": status, "detail": message, "cutoff_at": snapshot.cutoff_at}
            path = _write_json(Path(reports_dir) / f"{day}.json", payload)
            return NightlyResult(status, "recording_error", path, payload)
        finally:
            if engine is not None:
                engine.dispose()

    tickets = day_tickets(source)
    digest = tickets_digest(tickets)
    ticket_path = _write_json(Path(tickets_dir) / f"{day}-{digest[:16]}.json", tickets)
    book = offer_book(snapshot)
    payload = {
        **base,
        "status": "recorded",
        "cutoff_at": snapshot.cutoff_at,
        "world_id": recorded.world_id,
        "sealed_manifest_hash": recorded.sealed_manifest_hash,
        "manifest_hash": snapshot.manifest_hash,
        "offers": offers,
        "excluded": excluded,
        "shards": shard_fn(Path(shadow_db), recorded.world_id),
        "ticket_digest": digest,
        "ticket_snapshot_path": str(ticket_path),
        "ticket_snapshot": tickets,
        "offer_book": book,
        "decision_rule_best": decision_rule_best(book),
        "band_best": _band_best(snapshot, pilot),
    }
    path = _write_json(Path(reports_dir) / f"{day}.json", payload)
    return NightlyResult("recorded", None, path, payload)
```

- [ ] **Step 4: 确认通过**

Run: `uv run pytest tests/discovery/test_nightly.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add nutmeg/discovery/nightly.py tests/discovery/test_nightly.py
git commit -m "feat(discovery): nightly runner records one approved day world and its comparison material"
```

---

### Task 9: CLI `discovery nightly` 与 `discovery compare`

**Files:**
- Modify: `nutmeg/interfaces/cli/discovery.py`
- Test: `tests/test_cli_discovery.py`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_cli_discovery.py`）

```python
def _standing_file(tmp_path, jczq, shadow_db):
    from datetime import UTC, datetime, timedelta

    approved = (datetime.now(UTC) - timedelta(hours=1)).replace(microsecond=0).isoformat()
    path = tmp_path / "standing.json"
    path.write_text(json.dumps({
        "approval_id": "standing-cli", "kind": "standing", "approved_by": "op:jun",
        "approved_at": approved, "valid_from": approved,
        "valid_until": (datetime.now(UTC) + timedelta(days=30)).isoformat(), "revoked_at": None,
        "scope_template": {"source_kind": "day", "jczq_dir": str(jczq), "shadow_db": str(shadow_db),
                           "policy_revision_id": "structural-baseline-v1",
                           "generation_request_pattern": "day:{business_date}",
                           "cutoff_window_bjt": ["00:00", "23:59"],
                           "max_worlds_per_business_date": 1},
    }), encoding="utf-8")
    return path


def test_nightly_records_one_world_under_a_standing_approval_then_skips(tmp_path):
    jczq, day, day_dir, _cutoff, _approved = _prospective_day_fixture(tmp_path)
    shadow_dir = tmp_path / "shadow"
    registered = runner.invoke(
        app, ["discovery", "register-baseline", "--data-dir", str(shadow_dir), "--by", "op:jun"]
    )
    assert registered.exit_code == 0, registered.output
    shadow_db = OntologyPaths.from_data_dir(shadow_dir).database
    standing = _standing_file(tmp_path, jczq, shadow_db)
    args = ["discovery", "nightly", "--day", day, "--jczq-dir", str(jczq),
            "--shadow-db", str(shadow_db), "--standing-approval", str(standing),
            "--reports-dir", str(tmp_path / "reports"), "--tickets-dir", str(tmp_path / "tickets")]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    payload = json.loads(first.stdout.strip().splitlines()[-1])
    assert payload["status"] == "recorded" and payload["world_id"]
    status = runner.invoke(app, ["discovery", "status", "--data-dir", str(shadow_dir)])
    assert "sealed worlds: 1" in status.output
    second = runner.invoke(app, args)
    assert second.exit_code == 0
    assert json.loads(second.stdout.strip().splitlines()[-1])["reason"] == "already_recorded"


def test_nightly_refuses_a_shadow_store_inside_production(monkeypatch, tmp_path):
    import nutmeg.interfaces.cli.discovery as discovery_cli

    production = tmp_path / "prod-data"
    (production / "ontology").mkdir(parents=True)
    monkeypatch.setattr(discovery_cli, "PRODUCTION_DATA_DIR", production)
    result = runner.invoke(app, ["discovery", "nightly", "--day", "2026-09-29",
                                 "--shadow-db", str(production / "ontology" / "ontology.db")])
    assert result.exit_code == 1 and "production data directory" in result.output


def test_compare_scores_a_recorded_night_and_appends_the_ledger_once(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    book = {"A": {"belief": {"3": 0.5, "1": 0.3, "0": 0.2}, "odds": {"3": 1.8, "1": 3.2, "0": 4.5}},
            "C": {"belief": {"3": 0.7, "1": 0.2, "0": 0.1}, "odds": {"3": 1.3, "1": 4.6, "0": 8.0}}}
    (reports / "2026-09-29.json").write_text(json.dumps({
        "day": "2026-09-29", "status": "recorded", "world_id": "w", "manifest_hash": "m",
        "offer_book": book, "band_best": {}, "ticket_snapshot": {"betslips": []},
        "decision_rule_best": {"legs": [{"code": "A", "faces": "3"}, {"code": "C", "faces": "3"}],
                               "p_belief": 0.35, "notes": 1, "modal_return_per_yuan": 2.34},
    }), encoding="utf-8")
    data = tmp_path / "data"
    results = data / "daily" / "2026-09-30" / "results-90.json"
    results.parent.mkdir(parents=True)
    results.write_text(json.dumps({"A": {"outcome_90": "3"}, "C": {"outcome_90": "1"}}), encoding="utf-8")
    args = ["discovery", "compare", "--day", "2026-09-29", "--data-dir", str(data),
            "--reports-dir", str(reports)]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    out = json.loads(first.stdout.strip().splitlines()[-1])
    assert out["status"] == "settled"
    assert {r["kind"] for r in out["rows"]} == {"decision_rule", "empty"}
    assert out["summary"]["n_days"] == 1
    runner.invoke(app, args)
    ledger = data / "analytics" / "dream-compare" / "ledger.jsonl"
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1


def test_compare_without_a_recorded_night_is_a_quiet_no_world(tmp_path):
    result = runner.invoke(app, ["discovery", "compare", "--day", "2026-09-29",
                                 "--data-dir", str(tmp_path / "data"),
                                 "--reports-dir", str(tmp_path / "reports")])
    assert result.exit_code == 0
    assert json.loads(result.stdout.strip().splitlines()[-1])["status"] == "no_world"
```

- [ ] **Step 2: 确认失败**

Run: `uv run pytest tests/test_cli_discovery.py -k "nightly or compare" -q`
Expected: FAIL，`No such command 'nightly'`。

- [ ] **Step 3: 实现**（追加到 `nutmeg/interfaces/cli/discovery.py`）

```python
SHADOW_HOME = Path.home() / "nutmeg-shadow"


def _bj_today() -> str:
    from nutmeg.discovery.standing_approval import BJ

    return datetime.now(BJ).date().isoformat()


@discovery_app.command("nightly")
def nightly(
    day: str | None = typer.Option(None, "--day", help="业务日 YYYY-MM-DD，默认北京时间今天"),
    jczq_dir: Path = JCZQ_DIR_OPTION,
    shadow_db: Path = typer.Option(SHADOW_HOME / "ontology" / "ontology.db", "--shadow-db"),
    standing_approval: Path | None = typer.Option(None, "--standing-approval"),
    reports_dir: Path = typer.Option(SHADOW_HOME / "reports", "--reports-dir"),
    tickets_dir: Path = typer.Option(SHADOW_HOME / "tickets", "--tickets-dir"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只打印将冻结的场次与批准校验，不写影子库"),
) -> None:
    """常设批准下录一晚的 day 源世界（Jun 2026-09-28，至 10-31）。"""
    from nutmeg.discovery.nightly import run_nightly
    from nutmeg.discovery.standing_approval import DEFAULT_STANDING_PATH

    try:
        reject_production_store(shadow_db)
    except ValueError as exc:
        typer.echo(f"discovery error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    result = run_nightly(
        day=day or _bj_today(), jczq_dir=jczq_dir, shadow_db=shadow_db,
        standing_path=standing_approval or DEFAULT_STANDING_PATH,
        reports_dir=reports_dir, tickets_dir=tickets_dir,
        now=lambda: datetime.now(UTC), dry_run=dry_run,
    )
    summary = {"status": result.status, "reason": result.reason,
               "report": str(result.report_path) if result.report_path else None,
               **{k: result.payload.get(k) for k in ("day", "world_id", "offers", "excluded",
                                                     "cutoff_at", "standing_approval", "detail")
                  if k in result.payload}}
    typer.echo(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    raise typer.Exit(code=result.exit_code)


@discovery_app.command("compare")
def compare(
    day: str = typer.Option(..., "--day", help="录制业务日 YYYY-MM-DD"),
    data_dir: Path = DATA_DIR_OPTION,
    reports_dir: Path = typer.Option(SHADOW_HOME / "reports", "--reports-dir"),
) -> None:
    """次日对照：实际出票 / 决策规则最优 / 世界各档最优 / 空仓（只报告）。"""
    from datetime import date as _date

    from nutmeg.decision.betslip import load_slips
    from nutmeg.discovery.dream_compare import compare_day, summarize
    from nutmeg.discovery.standing_approval import (
        DEFAULT_STANDING_PATH,
        StandingApprovalError,
        days_left,
        load_standing_approval,
    )

    report_path = reports_dir / f"{day}.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
    try:
        left = days_left(load_standing_approval(DEFAULT_STANDING_PATH), datetime.now(UTC))
    except StandingApprovalError:
        left = None
    if not report or report.get("status") != "recorded":
        typer.echo(json.dumps({"day": day, "status": "no_world",
                               "reason": (report or {}).get("reason") or (report or {}).get("status"),
                               "standing_days_left": left}, ensure_ascii=False))
        return
    next_day = (_date.fromisoformat(day) + timedelta(days=1)).isoformat()
    results_path = data_dir / "daily" / next_day / "results-90.json"
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else {}
    slips = [s for s in load_slips(data_dir, channel="jczq")
             if s.purchased and str(s.placed_at)[:10] == day]
    scored = compare_day(report, results, slips)
    out_dir = data_dir / "analytics" / "dream-compare"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{day}.json").write_text(json.dumps(scored, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    ledger = out_dir / "ledger.jsonl"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
            if line.strip()] if ledger.exists() else []
    if scored["status"] == "settled" and all(row["day"] != day for row in rows):
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(scored, ensure_ascii=False) + "\n")
        rows.append(scored)
    typer.echo(json.dumps({**scored, "summary": summarize(rows), "standing_days_left": left},
                          ensure_ascii=False))
```

- [ ] **Step 4: 确认通过**

Run: `uv run pytest tests/test_cli_discovery.py -q`
Expected: 全部 PASS（`nightly` 集成测试会起真实分片子进程，约 10–30 秒）。

- [ ] **Step 5: 提交**

```bash
git add nutmeg/interfaces/cli/discovery.py tests/test_cli_discovery.py
git commit -m "feat(discovery): nightly and compare commands"
```

---

### Task 10: `day run --job dream` + 20:30 plist

**Files:**
- Modify: `nutmeg/decision/day_runner.py`（`JOBS`、`run_job`）、`nutmeg/interfaces/cli/day.py:21`
- Create: `ops/launchd/com.nutmeg.day.dream.plist`
- Test: `tests/decision/test_day_runner.py`

- [ ] **Step 1: 写失败测试**

把 `test_jobs_and_planned_settle_commands` 里的 `assert JOBS == ("settle", "brief", "session", "results", "broadcast")` 改成 `assert JOBS == ("settle", "brief", "session", "results", "broadcast", "dream")`，并追加：

```python
def test_dream_job_runs_nightly_and_records_its_outcome(tmp_path: Path):
    log: list[list[str]] = []
    ctx = _ctx(tmp_path, log)

    def runner(cmd):
        log.append(list(cmd))
        out = json.dumps({"status": "skipped", "reason": "outside_window", "day": "2026-09-23"})
        return subprocess.CompletedProcess(cmd, 0, out + "\n", "")

    ctx.runner = runner
    rec = run_job(ctx, "dream")
    assert log[0][:5] == ["uv", "run", "nutmeg", "discovery", "nightly"]
    assert "--day" in log[0] and "2026-09-23" in log[0]
    assert "--jczq-dir" in log[0] and str(ctx.data_dir / "jczq") in log[0]
    assert rec.exit == 0 and rec.summary == "dream skipped outside_window"
    assert read_timeline(ctx.data_dir, "2026-09-23")[-1]["job"] == "dream"


def test_dream_job_failure_keeps_the_exit_code(tmp_path: Path):
    ctx = _ctx(tmp_path, [])
    ctx.runner = lambda cmd: subprocess.CompletedProcess(
        cmd, 1, json.dumps({"status": "failed", "reason": "shadow_store_missing"}) + "\n", "")
    rec = run_job(ctx, "dream")
    assert rec.exit == 1 and rec.summary == "dream failed shadow_store_missing"
```

- [ ] **Step 2: 确认失败**

Run: `uv run pytest tests/decision/test_day_runner.py -q`
Expected: FAIL（`JOBS` 不含 `dream` / `unknown job 'dream'`）。

- [ ] **Step 3: 实现**

`nutmeg/decision/day_runner.py`：`JOBS = ("settle", "brief", "session", "results", "broadcast", "dream")`；`run_job` 的 `elif job == "broadcast":` 分支之后、`else:` 之前加：

```python
    elif job == "dream":
        # 夜间 Dream 录制（常设批准至 2026-10-31）：跳过/无解是数据，只有基础设施错误退出 1
        cmd = ["uv", "run", "nutmeg", "discovery", "nightly", "--day", ctx.date,
               "--jczq-dir", str(ctx.data_dir / "jczq")]
        proc = ctx.runner(cmd)
        commands = [{"cmd": " ".join(cmd[2:]), "exit": proc.returncode,
                     "tail": _tail((proc.stdout or "") + (proc.stderr or ""))}]
        try:
            outcome = json.loads((proc.stdout or "").strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            outcome = {"status": "failed", "reason": "no_json"}
        summary = f"dream {outcome.get('status')} {outcome.get('reason') or outcome.get('world_id')}"
        exit_code = proc.returncode
        evidence = outcome.get("report")
```

`nutmeg/interfaces/cli/day.py`：`_JOB` 的 help 改为 `"settle | brief | session | results | broadcast | dream"`。

新建 `ops/launchd/com.nutmeg.day.dream.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>EnvironmentVariables</key>
	<dict>
		<key>PATH</key>
		<string>/Users/jz71/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
	</dict>
	<key>Label</key>
	<string>com.nutmeg.day.dream</string>
	<key>ProgramArguments</key>
	<array>
		<string>/bin/zsh</string>
		<string>-lc</string>
		<string>cd /Users/jz71/Projects/Nutmeg &amp;&amp; /opt/homebrew/bin/uv run nutmeg day run --job dream</string>
	</array>
	<key>StandardErrorPath</key>
	<string>/Users/jz71/Projects/Nutmeg/.nutmeg-data/logs/day.dream.err.log</string>
	<key>StandardOutPath</key>
	<string>/Users/jz71/Projects/Nutmeg/.nutmeg-data/logs/day.dream.out.log</string>
	<key>StartCalendarInterval</key>
	<dict>
		<key>Hour</key>
		<integer>20</integer>
		<key>Minute</key>
		<integer>30</integer>
	</dict>
	<key>WorkingDirectory</key>
	<string>/Users/jz71/Projects/Nutmeg</string>
</dict>
</plist>
```

- [ ] **Step 4: 确认通过**

Run: `uv run pytest tests/decision/test_day_runner.py tests/test_cli_day.py -q && plutil -lint ops/launchd/com.nutmeg.day.dream.plist`
Expected: 全部 PASS，`OK`。

- [ ] **Step 5: 提交**

```bash
git add nutmeg/decision/day_runner.py nutmeg/interfaces/cli/day.py \
  ops/launchd/com.nutmeg.day.dream.plist tests/decision/test_day_runner.py
git commit -m "feat(day): nightly dream job at 20:30"
```

---

### Task 11: RSI 闭环 `dream_compare` 步骤与报告节

**Files:**
- Modify: `nutmeg/decision/rsi_loop.py`
- Test: `tests/decision/test_rsi_loop.py`

- [ ] **Step 1: 写失败测试**

```python
def test_dream_compare_step_reports_yesterday_and_expiry_countdown(tmp_path):
    log: list[list[str]] = []
    ctx = _ctx(tmp_path, log)
    base = ctx.runner

    def runner(cmd):
        if "compare" in cmd:
            log.append(list(cmd))
            payload = {"day": "2026-09-21", "status": "settled",
                       "rows": [{"kind": "decision_rule", "status": "settled", "hit": True,
                                 "pnl_per_yuan": 0.4, "p_belief": 0.52}],
                       "summary": {"n_days": 3, "kinds": {}, "actual_minus_rule":
                                   {"n": 3, "mean": -0.2, "ci95": None}},
                       "standing_days_left": 5}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload) + "\n", "")
        return base(cmd)

    ctx.runner = runner
    plan = planned_commands(ctx)
    assert STEP_ORDER[-1] == "dream_compare"
    assert plan["dream_compare"][0][2:6] == ["nutmeg", "discovery", "compare", "--day"]
    assert "2026-09-21" in plan["dream_compare"][0]
    report = run_loop(ctx)
    assert report.dream["day"] == "2026-09-21"
    assert any("常设批准" in a and "5" in a for a in report.human_actions)
    md = (ctx.out_dir / "2026-09-22.md").read_text(encoding="utf-8")
    assert "## Dream 对照" in md and "decision_rule" in md and "−0.2" in md.replace("-0.2", "−0.2")
```

- [ ] **Step 2: 确认失败**

Run: `uv run pytest tests/decision/test_rsi_loop.py -q`
Expected: FAIL（`KeyError: 'dream_compare'`）。

- [ ] **Step 3: 实现**

`nutmeg/decision/rsi_loop.py`：

1. 模块 docstring 步骤表在 `8. scoreboard` 下加一行 `    8b. dream_compare     前一业务日 Dream 世界对照记账（只报告；常设批准到期前 7 天报倒计时）`。
2. `STEP_ORDER` 末尾加 `"dream_compare",`。
3. `LoopReport` 加字段 `dream: dict = field(default_factory=dict)`（放在 `failed_steps` 之后）。
4. `planned_commands` 返回字典末尾加：

```python
        "dream_compare": [
            [*uv, "nutmeg", "discovery", "compare", "--day", _days_before(ctx.date, 1), *data],
        ],
```

5. `_collect` 返回值扩成五元组：函数签名改为 `-> tuple[list[dict], list[dict], list[dict], list[str], dict]`，开头加 `dream: dict = {}`，`for item in step.detail…` 循环里加分支：

```python
            elif step.name == "dream_compare":
                for row in item.get("json", []):
                    dream = row
                left = dream.get("standing_days_left")
                if left is not None and left <= 7:
                    actions.append(f"Dream 常设批准还剩 {left} 天到期（2026-10-31）→ 续期/撤销/改窗口由 Jun 裁")
```

   末尾 `return proposals, grades, verdicts, actions, dream`。
6. `run_loop` 里 `proposals, grades, verdicts, actions, dream = _collect(steps)`，构造 `LoopReport(..., failed_steps=failed, dream=dream)`。
7. `render_markdown` 在因子提案之后、结尾警示之前加：

```python
    if report.dream:
        d = report.dream
        lines += ["", "## Dream 对照", "",
                  f"- {d.get('day')}：{d.get('status')}"
                  + (f"（{d.get('reason')}）" if d.get("reason") else "")]
        for row in d.get("rows", []):
            lines.append(
                f"  - {row['kind']} {row.get('id') or ''} P={row.get('p_belief')} "
                f"中={row.get('hit')} 每元盈亏={row.get('pnl_per_yuan')}"
            )
        summary = d.get("summary") or {}
        diff = summary.get("actual_minus_rule") or {}
        if summary:
            ci = diff.get("ci95") or f"n={diff.get('n')}<20，不给区间"
            mean_text = "—" if diff.get("mean") is None else f"{diff['mean']:+.4f}".replace("-", "−")
            lines.append(f"- 累计 {summary.get('n_days')} 天；实际−规则最优 日均每元 {mean_text}（{ci}）")
```

- [ ] **Step 4: 确认通过**

Run: `uv run pytest tests/decision/test_rsi_loop.py tests/test_cli_rsi.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add nutmeg/decision/rsi_loop.py tests/decision/test_rsi_loop.py
git commit -m "feat(rsi): dream comparison step and report section"
```

---

### Task 12: 常设批准落文件、spec 修订、全量验证、合并与装载

**Files:**
- Create: `experiments/discovery/approvals/standing-dream-nightly-2026-10.json`
- Modify: `docs/superpowers/specs/2026-09-28-dream-nightly-recording-design.md`
- Create: `docs/superpowers/evidence/2026-09-28-dream-nightly-recording.md`

- [ ] **Step 1: 落常设批准**（主会话，时刻取落文件那一刻）

```bash
NOW=$(TZ=Asia/Shanghai date +%Y-%m-%dT%H:%M:%S+08:00)
mkdir -p experiments/discovery/approvals
cat > experiments/discovery/approvals/standing-dream-nightly-2026-10.json <<EOF
{
 "approval_id": "standing-dream-nightly-2026-10",
 "kind": "standing",
 "approved_by": "op:jun",
 "approved_at": "$NOW",
 "valid_from": "$NOW",
 "valid_until": "2026-10-31T23:59:59+08:00",
 "revoked_at": null,
 "scope_template": {
  "source_kind": "day",
  "jczq_dir": "/Users/jz71/Projects/Nutmeg/.nutmeg-data/jczq",
  "shadow_db": "/Users/jz71/nutmeg-shadow/ontology/ontology.db",
  "policy_revision_id": "structural-baseline-v1",
  "generation_request_pattern": "day:{business_date}",
  "cutoff_window_bjt": ["20:00", "23:59"],
  "max_worlds_per_business_date": 1
 },
 "note": "Jun 2026-09-28 聊天：「以上全写成设计，常批准先实验到10.31日」；撤销＝填 revoked_at 或删文件"
}
EOF
uv run python -c "from nutmeg.discovery.standing_approval import load_standing_approval, DEFAULT_STANDING_PATH as p; print(load_standing_approval(p).approval_id)"
```
Expected: 打印 `standing-dream-nightly-2026-10`。

- [ ] **Step 2: spec 修订**——在 spec §3.1 末尾追加一段「评估器 v2（Jun 2026-09-28 批）」：P0 修复后 7 场真实板面四分片 0.0–0.9 s 完成，但全部被 v1 的每档 20 上限判 over_cap；v2 去掉整片失败、只记 `band_candidate_counts`，三个质量字段数值不变，试点与选择契约重冻结，09-28 超时世界留在 v1 下且被世界池按评估器版本排除。§3.5 把「次日在冻结 snapshot 上重跑纯分片函数」改为「录制时用同一冻结快照算好 `offer_book`/`decision_rule_best`/`band_best` 写进夜间报告（与 manifest 哈希绑定），次日只读报告」。

- [ ] **Step 3: 全量测试**

Run: `uv run pytest -q -x`
Expected: 全部 PASS（与 main 基线相同的跳过数）。

- [ ] **Step 4: 端到端（verify 口径，生产数据只读）**

```bash
uv run nutmeg discovery nightly --jczq-dir /Users/jz71/Projects/Nutmeg/.nutmeg-data/jczq --dry-run
uv run nutmeg discovery compare --day $(TZ=Asia/Shanghai date -v-1d +%F) --data-dir /Users/jz71/Projects/Nutmeg/.nutmeg-data
```
Expected: 第一条打印 `status`（窗口内为 `dry_run` 并列出未开球场次；窗口外为 `skipped outside_window`）；第二条打印 `no_world`（此前没有夜间报告）。另外用 Task 1/2 的修复在今天的真实板面上重跑四分片计时（`uv run python` 调 `execute_template_shard`），记下每分片状态与耗时进证据。

- [ ] **Step 5: 证据、合并、装载**

写 `docs/superpowers/evidence/2026-09-28-dream-nightly-recording.md`（出生事故、四分片前后对比、评估器 v2 批准原话、常设批准文件哈希、E2E 输出、装载命令与 Jun 授权原话）。然后：

```bash
git add experiments/discovery/approvals/standing-dream-nightly-2026-10.json \
  docs/superpowers/specs/2026-09-28-dream-nightly-recording-design.md \
  docs/superpowers/evidence/2026-09-28-dream-nightly-recording.md
git commit -m "chore(discovery): standing approval through 2026-10-31 and nightly evidence"
cd /Users/jz71/Projects/Nutmeg
git merge --ff-only feat/dream-nightly
uv run pytest tests/discovery tests/decision/test_day_runner.py tests/decision/test_rsi_loop.py -q
cp ops/launchd/com.nutmeg.day.dream.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.nutmeg.day.dream.plist
launchctl list | grep com.nutmeg.day.dream
git worktree remove ../Nutmeg-dream-nightly && git branch -d feat/dream-nightly
```
Expected: 快进合并成功；`launchctl list` 出现 `com.nutmeg.day.dream`。
