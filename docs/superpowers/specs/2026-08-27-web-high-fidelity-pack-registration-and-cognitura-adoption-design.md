# Web High-Fidelity Capability Pack Registration and Cognitura Adoption Design

**Date:** 2026-08-27

**Status:** PROPOSED_FOR_USER_REVIEW

**Owning repository:** `omini-harness`

**Risk:** R2 / L3

**Target outcome:** lock `web-high-fidelity` as an external Capability Pack in
`omini-harness`, then let Cognitura explicitly adopt and receive its Skill without
transferring project Authority.

## 1. Decision

Use a two-level, opt-in model:

1. `omini-harness` registers and immutably locks the Pack source once.
2. Cognitura explicitly selects the registered capability and receives a
   project-specific exact lock.
3. A Harness-owned read-only Cognitura sidecar resolves and projects the locked
   Skill.
4. Cognitura authorizes and commits the managed repository-local Skill plus a
   small registration pointer.

Registration is not project adoption. Project adoption is not page completion.
Runtime projection is not authorization to modify, merge, publish, or release a
page.

The selected Capability ID remains:

```text
workflow:web-high-fidelity:reference-driven-visual-fidelity
```

The current Capability Pack becomes version `2.0.0`. Cognitura's active legacy
binding identifies the retired Harness as v1.0, while the current Pack rejects
`PROJECT_BINDING`, `HF3`, `LANDING_MODE=THIN_BINDING`, and `MANIFEST.sha256` as
active execution semantics. The migration is therefore breaking, even though
the earlier consumer was never registered in `omini-harness`.

## 2. Live starting point

### 2.1 `web-high-fidelity`

- Repository: `/Users/yuzhuangzhuang/Projects/web-high-fidelity`
- Branch: `main`
- Commit: `846ed37b0cb66849bc63aefb8fd24873b21bca49`
- Tree: `66de32f74bb94d79bb82d6e0c563d849b7ae2fe9`
- Worktree: clean
- Remote: absent
- Source Gate: `CAPABILITY_PACK_VERIFICATION=PASS`
- Registration: `NOT_REGISTERED`
- Current gaps: no `VERSION`, no machine-readable Pack manifest, no Harness
  registration, no external source lock.

### 2.2 `omini-harness`

- Repository: `/Users/yuzhuangzhuang/Projects/omini-harness`
- Branch at design base: `main`
- Commit: `4b9c202108ddb12f61a1ed731809282e628a11a3`
- Tree: `5097d84907bec86b7cdc6d2d8d20f28db08d8778`
- Worktree: clean
- Baseline: `658 passed`

The current Harness supports internal `PRINCIPLE`, `FRAMEWORK`, `SKILL`, and
`WORKFLOW` assets, project binding, exact locks, deterministic resolution,
runtime projection, and read-only project registration. It has no external Pack
registry or resolver path. Automatic projection installation remains disabled.

### 2.3 Cognitura

- Repository: `/Users/yuzhuangzhuang/Projects/cognitura`
- Current branch: `codex/i09-closure-clean`
- Commit: `a14206d5171b776b6fe14dbb0feca582d982a393`
- Tree: `cf439dd31078c734cbf64ecfbed682507399b0f7`
- Worktree: dirty because `.idea/` is untracked and not attributable to this
  change.
- Active Authority: `W2-D05=READY`, fixed Wave 2 design review only.
- Business/page implementation: not authorized.
- Real-page Pilot: `NOT_AUTHORIZED`.

Cognitura already contains a legacy thin binding to Pack commit `768f3a02...`
and tree `a8121904...`. That record is historical migration input, not proof that
the current Capability Pack is registered, locked, projected, or adopted.

## 3. Ownership boundaries

### 3.1 Capability Pack

`web-high-fidelity` owns:

- visual Reference analysis and implementation guidance;
- HF0/HF1/HF2 applicability semantics;
- evidence templates and Skill content;
- the Pack manifest and source self-verifier;
- `VISUAL_CAPABILITY_RESULT` semantics.

It does not own project scope, commands, baselines, task state, authorization,
merge, deployment, publication, or release.

### 3.2 Harness

`omini-harness` owns:

- external Pack registration status;
- source discovery and immutable source identity;
- Pack content digest and validator identity;
- project selection and exact lock resolution;
- deterministic runtime projection and managed-file planning;
- cross-project adoption verification.

It does not create Cognitura product facts or task completion decisions.

### 3.3 Cognitura

Cognitura owns:

- project Authority and task-card state;
- its selected capability and risk acceptance;
- application commands, browser environment, references, routes, states, and
  viewports;
- generated evidence and target engineering results;
- authorization to materialize managed Skill bytes;
- task acceptance, merge, deployment, publication, and release.

`TARGET_PROJECT_AUTHORITY_PREVAILS` remains unconditional.

## 4. Considered approaches

### 4.1 Directly repin the legacy Cognitura binding

Rejected. Replacing only commit, tree, and checksum would retain a retired
adoption contract, bypass the Harness registry, and provide no reusable project
lock or runtime projection identity.

### 4.2 Register the Pack and extend the existing binding/lock path

Selected. The current Capability ID already conforms to the Harness
`workflow:<namespace>:<name>` shape. Existing internal assets keep their current
bytes and semantics; external Pack metadata is added conditionally. This reuses
the existing resolver, projection, registration, and sidecar model without
creating a second control plane.

### 4.3 Create a separate external-Pack project control plane

Rejected for the first Pilot. Separate selection and lock files would duplicate
the existing project binding and exact-lock concepts. A new subsystem would only
be justified if multiple real Pilots prove that a Pack cannot be represented as
a registered source for canonical capabilities.

### 4.4 Enable automatic project installation and upgrades

Deferred. The existing `projection install --apply` and uninstall apply boundary
remains disabled. The first Pilot uses a reviewed projection plan followed by an
explicit project-authorized commit. Pack upgrades never drift into a project
without a new lock.

## 5. Pack manifest

Create `capability-pack.yaml` and `VERSION` in `web-high-fidelity`.

The manifest uses `capability-pack/v1` and contains only source-owned facts:

```yaml
schemaVersion: capability-pack/v1
projectPackName: web-high-fidelity
skillName: web-high-fidelity
displayName: Reference-Driven Web Visual Fidelity
capabilityId: workflow:web-high-fidelity:reference-driven-visual-fidelity
version: 2.0.0
contentDigestContract: capability-pack-content/v1
contentRoots:
  - docs
  - prompts
  - references
  - skills
  - templates
excludedContentRoots:
  - docs/history
  - docs/superpowers
validator:
  kind: FIXED_CANDIDATE_GATE
  path: scripts/verify-capability-pack
  argumentsContract: CANDIDATE_COMMIT_TREE
```

The manifest must not contain:

- absolute source paths;
- source commit or tree, because those are registration facts;
- project adoption, task, merge, or release state;
- arbitrary shell strings;
- Cognitura-specific fields;
- approval identities.

`REGISTRATION_STATUS` becomes an informational mirror whose Authority is the
Harness registry. The Pack self-gate may verify that the mirror has an allowed
shape, but it must report registration as not independently asserted. The
Harness cross-repository registration Gate is the only mechanism that can prove
the mirror agrees with a real registry entry.

## 6. Harness external Pack registry

Add an independent registry source and generated artifact rather than placing
Pack records under `design/capabilities/**` or `engineering/registrations/**`.

Source contract:

```text
core/registries/capability-packs.yaml
core/schemas/capability-pack-registration.schema.json
```

Generated projection:

```text
generated/registries/capability-pack-registry.json
```

Each registration records:

```yaml
registrationId: pack:web-high-fidelity
capabilityId: workflow:web-high-fidelity:reference-driven-visual-fidelity
packVersion: 2.0.0
status: ACTIVE
distributionStatus: LOCAL_ONLY
source:
  kind: LOCAL_GIT
  repositoryId: web-high-fidelity
  repositoryPath: /Users/yuzhuangzhuang/Projects/web-high-fidelity
  commit: ${PACK_CANDIDATE_COMMIT}
  tree: ${PACK_CANDIDATE_TREE}
resolvedContentDigest: sha256:<64 lowercase hex>
validator:
  kind: FIXED_CANDIDATE_GATE
  relativePath: scripts/verify-capability-pack
  sha256: <64 lowercase hex>
  argumentsContract: CANDIDATE_COMMIT_TREE
```

