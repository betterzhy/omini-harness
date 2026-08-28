# Java 开发规范

- 规范版本：`0.4.0`
- 活动基线：`java21-maven3`、`java21-spring35-maven3`
- 状态：活动
- 更新日期：`2026-08-26`
- 语言策略：解释、规则、原因和验收标准以中文为主；产品名、代码标识符及通行行业术语保留英文。

## 1. 阅读约定与核心术语

本规范使用“必须”“应当”“可以”“禁止”表达约束强度。“必须/禁止”是默认不可偏离的要求；只有规则明确写明“可例外”时，才可以通过批准的例外记录限时放宽。“应当”若不采用，也必须在 Review 中给出可验证理由。

- `Authority`（权威依据）：能够裁决事实、范围或行为的正式材料。
- `Domain`（领域）：软件要解决的业务知识和规则。
- `Bounded Context`（限界上下文）：统一语言和模型语义成立的明确边界。
- `Fact Owner`（事实所有者）：对某类业务事实拥有最终写入与解释权的 Context 或组件。
- `Aggregate`（聚合）：在单一一致性边界内维护不变量的一组 Domain 对象。
- `Value Object`（值对象）：由属性值定义身份且通常不可变的 Domain 类型。
- `Domain Event`（领域事件）：已经发生的、对业务有意义的事实。
- `Port`（端口抽象）：由应用核心定义、用于表达所需能力或对外用例的接口；不是网络端口。
- `Adapter`（适配实现）：把外部协议、存储或框架接到 Port 的实现。
- `Contract`（对外契约）：跨边界可依赖的 API、事件、Schema 或公开类型约定。
- `Maven Module`（构建模块）：由 Maven Reactor 管理的编译、依赖和制品边界。
- `Runtime Assembly`（运行装配）：负责启动、配置、依赖注入和运行时组合的模块或部署入口。
- `Storage Role`（存储角色）：对一组表、Migration、索引或持久化事实拥有写入责任的边界。
- `Adapter Surface`（适配表面）：HTTP、消息、数据库或第三方 SDK 等协议与基础设施入口。
- `Profile`（项目类型增量）：在主规范上增加某类项目的约束集合。
- `WriteSet`（写集）：一次变更被授权修改的精确路径集合。

规则原因采用短句说明。下游项目应锁定本仓库 Tag 或完整 Commit SHA，并记录主 Profile、活动基线与有效例外。

## 2. 治理规则（GOV）

| Id | 规则 |
| --- | --- |
| GOV-001 | Java Project Profile 必须选择 `standardVersion`、主 Profile、附加 Profile 和 Baseline；Quality Config 中每个可执行 Runner 必须固定完整 java-engineering-standard Commit、相对路径和 SHA-256。跨项目来源解析、采用锁和 resolved digest 不由 java-engineering-standard 维护。 |
| GOV-002 | 业务 Authority 必须裁决业务语义；它不能静默削弱认证、授权、数据完整性、审计和恢复底线，冲突必须显式记录。 |
| GOV-003 | 主规范必须是通用规则唯一正文；Profile 只能增加约束，不得复制、改写或降低主规范。 |
| GOV-004 | 每项变更必须先确定 Authority、Owner、Exact WriteSet、风险、验证和回退边界。 |
| GOV-005 | 规则等级只使用“必须”“应当”“可以”“禁止”；不得用模糊措辞替代可验收要求。 |
| GOV-006 | 例外资格必须由锁定规范版本的 `policies/exception-policy.yaml` 裁决；`defaultDecision: deny` 时，未列入 `eligibleRules` 的规则禁止例外。`0.4.0` 当前没有可例外规则。 |
| GOV-007 | 例外记录必须包含规则 Id、Owner、范围、原因、风险、补偿控制、验证证据、批准人、到期时间和退出条件；到期自动失效。 |
| GOV-008 | 规范、Profile 或基线升级必须提供差异、兼容性、迁移步骤和回退方案，禁止静默漂移。 |
| GOV-009 | 废弃规则必须先标记替代规则和最短迁移窗口；安全紧急修订可以立即生效，但必须补齐影响说明。 |
| GOV-010 | README、模板、示例、外部 Skill 和历史回执不是 Authority；发生冲突时必须按接入记录和项目 Authority 明确裁决。 |
| GOV-011 | 精确工具与框架版本必须从接入记录选择的活动基线解析；主规范、README、Profile 和示例不得形成相互竞争的版本 Authority。 |
| GOV-012 | 项目必须使用 Java Project Profile、Java Quality Config 和 Java Quality Evidence 分别表达能力选择、稳定技术输入和候选运行事实；人类说明不得与机器记录静默分叉。确定性 CLI 可以验证 Java 输入，禁止扩为任务编排、阶段推进或业务 Authority 平台。 |

## 3. Java 与构建环境（ENV）

| Id | 规则 |
| --- | --- |
| ENV-001 | 项目必须选择与主 Profile 兼容的活动基线，并在接入记录中固定基线 Id；禁止从 README 或开发机现状推断工具版本。 |
| ENV-002 | Java 编译 release、本机过渡 JDK、CI/发布 JDK 和补丁复核日期必须来自选定基线；过渡 JDK 超过 `validUntil` 后不得继续作为验收环境。 |
| ENV-003 | 项目必须提交 Maven Wrapper，并按基线固定 Maven 版本、分发 URL、分发校验和以及两脚本内容身份；`mvnw` 使用原始字节 SHA-256，`mvnw.cmd` 使用仅把完整 CRLF 转为 LF 后的 canonical-LF SHA-256，禁止 lone CR、LF/CRLF 混合或语义内容漂移。两脚本必须为仓库内普通非符号链接文件，且不得依赖开发者机器上的任意全局 Maven。 |
| ENV-004 | 只有选择含 Spring 的基线或实际引入 Spring 时才适用 Spring 规则；Spring Framework 必须由该基线指定的 Boot BOM 管理，不得无依据单独覆盖。 |
| ENV-005 | Maven 4、Java 25、Spring Boot 4 和 Java 预览特性禁止混入当前 Java 21 活动基线；试验必须使用独立基线和接入记录。 |
| ENV-006 | 源码、配置和文本文件必须使用 UTF-8、LF 和文件末尾换行；构建不得依赖平台默认编码。 |
| ENV-007 | 构建与测试必须固定必要的 Locale 和 ZoneId；禁止依赖开发机默认区域或默认时区解释业务数据。 |
| ENV-008 | 时间相关业务逻辑必须注入 `Clock`；测试禁止通过真实等待或修改系统时钟制造时间条件。 |
| ENV-009 | 环境差异必须以版本化配置、容器或可重复脚本表达；禁止把个人 IDE 设置当作唯一运行条件。 |
| ENV-010 | 交付证据必须记录 JDK、Maven、操作系统关键版本和实际命令；缓存命中不能替代干净环境的可复现验证。 |

## 4. Java 编码与类型设计（JAVA）

| Id | 规则 |
| --- | --- |
| JAVA-001 | Java 源文件必须为 UTF-8；一个源文件只应声明一个顶层类型，文件名必须与公开顶层类型一致。 |
| JAVA-002 | 禁止通配符导入和无用导入；同名类型必须通过清晰包结构或必要的限定名消除歧义。 |
| JAVA-003 | Java 格式必须由仓库固定版本的自动格式化器生成；禁止用个人排版偏好制造无语义差异。 |
| JAVA-004 | 包名必须全小写并按组织、产品、Context、层次组织；禁止使用 `util`、`common` 作为无边界杂物箱。 |
| JAVA-005 | 类型用 UpperCamelCase，方法和变量用 lowerCamelCase，常量用 UPPER_SNAKE_CASE；名称必须表达业务含义。 |
| JAVA-006 | 布尔值名称应表达肯定状态，如 `active`、`hasPermission`；禁止产生双重否定的命名。 |
| JAVA-007 | 依赖必须通过构造器传入并优先声明为 `final`；禁止字段注入和隐藏的 Service Locator。 |
| JAVA-008 | Domain 对象和值类型应当不可变；状态变化必须通过维护不变量的命名行为完成。 |
| JAVA-009 | `record` 可以用于不可变数据载体和 Value Object，但构造时仍必须校验不变量；禁止将可变集合直接暴露。 |
| JAVA-010 | `sealed` 类型只应用于确有封闭变体集合且由同一 Owner 演进的模型；跨团队公开扩展点禁止随意封闭。 |
| JAVA-011 | 非空是默认契约；可空边界必须通过注解、类型或文档明确，禁止让 `null` 在核心模型中无约束传播。 |
| JAVA-012 | `Optional` 只应用于可能缺失的返回值；禁止用于字段、方法参数、集合元素或序列化 Contract。 |
| JAVA-013 | 跨边界接收或返回集合时必须进行防御性复制或返回不可变视图；禁止泄露内部可变集合。 |
| JAVA-014 | 公开方法必须校验调用者可控参数；校验错误应包含稳定错误语义，但不得泄露秘密。 |
| JAVA-015 | 捕获并转换异常时必须保留 cause；禁止只记录消息后丢失堆栈和上下文。 |
| JAVA-016 | 禁止用异常控制可预期的正常业务分支；业务拒绝应使用清晰的结果或稳定异常类型表达。 |
| JAVA-017 | 实现 `AutoCloseable` 的资源必须使用 try-with-resources；资源获取与释放顺序必须可审查。 |
| JAVA-018 | `BigDecimal` 必须由字符串或整数构造，禁止从 `double` 构造；数值相等判断应使用 `compareTo`。 |
| JAVA-019 | 金额必须同时绑定币种和舍入规则；禁止用裸 `BigDecimal`、`double` 或 `float` 跨业务边界表示金额。 |
| JAVA-020 | 绝对时间点使用 `Instant`，日历日期使用 `LocalDate`，需要地域规则时显式使用 `ZoneId`；禁止持久化含糊的本地时间。 |
| JAVA-021 | 时间窗口、到期和重试逻辑必须使用注入的 `Clock`，并为边界时刻、夏令时和闰日建立测试。 |
| JAVA-022 | 业务实体必须使用稳定、不可变且与展示字段分离的标识；禁止将数据库自增值无依据暴露为跨系统业务 Id。 |
| JAVA-023 | 同时重写 `equals` 与 `hashCode`；Entity 相等语义必须基于稳定身份，Value Object 基于全部组成值。 |
| JAVA-024 | `toString`、异常和日志对象禁止包含密码、令牌、密钥、完整证件号或其他敏感字段。 |
| JAVA-025 | 服务器请求路径禁止无依据使用 `parallelStream()`；并行度、线程池归属和上下文传播必须显式设计。 |
| JAVA-026 | 虚拟线程只可以用于大量阻塞式、相互独立的任务；必须验证连接池、限流、ThreadLocal、Pinning 和可观测性。 |
| JAVA-027 | 共享可变状态必须有明确同步、所有权或无锁不变量；禁止用 `volatile` 替代复合操作的原子性。 |
| JAVA-028 | Stream 应当保持短小且无副作用；复杂分支、异常处理或状态变化应当使用可读的命名方法和普通循环。 |
| JAVA-029 | 公开泛型 API 禁止滥用原始类型、无界 Object 和不安全强转；编译警告必须消除或局部说明。 |
| JAVA-030 | 禁止在活动基线启用预览特性或忽略编译器告警；任何抑制只有在 `policies/exception-policy.yaml` 按 GOV-006 明确开放资格后，才可以限定到最小范围并记录理由与证据。 |

