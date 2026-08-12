# PAY-NEXUS PILOT TASK 001 — AUTHORITY ROUTING REVIEW

## Conclusion

The first real read-only Codex pilot is `PASS` for its declared scope: verify the execution-authority route after project technology selection closure. Technology selection is closed as design-only evidence and does not authorize development, repeat repository Landing, Wave 0, DDL, formal database writes, production operations, or Git push.

```text
PAY_NEXUS_PILOT_TASK_001 = PASS
REGISTRATION_DISCOVERY = PASS
AUTHORITY_GATE = PASS
EXACT_CAPABILITY_LOCK = PASS
RESOLVER_SELECTION = PASS
NEXT_SLICE_READINESS_RESOLUTION = PASS
CLOSED_TOPIC_PROTECTION = PASS
PROJECT_TRUTH_OVERRIDE = PASS
PROJECTION_FRESHNESS = PASS_EXACT_REQUEST_CONTEXT
INSTALL_PLAN = PASS_DRY_RUN_ONLY
PAY_NEXUS_SOURCE_READ_ALLOWLIST = PASS_AFTER_P1_CORRECTION
PAY_NEXUS_WRITE_COUNT = 0
SKILL_MATERIALIZATION = NOT_EXECUTED
FEEDBACK_EXPERIENCE_TRIAGE = NOT_REQUIRED_INTEGRATION_ROUTING_DEFECT_FIXED
```

This conclusion is not a business-implementation, technology-execution, production-readiness, deployment, or semantic-CI acceptance claim.

## Next Slice Admission Readiness Extension

The required request is:

```text
intent = implementation-readiness-review
topic = next-development-slice-admission
requestedOutput = next Slice admission guidance and exact planning constraints
runtime = CODEX
```

The first live run read the complete Authority Snapshot but selected zero capabilities because every exact-lock entry reported `intent-mismatch`. The Sidecar was bound only to the canonical `architecture-review` intent. That result could report authority facts, but it could not provide the requested shared admission-review guidance or a project-authority conflict signal.

The Harness-owned Sidecar control plane now declares the narrow, project-specific alias:

```text
implementation-readiness-review -> architecture-review
```

The original request intent remains in the resolved context. `selectionIntent=architecture-review` and `selectedBecause=intent-alias:implementation-readiness-review->architecture-review` make the routing decision auditable. The alias selects only the four-capability architecture-review dependency closure already present in the Sidecar exact lock; it does not add or modify a Canonical Capability, rebuild the lock, change its fingerprint, or require a Pay-Nexus registration write.

Fresh result:

```text
resolution = resolution:7c5b43e825be6a19b23623c5
selected = authority-analysis, lifecycle-analysis, project-truth-over-generic-guidance, architecture-review
excluded = closure-requires-authority (intent-mismatch)
conflict = PROJECT_EXECUTION_AUTHORITY_OVERRIDES_GENERIC_REVIEW
resolutionRule = PROJECT_TRUTH_WINS
DEV-S01 current gate = CLOSED
Stage 1/3/4/5 authority = CONSUMED
Stage 4 review = GO evidence only
development = DENY
repository landing = DENY
Wave 0 = DENY
```

The request therefore provides read-only planning constraints only. It does not reopen DEV-S01, select a business Slice, or grant development authority.

Fresh candidate Gate evidence: structural validation `PASS`; registry/catalog/project-lock/integration-lock checks `PASS`; neutral scenarios `2/2 PASS`; Pay-Nexus scenarios `6/6 PASS`; Codex Projection `fresh=true`; source/target-separated install planner `PASS / DRY_RUN`; engineering doctor `PASS`; pytest `164 passed`.

## Pilot Question

> After Pay-Nexus closed its project reference technology selection, does the current authority route still prevent consumed Stage 1/3/4/5 permissions and review receipts from being interpreted as new execution authority?

## Frozen Identity and Read Boundary

