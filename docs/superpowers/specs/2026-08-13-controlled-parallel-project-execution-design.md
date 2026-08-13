# Controlled Parallel Project Execution — Approved Design

## Status

This document materializes the user-approved direction for controlled, low-intervention project concurrency. It defines an execution-planning capability for Agent Evolution Harness and its adoption boundary for registered projects such as Pay-Nexus.

The design is approved at the conceptual level. This document is the written-spec review gate; it does not authorize implementation, mutate Pay-Nexus, or authorize any project development action.

## Decision

Use **controlled concurrency**:

- Run independent Change Conflict Domains in parallel, initially with at most three active lanes per project.
- Run Slices strictly sequentially inside each Change Conflict Domain.
- Serialize shared authority, public contract, registry, generated-artifact, migration, integration, Landing, Wave, push, and deployment surfaces.
- Treat missing, stale, ambiguous, or contradictory isolation evidence as a conflict and fall back to serial execution.

Owner or bounded-context identity seeds the isolation calculation but is not sufficient by itself. The authoritative isolation unit is a computed **Change Conflict Domain**.

## Problem

The current single-Slice control model is safe but leaves independent work idle. A naive “one lane per Owner” model is faster, but it can miss conflicts through shared contracts, producer-consumer relationships, root build files, generated projections, migrations, or authority documents.

The target model must improve throughput without weakening:

- project-owned authorization;
- exact WriteSet enforcement;
- fixed-candidate review;
- authority freshness;
- deterministic recovery;
- fail-closed treatment of unknown state; or
- explicit approval for high-risk external effects.

It must also reduce routine user intervention. One bounded authorization envelope should cover ordinary eligible Slice progression; the user should be asked again only when that envelope expires or a protected boundary is reached.

## Goals

1. Admit multiple independent project Slices without allowing shared-state races.
2. Make every concurrency decision reproducible from explicit project facts.
3. Keep one active Slice at a time inside each conflict domain.
4. Preserve exact fixed-candidate and independent-review gates for every lane.
5. Reconcile completed lane candidates through one serial integration barrier.
6. Allow continuous progress inside a pre-authorized envelope.
7. Keep the Harness generic and project-neutral.

## Non-goals

- Turning the Harness into a workflow engine, background scheduler, task runner, Git merger, or deployment system.
- Inferring project authority from prose, chat history, filenames, or model judgment.
- Automatically widening authorization, WriteSets, migration scope, or production access.
- Making concurrent writes to shared authority or generated aggregate files.
- Retrofitting an already active or fixed Pay-Nexus candidate into the new model.
- Authorizing formal database writes, destructive operations, Landing, Wave entry, push, release, or deployment.

## Capability ownership

| Responsibility | Owner |
| --- | --- |
| Portfolio, Delivery Track, Owner, Slice, dependencies, priorities, authorization, and stop conditions | Project authority, for example Pay-Nexus |
| Authority reading, schema validation, exact-lock validation, conflict calculation, deterministic admission plan, explain trace, and project-scoped lease/CAS primitive | Agent Evolution Harness |
| Invoking the lease primitive, isolated worktree/task creation, lane execution, fixed-candidate production, and gate invocation | Codex execution runtime |
| Independent fixed-candidate review | Designated reviewer role under repository policy |
| Integration ordering and project-wide gate policy | Project authority, executed serially by the runtime |
| Permission to cross protected boundaries | User or the project's named external authority |

The project remains the source of truth. Harness output is a derived decision projection and cannot grant authority absent from the project snapshot.

## Execution hierarchy

```text
Portfolio Authority
  -> Delivery Track / Value Stream
      -> Change Conflict Domain Lane
          -> Slice 1 -> Slice 2 -> Slice 3

Parallelism exists between eligible lanes.
Sequence is mandatory within a lane.
Integration is one project-wide serial barrier.
```

`Delivery Track` and `Value Stream` are planning and prioritization views. They do not prove technical isolation. A Change Conflict Domain is the smallest unit allowed to hold an execution lease.

