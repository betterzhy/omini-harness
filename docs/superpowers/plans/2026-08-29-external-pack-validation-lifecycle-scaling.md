# External Pack Validation Lifecycle Scaling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse repeated validation of one exact External Capability Pack inside a bounded operation from fourteen complete candidate Gates to one while preserving Registry, lock, projection, Authority, and TOCTOU semantics.

**Architecture:** `CapabilityVerificationSession` is an explicit, process-local context manager that owns exact Pack verification keys, retained fixed checkouts, verified lock contexts, active-use leases, cleanup, and immutable statistics. Public APIs accept an optional keyword-only session; calls without one create and close a bounded private session, while compound Harness operations propagate one session through every nested verification boundary. Pack bytes consumed by projection come only from the retained fixed checkout, and every existing source/registration/lock checkpoint remains a live recheck rather than another candidate Gate.

**Tech Stack:** Python 3.12, stdlib dataclasses/threading/context managers/subprocess/pathlib, PyYAML, jsonschema, pytest 8, Git CLI, existing Harness process-lock and anchored-filesystem utilities.

**Spec:** `docs/superpowers/specs/2026-08-29-external-pack-validation-lifecycle-scaling-design.md`

## Global Constraints

- Runtime work is R2: use RED → GREEN, focused regressions after every task, one stable complete regression, and one fixed-candidate `deep_reviewer / xhigh` gate.
- Reuse is explicit session-scoped only. Do not add a process-global, TTL, disk, database, remote, or cross-process cache.
- Keep `capability-lock/v2`, canonical lock and registration fingerprints, locator exclusion, Registry/projection bytes, CLI schema/output/exit behavior, and all business execution `DENY` decisions unchanged.
- Keep full pre/post source, validator, toolchain, registration, lock, projection pre-swap, and post-swap TOCTOU checks fail closed.
- Public calls without `verification_session` perform complete validation in a private session and preserve current return shapes and exception categories.
- Do not modify Capability Pack/lock/projection/Authority schemas, generated artifacts, external Pack repositories, Pay-Nexus files, `controlled_coordinator.py`, coordinator stores, or Phase 2 pytest receipt code.
- Register `fast`, `integration`, and `pack_e2e` markers with strict-marker checking, but add no default marker exclusion. All real `pack_e2e` nodes stay serial in one process.
- Use the current project interpreter for every command:

  ```bash
  HARNESS_PYTHON=/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest --version
  ```

## Exact WriteSet

Create:

- `tests/test_external_pack_verification_session.py`

Modify production code:

- `src/evolution_harness/capability_pack_registry.py`
- `src/evolution_harness/project.py`
- `src/evolution_harness/registry.py`
- `src/evolution_harness/resolver.py`
- `src/evolution_harness/integration.py`
- `src/evolution_harness/scenario.py`
- `src/evolution_harness/projection.py`
- `src/evolution_harness/install.py`
- `src/evolution_harness/assurance.py`
- `src/evolution_harness/registration.py`
- `src/evolution_harness/cli.py`

Modify deterministic tests/configuration:

- `pyproject.toml`
- `tests/test_capability_pack_registry.py`
- `tests/test_lock_enforcement.py`
- `tests/test_resolver.py`
- `tests/test_projection.py`
- `tests/test_projection_install.py`
- `tests/test_integration_e2e.py`
- `tests/test_assurance_cli.py`
- `tests/test_project_registration.py`
- `tests/test_pay_nexus_java_capability_adoption_pilot.py`

Regression-only files, which must remain byte-identical:

- `tests/test_project_state.py`
- `tests/test_registry_catalog_compat.py`
- `tests/test_cognitura_integration_fixture.py`
- `tests/test_e2e.py`

Any required write outside this set stops implementation and returns to design review.

---

### Task 1: Freeze the baseline and split toolchain measurement from environment construction

**Files:**

- Modify: `src/evolution_harness/capability_pack_registry.py:118-247,688-747`
- Modify: `tests/test_capability_pack_registry.py:480-656`

**Interfaces:**

- Consumes: existing registration `validator.environmentContract` and registered toolchain identities.
- Produces: immutable `VerifiedToolchain`; `_verify_validator_toolchain()` for the pre-Gate snapshot; `_recheck_validator_toolchain()` for the post-Gate comparison; `_validator_environment(registration, verified_toolchain)` with no recursive digest work.

- [ ] **Step 1: Record the unoptimized Pay baseline before runtime changes**

Run the exact current node three times from clean processes and retain logs outside the worktree:

```bash
HARNESS_PYTHON=/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python
for run_id in 1 2 3; do
  /usr/bin/time -lp env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src \
    "$HARNESS_PYTHON" -m pytest -q \
    tests/test_pay_nexus_java_capability_adoption_pilot.py::test_pay_nexus_scenarios_and_install_plan_remain_read_only \
    >"/private/tmp/harness-pack-baseline-${run_id}.stdout" \
    2>"/private/tmp/harness-pack-baseline-${run_id}.stderr"
done
```

Expected: every completed run exits `0`; if a run is interrupted, preserve its files and record it as interrupted rather than substituting it for a baseline PASS.

- [ ] **Step 2: Write RED tests proving environment construction performs no second digest**

Add a counter around `_directory_identity_digest` in `test_candidate_gate_uses_registered_host_home_offline_cache_contract` and require exactly six calls for one Gate:

```python
real_digest = capability_pack_registry._directory_identity_digest
digest_paths: list[Path] = []

def counted_digest(path: Path) -> str:
    digest_paths.append(path)
    return real_digest(path)

monkeypatch.setattr(
    capability_pack_registry,
    "_directory_identity_digest",
    counted_digest,
)

registry = build_capability_pack_registry(root, write=False)

assert registry["entries"][0]["validator"]["environmentContract"] == (
    "REGISTERED_TOOLCHAIN_OFFLINE_CACHE"
)
assert digest_paths == [
    trusted_java_home,
    trusted_maven_home,
    trusted_home / ".m2/repository",
] * 2
```

- [ ] **Step 3: Run the RED test**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest -q \
  tests/test_capability_pack_registry.py::test_candidate_gate_uses_registered_host_home_offline_cache_contract
```

Expected: FAIL because the current environment builder calls `_validator_toolchain_paths()` and produces nine directory digests.

- [ ] **Step 4: Implement the immutable toolchain snapshot and pre/post comparison**

Add these exact interfaces and make mapping fields read-only with `MappingProxyType`:

```python
@dataclass(frozen=True, slots=True)
class VerifiedToolchain:
    command_paths: tuple[Path, ...]
    command_digests: tuple[tuple[str, str], ...]
    directory_identities: tuple[tuple[str, Path, str], ...]
    environment: Mapping[str, str]


def _verify_validator_toolchain(
    registration: Mapping[str, Any],
) -> VerifiedToolchain:
    # Verify every registered command once, digest javaHome/mavenHome/
    # mavenRepository once, enforce the existing path relationships, and
    # construct the exact sanitized environment from those verified paths.
    return VerifiedToolchain(
        command_paths=tuple(paths),
        command_digests=tuple(command_digests),
        directory_identities=tuple(directory_identities),
        environment=MappingProxyType(environment),
    )


def _validator_environment(
    registration: Mapping[str, Any],
    verified_toolchain: VerifiedToolchain,
) -> dict[str, str]:
    del registration
    return dict(verified_toolchain.environment)


def _recheck_validator_toolchain(
    registration: Mapping[str, Any],
    expected: VerifiedToolchain,
) -> None:
    actual = _verify_validator_toolchain(registration)
    if actual != expected:
        raise ValueError("capability pack validator toolchain identity changed during candidate Gate")
```

For `SANITIZED`, return a snapshot with zero command/directory entries and `_GIT_ENVIRONMENT`. In `_validate_registration()`, compute `toolchain` once before the Gate, pass it to `_validator_environment()`, and call `_recheck_validator_toolchain()` once after the Gate.

- [ ] **Step 5: Run focused toolchain and Gate regressions**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest -q \
  tests/test_capability_pack_registry.py -k 'toolchain or candidate_gate or timeout'
```

Expected: PASS, including six directory digests and all existing mutation/timeout failures.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/evolution_harness/capability_pack_registry.py tests/test_capability_pack_registry.py
git commit -m "perf(pack): 固定 Validator 工具链双快照"
```

### Task 2: Add the operation-scoped Pack verification session and retained checkout

**Files:**

- Create: `tests/test_external_pack_verification_session.py`
- Modify: `src/evolution_harness/capability_pack_registry.py:1-913`
- Modify: `tests/test_capability_pack_registry.py`

**Interfaces:**

- Consumes: `VerifiedToolchain` from Task 1 and current fixed Git/materialization helpers.
- Produces: `PackVerificationKey`, `VerificationStats`, `VerifiedCapabilityPack`, `CapabilityVerificationSession`, `_get_verified_capability_pack()`, and session-aware public Registry APIs.

- [ ] **Step 1: Write RED lifecycle/count tests with a cheap synthetic Pack fixture**

The new test module must create two independent synthetic capability IDs and use barriers/events rather than sleeps. Its first tests use these public interfaces:

```python
from evolution_harness.capability_pack_registry import (
    CapabilityVerificationSession,
    get_registered_capability_pack,
)


def test_same_exact_pack_runs_one_gate_and_retains_one_checkout(pack_harness: PackHarness):
    with CapabilityVerificationSession(
        pack_harness.root,
        allowed_capability_ids={pack_harness.capability_id},
    ) as session:
        first = get_registered_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=session,
        )
        second = get_registered_capability_pack(
            pack_harness.root,
            pack_harness.capability_id,
            verification_session=session,
        )
        snapshot = session.stats

    assert first == second
    assert snapshot.full_candidate_gate_count == 1
    assert snapshot.isolated_checkout_count == 1
    assert snapshot.pack_reuse_hit_count == 1
    assert session.stats.active_use_lease_count == 0


def test_public_lookup_without_session_still_runs_one_full_gate(pack_harness: PackHarness):
    result = get_registered_capability_pack(
        pack_harness.root,
        pack_harness.capability_id,
    )
    assert result["capabilityId"] == pack_harness.capability_id
```

Also add RED tests for: unlisted capability, different repository root, foreign verified object, use after close, failed Gate not reused, same-key single-flight success/failure, different-key concurrency, close-vs-read/recheck, and two cleanup failures still invoking both cleanup owners.

- [ ] **Step 2: Run the new module to verify RED**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest -q \
  tests/test_external_pack_verification_session.py
```

