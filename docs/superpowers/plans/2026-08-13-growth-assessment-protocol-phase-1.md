# Growth Assessment Protocol Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic Growth Assessment Protocol that records R1 named-trigger and R2 closure assessments in a safe append-only user-local Inbox, returns auditable receipts, and scans them read-only without writing source projects, the Harness worktree, or governed learning records.

**Architecture:** Introduce four strict cross-project schemas, a pure normalization/identity layer, a source-provenance validator, and a directory-descriptor-anchored append-only store outside every Git worktree. Expose `harness growth assess`, `harness growth receipt`, and `harness growth scan`. Phase 1 stops before Experience import, Skill/Hook integration, scheduled execution, semantic clustering, live Brownfield adoption, Candidate creation, or Promotion.

**Tech Stack:** Python 3.12+, standard library, PyYAML, jsonschema Draft 2020-12, pytest, existing `SchemaStore`, `canonical_json_bytes`, `sha256_bytes`, `AnchoredRoot`, project registration, authority snapshot, and exact-lock validation.

## Risk and review route

This is an `R2` implementation because it changes governance contracts, schemas, cross-project provenance, owner-only durable state, path handling, concurrent persistence, and CLI behavior.

- Use RED → GREEN for each behavior task.
- During iteration, run only the smallest focused tests that can falsify the current change.
- Do not rerun the complete gate until the candidate tree is stable.
- Before closure, run the complete repository gate once, fix any finding, then rerun only gates affected by the changed tree.
- Freeze `Candidate`, direct `Parent`, and `Tree` and request an independent `deep_reviewer` review.
- Do not use `ultra_gatekeeper` unless a repository rule or later explicit user instruction requires a final ultra gate.
- Do not merge, push, install a scheduled task, or modify Pay-Nexus without separate authority.

## Phase 1 exact scope

### Allowed implementation WriteSet

- Create: `core/schemas/growth-assessment-request.schema.json`
- Create: `core/schemas/growth-assessment-receipt.schema.json`
- Create: `core/schemas/growth-capture-result.schema.json`
- Create: `core/schemas/growth-scan-report.schema.json`
- Create: `src/evolution_harness/growth_assessment.py`
- Create: `src/evolution_harness/growth_source.py`
- Create: `src/evolution_harness/growth_store.py`
- Modify: `src/evolution_harness/anchored_fs.py`
- Modify: `src/evolution_harness/cli.py`
- Create: `tests/test_growth_assessment.py`
- Create: `tests/test_growth_source.py`
- Create: `tests/test_growth_store.py`
- Create: `tests/test_growth_cli.py`
- Modify: `README.md`
- Modify only if structural validation proves it necessary: a schema inventory or explicit generated schema index already owned by the current repository

### Explicitly excluded

- `.agent-evolution/registration.yaml` in any project
- `core/schemas/project-harness-registration.schema.json`
- `src/evolution_harness/feedback.py`
- `src/evolution_harness/learning.py`
- existing Experience, Candidate, Eval, capability, or promotion-ledger records
- `generated/**`, unless an existing deterministic schema inventory requires regeneration and the verification command proves the dependency
- project-local outbox directories
- repo-local or global Skills
- Hooks, scheduled tasks, daemons, background processes, transcript capture, embeddings, vector search, or LLM classification
- Pay-Nexus files, tests, branches, commits, task cards, project state, exact lock, projections, or generated Skills

Any required implementation path outside the allowed WriteSet is a stop condition and requires a plan update before editing.

## Locked Phase 1 behavior

1. R0 and untriggered R1 work do not call GAP.
2. Adopted R2 closure records exactly one assessment obligation, including `NO_SIGNAL`.
3. The caller supplies explicit time, risk, trigger, gate, task, attempt, source, verdict, and distilled evidence.
4. The Harness validates but does not infer project truth or semantic transferability.
5. The Inbox is outside source and Harness Git worktrees.
6. The persisted receipt is one append-only JSON file keyed by a deterministic obligation identity.
7. Same key + same normalized request is idempotent; same key + different request fails closed.
8. Assessment reads only registered authority-map inputs or the explicit Harness-self Git identity; evidence references are never followed generically.
9. Scan reads only the Inbox and writes nothing.
10. Phase 1 never imports a receipt into governed learning.

## Locked public interfaces

### Python

```python
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
        cls, repository_root: Path, state_root: Path | None
    ) -> "GrowthInbox": ...
    def record(self, request: dict[str, Any]) -> dict[str, Any]: ...
    def receipt(self, assessment_id: str) -> dict[str, Any]: ...
    def scan(self, *, as_of: str) -> dict[str, Any]: ...
```

`GrowthAssessmentError.code` initially includes:

```text
ASSESSMENT_SCHEMA_INVALID
ASSESSMENT_KEY_CONFLICT
ASSESSMENT_ID_MISMATCH
REQUEST_DIGEST_MISMATCH
SOURCE_REGISTRATION_INVALID
SOURCE_CONTEXT_MISMATCH
SOURCE_AUTHORITY_NO_GO
SOURCE_REVISION_MISMATCH
SOURCE_LOCK_MISMATCH
SOURCE_SELF_INVALID
STATE_ROOT_UNAVAILABLE
STATE_ROOT_UNSAFE
INBOX_LOCKED
RECEIPT_UNSAFE
RECEIPT_CORRUPT
RECEIPT_NOT_FOUND
TIMESTAMP_INVALID
```

### CLI

```text
harness growth assess
  --source <absolute source root>
  --request <path | ->
  [--state-root <absolute state root>]
  --format json

harness growth receipt
  --id <growth-assessment:...>
  [--state-root <absolute state root>]
  --check
  --format json

harness growth scan
  --as-of <RFC3339>
  [--state-root <absolute state root>]
  --format json
```

All three use the existing `harness-cli/v1` envelope. `assess` returns `ok=true` only for `RECORDED` or exact `DUPLICATE`. `receipt --check` returns `ok=true` only when a schema-valid receipt recomputes to the requested ID. `scan` returns `ok=false` when any unsafe or corrupt record makes its gate `FAIL`; it still reports only safe metadata already validated before emission.

If normalized source validation succeeds but the state root is unavailable or the non-blocking Inbox lock is busy, `assess` returns `ok=false` with a schema-valid `growth-capture-result/v1` payload:

```text
growthCaptureGate: DEFERRED
status: DEFERRED
assessmentKey: <derived key>
assessmentId: <derived id>
requestDigest: <full digest>
deferredReason: STATE_ROOT_UNAVAILABLE | INBOX_LOCKED
retryInstruction:
  command: growth assess
  requiresSameRequestDigest: true
  requiresSameSourceContext: true
```

Unsafe state, corrupt state, invalid source/provenance, schema errors, and key conflicts return `FAIL`; they are never softened to `DEFERRED`.

### Default state root

Resolve the state root in this order:

1. explicit `--state-root`;
2. `Path(os.environ["CODEX_HOME"]) / "agent-evolution/growth/v1"`;
3. `STATE_ROOT_UNAVAILABLE`.

Do not fall back to the source repository, Harness repository, current working directory, home directory, or system temporary directory. Tests always pass an isolated explicit root.

---

### Task 1: Strict protocol schemas

**Files:**

- Create: `core/schemas/growth-assessment-request.schema.json`
- Create: `core/schemas/growth-assessment-receipt.schema.json`
- Create: `core/schemas/growth-capture-result.schema.json`
- Create: `core/schemas/growth-scan-report.schema.json`
- Create: `tests/test_growth_assessment.py`

- [ ] **Step 1: Write schema rejection tests first**

Add neutral factories for a valid R1 `SIGNAL` and R2 `NO_SIGNAL` request. Write failing tests for:

- missing every required top-level field;
- unknown fields including `transcript`, `messages`, `prompt`, `response`, `rawLog`, and `fileContent`;
- absolute, empty, `.` or `..` evidence references;
- summaries/distillations over their bounds;
- duplicate reason codes, capability hints, or evidence entries;
- `SIGNAL` without positive signal reason, evidence, summary, or impact;
- `NO_SIGNAL` without an allowed no-signal reason;
- R1 trigger outside the R1 set and R2 trigger outside the R2 set;
- malformed Git head/tree and SHA-256 values;
- fixed-candidate identities that are only partially present;
- invalid RFC 3339 timestamps, including offset-hour/minute overflow;
- unknown receipt/report fields and invalid status/disposition combinations.
- invalid capture-result combinations, including `PASS` without a receipt, `DEFERRED` with a receipt, missing key/ID/digest, or a non-retryable reason presented as deferred.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH=src uv run --isolated --python 3.12 \
  --with pytest --with PyYAML --with jsonschema \
  pytest -p no:cacheprovider -q tests/test_growth_assessment.py
