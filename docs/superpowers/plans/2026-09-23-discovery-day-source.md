# Discovery Day Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Discovery 试点能从当天决策泳道的三份文件（`jczq-legs-base.json`、`reads.json`、`sporttery_markets.json`）冻结一个世界输入并录制影子世界，不再依赖 operator_v2 内核表。

**Architecture:** 新模块 `nutmeg/discovery/day_inputs.py` 把三份文件映射成既有 `CandidateGenerationInput` + `StructuralInputSnapshot`（复用 `freeze_structural_input`，manifest 规则不变）；`online_recorder` 增加 `source_kind="day"` 分支（目录指纹 + 文件重读复核）；CLI `shadow-run` 加 `--source-day`。生成器、审计器、回放、锦标赛零改动。

**Tech Stack:** Python 3.12、pytest；既有 `nutmeg.product.operator_candidates`（`CandidateGenerationInput/OfferCandidateInput/FaceBundleOption/CandidateStructureTemplate`）与 `operator_workers._CandidateAuditOffer`、`_CANDIDATE_AUDIT_POLICY_VERSION`。

**Spec:** `docs/superpowers/specs/2026-09-23-discovery-day-source-design.md`。

---

### Task 1: `day_inputs.read_structural_input_from_day`

**Files:**
- Create: `nutmeg/discovery/day_inputs.py`
- Test: `tests/discovery/test_day_inputs.py`

先读：`nutmeg/discovery/online_inputs.py`（`freeze_structural_input` 的参数与校验：需要 ≥1 `forecast` 与 ≥1 `prescription` 引用，quote 引用必须覆盖 offers 的 `quote_ids_by_face`，所有 `captured_at` 带时区且 ≤ cutoff）、`nutmeg/product/operator_candidates.py`（四个输入 dataclass 的 `__post_init__` 约束，以及**面码常量**——生成器用的是 `3/1/0` 还是 `home/draw/away`，以它为准）、`nutmeg/product/operator_workers.py` 的 `_CandidateAuditOffer` 与 `_CANDIDATE_AUDIT_POLICY_VERSION`。

- [ ] **Step 1: Write the failing test**

