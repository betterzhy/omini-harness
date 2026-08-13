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
| Authority reading, schema validation, exact-lock validation, conflict calculation, deterministic admission plan, and explain trace | Agent Evolution Harness |
| Isolated worktree/task creation, lane execution, fixed-candidate production, and gate invocation | Codex execution runtime |
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

For each Slice, the Harness calculates a normalized lock footprint from the declared sets. Public producer-consumer closure and dependency relationships are expanded only from explicit project graphs. The resulting Change Conflict Domain identity is a digest of the normalized footprint plus the authority snapshot and policy version.

Repository paths are compared after the existing safe-relative-path normalization. Directory and file ancestry counts as overlap. Globs must be deterministically expanded against `batchBaseCommit`; unresolved, escaping, or filesystem-dependent patterns are invalid. `sharedArtifactSet` names every shared output affected by the Slice even when that output is generated later rather than written in the lane.

Two Slices conflict if any of the following is true:

1. Their `ownerSet` overlaps. Initial policy permits only one active lane per Owner.
2. Their `factFamilySet`, `bindingSet`, `exactWriteSet`, `sharedArtifactSet`, or `migrationResourceSet` overlaps.
3. Either Slice changes a public cross-owner contract or a shared schema, registry, catalog, manifest, aggregate authority projection, root build surface, or generated source.
4. A declared producer-consumer or dependency path connects them in either direction.
5. One Slice writes an authority input used to admit the other.
6. Their admission snapshots do not share the same project and batch authority fingerprint.
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
6. Select no more than `maxParallelLanes`, capped at three in policy version 1.
7. Sort equally eligible Slices by project priority, dependency depth, then canonical `sliceId`.
8. Emit admitted, serialized, blocked, and rejected results with exact reason codes.

Multiple READY Slices are valid only when they resolve to independent lanes. More than one READY Slice in the same conflict cluster is not executed concurrently; the deterministic ordering rule selects one and leaves the others queued.

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

Only one Slice may be `ACTIVE` through `QUEUED_FOR_INTEGRATION` in a conflict cluster. A `NO_GO` or `STALE` Slice releases no successor in its cluster. It does not block independent clusters unless its authority or dependency surface is shared.

Lifecycle facts are project-owned. The Harness validates current facts and derives allowed next transitions; it never writes the authoritative lifecycle state.

## Low-intervention authorization envelope

The project may issue one explicit, bounded authorization envelope for continuous ordinary work. The envelope contains:

- envelope identity and issuing authority reference;
- project and portfolio scope;
- permitted Delivery Tracks, Slice classes, and repository path prefixes;
- permitted action classes;
- maximum lane count, never greater than the Harness policy cap;
- required tests, gates, reviewers, and minimum review verdict;
- authorization-fact digest and `REVALIDATE_NO_SCOPE_WIDENING` refresh policy;
- expiry time or expiry event;
- denied actions and mandatory stop conditions.

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

A refreshed project snapshot may reuse the envelope without user intervention only when the issuing authority, authorization-fact digest, permitted scope, denied actions, and stop conditions are byte-equivalent. Any widening or authorization ambiguity expires the envelope.

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

## Serial integration barrier

One project integration controller processes queued lane candidates in deterministic dependency and priority order.

For each candidate it:

1. verifies candidate identity and original lane receipts;
2. compares the candidate footprint with all changes integrated since `batchBaseCommit`;
3. reapplies or rebases the candidate onto the current integration head without force operations;
4. recomputes authority, contract, dependency, and WriteSet freshness;
5. marks the candidate `STALE` when relevant inputs changed;
6. generates shared projections or aggregates exactly once at the barrier;
7. runs affected gates and the full project integration gate suite;
8. creates a new fixed integration candidate;
9. obtains the required integration-candidate review before closure.

A changed Git base alone does not require user intervention. If the integrated changes are proven disjoint and the relevant authority inputs remain equivalent, the controller may refresh the candidate mechanically and rerun gates. Any semantic conflict, authority change, WriteSet expansion, or failed gate returns the Slice to `STALE`, `BLOCKED`, or `NO_GO` as appropriate.