## Project authority inputs

The project must expose machine-readable, authoritative facts for each proposed Slice. A sidecar may extract these facts from existing project authority files, but it may not invent missing facts.

Each Slice descriptor contains:

- `sliceId` and current lifecycle state;
- `portfolioId` and `deliveryTrackId`;
- `ownerSet`;
- `factFamilySet`;
- `publicContractSet`;
- `producerConsumerSet`;
- `bindingSet`;
- `exactWriteSet`;
- `ephemeralWriteSet` for lane-exclusive build and cache paths;
- `sharedArtifactSet`;
- `dependencySet`;
- `migrationResourceSet`;
- required gates and review policy;
- authorization class;
- authority references.

Each set is explicit and uses canonical project identifiers or repository-relative paths. Empty and unknown are distinct: an empty set is an asserted absence; an unknown or omitted set fails closed.

Legacy projects may omit the concurrency model entirely and remain serial. Once a project declares any concurrency descriptor, every required field must be present for that Slice; a partially specified descriptor is rejected rather than treated as legacy serial input.

## Frozen admission snapshot

All lanes admitted in one parallel batch use the same frozen input snapshot:

- `batchBaseCommit`;
- `authoritySnapshotFingerprint`;
- `contractRegistryDigest`;
- `dependencyGraphDigest`;
- `sliceDescriptorDigest` for every admitted Slice;
- `exactWriteSetDigest` for every admitted Slice;
- Harness version and conflict-policy version.

The Harness derives a `batchPlanId` from these inputs and records the source bytes or content digests already allowed by the integration authority map. A plan is not valid against a different project, authority snapshot, conflict policy, or Slice descriptor.

## Change Conflict Domain

For each Slice, the Harness calculates a normalized lock footprint from the declared sets. Public producer-consumer closure and dependency relationships are expanded only from explicit project graphs. A diagnostic `conflictFootprintId` is a digest of the project identity, normalized footprint, and conflict-policy version. It excludes batch and authority-snapshot identities; it is not itself a lease key because two different footprints may still overlap.

Repository paths are compared after the existing safe-relative-path normalization. Directory and file ancestry counts as overlap. Globs must be deterministically expanded against `batchBaseCommit`; unresolved, escaping, or filesystem-dependent patterns are invalid. Every declared write path is checked component by component from an opened lane-root directory descriptor; a symlink ancestor or final target is invalid even when it resolves inside the worktree. `sharedArtifactSet` names every shared output affected by the Slice even when that output is generated later rather than written in the lane.

Two Slices conflict if any of the following is true:

1. Their `ownerSet` overlaps. Initial policy permits only one active lane per Owner.
2. Their `factFamilySet`, `bindingSet`, `exactWriteSet`, `sharedArtifactSet`, or `migrationResourceSet` overlaps.
3. Either Slice changes a public cross-owner contract or a shared schema, registry, catalog, manifest, aggregate authority projection, root build surface, or generated source.
4. A declared producer-consumer or dependency path connects them in either direction.
5. One Slice writes an authority input used to admit the other.
6. Their admission snapshots do not share the same project identity and `authoritySnapshotFingerprint`, even when their batch IDs differ.
7. Required conflict facts are missing, invalid, stale, contradictory, or cannot be normalized safely.

Conflict is symmetric for scheduling even when the underlying dependency is directional. A conflict edge places the Slices in the same serial conflict cluster for that batch.

The first policy version is intentionally conservative. Later relaxation requires observed evidence, a new policy version, compatibility tests, and explicit project adoption.

## Deterministic scheduling

The Harness produces a plan; it does not execute it.

