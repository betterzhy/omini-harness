# Agent Design Evolution Repository Bootstrap MVP — Implementation Report

**MVP Version:** `0.1.0`  
**Execution Date:** `2026-08-11`  
**Target State:** `DESIGN_EVOLUTION_ENGINEERING_MVP = CLOSED` for this executable bootstrap package  
**Brownfield Source Migration:** `DEFERRED` until the original richer Continuous Learning checkout is available

## 1. Executive Result

本轮已经从 CLOSED 的 Engineering Architecture 落地出一套真实、可执行、可删除重建、可通过 CLI/CI 验证的 Unified Evolution Workspace：

```text
core/
design/
engineering/
runtime/
tooling/
generated/
```

MVP 已经打通：

```text
Canonical Capability
→ Schema / Identity / Version Validation
→ Generated Registry
→ Generated Active Catalog
→ Project Binding
→ Exact Capability Lock
→ Deterministic Resolver + Explain Trace
→ Resolved Design Context
→ Discussion Contract
→ ChatGPT / Codex Runtime Projection

Experience / Repository Feedback
→ Explicit Triage
→ Candidate Wrapper
→ Eval Result
→ Human Authority Gate
→ Promotion / Generalization / Supersession
→ Canonical Capability
→ Registry / Catalog / Resolver / Projection
```

同时保持以下边界：

```text
Canonical Capability != Runtime Projection
Project Truth != Shared Capability
Experience != Conversation Transcript
Candidate != Fifth Capability Kind
Registry / Catalog / Lock / Resolution / Handoff / Projection != Source Of Truth
Structural CI != Semantic Design Authority
```

## 2. Brownfield Inventory 与迁移结论

当前执行环境没有挂载此前 richer Continuous Learning Repository 的实际 source checkout。因此本轮没有伪造“原地 refactor 已完成”的结论，而是按已有 Bootstrap Contract 重建兼容边界，并形成 migration-ready package。

| Concern | Decision | Physical Result |
|---|---|---|
| Python repository tooling | KEEP / ADAPT | `harness`, `eng`, `src/` |
| Stable Identity / SemVer | EXTRACT / REUSE | `identity.py` |
| Schema / hash / deterministic output mechanics | EXTRACT / REUSE | `schema.py`, `hashing.py`, `generated.py` |
| Lifecycle / validity / provenance | EXTRACT / REUSE | shared metadata + validators |
| Existing engineering manifest | KEEP | `engineering/manifest.yaml` |
| Brownfield registration model | KEEP | `engineering/registrations/` |
| Brownfield canonical artifacts | KEEP IN PLACE | `contracts/`, `policies/`, `verification/`, `skills/` |
| Engineering registry/catalog | KEEP DOMAIN + ADAPT | `engineering/generated/` |
| Design capability domain | ADD | `design/capabilities/` |
| Design learning domain | ADD | `design/learning/`, `design/evals/` |
| Project design control plane | ADD | `.agent-evolution/` |
| Deterministic resolver | ADD | `resolver.py` |
| Runtime projection | ADD | `projection.py` |
| Handoff / feedback | ADD | `handoff.py`, `feedback.py` |
| Duplicate design-only lifecycle stack | REJECT | shared core only |
| Universal mega-schema | REJECT | common metadata + kind payload schemas |

真实 Brownfield merge 时，应保留任何 richer `engineering_cli` 代码，将共用 mechanics 接到 `evolution_harness`，而不是用当前兼容 facade 覆盖已有能力。

## 3. Final Repository Architecture