```text
Harness baseline HEAD = f46c90132d2373279ef082f7ec5c0cf1b277290a
Pay-Nexus HEAD        = 6ac4b5cf21eae16a8c662d47e89dea13c5ccb9fc
Pay-Nexus tree        = d27cf9161d9c5a4fc0e339c22381d44b574fd202
Authority-set status  = CLEAN_FOR_AUTHORITY_SET
Authority-set digest  = sha256:15a1b4bb44d0534dc50dd3696d225fa78b12484071830d976e38ef651a0e8356
Authority snapshot    = sha256:eda768c0ea421009a980b39a46e29e99f9c4585fcf93f47aa8afa5edd4fd67ef
Exact lock            = sha256:1b5b5116bbd7b98be65f207b0f849cca0cf16cd541e80bb3f6a93f405d4f6bdb
Resolution            = resolution:66f9dde4ff1c908994c4ae6b
```

Authority resolution was limited to the registration pointer and the six paths registered by `authority-map.yaml`:

- `current-formal-status.md` — canonical global execution authority.
- `AGENTS.md` — repository guidance; owns no project facts.
- `docs/architecture/engineering-readiness/development-control-plane-progress.md` — specialized stable registration receipt.
- `docs/architecture/engineering-readiness/development-entry-admission-progress.md` — specialized assessment receipt.
- `docs/architecture/engineering-readiness/dev-s01-cpc-query-reference-slice-progress.md` — specialized active Slice authority.
- `docs/architecture/engineering-readiness/machine/active-development-projection-1.0.0.yaml` — derived projection; owns no facts.

`temp-input/**` was never read, enumerated, or hashed. `.git/**` was not traversed as project Authority content; the required HEAD/tree, tracked-status, authority-set, and committed-blob checks did consume Git revision/blob metadata through bounded Git commands. An earlier superseded planner call incorrectly used the live Pay-Nexus root as its materialization target; it made zero writes but metadata-probed the non-allowlisted transaction, install-manifest, and target-Skill paths. Independent review rejected that candidate as `NO-GO / P1=1`. The corrected planner path separates the live allowlisted authority source from a disposable empty materialization target, so no Pay-Nexus target path is inspected.

## Project-Truth Findings

### 1. Technology selection closure remains design-only

`current-formal-status.md` records:

```text
TechnologySelectionStatus = PROJECT_REFERENCE_WINNERS_SEMANTIC_REVIEWED_GO
TechnologySelectionClosureStatus = FINAL_CLOSURE_REVIEWED_GO_DESIGN_ONLY
TechnologySelectionVerificationBoundary = SELECTED_NOT_VERIFIED_UNLESS_EXECUTED_RECEIPT
```

Therefore the selection is a project reference decision, not evidence that the selected stack has been executed or verified and not an execution authorization source.

### 2. Current global execution authority remains closed

The normalized live snapshot and canonical raw fields agree:

| Boundary | Normalized result | Canonical evidence |
|---|---|---|
| Development | `DENY` | `NO_DEV_S01_STAGE5_LOCAL_LANDING_COMPLETE` |
| Repository Landing | `DENY` | `NO` |
| DDL | `DENY` | `NO` |
| Formal database write | `DENY` | `NO` |
| Wave 0 | `DENY` | `NO` |
| Git push | `DENY` | `NO` |

The active derived projection independently reflects all of these as `false`, but it is not the owner of the facts.

### 3. Earlier Stage authority is consumed, not reusable

The active Slice authority records:

```text
Stage1Authorization = EXPLICIT_USER_AUTHORIZATION_CONSUMED_TOOLCHAIN_ONLY
Stage3Authorization = EXPLICIT_USER_AUTHORIZATION_CONSUMED_CPC_QUERY_TDD_COMPLETE
Stage4ClosureProjectionAndLandingPreflightAuthorization = EXPLICIT_USER_AUTHORIZATION_CONSUMED
Stage5RepositoryLandingAuthorization = EXPLICIT_USER_AUTHORIZATION_CONSUMED_LOCAL_ONLY
AllowedFutureWriteEnvelope = CLOSED_DEV_S01_NO_FURTHER_EXECUTION_AUTHORIZED
NextRequiredAction = AWAIT_SEPARATE_WAVE0_OR_NEXT_SLICE_AUTHORIZATION
```

The Stage 4 review GO and Landing comparison receipt are evidence of their completed scopes. They do not authorize a new stage or repeat their consumed operations.

### 4. Registration and runtime projection remain subordinate

`AGENTS.md` states that `.agent-evolution/registration.yaml` is only discovery/read-only binding and exact-lock metadata. Project formal sources outrank shared guidance, and neither registration nor a generated Skill authorizes installation or project execution.

## Resolver Evidence