```

Expected: FAIL because the four schemas do not exist.

- [ ] **Step 2: Implement the four schemas**

Use Draft 2020-12, repository-local `$id` values, strict `required`, bounded arrays/strings, `uniqueItems: true`, conditional `allOf`, and `additionalProperties: false` at every object level.

Keep request source modes explicit:

- `REGISTERED_PROJECT` requires `integrationId`, `authoritySnapshotFingerprint`, and `capabilityLockFingerprint`.
- `HARNESS_SELF` forbids those registered-project-only fields and requires Harness project identity.

Keep evidence references opaque and safe; the schema must not claim they are readable files.

- [ ] **Step 3: Run focused schema tests**

Run the command from Step 1.

Expected: PASS.

- [ ] **Step 4: Commit the schema contract**

```bash
git add core/schemas/growth-assessment-request.schema.json \
  core/schemas/growth-assessment-receipt.schema.json \
  core/schemas/growth-capture-result.schema.json \
  core/schemas/growth-scan-report.schema.json \
  tests/test_growth_assessment.py
git commit -m "feat: define growth assessment protocol contracts"
```

---

### Task 2: Pure normalization, timestamps, and content identities

**Files:**

- Create: `src/evolution_harness/growth_assessment.py`
- Modify: `tests/test_growth_assessment.py`

- [ ] **Step 1: Write identity and normalization tests**

Tests must prove:

- normalization validates before hashing;
- CRLF and LF normalize identically in bounded text fields;
- set-valued arrays normalize lexicographically;
- evidence ordering is canonical by `(kind, reference, revision, digest)`;
- ordered task identity fields are unchanged;
- the same normalized request yields the same key, ID, and full digest;
- summary, verdict, evidence, source revision, authority snapshot, exact lock, task attempt, gate, policy, or fixed candidate changes the expected identity;
- fields excluded from the obligation key still change `assessmentId` and cause a key conflict;
- timestamps accept valid RFC 3339 offsets and reject offset overflow;
- caller-provided IDs are impossible because the request schema has no ID fields.
- `PASS` and `DEFERRED` capture results validate only with their exact conditional fields and retain the same derived key/ID/digest.

Expected: FAIL because the module does not exist.

- [ ] **Step 2: Implement the pure layer**

Implement:

```python
GROWTH_POLICY_VERSION = "growth-assessment-policy/v1"

class GrowthAssessmentError(ValueError):
    def __init__(self, code: str, message: str): ...

def parse_rfc3339(value: str) -> datetime: ...
def normalize_growth_assessment_request(repository_root: Path, value: dict[str, Any]) -> dict[str, Any]: ...
def growth_assessment_key(value: dict[str, Any]) -> str: ...
def growth_assessment_id(value: dict[str, Any]) -> str: ...
def growth_request_digest(value: dict[str, Any]) -> str: ...
def build_growth_receipt(value: dict[str, Any]) -> dict[str, Any]: ...
def validate_growth_receipt(repository_root: Path, value: dict[str, Any]) -> dict[str, Any]: ...
def build_growth_capture_result(
    value: dict[str, Any],
    *,
    receipt: dict[str, Any] | None = None,
    deferred_reason: str | None = None,
) -> dict[str, Any]: ...
```

Use existing `SchemaStore`, `canonical_json_bytes`, and `sha256_bytes`. Do not read the clock, filesystem, environment, Git, project, or Inbox in this module.

Use separate canonical payloads:

- key payload: policy + source identity + task/attempt/gate/fixed candidate;
- assessment payload: the complete normalized request;
- digest payload: the same complete normalized request, retaining the full 64-hex digest.

Receipt and capture-result validation recompute all three identities and never trust the stored values. Only `STATE_ROOT_UNAVAILABLE` and `INBOX_LOCKED` can construct a deferred result.

- [ ] **Step 3: Run focused tests and `git diff --check`**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH=src uv run --isolated --python 3.12 \
  --with pytest --with PyYAML --with jsonschema \
  pytest -p no:cacheprovider -q tests/test_growth_assessment.py
git diff --check
```

Expected: PASS.

- [ ] **Step 4: Commit the pure protocol layer**

```bash
git add src/evolution_harness/growth_assessment.py tests/test_growth_assessment.py
git commit -m "feat: normalize growth assessment identities"
```

---

### Task 3: Source provenance validation with zero source writes

**Files:**

- Create: `src/evolution_harness/growth_source.py`
- Create: `tests/test_growth_source.py`

- [ ] **Step 1: Write registered-project provenance tests**

Build a neutral Harness fixture and registered external-source fixture using the same patterns as `tests/test_project_registration.py`. Snapshot every source filesystem entry before and after each call.

Tests must prove:

- valid registration, runtime, integration, exact lock, live source revision, and Authority Snapshot pass;
- missing registration fails;
- explicit source path symlink fails;
- registration/integration/runtime/lock mismatch fails;
- live authority drift, dirty authority set, missing authority, excluded authority, or symlinked authority fails;
- a request fingerprint from a prior snapshot fails;
- `REPLAYABLE` evidence passes only when both strings pass `safe_relative_path` and the resulting safe POSIX reference is byte-for-byte equal to exactly one live `authorities[].path`; no filesystem resolution, case/Unicode folding, alias expansion, or other normalization is allowed. Its digest must equal `sha256:` plus that record's SHA-256, and its revision must equal the snapshot `sourceRevision.head`;
- an absent, duplicate, derived-only, mismatched-digest, or mismatched-revision `REPLAYABLE` claim fails before the Inbox is opened;
- `OPAQUE` evidence is never opened merely because its reference resembles a path;
- excluded `temp-input/**`-style paths are never read, enumerated, or hashed;
- the source snapshot is byte-for-byte and entry-for-entry unchanged on success and every failure.

Use instrumentation around `AnchoredRoot.read_bytes` or the authority reader to assert the exact allowlist, not only a Git status check.

Expected: FAIL because `growth_source.py` does not exist.

- [ ] **Step 2: Write Harness-self provenance tests**

Create a disposable Git repository fixture. Prove:

- `HARNESS_SELF` accepts only when source root and repository root are the same physical directory and requested HEAD/tree match;
- an external unregistered repository cannot claim `HARNESS_SELF`;
- head drift, tree drift, partial fixed identity, or an unsafe source root fails;
- `HARNESS_SELF` rejects `REPLAYABLE` evidence in Phase 1 because self mode has no authority allowlist;
- the validator uses read-only Git commands and leaves refs, index, tracked files, untracked files, and worktree status unchanged.

- [ ] **Step 3: Implement the source validator**

Implement:

```python
def validate_growth_source(
    repository_root: Path,
    source_root: Path,
    request: dict[str, Any],
) -> dict[str, Any]: ...
```

For registered projects, reuse:

- `load_project_registration(...)`;
- the existing integration loader and exact-lock validation already reached by registration;
- `build_authority_snapshot(...)` using only the registered integration authority map.

Compare every request source identity to validated live values. For each `REPLAYABLE` evidence item, validate both reference strings with `safe_relative_path`, then require exact safe-string equality with exactly one non-`DERIVED` live `authorities[].path`, the `sha256:`-prefixed record SHA-256, and snapshot `sourceRevision.head`; never resolve or read the evidence reference again. Reject aliases even if they would resolve to the same file, and reject `REPLAYABLE` in `HARNESS_SELF` during Phase 1. Do not introduce a second source scanner or duplicate registration semantics.

For Harness self, obtain only `git rev-parse HEAD` and `git rev-parse HEAD^{tree}` through non-interactive read-only subprocess calls. Do not run Git cleanup, checkout, reset, add, commit, update-index, or status commands that refresh the index.

Return a small validated context projection; do not mutate the request.

- [ ] **Step 4: Run focused source and registration regression tests**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH=src uv run --isolated --python 3.12 \
  --with pytest --with PyYAML --with jsonschema \
  pytest -p no:cacheprovider -q \
    tests/test_growth_source.py \
    tests/test_project_registration.py \
    tests/test_authority_engine.py \
    tests/test_lock_enforcement.py
