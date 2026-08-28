# Java Engineering Capability Pack

本仓库提供可组合的 Java 工程规则、Profile、Baseline、机器 Contract、确定性 Runner、选择性模板、Java Engineering Skill 和自验证 Gate。它是 Java Engineering Capability Pack，不是跨项目 Harness、项目 Authority、采用控制面、Task/Stage 裁决器或发布授权器。

```text
PROJECT_PACK_NAME=java-engineering-standard
SKILL_NAME=java-engineering-standard
DISPLAY_NAME=Java Engineering Capability Pack
CANONICAL_CAPABILITY_ID=framework:java:java-engineering-standard
CANONICAL_CAPABILITY_ID_OWNER=omini-harness
REGISTRATION_STATUS=REGISTERED
```

项目目录、Pack 机器名与 Skill 名保持一致。正式注册只建立稳定能力身份，不表示任何下游项目已采用、安装或投影本 Pack；`java-spec` 只保留为 0.4.0 Schema、Adapter、质量输出路径、CI 变量和历史材料的兼容协议命名空间。

- 当前规范版本：`0.4.0`
- 活动通用基线：`java21-maven3`
- 活动 Spring 基线：`java21-spring35-maven3`
- 默认建议：新业务应用采用 Modular Monolith（模块化单体）
- 语言：中文为主；`Domain`、`Port`、`Adapter`、`Bounded Context`、`Aggregate`、`Contract` 等常用术语保留英文，首次出现附中文解释

## Authority 与阅读顺序

```text
downstream AGENTS.md and business/contract Authority
-> downstream java-project-profile.yaml
-> downstream code-quality.yaml and java-quality-evidence.yaml
-> JAVA-DEVELOPMENT-STANDARD.md at locked version/commit
-> selected baseline inheritance and compatibility matrix
-> selected profiles/*.md
-> exception policy and valid exception records
-> module boundaries, evidence map and project-owned candidate receipts
```

对应入口：

1. 阅读唯一规则正文 [JAVA-DEVELOPMENT-STANDARD.md](JAVA-DEVELOPMENT-STANDARD.md)。
2. 从 [兼容矩阵](compatibility/baseline-matrix.yaml) 选择 Profile 兼容的基线。
3. 纯 Java 项目从 [java21-maven3](baselines/java21-maven3.yaml) 解析工具链；Spring 项目再叠加 [java21-spring35-maven3](baselines/java21-spring35-maven3.yaml)。
4. 选择一个主 Profile，必要时叠加与真实职责相符的附加 Profile。
5. Java Project Profile 选择规范版本、Profile 与 Baseline；Quality Config 固定 Runner commit/path/SHA，禁止引用浮动 `main` 作为 Runner 身份。

精确版本以 `VERSION`、活动 `baselines/*.yaml` 和兼容矩阵为准。README、示例、外部网页和 Skill 不是版本 Authority。

## Project Profile

| Profile | 推荐基线 | 使用场景 | 入口 |
| --- | --- | --- | --- |
| Library | `java21-maven3` | 可被多个项目复用的 Java 库；确有 Spring 集成时可选 Spring 基线 | [library](profiles/library.md) |
| Modular Monolith | `java21-spring35-maven3` | 有清晰业务模块、默认单一部署单元的新业务应用；推荐默认值 | [modular-monolith](profiles/modular-monolith.md) |
| Microservice | `java21-spring35-maven3` | 已证明需要独立部署、演进、隔离或扩缩容的服务 | [microservice](profiles/microservice.md) |
| Batch | 按实现选择 | 大批量、长时间、可分片且需要中断恢复的任务 | [batch](profiles/batch.md) |

Profile 只增加项目类型约束，不能复制或放宽主规范。项目版本差异通过 Java Project Profile、项目基线或兼容矩阵表达。

## 服务内部模块划分

项目必须分别识别以下维度，禁止由 Artifact Id、包名或部署名推断业务 Owner：

- Bounded Context / Fact Owner：业务事实解释权与写权；
- Maven Module：编译、依赖和制品边界；
- Runtime Assembly：启动、配置和依赖注入；
- Storage Role：表、Migration 和本地事务写入责任；
- Adapter Surface：HTTP、消息、数据库和第三方 SDK 边缘。

