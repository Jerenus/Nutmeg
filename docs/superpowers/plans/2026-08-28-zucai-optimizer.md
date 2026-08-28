# 足彩候选票优化器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 新增一个只比较人工给定候选票的确定性 CLI，稳定输出单票算术、帽内排序、版本变化、多票联合命中率和共同死面。

**Architecture:** `nutmeg.decision.zucai_optimizer` 是无 IO 的校验与计算边界，内部用 `Decimal` 防止浮点排序漂移；`interfaces.cli.decision` 只读 JSON、渲染结果并映射输入错误退出码。候选生成、fair 判读和出票裁决仍由主循环承担。

**Tech Stack:** Python 3.12、标准库 `decimal/itertools/json`、Typer、pytest。

---

## 文件结构

- Create `nutmeg/decision/zucai_optimizer.py`：输入校验、单票/组计算、文本报告。
- Modify `nutmeg/interfaces/cli/decision.py`：注册 `zucai-optimize`。
- Create `tests/decision/test_zucai_optimizer.py`：纯函数、边界和 26111 回放。
- Create `tests/decision/test_zucai_optimizer_cli.py`：CLI 合同和退出码。
- Modify `docs/superpowers/plans/2026-08-28-zucai-optimizer.md`：执行时逐项勾选。

## Task 1: 单票算术与严格输入校验

**Files:**
- Create: `tests/decision/test_zucai_optimizer.py`
- Create: `nutmeg/decision/zucai_optimizer.py`

- [x] **Step 1: 写失败测试**

```python
from decimal import Decimal

import pytest

from nutmeg.decision.zucai_optimizer import OptimizerInputError, optimize


def _payload():
    return {
        "issue": "X",
        "price_per_note": 2,
        "budget_yuan": 12,
        "fair": {
            "1": {"home": 0.5, "draw": 0.3, "away": 0.2},
            "2": {"home": 0.6, "draw": 0.25, "away": 0.15},
        },
        "versions": [{"id": "A", "faces": {"1": "31", "2": "3"}}],
    }


def test_single_version_arithmetic():
    result = optimize(_payload())
    version = result["versions"][0]
    assert version["notes"] == 2
    assert version["cost_yuan"] == 4
    assert version["p_all"] == pytest.approx(0.48)
    assert version["expected_broken"] == pytest.approx(0.6)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["fair"]["1"].update(away=0.1),
        lambda p: p["versions"][0]["faces"].update({"1": "33"}),
        lambda p: p["versions"][0]["faces"].update({"1": "3x"}),
        lambda p: p["versions"][0]["faces"].update({"3": "3"}),
        lambda p: p["versions"].append({"id": "A", "faces": {"1": "3"}}),
    ],
)
def test_invalid_input_is_rejected(mutation):
    payload = _payload()
    mutation(payload)
    with pytest.raises(OptimizerInputError):
        optimize(payload)
```

- [x] **Step 2: 跑测试确认 RED**

Run: `uv run pytest tests/decision/test_zucai_optimizer.py -v`
Expected: collection FAIL，`nutmeg.decision.zucai_optimizer` 不存在。

- [x] **Step 3: 写最小实现**

实现 `OptimizerInputError`、`_decimal`、`_validate_payload`、`_version_stats` 和
`optimize`。校验 fair 三键、0..1、总和误差不超过 `Decimal("0.001")`；校验正整数
票价/注金帽、唯一 ID、合法且不重复的 faces。每票用覆盖率乘积和未覆盖率之和计算：

```python
FACE_KEYS = {"3": "home", "1": "draw", "0": "away"}


def _version_stats(version, fair, price_per_note):
    coverages = []
    notes = 1
    for match_no, faces in _sorted_faces(version["faces"]):
        coverage = sum(fair[match_no][FACE_KEYS[face]] for face in faces)
        coverages.append(coverage)
        notes *= len(faces)
    probability = prod(coverages, start=Decimal(1))
    return {
        "id": version["id"],
        "faces": dict(_sorted_faces(version["faces"])),
        "notes": notes,
        "cost_yuan": notes * price_per_note,
        "p_all": float(probability),
        "expected_broken": float(sum((1 - value for value in coverages), Decimal(0))),
    }
```

