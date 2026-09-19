# 传统足彩专项（结构层）Implementation Plan · Part 2（Task 6–10）

> 续 Part 1（Task 1–5）。同一份 header/纪律适用。RSI 层的模式参考：`nutmeg/ontology/actions/rsi_actions.py`、`repository/rsi.py`、`schema_rsi.py`、`migrations.py`（最后一条 `version=29`）。

---

### Task 6: `zucai_capital_plan` —— 表、迁移 v30、仓库、Action（仅 judge_operator）

**Files:**
- Create: `nutmeg/ontology/repository/schema_capital.py`
- Modify: `nutmeg/ontology/repository/migrations.py`（import + `_CAPITAL_PERMISSIONS` + `_apply_capital_plans` + `Migration(version=30)`）
- Create: `nutmeg/ontology/repository/capital.py`
- Modify: `nutmeg/ontology/repository/unit_of_work.py`（`capital` 属性，与 `rsi` 同样写法）
- Create: `nutmeg/ontology/actions/capital_actions.py`
- Modify: `nutmeg/ontology/wiring.py`、`nutmeg/ontology/kernel.py`（挂 `capital_actions`，与 `rsi_actions` 同样写法）
- Create: `nutmeg/decision/capital_rules.py`（帽的纯校验，零 IO）
- Test: `tests/decision/test_capital_plan_rules.py`、`tests/ontology/test_capital_plan_actions.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/decision/test_capital_plan_rules.py
import pytest

from nutmeg.decision.capital_rules import CapError, validate_caps

def test_constitution_and_standing_override_caps():
    validate_caps({"renjiu": 1200, "shengfucai": 400, "total": 1600}, jczq_used_today=0)
    with pytest.raises(CapError, match="renjiu"):
        validate_caps({"renjiu": 1201, "shengfucai": 0, "total": 1201}, jczq_used_today=0)
    with pytest.raises(CapError, match="1,600"):
        validate_caps({"renjiu": 1000, "shengfucai": 700, "total": 1700}, jczq_used_today=0)
    with pytest.raises(CapError, match="日帽"):
        validate_caps({"renjiu": 1200, "shengfucai": 400, "total": 1600}, jczq_used_today=500)   # 1600+500>2000
    with pytest.raises(CapError, match="合计"):
        validate_caps({"renjiu": 800, "shengfucai": 400, "total": 1000}, jczq_used_today=0)
```

```python
# tests/ontology/test_capital_plan_actions.py
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nutmeg.ontology.actions.capital_actions import CapitalActions, CommitCapitalPlanRequest
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.connection import build_ontology_engine
from nutmeg.ontology.repository.migrations import migration_status, run_migrations
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

T0 = datetime(2026, 9, 19, 12, tzinfo=UTC)
HUMAN = dict(actor_id="op:jun", actor_role=ActorRole.JUDGE_OPERATOR)
SYSTEM = dict(actor_id="sys:plan", actor_role=ActorRole.DETERMINISTIC_SYSTEM)


def _rig(tmp_path: Path):
    engine = build_ontology_engine(tmp_path / "o.db"); run_migrations(engine)
    assert migration_status(engine).current_version >= 30
    return CapitalActions(ActionService(lambda: OntologyUnitOfWork(engine))), engine


def _req(key, *, cap_source="baseline", adjudication_ref=None, caps=None, role=HUMAN, supersedes=None):
    return CommitCapitalPlanRequest(
        issue="26130", day="2026-09-26", cap_source=cap_source, adjudication_ref=adjudication_ref,
        caps=caps or {"renjiu": 400, "shengfucai": 400, "total": 800}, jczq_used_today=0,
        frontier_refs={"renjiu": "h" * 64}, max_p_matrix=0.12, max_p_strict=0.03, chosen_p=0.10,
        chosen=[{"channel": "renjiu", "candidate_node": "chosen#0@renjiu", "legs_file_hash": "l" * 64,
                 "notes": 200, "stake_yuan": 400, "p_all": 0.10}],
        verdict_refs=[], supersedes=supersedes, idempotency_key=key, requested_at=T0, **role)


def test_commit_is_human_only_and_records_gate_cost(tmp_path):
    actions, engine = _rig(tmp_path)
    assert actions.commit_capital_plan(_req("c:sys", role=SYSTEM)).status is ActionStatus.REJECTED
    out = actions.commit_capital_plan(_req("c:h"))
    assert out.status is ActionStatus.COMMITTED
    with OntologyUnitOfWork(engine) as uow:
        plan = uow.capital.latest_plan("26130")
        assert plan.cap_source == "baseline" and abs(plan.gate_cost_pp - 9.0) < 1e-9
        assert plan.chosen[0]["slip_id"] is None


def test_override_requires_an_adjudication_and_caps_are_enforced(tmp_path):
    actions, _ = _rig(tmp_path)
    with pytest.raises(ValueError, match="adjudication"):
        actions.commit_capital_plan(_req("c:o", cap_source="override"))
    with pytest.raises(ValueError, match="renjiu"):
        actions.commit_capital_plan(_req("c:cap", cap_source="override", adjudication_ref="ADJ-1",
                                         caps={"renjiu": 1300, "shengfucai": 0, "total": 1300}))


def test_recommit_supersedes_and_strict_empty_gives_none_gate_cost(tmp_path):
    actions, engine = _rig(tmp_path)
    first = actions.commit_capital_plan(_req("c:1"))
    pid = first.result_refs[0].object_id
    req = _req("c:2", supersedes=pid)
    req2 = CommitCapitalPlanRequest(**{**req.__dict__, "max_p_strict": None})
    actions.commit_capital_plan(req2)
    with OntologyUnitOfWork(engine) as uow:
        plan = uow.capital.latest_plan("26130")
        assert plan.supersedes == pid and plan.gate_cost_pp is None
        assert len(uow.capital.plans("26130")) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/decision/test_capital_plan_rules.py tests/ontology/test_capital_plan_actions.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/capital_rules.py
"""帽的校验。常量来自宪法 §4 与用户常设行权（spec Z5）。零 IO。"""
from __future__ import annotations

DAY_CAP_YUAN = 2000            # 宪法：日总帽
ZUCAI_TOTAL_CAP_YUAN = 1600    # 宪法：足彩两票合计
RENJIU_CAP_YUAN = 1200         # 用户常设行权 2026-09-19（Adjudication 登记后引用）
SHENGFUCAI_BASELINE_YUAN = 400


class CapError(ValueError):
    pass


def validate_caps(caps: dict, *, jczq_used_today: int) -> None:
    r, s, t = int(caps.get("renjiu", 0)), int(caps.get("shengfucai", 0)), int(caps.get("total", 0))
    if r + s != t:
        raise CapError(f"合计 {t} ≠ renjiu {r} + shengfucai {s}")
    if r > RENJIU_CAP_YUAN:
        raise CapError(f"renjiu 帽 {r} > 常设行权 {RENJIU_CAP_YUAN}")
    if t > ZUCAI_TOTAL_CAP_YUAN:
        raise CapError(f"足彩合计 {t} > 宪法 {ZUCAI_TOTAL_CAP_YUAN:,}")
    if t + jczq_used_today > DAY_CAP_YUAN:
        raise CapError(f"日帽：足彩 {t} + 竞彩已登记 {jczq_used_today} > {DAY_CAP_YUAN}")
```

