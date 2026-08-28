# Java Capability Pack Boundary

## Canonical identity

```text
PROJECT_PACK_NAME=java-engineering-standard
SKILL_NAME=java-engineering-standard
DISPLAY_NAME=Java Engineering Capability Pack
CANONICAL_CAPABILITY_ID=framework:java:java-engineering-standard
CANONICAL_CAPABILITY_ID_OWNER=omini-harness
REGISTRATION_STATUS=REGISTERED
```

The project directory, Pack machine name, and callable Skill name use `java-engineering-standard`. Registration establishes the stable omini Capability Id only; it does not establish downstream adoption, installation, runtime projection, task completion, or release authorization. The string `java-spec` remains only as a 0.4.0 compatibility protocol namespace for Schema `$id` values, Adapter identities, `target/java-spec-quality/**`, `JAVA_SPEC_*` CI variables, and historical material.

## Purpose

`java-engineering-standard` 0.4.0 is a Java Engineering Capability Pack. It defines versioned Java rules, composable Profiles, Baselines, module/quality/exception input contracts, deterministic Source Layout/Finding Normalization/Strict-Ratchet runners, optional Maven/CI/ArchUnit templates, a Java Engineering Skill, and Pack self-verification.

It is not a cross-project Harness, project Authority, adoption control plane, task/stage completion adjudicator, merge/release authorization service, deployment system, or general Agent runtime.

## Ownership

### java-engineering-standard

- owns Java rule text, Profile and Baseline definitions, Pack schemas/templates, deterministic Runner implementations, technical trust checks, and the result of validating supplied Java inputs/evidence;
- may report rule applicability and `JAVA_PROFILE_RESULT` / `JAVA_QUALITY_RESULT`;
- does not infer target business facts or authorize implementation, merge, release, or task completion.

### target Java project

- owns business Authority and Contracts, module facts, source, actual commands, raw reports, Baseline selection, fixed candidate evidence, exceptions/risk acceptance, and rollout/recovery decisions;
- decides its own task/stage completion, merge permission, and release permission;
- may impose stricter requirements than the Pack.

### omini-harness or calling environment

- owns capability source resolution, immutable lock, resolved content digest, validator identity, and registration provenance;
- does not authorize downstream adoption, installation, task completion, merge, release, or deployment. java-engineering-standard does not maintain a second source/adoption lock.

## Current execution contracts

Exactly three active Java contracts exist:

1. `schemas/java-project-profile.schema.json` selects standard version, Profile(s), Baseline, module/quality/exception inputs, and out-of-scope facts.
2. `schemas/code-quality.schema.json` version 2 fixes Reactor/source/report configuration, Strict/Ratchet mode, and Runner source commit/path/SHA-256.
3. `schemas/java-quality-evidence.schema.json` binds actual subject Commit/Tree, Profile/Config hashes, runtime/tool/report/output facts, check results, and Java results.

The former combined adoption draft is preserved only under `docs/history/project-adoption-v1/` with a deterministic migration guide. It cannot produce a 0.4.0 VALID result.

## Result separation

- Rule applicability is analysis, never behavior authorization.
- `JAVA_PROFILE_RESULT=VALID` validates Profile input only.
- `JAVA_QUALITY_RESULT=VALID` validates supplied Java quality evidence only.
- `JAVA_QUALITY_RESULT=MISSING_EVIDENCE` is mandatory when generated source is unsupported or required current evidence is absent.
- Project authorization and task/stage/merge/release outcomes remain project-owned.

## Technical trust and safety

Executable Runner identities retain the full java-engineering-standard commit, canonical relative path, and SHA-256. Wrapper scripts, all four Wrapper properties, and the Maven distribution retain fixed Baseline identities. Evidence binds non-symlink in-project output paths and SHA-256 values to the actual project Commit/Tree. For VALID evidence the Validator first closes all static project/Wrapper trust checks, then replays only its own Ruby and current `JAVA_HOME/bin/java` fixed version probes; it never executes the target Wrapper. Maven output is parsed against the Baseline, all quality tools bind the same stable project `commandRef` and complete successful Maven build output, every Module report version is parsed, and Error Prone must match both plugin and compile/testCompile execution annotation-processor paths. Stable `commandRef` or registered runner name plus argv may describe execution; java-engineering-standard never evaluates an arbitrary project shell string, runs a project build, executes target project code, or downloads Maven.

`JAVA_QUALITY_RESULT=VALID` means that the supplied, hash-bound Evidence is structurally and semantically valid under this Pack. It is not a cryptographic execution attestation: the target project remains the owner of workflow execution, raw outputs, candidate evidence and provenance authenticity. Signed cross-project attestation belongs to the caller/omini control plane, not to java-engineering-standard 0.4.0.

Source Layout, normalized findings, report provenance, Strict/Ratchet delta, generated-source fail-closed behavior, symlink/path/TOCTOU/command-injection/recovery tests remain part of Pack verification.

## Non-goals for 0.4.0

No Java, Spring, Maven, ArchUnit, or quality-tool upgrade; no Generated Source enablement; no Baseline debt acceptance; no global Skill install; no real downstream Pilot; no reusable workflow publication; no Harness infrastructure implementation; no Pay-Nexus, database, network, deployment, push, release, or automatic main merge.
