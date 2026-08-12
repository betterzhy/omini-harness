# Existing Continuous Learning → Unified Evolution Workspace Migration Map

The richer previous Continuous Learning checkout is not mounted in this execution environment. This repository therefore preserves the documented engineering compatibility surface and demonstrates the merge architecture. When applied to the real Brownfield checkout, **keep richer working engineering code and redirect shared mechanics to `evolution_harness`; do not replace working behavior with this compatibility facade.**

| Existing concern | Action | Unified target | Boundary |
|---|---|---|---|
| Python repository tooling | KEEP + ADAPT | `harness`, `eng`, `src/` | Preserve richer existing CLI commands when present. |
| Engineering manifest | KEEP | `engineering/manifest.yaml` | Remains engineering-domain entry point. |
| Stable identity / SemVer | EXTRACT / REUSE | `src/evolution_harness/identity.py` | Shared mechanics only. |
| Schema loading / hashing | EXTRACT / REUSE | `schema.py`, `hashing.py` | Domain-specific payload schemas stay separate. |
| Lifecycle / validity / provenance | EXTRACT / REUSE | common capability metadata + validators | No duplicate design-only lifecycle stack. |
| Brownfield registrations | KEEP | `engineering/registrations/` | Canonical artifacts remain in place. |
| Engineering registry/catalog | KEEP DOMAIN + ADAPT | `engineering/generated/` | Unified catalog is projection, not authority. |
| Engineering Experience/Candidate | KEEP IN REAL MERGE | `engineering/continuous-learning/` | Exact richer source must be retained when available. |
| Design capability model | ADD | `design/capabilities/` | Four kinds only: Principle/Framework/Skill/Workflow. |
| Design learning loop | ADD | `design/learning/`, `design/evals/` | Experience ≠ transcript; Candidate ≠ capability. |
| Project control plane | ADD | `.agent-evolution/` | References truth; does not copy architecture bodies. |
| Deterministic design resolver | ADD | `resolver.py` | No embeddings/LLM dependency. |
| Runtime projection | ADD | `runtime/`, `projection.py` | Generated packaging cannot become canonical. |
| ChatGPT/Codex integration | ADD | generated runtime packs | Same semantic capability identity/version/hash. |
| Handoff / feedback | ADD | `handoff.py`, `feedback.py` | Feedback enters learning via triage only. |

## Explicit non-migrations

No canonical architecture, OpenAPI, policy, validator, test, or skill body is moved merely to fit a new directory. No historic conversation bulk import, vector store, graph database, remote registry, package manager, workflow engine, automatic promotion, automatic reopen, or Custom GPT rewrite is introduced.
