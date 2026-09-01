# Growth Assessment Protocol — Approved Design

## Status

This document materializes the user-approved direction for deterministic Agent growth-signal capture across registered projects.

The design is approved at the conceptual level. It does not implement the protocol, install a Skill, enable a Hook, create a scheduled task, modify Pay-Nexus, import any Experience, or authorize Candidate creation or promotion.

The exact public machine contract for the four Phase 1 Schemas is frozen by
`docs/superpowers/specs/2026-09-01-growth-assessment-protocol-v1-schema-contract.md`.
That user-approved Schema Authority controls wherever this conceptual design is
less specific or differs about fields, bounds, branches, normalization,
transport limits, error envelopes, or scan invariants.

## Decision

Add a **Growth Assessment Protocol (GAP)** to Agent Evolution Harness as a governed intake boundary, not as a Skill.

The critical path is:

```text
Project work
  -> existing R1/R2 gate
  -> explicit Growth Assessment
  -> append-only operational receipt outside every Git repository
  -> deterministic read-only scan
  -> human triage
  -> optional explicit import as UNTRIAGED Experience
  -> existing Candidate / Eval / human Promotion flow
```

The protocol separates four concerns:

1. **Assessment:** decide whether one completed task contains a possible reusable growth signal.
2. **Capture:** persist a small, provenance-bound receipt without copying transcripts or project truth.
3. **Triage:** decide whether the signal is noise, a project fact, a project Experience, or a cross-project candidate.
4. **Learning:** use the existing governed Experience → Candidate → Eval → human Promotion flow.

No component may skip directly from Assessment to Candidate, canonical capability, Skill, projection, or Promotion.

## Why this is not a Skill

A Skill is useful runtime guidance, but its activation depends on task-description matching and therefore is not a sufficiently deterministic compliance boundary. A missing Skill invocation would also be hard to distinguish from a valid `NO_SIGNAL` assessment.

GAP is instead invoked by the same explicit execution workflow that already performs project gates. A Skill may later explain GAP or help author a request, but it may never be the only mechanism responsible for assessment, persistence, deduplication, or auditability.

## Why Phase 1 has no Hook or scheduler

Hooks are event-driven runtime extensions, not project authority. A Hook can observe lifecycle events, but using it immediately as a semantic classifier would introduce transcript handling, unstable context assumptions, duplicate events, and an unclear failure boundary.

A scheduled task is suitable for later batch review of already-validated receipts. It is not suitable for reconstructing missing task context by scanning arbitrary repositories or conversations.

Phase 1 therefore has:

- no Hook;
- no conversation or transcript scraper;
- no arbitrary repository scanner;
- no background writer;
- no scheduled mutation; and
- no automatic import or Promotion.

After a real pilot proves the receipt contract, an optional Hook may only remind or verify that a mandatory R2 receipt exists. A later scheduled task may only invoke the read-only scanner over the central Inbox.

## Problem

The Harness already supports explicit Repository Feedback, Experience capture, triage, Candidate creation, Eval, and human-authorized Promotion. It does not currently provide a reliable way for routine work in other repositories to declare:

- that a growth assessment happened;
- that no useful signal was found;
- that a possible signal was found but is not yet shared knowledge;
- which project revision, authority snapshot, exact capability lock, task, gate, and evidence produced the observation; or
- that replaying the same observation did not create duplicate learning records.

The existing `feedback capture` command is too late in the lifecycle for this role because it directly materializes an `UNTRIAGED` Experience. An assessment is weaker evidence than an Experience and must first pass a separate intake boundary.

## Goals

1. Make growth assessment deterministic at named R1 triggers and every adopted R2 closure.
2. Record both `SIGNAL` and `NO_SIGNAL`, so absence of learning is distinguishable from a missed assessment.
3. Preserve project truth, project evidence, and project authorization in the source project.
4. Persist only a small, redacted, provenance-bound receipt outside project and Harness Git worktrees.
5. Make replay idempotent and conflicting reuse fail closed.
6. Allow a central, read-only scanner to report pending signals without reaching into arbitrary repositories.
7. Keep import, triage, Candidate creation, Eval, and Promotion explicit and human-governed.
8. Work for registered Brownfield projects without requiring a repo-local Skill or duplicated Harness installation.

