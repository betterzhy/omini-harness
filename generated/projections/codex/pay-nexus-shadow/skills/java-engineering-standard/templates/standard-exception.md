# Java 规范例外记录

> 本文件是未来例外的人类可读说明模板，对应机器模板为 `standard-exception.yaml`。`0.4.0` 的 `policies/exception-policy.yaml` 没有列出任何可例外规则，也禁止项目级质量 Suppression，因此当前禁止创建有效例外。未来只有策略显式列入的规则才可使用本模板。

## 1. 身份

| 字段 | 内容 |
| --- | --- |
| 例外 Id | `__EXCEPTION_ID__` |
| 规则 Id | `__RULE_ID__` |
| 项目/模块 | `__PROJECT_AND_MODULE__` |
| Owner | `__OWNER__` |
| 批准人 | `__APPROVER__` |
| 创建日期 | `__CREATED_DATE__` |
| 到期日期 | `__EXPIRY_DATE__` |
| 状态 | `__PROPOSED_APPROVED_EXPIRED_OR_CLOSED__` |

## 2. 范围与原因

- 精确范围/WriteSet：`__EXACT_SCOPE_OR_WRITESET__`
- 业务或技术原因：`__REASON__`
- 为什么不能在期限内直接满足规则：`__WHY_STANDARD_CANNOT_BE_MET_NOW__`
- 明确不在例外内的范围：`__OUT_OF_SCOPE__`

## 3. 风险与补偿控制

- 风险与最坏影响：`__RISKS_AND_WORST_CASE__`
- 受影响的 Owner/Contract/数据/安全边界：`__AFFECTED_BOUNDARIES__`
- 补偿控制：`__COMPENSATING_CONTROLS__`
- 监控、告警和人工处置：`__MONITORING_AND_RESPONSE__`

## 4. 验证证据

| 检查 | 命令或证据路径 | 结果 |
| --- | --- | --- |
| 当前差异 | `__CURRENT_DIFF_EVIDENCE__` | `__RESULT__` |
| 直接风险验证 | `__FOCUSED_VERIFICATION__` | `__RESULT__` |
| 回归/兼容性 | `__REGRESSION_OR_COMPATIBILITY__` | `__RESULT__` |
| 候选身份 | `__CANDIDATE_PARENT_TREE__` | `__RESULT__` |

## 5. 退出条件

- 修复 Owner：`__EXIT_OWNER__`
- 目标规则满足方式：`__TARGET_COMPLIANCE__`
- 最晚完成日期：`__EXIT_DATE__`
- 关闭验证：`__CLOSURE_VERIFICATION__`
- 过期处置：`__EXPIRY_ACTION__`

例外到期后自动失效。延期必须创建新的批准记录，不得直接改写原到期事实。