正确示例：

```java
public record Money(BigDecimal amount, Currency currency) {
  public Money {
    Objects.requireNonNull(amount, "amount");
    Objects.requireNonNull(currency, "currency");
    amount = amount.setScale(currency.getDefaultFractionDigits(), RoundingMode.HALF_EVEN);
  }

  public boolean isZero() {
    return amount.compareTo(BigDecimal.ZERO) == 0;
  }
}
```

错误示例：

```java
double amount = 0.1 + 0.2;
BigDecimal money = new BigDecimal(amount);
if (money.equals(BigDecimal.valueOf(0.3))) {
  // 错误：二进制浮点误差、缺少币种，并错误依赖 scale 相等。
}
```

正确示例：

```java
public final class ExpirationPolicy {
  private final Clock clock;

  public ExpirationPolicy(Clock clock) {
    this.clock = Objects.requireNonNull(clock);
  }

  public boolean expiredAt(Instant deadline) {
    return !clock.instant().isBefore(deadline);
  }
}
```

错误示例：

```java
public boolean expiredAt(Instant deadline) {
  return Instant.now().isAfter(deadline); // 错误：隐式系统时钟且漏掉相等边界。
}
```

## 4.1 Java 编码质量规则（CODE）

`CODE-*` 负责源码组织、命名、可读性、API 表达、注释、测试代码和质量债务治理；`JAVA-*` 继续负责 Java 类型、值语义和运行安全。表中的 Source Set 与 Layer Role 是独立坐标。`0.4.0` 的规则均不得通过项目级 Suppression 或规范例外绕过；阈值类规则只产生 Review Signal，不构成机械重构授权。

### 4.1.1 源码组织（CODE-001..010）

| Id | 等级 | Source Set | Layer Role | 规则与风险 | 主执行器 | 失败标识 | 交叉引用 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CODE-001 | 必须 | main/test | 全部 | 文本使用 UTF-8、LF、末尾换行且无行尾空白，避免平台漂移。 | Spotless | `CODE_TEXT_FORMAT` | ENV-006、JAVA-001 |
| CODE-002 | 应当 | main/test | 全部 | 一个源文件只声明一个主要顶层类型；紧密关联的非公开辅助类型必须保持局部，避免隐藏职责。 | Authority Review | `CODE_TOP_LEVEL_TYPE_REVIEW` | JAVA-001 |
| CODE-003 | 必须 | main/test | 全部 | Package、Import、类型声明按固定结构排列，禁止用视觉排列表达不存在的语义。 | Authority Review | `CODE_DECLARATION_ORDER_REVIEW` | JAVA-003 |
| CODE-004 | 禁止 | main/test | 全部 | 禁止通配符 Import，避免新增同名类型后解析漂移。 | Spotless | `CODE_WILDCARD_IMPORT` | JAVA-002 |
| CODE-005 | 禁止 | main/test | 全部 | 禁止重复或无用 Import，保持依赖面可读。 | Spotless | `CODE_UNUSED_IMPORT` | JAVA-002 |
| CODE-006 | 必须 | main/test | 全部 | 每行只写一个语句，禁止压缩多个业务步骤。 | Checkstyle | `OneStatementPerLine` | JAVA-003 |
| CODE-007 | 必须 | main/test | 全部 | Java 格式只由活动基线固定的 Formatter 裁决，Review 禁止另造空格与换行规则。 | Spotless | `CODE_FORMAT_DRIFT` | JAVA-003、BUILD-005 |
| CODE-008 | 必须 | generated | adapter/runtime | `0.4.0` 的每个 Module 必须显式登记空 `generatedSources`；完整 Reactor 只要存在 Generated Source 就禁止形成合规结论。 | Schema / Production Validator | `QUALITY_GENERATED_SOURCE_UNSUPPORTED` | ARCH-019 |
| CODE-009 | 禁止 | generated | adapter/runtime | 禁止把内部保留的重建实现、历史测试或生成目录 Hash 表述为 `0.4.0` 的生产合规能力。 | Production Validator | `QUALITY_GENERATED_SOURCE_UNSUPPORTED` | ARCH-019、AI-010 |
| CODE-010 | 必须 | main/test | 全部 | 首次 Maven 前必须从实际 raw POM 递归发现 Reactor Module 并与配置全集对账；Maven 后还必须对账全部手写 Source Root，禁止通过缩窄配置隐藏 Module 或源码。 | Production Validator / Source Layout Validator | `QUALITY_REACTOR_MODULE_SET_MISMATCH` / `QUALITY_HANDWRITTEN_SOURCE_UNSCANNED` | ARCH-021、BUILD-023 |

### 4.1.2 命名（CODE-011..020）

| Id | 等级 | Source Set | Layer Role | 规则与风险 | 主执行器 | 失败标识 | 交叉引用 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CODE-011 | 必须 | main/test | 全部 | Package 使用小写领域或能力词，禁止编码临时阶段或形成无边界 `common`。 | Authority Review | `CODE_PACKAGE_NAME_REVIEW` | JAVA-004、ARCH-030 |
| CODE-012 | 必须 | main/test | 全部 | 类型使用名词或明确角色的 UpperCamelCase 名称。 | Checkstyle | `TypeName` | JAVA-005 |
| CODE-013 | 必须 | main/test | 全部 | 方法使用表达行为的 lowerCamelCase 动词名称。 | Checkstyle | `MethodName` | JAVA-005、DDD-006 |
| CODE-014 | 应当 | main/test | 全部 | Boolean 名称使用肯定谓词，禁止双重否定。 | Authority Review | `CODE_BOOLEAN_NAMING_REVIEW` | JAVA-006 |
| CODE-015 | 必须 | main/test | 全部 | 缩写按普通单词处理，禁止难辨认的连续全大写名称。 | Authority Review | `CODE_ABBREVIATION_REVIEW` | JAVA-005 |
| CODE-016 | 应当 | main/test | 全部 | 泛型参数仅在局部简单语境使用 `T/K/V`；多角色或跨多行时使用语义名称。 | Authority Review | `CODE_GENERIC_NAME_REVIEW` | JAVA-029 |
| CODE-017 | 必须 | main/test | 全部 | 常量使用 UPPER_SNAKE_CASE，枚举常量使用稳定业务词。 | Checkstyle | `ConstantName` | JAVA-005 |
| CODE-018 | 必须 | test | test-support | 测试、Fixture、Case Source 和 Builder 使用稳定角色后缀，名称必须暴露其测试职责。 | Authority Review | `CODE_TEST_ROLE_NAME_REVIEW` | TEST-001 |
| CODE-019 | 应当 | main | application/adapter | Adapter 与 Port 名称必须表达方向和能力，禁止以供应商形状替代业务语义。 | Authority Review | `CODE_BOUNDARY_NAME_REVIEW` | DDD-013、DDD-014 |
| CODE-020 | 应当 | main/test | 全部 | `Manager`、`Helper`、`Util`、`Common`、`Processor` 只产生职责 Review Signal；工具禁止伪装成业务裁决。 | Authority Review | `AUTHORITY_REVIEW_REQUIRED` | JAVA-004、ARCH-011 |

### 4.1.3 类、方法与 API（CODE-021..030）