## Non-goals

- Automatically deciding that a shared capability is wrong.
- Recording full conversations, prompts, responses, terminal logs, or project documents.
- Treating every correction or failure as reusable learning.
- Semantic clustering with an LLM, embeddings, or a vector database.
- Writing assessment files into source projects by default.
- Writing raw assessment events directly into `design/learning/experiences/`.
- Modifying project registration, design state, exact locks, projections, or generated Skills.
- Creating or promoting Candidates automatically.
- Polling projects, Git histories, issue trackers, or chat histories.
- Blocking an otherwise correct project gate merely because the central Inbox is temporarily unavailable, unless that project explicitly adopts GAP receipt completion as a separate closure requirement.

## Authority and ownership

| Concern | Authority / owner |
| --- | --- |
| Project facts, contracts, lifecycle, gate result, evidence, and implementation authorization | Source project |
| R0/R1/R2 classification and whether GAP is mandatory for a gate | Effective user, repository, or task-card instructions |
| GAP schemas, normalization, safe receipt persistence, scan semantics, and import rules | Agent Evolution Harness |
| Operational Inbox bytes | User-local Harness state root, outside Git repositories |
| Experience triage and Candidate/Eval/Promotion decisions | Existing Harness learning governance and human authority |
| Runtime reminder or invocation | Codex execution workflow; optional non-authoritative helpers later |

Project authority always outranks a captured signal. A GAP receipt is evidence that an assessment occurred; it is not a project decision, capability truth, or authorization grant.

## Risk policy

### R0

R0 work produces no assessment by default. Formatting, comments, spelling, and other non-semantic changes should not generate central noise.

### R1

R1 work produces an assessment only when at least one named trigger occurs:

- `HUMAN_CORRECTION` — a human corrected material Agent reasoning or behavior;
- `REPEATED_FRICTION` — the same workflow or tool friction materially recurred;
- `SHARED_GUIDANCE_CONFLICT` — reusable guidance conflicted with project truth;
- `CONTRACT_AMBIGUITY` — a contract or authority boundary was materially ambiguous;
- `VERIFICATION_GAP` — required behavior could not be verified with the available contract or evidence.

An R1 trigger does not force `SIGNAL`. The assessment may conclude `NO_SIGNAL` because the observation is project-local, accidental, already covered, insufficiently evidenced, or not transferable.

### R2

Every R2 task that adopts GAP produces one assessment before formal closure. Common triggers are:

- `FORMAL_CLOSURE`;
- `FIXED_CANDIDATE_REVIEW`;
- `GATE_FAILURE`;
- `AUTHORITY_OR_GOVERNANCE_CHANGE`;
- `SECURITY_RECOVERY_OR_CONCURRENCY_FINDING`;
- `CONTRACT_SCHEMA_OR_PROJECTION_CHANGE`.

The record is mandatory even when the verdict is `NO_SIGNAL`.

## Separate gate results

Project correctness and growth capture are reported separately:

```text
projectGate       = PASS | FAIL | BLOCKED | NOT_RUN
growthCaptureGate = PASS | DEFERRED | FAIL | NOT_REQUIRED
```

- `PASS`: a valid, durable, idempotent GAP receipt exists.
- `DEFERRED`: the assessment was formed but durable capture was unavailable for an operational reason. The task report must retain the normalized request digest and retry instruction; it must not claim GAP closure.
- `FAIL`: the request, provenance, path, registration, exact lock, or storage boundary was invalid or unsafe.
- `NOT_REQUIRED`: R0, or R1 without a named trigger.

A `growthCaptureGate` failure never rewrites `projectGate`. A project may explicitly require both gates to pass before its own protocol closure, but GAP itself cannot invent that authority.

## Protocol contracts

Phase 1 introduces four strict Draft 2020-12 contracts under `core/schemas/` because GAP is a cross-project transport and provenance protocol, not a canonical learning asset.

### `growth-assessment-request/v1`

The caller supplies a request containing exactly:

```text
schemaVersion
policyVersion
source
task
riskLevel
trigger
projectGate
verdict
reasonCodes
summary
impact
capabilityHints
evidence
assessedAt
```