```text
agent-evolution-harness/
├── core/
│   ├── governance/
│   │   ├── bootstrap-baseline.yaml
│   │   └── promotion-ledger.yaml
│   ├── schemas/
│   └── vocabulary/v1.yaml
├── design/
│   ├── capabilities/
│   │   ├── principles/
│   │   ├── frameworks/
│   │   ├── skills/
│   │   └── workflows/
│   ├── learning/
│   │   ├── experiences/
│   │   └── candidates/
│   ├── evals/
│   └── schemas/
├── engineering/
│   ├── manifest.yaml
│   ├── schemas/
│   ├── registrations/
│   └── generated/
├── runtime/
│   ├── profiles/
│   ├── adapters/chatgpt/
│   ├── adapters/codex/
│   └── templates/
├── tooling/
├── examples/
├── generated/
│   ├── registries/
│   ├── catalogs/
│   └── projections/
├── src/evolution_harness/
├── src/engineering_cli/
├── tests/
├── verification/final/
├── harness
└── eng
```

目录由 responsibility 决定，而不是为了整齐移动 canonical content。

## 4. Schema Decisions

### 4.1 Common Capability Metadata

`core/schemas/common-capability.schema.json` 只结构化机器真正需要的共同字段：

```text
schemaVersion
id
kind
version
title
summary
lifecycle
validity
scope
modelSensitivity
visibility
provenance
relationships
evalBindings
contentFile
```

可选 revalidation metadata：

```text
lastValidatedAt
reviewAfter
revalidationTriggers
```

### 4.2 Principle

最小 structured payload：`invariant` 必填，`exceptions` / `negativeExamples` 可选。Rationale 和长解释保留在 `content.md`。

### 4.3 Framework

最小 structured payload：`dimensions` + `expectedOutputs`。Questions、examples、failure modes、analysis guidance 保留 Markdown。

### 4.4 Skill

结构化：

```text
skillRole = LEAF | ORCHESTRATION
intent
triggers
whenNotToUse
requiredContext
referencedCapabilities
humanGates
outputContract
stopConditions
selfReview
```

Procedure 保留 `content.md`。LEAF 不可组合 Skill；ORCHESTRATION Skill graph 必须无环且最多六个 Skill 依赖/引用。

### 4.5 Workflow

结构化 stage、transition、optional stage、human gate、artifact、closure/routing metadata。它是 workflow definition，不是 runtime engine。

### 4.6 Structured vs Markdown Boundary

结构化：Identity、scope、lifecycle/validity、relationships、machine gates、workflow routing、promotion/eval metadata。  
Markdown：Principle rationale、Framework questions/examples/guidance、Skill procedure、Workflow guidance。

## 5. Seed Capability Baseline

10 个 Seed capability 被物理固化并通过 `BOOTSTRAP_AUTHORIZED` hash ledger 锁定：

**Principles**

- `principle:agent-design:canonical-capability-not-runtime-prompt@1.0.0`
- `principle:agent-design:project-truth-over-generic-guidance@1.0.0`
- `principle:agent-design:closure-requires-authority@1.0.0`

**Frameworks**

- `framework:agent-design:authority-analysis@1.0.0`
- `framework:agent-design:lifecycle-analysis@1.0.0`

**Skills**

- `skill:agent-design:design-closure-assessment@1.0.0`
- `skill:agent-design:baseline-finalization@1.0.0`
- `skill:agent-design:next-topic-routing@1.0.0`
- `skill:agent-design:architecture-review@1.0.0`

**Workflow**

- `workflow:agent-design:design-discussion@1.0.0`

`bootstrap-baseline.yaml` 明确 `baselineVersion=0.1.0`、`bootstrapBaselineDate=2026-08-10`，并声明正常 promotion governance 的 cutoff。

## 6. Identity / Version / Relationships / Immutability

Durable ID 严格为：

```text
kind:namespace:name
```

与 path/version/runtime/model/projection 无关。

Promoted/Bootstrap `id + version` 通过 `promotion-ledger.yaml` 中 canonical content hash 保证 semantic immutability。旧版本无需修改 lifecycle 才能退出 current selection；current version 是 Registry/Catalog 的派生结果，避免为了归档历史而违反 DI-22。

Relationship MVP：

```text
dependsOn
extends
derivedFrom
supersedes
constrainedBy
```

