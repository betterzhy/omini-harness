# 类库 Profile

- Profile Id: `library`
- 规范版本: `0.4.0`
- 推荐基线: `java21-maven3`
- 兼容基线: `java21-maven3`、`java21-spring35-maven3`
- 模式: 主 Profile
- 适用对象：供一个或多个项目编译期/运行时复用的 Java 库。

本文件只增加 Library 的约束；通用规则以 [Java 开发规范](../JAVA-DEVELOPMENT-STANDARD.md) 为准。

| Id | 增量规则 |
| --- | --- |
| LIB-001 | 必须定义公共 API/ABI 边界，并使用包可见性、模块描述或兼容性工具防止内部类型泄露。 |
| LIB-002 | 公开类型和方法必须保持最小；禁止把 Spring、Persistence Entity 或供应商类型暴露给消费者。 |
| LIB-003 | 传递依赖必须最小化；只在消费者编译确实需要时使用 Maven `compile` Scope。 |
| LIB-004 | 可选集成应拆为独立模块或可选依赖，禁止迫使所有消费者引入某个框架。 |
| LIB-005 | 版本必须遵循语义化版本；破坏性 API/行为变化必须提升主版本并提供迁移说明。 |
| LIB-006 | 每个公开 API 必须有中文为主的 Javadoc，说明契约、空值、线程安全、异常和版本要求。 |
| LIB-007 | 发布必须包含源码 Jar、Javadoc Jar、许可证和可复现的 POM 元数据。 |
| LIB-008 | 制品必须可复现并按发布风险生成校验和、SBOM 和签名；禁止发布本机路径或秘密。 |
| LIB-009 | 必须测试最低支持 Java/Maven 环境和代表性消费者；兼容性不能只由本库单元测试证明。 |
| LIB-010 | Spring Boot Plugin 禁止默认生成可执行 Jar；只有明确作为可运行应用交付时才可以启用重打包。 |
