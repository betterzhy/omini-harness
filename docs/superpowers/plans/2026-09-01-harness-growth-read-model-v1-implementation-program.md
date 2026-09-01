# Harness Growth Read Model v1 Implementation Program Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Implementation program plan only. No HG1–HG6 implementation, landing, push, Runtime enablement, real-project pilot, or Workbench adoption is implied by this document.

**Goal:** Deliver the approved Harness growth system in separately reviewable increments from GAP intake through deterministic cross-project projection, real-project evidence, Workbench read-only presentation, and two explicitly authorized improvement commands.

**Architecture:** `omini-harness` remains the authoritative provider and implements the sequence `GAP Receipt -> Experience -> Candidate -> Experiment/Trial -> controlled Eval -> human Promotion -> derived Release -> Adoption Observation -> Observed Effect -> growth-projection/v1`. Project Helm consumes only the versioned projection until HG6 introduces a separately negotiated command port. Each phase freezes its own Exact WriteSet, stable Candidate/Parent/Tree, fresh repository gate, and independent review before the next phase may be planned or executed.

**Tech Stack:** Python 3.12+, standard library, PyYAML, jsonschema Draft 2020-12, pytest, existing `SchemaStore`, anchored filesystem and coordinator CAS patterns; React, TypeScript, pnpm, Testing Library, Storybook, and Playwright only in the later Project Helm phases.

**Spec:** `docs/superpowers/specs/2026-09-01-harness-growth-read-model-v1-design.md` at Candidate `a4e5c277a52a7fd70f3cf07ca30f850ff5726979`, Tree `d168c19f8f5a9e012288b835a43730640c23c0c5`; the user approved these fixed bytes on 2026-09-01.

## Global Constraints

- Treat the approved Spec Candidate and its independent `xhigh` review as the semantic baseline. Do not rewrite the fixed Candidate merely to embed the later approval event.
- Execute phases only in this order: `HG1 -> HG2 -> HG3 -> HG4 -> HG5 -> HG6`.
- A phase cannot inherit a prior phase's fixed-candidate review, complete-suite result, project authorization, or Workbench visual evidence.
- Before each phase, refresh live Authority, HEAD/tree, direct Parent, worktree status, untracked files, relevant external-provider identity, and current test baseline.
- Each phase is `R2`: define one Exact WriteSet, use RED -> GREEN, run focused regression, freeze Candidate/Parent/Tree, run the repository-required complete Gate, and obtain one independent `deep_reviewer` verdict with P0/P1/P2 = `0/0/0`.
- Any P0 or P1, Authority drift, unexplained test failure, WriteSet expansion, schema compatibility conflict, missing project authorization, or uncertain recovery outcome is `NO-GO`.
- Preserve every failed, interrupted, superseded, or NO-GO receipt. A later PASS never erases it.
- Never infer merge, push, release, deployment, Hook installation, scheduler creation, project registration, adoption, Runtime mutation, destructive cleanup, or external-project write authority.
- Do not register Project Helm as a Harness consumer merely because Workbench displays Harness facts.
- Keep `declared`, `configured`, `loaded`, `invoked`, and `effective` as separate evidence axes.
- Keep `core`, `adoption`, and `all` Gate meanings separate. A `core` PASS is not a project-adoption or global PASS.
- Keep historical `experience/v1`, `candidate/v1`, `design-eval/v1`, `eval-result/v1`, canonical Capability, and promotion-ledger bytes compatible and immutable.
- Treat an unbound `eval-result/v1` as `LEGACY_ID_VERSION_ONLY`; it can never establish Experiment PASS.
- Store no raw conversation, prompt, response, terminal log, secret, credential, or project file body in Growth records or Workbench caches.
- Pure scan, projection build/check, Adapter read, and Workbench query operations make zero writes to source projects, Harness Git worktrees, and external Runtime state.
- HG5 may add one separately invoked, receipt-bound Workbench-local cache refresh only after Project Helm Authority names its owner and storage. It writes neither Harness nor a target project, and it is never hidden inside the pure read/query Port.
- Workbench can create only a local `GrowthImprovementProposal` until HG6. It never creates a formal Candidate or Experiment locally.
- HG6 enables only `CREATE_CANDIDATE` and `CREATE_EXPERIMENT`. Promotion, Release, Adoption, Runtime mutation, Supersession, Retirement, Revise, Rerun, and Revalidate remain disabled.
- Do not combine files from two phases in one Candidate or review.

## Program Decomposition and Readiness

| Phase | Detailed plan authority | Current readiness | Entry condition |
| --- | --- | --- | --- |
| HG1 GAP Phase 1 | `docs/superpowers/plans/2026-08-13-growth-assessment-protocol-phase-1.md` | `READY_FOR_EXECUTION_CHOICE` after Task 1 below | This program's fixed-plan GO plus a user-selected clean Harness landing that contains the approved Spec and program bytes |
| HG2 Lifecycle Contracts | Reserved: `docs/superpowers/plans/2026-09-01-harness-growth-hg2-lifecycle-contracts.md` | `PLAN_REQUIRED` | HG1 fixed Candidate GO and landed local baseline selected by user |
| HG3 Growth Runtime | Reserved: `docs/superpowers/plans/2026-09-01-harness-growth-hg3-runtime.md` | `PLAN_REQUIRED_AFTER_HG2` | HG2 Schema names, validators, and read interfaces fixed and reviewed |
| HG4 Real-project Pilot | Reserved: `docs/superpowers/plans/2026-09-01-harness-growth-hg4-real-project-pilot.md` | `PROJECT_AUTHORITY_REQUIRED` | HG3 GO plus explicit authorization for at least two named projects |
| HG5 Workbench Read | Reserved in Project Helm: `docs/superpowers/plans/2026-09-01-harness-growth-hg5-workbench-read-projection.md` | `AUTHORITY_MIGRATION_REQUIRED` | HG4 evidence GO plus reviewed Project Helm Port/roadmap migration |
| HG6 Improvement Commands | Reserved in Project Helm: `docs/superpowers/plans/2026-09-01-harness-growth-hg6-improvement-commands.md` | `PLAN_AND_COMMAND_AUTHORITY_REQUIRED` | HG5 read-only GO plus separate command-contract approval |

This program plan is intentionally not a substitute for the five reserved phase plans. HG1 is the only phase whose code-level steps, test bodies, public signatures, and commit boundaries are already complete enough to execute. Later plans must be written against the reviewed output of their immediate predecessor so they do not invent interfaces that the repository never froze.

---

### Task 1: Reconcile the Existing HG1 Plan Against the Execution Base

**Files:**

- Read: `docs/superpowers/specs/2026-08-13-growth-assessment-protocol-design.md`
- Read: `docs/superpowers/plans/2026-08-13-growth-assessment-protocol-phase-1.md`
- Read: `docs/superpowers/specs/2026-09-01-harness-growth-read-model-v1-design.md`
- Read: `src/evolution_harness/schema.py`
- Read: `src/evolution_harness/registry.py`
- No production or test files change during reconciliation.

**Interfaces:**

- Consumes: the approved GAP contracts and Harness Growth Spec Candidate `a4e5c277a52a7fd70f3cf07ca30f850ff5726979`.
- Produces: an execution-base receipt containing base HEAD/tree, clean status, exact HG1 WriteSet, baseline Gate results, and either `RECONCILED` or a fail-closed reason.

- [ ] **Step 1: Create an isolated execution worktree only after the user selects an execution mode**

Use `superpowers:using-git-worktrees`. Read the repository worktree convention before creating or moving a worktree. Start from the exact local baseline authorized by the user; do not infer that the current documentation branch is the implementation base. The selected base must already contain the approved Spec and this reviewed program plan, either at their fixed commits or in a separately approved local landing descendant, so documentation bytes cannot leak into the HG1 implementation range.

- [ ] **Step 2: Capture the execution-base identity and worktree state**

```bash
git status --short --branch
export HGRM_HG1_PHASE_BASE="$(git rev-parse HEAD)"
git rev-parse "$HGRM_HG1_PHASE_BASE"
git rev-parse "${HGRM_HG1_PHASE_BASE}^{tree}"
git worktree list --porcelain
git ls-files --others --exclude-standard
```

Expected: the selected implementation worktree has no unexplained tracked or untracked changes. Record the exact 40-hex `HGRM_HG1_PHASE_BASE` and its tree in the reconciliation receipt; every later shell restores that exact value and fails if it is missing. Any unrelated file is preserved and the task stops before editing.

- [ ] **Step 3: Prove HG1 is not already partially implemented**

