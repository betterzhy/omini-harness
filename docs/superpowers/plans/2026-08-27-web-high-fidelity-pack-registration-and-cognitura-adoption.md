# Web High-Fidelity Pack Registration and Cognitura Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register and immutably lock `web-high-fidelity` in `omini-harness`, prove its Skill can be deterministically projected for a read-only Cognitura sidecar, and then complete an explicitly authorized Cognitura v2 adoption without rewriting fixed project history.

**Architecture:** Candidate A spans the Pack source and Harness: a machine manifest, external registry, v2 project lock, resolver/projection support, and `cognitura-shadow` are fixed and reviewed once. Candidate B changes only Cognitura after W2-D05 and a separate adoption Authority permit it; it preserves the v1 binding bytes, adds a v2 adoption record, registration pointer, and managed repo-local Skill, then receives one project review.

**Tech Stack:** Bash 3.2-compatible Pack verification, Python 3.12, PyYAML, JSON Schema Draft 2020-12, pytest, deterministic Git commit/tree/blob inspection, SHA-256, existing Harness registry/resolver/projection/install machinery.

**Spec:** `docs/superpowers/specs/2026-08-27-web-high-fidelity-pack-registration-and-cognitura-adoption-design.md`

## Global Constraints

- Use one plan and two stable candidates; do not create new task-card sets, stage models, acceptance dossiers, or duplicate evidence ledgers.
- All added worktrees live below each repository's `.worktrees/` directory and must be ignored by Git before creation.
- `web-high-fidelity` source version is `2.0.0`; Capability ID is exactly `workflow:web-high-fidelity:reference-driven-visual-fidelity`.
- Harness Registry is the registration Authority; Pack source verification cannot assert project adoption, page quality, task completion, merge, or release.
- The first Pack registration is `distributionStatus: LOCAL_ONLY`; no remote, push, publication, or cross-host distribution is introduced.
- Existing internal design assets, generated catalogs, `capability-lock/v1` bytes, lock fingerprints, and `verify_capability_lock()`'s two-value return shape must remain compatible.
- Automatic projection apply/uninstall remains disabled. Candidate A may generate and verify a plan but must not write Cognitura.
- Candidate B must not start until Cognitura is clean, W2-D05 is closed, and an explicit R2 adoption Authority permits the new v2 record, concise AGENTS route, registration, managed Skill, and successor-verifier transition.
- Preserve `docs/engineering/cognitura-high-fidelity-harness-binding.md` byte-for-byte. Do not move, rewrite, or relabel it.
- Do not modify Cognitura product code, visual baselines, reference images, packages, lockfiles, CI, database assets, or page task state.
- During RED-to-GREEN, run only focused tests. Candidate A gets one final full Harness regression and one `deep_reviewer / xhigh`; Candidate B gets only directly affected project Gates and one `deep_reviewer / xhigh`.
- Do not install dependencies globally, install a global Skill, authenticate services, run a real-page Pilot, deploy, release, or push.
- Use Chinese-first Git summaries and bodies under `<type>(<scope>)!: <summary>`; `gov` is a Scope, not a Type.

## Repository and branch layout

```text
/Users/yuzhuangzhuang/Projects/web-high-fidelity
└── .worktrees/web-high-fidelity-pack-v2-registration
    branch codex/web-high-fidelity-pack-v2-registration

/Users/yuzhuangzhuang/Projects/omini-harness
└── .worktrees/web-high-fidelity-pack-cognitura
    branch codex/web-high-fidelity-pack-cognitura

/Users/yuzhuangzhuang/Projects/cognitura
└── .worktrees/web-high-fidelity-pack-v2-adoption
    branch codex/web-high-fidelity-pack-v2-adoption
```

The Cognitura worktree is not created until Task 8 preconditions pass.

---

### Task 1: Freeze the Web Pack v2 source contract

**Files:**
- Create: `/Users/yuzhuangzhuang/Projects/web-high-fidelity/.worktrees/web-high-fidelity-pack-v2-registration/VERSION`
- Create: `/Users/yuzhuangzhuang/Projects/web-high-fidelity/.worktrees/web-high-fidelity-pack-v2-registration/capability-pack.yaml`
- Create: `/Users/yuzhuangzhuang/Projects/web-high-fidelity/.worktrees/web-high-fidelity-pack-v2-registration/docs/migrations/harness-v1-to-capability-pack-v2.md`
- Modify: `/Users/yuzhuangzhuang/Projects/web-high-fidelity/.worktrees/web-high-fidelity-pack-v2-registration/AGENTS.md`
- Modify: `/Users/yuzhuangzhuang/Projects/web-high-fidelity/.worktrees/web-high-fidelity-pack-v2-registration/README.md`
- Modify: `/Users/yuzhuangzhuang/Projects/web-high-fidelity/.worktrees/web-high-fidelity-pack-v2-registration/docs/07-CAPABILITY-PACK-BOUNDARY.md`
- Modify: `/Users/yuzhuangzhuang/Projects/web-high-fidelity/.worktrees/web-high-fidelity-pack-v2-registration/scripts/verify-capability-pack`
- Test: `/Users/yuzhuangzhuang/Projects/web-high-fidelity/.worktrees/web-high-fidelity-pack-v2-registration/tests/capability-pack/verify-capability-pack.sh`

**Interfaces:**
- Consumes: current canonical identity and fixed-candidate verifier.
- Produces: `capability-pack/v1`, version `2.0.0`, exact Skill path, declared content roots, and fixed validator path/argv contract for Harness Task 2.

- [ ] **Step 1: Create the isolated Pack worktree and prove the baseline**

Run from `/Users/yuzhuangzhuang/Projects/web-high-fidelity`:

```bash
git status --short --branch
git check-ignore -q .worktrees
git worktree add .worktrees/web-high-fidelity-pack-v2-registration \
  -b codex/web-high-fidelity-pack-v2-registration main
cd .worktrees/web-high-fidelity-pack-v2-registration
pack_base_commit="$(git rev-parse HEAD)"
pack_base_tree="$(git rev-parse 'HEAD^{tree}')"
bash scripts/verify-capability-pack "${pack_base_commit}" "${pack_base_tree}"
bash tests/capability-pack/verify-capability-pack.sh
```

Expected: current source and mutation suite PASS; worktree is clean.

- [ ] **Step 2: Add failing manifest and registration-boundary mutations**

Extend the existing `new_case`, `rewrite_file`, `commit_case`, and `expect_fail`
pattern with real Git commits. Add `write_valid_manifest`, which writes the
complete Step 4 manifest and `VERSION` into a case before mutation; this makes
the new checks fail against the old verifier without depending on implementation
files that do not exist yet:

```bash
case_root=$(new_case manifest-capability-id-drift)
write_valid_manifest "$case_root"
rewrite_file "$case_root" capability-pack.yaml \
  's/reference-driven-visual-fidelity/visual-delivery/'
commit_case "$case_root" "mutate: drift manifest capability id"
expect_fail manifest_capability_id_drift "$case_root" \
  'capability manifest canonical capability ID mismatch'

case_root=$(new_case manifest-verifier-escape)
write_valid_manifest "$case_root"
rewrite_file "$case_root" capability-pack.yaml \
  's#scripts/verify-capability-pack#../verify-capability-pack#'
commit_case "$case_root" "mutate: escape manifest verifier"
expect_fail manifest_verifier_escape "$case_root" \
  'capability manifest source verifier path is unsafe'

case_root=$(new_case manifest-project-authority-field)
write_valid_manifest "$case_root"
printf '\nTASK_COMPLETE: true\n' >>"$case_root/capability-pack.yaml"
commit_case "$case_root" "mutate: add project authority field"
expect_fail manifest_project_authority_field "$case_root" \
  'capability manifest contains forbidden project authority field'
```

Also cover missing `VERSION`, version mismatch, wrong `skillPath`, missing
validator, unsafe content root, and registration values other than the exact
source-side value approved below.

- [ ] **Step 3: Run RED and capture the expected first failure**

Run:

```bash
bash tests/capability-pack/verify-capability-pack.sh
```

Expected: FAIL because `capability-pack.yaml` and its verifier contract do not
exist yet; the first new case must report the stable expected diagnostic.

- [ ] **Step 4: Add the minimal Pack manifest and version**

Create `VERSION` containing exactly:

```text
2.0.0
```

Create `capability-pack.yaml`:

```yaml
schemaVersion: capability-pack/v1
projectPackName: web-high-fidelity
skillName: web-high-fidelity
displayName: Reference-Driven Web Visual Fidelity
canonicalCapabilityId: workflow:web-high-fidelity:reference-driven-visual-fidelity
version: 2.0.0
registrationAuthority: omini-harness
registrationStatus: REGISTERED
contentDigestContract: capability-pack-content/v1
contentRoots:
  - docs
  - prompts
  - references
  - skills
  - templates
excludedContentRoots:
  - docs/history
  - docs/superpowers
skillPath: skills/web-high-fidelity/SKILL.md
sourceVerifier:
  kind: FIXED_CANDIDATE_GATE
  path: scripts/verify-capability-pack
  argumentsContract: CANDIDATE_COMMIT_TREE
```

The Pack verifier may validate this source claim but must emit
`REGISTRATION_ASSERTION=NOT_EVALUATED_BY_PACK`; only Harness can emit the
registration PASS.

- [ ] **Step 5: Implement minimal manifest checks and migration text**

In `scripts/verify-capability-pack`, add exact-one checks for every scalar above,
verify roots and paths are relative, normalized, non-symlink tracked paths, and
reject the project-owned tokens:

```text
approvedBy approvedOn TASK_COMPLETE MERGE_ALLOWED RELEASE_ALLOWED
```

Update Boundary/README/AGENTS mirrors and explain that `REGISTERED` becomes true
only as part of the cross-repository Candidate A; self-verification alone does
not prove it. The migration document maps v1 `MANIFEST.sha256`, `PROJECT_BINDING`,
HF3, and direct source fields to Harness registration/lock, target v2 adoption,
and task-level HF0/HF1/HF2.

- [ ] **Step 6: Run GREEN and fixed-candidate Pack verification**

Run:

```bash
bash tests/capability-pack/verify-capability-pack.sh
git diff --check
git add VERSION capability-pack.yaml AGENTS.md README.md \
  docs/07-CAPABILITY-PACK-BOUNDARY.md \
  docs/migrations/harness-v1-to-capability-pack-v2.md \
  scripts/verify-capability-pack tests/capability-pack/verify-capability-pack.sh
git commit -m 'feat(pack): 定义 Web Capability Pack v2 注册契约' \
  -m '增加机器清单、版本和固定验证器入口，并保留项目 Authority 与任务结果边界。'
pack_candidate_commit="$(git rev-parse HEAD)"
pack_candidate_tree="$(git rev-parse 'HEAD^{tree}')"
bash scripts/verify-capability-pack \
  "${pack_candidate_commit}" "${pack_candidate_tree}"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
```

Expected: mutation suite and fixed-candidate Gate PASS; record Pack
Candidate/Parent/Tree for Tasks 2-7.

### Task 2: Build the external Pack registry and immutable source validator

**Files:**
- Create: `core/schemas/capability-pack-manifest.schema.json`
- Create: `core/schemas/capability-pack-registration.schema.json`
- Create: `core/registries/capability-packs.yaml`
- Create: `src/evolution_harness/capability_pack_registry.py`
- Test: `tests/test_capability_pack_registry.py`

**Interfaces:**
- Consumes: Pack Candidate/Tree from Task 1 and `SchemaStore.validate()`.
- Produces:
  - `load_capability_pack_registrations(repository_root: Path) -> list[dict[str, Any]]`
  - `compute_capability_pack_content_digest(source_root: Path, manifest: Mapping[str, Any]) -> str`
  - `build_capability_pack_registry(repository_root: Path, *, write: bool = False) -> dict[str, Any]`
  - `get_registered_capability_pack(repository_root: Path, capability_id: str) -> dict[str, Any]`

- [ ] **Step 1: Write Registry RED tests using real temporary Git repositories**

Create focused fixtures inside `tests/test_capability_pack_registry.py` rather
than reading or mutating the live Pack. The fixture helper must initialize a Git
repository, write a valid manifest/Skill/verifier, and return full commit/tree:

```python
def _pack_fixture(tmp_path: Path) -> tuple[Path, str, str]:
    source = tmp_path / "pack"
    source.mkdir()
    _write_valid_pack(source)
    _git(source, "init", "-q")
    _git(source, "config", "user.name", "Pack Test")
    _git(source, "config", "user.email", "pack-test@example.invalid")
    _git(source, "add", "-A")
    _git(source, "commit", "-qm", "test: pack fixture")
    commit = _git(source, "rev-parse", "HEAD")
    tree = _git(source, "rev-parse", "HEAD^{tree}")
    return source, commit, tree
```

Add exact RED cases:

