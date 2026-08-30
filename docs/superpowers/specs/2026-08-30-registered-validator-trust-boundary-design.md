# Registered Validator Trust Boundary Design

**Status:** APPROVED BASE; BENCHMARK-ISOLATION APPROACH APPROVED — written amendment pending user review

**Date:** 2026-08-30

**Supersedes:** only the hostile-Validator process-containment assumptions added
during Fix Rounds 2–5 of the external Pack toolchain-profile implementation. It
does not replace the canonical identity, provisioning, binding, session-reuse,
lock, projection, or project-Authority requirements in
`2026-08-29-external-pack-toolchain-profile-decoupling-design.md`.

## Decision

Harness treats the exact registered Validator bytes as part of its trust root.
External Pack candidate content is untrusted input to that Validator. The
Validator owns domain-specific containment of any candidate-derived command it
chooses to execute and must fail closed when that containment is unavailable.

Harness does not claim to contain a malicious registered Validator running as
the same host user. It therefore must not use process-group cleanup as proof that
all Validator descendants have been contained or terminated.

This boundary follows the existing canonical identity model: registration pins
the Validator digest, ABI, source commit/tree/content, history contract, timeout,
and toolchain profile. Changing Validator behavior requires a new digest and an
explicit registration/lock review.

## Why this boundary is required

The rejected candidate `f0807f3` tried to treat the registered Validator itself
as hostile while continuing to execute it as the current host user. A child can
create another process group or session, so POSIX process-group cleanup cannot
prove full descendant convergence. The same Validator could also read or modify
other same-user resources before returning; process cleanup alone would never be
a complete hostile-code sandbox.

The low-burden macOS alternative is not a durable Harness-wide dependency:

- `/usr/bin/sandbox-exec` is present and already used by scoped project guards,
  but its macOS manual marks it deprecated;
- Apple's supported App Sandbox helper model requires a containing signed app or
  helper/XPC distribution and signing lifecycle;
- a Linux container changes the Darwin Java/Maven toolchain identity and adds a
  host bootstrap dependency for every adopter.

Harness must not replace ChatGPT App coupling with a deprecated OS-tool coupling,
or make every adopting project install a new container/signing runtime as part of
this performance correction.

## Trust model

### Trusted and identity-pinned

- Harness source and schemas in the fixed candidate;
- exact registered Validator bytes and `CAPABILITY_PACK_VALIDATION_ABI`;
- canonical Pack source commit, tree, selected content, and content digest;
- canonical toolchain profile and host-local binding witness;
- operation-scoped `CapabilityVerificationSession` state and retained checkout;
- project Authority, registration, lock, and projection algorithms.

### Untrusted input

- Pack candidate content before the registered Validator accepts it;
- project locators and host-local binding paths before validation;
- ambient `PATH`, application bundles, package-manager metadata, timestamps, and
  network state;
- Validator stdout/stderr and exit status until Harness validates the process
  result and completes post-Gate identity checks.

### Explicitly outside this task's security claim

- a malicious or compromised registered Validator whose pinned bytes are already
  accepted as the validation program;
- a malicious same-UID host process, root, kernel compromise, or administrator;
- replacement of the Java Pack's own generated-source isolation implementation;
- a general-purpose cross-platform sandbox product.

Moving any of these into scope requires a separate product design with a signed
App Sandbox/XPC helper, dedicated service identity, or platform-specific VM/
container toolchain. It is not an implicit extension of Pack validation caching.

## Runtime contract

### Candidate Gate runner

Restore the pre-supervisor candidate runner contract:

- execute the exact absolute interpreter and fixed Validator path;
- start one process session so timeout cleanup can target the original group;
- capture stdout/stderr and preserve the Validator's real exit status;
- on timeout, send bounded termination to the original group and fail closed;
- do not install a supervisor, signal-disposition shim, status side channel, or
  claim of complete descendant convergence;
- preserve legacy `SANITIZED` and `REGISTERED_TOOLCHAIN_OFFLINE_CACHE` behavior.

Normal success does not signal the Validator process group. A registered
Validator must not detach work beyond its own completion. This is a Validator ABI
obligation, not an unenforceable same-UID process-containment claim.

### Managed runtime scratch

`MANAGED_TOOLCHAIN_PROFILE` receives an operation-private `TMPDIR` under the
Harness Git common-root cache. The scratch path is runtime-only and must never
enter registration, profile, binding witness, lock, projection, Pack key, or
`VerifiedToolchain.environment`.

Retain the already implemented descriptor-based safety properties:

- trusted, non-symlink common-root traversal;
- effective-user ownership, mode `0700`, and macOS ACL neutralization;
- cleanup restricted to the recorded owned inode;
- unrelated directory or symlink replacements are preserved;
- public-chain ambiguity and cleanup failure prevent Pack publication.

These checks prevent Harness cleanup mistakes and detect Validator defects. They
do not elevate TMPDIR into a sandbox against a malicious registered Validator.

### Candidate-derived execution

