# Java Engineering Capability Pack Agent 规则

## 0. Canonical Naming

```text
PROJECT_PACK_NAME=java-engineering-standard
SKILL_NAME=java-engineering-standard
DISPLAY_NAME=Java Engineering Capability Pack
CANONICAL_CAPABILITY_ID=UNASSIGNED
CANONICAL_CAPABILITY_ID_OWNER=omini-harness
REGISTRATION_STATUS=NOT_REGISTERED
```

- 项目目录、Pack 机器名和 Skill 名统一为 `java-engineering-standard`；显示名称只用于面向人的标题和说明。
- `CANONICAL_CAPABILITY_ID=UNASSIGNED` 表示当前没有可从本仓库 Authority 唯一推导的 omini Capability Id；禁止将占位值解释为保留、注册、采用、安装或运行时投影。
- `REGISTRATION_STATUS=NOT_REGISTERED` 只描述当前未接入 omini 的事实，不是 omini Registry 的 `lifecycle` 或 `validity` 字面值。
- `java-spec` 仅作为 0.4.0 兼容协议命名空间保留，包括 Schema `$id`、Adapter Id、`target/java-spec-quality/**`、`JAVA_SPEC_*` CI 变量和历史材料；不得再把它声明为当前项目、目录、Pack 或 Skill 名。

## 1. Authority 与适用范围

- 本文件约束本仓库中的人员与 Agent，不替代下游项目的业务 Authority（权威依据）。
- 本仓库定义 Java 规则、Profile、Baseline、输入 Contract、Runner、模板、Skill 和自验证；不拥有下游项目采用、Task/Stage、合入或发布裁决。
- Java Project Profile、Java Quality Config 和 Java Quality Evidence 是 0.4.0 唯一当前执行 Contract；`project-adoption/v1` 只允许保留在历史与迁移材料中。
- `JAVA-DEVELOPMENT-STANDARD.md` 是通用规则的唯一正文，优先级高于 `profiles/*.md`；Profile 只能增加项目类型约束，不得复制、改写或静默放宽主规范。
- 精确版本以 `VERSION`、活动 `baselines/*.yaml` 和 `compatibility/baseline-matrix.yaml` 为准。README、模板、示例和外部资料不是版本或规则 Authority。
- 下游项目的业务 Authority 决定业务事实、实施、合入和发布；若与通用规范冲突，必须记录具体规则、证据和处置，不得静默选边。
- 例外资格以 `policies/exception-policy.yaml` 为准；未列入 `eligibleRules` 的规则禁止例外。例外记录仍必须包含 Owner、范围、风险、补偿控制、证据、期限和退出条件。

## 2. 中文和英文术语

- 标题、规则、原因、例外和验收标准以中文为主。
- `Domain`、`Port`、`Adapter`、`Bounded Context`、`Aggregate`、`Value Object`、`Repository`、`Contract`、`Authority`、`WriteSet` 等行业术语可以保留英文，首次出现时附简短中文解释。
- 规则等级只使用“必须”“应当”“可以”“禁止”。除产品名、标识符、命令和配置外，不写无必要的整段英文说明。

## 3. 变更分级

- R0：拼写、排版、链接等不改变规则语义和产物身份的可逆修改。
- R1：规则语义、规范版本、Profile 增量规则或来源采用结论的修改；必须说明影响面并执行直接相关检查。
- R2：Authority、活动基线、模板、仓库级 Skill、发布、部署、Push 或不可逆动作；必须使用精确 WriteSet，完成强验证并固定候选身份。
- 机器接入、模块边界、兼容矩阵、例外策略、Registry、Schema 和 CI 模板均属于 R2 治理工件。
- 无法证明为较低风险时按更高等级处理。项目内更严格的 Authority 和门禁优先。

## 4. 精确 WriteSet

- 修改前必须列出 Exact WriteSet（精确写集），明确每个路径的唯一职责。
- 禁止顺手修改写集外文件；发现无关工作区变化时必须保留并隔离，不能覆盖、回滚或纳入提交。
- 主规范、基线、Profile、模板和 Skill 通过规则 Id、规范版本和基线 Id 对齐，不通过复制正文对齐。

## 5. 验证和证据

- 每次修改必须运行最接近变更的格式、语法、结构和链接检查，并执行 `git diff --check`。
- 涉及规范、基线、Profile、Schema、Registry 或模板时，必须运行 `ruby scripts/test_validate_standard.rb` 和 `ruby scripts/validate-standard.rb`。
- 行为或工具模板变化应提供可复现的聚焦验证；静态 XML 检查不得表述为 Maven 构建通过，文本检查不得表述为 Java 编译或 Spring 启动通过。
- 本仓库候选关闭必须报告当前 Candidate、Parent、Tree、实际 WriteSet、工作区状态和本轮验证结果；下游项目阶段关闭仍由项目 Authority 负责，Java Quality `VALID` 不能替代任务完成。

## 6. 外部 Skill 与来源

- 外部 Skill、GitHub 仓库、博客和搜索结果只能提供方法与参考，不能作为本仓库或下游项目的 Authority。
- 引入外部建议前必须在来源登记中记录核验日期、采用范围和限制；不得因外部示例臆造 Domain、Contract、Schema、状态机或授权结论。
- 仓库级 Skill 只规定读取与判定流程，加载 Skill 本身不授予代码、数据库、部署、Push 或不可逆操作权限。

## 7. 本地提交与禁止动作

- 每个职责单一的任务创建本地 Commit，并在提交前核对实际 WriteSet。
- 禁止自动执行 `git push`、发布 Maven 制品、部署、修改其他项目或安装外部 Skill。
- 未获得明确授权时，禁止数据库写入、删除、迁移、远程配置修改以及其他不可逆外部动作。