1. Validate project registration, authority map, source snapshot, descriptors, locks, and authorization envelope.
2. Reject any Slice that is not project-authorized and locally `READY`.
3. Build the symmetric conflict graph and its connected conflict clusters.
4. Enforce dependency order inside and across clusters.
5. Select at most one Slice from each cluster.
6. Read the current project coordinator journal and select no more than the remaining project-wide capacity: `max(0, min(envelope.maxParallelLanes, 3) - nonterminalLaneLeaseCount)` in policy version 1.
7. Sort equally eligible Slices by project priority, dependency depth, then canonical `sliceId`.
8. Compare the proposed batch with every recorded nonterminal lease from earlier batches and plans.
9. Emit proposed admissions, serialized Slices, blocked Slices, and rejected Slices with exact reason codes.

Multiple READY Slices are valid only when they resolve to independent lanes. More than one READY Slice in the same conflict cluster is not executed concurrently; the deterministic ordering rule selects one and leaves the others queued.

An execution plan is provisional. No Slice is `ADMITTED` and no mutating command may start until the runtime acquires the project-level lease described below.

## Project-level admission lease

The Harness provides one local **Project Concurrency Coordinator** primitive for all plans, batches, worktrees, and processes that target the same project. The Codex runtime must invoke it before execution. Coordinator state is operational safety state, not project authority. The primitive performs explicit caller-requested acquire, transition, release, and recovery compare-and-swap operations; it does not poll, prioritize work, launch tasks, advance lifecycle autonomously, or become a workflow engine.

`projectExecutionKey` is derived from the validated project registration identity and the canonical registered source-root identity. It excludes batch, snapshot, plan, worktree, branch, and policy identities. Every worktree request must name the original registered source root. If two callers cannot prove that they share the same coordinator and durable state store, concurrent execution is unsupported and admission fails closed. Policy version 1 is single-host only.

The coordinator maintains a Harness-owned durable per-user state root outside the project repository and outside system-temporary storage. All project processes use that same root. The root and journal are owner-only, directory-descriptor anchored, no-symlink, fsynced, and atomically replaced. Unsafe permissions, a second configured root, missing expected state, or state loss fails closed until explicit recovery reconstructs and reconciles every nonterminal project attempt.

The journal contains:

- a monotonically increasing fencing token;
- `batchPlanId`, `sliceId`, and project-authorized attempt identity;
- authority snapshot and policy version;
- the complete immutable normalized footprint, not only its digest;
- lifecycle and candidate identities;
- isolated worktree identity;
- acquisition, transition, release, and recovery receipts;
- any pending integration transaction.

Lease acquisition is a project-scoped compare-and-swap transaction:

1. take one OS process lock keyed only by `projectExecutionKey`;
2. reject a missing, corrupt, or pending-recovery journal;
3. revalidate the plan, current authority, envelope, and source identity;
4. compare the proposed full footprint against every nonterminal lease across all batches and plans using the current conflict predicate;
5. recompute the effective lane cap from the unchanged envelope and reject when the number of nonterminal lane leases across all batches and plans is already at that cap;
6. reject admission if an active lease uses a different conflict-policy version;
7. append the new lease and increment its fencing token through a journaled, fsynced, atomic replacement;
8. release the short-lived OS lock only after the durable receipt is readable and valid.

The idempotency key is `(projectExecutionKey, batchPlanId, sliceId, attemptId)`. Replaying it returns the existing lease and never starts a second lane. Replaying a terminal attempt is rejected; retry requires a new attempt explicitly present in project authority. Every mutating runtime boundary and every lifecycle transition must present the current fencing token. A stale or missing token denies the mutation or transition.

Time does not release a lease. A process crash, missing worktree, `BLOCKED`, `NO_GO`, or `STALE` state retains the footprint until the coordinator records a project-authorized recovery decision after verifying that no mutating process remains. A lease is released only after `CLOSED`, or after a `CANCELLED`/superseded attempt has been quiesced, audited, and durably recorded. New admissions stop while recovery is pending.

## Lifecycle

```text
PROPOSED
  -> READY
  -> ADMITTED
  -> ACTIVE
  -> FIXED_CANDIDATE
  -> REVIEW_GO
  -> QUEUED_FOR_INTEGRATION
  -> INTEGRATING
  -> CLOSED
```