- [x] **Step 4: 跑测试确认 GREEN**

Run: `uv run pytest tests/decision/test_zucai_optimizer.py -v`
Expected: all tests pass。

- [x] **Step 5: Commit**

```bash
git add nutmeg/decision/zucai_optimizer.py tests/decision/test_zucai_optimizer.py
git commit -m "feat(decision): add deterministic zucai version arithmetic"
```

## Task 2: 帽内排序与 baseline 变化量

**Files:**
- Modify: `tests/decision/test_zucai_optimizer.py`
- Modify: `nutmeg/decision/zucai_optimizer.py`

- [x] **Step 1: 写失败测试**

```python
def test_cap_ranking_and_baseline_deltas_are_stable():
    payload = _payload()
    payload["baseline_id"] = "A"
    payload["versions"] += [
        {"id": "B", "faces": {"1": "310", "2": "3"}},
        {"id": "C", "faces": {"1": "31", "2": "31"}},
    ]
    payload["budget_yuan"] = 8
    result = optimize(payload)
    assert result["ranking"] == ["C", "B", "A"]
    assert result["best_within_cap_id"] == "C"
    c = next(item for item in result["versions"] if item["id"] == "C")
    assert c["delta_vs_baseline"]["notes"] == 2
    assert c["delta_vs_baseline"]["p_all_pp"] == pytest.approx(0.20 * 100)
```

- [x] **Step 2: 跑指定测试确认 RED**

Run: `uv run pytest tests/decision/test_zucai_optimizer.py::test_cap_ranking_and_baseline_deltas_are_stable -v`
Expected: FAIL，缺少 ranking/delta。

- [x] **Step 3: 最小实现**

保留内部 `Decimal` 概率用于排序和差值；帽内排序键为
`(-p_all_decimal, cost_yuan, id)`。输出每版 `within_cap`，存在 baseline 时输出 notes、
cost、`p_all_pp`、expected_broken 差值。没有帽时 ranking 包含全部版本；帽内无候选时
ranking 为空且 `best_within_cap_id` 为 `None`，不渲染空仓建议。

- [x] **Step 4: 跑纯函数测试确认 GREEN**

Run: `uv run pytest tests/decision/test_zucai_optimizer.py -v`
Expected: all tests pass。

- [x] **Step 5: Commit**

```bash
git add nutmeg/decision/zucai_optimizer.py tests/decision/test_zucai_optimizer.py
git commit -m "feat(decision): rank supplied tickets within stake cap"
```

## Task 3: 多票联合概率与共同死面

**Files:**
- Modify: `tests/decision/test_zucai_optimizer.py`
- Modify: `nutmeg/decision/zucai_optimizer.py`

- [x] **Step 1: 写失败测试**

```python
def test_group_union_probability_uses_inclusion_exclusion():
    payload = _payload()
    payload["versions"] = [
        {"id": "H", "faces": {"1": "3"}},
        {"id": "D", "faces": {"1": "1"}},
    ]
    payload["groups"] = [{"id": "pair", "version_ids": ["H", "D"]}]
    group = optimize(payload)["groups"][0]
    assert group["p_any_all"] == pytest.approx(0.8)
    assert group["common_dead_faces"] == [{"match_no": "1", "faces": "0"}]


def test_group_omits_common_dead_faces_for_non_common_legs():
    payload = _payload()
    payload["versions"] = [
        {"id": "M1", "faces": {"1": "3"}},
        {"id": "M2", "faces": {"2": "3"}},
    ]
    payload["groups"] = [{"id": "pair", "version_ids": ["M1", "M2"]}]
    assert optimize(payload)["groups"][0]["common_dead_faces"] == []
```

- [x] **Step 2: 跑指定测试确认 RED**

Run: `uv run pytest tests/decision/test_zucai_optimizer.py -v -k group`
Expected: FAIL，groups 尚未计算。