| Id | 等级 | Source Set | Layer Role | 规则与风险 | 主执行器 | 失败标识 | 交叉引用 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CODE-021 | 必须 | main | 全部 | 使用满足消费者需要的最小可见性；公开 API 必须有稳定消费者和兼容责任。 | Authority Review | `CODE_VISIBILITY_REVIEW` | LIB-001、LIB-002 |
| CODE-022 | 应当 | main/test | 全部 | 类只承担一个可命名职责，职责不清必须形成 Review Signal。 | Authority Review | `CODE_CLASS_RESPONSIBILITY_REVIEW` | ARCH-011 |
| CODE-023 | 应当 | main | 全部 | 组合优先于仅为复用实现而继承；继承必须保留可替换契约。 | Authority Review | `CODE_INHERITANCE_REVIEW` | DDD-013 |
| CODE-024 | 禁止 | main | 全部 | 禁止为单一实现且无替换边界创建仪式性接口。 | Authority Review | `CODE_INTERFACE_REVIEW` | DDD-013 |
| CODE-025 | 必须 | main | domain/application/contract | 构造器只建立有效对象，禁止隐藏 I/O、线程启动或跨系统调用。 | Focused Test | `CODE_CONSTRUCTOR_SIDE_EFFECT` | JAVA-007、DDD-007 |
| CODE-026 | 应当 | main | 全部 | 构造器、静态工厂或 Builder 按不变量和可读性选择，禁止机械统一。 | Authority Review | `CODE_CREATION_API_REVIEW` | JAVA-009 |
| CODE-027 | 应当 | main/test | 全部 | 生产类超过 300 行或测试类超过 500 行时必须 Review；阈值不是自动拆分命令。 | Authority Review | `CODE_CLASS_SIZE_REVIEW` | AI-003 |
| CODE-028 | 应当 | main/test | 全部 | 方法超过 60 行、参数超过 7 个或嵌套超过 4 层时必须 Review，并以具名阶段或 Value Object 降低认知负担。 | Authority Review | `CODE_METHOD_COMPLEXITY_REVIEW` | DDD-007、DDD-009 |
| CODE-029 | 必须 | main | application/domain | 必需 Port 能力通过编译期类型和构造依赖表达，禁止用反射或默认异常协商。 | Focused Test | `CODE_PORT_CAPABILITY_HIDDEN` | JAVA-007、DDD-013 |
| CODE-030 | 禁止 | main | contract/application | 禁止以 `Object...`、万能 Context 或服务定位器形成公共 API。 | Focused Test | `CODE_DYNAMIC_API` | JAVA-029、DDD-013 |

### 4.1.4 Null、Optional、集合与 Stream（CODE-031..040）

| Id | 等级 | Source Set | Layer Role | 规则与风险 | 主执行器 | 失败标识 | 交叉引用 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CODE-031 | 必须 | main | contract/domain/application | 公开边界明确 Nullness；禁止用 `null` 合并不同 Result 分支。 | Focused Test | `CODE_NULLNESS_UNDECLARED` | JAVA-011 |
| CODE-032 | 必须 | main | 全部 | Optional 语义只由 JAVA-012 定义；main Source Set 必须提供静态策略和聚焦测试证据，失败必须定位到本 Rule Id。 | Focused Test | `CODE_OPTIONAL_MISUSE` | JAVA-012 |
| CODE-033 | 必须 | main | 全部 | 返回空集合而非 `null`，并明确集合是否可变。 | Focused Test | `CODE_NULL_COLLECTION` | JAVA-011、JAVA-013 |
| CODE-034 | 必须 | main | contract/domain/application | 跨边界集合进行防御性复制或返回不可变表示。 | Focused Test | `CODE_MUTABLE_COLLECTION_ESCAPE` | JAVA-013 |
| CODE-035 | 禁止 | main | contract/domain/application | 业务边界禁止 `Map<String, Object>` 动态属性包。 | Focused Test | `CODE_DYNAMIC_MAP_BOUNDARY` | JAVA-029、DDD-013 |
| CODE-036 | 可以 | main | adapter | 协议解析、Canonical Hash 前像或框架 Extension Map 只有在局部、不逸出且有确定性 Schema/测试时可以使用动态结构。 | Authority Review | `CODE_DYNAMIC_STRUCTURE_REVIEW` | DDD-014、TEST-003 |
| CODE-037 | 必须 | main/test | 全部 | `Collectors.toMap` 必须显式处理重复 Key，禁止依赖未声明覆盖顺序。 | Focused Test | `CODE_DUPLICATE_KEY_POLICY` | JAVA-028 |
| CODE-038 | 禁止 | main/test | 全部 | Stream 禁止重复消费或在 Pipeline 中隐藏状态副作用。 | Focused Test | `CODE_STREAM_REUSE` | JAVA-028 |
| CODE-039 | 必须 | main | adapter/application | 资源型 Stream、HTTP Body、文件和游标必须有明确关闭 Owner。 | Focused Test | `CODE_RESOURCE_OWNER` | JAVA-017 |
| CODE-040 | 必须 | main/test | 全部 | 资源默认使用 try-with-resources，禁止在清理时丢失 Suppressed Exception。 | Focused Test | `CODE_SUPPRESSED_EXCEPTION_PRESERVED` | JAVA-015、JAVA-017 |

### 4.1.5 异常、并发与日志（CODE-041..050）

| Id | 等级 | Source Set | Layer Role | 规则与风险 | 主执行器 | 失败标识 | 交叉引用 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CODE-041 | 必须 | main | contract/application/adapter | 异常类型表达调用方可采取的动作，转换时保留 Cause。 | Focused Test | `CODE_EXCEPTION_SEMANTICS` | JAVA-015、JAVA-016 |
| CODE-042 | 禁止 | main/test | 全部 | 禁止捕获 `Throwable`、`Error` 或无条件吞掉异常。 | Focused Test | `CODE_BROAD_CATCH` | JAVA-015 |
| CODE-043 | 必须 | main/test | 全部 | 捕获 `InterruptedException` 后传播中断、恢复标志或执行正式取消协议。 | Error Prone | `InterruptedExceptionSwallowed`、`InterruptedInCatchBlock` | JAVA-027 |
| CODE-044 | 禁止 | main | 全部 | 禁止同一异常在多层重复记录后再抛出。 | Authority Review | `CODE_DUPLICATE_EXCEPTION_LOG` | OBS-006 |
| CODE-045 | 必须 | main | runtime/application/adapter | 线程池、Scheduler、虚拟线程和 `CompletableFuture` 声明生命周期、命名、执行器及清理 Owner。 | Authority Review | `CODE_EXECUTOR_OWNER_REVIEW` | JAVA-026、JAVA-027 |
| CODE-046 | 禁止 | main | application/adapter | 业务异步负载禁止无证据使用共享 Common Pool，异步操作必须显式选择执行器。 | Focused Test | `CODE_COMMON_POOL` | JAVA-025 |
| CODE-047 | 必须 | main/test | domain/application/adapter | 锁顺序、超时、中断、CAS 失败和重试必须有限、可观察且可测试。 | Focused Test | `CODE_CONCURRENCY_BRANCH_UNTESTED` | JAVA-027、TEST-012 |
| CODE-048 | 必须 | main | 全部 | 常规日志使用参数化模板，异常作为最后参数，禁止字符串拼接。 | Authority Review | `CODE_LOG_PARAMETERIZATION_REVIEW` | OBS-006 |
| CODE-049 | 禁止 | main/test | 全部 | 禁止记录秘密、完整令牌、敏感对象或未脱敏业务对象。 | Authority Review | `CODE_SENSITIVE_LOG_REVIEW` | JAVA-024、SEC-008 |
| CODE-050 | 必须 | main | runtime/application/adapter | Trace/Correlation 上下文装载、传播与清理必须成对，异步边界禁止依赖泄漏的 ThreadLocal。 | Focused Test | `CODE_CONTEXT_LEAK` | OBS-003、JAVA-026 |

### 4.1.6 Java 21、值语义与序列化（CODE-051..060）

| Id | 等级 | Source Set | Layer Role | 规则与风险 | 主执行器 | 失败标识 | 交叉引用 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CODE-051 | 必须 | main/test | 全部 | 只使用活动 Java 21 基线允许的非 Preview 特性。 | Compiler | `CODE_PREVIEW_FEATURE` | ENV-005、JAVA-030 |
| CODE-052 | 必须 | main | domain/contract | `record` 中的数组和可变集合必须防御复制或改为不可变表示。 | Focused Test | `CODE_RECORD_MUTABILITY` | JAVA-009、JAVA-013 |
| CODE-053 | 应当 | main | domain/contract | `sealed` 只表达真实闭集；公开密封层次必须评估消费者兼容性。 | Authority Review | `CODE_SEALED_COMPATIBILITY_REVIEW` | JAVA-010 |
| CODE-054 | 必须 | main | domain/application | 内部闭集的模式匹配 `switch` 禁止用宽泛 `default` 吞掉新增状态。 | Focused Test | `CODE_NON_EXHAUSTIVE_STATE` | JAVA-010、DDD-018 |
| CODE-055 | 必须 | main/test | 全部 | equals/hashCode 语义只由 JAVA-023 定义；main/test Source Set 必须执行对应聚焦测试并保留可定位失败证据。 | Focused Test | `CODE_EQUALS_HASHCODE_CONTRACT` | JAVA-023 |
| CODE-056 | 禁止 | main | domain | 作为 Map Key 或 Set 元素期间，参与 Hash 的字段禁止变化。 | Focused Test | `CODE_MUTABLE_HASH_KEY` | JAVA-023 |
| CODE-057 | 必须 | main | domain | Entity 相等由项目身份策略裁决，禁止套用全部字段或未持久化的数据库自增 Id。 | Authority Review | `CODE_ENTITY_EQUALITY_REVIEW` | JAVA-022、JAVA-023 |
| CODE-058 | 禁止 | main | 全部 | `toString` 限制长度、递归和敏感数据，禁止充当稳定序列化格式。 | Focused Test | `CODE_TOSTRING_CONTRACT` | JAVA-024、SEC-008 |
| CODE-059 | 必须 | main | contract/adapter | 序列化 Contract 固定字段语义、Null 策略、版本和兼容窗口，禁止依赖对象默认形状。 | Compatibility Test | `CODE_SERIALIZATION_CONTRACT` | API-018、API-024 |
| CODE-060 | 必须 | main/test | domain/contract | 金额、时间、单位和标识使用强类型值语义，禁止通过裸数值或展示字符串序列化。 | Focused Test | `CODE_VALUE_SEMANTICS` | JAVA-018、JAVA-019、JAVA-020、JAVA-022 |

### 4.1.7 Handler、状态与注释（CODE-061..070）

