# Java Engineering Standard 外部 Pack 注册设计

## 目标与边界

本 Slice 在 Harness Candidate A `050c58c7b6e8786e653bc5e60f9ad5b26dc01820`
之上注册 `java-engineering-standard` 0.4.0，并停在独立 Harness worktree
中的固定候选审查完成状态。

本 Slice 不修改 Java Pack，不修改现有 Web Pack worktree，不接入真实项目，不合并
Harness `main`，不 push、发布、部署或安装 Skill。Java 来源仓库中的
`CANONICAL_CAPABILITY_ID=UNASSIGNED` 与 `REGISTRATION_STATUS=NOT_REGISTERED`
继续描述尚未进入 Harness `main` 的来源镜像；本候选内的 Harness Registry 是待合入的
注册事实，不能反向宣称 `main` 已注册。

## 注册身份

Harness 分配以下唯一身份：

```text
registrationId=pack:java-engineering-standard
capabilityId=framework:java:java-engineering-standard
packVersion=0.4.0
status=ACTIVE
distributionStatus=LOCAL_ONLY
```

来源不可变身份固定为来源仓库实时验证后的 Commit、Tree、选定内容 digest 和 validator
identity。`source.repositoryPath` 仅用于本地发现和读取 Git objects，不进入 registration
fingerprint、v2 lock fingerprint、source revision 或 projection provenance。

## Harness-declared manifest

Candidate A 要求来源 tree 内存在 `capability-pack.yaml`。Java 0.4.0 已完成 Contract
Split、Skill、Eval 与固定候选 Gate，但固定 tree 没有该文件；本 Slice 又禁止写 Java
仓库。因此注册 Contract 增加两种互斥声明方式：

- `SOURCE_TRACKED_MANIFEST`：保持 Web Pack 现有行为，从固定 tree 的
  `capability-pack.yaml` 读取 manifest。
- `HARNESS_DECLARED_MANIFEST`：Registry 内嵌一个完整 `capability-pack/v1`
  manifest，并使用同一 manifest Schema 校验。

内嵌 manifest 是 Harness 注册身份，不伪装成来源文件。它必须进入 canonical
registration record；任一字段变化都会移动 registration fingerprint、v2 lock source
revision 和 projection provenance。locator 变化不会移动这些身份。

Java manifest 固定 Pack/Skill/显示名、Capability ID、0.4.0、Skill 路径、Gate argv
Contract，以及以下活动内容选择：

```text
AGENTS.md
README.md
JAVA-DEVELOPMENT-STANDARD.md
VERSION
baselines/
compatibility/
config/
docs/07-CAPABILITY-PACK-BOUNDARY.md
policies/
profiles/
registries/
schemas/
skills/
sources/
templates/
```

Validator `scripts/verify-capability-pack` 单独以 executable Git blob 和 SHA-256 绑定。
测试、历史、迁移、设计计划和 fixture 不进入运行内容 digest；Gate 仍在固定隔离 checkout
中执行并自行覆盖这些验证面。

## 验证链

Registry 验证统一执行：

1. 校验 registration 与 manifest Schema。
2. 解析绝对、规范化、非 symlink locator。
3. 核对 HEAD Commit/Tree、cleanliness 和 hidden index flags。
4. 从固定 commit tree 选择 regular blobs，拒绝 unsafe path、symlink、submodule、
   Unicode normalization/case-fold collision 及活动范围内未跟踪内容。
5. 核对 content digest 与 validator Git blob digest。
6. 将固定 Git object closure 打包到隔离 checkout，执行固定 Gate argv Contract。
7. Gate 后重新核对 validator bytes、Commit/Tree、cleanliness 和 index flags。
8. 生成 locator-free Registry revision、v2 lock、resolved context 与 projection manifest。
9. 从固定 Skill Git blob生成投影，并核对源 blob SHA-256、投影文件 bytes 和 manifest。

`read_registered_pack_blob`、lock verification、projection build/validate 都通过同一 manifest
resolver，禁止后续阶段退回到 locator 上的可变文件系统内容。

## 中立内部 fixture

新增 `examples/java-engineering-standard-registration-fixture`，只用于证明 Registry →
v2 lock → resolved context → Codex projection 的闭环。它不代表任何真实 Java 项目采用，
不包含业务 Authority、Profile 选择、构建命令或项目完成状态。