```python
def test_registry_entry_binds_immutable_source_and_validator_identity(tmp_path: Path):
    root, source, commit, tree = _harness_with_pack(tmp_path)
    registry = build_capability_pack_registry(root, write=False)
    entry = registry["entries"][0]
    assert entry["source"]["commit"] == commit
    assert entry["source"]["tree"] == tree
    assert entry["resolvedContentDigest"].startswith("sha256:")
    assert entry["validator"]["sha256"].startswith("sha256:")

def test_registry_rejects_manifest_identity_drift(tmp_path: Path):
    root, source, _, _ = _harness_with_pack(tmp_path)
    _replace(source / "capability-pack.yaml", "reference-driven-visual-fidelity", "visual-delivery")
    _commit(source, "mutate: identity drift")
    with pytest.raises(ValueError, match="capability pack manifest identity mismatch"):
        build_capability_pack_registry(root, write=False)

def test_registry_rejects_validator_digest_drift(tmp_path: Path):
    root, source, _, _ = _harness_with_pack(tmp_path)
    (source / "scripts/verify-capability-pack").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    _commit(source, "mutate: validator drift")
    with pytest.raises(ValueError, match="capability pack validator identity mismatch"):
        build_capability_pack_registry(root, write=False)
```

Also cover duplicate active Capability ID, wrong commit/tree pair, dirty source,
missing Git object, unsafe roots, symlink/submodule/case-fold collision, untracked
active content, failed candidate Gate, and unknown/inactive lookup.

- [ ] **Step 2: Run RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/test_capability_pack_registry.py
```

Expected: import failure for `evolution_harness.capability_pack_registry`.

- [ ] **Step 3: Add strict manifest and registration Schemas**

The manifest Schema requires the exact fields from Task 1, uses
`additionalProperties: false`, restricts paths to normalized relative paths,
restricts version to SemVer, and forbids empty/duplicate roots.

The registration Schema requires exact constants for schema version,
registration ID, capability ID, Pack version, active status, local-only
distribution, local-Git source kind/repository ID, fixed validator kind/path,
and the `CANDIDATE_COMMIT_TREE` argv contract. It requires:

- `source.repositoryPath` equal to the Pack worktree path from this plan;
- `source.commit` and `source.tree` matching `^[0-9a-f]{40}$`;
- `resolvedContentDigest` and `validator.sha256` matching
  `^sha256:[0-9a-f]{64}$`.

Task 1's `git rev-parse` outputs and Task 2's digest functions supply the exact
committed values. No sample, truncated hash, or symbolic marker is committed.

- [ ] **Step 4: Implement the registry module minimally**

Use fixed argv arrays and fail closed:

```python
def build_capability_pack_registry(repository_root: Path, *, write: bool = False) -> dict[str, Any]:
    root = Path(repository_root)
    registrations = load_capability_pack_registrations(root)
    entries = [_validate_registration(root, item) for item in registrations]
    _reject_duplicate_active_ids(entries)
    result = {
        "schemaVersion": "capability-pack-registry/v1",
        "sourceRevision": "content-sha256:" + sha256_bytes(canonical_json_bytes(entries)),
        "entries": sorted(entries, key=lambda entry: entry["registrationId"]),
    }
    if write:
        write_generated_json(root / "generated/registries/capability-pack-registry.json", result)
    return result

def get_registered_capability_pack(repository_root: Path, capability_id: str) -> dict[str, Any]:
    matches = [
        entry for entry in build_capability_pack_registry(repository_root)["entries"]
        if entry["capabilityId"] == capability_id and entry["status"] == "ACTIVE"
    ]
    if len(matches) != 1:
        raise KeyError(f"active capability pack registration not found or ambiguous: {capability_id}")
    return matches[0]
```

Use `git -C <source> ls-tree`, `cat-file`, and `status --porcelain` through
non-shell subprocess argv. Invoke only:

```python
["bash", str(validator_path), source_commit, source_tree]
```

with a fixed environment that disables prompts, lazy fetch, maintenance,
fsmonitor, and untracked cache. Never execute a command string from YAML.

- [ ] **Step 5: Resolve the real Task 1 registration identity**

Run read-only commands against the fixed Pack worktree to compute commit, tree,
content digest, and validator SHA-256 through the new module. Insert those exact
values in `core/registries/capability-packs.yaml`; do not type or truncate hashes
manually.

- [ ] **Step 6: Run GREEN and commit**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/test_capability_pack_registry.py
git diff --check
git add core/schemas/capability-pack-manifest.schema.json \
  core/schemas/capability-pack-registration.schema.json \
  core/registries/capability-packs.yaml \
  src/evolution_harness/capability_pack_registry.py \
  tests/test_capability_pack_registry.py
git commit -m 'feat(registry): 注册外部 Capability Pack 来源' \
  -m '校验固定 Git 候选、内容摘要和验证器身份，并拒绝可变或歧义来源。'
```

Expected: focused tests PASS; no generated artifact is committed until Task 3.

### Task 3: Integrate the Pack registry with generated checks and assurance

**Files:**
- Create: `generated/registries/capability-pack-registry.json`
- Modify: `src/evolution_harness/registry.py`
- Modify: `src/evolution_harness/cli.py`
- Modify: `src/evolution_harness/assurance.py`
- Modify: `tests/test_registry_catalog_compat.py`
- Modify: `tests/test_assurance_cli.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `build_capability_pack_registry()` from Task 2.
- Produces: fourth deterministic registry output, CLI `registry build --check`
  coverage, and structural drift detection. Internal unified catalogs remain
  unchanged.

- [ ] **Step 1: Write generated-drift and catalog-isolation RED tests**

Add:

```python
def test_external_pack_registry_does_not_enter_internal_unified_catalog(tmp_path: Path):
    root = _copy_repo(tmp_path)
    build_capability_pack_registry(root, write=True)
    unified = build_all_catalogs(root, write=True)["unified"]
    assert "workflow:web-high-fidelity:reference-driven-visual-fidelity" not in {
        entry["id"] for entry in unified["entries"]
    }

def test_structural_validation_detects_capability_pack_registry_drift(tmp_path: Path):
    root = _copy_repository_fixture(tmp_path)
    structural_validate(root, check_generated=False)
    generated = root / "generated/registries/capability-pack-registry.json"
    generated.write_text("{}\n", encoding="utf-8")
    result = structural_validate(root, check_generated=True)
    assert result["structuralGate"] == "FAIL"
    assert any("capability-pack-registry.json" in issue for issue in result["issues"])
