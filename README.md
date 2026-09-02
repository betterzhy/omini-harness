# Agent Evolution Harness — Design Evolution Repository Bootstrap MVP

This repository is an executable bootstrap for the CLOSED Agent Design Evolution architecture. It extends the prior repository-local Continuous Learning model into one **Unified Evolution Workspace** without creating a second learning platform.

> Registry, active catalog, lock, resolved context, discussion contract, handoff, and ChatGPT/Codex packs are generated projections. Canonical meaning remains in design capability assets, project-authoritative artifacts/references, and governed learning records.

## What the MVP proves

```text
Canonical Design Capability
  → schema / identity / version validation
  → generated design registry
  → generated active catalog
  → project binding + exact lock
  → deterministic resolver + explain trace
  → resolved context
  → discussion contract
  → runtime projection
      ├─ ChatGPT Project Pack
      └─ Codex Repository Pack

Design Interaction / Repository Feedback
  → selective Experience
  → explicit triage
  → Candidate wrapper
  → Eval Result bound to capability/projection/runtime/model
  → human-authority promotion
  → canonical capability + immutable promotion ledger
```

The MVP intentionally has no vector database, embeddings, graph database, remote registry, server, database, workflow engine, autonomous promotion, conversation scraper, automatic closure/reopen, or LLM-required resolver.

## Brownfield migration boundary

The original richer Continuous Learning source checkout was not mounted in this execution environment. The engineering domain here is therefore a **migration-ready compatibility implementation**, not a claim of byte-for-byte in-place refactoring. In a real merge, retain richer existing `engineering_cli` modules and wire reusable mechanics to `evolution_harness` rather than deleting working code.

## Repository layout

```text
core/                     shared schemas, vocabulary, bootstrap/promotion governance
design/                   canonical design capabilities, Experiences, Candidates, Evals
engineering/              Brownfield-compatible repository learning domain
runtime/                  profiles, adapter descriptors, stable runtime templates
tooling/                  implementation-tool boundary only
examples/                 project/runtime fixtures
integrations/             Harness-owned Brownfield sidecars and scenario fixtures
generated/                rebuildable registries, catalogs, runtime packs
src/evolution_harness/    unified implementation
src/engineering_cli/      engineering compatibility facade
tests/                    unit/schema/resolver/projection/E2E tests
verification/             executable verification assets
harness                   unified CLI
eng                       engineering compatibility CLI
```

## Canonical capability representation

```text
design/capabilities/<kind>/<name>/
├── asset.yaml
└── content.md
```

Durable identity is `kind:namespace:name`. It does not include path, semantic version, runtime, model, or projection version. Common YAML contains only metadata that machines need; long-form rationale, analytical guidance, procedures, and workflow guidance remain Markdown unless a resolver or validator must interpret them structurally.

The four canonical design kinds are `PRINCIPLE`, `FRAMEWORK`, `SKILL`, and `WORKFLOW`. A Candidate remains a governance wrapper around a proposed normal capability.

## Project integration

```text
.agent-evolution/
├── design-state.yaml
├── capabilities.yaml
├── capabilities.lock.yaml       generated exact resolution
├── handoff-input.yaml           small project-authored handoff fields
├── design-handoff.yaml          generated reference-first projection
└── feedback/
```

`design-state.yaml` is a routing/control plane. CLOSED topics are explicit and default to `DO_NOT_REOPEN`. An explicit represented reopen signal only produces review-required state; the resolver never mutates CLOSED → OPEN.

Existing repositories can also be registered without receiving Harness control files. A Harness-owned integration directory contains `integration.yaml`, an explicit authority map, a sidecar control plane, and executable scenarios. Source access is read-only and allowlist-based; excluded paths are rejected before reading. Every authority is read through a no-symlink directory anchor, and the same captured bytes drive its content hash, fact extraction and Git cleanliness comparison. Canonical and specialized project facts become a fingerprinted Authority Snapshot, while derived reports may be referenced but cannot own facts.

```text
integrations/<id>/
├── integration.yaml
├── authority-map.yaml
├── control-plane/.agent-evolution/
└── scenarios/
```

The sidecar's stage describes the integration work, not the external project's delivery stage. External project state remains in its own authority files and always wins over shared capability guidance.