`source` contains:

- `sourceKind`: `REGISTERED_PROJECT | HARNESS_SELF`;
- `projectId`;
- `integrationId` when registered;
- `runtime`;
- `sourceRevision` with explicit kind, head, and tree when Git-backed;
- `authoritySnapshotFingerprint` when registered;
- `capabilityLockFingerprint` when shared capabilities were consumed.

`task` contains:

- `taskId`;
- `attemptId`;
- `gateId`;
- optional fixed `candidate`, `parent`, and `tree` identities.

`riskLevel` is `R1 | R2`. `trigger` is one of the named values above. `verdict` is `NO_SIGNAL | SIGNAL`.

`reasonCodes` is a unique, sorted subset of:

- `PROJECT_LOCAL_ONLY`;
- `ACCIDENTAL`;
- `INSUFFICIENT_EVIDENCE`;
- `ALREADY_COVERED`;
- `NON_TRANSFERABLE`;
- `REUSABLE_AGENT_BEHAVIOR`;
- `CAPABILITY_MISMATCH`;
- `CAPABILITY_GAP`;
- `REVALIDATION_NEEDED`;
- `CROSS_PROJECT_PATTERN`.

For `SIGNAL`, at least one positive signal code, one evidence item, non-empty `summary`, and non-empty `impact` are required. `NO_SIGNAL` still requires a reason code and a concise summary, but `capabilityHints` may be empty.

### Evidence item

Each evidence item contains exactly:

```text
kind
reference
revision
digest
availability
visibility
distillation
```

- `kind`: `PROJECT_ARTIFACT | FIXED_REVIEW | HUMAN_CORRECTION | TEST_RECEIPT | GATE_RECEIPT | OTHER`.
- `reference`: an opaque identifier or safe repository-relative reference; never an absolute filesystem path.
- `revision`: the source revision or immutable evidence revision.
- `digest`: `sha256:<64 lowercase hex>`.
- `availability`: `REPLAYABLE | OPAQUE`.
- `visibility`: `PRIVATE | PROJECT | SHARED | PUBLIC`.
- `distillation`: 1–1000 characters.

Phase 1 never follows an evidence reference merely because it looks like a path. For registered projects, both the evidence reference and live record path first pass `safe_relative_path`; the two resulting safe POSIX strings must then be byte-for-byte equal to exactly one live `authorities[].path`. No filesystem resolution, case folding, Unicode folding, alias expansion, or additional path normalization is permitted. `digest` must equal `sha256:` plus that record's SHA-256, and `revision` must equal `sourceRevision.head` from the validated snapshot. A claim with no exact match, multiple matches, a derived-only authority, or mismatched bytes/revision fails before the Inbox is opened. All other evidence is `OPAQUE`. `HARNESS_SELF` evidence is `OPAQUE` in Phase 1 because self mode has no equivalent authority allowlist. The receipt records a reference and digest, not the evidence body.

The schema has `additionalProperties: false`, bounded arrays, bounded strings, and no `transcript`, `messages`, `prompt`, `response`, `logBody`, `fileContent`, or arbitrary metadata field.

### `growth-assessment-receipt/v1`

The durable record contains:

```text
schemaVersion
policyVersion
assessmentKey
assessmentId
requestDigest
status
growthCaptureGate
assessment
```

- `assessmentKey` identifies one project/task/attempt/gate/policy assessment obligation.
- `assessmentId` identifies the complete normalized assessment content.
- `requestDigest` hashes canonical JSON of the normalized request.
- `status`: `RECORDED | DUPLICATE` in the returned projection. The persisted authoritative record always uses `RECORDED`; `DUPLICATE` means the same bytes were replayed.
- `growthCaptureGate` is `PASS` for a persisted or exactly replayed valid record.

The IDs are content-derived:

```text
assessmentKey = growth-key:<24 hex of source + task + policy identity>
assessmentId  = growth-assessment:<24 hex of the complete normalized request>
requestDigest = sha256:<64 hex of canonical normalized request JSON>
```

The caller does not choose these identities.

### `growth-capture-result/v1`