```python
# nutmeg/ontology/repository/schema_capital.py
"""当日足彩资金方案。只追加；重定案是新行 + supersedes。"""
from __future__ import annotations

from sqlalchemy import Column, Integer, Table, Text

from nutmeg.ontology.repository.schema import metadata

zucai_capital_plans = Table(
    "zucai_capital_plans", metadata,
    Column("plan_id", Text, primary_key=True),
    Column("issue", Text, nullable=False, index=True),
    Column("day", Text, nullable=False),
    Column("supersedes", Text, nullable=True),
    Column("cap_source", Text, nullable=False),          # baseline | override | brake
    Column("adjudication_ref", Text, nullable=True),
    Column("caps_json", Text, nullable=False),
    Column("jczq_used_today", Integer, nullable=False),
    Column("frontier_refs_json", Text, nullable=False),
    Column("max_p_matrix", Text, nullable=True),
    Column("max_p_strict", Text, nullable=True),
    Column("chosen_p", Text, nullable=True),
    Column("gate_cost_pp", Text, nullable=True),
    Column("chosen_json", Text, nullable=False),
    Column("verdict_refs_json", Text, nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("committed_at", Text, nullable=False),
)
```

`migrations.py`：import `from nutmeg.ontology.repository import schema_capital`；在 `MIGRATIONS = (` 之前加：

```python
_CAPITAL_PERMISSIONS = (("zucai_commit_capital_plan", "judge_operator"),)   # 这是钱：只许人


def _apply_capital_plans(connection: Connection) -> None:
    schema_capital.zucai_capital_plans.create(connection)
    connection.execute(insert(schema.action_permissions),
                       [{"policy_version_id": "governance-v1", "action_type": a, "actor_role": r}
                        for a, r in _CAPITAL_PERMISSIONS])
```
在 `Migration(version=29, …)` 之后加：
```python
    Migration(version=30, name="zucai_capital_plans",
              fingerprint="capital_plans+gate_cost+commit_human_only", apply=_apply_capital_plans),
```

```python
# nutmeg/ontology/repository/capital.py
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from sqlalchemy import Connection, insert, select

from nutmeg.ontology.actions.models import canonical_json
from nutmeg.ontology.repository import schema_capital as sc


@dataclass(frozen=True, slots=True)
class CapitalPlanRow:
    plan_id: str
    issue: str
    day: str
    supersedes: str | None
    cap_source: str
    adjudication_ref: str | None
    caps: dict
    jczq_used_today: int
    frontier_refs: dict
    max_p_matrix: float | None
    max_p_strict: float | None
    chosen_p: float | None
    gate_cost_pp: float | None
    chosen: list
    verdict_refs: list
    actor_id: str
    committed_at: str


_FLOATS = ("max_p_matrix", "max_p_strict", "chosen_p", "gate_cost_pp")


class CapitalRepository:
    def __init__(self, connection: Connection) -> None:
        self._c = connection

    def insert_plan(self, row: CapitalPlanRow) -> None:
        v = asdict(row)
        for k in ("caps", "frontier_refs", "chosen", "verdict_refs"):
            v[f"{k}_json"] = canonical_json(v.pop(k))
        for k in _FLOATS:
            v[k] = None if v[k] is None else repr(float(v[k]))
        self._c.execute(insert(sc.zucai_capital_plans).values(**v))

    def plans(self, issue: str) -> list[CapitalPlanRow]:
        t = sc.zucai_capital_plans
        rows = self._c.execute(select(t).where(t.c.issue == issue)
                               .order_by(t.c.committed_at, t.c.plan_id)).mappings().all()
        return [self._row(r) for r in rows]

    def latest_plan(self, issue: str) -> CapitalPlanRow | None:
        ps = self.plans(issue)
        return ps[-1] if ps else None

    def all_latest(self) -> list[CapitalPlanRow]:
        t = sc.zucai_capital_plans
        issues = self._c.execute(select(t.c.issue).distinct()).scalars().all()
        return [p for i in sorted(issues) if (p := self.latest_plan(i)) is not None]

    @staticmethod
    def _row(r) -> CapitalPlanRow:
        d = dict(r)
        for k in ("caps", "frontier_refs", "chosen", "verdict_refs"):
            d[k] = json.loads(d.pop(f"{k}_json"))
        for k in _FLOATS:
            d[k] = None if d[k] is None else float(d[k])
        return CapitalPlanRow(**d)
```

`unit_of_work.py`：与 `rsi` 属性同样写法加 `capital` 属性（TYPE_CHECKING import + 延迟 import + 返回 `CapitalRepository(self.connection)`）。

