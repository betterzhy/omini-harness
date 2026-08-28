# External Pack Validation Lifecycle Scaling Design

## Status and decision

This specification records the user-approved architectural direction for fixing
repeated External Capability Pack validation in Harness. It is a design artifact,
not an implementation, fixed candidate, Gate receipt, merge, release, or downstream
adoption authorization.

The change is classified as R2 because it touches Registry, immutable Pack identity,
exact lock verification, validator/toolchain identity, projection provenance, and
TOCTOU behavior. Runtime implementation must use RED → GREEN, a bounded Exact
WriteSet, stable-candidate verification, and one independent `deep_reviewer / xhigh`
review. No implementation candidate may merge to `main`, push, release, deploy, or
modify an external Pack or project Authority without separate authorization.

This specification intentionally separates two candidates:

1. this document owns the in-process validation lifecycle and deterministic cost
   counters;
2. `2026-08-29-pytest-shard-receipts-design.md` owns pytest cost lanes, node-level
   progress, sharding, and interrupted-run receipts.

The split prevents a Pack validation optimization from silently introducing a
cross-process trust cache or a new test-receipt authority system.

## Problem statement

Harness currently treats every request for an active External Pack as a request to
repeat the complete candidate acceptance Gate. `get_registered_capability_pack()`
loads the registration and calls `_validate_registration()` on every invocation.
Resolver, lock verification, projection validation, freshness, integration, and
install then enter the same path independently.

At repository HEAD `7a76cf0544a747cda10ca1785f03daab7459204b`, the Pay-Nexus Java pilot test has this
static amplification:

```text
six scenario resolutions       6 complete candidate Gates
one install dry-run            8 complete candidate Gates
total                         14 complete candidate Gates
```

Each complete Java Gate creates an isolated fixed checkout and validates the
registered toolchain three times. Each toolchain validation recursively hashes
`javaHome`, `mavenHome`, and the Maven repository. The current static count is thus:

```text
14 Gates × 3 toolchain validations × 3 directory digests = 126 directory digests
```

The observed full regression was interrupted after 3,604 seconds with 644 tests
passed while executing this test. That receipt is evidence of a control-plane
availability problem; it is not a complete regression PASS or an isolated benchmark.

The defect is in Harness Core. Java only exposes it because its validator and
toolchain closure are expensive. Any External Pack follows the same repeated Gate
path, and cost grows approximately with the number of selected external Packs and
nested verification entrypoints.

## Goals

The implementation must:

1. run a complete candidate Gate at most once for the same exact Pack identity in
   one explicit validation session;
2. reuse only a successful, immutable, operation/session-scoped verified object;
3. preserve current public return shapes and fail-closed behavior when no session is
   supplied;
4. keep source, registration, lock, validator, and projection TOCTOU checkpoints;
5. reduce registered-toolchain full directory digests to one pre-Gate and one
   post-Gate snapshot per complete validation;
6. reject identity mismatch, session/root mismatch, a closed session, or a foreign
   verified object;
7. retain the fixed isolated checkout for the session and read Pack bytes only from
   that verified materialization;
8. expose deterministic, read-only counters for Gate, checkout, directory-digest,
   recheck, and reuse events;
9. leave canonical Registry, lock, resolver, projection, and install bytes and
   semantics unchanged;
10. preserve all project Authority and business execution `DENY` decisions.

## Non-goals

This candidate will not:

- create a process-global, TTL, disk, database, remote, or cross-process validation
  cache;
- create a signed Pack Gate receipt or make an old Gate result current Authority;
- change Capability Pack Registry identity, `capability-lock/v2`, canonical lock
  fingerprinting, or locator exclusion rules;
- change Java Pack content, its validator, Maven repository, or registered toolchain;
- change project Authority, projection business semantics, Skill install/apply, or
  execution permissions;
- remove negative scenario coverage or weaken post-read/pre-swap/post-swap checks;
- automatically parallelize external candidate Gates;
- repair the Pay-Nexus-specific `originalSourceRoot` / replacement-root validator
  correctness defect;
- add Bazel, SLSA, OPA, Temporal, a remote CAS, pytest-xdist, or another framework.

## Considered approaches

