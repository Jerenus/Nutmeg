# Nutmeg Intelligence OS M2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the read-heavy Command Center and Data Operations workspaces on the M1 product contract, including filtered board inspection, explicit alerts/readiness, source and identity queues, governed identity merge, match/lineage navigation, and a responsive local application shell.

**Architecture:** Extend the versioned Python DTO/query layer first, then expose JSON routes and server-rendered Jinja views from the same FastAPI application. The browser receives display-ready values only: it performs no probability, readiness, identity, audit, or money logic. The only M2 mutation is the already-governed `merge_entity` Action, protected by the M1 local session/CSRF/origin boundary.

**Tech Stack:** Python 3.12, SQLAlchemy Core, Pydantic v2, FastAPI, Jinja2 SSR, small dependency-free JavaScript, CSS, pytest/TestClient, ruff, Codex local browser verification.

---

## Scope and file structure

### Product contract

- Modify `nutmeg/product/contracts.py`: M2 board metadata, alerts, source health,
  identity queue, operation metrics, and aggregate response DTOs.
- Modify `nutmeg/product/repository.py`: filtered/operational reads and expanded typed
  lineage. Queries remain read-only and temporal where the source object has a time.
- Modify `nutmeg/product/queries.py`: filtering, alert derivation, Command Center and
  Data Operations assembly.
- Modify `nutmeg/product/actions.py`: whitelist and validate `merge_entity` only.
- Modify `nutmeg/product/wiring.py`: retain one repository shared by queries/actions.
- Modify `nutmeg/ontology/kernel.py` and `nutmeg/ontology/wiring.py`: expose the
  existing `EntityActions` facade; do not add a second identity implementation.

### Application interface

- Modify `nutmeg/interfaces/product_api.py`: M2 JSON routes and UI registration.
- Create `nutmeg/interfaces/product_ui.py`: SSR route/controller boundary.
- Create `nutmeg/interfaces/web/templates/product/layout.html`.
- Create `nutmeg/interfaces/web/templates/product/command_center.html`.
- Create `nutmeg/interfaces/web/templates/product/operations.html`.
- Create `nutmeg/interfaces/web/templates/product/match.html`.
- Create `nutmeg/interfaces/web/templates/product/lineage.html`.
- Create `nutmeg/interfaces/web/static/product/app.css`.
- Create `nutmeg/interfaces/web/static/product/app.js`.

### Tests and documentation

- Create `tests/product/test_m2_queries.py`.
- Create `tests/product/test_m2_actions.py`.
- Create `tests/product/test_m2_api.py`.
- Create `tests/product/test_m2_ui.py`.
- Create `tests/product/test_m2_e2e.py`.
- Modify `README.md` and `docs/ontology-kernel-operations.md`.

M2 does not implement AI chat, Forecast mutation UI, ticket construction, dispatch,
settlement, scoreboard authority, scheduler restoration, or Alert acknowledgement.
Derived alerts are read-only attention objects in M2; durable acknowledgement and
resolution arrive with the M6 reliability workflow.

## Task 1: M2 versioned contracts

**Files:**
- Modify: `nutmeg/product/contracts.py`
- Test: `tests/product/test_m2_queries.py`

- [x] **Step 1: Write failing DTO strictness tests**

```python
def test_m2_contracts_are_versioned_and_strict() -> None:
    response = OperationsResponse(
        as_of=CLOCK,
        sources=[],
        identities=[],
        recent_failures=[],
        alerts=[],
        metrics=OperationsMetrics(
            ontology_integrity="ok",
            ontology_schema_version=10,
            action_high_watermark=8,
            outbox_high_watermark=8,
            projection_run_count=1,
            unresolved_identity_count=0,
        ),
    )
    assert response.schema_version == "1"
    with pytest.raises(ValidationError):
        AlertSummary(
            alert_id="alert-1", severity="warn", code="stale",
            title="stale source", detail="age exceeds six hours",
            observed_at=CLOCK, invented=True,
        )
```

Also assert `MatchSummary` exposes `evidence_count`, `workflow_state`, `next_action`,
and `flag_count` with conservative defaults so existing M1 clients remain valid.

- [x] **Step 2: Run the test and verify RED**

Run: `UV_FROZEN=1 uv run pytest -o addopts='' tests/product/test_m2_queries.py -q`
Expected: collection fails because M2 contracts do not exist.

