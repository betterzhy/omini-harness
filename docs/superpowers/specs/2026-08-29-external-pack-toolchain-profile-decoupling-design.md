# External Pack Toolchain Profile Decoupling Design

## Status and decision

This specification records the user-approved R2 Harness Core design for removing
host-application paths from External Capability Pack validator identity. It is a
design artifact, not implementation, a fixed candidate, a Gate receipt, a merge,
a release, or downstream adoption authorization.

Implementation starts from Harness candidate
`c7923a65516cecb468b548f40bfc6970ed48d39f`. The later Harness rebind commit
`047df9ab83a4bb74f203fa7b34d8ceebbff2ea2f` and Pay-Nexus rebind commit
`5325392748d0b619072cc2fac41f235b42439d77` remain evidence-only NO-GO branches.
They must not be merged, pushed, benchmarked as the final design, or used as the
base of this candidate.

The selected design separates three facts that the current registration combines:

1. a canonical, locator-free `ToolchainProfile` describing the exact approved
   validator inputs;
2. a host-local `ToolchainBinding` resolving logical artifacts to paths for one
   Harness installation;
3. an operation/session-scoped `VerifiedToolchain` attesting that the resolved
   bytes, directories, permissions, relationships, and platform matched before
   and after the candidate Gate.

The Java Pack is the first expensive consumer to expose the defect, but the defect
is in Harness Core. The design applies to every External Pack that declares a
registered validator toolchain.

## Problem statement

The current `REGISTERED_TOOLCHAIN_OFFLINE_CACHE` record stores `absolutePath` and
SHA-256 together for `ruby`, `rg`, `java`, `javac`, `mvn`, `javaHome`,
`mavenHome`, and `mavenRepository`. Harness then copies the complete object into:

- canonical registration identity and Registry revision;
- `capability-lock/v2` validator identity and exact lock fingerprint;
- resolved context and runtime projection provenance;
- the in-process Pack verification key.

The Java registration selected
`/Applications/ChatGPT.app/Contents/Resources/rg` as a concrete locator. A normal
ChatGPT App update replaced that executable. Even though the Pack source, Pack
validator, project Authority, Java/Maven closure, and business semantics did not
change, the stored command digest no longer matched the bytes at that path.

Rebinding the registration to the new App bytes would make the candidate run, but
would also move registration, lock, resolution, and projection identities merely
because an unrelated desktop application was updated. The observed App bundle also
fails strict local signature verification, so treating its embedded utility as a
durable Harness trust root is not acceptable. The App is current and cannot be
rolled back; rollback is neither required nor a valid repair.

This coupling is more than a Java inconvenience. Any Pack may become unavailable
when a package manager, IDE, desktop application, JDK installation directory, user
home, or worktree locator changes. Requiring every adopting project to regenerate
locks and projections converts host maintenance into cross-project governance work
and destroys the intended locator-free identity boundary.

## Root cause

The original registration design correctly excluded `source.repositoryPath`, but
did not classify toolchain locators separately from toolchain content. The negative
matrix proved source relocation and content drift; it did not prove toolchain
relocation with identical bytes, App/package-manager lifecycle independence, or
absence of absolute toolchain paths in canonical outputs.

Subsequent read-only, directory-digest, and TOCTOU hardening strengthened the
validation of the combined object without correcting that classification. The
result is secure measurement of the wrong identity boundary: Harness correctly
detects that the App changed, but incorrectly treats the App locator as Pack and
project identity.

## Design goals

The implementation must:

1. preserve exact Pack source commit, tree, content digest, validator blob, and
   validator ABI binding;
2. preserve the `capability-lock/v2` schema version and exact canonical fingerprint
   algorithm;
3. make canonical registration, lock, resolution, and projection independent of
   host absolute paths;
4. make a pure binding relocation with identical content produce byte-identical
   canonical Registry, lock, resolution, and projection outputs;