```python
# tests/discovery/test_day_inputs.py
import json
from pathlib import Path

import pytest

from nutmeg.discovery.day_inputs import (
    day_fingerprint,
    day_source_identity,
    read_structural_input_from_day,
)

DAY = "2026-09-23"


def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _day(tmp_path: Path, *, n: int = 3) -> Path:
    jczq = tmp_path / "jczq"
    d = jczq / "daily" / DAY
    codes = [f"周三{i:03d}" for i in range(1, n + 1)]
    legs = {}
    reads = []
    subs = []
    for i, code in enumerate(codes, start=1):
        legs[code] = {
            "match_id": f"m-{i}", "name": f"A{i}-B{i}", "kickoff_bj": f"{DAY}T19:30:00+08:00",
            "fair": {"home": 0.5, "draw": 0.28, "away": 0.22}, "faces": "31",
            "stance": {"face": "3", "structure": "double", "cover": "1", "faces": "31"},
            "anchor_integrity": "pass", "precedents": [["3", "2026-01 某场 2-1", "alive"]],
        }
        reads.append({
            "read_id": f"R-ai-jczq-{DAY}-{code}-had-1000", "match_id": f"m-{i}", "status": "draft",
            "made_at": f"{DAY}T10:00:00+08:00",
            "prior": {"home": 0.5, "draw": 0.28, "away": 0.22},
            "belief": {"home": 0.56, "draw": 0.26, "away": 0.18},
        })
        subs.append({"matchNumStr": code, "matchId": 1000 + i, "had": {
            "h": "1.95", "d": "2.90", "a": "3.68", "updateDate": DAY, "updateTime": "08:00:00"}})
    _write(d / "jczq-legs-base.json", {"day": DAY, "legs": legs})
    _write(d / "reads.json", reads)
    _write(d / "sporttery_markets.json", {"matchInfoList": [{"businessDate": DAY, "subMatchList": subs}]})
    return jczq


def test_snapshot_maps_board_reads_and_quotes(tmp_path: Path):
    jczq = _day(tmp_path)
    snap = read_structural_input_from_day(jczq, DAY, cutoff_at=f"{DAY}T12:00:00+08:00")
    ci = snap.candidate_input
    assert ci.lane == "jczq" and ci.ticket_kind == "jczq_pass"
    assert len(ci.offers) == 3 and ci.offers[0].official_match_no == "周三001"
    assert ci.offers[0].booked_decimal_odds_by_face and ci.offers[0].quote_ids_by_face
    assert {b.bundle_code for b in ci.offers[0].allowed_face_bundles} >= {"31"}
    assert snap.template_ids == ("pass-2-1", "pass-3-1")   # 3 场 → N=2..3
    kinds = {r.kind for r in snap.references}
    assert kinds == {"forecast", "prescription", "quote"}
    assert sum(1 for r in snap.references if r.kind == "forecast") == 3
    assert snap.business_date == DAY and snap.slate_revision_id.startswith(f"day:{DAY}:")
    assert snap.source_identity == day_source_identity(jczq, DAY)
    assert len(snap.audit_offers) == 3 and snap.audit_offers[0].anchor_integrity == "pass"
    assert snap.manifest_hash and len(snap.task_snapshot_hash) == 64


def test_templates_are_capped_and_matches_without_reads_are_skipped(tmp_path: Path):
    jczq = _day(tmp_path, n=7)
    reads = json.loads((jczq / "daily" / DAY / "reads.json").read_text(encoding="utf-8"))
    (jczq / "daily" / DAY / "reads.json").write_text(json.dumps(reads[:5]), encoding="utf-8")
    snap = read_structural_input_from_day(jczq, DAY, cutoff_at=f"{DAY}T12:00:00+08:00", max_templates=4)
    assert len(snap.candidate_input.offers) == 5
    assert snap.template_ids == ("pass-2-1", "pass-3-1", "pass-4-1", "pass-5-1")


def test_reference_after_cutoff_is_rejected(tmp_path: Path):
    jczq = _day(tmp_path)
    with pytest.raises(ValueError, match="cutoff"):
        read_structural_input_from_day(jczq, DAY, cutoff_at=f"{DAY}T07:00:00+08:00")


def test_fingerprint_changes_when_any_source_file_changes(tmp_path: Path):
    jczq = _day(tmp_path)
    before = day_fingerprint(jczq / "daily" / DAY)
    p = jczq / "daily" / DAY / "reads.json"
    p.write_text(p.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert day_fingerprint(jczq / "daily" / DAY) != before
```

