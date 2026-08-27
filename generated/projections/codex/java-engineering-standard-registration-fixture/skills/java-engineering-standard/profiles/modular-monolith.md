# 模块化单体 Profile

- Profile Id: `modular-monolith`
- 规范版本: `0.4.0`
- 推荐基线: `java21-spring35-maven3`
- 兼容基线: `java21-maven3`、`java21-spring35-maven3`
- 模式: 主 Profile
- 适用对象：在一个部署单元内保持清晰业务模块边界的应用；这是新业务应用的推荐主 Profile。

本文件只增加模块化单体约束；通用规则以 [Java 开发规范](../JAVA-DEVELOPMENT-STANDARD.md) 为准。

| Id | 增量规则 |
| --- | --- |
| MOD-001 | 顶层模块必须按业务能力或 Bounded Context 组织，禁止按 Controller/Service/Repository 全局技术层分组。 |
| MOD-002 | 每个业务模块必须声明 Owner、公开入口、公开事件、内部包和持久化事实。 |
| MOD-003 | 跨模块调用只能使用目标模块的公开 Contract，禁止依赖内部 Domain、Entity 或 Repository。 |
| MOD-004 | 默认事务应位于单一 Owner 模块内；跨模块强事务必须有共同不变量证据和 ADR。 |
| MOD-005 | 跨模块协作应通过公开用例或事件完成；事件消费者必须处理重复、失败和延迟。 |
| MOD-006 | 禁止模块循环依赖，也禁止抽取无语义 `common` 模块掩盖循环。 |
| MOD-007 | 数据库可以共享物理实例，但表、Migration、访问权限和写入路径必须按模块 Owner 隔离。 |
| MOD-008 | 必须使用 Spring Modulith、ArchUnit 或等价检查验证模块可见性和依赖方向。 |
| MOD-009 | 应当为每个模块建立无需完整应用启动的模块级测试，并覆盖公开 Contract。 |
| MOD-010 | 默认只有一个运行装配和发布节奏；禁止仅因 Maven 模块数量宣称已形成微服务。 |
| MOD-011 | 拆分服务前必须先证明模块边界、Contract、数据 Owner、观测和恢复已经可独立成立。 |
| MOD-012 | 合并或调整模块边界必须同步迁移统一语言、Contract、表 Owner、测试和运行手册。 |
| MOD-013 | 项目必须分别登记 Bounded Context/Fact Owner、Maven Module、Runtime Assembly、Storage Role 和 Adapter Surface，禁止由 Artifact Id 或部署名反推 Owner。 |
| MOD-014 | 小型单 Context 项目可以使用单 Maven Module 和显式公开/内部包；物理拆分必须提供编译隔离、独立 Contract、可选 Adapter 或独立维护证据。 |
| MOD-015 | 跨 Owner 的唯一直接发布面必须是接收方 Contract；Application 自用 Port、内部 Schema 片段和持久化快照禁止发布为公共 SDK。 |
| MOD-016 | 同 JVM 跨 Owner 调用仍必须使用接收方本地事务，禁止共享 Repository、可变 Aggregate 或跨调用环境事务。 |
| MOD-017 | Runtime Assembly 只能装配 Owner Module 和 Adapter，禁止承载业务事实；Owner Module 禁止反向依赖 Runtime。 |
| MOD-018 | 可选 `persistence`、`integration`、`worker`、`batch`、`test-support` 模块必须有非空职责、允许依赖和 Owner，禁止为了拓扑对称预建空模块。 |
