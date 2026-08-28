---
name: java-engineering-standard
description: Use when a project explicitly adopts java-engineering-standard (including the 0.4.0 compatibility alias java-spec), the user explicitly requests evaluation against this Pack, or the task concerns a declared Java Project Profile, Baseline, module boundaries, Strict/Ratchet quality configuration, version upgrade assessment, or fixed Pack evidence. Do not trigger merely because a request mentions Java, Spring, Maven, DDD, or tests.
---

# Java Engineering Standard

## Purpose

Apply a fixed Java Engineering Capability Pack without turning it into project Authority. Read the target project's Authority first, establish adoption, load only the selected Profile and relevant rule families, and keep applicability, quality, and authorization as separate conclusions.

This Skill is a reasoning and evidence workflow. It is not installed merely because this file exists, and it does not make `java-engineering-standard` a cross-project Harness.

## Trigger decision

Use this Skill when at least one condition is true:

- project Authority or a Java Project Profile explicitly adopts a fixed java-engineering-standard version or its 0.4.0 `java-spec` compatibility alias;
- the user explicitly asks for java-engineering-standard evaluation;
- the request is to create, validate, or review a Java Project Profile, compatible Baseline, Java Quality Config/Evidence, module boundaries, Strict/Ratchet result, exception input, or fixed-version upgrade;
- the request reviews java-engineering-standard itself at a fixed candidate.

If none is true, report `ADOPTION=NOT_ADOPTED` and `AUTHORIZATION=NOT_EVALUATED`. You may offer the Pack as a reference, but do not demand a Profile/Evidence, apply its gates, or issue a project GO/NO-GO. Java, Spring, Maven, DDD, or test vocabulary alone never establishes adoption.

## Progressive workflow

### 1. Read project Authority and adoption facts

Read the target repository's current `AGENTS.md`, business Authority, Contract, Task/Stage material, user authorization, current Git identity, and worktree state before Pack material. Identify who owns business facts, public contracts, modules, state, persistence, merge, and release.

Then locate the declared Java Project Profile. A valid Profile selects `standardVersion`, `primaryProfile`, optional `additionalProfiles`, `baselineId`, module-boundary and quality-config paths, exception paths, and out-of-scope facts. It is capability input, not adoption approval. Capability source resolution or locks belong to the caller or omini-harness, not java-engineering-standard.

Use one adoption state:

- `ADOPTION=ADOPTED`: fixed source and Profile are explicit and resolvable;
- `ADOPTION=EXPLICIT_EVALUATION`: user requested comparison without project adoption;
- `ADOPTION=NOT_ADOPTED`: neither condition exists;
- `ADOPTION=CONFLICT`: project facts disagree about adoption or fixed identity.

### 2. Load only selected material

For an adopted or explicitly evaluated request, load:

1. the fixed `JAVA-DEVELOPMENT-STANDARD.md` rule family directly related to the request;
2. the selected primary Profile and any declared Additional Profile;
3. the chosen Baseline plus compatibility entry;
4. the referenced module-boundary, quality-config, evidence, exception-policy, and rule-evidence entries only when the request needs them.

Do not copy or load all 469 rules. A Modular Monolith request normally needs the modular-monolith Profile and relevant GOV/ARCH/MOD/TEST/BUILD families; a High-Integrity Transaction Additional Profile also loads HIT rules. Preserve stable Rule Ids in every finding.

### 3. Resolve Profile and version constraints

Check Profile/Baseline compatibility and fixed Java, Maven, Spring, Wrapper, Runner, ArchUnit, and quality-tool identities. A request to move beyond the active Baseline—such as Spring Boot 4 when only Boot 3.5.16 is fixed—has `APPLICABILITY=CONFLICT` or `MISSING_EVIDENCE`; do not silently select a new version or mutate a Baseline.

The Pack can validate whether an exception input satisfies Pack rules. The target project may be stricter, and a Pack-valid exception does not approve project risk. Never open `eligibleRules`, add suppressions, or accept an exception without project Authority.

### 4. Evaluate quality evidence

Treat the three contracts separately:

- Java Project Profile selects capability inputs.
- Java Quality Config fixes modules, source sets, Strict/Ratchet mode, reports, and Runner commit/path/SHA-256.
- Java Quality Evidence binds the actual subject Commit/Tree, Profile/Config hashes, runtime/tool facts, report/output hashes, normalized findings, and results.

Runner source identity and Wrapper checksums are technical trust facts, not adoption Authority. Never execute a free-form shell string from Evidence; accept only stable `commandRef` identity or registered runner name plus argv data.

If `generatedSources` is non-empty under 0.4.0, set `JAVA_QUALITY_RESULT=MISSING_EVIDENCE`; dormant rebuild code or a successful Maven build cannot turn it into VALID.

For Strict, a Ratchet Baseline is forbidden. For Ratchet, new findings are not automatically accepted, the Baseline is never expanded by this Skill, and a nonzero NEW delta prevents VALID. Maven PASS alone is only Maven evidence, not complete Java quality evidence.

### 5. Preserve Authority and action boundaries

Project Authority decides implementation, merge, task/stage completion, and release. Rules may be applicable while an action remains unauthorized. If general Pack guidance conflicts with specific project Authority, report both paths, concrete Rule Ids, impact, and decision owner; do not silently choose or modify either.

This Skill does not install dependencies or Skills; modify Baselines; generate or accept Ratchet debt; perform database operations; deploy; publish; push; merge; send messages; or execute irreversible actions. It does not infer permission to modify code from adoption or quality results.

## Required output

Always output these lines independently:

```text
ADOPTION=ADOPTED|EXPLICIT_EVALUATION|NOT_ADOPTED|CONFLICT
APPLICABILITY=APPLICABLE|NOT_APPLICABLE|CONFLICT|MISSING_EVIDENCE
JAVA_PROFILE_RESULT=VALID|INVALID|NOT_EVALUATED
JAVA_QUALITY_RESULT=VALID|INVALID|MISSING_EVIDENCE|NOT_EVALUATED
AUTHORIZATION=PROJECT_OWNED|NOT_EVALUATED
```

Then state fixed Pack identity, project Authority paths, selected Profile/Baseline, relevant Rule Ids/families, evidence present/missing, Exact WriteSet if implementation is authorized, verification needed, limitations, and the project-owned next decision.

`APPLICABILITY=APPLICABLE` means the rule analysis applies; it grants no behavior permission. `JAVA_QUALITY_RESULT=VALID` means the supplied Java quality evidence passed Pack checks; it never closes a project task, stage, merge, or release decision.