```

Update fixture-copy lists to include `core/registries` and the new generated
registry without copying the external Pack repository into test roots.

- [ ] **Step 2: Run RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/test_registry_catalog_compat.py::test_external_pack_registry_does_not_enter_internal_unified_catalog \
  tests/test_assurance_cli.py::test_structural_validation_detects_capability_pack_registry_drift
```

Expected: FAIL because build/check/assurance do not include the new registry.

- [ ] **Step 3: Add the registry without changing catalog semantics**

Update `build_all_registries()`:

```python
def build_all_registries(root: Path, *, write: bool = False) -> dict[str, dict[str, Any]]:
    return {
        "design": build_design_registry(root, write=write),
        "designLearning": build_design_learning_registry(root, write=write),
        "engineering": build_engineering_registry(root, write=write),
        "capabilityPacks": build_capability_pack_registry(root, write=write),
    }
```

Do not add Pack entries to `build_all_catalogs()` or
`generated/catalogs/unified-active-catalog.json`.

Extend CLI and assurance generated-path maps with exactly:

```python
"capabilityPacks": root / "generated/registries/capability-pack-registry.json"
```

Add README language that external Pack registration is a separate registry and
does not imply project adoption.

- [ ] **Step 4: Generate, check, and commit the artifact**

Run:

```bash
.venv/bin/harness registry build --check --json
.venv/bin/harness validate --check-generated --json
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/test_registry_catalog_compat.py \
  tests/test_assurance_cli.py
git diff --check
git add generated/registries/capability-pack-registry.json \
  src/evolution_harness/registry.py src/evolution_harness/cli.py \
  src/evolution_harness/assurance.py tests/test_registry_catalog_compat.py \
  tests/test_assurance_cli.py README.md
git commit -m 'feat(registry): 纳入外部 Pack 生成校验' \
  -m '将外部 Pack Registry 加入 CLI 与结构完整性检查，同时保持内部统一目录不变。'
```

Expected: registry and assurance tests PASS; internal catalog counts and bytes do
not change.

### Task 4: Add backward-compatible external Pack project locking

**Files:**
- Modify: `core/schemas/capability-lock.schema.json`
- Modify: `src/evolution_harness/project.py`
- Modify: `tests/test_project_state.py`
- Modify: `tests/test_lock_enforcement.py`

**Interfaces:**
- Consumes: project binding capability IDs and active Pack Registry entries.
- Produces: `capability-lock/v2` only when an external Pack is selected;
  `capability-lock/v1` remains byte-identical for internal-only projects.
- Preserves: `verify_capability_lock(...) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]`.

- [ ] **Step 1: Write lock compatibility and drift RED tests**

Add:

```python
def test_internal_only_lock_is_byte_stable_without_external_packs(tmp_path: Path):
    root, project = _copy_internal_project(tmp_path)
    before = build_capability_lock(root, project, write=False)
    assert before["schemaVersion"] == "capability-lock/v1"
    assert canonical_json_bytes(before) == INTERNAL_V1_LOCK_BYTES

def test_external_pack_binding_generates_v2_exact_lock(tmp_path: Path):
    root, project = _project_selecting_registered_pack(tmp_path)
    lock = build_capability_lock(root, project, write=False)
    assert lock["schemaVersion"] == "capability-lock/v2"
    item = next(item for item in lock["capabilities"] if item["sourceKind"] == "EXTERNAL_CAPABILITY_PACK")
    assert item["sourceRegistrationId"] == "pack:web-high-fidelity"
    assert item["resolvedContentDigest"].startswith("sha256:")
    assert item["validatorIdentity"]["sha256"].startswith("sha256:")

def test_external_pack_lock_rejects_registry_digest_or_revision_drift(tmp_path: Path):
    root, project = _project_selecting_registered_pack(tmp_path)
    build_capability_lock(root, project, write=True)
    _mutate_registration_digest(root)
    with pytest.raises(ValueError, match="external capability pack lock registration drift"):
        verify_capability_lock(root, project)
```

Also prove duplicate IDs, missing active registration, wrong validator identity,
wrong source commit/tree, changed resolved reasons, and unrelated registry entry
addition not moving the selected lock.

- [ ] **Step 2: Run RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/test_project_state.py::test_external_pack_binding_generates_v2_exact_lock \
  tests/test_lock_enforcement.py::test_external_pack_lock_rejects_registry_digest_or_revision_drift \
  tests/test_project_state.py::test_internal_only_lock_is_byte_stable_without_external_packs
```

Expected: external tests FAIL; existing internal test continues to PASS.

- [ ] **Step 3: Extend the lock Schema with conditional v2 fields**

Keep the v1 branch unchanged. Add a v2 branch where external items require:

```yaml
sourceKind: EXTERNAL_CAPABILITY_PACK
sourceRegistrationId: pack:web-high-fidelity
validatorIdentity:
  relativePath: scripts/verify-capability-pack
```

The same item requires `sourceCommit` and `sourceTree` to match
`^[0-9a-f]{40}$`; `resolvedContentDigest`, `validatorIdentity.sha256`, and
`registrationFingerprint` must match `^sha256:[0-9a-f]{64}$`. Values are copied
from the selected Registry entry, not authored independently.

Internal entries in a v2 lock keep their current fields and use
`sourceKind: HARNESS_CANONICAL` only inside the v2 document.

- [ ] **Step 4: Resolve external entries without changing the public return shape**

In `build_capability_lock`, check the internal active catalog first. If absent,
require exactly one active Pack registration and build an external source entry.
Use a combined source revision only for v2:

```python
def capability_lock_v2_source_revision(capabilities: list[dict[str, Any]]) -> str:
    sources = sorted(
        [{key: item[key] for key in _source_identity_keys(item)} for item in capabilities],
        key=lambda item: item["capabilityId"],
    )
    return "content-sha256:" + sha256_bytes(canonical_json_bytes(sources))
```

In `verify_capability_lock`, keep returning `(lock, verified)`. Each verified
external entry includes `sourceKind`, the Registry entry, and manifest data;
internal entries retain the existing Registry shape. Branch verification by
`lock["schemaVersion"]` and never reinterpret a v1 entry as external.

- [ ] **Step 5: Run GREEN and commit**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/test_project_state.py tests/test_lock_enforcement.py
git diff --check
git add core/schemas/capability-lock.schema.json \
  src/evolution_harness/project.py tests/test_project_state.py \
  tests/test_lock_enforcement.py
git commit -m 'feat(lock): 锁定项目采用的外部 Pack 来源' \
  -m '仅在选择外部 Pack 时生成 v2 Lock，并保持内部 v1 Lock 字节和验证接口兼容。'
```