5. fail closed when a selected binding is missing, unsafe, writable, incompatible,
   or does not match the canonical profile;
6. retain pre-Gate and post-Gate byte/directory measurements and TOCTOU poisoning;
7. keep validation offline; provisioning may use the network only as a separate,
   explicit operation;
8. use a Harness-managed, independently versioned `rg` artifact rather than an
   executable inside ChatGPT.app;
9. avoid per-project tool installation and per-project host path configuration;
10. coexist with the operation-scoped validation reuse introduced by the lifecycle
    scaling candidate;
11. preserve project Authority, Pack semantics, projection business semantics,
    Skill install/apply boundaries, and all execution `DENY` decisions;
12. provide an explicit legacy migration rather than silently reinterpreting old
    registration bytes.

## Non-goals

This candidate will not:

- modify Java Pack source, its validator, or Pay-Nexus Authority;
- repair the Pay-Nexus-specific `originalSourceRoot` / replacement-root validator
  correctness defect;
- make ChatGPT.app, Homebrew, a JDK vendor, or a user home directory a Harness
  release dependency;
- trust `PATH`, command names, file timestamps, package-manager metadata, or version
  output in place of content digests;
- create a persistent candidate-Gate trust cache or reuse a Gate result across
  processes;
- download tools during Registry build, lock verification, resolve, projection,
  freshness, install, or candidate Gate execution;
- weaken read-only, symlink, special-file, directory-closure, or TOCTOU checks;
- change lock canonical JSON or fingerprint algorithms;
- merge, push, release, deploy, or adopt the candidate in another project.

## Engineering basis

The design follows three established principles without importing their complete
systems:

- SLSA provenance identifies an artifact by verifiable provenance, subject digest,
  and verifier identity rather than by the consumer's local file path. See
  [SLSA Provenance](https://slsa.dev/spec/v1.2/provenance) and
  [SLSA verification guidance](https://slsa.dev/spec/v1.2/verifying-source).
- Bazel toolchain resolution separates an abstract toolchain dependency and
  platform constraints from the concrete execution-platform selection. See
  [Bazel Toolchains](https://bazel.build/extending/toolchains) and
  [Bazel Platforms](https://bazel.build/extending/platforms).
- Reproducible-build guidance treats a host build path as environmental variation
  that should be removed or normalized, not embedded as output identity. See
  [Reproducible Builds: Build path](https://reproducible-builds.org/docs/build-path/).

The ripgrep project publishes platform-specific release archives and signed release
tags. Harness will pin one reviewed official archive and its hashes as a managed
artifact. The profile must not infer trust from the version bundled with another
application. See the official
[ripgrep 15.2.0 release](https://github.com/BurntSushi/ripgrep/releases/tag/15.2.0).

These references support the identity split; they do not grant implementation or
release Authority and do not make Harness SLSA- or Bazel-compliant.

## Considered approaches

### A. Rebind the latest ChatGPT App `rg` — rejected

This is the evidence-only branch. It restores the expected digest for one App build
but preserves the lifecycle coupling, forces lock/projection churn, and leaves
projects exposed to the next App update. The current strict signature failure also
prevents the App binary from satisfying the proposed managed-artifact provenance
policy.

### B. Copy App `rg` into a stable path — rejected

A copied locator is stable, but its origin remains an unrelated application bundle.
Copying without a separate artifact manifest and verified acquisition record merely
hides provenance. It also creates unclear redistribution, update, and ownership
semantics.

### C. Exclude the complete toolchain from identity — rejected

This would make two validator executions using different Java, Maven, Ruby, or
repository bytes appear equivalent. It weakens reproducibility and makes a prior
Gate result ambiguous. Paths must be removed; tool content and platform identity
must remain.

### D. Canonical profile plus host binding and runtime attestation — selected

The profile binds the exact semantic inputs. A binding selects where those inputs
are materialized on one host. Runtime attestation proves the selected paths contain
the approved content and remain unchanged during the Gate. This removes lifecycle
coupling without turning a locator change into trust.

## Canonical `ToolchainProfile`

The registration contract adds `MANAGED_TOOLCHAIN_PROFILE`. A registration using
this contract contains `validator.toolchainProfile` and must not contain the legacy
`validator.toolchain` object.

The canonical profile is a closed schema with at least:

```yaml
schemaVersion: capability-validator-toolchain-profile/v1
profileId: toolchain-profile:java-engineering-standard:darwin-arm64:v1
platform:
  os: darwin
  architecture: arm64
commands:
  rg:
    artifactId: artifact:ripgrep:darwin-arm64
    fileName: rg
    sha256: sha256:<executable-bytes>
    bindingPolicy: HARNESS_MANAGED_STORE
  ruby:
    artifactId: artifact:ruby:host-attested
    fileName: ruby
    sha256: sha256:<executable-bytes>
    bindingPolicy: HOST_ATTESTED
  java: {artifactId: artifact:temurin-21, fileName: java, sha256: sha256:<bytes>, bindingPolicy: HOST_ATTESTED}
  javac: {artifactId: artifact:temurin-21, fileName: javac, sha256: sha256:<bytes>, bindingPolicy: HOST_ATTESTED}
  mvn: {artifactId: artifact:maven-3.9.x, fileName: mvn, sha256: sha256:<bytes>, bindingPolicy: HARNESS_MANAGED_STORE}
directories:
  javaHome: {artifactId: artifact:temurin-21, sha256: sha256:<closure>}
  mavenHome: {artifactId: artifact:maven-3.9.x, sha256: sha256:<closure>}
  mavenRepository: {artifactId: artifact:java-pack-offline-repository, sha256: sha256:<closure>}
relationships:
  javaHomeCommands: [java, javac]
  mavenHomeCommand: mvn
  mavenRepositoryLayout: DOT_M2_REPOSITORY
```

The concrete field names are implementation-plan inputs, but the following facts
are mandatory and canonical:

- profile schema version and profile ID;
- normalized OS and architecture constraints;
- logical artifact IDs, command basenames, command SHA-256 values, directory closure
  SHA-256 values, and binding policies;
- command-to-directory and offline-cache relationship constraints;
- validator environment contract, arguments contract, history contract, timeout,
  and validation ABI.

An artifact's approved version, upstream release/tag, archive digest, extracted-file
digest, and acquisition policy are recorded in a Harness-owned artifact manifest.
The profile references its immutable artifact identity/digest. A deliberate artifact
or profile change therefore moves registration and downstream canonical identities;
a host path relocation does not.

No absolute path, user name, home directory, worktree name, App version, package
manager prefix, inode, timestamp, or current `PATH` may enter the profile.

## Host-local `ToolchainBinding`

`ToolchainBinding` maps every logical command and directory in one profile to an
absolute path on the current host. It is configuration, not identity.

The default binding provider uses the Harness common repository root so every Git
worktree shares one cache. Managed artifacts and host binding records live below the
ignored `.worktrees/.capability-pack-cache/` hierarchy. They are never copied into:

- `core/registries/capability-packs.yaml`;
- generated Registry JSON;
- a project capability lock;
- resolved context;
- projection manifests or projected resources;
- registration, source-revision, lock, or projection fingerprints.

Tests may inject a binding provider explicitly. Production code must not accept
binding paths from Pack source, project configuration, projection contents, or an
ambient `PATH`. A host-local binding record is loaded only after the canonical
profile has been selected and schema-validated.

Binding changes have two distinct outcomes:

- same profile and same measured content at a different safe path: canonical bytes
  are unchanged; an open validation session rejects the changed access witness, and
  a new session performs a full Gate;
- different or unsafe content: validation fails closed before the candidate Gate.

The first rule prevents a mid-operation relocation from crossing the linearization
boundary. The second prevents locator exclusion from becoming content substitution.

## Managed artifact provisioning

Harness adds an explicit provisioning operation for artifacts with
`HARNESS_MANAGED_STORE` policy. Provisioning and validation are separate:

1. select the exact platform artifact manifest;
2. download only on an explicit provisioning command;
3. verify the upstream archive digest and, where declared, release/tag provenance;
4. extract into a fresh temporary directory without following archive symlinks or
   allowing path traversal, special files, or duplicate normalized paths;
5. verify extracted command and directory digests against the profile;
6. remove write permission and remeasure;
7. atomically publish to a content-addressed managed-store path;
8. write a host-local binding record only after all checks pass.

Candidate validation never performs network access and never updates a managed
artifact. Missing artifacts produce a deterministic error that names the profile,
artifact ID, platform, and the explicit provisioning command. There is no fallback
to ChatGPT.app, Homebrew, `/usr/bin`, or another `PATH` entry.

The initial Java migration must provision `rg` from an official ripgrep release
artifact independently of ChatGPT.app. Maven home and the offline repository remain
Harness-managed. Java/Ruby may initially use `HOST_ATTESTED` bindings if their exact
bytes and directory closure match the profile; moving their installation without
changing bytes must not alter canonical project artifacts. A later decision to
manage Java/Ruby is a profile/artifact change, not a hidden resolver fallback.

## Runtime verification and TOCTOU

`_verify_validator_toolchain()` becomes a profile-and-binding verification function.
For every command it must:

- resolve the binding by logical artifact ID;
- require an absolute, normalized, non-symlink regular file with the declared
  basename;
- enforce the binding policy, including containment in the Harness managed store;
- read bytes with before/after file identity checks;
- match the canonical SHA-256 and reject writable or special files.

For every directory it must preserve the current complete closure algorithm:

- absolute, normalized, non-symlink root;
- no writable root, directory, or file;
- no symlink or special file anywhere in the closure;
- canonical path/type/mode/file-digest entries;
- before/after identity comparison while hashing;
- exact match to the canonical directory digest.

It must then verify the declared relationships: Java and javac belong to the bound
Java home, Maven belongs to the bound Maven home, the Maven repository has the
required offline-cache layout, and Maven home is within the allowed cache boundary.

The resulting immutable `VerifiedToolchain` contains the canonical profile digest,
resolved binding witness, measured command/directory identities, and exact sanitized
environment. The candidate Gate consumes only this object.

A full validation has one pre-Gate measurement and one post-Gate measurement. The
post-Gate object must equal the pre-Gate object. Source, validator, profile, binding,
or toolchain mutation at any pre-read/post-read/pre-Gate/post-Gate checkpoint poisons
the operation-scoped `CapabilityVerificationSession`; no successful object may be
published or reused from that session.

The Pack verification key contains the canonical profile identity/digest and
platform constraints, but never resolved paths. The session separately retains a
binding/access witness. Reuse therefore means “same approved profile, same session,
same measured binding,” not “trust whatever now exists at this path.”

## Canonical outputs and compatibility

For `MANAGED_TOOLCHAIN_PROFILE`, canonical registration identity carries
`toolchainProfile`; lock and projection `validatorIdentity` carry the same canonical
profile information or an unambiguous profile digest/reference. They do not carry
`ToolchainBinding`.

The following algorithms remain unchanged:

- canonical JSON byte encoding;
- registration fingerprint SHA-256 construction;
- `capability_lock_fingerprint()` exclusion of only `lockFingerprint`;
- `capability_lock_v2_source_revision()` ordering and hashing;
- Registry revision and projection digest algorithms.

Their input record changes once during the explicit Java migration because a legacy
toolchain identity is replaced by a canonical profile. Exact fingerprints therefore
move once, intentionally. Future host binding relocation or ChatGPT App updates do
not move them.

`capability-lock/v2` remains the lock schema version. Its `validatorIdentity` accepts
exactly one of:

- legacy `REGISTERED_TOOLCHAIN_OFFLINE_CACHE` plus legacy path-bearing `toolchain`;
- `MANAGED_TOOLCHAIN_PROFILE` plus locator-free `toolchainProfile`.

Legacy records retain their current exact semantics and fail closed. Harness does
not silently strip their paths or reinterpret an old fingerprint. New registrations
must use the profile contract; the Java registration migrates explicitly. Removal of
legacy support requires a later compatibility decision and repository-wide evidence.

## Project-impact boundary

The target operating model removes recurring toolchain maintenance from adopting
projects:

```text
Harness installation
  ├─ owns one canonical profile and managed artifact cache
  ├─ provisions/attests once per host and profile
  └─ verifies once per explicit validation session
        ├─ Project A lock/resolve/projection reuse verified Pack
        ├─ Project B lock/resolve/projection reuse verified Pack
        └─ App updates are outside the dependency graph
```

Projects continue to own capability selection, exact lock, Authority, and adoption
evidence. They do not install `rg`, point Harness at an App bundle, or rebind because
the App, IDE, or package-manager prefix changed. When a canonical profile changes,
affected projects deliberately regenerate and review exact locks/projections once.

Expected practical effects after migration:

- ChatGPT App update impact on Pack registration/lock/projection: zero;
- per-project `rg` setup or rebind: zero;
- host bootstrap: one explicit managed-artifact provisioning action per profile;
- validation-time network dependency: zero;
- unchanged-profile project churn: zero;
- security posture: content/directory/TOCTOU checks preserved, with provenance and
  managed-root policy added for `rg`.

The lifecycle-scaling candidate remains responsible for reducing one Pay-Nexus
scenario/install group from 14 candidate Gates to at most 2, target 1, and directory
digests from the observed amplification to at most 12, target 6. This profile design
does not claim that performance result by itself; it removes the environmental
blocker so the fixed benchmark can run on a valid independent toolchain.

## Migration sequence

Migration is intentionally ordered so no project consumes a partially changed
identity:

1. add profile, artifact-manifest, binding-provider, provisioning, and verification
   schema/code behind the new environment contract;
2. prove all synthetic positive/negative and locator-relocation behavior while the
   Java registration remains legacy;
3. provision and verify the fixed official `rg` artifact on the Harness host;
4. migrate the Java registration to the reviewed profile and regenerate the Harness
   Registry projection;
5. regenerate the neutral Java fixture lock/projections and prove byte stability
   across two different safe bindings;
6. perform the one-time Pay-Nexus registration/lock/projection rebind in a separate
   project-authorized candidate;
7. run the performance benchmark using the fixed Harness and fixed Pay source
   identities;
8. run complete Harness regression, fix candidate/parent/tree, and obtain one
   independent `deep_reviewer / xhigh` GO with no P0/P1 finding.

Steps 6 and any merge, push, release, or adoption require separate project Authority.
This Harness design cannot authorize them.

## Deterministic test matrix

### Canonical identity

- two bindings with different absolute roots and byte-identical tools/directories
  produce identical registration fingerprint, Registry revision,
  `capability-lock/v2`, exact lock fingerprint, resolution, and projection bytes;
- no host absolute toolchain path or ChatGPT App identifier occurs in those outputs;
- command digest, directory digest, platform, binding policy, profile ID, artifact
  manifest, validator digest, or validation ABI mutation moves the appropriate
  canonical identity and invalidates reuse;
- lock canonical fingerprint behavior remains exact and locator-free.

### Binding and fail-closed behavior

- missing binding, relative/non-normalized path, symlink, wrong basename, special
  file, writable content, managed-root escape, platform mismatch, wrong file digest,
  wrong directory digest, invalid Java/Maven relationship, and offline-cache layout
  drift all fail before the candidate Gate;
- ambient `PATH` and an installed ChatGPT App `rg` are never fallback sources;
- binding relocation during an open session poisons the session; a new session runs
  one full Gate on the new binding;
- source, validator, command, or directory mutation before/during/after the Gate
  produces no verified object and cannot be reused;
- public APIs without a supplied session still perform complete fail-closed
  validation.

### Provisioning

- wrong archive digest, unsigned/unapproved release when policy requires provenance,
  archive path traversal, symlink, special file, duplicate normalized path, wrong
  extracted digest, writable final state, partial extraction, and interrupted
  publication never create a usable binding;
- repeated provisioning of the same content is deterministic and does not mutate a
  valid store object;
- validation remains offline and produces a deterministic provisioning instruction
  when content is absent.

### Compatibility and project burden

- legacy registrations retain their exact fingerprints and failure behavior;
- the explicit Java migration moves expected artifacts once and only once;
- changing or removing ChatGPT.app after migration changes no Harness canonical
  output and does not block the Java candidate Gate;
- two consumer projects reuse the same host profile without project-specific paths
  or tool installation;
- closed scenarios still do not select Java, and all business execution permissions
  remain `DENY`.

## Verification and benchmark acceptance

The fixed implementation candidate must provide:

- RED evidence for path relocation and App-update independence before implementation;
- GREEN synthetic profile/binding/provisioning tests;
- focused Registry, lock, resolver, projection, install, and verification-session
  regression;
- Java candidate Gate PASS using a managed `rg` outside ChatGPT.app;
- two-path byte/semantic equivalence receipts for Registry, lock, resolver, resource
  digest, projection, and install dry-run;
- `git diff --check` and schema validation PASS;
- complete Harness regression PASS, not an interrupted partial result;
- fixed Candidate/Parent/Tree and one independent R2 deep review;
- before/after benchmark using fixed Pack/project/toolchain profiles, reporting Gate
  count, checkout count, toolchain directory digest count, elapsed time, node IDs,
  stdout/stderr, exit code, and passed summary.

The combined performance objective remains at least 70% wall-time reduction for the
equivalent Pay-Nexus workload, with actual measurements authoritative. The profile
candidate is successful even if its standalone provisioning cost is non-zero;
provisioning time is reported separately and never hidden inside validation time.

## Proposed Exact WriteSet

The implementation plan must narrow and confirm this set before code changes.

Design and plan:

- `docs/superpowers/specs/2026-08-29-external-pack-toolchain-profile-decoupling-design.md`
- `docs/superpowers/plans/2026-08-29-external-pack-toolchain-profile-decoupling.md`

Core contracts and canonical artifacts:

- `core/schemas/capability-pack-registration.schema.json`
- `core/schemas/capability-lock.schema.json`
- `core/schemas/runtime-projection-manifest.schema.json`
- a new Toolchain Profile/artifact-manifest schema and Harness-owned registry
- `core/registries/capability-packs.yaml`
- `generated/registries/capability-pack-registry.json`

Runtime:

- `src/evolution_harness/capability_pack_registry.py`
- `src/evolution_harness/project.py`
- the narrow CLI/provisioning module and command routing selected by the plan

Tests and generated neutral fixture:

- `tests/test_capability_pack_registry.py`
- `tests/test_external_pack_verification_session.py`
- `tests/test_lock_enforcement.py`
- `tests/test_project_state.py`
- `tests/test_resolver.py`
- `tests/test_projection.py`
- `tests/test_projection_install.py`
- `tests/test_java_engineering_standard_registration_fixture.py`
- Java neutral fixture lock and generated projections whose canonical identity
  changes in the explicit migration

The plan must not include Pay-Nexus files, Java Pack source, App files, user-global
configuration, Skill installation, deployment, push, or unrelated generated output.

## Completion boundary

This specification is ready for implementation planning only after user review.
Implementation completion requires all acceptance evidence above, a clean fixed
candidate, and independent review with no P0/P1 finding. Even then it is not merged,
pushed, released, deployed, or adopted by Pay-Nexus without separate authorization.
