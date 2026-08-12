---
name: architecture-review
description: Review architecture using explicit authority, lifecycle, scope, and project constraints.
---

<!-- agent-evolution-source
sourceCapabilityId: skill:agent-design:architecture-review
sourceCapabilityVersion: 1.0.0
sourceContentHash: 00094ad3677d968fa101879886d2dc0e14bac5926930ddcfad897c9f8879c834
projectionVersion: agent-skill-projection/1
-->

# Architecture Review

## Procedure

1. Resolve the explicit project state and authoritative references before applying reusable guidance.
2. Apply only the selected referenced capabilities relevant to the current intent/stage.
3. Surface conflicts, gaps, and human authority gates explicitly.
4. Produce the declared output contract without mutating canonical project state.

## Guardrails

Generated runtime packaging is not canonical. CLOSED topics stay closed unless an explicit reopen signal and human authority are present.

## Referenced Canonical Guidance

### principle:agent-design:project-truth-over-generic-guidance@1.0.0

# Project Truth Over Generic Guidance

## Rationale

Project-specific canonical truth outranks generic shared guidance.

The runtime may package or summarize this principle, but the generated representation is disposable and must trace back to this canonical identity/version.

### framework:agent-design:authority-analysis@1.0.0

# Authority Analysis

## Questions

Use these dimensions to challenge ambiguity rather than to force a fixed checklist answer. Identify authoritative facts, lifecycle boundaries, missing evidence, and decisions that require human authority.

## Failure modes

Do not infer project authority from generic practice. Do not treat absence of detail as permission to invent a rule.

### framework:agent-design:lifecycle-analysis@1.0.0

# Lifecycle Analysis

## Questions

Use these dimensions to challenge ambiguity rather than to force a fixed checklist answer. Identify authoritative facts, lifecycle boundaries, missing evidence, and decisions that require human authority.

## Failure modes

Do not infer project authority from generic practice. Do not treat absence of detail as permission to invent a rule.