Partial integration is not accepted. Failed application leaves the current integration head unchanged and preserves the lane candidate for diagnosis.

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
- `execution-plan.json` (`controlled-execution-plan/v1`): admitted lanes, queued Slices, ordering, snapshot identity, and cap;
- `authorization-decision.json` (`controlled-authorization-decision/v1`): allowed action classes, denied boundaries, and expiry;
- `integration-refresh.json` (`controlled-integration-refresh/v1`): candidate freshness, relevant changes, and required next state.

Each output records source identities and content digests. JSON output ordering and identifiers are deterministic. Human-readable explanations are projections of the same structured reason codes.

These outputs are advisory control artifacts. They do not launch agents, create worktrees, write project files, merge commits, or approve protected actions.

## Failure and recovery

- Unknown or unreadable authority: reject admission without project writes.
- Concurrent planner use of the same plan target: reject through the existing process-lock pattern.
- Lane process loss: preserve the fixed base, task identity, and evidence; resume only after snapshot validation.
- Authority drift during execution: finish no transition; mark affected candidate `STALE` at the next gate.
- Reviewer finding: mark `NO_GO`; do not release a successor in the same conflict cluster.
- Integration conflict: leave integration head unchanged; do not auto-resolve semantic conflicts.
- Generated-artifact drift: regenerate only at the integration barrier, then rerun full validation.
- Envelope expiry or stop condition: cease new admissions and stop every lane before its next mutating step; preserve its isolated worktree and existing evidence for explicit recovery.

## Backward compatibility

Existing projects without concurrency facts continue to use the current single-Slice serial behavior. Their missing concurrency fields are not guessed.

For a project adopting the model, the existing single dynamic Slice maps to one default conflict domain until explicit lane descriptors are authoritative. An active, dirty, reviewed, or fixed candidate is never retroactively split, rebased, or migrated merely because the new capability becomes available.

For Pay-Nexus specifically:

- the current DEV-S02 work and its candidate chain remain untouched;
- Harness implementation begins with project-neutral fixtures;
- Pay-Nexus adoption starts only from a clean, project-authorized checkpoint after the active candidate chain closes or is explicitly superseded;
- Pay-Nexus authority files, not the Harness sidecar, declare the portfolio, lane, Slice, envelope, and stop facts;
- the sidecar remains read-only and projects those facts into the generic Harness schemas.

## Delivery phases

### Phase 0 — Written design gate

Commit and review this specification. No runtime behavior changes.

### Phase 1 — Generic Harness planner

Add project-neutral schemas, conflict calculation, deterministic plan outputs, negative fixtures, and CLI checks. Preserve the “no workflow engine” boundary. This is the first implementation-plan scope.

### Phase 2 — Pay-Nexus read-only projection

After Phase 1 fixed-candidate acceptance, extend the Harness-owned Pay-Nexus sidecar to extract the project's current admission facts and validate a read-only planning scenario. Do not write Pay-Nexus.

### Phase 3 — Project authority adoption

At a clean Pay-Nexus checkpoint and under separate explicit authorization, add project-owned portfolio, conflict-domain, Slice, and envelope facts. Rebuild the sidecar lock and projection from those facts.

### Phase 4 — Controlled pilot

Run two independent lanes first. Compare predicted conflicts with integration results. Increase the project cap to three only after the pilot has no isolation or authority finding.

The implementation plan following this spec covers Phase 1 only. Each later phase receives its own exact WriteSet, fixed candidate, review, and project authorization.

## Verification and acceptance

Phase 1 acceptance requires tests for:

- deterministic normalization and plan identity;
- same-Owner serialization;
- exact WriteSet, shared-artifact, and migration overlap;
- direct and transitive producer-consumer conflicts;
- public-contract and global-surface serialization;
- genuinely disjoint cross-Owner admission;
- missing and unknown facts failing closed;
- stale snapshot and descriptor rejection;
- deterministic priority and dependency ordering;
- one active Slice per conflict cluster;
- maximum three admitted lanes;
- envelope allow, deny, expiry, and stop behavior;
- integration refresh after disjoint and relevant base changes;
- schema and path-boundary negatives;
- compatibility fallback to the existing serial model;
- unchanged registry, catalog, resolver, projection, learning, and engineering gates;
- full test-suite success from a clean candidate checkout.

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

These stops are safety behavior, not permission to silently expand scope. Independent lanes may continue only when the project authority and conflict graph prove that the stop condition does not affect them.