```python
# nutmeg/ontology/actions/capital_actions.py
"""当日足彩资金方案。一个 action_type：zucai_commit_capital_plan，权限表里只许 judge_operator。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from nutmeg.decision.capital_rules import validate_caps
from nutmeg.ontology.actions.models import ActionCommand, ActionOutcome, ActorRole, ObjectRef
from nutmeg.ontology.actions.service import ActionService
from nutmeg.ontology.repository.capital import CapitalPlanRow

_CAP_SOURCES = ("baseline", "override", "brake")


@dataclass(frozen=True, slots=True)
class CommitCapitalPlanRequest:
    issue: str
    day: str
    cap_source: str
    adjudication_ref: str | None
    caps: dict
    jczq_used_today: int
    frontier_refs: dict
    max_p_matrix: float | None
    max_p_strict: float | None
    chosen_p: float | None
    chosen: list
    verdict_refs: list
    supersedes: str | None
    actor_id: str
    actor_role: ActorRole
    idempotency_key: str
    requested_at: datetime


class CapitalActions:
    def __init__(self, action_service: ActionService) -> None:
        self._svc = action_service

    def commit_capital_plan(self, request: CommitCapitalPlanRequest) -> ActionOutcome:
        if request.cap_source not in _CAP_SOURCES:
            raise ValueError(f"cap_source 必须是 {_CAP_SOURCES}")
        if request.cap_source == "override" and not request.adjudication_ref:
            raise ValueError("override 必须带 adjudication_ref——口头行权不是账")
        validate_caps(request.caps, jczq_used_today=request.jczq_used_today)
        gate = (None if request.max_p_matrix is None or request.max_p_strict is None
                else (request.max_p_matrix - request.max_p_strict) * 100.0)
        command = ActionCommand.create(
            action_type="zucai_commit_capital_plan", actor_id=request.actor_id,
            actor_role=request.actor_role, idempotency_key=request.idempotency_key,
            payload={"issue": request.issue, "cap_source": request.cap_source,
                     "caps": dict(request.caps), "supersedes": request.supersedes},
            requested_at=request.requested_at)

        def handler(uow, _cmd) -> tuple[ObjectRef, ...]:
            if request.supersedes and not any(p.plan_id == request.supersedes
                                              for p in uow.capital.plans(request.issue)):
                raise ValueError(f"supersedes {request.supersedes} 不是本期已有方案")
            pid = f"zcp-{uuid.uuid4().hex[:12]}"
            chosen = [{**c, "slip_id": c.get("slip_id")} for c in request.chosen]
            uow.capital.insert_plan(CapitalPlanRow(
                plan_id=pid, issue=request.issue, day=request.day, supersedes=request.supersedes,
                cap_source=request.cap_source, adjudication_ref=request.adjudication_ref,
                caps=dict(request.caps), jczq_used_today=int(request.jczq_used_today),
                frontier_refs=dict(request.frontier_refs), max_p_matrix=request.max_p_matrix,
                max_p_strict=request.max_p_strict, chosen_p=request.chosen_p, gate_cost_pp=gate,
                chosen=chosen, verdict_refs=list(request.verdict_refs), actor_id=request.actor_id,
                committed_at=request.requested_at.isoformat(timespec="seconds")))
            return (ObjectRef("zucai_capital_plan", pid),)

        return self._svc.execute(command, handler)
```

`wiring.py` / `kernel.py`：与 `rsi_actions` 同样方式挂 `capital_actions = CapitalActions(action_service)`。

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/decision/test_capital_plan_rules.py tests/ontology/test_capital_plan_actions.py tests/ontology/test_migrations.py -v`，再 `uv run pytest tests/ontology/ -q -x`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/decision/capital_rules.py nutmeg/ontology/repository/schema_capital.py nutmeg/ontology/repository/capital.py nutmeg/ontology/repository/migrations.py nutmeg/ontology/repository/unit_of_work.py nutmeg/ontology/actions/capital_actions.py nutmeg/ontology/wiring.py nutmeg/ontology/kernel.py tests/decision/test_capital_plan_rules.py tests/ontology/test_capital_plan_actions.py
git add nutmeg/decision/capital_rules.py nutmeg/ontology/repository/schema_capital.py nutmeg/ontology/repository/capital.py nutmeg/ontology/repository/migrations.py nutmeg/ontology/repository/unit_of_work.py nutmeg/ontology/actions/capital_actions.py nutmeg/ontology/wiring.py nutmeg/ontology/kernel.py tests/decision/test_capital_plan_rules.py tests/ontology/test_capital_plan_actions.py
git commit -m "feat(plan): zucai_capital_plan 内核对象——迁移 v30，commit 只许人，帽校验入代码"
```

---

### Task 7: CLI `plan commit` / `plan status`（+ 日帽读竞彩已登记）