Exceptional states are:

- `BLOCKED`: a declared prerequisite, gate, or authorization is unsatisfied;
- `NO_GO`: fixed-candidate or integration review found a defect;
- `STALE`: relevant authority, contract, dependency, descriptor, or WriteSet inputs changed;
- `CANCELLED`: project authority withdrew the Slice.

Only one Slice may hold a lease in a conflict cluster. The lease begins before `ADMITTED`, remains held through `INTEGRATING`, and ends only after the durable release conditions above. `BLOCKED`, `NO_GO`, and `STALE` do not release a successor in the cluster. A retained lease does not block independent clusters unless its authority or dependency surface is shared or recovery is project-wide.

Lifecycle facts are project-owned. The Harness validates current facts and derives allowed next transitions; it never writes the authoritative lifecycle state.

## Low-intervention authorization envelope

The project may issue one explicit, bounded authorization envelope for continuous ordinary work. The envelope contains:

- envelope identity and issuing authority reference;
- project and portfolio scope;
- permitted Delivery Tracks, Slice classes, and repository path prefixes;
- permitted action classes;
- maximum lane count, never greater than the Harness policy cap;
- required tests, gates, reviewers, and minimum review verdict;
- complete `envelopeDigest` and `REVALIDATE_NO_SCOPE_WIDENING` refresh policy;
- expiry time or expiry event;
- denied actions and mandatory stop conditions.

`envelopeDigest` is SHA-256 over canonical JSON for the complete schema-validated envelope, excluding only the digest field itself. The schema denies unknown properties. The digest covers schema version, envelope identity, issuer identity and authority-source content digest, project and portfolio, Delivery Tracks, Slice and action classes, path prefixes, lane cap, gates, reviewers, minimum verdict, refresh policy, issue/expiry facts, denied actions, and stop conditions. Lists used as sets are normalized before hashing; ordered gate sequences retain their declared order.

Within a valid envelope, the runtime may automatically select the next deterministic READY Slice, execute it, obtain its required fixed-candidate review, and submit a zero-finding candidate to the integration queue. Routine transitions do not require repeated user prompts.

The envelope never implies permission for:

- formal database or migration application;
- destructive or irreversible actions;
- secret, credential, or production access;
- scope expansion outside declared paths or action classes;
- Landing, Wave entry, remote push, release, or deployment;
- bypassing a failed gate or reviewer finding;
- changing the envelope or its issuing authority.

Those boundaries stop execution and require their own explicit authority.

A refreshed project snapshot may reuse the envelope without user intervention only when the full canonical `envelopeDigest` and its issuing authority-source content digest are unchanged and the envelope is not expired. Any field change, widening, unknown property, digest mismatch, or authorization ambiguity expires the envelope and requires a newly issued project-authoritative envelope.

## Lane execution

For each admitted lane, the Codex runtime:

1. creates an isolated worktree from `batchBaseCommit`;
2. materializes the exact Slice context and approved WriteSet;
3. follows the project's required RED, GREEN, and gate sequence;
4. rejects writes outside the exact WriteSet;
5. creates one fixed commit candidate;
6. invokes the repository-prescribed independent reviewer;
7. queues only a `GO` candidate with zero P0, P1, and P2 findings.

Lanes do not merge into one another and do not update shared generated aggregates. Lane-specific evidence is immutable and bound to the candidate commit, parent, tree, snapshot, descriptor, and gate receipts.

### WriteSet containment and invalidation

Every command that may mutate state is a managed foreground operation in the isolated lane worktree. Before it starts, the runtime validates the current fencing token and constructs an OS-enforced write sandbox from descriptor-anchored `exactWriteSet` and `ephemeralWriteSet` targets. Authorization follows the physical target, not lexical path text: every existing ancestor and final target is opened no-follow from the lane-root descriptor, its device/inode/type is captured, and any symlink or path swap invalidates the command. Creation is permitted only beneath an already anchored, non-symlink directory whose normalized path is declared. The sandbox denies all other writes, including writes reached through a symlink created after preflight. If the host cannot enforce this boundary for the full process tree, concurrent mutation is unsupported and the lane is not admitted.