### Task 5: Resolve and project the locked external Skill

**Files:**
- Modify: `core/schemas/runtime-projection-manifest.schema.json`
- Modify: `src/evolution_harness/capability_pack_registry.py`
- Modify: `src/evolution_harness/resolver.py`
- Modify: `src/evolution_harness/projection.py`
- Modify: `tests/test_resolver.py`
- Modify: `tests/test_projection.py`
- Modify: `tests/test_projection_install.py`

**Interfaces:**
- Consumes: verified external entries returned through the unchanged
  `verify_capability_lock()` tuple.
- Produces:
  - `read_registered_pack_blob(registration: Mapping[str, Any], relative_path: str) -> bytes`
  - external `selectedCapabilities` provenance in `resolved-design-context/v1`
  - runtime manifest source/Skill provenance bound to the v2 lock.
- Preserves: automatic install and uninstall apply rejection.

- [ ] **Step 1: Write resolver and projection RED tests**

Add:

```python
def test_resolver_selects_locked_external_pack_without_mutable_checkout_reads(tmp_path: Path):
    root, project, source = _external_pack_project(tmp_path)
    resolved = resolve_design_context(
        root, project, intent="visual-reference-review", topic="web-fidelity",
        requested_output="review findings", runtime="CODEX",
    )
    selected = next(item for item in resolved["selectedCapabilities"] if item["sourceKind"] == "EXTERNAL_CAPABILITY_PACK")
    assert selected["id"] == "workflow:web-high-fidelity:reference-driven-visual-fidelity"
    (source / "skills/web-high-fidelity/SKILL.md").write_text("mutable drift\n", encoding="utf-8")
    assert resolve_design_context(
        root, project, intent="visual-reference-review", topic="web-fidelity",
        requested_output="review findings", runtime="CODEX",
    )["resolutionId"] == resolved["resolutionId"]

def test_projection_snapshots_external_skill_from_locked_git_blob(tmp_path: Path):
    root, project, source = _external_pack_project(tmp_path)
    resolved = _resolve(root, project)
    pack = build_projection_pack(root, project, resolved, runtime="CODEX")
    skill = pack["files"]["skills/web-high-fidelity/SKILL.md"]
    assert skill == _git_bytes(source, "show", f"{_locked_commit(project)}:skills/web-high-fidelity/SKILL.md")
    assert pack["manifest"]["sourceCapabilities"][0]["sourceKind"] == "EXTERNAL_CAPABILITY_PACK"

def test_external_pack_projection_apply_remains_disabled(tmp_path: Path):
    root, project, target = _external_projection_fixture(tmp_path)
    before = _snapshot(target)
    with pytest.raises(ProjectionInstallError, match="automatic projection install is disabled"):
        install_projection(root, _pack_root(root, project), target, apply=True)
    assert _snapshot(target) == before
```

Also reject missing locked blob, Skill path drift, Skill front-matter name drift,
projection manifest/lock provenance mismatch, and registry change after lock.

- [ ] **Step 2: Run RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/test_resolver.py::test_resolver_selects_locked_external_pack_without_mutable_checkout_reads \
  tests/test_projection.py::test_projection_snapshots_external_skill_from_locked_git_blob \
  tests/test_projection_install.py::test_external_pack_projection_apply_remains_disabled
```

Expected: FAIL because resolver and projection treat every verified item as an
internal `asset.yaml`.

- [ ] **Step 3: Read Pack bytes from the locked Git object**

Implement:

```python
def read_registered_pack_blob(registration: Mapping[str, Any], relative_path: str) -> bytes:
    safe_path = validate_relative_pack_path(relative_path)
    source_root = Path(registration["source"]["repositoryPath"])
    commit = registration["source"]["commit"]
    completed = _run_git(source_root, "show", f"{commit}:{safe_path}", text=False)
    return completed.stdout
```

The helper must revalidate commit/tree/registration fingerprint before reading,
reject symlink modes, and never read the mutable working-tree file.

- [ ] **Step 4: Branch resolver handling by source kind**

Keep current `_load_asset()` for internal entries. For external entries, create
the selected item directly from verified registration data:

```python
{
    "id": entry["capabilityId"],
    "kind": "WORKFLOW",
    "version": entry["packVersion"],
    "contentHash": entry["resolvedContentDigest"].removeprefix("sha256:"),
    "sourceKind": "EXTERNAL_CAPABILITY_PACK",
    "sourceRegistrationId": entry["registrationId"],
    "selectedBecause": lock_item["resolvedBecause"],
}
```

Internal selected items omit the new fields so existing resolved-context bytes
remain unchanged.

- [ ] **Step 5: Render one external managed Skill with full provenance**

When an external workflow is selected, read `skillPath` from the locked manifest,
verify front matter `name` equals `skillName`, and generate exactly
`skills/web-high-fidelity/SKILL.md`. Add an external branch to
`sourceCapabilities` and `generatedSkills` requiring source registration,
commit/tree, resolved content digest, validator digest, and Skill blob SHA-256.

Do not render Pack docs/templates into the project and do not modify
`src/evolution_harness/install.py`.

- [ ] **Step 6: Run GREEN and commit**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/test_resolver.py tests/test_projection.py tests/test_projection_install.py
git diff --check
git add core/schemas/runtime-projection-manifest.schema.json \
  src/evolution_harness/capability_pack_registry.py \
  src/evolution_harness/resolver.py src/evolution_harness/projection.py \
  tests/test_resolver.py tests/test_projection.py tests/test_projection_install.py
git commit -m 'feat(projection): 投影锁定的外部 Pack Skill' \
  -m '从固定 Git Blob 解析 Web Skill，绑定 Registry 与项目 Lock 身份，并保持自动安装禁用。'
```

### Task 6: Add the read-only Cognitura sidecar to Candidate A

