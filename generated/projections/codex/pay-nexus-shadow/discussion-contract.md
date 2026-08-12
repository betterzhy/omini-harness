# Discussion Contract

## Topic
- Project: pay-nexus-shadow
- Topic: next-development-slice-admission
- Stage: CALIBRATION
- Intent: implementation-readiness-review
- Topic Guard: OPEN_OR_IN_PROGRESS

## Background References
- current-formal-status.md
- AGENTS.md
- docs/architecture/engineering-readiness/development-control-plane-progress.md
- docs/architecture/engineering-readiness/development-entry-admission-progress.md
- docs/architecture/engineering-readiness/dev-s01-cpc-query-reference-slice-progress.md
- current-formal-status.md#architecturesemanticstatus
- decision://pay-nexus/harness-project-local-install-not-authorized

## Known CLOSED Topics
- payment-platform-v1.13-architecture → current-formal-status.md#architecturesemanticstatus
- dev-s01-local-landing → docs/architecture/engineering-readiness/dev-s01-cpc-query-reference-slice-progress.md

## Scope
- Produce: next Slice admission guidance and exact planning constraints
- Runtime: CODEX

## Non-Goals
- Do not silently change project decisions, topic closure state, or shared capability lifecycle.
- Do not copy project-specific truth into the shared harness as reusable knowledge.

## Core Questions
- Which authoritative references govern topic `next-development-slice-admission`?
- What must remain true while producing `next Slice admission guidance and exact planning constraints`?
- Which decisions require human authority rather than agent inference?

## Constraints
- Project canonical authority takes precedence over generic shared guidance (PROJECT_TRUTH_WINS).
- CLOSED topics must not be reopened without an explicit represented reopen signal and human authority.
- Generated discussion context is not canonical project truth.
- skill:agent-design:architecture-review conflicts with current-formal-status.md#current-execution-authority; PROJECT_TRUTH_WINS

## Expected Outputs
- next Slice admission guidance and exact planning constraints
- framework:agent-design:authority-analysis@1.0.0 (4fd4857d170c)
- framework:agent-design:lifecycle-analysis@1.0.0 (7a6d87e989ae)
- principle:agent-design:project-truth-over-generic-guidance@1.0.0 (fb16ec4b824f)
- skill:agent-design:architecture-review@1.0.0 (00094ad3677d)

## Closure Criteria
- stage-specific output accepted

## Next Stage
- BOUNDARY_CLOSURE
- BASELINE
