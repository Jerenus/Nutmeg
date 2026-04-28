# Implementation Plan: Graph Refresh Assets

**Branch**: `021-graph-refresh` | **Date**: 2026-04-25 | **Spec**: `.specify/specs/021-graph-refresh/spec.md`

## Summary

Add a no-dependency AST-based graph refresh script that writes `graphify-out/GRAPH_REPORT.md` plus JSON module/edge data.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: Python stdlib AST  
**Storage**: `graphify-out/` generated assets  
**Testing**: pytest subprocess tests  
**Constraints**: no network, deterministic sorted output, useful enough for AGENTS graph-native workflow
