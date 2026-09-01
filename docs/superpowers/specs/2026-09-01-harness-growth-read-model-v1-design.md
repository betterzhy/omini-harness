# Harness Growth Read Model v1 — Design Candidate

## Status

**Decision status:** ARCHITECTURE AND BOUNDARIES USER APPROVED

**Artifact status:** PENDING USER REVIEW

**Change class:** R2 cross-project Contract / Governance design

**Authoritative provider:** `omini-harness`

**Consumer:** Personal Agent Workbench through `HarnessEvolutionPort`
**Runtime behavior:** NOT IMPLEMENTED BY THIS DOCUMENT

This specification materializes the user-approved architecture and boundary decisions for measuring whether Harness capabilities actually improve across real projects and for exposing those facts to Personal Agent Workbench. The exact written artifact remains a candidate until the user reviews it. It extends the existing Growth Assessment Protocol (GAP) and governed learning flow; it does not create a second growth system.

Approval was granted for these boundaries:

1. Workbench may detect and present a growth gap, but it only creates a local `GrowthImprovementProposal`.
2. A user decision is required before any Candidate or Experiment command is submitted to `omini-harness`.
3. No component automatically promotes, releases, adopts, retires, or modifies a target project.
4. Real project evidence remains owned by the source project and Runtime.
5. `omini-harness` owns the authoritative growth lifecycle and the deterministic cross-project projection.

## 1. Problem

The current Harness has useful governed-learning primitives:

```text
Experience
-> explicit triage
-> Candidate
-> Eval Result
-> human-authorized Promotion
-> canonical capability and immutable promotion ledger
```

The approved GAP design adds a deterministic intake boundary:

```text
Project work
-> Growth Assessment
-> append-only Receipt
-> read-only Scan
-> human triage
-> optional UNTRIAGED Experience import
```

These mechanisms do not yet provide the complete product truth required by Workbench:

- no authoritative Experiment lifecycle;
- no unified Release projection tied to Candidate and Eval evidence;
- no versioned observation of each real project's declared, configured, loaded, invoked, and effective state;
- no `ObservedEffect` contract with a predeclared baseline, target, observation window, attribution, and evidence;
- no deterministic cross-project `growth-projection/v1`;
- no supported Workbench Adapter for Harness Evolution, Evaluation Ledger, or cross-project growth views.

Consequently, a green structural or adoption Gate cannot answer whether Harness growth meets expectations. Capability existence, release, project configuration, runtime loading, invocation, and measured effectiveness are separate facts.

## 2. Goals

1. Preserve one governed intake path: GAP Receipt -> triage -> Experience -> Candidate.
2. Define a complete, evidence-bound lifecycle from Candidate through Observed Effect and Retirement.
3. Let users determine which real project signals produced which Harness changes.
4. Show which projects declared, configured, loaded, invoked, and verified a particular Release.
5. Evaluate predeclared expectations without inventing a single Growth Score.
6. Retain failed experiments, regressions, counterexamples, and inconclusive evidence.
7. Produce a deterministic, versioned, read-only cross-project projection for Workbench.
8. Keep Workbench a projection, review, and routing layer rather than an authority for Harness facts.
9. Keep all formal improvement actions explicitly human-authorized and receipt-backed.

## 3. Non-goals

- Registering Project Helm as a governed Harness consumer merely because Workbench displays Harness data.
- Reordering or declaring PASS for any Project Helm W3, W4, H0, H1, or later delivery Gate.
- Rebuilding `omini-harness` inside Workbench.
- Automatically classifying every failure as reusable growth.
- Reading or storing raw conversations, prompts, responses, terminal logs, or project file bodies.
- Automatically creating a formal Candidate from a GAP Receipt.
- Automatically running Eval, publishing a Release, changing project configuration, or retiring a capability.
- Treating configured, loaded, invoked, or effective as synonyms.
- Replacing evidence with a blended Growth, Confidence, Hygiene, or Health score.
- Requiring native or legacy projects to adopt Harness before they can appear in Workbench.
- Introducing a server, database, scheduler, Hook, vector index, or semantic clustering before pilot evidence requires it.

## 4. Existing Contract Compatibility

The following existing contracts remain authoritative and are not renamed:

- `growth-assessment-request/v1`, `growth-assessment-receipt/v1`, `growth-capture-result/v1`, and `growth-scan-report/v1` from the approved GAP design;
- `experience/v1`;
- `candidate/v1`;
- `design-eval/v1`;
- `eval-result/v1`;
- canonical capability identity, semantic version, content hash, and promotion ledger rules;
- project registration, exact capability lock, integration, runtime projection, and adoption validation contracts.

New contracts extend this sequence. They do not reinterpret an existing `candidate/v1`, `eval-result/v1`, canonical Capability, or historical ledger entry, and they never mutate historical records to fit the new model. Specifically:

- an existing unbound `eval-result/v1` remains valid for the existing Candidate/Eval Promotion path but cannot establish Experiment PASS;
- a historical ledger-backed Capability with no trial or Promotion binding remains a Release with partial lineage, not a fabricated Experiment-backed Release;
- canonical `lifecycle` and `validity` remain the only Release availability source axes;
- no migration adds Experiment, Trial, Eval, or versioned supersession facts that the original bytes did not contain.

## 5. Architecture and Data Flow

```text
Real project task, failure, correction, or verified result
        |
        v
Existing GAP Assessment + append-only Receipt
        |
        v
Human triage
        |
        v
UNTRIAGED Experience
        |
        v
Candidate -> Growth Experiment / Trial-scoped Eval -> human Promotion
        |
        v
Canonical Capability + Promotion Ledger -> derived Release Projection
        |
        v
Project Adoption Observation
        |
        v
Loaded / Invoked / Observed Effect
        |
        v
omini-harness growth-projection/v1
        |
        v
Workbench HarnessEvolutionPort
        |
        v
Harness Evolution / Evaluation Ledger / Needs You
```

Workbench does not scan target repositories or infer source facts from arbitrary files. The Harness projection composes validated, source-owned facts and retains their provenance, freshness, and coverage.

### 5.1 Component boundaries

1. **GAP Intake** — existing governed assessment and append-only receipt boundary.
2. **Human Triage / Import Bridge** — converts an explicitly approved, sanitized Receipt into an `UNTRIAGED` Experience; dry-run by default.
3. **Growth Lifecycle** — owns Experiment decisions, Eval linkage, Release lineage, Revalidation, Supersession, and Retirement.
4. **Adoption Observation** — records immutable observations without editing target project configuration.
5. **Effect Evaluation** — compares source evidence against expectations frozen before the Experiment or adoption observation window.
6. **Growth Projection Builder** — deterministically emits one versioned cross-project read model.
7. **Workbench Adapter** — parses only supported projection versions and maps them to `HarnessEvolutionPort` ViewModels.
8. **Improvement Proposal Router** — holds a Workbench-local intent until user approval, then submits a versioned Harness command.

## 6. Authority and Ownership

| Fact or action | Authoritative owner | Workbench responsibility |
| --- | --- | --- |
| Project result, failure, verification, and Runtime evidence | Source project and Runtime | Link and display provenance |
| Growth Assessment Receipt | User-local Harness GAP Inbox | Display receipt identity and disposition |
| Experience and triage | `omini-harness` learning governance | Display and route review |
| Candidate | `omini-harness` | Render Candidate and evidence; never create a local formal Candidate |
| Experiment, Eval suite, Trial, and decision | `omini-harness` | Render hypothesis, gates, results, and pending decision |
| Canonical capability version and Release lineage | `omini-harness` | Display version, compatibility, rollback, and lifecycle |
| Project declaration and configuration | Target project | Display exact source Revision and evidence |
| Adoption registry and verification | `omini-harness` | Display registry state and reconciliation status |
| Loaded and Invoked observations | Runtime and target project evidence | Display observation time, provenance, and coverage |
| Observed Effect | Evidence producer; evaluated under Harness contract | Display expectation, result, attribution, and evidence |
| Cross-project Growth Projection | `omini-harness` | Cache with watermark; never become source authority |
| UI filters, selected object, and local proposal | Workbench | Own local state only |
| Candidate/Experiment submission decision | User plus `omini-harness` command authority | Capture intent and show authoritative receipt |

Project Authority always outranks an assessment or projection. A Workbench cache never becomes the authoritative version of a Harness or project fact.

## 7. New Domain Contracts

All new machine contracts use strict JSON Schema Draft 2020-12, `additionalProperties: false`, bounded strings and arrays, explicit schema versions, immutable identities, and exact source references.

