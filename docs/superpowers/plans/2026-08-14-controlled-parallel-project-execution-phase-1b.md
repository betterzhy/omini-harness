# Controlled Parallel Project Execution Phase 1B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single-host, project-scoped coordination safety layer that turns a Phase 1A provisional plan into durable, fenced lane leases without launching project work or modifying a registered project.

**Architecture:** Keep Phase 1A pure and read-only. Add strict coordinator command/receipt schemas, a durable owner-only state store outside repositories and system temporary storage, a project-scoped CAS journal, lease lifecycle validation, a guarded-command library boundary, WriteSet breach quarantine, and explicit recovery receipts. Every mutation is serialized by one OS lock keyed only by the canonical registered project identity; lifecycle authority remains project-owned.

**Tech Stack:** Python 3.12+, standard library (`fcntl`, `os`, `stat`, `subprocess`, `json`, `pathlib`), PyYAML, jsonschema Draft 2020-12, pytest, existing `SchemaStore`, canonical hashing helpers, registration loader, Phase 1A controlled planner/conflict predicates, and macOS `/usr/bin/sandbox-exec` when a real process-tree write sandbox is exercised.

## Global Constraints

- Work only in an isolated Harness worktree created from the reviewed Phase 1A base. Never modify Pay-Nexus in Phase 1B.
- Phase 1B may write only Harness-owned coordinator state below the configured per-user state root and synthetic test roots. It does not create project worktrees, launch agents, change project lifecycle files, integrate commits, update Git refs, or write registered project paths.
- The default state root is `~/.codex/state/agent-evolution-harness/coordinator/v1`; tests override it with `AGENT_EVOLUTION_COORDINATOR_ROOT` pointing to a fresh temporary directory.
- State-root, project-directory, journal, and receipt access is descriptor-anchored and no-follow. Owner, mode, inode/type, and single-root identity checks fail closed.
- The project execution key is derived only from validated registration identity plus canonical registered source-root device/inode identity. It excludes plan, batch, snapshot, branch, worktree, and policy identities.
- Every coordinator write uses one non-blocking OS process lock keyed by `projectExecutionKey`, then fsyncs a same-directory temporary file, atomically replaces the journal, fsyncs the directory, rereads the journal, and validates the persisted receipt before unlocking.
- The acquisition idempotency key is `(projectExecutionKey, batchPlanId, sliceId, attemptId)`. A replay returns the existing nonterminal lease; a terminal replay is rejected.
- Every transition and guarded command requires the current fencing token. Missing or stale tokens fail closed.
- `BLOCKED`, `NO_GO`, `STALE`, and `CANCELLED` retain the lease. Task 4 releases only a valid `CLOSED`; a retained `CANCELLED` can release only through Task 6's durable project-authorized recovery receipt with verified process quiescence.
- Any persistent WriteSet breach freezes all nonterminal leases for the project, revokes their tokens, blocks new admissions, records `PROJECT_WRITESET_RECOVERY`, and requires a fresh plan after explicit recovery.
- Protected actions remain denied: formal database writes, migration application, destructive operations, production/secret access, Landing, Wave entry, push, release, and deployment.
- Use RED -> GREEN for every behavior task. Run focused tests during iteration; run the full Harness suite and one `gpt-5.6-sol/xhigh` fixed-candidate gate only after the Phase 1B candidate stabilizes.
- Stop after the reviewed Phase 1B local candidate. Phase 1C, Pay-Nexus Phase 2, and Pay-Nexus project writes remain separate later plans.

## Delivery Roadmap and Release Gates

```text
Phase 1B reviewed GO
  -> write Phase 1C plan
  -> Phase 1C reviewed GO
  -> write/run Pay-Nexus Phase 2 read-only projection plan
  -> prove two independent authorized Slice descriptors
  -> write Pay-Nexus Phase 3 adoption plan
  -> project-owned authorization envelope + two-lane pilot
```

No later arrow is released by tests alone. Each arrow requires its predecessor's exact Candidate/Parent/Tree, complete WriteSet, full regression receipt, and `GO / P0=0 / P1=0 / P2=0` on the fixed candidate.

## Locked Phase 1B Interfaces

### Public Python interfaces

```python
class ControlledCoordinationError(RuntimeError):
    code: str

def resolve_project_execution_identity(
    repository_root: Path,
    source_root: Path,
) -> dict[str, str | int]: ...

def acquire_lane_lease(
    repository_root: Path,
    source_root: Path,
    command: dict[str, object],
) -> dict[str, object]: ...

def transition_lane_lease(
    repository_root: Path,
    source_root: Path,
    command: dict[str, object],
) -> dict[str, object]: ...

def inspect_project_coordinator(
    repository_root: Path,
    source_root: Path,
) -> dict[str, object]: ...

def observe_lane_writes(
    repository_root: Path,
    source_root: Path,
    command: dict[str, object],
) -> dict[str, object]: ...

def record_project_recovery(
    repository_root: Path,
    source_root: Path,
    command: dict[str, object],
) -> dict[str, object]: ...

def run_guarded_command(
    lease: dict[str, object],
    lane_root: Path,
    argv: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[bytes]: ...
```

### Coordinator command identities

```text
Acquire command:
  schemaVersion, projectId, batchPlanId, sliceId, attemptId,
  authoritySnapshotFingerprint, authorizationEnvelopeDigest,
  conflictPolicyVersion, asOf, planningRequest, executionPlan,
  sliceDescriptor, authorizationEnvelope, authoritySnapshot,
  admissionAuthorityProof, fullFootprint,
  originalSourceRoot, laneRoot, expectedLaneBase, commandDigest

Transition command:
  schemaVersion, projectExecutionKey, leaseId, attemptId, fencingToken,
  expectedState, nextState, authoritySnapshotFingerprint,
  candidateIdentity, processQuiescence, lifecycleAuthorityProof,
  reviewEvidence, commandDigest

Write observation command:
  schemaVersion, projectExecutionKey, leaseId, fencingToken,
  beforeInventoryDigest, observedPaths, ephemeralPathsRemoved,
  processQuiescence, commandDigest

Recovery command:
  schemaVersion, projectExecutionKey, recoveryId, recoveryAuthorityId,
  recoveryAuthorityReference, recoveryAuthorityDigest, recoveryAuthorityPublicKey,
  signatureAlgorithm, signatureFormat, signature,
  expectedJournalVersion, processQuiescenceProofs, observedWriteSet,
  affectedLeaseDecisions, replacementPlanRequired, commandDigest
```