Detached child processes and writes to the registered source root, another worktree, the integration worktree, or undeclared external resources are denied in policy version 1. The managed process tree must terminate before the fencing token can transition.

After each mutating command, before another command or lifecycle transition, the runtime performs a descriptor-anchored, no-follow inventory of tracked and untracked changes in the isolated lane and compares their normalized physical paths with `exactWriteSet`. Only paths explicitly declared in `ephemeralWriteSet` may be excluded; they must be Git-ignored, lane-exclusive, non-symlinked, absent from the fixed candidate, and removed at closure. Shared caches or output directories are not permitted. The before/after guard and isolated filesystem boundary limit a violation to its lane, but the declared conflict footprint is still considered disproved.

If any persistent path falls outside `exactWriteSet`, the coordinator takes the project-scoped lock and atomically records `PROJECT_WRITESET_RECOVERY`. Because the actual footprint is not yet known, it revokes every nonterminal lease fencing token for the project across all batches and plans, then stops every new admission and integration transaction. An in-flight command may finish only inside its already isolated roots; it cannot begin another mutation or transition. No original conflict graph may justify continued work.

Recovery preserves all lane evidence, calculates an `observedWriteSet`, rebuilds the conflict graph against every active and queued footprint, and marks every overlapping or authority-affected lane `STALE`. Even a non-overlapping lane resumes only under a newly validated plan and fresh lease after the project-authorized recovery receipt is recorded. Widening `exactWriteSet` always requires a new project-authorized descriptor and attempt; the envelope cannot approve it implicitly.

## Serial integration barrier

One project integration controller processes queued lane candidates in deterministic dependency and priority order. “One” is enforced by an exclusive integration lease in the Project Concurrency Coordinator, not assumed from process convention. Admission, recovery, and publication transitions use the same project-scoped OS lock and durable journal.

For each candidate the controller:

1. submits a caller-stable `integrationRequestId`, acquires the exclusive integration lease, and records a coordinator-issued `integrationAttemptId` plus `expectedIntegrationHead`;
2. verifies candidate identity, original lane receipts, fencing token, request/attempt replay status, and fresh authority for this attempt;
3. compares the candidate footprint with every change integrated since `batchBaseCommit`;
4. creates a dedicated staging ref and isolated integration worktree from `expectedIntegrationHead`;
5. applies or rebases the candidate only in staging, without force operations or target-branch mutation;
6. recomputes authority, contract, dependency, and WriteSet freshness;
7. marks the candidate `STALE` when relevant inputs changed;
8. generates shared projections or aggregates exactly once in staging;
9. runs affected gates and the full project integration gate suite in staging;
10. creates a `reviewBindingDigest` and independently reviews the fixed integration candidate against it;
11. reacquires the project-scoped lock and recomputes the complete `reviewBindingDigest` from live inputs;
12. marks the transaction `STALE` without publication if any bound input changed, expired, or was revoked;
13. checks that the target ref still equals `expectedIntegrationHead`;
14. publishes with an atomic compare-and-swap ref update from `expectedIntegrationHead` to the reviewed candidate;
15. fsyncs the published receipt before releasing the integration and lane leases.

`reviewBindingDigest` is canonical JSON over the integration candidate commit and tree, `expectedIntegrationHead`, authority snapshot, complete `envelopeDigest` and expiry status, authorization-source digest, conflict-policy version, contract-registry digest, dependency-graph digest, lane and observed WriteSets, generated-artifact manifest, gate definitions, and gate receipts. The independent review receipt is valid only for that exact digest. Any mismatch after review—including a narrower or revoked authorization—abandons the prepared transaction; a refreshed transaction must rerun generation, all gates, and independent review before it can publish.