Every `growth assess` invocation that reaches normalized source validation returns a machine-checkable capture result:

```text
schemaVersion
growthCaptureGate
status
assessmentKey
assessmentId
requestDigest
receipt
deferredReason
retryInstruction
```

The contract uses conditional fields:

- `PASS` requires `status: RECORDED | DUPLICATE` and the validated receipt; it forbids deferred fields.
- `DEFERRED` requires `status: DEFERRED`, no receipt, a `deferredReason` of `STATE_ROOT_UNAVAILABLE | INBOX_LOCKED`, and an explicit retry instruction that requires the same normalized request and source context.
- unsafe state, corrupt records, invalid provenance, schema failures, and key conflicts are `FAIL` errors, not `DEFERRED`.

`DEFERRED` is not success and does not create a receipt. It preserves the derived key, ID, and full request digest so the task report can prove what remains to be retried without persisting the request body.

### `growth-scan-report/v1`

The read-only scanner emits:

```text
schemaVersion
policyVersion
asOf
stateRootIdentity
records
counts
gate
```

Each record reports the assessment identity, project, risk, trigger, verdict, visibility ceiling, capability hints, and one deterministic disposition:

- `NO_ACTION` for a valid `NO_SIGNAL` receipt;
- `HUMAN_TRIAGE_REQUIRED` for `SIGNAL`;
- `INVALID_RECEIPT` for malformed, corrupt, or identity-mismatched state.

The scanner performs no semantic clustering and writes nothing. Exact replay is reported by the `assess` command that observes it; Phase 1 does not persist a mutable replay counter, so a later scan does not claim to reconstruct replay history.

## Normalization and identity

Normalization is LLM-free and deterministic:

- validate before hashing;
- normalize line endings in bounded text;
- sort set-valued arrays lexicographically;
- preserve no field whose semantics depend on filesystem enumeration;
- use explicit RFC 3339 `assessedAt`; never inject an implicit time into identity;
- bind the registered integration identity, source revision, Authority Snapshot fingerprint, exact capability-lock fingerprint, task attempt, and fixed candidate when present;
- hash canonical UTF-8 JSON with SHA-256.

Two submissions with the same `assessmentKey` and `assessmentId` are idempotent. The command returns the existing receipt with projected `status: DUPLICATE`.

Two submissions with the same `assessmentKey` but different `assessmentId` fail closed as `ASSESSMENT_KEY_CONFLICT`. A corrected assessment uses a new project-authorized `attemptId`; Phase 1 does not overwrite or mutate a receipt.

## Operational state root

Raw receipts do not belong in either project Git history or the Harness worktree. Phase 1 uses a user-local state root:

```text
$CODEX_HOME/agent-evolution/growth/v1/
├── inbox/
│   └── <assessment-key-hash>.json
├── staging/
│   └── <random-operation-id>.part
└── locks/
    └── inbox.lock
```

Tests and isolated tools always pass `--state-root` explicitly. Runtime resolution is:

1. explicit `--state-root`;
2. `$CODEX_HOME/agent-evolution/growth/v1`;
3. fail closed if neither is available.

Explicit source, request-file, and state-root paths must be absolute; `$CODEX_HOME` must also be absolute when used. Relative paths are rejected before resolution so the current working directory cannot change source or state identity. The implementation must not guess a different repository, use a broad temporary directory as durable state, or silently create state under the source project.

Before creating anything, the writer verifies the intended physical state root is outside:

- the Harness repository and all of its worktrees;
- the registered source repository and all of its worktrees; and
- any other containing Git worktree discovered from the nearest existing ancestor.

Lexical prefix checks alone are insufficient. Validation rejects symlink components and compares canonical physical roots before opening the directory anchor. A state root inside any protected or discovered Git worktree fails with `STATE_ROOT_UNSAFE` and creates no directory, lock, or receipt.

State invariants:

- root and directories are owned by the current user and mode `0700`;
- receipt files are regular owner-only files with mode `0600`;
- root and every path component are opened no-follow from a directory descriptor;
- one process lock covers key lookup and staged publication;
- receipt publication is atomic, fsynced, and no-replace: write and fsync a random owner-only regular file under the same-root `staging/` directory, atomically hard-link it to the absent final Inbox name, fsync `inbox/`, then unlink the staging name and fsync `staging/`;
- existing bytes are read once and validated before idempotent replay;
- symlinks, unexpected file types, unsafe permissions, corrupt records, and key collisions fail closed;
- the scanner never enumerates `staging/`; a crash before publication leaves no visible receipt, while a final entry observed after hard-link publication is always complete. Durability is committed only after the Inbox directory fsync;
- no startup cleanup, overwrite, rename-over-existing, partial-file repair, or destructive recovery occurs in Phase 1. Stale staging links are a reported storage limitation until an explicit retention/recovery policy exists.

Because the final append-only file contains both the assessment and its receipt identity, Phase 1 has no authoritative multi-file transaction or mutable index. `staging/` is non-authoritative publication scratch space on the same filesystem; hard-link publication is the single visibility commit point.

## Registered-project validation

For `REGISTERED_PROJECT`, `growth assess` must:

1. load the existing `.agent-evolution/registration.yaml` through the current safe registration loader;
2. verify Harness identity, integration identity, `READ_ONLY` access, runtime, and exact capability lock;
3. rebuild the live Authority Snapshot using only the integration authority-map allowlist;
4. reject missing, excluded, unsafe, symlinked, dirty-for-authority-set, or stale authority;
5. compare the request source revision, snapshot fingerprint, integration ID, runtime, and lock fingerprint to the validated live values;
6. validate every `REPLAYABLE` evidence item against exactly one live Authority Snapshot record path/hash/revision;
7. read no arbitrary evidence paths and write nothing to the source project.

For `HARNESS_SELF`, the command validates that the source path is the Harness repository, the requested Git HEAD/tree match the current tracked tree, and the worktree conditions required by the adopting gate are explicit. It does not silently treat an unregistered external repository as self.

## Submission flow

```text
Gate determines R0/R1/R2
  -> NOT_REQUIRED, or construct strict request
  -> validate schema
  -> validate registration/self identity and source context
  -> normalize and derive key/id/digest
  -> open safe state root
  -> acquire key-independent Inbox lock
  -> if key absent: stage + file fsync + hard-link no-replace + inbox fsync -> RECORDED
  -> if same key and same bytes: DUPLICATE
  -> if same key and different bytes: fail closed
  -> release lock
  -> return receipt to gate report
```

The recommended CLI accepts stdin to avoid creating a source-project outbox file:

```bash
./harness growth assess \
  --source /absolute/path/to/registered-project \
  --request - \
  --state-root /absolute/path/to/isolated-state \
  --format json
```

It also accepts an explicit request file for testing and controlled automation. A request file is input only and is never modified.

## Read-only scan flow

```text
Explicit user command or later scheduled task
  -> open safe state root read-only
  -> no-follow enumerate direct Inbox entries; parse only expected *.json receipts
  -> validate filename, file type, permissions, schema, key, id and digest
  -> emit deterministic report
  -> no import, mutation, deletion, move, rewrite, or source-project access
```

Recommended CLI:

```bash
./harness growth scan \
  --as-of 2026-08-13T12:00:00+08:00 \
  --state-root /absolute/path/to/isolated-state \
  --format json
```

## Human triage and import boundary

Phase 1 ends at the scan report. A `SIGNAL` receipt remains operational evidence, not a formal Experience.

A later, separately designed import phase may:

1. display one receipt and its provenance;
2. require an explicit human decision: `IGNORE | PROJECT_FACT | PROJECT_EXPERIENCE | CROSS_PROJECT_CANDIDATE`;
3. copy only a sanitized distillation into a new `UNTRIAGED` Experience for the applicable decisions;
4. record the receipt identity in the Experience source reference;
5. never create a Candidate directly;
6. never auto-Promote.

Import must be dry-run by default and requires explicit apply authority. The existing `feedback capture` and learning semantics remain unchanged until that phase is separately approved.

## Scheduled processing and Hook roadmap

Automation is eligible only after a pilot of at least 10–20 real task receipts demonstrates acceptable signal quality, privacy, and friction.

### Optional scheduled scan