| Id | 等级 | Source Set | Layer Role | 规则与风险 | 主执行器 | 失败标识 | 交叉引用 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CODE-061 | 应当 | main | application | Handler 必须让验证、准入、领域推进、原子提交、审计和结果映射的实际顺序可读；具体阶段由 Use Case 决定。 | Authority Review | `CODE_HANDLER_FLOW_REVIEW` | DDD-009 |
| CODE-062 | 必须 | main | domain/application | 稳定键、Hash 前像或状态快照必须有唯一构造和解析位置。 | Focused Test | `CODE_CANONICAL_BUILDER_DUPLICATED` | DDD-020 |
| CODE-063 | 禁止 | main | domain/application | 禁止散落 `split`、裸索引和重复字符串拼装解析权威身份。 | Authority Review | `CODE_ADHOC_PARSING_REVIEW` | DDD-003、DDD-020 |
| CODE-064 | 应当 | main | domain/application | 控制流程 Boolean 应改为具名方法、Enum、Policy 或封闭 Result；正式 Boolean Fact 可以保留。 | Authority Review | `CODE_CONTROL_BOOLEAN_REVIEW` | JAVA-006、DDD-018 |
| CODE-065 | 必须 | main | domain/application | 内部闭集状态使用 Enum 或 Sealed Result，并保持失败分支穷尽。 | Focused Test | `CODE_STATE_SET_OPEN` | JAVA-010、DDD-018 |
| CODE-066 | 必须 | main | contract/adapter | 跨系统字符串码集中到 Catalog 或 Mapper，禁止散落字面量。 | Focused Test | `CODE_EXTERNAL_CODE_LITERAL` | API-015、DDD-014 |
| CODE-067 | 应当 | main/test | 全部 | 注释解释不变量、原因、恢复、安全或兼容边界，禁止逐句复述代码。 | Authority Review | `CODE_COMMENT_INTENT_REVIEW` | AI-010 |
| CODE-068 | 必须 | main | contract | 公开 API Javadoc 说明线程安全、Nullness、单位、时区、副作用、异常和兼容性。 | Authority Review | `CODE_PUBLIC_API_JAVADOC_REVIEW` | LIB-006、API-018 |
| CODE-069 | 必须 | main | contract | 废弃 API 提供替代路径、迁移说明和移除条件。 | Authority Review | `CODE_DEPRECATION_MIGRATION_REVIEW` | GOV-009、API-019 |
| CODE-070 | 禁止 | main/test | 全部 | 禁止用注释、日志或测试名称代替编译期类型、正式 Contract 或可执行不变量。 | Authority Review | `CODE_PROSE_AS_CONTRACT_REVIEW` | GOV-002、TEST-003 |

### 4.1.8 可读性与边界信号（CODE-071..080）

| Id | 等级 | Source Set | Layer Role | 规则与风险 | 主执行器 | 失败标识 | 交叉引用 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CODE-071 | 应当 | main/test | 全部 | 复杂流程用具名阶段和强类型中间值表达，禁止用压缩写法隐藏业务顺序；PMD Finding 只触发 Review。 | PMD | `CognitiveComplexity` | DDD-009 |
| CODE-072 | 应当 | main | application/domain | 同一生命周期的数据应形成 Use Case 专用 Command、Query 或 Value Object。 | Authority Review | `CODE_LONG_PARAMETER_REVIEW` | DDD-007、DDD-009 |
| CODE-073 | 禁止 | main | domain/application/contract | 禁止万能 Context、动态参数包和静默 `null` 默认值掩盖边界。 | Focused Test | `CODE_CONTEXT_BAG` | JAVA-011、CODE-030 |
| CODE-074 | 必须 | main | application/domain | 抽象复用必须证明相同语义、不变量、生命周期、错误语义、Owner 和至少两个现实使用点。 | Authority Review | `CODE_ABSTRACTION_EVIDENCE_REQUIRED` | ARCH-011、ARCH-030 |
| CODE-075 | 应当 | main | adapter/application | 边界转换集中且可命名；禁止传输 DTO、供应商异常或持久化对象逸入核心。 | Focused Test | `CODE_BOUNDARY_TYPE_LEAK` | DDD-014、ARCH-013 |
| CODE-076 | 必须 | main | contract/application | Result 分支保持封闭、可区分和可测试，禁止把拒绝、未知和技术失败合并。 | Focused Test | `CODE_RESULT_BRANCH_COLLAPSED` | JAVA-016、DDD-018 |
| CODE-077 | 必须 | main | domain/application | 状态变化只能通过维护不变量的命名行为完成，禁止公开无约束 Setter。 | Focused Test | `CODE_STATE_SETTER` | JAVA-008、DDD-006 |
| CODE-078 | 应当 | main/test | 全部 | 行数、参数数和复杂度只作为边界信号；重构前必须固定 Authority 和行为证据。 | Authority Review | `CODE_REFACTOR_AUTHORITY_REQUIRED` | GOV-004、AI-003 |
| CODE-079 | 禁止 | main | application/domain | 禁止为拓扑对称、未来想象或工具安静而创建空抽象与空模块。 | Authority Review | `CODE_SPECULATIVE_STRUCTURE_REVIEW` | ARCH-023、MOD-018 |
| CODE-080 | 必须 | main/test | 全部 | 可读性 Finding 必须带规则 Id、相对路径和稳定源码锚点，禁止仅用绝对路径或行号形成身份。 | Finding Adapter / Validator | `QUALITY_FINDINGS_NORMALIZATION_FAILED` | GOV-012、AI-014 |

### 4.1.9 测试、Generated Source 与抑制（CODE-081..090）

| Id | 等级 | Source Set | Layer Role | 规则与风险 | 主执行器 | 失败标识 | 交叉引用 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CODE-081 | 必须 | test | test-support | 测试代码执行与生产代码相同的 Formatter、Import 和基础静态规则。 | Spotless | `CODE_TEST_STATIC_DRIFT` | TEST-001、AI-010 |
| CODE-082 | 必须 | test | test-support | 测试名表达行为、条件和结果，禁止依赖执行顺序或时间偶然性。 | Authority Review | `CODE_TEST_NAME_REVIEW` | TEST-001、TEST-004 |
| CODE-083 | 应当 | test | test-support | 大型测试按行为 Case、Fixture、Case Source、Builder 和断言辅助拆分，辅助代码禁止隐藏 Oracle。 | Authority Review | `CODE_TEST_STRUCTURE_REVIEW` | TEST-003 |
| CODE-084 | 禁止 | test | test-support | 禁止用 Mock 调用次数、文件存在或序列化成功替代业务语义断言。 | Authority Review | `CODE_WEAK_ORACLE_REVIEW` | TEST-003、TEST-010 |
| CODE-085 | 禁止 | generated | adapter/runtime | `java21-maven3` / `0.4.0` 禁止非空 Generated Source 登记；后继版本必须先取得单独批准的隔离执行设计，不能沿用本版 dormant implementation 作为接入证据。 | Schema / Production Validator | `QUALITY_GENERATED_SOURCE_UNSUPPORTED` | ARCH-019、BUILD-023 |
| CODE-086 | 必须 | generated | adapter/runtime | 完整 Reactor 中发现 Generated Source 时必须得到 `JAVA_QUALITY_RESULT=MISSING_EVIDENCE`，不能得到 `VALID`，直至后继版本提供批准的生产入口与当前 Candidate 证据。 | Java Quality Validator | `QUALITY_GENERATED_SOURCE_UNSUPPORTED` | AI-014、DEL-006 |
| CODE-087 | 必须 | main/test/generated | 全部 | 抑制资格语义只由 JAVA-030 与 GOV-006 定义；质量扫描必须输出可复现的抑制输入清单，并按锁定 Policy 对每项资格 Fail Closed。 | Suppression Validator | `QUALITY_SUPPRESSION_PROHIBITED` | GOV-006、JAVA-030 |
| CODE-088 | 必须 | main/test | 全部 | 新项目无质量抑制；存量债务只能使用受控机器基线并禁止新增 Finding。 | Ratchet Validator | `QUALITY_BASELINE_NEW_FINDING` | GOV-008、BUILD-023 |
| CODE-089 | 必须 | main/test/generated | 全部 | 工具误报必须由新的 `java-engineering-standard` 固定候选统一调整或保持 Observed，单项目禁止静默关闭。 | Fixed Candidate Review | `QUALITY_RULE_OVERRIDE_PROHIBITED` | GOV-003、AI-014 |
| CODE-090 | 禁止 | main/test/generated | 全部 | 后继版本未建立 Registry、Schema、工具引用协议、行为测试和迁移前，禁止开放 Suppression。 | Fixed Candidate Review | `QUALITY_SUPPRESSION_CONTRACT_MISSING` | GOV-006、GOV-008 |

## 5. DDD 规则（DDD）