A registered Validator that executes candidate-controlled build or generator
commands must provide and self-test its required isolation. For the current Java
Pack, the Validator already probes its macOS isolation for both permitted work and
denied network/repository-external writes, and reports
`QUALITY_GENERATED_SOURCE_ISOLATION_UNAVAILABLE` when that capability is absent.

Harness records the exact Validator identity that ran. It does not duplicate or
silently weaken the Java Pack's project-specific isolation semantics.

## Performance and reuse

The trust-boundary correction does not change the performance architecture:

- one `CapabilityVerificationSession` performs one full Gate per immutable Pack
  identity and measured binding;
- resolve, projection, install dry-run, freshness, lock verification, and repeated
  scenarios consume the same `VerifiedCapabilityPack`;
- public APIs without a supplied session still validate completely and fail closed;
- source, registration, lock, Validator, profile, binding, toolchain, or checkout
  drift poisons the session and prevents reuse;
- no result is trusted across processes or persisted as a permanent Gate cache.

The Java acceptance target remains one Gate, with an allowed maximum of two, and
six directory digests, with an allowed maximum of twelve, for the equivalent
scenario/install group. The total runtime reduction target remains at least 70%,
subject to the fixed before/after benchmark.

## Benchmark isolation amendment

### Why the original Pay benchmark cannot remain the acceptance fixture

The active Java registration now uses `MANAGED_TOOLCHAIN_PROFILE` and registration
fingerprint
`sha256:cd5bbf5e763b38c96fccbf4c5a9357497c82e10fbf2272e4693fbcd2f63a708b`.
The committed `integrations/pay-nexus-shadow` lock intentionally remains bound to
the real Pay historical registration, whose legacy Validator identity uses
`REGISTERED_TOOLCHAIN_OFFLINE_CACHE`, contains the App-local `rg` locator, and has
a different registration fingerprint.

Harness correctly rejects that drift before scenario resolution. Refreshing only
the Harness shadow would break its exact binding to the real Pay historical
registration and would amount to an unauthorized Pay rebind. Keeping those seven
nodes as the performance acceptance fixture would therefore make the Harness
optimization depend on a separate consumer migration—the coupling this task is
intended to remove.

### Harness-owned immutable benchmark fixture

Add a committed, test-only fixture at
`tests/fixtures/java-toolchain-profile-pay-benchmark/` with:

- a synthetic source containing only stable Markdown authority facts required by
  the benchmark;
- a neutral integration and control plane that select the exact registered Java
  Pack plus the existing internal architecture-review Skill;
- six scenario YAML files preserving the original benchmark's intent, topic,
  requested output, stage/reopen inputs, and expected resolver results, but using
  benchmark-specific IDs;
- no copied Pay lock, Pay projection, Pay repository locator, Pay Git identity,
  or claim that the fixture is Pay Authority.

The benchmark test copies the minimal Harness roots and this fixture into a
temporary directory. In one explicit `CapabilityVerificationSession`, it builds
the current lock and CODEX integration projection, executes the six scenario
nodes, checks freshness, and performs one install dry-run. Lock/projection outputs
are runtime evidence in the temporary directory; they are never committed as a
second source of truth.

The seven stable acceptance nodes are:

```text
tests/test_java_toolchain_profile_pay_benchmark.py::test_java_toolchain_profile_pay_scenario_benchmark[closed-architecture-protection]
tests/test_java_toolchain_profile_pay_benchmark.py::test_java_toolchain_profile_pay_scenario_benchmark[consumed-stage-does-not-authorize-wave0]
tests/test_java_toolchain_profile_pay_benchmark.py::test_java_toolchain_profile_pay_scenario_benchmark[current-authority-denies-execution]
tests/test_java_toolchain_profile_pay_benchmark.py::test_java_toolchain_profile_pay_scenario_benchmark[next-slice-readiness-resolution]
tests/test_java_toolchain_profile_pay_benchmark.py::test_java_toolchain_profile_pay_scenario_benchmark[review-go-does-not-authorize]
tests/test_java_toolchain_profile_pay_benchmark.py::test_java_toolchain_profile_pay_scenario_benchmark[stage4-stop-replay]
tests/test_java_toolchain_profile_pay_benchmark.py::test_java_toolchain_profile_pay_install_plan_benchmark
```

All seven remain `integration` and `pack_e2e`; no production API or Registry
algorithm is added for the fixture.

### Equivalence contract

The benchmark proves Harness validation cost only when every run establishes:

- the same six scenario input/expectation vectors and PASS results as the original
  baseline, including `PROJECT_TRUTH_WINS`, required authority facts, selected and
  excluded capability IDs, and the closed scenario's Java exclusion;
- immutable Java commit/tree/content/Validator/history/timeout identity plus the
  fixed managed profile and registration fingerprint;
- exactly 45 byte-identical Java resource files and the fixed Java resource-set
  digest;
- the existing internal architecture-review Skill remains present, so the install
  dry-run has the original 46 total actions: 45 Java resources plus one internal
  Skill action;