**Files:**
- Modify: `nutmeg/interfaces/cli/plan.py`
- Test: `tests/test_cli_plan.py`

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/test_cli_plan.py
def _slips(tmp_path, rows):
    (tmp_path / "betslips.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def test_commit_baseline_then_status_shows_unregistered_ticket(tmp_path):
    d = _data_dir(tmp_path); r = CliRunner()
    r.invoke(app, ["plan", "tiers", "--issue", "26130", "--data-dir", str(d)])
    r.invoke(app, ["plan", "frontier", "--issue", "26130", "--channel", "renjiu", "--cap", "400", "--data-dir", str(d)])
    r.invoke(app, ["plan", "choose", "--issue", "26130", "--channel", "renjiu", "--point", "0", "--data-dir", str(d)])
    _slips(d, [{"slip_id": "26130-JC-A", "channel": "jczq", "stake_yuan": 100, "issue": None}])
    out = r.invoke(app, ["plan", "commit", "--issue", "26130", "--cap-source", "baseline", "--data-dir", str(d)])
    assert out.exit_code == 0, out.output
    assert "gate_cost" in out.output and "竞彩已登记 ¥100" in out.output
    out = r.invoke(app, ["plan", "status", "--issue", "26130", "--data-dir", str(d)])
    assert out.exit_code == 0 and "没入账=没打" in out.output


def test_commit_override_without_adjudication_exits_one(tmp_path):
    d = _data_dir(tmp_path); r = CliRunner()
    r.invoke(app, ["plan", "tiers", "--issue", "26130", "--data-dir", str(d)])
    r.invoke(app, ["plan", "frontier", "--issue", "26130", "--channel", "renjiu", "--cap", "1200", "--data-dir", str(d)])
    r.invoke(app, ["plan", "choose", "--issue", "26130", "--channel", "renjiu", "--point", "0", "--data-dir", str(d)])
    out = r.invoke(app, ["plan", "commit", "--issue", "26130", "--cap-source", "override", "--data-dir", str(d)])
    assert out.exit_code == 1 and "adjudication" in out.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_plan.py -v -k "commit or status"`
Expected: FAIL — `No such command 'commit'`

- [ ] **Step 3: Write minimal implementation**

追加到 `nutmeg/interfaces/cli/plan.py`：

```python
import hashlib
import json
from datetime import datetime

from nutmeg.config.settings import AppSettings
from nutmeg.ontology.actions.models import ActionStatus, ActorRole
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

_CAP_SOURCE = typer.Option("baseline", "--cap-source", help="baseline | override | brake")
_ADJ = typer.Option(None, "--adjudication", help="override 必带")


def _kernel(data_dir: Path):
    k = _cli.build_ontology_kernel(AppSettings(data_dir=Path(data_dir).expanduser().resolve()))
    k.initialize()
    return k


def _jczq_used_today(data_dir: Path, day: str) -> int:
    p = Path(data_dir) / "betslips.jsonl"
    if not p.exists():
        return 0
    used = 0
    for line in p.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        placed = str(r.get("placed_at") or "")
        if r.get("channel") == "jczq" and (not placed or placed[:10] == day):
            used += int(r.get("stake_yuan") or 0)
    return used


def _registered_slips(data_dir: Path, issue: str) -> dict[str, dict]:
    p = Path(data_dir) / "betslips.jsonl"
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text("utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if str(r.get("issue") or "") == issue or str(r.get("slip_id", "")).startswith(issue):
                out[r["slip_id"]] = r
    return out


@plan_app.command("commit")
def commit(issue: str = _ISSUE, cap_source: str = _CAP_SOURCE, adjudication: str | None = _ADJ,
           data_dir: Path = _DATA_DIR) -> None:
    """B9 定案：写 zucai_capital_plan（只许人）。帽来源三态、三个 max P 并排、门代价。"""
    from nutmeg.decision.plan_flow import _day_of
    from nutmeg.ontology.actions.capital_actions import CommitCapitalPlanRequest

    z = Path(data_dir) / "zucai"
    day = _day_of(issue, data_dir)
    frontiers, chosen, caps = {}, [], {"renjiu": 0, "shengfucai": 0, "total": 0}
    for ch in ("renjiu", "shengfucai"):
        fp, lp = z / f"{issue}-frontier-{ch}.json", z / f"{issue}-legs-{ch}.json"
        if not (fp.exists() and lp.exists()):
            continue
        fr = json.loads(fp.read_text("utf-8"))
        frontiers[ch] = fr
        legs_raw = lp.read_bytes()
        legs = json.loads(legs_raw)["legs"]
        notes = 1
        for leg in legs.values():
            notes *= len(leg["faces"])
        p_all = 1.0
        for leg in legs.values():
            p_all *= sum(float(leg["fair"][{"3": "home", "1": "draw", "0": "away"}[c]]) for c in leg["faces"])
        chosen.append({"channel": ch, "candidate_node": f"chosen@{ch}", "legs_file_hash": hashlib.sha256(legs_raw).hexdigest(),
                       "notes": notes, "stake_yuan": notes * 2, "p_all": p_all, "slip_id": None})
        caps[ch] = fr["cap_yuan"]
    if not chosen:
        _fail("没有已 choose 的票面（先 plan frontier → plan choose）")
    caps["total"] = caps["renjiu"] + caps["shengfucai"]
    used = _jczq_used_today(data_dir, day)
    mp = [f["max_p"] for f in frontiers.values() if f["max_p"] is not None]
    sp = [f["strict_max_p"] for f in frontiers.values() if f.get("strict_max_p") is not None]
    k = _kernel(data_dir)
    try:
        out = k.capital_actions.commit_capital_plan(CommitCapitalPlanRequest(
            issue=issue, day=day, cap_source=cap_source, adjudication_ref=adjudication, caps=caps,
            jczq_used_today=used, frontier_refs={c: f["frontier_hash"] for c, f in frontiers.items()},
            max_p_matrix=max(mp) if mp else None, max_p_strict=max(sp) if sp else None,
            chosen_p=max(c["p_all"] for c in chosen), chosen=chosen, verdict_refs=[], supersedes=None,
            actor_id="operator:plan", actor_role=ActorRole.JUDGE_OPERATOR,
            idempotency_key=f"zcp:{issue}:{datetime.now().astimezone().isoformat(timespec='seconds')}",
            requested_at=datetime.now().astimezone()))
    except ValueError as exc:
        _fail(str(exc))
    if out.status is ActionStatus.REJECTED:
        _fail(f"权限拒绝：{out.error_detail}")
    with OntologyUnitOfWork(k.engine) as uow:
        plan = uow.capital.latest_plan(issue)
    gc = "None" if plan.gate_cost_pp is None else f"{plan.gate_cost_pp:+.2f}pp"
    typer.echo(f"{issue} 定案 {plan.plan_id} · {cap_source} · 足彩帽 ¥{caps['total']}（竞彩已登记 ¥{used}）"
               f" · max P 矩阵/strict/所选 = {plan.max_p_matrix}/{plan.max_p_strict}/{plan.chosen_p} · gate_cost {gc}")


@plan_app.command("status")
def status(issue: str = _ISSUE, data_dir: Path = _DATA_DIR) -> None:
    """对账：方案 / 每张所选票有没有入账（没入账=没打）/ 方案号缺失。"""
    k = _kernel(data_dir)
    with OntologyUnitOfWork(k.engine) as uow:
        plan = uow.capital.latest_plan(issue)
    if plan is None:
        _fail(f"{issue} 没有资金方案")
    slips = _registered_slips(data_dir, issue)
    typer.echo(f"{issue} {plan.plan_id} · {plan.cap_source} · 帽 {plan.caps} · gate_cost {plan.gate_cost_pp}")
    for c in plan.chosen:
        match = [s for s in slips.values() if s.get("channel") in (c["channel"], {"renjiu": "renjiu", "shengfucai": "shengfucai"}[c["channel"]])]
        if not match:
            typer.echo(f"  {c['channel']} {c['notes']}注 ¥{c['stake_yuan']}  ⚠️未入账（没入账=没打）")
        else:
            s = match[0]
            tag = "" if s.get("scheme_no") else " · ⚠️方案号待补"
            typer.echo(f"  {c['channel']} {c['notes']}注 ¥{c['stake_yuan']}  ✓ {s['slip_id']}{tag}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_plan.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/interfaces/cli/plan.py tests/test_cli_plan.py
git add nutmeg/interfaces/cli/plan.py tests/test_cli_plan.py
git commit -m "feat(cli): plan commit/status——定案入内核，日帽扣竞彩已登记，没入账=没打"
```

---

### Task 8: F4 适配器进 `rsi grade` + `plan commit` 后 `rsi fulfill --exp F4` + `rsi dream` CLI

**Files:**
- Modify: `nutmeg/decision/rsi_grading.py`（加 `grade_f4`、`c14_line_harness`）
- Modify: `nutmeg/interfaces/cli/rsi.py`（`grade` 分派 F4；新增 `dream` 命令）
- Modify: `nutmeg/interfaces/cli/plan.py`（commit 成功后调 `rsi_wiring.after_capital_plan`）
- Modify: `nutmeg/decision/rsi_wiring.py`（加 `after_capital_plan`）
- Create: `experiments/dream/b5c-c14-line.json`
- Test: `tests/decision/test_rsi_grading.py`、`tests/test_cli_rsi.py`、`tests/decision/test_rsi_wiring.py`

- [ ] **Step 1: Write the failing tests**

```python
# 追加到 tests/decision/test_rsi_grading.py
from nutmeg.decision.rsi_grading import c14_line_harness, grade_f4


def test_grade_f4_bootstraps_the_median_gate_cost_over_plans():
    plans = [{"issue": i, "gate_cost_pp": g} for i, g in
             (("26129", 24.5), ("26130", 8.0), ("26131", 12.0), ("26132", None), ("26133", 6.0))]
    g = grade_f4(plans)
    assert g.n_cum == 4 and g.stratum == "zucai" and g.as_of_policy == "per_issue_plan"
    assert g.ci_low_pp <= g.metric_value_pp <= g.ci_high_pp
    assert 6.0 <= g.metric_value_pp <= 24.5                                  # 中位数落在样本内


def test_c14_line_harness_only_scores_excluded_faces_under_the_line():
    rows = [{"fair": {"home": 0.7, "draw": 0.2, "away": 0.10}, "actual": "home"},
            {"fair": {"home": 0.7, "draw": 0.2, "away": 0.10}, "actual": "away"},
            {"fair": {"home": 0.5, "draw": 0.3, "away": 0.20}, "actual": "home"}]
    ci = c14_line_harness(rows, {"line": 0.15})
    assert ci.n == 2                                                           # 只有 away≤0.15 的两行
    ci2 = c14_line_harness(rows, {"line": 0.25})
    assert ci2.n == 3
```

```python
# 追加到 tests/decision/test_rsi_wiring.py
from nutmeg.decision.rsi_wiring import after_capital_plan


def test_after_capital_plan_fulfills_f4_with_the_plan_hash(tmp_path):
    calls = []
    after_capital_plan(exp="F4", issue="26130", day="2026-09-26", plan_id="zcp-abc", data_dir=tmp_path,
                       invoke=lambda argv: calls.append(argv) or (0, ""))
    assert calls[0][:4] == ["rsi", "fulfill", "--exp", "F4"] and "--artifact" in calls[0]
```

```python
# 追加到 tests/test_cli_rsi.py
def test_dream_ranks_variants_and_prints_variants_tried(tmp_path):
    corpus = tmp_path / "c.json"
    corpus.write_text(json.dumps([{"fair": {"home": 0.7, "draw": 0.2, "away": 0.10}, "actual": "home"}] * 20
                                 + [{"fair": {"home": 0.7, "draw": 0.2, "away": 0.10}, "actual": "away"}] * 5),
                      encoding="utf-8")
    fam = tmp_path / "fam.json"
    fam.write_text(json.dumps({"harness": "nutmeg.decision.rsi_grading:c14_line_harness",
                               "corpus": str(corpus), "variants": [{"line": 0.15}, {"line": 0.12}]}), encoding="utf-8")
    r = CliRunner().invoke(app, ["rsi", "dream", "--family", str(fam)])
    assert r.exit_code == 0 and "variants_tried=2" in r.output and "进不了判决" in r.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/decision/test_rsi_grading.py tests/decision/test_rsi_wiring.py tests/test_cli_rsi.py -v -k "f4 or c14 or capital_plan or dream"`
Expected: FAIL with `ImportError` / `No such command 'dream'`

- [ ] **Step 3: Write minimal implementation**

追加到 `nutmeg/decision/rsi_grading.py`：

```python
def grade_f4(plans: Sequence[dict], *, seed: int = 7, boots: int = 4000) -> GradeResult:
    """F4 门代价：每期 capital_plan 的 gate_cost_pp（strict 空解的期不计）→ 中位数 + bootstrap CI。"""
    xs = [float(p["gate_cost_pp"]) for p in plans if p.get("gate_cost_pp") is not None]
    if not xs:
        return GradeResult(stratum="zucai", n_cum=0, metric_value_pp=0.0, ci_low_pp=0.0, ci_high_pp=0.0,
                           cost_axis_pp=None, as_of_policy="per_issue_plan",
                           inputs_hash=inputs_hash(b""), computed_by="nutmeg.decision.rsi_grading.grade_f4")
    rng = random.Random(seed)
    med = statistics.median(xs)
    meds = sorted(statistics.median(rng.choice(xs) for _ in xs) for _ in range(boots))
    raw = json.dumps(sorted(xs)).encode("utf-8")
    return GradeResult(stratum="zucai", n_cum=len(xs), metric_value_pp=med,
                       ci_low_pp=meds[int(0.025 * boots)], ci_high_pp=meds[int(0.975 * boots) - 1],
                       cost_axis_pp=None, as_of_policy="per_issue_plan", inputs_hash=inputs_hash(raw),
                       computed_by="nutmeg.decision.rsi_grading.grade_f4")


def c14_line_harness(rows: Sequence[dict], variant: dict) -> ResidualCI:
    """dream 变体族「C14 省钱线」：被排面 fair ≤ line 的行，算该面 (实开 − fair)。只产候选。"""
    line = float(variant["line"])
    sub = []
    for r in rows:
        face = min(r["fair"], key=lambda f: r["fair"][f])
        if float(r["fair"][face]) <= line:
            sub.append({"fair": {face: r["fair"][face]}, "actual": r["actual"], "_face": face})
    if not sub:
        return ResidualCI(0, 0.0, 0.0, 0.0)
    # 统一成 bootstrap_residual_pp 的行形状：把被排面映射成同名 key
    resid_rows = [{"fair": {"x": s["fair"][s["_face"]]}, "actual": "x" if s["actual"] == s["_face"] else "y"}
                  for s in sub]
    return bootstrap_residual_pp(resid_rows, face="x")
```

`nutmeg/interfaces/cli/rsi.py` 的 `grade` 命令：把 `if exp != "F2": _fail(...)` 改成分派：

```python
    if exp == "F2":
        g = grade_f2_prospective(ledger_path=Path("experiments/prereg-26126-F2-ledger.json"),
                                 zucai_dir=data_dir / "zucai", primary_bucket=e.buckets[-1])
    elif exp == "F4":
        from nutmeg.decision.rsi_grading import grade_f4
        with OntologyUnitOfWork(k.engine) as uow:
            plans = [{"issue": p.issue, "gate_cost_pp": p.gate_cost_pp} for p in uow.capital.all_latest()]
        g = grade_f4(plans)
    else:
        _fail(f"{exp} 的结账适配器尚未接入（replay_spec.harness={e.replay_spec})")
```
（保留原来的 `LeakError` 捕获包住 F2 分支。）

新增 `dream` 命令：

```python
@rsi_app.command("dream")
def dream_cmd(family: Path = typer.Option(..., "--family", help="{harness, corpus, variants[]}"),
              register_winner: bool = typer.Option(False, "--register-winner",
                                                    help="把赢家写成 candidate 档登记原件草稿")) -> None:
    """在冻结语料上重放一族变体，只排序、只记 variants_tried；结果进不了判决。"""
    import importlib

    from nutmeg.decision.rsi_grading import dream

    fam = json.loads(family.read_text("utf-8"))
    mod, fn = fam["harness"].split(":")
    harness = getattr(importlib.import_module(mod), fn)
    corpus = json.loads(Path(fam["corpus"]).read_text("utf-8"))
    table = dream(corpus, harness, variants=fam["variants"])
    typer.echo(f"dream · variants_tried={table['variants_tried']} · {table['note']}")
    for r in table["ranked"]:
        typer.echo(f"  {r['variant']}  n={r['n']}  {r['value_pp']:+.2f}pp  CI[{r['ci_low_pp']:+.2f},{r['ci_high_pp']:+.2f}]")
    if register_winner and table["ranked"]:
        w = table["ranked"][0]
        draft = family.with_suffix(".winner.json")
        draft.write_text(json.dumps({"dream_ref": str(family), "variants_tried": table["variants_tried"],
                                     "winner": w["variant"], "tier": "candidate", "layer": "structural",
                                     "note": "草稿：补齐 claim/falsifier/window 后 rsi register"},
                                    ensure_ascii=False, indent=1), encoding="utf-8")
        typer.echo(f"  赢家草稿 → {draft}（仍需人补 claim/falsifier/window 再 rsi register）")
```

`nutmeg/decision/rsi_wiring.py` 加：

```python
def after_capital_plan(*, exp: str, issue: str, day: str, plan_id: str, data_dir: Path,
                       invoke: Invoker = _cli_invoke) -> None:
    """plan commit 落库后登记 F4 的当期观察：产物 = 方案 id 文本。"""
    art = Path(data_dir) / "zucai" / f"{issue}-capital-plan.txt"
    art.write_text(plan_id + "\n", encoding="utf-8")
    invoke(["rsi", "fulfill", "--exp", exp, "--duty", "capital-plan", "--day", day, "--issue", issue,
            "--artifact", str(art), "--n-rows", "1", "--data-dir", str(data_dir)])
```
`plan commit` 成功后加一行：`after_capital_plan(exp="F4", issue=issue, day=day, plan_id=plan.plan_id, data_dir=data_dir)`。

`experiments/registry/F4.json` 加 duty（否则 `rsi fulfill` 找不到实例）：
```json
"duties": [{"name": "capital-plan", "scope": "day", "deadline_rule": "earliest_kickoff",
            "instrument": ["uv", "run", "nutmeg", "plan", "commit", "--issue", "{issue}"],
            "artifact_glob": ".nutmeg-data/zucai/{issue}-capital-plan.txt",
            "description": "F4：当期资金方案落库即观察"}]
```
（F4 已在真库登记且原件冻结 duties 不在冻结字段里——用 `rsi amend --exp F4 --what "补 capital-plan duty"`，并在迁移脚本里对已登记实验补插 duty 行：在 `scripts/rsi_migrate_preregs.py` 加 `ensure_duties(exp_id, doc)`，对缺失的 duty 直接 `uow.rsi.insert_duty`。）

`experiments/dream/b5c-c14-line.json`：
```json
{"harness": "nutmeg.decision.rsi_grading:c14_line_harness",
 "corpus": "experiments/corpus-v2.json",
 "variants": [{"line": 0.12}, {"line": 0.15}, {"line": 0.18}],
 "note": "C14 省钱线的三个候选；只产候选，进不了判决；赢家要另立 exp 走前瞻窗"}
```
（corpus-v2 行若不是 `{fair, actual}` 形状，在 harness 前加一个 `rows = [normalize(r) for r in corpus]`——先 `python -c "import json;print(json.load(open('experiments/corpus-v2.json'))[0])"` 看真形状再写映射。）

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/decision/test_rsi_grading.py tests/decision/test_rsi_wiring.py tests/test_cli_rsi.py tests/test_cli_plan.py -v`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/decision/rsi_grading.py nutmeg/interfaces/cli/rsi.py nutmeg/interfaces/cli/plan.py nutmeg/decision/rsi_wiring.py scripts/rsi_migrate_preregs.py tests/decision/test_rsi_grading.py tests/decision/test_rsi_wiring.py tests/test_cli_rsi.py
git add nutmeg/decision/rsi_grading.py nutmeg/interfaces/cli/rsi.py nutmeg/interfaces/cli/plan.py nutmeg/decision/rsi_wiring.py scripts/rsi_migrate_preregs.py experiments/registry/F4.json experiments/dream/b5c-c14-line.json tests/decision/test_rsi_grading.py tests/decision/test_rsi_wiring.py tests/test_cli_rsi.py
git commit -m "feat(rsi): F4 适配器 + 定案即观察 + rsi dream CLI（第一个变体族：C14 省钱线）"
```

---

### Task 9: sopbar 三个按钮

**Files:**
- Modify: `nutmeg/decision/sop_tasks.py`（`STEPS` 加三步）
- Test: `tests/decision/test_sop_tasks.py`

- [ ] **Step 1: Write the failing test**

```python
# 追加到 tests/decision/test_sop_tasks.py
def test_plan_steps_are_registered_in_lane_order():
    ids = [s.step_id for s in STEPS]
    assert ids.index("B5c_plan_tiers") < ids.index("B5_plan_frontier") < ids.index("B6_audit")
    assert ids.index("B9_plan_commit") > ids.index("B6b_adjudicate_issue")
    p = SopParams(issue="26130", date="2026-09-26", zucai_dir=Path("z"), output_dir=Path("o"))
    assert step_by_id("B5c_plan_tiers").argv(p) == ["plan", "tiers", "--issue", "26130", "--data-dir", "o/.."]
    assert step_by_id("B5_plan_frontier").argv(p)[:4] == ["plan", "frontier", "--issue", "26130"]
    assert step_by_id("B9_plan_commit").argv(p)[:6] == ["plan", "commit", "--issue", "26130", "--cap-source", "baseline"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_sop_tasks.py -v -k plan_steps`
Expected: FAIL with `KeyError: '未登记的 SOP 步骤: B5c_plan_tiers'`

- [ ] **Step 3: Write minimal implementation**

在 `STEPS` 里 `B4b_candidates` 之后插入两步、`B6b_adjudicate_issue` 之后插入一步（`_dd = lambda p: str(p.output_dir / "..")`）：

```python
    SopStep("B5c_plan_tiers", "B5c 定级+风向",
            lambda p: ["plan", "tiers", "--issue", p.issue, "--data-dir", str(p.output_dir / "..")],
            lambda p: [_z(p, "tiers.json")]),
    SopStep("B5_plan_frontier", "B5 前沿(任九)",
            lambda p: ["plan", "frontier", "--issue", p.issue, "--channel", "renjiu",
                       "--data-dir", str(p.output_dir / "..")],
            lambda p: [_z(p, "frontier-renjiu.json")]),
    ...
    SopStep("B9_plan_commit", "B9 定案(基线帽)",
            lambda p: ["plan", "commit", "--issue", p.issue, "--cap-source", "baseline",
                       "--data-dir", str(p.output_dir / "..")],
            lambda p: [_z(p, "capital-plan.txt")]),
```
（override 定案需要裁决 id，不做按钮——走 CLI。）

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/decision/test_sop_tasks.py -v`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
uv run ruff check nutmeg/decision/sop_tasks.py tests/decision/test_sop_tasks.py
git add nutmeg/decision/sop_tasks.py tests/decision/test_sop_tasks.py
git commit -m "feat(sop): 任务栏加 B5c 定级 / B5 前沿 / B9 基线定案"
```

---

### Task 10: 26129 回填 + 常设行权裁决 + RUNBOOK

**Files:**
- Create: `scripts/plan_backfill_26129.py`
- Modify: `docs/sop/RUNBOOK.md`（B5/B9 行）
- Test: `tests/test_plan_backfill_26129.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_backfill_26129.py
import json
from pathlib import Path

from nutmeg.decision.workbench import read_events


def test_backfill_writes_tree_plan_and_two_adjudications(tmp_path, monkeypatch):
    import scripts.plan_backfill_26129 as bf

    d = tmp_path; (d / "zucai").mkdir(); (d / "jczq").mkdir()
    (d / "zucai" / "26129-issue.json").write_text(json.dumps({"issue_id": "26129", "matches": [
        {"match_no": 1, "kickoff_bj": "2026-09-19 00:30"}]}), encoding="utf-8")
    (d / "betslips.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"slip_id": "26129-RJ9", "channel": "renjiu", "issue": "26129", "notes": 384, "stake_yuan": 768,
         "hit_probability": 0.161188, "placed_at": "2026-09-18T20:00:00+08:00", "scheme_no": None},
        {"slip_id": "26129-SFC", "channel": "shengfucai", "issue": "26129", "notes": 128, "stake_yuan": 256,
         "hit_probability": 0.001271, "placed_at": "2026-09-18T20:00:00+08:00", "scheme_no": None},
        {"slip_id": "26129-JC-A4", "channel": "jczq", "stake_yuan": 40, "placed_at": "2026-09-18T20:00:00+08:00"},
        {"slip_id": "26129-JC-B3", "channel": "jczq", "stake_yuan": 100, "placed_at": "2026-09-18T20:00:00+08:00"},
    ]) + "\n", encoding="utf-8")
    report = bf.backfill(data_dir=d)
    versions = [e["payload"]["version"] for e in read_events(d / "jczq", "2026-09-19") if e["kind"] == "candidate"]
    assert versions[:4] == ["SFC-B", "SFC-C", "SFC-D", "SFC-E"]
    parents = {e["payload"]["version"]: e["payload"]["parent_version"]
               for e in read_events(d / "jczq", "2026-09-19") if e["kind"] == "candidate"}
    assert parents["SFC-C"] == "SFC-B" and parents["SFC-E"] == "SFC-D" and parents["SFC-B"] is None
    assert report["plan"]["cap_source"] == "override" and report["plan"]["caps"]["renjiu"] == 1000
    assert report["adjudications"] == ["override-renjiu-1000-26129", "standing-renjiu-1200"]
    assert report["plan"]["chosen"][0]["slip_id"] == "26129-RJ9"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plan_backfill_26129.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.plan_backfill_26129'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/plan_backfill_26129.py
"""26129 回填：把聊天里的 SFC-B→C→D→E 与 RJ9 终版登记进候选树，写第一条 zucai_capital_plan，
补登两条 Adjudication（26129 的「选9 ≤¥1,000」行权；常设「任九 ≤¥1,200」）。只增不改，可重跑。

⚠️中间版本的 faces 当时只在聊天里，这里如实留空并注明；终版 faces 从 betslips 读。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from nutmeg.config.settings import AppSettings
from nutmeg.decision.workbench import append_candidate, read_events
from nutmeg.ontology import build_ontology_kernel
from nutmeg.ontology.actions.capital_actions import CommitCapitalPlanRequest
from nutmeg.ontology.actions.models import ActorRole
from nutmeg.ontology.actions.workflow_actions import RecordAdjudicationRequest
from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

HUMAN = dict(actor_id="operator:plan-backfill", actor_role=ActorRole.JUDGE_OPERATOR)
DAY = "2026-09-19"
ISSUE = "26129"
# (version, parent, notes, stake, p_all, verdict, reason) —— 来自 2026-09-18 的对话记录
VERSIONS = [
    ("SFC-B", None, 128, 256, 0.0038, "rejected", "三处 C2（旗面没盖住）"),
    ("SFC-C", "SFC-B", 128, 256, None, "rejected", "平局太少（用户指出受前一日票面影响）"),
    ("SFC-D", "SFC-C", 128, 256, None, "rejected", "全选 3 无必要（用户指出集中度）"),
    ("SFC-E", "SFC-D", 128, 256, 0.001271, "chosen", "综合裁定终版；用户保留场8 平负（有意翻面）"),
    ("RJ9-final", None, 384, 768, 0.161188, "chosen", "9/10/11/12 两双两单裁定；14/13 防平裁定"),
]


def _slips(data_dir: Path) -> dict:
    out = {}
    for line in (data_dir / "betslips.jsonl").read_text("utf-8").splitlines():
        if line.strip():
            r = json.loads(line); out[r["slip_id"]] = r
    return out


def backfill(*, data_dir: Path) -> dict:
    kernel = build_ontology_kernel(AppSettings(data_dir=Path(data_dir).resolve())); kernel.initialize()
    now = datetime.now().astimezone()
    existing = {e["payload"]["version"] for e in read_events(data_dir / "jczq", DAY) if e.get("kind") == "candidate"}
    for version, parent, notes, stake, p, verdict, reason in VERSIONS:
        if version in existing:
            continue
        append_candidate(data_dir / "jczq", DAY, obj_id=f"ticket:{ISSUE}", version=version, parent_version=parent,
                         faces={}, notes=notes, stake_yuan=stake, p_all=p, verdict=verdict,
                         reason=reason + "（faces 当时只在聊天里，未记录）")
    adj_ids = []
    for adj_id, reason, alt in (
        ("override-renjiu-1000-26129", "用户 2026-09-18 裁定：选9 成本控制在 ¥1,000 以内（覆盖 ¥400 基线与刹车）",
         {"cap_yuan": 1000, "channel": "renjiu", "issue": ISSUE}),
        ("standing-renjiu-1200", "用户 2026-09-19 常设行权：任九帽 ≤¥1,200（spec Z5）",
         {"cap_yuan": 1200, "channel": "renjiu", "standing": True}),
    ):
        kernel.workflow.record_adjudication(RecordAdjudicationRequest(
            subject_type="capital_cap", subject_id=adj_id, decision="override", reason=reason,
            evidence_rejected=[], alternative=alt, supersedes_adjudication_id=None,
            idempotency_key=f"adj:{adj_id}", requested_at=now, **HUMAN))
        adj_ids.append(adj_id)
    slips = _slips(data_dir)
    jczq_used = sum(int(s.get("stake_yuan") or 0) for s in slips.values() if s.get("channel") == "jczq")
    chosen = [{"channel": "renjiu", "candidate_node": "RJ9-final", "legs_file_hash": "backfill", "notes": 384,
               "stake_yuan": 768, "p_all": 0.161188, "slip_id": "26129-RJ9"},
              {"channel": "shengfucai", "candidate_node": "SFC-E", "legs_file_hash": "backfill", "notes": 128,
               "stake_yuan": 256, "p_all": 0.001271, "slip_id": "26129-SFC"}]
    with OntologyUnitOfWork(kernel.engine) as uow:
        already = uow.capital.latest_plan(ISSUE)
    if already is None:
        kernel.capital_actions.commit_capital_plan(CommitCapitalPlanRequest(
            issue=ISSUE, day=DAY, cap_source="override", adjudication_ref="override-renjiu-1000-26129",
            caps={"renjiu": 1000, "shengfucai": 500, "total": 1500}, jczq_used_today=jczq_used,
            frontier_refs={}, max_p_matrix=0.1609, max_p_strict=None, chosen_p=0.161188, chosen=chosen,
            verdict_refs=["override-renjiu-1000-26129"], supersedes=None,
            idempotency_key=f"zcp:{ISSUE}:backfill", requested_at=now, **HUMAN))
    with OntologyUnitOfWork(kernel.engine) as uow:
        plan = uow.capital.latest_plan(ISSUE)
    return {"plan": {"plan_id": plan.plan_id, "cap_source": plan.cap_source, "caps": plan.caps,
                     "chosen": plan.chosen, "gate_cost_pp": plan.gate_cost_pp},
            "adjudications": adj_ids}


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--data-dir", type=Path, default=Path(".nutmeg-data"))
    a = ap.parse_args()
    print(json.dumps(backfill(data_dir=a.data_dir), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
```
（`kernel.workflow.record_adjudication` 的权限若只对 `judge_operator` 开放则 HUMAN 即可；若 REJECTED，`grep -n "record_adjudication" nutmeg/ontology/repository/migrations.py` 看权限行。26129 的 `max_p_matrix=0.1609` 是 DRAFT-A 的 P，`max_p_strict=None`（当时 ¥1000 帽严格空间空解，机器已确认）→ `gate_cost_pp=None`，F4 对该期不计——如实。）

RUNBOOK：B5 行开头加「**先 `plan tiers` → `plan frontier` → `plan choose`（2026-09-19 起，票面只从前沿上来）**」；B9 行开头加「**`plan commit --cap-source baseline|override --adjudication …`（override 必带裁决；日帽扣竞彩已登记）；`plan status` 对账**」。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_plan_backfill_26129.py -v`
Expected: 1 passed

- [ ] **Step 5: 对真库跑回填并核数**

```bash
cp -r .nutmeg-data/ontology /private/tmp/claude-501/ontology-backup-before-plan-backfill
uv run python scripts/plan_backfill_26129.py
uv run nutmeg plan status --issue 26129
uv run nutmeg rsi status
```
Expected：`plan status` 显示 26129 override 方案、RJ9/SFC 两票 ✓ 已入账（方案号待补）；`rsi status` 里 F4 **仍 n=0**（26129 的 gate_cost 为 None，如实不计）——第一条 F4 观察要等 26130。

- [ ] **Step 6: Commit**

```bash
uv run ruff check scripts/plan_backfill_26129.py tests/test_plan_backfill_26129.py
git add scripts/plan_backfill_26129.py tests/test_plan_backfill_26129.py docs/sop/RUNBOOK.md
git commit -m "feat(plan): 26129 回填——候选树 SFC-B→E、首条资金方案、两条行权裁决；RUNBOOK B5/B9 入册"
```

---

## Self-review（对照 spec）

| spec | 任务 |
|---|---|
| §4.1 face_status 四条规则 | Task 1 |
| §4.2 定级矩阵 + 面规则 + 常量非参数 | Task 2 |
| §4.3 风向 | Task 2 |
| §4.4 枚举器 / 两模式 / hash / 第三序 key / 空前沿 | Task 3 |
| §4.5 资金方案字段与校验 | Task 6、7 |
| §4.6 候选树自动生长 | Task 4 |
| §5 命令面 / 权限 / 拒绝无 face_status / sopbar | Task 5、7、9 |
| §6 F4 适配 / 定案即观察 / dream CLI | Task 8；F6/F7 只登记不在本计划（需前瞻产物） |
| §7 迁移（26129 树 / 方案 / 两条裁决） | Task 10 |
| §8 测试 | 分布各任务；「T3 场无收窄」「灰带不可」「strict 空解 None」「override 无裁决拒」「system 调 commit 拒」「没入账=没打」均有 |
| §9 出口 | Task 10 Step 5 + 26130 实战 |

**类型一致性**：`enumerate_frontier` 返回体字段（`frontier_hash/max_p/points[k,faces,notes,stake_yuan,p_all,shape,narrowings]`）在 Task 3/4/5/7 一致；`CommitCapitalPlanRequest` 字段在 Task 6/7/10 一致；`after_capital_plan` 签名在 Task 8 定义与调用一致；候选树 `version/parent_version` 命名（`tiers@…`/`frontier#k@¥cap`/`chosen#k@ch`/`edit#n@ch`）在 Task 4 与 spec §4.6 一致。

**有意留白**：F6/F7 的登记原件与 harness——它们的样本要等 26130 起的候选树与赛果；`plan commit` 的 `chosen_p` 取各渠道最大值而非联合概率（两票独立，联合无意义）；`c14_line_harness` 依赖 corpus-v2 行形状，Task 8 要求先看真形状再写映射。