| Id | 规则 |
| --- | --- |
| DDD-001 | 团队必须为关键业务概念建立统一语言，并让代码、Contract、测试和文档使用相同含义。 |
| DDD-002 | 每个 Bounded Context 必须说明职责、输入、输出、Owner 和不拥有的事实，禁止仅按技术层命名 Context。 |
| DDD-003 | 每类可变业务事实必须使用稳定、可比较的事实标识并且只能有一个 Fact Owner；其他 Context 只能通过公开 Contract 请求或消费事实。 |
| DDD-004 | Aggregate 必须围绕必须立即一致的不变量划定；禁止为了对象导航构造超大 Aggregate。 |
| DDD-005 | 外部只能通过 Aggregate Root 改变聚合内状态；禁止绕过 Root 直接持久化内部 Entity。 |
| DDD-006 | Aggregate 方法必须使用业务动词并在一次行为中维护不变量；禁止公开无约束 Setter。 |
| DDD-007 | Value Object 必须不可变、自校验并具有明确值相等语义；单位、币种和格式不得由调用者猜测。 |
| DDD-008 | Domain Service 只承载不自然属于某个 Entity/Value Object 的领域规则；禁止成为任意逻辑容器。 |
| DDD-009 | Application Service 必须负责编排用例、事务和 Port，不得复制 Aggregate 内的业务不变量。 |
| DDD-010 | Domain Event 必须用过去式表达已发生事实，并包含稳定事件 Id、发生时间、类型和业务关联标识。 |
| DDD-011 | Domain Event 与外部 Integration Event 必须分离；出站 Adapter 负责 Contract 转换和兼容。 |
| DDD-012 | `Repository` 是聚合持久化 Port，接口必须由使用它的应用核心拥有；禁止暴露存储框架查询对象。 |
| DDD-013 | Port 必须表达业务所需能力和失败语义，不得按某个供应商 SDK 形状反向设计。 |
| DDD-014 | Adapter 必须隔离协议、存储和第三方模型；转换失败应在边界处形成稳定错误。 |
| DDD-015 | 跨 Context 只能依赖公开 Contract；禁止导入对方内部 Domain 类型或共享可变 Aggregate。 |
| DDD-016 | 禁止跨 Context 直接写表、共享 Repository 实现或通过数据库外键夺取对方事实所有权。 |
| DDD-017 | 跨 Aggregate 强一致要求必须有业务证据；否则应使用事件、流程管理器和可恢复的最终一致性。 |
| DDD-018 | 长流程必须显式建模状态、幂等、超时、补偿和人工恢复入口，禁止隐藏在连续回调中。 |
| DDD-019 | 读模型可以为查询去规范化，但不得反向成为写入事实源；刷新延迟必须可观测。 |
| DDD-020 | 模型变更必须同步检查统一语言、Owner、Contract、不变量、迁移和历史数据解释。 |

## 6. 工程与模块架构（ARCH）

默认依赖方向如下，箭头表示“左侧可以依赖右侧”；`contract` 与 `domain` 默认互不依赖：

```text
contract -> JDK only
domain -> JDK + approved owner-local stable value types
application -> domain + contract
adapter-in/out -> application + contract; domain only for justified boundary mapping
boot/runtime -> owner modules + adapters
cross-context -> receiver published contract or caller Port through Adapter
```

| Id | 规则 |
| --- | --- |
| ARCH-001 | 新业务应用必须优先选择模块化单体；微服务拆分必须提供独立演进、扩缩容、隔离或合规证据。 |
| ARCH-002 | Bounded Context/Fact Owner、Maven Module、Java package、Runtime Assembly、Storage Role 和 Adapter Surface 是独立维度；禁止从任一维度推断其他维度或把模块数量等同于服务数量。 |
| ARCH-003 | `domain` 必须保持纯 Java，禁止依赖 Spring、JPA、MyBatis、Web、消息或供应商 SDK。 |
| ARCH-004 | `application` 可以依赖 `domain`，并拥有用例 Port 与所需出站 Port；禁止依赖具体 Adapter。 |
| ARCH-005 | `adapter-in` 必须只负责协议解析、认证上下文、输入转换和调用用例，不得实现核心业务规则。 |
| ARCH-006 | `adapter-out` 必须实现应用核心定义的 Port，默认只依赖 application 与 contract；只有边界映射确实使用 Domain 类型且由模块登记或 ADR 说明时才可以依赖 domain，禁止反向控制核心模型。 |
| ARCH-007 | `boot` 只负责装配、配置和启动，可以依赖 Adapter；其他模块禁止依赖 `boot`。 |
| ARCH-008 | 跨 Context 依赖只允许指向发布的 Contract，禁止访问对方 `internal` 包、表或内部事件。 |
| ARCH-009 | 每个模块必须声明公开入口和内部实现；Java 可见性、包规则和架构测试应共同执行边界。 |
| ARCH-010 | 禁止循环模块依赖；临时循环不能通过抽取无语义 `common` 模块掩盖。 |
| ARCH-011 | 共用库必须有单一清晰职责和 Owner；业务语义应留在拥有它的 Context，而非全局共享。 |
| ARCH-012 | 配置、框架注解和序列化模型必须停留在边界层，除非它们是经过批准的公开 Contract。 |
| ARCH-013 | 第三方 SDK 必须置于 Adapter 后；核心代码不得传播供应商异常、DTO 或分页类型。 |
| ARCH-014 | 架构边界必须使用 ArchUnit、Spring Modulith 或等价自动检查，禁止只靠目录约定。 |
| ARCH-015 | 入口、事务、远程调用和持久化边界必须在代码结构中可定位，禁止依赖隐式 AOP 知识才能理解。 |
| ARCH-016 | 依赖方向例外只有在当前例外策略明确列出该规则时才可以启用，并且必须有 ADR、Owner、期限、证据和替代方案；`0.4.0` 禁止有效依赖方向例外，禁止用“方便”作为长期反向依赖理由。 |
| ARCH-017 | 模块公开 Contract 必须至少登记一个位于该 Contract Module 基础包内的公开包，并应保持最小、稳定和面向用例；禁止公开内部 Entity 或通用数据访问能力。 |
| ARCH-018 | 微服务不得共享可写数据库 Schema；共享物理设施时仍必须保持逻辑 Owner、访问控制和迁移边界。 |
| ARCH-019 | 生成代码与生成投影必须有来源、版本和重建命令；禁止手工修改会被覆盖的产物。 |
| ARCH-020 | 架构变更必须说明受影响模块、Contract、运行拓扑、迁移、回退和验证证据。 |
| ARCH-021 | 项目必须登记每个 Context 的 Fact Owner、拥有与不拥有事实、公开 Contract、内部包、Storage Role、Runtime Assembly、Adapter Surface、允许依赖和结构化禁止依赖；所有跨项引用必须能解析到唯一登记 Id，Fact 与可写资源 Owner 必须唯一，角色方向、Surface 方向、Context 与 Runtime 装配清单必须双向一致。 |
| ARCH-022 | 小型单 Context 项目可以在单一 Maven Module 内以公开 `contract` 和 `internal` 包表达边界；不得为了形式完整机械拆分物理模块。 |
| ARCH-023 | 物理 Maven Module 必须至少提供编译隔离、独立 Owner/Contract、可选 Adapter/SDK、独立维护测试或现实运行需求之一的证据；禁止创建空模块或未来想象模块。 |
| ARCH-024 | 跨 Owner 的直接编译依赖必须只指向接收方发布的 Contract；需要隔离 Transport 时，调用方核心必须定义出站 Port，由 Adapter 转换到接收方 Contract。 |
| ARCH-025 | `contract` 默认只依赖 JDK 和批准的稳定标准类型；Domain 与 Contract 默认互不依赖。Domain 复用 Contract 类型必须用 ADR 证明其为 Owner 稳定值语义而非传输 DTO。 |
| ARCH-026 | Runtime Assembly 只负责启动、配置、DI、协议入口、Health 和 Telemetry；禁止拥有 Aggregate、业务规则、通用 Repository 或跨 Owner 事务。 |
| ARCH-027 | Owner Module 禁止反向依赖 Runtime Assembly；技术支持模块也禁止反向决定业务 Owner、Contract 或状态语义。 |
| ARCH-028 | 同一 JVM 内跨 Fact Owner 协作仍禁止共享可变 Aggregate、Repository 和隐式环境事务；接收方必须在自己的本地事务中提交事实。 |
| ARCH-029 | 进程拆分只能改变 Transport 和运行隔离；Fact Owner、Contract、状态解释、数据写权和恢复责任必须显式迁移或保持不变。 |
| ARCH-030 | `common` 或 Shared Kernel 只能包含有明确 Owner、稳定语义和消费者清单的最小共享类型；禁止放置业务 Entity、通用 Repository、万能 DTO 或任意框架配置。 |

## 7. Spring 系列（SPR）

| Id | 规则 |
| --- | --- |
| SPR-001 | Spring 依赖必须由选定 Spring 基线指定的 Spring Boot BOM 管理；禁止为常规修复单独覆盖其管理的 Spring Framework。 |
| SPR-002 | 禁止在 `domain` 引入 Spring Framework、Spring Data、Spring Validation 或 Spring 序列化注解。 |
| SPR-003 | Spring Bean 依赖必须使用单一构造器注入并尽量 `final`；禁止字段注入。 |
| SPR-004 | 应用配置应使用类型安全、可校验的 `@ConfigurationProperties`；禁止散落大量 `@Value` 字符串。 |
| SPR-005 | Spring Profile 只控制确有环境差异的 Bean 或配置组合；禁止用 Profile 保存秘密或隐藏业务分支。 |
| SPR-006 | 配置必须定义默认值、必填项、单位和校验；启动时应快速失败而非运行后才暴露错误。 |
| SPR-007 | Controller 必须保持薄层，只处理协议、认证上下文、校验、DTO 映射和用例调用。 |
| SPR-008 | Web DTO、消息 DTO、Persistence Entity 与 Domain 类型必须分离，转换责任放在 Adapter。 |
| SPR-009 | HTTP 错误应当使用 RFC 9457 `ProblemDetail` 或等价统一结构，并包含稳定业务错误码。 |
| SPR-010 | 入站边界必须使用 Bean Validation 或等价校验；Domain 仍必须维护自己的业务不变量。 |
| SPR-011 | `@Transactional` 必须位于 Application 用例边界或明确的持久化操作边界，范围尽量短。 |
| SPR-012 | 禁止依赖同类 self-invocation 触发 `@Transactional`、`@Async`、缓存或安全代理。 |
| SPR-013 | 远程调用禁止无依据放在数据库事务中；确需如此必须说明锁持有、超时和恢复影响。 |
| SPR-014 | 事务传播与隔离级别必须基于不变量选择，禁止用 `REQUIRES_NEW` 掩盖错误的业务边界。 |
| SPR-015 | JPA 与 MyBatis 不设全局默认优先级；项目必须按聚合、查询、团队能力和数据库特性选择并记录。 |
| SPR-016 | 使用 JPA 时必须控制 Aggregate 边界、加载策略和 N+1；禁止将 Entity 直接作为 API DTO。 |
| SPR-017 | 使用 MyBatis 时 SQL、映射、分页和动态条件必须可测试；禁止字符串拼接用户输入。 |
| SPR-018 | Spring Data Repository 必须只作为出站 Adapter 细节；Domain/Application 不得依赖其接口。 |
| SPR-019 | 异步方法必须定义执行器、队列、拒绝策略、上下文传播和关闭行为；禁止使用无界默认执行器。 |
| SPR-020 | 定时任务必须具备稳定任务身份、幂等、并发控制、错过执行策略和运行证据。 |
| SPR-021 | 缓存注解只能优化读取；缓存键、TTL、失效、穿透和一致性策略必须明确。 |
| SPR-022 | Spring Security 必须默认拒绝，公开端点显式列举；方法级权限不能替代入口层防护。 |
| SPR-023 | 认证主体、租户和权限上下文必须显式传播并在异步边界验证，禁止相信客户端自报身份。 |
| SPR-024 | Actuator 只暴露运行所需的最小端点；敏感端点必须认证、授权并与业务流量隔离。 |
| SPR-025 | 健康检查必须区分 liveness（存活）与 readiness（就绪）；短暂下游故障不得无依据触发进程重启。 |
| SPR-026 | 启动日志和配置端点禁止输出秘密；配置来源优先级必须可审计。 |
| SPR-027 | 测试切片应匹配被测边界；禁止用全量 `@SpringBootTest` 替代所有单元和组件测试。 |
| SPR-028 | `@MockBean` 等框架替身只用于边界隔离；关键序列化、事务和数据语义必须由真实组件测试证明。 |
| SPR-029 | Spring Cloud 默认不启用；启用时必须采用选定 Spring 基线登记的兼容 Release Train，并在项目接入记录中固定具体补丁版本。 |
| SPR-030 | Spring Boot 或 Cloud 升级必须核查配置迁移、自动配置、端点、安全默认值、依赖树和原生镜像影响。 |