### 7.1 Shared typed primitives

HG2 must first freeze shared strict primitives instead of letting each Schema invent its own null, time, evidence, or counting semantics:

- `AssetRevisionReference` binds `kind`, ID, Schema version, canonical source path, immutable Git Revision or ledger identity, canonical content digest, and domain-version availability. Existing `experience/v1` and `candidate/v1` records have no domain-version field, so their domain version is `NOT_AVAILABLE` with reason `SCHEMA_HAS_NO_DOMAIN_VERSION`; source identity plus content digest provides their exact snapshot and concurrency identity without changing either v1 payload.
- `CommandReference` binds command Schema version, command ID, IdempotencyKey, PayloadHash, canonical command digest, and durable journal identity. It never treats a human-readable command name as execution evidence.
- `LedgerEntryReference` binds ledger Schema version, canonical source path, immutable repository Revision or ledger identity, the `(capabilityId, version)` entry key, canonical entry digest, and enclosing ledger digest. The entry key must resolve exactly once.
- `ExpectationOwnerAnchor` binds only the logical owner kind, ID, and version. It never contains owner content digest, record revision, Git Revision, ledger identity, or another `AssetRevisionReference`.
- `ExecutionCohortIdentity` binds an exact Project reference; a target kind `PROPOSED_CAPABILITY | RELEASE` plus exact target reference; source commit and tree; Authority Snapshot fingerprint; capability-lock fingerprint; Runtime identity/profile/toolchain digest; model identity/configuration digest; and projection schema/builder/input digest. A not-applicable dimension uses an explicit typed state and reason. `cohortKey` is `sha256:` of its `canonical_json_bytes`. Trial Attempts require `PROPOSED_CAPABILITY`; Adoption Observations and Effects require `RELEASE`.
- `Availability<T>` is a discriminated union: `PRESENT` requires `value`; `NOT_AVAILABLE` or `UNKNOWN` requires a bounded reason and forbids `value`.
- `EvidenceReference` binds source kind, visibility, opaque reference, digest, source Revision, observation time, and replayability. It never embeds an evidence body.
- `Freshness` is `CURRENT | STALE | UNKNOWN` and carries `observedAt`, the applicable freshness deadline when known, and a reason for non-current states.
- `Coverage` is `COMPLETE | PARTIAL | NONE | UNKNOWN` and carries numerator, denominator, unknown count, population definition, and exclusions when a count is meaningful.
- `TypedValue` is a discriminated `BOOLEAN | DECIMAL | ENUM | GATE` value. A decimal is a canonical decimal string plus an exact unit; v1 performs no implicit unit conversion.
- Every timestamp is normalized RFC 3339 UTC. Every identity, enum, decimal, array bound, and free-text length is schema-bounded.

An unavailable value is never encoded as an empty string, zero, false, an epoch timestamp, or a fabricated identity.

#### 7.1.1 Existing `bootstrap-baseline/v1` read profile

HG2 freezes a strict read Schema for the existing canonical `core/governance/bootstrap-baseline.yaml` bytes; it does not rewrite or create a second baseline. The closed Schema has `additionalProperties: false` and exactly these required fields:

```text
schemaVersion = bootstrap-baseline/v1
baselineVersion
bootstrapBaselineDate
governanceBeginsAfter
authorizedSeeds[]
```

`baselineVersion` is SemVer, `bootstrapBaselineDate` is an ISO date, and `governanceBeginsAfter` is an RFC 3339 UTC timestamp whose calendar date is not earlier than the baseline date. Each `authorizedSeeds[]` element is a canonical `capabilityId@semanticVersion` key; keys are unique and duplicate or malformed entries invalidate the baseline. A Projection invocation accepts exactly one baseline at the canonical path and binds its exact bytes through `bootstrapBaselineReference: AssetRevisionReference`, including source Git Revision and content digest.

The baseline is a closed historical authority boundary. Its accepted bytes must agree with the existing governance validator and every matching ledger entry must have `authorization: BOOTSTRAP_AUTHORIZED`, `authorityDecision: CLOSED_BASELINE_BOOTSTRAP`, a matching content hash, and `authorizedAt <= governanceBeginsAfter`. A changed digest at the same baseline version, a second baseline, a post-cutoff seed, or an unlisted tuple is invalid and makes the projection Gate `NO_GO`. A future baseline version or authority mechanism requires a separately approved contract change; the builder never infers one from later canonical assets or ledger text.

### 7.2 `growth-expectation/v1`

This immutable contract is the authority for both Experiment-level and Release-level expectations. An `ObservedEffect` never points to an unversioned label.

Required fields:

```text
schemaVersion
expectationId
version
ownerAnchor
name
requirement
measurement
baselineDefinition
target
comparison
observationWindow
sampleContract
freshnessContract
coverageContract
protectedClass
freeze
evidence[]
```

`ownerAnchor` is an `ExpectationOwnerAnchor` for one Experiment definition version or one Release identity. The only digest edge points from the owner record to `expectationReferences[]`; each reference binds Expectation ID, version, and definition digest. The Expectation points back only to the digest-free logical anchor. Validation requires exact anchor equality and rejects unreferenced orphan Expectations, so ownership remains bidirectionally checkable without a digest cycle.

`requirement` is `REQUIRED | OPTIONAL`. `measurement` fixes value kind and unit; `comparison` is `EQUAL | IN_SET | AT_LEAST | AT_MOST | PASS`. `sampleContract` fixes the eligible population, minimum sample, exclusions, and aggregation rule. `freeze` records `FROZEN`, time, actor reference, authority reference, and the canonical definition digest. That digest is `sha256(canonical_json_bytes(expectation with freeze.definitionDigest omitted))`; it never hashes itself.

An Experiment-owned expectation must be frozen before that Experiment enters `AUTHORIZED`. A Release-owned expectation must be frozen by an explicit Harness authority decision before its first adoption observation window begins. Changing its target, direction, unit, sample, freshness, coverage, protected class, or window creates a new expectation version; no prior effect is recomputed under the new definition.

### 7.3 `growth-experiment/v1`

Required fields:

```text
schemaVersion
experimentId
version
recordRevision
previousRecordDigest
previousExperimentVersionReference
candidateReference
targetCapability
hypothesis
scope
baseline
expectationReferences[]
evalRequirements[]
trialPlan
trialAttemptReferences[]
regressionCriteria[]
safetyCriteria[]
recoveryCriteria[]
status
authorityDecision
evidence[]
createdAt
stateEnteredAt
```

`targetCapability` binds capability ID, proposed or released version, projection version where applicable, Runtime, and model sensitivity. `scope` names eligible projects or canary classes without copying project truth. Every expectation reference binds exact ID, version, and digest. Experiment `evalRequirements[]` is a nonempty array whose entries contain an exact `evalDefinitionReference: AssetRevisionReference`; entries are unique by Eval ID and definition digest. The array freezes the exact Eval Definition bytes when the Experiment becomes `AUTHORIZED`, not merely logical Eval IDs. Every terminal Trial must account for this exact reference set without substitution. Existing Candidate/Eval records remain on their unchanged ID-based path and are not rewritten.

`authorityDecision` is a discriminated object with `PENDING | APPROVE | REJECT`. `APPROVE` and `REJECT` require actor, decision time, authority reference, reason, and decision digest; `PENDING` forbids fabricated decision fields. `DRAFT` and `AWAITING_AUTHORITY` require `PENDING`; `AUTHORIZED`, `RUNNING`, `EVIDENCE_READY`, `PASSED`, `FAILED`, and `INCONCLUSIVE` require `APPROVE`; `REJECTED` requires `REJECT`; `CANCELLED` retains the decision state in force when cancellation occurred. Authorization is not inferred from status text.

Experiment status:

```text
DRAFT
AWAITING_AUTHORITY
AUTHORIZED
RUNNING
EVIDENCE_READY
PASSED
FAILED
INCONCLUSIVE
REJECTED
CANCELLED
```

`version` and `recordRevision` are positive integers. `previousRecordDigest` has type `Availability<Digest>` and `previousExperimentVersionReference` has type `Availability<AssetRevisionReference>`; HG2 encodes both with discriminated `oneOf` branches. Storage is append-only by `(experimentId, version, recordRevision)`. For `recordRevision = 1`, `previousRecordDigest` must be `NOT_AVAILABLE` with reason `FIRST_RECORD_REVISION`; every later record requires `PRESENT` with the exact prior digest. For `version = 1`, `previousExperimentVersionReference` must be `NOT_AVAILABLE` with reason `FIRST_EXPERIMENT_VERSION`; every later definition version requires `PRESENT` with an `AssetRevisionReference` to the terminal record of the immediately prior version. The projection selects the unique highest valid version and record revision. Definition fields become immutable at `AUTHORIZED`. A later change to hypothesis, scope, expectation, Eval requirement, protected criterion, or trial plan creates a new linked Experiment version. A rerun creates a new Trial Attempt reference and never overwrites an earlier result.