All schemas use Draft 2020-12, `additionalProperties: false`, explicit enums, canonical set normalization, and SHA-256 command digests that cover every field except the digest itself.

Authority/WriteSet migration (2026-08-14): the locked Acquire identity carries the complete Phase 1A `planningRequest` plus its normalized descriptor, envelope, snapshot, admission proof, and full conflict footprint. Envelope provenance is an independent issuer authority record referenced by `issuerId`, `issuerAuthorityReference`, and `issuerAuthorityDigest`. The six file-owned `controlled_planning.*` facts are owned by one separate planning manifest authority; `controlled_planning.batch_base_commit` is deliberately not a file-owned fact because that would create a Git-HEAD self-hash cycle. `admissionAuthorityProof` binds `manifestAuthorityId`, `manifestAuthorityReference`, and `manifestAuthorityDigest`; its manifest-serialized binding covers project, Slice, attempt, registered source, and lane, but excludes `expectedLaneBase`. The request and command independently require `batchBaseCommit == expectedLaneBase == rebuiltSnapshot.sourceRevision.head`. Under the project lock, Acquire reloads the registration, rebuilds the Authority Snapshot through the registered integration, exact-compares the complete snapshot, requires live `permission.development=ALLOW`, and rejects caller-rehashed facts.

Task 4 Review Fix Round 1 Authority + WriteSet migration (fixed base `5cbf34d5bfa69b12ecc95fbe872d9fa9d2ed87ee`): the actual nine-file WriteSet is `src/evolution_harness/controlled_coordinator.py`, `src/evolution_harness/controlled_coordinator_inputs.py`, `core/schemas/controlled-coordinator-transition-command.schema.json`, `tests/test_controlled_coordinator_lifecycle.py`, `tests/test_controlled_coordinator_inputs.py`, `integrations/neutral-shadow/authority-map.yaml`, `examples/external-project-source/lifecycle-authority-public.pem`, `examples/external-project-source/deep-reviewer-public.pem`, and this formal plan. The expansion was required to make lifecycle/review evidence unforgeable through current public-key authorities, to bind every candidate state and replay to the live no-follow Git Candidate/Parent/Tree, and to retain `CANCELLED` capacity until durable Task 6 recovery rather than trust caller quiescence arrays.

Task 4 Review Fix Round 2 Authority + WriteSet migration (exact base/parent `62bf3c07497bc89beb279a29bce434960b086457`; exact Candidate `e04452def6831e127f69aa321dff3c29c713fa6f`): the actual seven-file WriteSet is exactly `src/evolution_harness/controlled_coordinator.py`, `core/schemas/controlled-coordinator-transition-command.schema.json`, `tests/test_controlled_coordinator_lifecycle.py`, `tests/test_controlled_coordinator_inputs.py`, `examples/external-project-source/lifecycle-authority-public.pem`, `examples/external-project-source/deep-reviewer-public.pem`, and `docs/superpowers/plans/2026-08-14-controlled-parallel-project-execution-phase-1b.md`; Round 1's input normalizer and neutral authority-map bytes remain authoritative and unchanged. `signatureAlgorithm=ED25519` and `signatureFormat=OPENSSH_SSHSIG_V1` are closed. Lifecycle uses SSHSIG identity `lifecycle-controller` and namespace `agent-evolution-controlled-lifecycle-v1`; review uses the exact acquired reviewer identity and namespace `agent-evolution-controlled-review-v1`. The lifecycle canonical JSON payload binds authority id, project execution key, lease, attempt, fencing token, snapshot fingerprint, expected/next state, Candidate/Parent/Tree, review binding/evidence digests, and assertion time. The review canonical JSON payload binds project/lease/attempt/token/snapshot, Candidate/Parent/Tree, reviewer id/role, verdict, finding counts, review time, and the acquired reviewer/minimum-verdict policy. Verification executes only absolute `/usr/bin/ssh-keygen -Y verify`; immediately before execution it opens that exact no-follow regular file, requires root:wheel numeric uid/gid `0:0`, rejects group/world write, and requires SHA-256 `bddae9c4ea46fd903574ec6ff61eda75e133f940fa538f2adca80af474767596`. PATH and caller environment never select the verifier. Authority files contain one canonical OpenSSH `ssh-ed25519` public key; private keys are never repository material. Caller SHA-256 digests remain structural bindings, never substitutes for SSHSIG verification.

The Round 2 commit staged only that exact seven-file WriteSet:

```bash
git add -- src/evolution_harness/controlled_coordinator.py \
  core/schemas/controlled-coordinator-transition-command.schema.json \
  tests/test_controlled_coordinator_lifecycle.py \
  tests/test_controlled_coordinator_inputs.py \
  examples/external-project-source/lifecycle-authority-public.pem \
  examples/external-project-source/deep-reviewer-public.pem \
  docs/superpowers/plans/2026-08-14-controlled-parallel-project-execution-phase-1b.md
git commit -m "fix: pin lifecycle sshsig verifier"
```

Task 6 Authority + WriteSet migration (fixed base/parent `7e8623b3d3f35514d633a21dd3f3db504da9e32c`): recovery clears a project-wide safety stop, releases retained capacity, and makes old plan/batch/attempt identities permanently ineligible, so caller-provided digests, decision arrays, status text, and quiescence text are evidence only and never authorization. The exact authorized twelve-path WriteSet is `src/evolution_harness/controlled_recovery.py`, `tests/test_controlled_recovery.py`, `src/evolution_harness/controlled_coordinator.py`, `src/evolution_harness/controlled_write_guard.py`, `src/evolution_harness/coordinator_state.py`, `tests/test_coordinator_state.py`, `core/schemas/controlled-recovery-command.schema.json`, `src/evolution_harness/controlled_coordinator_inputs.py`, `tests/test_controlled_coordinator_inputs.py`, `integrations/neutral-shadow/authority-map.yaml`, `examples/external-project-source/recovery-authority-public.pem`, and this formal plan. The distinct current project authority is exactly `recovery-controller`, backed by one canonical OpenSSH Ed25519 public key and no repository private key. The signed canonical JSON payload covers every semantic recovery field except `signature` and `commandDigest`; `commandDigest` then covers the complete signed command except itself. Verification reuses the Task 4 pinned absolute `/usr/bin/ssh-keygen` boundary with SSHSIG identity `recovery-controller` and namespace `agent-evolution-controlled-recovery-v1`; PATH, caller environment, caller digest, or a stale Authority Snapshot cannot select or replace trust.