实现 target existence、self-reference、kind compatibility、cycle detection，以及 bounded Skill composition。`SUPERSEDE` Candidate 必须在 proposed capability 中显式声明 superseded target。

## 7. Experience / Candidate / Eval

### Experience

`experience/v1` 保存 source reference + distilled signal：

```text
experienceId
source
capturedAt
designStage
signal
observedBehavior
humanCorrection
impact
triageStatus
triageDecision?
candidateHints
visibility
```

Schema 不允许 `messages` / full transcript。

Triage：

```text
IGNORE
PERSONAL_PREFERENCE
PROJECT_FACT
PROJECT_EXPERIENCE
CROSS_PROJECT_CANDIDATE
```

### Candidate

Candidate 是 wrapper；`proposed/asset.yaml` 直接复用正常 Principle/Framework/Skill/Workflow schema。

Operations：

```text
CREATE
UPDATE
BROADEN_SCOPE
NARROW_SCOPE
SUPERSEDE
```

Promotion 默认 dry review；只有 `promotionStatus=AUTHORIZED` + `authorityDecision=APPROVE` + source/eval/version/scope gates 全部满足时才能 `--apply`。

`BROADEN_SCOPE` 额外要求：至少两份 independent evidence、cross-case analysis、counterexample review、transfer eval PASS，并验证 sparse scope 实际为 monotonic broadening。

### Eval

Eval 定义 reasoning boundary，而不是 exact answer；Eval Result 固定绑定：

```text
capabilityId
capabilityVersion
projectionVersion
runtime
model
executedAt
result
evidence
```

MVP runner 记录 manual/fixture result，不伪装成自动 judge platform。

## 8. Registry / Active Catalog

生成结果：

```text
Design canonical registry: 10
Design learning registry:   5  (3 Experience + 2 Candidate)
Engineering registry:       6
Design active catalog:     10
Engineering active catalog: 4
Unified active projection: 14
```

Registry 不复制 capability body；Active Catalog 只选择 `ACTIVE + VALID + current + not superseded`。Candidate/Experience 不会进入正常 runtime selection。

Design Registry 与 Engineering Registry 保持领域分离；Unified Catalog 只是 cross-domain projection。

## 9. Project Design State / CLOSED / Binding / Lock

`examples/project-fixture/.agent-evolution/` 包含：

```text
design-state.yaml
capabilities.yaml
capabilities.lock.yaml
handoff-input.yaml
design-handoff.yaml
feedback/
```

CLOSED Topic 包含 `closedAt/closedBy/baselineReference/scope/reopenConditions`。Resolver 默认 `DO_NOT_REOPEN`。合法 reopen signal 只产生 `REOPEN_REVIEW_REQUIRED`，不会修改项目状态。

Project Binding 使用 profile/capabilities/extensions/disabledCapabilities，不隐式加载所有 active capability。

Lock 固定 exact `capabilityId + resolvedVersion + contentHash + sourceHarnessRevision`。

## 10. Deterministic Design Context Resolver

输入：

```text
project
intent
topic
requestedOutput
explicitStage?
runtime
reopenSignal?
```

执行顺序：

```text
Project State
→ Binding / Profile
→ Lifecycle / Validity / Supersession
→ Runtime
→ Intent / Stage / Sparse Scope
→ Workflow Required Skills
→ Bounded Dependency Expansion
→ Project Conflict Signals
→ Resolved Context + Explain
```

不调用 LLM、Embedding、Vector DB。

Explain 输出：`selectedBecause` / `excludedBecause`，含 profile、scope、workflow、dependency、disabled、invalid、superseded、closed-topic 等原因。

Explicit Project Constraint 产生 conflict signal，`resolutionRule=PROJECT_TRUTH_WINS`，不会修改 shared capability。

## 11. Discussion Workflow / Contract / Next Topic

`workflow:agent-design:design-discussion` 支持：