After a sidecar has been accepted, a project can opt into repository-local discovery with one routing file:

```text
<project>/.agent-evolution/registration.yaml
```

The registration records only the Harness identity, repository-relative integration identity/path, `SELF` source root, `READ_ONLY` access, runtime and exact capability-lock fingerprint. It cannot contain project stage, topic state, authorization, architecture text or capability bodies. The Harness validates the registration and exact lock before reusing the sidecar's live Authority Snapshot; it does not create a second project state system. Explicit `--integration` calls remain supported, but if a registration is present an explicit path must identify the same integration.

`integration registration-check --source <project>` validates only this discovery/binding boundary. `integration inspect`, `integration resolve` and `integration projection` can omit `--integration` when the source has a valid registration. Discovery does not authorize project writes, and it does not change the separate plan-only materialization boundary below.

## Deterministic resolver

```text
request
→ explicit project state
→ binding/profile
→ lifecycle + validity + supersession
→ runtime
→ intent + stage + sparse scope
→ workflow-required capabilities
→ bounded dependency expansion
→ selected / excluded + explain trace
```

The resolver does not invoke an LLM. Explicit project state wins over reusable guidance and conflict signals use `PROJECT_TRUTH_WINS`.

Exact locks record capability ID, version and canonical content hash. Their `sourceHarnessRevision` is a reproducible digest of that exact selected source set, so synchronized metadata edits fail verification while unrelated future catalog versions do not silently move an existing project lock.

## Runtime projection

A canonical Skill can generate runtime `SKILL.md`; only explicitly selected and referenced Principle/Framework content is materialized. Both ChatGPT and Codex packs record the same source capability ID/version/hash while using independent packaging/projection versions.

ChatGPT pack:

```text
generated/projections/chatgpt/<project>/
├── project-instructions.md
├── resolved-context.md
├── resolved-context.json
├── discussion-contract.md
├── skills/**/SKILL.md
└── projection-manifest.json
```

Codex pack uses `repository-guidance.md` and `resolved-task-context.md`, also includes `resolved-context.json`, and never overwrites project `AGENTS.md`.

Projection installation is a manifest-aware, dry-run planning boundary. The planner deterministically revalidates the pack from canonical capability, exact lock, resolved context and control-plane inputs; an integration pack must also remain fresh against the installation target's complete live Authority Snapshot. The validated Skill bytes are snapshotted while holding the same pack lock used by the builder. Only resolved generated `skills/*/SKILL.md` files can map to repo-local `.agents/skills/`; existing unmanaged skills, changed managed files, symlinks, unsafe paths, and missing ownership evidence fail closed. `AGENTS.md` is outside the planned write set. `projection install --apply` and `projection uninstall --apply` are deliberately disabled: a separate project-authorized materialization/removal step must consume and revalidate the plan. Any legacy transaction journal or recovery attestation fails closed for manual recovery without touching project paths. Projection-pack swaps remain directory-descriptor anchored and journaled. Cross-process pack and target locks make concurrent planners/builders fail closed; the OS releases those locks after process termination.

## Governed learning

Experience stores distilled behavior/correction/impact plus a source reference; it has no transcript field. Candidate promotion is dry-review by default and requires explicit approval metadata plus required PASS eval results. `BROADEN_SCOPE` additionally requires independent evidence, cross-case analysis, counterexample review, and a transfer eval. `SUPERSEDE` requires the proposed capability to explicitly point to the superseded target.

CI proves mechanical integrity only. Structural pass is reported separately from semantic quality:

```text
structuralGate = PASS | FAIL
semanticGate   = NOT_ASSERTED_BY_CI
```

## CLI

```text
harness validate
harness list
harness show
harness registry build
harness catalog build
harness resolve --explain
harness planning plan --request <file>
harness coordination status --source <registered-project>
harness coordination acquire --source <registered-project> --request <command-file>
harness coordination transition --source <registered-project> --request <command-file>
harness coordination observe --source <registered-project> --request <command-file>
harness coordination recover --source <registered-project> --request <command-file>
harness project bind
harness project lock
harness experience capture
harness experience triage
harness candidate create
harness candidate promote
harness eval run
harness projection build
harness projection install --pack <pack> --target <project>
harness projection uninstall --target <project>
harness integration registration-check --source <project>
harness integration inspect --integration <sidecar> --source <project>
harness integration lock --integration <sidecar>
harness integration resolve --integration <sidecar> --source <project> --explain
harness integration projection --integration <sidecar> --source <project>
harness integration scenario --integration <sidecar> --source <project> --scenario <file>
harness discussion materialize
harness discussion route-next
harness handoff build
harness feedback capture
harness revalidation check
```

