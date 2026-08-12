# Discussion Contract

## Topic
- Project: project-fixture
- Topic: resolver-mvp
- Stage: BOUNDARY_CLOSURE
- Intent: architecture-review
- Topic Guard: OPEN_OR_IN_PROGRESS

## Background References
- baseline://project-fixture/authority-model/1.0
- decision://project-fixture/project-truth-wins
- assumption://project-fixture/metadata-first-resolver
- decision://project-fixture/projection-pack-installation

## Known CLOSED Topics
- authority-model → baseline://project-fixture/authority-model/1.0

## Scope
- Produce: review findings
- Runtime: CHATGPT

## Non-Goals
- Do not silently change project decisions, topic closure state, or shared capability lifecycle.
- Do not copy project-specific truth into the shared harness as reusable knowledge.

## Core Questions
- Which authoritative references govern topic `resolver-mvp`?
- What must remain true while producing `review findings`?
- Which decisions require human authority rather than agent inference?

## Constraints
- Project canonical authority takes precedence over generic shared guidance (PROJECT_TRUTH_WINS).
- CLOSED topics must not be reopened without an explicit represented reopen signal and human authority.
- Generated discussion context is not canonical project truth.

## Expected Outputs
- review findings
- framework:agent-design:authority-analysis@1.0.0 (4fd4857d170c)
- framework:agent-design:lifecycle-analysis@1.0.0 (7a6d87e989ae)
- principle:agent-design:closure-requires-authority@1.0.0 (c7bf1c1477f2)
- principle:agent-design:project-truth-over-generic-guidance@1.0.0 (fb16ec4b824f)
- skill:agent-design:architecture-review@1.0.0 (00094ad3677d)
- skill:agent-design:design-closure-assessment@1.0.0 (ca40a8b7b3e0)

## Closure Criteria
- stage-specific output accepted
- authorized closure evidence exists

## Next Stage
- BASELINE
- ENGINEERING_DESIGN