```

Expected: PASS.

- [ ] **Step 5: Commit provenance validation**

```bash
git add src/evolution_harness/growth_source.py tests/test_growth_source.py
git commit -m "feat: validate growth assessment provenance"
```

---

### Task 4: Safe append-only external Inbox

**Files:**

- Modify: `src/evolution_harness/anchored_fs.py`
- Create: `src/evolution_harness/growth_store.py`
- Modify: `tests/test_anchored_fs.py`
- Create: `tests/test_growth_store.py`

- [ ] **Step 1: Write anchored staged-publication tests**

Add tests for a minimal new primitive such as:

```python
AnchoredRoot.publish_bytes_no_replace(
    staging_directory: str,
    destination: str,
    data: bytes,
    *,
    mode: int = 0o600,
) -> None
```

Tests must prove:

- the staging and destination directories are already-opened, no-follow directories on the same device;
- data is written to a random `O_CREAT | O_EXCL | O_NOFOLLOW` staging file with the requested owner-only mode and fsynced before publication;
- one `os.link(..., follow_symlinks=False)` publishes the complete inode to the absent final name without replacement;
- the destination directory is fsynced before success can return;
- the current operation's staging link is removed only after publication, and the staging directory is then fsynced;
- existing regular file is never replaced;
- symlink final target and symlink parent fail without touching the referent;
- directory and special-file targets fail;
- a losing publisher cannot overwrite the winner;
- a crash during staging write exposes no final Inbox entry;
- a crash after staging fsync but before link exposes no final Inbox entry;
- a crash after link but before destination-directory fsync leaves the final entry either absent or complete after restart, never partial;
- a crash after destination-directory fsync but before staging unlink leaves one complete durable final receipt and a harmless non-authoritative staging link.

Expected: FAIL because the primitive does not exist.

- [ ] **Step 2: Implement only the reusable staged no-replace primitive**

Use directory-relative operations throughout. Create a random staging name with `O_CREAT | O_EXCL | O_NOFOLLOW`; keep and verify its inode while writing; `fsync` the complete file; compare the opened staging and destination directory devices; publish with a hard link that fails when the destination exists; then `fsync` the destination directory. Only after the visibility commit may the method unlink its own still-inode-matched staging name and `fsync` the staging directory.

Do not use direct `O_EXCL` creation of the final Inbox name, `os.replace`, rename-over-existing, `Path.write_text`, or a check-then-write final publication. Do not scan or treat staging bytes as authority. On an ordinary handled failure, the method may unlink only the current operation's random staging name after verifying that name still references the opened inode. A process crash may leave a staging link; Phase 1 performs no startup cleanup.

Do not change existing `write_bytes` semantics in this task.

- [ ] **Step 3: Write Growth Inbox safety and race tests**

Tests must cover:

- explicit missing state root is created only at the exact requested path with `0700` directories;
- default root requires `CODEX_HOME` and never uses another fallback;
- relative explicit `--state-root` and relative `CODEX_HOME` values are rejected before CWD-based resolution or state creation;
- a state root equal to or contained by the Harness repository, source repository, any linked worktree of either repository, or any other containing Git worktree is rejected before creating a directory or lock;
- lexical aliases, `..`, symlink components, and a symlinked nearest-existing ancestor cannot bypass repository-containment checks;
- existing state root with group/other permissions, wrong owner, symlink component, non-directory component, or unsafe Inbox/lock entry fails;
- `staging`, `inbox`, and `locks` must be fixed owner-only anchored directories, and `staging`/`inbox` must be on the same device;
- lock file is regular, current-user-owned, mode `0600`, and opened no-follow;
- two processes contending on identical requests produce exactly one file; the lock loser returns `DEFERRED`, and its later exact retry returns `DUPLICATE`;
- two processes contending on conflicting requests preserve exactly one valid winner; the lock loser returns `DEFERRED`, and its later retry returns `ASSESSMENT_KEY_CONFLICT`;
- deterministic process-death injection after staging create, mid-write, after file fsync, after hard-link, after Inbox-directory fsync, and after staging unlink proves that a final receipt is never partial;
- staging files and links are never enumerated by receipt lookup or scan and never count as receipts;
- a complete published receipt is always readable and identity-valid;
- an existing corrupt or identity-mismatched record is never overwritten or repaired;
- no operation removes, truncates, replaces, hard-links from, or renames an existing final receipt;
- scan enumerates only direct `inbox/*.json` entries through an anchored directory descriptor and rejects symlinks, subdirectories, special files, unsafe names, and unsafe modes;
- scan has zero writes, including no index, mtime update by application logic, quarantine move, or repair.

Use real subprocesses for the concurrent cases. Do not rely only on threads.

Expected: FAIL because `growth_store.py` does not exist.

- [ ] **Step 4: Implement `GrowthInbox`**

Implement a single state owner:

```python
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
        cls, repository_root: Path, state_root: Path | None
    ) -> "GrowthInbox": ...
    def record(self, request: dict[str, Any]) -> dict[str, Any]: ...
    def receipt(self, assessment_id: str) -> dict[str, Any]: ...
    def scan(self, *, as_of: str) -> dict[str, Any]: ...
```

Requirements:

- create only the fixed `inbox`, `staging`, and `locks` children;
- `open_for_record` may safely create the exact state root and fixed children; `open_read_only` used by receipt/scan must create nothing and fails if state is absent;
- before creation, reject any intended state root inside the physical Harness/source roots, any of their Git common-directory worktrees, or a Git worktree discovered from the nearest existing ancestor; do not rely on a string-prefix check;
- derive the receipt filename from the 24-hex key suffix, never from project text;
- hold one non-blocking exclusive `flock` on `locks/inbox.lock` across existing-record validation and staged publication; receipt/scan use a shared lock on the already-existing safe lock file;
- implement this Inbox-local lock directly against the anchored `locks/inbox.lock`; do not reuse `exclusive_process_lock`, whose temporary state root and exclusive-only contract do not satisfy GAP;
- serialize the authoritative persisted receipt as canonical JSON plus one newline;
- persist `status: RECORDED`; project `DUPLICATE` only in the returned copy;
- when the key file exists, read its bytes once, validate schema/key/id/digest, and compare canonical bytes;
- find `receipt --id` by safe anchored enumeration and require exactly one match;
- derive scan counts in memory;
- never enumerate or interpret `staging/` during receipt lookup or scan;
- never read or write a source project.

If state-root creation and worktree-containment safety cannot be proven with existing helpers, add the smallest private descriptor-anchored constructor and read-only Git worktree detector in `growth_store.py`; do not generalize unrelated filesystem APIs. Containment validation must complete before the first `mkdir` or lock-file open.

- [ ] **Step 5: Run focused filesystem/store tests**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH=src uv run --isolated --python 3.12 \
  --with pytest --with PyYAML --with jsonschema \
  pytest -p no:cacheprovider -q \
    tests/test_anchored_fs.py \
    tests/test_growth_assessment.py \
    tests/test_growth_store.py \
    tests/test_process_lock.py
git diff --check
```

Expected: PASS.

- [ ] **Step 6: Commit the safe store**

```bash
git add src/evolution_harness/anchored_fs.py \
  src/evolution_harness/growth_store.py \
  tests/test_anchored_fs.py \
  tests/test_growth_store.py
git commit -m "feat: add append-only growth receipt inbox"
```

---

### Task 5: Assessment, receipt, and scan CLI

**Files:**

- Modify: `src/evolution_harness/cli.py`
- Create: `tests/test_growth_cli.py`

- [ ] **Step 1: Write CLI contract and zero-write tests**

Use isolated Harness, source, request, and state fixtures. Snapshot the complete Harness worktree, source tree, request directory, and state root before and after each command as appropriate.

Tests must prove:

- `growth assess --request -` accepts one JSON or YAML document from stdin;
- an explicit request file behaves identically and remains unchanged;
- a valid registered R1 `SIGNAL` returns `RECORDED` and a valid receipt;
- a valid registered R2 `NO_SIGNAL` returns `RECORDED`;
- exact replay returns `DUPLICATE`, the same ID/digest, and no second file;
- conflicting replay returns `ASSESSMENT_KEY_CONFLICT` and preserves the winner;
- an unavailable default state root and a busy non-blocking Inbox lock return schema-valid `DEFERRED` results with the derived key/ID/digest and same-context retry instruction;
- unsafe state, source mismatch, corrupt receipt, and key conflict return `FAIL`, never `DEFERRED`;
- `growth receipt --check` verifies an existing ID and fails for missing/corrupt state;
- `growth scan` returns deterministic records and counts for a fixed `--as-of`;
- scan reports `HUMAN_TRIAGE_REQUIRED` only for `SIGNAL` and `NO_ACTION` for `NO_SIGNAL`;
- receipt/scan against missing state fail without creating the state root, Inbox, or lock file;
- `--state-root` inside the source project, Harness repository, a linked worktree, or another Git repository fails before any state entry is created;
- relative `--source`, request-file, `--state-root`, or `CODEX_HOME` values fail before source or state access;
- no command changes source project or Harness worktree bytes, entries, refs, index, or status;
- invalid registration, authority, lock, schema, path, timestamp, state root, or receipt returns the public error code in the existing CLI envelope;
- existing `feedback capture`, `experience`, `integration`, and `planning` CLI contracts remain unchanged.

Expected: FAIL because the parser has no `growth` command.

- [ ] **Step 2: Add parser and dispatch without changing existing commands**

Add one `growth` command with required actions `assess`, `receipt`, and `scan`. Reuse the current `_emit` envelope and top-level exception mapping.

Implementation order for `assess` is mandatory:

1. read one bounded request document;
2. schema-validate and normalize;
3. validate source context;
4. derive key/ID/digest and validate that the intended state root is outside every protected or containing Git worktree;
5. only then open the state root;
6. record or replay the receipt;
7. return structured data.

This order proves invalid/untrusted source input cannot create Inbox state.

Bound stdin and request-file bytes before YAML parsing. Use `yaml.safe_load` only. Reject multiple YAML documents and non-object roots.

Open an explicit request file as one no-follow regular file and read its bounded bytes once. Do not follow a request-file symlink or reread the path after validation.

`scan` and `receipt` do not accept `--source` and must never load project registration or enumerate source repositories.

Catch only `STATE_ROOT_UNAVAILABLE` and `INBOX_LOCKED` at the `assess` orchestration boundary and return a validated `growth-capture-result/v1` with `growthCaptureGate: DEFERRED`. All other exceptions continue through the normal `ok=false` error envelope with `growthCaptureGate: FAIL` where applicable.

- [ ] **Step 3: Run focused CLI and compatibility tests**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH=src uv run --isolated --python 3.12 \
  --with pytest --with PyYAML --with jsonschema \
  pytest -p no:cacheprovider -q \
    tests/test_growth_cli.py \
    tests/test_growth_assessment.py \
    tests/test_growth_source.py \
    tests/test_growth_store.py \
    tests/test_handoff_feedback.py \
    tests/test_learning_flow.py \
    tests/test_project_registration.py \
    tests/test_controlled_planning_cli.py
```

Expected: PASS.

- [ ] **Step 4: Commit the CLI**

```bash
git add src/evolution_harness/cli.py tests/test_growth_cli.py
git commit -m "feat: expose growth assessment receipts"
```

---

### Task 6: Documentation and compatibility boundary

**Files:**

- Modify: `README.md`
- Modify only if verification proves necessary: the current explicit schema inventory or generated structural artifact

- [ ] **Step 1: Add README usage and boundaries**

Document:

- R0 skip, named-trigger R1, and mandatory adopted R2 assessment;
- separate `projectGate` and `growthCaptureGate`;
- `SIGNAL` and `NO_SIGNAL` examples;
- external Inbox location and permissions;
- stdin-first `growth assess`, `growth receipt --check`, and read-only `growth scan` commands;
- no Skill/Hook/scheduler in Phase 1;
- no transcript or source-body capture;
- no project/Harness worktree writes during assess/scan;
- no automatic Experience, Candidate, Eval, capability change, projection, or Promotion;
- later human-triage/import boundary.

Do not describe Phase 2–4 behavior as implemented.

- [ ] **Step 2: Run documentation/static checks**

```bash
git diff --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  uv run --isolated --python 3.12 --with PyYAML --with jsonschema \
  python -m compileall -q src
```

Expected: PASS.

- [ ] **Step 3: Commit documentation**

```bash
git add README.md
git commit -m "docs: explain growth assessment boundaries"
```

---

### Task 7: Neutral end-to-end pilot

**Files:**

- Prefer test-only fixtures in: `tests/test_growth_cli.py`
- Create a committed neutral example only if it materially improves operator usability and is added to the reviewed WriteSet first

- [ ] **Step 1: Run the neutral registered-project pilot in a disposable directory**

The pilot must execute:

1. valid R2 `NO_SIGNAL` capture;
2. exact replay;
3. valid R1 `SIGNAL` capture under a different obligation key;
4. same-key conflicting replay;
5. receipt verification;
6. read-only scan;
7. source and Harness before/after filesystem comparison.

Record evidence in test output or a temporary receipt bundle only; do not commit operational Inbox data.

- [ ] **Step 2: Run adversarial negative matrix**

At minimum:

- path traversal and absolute paths;
- source and state-root symlinks plus state roots nested in any Git worktree;
- unsafe owner/mode;
- excluded authority alias/symlink bypass;
- forged, missing, duplicate, digest-drifted, and revision-drifted `REPLAYABLE` evidence;
- stale lock/source/snapshot;
- transcript/unknown/oversized data;
- identical and conflicting multiprocess races;
- process exit at every staged-publication boundary, including mid-write and after hard-link but before directory fsync;
- stale partial and complete staging entries proving scan isolation and retry safety;
- corrupt existing receipt;
- scan with unexpected entry types;
- `CODEX_HOME` absent with no explicit root;
- busy Inbox lock returning a reproducible `DEFERRED` result without a write.

Expected: every unsafe case fails closed and leaves project, Harness, and prior valid receipts unchanged.

- [ ] **Step 3: Run the complete focused GAP suite**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH=src uv run --isolated --python 3.12 \
  --with pytest --with PyYAML --with jsonschema \
  pytest -p no:cacheprovider -q \
    tests/test_growth_assessment.py \
    tests/test_growth_source.py \
    tests/test_growth_store.py \
    tests/test_growth_cli.py
```

Expected: PASS.

---

### Task 8: Stable candidate, complete verification, and independent review

**Files:**

- No new scope

- [ ] **Step 1: Confirm exact WriteSet and diff hygiene**

```bash
git status --short
git diff --check
git diff --stat
git diff --name-status <phase-1-base>...HEAD
```

Expected: only the approved Phase 1 WriteSet is present; no source-project or operational Inbox bytes are tracked.

- [ ] **Step 2: Run the complete Harness gate once on the stable tree**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH=src uv run --isolated --python 3.12 \
  --with pytest --with PyYAML --with jsonschema \
  pytest -p no:cacheprovider -q

./harness validate --check-generated --format json
./harness registry build --check --format json
./harness catalog build --check --format json
./harness project lock --project examples/project-fixture --check --format json
./harness projection build \
  --project examples/project-fixture \
  --intent architecture-review \
  --topic resolver-mvp \
  --output 'review findings' \
  --runtime CHATGPT \
  --check \
  --format json
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

Expected:

- full pytest PASS;
- structural validation PASS with no issues;
- registry/catalog freshness PASS;
- exact lock PASS;
- ChatGPT and Codex projection freshness PASS;
- engineering doctor PASS;
- `semanticGate` remains reported separately and is not inferred from mechanical tests.

- [ ] **Step 3: Commit the stable candidate if needed**

```bash
git status --short
git add <only-approved-phase-1-files>
git commit -m "feat: add growth assessment protocol phase 1"
```

Do not stage unrelated files or any operational Inbox data.

- [ ] **Step 4: Freeze reproducible identity**

Capture:

```bash
git rev-parse HEAD
git rev-parse HEAD^
git rev-parse 'HEAD^{tree}'
git status --short
```

Expected: exact Candidate, direct Parent, Tree, and clean worktree.

- [ ] **Step 5: Request independent fixed-candidate review**

Assign a `deep_reviewer` the exact Candidate/Parent/Tree, Phase 1 base, allowed WriteSet, design spec, plan, and required gates. Require:

- clean detached clone;
- complete `base..candidate` review;
- P0/P1/P2 count and GO/NO-GO;
- focused adversarial replay of path, permission, source-boundary, idempotency, and concurrency cases;
- explicit confirmation that assess/scan never write the registered source project or the Harness worktree;
- explicit confirmation that `REPLAYABLE` evidence is bound to the validated Authority Snapshot and state roots inside Git worktrees are rejected before creation;
- explicit confirmation that deferred capture retains key/ID/digest and cannot masquerade as PASS;
- explicit confirmation that no Experience/Candidate/Promotion is created;
- no Pay-Nexus access because the live Brownfield pilot is outside Phase 1.

Any P0/P1 is `NO-GO`. Fix on a new commit, rerun only affected gates plus the final complete gate required by the changed tree, freeze a new identity, and request a fresh review.

- [ ] **Step 6: Report without crossing deployment boundaries**

The final report must include:

```text
GAP_PROTOCOL_CONTRACTS
GAP_REGISTERED_SOURCE_VALIDATION
GAP_REPLAYABLE_EVIDENCE_BINDING
GAP_APPEND_ONLY_INBOX
GAP_STATE_ROOT_OUTSIDE_GIT
GAP_IDEMPOTENT_REPLAY
GAP_CONCURRENT_WRITER_SAFETY
GAP_DEFERRED_CAPTURE_CONTRACT
GAP_READ_ONLY_SCAN
GAP_PROJECT_ZERO_WRITE
GAP_HARNESS_WORKTREE_ZERO_WRITE
GAP_NO_AUTOMATIC_LEARNING
GAP_NEUTRAL_PILOT
GAP_FIXED_CANDIDATE_REVIEW
```

For each item provide `PASS | FAIL`, command, evidence, and result. Also report known limits:

- no scheduled task;
- no Hook;
- no import;
- no semantic deduplication;
- no automatic Experience/Candidate/Eval/Promotion;
- no production or cross-device state store;
- no push, deployment, or project-local materialization.

Stop after the reviewed local candidate. Merge, push, scheduled-task creation, user-level instruction changes, and Phase 2 require separate authorization.

## Phase 1 definition of done

Phase 1 is complete only when:

- all four protocol schemas are strict and validated;
- normalized identities are deterministic;
- registered and self provenance fail closed on drift;
- the external Inbox uses owner-only, no-follow, same-filesystem staged hard-link publication so final receipts are append-only, atomically visible, and concurrency-safe;
- exact replay is idempotent and conflicting replay preserves the winner;
- scan is read-only and deterministic;
- source projects and the Harness Git worktree remain unchanged during assess/receipt/scan;
- no raw transcript or file body is persisted;
- privacy enforcement is structural and bounded; Phase 1 does not claim complete semantic secret detection inside otherwise valid prose;
- no receipt is automatically imported;
- the neutral end-to-end pilot passes;
- full Harness gates pass on the fixed tree;
- the independent fixed-candidate reviewer returns GO with P0/P1/P2 = 0/0/0;
- no protected boundary has been crossed.

## Deferred follow-up plans

Do not append these to Phase 1 during implementation:

1. **Phase 2:** explicit human triage and dry-run-first Experience import.
2. **Pilot A:** separately authorized, read-only Brownfield validation; Pay-Nexus is the preferred first candidate after fresh registration/authority/lock revalidation and with `temp-input/**` untouched.
3. **Phase 3:** 10–20 receipt measurement and optional weekly read-only scheduled scan.
4. **Phase 4:** optional Hook/runtime reminder for missing adopted R2 receipts.
5. **Later:** retention/deletion policy, multi-host state, semantic clustering, or external service integration—only if evidence justifies them.
