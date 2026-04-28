# Superpowers Reliability Gates

Nutmeg uses Superpowers Bridge as the execution reliability layer on top of Spec Kit.

## Installed bridge

- Extension: `.specify/extensions/superb`
- Workspace skill root: `.agents/skills/`
- Required skills present:
  - `test-driven-development`
  - `verification-before-completion`
- Optional skills present:
  - `systematic-debugging`
  - `receiving-code-review`
  - `finishing-a-development-branch`

## Operating model

1. Write or update a Spec Kit artifact.
2. Generate or revise `tasks.md`.
3. Run the review gate (`speckit.superb.review`) to check coverage and TDD readiness.
4. Implement through TDD (`speckit.superb.tdd`).
5. Refuse completion claims until verification runs (`speckit.superb.verify`).

## Repo-native confirmation

`nutmeg doctor` includes a bridge readiness report that checks:
- discovery roots for local and global skills
- required and optional skill availability
- readiness of the `before_implement`, `after_implement`, and `after_tasks` hooks

## Expected verdicts

- `READY`: required skills installed, hooks ready
- `PARTIAL`: required skills installed, one or more optional skills missing
- `BLOCKED`: one or more required skills missing
