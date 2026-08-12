# PAY-NEXUS AGENT EVOLUTION HARNESS SHADOW PILOT REPORT

## Conclusion

The read-only Shadow pilot is `PASS`. This is not a claim that repo-local binding has been installed into Pay-Nexus. The source repository remained unchanged, no Pay-Nexus task was executed, and no development, repeat Landing, Wave 0, DDL, database write, production operation, or push authority was inferred.

```text
PAY_NEXUS_SHADOW_AUTHORITY_BINDING = PASS
PAY_NEXUS_SHADOW_EXACT_CAPABILITY_LOCK = PASS
PAY_NEXUS_SHADOW_RESOLVER_INTEGRATION = PASS
PAY_NEXUS_SHADOW_CODEX_PROJECTION = PASS
PAY_NEXUS_SHADOW_CLOSED_TOPIC_PROTECTION = PASS
PAY_NEXUS_SHADOW_PROJECT_AUTHORITY_PRESERVATION = PASS
PAY_NEXUS_SHADOW_INSTALL_PLAN = PASS_DRY_RUN_ONLY
PAY_NEXUS_EXISTING_ENGINEERING_COMPATIBILITY = PASS_ZERO_WRITE_BOUNDARY
PAY_NEXUS_PROJECT_LOCAL_BINDING = NOT_EXECUTED_REQUIRES_SEPARATE_AUTHORITY
PAY_NEXUS_PROJECT_LOCAL_MATERIALIZATION = NOT_EXECUTED_REQUIRES_SEPARATE_AUTHORITY_AND_MECHANISM
PAY_NEXUS_PROJECT_LOCAL_FEEDBACK_ENTRY = NOT_EXECUTED_NO_REAL_PILOT_TASK
PAY_NEXUS_REAL_CODEX_TASK = NOT_EXECUTED
```

## Repository Inventory

| Area | Current evidence | Shadow interpretation |
|---|---|---|
| Repository | `/Users/yuzhuangzhuang/Projects/pay-nexus` at `6db5e1efe548abe3a7862c231aba3b2e62b89eab` | Read-only source root; revalidated after the original pilot |
| Global authority | `current-formal-status.md` | Owns global stage and execution permissions |
| Agent guidance | `AGENTS.md` | Project guidance remains unchanged and outranks generic guidance |
| Design state | `ArchitectureSemanticStatus=SEALED` | Registered as CLOSED only because explicit evidence exists |
| Engineering state | `DEV_S01_STAGE5_LOCAL_REPOSITORY_LANDING_COMPLETED` | Historical Stage 5 Landing is complete; its authority is consumed |
| Stable control-plane registration | `development-control-plane-progress.md` | Owns ER-05 registration only, not current execution authority |
| Stable admission assessment | `development-entry-admission-progress.md` | Assessment receipt only; cannot authorize execution |
| Active Slice authority | `dev-s01-cpc-query-reference-slice-progress.md` | Owns DEV-S01 dynamic Gate and consumption facts |
| Machine projection | `machine/active-development-projection-1.0.0.yaml` | Registered as `DERIVED`, owns no facts |
| Existing repo-local Skill | `.agents/skills/pay-nexus-implementation-quality-gate/` | Project-owned; not overwritten or reclassified |
| Existing engineering governance | Contracts, schemas, registries, traceability, validators, CI and test evidence remain in Pay-Nexus | Harness does not replace them |

Product-gap and financial-domain progress authorities were not loaded because this pilot asks only about the current execution/closure boundary. `temp-input/**` is the first excluded pattern and was not used as an authority, input, hash source, install source, or write target.

## Harness Location and Write Boundary

- Harness: `/Users/yuzhuangzhuang/Projects/omini-harness`
- Pay-Nexus: `/Users/yuzhuangzhuang/Projects/pay-nexus`
- All control-plane, scenario, lock and projection files are under the Harness repository.
- Pay-Nexus files added: none.
- Pay-Nexus files modified: none.
- `AGENTS.md` changes: none.
- Repo-local generated Skill installation: not executed.

## Files Added in the Harness

```text
integrations/pay-nexus-shadow/
├── integration.yaml
├── authority-map.yaml
├── control-plane/.agent-evolution/
│   ├── design-state.yaml
│   ├── capabilities.yaml
│   └── capabilities.lock.yaml
├── scenarios/
│   ├── closed-architecture-protection.yaml
│   ├── consumed-stage-does-not-authorize-wave0.yaml
│   ├── current-authority-denies-execution.yaml
│   ├── review-go-does-not-authorize.yaml
│   └── stage4-stop-replay.yaml
└── PILOT_INTEGRATION_REPORT.md

generated/projections/codex/pay-nexus-shadow/
├── repository-guidance.md
├── resolved-task-context.md
├── resolved-context.json
├── discussion-contract.md
├── skills/architecture-review/SKILL.md
└── projection-manifest.json
```

