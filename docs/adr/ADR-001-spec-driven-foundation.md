# ADR-001: Use Spec Kit and Superpowers Bridge for delivery governance

- **Status**: Accepted
- **Date**: 2026-04-24

## Context

Nutmeg is a greenfield product with a large surface area: data ingestion, analytical modeling, agent orchestration, and future multi-user evolution. The project needs durable delivery structure, not only code scaffolding.

## Decision

Use Spec Kit as the repository-native spec workflow and Superpowers Bridge as the reliability layer for TDD and verification gates.

## Consequences

- The repo keeps a constitution plus feature-level spec/plan/tasks artifacts.
- TDD and verification become explicit workflow gates instead of informal habits.
- Initial setup cost is higher, but change discipline improves for future sprint work.