- [x] **Step 3: Implement the contracts**

Add strict DTOs with these exact shapes:

```python
class AlertSeverity(StrEnum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class AlertSummary(StrictContract):
    alert_id: str
    severity: AlertSeverity
    code: str
    title: str
    detail: str
    observed_at: datetime
    object_ref: ObjectRefContract | None = None
    href: str | None = None


class SourceHealthSummary(StrictContract):
    source_name: str
    source_type: str
    status: str
    retrieval_count: int
    latest_retrieved_at: str | None = None
    age_seconds: int | None = None
    error_code: str | None = None
    error_detail: str | None = None


class IdentityQueueItem(StrictContract):
    entity_type: Literal["team"]
    entity_id: str
    canonical_name: str
    resolution_status: str
    country: str | None = None
    created_at: str
    external_identifiers: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)


class OperationsMetrics(StrictContract):
    ontology_integrity: str
    ontology_schema_version: int
    action_high_watermark: int
    outbox_high_watermark: int
    projection_run_count: int
    unresolved_identity_count: int


class OperationsResponse(VersionedContract):
    as_of: datetime
    sources: list[SourceHealthSummary] = Field(default_factory=list)
    identities: list[IdentityQueueItem] = Field(default_factory=list)
    recent_failures: list[ActionView] = Field(default_factory=list)
    alerts: list[AlertSummary] = Field(default_factory=list)
    metrics: OperationsMetrics


class CommandCenterResponse(VersionedContract):
    board: BoardResponse
    health: HealthResponse
    alerts: list[AlertSummary] = Field(default_factory=list)
    readiness_counts: dict[str, int] = Field(default_factory=dict)
    pending_workflow_count: int = 0
```

Extend `MatchSummary` with the four defaulted display fields named in Step 1.

- [x] **Step 4: Run tests and ruff**

Run: `UV_FROZEN=1 uv run pytest -o addopts='' tests/product/test_m2_queries.py -q && UV_FROZEN=1 uv run ruff check nutmeg/product/contracts.py tests/product/test_m2_queries.py`
Expected: DTO tests pass and ruff reports no errors.

- [x] **Step 5: Commit**

```bash
git add nutmeg/product/contracts.py tests/product/test_m2_queries.py
git commit -m "feat(product): define M2 operations contracts"
```

## Task 2: Operational repository and source lineage

**Files:**
- Modify: `nutmeg/product/repository.py`
- Modify: `tests/product/conftest.py`
- Modify: `tests/product/test_m2_queries.py`

- [x] **Step 1: Seed and test operational reads**

Extend the fixture with two artifact retrievals (`sporttery` fresh and `intl` stale),
one failed Action, and one provisional duplicate Team. Test:

```python
def test_repository_exposes_sources_identity_queue_and_failures(m2_repository):
    sources = m2_repository.source_health(CLOCK.isoformat())
    identities = m2_repository.identity_queue(limit=100)
    failures = m2_repository.failed_actions(limit=20)
    assert {row["source_name"] for row in sources} == {"sporttery", "intl"}
    assert "team-duplicate" in {row["entity_id"] for row in identities}
    assert failures[0]["status"] in {"failed", "rejected"}
```

Define `m2_repository` as a fixture that constructs `ProductReadRepository` from the
seeded kernel engine; do not share a write connection across test assertions.

Add lineage assertions for `source_artifact`, `artifact_retrieval`,
`market_snapshot`, `observation`, `claim`, and `team`.

- [x] **Step 2: Run the tests and verify RED**

Run: `UV_FROZEN=1 uv run pytest -o addopts='' tests/product/test_m2_queries.py -q`
Expected: `ProductReadRepository` is missing the M2 methods and lineage cases.

- [x] **Step 3: Implement explicit SQLAlchemy queries**

Add seven explicit methods: `source_health(as_of)`, `identity_queue(limit=)`,
`identity_item(entity_type, entity_id)`, `failed_actions(limit=)`,
`action_high_watermark()`, `pending_workflow_count(as_of=)`, and
`flag_count_for_match(match_id, as_of=)`. Their return values are plain dictionaries
whose keys exactly match the DTO field names declared in Task 1; JSON columns are
decoded with `_decode_json` before leaving the repository.