```bash
rg -n "growth_assessment|GrowthInbox|growth assess|growth receipt|growth scan" \
  src tests core README.md || true
test ! -e src/evolution_harness/growth_assessment.py
test ! -e src/evolution_harness/growth_source.py
test ! -e src/evolution_harness/growth_store.py
```

Expected on the current repository: no implementation matches and all three files are absent. If a later base contains any of them, compare it line-by-line with the HG1 plan and write a new reconciliation finding before deciding whether the old plan remains executable.

- [ ] **Step 4: Freeze the allowed HG1 WriteSet**

```text
core/schemas/growth-assessment-request.schema.json
core/schemas/growth-assessment-receipt.schema.json
core/schemas/growth-capture-result.schema.json
core/schemas/growth-scan-report.schema.json
src/evolution_harness/growth_assessment.py
src/evolution_harness/growth_source.py
src/evolution_harness/growth_store.py
src/evolution_harness/anchored_fs.py
src/evolution_harness/cli.py
tests/test_growth_assessment.py
tests/test_growth_source.py
tests/test_anchored_fs.py
tests/test_growth_store.py
tests/test_growth_cli.py
README.md
```

The current repository has no separately maintained deterministic Schema inventory: `SchemaStore` discovers `**/*.schema.json`, and the generated registries do not enumerate core protocol Schemas. Therefore `registry.py`, generated registry bytes, and any inventory file are excluded from HG1. If the selected future execution base changes that fact or a baseline generated check requires another path, reconciliation returns `WRITESET_DRIFT` and stops to revise and reapprove the plan; execution never adds the path dynamically. `feedback.py`, `learning.py`, existing Experience/Candidate/Eval/ledger records, Project Helm, target projects, and operational Inbox data remain excluded.

- [ ] **Step 5: Run the fresh HG1 baseline Gate**

```bash
PATH="/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin:$PATH" \
  ./harness validate --scope core --check-generated --format json
PYTHONPATH="$PWD/src" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q
```

Expected: both commands exit 0. Record the exact counts and duration. A pre-existing failure is not an implementation RED test and must be diagnosed before HG1 begins.

- [ ] **Step 6: Record the reconciliation decision**

The decision is `RECONCILED` only when the live interfaces still match:

```python
from pathlib import Path
from typing import Any

class GrowthAssessmentError(ValueError):
    code: str

def normalize_growth_assessment_request(
    repository_root: Path,
    value: dict[str, Any],
) -> dict[str, Any]: ...

def growth_assessment_key(value: dict[str, Any]) -> str: ...
def growth_assessment_id(value: dict[str, Any]) -> str: ...
def growth_request_digest(value: dict[str, Any]) -> str: ...

def validate_growth_source(
    repository_root: Path,
    source_root: Path,
    request: dict[str, Any],
) -> dict[str, Any]: ...

class GrowthInbox:
    @classmethod
    def open_for_record(
        cls,
        repository_root: Path,
        source_root: Path,
        state_root: Path | None,
    ) -> "GrowthInbox": ...

    @classmethod
    def open_read_only(
        cls,
        repository_root: Path,
        state_root: Path | None,
    ) -> "GrowthInbox": ...

    def record(self, request: dict[str, Any]) -> dict[str, Any]: ...
    def receipt(self, assessment_id: str) -> dict[str, Any]: ...
    def scan(self, *, as_of: str) -> dict[str, Any]: ...
```

If the repository has changed these dependencies, stop and revise the HG1 plan rather than silently adapting during implementation.

---

### Task 2: Execute HG1 GAP Phase 1 Without Importing Learning Facts

**Files:**

- Implement exactly the HG1 WriteSet frozen in Task 1.
- Test through `tests/test_growth_assessment.py`, `tests/test_growth_source.py`, `tests/test_anchored_fs.py`, `tests/test_growth_store.py`, and `tests/test_growth_cli.py`.
- Follow every RED/GREEN and logical commit boundary in `docs/superpowers/plans/2026-08-13-growth-assessment-protocol-phase-1.md` Tasks 1–7. The current shared commit-message convention overrides that historical plan's English message examples.

**Interfaces:**

- Consumes: validated registration, Authority Snapshot, exact lock, `SchemaStore`, `canonical_json_bytes`, `sha256_bytes`, and `AnchoredRoot`.
- Produces: strict GAP request/receipt/result/report contracts; deterministic identities; owner-only append-only Inbox; read-only receipt lookup and scan; CLI commands `growth assess`, `growth receipt`, and `growth scan`.

HG1 preserves the approved contract versions exactly: `growth-assessment-request/v1`, `growth-assessment-receipt/v1`, `growth-capture-result/v1`, and `growth-scan-report/v1`.

- [ ] **Step 1: Implement strict protocol Schemas using the existing HG1 plan Task 1**

Run its failing schema tests before creating the four Schema files. Require Draft 2020-12, `additionalProperties: false`, bounded fields, and closed conditional branches.

- [ ] **Step 2: Implement pure normalization and identity using the existing HG1 plan Task 2**

The module must not read the clock, filesystem, environment, Git, project, or Inbox. Every stored ID and digest is recomputed on read.

- [ ] **Step 3: Implement zero-write source provenance using the existing HG1 plan Task 3**

Registered-project evidence resolves only through validated registration and Authority Snapshot inputs. `OPAQUE` evidence is never opened. `HARNESS_SELF` uses only read-only Git identity commands.

- [ ] **Step 4: Implement no-replace Inbox publication using the existing HG1 plan Task 4**

Add the narrowly scoped primitive:

```python
def publish_bytes_no_replace(
    self,
    staging_directory: str,
    destination: str,
    data: bytes,
    *,
    mode: int = 0o600,
) -> None: ...
```

The final receipt appears only after a complete fsynced staging inode is hard-linked into the Inbox. Never use the existing replace-capable `write_bytes` for receipts.

- [ ] **Step 5: Implement the three CLI actions using the existing HG1 plan Task 5**

```text
harness growth assess --source ABSOLUTE --request PATH_OR_STDIN --format json
harness growth receipt --id ASSESSMENT_ID --check --format json
harness growth scan --as-of RFC3339 --format json
```

Only `STATE_ROOT_UNAVAILABLE` and `INBOX_LOCKED` can return a validated `DEFERRED` result. No action imports an Experience or creates Candidate/Eval/Promotion state.

- [ ] **Step 6: Document only implemented HG1 behavior using the existing HG1 plan Task 6**

README text must retain the limits: no Hook, scheduler, semantic clustering, automatic import, Candidate, Eval, Promotion, or target-project write.

- [ ] **Step 7: Run the neutral and adversarial pilot using the existing HG1 plan Task 7**

The pilot uses disposable registered fixtures and proves exact replay, conflicting replay, receipt lookup, read-only scan, multiprocess contention, crash boundaries, path/symlink/permission failures, and source/Harness zero-write.

- [ ] **Step 8: Confirm the implementation diff never crossed the WriteSet**

```bash
: "${HGRM_HG1_PHASE_BASE:?restore the exact Phase Base from the reconciliation receipt}"
git cat-file -e "${HGRM_HG1_PHASE_BASE}^{commit}"
git status --short
git diff --check
git diff --check "${HGRM_HG1_PHASE_BASE}..HEAD"
git diff --name-status "${HGRM_HG1_PHASE_BASE}..HEAD"
```

Expected: the cumulative Phase Base-to-HEAD diff, including already committed task slices, equals the Task 1 WriteSet exactly. Operational Inbox files and target-project artifacts are absent. An uncommitted-only diff is not accepted as cumulative WriteSet evidence.

---

### Task 3: Close HG1 as an Independent Fixed Candidate

**Files:**

- No new files beyond the reconciled HG1 WriteSet.

**Interfaces:**

- Consumes: the stable HG1 implementation tree.
- Produces: fixed Candidate/Parent/Tree, complete Gate receipt, independent review, and a local landing decision request.

- [ ] **Step 1: Run the focused GAP suite on the stable tree**

```bash
PYTHONPATH="$PWD/src" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q \
    tests/test_growth_assessment.py \
    tests/test_growth_source.py \
    tests/test_anchored_fs.py \
    tests/test_growth_store.py \
    tests/test_growth_cli.py
```

Expected: terminal PASS with zero failures.

- [ ] **Step 2: Run the repository-required complete Gate once**