- [x] **Step 3: 最小实现**

用 `itertools.combinations` 遍历组成员的所有非空子集。对子集每一场收集所有约束该场
的 faces 并求交集；无约束场忽略，交集为空则该事件为零。按奇数子集加、偶数子集减得到
`p_any_all`。共同死面仅遍历所有版本 faces 键的交集，并以固定 `310` 顺序输出未被各票
faces 并集覆盖的面。

- [x] **Step 4: 跑纯函数测试确认 GREEN**

Run: `uv run pytest tests/decision/test_zucai_optimizer.py -v`
Expected: all tests pass。

- [x] **Step 5: Commit**

```bash
git add nutmeg/decision/zucai_optimizer.py tests/decision/test_zucai_optimizer.py
git commit -m "feat(decision): compare joint ticket coverage deterministically"
```

## Task 4: 26111 三版本验收回放

**Files:**
- Modify: `tests/decision/test_zucai_optimizer.py`

- [x] **Step 1: 写验收测试**

在测试内固定 26111 九场 fair（场 5 取 `26111-legs-SFC486.json`，其余取
`26111-legs-U864F.json`），声明三个版本：

```python
versions = [
    {"id": "U864用户版", "faces": {
        "1": "310", "3": "3", "5": "310", "7": "31", "9": "01",
        "10": "31", "11": "310", "12": "31", "14": "3"}},
    {"id": "U864优化版", "faces": {
        "1": "310", "3": "31", "5": "310", "7": "3", "9": "01",
        "10": "31", "11": "310", "12": "31", "14": "3"}},
    {"id": "U1296", "faces": {
        "1": "310", "3": "31", "5": "310", "7": "3", "9": "310",
        "10": "31", "11": "310", "12": "31", "14": "3"}},
]
```

断言注数为 432/432/648，票价为 864/864/1296，P 的百分比四舍五入两位为
24.49/27.96/33.65；帽 864 的第一名为 U864优化版。

- [x] **Step 2: 跑测试；如失败只修计算实现，不改验收锚**

Run: `uv run pytest tests/decision/test_zucai_optimizer.py -v -k 26111`
Expected: PASS；若 RED，差异必须追溯到输入/公式后修实现。

- [x] **Step 3: 跑整个纯函数文件**

Run: `uv run pytest tests/decision/test_zucai_optimizer.py -v`
Expected: all tests pass。

- [x] **Step 4: Commit**

```bash
git add tests/decision/test_zucai_optimizer.py
git commit -m "test(decision): replay 26111 optimizer versions"
```

## Task 5: CLI 文本、JSON 与错误退出码

**Files:**
- Create: `tests/decision/test_zucai_optimizer_cli.py`
- Modify: `nutmeg/interfaces/cli/decision.py`
- Modify: `nutmeg/decision/zucai_optimizer.py`

- [x] **Step 1: 写失败 CLI 测试**

```python
import json

from typer.testing import CliRunner

from nutmeg.interfaces.cli import app


runner = CliRunner()


def test_zucai_optimize_json_output(tmp_path):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(SIMPLE_PAYLOAD, ensure_ascii=False), "utf-8")
    result = runner.invoke(app, ["zucai-optimize", "--input-file", str(path), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["best_within_cap_id"] == "A"


def test_zucai_optimize_text_table(tmp_path):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(SIMPLE_PAYLOAD, ensure_ascii=False), "utf-8")
    result = runner.invoke(app, ["zucai-optimize", "--input-file", str(path)])
    assert result.exit_code == 0
    assert "版本" in result.stdout and "P(全对)" in result.stdout


def test_zucai_optimize_bad_input_exits_two(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{}", "utf-8")
    result = runner.invoke(app, ["zucai-optimize", "--input-file", str(path)])
    assert result.exit_code == 2
    assert "输入错误" in result.stderr
```

- [x] **Step 2: 跑 CLI 测试确认 RED**

Run: `uv run pytest tests/decision/test_zucai_optimizer_cli.py -v`
Expected: FAIL，命令不存在。