```text
EXPLORATION
FOCUSED_DESIGN
CALIBRATION
BOUNDARY_CLOSURE
BASELINE
ENGINEERING_DESIGN
REPOSITORY_LANDING
```

optional/skip transition 由 metadata 表达。

Discussion Contract 默认 ephemeral，确定性生成 Topic / Background / CLOSED Topics / Scope / Non-Goals / Questions / Constraints / Expected Outputs / Closure Criteria / Next Stage。

Next Topic Routing 读取 topic status、dependencies、current stage、workflow transition、nextTopicCandidates，只输出 ranking inputs；`usesSemanticPlanner=false`。

## 12. Runtime Projection

Projection Adapter 将 canonical semantic meaning 与 runtime packaging 分离。

独立版本轴：

```text
Capability SemVer             1.0.0
Agent Skill Projection        agent-skill-projection/1
ChatGPT Pack Projection       chatgpt-project-pack/1
Codex Pack Projection         codex-project-pack/1
```

生成 Skill 只 materialize selected Skill 及其 selected referenced Principle/Framework；不会把所有 active knowledge 塞进 prompt。

ChatGPT pack：

```text
project-instructions.md
resolved-context.md
resolved-context.json
discussion-contract.md
skills/**/SKILL.md
projection-manifest.json
```

Codex pack：

```text
repository-guidance.md
resolved-task-context.md
resolved-context.json
discussion-contract.md
skills/**/SKILL.md
projection-manifest.json
```

Codex adapter 不覆盖 `AGENTS.md`。

两个 runtime manifest 使用同一 canonical capability `id/version/contentHash`；runtime-specific packaging 可以不同，但不能 semantic fork。

Visibility gate 会阻止低于 project materialization boundary 的 referenced content 进入共享 runtime pack，并记录 omitted reason。

## 13. Design → Repository Handoff / Repository → Design Feedback

Handoff 是 reference-first generated projection：

```text
baselineReferences
decisionReferences
entityReferences
authorityReferences
invariantReferences
protectedBoundaryReferences
externalContractReferences
assumptionReferences
implementationConstraints
openEngineeringQuestions
verificationObligations
reopenConditions
sourceRevision
fieldAuthority
```

`fieldAuthority` 明确哪些字段来自 project canonical references、哪些来自 small handoff input、哪些是 generated projection。Baseline body 不被复制。

Repository Feedback 只映射成 `UNTRIAGED Experience`，不会修改 Capability，也不会自动 reopen CLOSED Topic。

## 14. Revalidation MVP

`harness revalidation check` 根据：

```text
validity
reviewAfter
revalidationTriggers
```

报告 `CURRENT` / `REQUIRED` 及原因，例如 `review-due`、`validity:QUESTIONED`、`trigger:MODEL_UPGRADE`。命令只识别 revalidation pressure，不自动修改 capability。

## 15. CLI Surface

Unified CLI：

```text
harness validate
harness list
harness show
harness registry build
harness catalog build
harness resolve --explain
harness project bind
harness project lock
harness experience capture
harness experience triage
harness candidate create
harness candidate promote
harness eval run
harness projection build
harness discussion materialize
harness discussion route-next
harness handoff build
harness feedback capture
harness revalidation check
```

JSON envelope：`harness-cli/v1`。

Engineering compatibility facade：

```text
eng validate
eng registry build
eng catalog build
eng doctor --ci
eng context resolve
eng test
```

真实 Brownfield merge 时，应保留 richer historical commands。

## 16. Structural Gate vs Semantic Gate

CI structural validation 覆盖：

- capability schema / identity / version；
- relationship target / compatibility / cycle / bounded composition；
- bootstrap/promotion hash immutability；
- Experience/Candidate/Eval schema/reference integrity；
- Engineering registration integrity；
- Project state/binding；
- Registry/Catalog drift；
- Exact lock drift；
- ChatGPT/Codex projection freshness；
- Handoff schema。