```bash
PYTHONPATH="$PWD/src" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q
PATH="/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin:$PATH" \
  ./harness validate --scope core --check-generated --format json
PATH="/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin:$PATH" \
  ./harness registry build --check --format json
PATH="/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin:$PATH" \
  ./harness catalog build --check --format json
PATH="/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin:$PATH" \
  ./harness project lock --project examples/project-fixture --check --format json
PATH="/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin:$PATH" \
  ./harness projection build \
  --project examples/project-fixture \
  --intent architecture-review \
  --topic resolver-mvp \
  --output 'review findings' \
  --runtime CHATGPT \
  --check \
  --format json
PATH="/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin:$PATH" \
  ./harness projection build \
  --project examples/project-fixture \
  --intent architecture-review \
  --topic resolver-mvp \
  --output 'review findings' \
  --runtime CODEX \
  --check \
  --format json
./eng doctor --ci --json
```

Expected: every command exits 0; structural and generated checks report PASS; `semanticGate` remains a separate reported fact.

- [ ] **Step 3: Verify cumulative task commits and commit only an approved remainder**

Read the shared commit-message convention first. The existing HG1 plan creates logical task commits, so the phase Candidate may have multiple commits after the recorded Phase Base. Inspect the complete Phase Base-to-Candidate range; never use only `git diff HEAD^` or an uncommitted diff as the phase WriteSet. If an approved remainder exists after the old plan's task commits, stage explicit paths only; never `git add .`.

```bash
: "${HGRM_HG1_PHASE_BASE:?restore the exact Phase Base from the reconciliation receipt}"
git status --short
git diff --check
git diff --check "${HGRM_HG1_PHASE_BASE}..HEAD"
git diff --name-status "${HGRM_HG1_PHASE_BASE}..HEAD"
git add core/schemas/growth-assessment-request.schema.json \
  core/schemas/growth-assessment-receipt.schema.json \
  core/schemas/growth-capture-result.schema.json \
  core/schemas/growth-scan-report.schema.json \
  src/evolution_harness/growth_assessment.py \
  src/evolution_harness/growth_source.py \
  src/evolution_harness/growth_store.py \
  src/evolution_harness/anchored_fs.py \
  src/evolution_harness/cli.py \
  tests/test_growth_assessment.py \
  tests/test_growth_source.py \
  tests/test_anchored_fs.py \
  tests/test_growth_store.py \
  tests/test_growth_cli.py \
  README.md
git diff --cached --check
git diff --cached --quiet || git commit -m "feat(growth): 增加评估收据 Inbox"
git diff --check "${HGRM_HG1_PHASE_BASE}..HEAD"
git diff --name-status "${HGRM_HG1_PHASE_BASE}..HEAD"
```

Expected: the final cumulative path set equals the frozen WriteSet exactly and the worktree is clean. No extra final commit is created when every approved byte is already present in the logical task commits.

- [ ] **Step 4: Freeze and verify identity**

```bash
git rev-parse HEAD
git rev-parse HEAD^
git rev-parse 'HEAD^{tree}'
: "${HGRM_HG1_PHASE_BASE:?restore the exact Phase Base from the reconciliation receipt}"
git rev-parse "$HGRM_HG1_PHASE_BASE"
git rev-parse "${HGRM_HG1_PHASE_BASE}^{tree}"
git status --short
```

Expected: exact Candidate, direct Parent, Candidate Tree, Phase Base, Phase Base Tree, and a clean worktree.

- [ ] **Step 5: Request a fresh independent review**

The `deep_reviewer` receives the fixed Candidate/Parent/Tree plus Phase Base/Phase Base Tree, approved Spec, existing HG1 plan, reconciled WriteSet, all Gate receipts, and adversarial pilot output. It reviews the complete `Phase Base..Candidate` range and every task commit, not only `Parent..Candidate`. Require explicit review of path containment, owner-only state, no-replace publication, multiprocess races, idempotency conflict, deferred behavior, privacy bounds, zero source/Harness writes, and absence of automatic learning.

- [ ] **Step 6: Stop for the HG1 landing decision**

Report code/tests/review/local-landing separately. Do not merge, push, schedule, import Experience, or begin HG2 without a new user decision.

---

### Task 4: Write and Review the HG2 Lifecycle Contracts Plan

**Files:**

- Reserved phase-plan path: `docs/superpowers/plans/2026-09-01-harness-growth-hg2-lifecycle-contracts.md`
- Do not change Runtime, CLI, Workbench, target projects, or operational Growth state while writing the plan.

**Interfaces:**

- Consumes: landed HG1 interfaces and the approved Growth Spec Sections 7.1–7.10.
- Produces: a code-level HG2 plan whose tasks freeze strict Schemas, canonical references, compatibility readers, deterministic projection builder, generated checks, negative fixtures, and exactly one Authority-bound Bootstrap Content Binding materialization. No general Runtime write command is enabled.

- [ ] **Step 1: Refresh the post-HG1 repository before naming HG2 files**

Re-run the Task 1 identity/status commands and search for any Schema inventory or Growth helpers introduced by HG1. Do not assume the pre-HG1 file map remains current.

- [ ] **Step 2: Keep HG2's proposed WriteSet isolated**

The HG2 plan should start from these responsibility groups, refining exact names only against the live post-HG1 tree:

```text
design/schemas/growth-common.schema.json
design/schemas/growth-bootstrap-content-binding.schema.json
design/schemas/growth-expectation.schema.json
design/schemas/growth-experiment.schema.json
design/schemas/growth-trial-attempt.schema.json
design/schemas/growth-eval-execution-input.schema.json
design/schemas/growth-eval-execution-journal.schema.json
design/schemas/growth-eval-execution-receipt.schema.json
design/schemas/promotion-lineage-binding.schema.json
design/schemas/growth-promotion-plan.schema.json
design/schemas/growth-promotion-journal.schema.json
design/schemas/growth-candidate-integration-transition.schema.json
design/schemas/promotion-receipt.schema.json
design/schemas/growth-legacy-promotion-cutover.schema.json
design/schemas/growth-release-projection.schema.json
design/schemas/growth-project.schema.json
design/schemas/project-adoption-observation.schema.json
design/schemas/observed-effect.schema.json
design/schemas/growth-project-release-view.schema.json
design/schemas/growth-projection-builder-profile.schema.json
design/schemas/growth-projection.schema.json
src/evolution_harness/growth_canonicalization.py
src/evolution_harness/growth_projection.py
tests/test_growth_canonicalization.py
tests/test_growth_lifecycle_contracts.py
tests/test_growth_projection.py
tests/fixtures/growth-read-model-v1/
```

The plan must decide, with a failing test, whether the existing Bootstrap Baseline read Schema belongs in `core/schemas` or the new `design/schemas` family. It must freeze the exact canonical path of the one-time Bootstrap Content Binding against the live post-HG1 Authority before declaring an Exact WriteSet. It must not silently broaden `registry.py` or `generated/registries/design-learning-registry.json` unless a failing generated-contract test proves that ownership.

The detailed HG2 plan must bind the proposed files to these exact contract or rule identities rather than deriving versions from filenames:

```text
bootstrap-baseline/v1
growth-bootstrap-content-binding/v1
growth-expectation/v1
growth-experiment/v1
growth-trial-attempt/v1
growth-eval-execution-input/v1
growth-eval-execution-journal/v1
growth-eval-execution-receipt/v1
promotion-lineage-binding/v1
growth-promotion-plan/v1
growth-candidate-integration-transition/v1
promotion-receipt/v1
growth-legacy-promotion-cutover/v1
growth-release-projection/v1
growth-project/v1
project-adoption-observation/v1
observed-effect/v1
growth-project-release-view/v1
growth-projection-builder-profile/v1
growth-projection/v1
growth-projection-provider-state/v1
growth-projection-counts/v1
growth-projection-gate/v1
```

`promotion-ledger/v1` remains an existing read dependency, not a replacement contract. The HG2 plan must resolve whether the Promotion journal entry Schema receives its own public `schemaVersion` in addition to `PromotionJournalEntryReference`; it cannot invent that identity during implementation.

- [ ] **Step 3: Freeze the pure HG2 read interfaces in that plan**

The HG2 detailed plan must adopt these signatures or record an explicit reviewed compatibility rationale before implementation; the interface responsibilities cannot change:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

@dataclass(frozen=True)
class CandidateBundleSnapshot:
    candidate_reference: dict[str, Any]
    member_bytes: Mapping[str, bytes]

@dataclass(frozen=True)
class GrowthSourceSet:
    records_by_kind: Mapping[str, tuple[dict[str, Any], ...]]
    source_identities: tuple[dict[str, Any], ...]
    provider_state: dict[str, Any]

