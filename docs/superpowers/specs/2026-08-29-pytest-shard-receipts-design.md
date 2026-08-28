# Harness Pytest Cost Lanes and Shard Receipts Design

## Status and dependency

This specification is the second, separately reviewable candidate in the approved
External Pack performance repair. It depends on the operation-scoped verification
session defined by
`2026-08-29-external-pack-validation-lifecycle-scaling-design.md`.

It changes test topology and operational receipt semantics, not Pack identity,
candidate-Gate trust, project Authority, or projection behavior. It must not begin
until the validation-session candidate has stable focused tests. The two candidates
may be benchmarked together, but they retain separate WriteSets and review evidence.

## Problem statement

The Pay-Nexus Java pilot currently executes six scenarios in one pytest test body and
then performs install validation in the same node. Pytest exposes no independent
progress for those scenarios. When the node is interrupted, the receipt proves that
644 prior nodes passed but cannot prove which scenario/install substeps completed.

The repository also has no registered cost markers, shard manifest, per-node flushed
progress log, or outer receipt that binds the run to HEAD/tree, selected node IDs,
stdout/stderr, and exit status. `--last-failed` and `--stepwise` are developer
conveniences, not a complete Gate receipt.

## Goals

The implementation must:

1. provide explicit `fast`, `integration`, and `pack_e2e` cost lanes;
2. give every Pay-Nexus scenario and the install plan its own stable pytest node ID;
3. run the real Java Pack E2E lane serially with one shared
   `CapabilityVerificationSession` per shard/process;
4. collect the exact ordered node-ID set before execution and bind it into the shard
   receipt;
5. flush node phase/results as tests execute so completed progress survives SIGINT or
   process failure;
6. preserve stdout, stderr, exit code/signal, timing, candidate identity, and summary
   counts for every completed or interrupted shard;
7. continue later shards after an ordinary test failure while keeping each shard's
   independent exit status;
8. aggregate a PASS only from complete, disjoint coverage of the expected node set
   with every shard PASS;
9. keep receipts outside every Git worktree and prevent them from becoming Pack Gate
   trust or project Authority;
10. add no plugin dependency unless built-in pytest hooks prove insufficient.

## Non-goals

This candidate will not:

- make an interrupted shard or partial node list a full Gate PASS;
- resume inside a partially executed test function;
- make pytest session fixtures execute once across xdist workers;
- share a verification session across processes;
- automatically parallelize the Java/Maven Pack E2E lane;
- reuse coordinator receipts for pytest or Pack validation;
- store receipt bodies in Harness, external Pack, or project Git history;
- change Pack, lock, projection, Authority, install, or execution semantics;
- skip the real candidate Gate for a fixed-candidate acceptance run.

## Considered approaches

### A. Deterministic in-repository runner plus a minimal pytest hook plugin — selected

Harness owns a small test runner and plugin. The runner fixes a node manifest,
executes explicit shards, streams stdout/stderr, and writes an outer receipt. The
plugin records collection and `setup`/`call`/`teardown` reports as line-delimited JSON,
flushing each record. This works when `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` because the
runner loads the plugin explicitly.

It avoids a new dependency and allows Harness to bind the receipt to repository and
Pack verification counters without treating a third-party report format as
Authority.

### B. pytest-xdist as the first fix — rejected for this candidate

