# Agent Design Evolution Repository Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-materialize the approved Agent Design Evolution Harness MVP as a runnable Python repository package with deterministic governance, resolution, projection, learning-loop, and verification surfaces.

**Architecture:** Preserve `core/design/engineering/runtime/tooling/generated` responsibility boundaries. Implement one shared Python core for identity/schema/hash/governance mechanics, domain-specific design schemas/assets, a deterministic resolver, generated ChatGPT/Codex projections, and a compatibility `eng` facade for the prior Continuous Learning control surface.

**Tech Stack:** Python 3.12+ compatible code (executed on Python 3.13), PyYAML, jsonschema, pytest, standard-library argparse/hashlib/pathlib/json.

## Global Constraints

- Do not create a parallel Design learning platform; use one Unified Evolution Workspace.
- Do not create a universal capability payload schema; common metadata + kind-specific schemas only.
- Registry/catalog/lock/resolution/projection are generated and non-authoritative.
- Resolver is deterministic first and must not require LLM/vector/embedding services.
- Experience is distilled/source-referenced, never a transcript store.
- Candidate is a promotion wrapper and promotion/generalization require explicit governance.
- Project truth outranks generic shared capability guidance.
- ChatGPT and Codex projections preserve the same canonical capability identity/version/hash.
- Structural CI does not assert semantic design quality.

---

### Task 1: Shared core schemas, identity, hashing, and schema validation
**Files:** `core/schemas/**`, `core/vocabulary/v1.yaml`, `src/evolution_harness/{identity,schema,hashing}.py`, `tests/test_schema_identity.py`
**Interfaces:** Produces `parse_capability_id()`, `validate_semver()`, `SchemaStore.validate()`, `capability_content_hash()`.
- [ ] Write failing tests for identity, SemVer, and common/kind schema validation.
- [ ] Run focused tests and confirm failures are due to missing implementation.
- [ ] Implement minimal shared core and schemas.
- [ ] Re-run focused tests to green.

### Task 2: Seed capability artifacts and structural relationship/governance validator
**Files:** `design/capabilities/**`, `core/governance/**`, `src/evolution_harness/{loader,relations,validation,governance}.py`, `tests/{test_capability_assets,test_governance}.py`
**Interfaces:** Produces `load_capabilities()`, `validate_repository()`, relationship/cycle/bounded Skill checks, promotion-ledger immutability checks.
- [ ] Write failing tests for seed validation, relation legality, cycles, lifecycle/validity/supersession, immutable ID+version hash, and bootstrap cutoff.
- [ ] Verify red.
- [ ] Implement minimal validation/governance.
- [ ] Verify green.

### Task 3: Experience, Candidate, Eval, promotion, broadening, and feedback learning loop
**Files:** `design/schemas/{experience,candidate,eval,eval-result}.schema.json`, `design/learning/**`, `design/evals/**`, `src/evolution_harness/{learning,evals,feedback}.py`, `tests/test_learning_flow.py`, `tests/test_handoff_feedback.py`
**Interfaces:** Produces capture/triage/create/promote/eval-record/feedback-to-experience functions.
- [ ] Write failing tests for distilled Experience, explicit triage, proposed capability schema reuse, authority/eval promotion gate, BROADEN_SCOPE transfer gate, and feedback->UNTRIAGED Experience.
- [ ] Verify red.
- [ ] Implement minimal learning loop.
- [ ] Verify green.

### Task 4: Deterministic registries and active catalogs
**Files:** `src/evolution_harness/{registry,catalog,generated}.py`, `engineering/**`, `tests/test_registry_catalog_compat.py`
**Interfaces:** Produces `build_registries()`, `build_catalogs()`, generated freshness/drift checks, legacy engineering projections.
- [ ] Write failing tests for deterministic registry, active eligibility, candidate isolation, superseded exclusion, engineering-domain separation, unified projection.
- [ ] Verify red.
- [ ] Implement generators and engineering compatibility data.
- [ ] Verify green.

### Task 5: Project state, binding, exact lock, deterministic resolver and explain trace
**Files:** `core/schemas/{project-design-state,project-capability-binding}.schema.json`, `examples/project-fixture/.agent-evolution/**`, `runtime/profiles/agent-design-base.yaml`, `src/evolution_harness/{project,resolver}.py`, `tests/{test_project_state,test_resolver}.py`
**Interfaces:** Produces `build_capability_lock()` and `resolve_design_context()`.
- [ ] Write failing tests for CLOSED topic guard, disabled/invalid/superseded exclusion, stage/runtime/intent filtering, dependency expansion, project truth conflict signal, exact lock.
- [ ] Verify red.
- [ ] Implement project control plane and resolver.
- [ ] Verify green.

### Task 6: Discussion workflow materialization and next-topic routing
**Files:** canonical workflow fixture, `src/evolution_harness/discussion.py`, `tests/test_discussion.py`
**Interfaces:** Produces `materialize_discussion_contract()` and `route_next_topics()`.
- [ ] Write failing tests for deterministic contract sections, optional workflow stages, CLOSED preservation, and metadata-only next-topic ranking inputs.
- [ ] Verify red.
- [ ] Implement discussion logic.
- [ ] Verify green.

### Task 7: Runtime projection adapters and traceability/freshness
**Files:** `runtime/adapters/**`, `runtime/templates/**`, `src/evolution_harness/projection.py`, `tests/test_projection.py`
**Interfaces:** Produces ChatGPT/Codex projection pack builders and freshness checker.
- [ ] Write failing tests proving same semantic capability identity across runtimes, referenced-only Principle/Framework inclusion, independent projection version, source hash trace, stale detection, no AGENTS overwrite.
- [ ] Verify red.
- [ ] Implement projection layer.
- [ ] Verify green.

### Task 8: Design handoff, CLI surfaces, CI workflows, and end-to-end acceptance
**Files:** project/handoff schemas, `src/evolution_harness/{handoff,cli,engineering_compat}.py`, `src/engineering_cli/**`, `harness`, `eng`, `.github/workflows/**`, `tests/{test_cli,test_e2e}.py`, `README.md`, `MIGRATION_MAP.md`, `IMPLEMENTATION_REPORT.md`
**Interfaces:** Produces the documented unified CLI and legacy `eng` compatibility surface.
- [ ] Write failing CLI/E2E tests for validate/list/show/catalog/resolve/lock/triage/promotion/eval/projection/handoff/feedback/revalidation and legacy fast gate.
- [ ] Verify red.
- [ ] Implement CLI, handoff, compatibility facade, CI and docs.
- [ ] Verify green.

### Task 9: Release verification and deterministic rebuild package
**Files:** `verification/final/**`, packaging outputs outside source tree.
**Interfaces:** Produces fresh command evidence, test summary, deterministic rebuild proof, ZIP/TAR.GZ + SHA-256.
- [ ] Run full test suite.
- [ ] Run structural acceptance commands.
- [ ] Build generated artifacts and hash them.
- [ ] Delete generated artifacts, rebuild, compare hashes.
- [ ] Package source and write SHA-256 manifest.