Expected: collection FAIL because the session types do not exist.

- [ ] **Step 3: Move canonical registration identity helpers to the Pack owner without changing bytes**

Move `_canonical_registration_identity_record()`, `_registration_fingerprint()`, and `_locator_bound_blob_access_fingerprint()` from `project.py` into `capability_pack_registry.py`; Task 3 will update `project.py` imports. Add a byte-preservation assertion against the existing `REGISTRATION_FINGERPRINT` fixtures before deleting the old definitions.

- [ ] **Step 4: Implement immutable keys, stats, leases, and session state**

Use these exact public shapes; internal dictionaries remain private and are never serialized:

```python
CAPABILITY_PACK_VALIDATION_ABI = "v1"


@dataclass(frozen=True, slots=True)
class PackVerificationKey:
    capability_id: str
    registration_id: str
    digest: str


@dataclass(frozen=True, slots=True)
class VerificationStats:
    full_candidate_gate_count: int
    isolated_checkout_count: int
    toolchain_directory_digest_count: int
    verified_pack_count: int
    verified_lock_count: int
    pack_reuse_hit_count: int
    lock_reuse_hit_count: int
    source_recheck_count: int
    registration_recheck_count: int
    lock_witness_recheck_count: int
    active_use_lease_count: int
    by_pack: Mapping[str, Mapping[str, int]]
    by_lock: Mapping[str, Mapping[str, int]]


class CapabilityVerificationSession:
    """Operation-scoped owner of verified Pack and lock contexts."""
```

Implement these exact members on the class:

- `__init__(self, repository_root: Path, *, allowed_capability_ids: Iterable[str]) -> None`
- `__enter__(self) -> CapabilityVerificationSession`, which requires `OPEN` and returns `self`
- `__exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None) -> bool`, which calls `close()` and returns `False`
- `close(self) -> None`, which transitions `OPEN/FAILED -> CLOSING -> CLOSED`, waits for active leases, and runs every registered cleanup in reverse order
- read-only `stats: VerificationStats`, which returns a newly frozen snapshot under the session mutex

The concrete state machine is: normalized root/token/allowed set, `OPEN/FAILED/CLOSING/CLOSED`, one condition per Pack key, one owner per key, active-use lease increments/decrements in `finally`, atomic failure publication, immutable stats snapshots, and serial reverse-order cleanup outside the mutex. Never hold the session mutex while hashing, running Git, or executing the candidate Gate.

- [ ] **Step 5: Retain the fixed checkout and expose only verified blob methods**

Split `_validate_registration()` into a session-managed validator returning:

```python
@dataclass(frozen=True, slots=True)
class VerifiedCapabilityPack:
    key: PackVerificationKey
    registration: Mapping[str, Any]
    manifest: Mapping[str, Any]
    selected_entries: tuple[tuple[str, str, str, str], ...]
    verified_toolchain: VerifiedToolchain
    _checkout_root: Path
    _locator_bound_fingerprint: str
    _session: CapabilityVerificationSession
    _session_token: object
```

Implement these exact methods:

- `registration_copy(self) -> dict[str, Any]`: return a deep mutable compatibility copy of the frozen registration.
- `lock_entry_copy(self) -> dict[str, Any]`: return the existing external verified-entry shape, including `sourceKind`, locator-bound compatibility fingerprint, and manifest.
- `read_blob(self, relative_path: str) -> bytes`: delegate to `self._session._read_verified_blob(self, relative_path)`.
- `read_blobs(self) -> dict[str, bytes]`: delegate to `self._session._read_verified_blobs(self)`.
- `recheck(self) -> None`: delegate to `self._session._recheck_verified_pack(self)`.

The three session helpers acquire an active-use lease, reload and compare the current selected registration plus locator/source witnesses, read captured object IDs from `_checkout_root` where applicable, recheck again, and release in `finally`. `registration_copy()` preserves the current `get_registered_capability_pack()` shape.

- [ ] **Step 6: Make Registry public APIs own or reuse a session**

Add the optional keyword-only parameter exactly:

```python
def get_registered_capability_pack(
    repository_root: Path,
    capability_id: str,
    *,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, Any]:


def build_capability_pack_registry(
    repository_root: Path,
    *,
    write: bool = False,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, Any]:
```

Both call private `_get_verified_capability_pack()`; an absent session creates a bounded private session and returns a defensive compatibility copy only after cleanup. A supplied session must match the resolved Harness root and allowed capability ID.

Preserve the existing Registry case where one capability ID has multiple non-active registration identities: `build_capability_pack_registry()` validates each distinct identity in its own bounded private child session, retains the existing aggregation/order semantics, and never treats two identities as one session reuse key. Add a regression with two inactive registrations for one capability ID and assert the Registry bytes and validation count remain unchanged. Active-registration uniqueness rules remain unchanged.

Add a parameterized invalidation test that verifies once and then mutates exactly one of: source commit, source tree, content digest, canonical registration identity, locator-bound access identity, validator ABI/version, validator executable digest, or expected toolchain identity. Every same-session mutation must fail closed and poison the session; a new session must perform a fresh Gate. Also mutate the toolchain after a successful session and prove that the next session detects it rather than inheriting trust.

