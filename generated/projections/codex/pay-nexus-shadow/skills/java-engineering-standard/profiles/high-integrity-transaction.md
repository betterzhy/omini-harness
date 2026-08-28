# 高完整性事务 Profile

- Profile Id: `high-integrity-transaction`
- 规范版本: `0.4.0`
- 推荐基线: `java21-maven3`
- 兼容基线: `java21-maven3`、`java21-spring35-maven3`
- 模式: 附加 Profile
- 适用对象：支付、账务、订单最终态、库存预留、身份授权或其他需要严格幂等、并发恢复和审计的 Java 项目。

本文件只增加高完整性事务约束；通用规则以 [Java 开发规范](../JAVA-DEVELOPMENT-STANDARD.md) 为准。该 Profile 只能出现在接入记录的 `additionalProfiles`，不能替代 `library`、`batch`、`modular-monolith` 或 `microservice` 主 Profile；实际基线继承主 Profile 的选择。

| Id | 增量规则 |
| --- | --- |
| HIT-001 | Fact Owner 语义只由 DDD-003 定义；高完整性项目必须为每个适用事实提供绑定当前 Candidate 的 Authority Review、Owner 清单和跨 Owner Contract 证据。 |
| HIT-002 | 稳定业务键、Payload Hash、结果身份、尝试身份和 Correlation Id 必须分离，禁止用一个标识承担多种生命周期。 |
| HIT-003 | 重放、冲突与超时语义只由 API-011..013 定义；高完整性项目必须为三类分支分别提供具名聚焦测试，并将结果绑定当前 Candidate。 |
| HIT-004 | `UNKNOWN`、`FAILED`、`CONFLICT`、`CANCELLED` 和恢复态必须保持可区分，禁止静默合并。 |
| HIT-005 | CAS、Lease、Fence、Version 和原子提交必须声明线性化点、失败分支、并发不变量和恢复路径。 |
| HIT-006 | Canonical Hash 前像的字段、顺序、编码和版本必须唯一登记，并使用确定性向量验证。 |
| HIT-007 | Owner-local Audit 必须与事实同事务或通过正式可靠传递机制落地，禁止泄漏秘密和未授权存在性。 |
| HIT-008 | 并发、重放、响应丢失、重启和冲突必须有具名测试或恢复演练证据。 |