def capture_candidate_bundle(
    repository_root: Path,
    candidate_id: str,
) -> CandidateBundleSnapshot: ...

def validate_growth_sources(
    repository_root: Path,
    *,
    profile: dict[str, Any],
    as_of: str,
) -> GrowthSourceSet: ...

def build_growth_projection(
    repository_root: Path,
    *,
    profile: dict[str, Any],
    as_of: str,
) -> dict[str, Any]: ...

def validate_growth_projection(
    repository_root: Path,
    value: dict[str, Any],
) -> dict[str, Any]: ...
```

All four functions are pure/read-only in HG2. Promotion Plan, journal, transition, and Receipt are validated fixture contracts only; no HG2 command may publish them.

- [ ] **Step 4: Require RED/GREEN coverage for every Spec contract family**

The HG2 plan must map each Spec section to a failing test before implementation, including safe YAML, exact Candidate bundle identity, typed availability, raw/canonical digests, Experiment/Trial transitions, controlled Eval chain, Promotion generation recovery, Release path exclusivity, cohort identity, `asOf`, sorting, counts, provider states, Gate reasons, and byte-identical watermark.

- [ ] **Step 5: Freeze and authorize the one-time Bootstrap Content Binding**

The detailed plan must identify one exact source repository Revision and tree, the immutable `bootstrap-baseline/v1` bytes and digest, the complete sorted authorized-seed set, every canonical Capability and ledger-entry digest, the proposed binding bytes/digest, the destination path, and the Authority Decision reference. Generate the proposed bytes in a disposable read-only derivation step, prove that later Capability/ledger bytes cannot refresh them, and stop for explicit approval of that exact identity before adding the binding to the HG2 Candidate. A missing or changed approval, source Revision, seed set, digest, or destination path is `NO-GO`; no generic materialize/refresh command remains enabled afterward.

- [ ] **Step 6: Review and approve the HG2 plan before implementation**

Run unresolved-marker, type/interface, Spec coverage, WriteSet, and independent R2 review. Stop for explicit user approval; an HG1 GO does not authorize HG2 implementation.

---

### Task 5: Plan HG3 Only After HG2 Interfaces Are Fixed

**Files:**

- Reserved phase-plan path: `docs/superpowers/plans/2026-09-01-harness-growth-hg3-runtime.md`
- The HG3 plan, not this program document, will name its Runtime modules and tests.

**Interfaces:**

- Consumes: reviewed HG2 Schemas, canonicalization functions, source readers, and projection builder.
- Produces: explicit receipt triage/import, append-only Experiment/Trial revisions, controlled Eval runner, Promotion Plan/journal/CAS/transition/Receipt transaction, persisted Project/Adoption Observation/Observed Effect facts, purely derived Release projections, a read-only projection CLI, and closed service-side command/receipt contracts for Candidate and Experiment creation that remain disconnected from Workbench until HG6.

- [ ] **Step 1: Re-read the actual HG2 public interfaces and generated Schemas**

Do not copy tentative names from Task 4 if HG2 review changed them. Record exact function signatures and Schema IDs from the fixed HG2 Candidate.

- [ ] **Step 2: Keep legacy and controlled Eval paths separate**

The HG3 plan must preserve:

```text
existing record_eval_result -> LEGACY_ID_VERSION_ONLY
controlled runner -> frozen input + same-journal chain + receipt -> EXACT_VIA_EXECUTION_CHAIN
```

No timestamp backfill or same-ID match upgrades legacy evidence.

- [ ] **Step 3: Specify Promotion as one recoverable transaction**

The plan must test the exact order:

```text
BUNDLE_ADMITTED
< ARTIFACTS_STAGED
< CANDIDATE_STATUS_APPLY_INTENT
< candidate.yaml CAS and durable reread
< CANDIDATE_STATUS_APPLIED
< Candidate Integration Transition
< terminal Promotion Receipt
```

Every recovery generation repeats the same immutable Plan, links the immediately prior terminal prefix, emits its own staged/intent prefix, never forks, and never produces a second successful Receipt.

- [ ] **Step 4: Treat the Legacy Promotion Cutover as a separately authorized materialization**

The HG3 plan must stop before writing the one-time cutover until the user approves its exact source Revision, ledger digest, entry list, activation time, and Authority Decision.

- [ ] **Step 5: Freeze the two service-side creation command contracts**

The HG3 plan must define closed, versioned Harness Schemas and durable service behavior for `CREATE_CANDIDATE` and `CREATE_EXPERIMENT`: command ID, IdempotencyKey, requested actor/time, PayloadHash, command-specific exact precondition and payload, append-only acceptance/terminal Receipt, conflict behavior, and receipt lookup after Unknown Outcome. The service-side submission also carries an immutable APPROVE binding whose decision/reference digest binds the actor, command kind, subject, precondition digest, and PayloadHash; the Harness validates that binding again before command acceptance and binds it into the Receipt. Candidate creation binds the exact current triaged Experience references required by Spec 11; Experiment creation binds the exact current Candidate bundle, Authority decision, Promotion state, and deterministic creation key. Missing, rejected, expired, or mismatched approval is rejected before a command journal entry. Same key plus different payload is conflict; an unresolved or absent lookup never permits blind replay. The fixed HG3 Candidate must include an official local submit/receipt-lookup entry over this service and prove the same Schemas and receipts end to end; its exact CLI, local HTTP, or file-exchange transport is selected in the detailed plan under the Web local-host boundary. HG3 creates no Project Helm Adapter and does not activate that transport for Workbench; tests use only owner-controlled fixtures, and no operational command runs without separate authority.

- [ ] **Step 6: Keep Release derived and source facts owner-bound**

No HG3 API persists, edits, or accepts a `growth-release-projection/v1` object as input. Release is recomputed only from the exact canonical Capability, ledger, baseline/cutover, Candidate/Experiment lineage, Promotion Plan/journal/transition, and terminal Receipt rules. Project definitions, Adoption Observations, and Observed Effects remain immutable source facts owned by their declared providers and are admitted only through reviewed reference-based contracts.

- [ ] **Step 7: Review and approve the HG3 plan before implementation**

Require an R2 fixed-plan candidate and independent review. HG2 completion does not authorize Runtime writes.

---

### Task 6: Plan and Authorize the HG4 Real-project Pilot

**Files:**

- Reserved phase-plan path: `docs/superpowers/plans/2026-09-01-harness-growth-hg4-real-project-pilot.md`
- No Project Helm production files change in HG4.

**Interfaces:**

- Consumes: reviewed HG3 CLI/contracts and two or more explicitly named project authorities.
- Produces: 10–20 real GAP Receipts, at least one complete Experiment-backed lineage, Adoption/Effect observations, preserved negative evidence, zero-write receipts, metrics, and an independent pilot review.

- [ ] **Step 1: Ask the user to name and authorize at least two pilot projects**

The plan records each exact repository root, allowed read paths, privacy ceiling, Authority Revision, lock/runtime identity, and whether any project-local writes are allowed. The default is zero project writes.

- [ ] **Step 2: Freeze the pilot cohort and denominators before capture**

Record the intended 10–20 receipt population, project count, observation windows, expected triage denominator, and zero-write checks. Do not choose only successful cases after results exist.

- [ ] **Step 3: Exercise one complete Experiment-backed lineage and a separate negative path**

At least one real `SIGNAL` must proceed through Experience, Candidate, Experiment, frozen Eval input, complete journal/Receipt admission, valid Promotion Plan and nonbranching Promotion journal, Candidate Integration Transition, terminal Promotion Receipt, Release, cross-project Adoption or `NOT_ADOPTED`, and Observed Effect. A separate preserved failure, regression, counterexample, or inconclusive result is also mandatory; it cannot substitute for the complete lineage. The accepted evidence chain is exactly the Spec Section 16 chain. A high pass rate or high signal count is not a success criterion.

- [ ] **Step 4: Report capture cost and safety separately from capability effectiveness**

Required metrics are capture failure/deferred rate, privacy/schema rejection rate, triage acceptance rate, closure friction, source-project zero-write, and expectation outcomes. Never collapse them into one score.

- [ ] **Step 5: Stop after pilot review**

HG4 does not authorize Project Helm code, project registration, Hook/scheduler installation, or broader adoption.

---

### Task 7: Plan HG5 as a Project Helm Authority Migration Plus Read-only Adapter

**Files:**

- Reserved Project Helm phase-plan path: `docs/superpowers/plans/2026-09-01-harness-growth-hg5-workbench-read-projection.md`
- Proposed Authority Modify: `docs/visual/authority-map.md`
- Proposed Authority Modify: `docs/design-baseline/v0.1.4-web-first/15-Knowledge-Management-Workspace-Design-v0.1.md`
- Proposed Authority Modify: `docs/design-baseline/v0.1.4-web-first/16-Knowledge-Workspace-Page-State-Matrix-v0.1.csv`
- Proposed Authority Modify: `docs/design-baseline/v0.1.4-web-first/17-Knowledge-Workbench-Harness-Ownership-Matrix-v0.1.csv`
- Conditional Authority Modify, only if the HG5 Authority review proves it owns the changed claim: `docs/design-baseline/v0.1.4-web-first/02-Implementation-Roadmap-v0.1.4.md`
- Conditional Authority Modify, only if the existing delivery Gate cannot express the new evidence class: `docs/design-baseline/v0.1.4-web-first/25-Unified-Web-Delivery-Gate-Addendum-v0.1.md`
- Proposed Create: `src/features/harness/ports/HarnessEvolutionReadPort.ts`
- Proposed Create: `src/features/harness/ports/HarnessEvolutionCachePort.ts`
- Proposed Create: `src/features/harness/models/growthProjectionV1.ts`
- Proposed Create: `src/features/harness/models/growthProjectionValidationReceiptV1.ts`
- Proposed Create: `src/features/harness/models/growthProjectionCacheV1.ts`
- Proposed Create: `src/features/harness/integrity/growthProjectionIntegrityV1.ts`
- Proposed Create: `src/features/harness/adapters/GrowthProjectionV1Adapter.ts`
- Proposed Create: `src/features/harness/adapters/GrowthProjectionCacheAdapter.ts`
- Proposed Create: `src/features/harness/fixtures/growthProjectionV1.ts`
- Proposed Create: `src/features/harness/components/HarnessEvolutionPage.tsx`
- Proposed Create: `src/features/harness/components/HarnessEvolutionPage.module.css`
- Proposed Create: `src/features/harness/components/EvaluationLedgerPanel.tsx`
- Proposed Create: `src/features/harness/components/HarnessNeedsYouProjection.tsx`
- Proposed Modify: `src/features/harness/components/HarnessStateRail.tsx`
- Proposed Modify: `src/features/harness/components/index.ts`
- Proposed Modify: `src/features/search/components/ProviderStatusStrip.tsx`
- Proposed Modify: `src/features/search/components/SearchResultRow.tsx`
- Proposed Modify: `src/features/search/components/WorkbenchSearchPalette.tsx`
- Proposed Modify: `src/features/search/components/index.ts`
- Proposed Modify: `src/app/App.tsx`
- Proposed Modify: `src/app/shell/WorkbenchAppShell.tsx`
- Proposed Story: `stories/features/harness/HarnessEvolutionPage.stories.tsx`
- Proposed Story: `stories/features/harness/EvaluationLedgerPanel.stories.tsx`
- Proposed Story: `stories/features/harness/HarnessNeedsYouProjection.stories.tsx`
- Proposed Modify: `stories/features/harness/HarnessStateRail.stories.tsx`
- Proposed Modify: `stories/features/search/ProviderStatusStrip.stories.tsx`
- Proposed Modify: `stories/features/search/SearchResultRow.stories.tsx`
- Proposed Modify: `stories/features/search/WorkbenchSearchPalette.stories.tsx`
- Proposed Test: `tests/contracts/harness-evolution-read-port.test.ts`
- Proposed Test: `tests/contracts/harness-evolution-cache-port.test.ts`
- Proposed Test: `tests/contracts/growth-projection-v1-adapter.test.ts`
- Proposed Test: `tests/contracts/growth-projection-validation-receipt.test.ts`
- Proposed Test: `tests/contracts/growth-projection-integrity.test.ts`
- Proposed Test: `tests/contracts/growth-projection-cache-adapter.test.ts`
- Proposed Test: `tests/contracts/harness-evolution-page.test.tsx`
- Proposed Test: `tests/contracts/harness-needs-you-projection.test.tsx`
- Conditional Test Modify, only if the component catalog contract owns the new exported components: `tests/contracts/w3-component-catalog.test.ts`
- Conditional Script Modify, only if the catalog verifier owns the new exported components: `scripts/verify-w3-component-catalog.mjs`
- Proposed Test: `tests/visual/pages/harness-evolution.spec.ts`

**Interfaces:**

- Consumes: a validated `growth-projection/v1` and the reviewed HG4 provider/freshness evidence.
- Produces: read-only Harness Evolution, Evaluation Ledger, search, and Needs You projections with explicit degraded states, plus a separately invoked Workbench-local validated-snapshot cache refresh with its own receipt.

- [ ] **Step 1: Migrate and review Project Helm Authority before code**

The current conceptual `HarnessEvolutionPort` mixes read and write methods. The HG5 Authority change must split or version the read capability so a read Adapter cannot imply commands exist. Update the Harness Evolution rows in `16-Knowledge-Workspace-Page-State-Matrix-v0.1.csv`: request/revise/rerun/adoption operations remain local proposals or unavailable in HG5, and no row may imply an enabled formal Harness command. Authority must also name the Workbench-local cache owner, storage mechanism, retention/freshness rule, and the exact pure-read versus explicit-refresh boundary. It must define `workbench-growth-projection-validation-receipt/v1` as a non-authoritative Workbench-local record, name `GrowthProjectionV1Adapter` as its sole producer, name `growthProjectionIntegrityV1.ts` as the single producer/consumer integrity implementation, freeze its Harness-compatible canonical-byte and SHA-256 rules, permit Receipt emission only after complete validation PASS, require the validated read and cache snapshot to carry the exact Receipt and explicit refresh and every cache read to revalidate it, and state that the Receipt cannot change Harness projection freshness or provider state. The Page-State Matrix must make Receipt availability explicit for both `VALIDATED` and `LAST_VALIDATED_STALE` states, map an invalid retained cache only to `INVALID` with no snapshot data, and must not imply a PASS Receipt for any failed validation branch.

- [ ] **Step 2: Freeze the read Port**

```typescript
// src/features/harness/models/growthProjectionV1.ts
export interface GrowthProjectionSnapshotIdentity {
  schemaVersion: 'growth-projection/v1';
  asOf: string;
  watermark: string;
}