`integrationRequestId` is supplied by the caller and remains stable only for retries of one requested integration generation. Under the project-scoped compare-and-swap, the coordinator maps `(projectExecutionKey, integrationRequestId)` to exactly one append-only transaction, allocates a monotonically increasing generation, and derives `integrationAttemptId` from the project key, request ID, generation, lane candidate, expected head, policy version, and initial review-binding inputs. A crash before the caller receives the ID is retried with the same request ID and returns the already recorded attempt.

The integration idempotency key is `(projectExecutionKey, integrationAttemptId)`. Replaying a prepared or published attempt resumes or returns its recorded outcome; it never reapplies the candidate, regenerates aggregates, or publishes twice. A `STALE` or aborted attempt is terminal and its key permanently returns that exact outcome; its receipts are append-only and cannot be overwritten or reopened.

Creating a replacement after `STALE`, changed authority, or a changed target head requires a new `integrationRequestId`. The coordinator first revalidates current project authority, envelope, lane lease, candidate, head, and recovery state, then allocates a new `integrationAttemptId`. The new attempt has no inherited generated artifacts, gates, or review receipt and must execute the complete transaction from staging. Reusing an old request ID with different inputs is rejected as an idempotency conflict.

The integration journal records `PREPARED`, `STAGED`, `REVIEWED`, and `PUBLISHED` commit points. After a crash:

- `PREPARED`, `STAGED`, or `REVIEWED` blocks other integration and new admission until the staging ref, worktree, candidate identity, and authority snapshot are audited; recovery may resume the same idempotency key or record a project-authorized abort;
- `PUBLISHED` is complete only when the target ref equals the journaled new commit; that state is finalized idempotently;
- an unexpected target ref, missing object, invalid receipt, or ambiguous journal marks that immutable attempt `STALE` and forbids automatic publication or reopening under the same request ID.

A changed Git base alone does not require user intervention. If the integrated changes are proven disjoint and the relevant authority inputs remain equivalent, the controller may refresh the candidate mechanically in a new transaction and rerun gates. Any semantic conflict, authority change, WriteSet expansion, or failed gate returns the Slice to `STALE`, `BLOCKED`, or `NO_GO` as appropriate.

Partial integration is not accepted. Application, generation, test, or review failure deletes no evidence and leaves the target ref unchanged because all work occurred in staging. Only the atomic compare-and-swap is the publication point.

## Globally serial surfaces

Policy version 1 always serializes:

- project authorization and aggregate status authorities;
- public cross-owner Contracts and their registries;
- shared schemas, catalogs, manifests, traceability indexes, and generated aggregates;
- root build, dependency-management, and repository-wide configuration files;
- DDL, migrations, formal database resources, and shared infrastructure state;
- integration-head mutation and project-wide gate closure;
- Landing, Wave entry, remote push, release, and deployment.

Private implementation contracts may remain lane-local only when the project explicitly classifies them as private and their producer-consumer closure has no cross-lane edge.

## Output contracts

The Harness adds deterministic, schema-validated projections conceptually equivalent to:

- `conflict-report.json` (`controlled-conflict-report/v1`): normalized footprints, conflict edges, clusters, and reason codes;
- `execution-plan.json` (`controlled-execution-plan/v1`): proposed lanes, queued Slices, ordering, snapshot identity, and cap;
- `authorization-decision.json` (`controlled-authorization-decision/v1`): allowed action classes, denied boundaries, and expiry;
- `lease-receipt.json` (`controlled-execution-lease/v1`): idempotency key, full footprint, fencing token, transition, and recovery status;
- `integration-refresh.json` (`controlled-integration-refresh/v1`): candidate freshness, relevant changes, and required next state;
- `integration-transaction.json` (`controlled-integration-transaction/v1`): immutable request/attempt identity and generation, expected head, staging identity, commit point, and publication receipt.

Each output records source identities and content digests. JSON output ordering and identifiers are deterministic. Human-readable explanations are projections of the same structured reason codes.