The absolute local path is a discovery locator, not identity. Because the Pack
has no remote, the first registration is deliberately `LOCAL_ONLY`. Commit,
tree, resolved content digest, and validator identity remain stable if the local
repository is moved. Publication or a remote source is a later, separately
authorized change.

The registry builder must reject duplicate registration ID, duplicate active
Capability ID, source symlinks, missing Git objects, commit/tree mismatch,
unclean candidate checkout, manifest/registry identity mismatch, content digest
drift, validator path/hash drift, and a failing Pack candidate Gate.

## 7. Deterministic content digest

Define `capability-pack-content/v1` over tracked regular files below the declared
content roots after excluded roots are removed. Entries are sorted by UTF-8 path
bytes. Each entry contributes an unambiguous length-prefixed tuple of:

```text
relative path, Git mode, byte length, raw blob bytes
```

The SHA-256 digest covers the canonical concatenation. Symlinks, submodules,
unsafe paths, case-fold collisions, duplicate normalized paths, and untracked
files inside active content roots fail registration. The Pack manifest and
`VERSION` are included explicitly. The validator is hashed separately so that
runtime content identity and executable trust identity cannot mask each other.

The Git commit and tree remain required even though a content digest exists:

- commit binds provenance and parent history;
- tree binds every tracked source file;
- content digest binds the selected runtime surface;
- validator digest binds the code that judges the candidate.

## 8. Project binding and lock compatibility

The existing project binding already accepts the Web capability's canonical
`workflow:*` ID. Extend the loader and resolver so that an ID absent from the
internal catalog may resolve only through one active external Pack registration.

Do not change the serialized bytes or fingerprints of existing internal-only
bindings and v1 locks.

Introduce `capability-lock/v2` for locks containing an external Pack. Existing
`capability-lock/v1` remains valid and unchanged. An external locked entry adds:

```yaml
sourceKind: EXTERNAL_CAPABILITY_PACK
sourceRegistrationId: pack:web-high-fidelity
sourceCommit: ${PACK_CANDIDATE_COMMIT}
sourceTree: ${PACK_CANDIDATE_TREE}
resolvedContentDigest: sha256:<64 lowercase hex>
validatorIdentity:
  relativePath: scripts/verify-capability-pack
  sha256: <64 lowercase hex>
registrationFingerprint: sha256:<64 lowercase hex>
```

`sourceHarnessRevision` in a v2 project lock identifies the exact combined
internal-catalog and external-registration source set. It must change when any
selected external registration identity changes, while unrelated Pack registry
changes must not move an existing project's resolved lock.

## 9. Resolution and runtime projection

External resolution is deterministic and never invokes an LLM:

```text
project binding
→ active external registration lookup
→ manifest identity comparison
→ source commit/tree verification
→ content and validator digest verification
→ Pack candidate Gate
→ project lock v2
→ selected Skill snapshot
→ runtime projection manifest
```

The resolver loads only manifest-declared runtime content at the locked commit.
It cannot execute project commands from the manifest, registry, binding, or
evidence. The only permitted Pack executable is the fixed registered validator
with the `CANDIDATE_COMMIT_TREE` argv contract.

Extend the runtime projection manifest so an external source capability records
the same Pack registration identity, source commit/tree, content digest, and
validator digest as the project lock. The generated Skill bytes must match the
locked source blob and remain stable while the projection builder holds its
source lock.

Automatic materialization remains disabled. For the first Cognitura adoption:

1. Harness produces and verifies a dry-run managed-file plan.
2. Cognitura Authority explicitly authorizes the plan as a bounded repository
   write.
3. The approved bytes are committed under
   `.agents/skills/web-high-fidelity/SKILL.md` with the existing manifest-aware
   ownership evidence.
4. A short `AGENTS.md` route activates the Skill only for explicit or materially
   visual work.

No Pack rule body is copied into `AGENTS.md`.

## 10. Cognitura sidecar and adoption migration

Create a Harness-owned read-only integration:

```text
integrations/cognitura-shadow/
├── integration.yaml
├── authority-map.yaml
├── control-plane/.agent-evolution/
│   ├── design-state.yaml
│   ├── capabilities.yaml
│   └── capabilities.lock.yaml
└── scenarios/
```

The sidecar selects only the registered Web capability. Its stage describes the
integration work, never Cognitura's product delivery state. The authority map
reads only allowlisted Cognitura sources and cannot claim ownership of project
facts.

After the sidecar candidate passes, Cognitura receives:

```text
.agent-evolution/registration.yaml
.agents/skills/web-high-fidelity/SKILL.md
docs/engineering/cognitura-high-fidelity-harness-binding.md
AGENTS.md
```

The existing binding path is retained to preserve links, but its active content
is rewritten as a Capability Pack adoption record. The legacy v1 text moves to:

```text
docs/history/high-fidelity/cognitura-high-fidelity-harness-v1-binding.md
```

The new active record contains:

- canonical Capability ID;
- Harness registration ID and registration fingerprint;
- Cognitura capability-lock fingerprint;
- managed Skill projection identity;
- project-owned commands and relevant baseline references;
- `TARGET_PROJECT_AUTHORITY_PREVAILS`;
- `REAL_PAGE_PILOT=NOT_AUTHORIZED` until a separate page task exists.

It must not contain the retired active terms `PROJECT_BINDING`, `HF3`,
`LANDING_MODE=THIN_BINDING`, or `MANIFEST.sha256`. Historical files may preserve
them and must not be treated as active execution surfaces.

HF0/HF1/HF2 remain task-level applicability profiles, not permanent project
status. Registering the Pack does not classify every Cognitura task as HF2.

## 11. Gates and result semantics

The work reports independent results:

```text
PACK_SOURCE_RESULT=PASS|FAIL
PACK_REGISTRATION_RESULT=PASS|FAIL
PROJECT_ADOPTION_RESULT=PASS|FAIL|NOT_ATTEMPTED
RUNTIME_PROJECTION_RESULT=PASS|FAIL|NOT_ATTEMPTED
VISUAL_CAPABILITY_RESULT=PASS|FAIL|PASS_WITH_KNOWN_LIMITATION|NOT_RUN
TARGET_ENGINEERING_RESULT=PASS|FAIL|NOT_RUN
```

The first two results do not establish Cognitura adoption. Project adoption and
runtime projection do not establish page quality. `VISUAL_CAPABILITY_RESULT`
cannot become PASS without real-browser evidence bound to a real application
commit/tree, Reference, route/state/viewports, assets/fonts, and browser
environment. Cognitura alone decides task completion, merge, and release.

## 12. RED-to-GREEN requirements

### 12.1 Pack registration

RED cases must reject:

- identity or version mismatch between manifest and registry;
- missing, dirty, or moved candidate identity;
- wrong commit/tree pair;
- content-root digest mutation;
- validator path, bytes, or argv-contract drift;
- duplicate active Capability ID;
- unsafe path, symlink, submodule, case collision, or untracked active content;
- a Pack that self-claims project adoption or task completion.

### 12.2 Project lock and resolution

RED cases must reject:

- an unregistered external capability;
- inactive, ambiguous, or duplicate registrations;
- project lock v2 source drift;
- changed registration that is silently accepted by an old project lock;
- unrelated registry changes moving a locked project's fingerprint;
- external Pack metadata changing existing internal v1 lock bytes;
- resolver fallback from a failed external registration to mutable source.

### 12.3 Projection and Cognitura adoption

RED cases must reject:

- Skill bytes differing from the locked source blob;
- projection metadata differing from the project lock;
- automatic apply, unmanaged overwrite, unsafe target paths, or symlink targets;
- registration discovery pointing to a different sidecar or lock fingerprint;
- Cognitura active surfaces retaining retired v1 adoption terms;
- Pack applicability being interpreted as project authorization;
- adoption PASS being interpreted as visual, task, merge, or release PASS.

Mutation tests use temporary Git repositories with real commit/tree identities.

## 13. Candidate and review sequence

Use two stable candidates rather than one cross-repository mega-candidate.