`source_health` aggregates `artifact_retrievals` by `(source_name, source_type)`,
uses the latest retrieval status/time, and left-joins the latest matching SourceRun
error when present. `identity_queue` returns only `provisional` Teams and loads
external IDs/aliases in bounded secondary queries. `failed_actions` returns only
`failed`/`rejected`, newest first. No method writes or creates a database.

Expand `_lineage_for_object` with exact edges:

```text
artifact_retrieval --retrieval_of--> source_artifact
source_artifact --artifact_has_retrieval--> artifact_retrieval
market_snapshot --snapshot_for_match--> match
market_snapshot --snapshot_contains_quote--> market_quote
observation --observation_for_match--> match (when scope_match_id exists)
claim --claim_for_match--> match (when scope_match_id exists)
team --team_has_external_id--> external_identifier:<provider>:<external_id>
```

- [x] **Step 4: Run repository and existing query regressions**

Run: `UV_FROZEN=1 uv run pytest -o addopts='' tests/product/test_m2_queries.py tests/product/test_queries.py -q`
Expected: all pass.

- [x] **Step 5: Commit**

```bash
git add nutmeg/product/repository.py tests/product/conftest.py tests/product/test_m2_queries.py
git commit -m "feat(product): add operations and source lineage queries"
```

## Task 3: Command Center filtering, alerts, and operations assembly

**Files:**
- Modify: `nutmeg/product/queries.py`
- Modify: `tests/product/test_m2_queries.py`

- [x] **Step 1: Write failing service behavior tests**

```python
def test_command_center_filters_without_hiding_empty_state(product_services):
    result = product_services.queries.command_center(
        date(2026, 8, 24), as_of=CLOCK, readiness=ReadinessLevel.READY,
        competition=None, query="Home",
    )
    assert [item.match_id for item in result.board.matches] == ["match-1"]
    empty = product_services.queries.command_center(
        date(2026, 8, 24), as_of=CLOCK, readiness=ReadinessLevel.BLOCKED,
        competition=None, query="nothing",
    )
    assert empty.board.matches == []
    assert empty.readiness_counts["ready"] == 1


def test_operations_turns_stale_source_and_failed_action_into_alerts(product_services):
    result = product_services.queries.operations(as_of=CLOCK, identity_limit=100)
    assert {alert.code for alert in result.alerts} >= {
        "source_stale", "action_failed", "identity_unresolved"
    }
```

Also test readiness-derived match alerts retain the affected Match object reference
and that the service never ranks matches by an opaque score.

- [x] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest -o addopts='' tests/product/test_m2_queries.py -q`
Expected: missing `command_center` and `operations` methods.

- [x] **Step 3: Implement deterministic assembly**

`command_center()` calls `board()` once, computes unfiltered readiness counts, then
applies case-insensitive team/competition text, readiness, and competition filters.
It joins `health()`, pending workflow count, and alerts sorted by
`ERROR`, `WARN`, `INFO`, then `observed_at`, then `alert_id`.

`operations(as_of, identity_limit=100)` computes source age against the caller
`as_of`; six hours is WARN.
It emits stable alert IDs as SHA-256 of `(code, object type, object id, observed_at)`.
No wall clock is read below the service boundary and no alert changes domain state.

Populate display fields conservatively:

```text
READY      -> workflow_state="inspect", next_action="open_match"
DEGRADED   -> workflow_state="needs_evidence", next_action="inspect_gaps"
BLOCKED    -> workflow_state="blocked", next_action="resolve_blocker"
```

- [x] **Step 4: Run M1/M2 query tests**

Run: `UV_FROZEN=1 uv run pytest -o addopts='' tests/product/test_queries.py tests/product/test_m2_queries.py -q`
Expected: all pass, including historical `as_of` exclusions.

- [x] **Step 5: Commit**

```bash
git add nutmeg/product/queries.py tests/product/test_m2_queries.py
git commit -m "feat(product): assemble command and operations views"
```

## Task 4: Governed identity merge through the Product Action Gateway

**Files:**
- Modify: `nutmeg/ontology/kernel.py`
- Modify: `nutmeg/ontology/wiring.py`
- Modify: `nutmeg/product/actions.py`
- Create: `tests/product/test_m2_actions.py`

- [x] **Step 1: Write merge safety tests**

```python
def test_operator_can_merge_provisional_duplicate(product_services):
    response = product_services.actions.execute(ProductActionRequest(
        action_type="merge_entity", idempotency_key="ui:merge:1",
        payload={"entity_type": "team", "from_id": "team-duplicate",
                 "into_id": "team-home", "reason": "same provider-backed club"},
        expected_versions={},
    ))
    assert response.status == "committed"
    with OntologyUnitOfWork(product_services.kernel.engine) as uow:
        assert uow.identity.redirect("team-duplicate", EntityType.TEAM) == "team-home"