Each xdist worker is a separate process, so a session-scoped fixture executes once per
worker rather than once for the complete run. Splitting the Java Pack nodes would
repeat the expensive Gate and contend for the same toolchain/cache. xdist can be
reconsidered only after measured shard costs and explicit grouping/resource limits.
See [pytest-xdist distribution](https://pytest-xdist.readthedocs.io/en/stable/distribution.html)
and [session fixture limitations across workers](https://pytest-xdist.readthedocs.io/en/stable/how-to.html#making-session-scoped-fixtures-execute-only-once).

### C. JUnit XML or `pytest-reportlog` alone — rejected as the outer receipt

JUnit remains useful for CI presentation but may be absent or incomplete after hard
interruption and does not bind the run's Git/candidate/shard identity. `pytest-reportlog`
has suitable streaming properties, but adding it is unnecessary when a minimal local
hook can emit only the fields Harness needs. See
[pytest JUnit XML](https://docs.pytest.org/en/stable/how-to/output.html#creating-junitxml-format-files)
and [pytest-reportlog](https://github.com/pytest-dev/pytest-reportlog).

## Cost-lane contract

`pyproject.toml` registers these strict markers:

- `fast`: deterministic tests with no live external candidate Gate;
- `integration`: cross-module, Git, projection, or integration semantics;
- `pack_e2e`: an integration test that executes or consumes the real External Pack
  candidate Gate/toolchain.

Every `pack_e2e` test also carries `integration`. `fast` is mutually exclusive with
both `integration` and `pack_e2e`. The initial change marks only the External
Pack/Pay pilot surface needed by this repair. It does not require a speculative
all-repository reclassification.

Canonical selections are explicit:

```text
fast feedback                 -m fast
normal integration            -m "integration and not pack_e2e"
real Pack acceptance          -m pack_e2e    (serial, one process)
complete regression           no marker exclusion
```

`--strict-markers` is enabled so a typo cannot silently create an unselected lane.
The repository's complete acceptance command remains complete; no global `addopts`
silently excludes `pack_e2e`.

## Pay-Nexus pilot decomposition

The current combined test is split into:

1. six parameterized scenario nodes, with IDs derived from the stable scenario file
   stem;
2. one install-plan/read-only node;
3. existing lock, Authority/progress, and projected-resource tests kept separate.

A module-scoped fixture opens one explicit `CapabilityVerificationSession` and passes
it to every scenario and install public operation. The module is always executed in
one process in the `pack_e2e` lane. A selected subset remains valid: it gets one
session for the selected nodes and never inherits trust from another pytest process.

The scenario parameterization provides independently selectable node IDs; unlike a
loop or subtest, pytest can select, shard, retry, and report each node independently.
See [pytest parametrization](https://docs.pytest.org/en/stable/how-to/parametrize.html).

## Node manifest and shard model

The runner uses two explicit stages.

### Collection

Collection runs pytest with the exact requested paths/markers and an explicitly
loaded local plugin. It writes a canonical node manifest containing:

- schema version;
- repository HEAD, tree, branch, and tracked/untracked status digest;
- Python, pytest, and explicitly loaded plugin versions;
- normalized collection command and marker expression;
- ordered unique node IDs;
- SHA-256 of canonical ordered node IDs;
- collection exit code and captured output digests.

Collection failure creates a non-PASS receipt and no executable shard manifests.

### Sharding and execution

Shard manifests are immutable inputs generated from one node manifest. Each contains
the same repository/node-manifest identity, a unique shard ID, total shard count, and
an explicit ordered node-ID subset.

The default Harness acceptance layout is deterministic rather than automatically
balanced:

- `fast` shards may be split by an explicitly fixed manifest;
- normal `integration` shards may be split after measured cost data exists;
- all `pack_e2e` nodes for one Pack/toolchain group remain in one serial shard.

The runner executes every listed shard even if an earlier shard exits because tests
failed. User interrupt/host termination stops launching new shards; already completed
receipts remain valid as partial evidence and later execution starts from explicit
not-run shard manifests.

Immediately before execution, the pytest plugin collects again and requires the exact
ordered node IDs to equal the shard manifest. Collection/run drift, duplicate nodes,
an empty declared selection, exit code 5, or any collection error is an infrastructure
failure and no executable PASS shard can be constructed.

## Streaming event log

The explicitly loaded pytest plugin emits one canonical JSON object per line and
flushes it after every event. At minimum it records:

- session/collection start;
- ordered collected node IDs and their digest;
- per-node `setup`, `call`, and `teardown` outcome and duration;
- failure/error representation in bounded form;
- final session exit status when pytest reaches normal teardown.

The event log is operational evidence, not the final receipt. The outer runner owns
process creation, signal observation, stdout/stderr streaming, and finalization. It
must not infer a node PASS until all required phases for that node have completed.

### Node terminal-state rules

The event reducer accepts one ordered `setup`, optional `call`, and one `teardown`
report per collected node. Duplicate, missing, or out-of-order terminal reports and
unknown outcomes make the shard `INFRA_ERROR`.

| Pytest reports | Terminal class |
|---|---|
| setup passed; call passed without `wasxfail`; teardown passed | `PASSED` |
| setup skipped; teardown passed | `SKIPPED` |
| setup failed; teardown passed | `ERROR` |
| setup passed; call failed without `wasxfail`; teardown passed | `FAILED` |
| setup passed; call skipped without `wasxfail`; teardown passed | `SKIPPED` |
| call skipped with `wasxfail`; teardown passed | `XFAILED` |
| call passed with `wasxfail`; teardown passed | `XPASSED` |
| teardown failed, regardless of earlier phase | `ERROR` |
| process ends before a terminal teardown report is flushed | `INCOMPLETE` |

`completedNodeIds` is exactly the disjoint union of nodes in `PASSED`, `FAILED`,
`ERROR`, `SKIPPED`, `XFAILED`, and `XPASSED`. `INCOMPLETE` nodes are reported
separately and remain part of `notRunOrIncompleteNodeIds`; they cannot support PASS.
Collection-time errors are shard infrastructure errors rather than synthetic node
results.

The run plan contains an explicit terminal-outcome policy. The default allows
`PASSED`, `SKIPPED`, and `XFAILED`, rejects `XPASSED`, and always rejects `FAILED`,
`ERROR`, and `INCOMPLETE`. A fixed-candidate Gate may choose a stricter policy, but a
receipt cannot weaken the policy fixed in its run plan.

## Shard receipt

Each shard writes an immutable `pytest-shard-receipt/v1` JSON record containing:

- unique run and shard IDs;
- node-manifest digest, shard index/count, and exact ordered expected node IDs;
- Candidate/Parent/Tree when the run is a fixed-candidate Gate;
- the immutable run-plan digest binding the complete expected node set, normalized
  invocation/config, terminal-outcome policy, and complete shard layout;
- Harness HEAD/tree/branch and worktree-status digest;
- exact command, marker selection, environment allowlist, Python/pytest/plugin
  versions, start/end timestamps, and duration;
- process exit code or terminating signal;
- `PASS`, `FAIL`, `INTERRUPTED`, `TIMEOUT`, or `INFRA_ERROR` status;
- a terminal-class map plus completed/passed/failed/error/skipped/xfailed/xpassed/
  incomplete/not-run node IDs and counts derived from that map;
- receipt-directory-relative stdout, stderr, event-log, and optional JUnit paths plus
  SHA-256, size, device, and inode witnesses;
- per-`PackVerificationKey` `VerificationStats` deltas from the Pack validation
  session when present;
- receipt self-digest over canonical JSON excluding the digest field.

Receipt status rules are fail closed:

- `PASS` requires exit code zero, complete exact node coverage, no failed/error/not-run
  node, matching collection/shard identity, and valid referenced file digests;
- any missing/truncated event log or mismatched node identity is `INFRA_ERROR` or
  `INTERRUPTED`, never PASS;
- an interrupted receipt remains useful evidence of completed nodes but grants no
  complete regression/fixed-candidate conclusion;
- aggregate PASS requires identical candidate/tree/node-manifest identities,
  identical Parent, HEAD/tree/status, normalized command/marker/config, environment
  allowlist, Python/pytest/plugin identities, outcome policy, and run-plan digest;
  exactly one valid PASS receipt must exist for every planned shard ID/index/count,
  and their disjoint node sets must union to the complete expected node set.

The `runPlanDigest` is canonical JSON over Candidate/Parent/Tree, repository
HEAD/tree/status digest, node-manifest digest and full ordered node set, normalized
command/markers/config root, environment allowlist digest, Python/pytest/plugin
identities, outcome policy, and every shard ID/index/count/ordered node subset. A
fixed-candidate Gate aggregates receipts from one run ID only; diagnostic recovery
runs may report combined coverage but cannot become the final Gate PASS.

The outer receipt is written atomically. Streaming event/stdout/stderr files may be
partial but are never rewritten after final receipt creation. A separate
`pytest-run-receipt/v1` records the run plan, every expected shard receipt digest,
aggregate status, stopped/not-launched shards, and the exact reason a run is not PASS.

## Receipt storage boundary

The runner requires an explicit receipt root. It rejects a root inside:

- the Harness repository or any Harness worktree;
- an External Pack source or worktree;
- a registered project source or integration target;
- a symlinked or non-owner-controlled directory.

Each run uses a unique directory created with owner-only permissions. The runner does
not delete existing receipts, overwrite a run ID, or claim append-only durability
beyond the local filesystem. CI may archive the directory as an artifact.

Every referenced artifact path is a normalized relative path anchored beneath that
run directory. Creation and verification use no-follow opens and require a regular,
owner-owned, non-group/world-writable, single-link file. Before final receipt rename,
the runner closes, flushes, and `fsync`s each artifact, records its device/inode/size,
reopens it no-follow, recomputes its digest, and verifies the same witness. It then
`fsync`s the run directory, atomically renames the receipt, and `fsync`s the directory
again. A path escape, symlink, hard link, replacement, digest/witness mismatch, or a
filesystem unable to provide these guarantees makes the run `INFRA_ERROR`.

This receipt proves test execution facts only. It does not become a Pack validation
cache, coordinator receipt, Authority snapshot, project authorization, merge/release
approval, or cross-process trust token.

## Failure and recovery behavior

- Ordinary pytest failures finalize a `FAIL` receipt and the runner continues with
  the next shard.
- The first SIGINT/SIGTERM observed by the parent is latched as the run's original
  interrupt, even if the child has exited but has not yet been reaped. No later shard
  starts. If a child exists, the parent sends the same signal to its process group,
  waits a bounded grace period, then sends SIGTERM and finally SIGKILL if needed, and
  always reaps it. A second signal shortens the grace period but does not replace the
  recorded original signal. The child exit and original parent-observed signal are
  recorded separately. The current run/shard is `INTERRUPTED` regardless of a later
  zero child exit.
- An interrupt during collection or before shard launch produces an interrupted run
  receipt with the unlaunched shard/node set and no fabricated shard PASS.
- If the parent is killed before finalization, a later inspection command derives a
  read-only incomplete-run report from the node manifest and flushed event log; it
  does not fabricate a final receipt.
- Resume selects only explicit not-run/failed node IDs from compatible receipts. It
  creates a new run/shard receipt and never mutates the original.
- A resumed partial run is not equivalent to one complete fixed-candidate Gate unless
  the aggregator verifies complete compatible coverage under the approved Gate
  policy. The conservative default for final candidate review is still a fresh
  complete run.

## Test strategy

RED → GREEN tests must cover:

- marker registration and strict typo rejection;
- the seven decomposed Pay pilot nodes have exactly the expected marker sets;
- `-m pack_e2e --collect-only` selects exactly those nodes and
  `integration and not pack_e2e` excludes them;
- six stable Pay scenario node IDs plus one separate install node;
- one shared serial Pack session and Gate/digest count ceilings;
- collection identity and duplicate/missing node rejection;
- ordinary PASS, assertion failure, setup error, teardown error, skip, timeout,
  xfail, xpass, duplicate/out-of-order report, collection drift, SIGINT, SIGTERM,
  signal-after-child-exit, second signal, truncated event log, and
  parent-finalization failure;
- continuation to later shards after an ordinary failed shard;
- no later shard launch after user interruption;
- aggregate rejection for overlap, gaps, different candidate/tree, different node
  manifest, changed command/environment, or non-PASS shard;
- receipt root symlink/worktree/project-path rejection;
- immutable prior receipt and new receipt on resume;
- interrupted output reports completed/not-run node IDs without claiming PASS;
- current full-regression command still collects the complete suite.

## Acceptance

The combined validation-session and test-lane candidates must demonstrate:

- the six scenarios and install plan are independently visible/selectable nodes;
- for the single Java `PackVerificationKey`, one serial `pack_e2e` shard records
  exactly one complete candidate Gate, one isolated checkout, and six directory
  digests. The wider ceiling of two/twelve remains a diagnostic threshold only; a
  second Gate for this one-key acceptance path is a performance failure unless a
  separately approved test deliberately introduces a second exact identity;
- an induced failed shard does not prevent a later independent shard from running;
- an induced SIGINT leaves stdout, stderr, event log, exit/signal, exact completed and
  not-run node IDs, and a non-PASS receipt;
- the aggregator refuses incomplete or incompatible shard sets;
- no receipt file is written inside a protected Git worktree or project path;
- complete semantic outputs and all existing fail-closed tests remain unchanged;
- controlled before/after wall-clock measurement reports at least 70% reduction for
  the equivalent Pay pilot batch, or reports the actual shortfall without claiming
  acceptance.

## Candidate implementation WriteSet

The implementation plan must freeze its own Exact WriteSet after the validation
session candidate stabilizes. The current candidate set is:

- `pyproject.toml`
- `tests/test_pay_nexus_java_capability_adoption_pilot.py`
- `src/evolution_harness/pytest_receipt.py`
- `src/evolution_harness/pytest_shard_runner.py`
- `harness-test`, which only sets repository `PYTHONPATH` and invokes
  `python -m evolution_harness.pytest_shard_runner`; the product `harness` CLI and
  `src/evolution_harness/cli.py` remain unchanged
- `core/schemas/pytest-shard-receipt.schema.json`
- `core/schemas/pytest-run-receipt.schema.json`; no Pack, lock, projection,
  Authority, or coordinator schema changes
- `tests/test_pytest_shard_runner.py`
- `README.md` local acceptance commands after behavior is stable

The Pay module fixture reports its final per-key session statistics to the explicitly
loaded plugin through a no-op-safe helper in `pytest_receipt.py`. Ordinary pytest runs
without that plugin still execute the assertions and do not require a receipt. This
candidate consumes the stable public/session API from the first candidate and must
not reopen upstream Registry implementation files.

No external dependency is added in the initial candidate. If pytest's documented
hooks cannot provide the required flushed evidence, implementation stops and returns
for approval before adding `pytest-reportlog`, xdist, or another plugin.

## Delivery sequence

1. Add strict marker registration and RED collection tests.
2. Parameterize the six scenarios and separate install planning.
3. Bind the serial `pack_e2e` fixture to one explicit validation session and assert
   Gate/digest counters.
4. Implement collection/node/shard manifests and the flushed pytest event plugin.
5. Implement the outer runner, signal handling, final receipt, and aggregation.
6. Run deterministic failure/interruption/recovery tests.
7. Run the combined benchmark and one stable complete regression.
8. Fix Candidate/Parent/Tree and obtain the repository-required independent review.

## Stop conditions

Stop and request renewed design approval if:

- the runner needs persistent Pack validation trust or cross-process session reuse;
- xdist or a new third-party plugin becomes required;
- receipt semantics expand into merge/release/Authority or coordinator decisions;
- receipt storage needs to enter a protected repository/project path;
- full-suite selection would silently exclude `pack_e2e`;
- scenario parameterization changes expected resolution, projection, lock, or business
  permission semantics;
- the WriteSet expands into Pack content, project Authority, generated projection, or
  installation/apply paths.