// src/features/harness/models/growthProjectionValidationReceiptV1.ts
import type {
  GrowthProjectionSnapshotIdentity,
} from './growthProjectionV1';

export type Sha256DigestV1 = `sha256:${string}`;

export interface GrowthProjectionValidationReceiptV1 {
  schemaVersion: 'workbench-growth-projection-validation-receipt/v1';
  receiptId: `growth-projection-validation:${string}`;
  validatedAt: string;
  validatorIdentity: Readonly<{
    id: string;
    version: string;
    contentDigest: Sha256DigestV1;
  }>;
  snapshotIdentity: GrowthProjectionSnapshotIdentity;
  projectionContentDigest: Sha256DigestV1;
  validationState: 'PASS';
  receiptDigest: Sha256DigestV1;
}
```

```typescript
// src/features/harness/integrity/growthProjectionIntegrityV1.ts
import type {
  GrowthProjectionSnapshotIdentity,
  GrowthProjectionV1,
} from '../models/growthProjectionV1';
import type {
  GrowthProjectionValidationReceiptV1,
} from '../models/growthProjectionValidationReceiptV1';

export declare function canonicalProjectionFileBytesV1(
  projection: Readonly<GrowthProjectionV1>,
): Uint8Array;

export declare function deriveGrowthProjectionValidationReceiptV1(input: {
  projection: Readonly<GrowthProjectionV1>;
  snapshotIdentity: Readonly<GrowthProjectionSnapshotIdentity>;
  validatedAt: string;
  validatorIdentity: Readonly<
    GrowthProjectionValidationReceiptV1['validatorIdentity']
  >;
}): Promise<GrowthProjectionValidationReceiptV1>;

export declare function validateGrowthProjectionValidationReceiptV1(input: {
  projection: Readonly<GrowthProjectionV1>;
  snapshotIdentity: Readonly<GrowthProjectionSnapshotIdentity>;
  receipt: Readonly<GrowthProjectionValidationReceiptV1>;
  acceptedValidatorIdentity: Readonly<
    GrowthProjectionValidationReceiptV1['validatorIdentity']
  >;
}): Promise<
  | Readonly<{ state: 'VALID' }>
  | Readonly<{ state: 'INVALID'; reasonCode: string }>