`PASSED` requires at least one single terminal Trial Attempt that itself satisfies the complete PASS rule below. The Experiment's qualifying Trial, complete receipt set, Eval Results, cohort, and protected-criterion results must all come from that same `trialAttemptReference`; facts from different Trials can never be combined to establish PASS. An unbound `eval-result/v1` can never establish Experiment PASS. `FAILED`, `INCONCLUSIVE`, `REJECTED`, and `CANCELLED` remain immutable historical outcomes.

#### 7.3.1 `growth-trial-attempt/v1`

A Trial Attempt is an immutable execution cohort for one authorized Experiment definition. Required fields:

```text
schemaVersion
trialAttemptId
recordRevision
previousRecordDigest
experimentReference
candidateReference
executionCohortIdentity
cohortKey
evalExecutionReceiptReferences[]
evalCoverage
protectedCriterionResults[]
state
outcome
cancellationDecision
openedAt
closedAt
stateEnteredAt
evidence[]
```

`recordRevision` and `previousRecordDigest` use the same first-record/later-record `Availability<Digest>` rule as Experiment. `state` is `AUTHORIZED | RUNNING | EVIDENCE_READY | TERMINAL`. `outcome` has type `Availability<PASS | FAIL | INCONCLUSIVE | CANCELLED>` and `closedAt` has type `Availability<Timestamp>`. HG2 encodes their relationship as a closed `oneOf`: `AUTHORIZED`, `RUNNING`, and `EVIDENCE_READY` require both fields to be `NOT_AVAILABLE`; `TERMINAL` requires both fields to be `PRESENT`. Pre-evidence states may have an empty receipt array. State transitions create append-only revisions and are compare-and-swap protected. `experimentReference`, `candidateReference`, and the `PROPOSED_CAPABILITY` target must match the enclosing Experiment exactly. The exact referenced Experiment revision must carry an `APPROVE` authority decision before the first Trial revision; the Trial inherits that authority and never stores a second mutable approval verdict. The cohort identity is frozen before `RUNNING`; changing Revision, lock, Runtime, model, projection, or toolchain creates another Trial Attempt.

`evalCoverage` is a closed ledger over the Experiment's frozen exact Eval Definition reference set: it records the required count, exactly matched count, missing references, duplicate references, unexpected references, and `COMPLETE | PARTIAL | INVALID`. A receipt counts only when its `evalDefinitionReference` exactly equals one frozen entry, including source Revision and content digest; matching only Eval ID is insufficient. `protectedCriterionResults[]` accounts for every frozen Regression, Safety, and Recovery criterion by exact criterion reference and records `PASS | FAIL | UNKNOWN` with evidence. Neither object is a caller-supplied verdict; both are deterministically derived from validated Trial receipts and criterion evidence.

`cancellationDecision` has type `Availability<CancellationDecision>`. Its `PRESENT` branch requires action `CANCEL_TRIAL`, actor, decision time, authority reference, bounded reason, and decision digest; the `NOT_AVAILABLE` branch forbids those fields. It must be `NOT_AVAILABLE` for every nonterminal revision and for terminal PASS, FAIL, or INCONCLUSIVE. It is `PRESENT` if and only if terminal outcome is CANCELLED. A cancellation transition is rejected when already-durable Trial evidence establishes FAIL; compare-and-swap prevents a second terminal outcome.

The terminal Trial outcome is derived by the first matching rule after schema, digest, reference, and cohort validation:

1. `FAIL` when any required Eval Result is `FAIL` or any protected Regression, Safety, or Recovery criterion is `FAIL`. This takes precedence over a later cancellation request. Early termination is allowed, but missing coverage remains explicit and the Trial can never be reported as PASS.
2. `CANCELLED` only when an explicit authorized cancellation transition exists and no FAIL evidence exists. It preserves all accumulated receipts and coverage and cannot satisfy Experiment PASS.
3. `PASS` if and only if `evalCoverage` is `COMPLETE`, every required Eval has exactly one unique execution receipt bound to this Trial and the same `cohortKey`, every referenced exact Eval Result is `PASS`, no unexpected or reused result exists, and every protected criterion is accounted for as `PASS`.
4. `INCONCLUSIVE` when no FAIL exists but any required receipt or criterion is missing or unavailable, any required Eval Result is `INCONCLUSIVE`, or any protected criterion is `UNKNOWN`.

No stored `outcome` overrides this derivation: disagreement is an invalid Trial record and makes the projection Gate `NO_GO`. An Experiment can become `PASSED` only from a terminal Trial that satisfies the complete PASS rule above.

#### 7.3.2 `growth-eval-execution-receipt/v1`

The existing `eval-result/v1` remains valid and unchanged. This new append-only receipt proves that exact Eval Result bytes were produced for a particular Trial rather than later attached to it.

Required fields:

```text
schemaVersion
executionReceiptId
executionCommandReference
executionNonce
trialAttemptReference
experimentReference
candidateReference
evalDefinitionReference
evalResultReference
targetCapabilityReference
executionCohortIdentity
cohortKey
startedAt
completedAt
evidence[]
```

The trial-scoped execution command must exist before `startedAt` and bind the nonce, Experiment, Trial, Candidate, exact Eval Definition reference, target Capability, and cohort. The receipt's `evalDefinitionReference` must exactly equal one entry frozen in the authorized Experiment; Eval ID equality alone is insufficient. The exact `eval-result/v1` reference binds canonical bytes and must match Eval ID, Capability ID/version, projection version, Runtime, model, result, and execution interval. One Eval Result digest may satisfy at most one Trial receipt. Existing manual or fixture results without this receipt remain usable by the existing Candidate/Eval Promotion path but cannot establish Experiment PASS.

#### 7.3.3 `promotion-lineage-binding/v1`

This append-only evidence record proves which exact governed evidence a future Promotion command consumed. It supplements but never replaces the existing promotion ledger.

Required fields:

```text
schemaVersion
bindingId
bindingKind
candidateReference
experimentReference
qualifyingTrialAttemptReference
trialAttemptReferences[]
evalExecutionReceiptReferences[]
legacyEvalResultReferences[]
capabilityReference
lineageIntentDigest
promotionCommandReference
ledgerEntryReference
coverage
evidence[]
```

`bindingKind` is `EXPERIMENT_BACKED | CANDIDATE_EVAL_BACKED`. `candidateReference` and `capabilityReference` have type `AssetRevisionReference`. `experimentReference` and `qualifyingTrialAttemptReference` have type `Availability<AssetRevisionReference>` with closed `PRESENT` and `NOT_AVAILABLE` `oneOf` branches. `trialAttemptReferences[]`, `evalExecutionReceiptReferences[]`, and `legacyEvalResultReferences[]` contain exact `AssetRevisionReference` values and reject duplicate `(kind, ID, contentDigest)` keys or two digests for the same record revision. `promotionCommandReference` has type `CommandReference`; `ledgerEntryReference` has type `LedgerEntryReference`. Before Promotion, the command binds a canonical lineage-intent object and its digest. The lineage binding must reproduce that exact intent field-for-field and references the command, canonical Capability, and ledger entry. The terminal Promotion Receipt is the final commit marker: it binds the same intent digest, exact binding digest, canonical Capability content hash, and ledger-entry digest. The binding never references the terminal Receipt, so the hash graph and publication order are acyclic.

The future Promotion operation uses one durable journaled transaction boundary. It stages canonical Capability bytes, the unique ledger entry, and lineage binding, then publishes the terminal Receipt/transaction marker last. It emits `SUCCEEDED` only after all are durable and mutually valid. Interruption before that point yields `UNKNOWN_OUTCOME` or `RECOVERY_REQUIRED`; the projection rejects partial artifacts, and recovery never guesses completion or deletes prior evidence.

