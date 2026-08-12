# Agent Design Evolution Repository Bootstrap — Approved Implementation Design

## Status

This document materializes the user-approved CLOSED architecture for executable implementation. It does not reopen conceptual decisions.

## Goal

Build the smallest executable **Unified Agent Evolution Workspace** that upgrades the prior repository-local Continuous Learning model with pre-repository Design Evolution while preserving the engineering domain and common governance mechanics.

The MVP must prove the end-to-end chain:

```text
Experience -> Candidate -> Eval -> Human Promotion -> Canonical Capability
-> Registry -> Active Catalog -> Project Binding/Lock -> Deterministic Resolver
-> Resolved Context -> Runtime Projection (ChatGPT/Codex) -> Feedback -> Experience
```

## Architecture

The physical workspace is responsibility-oriented:

```text
core/          shared schema/vocabulary/governance mechanics
design/        canonical design capabilities + design learning + evals
engineering/   prior Continuous Learning compatibility domain
runtime/       profiles and runtime projection adapters/templates
tooling/       tooling boundary/support files
generated/     rebuildable registries/catalogs/projections
src/           executable Python implementation
examples/      project/runtime fixtures
tests/         structural/runtime/end-to-end verification
```

Canonical capability identity is `kind:namespace:name`; semantic version is separate. Canonical meaning lives in `design/capabilities/**/asset.yaml + content.md`. Registry, catalog, lock, resolution, discussion contract, handoff, and runtime projections are derived artifacts.

## Shared core vs domain payload

Reuse one shared implementation for identity, SemVer, schema loading, hashing, lifecycle/validity, scope vocabulary, provenance/visibility, relationship validation, generated-file drift, and promotion-ledger immutability.

Do **not** create one universal capability payload. Principle, Framework, Skill, and Workflow retain kind-specific schemas. Human/model-rich semantics remain Markdown unless a machine must query or validate them.

## Resolver

Resolver V1 is deterministic and metadata-first. It consumes project state, capability binding/profile, active catalog, workflow metadata, intent/stage/runtime/scope, disabled capability declarations, and bounded dependency expansion. It must not require embeddings, vector search, or an LLM.

Explicit project state and project canonical constraints outrank generic shared guidance. CLOSED topics are discoverable and not reopened automatically.

## Learning governance

Experience stores distilled signal and source reference, never full transcripts. Candidate is a promotion wrapper, not a fifth capability kind. Promotion is explicit and authority-gated; scope broadening additionally requires transfer evidence/eval. Structural CI never claims semantic quality.

Bootstrap seed capability versions are authorized through a bootstrap baseline/promotion ledger. After the cutoff, new canonical capability versions require normal promotion governance.

## Runtime projection

ChatGPT and Codex consume the same semantic capability identities and versions. Runtime packages may differ in packaging, but every projected Skill must preserve source capability ID/version/hash plus an independent projection version. Generated `SKILL.md` is never canonical.

## MVP boundaries

No database, queue, server, remote registry, package manager, graph database, vector database, embedding search, autonomous learning/promotion/reopen/closure, workflow engine, model-dependent basic resolver, Custom GPT automatic rewrite, or mass project migration.

## Verification

Acceptance requires executable tests for schemas, identity/version/reference integrity, registry/catalog derivation, CLOSED/disabled/invalid/superseded resolver behavior, exact lock, projection traceability/freshness, Experience->Candidate->Eval->Promotion E2E, broadening, supersession, feedback->Experience, and deterministic generated rebuild.