Machine-readable commands support `--format json`; engineering compatibility supports:

```text
eng validate --json
eng registry build --check --json
eng catalog build --check --json
eng doctor --ci --json
eng context resolve --json
eng test --json
```

### Phase 1B coordination safety boundary

The five `coordination` commands are JSON-only. `status` requires an explicit registered `--source`; every mutating operation also requires an explicit `--request` containing the complete authority-bound coordinator command. Durable state is Harness-owned and defaults to `~/.codex/state/agent-evolution-harness/coordinator/v1`. Tests and isolated Harness environments may set `AGENT_EVOLUTION_COORDINATOR_ROOT` to a fresh owner-only state directory.

Phase 1B records and inspects project-scoped safety leases only. It does **not** launch work or agents, create worktrees, write registered project files, mutate project authority or lifecycle files, integrate candidates, update Git refs, merge or push, release or deploy, enter Landing or a Wave, or authorize Pay-Nexus development. A lease is a fencing and admission-safety record, not project implementation authority.

A persistent WriteSet breach places the entire project coordinator into explicit recovery. Recovery never deletes project evidence: a current project recovery authority must submit a signed `coordination recover` command that exactly binds the pending journal version, complete observed WriteSet, affected leases, and quiescence proofs. Recovery releases retained capacity only after that receipt is durable, and all revoked batch and attempt identities remain retired; later admission needs a fresh authorized plan.

Protected actions remain denied even when a request claims permission: formal database writes, migration application, destructive operations, production or secret access, Landing, Wave entry, push, release, and deployment.

### Growth Assessment Protocol (GAP) Phase 1 boundary

GAP Phase 1 is a narrow, receipt-backed assessment intake. It records whether a
completed task supplies a reusable-growth signal; it does not make a learning
decision or change a project. The assessment risk levels are deliberately
separate from the project result: `R0` is skipped; `HUMAN_CORRECTION`,
`REPEATED_FRICTION`, `SHARED_GUIDANCE_CONFLICT`, `CONTRACT_AMBIGUITY`, and
`VERIFICATION_GAP` use `R1`; and an adopted `R2` trigger (formal closure,
fixed-candidate review, Gate failure, Authority/governance change,
security/recovery/concurrency finding, or Contract/Schema/projection change)
requires an assessment. The request carries the independent `projectGate`
(`PASS`, `FAIL`, `BLOCKED`, or `NOT_RUN`); it must never be inferred from,
replaced by, or reported as `growthCaptureGate`.

An assessment concludes either `SIGNAL` or `NO_SIGNAL`. For example, a repeated
reusable verification failure supported by distilled evidence can be an `R1`
`SIGNAL`; a one-off project-local correction, accidental event, non-transferable
fact, already-covered issue, or insufficient evidence is a `NO_SIGNAL`. A
`SIGNAL` is only an explicit `HUMAN_TRIAGE_REQUIRED` disposition in a scan; a
`NO_SIGNAL` is `NO_ACTION`. Neither outcome is a runtime enablement, adoption,
landing, push, release, or promotion claim.

The Inbox is external to both the Harness and source project worktrees. With no
explicit `--state-root`, its location is
`$CODEX_HOME/agent-evolution/growth/v1`; `CODEX_HOME` must be present and
absolute. An explicit state root must also be absolute and must not be inside a
protected Harness, source, or Git worktree. The state root and its fixed
`inbox`, `staging`, and `locks` directories are owner-only (`0700`), and the
Inbox lock is owner-only (`0600`). `assess` may append one validated Receipt;
`receipt` and `scan` open the Inbox read-only. Assessment and scan never write
the Harness worktree or a project worktree.

