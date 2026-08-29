# External Pack Toolchain Profile Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace path-bearing External Pack validator toolchain identity with a locator-free canonical profile, host-local binding, fail-closed runtime attestation, and independently provisioned ripgrep artifact.

**Architecture:** A new `toolchain_profile` module owns canonical profile loading, binding resolution, content measurement, and immutable verification results. A separate `toolchain_provisioning` module owns explicit download/archive verification and atomic managed-store publication. Existing Pack Registry, lock, resolver, projection, install, and verification-session code consume the canonical profile reference while retaining legacy behavior for legacy registrations.

**Tech Stack:** Python 3.12, JSON Schema Draft 2020-12, PyYAML, `jsonschema`, stdlib `urllib.request`, `tarfile`, SHA-256, pytest, Git worktrees.

**Spec:** `docs/superpowers/specs/2026-08-29-external-pack-toolchain-profile-decoupling-design.md`

## Global Constraints

- Base every implementation commit on `797db5f8c6aabf265da54b029bc51969873eaa0d`; do not cherry-pick evidence-only commits `047df9ab83a4bb74f203fa7b34d8ceebbff2ea2f` or `5325392748d0b619072cc2fac41f235b42439d77`.
- Preserve `capability-lock/v2`, canonical JSON encoding, exact lock fingerprint construction, immutable Pack source commit/tree/content, validator identity, closed-scenario Java exclusion, and all business execution `DENY` decisions.
- `source.repositoryPath` and every toolchain binding path remain non-canonical locators.
- Candidate validation is offline. Network access is permitted only by explicit `harness toolchain provision --apply`.
- Missing/unsafe/mismatched bindings fail before the candidate Gate; there is no `PATH`, ChatGPT.app, Homebrew, or system-directory fallback.
- A full Gate retains one pre-Gate and one post-Gate toolchain measurement and poisons the operation-scoped session on any drift.
- `rg` uses the official ripgrep 15.2.0 macOS arm64 archive with archive SHA-256 `3750b2e93f37e0c692657da574d7019a101c0084da05a790c83fd335bad973e4`.
- The extracted official `rg` executable SHA-256 is `a326a1fb48074202e9ad41e4cd1e389eeea372c8c6f7d7e80da81176d5d9430e`; the canonical artifact-manifest digest is `sha256:bfa2614eba25313624c604d16c6c727f3b243e5453b5b261321858f7eee75512`.
- Do not modify Java Pack source, Pay-Nexus files or Authority, ChatGPT.app, user-global configuration, Skill installation, deployment, push, or release state.
- Use `/Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python` for pytest commands from this worktree.
- Use RED → GREEN for each behavior task, focused regression during iteration, then one complete Harness regression and one fixed-candidate `deep_reviewer / xhigh` gate.
- Keep generated files deterministic and regenerate them through repository functions/CLI, never by hand-editing generated JSON or projection manifests.
- Commit messages follow `/Users/yuzhuangzhuang/Projects/engineering-conventions/rules/git/commit-message.md`; no merge, push, release, deploy, or downstream adoption is authorized by this plan.

## File and responsibility map

- Create `core/schemas/capability-validator-toolchain-registry.schema.json`: closed canonical schema for artifact manifests and locator-free profiles.
- Create `core/schemas/capability-validator-toolchain-binding.schema.json`: closed host-local binding schema; never referenced by canonical output schemas.
- Create `core/registries/capability-validator-toolchains.yaml`: Harness-owned artifact/profile registry, including official ripgrep provenance.
- Create `src/evolution_harness/toolchain_profile.py`: profile loading/digest, binding loading, safe command/directory measurement, relationship checks, and `VerifiedToolchain`.
- Create `src/evolution_harness/toolchain_provisioning.py`: explicit fetch/offline-archive verification, safe extraction, read-only publication, and binding-file transaction.
- Modify `src/evolution_harness/capability_pack_registry.py`: dispatch legacy versus profile toolchain verification, carry profile identity in keys, and retain session witnesses.
- Modify `src/evolution_harness/project.py`: copy profile identity—not binding—into v2 lock sources.
- Modify `src/evolution_harness/cli.py`: add `toolchain status` and dry-run/apply `toolchain provision` commands.
- Modify the three existing registration/lock/projection schemas: add a closed `MANAGED_TOOLCHAIN_PROFILE` alternative while retaining exact legacy alternatives.
- Modify `core/registries/capability-packs.yaml` only after synthetic behavior is GREEN: explicitly migrate the Java registration.
- Regenerate `generated/registries/capability-pack-registry.json` and only the neutral Java fixture locks/projections affected by the canonical migration.
- Create `tests/test_toolchain_profile.py`: canonical identity, binding relocation, negative binding, relationship, and TOCTOU coverage.
- Create `tests/test_toolchain_provisioning.py`: archive, extraction, publication, idempotency, CLI, and offline-validation coverage.
- Modify existing Registry/session/lock/project/resolver/projection/install/Java-fixture tests only where they assert canonical propagation or the explicit migration.

---

### Task 1: Define canonical profile and host-binding contracts

**Files:**
- Create: `core/schemas/capability-validator-toolchain-registry.schema.json`
- Create: `core/schemas/capability-validator-toolchain-binding.schema.json`
- Create: `core/registries/capability-validator-toolchains.yaml`
- Create: `tests/test_toolchain_profile.py`
- Modify: `core/schemas/capability-pack-registration.schema.json`

**Interfaces:**
- Consumes: `SchemaStore.validate(schema_path: str, instance: Any) -> None` and canonical JSON/SHA-256 helpers.
- Produces: registry schema `capability-validator-toolchain-registry/v1`, binding schema `capability-validator-toolchain-binding/v1`, environment contract `MANAGED_TOOLCHAIN_PROFILE`, and registration field `validator.toolchainProfile = {profileId, profileDigest}`.

- [ ] **Step 1: Write the failing schema tests**

Add tests that load the new schema through `SchemaStore`, validate a minimal fixture,
and prove canonical profiles reject path-bearing fields:

```python
def _profile_registry() -> dict[str, object]:
    digest = "sha256:" + "a" * 64
    return {
        "schemaVersion": "capability-validator-toolchain-registry/v1",
        "artifacts": [{
            "artifactId": "artifact:ripgrep:15.2.0:darwin-arm64",
            "kind": "OFFICIAL_RELEASE_ARCHIVE",
            "platform": {"os": "darwin", "architecture": "arm64"},
            "sourceUri": "https://github.com/BurntSushi/ripgrep/releases/download/15.2.0/ripgrep-15.2.0-aarch64-apple-darwin.tar.gz",
            "archiveFormat": "TAR_GZ",
            "archiveSha256": "sha256:" + "b" * 64,
            "extractedRoot": "ripgrep-15.2.0-aarch64-apple-darwin",
        }],
        "profiles": [{
            "schemaVersion": "capability-validator-toolchain-profile/v1",
            "profileId": "toolchain-profile:test:darwin-arm64:v1",
            "environmentAdapter": "JAVA_MAVEN_OFFLINE_V1",
            "platform": {"os": "darwin", "architecture": "arm64"},
            "commands": {
                name: {
                    "artifactId": f"artifact:{name}:fixture",
                    "fileName": name,
                    "sha256": digest,
                    "bindingPolicy": "HOST_ATTESTED",
                }
                for name in ("ruby", "rg", "java", "javac", "mvn")
            },
            "directories": {
                name: {"artifactId": f"artifact:{name}:fixture", "sha256": digest}
                for name in ("javaHome", "mavenHome", "mavenRepository")
            },
            "relationships": {
                "javaHomeCommands": ["java", "javac"],
                "mavenHomeCommand": "mvn",
                "mavenRepositoryLayout": "DOT_M2_REPOSITORY",
            },
        }],
    }


def test_toolchain_profile_schema_rejects_host_locator(tmp_path: Path):
    registry = _profile_registry()
    registry["profiles"][0]["commands"]["rg"]["absolutePath"] = "/Applications/ChatGPT.app/Contents/Resources/rg"
    with pytest.raises(SchemaValidationError, match="absolutePath"):
        SchemaStore(tmp_path).validate(
            "core/schemas/capability-validator-toolchain-registry.schema.json",
            registry,
        )
```

Also add registration tests proving legacy requires `toolchain`, profile mode requires
`toolchainProfile`, the two are mutually exclusive, and `profileDigest` matches
`^sha256:[0-9a-f]{64}$`.

- [ ] **Step 2: Run the tests to verify RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q tests/test_toolchain_profile.py
```

Expected: FAIL because the two schemas and registry source do not exist and
`MANAGED_TOOLCHAIN_PROFILE` is not accepted.

- [ ] **Step 3: Implement the closed schemas and source registry**

Define closed `$defs` for `sha256`, `platform`, `artifact`, `commandIdentity`,
`directoryIdentity`, `relationships`, and `profile`. Command/directory maps use safe
logical-name patterns so the Core contract is not permanently Java-shaped. Require
`environmentAdapter`; `JAVA_MAVEN_OFFLINE_V1` uses schema `allOf` constraints to
require exactly `ruby`, `rg`, `java`, `javac`, `mvn`, `javaHome`, `mavenHome`, and
`mavenRepository`. Allow only `HOST_ATTESTED`, `HARNESS_MANAGED_CACHE`, and
`HARNESS_MANAGED_STORE` binding policies. Use `oneOf` in the registration validator:

```json
{
  "if": {
    "required": ["environmentContract"],
    "properties": {"environmentContract": {"const": "MANAGED_TOOLCHAIN_PROFILE"}}
  },
  "then": {
    "required": ["toolchainProfile"],
    "not": {"required": ["toolchain"]}
  }
}
```

Seed the artifact registry with ripgrep 15.2.0 provenance, archive digest, extracted
`rg` digest, and canonical artifact digest
`sha256:bfa2614eba25313624c604d16c6c727f3b243e5453b5b261321858f7eee75512`.
The source URI is the fixed GitHub release URL in the test fixture,
`extractedRoot` is `ripgrep-15.2.0-aarch64-apple-darwin`, `extractedFiles.rg` is
`sha256:a326a1fb48074202e9ad41e4cd1e389eeea372c8c6f7d7e80da81176d5d9430e`,
and `provenancePolicy` is `OFFICIAL_GITHUB_RELEASE_ARCHIVE_SHA256`.
Require `artifactDigest` on every `HARNESS_MANAGED_STORE` command. Do not
add a Java profile yet; Task 5 records actual extracted executable and live closure
digests after the new runtime is proven synthetically.

- [ ] **Step 4: Run schema tests and existing registration-schema regression**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q tests/test_toolchain_profile.py tests/test_capability_pack_registry.py -k 'schema or registered_toolchain or registration'
```

Expected: PASS; existing legacy registrations remain valid.

- [ ] **Step 5: Commit the contract slice**

```bash
git add core/schemas/capability-validator-toolchain-registry.schema.json core/schemas/capability-validator-toolchain-binding.schema.json core/schemas/capability-pack-registration.schema.json core/registries/capability-validator-toolchains.yaml tests/test_toolchain_profile.py
git commit -m "feat(pack): 定义工具链 Profile 与本地 Binding 契约"
```

### Task 2: Implement profile loading, binding resolution, and fail-closed attestation

**Files:**
- Create: `src/evolution_harness/toolchain_profile.py`
- Modify: `src/evolution_harness/capability_pack_registry.py`
- Modify: `tests/test_toolchain_profile.py`
- Modify: `tests/test_capability_pack_registry.py`

**Interfaces:**
- Consumes: the Task 1 profile/binding schemas and registration
  `validator.toolchainProfile` reference.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class ToolchainBinding:
    profile_id: str
    command_paths: tuple[tuple[str, Path], ...]
    directory_paths: tuple[tuple[str, Path], ...]
    witness_digest: str

@dataclass(frozen=True, slots=True)
class VerifiedToolchain:
    profile_id: str | None
    profile_digest: str | None
    binding_witness: str | None
    command_paths: tuple[Path, ...]
    command_digests: tuple[tuple[str, str], ...]
    directory_identities: tuple[tuple[str, Path, str], ...]
    environment: Mapping[str, str]

def load_toolchain_profile(repository_root: Path, profile_id: str, expected_digest: str) -> Mapping[str, Any]: ...
def find_toolchain_profile(repository_root: Path, profile_id: str) -> tuple[Mapping[str, Any], str]: ...
def find_toolchain_artifact(repository_root: Path, artifact_id: str, expected_digest: str) -> Mapping[str, Any]: ...
def load_toolchain_binding(repository_root: Path, profile_id: str) -> ToolchainBinding: ...
def verify_profile_toolchain(repository_root: Path, profile: Mapping[str, Any], binding: ToolchainBinding) -> VerifiedToolchain: ...
def recheck_profile_toolchain(repository_root: Path, profile: Mapping[str, Any], binding: ToolchainBinding, expected: VerifiedToolchain) -> None: ...
def directory_identity_digest(root: Path) -> str: ...
def profile_digest(profile: Mapping[str, Any]) -> str: ...
def binding_path(repository_root: Path, profile_id: str) -> Path: ...
```

`capability_pack_registry.py` re-exports
`directory_identity_digest as _directory_identity_digest` so existing fixture tests
retain one digest implementation while migrating.

- [ ] **Step 1: Write RED tests for canonical digest and binding relocation**

Add a fixture writer that creates two read-only toolchain trees with the same bytes,
writes one host binding at a time below
`.worktrees/.capability-pack-cache/bindings/`, and asserts:

```python
def test_profile_digest_excludes_binding_paths(profile_harness: ProfileHarness):
    first = load_toolchain_profile(
        profile_harness.root,
        profile_harness.profile_id,
        profile_harness.profile_digest,
    )
    profile_harness.write_binding(profile_harness.second_root)
    second = load_toolchain_profile(
        profile_harness.root,
        profile_harness.profile_id,
        profile_harness.profile_digest,
    )
    assert canonical_json_bytes(first) == canonical_json_bytes(second)