- all development, repository landing, DDL, database write, Wave 0, and Git push
  permissions remain `DENY`;
- exactly one Java candidate Gate, one isolated checkout, and six toolchain
  directory digests across all six scenarios, projection freshness, and install;
- the source fixture is byte-identical before and after every read-only operation;
- no App path, fallback toolchain identity, persistent cache, or cross-process
  verified result enters the operation.

The fixed historical baseline durations remain `4037.40s`, `2910.40s`, and
`2654.28s`. The optimized three-run median is compared with the same `2910.40s`
median because the scenario/install workload is preserved. The result is evidence
of Harness cost reduction, not evidence that Pay adoption has been rebound or is
ready for implementation.

### Real Pay adoption sentinel

Do not mark the stale Pay nodes `xfail` or skip them: either mechanism could hide
an unrelated regression behind the expected drift. Keep the structural Pay
identity tests, and replace the seven no-longer-runnable success nodes with one
explicit Pack-E2E sentinel that calls the real integration path, asserts the exact
legacy-lock registration-drift failure, and proves the cloned Pay source remains
unchanged. Removing that sentinel or restoring Pay scenario success requires the
separate Pay rebind/Authority task.

## Implementation sequence

1. Add deterministic tests that express this trust boundary and preserve legacy
   signal/exit/timeout behavior.
2. Remove the `f0807f3` supervisor/status-pipe implementation while retaining safe
   managed scratch and post-Gate TOCTOU checks.
3. Prove ordinary success, nonzero exit, startup failure, timeout, output capture,
   scratch cleanup, replacement preservation, and session poisoning.
4. Resume the paused Java profile migration without changing Java Pack content or
   Validator bytes.
5. Regenerate Harness Registry and neutral fixture lock/projections from one real
   Java Gate executed outside the outer Codex filesystem sandbox.
6. Add the Harness-owned immutable seven-node benchmark fixture and retain one
   exact fail-closed sentinel for the unchanged real Pay adoption lock.
7. Run the fixed equivalent scenario/install benchmark and assert per-Pack counters.
8. Complete focused regressions, disjoint tier receipts, one full unfiltered
   regression, and one fixed-candidate independent `deep_reviewer / xhigh` gate.

Product-level resumable shard receipts remain the separately deferred scope in
`2026-08-29-pytest-shard-receipts-design.md`; this design does not authorize or
implement that subsystem.

## Acceptance criteria

- no supervisor loop, private status pipe, inherited ignored `SIGTERM`, or claim of
  full hostile-Validator descendant convergence remains;
- legacy Gate exit, signal, timeout, stdout, and stderr behavior matches the
  pre-`afa97a8` contract;
- managed-profile Gate receives a private runtime `TMPDIR`, while canonical bytes
  remain locator-free and App-independent;
- safe scratch cleanup and pre/post source, Validator, toolchain, and binding
  measurements remain fail closed;
- Java Pack candidate Gate passes using the registered toolchain profile with no
  ChatGPT App path or fallback;
- Java Gate and directory-digest counts meet the stated limits;
- the Harness-owned benchmark passes all seven stable nodes with the equivalence
  contract above, while the real Pay sentinel passes only by observing the exact
  expected legacy-lock drift;
- Registry, lock, resolution, projection, closed-scenario selection, business
  `DENY`, and exact fingerprint semantics remain unchanged except for the approved
  one-time Java profile migration;
- no `integrations/pay-nexus-shadow`, real Pay-Nexus, Java Pack, Validator, merge,
  push, release, deploy, or business execution write occurs in this Harness
  candidate.

## Rejected alternatives

### Make `sandbox-exec` the Harness-wide Gate boundary

Rejected as the default because the tool is deprecated and would become a new
host lifecycle dependency. Its existing scoped uses remain unchanged.

### Build a signed App Sandbox/XPC Runner in this task

Rejected because it adds a macOS product, signing, packaging, installation, and
release lifecycle. Apple documents this as the supported strong-isolation route,
but it requires a separately authorized product plan.

### Move the Darwin Pack Gate into Docker or a Linux VM

Rejected because it changes the toolchain platform/identity and imposes a new
runtime bootstrap on every host. It is not a transparent performance fix.

### Accept the process-group supervisor as sufficient containment

Rejected because process groups are not a complete descendant boundary and the
supervisor changed legacy signal semantics. The final review of `f0807f3` remains
valid NO-GO evidence for that implementation.

### Rebind the Harness Pay shadow inside this performance task

Rejected because the shadow is intentionally tied to a real Pay historical
registration. Refreshing only its lock/projection would falsify that contract;
refreshing the real Pay registration requires a separate project Authority and
rebind task.

### Mark the seven stale Pay success nodes xfail or skip

Rejected because a broad expected-failure marker accepts any failure cause and a
skip stops testing the fail-closed boundary. One exact drift sentinel is smaller,
deterministic, and preserves the adoption truth without contaminating the Harness
performance benchmark.