For `EXPERIMENT_BACKED`, exactly one terminal PASSED Experiment and one PRESENT qualifying PASSED Trial are required. Every required Eval must have a unique matching PASS Eval Execution Receipt for that same Trial and cohort; other Trial references are historical context only and cannot fill its coverage. `legacyEvalResultReferences[]` is empty. For `CANDIDATE_EVAL_BACKED`, `experimentReference` and `qualifyingTrialAttemptReference` are `NOT_AVAILABLE`, Trial and execution-receipt arrays are empty with explicit not-applicable coverage, while exact PASS legacy Eval Result references satisfy the existing Candidate requirements. In both cases Candidate proposed Capability, Eval targets, canonical Capability, ledger tuple, and Receipt must agree on Capability ID/version/content hash. Any mismatch, duplicate ledger tuple, reused trial result, missing Promotion Receipt, or ambiguous reference makes the binding invalid. The binding's canonical digest is carried by its `AssetRevisionReference`, not embedded recursively in the record.

Current `candidate/v1`, `eval-result/v1`, and historical `promotion-ledger/v1` entries are never rewritten. A historical Promotion with no valid binding remains a real ledger-backed Release with explicit partial lineage; it can never be relabeled `EXPERIMENT_BACKED`. HG3 must add the trial-scoped execution and Promotion receipt path before any new Experiment-backed claim is possible.

### 7.4 `growth-release-projection/v1`

This is a pure derived record over a canonical Capability version and its unique matching promotion-ledger entry. The builder accepts no independently editable Release input and owns no lifecycle transition.

Required fields:

```text
schemaVersion
releaseId
capabilityReference
ledgerEntryReference
promotionReceiptReference
promotionPath
lineageBindingReference
bootstrapBaselineReference
sourceCandidateReferences[]
sourceExperimentReferences[]
trialAttemptReferences[]
evalResultReferences[]
expectationReferences[]
lineageCoverage
compatibility
rollback
canonicalLifecycle
canonicalValidity
availability
supersession
releasedAt
evidence[]
```

`promotionPath` is:

```text
EXPERIMENT_BACKED
CANDIDATE_EVAL_BACKED
HISTORICAL_PROMOTION_PARTIAL
BOOTSTRAP_AUTHORIZED
```

`releaseId` is a stable encoding of `sha256(canonical_json_bytes({capabilityId, capabilityVersion, contentHash, ledgerEntryDigest}))`. The canonical asset and exactly one ledger entry must agree on Capability ID/version/content hash; otherwise no Release is emitted and the projection Gate is `NO_GO`.

`capabilityReference` and every source Candidate, Experiment, Trial, Eval Result, and Expectation array element have type `AssetRevisionReference`; each array rejects duplicate identity/digest keys. `ledgerEntryReference` has type `LedgerEntryReference`. `lineageBindingReference`, `promotionReceiptReference`, and `bootstrapBaselineReference` each have type `Availability<AssetRevisionReference>` with closed `PRESENT` and `NOT_AVAILABLE` `oneOf` branches. `EXPERIMENT_BACKED` requires PRESENT lineage and Receipt references and a NOT_AVAILABLE bootstrap reference, with a valid binding plus terminal Receipt whose bound lineage intent consumed a PASSED Experiment and its exact same-Trial Eval receipts. `CANDIDATE_EVAL_BACKED` has the same reference availability but consumes a valid non-Experiment binding and terminal Receipt. A valid historical `PROMOTED` ledger entry without that binding/Receipt is `HISTORICAL_PROMOTION_PARTIAL` and requires all three references to be `NOT_AVAILABLE` with path-specific reasons. A PASSED Experiment, lineage binding, or Promotion Receipt without the canonical asset and existing ledger entry never creates a Release.

`BOOTSTRAP_AUTHORIZED` is selected only when all of the following exact sources agree: the ledger entry has `authorization: BOOTSTRAP_AUTHORIZED` and `authorityDecision: CLOSED_BASELINE_BOOTSTRAP`; its tuple and content hash match the canonical Capability; and the tuple appears exactly once in `authorizedSeeds[]` of the immutable `bootstrap-baseline/v1` referenced by PRESENT `bootstrapBaselineReference`. Its lineage and Promotion Receipt references are `NOT_AVAILABLE` with `CUTOFF_BOOTSTRAP_HAS_NO_PROMOTION_BINDING`. A claimed bootstrap entry absent from that baseline, a baseline duplicate, or any disagreement is invalid, emits no Release, and makes the projection Gate `NO_GO`.

Promotion-path selection is mutually exclusive and ordered: a validated bootstrap tuple selects `BOOTSTRAP_AUTHORIZED`; a `PROMOTED` ledger entry with one valid Experiment binding and Receipt selects `EXPERIMENT_BACKED`; a `PROMOTED` entry with one valid Candidate/Eval binding and Receipt selects `CANDIDATE_EVAL_BACKED`; an otherwise valid historical `PROMOTED` entry with neither selects `HISTORICAL_PROMOTION_PARTIAL`. Multiple matching bindings, contradictory authorization markers, or any other authorization value are projection errors, never tie-broken guesses.

`lineageCoverage` is a typed object with `COMPLETE | PARTIAL | NOT_APPLICABLE | UNKNOWN`, explicit missing kinds, and reason. Empty Experiment/Trial references are valid for non-Experiment paths only; historical references that cannot be reconstructed remain partial rather than guessed. `compatibility` and `rollback` are typed availability objects sourced only from explicit canonical or Promotion evidence; absence in current v1 contracts is `NOT_AVAILABLE`, not an invented default.

A historical ledger `sourceReference` such as `candidate://...` may be shown as opaque ledger evidence, but it is not promoted to an `AssetRevisionReference` unless the exact historical bytes, Revision, and digest are independently available. The current file with the same Candidate ID is never assumed to be the historical snapshot.

The projection exposes the canonical source axes without renaming them:

```text
canonicalLifecycle = EXPERIMENTAL | ACTIVE | DEPRECATED | RETIRED
canonicalValidity  = VALID | QUESTIONED | INVALID
```

`availability.state` is derived by the first matching rule:

| Priority | Canonical condition | Derived state |
| ---: | --- | --- |
| 1 | lifecycle `RETIRED` | `RETIRED` |
| 2 | validity `INVALID` | `INVALID` |
| 3 | validity `QUESTIONED` | `QUESTIONED` |
| 4 | lifecycle `DEPRECATED` and validity `VALID` | `DEPRECATED` |
| 5 | lifecycle `EXPERIMENTAL` and validity `VALID` | `EXPERIMENTAL` |
| 6 | lifecycle `ACTIVE` and validity `VALID` | `ACTIVE` |

Only `ACTIVE` is eligible for the current resolver/catalog. The derived state does not authorize any canonical change. In particular `INVALID` is not Retirement, and the projection cannot turn a proposal into `RETIRED`.

`supersession` is a separate derived object with `NONE | PARTIAL | SUPERSEDED | CONFLICT | UNKNOWN`, exact source references, and coverage. Existing `relationships.supersedes` carries only Capability ID, not version; it remains `PARTIAL` with reason `UNVERSIONED_V1_RELATIONSHIP` and cannot mark a particular Release `SUPERSEDED`. Only a future explicit version-bound relation can do so. Retirement and supersession never delete Release, adoption, effect, negative, or lineage history.

### 7.5 `growth-project/v1`

This contract makes a real project visible independently of whether an observation exists for a particular Release.

Required fields:

```text
schemaVersion
projectId
relationship
sourceIdentity
authoritySnapshot
registrationReference
visibility
freshness
coverage
evidence[]
```

`relationship` is `REGISTERED | DISCOVERED_NATIVE | UNREGISTERED | UNKNOWN`. `sourceIdentity`, `authoritySnapshot`, and `registrationReference` use `Availability<T>`. A native or legacy project can therefore appear without invented Harness files. Project absence from a Harness registry is not failure and is not itself a Release-specific `NOT_ADOPTED` observation. A Project record may originate only from explicit registration, a configured project catalog, or a separately authorized discovery receipt; the projection never crawls arbitrary filesystem roots to discover projects.

### 7.6 `project-adoption-observation/v1`

An adoption observation is immutable evidence about one project and one Release at one source/Runtime identity. It never edits project configuration.

Required fields:

```text
schemaVersion
observationId
executionCohortIdentity
cohortKey
declared
configured
loaded
invoked
reconciliation
observedAt
freshness
coverage
evidence[]
```

The Cohort Identity is the only source for Project, `RELEASE` target, Revision, Authority Snapshot, lock, Runtime, model, and projection identity. The observation does not carry parallel editable copies. Its `cohortKey` must recompute exactly; a collision or mismatch is invalid.

Each adoption axis is an independent typed object with:

```text
state
expectedReleaseReference
observedVersion
observedAt
freshness
coverage
evidence[]
reasonCodes[]
```