Task 6 quarantine and recovery migration: Task 5 invokes one internal locked quarantine primitive while still holding the same project lock used for fencing validation, target anchoring, foreground execution, and complete before/after inventory. No breach may cross an unlock-to-observe admission window. The public observation API independently rebuilds and exact-matches the current complete physical breach set; caller `observedPaths`, inventory digest, ephemeral-removal flag, or quiescence text cannot replace that live evidence. First or widened breach unions the complete observed WriteSet, advances the revocation fencing floor for every nonterminal or retained lease without rewriting historical tokens, records immutable all-project decisions and one WRITE_OBSERVATION receipt, and blocks admission, transition, guard, and later integration preparation. Recovery executes under the same project lock only after every guarded command has returned, exact-matches journal version, pending WriteSet, complete revoked lease proof/decision sets, live lane physical identities and fencing proofs, rebuilds current Authority, verifies the recovery SSHSIG, durably appends the RECOVERY receipt, releases affected leases, and clears recovery in one CAS write. Every WRITE_OBSERVATION and RECOVERY receipt remains part of the store's ordered integrity chain; orphan, duplicate, deleted, reordered, or self-consistently rewritten evidence and token rollback fail closed.

Task 6 Review Fix Round 1 Authority migration (fixed base/parent `bff525c8e1c1537011c6ec3d28e70e61b5ec606b`): a new public observation may persist only when the same locked no-follow inventory proves a nonempty breach, its canonical inventory digest exactly equals `beforeInventoryDigest`, its complete declared-and-absent ephemeral set exactly equals `ephemeralPathsRemoved`, its `processIds` set is empty, and `observedPaths` exact-matches the live breach. Exact receipt replay remains idempotent before those new-observation checks. Task 5 synthesizes the same complete evidence from its real before inventory and declared removed ephemeral set while holding the command-lifetime project lock. Every completed recovery cycle permanently retires each revoked `batchPlanId` and `attemptId` independently; a new attempt under an old batch or an old attempt under a new batch fails closed.

Task 6 Review Fix Round 1 persisted-signature migration: the closed recovery command additionally carries `recoveryAuthorityPublicKey`, exactly the complete canonical one-line current `recovery-controller` OpenSSH Ed25519 public-key file including its terminating newline. The field is covered by the SSHSIG payload and `commandDigest`. Initial recovery exact-compares those bytes with the live no-follow authority file and its current digest. On every journal read, the store deterministically recomputes recovery receipt identities, anchors recovery authority id/reference/digest/public-key bytes to the immutable Acquire Authority Snapshot of the corresponding revoked leases, and reuses the pinned Task 4 SSHSIG verifier to verify each persisted recovery command. Recomputed command, receipt, and journal digests cannot replace that keyed verification. The authorized twelve-path Task 6 WriteSet is unchanged.

Task 7 public-inspection migration (fixed base/parent `ae46bdb5ec9286d8a4bd27389ff6d262d45d7d17`): the locked Phase 1B interface already requires `inspect_project_coordinator`, but the fixed parent contains no implementation. The CLI must not create a second status projection, so the authorized Task 7 WriteSet expands to exactly `src/evolution_harness/controlled_coordinator.py`, `tests/test_controlled_coordinator_acquire.py`, `src/evolution_harness/cli.py`, `tests/test_controlled_coordinator_cli.py`, `README.md`, and this formal plan. The public inspection API resolves the registered physical project identity, acquires the existing non-blocking project lock, and reads the durable journal through `CoordinatorStateStore`; an uninitialized project returns a structured, read-only safety status without creating a journal. Corrupt or unsafe state and lock contention fail closed through the existing coordinator error codes. The CLI consumes only that public status API and the four existing mutation APIs.

Task 7 Review Fix Round 1 Authority + WriteSet migration (fixed base/parent `a5a9351970a5f6da19f39b8003107c5b1b78baf2`): the exact authorized eight-path WriteSet is `src/evolution_harness/controlled_coordinator.py`, `tests/test_controlled_coordinator_acquire.py`, `src/evolution_harness/cli.py`, `tests/test_controlled_coordinator_cli.py`, `src/evolution_harness/coordinator_state.py`, `tests/test_coordinator_state.py`, `README.md`, and this formal plan. Inspection uses a descriptor-anchored no-create state-root open plus a no-create existing-project lock: an absent root creates nothing, and an existing root for an uninitialized project creates no project lock, lock identity, initialization marker, or journal; initialized corrupt/unsafe state and lock contention still fail closed. Coordination-only argparse failures emit one stable JSON object on stdout with empty stderr while all legacy command parse behavior remains unchanged. Acquire and transition results bind `receiptId` and `journalVersion` to the exact original durable receipt and reconstruct that receipt's lease/fencing/released/recovery projection on first execution and exact replay; a later lease state may not rewrite historical output. Only `ControlledCoordinationError` supplies a coordinator protocol code; OS/environment failures use a stable redacted `SYSTEM_ERROR` channel and unexpected programmer failures use a stable redacted `INTERNAL_ERROR` channel.

Task 8 Final Gate Remediation Authority + WriteSet migration (fixed base/parent `1e13664fc561dc0289cc0747241b3972595194d7`): the first whole-branch xhigh gate returned `NO-GO / P0=0 / P1=3 / P2=0`. The exact authorized eleven-path remediation WriteSet is `src/evolution_harness/controlled_planner.py`, `src/evolution_harness/controlled_coordinator_inputs.py`, `src/evolution_harness/controlled_coordinator.py`, `src/evolution_harness/controlled_write_guard.py`, `core/schemas/controlled-coordinator-transition-command.schema.json`, `tests/test_controlled_planner.py`, `tests/test_controlled_coordinator_inputs.py`, `tests/test_controlled_coordinator_lifecycle.py`, `tests/test_controlled_coordinator_acquire.py`, `tests/test_controlled_write_guard.py`, and this formal plan. Candidate and registered-source Git evidence must use one absolute sealed Git boundary, reject ambient Git/object/replace configuration, bind an explicitly opened no-follow `.git` or gitdir administration root and its pre/post physical identity, and fail closed on executable, admin, or object-view drift. `action:secret-access` and `action:credential-access` join the authoritative protected-action vocabulary and remain denied even if an envelope or descriptor claims them. Transition review evidence becomes a canonical complete set whose roles exactly satisfy the acquired Phase 1A execution requirements, including the Slice review policy; every member is candidate-bound, zero-finding, policy-verdict-matched, authority-current, and independently signature-verified. The two implementation domains may proceed concurrently only while their tracked ownership is disjoint; shared runtime integration remains serial under the main Agent.