- [ ] **Step 2: Run** `uv run pytest tests/discovery/test_day_inputs.py -q` → `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/discovery/day_inputs.py
"""Discovery 世界输入 · day 源：从当天决策泳道三份文件冻结 StructuralInputSnapshot（设计 2026-09-23-discovery-day-source）。

不读内核、不写任何文件；面码以生成器口径为准。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.discovery.online_inputs import StructuralInputSnapshot, freeze_structural_input
from nutmeg.product.operator_candidates import (
    CandidateGenerationInput,
    CandidateStructureTemplate,
    FaceBundleOption,
    OfferCandidateInput,
)
from nutmeg.product.operator_workers import _CANDIDATE_AUDIT_POLICY_VERSION, _CandidateAuditOffer

BJ = timezone(timedelta(hours=8))
FACE_CODE = {"home": "3", "draw": "1", "away": "0"}   # 若生成器用 home/draw/away，把映射改成恒等
CAPITAL_CAP_MINOR = 200_000   # ¥2,000 日帽
UNIT_STAKE_MINOR = 200        # ¥2 单注
MAX_TICKET_COUNT = 20
MAX_EXHAUSTIVE = 50_000
SOURCE_FILES = ("jczq-legs-base.json", "reads.json", "sporttery_markets.json")


def day_source_identity(jczq_dir: Path | str, day: str) -> str:
    return f"day:{(Path(jczq_dir) / 'daily' / day).resolve()}"


def day_fingerprint(day_dir: Path) -> str:
    h = hashlib.sha256()
    for name in SOURCE_FILES:
        p = Path(day_dir) / name
        h.update(name.encode()); h.update(p.read_bytes() if p.exists() else b"<missing>")
    return h.hexdigest()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dec(x: float) -> str:
    return f"{float(x):.6f}"


def _had_quotes(markets: dict) -> dict[str, dict]:
    out = {}
    for block in markets.get("matchInfoList") or []:
        for sub in block.get("subMatchList") or []:
            had = sub.get("had") or {}
            if sub.get("matchNumStr") and had.get("h"):
                out[sub["matchNumStr"]] = had
    return out


def read_structural_input_from_day(
    jczq_dir: Path | str, day: str, *, cutoff_at: str, max_templates: int = 4,
) -> StructuralInputSnapshot:
    day_dir = Path(jczq_dir) / "daily" / day
    board_bytes = (day_dir / "jczq-legs-base.json").read_bytes()
    reads_bytes = (day_dir / "reads.json").read_bytes()
    markets_bytes = (day_dir / "sporttery_markets.json").read_bytes()
    legs = json.loads(board_bytes)["legs"]
    reads = {r["match_id"]: r for r in json.loads(reads_bytes) if isinstance(r, dict)}
    quotes = _had_quotes(json.loads(markets_bytes))
    board_captured = datetime.fromtimestamp((day_dir / "jczq-legs-base.json").stat().st_mtime, tz=BJ)

    offers, audits, refs = [], [], []
    for code, leg in sorted(legs.items()):
        read = reads.get(leg.get("match_id"))
        had = quotes.get(code)
        if not read or not had:
            continue
        faces = str(leg.get("faces") or "310")
        bundles = [FaceBundleOption(bundle_code=faces, face_codes=tuple(faces))]
        bundles += [FaceBundleOption(bundle_code=f, face_codes=(f,)) for f in faces if len(faces) > 1]
        belief = tuple((FACE_CODE[k], _dec(read["belief"][k])) for k in ("home", "draw", "away"))
        prior = tuple((FACE_CODE[k], _dec(read["prior"][k])) for k in ("home", "draw", "away"))
        quote_ids = tuple((FACE_CODE[k], f"sporttery:{day}:{code}:had:{FACE_CODE[k]}") for k in ("home", "draw", "away"))
        odds = tuple((FACE_CODE[k], str(had[c])) for k, c in (("home", "h"), ("draw", "d"), ("away", "a")))
        offers.append(OfferCandidateInput(
            official_match_no=code, official_offer_revision_id=f"{day}:{code}:had",
            match_id=str(leg["match_id"]), market_definition_id="had", probabilities=belief,
            allowed_face_bundles=tuple(bundles), omission_allowed=True,
            quote_ids_by_face=quote_ids, booked_decimal_odds_by_face=odds,
        ))
        audits.append(_CandidateAuditOffer(
            official_match_no=code, market_definition_id="had", belief=belief, prior=prior,
            prescribed_face_bundles=(frozenset(faces),), rule_ids=(),
            anchor_integrity=str(leg.get("anchor_integrity") or "unknown"),
            face_precedents=tuple(tuple(map(str, p))[:3] for p in leg.get("precedents") or [] if len(p) >= 3),
        ))
        refs.append({"kind": "forecast", "id": str(read["read_id"]),
                     "source_revision": f"{read.get('status', 'draft')}:{_sha(json.dumps(read, sort_keys=True).encode())}",
                     "captured_at": str(read["made_at"])})
        captured = f"{had.get('updateDate', day)}T{had.get('updateTime', '00:00:00')}+08:00"
        for _face, qid in quote_ids:
            refs.append({"kind": "quote", "id": qid, "source_revision": _sha(json.dumps(had, sort_keys=True).encode()),
                         "captured_at": captured})
    if not offers:
        raise ValueError("day source has no match with both a Read and sporttery odds")
    refs.append({"kind": "prescription", "id": f"{day}:legs-base", "source_revision": _sha(board_bytes),
                 "captured_at": board_captured.isoformat(timespec="seconds")})
    codes = tuple(o.official_match_no for o in offers)
    templates = tuple(
        CandidateStructureTemplate(kind="jczq_pass", structure_code=f"pass-{n}-1",
                                   eligible_official_match_nos=codes, required_offer_count=n,
                                   maximum_groups=1, pass_size=n)
        for n in range(2, min(len(codes), 1 + max_templates) + 1)
    )
    if not templates:
        raise ValueError("day source needs at least two matches for a pass template")
    candidate_input = CandidateGenerationInput(
        lane="jczq", ticket_kind="jczq_pass", currency="CNY",
        capital_cap_minor=CAPITAL_CAP_MINOR, unit_stake_minor=UNIT_STAKE_MINOR,
        maximum_ticket_count=MAX_TICKET_COUNT, maximum_exhaustive_candidate_count=MAX_EXHAUSTIVE,
        offers=tuple(offers), templates=templates,
    )
    slate = f"day:{day}:{_sha(markets_bytes)[:16]}"
    return freeze_structural_input(
        candidate_input=candidate_input, references=tuple(refs), business_date=day,
        task_snapshot_hash=_sha(board_bytes + reads_bytes), slate_revision_id=slate,
        board_slate_revision_id=slate, cutoff_at=cutoff_at,
        audit_policy_revision=_CANDIDATE_AUDIT_POLICY_VERSION, audit_offers=tuple(audits),
        source_identity=day_source_identity(jczq_dir, day),
    )
```