def test_binding_relocation_changes_witness_not_verified_profile(profile_harness: ProfileHarness):
    profile = profile_harness.load_profile()
    first_binding = profile_harness.binding(profile_harness.first_root)
    second_binding = profile_harness.binding(profile_harness.second_root)
    first = verify_profile_toolchain(profile_harness.root, profile, first_binding)
    second = verify_profile_toolchain(profile_harness.root, profile, second_binding)
    assert first.profile_digest == second.profile_digest
    assert first.binding_witness != second.binding_witness
    assert first.command_digests == second.command_digests
    assert tuple((name, digest) for name, _, digest in first.directory_identities) == tuple(
        (name, digest) for name, _, digest in second.directory_identities
    )
```

- [ ] **Step 2: Write RED negative tests**

Parameterize exact mutations and expected error fragments:

```python
@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("relative-path", "binding path is unavailable or unsafe"),
        ("symlink", "binding path is unavailable or unsafe"),
        ("wrong-basename", "command basename mismatch"),
        ("writable-command", "command is writable"),
        ("wrong-command-digest", "command identity mismatch"),
        ("wrong-directory-digest", "directory identity mismatch"),
        ("managed-root-escape", "outside Harness managed store"),
        ("wrong-platform", "toolchain profile platform mismatch"),
        ("java-relationship", "Java home identity mismatch"),
        ("maven-relationship", "Maven home identity mismatch"),
        ("repository-layout", "Maven repository identity mismatch"),
    ],
)
def test_profile_binding_fails_closed(profile_harness: ProfileHarness, mutation: str, message: str):
    profile, binding = profile_harness.mutated(mutation)
    with pytest.raises(ValueError, match=message):
        verify_profile_toolchain(profile_harness.root, profile, binding)
```

Add an environment test that sets `PATH` to a directory containing valid-looking
`rg`, omits the `rg` binding, and expects `capability pack toolchain binding is incomplete`.

- [ ] **Step 3: Run profile tests to verify RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q tests/test_toolchain_profile.py
```

Expected: FAIL because the loading and verification interfaces are absent.

- [ ] **Step 4: Implement immutable profile and binding loading**

In `toolchain_profile.py`:

```python
TOOLCHAIN_REGISTRY_SOURCE = "core/registries/capability-validator-toolchains.yaml"
TOOLCHAIN_REGISTRY_SCHEMA = "core/schemas/capability-validator-toolchain-registry.schema.json"
TOOLCHAIN_BINDING_SCHEMA = "core/schemas/capability-validator-toolchain-binding.schema.json"
MANAGED_CACHE_RELATIVE = Path(".worktrees/.capability-pack-cache")


def profile_digest(profile: Mapping[str, Any]) -> str:
    return "sha256:" + sha256_bytes(canonical_json_bytes(profile))


def binding_path(repository_root: Path, profile_id: str) -> Path:
    safe = hashlib.sha256(profile_id.encode("utf-8")).hexdigest()
    return Path(repository_root) / MANAGED_CACHE_RELATIVE / "bindings" / f"{safe}.json"
```

Validate the complete registry, require exactly one matching profile, compare the
computed canonical digest to `expected_digest` in `load_toolchain_profile()`, and
return the same frozen profile plus computed digest without an expected value from
`find_toolchain_profile()` for provisioning/status. Freeze nested values, validate the
host-local binding, and compute `witness_digest` over the validated binding including
its absolute paths. Reject symlink/non-regular binding files and before/after binding
file mutation. For each `HARNESS_MANAGED_STORE` command, resolve exactly one artifact
and compare its canonical digest to the command's `artifactDigest`; artifact registry
drift fails before binding or Gate execution.

- [ ] **Step 5: Move the single measurement implementation and verify relationships**

Move `_directory_identity_digest` and `VerifiedToolchain` to the new module, extend
command reads with before/after `(st_dev, st_ino, st_mode, st_size, st_mtime_ns)`
checks, then dispatch relationship/environment construction through the canonical
`environmentAdapter`. For `JAVA_MAVEN_OFFLINE_V1`, enforce:

```python
if java.parent.parent != directories["javaHome"] or javac.parent.parent != directories["javaHome"]:
    raise ValueError("capability pack validator Java home identity mismatch")
if mvn.parent.parent != directories["mavenHome"]:
    raise ValueError("capability pack validator Maven home identity mismatch")
if repository.name != "repository" or repository.parent.name != ".m2":
    raise ValueError("capability pack validator Maven repository identity mismatch")
```

For `HARNESS_MANAGED_STORE`, require
`path.is_relative_to(repository_root / MANAGED_CACHE_RELATIVE / "store")`; for
`HARNESS_MANAGED_CACHE`, require containment under `MANAGED_CACHE_RELATIVE`. Apply
both checks after strict normalization. Construct `PATH`, `HOME`, `JAVA_HOME`,
`LANG`, and `LC_ALL` only from verified paths plus the existing fixed system Git
path entries.

- [ ] **Step 6: Dispatch legacy and profile contracts in Pack validation**

Keep the legacy verification body behavior-identical under a renamed
`_verify_legacy_validator_toolchain()`. Implement:

```python
def _verify_validator_toolchain(repository_root: Path, registration: Mapping[str, Any]) -> VerifiedToolchain:
    contract = registration["validator"].get("environmentContract", "SANITIZED")
    if contract in {"SANITIZED", "REGISTERED_TOOLCHAIN_OFFLINE_CACHE"}:
        return _verify_legacy_validator_toolchain(registration)
    if contract != "MANAGED_TOOLCHAIN_PROFILE":
        raise ValueError("capability pack validator environment contract is unsupported")
    reference = registration["validator"]["toolchainProfile"]
    profile = load_toolchain_profile(repository_root, reference["profileId"], reference["profileDigest"])
    binding = load_toolchain_binding(repository_root, reference["profileId"])
    return verify_profile_toolchain(repository_root, profile, binding)
```

Pass `repository_root` into pre/post verification and retain the verified binding
witness in the returned object.

- [ ] **Step 7: Run GREEN and legacy regression**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q tests/test_toolchain_profile.py tests/test_capability_pack_registry.py -k 'toolchain or candidate_gate_uses_registered_host_home'
```

Expected: PASS with both contracts exercising the same directory closure checks.

- [ ] **Step 8: Commit the attestation slice**

```bash
git add src/evolution_harness/toolchain_profile.py src/evolution_harness/capability_pack_registry.py tests/test_toolchain_profile.py tests/test_capability_pack_registry.py
git commit -m "feat(pack): 分离工具链 Profile 与宿主 Binding 验证"
```

### Task 3: Add explicit managed-artifact provisioning and CLI

**Files:**
- Create: `src/evolution_harness/toolchain_provisioning.py`
- Create: `tests/test_toolchain_provisioning.py`
- Modify: `src/evolution_harness/cli.py`
- Modify: `tests/test_assurance_cli.py`

**Interfaces:**
- Consumes: Task 2 `find_toolchain_profile()`, `find_toolchain_artifact()`, `load_toolchain_binding()`, `binding_path()`,
  `verify_profile_toolchain()`, managed-store boundary, and Task 1 artifact manifest.
- Produces:

```python
def plan_toolchain_provision(
    repository_root: Path,
    profile_id: str,
    explicit_bindings: Mapping[str, Path],
    archive_path: Path | None,
) -> dict[str, Any]: ...