**Files:**
- Create: `integrations/cognitura-shadow/integration.yaml`
- Create: `integrations/cognitura-shadow/authority-map.yaml`
- Create: `integrations/cognitura-shadow/control-plane/.agent-evolution/design-state.yaml`
- Create: `integrations/cognitura-shadow/control-plane/.agent-evolution/capabilities.yaml`
- Create: `integrations/cognitura-shadow/control-plane/.agent-evolution/capabilities.lock.yaml`
- Create: `integrations/cognitura-shadow/scenarios/non-visual-authority-precedence.yaml`
- Create: `integrations/cognitura-shadow/scenarios/locked-visual-review.yaml`
- Create: `integrations/cognitura-shadow/scenarios/unauthorized-page-completion.yaml`
- Create: `generated/projections/codex/cognitura-shadow/discussion-contract.md`
- Create: `generated/projections/codex/cognitura-shadow/projection-manifest.json`
- Create: `generated/projections/codex/cognitura-shadow/repository-guidance.md`
- Create: `generated/projections/codex/cognitura-shadow/resolved-context.json`
- Create: `generated/projections/codex/cognitura-shadow/resolved-task-context.md`
- Create: `generated/projections/codex/cognitura-shadow/skills/web-high-fidelity/SKILL.md`
- Create: `tests/test_cognitura_integration_fixture.py`
- Modify: `tests/test_integration_e2e.py`
- Modify: `tests/test_project_registration.py`

**Interfaces:**
- Consumes: registered Pack, v2 project lock, and external Skill projection.
- Produces: fixed `cognitura-shadow` lock fingerprint and verified Codex
  projection used read-only by Candidate B.

- [ ] **Step 1: Create a clean detached Cognitura source fixture**

Do not use or modify the dirty Cognitura checkout. Create a temporary clean clone
at its current full commit for Candidate A verification:

```bash
cognitura_source_commit="$(git -C /Users/yuzhuangzhuang/Projects/cognitura rev-parse HEAD)"
cognitura_fixture="$(mktemp -d /tmp/cognitura-pack-source.XXXXXX)"
git clone --shared --no-checkout -q \
  /Users/yuzhuangzhuang/Projects/cognitura "${cognitura_fixture}"
git -C "${cognitura_fixture}" checkout -q --detach "${cognitura_source_commit}"
test -z "$(git -C "${cognitura_fixture}" status --porcelain=v1 --untracked-files=all)"
```

The temporary fixture is test input only and is not recorded as a source path in
the sidecar or project lock.

- [ ] **Step 2: Write sidecar RED tests**

Add tests that assert:

```python
def test_cognitura_shadow_is_read_only_and_locks_web_pack(tmp_path: Path):
    root, source = _copy_cognitura_shadow_fixture(tmp_path)
    loaded = load_integration(root, root / "integrations/cognitura-shadow", source)
    assert loaded["integration"]["sourceAccess"] == "READ_ONLY"
    lock = load_capability_lock(root, loaded["controlPlaneRoot"])
    assert lock["schemaVersion"] == "capability-lock/v2"
    assert lock["capabilities"][0]["capabilityId"] == "workflow:web-high-fidelity:reference-driven-visual-fidelity"

def test_cognitura_shadow_cannot_turn_pack_result_into_page_authorization(tmp_path: Path):
    result = _run_scenario(tmp_path, "unauthorized-page-completion")
    assert result["authorityGate"] == "PASS"
    assert result["facts"]["permission.pageImplementation"] == "DENY"
    assert "PROJECT_TRUTH_WINS" in result["conflictResolutionRules"]
```

Also mutate the Pack digest, validator hash, project lock fingerprint, and
Authority selector to prove each fails closed.

- [ ] **Step 3: Run RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/test_cognitura_integration_fixture.py \
  tests/test_integration_e2e.py \
  tests/test_project_registration.py
