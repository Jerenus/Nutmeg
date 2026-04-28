# Long-running Agent Harness

Nutmeg adopts a repository-local long-running agent harness inspired by Anthropic's article "Effective harnesses for long-running agents" (published on November 26, 2025).

## Why this exists

Long tasks fail when a later session has to guess what an earlier session was doing. Nutmeg keeps three continuity artifacts in the repository so a fresh session can get bearings quickly and continue with low ambiguity:

- `init.sh`: restores the local environment and runs a basic health check
- `agent-progress.md`: human-readable status log and next-step notes
- `feature-list.json`: structured feature checklist with explicit pass/fail state

## Session protocol

1. Run `pwd` and confirm you are in the repository root.
2. Read `agent-progress.md` and `feature-list.json`.
3. Read recent git history.
4. Run `bash ./init.sh`.
5. Pick a single incomplete feature and work it to a clean stopping point.
6. Verify it with fresh evidence.
7. Update `feature-list.json` and `agent-progress.md` before ending the session.

## Nutmeg adaptation

The original article focuses on long-running web-app agents. Nutmeg adapts the same ideas to a CLI-first analytical system:

- objective football data sync is treated as a feature slice
- sync results are verified through CLI output and repository tests
- the continuity artifacts live in the repository root so any future coding session can resume quickly
- a clean stop means the repo is linted, tested, and documented enough for the next session to continue safely