### Candidate A: Pack registration and Harness external-source support

1. Freeze `web-high-fidelity` v2.0.0 manifest and source Gate.
2. Freeze the Harness Registry/Schema/Builder/Lock/Resolver/Projection changes.
3. Register and lock the exact Pack candidate.
4. Run Pack Gate, Harness focused tests, full Harness regression, generated
   artifact check, `git diff --check`, and one `deep_reviewer / xhigh` review.
5. Stop on P0/P1. Judge P2 against the first Cognitura Pilot.

### Candidate B: Cognitura adoption

Start only after Cognitura has a clean approved base and an adoption-specific
Authority outside W2-D05's fixed WriteSet.

1. Freeze `cognitura-shadow` and its exact project lock.
2. Generate and verify the Cognitura runtime projection plan.
3. Migrate the legacy binding and add the repository registration plus managed
   Skill on an isolated Cognitura worktree.
4. Run Harness integration scenarios and all directly affected Cognitura gates.
5. Fix Candidate/Parent/Tree and perform the Cognitura-required independent
   `deep_reviewer / xhigh` Gate.

No remote push, deployment, publication, global Skill installation, baseline
refresh, dependency installation, or real-page Pilot is part of either
candidate.

## 14. Planned implementation WriteSets

The detailed implementation plans may narrow these sets. Expansion requires an
explicit dependency chain and renewed scope review.

### 14.1 `web-high-fidelity`

- Create `VERSION`.
- Create `capability-pack.yaml`.
- Modify `AGENTS.md`.
- Modify `README.md`.
- Modify `docs/07-CAPABILITY-PACK-BOUNDARY.md`.
- Modify `scripts/verify-capability-pack`.
- Modify `tests/capability-pack/verify-capability-pack.sh`.
- Create a migration note for Harness v1 consumers under `docs/migrations/`.

The Skill body, visual rules, profiles, templates, and evaluation cases remain
unchanged unless RED tests prove a registration-interface dependency.

### 14.2 `omini-harness` Candidate A

- Create `core/schemas/capability-pack-manifest.schema.json`.
- Create `core/schemas/capability-pack-registration.schema.json`.
- Create `core/registries/capability-packs.yaml`.
- Create `generated/registries/capability-pack-registry.json`.
- Create `src/evolution_harness/capability_pack_registry.py`.
- Create `tests/test_capability_pack_registry.py`.
- Modify `core/schemas/capability-lock.schema.json`.
- Modify `core/schemas/runtime-projection-manifest.schema.json`.
- Modify `src/evolution_harness/registry.py`.
- Modify `src/evolution_harness/project.py`.
- Modify `src/evolution_harness/resolver.py`.
- Modify `src/evolution_harness/projection.py`.
- Modify `src/evolution_harness/cli.py`.
- Modify `src/evolution_harness/assurance.py`.
- Modify `tests/test_registry_catalog_compat.py`.
- Modify `tests/test_project_state.py`.
- Modify `tests/test_lock_enforcement.py`.
- Modify `tests/test_resolver.py`.
- Modify `tests/test_projection.py`.
- Modify `tests/test_projection_install.py` only to prove apply remains disabled.
- Modify `tests/test_assurance_cli.py`.
- Modify `README.md`.

`design/capabilities/**`, `runtime/profiles/**`,
`core/schemas/project-harness-registration.schema.json`,
`src/evolution_harness/registration.py`, and existing internal generated
catalog bytes are outside Candidate A unless a failing compatibility test proves
otherwise.

### 14.3 `omini-harness` Candidate B sidecar

- Create `integrations/cognitura-shadow/integration.yaml`.
- Create `integrations/cognitura-shadow/authority-map.yaml`.
- Create
  `integrations/cognitura-shadow/control-plane/.agent-evolution/design-state.yaml`.
- Create
  `integrations/cognitura-shadow/control-plane/.agent-evolution/capabilities.yaml`.
- Create
  `integrations/cognitura-shadow/control-plane/.agent-evolution/capabilities.lock.yaml`.
- Create bounded scenarios for project-Authority precedence, non-visual scope,
  locked visual scope, stale Pack source, and unauthorized page completion.