def provision_toolchain(
    repository_root: Path,
    profile_id: str,
    explicit_bindings: Mapping[str, Path],
    archive_path: Path | None,
) -> dict[str, Any]: ...

def toolchain_status(repository_root: Path, profile_id: str) -> dict[str, Any]: ...
```

CLI:

```text
harness toolchain status --profile PROFILE_ID [--format text|json]
harness toolchain provision --profile PROFILE_ID [--archive ABSOLUTE_PATH]
  --bind NAME=ABSOLUTE_PATH ... [--apply] [--format text|json]
```

Without `--apply`, provision is a pure dry-run and performs no network or file write.
With `--apply`, omission of `--archive` explicitly authorizes download from the
profile artifact's fixed HTTPS `sourceUri`.

- [ ] **Step 1: Write RED archive-security and transaction tests**

Build small tar.gz fixtures in memory and parameterize:

```python
@pytest.mark.parametrize(
    ("member_kind", "message"),
    [
        ("parent-traversal", "archive member path is unsafe"),
        ("absolute-path", "archive member path is unsafe"),
        ("symlink", "archive contains link or special file"),
        ("hardlink", "archive contains link or special file"),
        ("fifo", "archive contains link or special file"),
        ("duplicate-normalized", "archive member path is duplicated"),
    ],
)
def test_provision_rejects_unsafe_archive(provision_harness: ProvisionHarness, member_kind: str, message: str):
    archive = provision_harness.archive(member_kind)
    with pytest.raises(ValueError, match=message):
        provision_toolchain(
            provision_harness.root,
            provision_harness.profile_id,
            provision_harness.explicit_bindings,
            archive,
        )
    assert not provision_harness.binding_path.exists()
    assert not provision_harness.published_root.exists()
```

Add separate tests for wrong archive SHA-256, wrong extracted `rg` SHA-256,
interrupted `os.replace`, binding-write failure after store publication, idempotent
same-content reprovisioning, and conflict at an existing content-addressed store
path. Store publication may remain after a binding-write failure because it is
immutable/unreferenced; no valid binding may be published.

- [ ] **Step 2: Write RED CLI dry-run/apply/offline tests**

Use `cli.main([...])` with `capsys` and assert:

```python
def test_toolchain_provision_dry_run_performs_no_io(cli_harness: CliHarness, monkeypatch: pytest.MonkeyPatch, capsys):
    monkeypatch.setattr("evolution_harness.toolchain_provisioning.urlopen", lambda *args, **kwargs: pytest.fail("network used"))
    result = main([
        "--repository-root", str(cli_harness.root),
        "toolchain", "provision",
        "--profile", cli_harness.profile_id,
        *cli_harness.bind_arguments,
        "--format", "json",
    ])
    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["data"]["apply"] is False
    assert not cli_harness.binding_path.exists()
```

Add a test that candidate validation with no binding performs no network call and
returns the deterministic message containing:

```text
harness toolchain provision --profile toolchain-profile:test:darwin-arm64:v1 --apply
```

- [ ] **Step 3: Run provisioning tests to verify RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q tests/test_toolchain_provisioning.py tests/test_assurance_cli.py -k toolchain
```

Expected: FAIL because the module and CLI command do not exist.

- [ ] **Step 4: Implement safe acquisition and extraction**

Use `urllib.request.urlopen()` only inside `provision_toolchain()` when no archive is
supplied. Require HTTPS, a 30-second timeout, a 64 MiB maximum response, and exact
archive SHA-256 before opening the tar. Inspect every `TarInfo` before extraction:

```python
def _safe_member_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("toolchain archive member path is unsafe")
    return path


for member in archive.getmembers():
    relative = _safe_member_name(member.name)
    normalized = unicodedata.normalize("NFC", relative.as_posix()).casefold()
    if normalized in seen:
        raise ValueError("toolchain archive member path is duplicated")
    seen.add(normalized)
    if not (member.isdir() or member.isfile()):
        raise ValueError("toolchain archive contains link or special file")
```

Extract regular files by reading `archive.extractfile(member)` and writing through a
new file opened with exclusive creation under a `tempfile.mkdtemp()` root. Do not use
`extractall()`. Enforce a 128 MiB total extracted-byte limit and compare each member's
actual byte count to its declared size.

- [ ] **Step 5: Implement read-only atomic publication and binding transaction**

Publish to:

```text
.worktrees/.capability-pack-cache/store/{artifact-id-sha256}/{archive-sha256}/
```

Verify the extracted `rg` file against the profile command digest, chmod files
`0555` for executables and `0444` otherwise, chmod directories `0555`, remeasure,
and use `os.replace(temp_root, final_root)` only when the final root is absent. If it
exists, compare its complete directory identity and reuse only on equality.

Merge the managed `rg` path with the seven explicit command/directory bindings,
validate the complete binding and `VerifiedToolchain`, then write canonical JSON to
a same-directory temporary file, fsync, chmod `0444`, and atomically replace the
binding path. Return profile ID/digest, artifact ID/archive digest, binding witness,
resolved paths, and `apply: True`; never return a successful result before runtime
verification passes.

- [ ] **Step 6: Add CLI routing and stable failures**

Add parser entries and dispatch before Registry commands:

```python
p = sub.add_parser("toolchain")
s = p.add_subparsers(dest="action", required=True)
q = s.add_parser("status")
q.add_argument("--profile", required=True)
_add_format(q)
q = s.add_parser("provision")
q.add_argument("--profile", required=True)
q.add_argument("--archive")
q.add_argument("--bind", action="append", default=[])
q.add_argument("--apply", action="store_true")
_add_format(q)
```

Parse each binding with `partition("=")`, reject duplicate/unknown names and
non-absolute paths, and emit through the existing `harness-cli/v1` envelope.

