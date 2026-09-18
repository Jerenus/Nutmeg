# RSI 过程持久化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「假设 → 预注册 → 按日义务 → 采样 → 结账 → 判决 → 上线」做成 Ontology Kernel v2 里一组只追加的 typed Action，`nutmeg rsi status` 一屏答出每条实验的状态 / n_cum / 距 falsifier / 下一步义务。

**Architecture:** 八张只追加的表（`schema_rsi.py`）+ 一个 `RsiRepository` + 一个 `RsiActions`（8 个 action_type，权限落 `action_permissions`）+ 纯函数层 `nutmeg/ontology/rsi/models.py`（frozen_hash、falsifier 判定、状态投影，零 IO，最重的测试在这里）+ CLI `nutmeg rsi …`。状态永远是投影，没有可改写的 status 列。人 = `ActorRole.JUDGE_OPERATOR`，系统 = `ActorRole.DETERMINISTIC_SYSTEM`。

**Tech Stack:** Python 3.13 / SQLAlchemy Core（沿用 `schema.py` 的 `Table` 声明）/ typer / pytest。Spec：`docs/superpowers/specs/2026-09-18-rsi-experiment-persistence-design.md`。

**仓库纪律（每个任务都适用）：** `git add` 只用显式路径；提交不接管道，`echo "EXIT=$?"` 后用 `git log --oneline -1` 复验；提交时不要有别的进程在改文件（pre-commit 会把并发编辑当成「钩子改了文件」）。

---

## 文件结构

- Create `nutmeg/ontology/rsi/__init__.py`、`nutmeg/ontology/rsi/models.py` — 枚举、行 dataclass、`frozen_hash`、`Falsifier.evaluate`、`project_status`（纯函数）
- Create `nutmeg/ontology/repository/schema_rsi.py` — 8 张表
- Create `nutmeg/ontology/repository/rsi.py` — `RsiRepository`
- Modify `nutmeg/ontology/repository/unit_of_work.py` — `rsi` 属性
- Modify `nutmeg/ontology/repository/migrations.py` — `_apply_rsi_experiments` + 权限 + `Migration(version=29)`
- Create `nutmeg/ontology/actions/rsi_actions.py` — `RsiActions`
- Modify `nutmeg/ontology/wiring.py`、`nutmeg/ontology/kernel.py` — 挂 `rsi_actions`
- Create `nutmeg/decision/rsi_prereg.py` — 登记原件加载与校验
- Create `nutmeg/decision/rsi_grading.py` — F2 结账适配器 + 泄漏拒收 + dream 重放
- Create `nutmeg/interfaces/cli/rsi.py`；Modify `nutmeg/interfaces/cli/__init__.py`
- Modify `nutmeg/product/repository.py` — 读侧三个查询
- Create `experiments/registry/{F2,F1c,F3,F4,F5}.json`、`scripts/rsi_migrate_preregs.py`
- Modify `scripts/zucai_f2_observe.py`、`scripts/zucai_book_dispersion.py`、`docs/sop/RUNBOOK.md` — 接线一行
- Tests：`tests/ontology/test_rsi_models.py`、`tests/ontology/test_rsi_migration.py`、`tests/ontology/test_rsi_repository.py`、`tests/ontology/test_rsi_actions.py`、`tests/decision/test_rsi_prereg.py`、`tests/decision/test_rsi_grading.py`、`tests/test_cli_rsi.py`

---

### Task 1: 纯函数层——枚举、frozen_hash、falsifier 判定、状态投影