- [x] **Step 3: 实现文本渲染与 CLI**

在纯模块增加 `format_report(result)`，按版本输出 ID、注数、票价、P、期望断腿、帽内状态，
随后输出帽内排名与组联合结果。CLI 使用：

```python
@_cli.app.command("zucai-optimize")
def zucai_optimize(
    input_file: Path = _cli.typer.Option(..., "--input-file", help="候选版本 JSON"),
    json_output: bool = _cli.typer.Option(False, "--json", help="输出稳定 JSON"),
) -> None:
    try:
        payload = json.loads(input_file.read_text("utf-8"))
        result = optimize(payload)
    except (OSError, json.JSONDecodeError, OptimizerInputError) as exc:
        _cli.typer.echo(f"输入错误：{exc}", err=True)
        raise _cli.typer.Exit(code=2) from exc
    _cli.typer.echo(
        json.dumps(result, ensure_ascii=False, indent=2) if json_output
        else format_report(result)
    )
```

- [x] **Step 4: 跑 CLI 与纯函数测试确认 GREEN**

Run: `uv run pytest tests/decision/test_zucai_optimizer.py tests/decision/test_zucai_optimizer_cli.py -v`
Expected: all tests pass。

- [x] **Step 5: Commit**

```bash
git add nutmeg/interfaces/cli/decision.py nutmeg/decision/zucai_optimizer.py \
  tests/decision/test_zucai_optimizer_cli.py
git commit -m "feat(cli): expose zucai candidate optimizer"
```

## Task 6: 全量验证与真实文件回放

**Files:**
- Modify: `docs/superpowers/plans/2026-08-28-zucai-optimizer.md`（勾选实际完成项）

- [x] **Step 1: 静态检查**

Run: `uv run ruff check .`
Expected: `All checks passed!`

- [x] **Step 2: 全量测试**

Run: `uv run pytest -q`
Expected: 0 failed。

- [x] **Step 3: CLI help smoke**

Run: `uv run nutmeg zucai-optimize --help`
Expected: exit 0，列出 `--input-file` 与 `--json`。

- [x] **Step 4: 临时目录回放 26111**

从只读生产文件提取 fair 写入 `mktemp -d` 下的输入，运行文本与 JSON 两种输出。确认显示
432/¥864/24.49%、432/¥864/27.96%、648/¥1,296/33.65%，帽 864 第一名为
U864优化版；不得写 `.nutmeg-data`。

- [x] **Step 5: 完成计划勾选并提交**

```bash
git add docs/superpowers/plans/2026-08-28-zucai-optimizer.md
git commit -m "docs(plan): record zucai optimizer verification"
```

## 显式排除

- 不自动生成候选、不搜索面组合、不自动裁决换血或投注。
- 不读取赔率源推导 fair，不计算 EV 或部署门。
- 不写 rx、ledger、ontology、scoreboard 或生产 `.nutmeg-data`。
- 不把帽内第一名输出成出票建议，也不加入空仓建议。

## 执行记录（2026-08-28）

- `uv run ruff check .`：All checks passed。
- `uv run pytest -q`：1,408 tests collected，退出码 0。
- `uv run nutmeg zucai-optimize --help`：退出码 0，`--input-file` / `--json` 正常。
- 26111 只读生产 fair 回放：U864用户版 432 注 / ¥864 / 24.47%，U864优化版
  432 注 / ¥864 / 27.96%，U1296 648 注 / ¥1,296 / 33.64%；帽 864 第一名为
  U864优化版；U864 双票联合命中率 32.11%。
- rx 在更高精度工作 fair 下记录 24.49% / 27.96% / 33.65%，但现存 legs 只保存三位
  fair，回放最大差 0.02pp。测试按半个三位 fair 量化单位（0.05pp）验收，不在代码中
  添加期次常数修饰结果。
- 全量首跑发现 main 的 reliability backup 测试仍硬编码 schema 14；cherry-pick 已完成的
  schema 15 共享修复 `5c68f09` 后复跑全绿，本分支对应 commit 为 `c5a043c`。