Coordinator-projection migration (2026-08-14): `ACTIVE_LEASE_CONFLICT` is a locked closed-enum projection reason and `PROJECT_CAPACITY_LIMIT` remains the distinct project-wide capacity reason. The optional planner input is a closed `controlled-coordinator-snapshot/v1` object that binds project, project execution key, base provisional plan, journal version/digest/recovery state, envelope, conflict policy, source base, and the complete journal. When absent, the returned bundle and provisional execution-plan bytes are unchanged. When present, `bundle.executionPlan` is still that original provisional plan and the read-only result is added separately as `bundle.coordinatorProjection` with schema `controlled-coordinator-projection/v1`. A projection is not an Acquire `executionPlan`, never mutates coordinator state, and never removes `requiresCoordinatorRecheck=true`.

### Journal invariants

```text
schemaVersion = controlled-coordinator-journal/v1
projectExecutionKey = immutable
journalVersion = monotonically increasing integer
nextFencingToken = monotonically increasing integer
recoveryState = CLEAR | PROJECT_WRITESET_RECOVERY | STATE_RECOVERY_REQUIRED
recoveryEvidence = explicit null for no recorded recovery, or complete immutable evidence
leases = append-only identities with immutable acquisition binding
receipts = append-only ordered mutation receipts
integrationTransactions = [] in Phase 1B
```

Every lease stores the complete target footprint plus the authority-bound planning footprints needed to reconstruct the cross-plan dependency/producer-consumer closure. It also stores the existing lane directory's no-follow `{device, inode, type}` physical identity. Candidate identity is either `null` or exactly `{commit, parent, tree}`. At `FIXED_CANDIDATE`, every later candidate-bound transition, and exact replay, Task 4 reopens the lane from `/` without following symlinks, matches that durable physical identity, requires the Git top-level to equal `laneRoot`, requires live `HEAD == commit`, and proves that commit exists with exactly one `parent` and the exact `tree`. On every read and replacement the store validates the ordered receipt/version/lease association, requires `nextFencingToken` above every durable token, and verifies the latest receipt digest against the complete sentinel-normalized journal. Corruption fails closed as `COORDINATOR_STATE_CORRUPT`; recovery execution remains Task 6.
`recoveryEvidence` is always present. Both pending recovery states require non-null complete evidence; `CLEAR` permits `null` before any recovery and retains non-null immutable evidence after an authorized recovery closes.

---

### Task 1: Coordinator schemas and canonical command validation

**Files:**

- Create: `core/schemas/controlled-coordinator-acquire-command.schema.json`
- Create: `core/schemas/controlled-coordinator-transition-command.schema.json`
- Create: `core/schemas/controlled-write-observation-command.schema.json`
- Create: `core/schemas/controlled-recovery-command.schema.json`
- Create: `core/schemas/controlled-execution-lease.schema.json`
- Create: `core/schemas/controlled-coordinator-journal.schema.json`
- Create: `core/schemas/controlled-coordinator-receipt.schema.json`
- Create: `src/evolution_harness/controlled_coordinator_inputs.py`
- Create: `tests/test_controlled_coordinator_inputs.py`

**Interfaces:**

- Consumes: Phase 1A schema-validated `controlled-execution-plan/v1`, conflict footprint records, `SchemaStore`, `canonical_json_bytes`, `sha256_bytes`, `safe_relative_path`, and strict RFC 3339 parsing.
- Produces: `normalize_acquire_command`, `normalize_transition_command`, `normalize_write_observation_command`, `normalize_recovery_command`, and `ControlledCoordinationError(code, message)`.

- [ ] **Step 1: Add RED tests for schema closure and digest binding**

```python
def test_acquire_rejects_unknown_field_and_digest_mutation(coordinator_factory):
    command = coordinator_factory.acquire()
    command["surprise"] = True
    with pytest.raises(ControlledCoordinationError) as unknown:
        normalize_acquire_command(ROOT, command)
    assert unknown.value.code == "COORDINATOR_COMMAND_INVALID"

    command = coordinator_factory.acquire()
    command["attemptId"] = "attempt:changed"
    with pytest.raises(ControlledCoordinationError) as changed:
        normalize_acquire_command(ROOT, command)
    assert changed.value.code == "COMMAND_DIGEST_MISMATCH"
```

Add parameterized mutations for every acquire, transition, observation, and recovery authority-bearing field. Assert path aliases, empty identifiers, duplicate set entries, invalid state transitions, malformed Candidate/Parent/Tree values, protected action classes, and noncanonical timestamps fail closed.

- [ ] **Step 2: Run the focused RED test**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/test_controlled_coordinator_inputs.py`

Expected: FAIL because the Phase 1B schemas and module do not exist.

- [ ] **Step 3: Implement closed schemas and normalization**

Normalization must deep-copy input, schema-validate before semantic checks, canonicalize only declared set-valued arrays, preserve ordered transitions/receipts, verify each command digest, reject protected action classes even when an envelope lists them, and bind every acquire field to the supplied execution plan and proposed admission.

- [ ] **Step 4: Run the focused GREEN test**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/test_controlled_coordinator_inputs.py`

Expected: PASS with zero skipped tests.

- [ ] **Step 5: Commit Task 1**

```bash
git add core/schemas/controlled-coordinator-*.json \
  core/schemas/controlled-execution-lease.schema.json \
  core/schemas/controlled-write-observation-command.schema.json \
  core/schemas/controlled-recovery-command.schema.json \
  src/evolution_harness/controlled_coordinator_inputs.py \
  tests/test_controlled_coordinator_inputs.py
git commit -m "feat: validate controlled coordinator commands"
```

### Task 2: Durable per-user state root and atomic journal store

**Files:**

- Create: `src/evolution_harness/coordinator_state.py`
- Create: `tests/test_coordinator_state.py`
- Modify: `tests/conftest.py`

**Interfaces:**

- Consumes: normalized journal dictionaries and project execution identities.
- Produces: `CoordinatorStateStore.open(identity)`, `read_journal()`, `replace_journal(expected_version, journal, receipt)`, and `exclusive_project_lock()`.

- [ ] **Step 1: Add RED tests for unsafe roots, atomicity, and loss detection**

```python
def test_state_root_rejects_symlink_and_permissive_mode(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("AGENT_EVOLUTION_COORDINATOR_ROOT", str(alias))
    with pytest.raises(ControlledCoordinationError) as caught:
        CoordinatorStateStore.open(IDENTITY)
    assert caught.value.code == "UNSAFE_COORDINATOR_ROOT"
```