def test_merge_rejects_absent_target_and_payload_actor_spoof(product_services):
    with pytest.raises(ProductNotFoundError):
        product_services.actions.execute(_merge_payload(into_id="missing"))
    denied = product_services.actions.execute(
        _merge_payload(key="ai:merge", actor_role="judge_operator"),
        actor_id="model:test", actor_role=ActorRole.AI_ANALYST,
    )
    assert denied.status == "rejected"
```

Also test same-ID merge, non-Team entity type, already-merged source, and idempotent
replay.

- [x] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest -o addopts='' tests/product/test_m2_actions.py -q`
Expected: `merge_entity` is not whitelisted and the kernel does not expose the facade.

- [x] **Step 3: Reuse the ontology identity Action**

Construct one `EntityActions` in `build_ontology_kernel`, pass the same instance to
`MarketDayIngestService`, and expose it as `kernel.entity_actions`. Do not alter its
permission or persistence implementation.

Add `merge_entity` to `_ALLOWED_ACTIONS`. Before invoking it, load source/target with
`repository.identity_item`, require two existing Teams, require source status
`provisional`, require target status not `merged`, ignore all payload actor fields,
and build the existing `MergeEntityRequest` with the server actor and clock.

- [x] **Step 4: Run gateway and ontology identity regressions**

Run: `UV_FROZEN=1 uv run pytest -o addopts='' tests/product/test_m2_actions.py tests/product/test_actions.py tests/ontology/test_merge_entity.py -q`
Expected: all pass.

- [x] **Step 5: Commit**

```bash
git add nutmeg/ontology/kernel.py nutmeg/ontology/wiring.py nutmeg/product/actions.py \
  tests/product/test_m2_actions.py
git commit -m "feat(product): expose governed identity merge"
```

## Task 5: M2 JSON API

**Files:**
- Modify: `nutmeg/interfaces/product_api.py`
- Create: `tests/product/test_m2_api.py`

- [x] **Step 1: Write endpoint and security tests**

```python
def test_m2_query_endpoints_publish_v1_contract(client):
    command = client.get("/api/v1/command-center?date=2026-08-24&q=Home")
    operations = client.get("/api/v1/operations")
    alerts = client.get("/api/v1/alerts")
    identities = client.get("/api/v1/identities?limit=50")
    assert all(response.status_code == 200 for response in
               (command, operations, alerts, identities))
    assert command.json()["schema_version"] == "1"
    assert operations.json()["schema_version"] == "1"


def test_identity_merge_still_requires_session_csrf_and_same_origin(client):
    payload = _merge_action_payload()
    assert client.post("/api/v1/actions", json=payload).status_code == 403
    headers = _session(client)
    assert client.post("/api/v1/actions", json=payload, headers=headers).status_code == 200
```

Test invalid readiness produces the standard 422 envelope and all `as_of` values are
timezone-aware.

- [x] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest -o addopts='' tests/product/test_m2_api.py -q`
Expected: the four M2 query routes return 404.

- [x] **Step 3: Add API routes**

Add:

```text
GET /api/v1/command-center?date=&as_of=&readiness=&competition=&q=
GET /api/v1/operations?as_of=
GET /api/v1/alerts?as_of=
GET /api/v1/identities?as_of=&limit=
```

All delegate to `ProductQueryService`; `alerts` and `identities` slice the same
`OperationsResponse` (passing the validated identity limit) so their semantics cannot
diverge. Keep `/api/v1/board` backward compatible while adding the same optional
filters.

- [x] **Step 4: Run all API tests**

Run: `UV_FROZEN=1 uv run pytest -o addopts='' tests/product/test_api.py tests/product/test_m2_api.py -q`
Expected: all pass.

- [x] **Step 5: Commit**

```bash
git add nutmeg/interfaces/product_api.py tests/product/test_m2_api.py
git commit -m "feat(api): expose M2 operations contract"
```

## Task 6: Product shell and Command Center

**Files:**
- Create: `nutmeg/interfaces/product_ui.py`
- Create: `nutmeg/interfaces/web/templates/product/layout.html`
- Create: `nutmeg/interfaces/web/templates/product/command_center.html`
- Create: `nutmeg/interfaces/web/static/product/app.css`
- Modify: `nutmeg/interfaces/product_api.py`
- Create: `tests/product/test_m2_ui.py`

- [x] **Step 1: Write failing shell and Command Center tests**

```python
def test_command_center_renders_semantic_attention_surface(client):
    response = client.get("/?date=2026-08-24")
    assert response.status_code == 200
    assert 'lang="zh-CN"' in response.text
    assert 'data-workspace="command-center"' in response.text
    assert "Home FC" in response.text
    assert "ready" in response.text
    assert "最佳投注" not in response.text
    assert 'href="/matches/match-1' in response.text