>;
```

```typescript
import type {
  GrowthProjectionSnapshotIdentity,
  GrowthProjectionV1,
} from '../models/growthProjectionV1';
import type {
  GrowthProjectionValidationReceiptV1,
} from '../models/growthProjectionValidationReceiptV1';

export interface GrowthProjectionFailureDetails {
  code: string;
  message: string;
}

export type GrowthProjectionFailedReadContext =
  | Readonly<{
      transportState: 'UNAVAILABLE';
      failure: GrowthProjectionFailureDetails & {
        kind: 'TRANSPORT_UNAVAILABLE';
      };
    }>
  | Readonly<{
      transportState: 'UNKNOWN';
      failure: GrowthProjectionFailureDetails & {
        kind: 'TRANSPORT_UNKNOWN';
      };
    }>
  | Readonly<{
      transportState: 'READY';
      failure: GrowthProjectionFailureDetails & {
        kind: 'VERSION' | 'VALIDATION' | 'IDENTITY' | 'CACHE';
      };
    }>;

export type GrowthProjectionReadResult =
  | Readonly<{
      readState: 'VALIDATED';
      retrieval: Readonly<{
        transportState: 'READY';
        cacheState: 'NOT_USED' | 'CURRENT';
      }>;
      snapshotIdentity: GrowthProjectionSnapshotIdentity;
      projection: Readonly<GrowthProjectionV1>;
      validationReceipt: Readonly<GrowthProjectionValidationReceiptV1>;
      failure?: never;
    }>
  | Readonly<{
      readState: 'LAST_VALIDATED_STALE';
      retrieval: GrowthProjectionFailedReadContext &
        Readonly<{ cacheState: 'STALE' }>;
      retainedSnapshot: Readonly<{
        snapshotIdentity: GrowthProjectionSnapshotIdentity;
        cacheFreshness: Readonly<{
          state: 'STALE';
          observedAt: string;
          reasonCode: string;
        }>;
        projection: Readonly<GrowthProjectionV1>;
        validationReceipt: Readonly<GrowthProjectionValidationReceiptV1>;
      }>;
    }>
  | Readonly<{
      readState: 'UNAVAILABLE';
      retrieval: Readonly<{
        transportState: 'UNAVAILABLE';
        cacheState: 'EMPTY';
        failure: GrowthProjectionFailureDetails & {
          kind: 'TRANSPORT_UNAVAILABLE';
        };
      }>;
      snapshotIdentity?: never;
      retainedSnapshot?: never;
    }>
  | Readonly<{
      readState: 'UNKNOWN';
      retrieval: Exclude<
        GrowthProjectionFailedReadContext,
        Readonly<{ transportState: 'UNAVAILABLE' }>
      > &
        Readonly<{ cacheState: 'EMPTY' }>;
      snapshotIdentity?: never;
      retainedSnapshot?: never;
    }>;

export interface HarnessEvolutionReadPort {
  getGrowthProjection(input: {
    schemaVersion: 'growth-projection/v1';
    asOf: string;
    knownWatermark?: string;
  }): Promise<GrowthProjectionReadResult>;
}
```

`GrowthProjectionV1` is the complete validated Schema model, not a UI summary shape. Its own provider state remains `READY | PARTIAL | STALE | UNAVAILABLE | UNKNOWN` together with the exact watermark, Gate, coverage, closed counts ledger, and typed references. `growthProjectionValidationReceiptV1.ts` imports `GrowthProjectionSnapshotIdentity` from the projection model. `growthProjectionIntegrityV1.ts` owns the one shared producer/consumer algorithm; neither Adapter may implement a second digest path. Its canonical JSON bytes are byte-compatible with Harness `src/evolution_harness/hashing.py::canonical_json_bytes`: recursive JSON only, object keys ordered by Unicode code point, array order preserved, no insignificant whitespace, UTF-8 without ASCII escaping, JSON scalar escaping, and only Schema-valid safe integers for numeric fields. The HG5 plan must add cross-runtime golden fixtures, including non-ASCII strings and numeric boundaries, emitted by the fixed HG3 Harness builder; any unsupported number or byte mismatch is validation failure rather than normalization. Projection file bytes are those canonical JSON bytes plus exactly one LF, and `projectionContentDigest` is `sha256:<64 lowercase hex>` over those complete file bytes. The Receipt core is the closed ordered value `{schemaVersion, validatedAt, validatorIdentity, snapshotIdentity, projectionContentDigest, validationState}`; `receiptDigest` is `sha256:<64 lowercase hex>` over its canonical JSON bytes without LF, and `receiptId` is `growth-projection-validation:<the same 64 lowercase hex>`. `GrowthProjectionV1Adapter` is the sole producer of this Workbench-local Receipt: only after complete Schema, digest, watermark, and identity validation does it call the shared derivation function. The Receipt is non-authoritative; its local `validatedAt` never changes projection freshness or provider state. Validation failure returns a failed read branch and emits no PASS Receipt. The orthogonal `retrieval.transportState` and `retrieval.cacheState` report Adapter transport/cache truth. A retained snapshot keeps its original provider state, identity, and exact validation Receipt plus separate local cache freshness; a failed latest read cannot rewrite that projection state, fabricate an empty projection, or discard validation failure.

- [ ] **Step 3: Freeze the separate local cache Port**

```typescript
import type {
  GrowthProjectionSnapshotIdentity,
  GrowthProjectionV1,
} from '../models/growthProjectionV1';
import type {
  GrowthProjectionValidationReceiptV1,
} from '../models/growthProjectionValidationReceiptV1';

export interface ValidatedGrowthProjectionSnapshot {
  snapshotIdentity: GrowthProjectionSnapshotIdentity;
  validationReceipt: Readonly<GrowthProjectionValidationReceiptV1>;
  projection: Readonly<GrowthProjectionV1>;
}

export interface ValidatedGrowthProjectionCacheEntry
  extends ValidatedGrowthProjectionSnapshot {
  cacheRevision: string;
  storedAt: string;
}

export interface GrowthProjectionCacheReceiptReference {
  kind: 'GROWTH_PROJECTION_CACHE_REFRESH_RECEIPT';
  refreshId: string;
  cacheRevision: string;
  contentDigest: string;
}

export type GrowthProjectionCacheReadResult =
  | Readonly<{
      state: 'FOUND';
      entry: Readonly<ValidatedGrowthProjectionCacheEntry>;
    }>
  | Readonly<{ state: 'EMPTY'; entry?: never }>
  | Readonly<{ state: 'INVALID'; reasonCode: string; entry?: never }>
  | Readonly<{ state: 'UNAVAILABLE'; reasonCode: string; entry?: never }>
  | Readonly<{ state: 'UNKNOWN'; reasonCode: string; entry?: never }>;

export type GrowthProjectionCacheRefreshResult =
  | Readonly<{
      state: 'STORED';
      cacheRevision: string;
      receiptReference: GrowthProjectionCacheReceiptReference;
    }>
  | Readonly<{ state: 'REJECTED'; reasonCode: string }>
  | Readonly<{ state: 'CONFLICT'; currentCacheRevision: string }>
  | Readonly<{
      state: 'UNKNOWN_OUTCOME';
      refreshId: string;
      idempotencyKey: string;
    }>;

export type GrowthProjectionCacheReceiptLookup =
  | Readonly<{
      state: 'FOUND';
      receiptReference: GrowthProjectionCacheReceiptReference;
    }>
  | Readonly<{ state: 'NOT_FOUND' }>
  | Readonly<{ state: 'CONFLICT'; reasonCode: string }>
  | Readonly<{ state: 'LOOKUP_UNAVAILABLE'; reasonCode: string }>
  | Readonly<{ state: 'LOOKUP_UNKNOWN'; reasonCode: string }>;

export interface HarnessEvolutionCachePort {
  readonly capability: 'CACHE_NOT_ENABLED' | 'VALIDATED_SNAPSHOT_CACHE_V1';

  readLastValidated(): Promise<GrowthProjectionCacheReadResult>;

  refreshValidated(input: {
    refreshId: string;
    idempotencyKey: string;
    payloadHash: string;
    expectedCacheRevision?: string;
    snapshot: Readonly<ValidatedGrowthProjectionSnapshot>;
  }): Promise<GrowthProjectionCacheRefreshResult>;