验证报告明确：

```text
structuralGate = PASS
semanticGate   = NOT_ASSERTED_BY_CI
```

因此 CI 不会把“YAML 合法”误判成“设计原则正确”。

## 17. End-to-End Proofs

### 17.1 Promotion

Executable test：

```text
Triaged Experience
→ Candidate CREATE
→ Eval PASS bound to runtime/model/projection
→ Human Authority Metadata
→ promote --apply
→ Canonical Skill 1.0.0
→ Promotion Ledger Hash
→ Registry / Catalog Rebuild
→ Project Extension + Exact Lock
→ Resolver Selection
→ ChatGPT SKILL.md Projection
```

### 17.2 Cross-Project Generalization

```text
architecture-review@1.0.0
→ BROADEN_SCOPE Candidate
→ Independent Evidence
→ Cross-Case + Counterexample Review
→ Transfer Eval PASS
→ Authority
→ architecture-review@1.1.0
→ Registry keeps 1.0.0 historically
→ Active Catalog selects 1.1.0
→ old exact project lock becomes stale
→ explicit project lock rebuild required
```

这证明 Generalization 不是普通 YAML edit。

### 17.3 Supersession

```text
Old Capability Identity
→ SUPERSEDE Candidate with new identity
→ explicit supersedes relationship
→ Eval + Authority
→ Promote replacement
→ Old identity remains historically discoverable
→ Active Catalog excludes old identity
```

## 18. Fresh Verification Evidence

`verification/final/` 保存本轮 fresh evidence。

### Tests

```text
PYTHONPATH=src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q
87 passed in 14.10s
```

### Structural / CLI Acceptance

以下命令 fresh exit `0` / `ok=true`：

```text
harness validate --check-generated
harness registry build --check
harness catalog build --check
harness project lock --check
harness projection build CHATGPT --check
harness projection build CODEX --check
harness handoff build --check
eng validate
eng registry build --check
eng catalog build --check
eng doctor --ci
eng context resolve
eng test
```

Structural snapshot：

```text
Capabilities: 10
Experiences:   3
Candidates:    2
Evals:         7
Issues:        0
Structural:    PASS
Semantic:      NOT_ASSERTED_BY_CI
```

### Deterministic Rebuild Proof

执行：

```text
hash 22 generated/derived files
→ delete registries/catalogs/projections/lock/handoff
→ rebuild from canonical inputs
→ hash again
```

结果：

```text
beforeFileCount = 22
afterFileCount  = 22
added            = []
removed          = []
changed          = []
byteEquivalent   = true
```

之后再次运行 `harness validate --check-generated`，结果继续为 PASS。

## 19. DI Invariant Implementation Mapping

| Invariant | Executable evidence |
|---|---|
| DI-01 Canonical ≠ runtime prompt | canonical `asset.yaml/content.md` vs generated packs |
| DI-02 identity independent | parser + path-independent asset identity tests |
| DI-03 no raw project truth leakage | Experience distillation + project references + handoff reference-first |
| DI-05 Registry not source | delete/rebuild byte-equivalence |
| DI-06 Projection not canonical | generated rebuild + freshness drift checks |
| DI-07 selection before materialization | resolver output is projection input |
| DI-08 Design State routes truth | state uses references; no baseline body copy |
| DI-09 selective Experience | strict distilled schema; transcript rejected |
| DI-10 explicit Promotion | Candidate + authority + eval + apply gate |
| DI-11 explicit Generalization | BROADEN_SCOPE transfer gate + E2E |
| DI-12 shared ChatGPT/Codex identity | cross-runtime manifest identity/hash tests |
| DI-15 Structural ≠ Semantic Eval | `semanticGate=NOT_ASSERTED_BY_CI` |
| DI-16 Active Catalog derived | lifecycle/validity/current/supersession filters |
| DI-18 CLOSED discoverable | state schema + resolver guard tests |
| DI-19 handoff references authority | generated reference-first handoff |
| DI-20 feedback via triage | feedback → UNTRIAGED Experience test |
| DI-22 immutable ID+version | promotion ledger content hash validation |
| DI-24 derived artifacts | deterministic delete/rebuild proof |
| DI-25 exact resolution lock | lock id/version/hash/source revision |
| DI-27 project truth authority | explicit conflict signal `PROJECT_TRUTH_WINS` |
| DI-28 explicit state beats inference | CLOSED/stage resolver tests |
| DI-29 bounded acyclic Skill composition | relation validator/tests |
| DI-30 closure assessment no state mutation | resolver/discussion byte-preservation tests |
| DI-31 baseline finalization no invention | semantic Skill contract + no state-mutating finalizer |
| DI-32 eval runtime/model binding | eval-result schema/tests |
| DI-37 projection version independent | independent adapter constants/tests |
| DI-38 resolved context preserves identity/hash | resolver schema/output + JSON projection |
| DI-40 feedback only through learning | feedback capture returns Experience only |