小型单 Context 项目可以在单 Maven Module 中使用公开 `contract` 与 `internal` 包。中大型项目只有在存在编译隔离、独立 Contract、可选 Adapter、独立维护或现实运行需求时才物理拆分模块。完整规则见 `ARCH-021..030` 和 `MOD-013..018`；机器登记使用 [模块边界模板](templates/module-boundaries.yaml)。

## 下游项目接入

1. 复制 [Java Project Profile](templates/java-project-profile.yaml) 并参考其 [说明](templates/java-project-profile.md)，选择规范版本、Profile、Baseline、模块边界和质量配置路径。该文件不是项目采用 Authority。
2. 复制并填写 [模块边界登记](templates/module-boundaries.yaml)，明确稳定 Fact 标识及唯一 Owner、发布 Contract、模块角色、公开包、允许依赖、结构化禁止依赖、Runtime Module、Runtime Assembly、Storage Role 和 Adapter Surface；所有引用必须解析到唯一登记 Id，角色、方向、Context、可写资源与装配清单必须双向一致。
3. 按实际项目吸收 [参考 Parent POM](templates/maven/reference-parent-pom.xml)；纯 Java Library 不应无条件导入 Spring BOM。
4. 使用 [Wrapper 属性模板](templates/maven/maven-wrapper.properties) 生成并提交项目自己的 `mvnw`、`mvnw.cmd` 与 `.mvn/wrapper/**`；分发 URL/SHA-256 证明下载完整性，`mvnw` 还必须匹配活动基线的原始字节 SHA-256，`mvnw.cmd` 的全 LF 或全 CRLF 表示必须匹配同一个 canonical-LF SHA-256。
5. 在下游模块以 `test` Scope 直接声明 `archunit`、`archunit-junit5-api` 和 `archunit-junit5-engine`，复制 [ArchUnit 示例](templates/tests/ArchitectureRulesTest.java)，替换全部模板变量并与模块登记保持一致；替换后先执行项目格式化命令，再执行 `clean verify`。测试引擎由 JUnit Platform 通过 `ServiceLoader` 发现，参考 Parent 已只对该依赖登记 `analyze-only` 例外。
6. 复制 [代码质量配置](templates/code-quality.yaml)，新项目使用 `strict`，已有质量债务的存量项目才使用 `ratchet`；三类 Runner 都必须锁定同一个 `java-engineering-standard` Commit、固定相对路径和 SHA-256。
7. 从 [Java Quality Evidence](templates/java-quality-evidence.yaml) 的 `MISSING_EVIDENCE` 安全初态开始，并参考 [说明](templates/java-quality-evidence.md) 绑定真实 Commit、Tree、配置 Hash、工具输出和逐 Module 报告。禁止填写伪造 Hash。
8. 按代码托管平台吸收 [Java 21 GitHub Actions 模板](templates/ci/github-actions-java21.yml)，替换固定 `java-engineering-standard` Repository/Commit 占位值，保持最小权限、完整 Action SHA、固定 OS 家族标签并记录托管 Runner 的实际镜像版本。模板中的 `JAVA_SPEC_*` 变量是 0.4.0 兼容接口，本次不改名。
9. 架构或工具链决策使用 [ADR 模板](templates/adr.md)；基线升级使用 [基线升级模板](templates/baseline-upgrade.md)。

`0.4.0` 的 [例外策略](policies/exception-policy.yaml) 为默认拒绝且 `eligibleRules` 为空，因此当前禁止创建有效例外。[例外模板](templates/standard-exception.yaml) 只保留未来受控开放能力。

### 完整质量 Job