**Files:**
- Create: `nutmeg/ontology/rsi/__init__.py`（空文件）
- Create: `nutmeg/ontology/rsi/models.py`
- Test: `tests/ontology/test_rsi_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ontology/test_rsi_models.py
from nutmeg.ontology.rsi.models import (
    Falsifier,
    Layer,
    Tier,
    Verdict,
    frozen_hash,
    project_status,
    validate_tier_for_layer,
)

_F2 = {
    "claim": "让球线向主移动 → 主胜残差为正", "mechanism": "改线是承诺",
    "tier": "observation", "layer": "judgment", "population": "zucai",
    "min_tier": "price_only", "window": {"issue_from": "26126", "issue_to": "26137"},
    "falsifier": {"metric": "home_resid_pp", "stratum": "zucai", "n_min": 140,
                  "bound": "ci_upper", "threshold_pp": 2.0, "direction": "lt_means_falsified"},
    "stop_rule": "n≥140 结账", "quota_slot": False,
    "buckets": ["向客 ≤-0.25", "不动 0", "向主 +0.25", "向主 ≥+0.5"],
}


def test_frozen_hash_covers_every_frozen_field_and_ignores_the_rest():
    h = frozen_hash(_F2)
    assert frozen_hash({**_F2, "source_doc": "x.json", "rule_ids": ["C11"]}) == h   # 非冻结字段不影响
    assert frozen_hash({**_F2, "mechanism": "改了"}) != h                           # U5：mechanism 也冻结
    assert frozen_hash({**_F2, "buckets": _F2["buckets"][:-1]}) != h


def test_falsifier_reads_only_the_ci_bound_and_refuses_before_n_min():
    f = Falsifier.from_dict(_F2["falsifier"])
    assert f.evaluate(n_cum=139, ci_low=-1.0, ci_high=1.0) is None            # 未到期：不判
    assert f.evaluate(n_cum=140, ci_low=-3.0, ci_high=1.9) is Verdict.FALSIFIED  # 上界 <2 → 证伪
    assert f.evaluate(n_cum=140, ci_low=2.5, ci_high=9.0) is Verdict.SURVIVED    # 下界 ≥2 → 成立
    assert f.evaluate(n_cum=140, ci_low=-1.0, ci_high=5.0) is Verdict.INCONCLUSIVE  # 跨线 → 不定


def test_judgment_layer_cannot_be_deploy_eligible():
    validate_tier_for_layer(Tier.OBSERVATION, Layer.JUDGMENT)
    try:
        validate_tier_for_layer(Tier.DEPLOY_ELIGIBLE, Layer.JUDGMENT)
    except ValueError as exc:
        assert "judgment" in str(exc)
    else:
        raise AssertionError("判读层实验不得 deploy_eligible")


def test_status_projection_is_derived_not_stored():
    base = dict(n_observations=0, latest_prospective_n=0, n_min=140, latest_verdict=None,
                latest_deployment=None)
    assert project_status(**base) == "registered"
    assert project_status(**{**base, "n_observations": 3}) == "observing"
    assert project_status(**{**base, "n_observations": 12, "latest_prospective_n": 140}) == "graded"
    assert project_status(**{**base, "n_observations": 12, "latest_prospective_n": 140,
                             "latest_verdict": "inconclusive"}) == "inconclusive"
    assert project_status(**{**base, "n_observations": 12, "latest_prospective_n": 150,
                             "latest_verdict": "survived", "latest_deployment": "deploy"}) == "deployed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ontology/test_rsi_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nutmeg.ontology.rsi'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/ontology/rsi/__init__.py
```
（空文件）

```python
# nutmeg/ontology/rsi/models.py
"""RSI 实验对象的纯函数层：枚举、冻结哈希、falsifier 判定、状态投影。零 IO。

宪法落点：
- frozen_hash 覆盖登记原件的**全部**判据字段（含 mechanism，用户裁定 U5）；
- Falsifier.evaluate 只读 CI 边界、n<n_min 返回 None（不判）——中途看得见数字看不见判决；
- 判读层（layer=judgment）不可重放，因此最高只能是 observation，永不 deploy（U8-⑤）。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from nutmeg.ontology.actions.models import canonical_json


class Tier(StrEnum):
    CANDIDATE = "candidate"
    OBSERVATION = "observation"
    DEPLOY_ELIGIBLE = "deploy_eligible"


class Layer(StrEnum):
    JUDGMENT = "judgment"
    STRUCTURAL = "structural"


class Population(StrEnum):
    ZUCAI = "zucai"
    JCZQ = "jczq"
    BOTH = "both"


class JudgmentTier(StrEnum):
    PRICE_ONLY = "price_only"
    LIGHT_READ = "light_read"
    DEEP_RESEARCH = "deep_research"


class GradeMode(StrEnum):
    REPLAY = "replay"
    PROSPECTIVE = "prospective"


class Verdict(StrEnum):
    FALSIFIED = "falsified"
    SURVIVED = "survived"
    INCONCLUSIVE = "inconclusive"


class DeploymentDecision(StrEnum):
    DEPLOY = "deploy"
    HOLD = "hold"
    RETIRE = "retire"
    EXTEND = "extend"


FROZEN_FIELDS: tuple[str, ...] = (
    "claim", "mechanism", "tier", "layer", "population", "min_tier",
    "window", "falsifier", "stop_rule", "quota_slot", "buckets",
)


def frozen_hash(doc: dict) -> str:
    """登记原件的冻结指纹。只看 FROZEN_FIELDS，与字段顺序无关。"""
    material = {k: doc.get(k) for k in FROZEN_FIELDS}
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def validate_tier_for_layer(tier: Tier, layer: Layer) -> None:
    if layer is Layer.JUDGMENT and tier is Tier.DEPLOY_ELIGIBLE:
        raise ValueError("judgment 层实验不可重放，最高只能是 observation，不得 deploy_eligible")


@dataclass(frozen=True, slots=True)
class Falsifier:
    metric: str
    stratum: str
    n_min: int
    bound: str            # "ci_upper" | "ci_lower"
    threshold_pp: float
    direction: str        # "lt_means_falsified" | "gt_means_falsified"

    @classmethod
    def from_dict(cls, d: dict) -> Falsifier:
        if d["bound"] not in ("ci_upper", "ci_lower"):
            raise ValueError(f"bound 必须是 ci_upper/ci_lower，得到 {d['bound']!r}")
        if d["direction"] not in ("lt_means_falsified", "gt_means_falsified"):
            raise ValueError(f"direction 非法: {d['direction']!r}")
        return cls(metric=str(d["metric"]), stratum=str(d["stratum"]), n_min=int(d["n_min"]),
                   bound=str(d["bound"]), threshold_pp=float(d["threshold_pp"]),
                   direction=str(d["direction"]))

    def evaluate(self, *, n_cum: int, ci_low: float, ci_high: float) -> Verdict | None:
        """n<n_min → None（不判）。判据只读 CI 边界，从不读点估计。"""
        if n_cum < self.n_min:
            return None
        t = self.threshold_pp
        if self.direction == "lt_means_falsified":
            # 「上界 < t」证伪；「下界 ≥ t」成立；否则跨线
            if ci_high < t:
                return Verdict.FALSIFIED
            if ci_low >= t:
                return Verdict.SURVIVED
            return Verdict.INCONCLUSIVE
        if ci_low > t:
            return Verdict.FALSIFIED
        if ci_high <= t:
            return Verdict.SURVIVED
        return Verdict.INCONCLUSIVE

    def distance_pp(self, *, ci_low: float, ci_high: float) -> float:
        """距触发 falsifier 还差多少 pp（正数=还没到）。"""
        if self.direction == "lt_means_falsified":
            return ci_high - self.threshold_pp
        return self.threshold_pp - ci_low


def project_status(*, n_observations: int, latest_prospective_n: int, n_min: int,
                   latest_verdict: str | None, latest_deployment: str | None) -> str:
    """状态是投影：registered → observing → graded → <verdict> → <deployment>。"""
    if latest_deployment == "deploy":
        return "deployed"
    if latest_deployment == "hold":
        return "held"
    if latest_deployment == "retire":
        return "retired"
    if latest_deployment == "extend":
        return "extended"
    if latest_verdict:
        return latest_verdict
    if latest_prospective_n >= n_min and n_min > 0:
        return "graded"
    if n_observations > 0:
        return "observing"
    return "registered"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ontology/test_rsi_models.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/ontology/rsi/ tests/ontology/test_rsi_models.py
git add nutmeg/ontology/rsi/__init__.py nutmeg/ontology/rsi/models.py tests/ontology/test_rsi_models.py
git commit -m "feat(rsi): 纯函数层——冻结哈希、falsifier 只读 CI 边界、状态投影"
```