## 20. Answers to the 50 Implementation Questions

1. Existing reusable pieces：Python tooling strategy、stable IDs、generated registry/catalog、deterministic context pattern、Candidate governance、CI/local command parity。
2. Shared Core：identity、SemVer、schema loading、hashing、provenance/source reference、relationship validation、generated drift、promotion ledger mechanics。
3. Final directories：`core/design/engineering/runtime/tooling/generated/src/examples/tests/verification`。
4. Common Capability Schema：共同 machine metadata，不包含 universal kind payload。
5. Principle minimum：`invariant`；exceptions/negativeExamples optional。
6. Framework minimum：`dimensions` + `expectedOutputs`。
7. Skill minimum：role/intent/triggers/not-use/context/references/gates/output/stop/self-review。
8. Workflow minimum：stages/transitions/optional/gates/artifacts/closure/routing。
9. Markdown semantics：Principle rationale、Framework analysis guidance、Skill procedure、Workflow guidance。
10. Identity validator：严格 `kind:namespace:name` + kind match + repo id/version uniqueness。
11. Promoted immutable：ledger stores canonical content hash；drift fails validation。
12. Scope vocabulary：stage/runtime constrained；domain/system/artifact/tag open sparse strings。
13. Provenance：sourceType/reference/revision?/visibility/distillation?。
14. Visibility gate：projection materialization checks source visibility and omits restricted referenced body。
15. Relationship legality：target existence + kind matrix + self/cycle checks。
16. Skill cycle：LEAF no Skill composition；ORCHESTRATION graph cycle-check + max-six。
17. Experience：strict distilled YAML under `design/learning/experiences/`。
18. Conversation source：opaque reference such as `chatgpt://...`，no transcript。
19. Triage CLI：explicit ID + decision persisted into triageStatus/triageDecision。
20. Candidate：wrapper YAML + `proposed/asset.yaml` + `proposed/content.md`。
21. Proposed capability：normal kind schema validation reused directly。
22. Promotion authority：`AUTHORIZED + APPROVE + source/eval/version/scope gates`；apply explicit。
23. Scope broadening：independent evidence + cross-case + counterexample + transfer eval + monotonic scope test。
24. Eval fixture：reasoning coverage/risk/question/boundary/alternative/regression/transfer metadata。
25. Eval Result：bind capability/version/projection/runtime/model/time/result/evidence。
26. Registry：scan canonical assets / registrations，hash authoritative files，deterministic JSON。
27. Active Catalog：filter Registry by lifecycle/validity/current/supersession。
28. Avoid authority drift：body omitted + generated check/rebuild + canonical source recoverable without Registry。
29. Project State：reference-based `.agent-evolution/design-state.yaml`。
30. CLOSED Topic：status + closure authority/time/baseline/scope/reopen conditions。
31. Binding：profiles/capabilities/extensions/disabledCapabilities，no body copy。
32. Lock：exact id/version/hash/sourceHarnessRevision + resolution reasons。
33. Resolver input：project/intent/topic/output/stage/runtime/reopen signal。
34. Selection rules：explicit state/binding/profile → eligibility → scope/runtime → workflow → dependencies。
35. Explain：selectedBecause/excludedBecause + conflict/topic guard。
36. CLOSED：default DO_NOT_REOPEN；signal only requests review, no mutation。
37. Project Constraint：conflict signal + PROJECT_TRUTH_WINS。
38. Disabled/Invalid/Superseded：explicit exclusion reasons, never materialized。
39. Discussion Contract：deterministic Markdown from resolved context/state/workflow。
40. Next Topic：status/dependency/stage/transition ranking inputs, no AI planner。
41. Projection Interface：runtime/type/version + stable guidance + build/freshness behavior separated from canonical asset。
42. Skill → SKILL.md：canonical procedure + selected referenced guidance + source trace metadata。
43. Principle/Framework：only referenced **and selected** capabilities materialized。
44. ChatGPT Pack：project instructions + resolved MD/JSON + discussion contract + skills + manifest。
45. Codex Pack：repository guidance + resolved task MD/JSON + discussion contract + skills + manifest。
46. Runtime consistency：same source ID/version/hash；projection version/package independent。
47. Handoff：reference-first schema + small project-authored engineering fields + fieldAuthority。
48. Feedback → Experience：feedback schema validation then `UNTRIAGED Experience`；no direct reopen/mutation。
49. CI Structural Invariants：schema/identity/version/reference/cycle/ledger/learning/project/generated/lock/projection/handoff checks。
50. End-to-End Promotion：真实 pytest flow 已执行并通过，直至 generated ChatGPT `SKILL.md`。

