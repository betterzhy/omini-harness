# Project Harness Registration Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a generic, read-only project-local registration pointer that discovers an existing Harness-owned Brownfield integration without duplicating project state or granting execution authority.

**Architecture:** A project owns only `.agent-evolution/registration.yaml`. The Harness validates that pointer, resolves its repository-relative integration through no-symlink path checks, verifies the registered integration identity/runtime/exact-lock fingerprint, and then reuses the existing live Authority Snapshot integration path. Existing explicit `--integration` calls remain compatible.

**Tech Stack:** Python 3.12, PyYAML, jsonschema, argparse, pytest, existing `evolution_harness` path/authority/project/integration modules.

## Global Constraints

- Scope is Harness stages 1-3 only; do not modify Pay-Nexus.
- Do not read, enumerate, or hash `/Users/yuzhuangzhuang/Projects/pay-nexus/temp-input/**`.
- Registration is routing metadata only and may not contain project stage, topic status, authorization, capability bodies, or canonical project facts.
- Project truth continues to override shared guidance through the live Authority Snapshot.
- Automatic projection install/uninstall apply remains disabled.
- No Skill materialization, business development, Landing, Wave 0, DDL, database operation, or push.

---

### Task 1: Registration schema and loader

**Files:**
- Create: `core/schemas/project-harness-registration.schema.json`
- Create: `src/evolution_harness/registration.py`
- Create: `tests/test_project_registration.py`

**Interfaces:**
- Consumes: repository root and project source root as `pathlib.Path` values.
- Produces: `load_project_registration(repository_root, source_root) -> dict[str, Any]` containing validated registration, integration root, and source root.

- [x] Write tests for a valid registration and independently asserted resolved integration identity.
- [x] Run the focused test and verify failure because the schema/loader is absent.
- [x] Implement the smallest schema and loader using `SchemaStore`, `safe_relative_path`, and `resolve_without_symlinks`.
- [x] Run the focused test and verify PASS.
- [x] Write and verify RED tests for absolute/traversal paths, registration/integration symlinks, Harness ID mismatch, integration ID mismatch, runtime mismatch, source access other than `READ_ONLY`, source root other than `SELF`, and lock fingerprint mismatch.
- [x] Implement fail-closed validation for each case and rerun the focused tests.

### Task 2: Registration-driven CLI discovery

**Files:**
- Modify: `src/evolution_harness/cli.py`
- Modify: `src/evolution_harness/integration.py`
- Modify: `tests/test_project_registration.py`

**Interfaces:**
- Consumes: optional explicit integration path plus required source path.
- Produces: `resolve_registered_integration(repository_root, source_root, explicit_integration=None)` and CLI command `integration registration-check --source <project>`.
- Preserves: explicit `--integration` behavior for inspect/resolve/projection.

- [x] Write a CLI test proving `registration-check` is missing, then run it and observe RED.
- [x] Add the command and return a machine-readable PASS result with integration ID/path, runtime, source access, and exact lock fingerprint.
- [x] Write RED tests showing inspect, resolve, and projection can omit `--integration` when a valid registration is present.
- [x] Make `--integration` optional for those commands and route discovery through the validated registration.
- [x] Write and pass negatives for missing registration, invalid registration, explicit/registered integration disagreement, Authority drift, CLOSED status disagreement, and excluded-path preservation.
- [x] Verify explicit legacy CLI invocations remain unchanged.

### Task 3: Neutral fixture proof

**Files:**
- Create: `examples/external-project-source/.agent-evolution/registration.yaml`
- Modify: `tests/test_neutral_integration_fixture.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: the existing `integrations/neutral-shadow` sidecar and neutral source fixture.
- Produces: equivalent explicit and discovered Authority Snapshot, Resolution ID, projection freshness, and dry-run plan results.

- [x] Add an end-to-end RED test for discovered neutral registration and verify failure before the fixture exists.
- [x] Add the neutral registration pointer with a literal current exact-lock fingerprint.
- [x] Assert explicit and discovered resolution IDs are identical, 2/2 scenarios PASS, projection is fresh, and dry-run planning passes.
- [x] Assert project paths outside the registration file are unchanged and apply remains rejected.
- [x] Document project-local registration as a pointer, the no-second-state-system rule, and the separate materialization boundary.

### Task 4: Candidate Gate and fixed review

**Files:**
- Modify only generated artifacts proven necessary by existing repository policy.

**Interfaces:**
- Produces: fixed Candidate/Parent/Tree and complete verification receipt.

- [ ] Run focused registration and neutral integration tests.
- [ ] Run full pytest, compileall, structural validation, registry/catalog freshness, engineering doctor, project/neutral/Pay exact locks, neutral 2/2 and Pay read-only 5/5 scenarios, projection freshness, and dry-run planners.
- [ ] Verify Pay-Nexus HEAD/tree/tracked state and absent project-local registration/materialized Skill without touching excluded paths.
- [ ] Commit the exact Harness write set and freeze Candidate/Parent/Tree.
- [ ] Request an independent deep review of the fixed candidate; fix and re-freeze any P0/P1.
- [ ] If deep review has no P0/P1, request an independent ultra final GO/NO-GO.
- [ ] Stop after the Harness/Neutral candidate receipt. Do not modify Pay-Nexus or merge/push without a later decision.
