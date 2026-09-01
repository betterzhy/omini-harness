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

New contracts extend this sequence. They do not reinterpret an existing `candidate/v1` or `eval-result/v1`, and they never mutate historical records to fit the new model.

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
Candidate -> Growth Experiment / Eval -> Capability Release
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
- `Availability<T>` is a discriminated union: `PRESENT` requires `value`; `NOT_AVAILABLE` or `UNKNOWN` requires a bounded reason and forbids `value`.
- `EvidenceReference` binds source kind, visibility, opaque reference, digest, source Revision, observation time, and replayability. It never embeds an evidence body.
- `Freshness` is `CURRENT | STALE | UNKNOWN` and carries `observedAt`, the applicable freshness deadline when known, and a reason for non-current states.
- `Coverage` is `COMPLETE | PARTIAL | NONE | UNKNOWN` and carries numerator, denominator, unknown count, population definition, and exclusions when a count is meaningful.
- `TypedValue` is a discriminated `BOOLEAN | DECIMAL | ENUM | GATE` value. A decimal is a canonical decimal string plus an exact unit; v1 performs no implicit unit conversion.
- Every timestamp is normalized RFC 3339 UTC. Every identity, enum, decimal, array bound, and free-text length is schema-bounded.

An unavailable value is never encoded as an empty string, zero, false, an epoch timestamp, or a fabricated identity.

### 7.2 `growth-expectation/v1`

This immutable contract is the authority for both Experiment-level and Release-level expectations. An `ObservedEffect` never points to an unversioned label.

Required fields:

```text
schemaVersion
expectationId
version
ownerReference
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

`ownerReference` is an exact `AssetRevisionReference` to an Experiment or Release. `requirement` is `REQUIRED | OPTIONAL`. `measurement` fixes value kind and unit; `comparison` is `EQUAL | IN_SET | AT_LEAST | AT_MOST | PASS`. `sampleContract` fixes the eligible population, minimum sample, exclusions, and aggregation rule. `freeze` records `FROZEN`, time, actor reference, authority reference, and the canonical definition digest.

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

`targetCapability` binds capability ID, proposed or released version, projection version where applicable, Runtime, and model sensitivity. `scope` names eligible projects or canary classes without copying project truth. Every expectation reference binds exact ID, version, and digest.

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

`PASSED` requires every required Eval Result to be PASS and no protected Regression, Safety, or Recovery criterion to fail. `FAILED`, `INCONCLUSIVE`, `REJECTED`, and `CANCELLED` remain immutable historical outcomes.

### 7.4 `growth-release-projection/v1`

This is a projection over a canonical capability version and its existing promotion ledger evidence. It is not a second release or promotion authority.

Required fields:

```text
schemaVersion
releaseId
capabilityId
capabilityVersion
contentHash
promotionAuthorityReference
promotionPath
sourceCandidateReferences[]
sourceExperimentReferences[]
evalResultReferences[]
expectationReferences[]
lineageCoverage
compatibility
rollback
lifecycle
supersedes[]
releasedAt
evidence[]
```

`promotionPath` is:

```text
EXPERIMENT_BACKED
EXISTING_CANDIDATE_EVAL
BOOTSTRAP_AUTHORIZED
```

The projection must represent every canonical capability version accepted by the existing promotion ledger. This design does not retroactively make Experiment evidence a prerequisite for the already-authoritative Candidate -> Eval -> human Promotion path. `EXPERIMENT_BACKED` requires a PASSED Experiment; `EXISTING_CANDIDATE_EVAL` preserves a non-Experiment promotion; `BOOTSTRAP_AUTHORIZED` preserves the declared seed boundary. No Experiment can create a Release without the existing human Promotion and ledger entry.

`lineageCoverage` is a typed object with `COMPLETE | PARTIAL | NOT_APPLICABLE | UNKNOWN`, explicit missing kinds, and reason. Empty Experiment references are valid only for `EXISTING_CANDIDATE_EVAL` or `BOOTSTRAP_AUTHORIZED`; they are not silently called complete.

Lifecycle values:

```text
RELEASED
QUESTIONED
SUPERSEDED
RETIRED
```

Retirement is logical. It never deletes the Release, adoption observations, effects, negative evidence, or supersession lineage.

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
projectReference
releaseReference
sourceIdentity
authoritySnapshot
capabilityLock
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
projectReference
releaseReference
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

`experimentReference` uses `Availability<AssetRevisionReference>`. A non-Experiment promotion may use `NOT_AVAILABLE` with reason `PROMOTION_PATH_HAS_NO_EXPERIMENT`; it cannot satisfy a criterion that explicitly requires complete Experiment provenance. `expectationReference` is always `PRESENT` and binds the exact frozen `growth-expectation/v1` version and digest.

`baseline`, `target`, and `observedValue` use `TypedValue` or a typed unavailable variant. Their value kind and unit must match the referenced expectation exactly. `sample` records eligible count, observed count, minimum count, exclusions, aggregation rule, and `ADEQUATE | INADEQUATE | UNKNOWN`. Freshness and coverage follow Section 7.1; v1 performs no implicit unit, timezone, population, or denominator conversion.

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
projectReference
releaseReference
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

The four adoption summaries use axis states `MATCHED | NOT_PRESENT | DIVERGED | STALE | CONFLICT | UNKNOWN | NOT_APPLICABLE`. For each axis, the rule considers only valid observations for the exact Project and Release at or before `asOf`, selects the greatest `observedAt`, and:

1. returns `UNKNOWN` when none exists;
2. uses the sole latest value when one exists;
3. deduplicates byte-identical latest values while retaining every reference; or
4. returns `CONFLICT` when equally latest values disagree.

Each axis summary contains the selected observation availability and the last-known present observation availability. A newer `UNKNOWN` or `STALE` remains the current summary; an older present value may be shown only as last-known evidence. `reconciliation` uses the same source references and has state `CONSISTENT | NOT_ADOPTED | DIVERGED | PARTIAL | STALE | CONFLICT | UNKNOWN`.

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

The required population is the Release's exact `expectationReferences[]` entries whose referenced expectation has `requirement: REQUIRED`. For each required expectation, the rule selects the latest valid Effect at or before `asOf`; equally latest disagreeing Effects produce `CONFLICT`. No required expectation produces `UNKNOWN` with reason `NO_REQUIRED_EFFECT_EXPECTATIONS` rather than success.

The fail-closed summary precedence is `REGRESSION`, `CONFLICT`, `BELOW_EXPECTATION`, `UNKNOWN`, `STALE`, `INCONCLUSIVE`, `NOT_OBSERVED`, then `VERIFIED_EFFECTIVE`. `VERIFIED_EFFECTIVE` additionally requires all four adoption axes to be `MATCHED`. Optional expectations remain visible but do not establish the summary. `freshness` is the least-current selected source state (`UNKNOWN`, then `STALE`, then `CURRENT`); `coverage` retains explicit counts and unknowns rather than averaging percentages. `evaluationRuleId` is fixed to `growth-project-release-view/v1` for this version.

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
- releases: `(capabilityId, capabilityVersion, releaseId)`;
- projects: `projectId`;
- adoption observations: `(projectId, releaseId, observedAt, observationId)`;
- effects: `(projectId, releaseId, expectationId, observedAt, effectId)`;
- project-release views: `(projectId, releaseId)`;
- Evidence References and Source Identities: their immutable reference tuple.

All set-like nested arrays are sorted by their declared immutable reference key. An order-significant array must carry an explicit ordinal and sort by `(ordinal, immutable reference key)`; filesystem enumeration order is never semantic.

For identical validated source bytes, `asOf`, schema set, and toolchain identity, the output is byte-identical. `counts` and `projectReleaseViews` are deterministic derived data and never replace their source objects. A project-release view keeps `declared`, `configured`, `loaded`, `invoked`, and `effective` separate; `effective` is derived only from referenced Effect outcomes, while reconciliation retains its rule ID and source references.

`providerState` is one of:

```text
READY
PARTIAL
STALE
UNAVAILABLE
UNKNOWN
```

Every aggregate includes explicit denominators and coverage classes. Unknown or unavailable projects are reported separately and never counted as failed, zero, adopted, or effective.

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
-> EVIDENCE_READY
-> PASSED | FAILED | INCONCLUSIVE
-> if PASSED, eligible to support existing human Promotion
-> canonical capability + promotion ledger
-> Experiment-backed Release Projection
-> Project Adoption Observation
-> Loaded / Invoked Observation
-> Observed Effect
```

