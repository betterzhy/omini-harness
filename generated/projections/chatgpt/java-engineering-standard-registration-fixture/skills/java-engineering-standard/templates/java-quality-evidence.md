# Java Quality Evidence 模板

该模板故意以 `MISSING_EVIDENCE` 开始，不包含伪造 Commit、Tree 或 Hash。目标项目必须把 null 项替换为当前候选的真实身份、输出引用和 SHA-256，且目标工作树不能存在非忽略改动，才能请求 `JAVA_QUALITY_RESULT=VALID` 校验。

Evidence 只描述 Java Profile 和质量检查结果。它不包含项目审批、`TASK_COMPLETE`、`MERGE_ALLOWED` 或 `RELEASE_ALLOWED`，也不把 shell 字符串交给 java-engineering-standard 执行。

请求 `JAVA_QUALITY_RESULT=VALID` 时，`moduleReports` 必须与 Quality Config 的每个 Source Module 一一对应：Effective POM 使用 `target/java-spec-quality/effective-poms/<module>/effective-pom.xml`，三类原始报告路径必须等于 Config 登记路径。`checks.normalizedFindings` 必须按 `checkstyle`、`pmd`、`spotbugs` 精确提供三份固定 Adapter 输出；每份 JSON 绑定相同 subject Commit、完整 Reactor、实际原始报告 SHA-256 和 Config 的 Finding Adapter SHA-256。Validator 会从固定 Commit 重放 Finding Adapter，并要求重放结果与 Evidence 逐结构相等。Source Layout 与 suppression receipt 必须使用已登记执行身份和可解析的确定性 JSON。Ratchet 还必须绑定与 Quality Config 相同的真实 Baseline path/hash，使用精确 argv，并得到与重算结果一致的 `BASELINE_MATCH`、`newFindings: 0`、`staleFindings: 0`。

Validator 会先完成项目与 Wrapper 静态 trust，再用固定 argv 重放自身 Ruby 和当前 `JAVA_HOME/bin/java`；它解析 Maven 输出但绝不执行目标 Wrapper。四个质量工具必须绑定同一稳定项目 `commandRef` 和一份含固定插件执行标记与 `BUILD SUCCESS` 的完整 Maven build output，逐 Module 报告的 root/version 必须匹配 Baseline，Error Prone 必须在 plugin 与 compile/testCompile execution annotation-processor path 一致。Validator 还会精确核对 Wrapper version/type/url/SHA，重放 Source Layout、Suppression Scan 与 Finding Adapter，并在读取前后复核目标 Candidate 身份和清洁度。它会拒绝缺 Module/工具、路径漂移、任意文本伪输出、错误位置/执行级 override 的 Error Prone 身份、DTD/Entity、symlink/hardlink、超限输出、Hash 漂移，以及 `JAVA_PROFILE_RESULT=INVALID` 与 Quality VALID 的矛盾组合。VALID 只表示供应的 hash-bound Evidence 符合 Pack，不是签名执行证明；目标项目仍拥有 workflow 执行和输出真实性。