Axis state is `MATCHED | NOT_PRESENT | DIVERGED | STALE | UNKNOWN | NOT_APPLICABLE`. `MATCHED` requires exact Release identity and evidence. `NOT_PRESENT` requires evidence that the supported check found no declaration, configuration, load, or invocation; it is not the same as missing evidence. `DIVERGED` requires both expected and observed identities. No later axis can be inferred from an earlier one.

`reconciliation.state` is `CONSISTENT | NOT_ADOPTED | DIVERGED | PARTIAL | STALE | UNKNOWN` and is deterministically derived from all four axes under a versioned rule identifier. It is not a fifth source fact. A discovered project with no Release-specific check appears only in `projects[]`; when an authorized read-only check proves that a Release is absent, a Release-bound observation may report `NOT_ADOPTED`.

### 7.7 `observed-effect/v1`

Required fields:

```text
schemaVersion
effectId
executionCohortIdentity
cohortKey
experimentReference
expectationReference
baseline
target
observationWindow
observedValue
sample
outcome
attribution
evaluationRuleId
evaluatorIdentity
freshness
coverage
evidence[]
observedAt
```

`executionCohortIdentity` must be byte-identical to the Adoption Observation cohort used for this Effect, and `cohortKey` must recompute exactly. `experimentReference` uses `Availability<AssetRevisionReference>`. A non-Experiment promotion may use `NOT_AVAILABLE` with reason `PROMOTION_PATH_HAS_NO_EXPERIMENT`; it cannot satisfy a criterion that explicitly requires complete Experiment provenance. `expectationReference` is always `PRESENT` and binds the exact frozen `growth-expectation/v1` version and digest.

`baseline`, `target`, and `observedValue` use `TypedValue` or a typed unavailable variant. Their value kind and unit must match the referenced expectation exactly. `observationWindow` and `sample` bind the frozen Expectation window/population/sample-contract digest; `sample` records eligible count, observed count, minimum count, exclusions, aggregation rule, and `ADEQUATE | INADEQUATE | UNKNOWN`. Freshness and coverage follow Section 7.1; v1 performs no implicit unit, timezone, population, denominator, Revision, Runtime, model, or projection conversion.

Effect outcomes:

```text
MEETS_EXPECTATION
BELOW_EXPECTATION
REGRESSION
INCONCLUSIVE
NOT_OBSERVED
STALE
UNKNOWN
```

Attribution values:

```text
SUPPORTED
CONFOUNDED
UNKNOWN
```

`evaluationRuleId` fixes the outcome algorithm; `evaluatorIdentity` binds its schema and toolchain identity. A rule upgrade creates a new Effect record and never rewrites the prior outcome. `MEETS_EXPECTATION` requires a frozen expectation, matching typed values, current evidence, adequate sample, sufficient coverage, `SUPPORTED` attribution, and no protected Regression, Safety, or Recovery failure. `NOT_OBSERVED` requires unavailable observed value with a reason. Inadequate sample produces `INCONCLUSIVE`; stale evidence produces `STALE`; unknown value or denominator produces `UNKNOWN`. Missing values never become zero or success.

### 7.8 `growth-project-release-view/v1`

This strict object is a deterministic view over Project, Release, Adoption Observation, Expectation, and Effect records. It is never stored as separately editable truth.

Required fields:

```text
schemaVersion
executionCohortIdentity
cohortKey
asOf
adoptionObservationReferences[]
effectReferences[]
declared
configured
loaded
invoked
effective
reconciliation
freshness
coverage
evaluationRuleId
```

The builder emits one view per unique valid `cohortKey`; `(projectId, releaseId)` alone is not a view identity. A query without a cohort key returns all context rows. A singular query is allowed to omit the key only when exactly one cohort exists; otherwise it returns `UNKNOWN` with `AMBIGUOUS_CONTEXT_COHORT` and never chooses latest globally.

The four adoption summaries use axis states `MATCHED | NOT_PRESENT | DIVERGED | STALE | CONFLICT | UNKNOWN | NOT_APPLICABLE`. The rule considers only whole Adoption Observations whose Cohort Identity is byte-identical to the view, at or before `asOf`. It selects one greatest `observedAt` observation for all four axes together and:

1. returns `UNKNOWN` when none exists;
2. uses the sole latest value when one exists;
3. deduplicates byte-identical latest values while retaining every reference; or
4. returns `CONFLICT` when equally latest values disagree.

Each axis summary copies its state from that one selected observation and contains the selected observation reference plus same-cohort last-known evidence. Axes are never selected independently across observations. A newer `UNKNOWN` or `STALE` remains current; an older same-cohort present value may be shown only as last-known evidence. A record from another Revision, Authority Snapshot, lock, Runtime, model, projection, or toolchain remains in its own cohort and can never fill a missing axis. Equal-time disagreeing same-cohort observations produce `CONFLICT`; a claimed identical cohort key with different identity bytes is a projection `NO_GO` integrity error. `reconciliation` uses the selected observation and has state `CONSISTENT | NOT_ADOPTED | DIVERGED | PARTIAL | STALE | CONFLICT | UNKNOWN`.

`effective.state` is:

```text
VERIFIED_EFFECTIVE
BELOW_EXPECTATION
REGRESSION
INCONCLUSIVE
NOT_OBSERVED
STALE
CONFLICT
UNKNOWN
```

The required population is the Release's exact `expectationReferences[]` entries whose referenced expectation has `requirement: REQUIRED`. For each required expectation, the rule selects only Effects with the exact view Cohort Identity and frozen window/sample-contract digest, then chooses the latest valid Effect at or before `asOf`; equally latest disagreeing Effects produce `CONFLICT`. No cross-cohort fallback is allowed. No required expectation produces `UNKNOWN` with reason `NO_REQUIRED_EFFECT_EXPECTATIONS` rather than success.

The fail-closed summary precedence is `REGRESSION`, `CONFLICT`, `BELOW_EXPECTATION`, `UNKNOWN`, `STALE`, `INCONCLUSIVE`, `NOT_OBSERVED`, then `VERIFIED_EFFECTIVE`. `VERIFIED_EFFECTIVE` additionally requires all four adoption axes to be `MATCHED` and every context dimension required by the observation/expectation profile to be exact; an explicitly `NOT_APPLICABLE` dimension is allowed only when that same frozen profile permits it. Optional expectations remain visible but do not establish the summary. `freshness` is the least-current selected source state (`UNKNOWN`, then `STALE`, then `CURRENT`); `coverage` retains explicit counts and unknowns rather than averaging percentages. `evaluationRuleId` is fixed to `growth-project-release-view/v1` for this version.

### 7.9 `growth-projection/v1`

Required top-level fields:

```text
schemaVersion
asOf
toolchainIdentity
watermark
sourceIdentities[]
providerState
expectations[]
candidates[]
experiments[]
trialAttempts[]
evalExecutionReceipts[]
promotionLineageBindings[]
releases[]
projects[]
adoptionObservations[]
effects[]
projectReleaseViews[]
counts
gate
```

`asOf` is a caller-supplied, normalized UTC cutoff; no wall-clock generation timestamp is embedded in projection bytes. Build execution time belongs in a non-authoritative command receipt. `watermark` is `sha256:` of the existing `canonical_json_bytes` representation of `{schemaVersion, asOf, toolchainIdentity, orderedSourceIdentityManifest}`. The manifest binds every validated source kind, ID, Schema version, domain-version availability, Revision or ledger identity, and content digest. The watermark is computed before and independently of the projection object, so it is not circular.

Canonical output uses the repository's existing `canonical_json_bytes` algorithm plus one newline. Arrays use these stable keys:

- expectations: `(expectationId, version)`;
- candidates: `(candidateId, canonicalCandidateBundleDigest)`;
- experiments: `(experimentId, version, recordRevision)`;
- Trial Attempts: `(experimentId, experimentVersion, trialAttemptId, recordRevision)`;
- Eval Execution Receipts: `(trialAttemptId, evalId, executionReceiptId)`;
- Promotion Lineage Bindings: `(capabilityId, capabilityVersion, bindingId)`;
- releases: `(capabilityId, capabilityVersion, releaseId)`;
- projects: `projectId`;
- adoption observations: `(projectId, releaseId, cohortKey, observedAt, observationId)`;
- effects: `(projectId, releaseId, cohortKey, expectationId, observedAt, effectId)`;
- project-release views: `(projectId, releaseId, cohortKey)`;
- Evidence References and Source Identities: their immutable reference tuple.

