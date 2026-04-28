# Quickstart: Nutmeg Platform Foundation

```bash
uv sync --extra dev
cp .env.example .env
uv run nutmeg doctor
uv run nutmeg fixtures --league epl --demo
uv run pytest
```

## Expected outcomes

- `nutmeg doctor` prints application, storage, provider, and workflow readiness.
- `nutmeg fixtures --league epl --demo` prints a small upcoming fixture table.
- `pytest` validates CLI, domain, model, and bridge inspection behavior.