- `strict` 是新项目默认值：所有 Source Module 都执行 Maven Gate、Source Layout Verifier 和三工具 Finding Adapter，不生成质量债务基线。
- `ratchet` 只用于已有债务的存量项目：与 `strict` 执行相同的 Source Layout/Adapter 路径，随后才对 Checkstyle/PMD 执行只读 Baseline Delta；普通 CI 禁止自动生成、改写或扩大基线。
- 每个 `qualityRole=source` 的 Module 必须分别登记 Effective POM 与 Checkstyle、PMD、SpotBugs 原始报告；Aggregator Module 不得伪造聚合报告代替逐 Module 证据。
- `java21-maven3` / `0.4.0` 只支持完整 Reactor 不含 Generated Source 的项目；每个 Module 的 `generatedSources` 必须显式为空。存在 Generated Source 的项目必须得到 `JAVA_QUALITY_RESULT=MISSING_EVIDENCE`，不能得到 `VALID`。仓库内保留的 dormant rebuild implementation 和历史测试不是生产合规入口。
- 固定 Trust Seam 必须在首次 Maven 进程前拒绝非空 `generatedSources`；按原始字节验真 `mvnw`，按 canonical-LF 内容验真 `mvnw.cmd` 并拒绝 lone CR、混合行尾或语义漂移；从实际 root/raw POM 递归发现完整 Reactor，与 `reactorModules` 精确对账，再拒绝每个已发现 Module 中的 `.mvn/maven.config`、`.mvn/jvm.config`、`.mvn/extensions.xml`。
- 下游 Workflow 只执行从固定 `java-engineering-standard` Commit 经 `git show`、私有临时文件和 SHA-256 先验真的 Runner；项目仓库同名脚本不构成信任根。

Maven `clean verify` 成功只证明该构建生命周期成功，不单独证明代码质量合规。只有 suppression 扫描、完整 Reactor/Source Root 对账、逐 Module 原始报告、归一化结果和适用模式的 Baseline Delta 全部绑定真实 Commit/Tree，才可得到 `JAVA_QUALITY_RESULT=VALID`。该结果仍不替代业务 Authority、Contract Review、Task 完成、合入、发布或运行时验收。

## 机器治理工件

| 工件 | 职责 |
| --- | --- |
| `compatibility/baseline-matrix.yaml` | Profile 与基线兼容关系 |
| `schemas/java-project-profile.schema.json` | 项目选择的 Java Profile、Baseline 和输入路径 |
| `schemas/code-quality.schema.json` | Reactor、Source Set、Strict/Ratchet 和 Runner trust 配置 |
| `schemas/java-quality-evidence.schema.json` | 真实候选、工具、报告和检查结果 |
| `policies/exception-policy.yaml` | 例外资格、期限和到期策略 |
| `registries/rule-evidence-map.yaml` | 规则族默认证据、关键规则专项证据及三个 Contract 的职责引用 |
| `scripts/validate-standard.rb` | 控制库版本、基线、Profile、规则、POM、Wrapper、CI、Schema 嵌套结构、模块跨引用和链接统一验证 |
| `scripts/test_validate_standard.rb` | 验证器成功与拒绝行为测试 |
| [`docs/07-CAPABILITY-PACK-BOUNDARY.md`](docs/07-CAPABILITY-PACK-BOUNDARY.md) | java-engineering-standard、目标项目与 omini/caller 的职责边界 |
| `scripts/verify-capability-pack` | 绑定 Commit/Tree、完整回归、执行面审计和清洁度重核验的固定候选 Gate |

控制库本地验证命令：

```bash
ruby scripts/test_validate_standard.rb
ruby scripts/test_verify_source_layout.rb
ruby scripts/test_normalize_quality_findings.rb
ruby scripts/test_quality_baseline.rb
ruby scripts/test_java_quality_gate.rb
ruby scripts/test_verify_capability_pack.rb
ruby scripts/validate-standard.rb
git diff --check
```

固定本地候选在工作树干净后使用：

```bash
bash scripts/verify-capability-pack "$(git rev-parse HEAD)" "$(git rev-parse HEAD^{tree})"
```

Gate 不联网，也不下载 Maven 或依赖；运行前必须由调用环境预置 Baseline 固定的 Maven Wrapper distribution 和完整离线依赖缓存。缓存缺失会得到 `CAPABILITY_PACK_OFFLINE_MAVEN_CACHE_MISSING` 或 Maven offline failure，而不是回退到网络。测试专用环境变量不能缩短正式 Gate。

## Agent 工作流与 Skill 建议