- Create `tests/test_cognitura_integration_fixture.py`.
- Modify `tests/test_integration_e2e.py`.
- Modify `tests/test_project_registration.py`.

### 14.4 Cognitura Candidate B

- Create `.agent-evolution/registration.yaml`.
- Create `.agents/skills/web-high-fidelity/SKILL.md` from the verified projection.
- Create
  `docs/history/high-fidelity/cognitura-high-fidelity-harness-v1-binding.md`.
- Modify `docs/engineering/cognitura-high-fidelity-harness-binding.md`.
- Modify `AGENTS.md` with one concise capability-routing rule.
- Modify the smallest existing Cognitura validator/test surface that owns this
  binding, registration, and managed Skill integrity.

No product source under `web/`, backend source, task-card state, visual baseline,
reference image, package file, lockfile, CI workflow, or database asset is in the
Cognitura adoption WriteSet.

## 15. Verification commands

Candidate A must include, at minimum:

```bash
pack_candidate_commit="$(git rev-parse HEAD)"
pack_candidate_tree="$(git rev-parse 'HEAD^{tree}')"
bash scripts/verify-capability-pack \
  "${pack_candidate_commit}" "${pack_candidate_tree}"
bash tests/capability-pack/verify-capability-pack.sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/test_capability_pack_registry.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/test_registry_catalog_compat.py \
  tests/test_project_state.py \
  tests/test_lock_enforcement.py \
  tests/test_resolver.py \
  tests/test_projection.py \
  tests/test_projection_install.py \
  tests/test_assurance_cli.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q
git diff --check
```

Candidate B must include, at minimum:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/test_cognitura_integration_fixture.py \
  tests/test_integration_e2e.py \
  tests/test_project_registration.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q
git diff --check
```

Cognitura then runs the binding/registration mutation tests and its directly
affected canonical gates on the fixed candidate. `pnpm test`, `pnpm build`, and
real-browser verification are not required for adoption-only changes because no
product or page bytes change. They become mandatory for the later real-page
Pilot.

## 16. Stop boundaries

Stop before the affected write if any of the following is true:

- any target worktree has unattributable user changes;
- `web-high-fidelity` changes after its fixed registration candidate;
- Cognitura still has `.idea/` or other unattributable state at adoption start;
- W2-D05 remains the only applicable Cognitura Authority and no separate
  adoption task has been approved;
- version `2.0.0` conflicts with a newly discovered formal consumer contract;
- the external lock requires changing existing internal lock bytes;
- source or validator identity cannot be reproduced locally;
- project registration would overwrite another integration;
- the WriteSet expands into product code, browser baseline, dependencies, CI,
  another repository, a remote system, or an external publication;
- push, release, deployment, global Skill installation, authentication, or an
  irreversible operation becomes necessary.

## 17. Rollback

Before Cognitura adoption, rollback is deletion of the unmerged external Pack
registration candidate and restoration of the Pack's `NOT_REGISTERED` mirror.
Existing internal capabilities and project v1 locks remain byte-for-byte
unchanged.

After a local Cognitura adoption commit, rollback is a normal revert that:

1. removes the project registration pointer and managed Skill;
2. restores the active legacy-binding predecessor from Git history;
3. removes the Cognitura sidecar registration from future resolution;
4. leaves Pack source history, Cognitura product code, baselines, and evidence
   untouched.

Rollback does not rewrite Git history or delete user worktrees.

## 18. Completion definition

The registration-and-adoption Slice is complete only when all are true:

- the Pack v2.0.0 candidate is clean and self-verified;
- the Harness registry resolves its exact source and validator identities;
- external source mutations fail closed;
- existing internal capability locks remain compatible;
- Cognitura has an exact v2 project lock through `cognitura-shadow`;
- Cognitura's registration fingerprint matches that sidecar lock;
- the managed Skill bytes match the locked Pack source;
- retired v1 terms appear only in history/migration material;
- both fixed candidates receive the required independent GO;
- every affected worktree is clean.

Completion does not mean a Cognitura page was implemented or verified, the Skill
was installed globally, or any change was pushed, published, deployed, merged to
another branch, or released.
