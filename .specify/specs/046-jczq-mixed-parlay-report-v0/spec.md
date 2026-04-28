# Feature Specification: JCTZQ Mixed Parlay Report v0

**Status**: Verified (2026-04-26)  
**Created**: 2026-04-26

## Summary

Nutmeg can generate two official-odds竞彩足球 4-leg high-odds mixed-parlay reports, write JSON/Markdown/PDF artifacts, and expose the workflow through CLI and the OpenClaw Nutmeg bot router.

## Requirements

- Fetch or load Sporttery calculator-style竞彩足球 odds data.
- Use only currently sellable matches and pools.
- Produce exactly two 4-leg combinations by default.
- Include pool, pick, odds, match metadata, explanation, official source URL, update times, total odds, and 2元 theoretical return.
- Render optional PDF with Chinese text.
- Support dry-run and real Telegram document dispatch through existing confirmation gates.
- Avoid wager execution, profit guarantees, and sportsbook integration.

## Success Criteria

- Focused service tests pass with no network.
- CLI JSON contract returns artifacts and two combinations.
- Router action builds an allowlisted command and rejects unconfirmed dispatch.