---

### Task 2: 八张表 + 迁移 v29 + 权限种子

**Files:**
- Create: `nutmeg/ontology/repository/schema_rsi.py`
- Modify: `nutmeg/ontology/repository/migrations.py`（`MIGRATIONS` 元组末尾追加；新 `_apply_rsi_experiments` 放在 `MIGRATIONS = (` 之前）
- Test: `tests/ontology/test_rsi_migration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ontology/test_rsi_migration.py
from pathlib import Path

from sqlalchemy import inspect, select

from nutmeg.ontology.repository import schema
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations


def test_v29_creates_rsi_tables_and_seeds_constitutional_permissions(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "ontology.db")
    run_migrations(engine)
    assert migration_status(engine).current_version >= 29
    names = set(inspect(engine).get_table_names())
    for t in ("rsi_experiments", "rsi_duties", "rsi_duty_instances", "rsi_observations",
              "rsi_grades", "rsi_verdicts", "rsi_deployments", "rsi_amendments"):
        assert t in names, t
    with engine.connect() as c:
        rows = c.execute(select(schema.action_permissions.c.action_type,
                                schema.action_permissions.c.actor_role)
                         .where(schema.action_permissions.c.action_type.like("rsi_%"))).all()
    perms = {(a, r) for a, r in rows}
    # 宪法：人不能替 falsifier 说话；代码不能把东西推进票面
    assert ("rsi_record_verdict", "deterministic_system") in perms
    assert ("rsi_record_verdict", "judge_operator") not in perms
    assert ("rsi_approve_deployment", "judge_operator") in perms
    assert ("rsi_approve_deployment", "deterministic_system") not in perms
    assert ("rsi_register_experiment", "judge_operator") in perms
    assert ("rsi_register_experiment", "deterministic_system") not in perms
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ontology/test_rsi_migration.py -v`
Expected: FAIL — `assert 'rsi_experiments' in names`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/ontology/repository/schema_rsi.py
"""RSI 实验对象的表。全部只追加：没有任何一张表有可改写的 status 列，状态是投影。"""
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, PrimaryKeyConstraint, Table, Text

from nutmeg.ontology.repository.schema import metadata