### A. Explicit operation/session-scoped verified context — selected

An explicit `CapabilityVerificationSession` owns verified Packs, retained isolated
checkouts, verified lock contexts, cleanup, and counters. Public operations accept an
optional keyword-only session. A caller may deliberately share a session across a
bounded batch, such as all nodes in one serial `pack-e2e` shard. When no session is
provided, the public operation creates and closes a private session before returning.

This option makes lifetime and reuse visible, preserves fail-closed public behavior,
and can meet the Gate-count acceptance target without persistent trust.

### B. Module/global `lru_cache`, TTL cache, or implicit process singleton — rejected

These approaches do not express the operation boundary, are difficult to invalidate
under registration/lock/toolchain changes, leak across unrelated callers and tests,
and invite accidental trust after Authority or source changes.

### C. Persistent CAS or signed validation receipt — deferred

A persistent result would require a separate trust domain, writer policy, receipt
schema, signer identity, revocation/invalidation, current Authority decision, and
read-back verification. It is not required to remove the current 14× amplification
and would turn a focused P1 repair into a new subsystem.

Content-addressed build systems support reuse only when the action key includes all
declared inputs, commands, tools, environment, and platform. Harness adopts that
identity discipline for an in-process session, not the persistent trust model. See
[Bazel Remote Caching](https://bazel.build/remote/caching) and
[Bazel Hermeticity](https://bazel.build/concepts/hermeticity).

## Core types

All trust-bearing types are immutable from consumers and created only by Harness.
Nested dictionaries/lists are represented by canonical bytes, frozen tuples, and
read-only mappings; a frozen dataclass containing caller-owned mutable containers is
not sufficient. Public compatibility returns are defensive copies. The trust-bearing
objects are not serialized into Registry, lock, resolved context, projection, or
receipts.

### `PackVerificationKey` and `LockVerificationKey`

`PackVerificationKey` is canonical JSON hashed with SHA-256. It contains:

- explicit module constant `CAPABILITY_PACK_VALIDATION_ABI = "v1"`; it is bumped
  whenever validation, key construction, or candidate-Gate input semantics change;
- canonical registration record and `registrationFingerprint`;
- `registrationId`, `capabilityId`, and Pack version;
- source commit, source tree, resolved content digest, and manifest digest; a tracked
  manifest digest is SHA-256 over bytes from its captured fixed Git blob, while a
  Harness-declared manifest digest is SHA-256 over canonical JSON;
- validator blob digest, argv contract, history contract, environment contract, and
  timeout;
- registered command and toolchain identities, including the expected directory
  digests;
- a canonical allowlist containing `os.name`, `sys.platform`, and normalized machine
  architecture. These facts scope in-process reuse only and do not enter Pack/lock
  canonical fingerprints.

The Pack key uses the registered expected toolchain directory digests. Full pre-Gate
measurement must equal those values before the key can become verified; the measured
values are also retained in `VerifiedToolchain` and must match the post-Gate
measurement.

The Pack key deliberately excludes a project lock. Candidate-Gate acceptance is a
fact about one exact Pack/validator/toolchain action and may be reused by two verified
locks in the same explicit session. Binding that fact to a project is the separate
responsibility of `LockVerificationKey`.

`LockVerificationKey` contains the exact lock fingerprint, project identity,
state/binding witnesses, internal Registry/catalog revisions, and the ordered
`PackVerificationKey` values for every selected external capability. A lock or
project-control-plane change therefore invalidates the lock context without forcing
two candidate Gates for an otherwise identical Pack in the same session.

`source.repositoryPath` remains excluded from canonical Pack and lock identities. The
session separately records a non-canonical locator witness so that the checked source
cannot silently change or relocate during the operation.

### `VerifiedToolchain`

`VerifiedToolchain` records the validated command paths, their content digests, the
three validated directory roots/digests, derived `PATH`, `HOME`, and `JAVA_HOME`, and
the exact environment passed to the validator.

It is created by one pre-Gate verification. `_validator_environment()` must consume
this object and must not recursively hash the same directories again. One post-Gate
verification recomputes command and directory identities and compares them with the
pre-Gate object.

The toolchain is used only by the candidate Gate. Once the post-Gate comparison
passes, later Pack consumers use the frozen Pack materialization, not the toolchain.
A mutation before or during the Gate fails the current session; a mutation after a
successful session changes the next session's input and forces a new validation. A
successful result is never reinterpreted as having run on a later toolchain state.

### `VerifiedCapabilityPack`

`VerifiedCapabilityPack` contains:

- its `PackVerificationKey` and owning session token;
- an immutable copy of the validated registration and manifest;
- the physical source locator witness used for live drift checks;
- fixed commit/tree and selected Git entries;
- the retained isolated checkout root;
- the verified toolchain identity;
- methods to read one or all selected blobs by the captured Git object IDs from the
  retained isolated repository, never by reopening mutable working-tree paths;
- a `recheck()` method that validates current registration bytes, locator identity,
  source commit/tree, hidden-index state, cleanliness, manifest provenance, and the
  expected fixed Pack identity without rerunning the candidate Gate.

Pack bytes must not be read from the mutable discovery locator after verification.
The session owns retained checkout context managers through one `ExitStack`. Close is
idempotent, excludes new/in-flight users, waits for any current verifier, and unwinds
all retained checkouts even if one cleanup reports an error. Cleanup failure makes the
owning operation fail; it never leaves a verified object usable.

### `VerifiedLockContext`

`VerifiedLockContext` contains:

- immutable lock bytes and exact lock fingerprint;
- the project state/binding and referenced profile witnesses used to verify the lock;
- the design Registry, active catalog, internal/external collision, and external
  registration witnesses used by current lock verification;
- current internal locked entries;
- external capability IDs mapped to `VerifiedCapabilityPack` objects;
- the owning session token and repository/project roots.

The public `verify_capability_lock()` return remains the existing `(lock, entries)`
tuple. Internal callers use the context so that downstream operations do not turn a
verified Pack back into an untrusted plain dictionary and trigger another Gate.

### `VerificationStats`

The session exposes an immutable snapshot of non-authoritative operational counters:

```text
fullCandidateGateCount
isolatedCheckoutCount
toolchainDirectoryDigestCount
verifiedPackCount
verifiedLockCount
packReuseHitCount
lockReuseHitCount
sourceRecheckCount
registrationRecheckCount
```

The snapshot includes totals and the same counters grouped by
`PackVerificationKey`, so a multi-Pack session cannot hide an extra Java Gate inside
an aggregate ceiling.

Counters are observational evidence only. They do not enter canonical fingerprints
or grant Gate/merge/release authority.

## Session lifecycle and API propagation

`CapabilityVerificationSession` is a context manager bound to one resolved Harness
repository root. It has `OPEN`, `VERIFYING`, `VERIFIED`, and `CLOSED` lifecycle rules:

1. construction performs no validation;
2. the first request for an exact Pack identity runs full validation;
3. a successful result is stored under the exact key;
4. a repeated request first rechecks current registration/source witnesses and then
   returns the same verified object;
5. a changed identity for the same registration/capability within one session fails
   closed; a deliberately requested different capability has its own Pack key and may
   be validated independently;
6. failures do not create reusable entries;
7. close invalidates every verified object and cleans every retained checkout;
8. use after close, a different repository root, or a different session raises an
   error before reading Pack bytes.

If the same key is requested concurrently inside one session, a short-held mutex
changes its entry from `UNSEEN` to `VERIFYING` and selects one owner. The mutex is not
held while Git, hashing, or the candidate Gate runs. Waiters block on that entry's
condition/future. The owner atomically publishes `VERIFIED` or the same failure to all
waiters; a failed entry is then removed rather than cached as trust. Session close and
new verification are mutually exclusive: close waits for an already in-flight owner,
rejects new requests, then unwinds resources. This is process-local single-flight only.

The optional keyword-only `verification_session` is propagated through:

- `get_registered_capability_pack`;
- `build_capability_pack_registry`;
- `build_all_registries`;
- `build_capability_lock`;
- `verify_capability_lock` and its internal context-returning helper;
- `resolve_design_context`;
- `resolve_integration_context`;
- `run_integration_scenario`;
- projection build, validation, and freshness;
- integration projection/freshness;
- projection install planning;
- structural assurance paths that validate multiple Packs/projects in one command.

The serial Pay-Nexus `pack_e2e` module fixture is the explicit owner that surrounds
the six parameterized scenario operations and the separate install-plan operation.
It passes one open session to all seven public calls and closes it after the shard.
This is the concrete path that turns the current fourteen complete Gate entries into
one. Independent pytest processes or ordinary calls without that owner do not share
the result.

Compatibility behavior is mandatory:

- a public call without a session creates a private session, performs complete
  validation, closes it before returning, and preserves the current return value;
- nested calls always propagate the current explicit session;
- a public call with a valid open session may reuse only exact successful identities;
- no API accepts a caller-created dictionary as proof of validation.

CLI commands continue to expose the same user-facing schema. The top-level operation
called by a command owns one session and propagates it through all nested work; only a
CLI dispatch path that itself sequences multiple independent operations needs to own
the session in `cli.py`. Ordinary independent CLI processes never share validation
trust.

## Validation and TOCTOU sequence

The first validation of a Pack in a session executes:

1. load and schema-validate the selected registration;
2. resolve the absolute, normalized, non-symlink discovery locator;
3. verify source commit/tree, hidden index flags, cleanliness, manifest identity,
   selected content digest, and validator Git blob digest;
4. compute the pre-Gate `VerifiedToolchain`, including exactly three full directory
   digests for the registered Java/Maven directories;
5. materialize one isolated fixed checkout and retain it in the session;
6. verify validator bytes in the checkout and run the fixed candidate Gate with the
   environment derived from `VerifiedToolchain`;
7. recompute validator/toolchain identity after the Gate, including exactly three
   full directory digests;
8. recheck the original source locator and registration identity;
9. construct `VerifiedCapabilityPack` only if every step passes.

Later reads use only captured Git object IDs in the retained fixed repository. Before returning resolution,
validating freshness, and at every existing projection post-read/pre-swap/post-swap
checkpoint, Harness rechecks registration, lock, and live source witnesses without
running the validator or recomputing the toolchain directory digest.

The locator witness is deliberately session-local. Moving an unchanged Pack to a new
locator during one open session is drift and fails that session. A later session may
accept the relocated discovery path when commit/tree/content/validator/registration
canonical identities remain equal; canonical fingerprints continue to exclude the
locator.

This preserves the current fail-closed projection rollback/removal behavior. A source
or lock change during projection still prevents a new canonical projection from
remaining visible. The mitigation follows the general TOCTOU rule of binding check
and use to one immutable object and retaining boundary rechecks; see
[MITRE CWE-367](https://cwe.mitre.org/data/definitions/367).

## Error behavior

Existing external error categories and public exception types remain stable where
tests assert them. Internally, failures distinguish at least:

- registration or lock identity drift;
- source locator/commit/tree/cleanliness drift;
- content or validator identity drift;
- toolchain pre-Gate or post-Gate drift;
- candidate Gate failure or timeout;
- foreign, closed, or repository-mismatched session;
- retained checkout cleanup failure.

No error path may return a verified object, publish a new projection, preserve a new
post-swap projection after failed recheck, or increment a reuse-hit counter.

## Test strategy

Implementation follows RED → GREEN. Deterministic tests must cover:

### Gate and digest counts

- fourteen current lookup paths collapse to one complete Gate in one shared session;
- a public call with no supplied session still performs one complete Gate;
- two exact Pack identities perform two Gates;
- one Java-style registered-toolchain Gate performs six directory digests, with an
  allowed ceiling of twelve while preserving all checks;
- one Gate creates one retained isolated checkout and cleanup occurs on success,
  Gate failure, mutation failure, timeout, and caller exception.

### Invalidation and misuse

- source commit/tree, active content, cleanliness, hidden index, or locator mutation;
- registration fingerprint, manifest, validator identity, timeout, argv, or
  environment-contract mutation;
- lock fingerprint or project state/binding mutation;
- toolchain command or directory mutation before/during the Gate;
- second session after toolchain mutation runs a new full validation;
- a failed Gate is not reused;
- a closed, foreign, or different-root session is rejected;
- a verified object cannot be forged from a registration dictionary;
- concurrent same-key requests produce one Gate and consistent failure propagation.

### Semantic preservation

- external source commit/tree/content and `capability-lock/v2` remain exact;
- locator remains outside canonical registration and lock fingerprints;
- resolver outputs, projection bytes/manifests/resource digests, lock fingerprints,
  and install-plan bytes remain unchanged;
- closed scenarios do not select Java;
- all business execution permissions remain `DENY`;
- existing blob-read, pre-swap, and post-swap mutation tests remain fail closed.

## Benchmark and acceptance

Counters are the primary deterministic acceptance evidence. Wall-clock results are
secondary and must be measured on the same machine, Harness HEAD, external source
commit/tree, JDK/Maven identities, Maven repository, network policy, and pytest
selection.

Record at least three baseline and three optimized isolated runs. Report every run,
the median, phase timings, and whether filesystem caches were warm or cold. Do not use
the interrupted full regression as the only baseline.

Acceptance for the Pay-Nexus equivalent serial `pack-e2e` batch is:

```text
complete candidate Gates       target 1, maximum 2
isolated fixed checkouts       target 1, maximum 2
toolchain directory digests    target 6, maximum 12
wall-clock reduction           at least 70%, final value reported from measurement
semantic output drift          zero
```

A complete regression is run once only after the candidate is stable. An interrupted
run is reported as interrupted, not PASS.

## Candidate implementation WriteSet

The implementation plan must narrow and freeze an Exact WriteSet before coding. The
current candidate set is:

- `src/evolution_harness/capability_pack_registry.py`
- `src/evolution_harness/project.py`
- `src/evolution_harness/registry.py`
- `src/evolution_harness/resolver.py`
- `src/evolution_harness/integration.py`
- `src/evolution_harness/scenario.py`
- `src/evolution_harness/projection.py`
- `src/evolution_harness/install.py`
- `src/evolution_harness/assurance.py`
- `tests/test_external_pack_verification_session.py`
- `tests/test_capability_pack_registry.py`
- `tests/test_lock_enforcement.py`
- `tests/test_project_state.py`
- `tests/test_registry_catalog_compat.py`
- `tests/test_resolver.py`
- `tests/test_projection.py`
- `tests/test_projection_install.py`
- `tests/test_integration_e2e.py`
- `tests/test_assurance_cli.py`
- `tests/test_cognitura_integration_fixture.py`
- `tests/test_e2e.py`

The candidate must not modify:

- `core/registries/capability-packs.yaml`;
- Capability Pack, lock, projection, or Authority schemas;
- generated registries or projections;
- `src/evolution_harness/cli.py` and the public CLI output schemas;
- any external Pack repository;
- Pay-Nexus Authority or project files;
- coordinator receipt/store code.

If implementation proves that a schema, generated artifact, external repository,
persistent state, or new dependency is necessary, work stops and the scope returns
for renewed design approval.

## Delivery sequence

1. Add RED tests for session lifetime, exact key invalidation, Gate/digest counters,
   cleanup, concurrency, and unchanged public fail-closed behavior.
2. Split registered toolchain verification from environment construction and close
   the current 3× per-Gate digest amplification.
3. Introduce `CapabilityVerificationSession` and `VerifiedCapabilityPack`, retaining
   one isolated checkout per exact Pack identity.
4. Introduce `VerifiedLockContext` and propagate the explicit session through
   resolver, projection, freshness, integration, install, and assurance.
5. Run focused regressions and existing mutation/rollback tests after each behavior
   slice.
6. Integrate the separate pytest cost-lane/receipt candidate.
7. Run the controlled before/after benchmark and one stable full regression.
8. Fix Candidate/Parent/Tree and obtain one independent `deep_reviewer / xhigh`
   review before any merge decision.

## Stop conditions

Stop implementation and request renewed review if:

- the session would need cross-process or persistent reuse;
- a canonical fingerprint or schema must change;
- source/toolchain mutation can no longer fail closed at the correct use boundary;
- projection rollback or zero-residue behavior regresses;
- public no-session behavior would skip a complete validation;
- Exact WriteSet expands into an external Pack, project Authority, generated
  projection, coordinator state, or project write path;
- the optimized candidate cannot meet the Gate/digest ceilings without weakening a
  trust invariant.