## 21. Implemented / Reused / Changed / Deprecated / Deferred

### Implemented

- Common + kind capability schemas；
- 10 seed capabilities；
- Experience/Candidate/Eval schemas and fixtures；
- promotion/generalization/supersession mechanics；
- registries/catalogs；
- project state/binding/exact lock；
- deterministic resolver/explain；
- discussion contract/next topic；
- ChatGPT/Codex projections；
- handoff/feedback/revalidation；
- unified + engineering compatibility CLIs；
- structural CI workflows；
- 87-test suite；
- deterministic rebuild evidence。

### Reused / Preserved

- Brownfield register-in-place principle；
- Python repository-tool approach；
- Engineering manifest/registration domain；
- stable typed identity concept；
- deterministic generated discovery model；
- Candidate isolation / governed promotion model；
- local command = CI command principle。

### Changed

- reusable mechanics moved to shared `evolution_harness` core；
- design domain adds pre-repository scope/provenance/visibility；
- resolver now reads explicit Design State + Binding + Workflow；
- runtime materialization becomes explicit projection layer；
- exact promoted version immutability is enforced by content hash ledger；
- bootstrap cutoff is executable rather than only documented。

### Deprecated / Rejected As Architecture

No canonical Brownfield artifact is deprecated merely to fit the workspace. Rejected approaches include parallel design-learning repository、universal schema、prompt-as-canonical、registry/catalog-as-authority、load-everything、LLM-required resolver、recursive Skill graph、transcript-as-Experience、auto-promotion、auto-reopen、runtime semantic fork。

### Deferred

- byte-for-byte in-place merge into unavailable original Continuous Learning checkout；
- richer historical `eng inspect/find/candidate-*` preservation/wiring；
- real ChatGPT project API installation；
- Custom GPT rewrite；
- automatic model judge / large benchmark；
- vector/semantic retrieval；
- remote registry/package manager；
- automatic revalidation service；
- team ACL/governance server；
- all-project migration / historic conversation import。

## 22. Known Limitations