## Project Design State

The sidecar uses `currentStage=CALIBRATION`. This describes the Shadow integration, not the Pay-Nexus delivery stage. The real project stage is extracted separately as `DEV_S01_STAGE5_LOCAL_REPOSITORY_LANDING_COMPLETED` from its canonical source.

Only two real topics are registered CLOSED:

- `payment-platform-v1.13-architecture`, backed by `ArchitectureSemanticStatus=SEALED`.
- `dev-s01-local-landing`, backed by the current Slice progress and consumed Stage 5 receipt.

`harness-shadow-binding` remains `IN_PROGRESS`; it cannot change either project topic.

## Authority Snapshot

Command:

```bash
PYTHONPATH=src .venv/bin/python -m evolution_harness.cli --repository-root . \
  integration inspect \
  --integration integrations/pay-nexus-shadow \
  --source /Users/yuzhuangzhuang/Projects/pay-nexus --format json
```

Evidence:

```text
source HEAD = 6db5e1efe548abe3a7862c231aba3b2e62b89eab
source tree = 831a91f865b674f244d2aa657aab0a4c2811cbb8
authority set status = CLEAN_FOR_AUTHORITY_SET
authority set digest = sha256:f5eeb28b701cb16301064060ae93ecb8f39c88d34c51e7d5c07efea4b9f351c2
snapshot = sha256:7edd374fdf7cfeadf106ac78fb8f8dcc74ea01de6c34907c235229903a985f52
authority gate = PASS
conflicts = []
missing facts = []
```

Important normalized facts:

```text
permission.development = DENY
permission.repository-landing = DENY
permission.ddl = DENY
permission.database-write = DENY
permission.wave0 = DENY
permission.git-push = DENY
permission.stage4-closure-projection = CONSUMED
permission.landing-preflight = CONSUMED
permission.local-landing = CONSUMED
slice.dev-s01.stage1-authorization = CONSUMED
slice.dev-s01.stage3-authorization = CONSUMED
slice.dev-s01.stage4-authorization = CONSUMED
slice.dev-s01.stage5-authorization = CONSUMED
```

## Capability Binding and Exact Lock

The minimum explicit binding contains five capabilities and no profile, extension or disabled capability:

- `principle:agent-design:project-truth-over-generic-guidance@1.0.0`
- `principle:agent-design:closure-requires-authority@1.0.0`
- `framework:agent-design:authority-analysis@1.0.0`
- `framework:agent-design:lifecycle-analysis@1.0.0`
- `skill:agent-design:architecture-review@1.0.0`

Command:

```bash
PYTHONPATH=src .venv/bin/python -m evolution_harness.cli --repository-root . \
  integration lock --integration integrations/pay-nexus-shadow --check --format json
```

Result:

```text
lock gate = PASS
lock fingerprint = sha256:1b5b5116bbd7b98be65f207b0f849cca0cf16cd541e80bb3f6a93f405d4f6bdb
```

Each lock entry records capability ID, exact version, content hash and Harness revision. No latest-version lookup occurs after lock verification.

## Resolver Explain Trace

For `intent=architecture-review`, `topic=harness-shadow-binding`, `runtime=CODEX`:

- Selected: `authority-analysis`, `lifecycle-analysis`, `project-truth-over-generic-guidance`, `architecture-review`.
- Excluded: `closure-requires-authority` because of `intent-mismatch`.
- Project conflict: `architecture-review` vs `current-formal-status.md#current-execution-authority`.
- Resolution: `PROJECT_TRUTH_WINS`.
- Resolution ID: `resolution:28a772208660adb5bf5b52c1`.

This demonstrates selection before materialization; the lock contains five capabilities, but the runtime context selects only four.

## Scenario Verification

Each scenario was executed through `integration scenario` against the live read-only source:

| Scenario | Result | Decisive evidence |
|---|---|---|
| `closed-architecture-protection` | PASS | `DO_NOT_REOPEN`, zero selected capabilities |
| `consumed-stage-does-not-authorize-wave0` | PASS | all prior stage permissions `CONSUMED`; Wave 0 `DENY` |
| `current-authority-denies-execution` | PASS | Development, Landing, DDL, DB, Wave 0 and Push all `DENY` |
| `review-go-does-not-authorize` | PASS | Stage 4 review `GO_P0_0_P1_0_P2_0_ULTRA_GATEKEEPER`; current Development and Landing still `DENY` |
| `stage4-stop-replay` | PASS | Stage 4/preflight consumed; future write envelope closed; separate authorization still required |