Add real competing-process tests for one project lock, distinct-project independence, stale `expected_version`, fsync/replace failure injection, corrupt JSON, truncated journal, wrong owner/mode, inode swap, missing previously initialized journal, and state-root identity changing between processes.

- [ ] **Step 2: Run the focused RED test**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/test_coordinator_state.py`

Expected: FAIL because `coordinator_state.py` does not exist.

- [ ] **Step 3: Implement the descriptor-anchored store**

Use `os.open(..., O_DIRECTORY | O_NOFOLLOW)`, `dir_fd` operations, owner-only `0700/0600`, a root identity file, project-key-derived filenames, non-blocking `flock`, same-directory temporary writes, `os.fsync` on file and directory, `os.replace` by descriptors, and a post-write reread validated by `SchemaStore`. Never reuse the temporary `_state_root()` in `process_lock.py`.

- [ ] **Step 4: Run the focused GREEN test**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/test_coordinator_state.py`

Expected: PASS, including subprocess race tests.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/evolution_harness/coordinator_state.py tests/test_coordinator_state.py tests/conftest.py
git commit -m "feat: persist project coordinator journals"
```

### Task 3: Project identity and lease acquisition CAS

**Files:**

- Create: `src/evolution_harness/controlled_coordinator.py`
- Create: `tests/test_controlled_coordinator_acquire.py`
- Modify: `src/evolution_harness/controlled_planner.py`
- Modify: `src/evolution_harness/controlled_inputs.py`
- Modify: `src/evolution_harness/controlled_coordinator_inputs.py`
- Modify: `src/evolution_harness/coordinator_state.py`
- Modify: `core/schemas/controlled-coordinator-acquire-command.schema.json`
- Modify: `core/schemas/controlled-execution-lease.schema.json`
- Modify: `core/schemas/controlled-execution-plan.schema.json`
- Create: `core/schemas/controlled-coordinator-snapshot.schema.json`
- Create: `core/schemas/controlled-coordinator-projection.schema.json`
- Modify: `integrations/neutral-shadow/authority-map.yaml`
- Create: `examples/external-project-source/coordinator-issuer.yaml`
- Create: `examples/external-project-source/controlled-planning.yaml`
- Modify: `tests/conftest.py`
- Modify: `tests/test_controlled_inputs.py`
- Modify: `tests/test_controlled_coordinator_inputs.py`
- Modify: `tests/test_coordinator_state.py`
- Modify: `tests/test_controlled_planner.py`
- Modify: `tests/test_neutral_integration_fixture.py`
- Modify: `docs/superpowers/plans/2026-08-14-controlled-parallel-project-execution-phase-1b.md`

**Interfaces:**

- Consumes: `load_project_registration`, Phase 1A planning request/result, current live Authority Snapshot, full conflict footprints, and `CoordinatorStateStore`.
- Produces: `resolve_project_execution_identity`, `acquire_lane_lease`, and a planner capacity projection that accounts for all nonterminal leases across plans and batches.

- [ ] **Step 1: Add RED tests for project-wide admission**

```python
def test_cross_batch_same_owner_is_serialized(coordinator_factory):
    first = acquire_lane_lease(ROOT, SOURCE, coordinator_factory.acquire(batch="batch:a"))
    with pytest.raises(ControlledCoordinationError) as caught:
        acquire_lane_lease(ROOT, SOURCE, coordinator_factory.acquire(batch="batch:b"))
    assert caught.value.code == "ACTIVE_FOOTPRINT_CONFLICT"
    assert first["fencingToken"] == 1
```

Cover cross-target aliases of the same repository, cross-plan and cross-batch capacity, cross-plan transitive conflict paths, disjoint project keys, changed policy/envelope/snapshot/HEAD, caller-forged facts, real development DENY, corrupt journals, lane missing/symlink/physical identity, same-key replay/changed payload/terminal replay, and two-process simultaneous acquisition where exactly one process succeeds.

- [ ] **Step 2: Run the focused RED test**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/test_controlled_coordinator_acquire.py`

Expected: FAIL because acquisition is not implemented.

- [ ] **Step 3: Implement identity and acquire CAS**

Derive the project key from registration fields plus source-root `st_dev`, `st_ino`, and directory type captured no-follow. Under the project lock: reread and integrity-check the journal; reject recovery state; re-run normalization; reload registration; rebuild and exact-compare live Authority; require development ALLOW; validate the existing approved lane directory no-follow from `/` through every ancestor; compare each nonterminal target using one closure built from every active lease planning graph plus the complete current descriptor graph; enforce `min(envelope.maxParallelLanes, 3)` globally; allocate the monotonic fencing token; append the physically bound lease and receipt; atomically persist and integrity-check the reread.

- [ ] **Step 4: Make Phase 1A planning coordinator-aware without making it mutating**

Add the optional immutable `controlled-coordinator-snapshot/v1` parameter to the planner. Reject cross-project/envelope/policy/base/recovery/version/digest bindings. When supplied, preserve the original provisional `executionPlan` and add a separate `controlled-coordinator-projection/v1` that subtracts nonterminal leases from capacity and queues conflicts with `ACTIVE_LEASE_CONFLICT` or `PROJECT_CAPACITY_LIMIT`. When absent, preserve the complete pre-Task-3 bundle bytes and `requiresCoordinatorRecheck: true`.

- [ ] **Step 5: Run focused and Phase 1A compatibility tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/test_controlled_coordinator_acquire.py tests/test_controlled_planner.py tests/test_controlled_inputs.py`

Expected: PASS with unchanged Phase 1A plan identities when no coordinator snapshot is supplied.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/evolution_harness/controlled_coordinator.py \
  src/evolution_harness/controlled_planner.py \
  tests/test_controlled_coordinator_acquire.py \
  core/schemas/controlled-execution-plan.schema.json \
  docs/superpowers/plans/2026-08-14-controlled-parallel-project-execution-phase-1b.md
git commit -m "feat: acquire fenced project lane leases"
```

### Task 4: Lease lifecycle, fencing, replay, and release rules

**Files:**

