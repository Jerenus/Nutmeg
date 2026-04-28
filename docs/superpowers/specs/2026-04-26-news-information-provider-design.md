# News / Information Provider v0 Design

Date: 2026-04-26

## Context

The AI-native betting client can already show an information panel, but it is currently a placeholder unless a fake provider is injected in tests. For betting-analysis assistance, latest credible information such as official lineup notes, injury updates, fixture status, and relevant match news is a core product requirement.

## Selected Approach

Implement a local-first information provider seam that can read deterministic JSON and RSS/Atom-like files without network calls. The service normalizes items, deduplicates them, filters them by fixture/team, labels reliability, and produces a client-ready digest. This closes the product gap while preserving a future path to live source fetching.

Alternatives considered:

- Direct web/news scraping now: rejected because source legality, robots/copyright, and unstable pages need a separate provider policy.
- Paid news API integration now: rejected because credentials, cost, and terms should be chosen later after local contract stabilizes.
- Keep the client placeholder: rejected because the product promise explicitly requires latest data and information context.

## Scope

- Normalize local JSON and RSS/Atom-style information items.
- Filter by fixture id, team names, and keywords.
- Deduplicate by URL or normalized title/source.
- Label status as complete, partial, or unavailable.
- Label reliability as official, credible, rumor, or unverified.
- Expose `fixture-information` CLI and integrate the provider into `client-match` / Web match workspace.
- Keep tests no-network and deterministic.

## Guardrails

- Do not scrape arbitrary web pages in v0.
- Do not treat rumors as confirmed facts.
- Do not make betting calls from information alone.
- Missing source files must return unavailable state, not fabricated updates.