## Authority Drift Verification

A temporary source containing only the six allowlisted authority/guidance files was committed, projected and checked fresh. A poisoned temporary change from `Wave0ExecutionAllowed=NO` to `YES_POISONED_DRIFT` then produced:

```text
fresh = false
reasons = [authority-snapshot-drift]
exit = 1
```

The temporary fixture was removed. The real Pay-Nexus source was never modified.

## Codex Projection and Skill Traceability

Commands:

```bash
PYTHONPATH=src .venv/bin/python -m evolution_harness.cli --repository-root . \
  integration projection --integration integrations/pay-nexus-shadow \
  --source /Users/yuzhuangzhuang/Projects/pay-nexus \
  --intent architecture-review --topic harness-shadow-binding \
  --output 'read-only authority review' --runtime CODEX --format json

# Same command with --check
```

Result:

```text
projection freshness = PASS
projection version = codex-project-pack/1
source resolution = resolution:28a772208660adb5bf5b52c1
source lock = sha256:1b5b5116bbd7b98be65f207b0f849cca0cf16cd541e80bb3f6a93f405d4f6bdb
source authority snapshot = sha256:7edd374fdf7cfeadf106ac78fb8f8dcc74ea01de6c34907c235229903a985f52
```

Generated `architecture-review/SKILL.md` records:

```text
sourceCapabilityId = skill:agent-design:architecture-review
sourceCapabilityVersion = 1.0.0
sourceContentHash = 00094ad3677d968fa101879886d2dc0e14bac5926930ddcfad897c9f8879c834
projectionVersion = agent-skill-projection/1
```

The generated Skill is a runtime artifact, not project or capability authority.

## Install Plan and Collision Boundary

Command:

```bash
PYTHONPATH=src .venv/bin/python -m evolution_harness.cli --repository-root . \
  projection install --pack generated/projections/codex/pay-nexus-shadow \
  --target /Users/yuzhuangzhuang/Projects/pay-nexus --format json
```

Result:

```text
mode = DRY_RUN
gate = PASS
planned create = .agents/skills/architecture-review/SKILL.md
collisions = []
```

The existing project-owned `pay-nexus-implementation-quality-gate` has a distinct identity and path. No install was applied. Generic installer tests separately prove that a same-path unmanaged Skill collision is `NO_GO` and never overwritten.

Automatic materialization and removal are deliberately disabled. On a disposable empty target, both `projection install --apply` and `projection uninstall --apply` exited `1` before target content access and left the target empty. The dry-run plan is therefore evidence for a proposed write set, not permission or a mechanism to apply it.

## Baseline and Post-Integration Verification

Pay-Nexus source checks for the original pilot and the later registration-candidate revalidation:

```text
HEAD before = f0bfce7a71314c313a01a518fa3a36f8e9bf659a
HEAD after  = f0bfce7a71314c313a01a518fa3a36f8e9bf659a
latest revalidation HEAD before = 6db5e1efe548abe3a7862c231aba3b2e62b89eab
latest revalidation HEAD after  = 6db5e1efe548abe3a7862c231aba3b2e62b89eab
latest authority set status before = CLEAN_FOR_AUTHORITY_SET
latest authority set status after  = CLEAN_FOR_AUTHORITY_SET
unrelated tracked modifications observed = 2 (outside the six-file authority allowlist; preserved)
.agent-evolution in Pay-Nexus = absent
.agents/skills/architecture-review in Pay-Nexus = absent
PAY_NEXUS_SHADOW_ZERO_WRITE = PASS
```

Pay-Nexus tests were intentionally not run because they may materialize build outputs in the source repository and the approved Shadow boundary is zero-write. No regression claim beyond byte-preservation is made. Harness tests, structural validation, lock freshness, scenario checks and projection freshness are the executable integration evidence.

Harness candidate-freeze verification:

```text
pytest = 162 passed
structural validation = PASS (issues = [])
registry freshness = PASS (design 10, design-learning 5, engineering 6)
catalog freshness = PASS (design 10, engineering 4, unified 14)
neutral exact lock = PASS
pay-nexus-shadow exact lock = PASS
neutral scenarios = 2/2 PASS
pay-nexus-shadow scenarios = 5/5 PASS
pay-nexus-shadow projection freshness = PASS
pay-nexus-shadow install plan = PASS / DRY_RUN
```

