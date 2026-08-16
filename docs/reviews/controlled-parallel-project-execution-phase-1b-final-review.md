# Controlled Parallel Project Execution Phase 1B Final Review

## Decision

`GO / P0=0 / P1=0 / P2=0`

This receipt accepts only the Phase 1B fixed implementation candidate. It does
not authorize Phase 1C, project work launch, Pay-Nexus adoption or writes,
database work, Landing, Wave entry, push, release, or deployment.

## Fixed Candidate

- Candidate: `93354c15db112e6d62cb7bffbc219278bd1b1be5`
- Parent: `e9b3ddfd6f12a0ed54897f964d2ffcd04906d6c9`
- Tree: `b9ddc7d1000ddc5e66c614f6f9d38f935f4c3714`
- Reviewed Phase 1A base: `ee1a29bd98e798598051d2ef3e56fd1c7fcb198d`
- Review date: `2026-08-16`
- Review route: independent `deep_reviewer`, `gpt-5.6-sol / xhigh`
- Worktree state after review: clean

## Exact Phase 1B WriteSet

The exact `ee1a29b..93354c1` WriteSet contains these 39 paths:

```text
README.md
core/schemas/controlled-coordinator-acquire-command.schema.json
core/schemas/controlled-coordinator-journal.schema.json
core/schemas/controlled-coordinator-projection.schema.json
core/schemas/controlled-coordinator-receipt.schema.json
core/schemas/controlled-coordinator-snapshot.schema.json
core/schemas/controlled-coordinator-transition-command.schema.json
core/schemas/controlled-execution-lease.schema.json
core/schemas/controlled-execution-plan.schema.json
core/schemas/controlled-recovery-command.schema.json
core/schemas/controlled-write-observation-command.schema.json
docs/superpowers/plans/2026-08-14-controlled-parallel-project-execution-phase-1b.md
examples/external-project-source/controlled-planning.yaml
examples/external-project-source/coordinator-issuer.yaml
examples/external-project-source/deep-reviewer-public.pem
examples/external-project-source/lifecycle-authority-public.pem
examples/external-project-source/recovery-authority-public.pem
integrations/neutral-shadow/authority-map.yaml
src/evolution_harness/authority.py
src/evolution_harness/cli.py
src/evolution_harness/controlled_coordinator.py
src/evolution_harness/controlled_coordinator_inputs.py
src/evolution_harness/controlled_inputs.py
src/evolution_harness/controlled_planner.py
src/evolution_harness/controlled_recovery.py
src/evolution_harness/controlled_write_guard.py
src/evolution_harness/coordinator_state.py
tests/conftest.py
tests/fixtures/guarded_writer.py
tests/test_authority_engine.py
tests/test_controlled_coordinator_acquire.py
tests/test_controlled_coordinator_cli.py
tests/test_controlled_coordinator_inputs.py
tests/test_controlled_coordinator_lifecycle.py
tests/test_controlled_inputs.py
tests/test_controlled_planner.py
tests/test_controlled_recovery.py
tests/test_controlled_write_guard.py
tests/test_coordinator_state.py
```

The final Round 5 remediation itself changed only the formal plan and the two
review-owned test files. No production path changed after the Round 4
implementation candidate.

## Verification Evidence

The following checks ran against the fixed candidate and exited `0`:

```text
.venv/bin/python -m evolution_harness.cli --repository-root . validate --check-generated --format json
  structuralGate=PASS; issues=[]
.venv/bin/python -m evolution_harness.cli --repository-root . registry build --check --format json
  ok=true
.venv/bin/python -m evolution_harness.cli --repository-root . catalog build --check --format json
  ok=true
PATH="$PWD/.venv/bin:/usr/bin:/bin" ./eng doctor --ci --json
  engineeringDomain=PASS; issues=[]
git diff --check
  PASS
.venv/bin/python -m compileall -q src tests
  PASS
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q \
  tests/test_controlled_coordinator_acquire.py tests/test_controlled_recovery.py
  100 passed in 125.85s
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q
  658 passed in 286.08s
```

The independent reviewer reran the two focused modules (`100 passed in
126.48s`) and the full suite (`658 passed in 286.90s`) and rechecked the exact
Candidate, Parent, Tree, WriteSet, clean worktree, structural checks, and
`git diff --check`.

## Security, Concurrency, and Recovery Findings

- Authority Snapshot Git evidence uses a descriptor-bound source root,
  descriptor/ref/object reads, explicit commit-tree parsing, local blob OID
  recomputation, sealed Git environment, disabled replace objects, and no
  caller `PATH`, Git environment, alternate-object, or ambient `hash-object`
  authority.
- Acquire and Transition hostile ambient-Git/replace negatives fail closed.
  The final Acquire negative constructs the clean command before contamination,
  observes the real live rebuild exactly once, requires
  `LIVE_AUTHORITY_SNAPSHOT_MISMATCH`, proves fake Git was not invoked, and
  proves no journal, lease, or receipt was created.
- Descriptor-bound candidate and inventory reads reject administration-root,
  ref, object, index, inode, symlink, and path-swap drift. Linked-worktree
  guarded execution remains an explicit pre-launch
  `LANE_INVENTORY_UNAVAILABLE` result.
- Complete physical inventory includes nonignored empty leaf directories.
  Exact WriteSet ancestors remain usable, while absent ephemeral evidence is
  not widened. The public observation negative rejects an incomplete set and
  then proves the complete directory set is persisted in project quarantine,
  recovery evidence, and the `WRITE_OBSERVATION` receipt.
- The suite covers competing-process project locks, cross-plan/cross-batch
  conflicts, monotonic fencing, crash/replay, terminal replay, WriteSet breach
  quarantine, project-wide token revocation, signed recovery, and retired
  plan/attempt identities.
- Protected database, migration, destructive, production/secret, Landing,
  Wave, push, release, and deployment actions remain denied.

## Registered-Project No-Write Boundary

- The fixed candidate diff contains only Harness-owned source, schemas, tests,
  documentation, neutral integration fixtures, and example authority material.
- No Pay-Nexus path appears in the Phase 1B WriteSet, and no Pay-Nexus command
  or project write was executed in the Round 4/5 remediation or final review.
- Coordinator mutation tests use per-test synthetic source/lane/state roots and
  assert project-file preservation at the CLI and guarded-command boundaries.
- Phase 1B records safety leases only. It does not create project worktrees,
  launch project agents, change project lifecycle authority, integrate Git
  candidates, or update project refs.

## Residual Platform Limits

- Real process-tree write isolation depends on the verified macOS
  `/usr/bin/sandbox-exec` boundary. Unsupported hosts fail closed before target
  execution.
- Linked-worktree guarded mutation is not claimed as supported; descriptor-bound
  inventory currently fails closed before target launch.
- A Phase 1B `GO` is not implementation or execution authority for a registered
  project and does not release any later roadmap arrow.

## Closure

Phase 1B is accepted at the fixed implementation candidate above. The separate
review-receipt commit may advance branch `HEAD`, but it does not change the
reviewed Candidate or Tree. Work stops at the Phase 1C planning boundary.