All set-like nested arrays are sorted by their declared immutable reference key. An order-significant array must carry an explicit ordinal and sort by `(ordinal, immutable reference key)`; filesystem enumeration order is never semantic.

For identical validated source bytes, `asOf`, schema set, and toolchain identity, the output is byte-identical. `counts` and `projectReleaseViews` are deterministic derived data and never replace their source objects. A project-release view keeps `declared`, `configured`, `loaded`, `invoked`, and `effective` separate; `effective` is derived only from referenced Effect outcomes, while reconciliation retains its rule ID and source references.

`providerState` is a strict object:

```text
state
reasonCodes[]
sourceCoverage
requiredSourceKinds[]
unavailableSourceKinds[]
staleSourceKinds[]
invalidSourceCount
ruleId
```

`state` is `READY | PARTIAL | STALE | UNAVAILABLE | UNKNOWN`; `ruleId` is `growth-projection-provider-state/v1`. Source-kind arrays are sorted unique enums from the builder profile. The first matching rule wins: required configured provider unreadable/unverifiable -> `UNAVAILABLE`; required identity, availability, Schema set, or cutoff unknowable -> `UNKNOWN`; required usable source past its deadline -> `STALE`; known incomplete coverage, omitted optional source, or known nonfatal gap -> `PARTIAL`; otherwise complete/current/valid -> `READY`. Priority is therefore `UNAVAILABLE`, `UNKNOWN`, `STALE`, `PARTIAL`, `READY`.

`counts` is a closed `growth-projection-counts/v1` ledger, not a dynamic map. It contains:

```text
ruleId
sourceIdentities { total, valid, invalid, unavailable }
records {
  expectations, candidates, experiments, trialAttempts,
  evalExecutionReceipts, promotionLineageBindings, releases,
  projects, adoptionObservations, effects, projectReleaseViews
}
projectReleaseViewsByEffectiveState {
  VERIFIED_EFFECTIVE, BELOW_EXPECTATION, REGRESSION, INCONCLUSIVE,
  NOT_OBSERVED, STALE, CONFLICT, UNKNOWN
}
projectReleaseViewsByReconciliationState {
  CONSISTENT, NOT_ADOPTED, DIVERGED, PARTIAL, STALE, CONFLICT, UNKNOWN
}
projectCoverage
```

Every enum bucket is present even when zero. Each record count equals its array length; each view-bucket sum equals `projectReleaseViews`; source total equals valid plus invalid plus unavailable. Context rows are counted separately from unique projects, and `projectCoverage` supplies the exact unique-project denominator and unknown count.

`gate` is:

```text
state = PASS | NO_GO
reasonCodes[]
ruleId = growth-projection-gate/v1
```

The fixed `NO_GO` reasons are `REQUIRED_PROVIDER_UNAVAILABLE | REQUIRED_SOURCE_UNKNOWN | SOURCE_IDENTITY_CONFLICT | SOURCE_SCHEMA_INVALID | SOURCE_CUTOFF_INVALID | COHORT_IDENTITY_MISMATCH | CROSS_REFERENCE_INVALID | DIGEST_INVALID | DERIVATION_INVARIANT_VIOLATION`. Gate is `NO_GO` exactly when provider state is `UNAVAILABLE` or `UNKNOWN`, `invalidSourceCount > 0`, or any listed identity, Schema, cutoff, cohort, cross-reference, digest, count, or derivation invariant fails. Otherwise it is `PASS`.

Known `STALE` or `PARTIAL` data may produce a structurally valid `PASS` projection so Workbench can display the degraded truth; `PASS` never means a Release is adopted or effective. Every aggregate includes explicit denominators and coverage. Unknown or unavailable projects are reported separately and never counted as failed, zero, adopted, or effective.

### 7.10 Workbench-local `GrowthImprovementProposal`

This object is intentionally not a formal Harness object. Its Schema uses discriminated `oneOf` branches rather than making decision and receipt fields universally required.

Common required fields:

```text
proposalId
subjectReference
detectedOutcome
expectationReferences[]
evidenceReferences[]
suggestedAction
state
createdAt
```

Suggested actions:

```text
CREATE_CANDIDATE
CREATE_EXPERIMENT
REVISE_EXPERIMENT
RERUN_EXPERIMENT
REVALIDATE
NARROW_SCOPE
SUPERSEDE
RETIRE
```

States:

```text
DRAFT
NEEDS_USER
APPROVED
REJECTED
SUBMITTED
UNKNOWN_OUTCOME
CONFIRMED
```

State conditions:

- `DRAFT` and `NEEDS_USER` forbid `userDecision` and `submission`.
- `APPROVED` and `REJECTED` require an immutable `userDecision`; `REJECTED` forbids `submission`.
- `SUBMITTED`, `UNKNOWN_OUTCOME`, and `CONFIRMED` require an APPROVE decision plus a `submission` object containing CommandID, IdempotencyKey, PayloadHash, command kind, submitted time, and receipt availability.
- `SUBMITTED` is not success. `UNKNOWN_OUTCOME` requires receipt lookup. `CONFIRMED` requires an authoritative terminal receipt and records its exact outcome.

Only `APPROVED` may enter command submission. A `RETIRE` proposal can be reviewed locally, but HG6 does not enable a Retirement command; Retirement remains a separately authorized lifecycle decision.

## 8. Lifecycle and Transition Rules

The existing authoritative promotion lifecycle remains valid:

```text
GAP SIGNAL
-> Experience
-> Candidate
-> required Eval Results
-> human-authorized Promotion
-> canonical capability + promotion ledger
-> Release Projection
```

The new Experiment track adds stronger growth evidence without replacing that authority:

```text
Candidate
-> Experiment DRAFT
-> AWAITING_AUTHORITY
-> AUTHORIZED
-> RUNNING
-> Trial Attempt
-> trial-scoped Eval Execution Receipts
-> EVIDENCE_READY
-> PASSED | FAILED | INCONCLUSIVE
-> if PASSED, eligible to support existing human Promotion
-> authority-bound Promotion consumes lineage intent
-> stage and durably validate canonical capability + promotion ledger + Promotion Lineage Binding
-> publish terminal Promotion Receipt last
-> Experiment-backed Release Projection
-> Project Adoption Observation
-> Loaded / Invoked Observation
-> Observed Effect
```

A PASSED Experiment establishes only its own outcome, not Promotion authority. `EXPERIMENT_BACKED` additionally requires exact same-Trial Eval receipts, a Promotion Lineage Intent consumed by the authorized Promotion command, a durable lineage binding, its terminal Receipt published last, the canonical Capability, and the matching ledger entry. A historical canonical Capability remains projectable as `HISTORICAL_PROMOTION_PARTIAL`; only an exact baseline-and-ledger-backed seed is `BOOTSTRAP_AUTHORIZED`.

Allowed Experiment transitions are exact:

| From | Allowed next status |
| --- | --- |
| `DRAFT` | `AWAITING_AUTHORITY`, `CANCELLED` |
| `AWAITING_AUTHORITY` | `AUTHORIZED`, `REJECTED`, `CANCELLED` |
| `AUTHORIZED` | `RUNNING`, `CANCELLED` |
| `RUNNING` | `EVIDENCE_READY`, `FAILED`, `INCONCLUSIVE`, `CANCELLED` |
| `EVIDENCE_READY` | `PASSED`, `FAILED`, `INCONCLUSIVE` |
| terminal status | none |

Each transition creates a new append-only `recordRevision`, binds the prior digest, identifies the actor or Runtime, records transition evidence, and passes compare-and-swap against the prior revision. Revision after authorization creates a new Experiment definition version; rerun creates a new Trial Attempt. Neither reopens nor overwrites a terminal record.

Failure branches:

```text
FAILED | INCONCLUSIVE
-> REVISE | REJECT | RERUN proposal

BELOW_EXPECTATION | REGRESSION
-> REVALIDATE | NARROW_SCOPE | SUPERSEDE | RETIRE proposal
```

No proposal performs the transition. A versioned Harness command plus authoritative receipt performs it after user approval.

Required invariants:

```text
CAPTURED != EVALUATED
CANDIDATE != EXPERIMENT_RUNNING
UNBOUND_EVAL_PASS != EXPERIMENT_PASS
EXPERIMENT_PASSED != PROMOTION_AUTHORIZED
LINEAGE_BINDING != PROMOTION_AUTHORITY
CANONICAL_INVALID != RETIRED
LEDGER_BACKED_RELEASE != PROJECT_ADOPTED
DECLARED != CONFIGURED
CONFIGURED != LOADED
LOADED != INVOKED
INVOKED != VERIFIED_EFFECTIVE
COHORT_A != COHORT_B
RETIRED != DELETED
```