投影包含 Harness 声明活动范围内的 45 个固定来源 blob，以来源 Skill 为入口并保留相对资源
结构；manifest 记录逐文件 sourcePath/SHA-256 与资源集 digest。入口
`skills/java-engineering-standard/SKILL.md` 必须与固定来源 commit 中同路径 blob 字节相同，
且 `skillBlobSha256` 必须一致。

## 负向矩阵

除复用 Candidate A 已有的 dirty checkout、commit/tree/digest/validator drift、locator
relocation、symlink、hidden index 与 TOCTOU 测试外，新增：

- Harness-declared manifest identity/version/Skill path/content selection drift；
- 声明活动路径缺失或为 symlink/submodule；
- Java source commit/tree/content digest/validator identity drift；
- locator relocation 保持 Registry canonical revision、lock 和 projection identity；
- blob 读取、pre-swap 与 post-swap 线性化点的 Java source drift；
- 投影 Skill bytes、front matter name、manifest provenance 与目标 symlink drift。

## Exact WriteSet

设计与计划：

- `docs/superpowers/specs/2026-08-27-java-engineering-standard-registration-design.md`
- `docs/superpowers/plans/2026-08-27-java-engineering-standard-registration.md`

Contract、实现与注册：

- `core/schemas/capability-pack-registration.schema.json`
- `core/registries/capability-packs.yaml`
- `src/evolution_harness/capability_pack_registry.py`
- `src/evolution_harness/project.py`
- `generated/registries/capability-pack-registry.json`

中立 fixture 与生成投影：

- `examples/java-engineering-standard-registration-fixture/.agent-evolution/design-state.yaml`
- `examples/java-engineering-standard-registration-fixture/.agent-evolution/capabilities.yaml`
- `examples/java-engineering-standard-registration-fixture/.agent-evolution/capabilities.lock.yaml`
- `generated/projections/codex/java-engineering-standard-registration-fixture/**`

测试：

- `tests/capability_pack_test_support.py`
- `tests/test_assurance_cli.py`
- `tests/test_capability_pack_registry.py`
- `tests/test_cognitura_integration_fixture.py`
- `tests/test_e2e.py`
- `tests/test_project_state.py`
- `tests/test_lock_enforcement.py`
- `tests/test_resolver.py`
- `tests/test_projection.py`
- `tests/test_projection_install.py`
- `tests/test_registry_catalog_compat.py`
- `tests/test_java_engineering_standard_registration_fixture.py`

补充 Contract/运行时写集：

- `core/schemas/capability-lock.schema.json`：lock 必须携带完整 validator/toolchain identity。
- `core/schemas/runtime-projection-manifest.schema.json`：投影必须声明完整资源集与目录身份。
- `src/evolution_harness/resolver.py`：外部 Framework 的 kind 必须来自 capability ID，而非 Web 特例。
- `src/evolution_harness/projection.py`：原先单 `SKILL.md` 投影不能满足 Java Skill 的自包含引用。
- `src/evolution_harness/install.py`：dry-run 必须覆盖完整 Skill 目录而非单文件。

测试扩大依赖链：Harness 新增第二个 ACTIVE 外部 Pack 后，既有测试把完整 Registry 复制到
临时仓库，或以 Web-only lock 触发全 Registry 校验，产生与被测语义无关的 Java locator/Gate
依赖；因此 test support、Cognitura、CLI、E2E、catalog/lock/resolver/projection 测试必须显式
隔离 fixture registration 或选择性校验 lock 引用的 registration。所有 45 个生成资源均落在
既有 `generated/projections/.../**` 范围。目录级 Java/Maven/离线仓库身份及超时进程组负测
直接位于 Registry 测试中，不新增外部采用面。

## 完成条件

完成需要 Java 固定 Gate PASS、Harness 聚焦回归 PASS、一次完整 Harness 回归 PASS、生成
工件可复现、`git diff --check` PASS、固定 Candidate/Parent/Tree、干净工作树，以及一次
`deep_reviewer / xhigh` 对固定候选给出无 P0/P1 的结论。停止时不合并 `main`。