  findRefreshReceipt(input: {
    refreshId: string;
    idempotencyKey: string;
  }): Promise<GrowthProjectionCacheReceiptLookup>;
}
```

`getGrowthProjection`, `readLastValidated`, and `findRefreshReceipt` are pure reads. On every `readLastValidated`, the Cache Adapter parses and Schema-validates the complete entry, recomputes the projection file digest and snapshot identity/watermark relation, and calls the shared Receipt validator against the complete Receipt and accepted validator identity. Only exact agreement may return `FOUND`. Any malformed entry, projection/Receipt/snapshot mismatch, forged digest, unsupported canonical value, or failed Receipt validation returns `INVALID` with no `entry`; the Read Adapter may form `LAST_VALIDATED_STALE` only from `FOUND`, never from `INVALID`, `UNAVAILABLE`, or `UNKNOWN`. `refreshValidated` is the only HG5 write: it performs the same shared validation, recomputes Schema/as-of/watermark and PayloadHash equality, verifies the complete validation Receipt identity/digest against those same bytes and validator, and accepts no caller-supplied cache Revision or storage time. Under one owner-controlled CAS lock, the Adapter generates `cacheRevision` and authoritative `storedAt`, atomically stores and durably rereads the entry, then returns a queryable local receipt. IdempotencyKey reuse with a different recomputed PayloadHash is conflict. `UNKNOWN_OUTCOME` retains both lookup keys; `NOT_FOUND`, `LOOKUP_UNAVAILABLE`, and `LOOKUP_UNKNOWN` all keep the refresh unresolved and forbid another refresh until a found authoritative Receipt or conflict resolves it. When capability is `CACHE_NOT_ENABLED`, refresh returns `REJECTED/CACHE_NOT_ENABLED` and creates no record. If Project Helm cannot prove the selected browser/local-host storage's atomicity, isolation, retention, and recovery semantics, capability remains disabled and the UI shows no fabricated last-known state.

- [ ] **Step 4: Keep command capability disabled**

HG5 exposes `CAPABILITY_NOT_ENABLED`. A retry may perform a pure provider/cache read or explicitly invoke the bounded cache refresh above after validation; it cannot submit a Harness command or mutate Harness, Runtime, or a target project.

- [ ] **Step 5: Extend UI semantics without inferred success**

Add the missing `declared` axis to the Harness lifecycle presentation. Add explicit `UNKNOWN` provider handling. A Release never implies configured, loaded, invoked, or effective. Search results carry typed reference/watermark identity instead of a display version alone.

- [ ] **Step 6: Require contract, build, Storybook, Playwright, and visual evidence**

```bash
pnpm test:contracts
pnpm verify:web-scope
pnpm design-tokens:check
pnpm build
pnpm storybook:build
pnpm test:visual:components
pnpm exec playwright test
git diff --check
```

The HG5 plan must define exact fixtures for each validated projection provider state; transport unavailable/unknown with and without a retained snapshot; unsupported version, invalid Schema, identity mismatch, corrupt cache, changed watermark, forged validation Receipt or PayloadHash, caller attempts to supply/forge cache Revision or storage time, cache CAS conflict/interruption/unknown outcome and every unresolved lookup result, and cache-disabled behavior; plus command-disabled behavior. Cross-runtime golden tests must prove the Workbench integrity utility matches fixed Harness canonical projection bytes and all three digest/ID derivations. Cache contract tests must prove every read revalidates the complete entry, each corruption/mismatch returns `INVALID` without `entry`, and no invalid cache can produce `LAST_VALIDATED_STALE`. Tests must also prove retained valid snapshots keep their original provider state while local cache freshness becomes stale, every pure read has zero writes, and explicit refresh writes only the single authorized cache record and receipt. It must obtain Project Helm's required fixed-candidate review before claiming closure.

- [ ] **Step 7: Stop with read capability only**

No local formal Candidate, Experiment, Promotion, Adoption, Runtime mutation, or optimistic command success exists in HG5.

---

### Task 8: Plan HG6 as Two Explicitly Authorized Commands

**Files:**

- Reserved Project Helm phase-plan path: `docs/superpowers/plans/2026-09-01-harness-growth-hg6-improvement-commands.md`
- Proposed Create: `src/features/harness/ports/HarnessEvolutionCommandPort.ts`
- Proposed Create: `src/features/harness/models/harnessGrowthCommandsV1.ts`
- Proposed Create: `src/features/harness/models/growthImprovementProposal.ts`
- Proposed Create: `src/features/harness/adapters/HarnessEvolutionCommandAdapter.ts`
- Proposed Create: `src/features/harness/components/GrowthImprovementProposalPanel.tsx`
- Proposed Modify: `src/features/harness/components/HarnessEvolutionPage.tsx`
- Proposed Modify: `src/features/harness/components/HarnessNeedsYouProjection.tsx`
- Proposed Modify: `src/features/harness/components/index.ts`
- Proposed Story: `stories/features/harness/GrowthImprovementProposalPanel.stories.tsx`
- Proposed Modify: `stories/features/harness/HarnessEvolutionPage.stories.tsx`
- Proposed Test: `tests/contracts/harness-evolution-command-port.test.ts`
- Proposed Test: `tests/contracts/growth-improvement-proposal.test.ts`
- Proposed Test: `tests/contracts/harness-command-adapter.test.ts`
- Proposed Test: `tests/contracts/growth-improvement-proposal-panel.test.tsx`
- Proposed Visual Test: `tests/visual/pages/harness-evolution.spec.ts`

**Interfaces:**

- Consumes: a local proposal, explicit user approval, and the exact Harness subject/version/digest precondition.
- Produces: a versioned command envelope, queryable receipt state, conflict presentation, and Unknown Outcome recovery for Candidate/Experiment creation only.

- [ ] **Step 1: Freeze the command capability negotiation**

```typescript
import type {
  CreateCandidateCommandEnvelopeV1,
  CreateExperimentCommandEnvelopeV1,
  GrowthCommandReceiptReferenceV1,
} from '../models/harnessGrowthCommandsV1';

export type GrowthCommandKind =
  | 'CREATE_CANDIDATE'
  | 'CREATE_EXPERIMENT';

export interface GrowthProposalApprovalCore {
  proposalId: string;
  proposalState: 'APPROVED';
  decision: 'APPROVE';
  decidedBy: string;
  decidedAt: string;
  decisionDigest: string;
  subjectReferenceDigest: string;
  payloadHash: string;
  preconditionDigest: string;
}

export type ApprovedGrowthCommandSubmission =
  | Readonly<{
      proposalBinding: Readonly<
        GrowthProposalApprovalCore & { commandKind: 'CREATE_CANDIDATE' }
      >;
      envelope: Readonly<CreateCandidateCommandEnvelopeV1>;
    }>
  | Readonly<{
      proposalBinding: Readonly<
        GrowthProposalApprovalCore & { commandKind: 'CREATE_EXPERIMENT' }
      >;
      envelope: Readonly<CreateExperimentCommandEnvelopeV1>;
    }>;

export type CommandSubmissionResult =
  | Readonly<{ state: 'ACCEPTED_FOR_PROCESSING'; commandId: string }>
  | Readonly<{
      state: 'SUCCEEDED';
      receiptReference: GrowthCommandReceiptReferenceV1;
    }>
  | Readonly<{ state: 'REJECTED'; reasonCode: string }>
  | Readonly<{ state: 'CONFLICT'; reasonCode: string }>
  | Readonly<{
      state: 'UNKNOWN_OUTCOME';
      commandId: string;
      idempotencyKey: string;
    }>;

export type CommandReceiptLookup =
  | Readonly<{
      state: 'FOUND';
      receiptReference: GrowthCommandReceiptReferenceV1;
    }>
  | Readonly<{ state: 'NOT_FOUND' }>
  | Readonly<{ state: 'CONFLICT'; reasonCode: string }>
  | Readonly<{ state: 'LOOKUP_UNAVAILABLE'; reasonCode: string }>
  | Readonly<{ state: 'LOOKUP_UNKNOWN'; reasonCode: string }>;

export interface HarnessEvolutionCommandPort {
  readonly capability:
    | 'CAPABILITY_NOT_ENABLED'
    | 'CREATE_CANDIDATE_AND_EXPERIMENT_V1';

  submit(
    input: ApprovedGrowthCommandSubmission,
  ): Promise<CommandSubmissionResult>;