def test_empty_filter_is_designed_state(client):
    response = client.get("/?date=2026-08-24&q=absent")
    assert response.status_code == 200
    assert 'data-empty-state="board"' in response.text
    assert "没有符合当前筛选的比赛" in response.text
```

Also assert skip-link, landmarks, visible focus stylesheet, no external CDN assets,
and no inline probability arithmetic script.

- [x] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest -o addopts='' tests/product/test_m2_ui.py -q`
Expected: `/` returns 404.

- [x] **Step 3: Register the SSR boundary**

`mount_product_ui(app, services, clock)` mounts `/assets/product`, creates Jinja
templates from package-relative paths, and registers `/`. The controller validates
filters through product enums, calls `queries.command_center`, and passes only DTOs,
active filter values, and route metadata to templates.

- [x] **Step 4: Build the visual shell**

Use the approved ledger/editorial direction:

```css
:root {
  --paper: #f5f7f3; --ink: #1b2620; --pine: #1f5c46;
  --cinnabar: #b23a2c; --gold: #8a6f2f; --line: #cbd4cc;
  --serif: "Songti SC", "Noto Serif CJK SC", Georgia, serif;
  --sans: "Avenir Next", "PingFang SC", sans-serif;
  --mono: "SFMono-Regular", "JetBrains Mono", monospace;
}
```

The shell has a narrow ontology rail, top health strip, global alert rail, command
surface, semantic status text/icons, and no dark-mode default. Desktop uses a dense
12-column grid; at 760 px it becomes one column with a sticky workspace switcher.
Cinnabar is limited to conflict/pending judgment. Add one staggered page-load reveal,
disabled by `prefers-reduced-motion`.

- [x] **Step 5: Run UI tests and ruff**

Run: `UV_FROZEN=1 uv run pytest -o addopts='' tests/product/test_m2_ui.py -q && UV_FROZEN=1 uv run ruff check nutmeg/interfaces/product_ui.py`
Expected: all pass.

- [x] **Step 6: Commit**

```bash
git add nutmeg/interfaces/product_ui.py nutmeg/interfaces/product_api.py \
  nutmeg/interfaces/web/templates/product/layout.html \
  nutmeg/interfaces/web/templates/product/command_center.html \
  nutmeg/interfaces/web/static/product/app.css tests/product/test_m2_ui.py
git commit -m "feat(ui): add Nutmeg command center"
```

## Task 7: Data Operations and identity queue UI

**Files:**
- Create: `nutmeg/interfaces/web/templates/product/operations.html`
- Create: `nutmeg/interfaces/web/static/product/app.js`
- Modify: `nutmeg/interfaces/product_ui.py`
- Modify: `nutmeg/interfaces/web/templates/product/layout.html`
- Modify: `tests/product/test_m2_ui.py`

- [x] **Step 1: Write failing operations interaction tests**

```python
def test_operations_page_shows_source_age_identity_and_failure(client):
    response = client.get("/operations?as_of=2026-08-24T10:00:00Z")
    assert response.status_code == 200
    assert 'data-workspace="operations"' in response.text
    assert "sporttery" in response.text
    assert "team-duplicate" in response.text
    assert 'data-action="merge-identity"' in response.text
    assert "直接编辑数据库" not in response.text


def test_merge_controls_embed_no_privileged_actor(client):
    html = client.get("/operations").text
    assert 'name="actor_role"' not in html
    assert 'name="actor_id"' not in html
```