- [ ] **Step 4: Run** → `4 passed`；`uv run ruff check nutmeg/discovery/day_inputs.py tests/discovery/test_day_inputs.py` clean。若生成器面码是 `home/draw/away`，把 `FACE_CODE` 改为恒等映射并让测试的 `"31"` 期望相应调整——先读 `operator_candidates.py` 再定。

- [ ] **Step 5: Commit** `git add nutmeg/discovery/day_inputs.py tests/discovery/test_day_inputs.py && git commit -m "feat(discovery): freeze a structural input from the day's board, reads and sporttery quotes"`

---

### Task 2: 录制器的 `source_kind="day"`

**Files:**
- Modify: `nutmeg/discovery/online_recorder.py`（`_validate_recording`、`record_shadow_world`、`_source_fingerprint` 的调用处 ~597/683/981/1054）
- Test: 追加 `tests/discovery/test_online_recorder.py`

- [ ] **Step 1: Test**

```python
def test_day_source_records_a_world_and_reverifies_files(tmp_path, monkeypatch):
    from nutmeg.discovery.day_inputs import day_fingerprint, read_structural_input_from_day
    from tests.discovery.test_day_inputs import _day, DAY  # 复用夹具
    monkeypatch.setattr("nutmeg.discovery.online_recorder._utcnow", lambda: T0)
    engine = _rig(tmp_path)
    jczq = _day(tmp_path)
    day_dir = jczq / "daily" / DAY
    snapshot = read_structural_input_from_day(jczq, DAY, cutoff_at=T0.isoformat())
    approval = _approval(day_dir, tmp_path / "shadow.db")
    approval["scope"]["generation_request_id"] = f"day:{DAY}"
    world = record_shadow_world(
        snapshot, engine=engine, shadow_database=tmp_path / "shadow.db",
        source_database=day_dir, policy_revision_id="structural-baseline-v1",
        generation_request_id=f"day:{DAY}", requested_at=T0, approval=approval, source_kind="day",
    )
    assert world.world_id and world.sealed_manifest_hash == snapshot.manifest_hash
    assert day_fingerprint(day_dir) == day_fingerprint(day_dir)  # 生产目录未被写


def test_day_source_rejects_changed_files(tmp_path, monkeypatch):
    ...同上，但在 record 前 monkeypatch `read_structural_input_from_day` 返回改过 belief 的快照 → `ValueError("source request snapshot differs")`
```

（`_rig`、`_approval`、`T0` 是该测试文件已有的夹具；`_approval(source, shadow)` 的 scope 里 `source_db` 用 `str(source.resolve())`——目录路径同样成立。）

- [ ] **Step 2: Run** → `TypeError: unexpected keyword 'source_kind'`

- [ ] **Step 3: Implement**

```python
def _fingerprint(source: Path, source_kind: str) -> str:
    if source_kind == "day":
        from nutmeg.discovery.day_inputs import day_fingerprint
        return day_fingerprint(source)
    return _source_fingerprint(source)
```

`_validate_recording(..., source_kind: str = "database")`：
- `snapshot.source_identity` 的检查：`database` 时 `== str(source_database.resolve())`，`day` 时 `== f"day:{source_database.resolve()}"`。
- `before = _fingerprint(source_database, source_kind)`。
- 独立复核分支：`day` 时 `from nutmeg.discovery.day_inputs import read_structural_input_from_day`，`verified = read_structural_input_from_day(source_database.parent.parent, source_database.name, cutoff_at=snapshot.cutoff_at)`（`day_dir = jczq_dir/daily/<day>`），其余（manifest 比对、指纹前后一致）同 database 分支；`generation_request_id` 在 `day` 时仍要求非空（用 `day:<date>`），错误文案不变。
- `record_shadow_world(..., source_kind="database")` 透传；文件里其它 `_source_fingerprint(source_database)` 调用改为 `_fingerprint(source_database, source_kind)`（把 `source_kind` 存进 recorder 状态或闭包）。

