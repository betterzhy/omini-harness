# Java Engineering Standard Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 Java Pack 的前提下，将固定 `java-engineering-standard` 0.4.0 来源注册到 Harness Capability Pack v2，并生成可验证的中立内部 lock 与 Codex Skill projection。

**Architecture:** 扩展 Candidate A 的 external Pack Contract，使 Registry 可选择 source-tracked 或 Harness-declared manifest。两种模式共用 manifest Schema、Git object 内容选择、固定 Gate、locator-free fingerprint、v2 lock 与 projection 验证链。

**审查修正 WriteSet：** 除各 Task 已列路径外，固定候选深审要求将 Java Skill 从单文件升级为
45 文件自包含资源集，并固定 Java/Javac/Maven home 与只读离线 artifact closure。因此补充修改
`core/schemas/{capability-lock,runtime-projection-manifest}.schema.json`、
`src/evolution_harness/{resolver,projection,install}.py`、`tests/test_projection_install.py` 与生成投影
目录。第二个 ACTIVE registration 暴露既有 Web-only 测试对完整 Registry 的隐式依赖，故
`tests/capability_pack_test_support.py`、`tests/test_{assurance_cli,cognitura_integration_fixture,e2e,registry_catalog_compat}.py`
仅做 fixture 隔离；`tests/test_{lock_enforcement,project_state,resolver,projection}.py` 对 lock 所引用
registration 做选择性验证。该依赖链不改变 Java Pack、Cognitura 或任何真实项目。

**Tech Stack:** Python 3.12、PyYAML、jsonschema、pytest、Git object plumbing、YAML/JSON deterministic generation。

**Spec:** `docs/superpowers/specs/2026-08-27-java-engineering-standard-registration-design.md`

## Global Constraints

- Harness 起点固定为 `050c58c7b6e8786e653bc5e60f9ad5b26dc01820`。
- 不修改 `/Users/yuzhuangzhuang/Projects/java-engineering-standard`。
- 不修改现有 Web Pack worktree，不改变 Web source-tracked manifest 行为。
- locator 不进入 canonical registration fingerprint、v2 lock source revision 或 projection identity。
- 不合并 main，不 push、发布、部署、安装 Skill 或接入真实项目。
- 所有行为修改执行 RED → GREEN；完整回归只在候选稳定后运行一次。

---

### Task 1: Harness-declared manifest Contract

**Files:**
- Modify: `core/schemas/capability-pack-registration.schema.json`
- Modify: `src/evolution_harness/capability_pack_registry.py`
- Modify: `src/evolution_harness/project.py`
- Modify: `tests/test_capability_pack_registry.py`
- Modify: `tests/test_project_state.py`

**Interfaces:**
- Consumes: Candidate A `capability-pack/v1` manifest Schema and external registration validator.
- Produces: `contentDeclaration.kind`, unified resolved manifest, locator-free canonical registry revision.

- [ ] **Step 1: Write failing tests**

Add literal registrations using `HARNESS_DECLARED_MANIFEST`; assert a fixed Java-like Git repo without
`capability-pack.yaml` registers, while identity/version/Skill path/content-selection drift fails.
Add a relocation test asserting registry `sourceRevision`, v2 lock and lock fingerprint remain byte-identical.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/test_capability_pack_registry.py \
  tests/test_project_state.py
```

Expected: new tests fail because the current Schema rejects `contentDeclaration` and the loader requires
`capability-pack.yaml`.

- [ ] **Step 3: Implement minimal Contract**

Extend the registration Schema with a strict `oneOf` for:

```yaml
contentDeclaration:
  kind: SOURCE_TRACKED_MANIFEST
  path: capability-pack.yaml
```

or:

```yaml
contentDeclaration:
  kind: HARNESS_DECLARED_MANIFEST
  manifest: <capability-pack/v1 object>
```

Implement one manifest resolver and ensure the canonical identity record excludes only
`source.repositoryPath`, while including `contentDeclaration`.

- [ ] **Step 4: Verify GREEN and compatibility**

Run the Task 1 command and confirm Web source-tracked tests plus new Java-like tests pass.

- [ ] **Step 5: Commit**

```bash
git add core/schemas/capability-pack-registration.schema.json \
  src/evolution_harness/capability_pack_registry.py \
  src/evolution_harness/project.py \
  tests/test_capability_pack_registry.py \
  tests/test_project_state.py