- Modify: `src/evolution_harness/controlled_coordinator.py`
- Modify: `src/evolution_harness/controlled_coordinator_inputs.py`
- Modify: `core/schemas/controlled-coordinator-transition-command.schema.json`
- Create/modify: `tests/test_controlled_coordinator_lifecycle.py`
- Modify: `tests/test_controlled_coordinator_inputs.py`
- Modify: `integrations/neutral-shadow/authority-map.yaml`
- Create/modify: `examples/external-project-source/lifecycle-authority-public.pem`
- Create/modify: `examples/external-project-source/deep-reviewer-public.pem`
- Modify: `docs/superpowers/plans/2026-08-14-controlled-parallel-project-execution-phase-1b.md`

**Interfaces:**

- Consumes: a current lease, current signed project-owned lifecycle/reviewer evidence, current fencing token, process evidence, durable lane physical identity, and optional Candidate/Parent/Tree identity.
- Produces: `transition_lane_lease` and immutable transition receipts.

- [ ] **Step 1: Add RED transition-matrix tests**

```python
@pytest.mark.parametrize("exceptional", ["BLOCKED", "NO_GO", "STALE"])
def test_exceptional_state_retains_lease(coordinator_factory, exceptional):
    lease = coordinator_factory.acquired_lease()
    result = transition_lane_lease(ROOT, SOURCE, coordinator_factory.transition(lease, exceptional))
    assert result["leaseRetained"] is True
    assert result["state"] == exceptional
```

Test every allowed normal transition, skipped-state rejection, stale/missing token, authority fingerprint drift, attempt mismatch, SSHSIG caller-rehash/wrong-key/wrong-role/policy/namespace/identity failures, fake PATH success executables, pinned-verifier digest/owner/mode drift, Candidate/Parent/Tree binding at `FIXED_CANDIDATE`, candidate object/HEAD/parent/tree and lane inode/symlink drift, zero-finding review binding at `REVIEW_GO`, exact replay live revalidation, retained lease through `INTEGRATING`, `CLOSED` release, signed `CANCELLED` with both empty and live caller process lists retaining capacity, terminal immutability, and subprocess loss retaining the lease.

- [ ] **Step 2: Run the lifecycle RED test**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/test_controlled_coordinator_lifecycle.py`

Expected: FAIL on missing lifecycle behavior.

- [ ] **Step 3: Implement the explicit state machine**

Keep allowed transitions in one immutable mapping. Never infer project lifecycle changes: under the project lock, rebuild authority, resolve the exact required public-key records, no-follow read their current digest-matched OpenSSH keys, integrity-pin absolute `/usr/bin/ssh-keygen`, and verify the closed identity/namespace SSHSIG payloads without PATH selection or caller environment. Revalidate live lane physical and Git Candidate/Parent/Tree identity before every candidate-bound mutation and exact replay. Raise `nextFencingToken` monotonically when authority drift, cancellation, or recovery revokes an attempt while retaining the historical lease token in evidence; ordinary transitions preserve both. Release capacity only for valid `CLOSED`. Task 4 records `CANCELLED` as terminal but `released=false`, so caller process arrays and subprocess loss never establish recovery quiescence or free capacity; only Task 6 may durably release it.

- [ ] **Step 4: Run the lifecycle GREEN test**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/test_controlled_coordinator_lifecycle.py`

Expected: PASS with no implicit transitions.

- [ ] **Step 5: Commit Task 4**

```bash
git add src/evolution_harness/controlled_coordinator.py tests/test_controlled_coordinator_lifecycle.py
git add src/evolution_harness/controlled_coordinator_inputs.py \
  core/schemas/controlled-coordinator-transition-command.schema.json \
  tests/test_controlled_coordinator_inputs.py \
  integrations/neutral-shadow/authority-map.yaml \
  examples/external-project-source/lifecycle-authority-public.pem \
  examples/external-project-source/deep-reviewer-public.pem \
  docs/superpowers/plans/2026-08-14-controlled-parallel-project-execution-phase-1b.md
git commit -m "feat: enforce fenced lane lifecycle transitions"
```

### Task 5: Physical WriteSet inventory and guarded command boundary

**Files:**

- Create: `src/evolution_harness/controlled_write_guard.py`
- Create: `tests/test_controlled_write_guard.py`
- Create: `tests/fixtures/guarded_writer.py`

**Interfaces:**

- Consumes: active lease, fencing token, lane root, exact/ephemeral WriteSets, argv/cwd/environment, and current Git index/worktree state.
- Produces: `run_guarded_command`, descriptor-anchored before/after inventories, and normalized `observedPaths`.

- [ ] **Step 1: Add RED real-process negatives**

```python
def test_guard_blocks_write_outside_exact_set(guarded_lane):
    result = run_guarded_command(
        guarded_lane.lease,
        guarded_lane.root,
        [sys.executable, "tests/fixtures/guarded_writer.py", "outside.txt"],
        cwd=guarded_lane.root,
        environment=guarded_lane.environment,
    )
    assert result.returncode != 0
    assert not (guarded_lane.root / "outside.txt").exists()
```

Add negatives for symlink ancestors, final-target symlinks, path swaps, writes through a newly created symlink, detached children, writes to the registered source root, another lane, integration roots, undeclared external paths, stale fencing tokens, and missing `/usr/bin/sandbox-exec`. Add positives for declared files/directories and Git-ignored, lane-exclusive ephemeral paths removed before closure.

- [ ] **Step 2: Run the guard RED test**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/test_controlled_write_guard.py`

Expected: FAIL because no guard exists.

- [ ] **Step 3: Implement descriptor anchoring and fail-closed sandbox selection**

Open every existing ancestor and final target no-follow from the lane-root descriptor and capture device/inode/type. Permit creation only below an anchored declared directory. On macOS, generate a deny-default `sandbox-exec` profile that permits process execution/read access needed by the command but grants writes only to anchored exact/ephemeral targets and the process-private system locations required by the interpreter. If the complete child process tree cannot be contained, raise `PROCESS_SANDBOX_UNAVAILABLE` before executing it.

- [ ] **Step 4: Implement before/after inventory**

Inventory tracked and untracked lane changes without following symlinks. Compare normalized physical paths to exact/ephemeral WriteSets. Require ephemeral paths to be Git-ignored, lane-exclusive, non-symlinked, absent from the candidate, and removed before `FIXED_CANDIDATE`.

- [ ] **Step 5: Run the guard GREEN test twice**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/test_controlled_write_guard.py && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/test_controlled_write_guard.py`

Expected: both runs PASS; no files remain outside each test's temporary lane root.

- [ ] **Step 6: Commit Task 5**

```bash
git add src/evolution_harness/controlled_write_guard.py \
  tests/test_controlled_write_guard.py tests/fixtures/guarded_writer.py
git commit -m "feat: guard controlled lane write sets"
```