## 8. API 与事件 Contract（API）

未知字段兼容矩阵必须按边界裁决：HTTP 请求由 Schema 决定开放或关闭；HTTP 响应消费者忽略未知的非关键扩展；事件消费者容忍新增可选字段；安全、签名、权限和幂等载荷默认使用关闭字段集。禁止用同一个全局开关替代边界设计。

| Id | 规则 |
| --- | --- |
| API-001 | 每个公开 API 或事件必须有 Owner、用途、调用方、版本和机器可校验的 Schema。 |
| API-002 | Contract 必须从 Domain 类型分离，禁止直接公开 Persistence Entity、供应商 DTO 或内部枚举。 |
| API-003 | 兼容性默认采用向后兼容的新增；删除、重命名、收紧约束或改变语义必须走版本迁移。 |
| API-004 | 字段名称、单位、可空性、默认值和枚举未知值策略必须明确，禁止由调用方猜测。 |
| API-005 | 错误响应必须包含稳定错误码、可读摘要和关联标识；禁止把堆栈、SQL 或内部类名暴露给调用方。 |
| API-006 | HTTP 状态码只表达协议结果，业务最终状态必须由稳定字段或查询 Contract 表达。 |
| API-007 | 列表接口必须有确定排序和有界分页；游标必须不可伪造或经过完整校验。 |
| API-008 | 时间点使用 UTC ISO-8601；日历日期单独表达；需要地域解释时必须传递 ZoneId。 |
| API-009 | 金额必须使用十进制字符串或最小货币单位，并同时传递 ISO 4217 币种；禁止二进制浮点。 |
| API-010 | 创建或副作用操作应支持稳定幂等键；键的作用域、保留期和冲突语义必须写入 Contract。 |
| API-011 | 同一幂等键与相同规范化载荷必须重放同一业务结果，不得重复执行副作用。 |
| API-012 | 同一幂等键与不同载荷必须返回明确冲突，禁止覆盖原请求或当作新请求执行。 |
| API-013 | 客户端超时只说明结果未知，不等于业务失败；Contract 必须提供安全查询或重试路径。 |
| API-014 | 重试必须只针对明确可重试错误并使用退避、抖动和截止时间；禁止无限重试。 |
| API-015 | 批量 API 必须定义原子性、逐项结果、最大数量和部分失败语义。 |
| API-016 | 事件必须包含事件 Id、类型、Schema 版本、发生时间、生产者和业务关联标识。 |
| API-017 | 事件消费者必须容忍重复与允许的字段新增；禁止依赖未声明的消息顺序。 |
| API-018 | Contract 变更必须执行消费者驱动或等价兼容性测试，并保留受影响调用方清单。 |
| API-019 | 对外限流必须返回可识别信号和合理重试提示；限流不能改变已受理业务事实。 |
| API-020 | API 文档必须由 Contract 源生成或与其自动比对；禁止长期维护不可验证的手写副本。 |
| API-021 | HTTP 请求对象必须在 Schema 中明确是否允许未知字段；安全、签名、权限、金额和幂等载荷默认拒绝未知字段。 |
| API-022 | HTTP 响应消费者必须忽略未知的非关键扩展字段；RFC 9457 扩展成员不得因客户端不认识而导致整体解析失败。 |
| API-023 | 事件新增字段必须默认可选且具有兼容默认语义；未知枚举值的拒绝、保留或降级策略必须写入 Contract。 |
| API-024 | OpenAPI、AsyncAPI 或 JSON Schema Contract 必须固定具体规范版本和 dialect；禁止引用浮动 latest 或由工具默认值决定语义。 |
| API-025 | 公开 Contract 登记必须包含 Owner、Producer/Consumer、版本、可见性、Schema 身份、兼容策略、幂等键、顺序键和测试来源。 |

## 9. 数据、事务与一致性（DATA）

| Id | 规则 |
| --- | --- |
| DATA-001 | 数据模型必须声明 Fact Owner、生命周期、保留要求、敏感级别和恢复目标。 |
| DATA-002 | 每次 Schema 变更必须使用版本化 Migration 单向演进；单向表示已执行版本不可改写，不等于每次都必须提供破坏性反向 DDL。禁止生产环境手工漂移。 |
| DATA-003 | 扩展与收缩必须采用 Expand、Backfill、Contract 或等价阶段兼容旧代码和新代码；破坏性删除必须在读取、写入和回滚窗口关闭后执行。 |
| DATA-004 | Migration 必须在代表性数据规模上验证锁、耗时、磁盘、复制和恢复策略；默认通过前滚修复、新 Migration、补偿或受控恢复处理数据问题。 |
| DATA-005 | 数据库事务必须与单一业务不变量边界对齐；禁止为方便把远程系统纳入伪原子事务。 |
| DATA-006 | 并发更新必须选择锁、版本号/CAS、唯一约束或串行化策略，并测试丢失更新。 |
| DATA-007 | 唯一性和引用完整性等关键不变量必须尽可能由数据库约束和 Domain 双重保护。 |
| DATA-008 | 查询必须有确定顺序、受控结果集和索引证据；禁止无界读取生产大表。 |
| DATA-009 | 分页、批处理和清理必须使用稳定键；禁止依赖不稳定偏移遍历变化中的数据集。 |
| DATA-010 | Outbox 必须与业务事实在同一数据库事务写入，并具有稳定消息 Id、投递状态和清理策略。 |
| DATA-011 | Inbox 或等价去重必须以消息 Id 和消费者作用域记录处理结果，支持重复投递。 |
| DATA-012 | 消息系统默认按至少一次投递设计；禁止在无端到端证据时宣称 exactly-once 业务语义。 |
| DATA-013 | 消费确认必须发生在业务结果持久化后；失败、重试、死信和人工恢复必须可追踪。 |
| DATA-014 | 消息顺序只能在明确分区键范围内依赖；跨分区不变量必须使用其他协调机制。 |
| DATA-015 | 禁止将缓存作为事实源；缓存丢失、过期或重建不得破坏正确性。 |
| DATA-016 | 缓存必须定义键空间、Owner、TTL、失效、容量、穿透和热点保护策略。 |
| DATA-017 | 读副本和搜索索引的延迟必须对调用方可解释；需要读己之写时必须选择正确数据源。 |
| DATA-018 | 数据修复、Backfill 和重放必须可暂停、限速、审计、幂等并有精确目标范围。 |
| DATA-019 | 备份必须加密、校验和定期恢复演练；只有备份成功记录不能证明可恢复。 |
| DATA-020 | 恢复流程必须声明 RPO、RTO、顺序、校验、回切和业务对账，且保留演练证据。 |
| DATA-021 | 审计记录必须追加式保存主体、动作、对象、结果、时间和关联标识；禁止普通业务流程覆写。 |
| DATA-022 | 数据删除必须满足保留、法务和审计约束，并区分逻辑删除、物理删除和匿名化。 |
| DATA-023 | 多租户数据必须在入口、查询、缓存、消息和审计全链路携带并校验租户边界。 |
| DATA-024 | 测试数据和生产数据必须隔离；禁止把生产秘密或未脱敏个人数据复制到开发环境。 |
| DATA-025 | 数据语义变更必须附 Schema、Migration、兼容窗口、验证查询、回退或前滚方案和 Owner 批准。 |
| DATA-026 | 只有经代表性数据验证且不会丢失新事实时才允许物理反向 Migration；否则必须保持 Schema 向后兼容并采用前滚方案。 |
| DATA-027 | 调用方禁止持有跨 Fact Owner 调用的写事务；接收方本地事务提交后，调用方失败不得假定能够回滚已经提交的对方事实。 |
| DATA-028 | 跨 Owner 外部 I/O 应位于本地数据库事务之外；确需事务内调用时必须证明锁持有、超时、幂等和恢复边界。 |

## 10. 安全（SEC）