- [ ] **Step 4: Run** `uv run pytest tests/discovery/test_online_recorder.py tests/discovery/test_day_inputs.py -q` → 全过；ruff clean。

- [ ] **Step 5: Commit** `git add nutmeg/discovery/online_recorder.py tests/discovery/test_online_recorder.py && git commit -m "feat(discovery): recorder accepts a day-directory source with file fingerprint and re-read verification"`

---

### Task 3: CLI `shadow-run --source-day`

**Files:**
- Modify: `nutmeg/interfaces/cli/discovery.py`
- Test: 追加 `tests/test_cli_discovery.py`

- [ ] **Step 1: Test**：用 Task 1 的 `_day` 夹具 + `register-baseline --by op:jun --data-dir <shadow-data>` 先登记，再写 approval JSON（scope `source_db`=day 目录绝对路径，`generation_request_id`=`day:<DAY>`，`cutoff_at`、`approved_at` = now±，`approved_by`=`op:jun`），调用 `discovery shadow-run --source-day DAY --jczq-dir <jczq> --shadow-db <shadow-data>/ontology/ontology.db --cutoff-at <now> --approval-file <json>` → exit 0，stdout JSON 含 `world_id`；再次调用 `status` 显示 sealed 1。`--source-day` 与 `--source-db` 同给 → exit 1「二选一」。
- [ ] **Step 2: Run** → `No such option: --source-day`
- [ ] **Step 3: Implement**：`SOURCE_DB_OPTION` 改为可选（`None`），新增 `SOURCE_DAY_OPTION = typer.Option(None, "--source-day")`、`JCZQ_DIR_OPTION = typer.Option(Path(".nutmeg-data/jczq"), "--jczq-dir")`；`generation_request_id` 可选。互斥校验；`day` 分支：`source = jczq_dir/daily/day`（须为目录）、`generation_request_id = f"day:{day}"`、`snapshot = read_structural_input_from_day(jczq_dir, day, cutoff_at=cutoff_at)`、`record_shadow_world(..., source_database=source, source_kind="day")`；scope 的 `source_db` = `str(source.resolve())`。`reject_production_store(shadow_db)` 照旧；**不再要求 source 是文件**。
- [ ] **Step 4: Run** `uv run pytest tests/test_cli_discovery.py -q` → 全过；ruff clean。
- [ ] **Step 5: Commit** `git add nutmeg/interfaces/cli/discovery.py tests/test_cli_discovery.py && git commit -m "feat(cli): discovery shadow-run --source-day records a world from the day's decision-lane files"`

---

### Task 4: 第一个真实世界 + 证据

- [ ] 在仓外建影子数据目录（如 `~/nutmeg-shadow/`），`uv run nutmeg discovery register-baseline --by op:jun --data-dir ~/nutmeg-shadow`（已登记则跳过）。
- [ ] 写 approval JSON（`approved_by: op:jun`、`approved_at`=现在、scope 如 Task 3），以当天板面跑 `shadow-run --source-day <今天>`；记录 `world_id`、`sealed_manifest_hash`、`discovery status` 输出、`daily/<今天>/` 三份文件 sha256 前后一致。
- [ ] `docs/superpowers/evidence/2026-09-23-discovery-day-source.md`：命令、输出、模板数、offers 数；注明是 `shadow_only`，生产目录零写。
- [ ] 在 `docs/superpowers/specs/2026-09-22-dream-rsi-pilot-cost-pruning-restatement.md` 末尾加一段「输入源改为 day（2026-09-23）」指向本 spec。
- [ ] Commit。

---

## Self-review

- Spec §2 映射全部在 T1；§3 录制器 day 源在 T2；§4 CLI 在 T3；§6 出口在 T4。
- 生成器/审计器/回放零改动 ✓；`freeze_structural_input` 的四条校验（forecast/prescription/quote 覆盖/时区与 cutoff）由 T1 的引用构造满足 ✓。
- 类型一致：`read_structural_input_from_day(jczq_dir, day, *, cutoff_at, max_templates=4)`、`day_fingerprint(day_dir)`、`day_source_identity(jczq_dir, day)`、`record_shadow_world(..., source_kind=)`。