## 9. Expectation Evaluation

### 9.1 Freeze before observation

An Experiment-owned expectation becomes immutable through its `growth-expectation/v1` freeze before the Experiment enters `AUTHORIZED`. A Release-owned expectation becomes immutable through the same contract and an explicit authority decision before the first adoption observation window starts. Results collected before the freeze are baseline evidence, not post-change effect evidence.

Changing a threshold, direction, sample requirement, protected criterion, or observation window creates a new Experiment or expectation version. It never rewrites the old outcome.

### 9.2 Outcome rules

- Observation not yet attempted, with an explicit unavailable observed value -> `NOT_OBSERVED`.
- Unknown identity, value kind, unit, population, denominator, or required source -> `UNKNOWN`.
- A known but inadequate sample, insufficient non-unknown coverage, or confounded attribution -> `INCONCLUSIVE`.
- Evidence outside its freshness contract -> `STALE`.
- A required expectation misses its target without a protected regression -> `BELOW_EXPECTATION`.
- Any protected Regression, Safety, or Recovery failure -> `REGRESSION` and blocks a positive overall decision.
- All required expectations meet their targets, values and units match, evidence is current, sample and coverage are sufficient, attribution is exactly `SUPPORTED`, and protected criteria pass -> `MEETS_EXPECTATION`.
- Confounded evidence remains visible and cannot independently establish `MEETS_EXPECTATION`.

### 9.3 No single Growth Score

Workbench presents these dimensions independently:

- expectation outcomes;
- evidence coverage;
- freshness;
- project adoption axes;
- sample and observation window;
- regression and safety findings;
- counterexamples;
- attribution;
- revalidation or retirement need.

An aggregate percentage may be shown only with numerator, denominator, unknown count, and the exact filtered population.

## 10. Cross-project Questions the Projection Must Answer

For each growth item, a user must be able to answer:

1. Which real projects contributed the original problem signals?
2. Which Capability changed, from which version to which version?
3. Which Candidate, Hypothesis, Eval suite, and trial evidence supported the change?
4. Which projects actually declared, configured, loaded, and invoked the Release?
5. Which expected improvements were observed after adoption?
6. Which projects produced regressions, divergence, counterexamples, or insufficient evidence?
7. Is the current recommendation to keep, revalidate, narrow, supersede, or retire?
8. Which Source, Revision, Runtime, model, projection, evidence digest, and timestamp support each answer?

The per-project view and cross-project Release view are projections over the same objects. They cannot maintain separately editable truth.

## 11. Human Authority and Commands

Workbench may automatically:

- read a validated projection;
- identify deterministic invariant violations or predeclared expectation outcomes;
- create or refresh a local `GrowthImprovementProposal`;
- route the proposal to `Needs You`;
- deep-link to authoritative evidence.

Workbench may not automatically:

- import a GAP Receipt;
- create or alter a formal Experience, Candidate, or Experiment;
- start or rerun Eval;
- release, adopt, reconfigure, supersede, or retire a capability;
- widen evidence visibility;
- change project files or Runtime state.

After explicit user approval, a formal Harness command envelope requires:

```text
CommandID
IdempotencyKey
CommandKind
RequestedBy
RequestedAt
PayloadHash
Precondition
Payload
```

The precondition is a command-specific discriminated union:

- `CREATE_CANDIDATE` requires at least one exact Experience ID, Schema version, canonical content digest, and source Revision whose current `triageStatus` is `TRIAGED` and `triageDecision` is `CROSS_PROJECT_CANDIDATE`, plus a deterministic Candidate creation key that must not already exist. A GAP Receipt cannot be the direct creation subject.
- `CREATE_EXPERIMENT` requires an exact Candidate ID, Schema version, canonical Candidate-bundle digest, current authority decision, and promotion state, plus a deterministic Experiment creation key that must not already exist.
- Any future mutation command must bind the exact subject version, record revision, and digest it expects to replace. It cannot reuse the create precondition.

HG6 enables only `CREATE_CANDIDATE` and `CREATE_EXPERIMENT`. Revise, Rerun, Revalidate, Narrow Scope, Supersede, Promotion, Release, Adoption, Runtime mutation, and Retirement remain proposal-only until each has a separate command Contract and execution authorization.

The result is one of:

```text
ACCEPTED_FOR_PROCESSING
SUCCEEDED
REJECTED
CONFLICT
UNKNOWN_OUTCOME
```

`UNKNOWN_OUTCOME` requires receipt lookup by `CommandID` and `IdempotencyKey`; it never authorizes blind replay.

## 12. Failure and Degraded Behavior

| Failure | Required behavior |
| --- | --- |
| Harness unavailable | Show last-known projection with Freshness or `UNAVAILABLE`; do not show empty/zero |
| Unsupported projection version | Reject new bytes and retain the last validated snapshot as `STALE` |
| Watermark, digest, or source identity mismatch | Fail closed; disable commands; show exact mismatch |
| Missing project evidence | Mark the affected axes `PARTIAL` or `UNKNOWN` |
| Declared/configured/loaded/invoked divergence | Show each axis and `DIVERGED`; route a deduplicated `Needs You` item |
| Unbound or reused Eval Result | Preserve it as legacy evidence; never count it toward Experiment PASS |
| Promotion lineage or ledger/canonical mismatch | Do not emit an Experiment-backed Release; set projection Gate `NO_GO` for identity/digest contradiction |
| Experiment failure or inconclusive result | Retain all evidence; allow only Revise/Reject/Rerun proposal |
| Regression, Safety, or Recovery failure | Block Experiment-backed Promotion and wider-adoption recommendation; never mutate an existing canonical Release |
| Multiple execution cohorts | Preserve separate context rows; a singular unkeyed query returns `AMBIGUOUS_CONTEXT_COHORT` |
| Conflicting same-cohort project observations | Retain all immutable observations and expose `CONFLICT` |
| Stale effect evidence | Mark `STALE`; never reuse as current effectiveness |
| Corrupt record | Report invalid identity/schema; never repair or overwrite automatically |
| Command conflict | Preserve authoritative version; show conflict and refresh |
| Command unknown outcome | Query receipt; never assume failure or resubmit blindly |
| Canonical lifecycle `RETIRED` | Exclude from default `ACTIVE` and `RECOMMENDED` filters; retain in historical filters and complete lineage |

## 13. Privacy, Security, and Storage

- Never persist raw transcripts, prompts, responses, terminal output, project file contents, secrets, or credentials.
- Persist only bounded distillation, immutable Evidence Reference, Revision, digest, visibility, and source identity.
- `PRIVATE` and `PROJECT` evidence cannot be widened by scan, projection, import, Workbench, or command submission.
- Operational GAP and observation state lives outside every Git worktree under an explicitly configured owner-only state root.
- Git-backed canonical facts use reviewed commits and immutable ledger entries.
- The projection includes references and digests, not arbitrary evidence bodies.
- The Web renderer consumes a typed local-host boundary; it cannot directly invoke Shell/Git or read arbitrary paths.
- Pure read/check commands prove zero writes to Harness, Workbench, and target project worktrees. An explicit Workbench cache refresh may write only its owner-controlled local cache, atomically and receipt-bound; it never writes Harness or target project state and is tested separately from the pure read path.
- Paths, permissions, ownership, symlinks, file types, races, duplicate identities, and no-replace publication fail closed.
- Initial delivery has no Hook, scheduler, background writer, server, database, or automatic semantic classifier.
- Phase 1 performs no deletion. Retention and destructive cleanup require a separate explicit policy and authorization.

## 14. Verification Gates

Every stable implementation candidate must prove:

1. strict Schema validation, `additionalProperties: false`, bounded payloads, and explicit compatibility behavior;
2. byte-identical Growth Projection for identical source bytes, `asOf`, schema set, and toolchain identity, including stable array ordering and watermark derivation;
3. coverage-aware lineage from Source -> Receipt -> Experience -> Candidate -> optional Experiment/Trial/Eval Execution Receipt -> human Promotion Receipt/ledger -> derived Release -> same-cohort Adoption -> Effect, with every allowed promotion path and every missing link explicit;
4. every lifecycle inequality in Section 8;
5. correct missing, Partial, Stale, Diverged, Failed, Inconclusive, canonical Retired, multi-cohort, same-cohort conflict, and provider-unavailable behavior;
6. explicit numerator, denominator, unknown count, and coverage for every cross-project aggregate;
7. zero source-project, Harness-worktree, or external writes for scan, projection build/check, Adapter reads, and Workbench queries; any separately invoked Workbench-local cache refresh writes only its declared cache root and proves the source worktrees unchanged;
8. fail-closed behavior for path, permission, symlink, malformed record, conflicting identity, concurrency, and version conflict attacks;
9. preserved failure, counterexample, and regression evidence after later PASS results;
10. compatibility with existing feedback, Experience, Candidate, Eval, Promotion, registration, lock, integration, projection, and adoption contracts;
11. focused tests plus one fresh repository-required complete Gate on the stable tree;
12. fixed Candidate/Parent/Tree identity and an independent `xhigh` review with P0/P1/P2 = 0/0/0.

Any P0 or P1 finding is NO-GO. A new tree requires affected gates and a fresh fixed-candidate review.

Required negative fixtures include: a PASS Eval from another Candidate/Experiment; the same Eval Result digest reused by two Trials; the same Eval Result ID with different bytes; a Promotion Receipt that does not bind the lineage intent; duplicate ledger tuples; ledger content hash different from canonical Capability; canonical `INVALID` incorrectly mapped to `RETIRED`; an unversioned v1 supersedes relation presented as exact; equal-time same-cohort conflicts; and four adoption/effect facts taken from different Revision/Runtime/model/projection cohorts. Each must fail closed or produce the explicitly degraded state, never complete lineage or verified effectiveness.

## 15. Delivery Sequence

The work is intentionally decomposed so each phase produces a separately reviewable outcome.

### HG0 — Design and Authority

- Materialize, self-review, and independently review this specification only.
- A local merge or other landing decision remains separate from design-candidate approval.
- No runtime behavior, Schema, CLI, project, Workbench, Inbox, or generated artifact changes.

### HG1 — GAP Phase 1

- Implement the already approved deterministic Assessment Receipt, append-only Inbox, receipt lookup, and read-only Scan.
- No automatic Experience import.
- Use the existing GAP Phase 1 plan as the starting implementation authority; reconcile it against the live repository before execution.

### HG2 — Growth Lifecycle Contracts

- Freeze the shared typed primitives, immutable Expectation, Experiment revision/transition table, Trial Attempt, Eval Execution Receipt, Promotion Lineage Binding, Release Projection, Project, Adoption Observation, Observed Effect, project-release view, and Growth Projection Schemas.
- Add compatibility, state-transition, promotion-path, cohort-isolation, determinism, and invariant tests.
- No Workbench changes and no controlled write commands.

### HG3 — Harness Growth Runtime

- Add explicit human triage/import.
- Persist Experiment, Trial Attempt, and trial-scoped Eval Execution Receipt records while preserving the existing unbound Eval path.
- Extend the existing direct Harness Promotion command so an Experiment-backed path consumes a frozen lineage intent, stages and validates the canonical Capability, ledger entry, and lineage binding in one durable journaled transaction, then publishes the terminal Promotion Receipt last. This does not expose Promotion through Workbench.
- Compose canonical Release lineage, context-isolated cross-project observations, effects, and deterministic read-only projection.
- Keep project and Runtime facts reference-based and source-owned.

### HG4 — Real-project Pilot

- Use at least two explicitly authorized real projects.
- Refresh their Authority, Revision, privacy, and zero-write boundaries at pilot time.
- Retain negative and inconclusive results.
- Do not silently enable a Hook, scheduler, or mutation.

### HG5 — Workbench Read-only Projection

- First migrate and review Project Helm Authority so the existing conceptual `HarnessEvolutionPort` is either split into `HarnessEvolutionReadPort` and `HarnessEvolutionCommandPort` or versioned with explicit capability negotiation. The current design's command methods must not be treated as available merely because the read Adapter exists.
- Implement only the read capability against `growth-projection/v1`; command capability reports `CAPABILITY_NOT_ENABLED`.
- Add Harness Evolution, Evaluation Ledger, cross-project search, and `Needs You` projection behavior.
- Show real provider, freshness, coverage, and degraded states.
- Do not enable formal improvement commands.

### HG6 — Controlled Improvement Commands

- Add a separately versioned `HarnessEvolutionCommandPort` for `CREATE_CANDIDATE` and `CREATE_EXPERIMENT` only.
- Submit Candidate or Experiment intent only after explicit user approval.
- Require command-specific creation preconditions, IdempotencyKey, PayloadHash, queryable Receipt, conflict handling, and Unknown Outcome recovery.
- Revise, Rerun, Promotion, Release, project Adoption, Runtime mutation, Supersession, and Retirement remain separate decisions with no enabled command in HG6.

## 16. Real-project Pilot Acceptance

HG4 cannot close until the pilot contains:

- 10–20 real GAP Receipts from at least two projects;
- at least one real `SIGNAL` that proceeds through Experience, Candidate, and Experiment;
- persisted PASS, FAIL, or INCONCLUSIVE Eval Result evidence plus its Trial-scoped execution receipt when used by an Experiment;
- at least one valid Promotion Lineage Binding and terminal Promotion Receipt for the Experiment-backed case;
- at least one Release with explicit Adoption or `NOT_ADOPTED` observations across at least two projects;
- at least one Observed Effect with frozen baseline, target, observation window, sample, attribution, and evidence;
- at least one preserved negative result, regression, counterexample, or inconclusive case;
- measured capture failure/deferred rate, privacy/schema rejection rate, user triage acceptance rate, and added closure friction;
- a zero-write report for source projects during assessment, scan, and observation;
- a stable candidate and independent review.

The pilot succeeds when capture and evaluation are safe, cheap, traceable, and decision-useful. A high signal count or high pass rate is not a success criterion.

## 17. Stop Conditions

Stop and request renewed Authority if:

- raw conversations or project bodies become required;
- source project writes become necessary for a read-only phase;
- Workbench needs to own or edit formal Harness facts;
- an assessment or projection would directly create a Candidate or perform Promotion;
- evidence visibility must be widened;
- a project observation cannot preserve source identity and freshness;
- a single blended score becomes necessary to hide missing evidence;
- a Hook, scheduler, server, database, or semantic clusterer becomes required before pilot evidence;
- the WriteSet expands across HG phases without a new plan and review;
- a real-project pilot lacks explicit project and privacy authorization;
- a destructive cleanup, release, push, deployment, or external Runtime mutation is proposed without separate authorization.

## 18. Current Reality at Design Time

The read-only refresh on 2026-09-01 observed:

- Harness `main@85e303f066287e556843c41b16cbf739c7069a67`, tree `fe9559831944ff53654c503d7aeec55979891aed`;
- existing Experience, Candidate, Eval definition, manual Eval Result recording, human Promotion, canonical capability, promotion ledger, and revalidation-check code;
- three seed Experiences, two seed Candidates, seven Eval definitions, and no persisted `design/evals/results` records;
- both seed Candidates at `DRAFT` with `authorityDecision: PENDING`;
- no complete Experiment, growth Release projection, cross-project Adoption Observation, Observed Effect, or `growth-projection/v1` implementation;
- Workbench has a presentational `HarnessStateRail` but no real Harness Evolution page, Adapter, or cross-project growth read model.

These observations are baseline evidence, not a future PASS. Every implementation phase must refresh live identities and facts.

## 19. Traceability

This specification aligns with:

- `docs/superpowers/specs/2026-08-13-growth-assessment-protocol-design.md`;
- `docs/superpowers/plans/2026-08-13-growth-assessment-protocol-phase-1.md`;
- `README.md` governed-learning and revalidation boundaries;
- `design/schemas/experience.schema.json`;
- `design/schemas/candidate.schema.json`;
- `design/schemas/eval.schema.json`;
- `design/schemas/eval-result.schema.json`;
- `core/schemas/common-capability.schema.json`;
- `core/schemas/relationships.schema.json`;
- `core/governance/promotion-ledger.yaml`;
- Project Helm `00-Product-Definition-v0.1.4.md`;
- Project Helm `15-Knowledge-Management-Workspace-Design-v0.1.md`;
- Project Helm `16-Knowledge-Workspace-Page-State-Matrix-v0.1.csv`;
- Project Helm `17-Knowledge-Workbench-Harness-Ownership-Matrix-v0.1.csv`;
- Project Helm `02-Implementation-Roadmap-v0.1.4.md`.

This document authorizes only HG0 design materialization. HG1 and every later phase require a separately reviewed implementation plan and the authorization applicable at execution time.