| Id | 规则 |
| --- | --- |
| SEC-001 | 系统必须建立资产、信任边界、主体、威胁和数据分级；安全控制应与风险相称。 |
| SEC-002 | 所有外部输入必须在可信边界前验证长度、类型、格式、范围和语义；拒绝未知关键字段。 |
| SEC-003 | 认证与授权必须分离；每次敏感操作都必须按服务端事实验证权限，默认拒绝。 |
| SEC-004 | 服务、数据库、消息、存储和 CI 身份必须遵循最小权限，禁止共享长期管理员凭证。 |
| SEC-005 | 秘密必须来自批准的秘密管理系统，禁止写入源码、镜像、日志、异常、URL 或普通配置文件。 |
| SEC-006 | 秘密必须支持轮换、吊销和访问审计；轮换失败应有安全回退而非继续使用未知凭证。 |
| SEC-007 | SQL、命令和模板必须参数化；禁止拼接不可信输入形成可执行语句。 |
| SEC-008 | 禁止反序列化不可信 Java 原生对象或启用无约束多态；允许类型必须显式列举。 |
| SEC-009 | 密码必须使用当前批准的慢速自适应 Hash（如 Argon2id、bcrypt 或 scrypt）并独立加盐；禁止可逆加密。 |
| SEC-010 | 传输中的敏感数据必须使用受支持的 TLS；证书校验、主机名校验和信任库不得关闭。 |
| SEC-011 | 静态敏感数据必须按分级加密，密钥与数据分离管理；算法和密钥版本必须可轮换。 |
| SEC-012 | 日志、指标、Trace 和审计必须脱敏；令牌、密码、密钥和完整个人敏感信息禁止输出。 |
| SEC-013 | 错误对外必须最小披露，对内保留关联证据；禁止通过不同错误细节泄露账号或资源存在性。 |
| SEC-014 | 文件上传必须限制类型、大小、名称和存储位置，并进行内容检测；禁止信任客户端 MIME。 |
| SEC-015 | 出站网络访问必须限制目标、协议、重定向和 DNS 风险，防止 SSRF 与内部资源探测。 |
| SEC-016 | 依赖必须锁定、持续扫描并评估可利用性；高风险漏洞必须有修复、缓解或批准的限时例外。 |
| SEC-017 | 构建必须生成并保存 SBOM、依赖来源和制品校验身份；签名要求由交付风险决定。 |
| SEC-018 | 安全相关配置缺失、验证失败或权限不明时必须 fail closed（默认关闭），禁止自动放行。 |
| SEC-019 | 关键安全行为必须有滥用、越权、重放、并发和降级测试；只测正常路径不构成验收。 |
| SEC-020 | 安全事件响应必须定义检测、隔离、证据保全、通知、恢复和复盘 Owner。 |
| SEC-021 | Maven Wrapper、容器化构建镜像、CI Action 和生成器必须固定不可变身份并验证来源完整性；托管 Runner 无法固定镜像 Digest 时，必须固定 OS 家族标签并记录实际镜像版本，禁止使用 `*-latest`；仅有下载校验和不能替代来源信任。 |
| SEC-022 | CI 工作流必须显式声明最小权限；第三方 GitHub Action 必须固定完整 Commit SHA，并通过受控更新流程接收安全修复。 |
| SEC-023 | 普通项目必须至少生成 SBOM、依赖来源和制品 Hash；对外发布或高风险系统应当增加签名来源证明、不可变制品和隔离构建。 |
| SEC-024 | 秘密扫描必须覆盖提交前、CI 和历史泄露处置；发现真实秘密后必须轮换或吊销，禁止只删除文本后宣称关闭。 |

## 11. 可观测性（OBS）

| Id | 规则 |
| --- | --- |
| OBS-001 | 应用日志必须结构化，至少包含时间、级别、服务、环境、事件名和关联标识。 |
| OBS-002 | Correlation Id 与 Trace 上下文必须跨 HTTP、消息和异步任务传播，并在不可信入口重新校验。 |
| OBS-003 | 日志必须描述可行动事实，禁止在高频正常路径输出大对象或重复堆栈。 |
| OBS-004 | 指标名称、单位、Owner 和业务含义必须稳定；标签禁止使用用户 Id、订单 Id 等无界高基数值。 |
| OBS-005 | 必须覆盖请求量、错误、延迟、饱和度，并为关键业务状态提供可对账指标。 |
| OBS-006 | Trace 采样策略必须保留错误和关键流程证据；采样变化不得无声造成审计缺口。 |
| OBS-007 | 审计日志与诊断日志必须区分存储、访问和保留策略，禁止把普通日志当作唯一审计证据。 |
| OBS-008 | 告警必须有 Owner、阈值依据、影响、运行手册和抑制策略；禁止对不可行动噪声告警。 |
| OBS-009 | SLI/SLO 必须从用户可感知结果定义，禁止只用 JVM 存活代表业务可用。 |
| OBS-010 | 外部依赖调用必须记录目标类别、结果、耗时、超时和重试次数，不得记录秘密或完整敏感载荷。 |
| OBS-011 | 异步与批处理必须暴露积压、吞吐、最老任务年龄、失败和重试状态。 |
| OBS-012 | 数据一致性流程必须提供 Outbox/Inbox 延迟、死信、对账差异和恢复进度指标。 |
| OBS-013 | 可观测数据时间戳必须可比较，主机时钟应同步；时钟异常必须可检测。 |
| OBS-014 | Dashboard 和告警配置必须版本化并通过 Review；手工生产修改必须回写 Authority。 |
| OBS-015 | 故障复盘必须把症状、业务影响、时间线、根因、恢复和防复发行动关联到证据。 |

## 12. 测试（TEST）

| Id | 规则 |
| --- | --- |
| TEST-001 | 测试策略必须按 Domain 单元、组件、Contract、集成和端到端分层，优先使用快速确定性测试。 |
| TEST-002 | 每个关键用例必须有稳定 Case Id 或可追踪名称，关联 Authority、规则和验收结果。 |
| TEST-003 | 行为变更必须先形成能够失败的测试或检查（RED），再实施并证明 GREEN。 |
| TEST-004 | 测试必须遵循 Arrange-Act-Assert 或等价清晰结构，一次测试聚焦一个可命名行为。 |
| TEST-005 | Domain 测试必须直接构造纯 Java 对象，禁止为测试业务规则启动 Spring。 |
| TEST-006 | 时间测试必须使用固定或可控 `Clock`，禁止 `Thread.sleep` 和依赖真实当前时间。 |
| TEST-007 | 随机测试必须记录 seed；并发测试必须有截止时间且能输出失败交错证据。 |
| TEST-008 | 数据库专属事务、约束、锁、SQL 和类型语义必须用真实目标数据库或兼容容器验证。 |
| TEST-009 | 禁止用 H2 证明 PostgreSQL、MySQL、Oracle 等数据库专属语义；H2 只可用于与目标无关的轻量测试。 |
| TEST-010 | 消息投递、顺序、重复、确认和死信语义必须使用真实中间件或高保真容器验证。 |
| TEST-011 | 第三方服务可以用 Stub 验证本方行为，但关键 Contract 必须有沙箱、录制或提供方测试证据。 |
| TEST-012 | API 和事件必须执行 Schema 及兼容性 Contract 测试，包含未知字段、缺失字段和版本演进。 |
| TEST-013 | 模块依赖方向、Domain 纯净性、Context 隔离和循环依赖必须用 ArchUnit 或等价工具检查。 |
| TEST-014 | 事务测试必须验证提交、回滚、异常转换和代理边界，禁止只检查 Mock 调用次数。 |
| TEST-015 | 幂等测试必须覆盖同键同载荷、同键不同载荷、并发重复和首次结果未知后的重试。 |
| TEST-016 | 并发测试必须覆盖丢失更新、重复处理、锁超时、CAS 冲突和可接受的最终状态集合。 |
| TEST-017 | 恢复测试必须覆盖进程中断、消息重投、部分写入、Backfill 重启和人工接管。 |
| TEST-018 | 安全测试必须覆盖未认证、越权、租户穿透、注入、敏感输出和安全配置缺失。 |
| TEST-019 | 性能测试必须使用代表性数据、并发和依赖延迟，报告分位数、资源和瓶颈，不只报告平均值。 |
| TEST-020 | 测试数据必须由 Builder/Fixture 明确创建并相互隔离，禁止依赖测试执行顺序。 |
| TEST-021 | Flaky 测试不得简单重跑后忽略；必须隔离影响、保留证据并指定修复 Owner 和期限。 |
| TEST-022 | 覆盖率只能发现未执行区域，禁止作为正确性的唯一结论；阈值不得驱动无意义断言。 |
| TEST-023 | Mock 应只位于真正边界；禁止 Mock 被测对象内部实现来证明自身行为。 |
| TEST-024 | 缺陷修复必须加入最小回归用例，并在适当层级补充同类风险的系统性检查。 |
| TEST-025 | 交付测试证据必须对应当前 Candidate、命令、环境、通过数、失败数和跳过项。 |

## 13. Maven 与构建（BUILD）