- [ ] **Step 7: Run GREEN and CLI regression**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q tests/test_toolchain_provisioning.py tests/test_assurance_cli.py
```

Expected: PASS; existing CLI envelopes and exit codes remain unchanged.

- [ ] **Step 8: Commit the provisioning slice**

```bash
git add src/evolution_harness/toolchain_provisioning.py src/evolution_harness/cli.py tests/test_toolchain_provisioning.py tests/test_assurance_cli.py
git commit -m "feat(pack): 增加受管工具链制品 Provisioning"
```

### Task 4: Propagate canonical profile identity and bind the session witness

**Files:**
- Modify: `core/schemas/capability-lock.schema.json`
- Modify: `core/schemas/runtime-projection-manifest.schema.json`
- Modify: `src/evolution_harness/capability_pack_registry.py`
- Modify: `src/evolution_harness/project.py`
- Modify: `tests/test_external_pack_verification_session.py`
- Modify: `tests/test_lock_enforcement.py`
- Modify: `tests/test_project_state.py`
- Modify: `tests/test_resolver.py`
- Modify: `tests/test_projection.py`
- Modify: `tests/test_projection_install.py`

**Interfaces:**
- Consumes: `validator.toolchainProfile`, verified profile digest, and binding witness
  from Tasks 1–2.
- Produces: locator-free canonical Registry/lock/resolution/projection identity and a
  session-only binding witness check. Public return shapes remain dictionaries; the
  only new canonical field is the mutually exclusive `toolchainProfile` alternative.

- [ ] **Step 1: Write RED byte-equivalence tests for two host bindings**

Create two Harness fixture roots with identical source/profile data and identical
tool bytes under different absolute paths. Build Registry, lock, resolved context,
projection pack, and install dry-run for each root. Normalize only the existing
source discovery locator before comparing the already-defined locator-free outputs;
do not remove any toolchain field in the test:

```python
def test_profile_binding_relocation_preserves_all_canonical_outputs(profile_project_pair: ProfileProjectPair):
    first = profile_project_pair.build(profile_project_pair.first_binding_root)
    second = profile_project_pair.build(profile_project_pair.second_binding_root)
    assert first.registry_bytes == second.registry_bytes
    assert first.lock_bytes == second.lock_bytes
    assert first.resolution_bytes == second.resolution_bytes
    assert first.projection_bytes == second.projection_bytes
    assert first.install_plan_bytes == second.install_plan_bytes
    for payload in (first.registry_bytes, first.lock_bytes, first.resolution_bytes, first.projection_bytes):
        assert str(profile_project_pair.first_binding_root).encode() not in payload
        assert str(profile_project_pair.second_binding_root).encode() not in payload
        assert b"ChatGPT.app" not in payload
```

Also assert source/resource digests, registration fingerprint, source revision,
exact lock fingerprint, resolver selection/reasons, and projection file bytes are
equal field-by-field.

- [ ] **Step 2: Write RED identity-mutation and session-witness tests**

Extend the existing Pack key parameterization with `profile-id`, `profile-digest`,
`profile-platform`, `profile-command-digest`, `profile-directory-digest`, and
`managed-artifact-manifest-digest`. Each
mutation must change the Pack key or fail profile loading before a Gate.

Add:

```python
def test_open_session_rejects_binding_relocation_but_fresh_session_revalidates(profile_pack_harness: ProfilePackHarness):
    with CapabilityVerificationSession(
        profile_pack_harness.root,
        allowed_capability_ids={profile_pack_harness.capability_id},
    ) as session:
        get_registered_capability_pack(
            profile_pack_harness.root,
            profile_pack_harness.capability_id,
            verification_session=session,
        )
        profile_pack_harness.write_binding(profile_pack_harness.second_root)
        with pytest.raises(ValueError, match="toolchain binding changed during verification session"):
            get_registered_capability_pack(
                profile_pack_harness.root,
                profile_pack_harness.capability_id,
                verification_session=session,
            )
    with CapabilityVerificationSession(
        profile_pack_harness.root,
        allowed_capability_ids={profile_pack_harness.capability_id},
    ) as fresh:
        get_registered_capability_pack(
            profile_pack_harness.root,
            profile_pack_harness.capability_id,
            verification_session=fresh,
        )
        assert fresh.stats.full_candidate_gate_count == 1
        assert fresh.stats.toolchain_directory_digest_count == 6
```

Retain `test_public_lookup_without_session_still_runs_one_full_gate` and add an
assertion that neither the managed store nor binding file contains a serialized Gate
result, verified Pack, session token, or reuse counter.

- [ ] **Step 3: Run canonical/session tests to verify RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q tests/test_external_pack_verification_session.py tests/test_lock_enforcement.py tests/test_project_state.py tests/test_resolver.py tests/test_projection.py tests/test_projection_install.py -k 'toolchain or profile or external'
```

Expected: FAIL because profile identity is not propagated and the binding witness is
not rechecked.

- [ ] **Step 4: Add exact schema alternatives without changing v2 algorithms**

In both lock and projection schemas, define:

```json
"toolchainProfileIdentity": {
  "type": "object",
  "required": ["profileId", "profileDigest"],
  "properties": {
    "profileId": {"type": "string", "pattern": "^toolchain-profile:[a-z0-9._:-]+$"},
    "profileDigest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
  },
  "additionalProperties": false
}
```

Use validator-level `oneOf` so legacy `toolchain` and new `toolchainProfile` are
mutually exclusive and neither is required for `SANITIZED`. Do not change
`capability_lock_fingerprint()` or `capability_lock_v2_source_revision()`.

- [ ] **Step 5: Update canonical registration/key construction**

Set `CAPABILITY_PACK_VALIDATION_ABI = "v2"` because profile/binding key semantics
changed, and extend the existing ABI-mutation session test to prove a v1 result is
never reused. In `_canonical_registration_identity_record()` and
`_pack_verification_key()`, carry
exactly one of the two fields:

```python
**(
    {"toolchainProfile": _thaw(validator["toolchainProfile"])}
    if "toolchainProfile" in validator
    else {}
),
```

Do not load or insert a binding here. The key includes profile ID/digest plus the
existing normalized platform allowlist. Profile loading later proves that the
referenced digest maps to the expected complete profile.

- [ ] **Step 6: Update lock and projection propagation**

In `_external_lock_source()`, copy `toolchainProfile` exactly as registration
identity. Existing resolver and projection propagation should then remain generic;
adjust only explicit field builders/assertions that currently assume `toolchain`.
Assert exact equality:

```python
assert locked["validatorIdentity"]["toolchainProfile"] == registration["validator"]["toolchainProfile"]
assert resolved["validatorIdentity"] == locked["validatorIdentity"]
assert projected["validatorIdentity"] == locked["validatorIdentity"]
```

- [ ] **Step 7: Recheck binding witness on verified Pack reuse**

Add the binding-file witness to `VerifiedToolchain`. During
`VerifiedCapabilityPack.recheck()`, reload only the small binding record, validate
it, and compare `witness_digest`; do not recursively rehash the toolchain on every
reuse. Mismatch calls the existing session poison path and raises the stable error.
The next new session performs the complete pre/post measurement.