Planning and refresh outputs are advisory control artifacts. Lease and transaction receipts mutate only the safe Harness state root and record explicit caller-requested safety transitions. No Harness command launches agents, creates project worktrees, writes project files, merges commits, or approves protected actions.

## Failure and recovery

- Unknown or unreadable authority: reject admission without project writes.
- Concurrent planners may write only separately locked plan targets; every actual admission still serializes through `projectExecutionKey` and checks all nonterminal leases.
- Missing, corrupt, divergent, or unavailable coordinator state: deny every new mutation and admission pending explicit recovery.
- Lane process loss: preserve the fixed base, task identity, evidence, and lease; resume only after process-quiescence and snapshot validation.
- Authority drift during execution: accept no transition, revoke the affected fencing token, and mark the candidate `STALE` through a journaled recovery decision.
- WriteSet breach: freeze every nonterminal project lease and rebuild from `observedWriteSet`; never continue from an original graph.
- Reviewer finding: mark `NO_GO`; do not release a successor in the same conflict cluster.
- Integration conflict or compare-and-swap failure: leave the target ref unchanged and do not auto-resolve semantic conflicts.
- Generated-artifact drift: regenerate only at the integration barrier, then rerun full validation.
- Envelope expiry or stop condition: cease new admissions and stop every lane before its next mutating step; preserve its isolated worktree and existing evidence for explicit recovery.

## Backward compatibility

Existing projects without concurrency facts continue to use the current single-Slice serial behavior. Their missing concurrency fields are not guessed.

For a project adopting the model, the existing single dynamic Slice maps to one default conflict domain until explicit lane descriptors are authoritative. An active, dirty, reviewed, or fixed candidate is never retroactively split, rebased, or migrated merely because the new capability becomes available.

For Pay-Nexus specifically:

- Harness implementation begins with project-neutral fixtures;
- immediately before any Pay-Nexus-specific phase, a fresh live Authority Snapshot must identify the then-active, dirty, reviewed, or fixed Slice chain because the existing Harness sidecar may lag the project's current Slice;
- every such pre-existing Slice chain remains untouched, and Pay-Nexus adoption starts only from a clean, project-authorized checkpoint after that chain closes or is explicitly superseded;
- Pay-Nexus authority files, not the Harness sidecar, declare the portfolio, lane, Slice, envelope, and stop facts;
- the sidecar remains read-only and projects those facts into the generic Harness schemas.

## Delivery phases

### Phase 0 — Written design gate

Commit and review this specification. No runtime behavior changes.

### Phase 1A — Generic Harness planner

Add project-neutral descriptor and envelope schemas, canonical normalization, conflict calculation, deterministic provisional plan outputs, negative fixtures, and read-only CLI checks. Preserve the “no workflow engine” boundary. This is the first implementation-plan scope.

### Phase 1B — Single-host coordination safety

Add the safe durable state root, project-scoped lease/CAS primitive, fencing and replay rules, WriteSet-breach quarantine decisions, recovery receipts, and race/crash tests. This primitive records explicit transitions but launches no work.

### Phase 1C — Integration transaction safety

Add integration refresh decisions, exclusive integration leases, staging transaction validation, expected-head compare-and-swap receipts, and crash/replay recovery tests. The Codex runtime remains responsible for invoking Git and gate commands described by the validated transaction.

### Phase 2 — Pay-Nexus read-only projection

After Phase 1A through Phase 1C fixed-candidate acceptance, first prove a fresh Pay-Nexus Authority Snapshot from live project-owned sources, then extend the Harness-owned sidecar to extract those admission facts and validate a read-only planning scenario. Do not treat the pre-existing DEV-S01 sidecar projection as proof of the current Slice, and do not write Pay-Nexus.

### Phase 3 — Project authority adoption

At a clean Pay-Nexus checkpoint and under separate explicit authorization, add project-owned portfolio, conflict-domain, Slice, and envelope facts. Rebuild the sidecar lock and projection from those facts.

