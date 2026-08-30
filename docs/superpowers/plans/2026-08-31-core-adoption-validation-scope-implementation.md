# Harness Core / Adoption Validation Scope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split Harness core validation from project adoption validation while preserving default aggregate fail-closed compatibility, and make the real-Pay sentinel accept only exact post-verification lock identity drift.

**Architecture:** `structural_validate` receives an explicit `all | core | adoption` scope and conditionally executes two non-overlapping validation domains; only adoption owns external Pack verification sessions. A private lock-drift `ValueError` subtype distinguishes genuine verified lock identity mismatch from Pack verification failure without changing the public error string.

**Tech Stack:** Python 3.12, argparse, pytest 8, JSON/YAML deterministic artifacts, Git, CapabilityVerificationSession.

**Spec:** `docs/superpowers/specs/2026-08-31-core-adoption-validation-scope-design.md`

## Global Constraints

- Default `validate` remains byte- and exit-compatible with `--scope all`.
- `core` must not load Pack registrations, create a verification session, enumerate integrations, build locks/projections/Pack Registry, execute a candidate Gate, or digest Pack toolchain directories.
- `adoption` and `all` remain fail-closed for the unchanged Pay shadow drift and every Pack verification failure.
- Public registration-drift error text remains exactly `external capability pack lock registration drift: <capability-id>`.
- No skip, xfail, path allowlist, hidden suppression, persistent verified cache, Pay rebind, or generated shadow refresh.
- Preserve immutable source/Validator/toolchain identity, `capability-lock/v2`, canonical fingerprint, locator exclusion, TOCTOU, closed-scenario Java exclusion and all business `DENY` decisions.
- Do not modify `integrations/pay-nexus-shadow/**`, real Pay, Java Pack, Validator, App, Authority, Skills, business permissions, merge, push, release or deploy state.
- Use `/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python` with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `PYTHONPATH=src`, and `-p no:cacheprovider`.
- Redirect long pytest/Validator stdout and stderr directly to `/private/tmp`; return only bounded summaries.

---

### Task 1: Split structural validation into core and adoption fault domains

**Files:**
- Modify: `src/evolution_harness/assurance.py`
- Modify: `src/evolution_harness/cli.py`
- Modify: `tests/test_assurance_cli.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `structural_validate(repository_root, *, project_roots=(), check_generated=False, scope="all") -> dict[str, Any]`.
- CLI: `harness validate --scope {all,core,adoption}`; default `all`.
- `structural-validation-report/v1` shape remains unchanged.

- [ ] **Step 1: Add RED for a core scope that never touches adoption paths**

Add this real-behavior test using existing `_copy_repo` and `_make_external_pack_source_unavailable` helpers:

```python
def test_core_scope_does_not_touch_adoption_or_external_pack_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from evolution_harness import assurance
    from evolution_harness import capability_pack_registry

    root, _ = _copy_repo(tmp_path)
    _make_external_pack_source_unavailable(root, tmp_path)

    def forbidden(*_args, **_kwargs):
        pytest.fail("core scope touched adoption validation")

    monkeypatch.setattr(assurance, "load_capability_pack_registrations", forbidden)
    monkeypatch.setattr(assurance, "CapabilityVerificationSession", forbidden)
    monkeypatch.setattr(assurance, "_validate_integrations", forbidden)
    monkeypatch.setattr(capability_pack_registry, "_run_candidate_gate", forbidden)

    report = assurance.structural_validate(
        root,
        scope="core",
        check_generated=True,
    )

    assert report["structuralGate"] == "PASS"
    assert report["issues"] == []
    assert report["integrationCount"] == 0
```

- [ ] **Step 2: Run RED and retain the exact missing-scope failure**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src \
/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q -p no:cacheprovider \
tests/test_assurance_cli.py::test_core_scope_does_not_touch_adoption_or_external_pack_paths
```

Expected RED: `TypeError` because `structural_validate` does not accept `scope`.