当前仓库级入口由 [`skills/java-engineering-standard/SKILL.md`](skills/java-engineering-standard/SKILL.md) 提供。它先读取项目 Authority 和采用状态，只加载选中的 Profile 与相关规则族，并分别输出规则适用性、Java 质量结果和 `AUTHORIZATION=PROJECT_OWNED|NOT_EVALUATED`。普通 Java/Spring/Maven 关键词不会自动把项目置于本 Pack 治理；Skill 文件存在不表示已经全局安装或被下游采用。

可按需评估以下外部 Skill；本仓库不自动安装：

| 建议 | 适用方向 | 使用边界 |
| --- | --- | --- |
| `github/awesome-copilot@java-springboot` | Java/Spring Boot 实现与 Review 提示 | 只作框架实践辅助，版本必须服从活动基线 |
| `github/awesome-copilot@create-spring-boot-java-project` | 新建 Spring Boot 项目步骤 | 当前候选默认 Boot 3.4.5 并捆绑多种基础设施；只能提取步骤，必须改用活动基线并删除无业务证据的依赖、默认凭证和容器 |
| `mattpocock/skills@domain-modeling` | Domain 建模讨论 | 不得代替项目 Fact Owner 和业务 Authority |
| `obra/superpowers@test-driven-development` | RED→GREEN 实施 | 与主规范 TEST/DEL 规则共同使用 |
| `obra/superpowers@systematic-debugging` | 缺陷根因分析 | 不允许通过放宽测试掩盖失败 |
| `obra/superpowers@verification-before-completion` | 完成前证据核验 | 当前 Candidate 证据优先于历史结果 |
| `obra/superpowers@requesting-code-review` | 稳定候选 Review | Review 不自动授权发布、部署或 Push |

采用外部 Skill 前必须记录不可变版本或 Commit、许可证、能力、所需权限、采用规则和复核日期。候选来源和采用限制见 [外部来源登记](sources/reference-register.md)。安装量、Star、排名和示例不是 Authority。

## 环境与版本边界

通用基线固定 Java release 21 和 Maven Wrapper 3.9.16。本机已有 Eclipse Temurin `21.0.7+6` 仅作为到 `2026-12-31` 的短期过渡环境；CI/发布验证目标为 Eclipse Temurin `21.0.12.1+1`。

Spring 增量基线固定 Spring Boot BOM `3.5.16`，其管理 Spring Framework `6.2.19`；Spring Modulith 默认关闭，采用时固定 Boot 3.5 兼容线 `1.4.12`。Spring Cloud 默认关闭；确需启用时采用 `2025.0` Release Train 并由下游固定具体补丁。

Java 25、Spring Boot 4、Maven 4 和 JUnit 6 必须另建基线验证，不得混入当前 Java 21 活动基线。版本迁移和已知差异见 [变更记录](CHANGELOG.md)。

## 验证与操作边界

- 控制库验证器证明 Markdown/YAML/JSON/XML、版本继承、规则与实际证据绑定、模块角色和 Surface 语义、Wrapper、Action SHA 和链接等静态结构一致。
- 控制库 Java Fixture 只证明锁定工具和通用失败路径可执行；控制库静态绿色或 Fixture Maven 成功都不等于下游项目质量合规、Spring 启动、数据库、消息或业务运行时通过。
- 下游项目必须使用自己的 Wrapper、依赖、基础设施和测试完成验收，并把 Java Quality Evidence 绑定真实 Commit/Tree；项目自己的 Workflow 决定工作区、阶段关闭、合入和发布门禁。
- 本仓库只创建本地 Commit；禁止自动 `git push`，也不发布 Maven 制品、不部署、不修改其他项目。
- 首版背景见 [0.1.0 设计](docs/superpowers/specs/2026-08-23-java-development-standards-control-design.md)；前次升级见 [0.2.0 设计](docs/superpowers/specs/2026-08-24-java-standard-v0.2-upgrade-design.md)，当前代码质量治理见 [0.3.0 设计](docs/superpowers/specs/2026-08-25-java-coding-quality-governance-design.md)，当前改造见 [0.4.0 设计](docs/superpowers/specs/2026-08-26-java-capability-pack-v0.4-design.md)。