- [ ] **Step 7: Run lifecycle, Registry, source-mutation, and timeout tests**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest -q \
  tests/test_external_pack_verification_session.py \
  tests/test_capability_pack_registry.py
```

Expected: PASS; same-key concurrency records one Gate, failures publish no reusable object, cleanup always runs, and legacy public lookups remain fail closed.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/evolution_harness/capability_pack_registry.py \
  tests/test_external_pack_verification_session.py \
  tests/test_capability_pack_registry.py
git commit -m "perf(pack): 引入操作级验证 session"
```

### Task 3: Preserve the complete lock contract with `VerifiedLockContext`

**Files:**

- Modify: `src/evolution_harness/project.py:1-407`
- Modify: `tests/test_lock_enforcement.py`
- Verify only: `tests/test_project_state.py`, `tests/test_registry_catalog_compat.py`

**Interfaces:**

- Consumes: `CapabilityVerificationSession`, `PackVerificationKey`, `VerifiedCapabilityPack`, and canonical registration helpers from Task 2.
- Produces: `LockVerificationKey`, `VerifiedLockContext`, `verify_capability_lock_context()`, and session-aware `build_capability_lock()`/`verify_capability_lock()`.

- [ ] **Step 1: Write RED tests for exact lock-context reuse and every witness family**

Add a test that verifies the same external lock twice in one session and checks one Gate plus one lock reuse. Parameterize mutation after the first verification over `lock`, `state`, `binding`, `profile`, `design-registry-input`, `active-catalog-input`, and `internal-external-collision`; every case must fail the second call and mark the session unusable:

```python
with CapabilityVerificationSession(
    root,
    allowed_capability_ids={EXTERNAL_CAPABILITY_ID},
) as session:
    first_lock, first_entries = verify_capability_lock(
        root,
        project,
        verification_session=session,
    )
    mutate_witness(root, project, witness)
    with pytest.raises(ValueError):
        verify_capability_lock(
            root,
            project,
            verification_session=session,
        )

assert first_lock["lockFingerprint"]
assert EXTERNAL_CAPABILITY_ID in first_entries
```

- [ ] **Step 2: Run RED lock tests**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest -q \
  tests/test_lock_enforcement.py -k 'external_pack or verification_session'
```

Expected: FAIL because lock APIs do not accept a session and no lock context exists.

- [ ] **Step 3: Implement lock key/context and compute all witnesses on every reuse**

Add exact internal types:

```python
@dataclass(frozen=True, slots=True)
class LockVerificationKey:
    project_root: Path
    digest: str


@dataclass(frozen=True, slots=True)
class VerifiedLockContext:
    key: LockVerificationKey
    lock: Mapping[str, Any]
    entries: Mapping[str, Mapping[str, Any]]
    verified_packs: Mapping[str, VerifiedCapabilityPack]
    _session_token: object
```

Implement `public_result(self) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]` as deep mutable copies of the frozen lock and entry mappings. Implement `verify_capability_lock_context(repository_root, project_root, *, verification_session)` by executing all current schema/fingerprint/state/binding/profile/reasons/Registry/catalog/collision checks every time. Replace the external `get_registered_capability_pack()` call with `_get_verified_capability_pack()`, use its immutable registration/manifest, build a canonical digest over every witness plus ordered Pack-key digests, and only then consult/publish the session lock cache. A changed key for the same project marks the session failed.

- [ ] **Step 4: Preserve public signatures with one optional keyword**

```python
def build_capability_lock(
    repository_root: Path,
    project_root: Path,
    *,
    write: bool = False,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, Any]:


def verify_capability_lock(
    repository_root: Path,
    project_root: Path,
    *,
    verification_session: CapabilityVerificationSession | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
```

Absent sessions are bounded from the lock/binding's declared external IDs and close before returning. Move imports for `_registration_fingerprint()` and `_locator_bound_blob_access_fingerprint()` to `capability_pack_registry.py`; assert canonical lock bytes remain identical.

- [ ] **Step 5: Run focused and semantic lock regressions**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest -q \
  tests/test_lock_enforcement.py \
  tests/test_project_state.py \
  tests/test_registry_catalog_compat.py
```

Expected: PASS with byte-identical v1/v2 locks, locator relocation preserving canonical identity, collision rules unchanged, and no repeated Gate in one session.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/evolution_harness/project.py tests/test_lock_enforcement.py
git commit -m "perf(lock): 复用已验证 External Pack 上下文"
```

### Task 4: Propagate one session through Registry, resolver, integration, and scenarios

**Files:**

- Modify: `src/evolution_harness/registry.py:173-179`
- Modify: `src/evolution_harness/resolver.py:78-295`
- Modify: `src/evolution_harness/integration.py:45-174`
- Modify: `src/evolution_harness/scenario.py:13-91`
- Modify: `tests/test_resolver.py`
- Modify: `tests/test_integration_e2e.py`

**Interfaces:**

- Consumes: session-aware Pack/lock APIs from Tasks 2-3.
- Produces: optional keyword-only `verification_session` on every listed compound entrypoint, passed unchanged to all nested calls.

- [ ] **Step 1: Add RED propagation tests**

Use one external-Pack fixture and monkeypatch `_run_candidate_gate` with a counting wrapper. Resolve twice and run two integration scenarios inside one session; require one Gate and byte-equal results to no-session calls:

```python
with CapabilityVerificationSession(
    root,
    allowed_capability_ids={EXTERNAL_CAPABILITY_ID},
) as session:
    first = resolve_design_context(
        root,
        project,
        intent="visual-reference-review",
        topic="web-fidelity",
        requested_output="review findings",
        runtime="CODEX",
        verification_session=session,
    )
    second = resolve_design_context(
        root,
        project,
        intent="visual-reference-review",
        topic="web-fidelity",
        requested_output="review findings",
        runtime="CODEX",
        verification_session=session,
    )

assert first == second
assert session.stats.full_candidate_gate_count == 1
```

- [ ] **Step 2: Run RED resolver/integration tests**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest -q \
  tests/test_resolver.py -k external \
  tests/test_integration_e2e.py -k 'resolution or scenario'
```

Expected: FAIL on unexpected `verification_session`.

- [ ] **Step 3: Add the exact optional keyword to the propagation surface**

Update these functions without changing their other parameters or return values; the exact post-change signatures are:

```python
def build_all_registries(
    repository_root: Path,
    *,
    write: bool = False,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, dict[str, Any]]:

def resolve_design_context(
    repository_root: Path,
    project_root: Path,
    *,
    intent: str,
    topic: str,
    requested_output: str,
    runtime: str,
    explicit_stage: str | None = None,
    reopen_signal: str | None = None,
    authority_snapshot: dict[str, Any] | None = None,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, Any]:

def resolve_integration_context(
    repository_root: Path,
    integration_root: Path,
    source_root: Path,
    *,
    intent: str,
    topic: str,
    requested_output: str,
    runtime: str,
    explicit_stage: str | None = None,
    reopen_signal: str | None = None,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, Any]:

def build_integration_projection(
    repository_root: Path,
    integration_root: Path,
    source_root: Path,
    *,
    intent: str,
    topic: str,
    requested_output: str,
    runtime: str,
    explicit_stage: str | None = None,
    reopen_signal: str | None = None,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, Any]:

def check_integration_projection(
    repository_root: Path,
    integration_root: Path,
    source_root: Path,
    *,
    runtime: str,
    intent: str | None = None,
    topic: str | None = None,
    requested_output: str | None = None,
    explicit_stage: str | None = None,
    reopen_signal: str | None = None,
    verification_session: CapabilityVerificationSession | None = None,
) -> ProjectionFreshness:

def run_integration_scenario(
    repository_root: Path,
    integration_root: Path,
    source_root: Path,
    scenario_path: Path,
    *,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, Any]:
```

Each nested call passes the same object. `build_all_registries()` passes it only to `build_capability_pack_registry()`; internal registries remain unchanged.

- [ ] **Step 4: Run propagation and existing authority regressions**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest -q \
  tests/test_resolver.py tests/test_integration_e2e.py
```

Expected: PASS; closed topics still do not select Java/exploration capabilities and all Authority gates remain unchanged.

- [ ] **Step 5: Commit Task 4**

```bash
git add src/evolution_harness/registry.py src/evolution_harness/resolver.py \
  src/evolution_harness/integration.py src/evolution_harness/scenario.py \
  tests/test_resolver.py tests/test_integration_e2e.py
git commit -m "perf(resolve): 贯通 External Pack 验证 session"
```

### Task 5: Reuse verified Pack bytes across projection, freshness, and install without weakening TOCTOU

**Files:**

- Modify: `src/evolution_harness/projection.py:222-952`
- Modify: `src/evolution_harness/install.py:45-295`
- Modify: `tests/test_projection.py`
- Modify: `tests/test_projection_install.py`

**Interfaces:**

- Consumes: `VerifiedLockContext` and `VerifiedCapabilityPack.read_blob(s)` from Tasks 2-3.
- Produces: session-aware build/validate/freshness/install paths; projection internals consume verified objects instead of turning them back into plain registration dictionaries.

- [ ] **Step 1: Add RED Gate-count tests around projection and install**

For one external Pack and one explicit session, require these ceilings independently:

```python
with CapabilityVerificationSession(
    root,
    allowed_capability_ids={EXTERNAL_CAPABILITY_ID},
) as session:
    resolved = resolve_design_context(
        root,
        project,
        intent="visual-reference-review",
        topic="web-fidelity",
        requested_output="review findings",
        runtime="CODEX",
        verification_session=session,
    )
    manifest = build_projection_pack(
        root,
        project,
        resolved,
        runtime="CODEX",
        verification_session=session,
    )
    freshness = check_projection_freshness(
        root,
        project,
        runtime="CODEX",
        verification_session=session,
    )

assert manifest["capabilityLockFingerprint"] == resolved["capabilityLockFingerprint"]
assert freshness.fresh
assert session.stats.full_candidate_gate_count == 1
assert session.stats.isolated_checkout_count == 1
```

Add the same one-Gate assertion around `install_projection(root, pack_root, target_root, source_root=source_root, apply=False, verification_session=session)` while preserving its exact DRY_RUN plan.

- [ ] **Step 2: Run RED projection/install tests**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest -q \
  tests/test_projection.py -k 'external or freshness' \
  tests/test_projection_install.py -k 'external or dry_run'
```

Expected: FAIL because projection/install APIs do not accept the session.

- [ ] **Step 3: Thread the session through every projection checkpoint**

Add `verification_session: CapabilityVerificationSession | None = None` to:

```python
_verify_resolved_context
_verify_external_source_snapshot
_build_projection_pack_unlocked
build_projection_pack
validate_projection_pack
check_projection_freshness
```

Replace public `verify_capability_lock()` in projection internals with `verify_capability_lock_context()`. Change `_external_skill_payload()` to accept `VerifiedCapabilityPack` and call its retained-checkout `read_blob()`/`read_blobs()`. At post-read, pre-swap, post-swap, validation-end, and freshness checkpoints, call the same session/context recheck; do not invoke a new validator or toolchain digest.

- [ ] **Step 4: Thread the same session through install planning**

Add the optional keyword to `_projection_inputs()`, `_install_projection_unlocked()`, and `install_projection()`. Pass it to `validate_projection_pack()` and `check_integration_projection()`; leave uninstall signatures unchanged because uninstall does not validate an External Pack.

- [ ] **Step 5: Run all existing mutation/rollback and writer-lock tests**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest -q \
  tests/test_projection.py \
  tests/test_projection_install.py \
  tests/test_lock_enforcement.py::test_projection_and_freshness_bind_lock_fingerprint
```

Expected: PASS, especially external drift after blob read, pre-swap rollback, post-swap removal, generated-byte equality, dry-run-only install, and process-lock tests.

- [ ] **Step 6: Commit Task 5**

```bash
git add src/evolution_harness/projection.py src/evolution_harness/install.py \
  tests/test_projection.py tests/test_projection_install.py
git commit -m "perf(projection): 复用投影验证上下文"
```

### Task 6: Bind project-registration precheck and compound CLI operations to one session

**Files:**

- Modify: `src/evolution_harness/registration.py:1-143`
- Modify: `src/evolution_harness/cli.py:1-450`
- Modify: `tests/test_project_registration.py`
- Modify: `tests/test_integration_e2e.py`

**Interfaces:**

- Consumes: project/integration session APIs from Tasks 3-5.
- Produces: immutable `ProjectRegistrationBootstrap`, registered-operation context manager, session-aware registration APIs, and CLI ownership without CLI schema/output changes.

- [ ] **Step 1: Add RED registered-CLI Gate-count and compatibility tests**

Extend `test_registered_cli_discovery_matches_explicit_inspect_resolve_and_projection` to run registered `inspect`, `resolve`, `projection`, and `projection --check` with a counted Gate and compare stdout JSON/exit codes with pre-change expectations. For each separate CLI process expect one Gate, never precheck plus downstream Gate.

Add a mutation between structural pre-read and full verification and assert the command fails rather than accepting the pre-read as trust.

- [ ] **Step 2: Run RED registration tests**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest -q \
  tests/test_project_registration.py -k 'registered_cli or registration'
```

Expected: FAIL because precheck and downstream calls own separate validation lifecycles.

- [ ] **Step 3: Split structural bootstrap from trusted registration loading**

Add:

```python
@dataclass(frozen=True, slots=True)
class ProjectRegistrationBootstrap:
    repository_root: Path
    source_root: Path
    registration_path: Path | None
    integration_root: Path
    control_plane_root: Path
    allowed_capability_ids: frozenset[str]


def _bootstrap_registered_integration(
    repository_root: Path,
    source_root: Path,
    explicit_integration: Path | None,
) -> ProjectRegistrationBootstrap:
```

The bootstrap performs only anchored registration read/schema/path/integration identity checks plus lock schema/fingerprint loading and external-ID extraction. It does not call `verify_capability_lock()` and does not return a trusted Pack/lock object. `load_project_registration()` reruns all live checks and full lock verification with the supplied session.

- [ ] **Step 4: Add the registered-operation owner and preserve public APIs**

```python
@contextmanager
def registered_integration_operation(
    repository_root: Path,
    source_root: Path,
    explicit_integration: Path | None = None,
) -> Iterator[tuple[dict[str, Any], CapabilityVerificationSession | None]]:


def load_project_registration(
    repository_root: Path,
    source_root: Path,
    *,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, Any]:


def check_project_registration(
    repository_root: Path,
    source_root: Path,
    *,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, str]:


def resolve_registered_integration(
    repository_root: Path,
    source_root: Path,
    explicit_integration: Path | None = None,
    *,
    verification_session: CapabilityVerificationSession | None = None,
) -> dict[str, Any]:
```

For a registered source, the context manager creates a bounded session from the untrusted ID set, reruns `resolve_registered_integration()` with that session, compares bootstrap/live roots, and yields both until downstream work completes. For the legacy explicit-integration path without registration, preserve existing behavior and yield `None` when no shared session is needed.

- [ ] **Step 5: Make CLI branches own one context without changing output**

Wrap ordinary `projection build`/`--check` in a session bounded from the project lock. Replace repeated `_registered_integration_root()` calls in registered `inspect`, `resolve`, `projection`, and `projection --check` with one `registered_integration_operation()` block; pass the yielded session downstream. Leave coordination branches and `controlled_coordinator.py` untouched.

- [ ] **Step 6: Run registration, Integration CLI, and projection CLI regressions**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest -q \
  tests/test_project_registration.py \
  tests/test_integration_e2e.py \
  tests/test_assurance_cli.py::test_harness_cli_validate_and_resolve_json
```

Expected: PASS with unchanged JSON payloads/exit codes and one Gate for every single-Pack compound CLI command.

- [ ] **Step 7: Commit Task 6**

```bash
git add src/evolution_harness/registration.py src/evolution_harness/cli.py \
  tests/test_project_registration.py tests/test_integration_e2e.py
git commit -m "perf(registration): 绑定注册项目 CLI session"
```

### Task 7: Share bounded sessions in structural assurance and registry commands

**Files:**

- Modify: `src/evolution_harness/assurance.py:90-201`
- Modify: `tests/test_assurance_cli.py`

**Interfaces:**

- Consumes: session-aware Registry, lock, and freshness entrypoints.
- Produces: one bounded session per `structural_validate()` command; identical structural report bytes and issue ordering.

- [ ] **Step 1: Add a RED structural-validation reuse test**

Run `structural_validate(root, project_roots=[project], check_generated=True)` on a copied repository with one external Pack and count Gates. Assert one Gate per exact Pack key, unchanged generated-drift findings, and identical sorted report content apart from no new fields:

```python
report = structural_validate(
    root,
    project_roots=[project],
    check_generated=True,
)

assert report["schemaVersion"] == "structural-validation-report/v1"
assert "verificationStats" not in report
assert gate_count == 1
```

- [ ] **Step 2: Run RED assurance tests**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest -q \
  tests/test_assurance_cli.py -k 'structural or registry'
```

Expected: FAIL on repeated Gate count.

- [ ] **Step 3: Add one internal owner to `structural_validate()`**

Pre-read active external registration IDs as a capacity bound, create one session for the command, and pass it to `_validate_integrations()`, `build_capability_pack_registry()`, `build_capability_lock()`, and `check_projection_freshness()`. Do not add statistics to the public structural report and do not modify generated files.

- [ ] **Step 4: Run assurance and Registry compatibility regressions**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest -q \
  tests/test_assurance_cli.py tests/test_registry_catalog_compat.py
```

Expected: PASS with byte-identical generated expectations and unchanged semantic-gate wording.

- [ ] **Step 5: Commit Task 7**

```bash
git add src/evolution_harness/assurance.py tests/test_assurance_cli.py
git commit -m "perf(assurance): 复用结构验证 session"
```

### Task 8: Decompose the Pay Java Pack E2E lane and prove the 14→1 result

**Files:**

- Modify: `pyproject.toml`
- Modify: `tests/test_pay_nexus_java_capability_adoption_pilot.py:1-198`
- Verify only: `tests/test_cognitura_integration_fixture.py`, `tests/test_e2e.py`

**Interfaces:**

- Consumes: stable session/statistics public API and propagation surface from Tasks 2-7.
- Produces: strict cost markers, six stable scenario nodes, one install-plan node, one module-scoped serial session, and deterministic Gate/checkout/digest assertions.

- [ ] **Step 1: Register strict markers without changing default selection**

Add exactly:

```toml
[tool.pytest.ini_options]
addopts = "--strict-markers"
markers = [
  "fast: deterministic focused coverage with no live External Pack candidate Gate",
  "integration: cross-module, Git, projection, or integration coverage",
  "pack_e2e: serial integration coverage executing a real External Pack candidate Gate/toolchain",
]
```

Do not add `-m` to `addopts`.

- [ ] **Step 2: Replace the combined Pay loop with seven stable nodes**

Add a module-scoped owner:

```python
@pytest.fixture(scope="module")
def pay_verification_session():
    from evolution_harness.capability_pack_registry import CapabilityVerificationSession

    root = Path(__file__).parents[1]
    with CapabilityVerificationSession(
        root,
        allowed_capability_ids={CAPABILITY_ID},
    ) as session:
        yield session
    assert session.stats.active_use_lease_count == 0
```

Parameterize the scenario nodes by exact stems:

```python
PAY_SCENARIOS = (
    "closed-architecture-protection",
    "consumed-stage-does-not-authorize-wave0",
    "current-authority-denies-execution",
    "next-slice-readiness-resolution",
    "review-go-does-not-authorize",
    "stage4-stop-replay",
)


@pytest.mark.integration
@pytest.mark.pack_e2e
@pytest.mark.parametrize("scenario_stem", PAY_SCENARIOS, ids=PAY_SCENARIOS)
def test_pay_nexus_scenario_remains_read_only(
    scenario_stem: str,
    pay_source: Path,
    pay_verification_session,
):
    result = run_integration_scenario(
        root,
        integration,
        pay_source,
        integration / "scenarios" / f"{scenario_stem}.yaml",
        verification_session=pay_verification_session,
    )
    assert result["gate"] == "PASS"
```

Create a separate `test_pay_nexus_install_plan_remains_read_only` using the same session and the existing exact `DRY_RUN`, 46-action, and source Git-state assertions.

- [ ] **Step 3: Add deterministic end-of-module cost assertions**

The install node executes after the six scenario nodes in the canonical serial selection and asserts:

```python
stats = pay_verification_session.stats
assert stats.full_candidate_gate_count == 1
assert stats.isolated_checkout_count == 1
assert stats.toolchain_directory_digest_count == 6
assert stats.by_pack
```

Also retain the broader diagnostic ceilings in a focused stats test: Gate/checkouts `<= 2`, directory digests `<= 12`. Never turn the second Gate into an accepted fixed-candidate result for the one-key canonical batch.

- [ ] **Step 4: Verify collection and marker boundaries before running Java**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest \
  --collect-only -q -m pack_e2e \
  tests/test_pay_nexus_java_capability_adoption_pilot.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest \
  --collect-only -q -m 'integration and not pack_e2e' \
  tests/test_pay_nexus_java_capability_adoption_pilot.py
```

Expected: the first command lists exactly six scenario nodes plus one install node; the second excludes those seven. The complete unfiltered collection still contains every repository test.

- [ ] **Step 5: Run the optimized Pay batch three times and record actual wall time**

```bash
for run_id in 1 2 3; do
  /usr/bin/time -lp env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src \
    "$HARNESS_PYTHON" -m pytest -q -m pack_e2e \
    tests/test_pay_nexus_java_capability_adoption_pilot.py \
    >"/private/tmp/harness-pack-optimized-${run_id}.stdout" \
    2>"/private/tmp/harness-pack-optimized-${run_id}.stderr"
done
```

Expected: all three runs PASS with one Gate, one checkout, six directory digests, zero semantic drift, and a reported median wall-clock reduction of at least 70%. If reduction is lower, report the measured result and do not claim acceptance.

- [ ] **Step 6: Run focused cross-Pack semantic regressions**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest -q \
  tests/test_pay_nexus_java_capability_adoption_pilot.py \
  tests/test_cognitura_integration_fixture.py \
  tests/test_e2e.py
```

Expected: PASS; Java and Web Pack identity, locator, Authority, projection, read-only install, and all business `DENY` behavior remain unchanged.

- [ ] **Step 7: Commit Task 8**

```bash
git add pyproject.toml tests/test_pay_nexus_java_capability_adoption_pilot.py
git commit -m "test(pack): 拆分 Java Pack E2E 成本节点"
```

### Task 9: Stabilize the candidate, run complete verification once, and obtain the final gate

**Files:**

- Modify only if a failing focused test identifies an in-scope defect in the frozen Exact WriteSet.
- Do not modify generated artifacts, external repositories, project Authority, Coordinator, or Phase 2 receipt files.

**Interfaces:**

- Consumes: the complete Phase 1 candidate from Tasks 1-8.
- Produces: fixed Candidate/Parent/Tree, focused/full test evidence, benchmark comparison, and one independent final review.

- [ ] **Step 1: Run the affected regression matrix**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest -q \
  tests/test_external_pack_verification_session.py \
  tests/test_capability_pack_registry.py \
  tests/test_lock_enforcement.py \
  tests/test_project_state.py \
  tests/test_registry_catalog_compat.py \
  tests/test_resolver.py \
  tests/test_projection.py \
  tests/test_projection_install.py \
  tests/test_integration_e2e.py \
  tests/test_assurance_cli.py \
  tests/test_project_registration.py \
  tests/test_pay_nexus_java_capability_adoption_pilot.py \
  tests/test_cognitura_integration_fixture.py \
  tests/test_e2e.py
```

Expected: PASS with no generated or external-project writes.

- [ ] **Step 2: Verify formatting, public CLI checks, and exact worktree scope**

```bash
git diff --check
PATH="/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin:$PATH" ./harness validate --check-generated --format json
PATH="/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin:$PATH" ./harness registry build --check --format json
PATH="/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin:$PATH" ./harness catalog build --check --format json
git status --short --untracked-files=all
```

Expected: commands PASS; status contains only files in the frozen Exact WriteSet and no generated drift.

- [ ] **Step 3: Run the complete regression exactly once after the candidate is stable**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src "$HARNESS_PYTHON" -m pytest -q \
  > /private/tmp/harness-external-pack-phase1-full.stdout \
  2> /private/tmp/harness-external-pack-phase1-full.stderr
```

Expected: exit `0` with a complete passed summary. If interrupted, report completed nodes and the interruption; do not call it a full PASS.

- [ ] **Step 4: Commit only necessary final in-scope corrections**

```bash
git status --short --untracked-files=all
git diff --check
```

If no corrections are needed, create no empty commit. If corrections are needed, stage only the affected Exact WriteSet files and use the concrete message `fix(pack): 修复验证 session 回归`.

- [ ] **Step 5: Freeze and record candidate identity**

```bash
git rev-parse HEAD HEAD^ HEAD^{tree}
git status --short --untracked-files=all
```

Expected: Candidate, Parent, and Tree resolve; tracked and untracked status is empty.

- [ ] **Step 6: Request one independent fixed-candidate deep review**

The reviewer receives Base, Candidate, Parent, Tree, Exact WriteSet, focused/full test commands and results, benchmark logs/medians, and must review correctness, concurrency, TOCTOU, Registry/lock/projection compatibility, CLI behavior, cleanup, failure poisoning, and consumer migration burden. Any P0/P1 finding is `NO-GO` and returns to the owning task's RED test; do not add a second full regression or duplicate reviewer unless the tree or risk changes.

- [ ] **Step 7: Report the implementation result without expanding authorization**

Report separately: code implemented, tests/benchmark evidence, fixed-candidate review verdict, local commit/branch state, and the facts that no merge to `main`, push, release, deployment, downstream adoption, Phase 2 receipts, or Coordinator optimization occurred.