| Id | 规则 |
| --- | --- |
| BUILD-001 | 项目必须提交 Maven Wrapper 并使用选定基线的 Maven 版本、分发 URL、分发校验和及两脚本内容身份；`mvnw` 必须匹配原始字节 SHA-256，`mvnw.cmd` 的全 LF 或全 CRLF 表示必须匹配同一 canonical-LF SHA-256。CI 和本地必须先验真两脚本，再使用 `./mvnw`。 |
| BUILD-002 | Java 编译必须设置选定基线的 `maven.compiler.release`，禁止只设置 source/target 而遗漏标准库约束。 |
| BUILD-003 | 引入 Spring 时必须导入选定 Spring 基线的 Boot BOM；禁止无依据单独覆盖 Spring Framework。 |
| BUILD-004 | Plugin 版本必须集中固定，禁止依赖 Maven Super POM 或父链中的浮动隐式版本。 |
| BUILD-005 | Maven Enforcer 必须按选定基线限制 Maven 和 Java 范围，并检查依赖收敛、发布依赖、Plugin 版本和 Reactor 一致性。 |
| BUILD-006 | Surefire 必须只执行单元/组件测试命名集；Failsafe 必须执行 `integration-test` 与 `verify` 阶段的集成测试。 |
| BUILD-007 | Spotless 必须使用选定基线固定的 google-java-format 并禁止通配符导入；格式检查进入 CI。 |
| BUILD-008 | Dependency Plugin 应执行 `analyze-only`；未使用或未声明依赖必须修复或局部说明。 |
| BUILD-009 | 依赖 Scope 必须最小化；测试、编译时处理器和运行时依赖禁止无依据泄露到消费者。 |
| BUILD-010 | SNAPSHOT 和动态版本禁止进入发布分支；版本范围仅在有明确消费者策略时使用。 |
| BUILD-011 | 多模块构建必须由单一聚合入口驱动；首次 Maven 前必须递归解析实际 raw POM 的直接 `<modules><module>`，拒绝 Profile Module、非 canonical/重复/循环 Module、缺失或非普通 POM、符号链接及越界路径，并要求发现集合与 `code-quality.yaml.reactorModules` 完全相等。模块顺序由依赖图决定，禁止脚本硬编码顺序。 |
| BUILD-012 | 构建必须固定源码编码、报告编码和 `project.build.outputTimestamp` 等可复现输入。 |
| BUILD-013 | 生成源码必须有固定生成器、输入和输出目录，并在编译前可重建；禁止手工编辑。 |
| BUILD-014 | 制品必须包含版本、Commit 和构建身份，但不得把秘密或个人路径写入产物。 |
| BUILD-015 | 编译和测试警告必须可见；禁止全局静默警告或通过宽泛 suppress 掩盖风险。 |
| BUILD-016 | `-DskipTests`、`maven.test.skip` 或忽略失败的构建结果禁止作为验收证据。 |
| BUILD-017 | 构建缓存只能优化执行；缓存键必须覆盖影响输出的源码、工具链和配置。 |
| BUILD-018 | 依赖仓库和镜像必须使用批准来源、TLS 与凭证隔离；禁止从任意 HTTP 仓库下载。 |
| BUILD-019 | 发布制品必须生成校验和、依赖清单/SBOM，并按风险执行签名和来源证明。 |
| BUILD-020 | 工具链升级必须在独立候选验证依赖树、编译、测试、打包和运行时兼容后再修改活动基线。 |
| BUILD-021 | Wrapper 验收必须分别检查属性文件中的 Maven 分发版本、HTTPS URL、分发 SHA-256，以及基线固定的 `mvnw` 原始字节 SHA-256 与 `mvnw.cmd` canonical-LF SHA-256，再执行实际 `./mvnw --version`；`.cmd` 只允许全 LF 或全 CRLF 的等价表示，分发完整性不能替代脚本身份。 |
| BUILD-022 | 可复现构建不能只设置 `outputTimestamp`；发布候选必须在独立干净环境比较制品内容或使用等价可重复性验证。 |
| BUILD-023 | 基线继承、Profile 兼容、参考 POM 和模板版本必须由控制库验证器自动比对；禁止依靠人工全文搜索维持一致。 |
| BUILD-024 | Maven 仓库校验和只证明传输完整性；高风险依赖还必须验证批准来源、签名或其他来源证明。 |

## 14. 交付与运维（DEL）

| Id | 规则 |
| --- | --- |
| DEL-001 | 提交应当使用 Conventional Commits 或项目批准的等价格式，一个提交只承载一个可解释职责。 |
| DEL-002 | 每次变更必须声明 Exact WriteSet，提交前核对实际路径；禁止夹带无关修改。 |
| DEL-003 | Review 必须检查 Authority、业务语义、边界、失败路径、安全、数据、测试和回退，不只检查格式。 |
| DEL-004 | CI 必须从干净检出使用 Wrapper 执行格式、编译、测试、架构、依赖和制品检查。 |
| DEL-005 | 任何跳过、隔离或预期失败项必须在交付证据中列出 Owner、影响和关闭条件。 |
| DEL-006 | 发布必须绑定不可变版本、Commit、Tree、制品校验和、配置版本和批准记录。 |
| DEL-007 | 部署必须区分构建、发布和上线授权；构建成功不自动授权部署或流量切换。 |
| DEL-008 | 配置变更必须版本化、Review、验证并可回退；秘密值不得出现在普通差异和回执中。 |
| DEL-009 | 数据库 Migration 必须在应用兼容窗口内独立门禁；禁止把不可逆 DDL 隐藏在应用启动中。 |
| DEL-010 | 上线前必须说明健康指标、观察窗口、停止条件和回退触发器；高风险变化应灰度。 |
| DEL-011 | 回滚必须包含代码、配置、数据和消息兼容性；不能安全回滚时必须提供可验证前滚方案。 |
| DEL-012 | Runbook 必须覆盖启动、停止、扩缩容、依赖故障、积压、恢复、对账和升级路径。 |
| DEL-013 | 事故期间的紧急修改仍必须保留 Authority、WriteSet、审查和事后补证，禁止长期留在隐式状态。 |
| DEL-014 | 目标项目阶段关闭必须保存当前 Candidate、Parent、Tree、工作区、验证和未决风险，禁止使用历史证据替代。java-engineering-standard 只校验收到的 Java Quality Evidence 是否绑定实际 Commit/Tree 和真实输出，不能替目标项目关闭 Stage。 |
| DEL-015 | 未经明确授权禁止 Push、发布、部署、生产数据库写入、删除或其他不可逆外部动作。 |
| DEL-016 | Review 必须选择能够裁决相关 Owner、Contract、数据或安全边界的审查者；高风险变更禁止由作者独自批准。 |
| DEL-017 | 变更应拆成可独立理解和验证的职责；禁止用超大差异隐藏无关修改，也禁止为追求小提交破坏原子语义。 |
| DEL-018 | GitHub Actions 或等价 CI 配置变更必须检查权限、不可变依赖身份、秘密暴露、非可信输入和制品上传边界。 |

## 15. Agent 与自动生成（AI）

| Id | 规则 |
| --- | --- |
| AI-001 | Agent 开始工作前必须读取项目 `AGENTS.md`、Authority、Contract、接入记录、活动基线和有效例外。 |
| AI-002 | Agent 必须区分设计、只读调查、实现、Review、发布、部署和外部写入授权；前一阶段不自动授权后一阶段。 |
| AI-003 | Agent 必须先确定 Owner、风险、Exact WriteSet、验证和回退，再修改文件。 |
| AI-004 | 禁止臆造 Domain、Fact Owner、Contract、Schema、状态机、数据、秘密或部署环境。 |
| AI-005 | 信息缺失时必须标记 `MISSING_EVIDENCE` 并收集安全的只读证据；不能用常见做法冒充项目事实。 |
| AI-006 | 项目 Authority 与本规范冲突时必须标记 `CONFLICT`，列出具体规则、证据和需要裁决的 Owner。 |
| AI-007 | 外部 Skill、README、搜索结果和示例不是 Authority；只可作为方法建议并必须经过项目证据验证。 |
| AI-008 | 禁止把加载或推荐 Skill 解释为代码修改、数据库操作、部署、Push、消息发送或不可逆动作的授权。 |
| AI-009 | Agent 必须保护用户已有和写集外修改，禁止覆盖、回滚、删除或纳入自己的提交。 |
| AI-010 | 生成代码、配置、Migration、测试和文档必须接受与人工产物相同的格式、测试、安全和 Review 门禁。 |
| AI-011 | Agent 必须先运行能够证伪当前改动的最小检查，候选稳定后再运行阶段完整门禁。 |
| AI-012 | 失败不得通过删除测试、放宽断言、跳过门禁或扩大权限解决；必须定位根因或明确阻断。 |
| AI-013 | Agent 报告必须区分已实施、已验证、未验证、仅静态检查和未授权动作，禁止乐观推断。 |
| AI-014 | Agent 形成提交前必须核对实际 WriteSet 和当前差异，阶段关闭时固定 Candidate、Parent 与 Tree。 |
| AI-015 | Skill 可以输出 `APPLICABLE`、`NOT_APPLICABLE`、`CONFLICT` 或 `MISSING_EVIDENCE` 作为规则适用性分析，并必须单独输出 `AUTHORIZATION=PROJECT_OWNED|NOT_EVALUATED`。规则适用不等于行为授权；项目 Authority 决定实施、合入和发布。 |
| AI-016 | Agent 使用外部 Skill 前必须记录不可变版本或 Commit、许可证、能力、所需权限、采用范围和复核日期；安装量、Star 和排名不能证明适用性。 |
| AI-017 | Agent 进行架构工作时必须读取项目模块边界登记；登记缺失时可以提出模板，但不得从包名、Artifact Id 或 Runtime 名称臆造 Fact Owner。 |

## 16. 采用建议

新项目应优先采用 `modular-monolith` 主 Profile；纯复用组件选择 `library`，有独立部署证据时选择 `microservice`，面向大批量可恢复处理时选择 `batch`。一个项目只能有一个主 Profile，可以叠加与实际职责相符的附加 Profile。项目小版本差异必须通过接入记录、项目基线或兼容矩阵表达；当前例外策略没有开放任何可例外规则。

纯 Java 项目优先选择 `java21-maven3`；Spring 项目选择 `java21-spring35-maven3`。精确版本、过渡 JDK 有效期和兼容 Profile 以基线与 `compatibility/baseline-matrix.yaml` 为准。Java 25、Spring Boot 4、Maven 4 和 JUnit 6 必须在独立基线完成兼容评估后再采用。