A PASSED Experiment is sufficient Experiment evidence, not Promotion authority. A canonical capability promoted through the existing Candidate/Eval path remains projectable as `EXISTING_CANDIDATE_EVAL`; a bootstrap seed remains projectable as `BOOTSTRAP_AUTHORIZED`.

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
EXPERIMENT_PASSED != RELEASED
RELEASED != PROJECT_ADOPTED
DECLARED != CONFIGURED
CONFIGURED != LOADED
LOADED != INVOKED
INVOKED != VERIFIED_EFFECTIVE
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
| Experiment failure or inconclusive result | Retain all evidence; allow only Revise/Reject/Rerun proposal |
| Regression, Safety, or Recovery failure | Block Release and wider-adoption recommendation |
| Conflicting project observations | Retain both immutable observations and expose the conflict |
| Stale effect evidence | Mark `STALE`; never reuse as current effectiveness |
| Corrupt record | Report invalid identity/schema; never repair or overwrite automatically |
| Command conflict | Preserve authoritative version; show conflict and refresh |
| Command unknown outcome | Query receipt; never assume failure or resubmit blindly |
| Retirement | Exclude from default `ACTIVE` and `RECOMMENDED` filters; retain in historical filters and complete lineage |

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
3. coverage-aware lineage from Source -> Receipt -> Experience -> Candidate -> optional Experiment -> human Promotion ledger -> Release -> Adoption -> Effect, with every allowed promotion path and every missing link explicit;
4. every lifecycle inequality in Section 8;
5. correct missing, Partial, Stale, Diverged, Failed, Inconclusive, Retired, and provider-unavailable behavior;
6. explicit numerator, denominator, unknown count, and coverage for every cross-project aggregate;
7. zero source-project, Harness-worktree, or external writes for scan, projection build/check, Adapter reads, and Workbench queries; any separately invoked Workbench-local cache refresh writes only its declared cache root and proves the source worktrees unchanged;
8. fail-closed behavior for path, permission, symlink, malformed record, conflicting identity, concurrency, and version conflict attacks;
9. preserved failure, counterexample, and regression evidence after later PASS results;
10. compatibility with existing feedback, Experience, Candidate, Eval, Promotion, registration, lock, integration, projection, and adoption contracts;
11. focused tests plus one fresh repository-required complete Gate on the stable tree;
12. fixed Candidate/Parent/Tree identity and an independent `xhigh` review with P0/P1/P2 = 0/0/0.

Any P0 or P1 finding is NO-GO. A new tree requires affected gates and a fresh fixed-candidate review.

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

- Freeze the shared typed primitives, immutable Expectation, Experiment revision/transition table, Release Projection, Project, Adoption Observation, Observed Effect, project-release view, and Growth Projection Schemas.
- Add compatibility, state-transition, promotion-path, determinism, and invariant tests.
- No Workbench changes and no controlled write commands.

### HG3 — Harness Growth Runtime

- Add explicit human triage/import.
- Persist Experiment and Eval Results.
- Compose canonical Release lineage, cross-project observations, effects, and deterministic read-only projection.
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
- persisted PASS, FAIL, or INCONCLUSIVE Eval Result evidence;
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
- Project Helm `00-Product-Definition-v0.1.4.md`;
- Project Helm `15-Knowledge-Management-Workspace-Design-v0.1.md`;
- Project Helm `16-Knowledge-Workspace-Page-State-Matrix-v0.1.csv`;
- Project Helm `17-Knowledge-Workbench-Harness-Ownership-Matrix-v0.1.csv`;
- Project Helm `02-Implementation-Roadmap-v0.1.4.md`.

This document authorizes only HG0 design materialization. HG1 and every later phase require a separately reviewed implementation plan and the authorization applicable at execution time.