A later Codex scheduled task may run `growth scan` weekly and summarize only:

- new `SIGNAL` receipts;
- invalid receipt counts;
- projects with missing R2 receipts only when a separate authoritative gate ledger makes that fact knowable; and
- receipts already reviewed by a human.

It may not scan raw conversations, arbitrary repositories, or mutate learning state.

### Optional Hook

A later Hook may verify or remind that an R2 task report contains a valid receipt. It may not classify semantic value, persist transcripts, synthesize Experiences, or block project correctness without explicit project authority.

## Privacy and retention

- Never persist raw transcript, prompt, response, terminal output, source file contents, secret values, or credentials.
- Keep summaries and distillations bounded and evidence references opaque where necessary.
- Phase 1 enforces structure, size, explicit redaction responsibility, and a prohibition on raw-content fields; it does not claim that a deterministic schema can recognize every possible secret embedded in prose.
- Visibility cannot be widened during scan or later import.
- `PRIVATE` and `PROJECT` evidence cannot become shared capability evidence without a separate redaction and authority decision.
- Phase 1 never deletes receipts. Retention and deletion require a later explicit policy because deletion is destructive and may affect auditability.
- Invalid submissions are rejected without persisting their raw bytes. The scanner reports corrupt existing state but does not move or rewrite it.

## Failure model

| Failure | Required behavior |
| --- | --- |
| Missing or invalid registration | Reject, zero project writes, zero Inbox writes |
| Live authority or exact lock drift | Reject, zero writes |
| Request/source identity mismatch | Reject, zero writes |
| `REPLAYABLE` evidence does not exactly match one live authority record | Reject before opening Inbox, zero writes |
| State root is inside Harness, source, or another Git worktree | Reject before creation, zero writes |
| Unsafe state root, symlink, mode, owner, or unexpected type | Reject, zero writes |
| Transcript/unknown/oversized field | Schema reject, do not persist raw bytes |
| Same key and same normalized content | Return existing receipt as `DUPLICATE` |
| Same key and different content | `ASSESSMENT_KEY_CONFLICT`, preserve existing record |
| Crash after staging create or during staging write | No final Inbox entry is visible; later retry may publish normally; partial staging file is never scanned |
| Crash after staging fsync but before publish | No final Inbox entry is visible; later retry may publish normally; complete staging file is never authority |
| Crash after hard-link but before Inbox-directory fsync | On restart the final name is absent or contains the complete inode, never partial; retry safely records or returns `DUPLICATE` |
| Crash after Inbox-directory fsync but before staging unlink | Complete durable final receipt remains visible and validates; later retry is `DUPLICATE`; stale staging link is not scanned |
| Concurrent identical writers | One `RECORDED`; a lock loser returns `DEFERRED`, and its later exact retry returns `DUPLICATE`; one durable record |
| Concurrent conflicting writers | At most one `RECORDED`; a lock loser is `DEFERRED`, and its later retry fails with key conflict; no partial record |
| Corrupt existing receipt | Scan/assess fail closed; no automatic repair |
| Inbox unavailable or non-blocking lock busy | Return validated `growth-capture-result/v1` with `DEFERRED`, key/ID/digest and retry instruction; never claim receipt PASS |
| Scanner encounters invalid record | Report `INVALID_RECEIPT`, continue only when safe to enumerate remaining entries |
| Scanner observes more than 10,000 direct Inbox entries | Return `SCAN_LIMIT_EXCEEDED`; emit no partial Scan Report and write nothing |

## Compatibility

- Project registration remains routing metadata and stays `READ_ONLY`; no assessment fields are added to its schema.
- Project design state, capability binding, exact lock, resolver, projection, and generated Skills are unchanged.
- Existing `repository-feedback/v1`, Experience, Candidate, Eval, and Promotion contracts are unchanged in Phase 1.
- `generated/**` remains unaffected because raw GAP receipts are operational state, not canonical or generated repository artifacts.
- Projects that do not adopt GAP continue unchanged.

## Delivery phases

### Phase 0 — Written design and implementation plan

Commit and review this specification plus the Phase 1 plan. No runtime behavior changes.

### Phase 1 — Deterministic receipt and read-only scan

