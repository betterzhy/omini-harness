# Java 基线升级记录

> 本模板用于提出、试用和批准新的活动基线。基线文件、兼容矩阵和当前候选证据共同构成升级依据；外部最新版本本身不是升级授权。

## 1. 身份

| 字段 | 内容 |
| --- | --- |
| 升级 Id | `__UPGRADE_ID__` |
| 当前基线 | `__CURRENT_BASELINE_ID__` |
| 候选基线 | `__CANDIDATE_BASELINE_ID__` |
| 目标规范版本 | `__TARGET_STANDARD_VERSION__` |
| Owner | `__UPGRADE_OWNER__` |
| 提出日期 | `__PROPOSED_DATE__` |
| 目标复核日期 | `__REVIEW_DATE__` |

## 2. 来源与差异

- 官方来源版本、发布日期和不可变身份：`__OFFICIAL_SOURCE_IDENTITIES__`
- 许可证或使用条款变化：`__LICENSE_OR_TERMS_CHANGES__`
- JDK/Maven/Spring/Plugin 精确差异：`__TOOLCHAIN_DIFF__`
- 配置、默认值、废弃与移除项：`__CONFIG_DEPRECATION_DIFF__`
- 安全修复与已知风险：`__SECURITY_DIFF__`

## 3. Profile 兼容矩阵

| Profile | 兼容结论 | 所需迁移 | 证据 |
| --- | --- | --- | --- |
| `library` | `__LIBRARY_COMPATIBILITY__` | `__LIBRARY_MIGRATION__` | `__LIBRARY_EVIDENCE__` |
| `batch` | `__BATCH_COMPATIBILITY__` | `__BATCH_MIGRATION__` | `__BATCH_EVIDENCE__` |
| `modular-monolith` | `__MODULAR_COMPATIBILITY__` | `__MODULAR_MIGRATION__` | `__MODULAR_EVIDENCE__` |
| `microservice` | `__MICROSERVICE_COMPATIBILITY__` | `__MICROSERVICE_MIGRATION__` | `__MICROSERVICE_EVIDENCE__` |

## 4. 验证

| 检查 | 命令/环境 | 预期 | 实际证据 |
| --- | --- | --- | --- |
| 依赖树与收敛 | `__DEPENDENCY_TREE_COMMAND__` | `__DEPENDENCY_EXPECTED__` | `__DEPENDENCY_EVIDENCE__` |
| 编译与静态分析 | `__COMPILE_COMMAND__` | `__COMPILE_EXPECTED__` | `__COMPILE_EVIDENCE__` |
| 单元/组件/架构测试 | `__FOCUSED_TEST_COMMAND__` | `__FOCUSED_EXPECTED__` | `__FOCUSED_EVIDENCE__` |
| 集成/Contract/基础设施测试 | `__INTEGRATION_COMMAND__` | `__INTEGRATION_EXPECTED__` | `__INTEGRATION_EVIDENCE__` |
| 打包与制品比较 | `__ARTIFACT_COMMAND__` | `__ARTIFACT_EXPECTED__` | `__ARTIFACT_EVIDENCE__` |
| 启动与运行时检查 | `__RUNTIME_COMMAND__` | `__RUNTIME_EXPECTED__` | `__RUNTIME_EVIDENCE__` |

## 5. 试点与迁移

- 试点项目及锁定 Commit：`__PILOT_PROJECT_AND_COMMIT__`
- 试点 Profile、模块和运行边界：`__PILOT_SCOPE__`
- 迁移步骤与顺序：`__MIGRATION_STEPS__`
- 兼容窗口和消费者清单：`__COMPATIBILITY_WINDOW__`
- 废弃项退出日期：`__DEPRECATION_EXIT_DATE__`

## 6. 回退

- 回退到的基线和 Candidate：`__ROLLBACK_BASELINE_AND_CANDIDATE__`
- 代码、配置、Contract、Schema 与制品回退：`__ROLLBACK_SCOPE__`
- 无法回退部分与前滚方案：`__FORWARD_FIX_PLAN__`
- 停止条件和恢复验证：`__STOP_AND_RECOVERY_EVIDENCE__`

## 7. 批准

- 结论：`__APPLICABLE_CONFLICT_MISSING_EVIDENCE_OR_NOT_APPLICABLE__`
- Candidate / Parent / Tree：`__CANDIDATE_PARENT_TREE__`
- 未决风险：`__OPEN_RISKS_OR_NONE__`
- 审查者：`__REVIEWERS__`
- 批准人及证据：`__APPROVER_AND_EVIDENCE__`