```

Expected: FAIL because `cognitura-shadow` does not exist.

- [ ] **Step 4: Implement the minimal sidecar**

Use `project-integration/v1`, `sourceAccess: READ_ONLY`, runtime `CODEX`, and
exclude `.idea/**` from readable paths without treating it as clean evidence.
Map only canonical facts required for adoption:

```text
task.wave2.active
permission.businessImplementation
permission.pageImplementation
permission.realPagePilot
```

Read Wave 2's canonical index for active task and authorization, and the frozen
legacy binding only for its explicit `REAL_PAGE_PILOT=NOT_AUTHORIZED` fact. The
sidecar stage is adoption preparation, not Cognitura delivery status.

The sidecar `capabilities.yaml` explicitly selects only:

```yaml
schemaVersion: project-capability-binding/v1
profiles: []
capabilities:
  - workflow:web-high-fidelity:reference-driven-visual-fidelity
extensions: []
disabledCapabilities: []
```

- [ ] **Step 5: Generate lock and projection from the clean fixture**

Run existing CLI integration lock/resolve/projection commands with the explicit
sidecar path and temporary clean source. Check the generated Pack and dry-run
install plan. Do not pass `--apply` and do not target the live Cognitura path.

- [ ] **Step 6: Run focused GREEN and commit**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/test_cognitura_integration_fixture.py \
  tests/test_integration_e2e.py \
  tests/test_project_registration.py
.venv/bin/harness validate --check-generated --json
git diff --check
git add integrations/cognitura-shadow \
  generated/projections/codex/cognitura-shadow \
  tests/test_cognitura_integration_fixture.py \
  tests/test_integration_e2e.py tests/test_project_registration.py
git commit -m 'feat(integration): 准备 Cognitura 只读 Pack 接入' \
  -m '通过 sidecar 锁定 Web Pack 并生成可复核投影，不写入目标项目或授权页面实现。'
```

## Task 7: Fix and review Candidate A once

**Repositories:**

- `/Users/yuzhuangzhuang/Projects/web-high-fidelity/.worktrees/web-high-fidelity-pack-v2-registration`
- `/Users/yuzhuangzhuang/Projects/omini-harness/.worktrees/web-high-fidelity-pack-cognitura`

- [ ] **Step 1: Audit the exact WriteSets**

For each repository, compare the actual changed paths with Tasks 1 through 6.
Stop on unexplained paths. Do not add a receipt document solely to record this
audit; the candidate identities and command output are the evidence.

- [ ] **Step 2: Run the Pack's final Gate**

Fix the Pack candidate commit first, confirm its tree is clean, then run its
validator with those exact identities:

```bash
pack_candidate_commit="$(git rev-parse HEAD)"
pack_candidate_parent="$(git rev-parse HEAD^)"
pack_candidate_tree="$(git rev-parse HEAD^{tree})"
bash scripts/verify-capability-pack "$pack_candidate_commit" "$pack_candidate_tree"
git diff --check
test -z "$(git status --porcelain)"
```

Expected: PASS, including manifest identity, version, Skill identity, boundary,
mutation suite, clean checkout, and exact commit/tree checks.

- [ ] **Step 3: Run focused Harness tests, then exactly one full regression**

First run the focused tests named in Tasks 2 through 6. After they pass, run the
existing complete Harness regression and generated-output check once:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q
.venv/bin/harness validate --check-generated --json
git diff --check
```

Expected: all tests PASS and generated files match their sources. Do not repeat
the full suite on the same tree merely to obtain a second receipt.

- [ ] **Step 4: Fix the Harness candidate and record immutable identities**

```bash
harness_candidate_commit="$(git rev-parse HEAD)"
harness_candidate_parent="$(git rev-parse HEAD^)"
harness_candidate_tree="$(git rev-parse HEAD^{tree})"
test -z "$(git status --porcelain)"
```

Record the six exact Pack/Harness candidate values in the execution handoff.
They must be full lowercase Git object IDs emitted by the commands above.

- [ ] **Step 5: Request one fixed-candidate independent review**

Use one `deep_reviewer / Sol xhigh` review covering both fixed candidates. Ask
the reviewer to check source provenance, immutable revision/tree/digest,
validator identity, v1 lock compatibility, Skill byte materialization, dirty
checkout handling, project Authority preservation, and the ban on automatic
apply or runtime expansion.

Expected: no P0/P1 and an explicit Candidate A GO. If a P0/P1 is found, fix it,
create a new affected candidate, rerun affected focused tests plus the one final
full Gate required for the changed repository, and request a fresh review. Do
not stack a second reviewer on an unchanged tree.

## Task 8: Perform the authorized Cognitura v2 adoption migration

**Files:**

- Create: `/Users/yuzhuangzhuang/Projects/cognitura/.worktrees/web-high-fidelity-pack-v2-adoption/.agent-evolution/registration.yaml`
- Create: `/Users/yuzhuangzhuang/Projects/cognitura/.worktrees/web-high-fidelity-pack-v2-adoption/.agents/skills/web-high-fidelity/SKILL.md`
- Create: `/Users/yuzhuangzhuang/Projects/cognitura/.worktrees/web-high-fidelity-pack-v2-adoption/docs/engineering/cognitura-web-high-fidelity-capability-pack-v2-adoption.md`
- Create: `/Users/yuzhuangzhuang/Projects/cognitura/.worktrees/web-high-fidelity-pack-v2-adoption/scripts/verify-web-high-fidelity-capability-adoption`
- Create: `/Users/yuzhuangzhuang/Projects/cognitura/.worktrees/web-high-fidelity-pack-v2-adoption/tests/capability-pack/verify-web-high-fidelity-capability-adoption.sh`
- Modify: `/Users/yuzhuangzhuang/Projects/cognitura/.worktrees/web-high-fidelity-pack-v2-adoption/AGENTS.md`
- Modify: `/Users/yuzhuangzhuang/Projects/cognitura/.worktrees/web-high-fidelity-pack-v2-adoption/scripts/verify-wave1-implementation-cards`
- Modify: `/Users/yuzhuangzhuang/Projects/cognitura/.worktrees/web-high-fidelity-pack-v2-adoption/tests/task-cards/verify-wave1-implementation-cards.sh`
- Preserve byte-for-byte: `/Users/yuzhuangzhuang/Projects/cognitura/.worktrees/web-high-fidelity-pack-v2-adoption/docs/engineering/cognitura-high-fidelity-harness-binding.md`

- [ ] **Step 1: Recheck the three hard preconditions**

Do not create the Cognitura worktree until all of these are true:

1. the live Cognitura checkout has no unowned changes, including `.idea/`;
2. W2-D05 is formally closed by Cognitura's existing Authority rather than only
   `READY` for fixed design review; and
3. the user has explicitly authorized Candidate B's R2 adoption WriteSet after
   seeing Candidate A's fixed identities and review result.

If any condition is false, stop Candidate B and report Candidate A as ready;
do not reinterpret Pack readiness as downstream adoption.

- [ ] **Step 2: Create the project-local worktree and freeze legacy bytes**

Use Cognitura's repository-local `.worktrees` convention and a branch from the
then-current authorized Cognitura base:

```bash
git worktree add .worktrees/web-high-fidelity-pack-v2-adoption \
  -b codex/web-high-fidelity-pack-v2-adoption
cd .worktrees/web-high-fidelity-pack-v2-adoption
legacy_binding_sha256="$(shasum -a 256 docs/engineering/cognitura-high-fidelity-harness-binding.md | awk '{print $1}')"
```

Record the base commit/tree and the legacy binding digest before editing.

- [ ] **Step 3: Write focused RED mutation tests**

The new shell behavior test must use temporary Git repositories with real
commits and trees. Add mutations for:

- wrong canonical capability ID;
- wrong source revision or source tree;
- wrong resolved content digest;
- wrong validator identity;
- wrong selected profile;
- missing target-project Authority reference;
- managed Skill bytes differing from the locked Pack blob;
- dirty candidate checkout;
- any byte drift in the frozen legacy binding.

Give each failure one stable machine-readable error code. The existing successor
test must continue to prove `POST_W1_SUCCESSOR_INVALID:binding drift` for the old
binding; do not weaken or replace that check.

- [ ] **Step 4: Run RED**

```bash
bash tests/capability-pack/verify-web-high-fidelity-capability-adoption.sh
bash tests/task-cards/verify-wave1-implementation-cards.sh --contract-only
```

Expected: the new capability-adoption suite FAILS because no v2 registration,
managed Skill, adoption record, or focused validator exists. The existing
successor contract suite remains GREEN before its narrow integration change.

- [ ] **Step 5: Create the exact project adoption record**

Create `.agent-evolution/registration.yaml` from Harness Candidate A's generated
`cognitura-shadow` projection. It must bind the exact Pack capability ID,
revision, tree, resolved content digest, validator identity, selected profile,
managed Skill path/hash, projection manifest hash, and Cognitura Authority
reference. Values that are candidate-dependent must be copied from exact command
output during execution; no symbolic marker may remain in a committed file.

The registration is a project selection and provenance record. It must not
claim task completion, merge permission, release permission, page implementation
authorization, or real-page Pilot authorization.

- [ ] **Step 6: Materialize the managed Skill from the locked blob**

Read `skills/web-high-fidelity/SKILL.md` from the Pack Candidate A Git object,
write those exact bytes to `.agents/skills/web-high-fidelity/SKILL.md`, and prove
its SHA-256 equals both the projection manifest and registration record. Do not
copy from a mutable working-tree path and do not install the Skill globally.

- [ ] **Step 7: Write the v2 migration record**

The new adoption document must state:

- the legacy binding is frozen history, with its pre-edit SHA-256;
- v2 selection lives in `.agent-evolution/registration.yaml`;
- Pack validation is not Cognitura task completion or implementation authority;
- `REAL_PAGE_PILOT=NOT_AUTHORIZED` remains unchanged;
- the fixed Candidate A Pack/Harness identities and Candidate B base identity;
- rollback removes only the v2 registration, managed Skill, focused verifier,
  and narrow routing changes, while preserving legacy history.

Use exact observed values and final declarative text; do not leave unfinished
markers, sample hashes, shell substitutions, or unresolved symbolic values.

- [ ] **Step 8: Implement one focused deterministic verifier**

`scripts/verify-web-high-fidelity-capability-adoption` accepts the expected
Cognitura candidate commit and tree as two positional arguments. It must:

1. verify checkout commit/tree and cleanliness;
2. validate registration shape and exact identities;
3. recompute the Pack content digest from the fixed Pack Git object;
4. run the fixed Pack validator by argv, never arbitrary shell text;
5. compare managed Skill bytes and all declared SHA-256 values;
6. verify the legacy binding SHA-256 is unchanged; and
7. emit a project-scoped adoption result without claiming task, merge, release,
   page implementation, or Pilot authorization.

The verifier must fail closed if the fixed Pack object cannot be read. It must
not fetch from the network, install dependencies, modify a baseline, modify the
Pack/Harness repositories, or execute a Pack-supplied shell string.

- [ ] **Step 9: Add the narrow Authority routing**

Add a concise `AGENTS.md` route telling agents to read the project Authority
first and consult the v2 registration/managed Skill only for adopted Web visual
fidelity work. Do not paste the Pack rules into `AGENTS.md`.

Add exactly one focused call to the new verifier from
`scripts/verify-wave1-implementation-cards`, plus the minimal test/allowlist
adjustment required for its new files. Preserve every existing successor
invariant, especially the frozen binding-drift rejection.

- [ ] **Step 10: Run GREEN and create the implementation commit**

```bash
bash tests/capability-pack/verify-web-high-fidelity-capability-adoption.sh
bash tests/task-cards/verify-wave1-implementation-cards.sh --contract-only
git diff --check
test "$legacy_binding_sha256" = \
  "$(shasum -a 256 docs/engineering/cognitura-high-fidelity-harness-binding.md | awk '{print $1}')"
git add AGENTS.md .agent-evolution/registration.yaml \
  .agents/skills/web-high-fidelity/SKILL.md \
  docs/engineering/cognitura-web-high-fidelity-capability-pack-v2-adoption.md \
  scripts/verify-web-high-fidelity-capability-adoption \
  scripts/verify-wave1-implementation-cards \
  tests/capability-pack/verify-web-high-fidelity-capability-adoption.sh \
  tests/task-cards/verify-wave1-implementation-cards.sh
git commit -m 'feat(capability): 接入 Web High Fidelity Pack v2' \
  -m '绑定固定来源、验证器与受管 Skill，同时保留 Cognitura Authority 和旧绑定历史。'
```

Expected: focused adoption and successor tests PASS, the old binding digest is
identical, and no unrelated Wave, page, browser, build, deployment, or Pilot
behavior is changed.

## Task 9: Fix, validate, and review Candidate B once

**Repository:**

- `/Users/yuzhuangzhuang/Projects/cognitura/.worktrees/web-high-fidelity-pack-v2-adoption`

- [ ] **Step 1: Run only the direct Candidate B gates**

From the Cognitura worktree, run:

```bash
bash tests/capability-pack/verify-web-high-fidelity-capability-adoption.sh
bash tests/task-cards/verify-wave1-implementation-cards.sh --contract-only
git diff --check
```

Also invoke the fixed Harness Candidate A registration check read-only against
the fixed Pack Candidate A object and the Cognitura registration. Do not rerun
the full Harness suite: Candidate A's unchanged tree already owns that evidence.

Do not run unrelated Wave implementation, browser, visual comparison, Java
build, deployment, or real-page Pilot gates. Candidate B changes adoption
provenance and routing only.

- [ ] **Step 2: Fix Candidate B and run its identity-aware verifier**

```bash
cognitura_candidate_commit="$(git rev-parse HEAD)"
cognitura_candidate_parent="$(git rev-parse HEAD^)"
cognitura_candidate_tree="$(git rev-parse HEAD^{tree})"
bash scripts/verify-web-high-fidelity-capability-adoption \
  "$cognitura_candidate_commit" "$cognitura_candidate_tree"
test -z "$(git status --porcelain)"
```

Expected: PASS with exact commit/tree, clean checkout, unchanged legacy binding,
fixed source identities, valid registration, and exact managed Skill bytes.

- [ ] **Step 3: Request one fixed-candidate independent review**

Use one `deep_reviewer / Sol xhigh` review of Candidate B. Ask it to verify the
three preconditions, Exact WriteSet, legacy binding immutability, deterministic
source/validator/Skill identities, project Authority precedence, rollback
boundary, and absence of page/Pilot/task/merge/release authorization expansion.

Expected: no P0/P1 and an explicit Candidate B GO. For P0/P1, fix, create a new
candidate, rerun the two focused suites and identity-aware verifier, then review
the changed candidate once. Judge each P2 explicitly for whether it blocks the
first neutral Pilot; do not dismiss or automatically expand scope for it.

- [ ] **Step 4: Produce the final handoff without merging**

Report separately:

- Pack v2 source candidate, Harness registration candidate, and Cognitura
  adoption candidate: Candidate, Parent, Tree, and clean state;
- focused tests, Pack Gate, one Harness full regression, both independent
  reviews, and any P0/P1/P2 findings;
- Pack readiness, Harness registration, projection availability, Cognitura
  adoption, and real-page Pilot authorization as distinct conclusions;
- no push, release, deploy, global Skill install, automatic apply, or merge;
- whether a neutral Cognitura Pilot may be proposed next under fresh project
  Authority.

Offer local merge choices, but do not merge any candidate automatically.

## Lean Gate budget summary

- Candidate A: focused RED/GREEN while iterating; one Pack final Gate; one
  Harness full regression; one combined `deep_reviewer / Sol xhigh` review.
- Candidate B: two Cognitura-focused suites; one identity-aware verifier; one
  `deep_reviewer / Sol xhigh` review; no repeated Harness full regression.
- Same-tree evidence is reused. A full Gate is rerun only after a material tree,
  scope, Authority, environment, or P0/P1 change.
- No new task-card family, lifecycle state machine, acceptance dossier, plugin
  runtime, automatic projection apply, or real-page implementation is created.