The first fixed candidate, `7d6882bc666ff521e163d9b0bb2e0689b26e2186`, was independently reviewed and rejected as `NO-GO` (`1 P0`, `6 P1`, `2 P2`). A second candidate, `e8903b7b541bdca75846841f1d33d472d1a83d8f`, passed its mechanical Gate but was rejected before acceptance because a negative test proved it did not independently reproduce and verify the saved resolver result. A third candidate, `9706122b7d41bae84ee64092a318b5c8be3d8a27`, was rejected because freshness still consulted untrusted generated-file paths after canonical validation had already failed. A fourth candidate, `61280ab7f50aa06b17a0916dc849d2e5e7b907d2`, closed that path but was rejected when independent review proved embedded authority facts were not compared with the complete live snapshot. A fifth candidate, `4af3112fb61464a038f418c9ef35e6a46b3d0022`, closed the authority gap but was rejected because `sourceHarnessRevision` could be synchronously forged and because concurrent writers were not serialized. A sixth candidate, `eecba56e65ff51311a087227cb93afe8c4d0753b`, closed those findings but was rejected because build and install used different pack-lock domains, automatic recovery accepted an unattested target-owned journal, and path checks were not anchored across the later write. A seventh candidate, `f60161f2aa1d517710b8e8fdefb56ccc0f5b18b3`, closed those three findings but was rejected because PREPARED recovery could delete a project-owned file created after the failed transaction began. An eighth candidate, `bb3975f5d8c0bbed7c1d0935eb2730294ed713cd`, added before/after-image checks but was rejected because comparison and destructive rollback still had a race window. A ninth candidate, `8752ad5c106da18ea14eaea6c5c6248cc310495a`, made recovery non-destructive but was rejected because ordinary APPLY still used compare-then-overwrite/delete semantics. A tenth candidate, `37b1ab63b7b5a54ee0d1c5913b154496ca4e37a4`, restricted writes to no-replace CREATE but was rejected because a multi-skill race could still produce a false successful manifest. All ten are superseded and none is acceptance evidence. The accepted model retains safe project identities and output boundaries, request-bound freshness, current-resolver reproduction, deterministic projection reconstruction, complete live authority snapshot equality, canonical topic-status reconciliation, reproducible exact-source lock revisions, one-byte authority snapshots, and shared pack/target planner locks. Project installation and removal are now plan-only: `--apply` is disabled, legacy recovery state blocks planning without mutation, and materialization requires a separate project-authorized mechanism.

## Fixed Candidate Acceptance Receipt

```text
Candidate = a50e9240c96a6acff6d63fb9d61e3390d143a27f
Parent    = 37b1ab63b7b5a54ee0d1c5913b154496ca4e37a4
Tree      = f8c94f1f144ee9e81d9547e4acd26b3fb73c8d5e
Deep review  = GO (P0=0, P1=0, P2=0)
Ultra gate   = GO (P0=0, P1=0, P2=0)
```

Both reviews used new clean detached clones and independently matched the Candidate, Parent and Tree. Their executable evidence included:

- `pytest -q`: 141 passed.
- Structural validation: PASS, `issues=[]`; `semanticGate=NOT_ASSERTED_BY_CI` remains an explicit limitation.
- Registry, catalog and engineering doctor freshness: PASS.
- Project fixture exact lock and CHATGPT/CODEX projection freshness: PASS.
- Neutral integration exact lock, 2/2 scenarios, projection freshness and dry-run install plan: PASS.
- Pay-Nexus read-only Shadow exact lock, 5/5 scenarios, projection freshness and dry-run install plan: PASS.
- Install/uninstall apply probes: disabled before project content access, zero target callbacks and unchanged bytes.
- Legacy journal/attestation probes: manual-recovery fail closed with project and journal bytes preserved.
- Projection-pack anchored swap, recovery and shared pack-lock regression coverage: PASS.

This receipt accepts the generic Brownfield adapter and the Pay-Nexus read-only Shadow pilot. It does not accept or authorize Pay-Nexus project-local registration, Skill materialization, a real Pay-Nexus task, project tests, database work, Landing, Wave 0 or push.

## Deferred Items and Hard Stop

The following require a separate user decision and were not executed:

- Add `.agent-evolution/` to Pay-Nexus.
- Add an Agent Evolution Harness discovery section to Pay-Nexus `AGENTS.md`.
- Install generated repo-local Skills.
- Create a project-local design handoff or feedback entry.
- Execute a real Pay-Nexus Codex task.
- Run project-local build/tests that write outputs.
- Execute Development, repeat Landing, Wave 0, DDL, database writes, production operations or push.

## Recommended First Real Pilot Task

If project-local installation is later authorized, use a read-only review of the current execution-authority routing and Stage 5 consumed-authorization boundary. Do not select a business implementation, schema migration, Landing or Wave 0 task.
