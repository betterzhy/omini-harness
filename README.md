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

Machine-readable commands support `--format json`; engineering compatibility supports:

```text
eng validate --json
eng registry build --check --json
eng catalog build --check --json
eng doctor --ci --json
eng context resolve --json
eng test --json
```

## Local acceptance sequence

```bash
python -m pip install -e '.[test]'
./harness validate --check-generated --format json
./harness registry build --check --format json
./harness catalog build --check --format json
./harness project lock --project examples/project-fixture --check --format json
./harness projection build --project examples/project-fixture --intent architecture-review --topic resolver-mvp --output 'review findings' --runtime CHATGPT --check --format json
./harness projection build --project examples/project-fixture --intent architecture-review --topic resolver-mvp --output 'review findings' --runtime CODEX --check --format json
./eng doctor --ci --json
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q
```

## Bootstrap cutoff

`core/governance/bootstrap-baseline.yaml` declares the v0.1.0 seed cutoff. Seed capability ID/version hashes are `BOOTSTRAP_AUTHORIZED`. New canonical capability versions must enter through the normal governed promotion ledger; adding arbitrary canonical files without authority evidence fails repository validation.

## Deliberate MVP limits

Eval execution records manual/fixture results rather than using an automatic model judge. Project conflict detection relies on explicit constraints rather than reading every baseline semantically. Version resolution is exact/highest-current, not a package-manager range solver. Revalidation identifies due/triggered assets but does not perform revalidation. Runtime packs are generated for explicit installation; no ChatGPT project configuration API or Custom GPT rewriting is invoked.

## Next step

Do not expand schema breadth first. Apply this package to the real Brownfield checkout and dogfood it in this order: Agent-Native Software Engineering → Agent Continuous Learning → Payment Platform. Measure resolver selection quality, context size, CLOSED-topic preservation, applicability, runtime consistency, feedback quality, false-positive learning, mega-skill pressure, model sensitivity, and human-authority friction before adding automation.