1. Engineering compatibility layer is reconstructed from the documented prior contract because original richer source checkout is not mounted.
2. Eval execution is manual/fixture result recording, not automatic LLM judging.
3. Project conflict detection depends on explicit project constraint metadata, not semantic reading of every baseline.
4. Version resolution has no range solver/package-manager semantics.
5. ChatGPT/Codex packs are generated for explicit/manual installation; no product configuration API is invoked.
6. Revalidation reports pressure but does not perform revalidation.
7. Resolver semantic fallback candidates are representable but MVP selection remains deterministic metadata-first.

这些是本轮明确的 MVP boundaries，不是隐藏的 Production-Ready 声明。

## 23. Freeze State

基于本包内真实代码与 `verification/final/` fresh evidence，可以冻结 **MVP implementation package**：

```text
DESIGN_EVOLUTION_REPOSITORY_BOOTSTRAP = CLOSED
UNIFIED_EVOLUTION_WORKSPACE_IMPLEMENTATION = CLOSED
COMMON_CAPABILITY_SCHEMA_IMPLEMENTATION = CLOSED
DESIGN_CAPABILITY_SCHEMA_IMPLEMENTATION = CLOSED
DESIGN_EXPERIENCE_SCHEMA_IMPLEMENTATION = CLOSED
DESIGN_CANDIDATE_SCHEMA_IMPLEMENTATION = CLOSED
DESIGN_EVAL_SCHEMA_IMPLEMENTATION = CLOSED
DESIGN_REGISTRY_GENERATOR = CLOSED
ACTIVE_DESIGN_CATALOG_GENERATOR = CLOSED
PROJECT_DESIGN_STATE_IMPLEMENTATION = CLOSED
PROJECT_CAPABILITY_BINDING_IMPLEMENTATION = CLOSED
PROJECT_CAPABILITY_LOCK_IMPLEMENTATION = CLOSED
DISCUSSION_WORKFLOW_MVP = CLOSED
DESIGN_CONTEXT_RESOLVER_MVP = CLOSED
RESOLUTION_EXPLAIN_TRACE = CLOSED
DISCUSSION_CONTRACT_MATERIALIZATION_MVP = CLOSED
NEXT_TOPIC_ROUTING_MVP = CLOSED
RUNTIME_PROJECTION_INTERFACE = CLOSED
OPENAI_AGENT_SKILL_PROJECTION_MVP = CLOSED
CHATGPT_RUNTIME_PROJECTION_MVP = CLOSED
CODEX_RUNTIME_PROJECTION_MVP = CLOSED
DESIGN_TO_REPOSITORY_HANDOFF_MVP = CLOSED
REPOSITORY_TO_DESIGN_FEEDBACK_MVP = CLOSED
DESIGN_EVOLUTION_CLI_MVP = CLOSED
DESIGN_EVOLUTION_CI_GATE = CLOSED
DESIGN_EVOLUTION_END_TO_END_PROMOTION_FLOW = CLOSED
DESIGN_EVOLUTION_ENGINEERING_MVP = CLOSED
```

同时保留：

```text
REAL_BROWNFIELD_CONTINUOUS_LEARNING_SOURCE_MIGRATION = DEFERRED
```

它不重开 CLOSED architecture，只表示需要在真实旧 checkout 可用时执行应用/合并步骤。

## 24. Next Pilot Recommendation

下一阶段不要继续扩 Schema，而应进入：

```text
Agent Design Evolution Harness Pilot
→ Real Project Binding
→ ChatGPT Discussion Dogfooding
→ Codex Repository Integration
→ Capability Eval
→ Learning Loop Validation
```

Pilot 顺序：

```text
1. Agent-Native Software Engineering
2. Agent Continuous Learning
3. Payment Platform
```

重点测量 Resolver selection quality、context size、CLOSED preservation、Skill applicability、workflow friction、baseline finalization quality、next-topic routing、ChatGPT/Codex consistency、feedback quality、false-positive learning、missing-capability pressure、mega-skill pressure、model sensitivity 与 human-authority friction。