- [x] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest -o addopts='' tests/product/test_m2_ui.py -q`
Expected: `/operations` returns 404.

- [x] **Step 3: Render operations from the product DTO**

Add `/operations` using `queries.operations`. Render source age/status, Action
high-water marks, projection count, failed/rejected Actions, provisional identities,
and explicit "schedule visibility not instrumented" degraded state. The identity
form asks for survivor ID and reason, then JavaScript posts a `merge_entity`
`ProductActionRequest` through `/api/v1/actions`.

- [x] **Step 4: Implement the small client boundary**

`app.js` obtains `/api/v1/session` only when the operator submits a mutation, sends
the CSRF header and same-origin request, generates an idempotency key with
`crypto.randomUUID()`, never stores secrets, and reloads the operations view only on
commit. It displays the stable server error envelope in an `aria-live="polite"`
region. It contains no probability/readiness/money calculations.

- [x] **Step 5: Run UI/API/action regressions**

Run: `UV_FROZEN=1 uv run pytest -o addopts='' tests/product/test_m2_ui.py tests/product/test_m2_api.py tests/product/test_m2_actions.py -q`
Expected: all pass.

- [x] **Step 6: Commit**

```bash
git add nutmeg/interfaces/product_ui.py \
  nutmeg/interfaces/web/templates/product/layout.html \
  nutmeg/interfaces/web/templates/product/operations.html \
  nutmeg/interfaces/web/static/product/app.js tests/product/test_m2_ui.py
git commit -m "feat(ui): add data operations workspace"
```

## Task 8: Match and lineage navigation

**Files:**
- Create: `nutmeg/interfaces/web/templates/product/match.html`
- Create: `nutmeg/interfaces/web/templates/product/lineage.html`
- Modify: `nutmeg/interfaces/product_ui.py`
- Modify: `tests/product/test_m2_ui.py`

- [x] **Step 1: Write failing navigation tests**

```python
def test_match_page_keeps_as_of_and_links_source_lineage(client):
    response = client.get("/matches/match-1?as_of=2026-08-24T10:00:00Z")
    assert response.status_code == 200
    assert "2026-08-24T10:00:00+00:00" in response.text
    assert "legacy_unbundled" in response.text
    assert "/lineage/forecast_revision/fr-legacy" in response.text
    assert "obs-future" not in response.text


def test_lineage_page_renders_typed_edges_not_raw_sql(client):
    response = client.get("/lineage/forecast_revision/fr-legacy")
    assert response.status_code == 200
    assert "forecast_for_match" in response.text
    assert "created_by_action" in response.text
    assert "SELECT " not in response.text
```

Test absent objects render the stable product 404 page without a stack trace.

- [x] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest -o addopts='' tests/product/test_m2_ui.py -q`
Expected: match/lineage UI routes return 404.

- [x] **Step 3: Add temporal Match and generic lineage views**

Match renders identity/context, one server-computed market anchor, readiness issues,
evidence, Forecast history, and workflow objects. Claims remain visually distinct from
Observations; legacy Forecasts show an explicit unsourced-history badge. Lineage
renders typed source/target object cards and keeps object IDs copyable in monospace.

- [x] **Step 4: Run all UI tests**

Run: `UV_FROZEN=1 uv run pytest -o addopts='' tests/product/test_m2_ui.py -q`
Expected: all pass.

- [x] **Step 5: Commit**

```bash
git add nutmeg/interfaces/product_ui.py \
  nutmeg/interfaces/web/templates/product/match.html \
  nutmeg/interfaces/web/templates/product/lineage.html tests/product/test_m2_ui.py
git commit -m "feat(ui): add temporal match and lineage views"
```

## Task 9: Event state, responsive behavior, and M2 golden path

**Files:**
- Modify: `nutmeg/interfaces/web/static/product/app.js`
- Modify: `nutmeg/interfaces/web/static/product/app.css`
- Create: `tests/product/test_m2_e2e.py`
- Modify: `README.md`
- Modify: `docs/ontology-kernel-operations.md`

- [x] **Step 1: Write the M2 golden-path test**

```python
def test_m2_golden_path_board_to_lineage_to_identity_merge(client, product_services):
    command = client.get("/?date=2026-08-24")
    assert command.status_code == 200 and "Home FC" in command.text
    match = client.get("/matches/match-1?as_of=2026-08-24T10:00:00Z")
    assert "obs-future" not in match.text
    lineage = client.get("/lineage/forecast_revision/fr-legacy")
    assert "forecast_for_match" in lineage.text
    headers = _session(client)
    merged = client.post("/api/v1/actions", headers=headers, json=_merge_action_payload())
    assert merged.status_code == 200
    refreshed = client.get("/operations?as_of=2026-08-24T10:00:00Z")
    assert 'data-identity-id="team-duplicate"' not in refreshed.text
```