All Growth commands are JSON-only and require their explicit arguments. Prefer
stdin for the bounded, single-read request; `--request` accepts `-` or an
absolute regular request file. The request is structured metadata plus bounded
distillations: it must not contain a transcript, messages, prompts, responses,
raw logs, source-body bytes, or a claim that opaque evidence references are
readable files.

```bash
# Read one request from stdin and append only an external Receipt when source
# validation and the external Inbox are available.
./harness growth assess \
  --source /absolute/path/to/registered-project \
  --request - \
  --format json < assessment.yaml

# Read and validate one existing Receipt without changing it.
./harness growth receipt \
  --id growth-assessment:0123456789abcdef01234567 \
  --check \
  --format json

# Read-only report over the external Inbox at an explicit cutoff.
./harness growth scan \
  --as-of 2026-09-02T00:00:00Z \
  --format json
```

`growthCaptureGate=PASS` means only that a typed Receipt was recorded or an
exact prior Receipt was returned as `DUPLICATE`; `DEFERRED` is limited to an
unavailable state root or a busy Inbox lock and must be retried with the same
request/source context. A failed capture is not a project Gate conclusion.
Receipt and scan validate existing data rather than repair it; scan can return
`gate=FAIL` for invalid Inbox entries while remaining read-only.

Phase 1 implements no Skill, Hook, scheduler, repository scanner, transcript
capture, source-body capture, automatic Experience import, Candidate creation,
Eval creation, capability change, projection, or Promotion. A later human
triage/import step may sanitize an explicitly selected Receipt into an
`UNTRIAGED` Experience under its own authority; that later boundary is not
executed by these commands. Phase 2--4 behavior is intentionally not described
here as implemented.

## Local acceptance sequence

```bash
python -m pip install -e '.[test]'
./harness validate --scope core --check-generated --format json
./harness validate --scope adoption --check-generated --format json
./harness validate --scope all --check-generated --format json
./harness registry build --check --format json
./harness catalog build --check --format json
./harness project lock --project examples/project-fixture --check --format json
./harness projection build --project examples/project-fixture --intent architecture-review --topic resolver-mvp --output 'review findings' --runtime CHATGPT --check --format json
./harness projection build --project examples/project-fixture --intent architecture-review --topic resolver-mvp --output 'review findings' --runtime CODEX --check --format json
./eng doctor --ci --json
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q
```

The `core` scope is the routine Harness candidate Gate: it validates only
Harness-owned, project-independent structure and generated artifacts. The
`adoption` scope reports project and integration consumption status, while `all`
is the compatibility and release-wide aggregate. Adoption failures remain
fail-closed in both `adoption` and `all`; a green `core` result does not assert
that any project adoption is current or valid. Omitting `--scope` is equivalent
to `--scope all`.

## Bootstrap cutoff

`core/governance/bootstrap-baseline.yaml` declares the v0.1.0 seed cutoff. Seed capability ID/version hashes are `BOOTSTRAP_AUTHORIZED`. New canonical capability versions must enter through the normal governed promotion ledger; adding arbitrary canonical files without authority evidence fails repository validation.

External Capability Pack registration is materialized in a separate generated
registry. It does not add Pack entries to the internal unified catalog and does
not by itself establish adoption or execution authority in any project.

## Deliberate MVP limits

Eval execution records manual/fixture results rather than using an automatic model judge. Project conflict detection relies on explicit constraints rather than reading every baseline semantically. Version resolution is exact/highest-current, not a package-manager range solver. Revalidation identifies due/triggered assets but does not perform revalidation. Runtime packs are generated for explicit installation; no ChatGPT project configuration API or Custom GPT rewriting is invoked.

Controlled planning is a deterministic Phase 1A projection only. It validates explicit authority-backed descriptors as input and emits a provisional, stdout-only plan. It does not discover missing concurrency facts, admit work, create worktrees, acquire leases, execute Slices, integrate commits, or write a registered project. Projects without the controlled model retain their existing serial flow.

## Next step

Do not expand schema breadth first. Register Brownfield projects through Harness-owned, read-only sidecars and validate neutral fixtures before any project-local installation. Measure resolver selection quality, context size, CLOSED-topic preservation, applicability, runtime consistency, feedback quality, false-positive learning, mega-skill pressure, model sensitivity, and human-authority friction before adding automation.