### Task 6: Project-wide breach quarantine and explicit recovery

**Files:**

- Create: `src/evolution_harness/controlled_recovery.py`
- Create: `tests/test_controlled_recovery.py`
- Modify: `src/evolution_harness/controlled_coordinator.py`
- Modify: `src/evolution_harness/controlled_write_guard.py`
- Modify: `src/evolution_harness/coordinator_state.py`
- Modify: `tests/test_coordinator_state.py`
- Modify: `core/schemas/controlled-recovery-command.schema.json`
- Modify: `src/evolution_harness/controlled_coordinator_inputs.py`
- Modify: `tests/test_controlled_coordinator_inputs.py`
- Modify: `integrations/neutral-shadow/authority-map.yaml`
- Create: `examples/external-project-source/recovery-authority-public.pem`
- Modify: `docs/superpowers/plans/2026-08-14-controlled-parallel-project-execution-phase-1b.md`

**Interfaces:**

- Consumes: live descriptor-anchored complete persistent inventories, all nonterminal and retained lease footprints, current recovery-controller Authority plus SSHSIG evidence, project-lock-established quiescence, and a recovery command.
- Produces: project-wide quarantine receipts, `observedWriteSet`, affected-lane decisions, and fresh-plan-only recovery closure.

- [ ] **Step 1: Add RED quarantine/recovery tests**

```python
def test_breach_revokes_every_project_token_and_blocks_admission(coordinator_factory):
    first, second = coordinator_factory.two_disjoint_leases()
    receipt = observe_lane_writes(ROOT, SOURCE, coordinator_factory.breach(first, "undeclared.txt"))
    assert receipt["recoveryState"] == "PROJECT_WRITESET_RECOVERY"
    assert set(receipt["revokedLeaseIds"]) == {first["leaseId"], second["leaseId"]}
    with pytest.raises(ControlledCoordinationError) as caught:
        acquire_lane_lease(ROOT, SOURCE, coordinator_factory.acquire_third())
    assert caught.value.code == "PROJECT_RECOVERY_PENDING"
```

Cover tracked/untracked breaches, authority-path writes, cross-lane overlap recomputation, non-overlapping lanes still requiring a fresh plan, missing process quiescence, widened WriteSet rejection, changed recovery authority, journal loss/corruption, recovery replay, conflicting recovery payload, and a new admission succeeding only after a valid recovery receipt plus fresh plan identity.

- [ ] **Step 2: Run the recovery RED test**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/test_controlled_recovery.py`

Expected: FAIL because quarantine/recovery is missing.

- [ ] **Step 3: Implement atomic project-wide quarantine**

On any breach, use the already-held project lock from Task 5 or acquire it in the public observation API, recompute current journal state, advance the revocation fencing floor for every nonterminal or retained lease, set `PROJECT_WRITESET_RECOVERY`, persist the complete observed path set, and block transitions/admissions/guard/integration preparation. Do not delete lane files or evidence.

- [ ] **Step 4: Implement authorized recovery closure**

Require the current no-follow `recovery-controller` OpenSSH key and valid SSHSIG, project-lock-established real quiescence plus exact proof for every affected lease, expected journal version, exact pending observed WriteSet, exact complete revoked-lease decisions, and `replacementPlanRequired=true`. Mark overlapping/authority-affected leases `STALE`; retain immutable evidence; clear recovery only in the same CAS write that durably appends the receipt and releases affected leases. A Task 4 `CANCELLED` lease remains capacity-bearing until included in this exact recovery proof. Never widen a descriptor or reuse an old plan/batch/attempt identity.

- [ ] **Step 5: Run recovery and race tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/test_controlled_recovery.py tests/test_controlled_coordinator_acquire.py tests/test_coordinator_state.py`

Expected: PASS, including concurrent breach/acquire and crash-replay cases.

- [ ] **Step 6: Commit Task 6**

```bash
git add -- src/evolution_harness/controlled_recovery.py \
  tests/test_controlled_recovery.py \
  src/evolution_harness/controlled_coordinator.py \
  src/evolution_harness/controlled_write_guard.py \
  src/evolution_harness/coordinator_state.py \
  tests/test_coordinator_state.py \
  core/schemas/controlled-recovery-command.schema.json \
  src/evolution_harness/controlled_coordinator_inputs.py \
  tests/test_controlled_coordinator_inputs.py \
  integrations/neutral-shadow/authority-map.yaml \
  examples/external-project-source/recovery-authority-public.pem \
  docs/superpowers/plans/2026-08-14-controlled-parallel-project-execution-phase-1b.md
git commit -m "feat: quarantine controlled project write breaches"
```

### Task 7: Readable CLI for explicit coordinator operations

**Files:**

- Modify: `src/evolution_harness/controlled_coordinator.py`
- Modify: `tests/test_controlled_coordinator_acquire.py`
- Modify: `src/evolution_harness/coordinator_state.py`
- Modify: `tests/test_coordinator_state.py`
- Modify: `src/evolution_harness/cli.py`
- Create: `tests/test_controlled_coordinator_cli.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-14-controlled-parallel-project-execution-phase-1b.md`

**Interfaces:**

- Consumes: the Phase 1B public Python APIs.
- Produces: JSON-only-safe CLI commands `coordination status`, `coordination acquire`, `coordination transition`, `coordination observe`, and `coordination recover`.

- [ ] **Step 1: Add RED CLI tests**

```python
def test_coordination_acquire_writes_only_coordinator_root(cli_factory):
    before = cli_factory.project_snapshot()
    result = cli_factory.run("coordination", "acquire", "--source", str(cli_factory.source), "--request", str(cli_factory.request))
    assert result.returncode == 0
    assert json.loads(result.stdout)["data"]["schemaVersion"] == "controlled-execution-lease/v1"
    assert cli_factory.project_snapshot() == before
```

Test invalid registration, stale authority, lock contention, protected actions, replay, status on an uninitialized project, recovery-pending output, JSON error codes, and absence of `--apply`, agent-launch, worktree-create, Git-ref, merge, push, or lifecycle-authority mutation options.

- [ ] **Step 2: Run the CLI RED test**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/test_controlled_coordinator_cli.py`

Expected: FAIL because the commands are absent.

- [ ] **Step 3: Wire the explicit commands**

Every mutating command requires `--source` and `--request`; status requires `--source`. Emit structured `code`, `message`, receipt identity, journal version, fencing token, retained/released state, and recovery status. Keep project files byte-identical across every CLI test.

- [ ] **Step 4: Document exact limits**

README must state that Phase 1B records safety leases only; it does not launch work, create worktrees, mutate project authority, integrate candidates, or authorize Pay-Nexus. Document the durable state root, explicit recovery requirement, and protected actions.

- [ ] **Step 5: Run the CLI GREEN test**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q tests/test_controlled_coordinator_cli.py tests/test_controlled_planning_cli.py`