The exact request context was:

```text
intent = architecture-review
topic = harness-shadow-binding
requestedOutput = read-only authority review
runtime = CODEX
```

Selected capabilities:

- `framework:agent-design:authority-analysis@1.0.0`
- `framework:agent-design:lifecycle-analysis@1.0.0`
- `principle:agent-design:project-truth-over-generic-guidance@1.0.0`
- `skill:agent-design:architecture-review@1.0.0`

Excluded capability:

- `principle:agent-design:closure-requires-authority@1.0.0` — `intent-mismatch`.

Conflict signal:

```text
sharedCapability = skill:agent-design:architecture-review
projectReference = current-formal-status.md#current-execution-authority
conflictType = PROJECT_EXECUTION_AUTHORITY_OVERRIDES_GENERIC_REVIEW
resolutionRule = PROJECT_TRUTH_WINS
```

This is the required result: generic review guidance cannot convert a design selection, assessment receipt, or consumed authorization into project execution authority.

## Scenario Results

| Scenario | Result | Decisive evidence |
|---|---|---|
| `closed-architecture-protection` | PASS | `DO_NOT_REOPEN`; no capability materialized for the CLOSED topic |
| `consumed-stage-does-not-authorize-wave0` | PASS | Stage 1/3/4/5 are `CONSUMED`; Wave 0 remains `DENY` |
| `current-authority-denies-execution` | PASS | Development, Landing, DDL, DB, Wave 0, and push are `DENY` |
| `next-slice-readiness-resolution` | PASS | Exact intent alias selects the minimum review closure while current authority stays `DENY` |
| `review-go-does-not-authorize` | PASS | Stage 4 review is GO; Development and Landing remain `DENY` |
| `stage4-stop-replay` | PASS | Future write envelope is closed; separate authority is required |

All six scenarios used the same live Authority Snapshot and Pay-Nexus source revision.

## Runtime Context and Friction

The six allowlisted project files total `197,540` bytes. The generated runtime surfaces are materially smaller:

| Runtime artifact | Bytes |
|---|---:|
| `resolved-task-context.md` | 1,273 |
| `repository-guidance.md` | 495 |
| generated `architecture-review/SKILL.md` | 2,162 |
| auditable `resolved-context.json` | 15,286 |

The compact task context plus guidance and generated Skill body total `3,930` bytes, while the larger JSON trace preserves auditability. This pilot did not need repo-local Skill installation to obtain the correct result.

One concrete friction signal was observed: projection freshness is intentionally bound to the exact `requestedOutput`. Replacing `read-only authority review` with the semantically narrower `authority routing review after technology selection closure` returned `resolution-context-drift`; reusing the saved exact request returned `fresh=true`. This is correct fail-closed behavior, but callers must reuse the locked request or explicitly rebuild and review a new projection.

The detailed technology-selection authorities were outside this pilot's allowlist. This review proves execution-authority routing after their projected closure; it does not independently review the selected technology choices. A future technology-decision review must explicitly register and authorize those inputs instead of silently broadening this pilot.

## Install and Zero-Write Verification

The corrected install planner used Pay-Nexus only as the live authority source and a disposable empty directory as the materialization target. It returned:

```text
mode = DRY_RUN
gate = PASS
actions = 1 CREATE .agents/skills/architecture-review/SKILL.md
collisions = 0
```

No apply operation was executed. The disposable target remained empty and was removed with `rmdir`. Pay-Nexus remained at the frozen HEAD/tree with no tracked worktree change. Because the live project target was deliberately not inspected, this plan does not claim live collision detection; it proves the proposed relative action only.

## Feedback Decision

No missing fact, conflicting project authority, unverifiable invariant, impossible lifecycle, ambiguous contract, or shared-capability defect was found. The exact-request friction and the fixed integration-routing defect are recorded here as pilot evidence, but neither justifies automatic Experience, Candidate, or Promotion creation.

## Recommendation and Stop Boundary

Keep Pay-Nexus on registration-plus-projection consumption. Do not install the generated Skill yet: the first real pilot produced the correct review with a compact context and zero project writes.

Stop after this Harness-owned report and its fixed-candidate verification. Separate user authority is required for any Skill materialization, Pay-Nexus modification, development, repeat Landing, Wave 0, DDL, formal database write, production operation, remote configuration, or push.