rsi_experiments = Table(
    "rsi_experiments", metadata,
    Column("exp_id", Text, primary_key=True),
    Column("claim", Text, nullable=False),
    Column("mechanism", Text, nullable=False),
    Column("tier", Text, nullable=False),
    Column("layer", Text, nullable=False),
    Column("population", Text, nullable=False),
    Column("min_tier", Text, nullable=False),
    Column("window_json", Text, nullable=False),
    Column("falsifier_json", Text, nullable=False),
    Column("stop_rule", Text, nullable=False),
    Column("quota_slot", Integer, nullable=False),
    Column("buckets_json", Text, nullable=False),
    Column("rule_ids_json", Text, nullable=False),
    Column("replay_spec_json", Text, nullable=True),
    Column("dream_ref", Text, nullable=True),
    Column("variants_tried", Integer, nullable=True),
    Column("source_doc", Text, nullable=False),
    Column("registered_at", Text, nullable=False),      # 原登记日，不是摄入日
    Column("frozen_hash", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)

rsi_duties = Table(
    "rsi_duties", metadata,
    Column("duty_id", Text, primary_key=True),
    Column("exp_id", Text, ForeignKey("rsi_experiments.exp_id"), nullable=False, index=True),
    Column("recurrence", Text, nullable=False),          # per_day
    Column("scope", Text, nullable=False),               # day | match
    Column("deadline_rule", Text, nullable=False),       # earliest_kickoff | match_kickoff
    Column("instrument_json", Text, nullable=False),     # argv，{issue}/{day} 占位
    Column("artifact_glob", Text, nullable=False),
    Column("description", Text, nullable=False),
)

rsi_duty_instances = Table(
    "rsi_duty_instances", metadata,
    Column("duty_id", Text, ForeignKey("rsi_duties.duty_id"), nullable=False),
    Column("day", Text, nullable=False),
    Column("match_id", Text, nullable=False, server_default=""),
    Column("due_at", Text, nullable=False),
    Column("issue", Text, nullable=True),
    Column("fulfilled_at", Text, nullable=True),
    Column("artifact_path", Text, nullable=True),
    Column("artifact_hash", Text, nullable=True),
    PrimaryKeyConstraint("duty_id", "day", "match_id"),
)

rsi_observations = Table(
    "rsi_observations", metadata,
    Column("observation_id", Text, primary_key=True),
    Column("exp_id", Text, ForeignKey("rsi_experiments.exp_id"), nullable=False, index=True),
    Column("day", Text, nullable=False),
    Column("population_stratum", Text, nullable=False),
    Column("n_rows", Integer, nullable=False),
    Column("captured_at", Text, nullable=False),
    Column("prospective", Integer, nullable=False),
    Column("judgment_tier_hist_json", Text, nullable=False),
    Column("artifact_hash", Text, nullable=False),
)

rsi_grades = Table(
    "rsi_grades", metadata,
    Column("grade_id", Text, primary_key=True),
    Column("exp_id", Text, ForeignKey("rsi_experiments.exp_id"), nullable=False, index=True),
    Column("mode", Text, nullable=False),                # replay | prospective
    Column("stratum", Text, nullable=False),             # zucai | jczq | pooled
    Column("n_cum", Integer, nullable=False),
    Column("metric", Text, nullable=False),
    Column("metric_value_pp", Text, nullable=False),
    Column("ci_low_pp", Text, nullable=False),
    Column("ci_high_pp", Text, nullable=False),
    Column("distance_to_falsifier_pp", Text, nullable=False),
    Column("cost_axis_pp", Text, nullable=True),         # 独立轴，从不与 metric 合成
    Column("as_of_policy", Text, nullable=False),
    Column("computed_by", Text, nullable=False),
    Column("inputs_hash", Text, nullable=False),
    Column("graded_at", Text, nullable=False),
)

rsi_verdicts = Table(
    "rsi_verdicts", metadata,
    Column("verdict_id", Text, primary_key=True),
    Column("exp_id", Text, ForeignKey("rsi_experiments.exp_id"), nullable=False, index=True),
    Column("verdict", Text, nullable=False),
    Column("grade_id", Text, ForeignKey("rsi_grades.grade_id"), nullable=False),
    Column("criterion_snapshot_json", Text, nullable=False),
    Column("decided_at", Text, nullable=False),
)

rsi_deployments = Table(
    "rsi_deployments", metadata,
    Column("deployment_id", Text, primary_key=True),
    Column("exp_id", Text, ForeignKey("rsi_experiments.exp_id"), nullable=False, index=True),
    Column("decision", Text, nullable=False),
    Column("rule_id", Text, nullable=True),
    Column("reason", Text, nullable=False),
    Column("adjudication_ref", Text, nullable=True),
    Column("extend_to_exp_id", Text, nullable=True),
    Column("actor_id", Text, nullable=False),
    Column("decided_at", Text, nullable=False),
)

rsi_amendments = Table(
    "rsi_amendments", metadata,
    Column("amendment_id", Text, primary_key=True),
    Column("exp_id", Text, ForeignKey("rsi_experiments.exp_id"), nullable=False, index=True),
    Column("what", Text, nullable=False),
    Column("why", Text, nullable=False),
    Column("rule_check", Text, nullable=False),
    Column("mechanism_note", Text, nullable=True),
    Column("amended_at", Text, nullable=False),
)
```

在 `nutmeg/ontology/repository/migrations.py` 顶部 import 区加：

```python
from nutmeg.ontology.repository import schema_rsi
```

在 `MIGRATIONS: tuple[Migration, ...] = (` 之前加：

```python
# 宪法落权限表（不靠自律）：人不能替 falsifier 说话；代码不能把东西推进票面。
_RSI_PERMISSIONS = (
    ("rsi_register_experiment", "judge_operator"),
    ("rsi_schedule_duties", "judge_operator"),
    ("rsi_schedule_duties", "deterministic_system"),
    ("rsi_fulfill_duty", "judge_operator"),
    ("rsi_fulfill_duty", "deterministic_system"),
    ("rsi_grade_experiment", "judge_operator"),
    ("rsi_grade_experiment", "deterministic_system"),
    ("rsi_record_verdict", "deterministic_system"),
    ("rsi_approve_deployment", "judge_operator"),
    ("rsi_amend_experiment", "judge_operator"),
)


def _apply_rsi_experiments(connection: Connection) -> None:
    for table in (
        schema_rsi.rsi_experiments, schema_rsi.rsi_duties, schema_rsi.rsi_duty_instances,
        schema_rsi.rsi_observations, schema_rsi.rsi_grades, schema_rsi.rsi_verdicts,
        schema_rsi.rsi_deployments, schema_rsi.rsi_amendments,
    ):
        table.create(connection)
    connection.execute(
        insert(schema.action_permissions),
        [{"policy_version_id": "governance-v1", "action_type": a, "actor_role": r}
         for a, r in _RSI_PERMISSIONS],
    )
```

在 `MIGRATIONS` 元组最后一个 `Migration(version=28, …)` 之后追加：

```python
    Migration(
        version=29,
        name="rsi_experiments",
        fingerprint=(
            "experiments+duties+duty_instances+observations+grades+verdicts+"
            "deployments+amendments+verdict_system_only+deploy_human_only"
        ),
        apply=_apply_rsi_experiments,
    ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ontology/test_rsi_migration.py tests/ontology/test_migrations.py -v`
Expected: 全部 passed（已有的 drift 测试仍绿）

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/ontology/repository/schema_rsi.py nutmeg/ontology/repository/migrations.py tests/ontology/test_rsi_migration.py
git add nutmeg/ontology/repository/schema_rsi.py nutmeg/ontology/repository/migrations.py tests/ontology/test_rsi_migration.py
git commit -m "feat(rsi): 八张只追加表 + 迁移 v29 + 宪法权限种子"
```

---

### Task 3: RsiRepository + `uow.rsi`

**Files:**
- Create: `nutmeg/ontology/repository/rsi.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py`（在 `reliability` 属性之后加 `rsi` 属性）
- Test: `tests/ontology/test_rsi_repository.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ontology/test_rsi_repository.py
from pathlib import Path

from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import run_migrations
from nutmeg.ontology.repository.rsi import DutyInstanceRow, DutyRow, ExperimentRow, ObservationRow
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork


def _exp(exp_id="F2") -> ExperimentRow:
    return ExperimentRow(
        exp_id=exp_id, claim="c", mechanism="m", tier="observation", layer="judgment",
        population="zucai", min_tier="price_only",
        window={"issue_from": "26126", "issue_to": "26137"},
        falsifier={"metric": "home_resid_pp", "stratum": "zucai", "n_min": 140,
                   "bound": "ci_upper", "threshold_pp": 2.0, "direction": "lt_means_falsified"},
        stop_rule="n≥140", quota_slot=False, buckets=["a", "b"], rule_ids=[],
        replay_spec=None, dream_ref=None, variants_tried=None,
        source_doc="experiments/prereg-26126-F1c-F2.json",
        registered_at="2026-09-14", frozen_hash="h" * 64, created_at="2026-09-18T20:00:00+08:00")


def test_experiment_round_trip_and_duty_projection(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "o.db"); run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.rsi.insert_experiment(_exp())
        uow.rsi.insert_duty(DutyRow(duty_id="F2:f2-observation", exp_id="F2", recurrence="per_day",
                                    scope="day", deadline_rule="earliest_kickoff",
                                    instrument=["python", "scripts/zucai_f2_observe.py", "record",
                                                "--issue", "{issue}"],
                                    artifact_glob=".nutmeg-data/zucai/{issue}-f2-observation.json",
                                    description="F2 观察单"))
        uow.rsi.insert_duty_instance(DutyInstanceRow(
            duty_id="F2:f2-observation", day="2026-09-19", match_id="", issue="26129",
            due_at="2026-09-19T00:30:00+08:00", fulfilled_at=None, artifact_path=None,
            artifact_hash=None))
    with OntologyUnitOfWork(engine) as uow:
        got = uow.rsi.experiment("F2")
        assert got is not None and got.falsifier["n_min"] == 140 and got.buckets == ["a", "b"]
        assert [d.duty_id for d in uow.rsi.duties("F2")] == ["F2:f2-observation"]
        pend = uow.rsi.pending_duty_instances(day="2026-09-19", now="2026-09-18T23:00:00+08:00")
        assert [(p.duty_id, p.issue) for p in pend] == [("F2:f2-observation", "26129")]
        # 过了 due_at 仍未落 → gap（事实记录，不是罚分）
        gaps = uow.rsi.gaps("F2", now="2026-09-19T01:00:00+08:00")
        assert gaps == ["2026-09-19"]
        assert uow.rsi.experiment("nope") is None


def test_observation_insert_and_count(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "o.db"); run_migrations(engine)
    with OntologyUnitOfWork(engine) as uow:
        uow.rsi.insert_experiment(_exp())
        uow.rsi.insert_observation(ObservationRow(
            observation_id="F2:2026-09-19", exp_id="F2", day="2026-09-19",
            population_stratum="zucai", n_rows=10, captured_at="2026-09-18T19:22:02+08:00",
            prospective=True, judgment_tier_hist={"price_only": 10}, artifact_hash="a" * 64))
    with OntologyUnitOfWork(engine) as uow:
        assert uow.rsi.count_observations("F2") == 1
        assert uow.rsi.observation("F2:2026-09-19").n_rows == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ontology/test_rsi_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'nutmeg.ontology.repository.rsi'`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/ontology/repository/rsi.py
"""RSI 实验对象的仓库。只 insert + select；状态由 projection 函数从行里算。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from sqlalchemy import Connection, func, insert, select

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.repository import schema_rsi as sr


@dataclass(frozen=True, slots=True)
class ExperimentRow:
    exp_id: str
    claim: str
    mechanism: str
    tier: str
    layer: str
    population: str
    min_tier: str
    window: dict
    falsifier: dict
    stop_rule: str
    quota_slot: bool
    buckets: list
    rule_ids: list
    replay_spec: dict | None
    dream_ref: str | None
    variants_tried: int | None
    source_doc: str
    registered_at: str
    frozen_hash: str
    created_at: str


@dataclass(frozen=True, slots=True)
class DutyRow:
    duty_id: str
    exp_id: str
    recurrence: str
    scope: str
    deadline_rule: str
    instrument: list
    artifact_glob: str
    description: str


@dataclass(frozen=True, slots=True)
class DutyInstanceRow:
    duty_id: str
    day: str
    match_id: str
    issue: str | None
    due_at: str
    fulfilled_at: str | None
    artifact_path: str | None
    artifact_hash: str | None


@dataclass(frozen=True, slots=True)
class ObservationRow:
    observation_id: str
    exp_id: str
    day: str
    population_stratum: str
    n_rows: int
    captured_at: str
    prospective: bool
    judgment_tier_hist: dict
    artifact_hash: str


@dataclass(frozen=True, slots=True)
class GradeRow:
    grade_id: str
    exp_id: str
    mode: str
    stratum: str
    n_cum: int
    metric: str
    metric_value_pp: float
    ci_low_pp: float
    ci_high_pp: float
    distance_to_falsifier_pp: float
    cost_axis_pp: float | None
    as_of_policy: str
    computed_by: str
    inputs_hash: str
    graded_at: str


@dataclass(frozen=True, slots=True)
class VerdictRow:
    verdict_id: str
    exp_id: str
    verdict: str
    grade_id: str
    criterion_snapshot: dict
    decided_at: str


@dataclass(frozen=True, slots=True)
class DeploymentRow:
    deployment_id: str
    exp_id: str
    decision: str
    rule_id: str | None
    reason: str
    adjudication_ref: str | None
    extend_to_exp_id: str | None
    actor_id: str
    decided_at: str


@dataclass(frozen=True, slots=True)
class AmendmentRow:
    amendment_id: str
    exp_id: str
    what: str
    why: str
    rule_check: str
    mechanism_note: str | None
    amended_at: str


class RsiRepository:
    def __init__(self, connection: Connection) -> None:
        self._c = connection

    # ── experiments ──────────────────────────────────────────────
    def insert_experiment(self, row: ExperimentRow) -> None:
        v = asdict(row)
        v["window_json"] = canonical_json(v.pop("window"))
        v["falsifier_json"] = canonical_json(v.pop("falsifier"))
        v["buckets_json"] = canonical_json(v.pop("buckets"))
        v["rule_ids_json"] = canonical_json(v.pop("rule_ids"))
        rs = v.pop("replay_spec")
        v["replay_spec_json"] = None if rs is None else canonical_json(rs)
        v["quota_slot"] = 1 if v["quota_slot"] else 0
        self._c.execute(insert(sr.rsi_experiments).values(**v))

    def experiment(self, exp_id: str) -> ExperimentRow | None:
        r = self._c.execute(select(sr.rsi_experiments)
                            .where(sr.rsi_experiments.c.exp_id == exp_id)).mappings().first()
        return None if r is None else self._experiment_row(r)

    def experiments(self) -> list[ExperimentRow]:
        rows = self._c.execute(select(sr.rsi_experiments)
                               .order_by(sr.rsi_experiments.c.registered_at,
                                         sr.rsi_experiments.c.exp_id)).mappings().all()
        return [self._experiment_row(r) for r in rows]

    @staticmethod
    def _experiment_row(r) -> ExperimentRow:
        return ExperimentRow(
            exp_id=r["exp_id"], claim=r["claim"], mechanism=r["mechanism"], tier=r["tier"],
            layer=r["layer"], population=r["population"], min_tier=r["min_tier"],
            window=json.loads(r["window_json"]), falsifier=json.loads(r["falsifier_json"]),
            stop_rule=r["stop_rule"], quota_slot=bool(r["quota_slot"]),
            buckets=json.loads(r["buckets_json"]), rule_ids=json.loads(r["rule_ids_json"]),
            replay_spec=None if r["replay_spec_json"] is None else json.loads(r["replay_spec_json"]),
            dream_ref=r["dream_ref"], variants_tried=r["variants_tried"],
            source_doc=r["source_doc"], registered_at=r["registered_at"],
            frozen_hash=r["frozen_hash"], created_at=r["created_at"])

    # ── duties ───────────────────────────────────────────────────
    def insert_duty(self, row: DutyRow) -> None:
        v = asdict(row)
        v["instrument_json"] = canonical_json(v.pop("instrument"))
        self._c.execute(insert(sr.rsi_duties).values(**v))

    def duties(self, exp_id: str) -> list[DutyRow]:
        rows = self._c.execute(select(sr.rsi_duties).where(sr.rsi_duties.c.exp_id == exp_id)
                               .order_by(sr.rsi_duties.c.duty_id)).mappings().all()
        return [DutyRow(duty_id=r["duty_id"], exp_id=r["exp_id"], recurrence=r["recurrence"],
                        scope=r["scope"], deadline_rule=r["deadline_rule"],
                        instrument=json.loads(r["instrument_json"]),
                        artifact_glob=r["artifact_glob"], description=r["description"])
                for r in rows]

    def all_duties(self) -> list[DutyRow]:
        rows = self._c.execute(select(sr.rsi_duties.c.exp_id)).scalars().all()
        out: list[DutyRow] = []
        for exp_id in sorted(set(rows)):
            out.extend(self.duties(exp_id))
        return out

    def insert_duty_instance(self, row: DutyInstanceRow) -> None:
        self._c.execute(insert(sr.rsi_duty_instances).values(**asdict(row)))

    def duty_instance(self, duty_id: str, day: str, match_id: str = "") -> DutyInstanceRow | None:
        t = sr.rsi_duty_instances
        r = self._c.execute(select(t).where(t.c.duty_id == duty_id, t.c.day == day,
                                            t.c.match_id == match_id)).mappings().first()
        return None if r is None else DutyInstanceRow(**dict(r))

    def mark_duty_fulfilled(self, duty_id: str, day: str, match_id: str, *,
                            fulfilled_at: str, artifact_path: str, artifact_hash: str) -> None:
        t = sr.rsi_duty_instances
        self._c.execute(t.update().where(t.c.duty_id == duty_id, t.c.day == day,
                                         t.c.match_id == match_id)
                        .values(fulfilled_at=fulfilled_at, artifact_path=artifact_path,
                                artifact_hash=artifact_hash))

    def pending_duty_instances(self, *, day: str, now: str) -> list[DutyInstanceRow]:
        """当天还没落、且还没过期的义务。"""
        t = sr.rsi_duty_instances
        rows = self._c.execute(select(t).where(t.c.day == day, t.c.fulfilled_at.is_(None),
                                               t.c.due_at > now)
                               .order_by(t.c.due_at, t.c.duty_id)).mappings().all()
        return [DutyInstanceRow(**dict(r)) for r in rows]

    def gaps(self, exp_id: str, *, now: str) -> list[str]:
        """过了 due_at 仍未落的日期——事实记录，不是罚分。"""
        t, d = sr.rsi_duty_instances, sr.rsi_duties
        rows = self._c.execute(
            select(t.c.day).select_from(t.join(d, t.c.duty_id == d.c.duty_id))
            .where(d.c.exp_id == exp_id, t.c.fulfilled_at.is_(None), t.c.due_at <= now)
            .distinct().order_by(t.c.day)).scalars().all()
        return list(rows)

    # ── observations ─────────────────────────────────────────────
    def insert_observation(self, row: ObservationRow) -> None:
        v = asdict(row)
        v["judgment_tier_hist_json"] = canonical_json(v.pop("judgment_tier_hist"))
        v["prospective"] = 1 if v["prospective"] else 0
        self._c.execute(insert(sr.rsi_observations).values(**v))

    def observation(self, observation_id: str) -> ObservationRow | None:
        t = sr.rsi_observations
        r = self._c.execute(select(t).where(t.c.observation_id == observation_id)).mappings().first()
        if r is None:
            return None
        d = dict(r)
        d["judgment_tier_hist"] = json.loads(d.pop("judgment_tier_hist_json"))
        d["prospective"] = bool(d["prospective"])
        return ObservationRow(**d)

    def observations(self, exp_id: str) -> list[ObservationRow]:
        t = sr.rsi_observations
        ids = self._c.execute(select(t.c.observation_id).where(t.c.exp_id == exp_id)
                              .order_by(t.c.day)).scalars().all()
        return [self.observation(i) for i in ids]  # type: ignore[misc]

    def count_observations(self, exp_id: str) -> int:
        t = sr.rsi_observations
        return int(self._c.execute(select(func.count()).select_from(t)
                                   .where(t.c.exp_id == exp_id)).scalar_one())

    # ── grades / verdicts / deployments / amendments ─────────────
    def insert_grade(self, row: GradeRow) -> None:
        v = asdict(row)
        for k in ("metric_value_pp", "ci_low_pp", "ci_high_pp", "distance_to_falsifier_pp"):
            v[k] = repr(float(v[k]))
        v["cost_axis_pp"] = None if v["cost_axis_pp"] is None else repr(float(v["cost_axis_pp"]))
        self._c.execute(insert(sr.rsi_grades).values(**v))

    def grade(self, grade_id: str) -> GradeRow | None:
        t = sr.rsi_grades
        r = self._c.execute(select(t).where(t.c.grade_id == grade_id)).mappings().first()
        return None if r is None else self._grade_row(r)

    def latest_grade(self, exp_id: str, *, mode: str, stratum: str) -> GradeRow | None:
        t = sr.rsi_grades
        r = self._c.execute(select(t).where(t.c.exp_id == exp_id, t.c.mode == mode,
                                            t.c.stratum == stratum)
                            .order_by(t.c.graded_at.desc(), t.c.grade_id.desc())).mappings().first()
        return None if r is None else self._grade_row(r)

    @staticmethod
    def _grade_row(r) -> GradeRow:
        d = dict(r)
        for k in ("metric_value_pp", "ci_low_pp", "ci_high_pp", "distance_to_falsifier_pp"):
            d[k] = float(d[k])
        d["cost_axis_pp"] = None if d["cost_axis_pp"] is None else float(d["cost_axis_pp"])
        return GradeRow(**d)

    def insert_verdict(self, row: VerdictRow) -> None:
        v = asdict(row)
        v["criterion_snapshot_json"] = canonical_json(v.pop("criterion_snapshot"))
        self._c.execute(insert(sr.rsi_verdicts).values(**v))

    def latest_verdict(self, exp_id: str) -> VerdictRow | None:
        t = sr.rsi_verdicts
        r = self._c.execute(select(t).where(t.c.exp_id == exp_id)
                            .order_by(t.c.decided_at.desc(), t.c.verdict_id.desc())).mappings().first()
        if r is None:
            return None
        d = dict(r)
        d["criterion_snapshot"] = json.loads(d.pop("criterion_snapshot_json"))
        return VerdictRow(**d)

    def insert_deployment(self, row: DeploymentRow) -> None:
        self._c.execute(insert(sr.rsi_deployments).values(**asdict(row)))

    def latest_deployment(self, exp_id: str) -> DeploymentRow | None:
        t = sr.rsi_deployments
        r = self._c.execute(select(t).where(t.c.exp_id == exp_id)
                            .order_by(t.c.decided_at.desc(), t.c.deployment_id.desc())).mappings().first()
        return None if r is None else DeploymentRow(**dict(r))

    def insert_amendment(self, row: AmendmentRow) -> None:
        self._c.execute(insert(sr.rsi_amendments).values(**asdict(row)))

    def amendments(self, exp_id: str) -> list[AmendmentRow]:
        t = sr.rsi_amendments
        rows = self._c.execute(select(t).where(t.c.exp_id == exp_id)
                               .order_by(t.c.amended_at)).mappings().all()
        return [AmendmentRow(**dict(r)) for r in rows]
```

在 `nutmeg/ontology/repository/unit_of_work.py` 的 `reliability` 属性之后加：

```python
    @property
    def rsi(self) -> RsiRepository:
        from nutmeg.ontology.repository.rsi import RsiRepository

        return RsiRepository(self.connection)
```

并在文件顶部 `TYPE_CHECKING` 块（若有）或 import 区加 `from nutmeg.ontology.repository.rsi import RsiRepository`——若该文件其它仓库都是延迟 import 且只在方法体内引用，则仅在返回类型注解处用字符串 `"RsiRepository"`，与相邻属性保持一致。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ontology/test_rsi_repository.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/ontology/repository/rsi.py nutmeg/ontology/repository/unit_of_work.py tests/ontology/test_rsi_repository.py
git add nutmeg/ontology/repository/rsi.py nutmeg/ontology/repository/unit_of_work.py tests/ontology/test_rsi_repository.py
git commit -m "feat(rsi): RsiRepository（只 insert/select，gap 与 pending 是查询不是列）"
```

---

（Task 4–12 见续篇 `2026-09-18-rsi-experiment-persistence-part2.md`：Actions、prereg 加载、F2 结账、CLI、读侧、五份迁移、接线。）