- [ ] **Step 3: Add RED for scope isolation, generated ownership and CLI compatibility**

Add deterministic tests with these exact contracts:

```python
def test_validation_scopes_keep_unavailable_pack_in_owning_fault_domain(tmp_path: Path):
    root, _ = _copy_repo(tmp_path)
    _make_external_pack_source_unavailable(root, tmp_path)
    core = structural_validate(root, scope="core", check_generated=True)
    adoption = structural_validate(root, scope="adoption", check_generated=True)
    aggregate = structural_validate(root, scope="all", check_generated=True)
    assert core["structuralGate"] == "PASS"
    assert core["integrationCount"] == 0
    for report in (adoption, aggregate):
        assert report["structuralGate"] == "FAIL"
        assert any(
            "capability pack source root is unavailable" in issue["message"]
            for issue in report["issues"]
        )


def test_validate_default_scope_is_byte_identical_to_explicit_all(tmp_path: Path):
    root, _ = _copy_repo(tmp_path)
    _make_external_pack_source_unavailable(root, tmp_path)
    default = _run_module(root, "evolution_harness.cli", "validate", "--check-generated", "--format", "json")
    explicit = _run_module(root, "evolution_harness.cli", "validate", "--scope", "all", "--check-generated", "--format", "json")
    assert (default.returncode, default.stdout, default.stderr) == (
        explicit.returncode,
        explicit.stdout,
        explicit.stderr,
    )
```

Also add:

- `test_core_generated_check_owns_local_registry_drift`: corrupt `generated/registries/design-registry.json`; only core/all contains that path.
- `test_adoption_generated_check_owns_capability_pack_registry_drift`: corrupt `generated/registries/capability-pack-registry.json`; core remains PASS and only adoption/all contains that path.
- `test_validate_core_scope_rejects_project_argument`: CLI returns `2`, stdout empty, and stderr contains both `--scope core` and `--project`.

Run all new nodes and require failures only because `scope`/CLI support is absent.

- [ ] **Step 4: Implement the minimal scope dispatcher**

In `assurance.py`, add:

```python
_VALIDATION_SCOPES = frozenset({"all", "core", "adoption"})


def structural_validate(
    repository_root: Path,
    *,
    project_roots: Iterable[Path] = (),
    check_generated: bool = False,
    scope: str = "all",
) -> dict[str, Any]:
    if scope not in _VALIDATION_SCOPES:
        raise ValueError(f"unsupported validation scope: {scope}")
    projects = tuple(Path(value) for value in project_roots)
    if scope == "core" and projects:
        raise ValueError("core validation scope does not accept project roots")
    if scope == "core":
        return _structural_validate(
            Path(repository_root),
            project_roots=(),
            check_generated=check_generated,
            verification_session=None,
            scope=scope,
        )
    # Existing registration/session fallback remains unchanged for adoption/all.
```

Extend `_structural_validate(..., scope: str)` and preserve current statement order for `all`:

```python
run_core = scope in {"all", "core"}
run_adoption = scope in {"all", "adoption"}
```

- Guard `validate_repository`, learning and engineering with `run_core`.
- Guard project control planes, handoffs, integrations and their count with `run_adoption`; otherwise set `integration_count = 0` and `primary_session_failed = False`.
- Guard the six local generated Registry/catalog checks with `check_generated and run_core`.
- Guard explicit project lock/projection freshness and Capability Pack Registry generation with `check_generated and run_adoption`.
- Keep report key order and metadata count construction unchanged.

In `cli.py`, add:

```python
p.add_argument("--scope", choices=("all", "core", "adoption"), default="all")
```

Before implicit project-fixture selection:

```python
if args.scope == "core" and args.project:
    parser.error("validate --scope core does not accept --project")
```

Select the implicit fixture only for `all` or `adoption`, pass `scope=args.scope`, and leave default `all` output unchanged.