Expected: PASS with Phase 1A CLI compatibility preserved.

- [ ] **Step 6: Commit Task 7**

```bash
git add src/evolution_harness/controlled_coordinator.py \
  tests/test_controlled_coordinator_acquire.py \
  src/evolution_harness/cli.py \
  tests/test_controlled_coordinator_cli.py \
  README.md \
  docs/superpowers/plans/2026-08-14-controlled-parallel-project-execution-phase-1b.md
git commit -m "feat: expose controlled coordination safety"
```

Review Fix Round 1 uses the fixed Task 7 candidate as parent and commits only actually changed paths from the exact authorized eight-path WriteSet:

```bash
git add src/evolution_harness/controlled_coordinator.py \
  tests/test_controlled_coordinator_acquire.py \
  src/evolution_harness/coordinator_state.py \
  tests/test_coordinator_state.py \
  src/evolution_harness/cli.py \
  tests/test_controlled_coordinator_cli.py \
  README.md \
  docs/superpowers/plans/2026-08-14-controlled-parallel-project-execution-phase-1b.md
git commit -m "fix: harden controlled coordination cli evidence"
```

### Task 8: Phase 1B acceptance, fixed candidate, and release decision

**Files:**

- Modify only if evidence requires correction: files already listed in Tasks 1-7.
- Create after verification: `docs/reviews/controlled-parallel-project-execution-phase-1b-final-review.md`

**Interfaces:**

- Consumes: the complete Phase 1B branch and the reviewed Phase 1A base.
- Produces: exact Candidate/Parent/Tree/WriteSet evidence and a single `gpt-5.6-sol/xhigh` `GO/NO-GO` decision.

- [ ] **Step 1: Run structural and generated checks**

```bash
.venv/bin/python -m evolution_harness.cli --repository-root . validate --check-generated --format json
.venv/bin/python -m evolution_harness.cli --repository-root . registry build --check --format json
.venv/bin/python -m evolution_harness.cli --repository-root . catalog build --check --format json
./eng doctor --ci --json
git diff --check
```

Expected: every command exits `0` and reports PASS/healthy according to its schema.

- [ ] **Step 2: Run complete focused Phase 1A/1B tests**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/test_controlled_inputs.py \
  tests/test_controlled_conflicts.py \
  tests/test_controlled_planner.py \
  tests/test_controlled_planning_cli.py \
  tests/test_controlled_coordinator_inputs.py \
  tests/test_coordinator_state.py \
  tests/test_controlled_coordinator_acquire.py \
  tests/test_controlled_coordinator_lifecycle.py \
  tests/test_controlled_write_guard.py \
  tests/test_controlled_recovery.py \
  tests/test_controlled_coordinator_cli.py
```

Expected: zero failures and zero skips.

- [ ] **Step 3: Run the full Harness regression once**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q`

Expected: zero failures. Do not rerun unchanged full regression unless candidate tree, environment, or evidence changes.

- [ ] **Step 4: Prove registered projects are unchanged**

Capture before/after SHA-256, size, mode, inode, mtime, and ctime for each exact allowlisted authority file in the neutral fixture and Pay-Nexus sidecar scenario. Assert registered project HEAD/tree/tracked status are unchanged. Do not read, enumerate, or hash Pay-Nexus `.git/**` or `temp-input/**` content.

- [ ] **Step 5: Freeze the stable implementation HEAD as the fixed candidate**

```bash
git status --short
git diff --check
git rev-parse HEAD HEAD^ HEAD^{tree}
git diff --name-only ee1a29bd98e798598051d2ef3e56fd1c7fcb198d..HEAD
```

Expected: Task 1-7 implementation is already committed, the worktree is clean,
and the stable `HEAD` is the fixed candidate with only the approved Phase 1B
WriteSet. If verification required a code or test correction, commit that
correction with its owning task before freezing `HEAD`; never create an empty
or evidence-only implementation commit.

- [ ] **Step 6: Run one independent xhigh final gate**

Review the exact detached Candidate/Parent/Tree with `deep_reviewer` at fixed `xhigh`. Require checks for cross-plan/cross-batch races, state loss, crash replay, symlink/path-swap escape, real process-tree write denial, protected actions, full regression evidence, registered-project no-write proof, and Phase 1C/Pay-Nexus exclusions.

Expected verdict: `GO / P0=0 / P1=0 / P2=0`. Any finding returns to the owning task, forms one cumulative remediation candidate, reruns only affected gates plus the final full regression when the tree stabilizes, and receives a fresh xhigh review.

- [ ] **Step 7: Record the review without changing the reviewed verdict**

Write `docs/reviews/controlled-parallel-project-execution-phase-1b-final-review.md` with Candidate, Parent, Tree, exact WriteSet, commands/exit codes, concurrency negatives, no-write evidence, P0/P1/P2 counts, residual target-platform limits, and explicit statement that Phase 1C and Pay-Nexus remain unexecuted. Commit it separately with:

```bash
git add docs/reviews/controlled-parallel-project-execution-phase-1b-final-review.md
git commit -m "docs: record controlled coordination review"
```

- [ ] **Step 8: Stop at the Phase 1C planning boundary**

Report Phase 1B as complete only after the fixed candidate receives zero-finding GO and the review receipt commit is present. Then create a new Phase 1C plan from the accepted interfaces; do not begin integration-transaction implementation in the Phase 1B candidate.

## Self-Review Record

- Spec coverage: state root, project identity, CAS admission, fencing, lifecycle, capacity, WriteSet sandbox, quarantine, recovery, CLI, registered-project no-write proof, and fixed-candidate review are each owned by exactly one task.
- Scope: Phase 1C, Pay-Nexus projection/adoption, task launching, worktree creation, Git integration, database work, push, and deployment are explicitly excluded.
- Interface consistency: all later tasks consume the public functions and command shapes locked above; `projectExecutionKey`, `leaseId`, `attemptId`, `fencingToken`, journal versions, and Candidate/Parent/Tree identities retain one spelling.
- Placeholder scan: the plan contains no unresolved implementation choices; platform inability to enforce the sandbox is a defined fail-closed result.