git commit -m "feat(registry)!: 支持 Harness 声明的外部 Pack 内容契约"
```

### Task 2: Register fixed Java Pack and close drift matrix

**Files:**
- Modify: `core/registries/capability-packs.yaml`
- Modify: `generated/registries/capability-pack-registry.json`
- Modify: `tests/test_capability_pack_registry.py`
- Modify: `tests/test_lock_enforcement.py`
- Modify: `tests/test_resolver.py`
- Modify: `tests/test_projection.py`

**Interfaces:**
- Consumes: Task 1 manifest resolver and live Java fixed Commit/Tree/Gate.
- Produces: active `pack:java-engineering-standard` registration with immutable identities.

- [ ] **Step 1: Write failing real-source and mutation tests**

Assert the live fixed Java source registers with
`framework:java:java-engineering-standard@0.4.0`; add commit/tree/content/validator drift,
dirty checkout, locator relocation, symlink and TOCTOU cases using temporary real Git repositories.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/test_capability_pack_registry.py \
  tests/test_lock_enforcement.py \
  tests/test_resolver.py \
  tests/test_projection.py
```

Expected: Java lookup fails before the Registry entry and generated Registry exist.

- [ ] **Step 3: Add exact registration and generated Registry**

Append the fixed Java registration, compute content and validator SHA-256 from fixed Git blobs, run its
fixed candidate Gate, and regenerate only `generated/registries/capability-pack-registry.json`.

- [ ] **Step 4: Verify GREEN**

Run the Task 2 focused command and verify both Web and Java registrations fail closed under mutations.

- [ ] **Step 5: Commit**

```bash
git add core/registries/capability-packs.yaml \
  generated/registries/capability-pack-registry.json \
  tests/test_capability_pack_registry.py \
  tests/test_lock_enforcement.py tests/test_resolver.py tests/test_projection.py
git commit -m "feat(registry)!: 注册 Java Engineering Capability Pack"
```

### Task 3: Neutral lock and projection fixture

**Files:**
- Create: `examples/java-engineering-standard-registration-fixture/.agent-evolution/design-state.yaml`
- Create: `examples/java-engineering-standard-registration-fixture/.agent-evolution/capabilities.yaml`
- Create: `examples/java-engineering-standard-registration-fixture/.agent-evolution/capabilities.lock.yaml`
- Create: `generated/projections/codex/java-engineering-standard-registration-fixture/**`
- Create: `tests/test_java_engineering_standard_registration_fixture.py`

**Interfaces:**
- Consumes: Task 2 active external registration.
- Produces: reproducible v2 lock and Codex projection with byte-identical Java Skill.

- [ ] **Step 1: Write failing fixture test**

Assert the fixture selects only the Java external capability, the v2 lock matches Registry identity,
the projection manifest repeats lock provenance, projected Skill bytes equal the fixed Git blob, and no
real-project adoption or completion facts exist.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/test_java_engineering_standard_registration_fixture.py
```

Expected: fixture paths are missing.

- [ ] **Step 3: Build fixture, lock and projection**

Use the existing Harness builders to generate the v2 lock and Codex projection; do not hand-edit
fingerprints, digests or projection bytes.

- [ ] **Step 4: Verify GREEN**

Run the Task 3 test and the focused projection/lock suites.

- [ ] **Step 5: Commit**

```bash
git add examples/java-engineering-standard-registration-fixture \
  generated/projections/codex/java-engineering-standard-registration-fixture \
  tests/test_java_engineering_standard_registration_fixture.py
git commit -m "test(projection)!: 固定 Java Pack 中立投影证据"
```

### Task 4: Fixed candidate verification and review

**Files:**
- Modify only files required to close a reproduced P0/P1 finding.

**Interfaces:**
- Consumes: stable implementation tree.
- Produces: fixed Candidate/Parent/Tree and independent review report.

- [ ] **Step 1: Run focused regression**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/test_capability_pack_registry.py \
  tests/test_project_state.py \
  tests/test_lock_enforcement.py \
  tests/test_resolver.py \
  tests/test_projection.py \
  tests/test_projection_install.py \
  tests/test_java_engineering_standard_registration_fixture.py
```

- [ ] **Step 2: Run Java fixed candidate Gate once**

```bash
bash /Users/yuzhuangzhuang/Projects/java-engineering-standard/scripts/verify-capability-pack \
  765e9d00a3173ecfe873c1646f5dbe375de677e7 \
  d79644b05149419feba8cdd7860b7dbbb48e4961
```

- [ ] **Step 3: Run one complete Harness regression and static checks**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q
git diff --check 050c58c7b6e8786e653bc5e60f9ad5b26dc01820..HEAD
git status --short
```

- [ ] **Step 4: Fix candidate identity**

Record:

```bash
git rev-parse HEAD
git rev-parse HEAD^
git rev-parse HEAD^{tree}
```

- [ ] **Step 5: Dispatch one `deep_reviewer / xhigh`**

Review the exact Parent..Candidate range read-only. Fix P0/P1 through a new RED/GREEN cycle, rerun only
affected focused tests plus the final required gates, then request a fresh review of the new fixed candidate.
Stop after a review with P0/P1 closed; do not merge main.