### Phase 4 — Controlled pilot

Run two independent lanes first. Compare predicted conflicts with integration results. Increase the project cap to three only after the pilot has no isolation or authority finding.

The implementation plan following this spec covers Phase 1A only. Phases 1B, 1C, and every later phase receive their own plan, exact WriteSet, fixed candidate, and review. Project-specific phases also require separate project authorization.

## Verification and acceptance

Phase 1A acceptance requires tests for:

- deterministic normalization and plan identity;
- same-Owner serialization;
- exact WriteSet, shared-artifact, and migration overlap;
- direct and transitive producer-consumer conflicts;
- public-contract and global-surface serialization;
- genuinely disjoint cross-Owner admission;
- missing and unknown facts failing closed;
- stale snapshot and descriptor rejection;
- deterministic priority and dependency ordering;
- at most one proposed Slice per conflict cluster;
- maximum three proposed lanes;
- envelope allow, deny, expiry, and stop behavior;
- `envelopeDigest` mutation negatives for every authoritative field and unknown-property rejection;
- schema and path-boundary negatives;
- compatibility fallback to the existing serial model;
- unchanged registry, catalog, resolver, projection, learning, and engineering gates;
- full test-suite success from a clean candidate checkout.

Phase 1B acceptance additionally requires concurrent-process tests for cross-target, cross-plan, cross-batch, project-wide lane-cap enforcement, replay, snapshot change, policy change, fencing, lease retention through `INTEGRATING`, crash, state loss, and project-authorized recovery. WriteSet tests must cover tracked and untracked breaches, symlink ancestor/final-target/path-swap escape attempts, unavailable process-tree sandbox rejection, in-flight fencing, project-wide cross-batch freeze, `observedWriteSet` recomputation, affected-lane staleness, and fresh-plan-only recovery.

Phase 1C acceptance additionally requires competing integration-controller, changed-head, apply failure, generated-artifact failure, review failure, authority and every envelope field changing after review, expiry/revocation after review, `reviewBindingDigest` mismatch, mandatory gate/review rerun, crash before and after attempt-ID delivery and at every journal commit point, same-request replay, same request with changed inputs, same candidate/head/policy with a new authorized generation, terminal-`STALE` immutability, replay-before-publication, replay-after-publication, atomic ref compare-and-swap, and target-ref-unchanged negatives.

Later Pay-Nexus acceptance additionally requires exact read allowlists, zero unauthorized project writes, authority-source freshness, project-specific negative scenarios, and independent review of both the lane candidate and the serial integration candidate.

## Operational measures

The pilot records:

- admitted lane count and completed Slices per batch;
- elapsed time relative to serial execution;
- conflict false positives and missed conflicts;
- stale-candidate and integration-rejection rates;
- gate and review failure rates;
- number and cause of user interventions;
- number of automatic fallbacks to serial execution.

Throughput is not a success if missed conflicts, stale candidates, unauthorized actions, or integration rejection increase. The initial objective is demonstrably safe two-lane execution with fewer routine prompts, not maximum parallelism.

## Stop conditions

The runtime stops admitting new work when any of the following occurs:

- no deterministic READY selection exists;
- the authority snapshot or envelope is invalid, stale, or expired;
- a required conflict fact is unknown;
- a lane exceeds its exact WriteSet or action class;
- a required test, gate, or review fails;
- a protected boundary is reached;
- the user or project authority pauses or revokes execution;
- the integration barrier cannot prove a clean, current candidate.

These stops are safety behavior, not permission to silently expand scope. For an ordinary lane-local stop, independent lanes may continue only when the current project authority, coordinator leases, and still-valid conflict graph prove that the condition does not affect them. A WriteSet breach or coordinator-state inconsistency stops every nonterminal project lane; shared-authority drift or pending integration recovery stops every affected batch. Work resumes only after a fresh plan and recovery receipt exist.