  findReceipt(input: {
    commandId: string;
    idempotencyKey: string;
  }): Promise<CommandReceiptLookup>;
}
```

`harnessGrowthCommandsV1.ts` is generated or manually frozen from the reviewed HG3 command Schemas before HG6 implementation; it is never an open `Record<string, unknown>` escape hatch. Both formal envelope branches carry exactly `commandId`, `idempotencyKey`, `commandKind`, `requestedBy`, `requestedAt`, `payloadHash`, one command-specific closed precondition, and one command-specific closed payload. The enclosing service submission additionally carries the immutable local APPROVE binding. The Adapter validates its decision digest, subject/precondition digest, command kind, actor, and payload hash before sending the complete submission; the Harness repeats the same validation before acceptance and binds the approval digest into its Receipt. A changed or mismatched binding is rejected locally and server-side.

- [ ] **Step 2: Keep the proposal local until approval**

Workbench can create or refresh a deduplicated `GrowthImprovementProposal`; it cannot create an authoritative record. Preserve all eight local suggested actions and all seven proposal states from Spec 7.11. `REVISE_EXPERIMENT`, `RERUN_EXPERIMENT`, `REVALIDATE`, `NARROW_SCOPE`, `SUPERSEDE`, and `RETIRE` remain reviewable local/Needs You proposals but cannot produce a submittable envelope. `REJECTED` forbids submission; `SUBMITTED`, `UNKNOWN_OUTCOME`, and `CONFIRMED` retain the immutable APPROVE decision plus submission/receipt state. The approval event selects exactly one enabled command kind and freezes the subject, payload hash, and precondition digest.

- [ ] **Step 3: Implement only closed creation preconditions**

`CREATE_CANDIDATE` requires one or more exact Experience references, each containing Experience ID, `experience/v1`, canonical content digest, source Revision, current `triageStatus: TRIAGED`, and current `triageDecision: CROSS_PROJECT_CANDIDATE`, plus a deterministic Candidate creation key that does not exist. `CREATE_EXPERIMENT` requires an exact Candidate bundle reference, current Authority decision, current Promotion state, and a deterministic Experiment creation key that does not exist. The proposal binding's command kind, subject/reference digest, precondition digest, actor, and payload hash must match the selected formal envelope byte-for-byte.

- [ ] **Step 4: Treat unknown outcome as lookup-only recovery**

`UNKNOWN_OUTCOME` retains the proposal and command identity, disables blind replay, and calls `findReceipt`. `NOT_FOUND`, `LOOKUP_UNAVAILABLE`, and `LOOKUP_UNKNOWN` all preserve the unresolved state and continue to forbid replay; only an authoritative found Receipt or conflict changes the recovery decision. A different payload under the same IdempotencyKey is a conflict.

- [ ] **Step 5: Prove every excluded command stays unavailable**

Tests must reject Revise, Rerun, Revalidate, Narrow Scope, Promotion, Release, Adoption, Runtime mutation, Supersession, Retirement, arbitrary command strings, and a Candidate/Experiment submit without a fresh exact approval binding. They also reject expired, mismatched-command, changed-subject, changed-precondition, changed-payload, changed-actor, and server-rejected approval bindings, and require the successful Harness Receipt to repeat the exact approval digest. When capability is `CAPABILITY_NOT_ENABLED`, `submit` returns `REJECTED/CAPABILITY_NOT_ENABLED` without creating a command; read refresh and receipt lookup remain read-only.

- [ ] **Step 6: Run the complete Project Helm Gate and independent review**

Run the HG5 command set plus command contract, failure, keyboard, accessibility, and visual-state tests. Stop before push, deployment, or external command enablement unless the user separately authorizes the exact endpoint and payload.

---

### Task 9: Maintain Program Traceability and Stop at Every Boundary

**Files:**

- Modify only the active phase's approved plan/report files.
- Do not create one mutable cross-phase completion flag.

**Interfaces:**

- Consumes: phase-specific fixed identities, Gate outputs, reviews, and user decisions.
- Produces: an append-only program matrix that keeps design, plan, implementation, review, local landing, push, Runtime, Release, adoption, and effectiveness separate.

- [ ] **Step 1: Report each phase with explicit denominators**

```text
DESIGN
PLAN
IMPLEMENTATION
FOCUSED_TESTS
COMPLETE_GATE
FIXED_CANDIDATE_REVIEW
LOCAL_LANDING
REMOTE_PUSH
RUNTIME_ENABLED
REAL_PROJECT_PILOT
WORKBENCH_READ_ADOPTION
COMMAND_CAPABILITY_ENABLED
```

Each row is `PASS | FAIL | NOT_STARTED | NOT_AUTHORIZED | NOT_APPLICABLE` with exact identity and receipt. Never derive one row from another.

- [ ] **Step 2: Revalidate predecessor identity before successor work**

If a predecessor tree or Authority changes, rerun the affected Gate and determine whether the successor plan is still valid. Do not edit another project's lock, Authority, generated projection, or validator to hide drift.

- [ ] **Step 3: Preserve final user choices as separate authority events**

A user decision to execute HG1 does not authorize local landing. Local landing does not authorize push. HG4 project authorization does not authorize HG5 Project Helm changes. HG5 read approval does not authorize HG6 commands.

- [ ] **Step 4: End the program only on evidence, not schedule**

The complete growth goal is met only when all authorized phases have their own fresh Gate and review, at least two real projects provide the HG4 evidence population, Workbench reads the validated projection without becoming authority, and every enabled command remains explicitly human-authorized and receipt-backed.

## Spec Coverage Matrix

| Approved Spec section | Implementing phase/task | Coverage rule |
| --- | --- | --- |
| 1–3 Problem, goals, non-goals | Global Constraints; Tasks 1–9 | One growth system; no implicit Project Helm registration or automation |
| 4 Existing compatibility | Tasks 2, 4, 5 | Existing Experience/Candidate/Eval/Capability/ledger contracts remain unchanged |
| 5 Architecture and data flow | Program order; Tasks 2–8 | Each owner boundary is delivered in its own phase |
| 6 Authority and ownership | Global Constraints; Tasks 6–9 | Source projects and Runtime own evidence; Harness owns lifecycle/projection; Workbench owns local UI state only |
| 7.1 Shared primitives and Candidate bundle | Task 4 | Strict refs, safe YAML, one-open bundle capture, raw/canonical digests, CAS identities |
| 7.2–7.3 Expectation, Experiment, Trial, Eval and Promotion contracts | Tasks 4–5 | HG2 validates contracts and materializes only the separately approved bootstrap binding; HG3 alone enables Runtime lifecycle writes |
| 7.4–7.10 Release, Project, Adoption, Effect and projection | Tasks 4–7 | Pure deterministic builder precedes real data and Workbench consumption |
| 7.11 Local proposal | Tasks 7–8 | Proposal is local; formal command submission waits for approval |
| 8 Lifecycle rules | Tasks 4–5 | Append-only revisions, closed transitions, Plan/journal/CAS/Receipt order |
| 9 Expectation evaluation | Tasks 4 and 6 | Frozen expectations, typed outcomes, no single Growth Score |
| 10 Cross-project questions | Tasks 4, 6, 7 | Projection and Workbench retain project, revision, Runtime, model, digest, time, coverage, and cohort |
| 11 Human authority and commands | Tasks 5 and 8 | HG3 owns the two closed Harness command/receipt services; HG6 exposes only their approved Workbench Adapter branches |
| 12 Failure and degraded behavior | Tasks 2–8 | Negative fixtures and provider/UI states fail closed without inferred zeros or success |
| 13 Privacy, security, storage | Global Constraints; Tasks 1, 2, 4, 6, 7 | Owner-only external state, one approved immutable bootstrap binding, bounded references, zero source writes, no raw bodies |
| 14 Verification Gates | Task 3 and phase-specific closure steps | RED/GREEN, complete Gate, fixed identity, independent review |
| 15 Delivery sequence | Program order | No phase skipping or cross-phase WriteSet |
| 16 Pilot acceptance | Task 6 | Two projects, 10–20 Receipts, full lineage, negative evidence, metrics, zero-write |
| 17 Stop conditions | Global Constraints; Task 9 | Authority, privacy, writes, automation, scope, destructive/external actions stop work |
| 18 Current reality | Task 1 | Refresh live state; never treat 2026-09-01 observations as future PASS |
| 19 Traceability | Spec header; Program Decomposition | Every phase names the fixed predecessor and its plan authority |

## Execution Handoff

The next executable unit is HG1 under `docs/superpowers/plans/2026-08-13-growth-assessment-protocol-phase-1.md`, preceded by Task 1 reconciliation in this program plan.

Two execution options are available:

1. **Subagent-Driven (recommended):** use `superpowers:subagent-driven-development`, dispatch a fresh bounded worker for each HG1 task, and perform specification and quality review between tasks.
2. **Inline Execution:** use `superpowers:executing-plans`, execute HG1 in batches with explicit checkpoints.

Neither option includes merge, push, scheduling, project registration, HG2 implementation, or Project Helm changes.