- [ ] **Step 5: Run GREEN and focused compatibility regression**

Run the new nodes, then:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src \
/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q -p no:cacheprovider \
tests/test_assurance_cli.py
```

Require every test PASS, including the existing exact report-byte and Gate-count tests.

- [ ] **Step 6: Prove the live scope boundary without writing generated files**

Run three separate processes with stdout/stderr receipts:

```bash
python -m evolution_harness.cli --repository-root . validate --scope core --check-generated --format json
python -m evolution_harness.cli --repository-root . validate --scope adoption --check-generated --format json
python -m evolution_harness.cli --repository-root . validate --scope all --check-generated --format json
```

Require:

- core exit `0`, structural `PASS`, no candidate Gate process and no tracked write;
- adoption/all nonzero only for the exact unchanged Pay adoption drift;
- default-without-scope bytes and exit equal explicit all;
- all worktree identities unchanged.

- [ ] **Step 7: Document and commit Task 1**

Update README's local acceptance sequence to show core, adoption and all separately, state that core is the routine Harness candidate Gate, and state that adoption/all remain fail-closed status. Run `git diff --check`, stage only Task 1 files, and commit:

```text
feat(assurance): 分离核心与接入验证故障域
```

---

### Task 2: Distinguish verified lock identity drift from Pack verification failure

**Files:**
- Modify: `src/evolution_harness/project.py`
- Modify: `tests/test_lock_enforcement.py`
- Modify: `tests/test_pay_nexus_java_capability_adoption_pilot.py`

**Interfaces:**
- Produces private `_ExternalCapabilityLockRegistrationDrift(ValueError)` with the existing exact public message.
- Does not change public function signatures or public error text.

- [ ] **Step 1: Add RED for a genuine post-verification identity mismatch**

Tighten an existing copied-identity test without importing a nonexistent class:

```python
with pytest.raises(ValueError) as exc_info:
    verify_capability_lock(root, project)
assert str(exc_info.value) == (
    f"external capability pack lock registration drift: {EXTERNAL_CAPABILITY_ID}"
)
assert type(exc_info.value).__name__ == "_ExternalCapabilityLockRegistrationDrift"
```

Apply this to `test_external_pack_lock_rejects_copied_registration_identity_drift` and the Validator-identity drift node, whose verified Pack succeeds before exact lock comparison.

- [ ] **Step 2: Run RED and verify the classification failure**

Run the two tests. Expected RED: exact public text already matches, but the concrete type is plain `ValueError`.

- [ ] **Step 3: Implement the private typed drift error and exact branches**

In `project.py`, add:

```python
class _ExternalCapabilityLockRegistrationDrift(ValueError):
    def __init__(self, capability_id: str) -> None:
        super().__init__(
            f"external capability pack lock registration drift: {capability_id}"
        )
        self.capability_id = capability_id
```

Raise it only for genuine registration-drift branches:

- internal/external capability collision;
- missing verified entry after collection;
- exact `_external_lock_source` mismatch;
- locator-bound witness mismatch.

Keep the `_get_verified_capability_pack` `KeyError/ValueError` compatibility wrapper as a plain `ValueError` raised from the original failure. Do not retype candidate Gate, toolchain, source, registration, session or TOCTOU failure.

- [ ] **Step 4: Run GREEN for exact identity drift**

Run the Step 2 nodes and require typed errors with byte-identical public strings. Then replace type-name string checks with a private-class import and `pytest.raises(_ExternalCapabilityLockRegistrationDrift)` as a refactor; rerun GREEN.

- [ ] **Step 5: Add deterministic failure-not-typed regression**

Using `_project_selecting_registered_pack`, first build the real lock, then monkeypatch `project._get_verified_capability_pack` to raise each of:

```text
capability pack candidate Gate failed
capability pack validator toolchain identity mismatch
capability pack source commit does not match checkout HEAD
```

Call `verify_capability_lock` and assert for every case:

- fail-closed `ValueError`;
- existing exact compatibility message;
- not an instance of `_ExternalCapabilityLockRegistrationDrift`;
- original failure is retained as `__cause__`.

This test must fail if the broad Pack-verification wrapper is ever changed to the typed drift class.

- [ ] **Step 6: Make the real-Pay sentinel prove successful Pack verification first**

In the existing Pack-E2E sentinel, use one session:

```python
get_registered_capability_pack(
    root,
    CAPABILITY_ID,
    verification_session=session,
)
before_scenario = session.stats
assert before_scenario.full_candidate_gate_count == 1
assert before_scenario.isolated_checkout_count == 1
assert before_scenario.toolchain_directory_digest_count == 6
assert before_scenario.verified_pack_count == 1

