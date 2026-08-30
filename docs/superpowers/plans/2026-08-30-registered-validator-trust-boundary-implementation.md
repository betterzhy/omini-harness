# Registered Validator Trust Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the rejected same-UID process-containment claim, retain safe managed runtime scratch and operation-scoped Pack reuse, complete the App-independent Java toolchain migration, and prove the 14→1 performance result with a Harness-owned immutable benchmark that is independent of Pay-Nexus adoption drift.

**Architecture:** The exact registered Validator bytes are a pinned trust root; the Validator owns isolation for candidate-derived execution. Harness restores the direct Validator process contract, retains descriptor-safe runtime scratch and pre/post TOCTOU checks, and reuses one `VerifiedCapabilityPack` inside an explicit `CapabilityVerificationSession`. Performance acceptance uses a test-only neutral Pay-shaped fixture; the real Pay shadow remains an exact fail-closed drift sentinel and is not rebound by this task.

**Tech Stack:** Python 3.12, pytest 8, Git, YAML/JSON schemas, Java 21, Maven 3.9.16, Ruby 3.4, macOS Darwin arm64.

**Spec:** `docs/superpowers/specs/2026-08-30-registered-validator-trust-boundary-design.md`

## Global Constraints

- Preserve `capability-lock/v2`, canonical JSON, exact lock fingerprint construction, immutable Pack source commit/tree/content, Validator digest/ABI, closed-scenario Java exclusion, and all business execution `DENY` decisions.
- Treat registered Validator bytes as trusted and identity-pinned; do not claim containment of a malicious registered same-UID Validator.
- Candidate-derived command isolation remains owned and self-tested by the registered Validator; do not modify Java Pack content or Validator bytes.
- Keep private runtime `TMPDIR` out of canonical registration, profile, binding witness, lock, projection, Pack key, and `VerifiedToolchain.environment`.
- Keep operation/session reuse in-process only. No persistent or cross-process Gate trust cache.
- Preserve the four paused Java-migration working-tree files until Task 2 owns them: `core/registries/capability-packs.yaml`, `core/registries/capability-validator-toolchains.yaml`, `tests/test_capability_pack_registry.py`, and `tests/test_java_engineering_standard_registration_fixture.py`.
- Use `/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python` with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and `PYTHONPATH=src`.
- Execute the real Java Gate outside the outer Codex filesystem sandbox because the fixed Java Validator deliberately probes nested isolation and fails closed when that capability is unavailable.
- No Pay-Nexus repository write, Java Pack write, App modification, merge, push, release, deploy, Skill install/apply, Authority change, or business execution authorization.
- Do not modify `integrations/pay-nexus-shadow/**`. The benchmark fixture is test-only, non-Authority, and must not be described as Pay adoption, projection, or implementation readiness.
- Do not xfail or skip the stale real-Pay success nodes. Replace their obsolete success contract with one exact Pack-E2E registration-drift sentinel while preserving structural identity tests.
- Preserve the benchmark workload contract: six independently collected scenarios, 45 Java resources, one existing internal architecture-review Skill action, and therefore 46 install dry-run actions.
- Preserve prior benchmark receipts; never overwrite them. Every new receipt has stdout, stderr, exit code, command/node selection, and SHA-256 evidence.

---

### Task 1: Restore the registered Validator process contract

**Files:**
- Modify: `src/evolution_harness/capability_pack_registry.py`
- Modify: `tests/test_capability_pack_registry.py`
- Verify only: `src/evolution_harness/toolchain_provisioning.py`

**Interfaces:**
- Consumes: `managed_runtime_scratch(repository_root) -> Iterator[Path]` and existing `VerifiedToolchain` environment.
- Produces: `_run_candidate_gate(arguments, *, cwd, timeout, environment) -> subprocess.CompletedProcess[bytes]` with the pre-supervisor signal/exit/output/timeout contract.

- [ ] **Step 1: Write the failing signal/output regression**

Add a direct behavior test that catches inherited ignored `SIGTERM` without inspecting implementation text:

```python
def test_candidate_gate_preserves_registered_validator_signal_and_output_contract(
    tmp_path: Path,
):
    completed = capability_pack_registry._run_candidate_gate(
        [
            "/bin/bash",
            "-c",
            "trap 'printf trapped; exit 41' TERM; "
            "printf before; kill -TERM $$; printf after",
        ],
        cwd=tmp_path,
        timeout=5,
        environment={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
    )

    assert completed.returncode == 41
    assert completed.stdout == b"beforetrapped"
    assert completed.stderr == b""
```

This test fails if a wrapper makes `SIGTERM` ignored before the registered Validator starts.

- [ ] **Step 2: Run RED and record the actual failure**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q tests/test_capability_pack_registry.py::test_candidate_gate_preserves_registered_validator_signal_and_output_contract
```

Expected against `f0807f3`: FAIL with actual return code `0` and output containing `after`.

- [ ] **Step 3: Restore the direct runner implementation**

Remove `threading`, `_CANDIDATE_GATE_TERM_GRACE_SECONDS`, `_CANDIDATE_GATE_KILL_WAIT_SECONDS`, the Bash supervisor, status pipe, drain threads, unconditional normal-exit signalling, and supervisor-specific communication errors. Implement:

```python
def _run_candidate_gate(
    arguments: list[str],
    *,
    cwd: Path,
    timeout: int,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[bytes]:
    try:
        process = subprocess.Popen(
            arguments,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(environment),
            start_new_session=True,
        )
    except OSError as exc:
        raise ValueError("capability pack candidate Gate failed to start") from exc
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        for signal_value in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(process.pid, signal_value)
            except ProcessLookupError:
                pass
        stdout, stderr = process.communicate()
        raise ValueError("capability pack candidate Gate timed out") from exc
    return subprocess.CompletedProcess(
        arguments, process.returncode, stdout, stderr
    )
```

Normal success/nonzero completion must not signal the process group. Timeout cleanup targets only the original group and makes no complete-descendant claim.

- [ ] **Step 4: Run GREEN for the exact regression**

Run the Step 2 command. Expected: `1 passed` with return code `41` and exact captured output.

- [ ] **Step 5: Remove tests that encode the rejected threat model**

Delete only these `f0807f3` surfaces:

- `_assert_process_gone`;
- `_managed_profile_harness` arguments and script branches for `background_descendant`, descendant PID, and descendant-ready files;
- `test_managed_profile_candidate_gate_converges_background_descendant`;
- `test_managed_profile_candidate_gate_rechecks_public_chain_after_group_cleanup`;
- `test_candidate_gate_communication_error_converges_process_session`.

Retain every private-scratch success/failure/timeout, directory/symlink replacement, ancestor replacement, moved-inode ACL, inherited ACL, binding drift, profile drift, and original timeout-process-group test.

- [ ] **Step 6: Run the runner and scratch regression**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q tests/test_capability_pack_registry.py -k 'candidate_gate or managed_runtime_scratch or managed_profile'
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q tests/test_toolchain_provisioning.py
```

Expected: all selected tests PASS; the known paused Java-migration artifact-only assertion may be excluded only if its failure is exactly the ungenerated migration state.

- [ ] **Step 7: Verify the final Task 1 diff and commit**

Confirm `git diff 1641a8f..HEAD` still contains the managed scratch/ACL/inode/public-chain implementation while the final working diff removes the supervisor. Stage only Task 1 hunks from the shared test file, leaving Task 5 hunks unstaged.

```bash
git diff --check
git add src/evolution_harness/capability_pack_registry.py
git add -p tests/test_capability_pack_registry.py
git diff --cached --check
git commit -m "fix(pack): 恢复注册 Validator 运行契约"
```

---

### Task 2: Complete the Java toolchain-profile migration and generated artifacts

**Files:**
- Modify: `core/registries/capability-packs.yaml`
- Modify: `core/registries/capability-validator-toolchains.yaml`
- Modify: `tests/test_capability_pack_registry.py`
- Modify: `tests/test_java_engineering_standard_registration_fixture.py`
- Regenerate: `generated/registries/capability-pack-registry.json`
- Regenerate: `examples/java-engineering-standard-registration-fixture/.agent-evolution/capabilities.lock.yaml`
- Regenerate: `generated/projections/chatgpt/java-engineering-standard-registration-fixture/**`
- Regenerate: `generated/projections/codex/java-engineering-standard-registration-fixture/**`

**Interfaces and fixed identities:**
- Profile ID: `toolchain-profile:java-engineering-standard:darwin-arm64:v1`
- Profile digest: `sha256:c852142343ea97aef6d3a555e5500ecb633baf1a23d846d7bbe72a8bcf5e4490`
- Registration fingerprint: `sha256:cd5bbf5e763b38c96fccbf4c5a9357497c82e10fbf2272e4693fbcd2f63a708b`
- Neutral source revision: `content-sha256:5dca53baa96b90b7786f9d1546d191d60e5c2dfd73a734c91fd9367f02ac366b`
- Lock fingerprint: `sha256:90cf64c1425e75240e1225bea8e1d1f574420d06ee7bff9955e794ea6c20fb73`
- Binding witness: `sha256:a7147595824e84d1bff455188b8b670867e040cf43bcfa800ecb455b29807dc3`
- Ripgrep archive SHA-256: `3750b2e93f37e0c692657da574d7019a101c0084da05a790c83fd335bad973e4`
- Ripgrep executable SHA-256: `a326a1fb48074202e9ad41e4cd1e389eeea372c8c6f7d7e80da81176d5d9430e`
- Artifact digest: `sha256:bfa2614eba25313624c604d16c6c727f3b243e5453b5b261321858f7eee75512`

- [ ] **Step 1: Re-audit the paused Java-migration diff and run its focused RED**

Inspect the four pre-existing dirty files before changing them. The diff must contain only the previously approved App-independent Java profile migration and its assertions; do not absorb unrelated edits.

```bash
git diff -- core/registries/capability-packs.yaml core/registries/capability-validator-toolchains.yaml tests/test_capability_pack_registry.py tests/test_java_engineering_standard_registration_fixture.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q tests/test_capability_pack_registry.py tests/test_java_engineering_standard_registration_fixture.py -k 'java or profile'
```

Expected RED: failures are limited to stale generated registry/lock/projection artifacts. The earlier pre-generation observation was `8 failed, 4 passed, 43 deselected`; if Task 1 changes collection counts, record the new denominator and prove every remaining failure has the same stale-artifact cause.

- [ ] **Step 2: Validate the fixed profile without writing generated artifacts**

Run the registry/profile validation path in dry-run/read-only mode and assert:

- the profile digest, registration fingerprint, binding witness, archive/executable hashes, and artifact digest equal the fixed values above;
- the registered toolchain status is exactly `VERIFIED`;
- no Codex App bundle or versioned App path occurs in the profile, registration, lock, projection, or verified environment;
- the Java Pack commit, tree, content digest, Validator bytes/identity, timeout, and history are unchanged;
- the dry run leaves `git status --short` byte-for-byte unchanged.

- [ ] **Step 3: Regenerate registry, lock, and projections inside one explicit verification session**

Use the repository's existing write APIs, passing the same `CapabilityVerificationSession` through registry generation, lock construction, resolution, and both projection builders. Execute this one real Java Gate outside the outer Codex filesystem sandbox.

Capture `VerificationStats` immediately after registry generation. Because the registry contains the Web and Java Packs, assert exactly:

```text
full_candidate_gate_count = 2
isolated_checkout_count = 2
toolchain_directory_digest_count = 6
verified_pack_count = 2
len(by_pack) = 2
```

The two `by_pack` entries must be exactly one Web entry with `full_candidate_gate_count=1`, `isolated_checkout_count=1`, and no toolchain-directory count, plus one Java entry with `full_candidate_gate_count=1`, `isolated_checkout_count=1`, and `toolchain_directory_digest_count=6`. Snapshot those counters, then build the Java lock, resolve the fixture, build both projections, run projection freshness, and perform the install dry-run through the same session. Assert every counter remains unchanged after those operations.

Do not invoke separate CLI processes between those steps: cross-process reuse is intentionally forbidden.

- [ ] **Step 4: Audit the generated WriteSet and semantic invariants**

Verify that the only generated changes are the registry snapshot, Java fixture lock, and the two Java fixture projections. Assert:

- the neutral artifacts contain exactly 45 resources;
- install dry-run produces exactly 45 read-only actions;
- the fixed lock fingerprint and neutral source revision match the values above;
- locator fields remain outside canonical fingerprints;
- closed scenarios do not select Java;
- all business execution decisions remain `DENY`;
- no Pay-Nexus shadow, Authority, Pack source, Validator, Skill, or business projection file is written.

- [ ] **Step 5: Run focused GREEN regression**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q \
  tests/test_capability_pack_registry.py \
  tests/test_java_engineering_standard_registration_fixture.py \
  tests/test_external_pack_verification_session.py \
  tests/test_resolver.py \
  tests/test_lock_enforcement.py \
  tests/test_projection.py \
  tests/test_projection_install.py
```

Expected: all selected tests PASS, the Java Pack contributes one Gate/checkout and six toolchain directory digests per explicit session, and later lock/resolver/projection/install calls contribute zero additional validations.

- [ ] **Step 6: Stage the exact migration WriteSet and commit**

Use interactive staging for both shared test files so Task 1 and Task 2 ownership stays auditable.

```bash
git diff --check
git add core/registries/capability-packs.yaml core/registries/capability-validator-toolchains.yaml
git add generated/registries/capability-pack-registry.json
git add examples/java-engineering-standard-registration-fixture/.agent-evolution/capabilities.lock.yaml
git add generated/projections/chatgpt/java-engineering-standard-registration-fixture
git add generated/projections/codex/java-engineering-standard-registration-fixture
git add -p tests/test_capability_pack_registry.py
git add -p tests/test_java_engineering_standard_registration_fixture.py
git diff --cached --check
git commit -m "fix(pack): 迁移 Java Validator 到受管工具链 Profile"
```

---

### Task 3: Add the Harness-owned Java profile benchmark and real-Pay drift sentinel

**Files:**
- Create: `tests/fixtures/java-toolchain-profile-pay-benchmark/source/AGENTS.md`
- Create: `tests/fixtures/java-toolchain-profile-pay-benchmark/source/TEST_ONLY.md`
- Create: `tests/fixtures/java-toolchain-profile-pay-benchmark/integration/integration.yaml`
- Create: `tests/fixtures/java-toolchain-profile-pay-benchmark/integration/authority-map.yaml`
- Create: `tests/fixtures/java-toolchain-profile-pay-benchmark/integration/control-plane/.agent-evolution/capabilities.yaml`
- Create: `tests/fixtures/java-toolchain-profile-pay-benchmark/integration/control-plane/.agent-evolution/design-state.yaml`
- Create: six scenario YAML files under `tests/fixtures/java-toolchain-profile-pay-benchmark/integration/scenarios/`
- Create: `tests/test_java_toolchain_profile_pay_benchmark.py`
- Modify: `tests/test_pay_nexus_java_capability_adoption_pilot.py`
- Do not modify: `integrations/pay-nexus-shadow/**`

The fixture is a test input, not Authority. It uses the active neutral Java profile registration and generates its lock and projections only under a per-process temporary Harness root. No lock or generated projection is committed.

- [ ] **Step 1: Write and run the missing-fixture RED**

Create `tests/test_java_toolchain_profile_pay_benchmark.py` with the seven stable test contracts but before adding fixture files:

```python
@pytest.mark.integration
@pytest.mark.pack_e2e
@pytest.mark.parametrize("scenario_name", BENCHMARK_SCENARIO_NAMES)
def test_java_toolchain_profile_pay_scenario_benchmark(...): ...

@pytest.mark.integration
@pytest.mark.pack_e2e
def test_java_toolchain_profile_pay_install_plan_benchmark(...): ...
```

Run one scenario node and require RED because the fixture is absent. The failure must not be a Java Gate, App path, or Pay-shadow error.

- [ ] **Step 2: Build the neutral Pay-shaped fixture**

Model exactly six independent scenario vectors with the same behavioral dimensions as the historical Pay workload:

- closed architecture protection selects no Java;
- consumed-stage evidence does not authorize Wave 0;
- current Authority denies execution;
- next-slice readiness remains read-only;
- review `GO` does not authorize implementation;
- Stage 4 stop replay remains read-only.

Use neutral synthetic names and source facts. Preserve `PROJECT_TRUTH_WINS`, selected/excluded capability IDs, immutable read-only source inputs, and all business execution decisions as `DENY`. The Java framework contributes exactly 45 resources; the existing internal architecture-review Skill contributes one additional read-only install action.

- [ ] **Step 3: Materialize a temporary Harness root and one explicit session**

Follow the repository-local fixture pattern from `tests/test_neutral_integration_fixture.py`: copy only the required `core`, `design`, and `runtime` roots plus the new source/integration fixture into `tmp_path_factory` storage so the integration stays inside its Harness root.

Within one module-scoped setup:

1. create one `CapabilityVerificationSession`;
2. build the active capability lock in the temporary integration;
3. build the integration projection;
4. run the six scenario resolutions;
5. run freshness/projection validation;
6. run the install dry-run;
7. expose immutable results and the session stats to the seven tests.

Do not spawn a second Python process or create a second verification session inside this benchmark module.

- [ ] **Step 4: Assert benchmark equivalence and exact cost**

Across the seven nodes assert:

- six independently collected scenario results retain their expected facts, selected/excluded IDs, `PROJECT_TRUTH_WINS`, closed-scenario Java exclusion, and `DENY` decisions;
- lock, projection, resource digests, and source bytes remain unchanged after resolution, freshness, and install dry-run;
- Java registration status is `VERIFIED`, no App path occurs, and the projection contains exactly 45 Java resources;
- the install plan contains exactly 46 read-only actions: 45 Java resource actions plus one internal Skill action;
- final session stats are exactly one Java candidate Gate, one isolated checkout, six toolchain-directory digests, and one verified Java Pack;
- later resolver/freshness/install operations add zero validation counts.

Run all seven nodes outside the outer sandbox. Expected GREEN: `7 passed`.

- [ ] **Step 5: Replace obsolete real-Pay success expectations with one exact drift sentinel**

Keep all structural Pay identity, source, registration-history, projection-shape, and read-only assertions that remain current. Remove the seven obsolete expected-success benchmark nodes and any now-unused module-scoped Pay verification session.

Add one `integration + pack_e2e` test that invokes one representative real Pay integration path with a fresh session and asserts the exact fail-closed error:

```text
external capability pack lock registration drift: framework:java:java-engineering-standard
```

Also assert the cloned Pay source bytes are unchanged. Do not xfail, skip, regenerate, rebind, or write the Pay shadow.

- [ ] **Step 6: Run focused semantic GREEN and commit**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q \
  tests/test_java_toolchain_profile_pay_benchmark.py \
  tests/test_pay_nexus_java_capability_adoption_pilot.py \
  tests/test_lock_enforcement.py \
  tests/test_resolver.py \
  tests/test_projection.py \
  tests/test_projection_install.py
```

Require no xfail/skip and no tracked write outside the Task 3 WriteSet. Then:

```bash
git diff --check
git add tests/fixtures/java-toolchain-profile-pay-benchmark tests/test_java_toolchain_profile_pay_benchmark.py tests/test_pay_nexus_java_capability_adoption_pilot.py
git diff --cached --check
git commit -m "test(pack): 增加独立 Java Profile 性能基准"
```

- [ ] **Step 7: Obtain Task 3 implementation review**

Use a fresh reviewer against the Task 3 commit. Require confirmation that the fixture is non-Authority, preserves the historical workload dimensions, proves exact cost, and does not weaken or hide the real Pay fail-closed state. Resolve all P0/P1 findings before evidence collection.

---

### Task 4: Close mutation, semantic, and performance evidence

**Files:**
- Verify only: production source, registries, generated artifacts, and tests
- Modify tests only by routing a demonstrated missing assertion back to Task 3
- Write receipts outside Git: `/private/tmp/harness-pack-profile-optimized-*`

Once this task starts, the candidate source and tests are frozen. Any source defect routes back to Task 1/2; any benchmark-test defect routes back to Task 3. After a fix, rerun all affected evidence.

- [ ] **Step 1: Run deterministic invalidation and TOCTOU tests**

Run the focused negative matrix covering source identity, Validator identity/ABI, registration/lock fingerprint, profile/binding/archive/executable/Java/Maven/Ruby/repository mutation, scratch/public-chain/ACL/inode mutation, pre/post Gate TOCTOU, and session-boundary revalidation:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q \
  tests/test_toolchain_profile.py \
  tests/test_toolchain_provisioning.py \
  tests/test_external_pack_verification_session.py \
  tests/test_capability_pack_registry.py -k 'mutation or drift or toctou or scratch or session or cache or candidate_gate'
```

Expected: every mutation fails closed deterministically; unchanged identity reuses only the current in-process session.

- [ ] **Step 2: Run semantic equivalence including both evidence chains**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q \
  tests/test_lock_enforcement.py \
  tests/test_resolver.py \
  tests/test_projection.py \
  tests/test_projection_install.py \
  tests/test_java_toolchain_profile_pay_benchmark.py \
  tests/test_pay_nexus_java_capability_adoption_pilot.py
```

Require the neutral benchmark to pass with exact lock/resource/resolver/projection/install invariants and require the real Pay sentinel to pass only by observing the exact registration drift. This proves Harness behavior without claiming Pay readiness.

- [ ] **Step 3: Freeze the exact seven benchmark node IDs**

Collect only `tests/test_java_toolchain_profile_pay_benchmark.py -m pack_e2e`. Store the six parameterized scenario IDs and one install-plan ID explicitly; do not benchmark the real-Pay drift sentinel.

- [ ] **Step 4: Execute three independent optimized benchmark processes**

For run IDs 1, 2, and 3, execute the same seven explicit node IDs in fresh Python processes outside the outer sandbox. Preserve distinct `.command`, `.nodes`, `.stdout`, `.stderr`, `.exit`, and duration receipts under `/private/tmp/harness-pack-profile-optimized-<run_id>.*`. Wrap with `/usr/bin/time -lp` and preserve the real pytest exit status.

Require per run: exit `0`, seven passed, one Java Gate, one checkout, six directory digests, 45 Java resources, 46 read-only install actions, no App path, and `VERIFIED` profile status.

- [ ] **Step 5: Compare the measured median with the fixed baseline**

Use historical durations `4037.40s`, `2910.40s`, and `2654.28s`; baseline median is `2910.40s`. Compute:

```text
reduction = 1 - optimized_median / 2910.40
target: optimized_median < 873.12 seconds
```

Report actual values. Preserve failed or slow receipts; never substitute the earlier invalid `96.76s / 7 failed` attempt.

- [ ] **Step 6: Hash all benchmark evidence**

Create `/private/tmp/harness-pack-profile-benchmark.sha256` over baseline and optimized command/node/stdout/stderr/exit receipts. Require `git status --short` unchanged from Task 3. Do not create an evidence-only commit.

---

### Task 5: Run tiered regression, fix the candidate, and obtain independent review

**Files:**
- Verify only: all tracked source, tests, registries, locks, and generated projections
- Write receipts outside Git: `/private/tmp/harness-pack-profile-regression-*`
- No product implementation of the deferred shard-receipt subsystem

- [ ] **Step 1: Run generated-artifact and schema gates**

Run the repository's existing registry, lock, projection, JSON/YAML schema, canonical serialization, and generated-artifact freshness checks. Every check must be read-only after Task 2 generation and leave the worktree unchanged.

- [ ] **Step 2: Collect four disjoint cost lanes**

Create node-ID receipts before execution for:

```text
pack-e2e:    -m 'pack_e2e'
integration: -m 'integration and not pack_e2e'
fast:        -m 'fast and not integration and not pack_e2e'
default:     -m 'not fast and not integration and not pack_e2e'
```

The selectors apply the precedence `pack-e2e -> integration -> fast -> default`, so a multiply marked node appears once. Also collect all unfiltered node IDs. Prove the four lane sets are pairwise disjoint and their union equals the complete collection. Record an explicit zero-node receipt if a lane is empty; do not call an empty lane a test PASS.

This is execution evidence for the current candidate only. It does not implement resumable product-level sharding, checkpoints, or a custom receipt runner.

- [ ] **Step 3: Execute every lane with stable receipts**

For each lane, save command, node IDs, stdout, stderr, exit code, duration, and SHA-256 under `/private/tmp/harness-pack-profile-regression-<lane>.*`. Run the Pack-E2E lane outside the outer Codex filesystem sandbox. Continue to the next lane after an ordinary test failure so every completed lane retains evidence; stop for an Authority violation, unexpected write, or safety boundary breach.

- [ ] **Step 4: Run one complete unfiltered regression**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q
```

Execute outside the outer sandbox, save complete stdout/stderr/exit/duration/node collection receipts, and require a real terminal pytest result. An interrupted summary such as `644 passed` plus `SIGINT` is evidence of interruption, not a full Gate PASS.

- [ ] **Step 5: Fix and record the candidate identity**

Require a clean worktree and record:

```bash
git status --short
git rev-parse HEAD
git rev-parse HEAD^
git rev-parse HEAD^{tree}
git log -1 --format='%H%n%P%n%T%n%s'
```

Record Candidate, Parent, Tree, Exact WriteSet, all test denominators, generated-artifact results, benchmark median/reduction, Gate/checkout/digest counters, and receipt hashes. Any later code/test/generated change invalidates the candidate and requires rerunning affected evidence.

- [ ] **Step 6: Obtain the required independent fixed-candidate review**

Request one `deep_reviewer` review at `gpt-5.6-sol / xhigh` against the exact Candidate/Parent/Tree. Provide the approved trust-boundary spec, this plan, Exact WriteSet, mutation matrix, semantic suite, tier/full regression receipts, benchmark receipts, and these explicit review questions:

- Does the implementation remove the rejected same-UID descendant-containment claim and preserve the registered Validator signal/exit/output contract?
- Is candidate-derived isolation still owned and fail-closed by the exact registered Validator?
- Are runtime scratch and verified-session reuse bounded, noncanonical, TOCTOU-safe, and invalidated by every required identity mutation?
- Are lock, projection, resolver, Registry, Authority, and business execution semantics unchanged?
- Does the Harness-owned benchmark faithfully preserve the six-scenario/45-resource/46-action workload while remaining non-Authority and independent of Pay adoption drift?
- Does the real Pay sentinel remain exact and fail-closed without xfail, skip, rebind, or shadow writes?
- Do the receipts prove the actual `14 -> <=2, target 1` Gate and `~84 -> <=12, target 6` digest result and the measured runtime outcome?

Final Gate requires `GO` with no unresolved P0/P1 finding. Resolve lesser findings or explicitly document why they do not block the approved acceptance criteria; any candidate-changing fix requires a new fixed candidate and affected reruns.

- [ ] **Step 7: Hand off without crossing authorization boundaries**

Report separately:

- implementation and test status;
- fixed Candidate/Parent/Tree;
- Gate/checkout/digest before/after counts;
- three-run baseline and optimized medians with actual reduction;
- semantic/security invariant status;
- tier and full-regression denominators and receipt locations/hashes;
- independent review verdict;
- remaining authorization boundaries.

Do not merge, push, release, deploy, modify Pay-Nexus, or authorize business execution. State explicitly that `docs/superpowers/specs/2026-08-29-pytest-shard-receipts-design.md` remains a separate deferred subsystem requiring explicit user approval, its own Exact WriteSet, and independent design review.