- [ ] **Step 8: Run GREEN focused regression**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q tests/test_toolchain_profile.py tests/test_external_pack_verification_session.py tests/test_lock_enforcement.py tests/test_project_state.py tests/test_resolver.py tests/test_projection.py tests/test_projection_install.py
```

Expected: PASS; relocation equivalence passes and legacy exact-fingerprint fixtures
remain unchanged.

- [ ] **Step 9: Commit canonical propagation**

```bash
git add core/schemas/capability-lock.schema.json core/schemas/runtime-projection-manifest.schema.json src/evolution_harness/capability_pack_registry.py src/evolution_harness/project.py tests/test_external_pack_verification_session.py tests/test_lock_enforcement.py tests/test_project_state.py tests/test_resolver.py tests/test_projection.py tests/test_projection_install.py
git commit -m "fix(pack): 从 canonical 身份排除宿主工具路径"
```

### Task 5: Migrate the Java registration and neutral generated artifacts once

**Files:**
- Modify: `core/registries/capability-validator-toolchains.yaml`
- Modify: `core/registries/capability-packs.yaml`
- Modify: `generated/registries/capability-pack-registry.json`
- Modify: `examples/java-engineering-standard-registration-fixture/.agent-evolution/capabilities.lock.yaml`
- Modify: `generated/projections/chatgpt/java-engineering-standard-registration-fixture/**`
- Modify: `generated/projections/codex/java-engineering-standard-registration-fixture/**`
- Modify: `tests/test_capability_pack_registry.py`
- Modify: `tests/test_java_engineering_standard_registration_fixture.py`

**Interfaces:**
- Consumes: all GREEN synthetic behavior from Tasks 1–4 and the current immutable
  Java Pack commit/tree/content/validator identity.
- Produces: canonical Java profile
  `toolchain-profile:java-engineering-standard:darwin-arm64:v1`, managed official
  ripgrep binding, registration fingerprint
  `sha256:cd5bbf5e763b38c96fccbf4c5a9357497c82e10fbf2272e4693fbcd2f63a708b`,
  neutral fixture source revision
  `content-sha256:5dca53baa96b90b7786f9d1546d191d60e5c2dfd73a734c91fd9367f02ac366b`,
  and neutral fixture lock fingerprint
  `sha256:90cf64c1425e75240e1225bea8e1d1f574420d06ee7bff9955e794ea6c20fb73`.

- [ ] **Step 1: Add RED exact-migration assertions**

Update the Java fixture tests before the source migration:

```python
PROFILE_ID = "toolchain-profile:java-engineering-standard:darwin-arm64:v1"
PROFILE_DIGEST = "sha256:c852142343ea97aef6d3a555e5500ecb633baf1a23d846d7bbe72a8bcf5e4490"
REGISTRATION_FINGERPRINT = "sha256:cd5bbf5e763b38c96fccbf4c5a9357497c82e10fbf2272e4693fbcd2f63a708b"
LOCK_FINGERPRINT = "sha256:90cf64c1425e75240e1225bea8e1d1f574420d06ee7bff9955e794ea6c20fb73"


def test_java_registration_uses_locator_free_managed_profile():
    registration = _java_registration()
    assert registration["validator"]["environmentContract"] == "MANAGED_TOOLCHAIN_PROFILE"
    assert registration["validator"]["toolchainProfile"] == {
        "profileId": PROFILE_ID,
        "profileDigest": PROFILE_DIGEST,
    }
    assert "toolchain" not in registration["validator"]
    assert b"ChatGPT.app" not in canonical_json_bytes(_canonical_registry_entry(registration))
```

Assert exact registration/lock fingerprints and the same `toolchainProfile` in both
runtime projection manifests.

- [ ] **Step 2: Run migration assertions to verify RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q tests/test_capability_pack_registry.py tests/test_java_engineering_standard_registration_fixture.py -k 'java or profile'
```

Expected: FAIL because the Java registration and generated neutral artifacts remain
legacy/path-bearing.

- [ ] **Step 3: Add the exact Java profile**

Add a profile with these canonical command identities:

```yaml
schemaVersion: capability-validator-toolchain-profile/v1
profileId: toolchain-profile:java-engineering-standard:darwin-arm64:v1
environmentAdapter: JAVA_MAVEN_OFFLINE_V1
platform: {os: darwin, architecture: arm64}
commands:
  ruby: {artifactId: artifact:host-ruby:darwin-arm64, fileName: ruby, sha256: sha256:4694e9689687f3c2d30339c3d444a7c3f3eb39d68c7e1d9e37194ece9fe15512, bindingPolicy: HOST_ATTESTED}
  rg: {artifactId: artifact:ripgrep:15.2.0:darwin-arm64, artifactDigest: sha256:bfa2614eba25313624c604d16c6c727f3b243e5453b5b261321858f7eee75512, fileName: rg, sha256: sha256:a326a1fb48074202e9ad41e4cd1e389eeea372c8c6f7d7e80da81176d5d9430e, bindingPolicy: HARNESS_MANAGED_STORE}
  java: {artifactId: artifact:temurin-21:darwin-arm64, fileName: java, sha256: sha256:1069d726eae63d510d2983a2a4c7869f14db200605685c98117d9a27aaa5270f, bindingPolicy: HOST_ATTESTED}
  javac: {artifactId: artifact:temurin-21:darwin-arm64, fileName: javac, sha256: sha256:68411beb17069d4a26f54fee148c2540251f42368f991d80a8087dcfa4c90a39, bindingPolicy: HOST_ATTESTED}
  mvn: {artifactId: artifact:maven-3.9.16:java-pack-cache, fileName: mvn, sha256: sha256:f9381d0cb98abaaf9592dae421eddc497e84ed9bfb723b84c111d1350863c3a2, bindingPolicy: HARNESS_MANAGED_CACHE}
directories:
  javaHome: {artifactId: artifact:temurin-21:darwin-arm64, sha256: sha256:a30ae0a3178be8aa787ecdb850d150f529e811e9b712c3bfcdbdfc2fdf91fd90, bindingPolicy: HOST_ATTESTED}
  mavenHome: {artifactId: artifact:maven-3.9.16:java-pack-cache, sha256: sha256:5447e4224f32bb94d26420a62ee18a39ccef3b2dfe62c7739c36c313991c2286, bindingPolicy: HARNESS_MANAGED_CACHE}
  mavenRepository: {artifactId: artifact:java-pack-offline-repository:v1, sha256: sha256:5187065b1bb4bf7d0a139cc97b3fb19213ed3ee713a15d83b525760ed3d520fe, bindingPolicy: HARNESS_MANAGED_CACHE}
relationships:
  javaHomeCommands: [java, javac]
  mavenHomeCommand: mvn
  mavenRepositoryLayout: DOT_M2_REPOSITORY
```

Assert `profile_digest(profile)` equals the fixed `PROFILE_DIGEST` before changing
the registration. A mismatch is a plan/schema divergence and must stop migration.

- [ ] **Step 4: Provision the managed artifact and complete host binding**

Run the dry-run first, then apply. The apply call is the only network-authorized
operation if `/private/tmp/ripgrep-15.2.0-aarch64-apple-darwin.tar.gz` is absent:

```bash
./harness toolchain provision --profile toolchain-profile:java-engineering-standard:darwin-arm64:v1 --bind ruby=/opt/homebrew/Cellar/ruby@3.4/3.4.10/bin/ruby --bind java=/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home/bin/java --bind javac=/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home/bin/javac --bind mvn=/Users/yuzhuangzhuang/Projects/omini-harness/.worktrees/.capability-pack-cache/java-engineering-standard/home/.m2/wrapper/dists/apache-maven-3.9.16/56ba1f9f/bin/mvn --bind javaHome=/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home --bind mavenHome=/Users/yuzhuangzhuang/Projects/omini-harness/.worktrees/.capability-pack-cache/java-engineering-standard/home/.m2/wrapper/dists/apache-maven-3.9.16/56ba1f9f --bind mavenRepository=/Users/yuzhuangzhuang/Projects/omini-harness/.worktrees/.capability-pack-cache/java-engineering-standard/home/.m2/repository --format json
./harness toolchain provision --profile toolchain-profile:java-engineering-standard:darwin-arm64:v1 --archive /private/tmp/ripgrep-15.2.0-aarch64-apple-darwin.tar.gz --bind ruby=/opt/homebrew/Cellar/ruby@3.4/3.4.10/bin/ruby --bind java=/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home/bin/java --bind javac=/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home/bin/javac --bind mvn=/Users/yuzhuangzhuang/Projects/omini-harness/.worktrees/.capability-pack-cache/java-engineering-standard/home/.m2/wrapper/dists/apache-maven-3.9.16/56ba1f9f/bin/mvn --bind javaHome=/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home --bind mavenHome=/Users/yuzhuangzhuang/Projects/omini-harness/.worktrees/.capability-pack-cache/java-engineering-standard/home/.m2/wrapper/dists/apache-maven-3.9.16/56ba1f9f --bind mavenRepository=/Users/yuzhuangzhuang/Projects/omini-harness/.worktrees/.capability-pack-cache/java-engineering-standard/home/.m2/repository --apply --format json
./harness toolchain status --profile toolchain-profile:java-engineering-standard:darwin-arm64:v1 --format json
```

Expected: dry-run performs no write; apply reports archive digest
`3750b2e93f37e0c692657da574d7019a101c0084da05a790c83fd335bad973e4`,
command digest `a326a1fb48074202e9ad41e4cd1e389eeea372c8c6f7d7e80da81176d5d9430e`,
and status `VERIFIED`. If the temp archive is absent, omit `--archive` only after the
execution environment grants the explicit download approval.

- [ ] **Step 5: Replace only the Java registration toolchain identity**

Keep commit/tree/content/validator/history/timeout unchanged. Replace:

```yaml
environmentContract: MANAGED_TOOLCHAIN_PROFILE
toolchainProfile:
  profileId: toolchain-profile:java-engineering-standard:darwin-arm64:v1
  profileDigest: sha256:c852142343ea97aef6d3a555e5500ecb633baf1a23d846d7bbe72a8bcf5e4490
```

Remove the legacy `toolchain` block. Run the Java candidate Gate through Registry
build and assert exact registration fingerprint before generating downstream files.

- [ ] **Step 6: Regenerate Registry, neutral lock, and both neutral projections in one session**

Use one explicit session so the real Java Gate count remains one:

```python
root = Path.cwd()
project = root / "examples/java-engineering-standard-registration-fixture"
with CapabilityVerificationSession(root, allowed_capability_ids={JAVA_CAPABILITY_ID}) as session:
    build_capability_pack_registry(root, write=True, verification_session=session)
    build_capability_lock(root, project, write=True, verification_session=session)
    for runtime in ("CHATGPT", "CODEX"):
        resolved = resolve_design_context(
            root,
            project,
            intent="architecture-review",
            topic="neutral-java-pilot-readiness",
            requested_output="review findings",
            runtime=runtime,
            verification_session=session,
        )
        build_projection_pack(
            root,
            project,
            resolved,
            runtime=runtime,
            verification_session=session,
        )
    stats = session.stats
    assert stats.full_candidate_gate_count == 1
    assert stats.isolated_checkout_count == 1
    assert stats.toolchain_directory_digest_count == 6
```

Run the script with the repository virtual environment and `PYTHONPATH=src`. Inspect
`git status --short`; reject any changed Pay-Nexus shadow projection, external Pack
source, or file outside the declared Task 5 set.

- [ ] **Step 7: Run GREEN Java migration regression**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q tests/test_capability_pack_registry.py tests/test_java_engineering_standard_registration_fixture.py tests/test_project_state.py tests/test_resolver.py tests/test_projection.py tests/test_projection_install.py
```

Expected: PASS; both neutral projection manifests carry the profile reference, all
45 resource bytes/digests remain unchanged, and install dry-run remains 45 actions.

- [ ] **Step 8: Commit the one-time canonical migration**

```bash
git add core/registries/capability-validator-toolchains.yaml core/registries/capability-packs.yaml generated/registries/capability-pack-registry.json examples/java-engineering-standard-registration-fixture/.agent-evolution/capabilities.lock.yaml generated/projections/chatgpt/java-engineering-standard-registration-fixture generated/projections/codex/java-engineering-standard-registration-fixture tests/test_capability_pack_registry.py tests/test_java_engineering_standard_registration_fixture.py
git commit -m "fix(pack): 迁移 Java Validator 到受管工具链 Profile"
```

### Task 6: Close focused security, compatibility, and performance evidence

**Files:**
- Modify: `tests/test_toolchain_profile.py`
- Modify: `tests/test_toolchain_provisioning.py`
- Modify: `tests/test_external_pack_verification_session.py`
- Modify: `tests/test_pay_nexus_java_capability_adoption_pilot.py` only if a deterministic counter assertion is required; do not recombine split node IDs.
- No source file change is permitted after this task starts without returning to the relevant RED task.

**Interfaces:**
- Consumes: stable implementation/migration candidate from Tasks 1–5.
- Produces: complete deterministic negative matrix, unchanged business semantics,
  candidate-Gate/directory-digest counters, and an actual post-change benchmark
  receipt. This task does not create a Pay-Nexus repository candidate.

- [ ] **Step 1: Complete mutation coverage at every linearization boundary**

Parameterize binding file, profile registry, managed `rg`, Java command, Maven home,
and Maven repository mutation at these hooks:

```text
before binding read
during binding read
after binding read / before pre-Gate measurement
during command read
during directory hashing
after pre-Gate measurement / before Gate
during Gate
after Gate / before post-Gate publication
after successful session / before verified Pack reuse
```

For each hook assert: stable error, session state `POISONED`, no verified Pack
publication, no reuse hit, cleanup attempted, and a fresh session either fails on the
still-mutated content or runs exactly one Gate after restoration.

- [ ] **Step 2: Run the complete focused mutation matrix**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q tests/test_toolchain_profile.py tests/test_toolchain_provisioning.py tests/test_external_pack_verification_session.py
```

Expected: PASS with no skipped mutation case.

- [ ] **Step 3: Verify exact unchanged semantic outputs**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q tests/test_capability_pack_registry.py tests/test_lock_enforcement.py tests/test_project_state.py tests/test_resolver.py tests/test_projection.py tests/test_projection_install.py tests/test_java_engineering_standard_registration_fixture.py tests/test_pay_nexus_java_capability_adoption_pilot.py
```

Expected: PASS. Review failures as semantic evidence; do not update golden values
unless the only difference is the approved one-time profile migration.

- [ ] **Step 4: Run and record the real post-change Pack E2E benchmark**

Collect stable node IDs, then run the complete pilot file under one receipt:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest --collect-only -q tests/test_pay_nexus_java_capability_adoption_pilot.py
/usr/bin/time -p /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q tests/test_pay_nexus_java_capability_adoption_pilot.py > /private/tmp/harness-toolchain-profile-post-benchmark.log 2>&1
```

Immediately record the shell exit code in
`/private/tmp/harness-toolchain-profile-post-benchmark.exit`. The receipt must show:

```text
full_candidate_gate_count <= 2, target 1
toolchain_directory_digest_count <= 12, target 6
isolated_checkout_count <= 2, target 1
all collected node IDs passed
```

Compare wall time to the existing interrupted lower-bound receipt
`/private/tmp/harness-phase3d-bd128c71545c-full-regression.log`: original elapsed
was greater than 3,604 seconds and stopped with 644 passed while inside the pilot.
If the new complete equivalent pilot is below 1,081.2 seconds, report a conservative
wall-time reduction greater than 70%; otherwise report the measured reduction and do
not claim the target.

- [ ] **Step 5: Confirm App lifecycle independence on the real candidate**

Run:

```bash
rg -n "/Applications/ChatGPT.app|ChatGPT.app/Contents/Resources/rg" core/registries/capability-packs.yaml generated/registries/capability-pack-registry.json examples/java-engineering-standard-registration-fixture/.agent-evolution/capabilities.lock.yaml generated/projections/chatgpt/java-engineering-standard-registration-fixture generated/projections/codex/java-engineering-standard-registration-fixture
./harness toolchain status --profile toolchain-profile:java-engineering-standard:darwin-arm64:v1 --format json
```

Expected: `rg` returns exit 1 with no matches; status is `VERIFIED` and its resolved
`rg` path is under the managed store, not an App bundle. Do not rename, modify, or
remove ChatGPT.app as a test action.

- [ ] **Step 6: Commit only test assertions if Step 1 required changes**

If Task 6 changed tests, commit them; otherwise record the clean worktree without an
empty commit:

```bash
git add tests/test_toolchain_profile.py tests/test_toolchain_provisioning.py tests/test_external_pack_verification_session.py tests/test_pay_nexus_java_capability_adoption_pilot.py
git commit -m "test(pack): 固化工具链解耦与 TOCTOU 负向矩阵"
```

### Task 7: Run complete Harness gates and fix the R2 candidate

**Files:**
- No planned source changes.
- Receipts: `/private/tmp/harness-toolchain-profile-fast.log`, `/private/tmp/harness-toolchain-profile-integration.log`, `/private/tmp/harness-toolchain-profile-pack-e2e.log`, `/private/tmp/harness-toolchain-profile-full.log`.

**Interfaces:**
- Consumes: clean candidate and focused evidence from Task 6.
- Produces: complete tiered/full regression receipts, generated-artifact verification,
  fixed Candidate/Parent/Tree, and independent xhigh verdict.

- [ ] **Step 1: Run generated/schema assurance**

Run:

```bash
./harness registry build --check --format json
./harness validate --check-generated --project examples/java-engineering-standard-registration-fixture --format json
git diff --check
```

Expected: Registry check PASS, structural Gate PASS, and no whitespace error.

- [ ] **Step 2: Run each cost tier with separate stdout/stderr and exit receipts**

Run each command without hiding its exit code:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q -m fast
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q -m integration
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q -m pack_e2e
```

Redirect each complete command's stdout/stderr to its named receipt and save the
actual exit code in the same basename with `.exit`. Expected: all three exit 0. An
empty marker selection is not PASS; the receipt must list collected/passed counts.

- [ ] **Step 3: Run the complete regression**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src /Users/yuzhuangzhuang/Projects/omini-harness/.venv/bin/python -m pytest -q
```

Write complete stdout/stderr to `/private/tmp/harness-toolchain-profile-full.log`
and the true exit code to `.exit`. Expected: exit 0 and no failed/error/interrupted
summary. A SIGINT or partial passed count is not a Gate PASS.

- [ ] **Step 4: Verify the exact candidate and clean worktree**

Run:

```bash
git status --short --branch
git diff --check HEAD^
git rev-parse HEAD HEAD^ HEAD^{tree}
git diff-tree --no-commit-id --name-status -r HEAD
```

Expected: no uncommitted/untracked files, all changed files inside the plan's
Harness-only WriteSet, and fixed Candidate/Parent/Tree recorded verbatim.

- [ ] **Step 5: Request one independent R2 deep review**

Use `superpowers:requesting-code-review` and dispatch exactly one
`deep_reviewer / xhigh` against the fixed Candidate/Parent/Tree. The prompt includes
the approved spec/plan, Exact WriteSet, focused/full receipts, benchmark receipt,
legacy compatibility, canonical locator exclusion, managed-artifact provenance,
directory/TOCTOU behavior, and the two evidence-only NO-GO commits.

Expected verdict: GO with no P0/P1. Any P0/P1 or requested code change invalidates
the fixed candidate; return to the owning RED task, make a new commit, rerun affected
gates, then full regression and a fresh fixed-candidate review.

### Task 8: Prepare the downstream migration handoff without changing Pay-Nexus

**Files:**
- No repository writes.

**Interfaces:**
- Consumes: fixed Harness GO candidate and exact one-time Java registration/neutral
  fixture migration identities.
- Produces: a user-facing handoff containing Harness Candidate/Parent/Tree, profile
  and registration fingerprints, provisioning/status evidence, benchmark result,
  residual risks, and the explicit downstream authorization boundary.

- [ ] **Step 1: Report exact completion layers**

Report separately:

```text
Harness design: committed
Harness implementation: fixed candidate and reviewed GO
Harness main landing: not performed
Harness push/release/deploy: not performed
Pay-Nexus lock/projection migration: not performed and not authorized by this plan
Pay-Nexus business/runtime Authority: unchanged
ChatGPT App lifecycle dependency after Harness migration: removed
```

- [ ] **Step 2: Propose the separate consumer plan**

The next plan, only after explicit Pay-Nexus authorization, uses a Pay-Nexus isolated
worktree and contains only its registration/lock/projection migration plus the fixed
before/after benchmark. It does not modify Java Pack content/validator, Pay
Authority, business permissions, or Harness Core.

- [ ] **Step 3: Stop at the authorization boundary**

Do not merge, push, release, deploy, modify Pay-Nexus, or clean historical worktrees.
Offer the user the exact choices: review/land the Harness candidate locally,
authorize the Pay-Nexus consumer migration plan, or retain the candidate without
further action.