Add an architecture test scanning product templates/static/controller for
`DecisionStore`, `workbench.jsonl`, raw SQL, devig formulas, payout formulas, and
privileged actor fields.

- [x] **Step 2: Run and verify RED**

Run: `UV_FROZEN=1 uv run pytest -o addopts='' tests/product/test_m2_e2e.py -q`
Expected: event connectivity and/or responsive shell assertions are missing.

- [x] **Step 3: Add client event connectivity state**

Open `EventSource('/api/v1/events/stream?after=<session cursor>')`, keep the cursor in
`sessionStorage`, mark the health strip connected on messages and visibly offline on
errors, and reconnect using the last event ID. Browser event state never changes
domain readiness. Add keyboard-visible focus, 44 px touch targets below 760 px, no
horizontal page overflow at 390 px, and reduced-motion handling.

- [x] **Step 4: Document M2 operations**

Document `/`, `/operations`, Match/lineage routes, filters, identity merge governance,
the absence of client arithmetic, and the fact that M2 still performs no ticket,
funds, dispatch, or scheduler operation.

- [x] **Step 5: Run M2 and M1 regression gates**

```bash
UV_FROZEN=1 uv run pytest -o addopts='' tests/product -q
UV_FROZEN=1 uv run pytest -o addopts='' tests/ontology -q
UV_FROZEN=1 uv run ruff check nutmeg/product nutmeg/interfaces/product_api.py \
  nutmeg/interfaces/product_ui.py tests/product
git diff --check
```

Expected: all pass.

- [x] **Step 6: Commit**

```bash
git add nutmeg/interfaces/web/static/product/app.js \
  nutmeg/interfaces/web/static/product/app.css tests/product/test_m2_e2e.py \
  README.md docs/ontology-kernel-operations.md
git commit -m "test(product): prove M2 operator path"
```

## Task 10: M2 browser and completion gate

**Files:**
- Modify: `docs/superpowers/plans/2026-08-24-nutmeg-intelligence-os-m2.md`
- Modify only if a verified defect is found: M2 files listed above

- [ ] **Step 1: Run the local server against a seeded isolated store**

Start `uv run nutmeg app --host 127.0.0.1 --port 8788` with an isolated
`NUTMEG_DATA_DIR`; never point browser mutation tests at production.

- [ ] **Step 2: Use the local browser verification skill**

Verify Command Center, Operations, Match, and lineage at desktop and 390 px width.
Capture screenshots as test evidence; check loading/empty/degraded/blocked/offline,
keyboard navigation, focus visibility, overflow, console errors, and SSE reconnect.
No external URL or dispatch workflow is authorized.

- [ ] **Step 3: Run final code gates**

```bash
UV_FROZEN=1 uv run ruff check .
UV_FROZEN=1 uv run python -m compileall -q nutmeg scripts
UV_FROZEN=1 uv run pytest -o addopts='' -q
UV_FROZEN=1 uv run pre-commit run pytest-product --all-files
git diff --check
```

Expected: zero failures and no whitespace errors.

- [ ] **Step 4: Run a real read-only M2 smoke**

Copy the 2026-08-24 Sporttery/international/Read fixtures into a fresh temp directory,
run the verified v2 dry replay, then request Command Center, Operations, one Match, and
one lineage page. Do not copy legs/results, dispatch, fetch live results, move funds,
or mutate production.

- [ ] **Step 5: Record verification evidence and commit**

Append UTC timestamp, tested commit, test counts, browser viewport/screenshots,
real-smoke object counts, and explicit safety statement to this plan, then commit:

```bash
git add docs/superpowers/plans/2026-08-24-nutmeg-intelligence-os-m2.md
git commit -m "docs(product): record M2 verification"
```

## M2 completion boundary

M2 is complete only when all ten tasks are checked, the full suite and browser gate are
green, the real read-only smoke renders from Ontology Kernel v2, and verification
evidence is committed. Completion does not authorize M3 AI provider calls, production
identity merges, schedule restoration, Telegram dispatch, ticket approval, or funds
actions.