Add strict request/receipt/capture-result/report schemas, normalization, safe external Inbox persistence, registered-project/self validation, CLI commands, race/path/privacy tests, and neutral fixtures. No import, automation, or live Brownfield pilot.

### Pilot A — Separately authorized Brownfield validation

After the fixed Phase 1 candidate passes independent review, run a separate, read-only registered-project pilot. Pay-Nexus is a suitable first candidate, but its current registration, authority, exact lock, exclusions, HEAD/tree and zero-write boundary must be revalidated at pilot time. The pilot is not a prerequisite for completing the generic Phase 1 implementation.

### Phase 2 — Explicit human triage/import bridge

Design a dry-run-first command that converts an approved, sanitized receipt into an `UNTRIAGED` Experience while recording an immutable intake decision. Preserve existing learning governance.

### Phase 3 — Scheduled read-only review

After 10–20 task receipts, measure precision, recall proxies, duplicates, privacy findings, capture failures, and user friction. If acceptable, add a weekly read-only scheduled scan.

### Phase 4 — Optional missing-receipt reminder

Only if real evidence shows missed R2 receipts, evaluate a minimal Hook or runtime check that verifies receipt presence. Do not add semantic classification to the Hook.

## Phase 1 acceptance criteria

1. R1 named-trigger and R2 mandatory requests validate deterministically.
2. Both `SIGNAL` and `NO_SIGNAL` produce durable, traceable receipts.
3. One assessment obligation produces at most one append-only record.
4. Exact replay is idempotent; conflicting replay fails closed.
5. Same-filesystem staged hard-link publication prevents a partial final receipt; concurrent submissions cannot overwrite, orphan, or misattribute an authoritative receipt.
6. Assessment and scan write neither the source project nor the Harness Git worktree.
7. Registered-project assessment reads only the existing authority allowlist, exactly verifies `REPLAYABLE` evidence, and excludes configured paths such as `temp-input/**`.
8. The state root is rejected before creation when it is inside Harness, the source project, or any other Git worktree.
9. A transiently unavailable Inbox produces a deterministic `DEFERRED` result with key/ID/digest and retry instruction, not a false receipt.
10. Transcript-like fields, absolute references, unsafe paths, excessive content, and visibility widening are rejected.
11. The scanner is deterministic, LLM-free, read-only, and does not access source projects.
12. No raw receipt becomes an Experience, Candidate, Eval, capability, projection, or Skill.
13. Existing feedback and learning tests remain unchanged and pass.
14. Neutral fixtures pass before any separately authorized Brownfield pilot.
15. The fixed Harness candidate passes the repository-required R2 gates and independent deep review.

## Success metrics for the pilot

Measure, but do not optimize prematurely:

- assessment completion rate for adopted R2 tasks;
- `SIGNAL` rate by trigger and project;
- human triage acceptance rate;
- exact duplicate and key-conflict observations available from task receipts;
- capture failure/deferred rate;
- privacy/schema rejection rate;
- mean assessment payload size;
- time added to task closure;
- number of receipts that later justify a real Experience;
- number of Experiences that later survive Candidate/Eval review.

The first pilot is successful when capture is safe, cheap, and auditable—not when the system reports many growth signals.

## Stop conditions

Stop implementation and request review if any of the following occurs:

- the design requires reading raw conversations;
- source project writes become necessary;
- registration must carry a second project state system;
- an assessment would directly create or modify a Candidate or capability;
- external state cannot be protected against symlinks, unsafe permissions, concurrent writers, and overwrite;
- project truth would be copied into the Inbox rather than referenced;
- a scheduler or Hook becomes necessary to make Phase 1 correct;
- a later Pay-Nexus pilot would require reading, enumerating, or hashing `temp-input/**`;
- the exact WriteSet must expand beyond approved Phase 1 files without renewed review.

## References

- Codex Skills: <https://learn.chatgpt.com/docs/build-skills>
- Codex Hooks: <https://learn.chatgpt.com/docs/hooks>
- Existing governed-learning boundary: `README.md`, `design/schemas/experience.schema.json`, `design/schemas/candidate.schema.json`, and `src/evolution_harness/learning.py`
