# Research Knowledge Index Design

**Date:** 2026-08-20
**Status:** Approved and implemented on 2026-08-21
**Scope:** Cross-session discovery of Nutmeg football research for GPT/Codex and Claude

## 1. Goal

Create one durable discovery path for league, team, fixture and correction research so future GPT/Codex and Claude sessions find the same evidence-backed archives before answering or changing football knowledge.

Success means:

- both `AGENTS.md` and `CLAUDE.md` point to the same research index;
- a future session can locate relevant archives without relying on chat history;
- structured entity data, research synthesis and historical notes have an explicit authority order;
- corrections supersede older conclusions without deleting the audit trail;
- adding a research archive has one documented registration step.

## 2. Current Problem

`docs/research/` contains multiple useful archives, but there is no directory index and neither model harness instructs agents to inspect them. Filename search can discover a known team or league, but it cannot reliably answer:

- which archive is current;
- whether a file is a reusable entity profile or a one-match judgment;
- which source wins when a research note conflicts with the live decision store;
- where a correction or replacement is recorded.

Copying the full archive list into both harnesses would create a second source of truth and invite drift.

## 3. Chosen Architecture

Use a single Markdown catalog at `docs/research/INDEX.md`. Add an identical, bounded `RESEARCH INDEX` block to `AGENTS.md` and `CLAUDE.md`. The harness blocks describe when the index is mandatory; the index owns all archive entries and maintenance rules.

The alternatives are rejected as follows:

- duplicate archive lists in both harnesses: simple initially, but guaranteed to drift;
- a JSON registry plus generated Markdown: machine-friendly but unnecessary at the current archive size;
- memory-only discovery: not auditable and unavailable to fresh sessions.

## 4. Authority Model

When facts conflict, future sessions use this order:

1. live decision store and current canonical Match/Snapshot data;
2. newer official or primary-source evidence collected for the current window;
3. curated seed entities in `nutmeg/data/decision_entities_seed.json`;
4. active entries in `docs/research/INDEX.md` and their linked archives;
5. superseded or historical research;
6. conversational memory.

The index is a discovery and interpretation layer, not a replacement database. A research archive may explain provenance, limitations and comparisons, but current structured Team/League facts remain in the entity store and seed.

## 5. Index Structure

`docs/research/INDEX.md` contains these sections:

1. **Usage Contract** — mandatory lookup rule and authority order;
2. **League and Team Ontology Archives** — reusable league/team profiles;
3. **Preparation Queues** — time-bounded upcoming-fixture collection queues;
4. **Fixture Deep Research** — match-specific analysis and cross-channel reads;
5. **Historical Research** — older material retained for evidence or method history;
6. **Correction and Supersession Protocol** — how to replace an archive safely;
7. **Registration Checklist** — how every future archive enters the catalog.

Each indexed archive records:

- date;
- coverage or fixture;
- archive type;
- status: `active`, `time-bounded`, `historical`, or `superseded`;
- primary use;
- limitations or refresh trigger;
- relative file link.

The catalog remains manually curated until archive volume or repeated registration errors justify automation.

## 6. Harness Discovery Contract

Insert the same marked block near the top of `AGENTS.md` and `CLAUDE.md`, without copying the archive table:

```text
<!-- RESEARCH INDEX START -->
For league, team, fixture, transfer, availability, cohesion, or correction work,
read docs/research/INDEX.md before answering or mutating entity knowledge. Follow
its authority order and supersession rules; do not rely on chat memory as the
knowledge source.
<!-- RESEARCH INDEX END -->
```

The block is deliberately short so both harness copies can remain byte-identical in intent. The existing JCZQ SOP and current-plan pointer remain unchanged.

## 7. Correction and Supersession

Research is never silently rewritten into a different conclusion without traceability.

- Small factual corrections may update the original archive with a dated correction note and new evidence.
- Material changes create a new dated archive. The old index entry becomes `superseded` and links to the replacement.
- Time-bounded preparation queues become `historical` after their fixture window; they remain available for audit but no longer represent current availability or market state.
- Current injury, transfer, lineup and market facts must always be refreshed before a match judgment, even when an active ontology archive exists.
- Entity-store corrections must be written through the existing `decision-profile` / `decision-entities-sync` workflow, not only documented in Markdown.

## 8. Initial Catalog Population

The first index version registers all existing files currently under `docs/research/`:

- Premier League MW1 intelligence;
- La Liga / Ligue 2 / Eerste Divisie ontology intelligence;
- the corresponding seven-day preparation queue;
- Serie A / Bundesliga / 2. Bundesliga ontology intelligence;
- Rayo Vallecano vs Alaves cross-channel deep read;
- three-priority-fixtures deep read;
- Tunisia vs Japan historical research.

The ontology archives are active reusable baselines. Dated fixture queues and deep reads are time-bounded or historical according to their match window.

## 9. Registration Workflow

For each new research archive:

1. create the dated file under `docs/research/`;
2. add one entry to the appropriate section of `docs/research/INDEX.md`;
3. state status, scope, primary use, limitations and refresh trigger;
4. if replacing another archive, mark the old entry `superseded` and cross-link both entries;
5. run the index consistency checks before claiming completion.

No routine archive addition edits `AGENTS.md` or `CLAUDE.md`; only the central index changes.

## 10. Validation

Implementation is accepted when fresh checks prove:

- both harnesses contain exactly one marked research-index block;
- the text between the two markers is identical;
- every Markdown file directly under `docs/research/` is represented in the index, excluding the index itself;
- every local archive link in the index resolves to an existing file;
- the index names the authority order, status vocabulary and supersession protocol;
- existing entity, alias and decision-read tests remain passing;
- no betting legs, Ticket, `decision-close`, dispatch or external publication is created.

## 11. Non-Goals

- Do not duplicate full Team/League profiles in the index.
- Do not turn research Markdown into a competing entity store.
- Do not build a generator, database table, search service or embedding index yet.
- Do not reinterpret existing match judgments while cataloging them.
- Do not modify the JCZQ decision rules or authorize betting or publication.
