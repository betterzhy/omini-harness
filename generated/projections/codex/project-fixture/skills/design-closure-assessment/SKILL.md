---
name: design-closure-assessment
description: Assess whether a topic has enough accepted authority/evidence to be eligible for closure.
---

<!-- agent-evolution-source
sourceCapabilityId: skill:agent-design:design-closure-assessment
sourceCapabilityVersion: 1.0.0
sourceContentHash: ca40a8b7b3e0e350f13f8fc0f5bf92feed371cfc9cf8314c7f5508e857980637
projectionVersion: agent-skill-projection/1
-->

# Design Closure Assessment

## Procedure

1. Resolve the explicit project state and authoritative references before applying reusable guidance.
2. Apply only the selected referenced capabilities relevant to the current intent/stage.
3. Surface conflicts, gaps, and human authority gates explicitly.
4. Produce the declared output contract without mutating canonical project state.

## Guardrails

Generated runtime packaging is not canonical. CLOSED topics stay closed unless an explicit reopen signal and human authority are present.

## Referenced Canonical Guidance

### principle:agent-design:closure-requires-authority@1.0.0

# Closure Requires Authority

## Rationale

Topic closure is an explicit authority-governed state.

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