with pytest.raises(_ExternalCapabilityLockRegistrationDrift) as exc_info:
    run_integration_scenario(..., verification_session=session)
assert str(exc_info.value) == EXPECTED_REGISTRATION_DRIFT
assert session.stats == before_scenario
```

Retain the source Git-state equality and zero active lease assertions. An unrelated Pack failure now occurs before or beneath the typed expectation and fails the sentinel.

- [ ] **Step 7: Run focused lock/session/sentinel GREEN**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src \
/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q -p no:cacheprovider \
tests/test_lock_enforcement.py \
tests/test_external_pack_verification_session.py \
tests/test_resolver.py \
tests/test_projection.py \
tests/test_cognitura_integration_fixture.py
```

Then run the exact real-Pay Pack-E2E sentinel outside any restrictive outer filesystem sandbox. Require one Gate/checkout, six directory digests, typed exact drift, unchanged Pay source and no temporary checkout residue.

- [ ] **Step 8: Commit Task 2**

Run `git diff --check`, stage only Task 2 files, and commit:

```text
fix(lock): 区分 Pack 验证失败与注册漂移
```

---

### Task 3: Rebuild fixed-candidate evidence and obtain final review

**Files:**
- Verify only: the entire repository and approved WriteSet
- Receipts only: `/private/tmp/harness-core-adoption-*`

- [ ] **Step 1: Re-run invalidation and TOCTOU evidence**

Run the prior mutation matrix and require source, Validator, registration, lock, profile, toolchain, scratch and TOCTOU mutation to remain fail-closed. Preserve command/stdout/stderr/exit/duration receipts.

- [ ] **Step 2: Execute and receipt all three live scopes**

Require core PASS without any Pack Gate count, adoption/all exact Pay drift FAIL, and default all byte equality. Record each command, stdout, stderr, exit, duration and SHA-256.

- [ ] **Step 3: Re-run Pack-E2E and full regression**

Run `-m pack_e2e` and the complete unfiltered pytest suite in separate standard processes. Require real terminal results, no skip/xfail, no tracked write, no residual worktree and no unclassified Validator failure. Preserve failures rather than overwriting them.

- [ ] **Step 4: Fix Candidate/Parent/Tree and receipt hashes**

Record clean status, Candidate, Parent, Tree, exact WriteSet, test denominators, scope results, typed sentinel evidence and hashes. Any later tracked change invalidates the candidate and affected evidence.

- [ ] **Step 5: Obtain one independent fixed-candidate deep review**

Request `deep_reviewer / xhigh` against the entire original performance diff plus this amendment. Require explicit decisions on:

- default-all compatibility and core/adoption fault isolation;
- absence of external Pack work in core;
- adoption/all fail-closed Pay truth;
- typed sentinel inability to hide Validator/toolchain/source/TOCTOU failure;
- unchanged identity/fingerprint/projection/resolver/Authority/business semantics;
- retained 14-to-1 Gate and approximately-84-to-6 digest performance evidence.

Final Gate requires `GO`, P0 `0`, P1 `0`. Do not merge, push, release, deploy, rebind Pay, or authorize business execution.
