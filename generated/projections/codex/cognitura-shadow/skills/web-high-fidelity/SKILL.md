---
name: web-high-fidelity
description: Use for high-fidelity Web page implementation, reconstructing rendered UI from screenshots or Figma, correcting visual differences, reviewing real-browser screenshots, evaluating visual regression or baseline changes, and resolving critical visual assets. Select the smallest HF0/HF1/HF2 flow. Do not trigger the full visual workflow for ordinary backend-only work, non-visual documentation, or changes proven to have no substantive rendered-UI impact.
---

# Web High-Fidelity

Turn an explicit visual Reference into target-owned browser evidence while
preserving the target repository's architecture, Authority, and completion
boundary.

## 1. Establish target authority first

Before choosing a flow or editing code, read the target repository's:

- applicable Authority and task scope;
- stack, routes, state model, and data fixtures;
- component library, design system, tokens, fonts, icons, and assets;
- CSS/layout conventions and responsive strategy;
- test, build, browser, screenshot, and accessibility methods;
- baseline ownership and review policy.

Do not invent commands, dependencies, paths, thresholds, or acceptance rules.
Target Authority prevails over this Skill.

## 2. Select the smallest visual-flow profile

Use the decision table:

| Profile | Select when | Evidence burden |
| --- | --- | --- |
| HF0 | No visual Reference is specified and there is no substantive rendered-UI change | No visual evidence created by this Skill; follow target engineering rules |
| HF1 | A bounded visual change affects an already accepted page, and evidence proves no composition, critical-asset, shared-component, or new-state impact | Focused real-browser evidence for affected regions/states/viewports |
| HF2 | New page, reconstruction, refactor, critical asset, shared component, multiple states/viewports, or uncertain impact | Full intake, asset, implementation, browser comparison, correction, and evidence flow |

Unknown impact selects HF2. That choice increases visual analysis only; it does
not widen the authorized WriteSet or replace the project's risk classification.

Do not assume HF1 from change size alone. State the qualification evidence. A
backend-only change with no rendered-UI impact is HF0 and should not acquire a
visual-evidence burden.

## 3. Declare the Reference

For HF1/HF2, declare one mode with identity and revision:

- `IMAGE_REFERENCE` for a designated screenshot/image;
- `FIGMA_REFERENCE` for authorized and authenticated Figma design evidence;
- `HYBRID_REFERENCE` for Figma structure/tokens/assets plus an explicit image
  as the perceptual target.

Read the [Design Input Contract](#appendix-design-input-contract)
when analyzing input or resolving a Reference conflict. If Figma is unavailable
or unauthenticated, report the prerequisite. Do not log in, borrow a personal
session, or fabricate design context. Tool availability is not integration.

## 4. Perform Design Intake and asset resolution

For HF2, and for the changed regions in HF1:

1. identify route, states, viewports, regions, layout relationships,
   typography, effects, responsive intent, and component reuse;
2. use the [Design Intake template](#appendix-design-intake-template) when a
   durable intake artifact is appropriate;
3. inventory critical assets with
   [Asset Manifest template](#appendix-asset-manifest-template);
4. resolve assets before pretending the page is visually faithful.

Read the [Asset Fidelity Standard](#appendix-asset-fidelity-standard)
when the Reference contains brand artwork, photos, product screenshots,
textures, complex meshes/glows, 3D visuals, or distinctive iconography.

An unresolved critical asset remains `ASSET_UNRESOLVED`. Never replace it with
an emoji, arbitrary icon, generic gradient, stock visual, or placeholder.
Generate a dedicated asset only when target Authority permits that capability;
never use a generated screenshot to impersonate an interactive page.

## 5. Implement in visual priority order

Reuse target components, tokens, and assets. Work in this order:

1. P0 Composition
2. P1 Geometry
3. P2 Typography
4. P3 Assets
5. P4 Color
6. P5 Effects
7. P6 Micro Details

Prefer real Grid/Flex/flow/sticky relationships over screenshot-shaped absolute
positioning. Preserve state correctness, responsiveness, accessibility, and
maintainability. For longer pages, close high-priority differences region by
region, then review the whole page.

Read the [Visual Implementation Standard](#appendix-visual-implementation-standard)
only when implementing or correcting rendered UI.

## 6. Require real-browser evidence

HF1/HF2 cannot receive visual PASS without a real target application rendered
in a real browser.

1. use the declared route, state, and viewport;
2. record browser/version, device scale, locale, timezone, and color scheme;
3. wait for fonts and critical images;
4. stabilize animation, timestamps, random content, and fixtures;
5. capture target-owned actual evidence;
6. compare Reference and actual side by side, adding a diff when useful;
7. register mismatches and correct the highest material P0-P6 issue;
8. recapture until material differences are closed or explicitly limited;
9. verify responsive and accessibility evidence required by target Authority.

Read [Visual Verification and Results](#appendix-visual-verification-and-results)
for capture/baseline rules and
[Responsive, Accessibility, and Engineering Evidence](#appendix-responsive-accessibility-and-engineering-evidence)
when responsive, accessibility, or target-command evidence applies.

Playwright, Storybook, Figma, browser automation, and image-diff tools are
optional. A CLI being installed does not prove the target has configured it.
Do not install dependencies or change configuration without target authority.

## 7. Protect baseline ownership

Do not create or update a visual-regression baseline merely because a test
fails. First prove an intentional design change, the exact render identity, and
the target project's authorized review. Treat reference/actual/diff paths as
target evidence, not source-pack files.

## 8. Record bounded results

Use the [Visual Task Evidence template](#appendix-visual-task-evidence-template)
in the target-owned evidence location when durable evidence is required.

Report exactly the applicable values:

```text
VISUAL_CAPABILITY_RESULT=PASS|FAIL|PASS_WITH_KNOWN_LIMITATION
TARGET_ENGINEERING_RESULT=PASS|FAIL|NOT_RUN
```

Visual PASS requires real-browser evidence. Engineering PASS comes only from
target-approved commands actually run. Explain NOT_RUN and all known
limitations.

These results are evidence only. Never interpret them as authorization to mark
the target task complete, merge, update a baseline, push, deploy, publish, or
release.

## 9. Safety limits

Do not automatically:

- install packages, browsers, plugins, MCP servers, or CLIs;
- authenticate Figma or another external service;
- use a personal signed-in browser session;
- create or update a baseline;
- expand the target WriteSet;
- push, deploy, publish, release, or merge;
- declare the target task complete.

If required authentication, target Authority, Reference identity, route/state,
browser access, or critical asset is missing, report the precise prerequisite
and preserve the bounded result semantics.

<a id="appendix-design-input-contract"></a>
## Appendix A: Design Input Contract

Declare one Reference mode plus a stable identity/revision.

### `IMAGE_REFERENCE`

Extract canvas/viewport, region boundaries, composition, typography, geometry,
effects, assets, and responsive clues. A screenshot is perceptual evidence; it
does not reveal layout intent, component APIs, breakpoints, or asset provenance.

### `FIGMA_REFERENCE`

When authorized and authenticated, inspect frame/layer dimensions, Auto Layout,
variables, typography, fills/effects, components, assets, annotations, and Code
Connect mappings. Reuse target-project components and tokens before creating new
ones. If stable identity or authentication is missing, report the prerequisite;
do not authenticate automatically or invent results.

### `HYBRID_REFERENCE`

Use Figma for structure, components, tokens, and assets; use the designated image
for final perceptual composition. Resolve revision conflicts explicitly rather
than constructing a third design from incompatible inputs.

### Design Intake output

Before material implementation, record:

- Reference mode, identity, and revision;
- target route, states, and viewports;
- regions and component-reuse candidates;
- typography, layout, tokens, effects, and responsive intent;
- asset inventory and unresolved items;
- known uncertainties and target engineering constraints.

Use the [Design Intake template](#appendix-design-intake-template) and
[Asset Manifest template](#appendix-asset-manifest-template) as needed.

<a id="appendix-asset-fidelity-standard"></a>
## Appendix B: Asset Fidelity Standard

High-information visual assets must not be degraded into cheap approximations.

### Resolution order

```text
Existing target asset
-> Authorized Figma export
-> Faithful extraction from the designated Reference
-> Authorized dedicated asset generation
-> ASSET_UNRESOLVED
```

Normal layout, buttons, borders, standard gradients, and common shadows may be
CSS/DOM primitives. Brand artwork, photos, product screenshots, textures,
complex mesh/glow fields, 3D renders, and distinctive iconography generally
require real SVG/image assets.

`ASSET_UNRESOLVED_REJECTS_PLACEHOLDER`: unresolved critical assets remain an
explicit limitation or failure. Do not substitute emoji, arbitrary icons, flat
blocks, generic gradients, stock artwork, or placeholders.

If target Authority permits image generation, generate a dedicated asset that
fits the real DOM layout. Never generate a whole-page screenshot to impersonate
an interactive page.

Record role, source identity, authorized target path, intrinsic dimensions,
crop/object positioning, responsive variants, and fidelity status in the
[Asset Manifest template](#appendix-asset-manifest-template).

<a id="appendix-visual-implementation-standard"></a>
## Appendix C: Visual Implementation Standard

Implement with the target project's existing architecture, components, tokens,
CSS strategy, fonts, assets, and state model. Do not rewrite a component merely
because a visually similar one is easier to invent.

### Priority

1. **P0 Composition** - information hierarchy, section order, first-screen
   balance, dominant visual scale, density.
2. **P1 Geometry** - container, grid/flex relationships, dimensions, spacing,
   alignment, radius, overlap.
3. **P2 Typography** - font files, axes/weights, size, line height, tracking,
   wrapping, text measure.
4. **P3 Assets** - identity, ratio, crop, mask, scale, object positioning.
5. **P4 Color** - backgrounds, surfaces, text, borders, alpha, state colors.
6. **P5 Effects** - shadow layers, inner highlights, blur, glow, gradients,
   texture.
7. **P6 Micro Details** - one-pixel alignment, separators, optical offsets.

Use real Grid/Flex/flow/sticky relationships for responsive layout. Do not
hard-code a desktop screenshot as an absolute-positioned page. Preserve focus,
semantics, contrast, reduced motion, keyboard access, and dynamic states while
matching the visual target.

When a page is large, implement and review regions independently, then perform
a full-page browser review. Correct the highest-priority material mismatch
before tuning lower-priority details.

<a id="appendix-visual-verification-and-results"></a>
## Appendix D: Visual Verification and Results

`REAL_BROWSER_EVIDENCE_REQUIRED`: a visual PASS requires the real target
application rendered in a real browser. Static code inspection, a build, unit
tests, a CLI being installed, or a design-tool response cannot substitute.

### Stabilize the capture

Record and stabilize as applicable:

- route, state, and data fixtures;
- viewport and device scale;
- browser name/version and rendering mode;
- fonts and critical image loading;
- locale, timezone, and color scheme;
- animation, reduced motion, timestamps, random content, and authentication.

### Compare and correct

Capture the target-owned actual image and compare it with the designated
Reference at the same intended viewport. Produce a diff when useful. Maintain a
mismatch register with priority, region, difference, cause, action, and status.
Correct in P0-P6 order and repeat capture until material differences are closed
or recorded as known limitations.

### Baselines

An accepted target-project render may become a regression baseline only through
the target's review policy. Never update a baseline because a test failed or to
improve a score without an intentional design change. Environment-specific
snapshot identity and tolerances remain target-owned configuration.

### Bounded results

Use:

```text
VISUAL_CAPABILITY_RESULT=PASS|FAIL|PASS_WITH_KNOWN_LIMITATION
TARGET_ENGINEERING_RESULT=PASS|FAIL|NOT_RUN
```

Visual PASS requires real-browser evidence and no unaccepted material mismatch.
Known limitations must identify their evidence and impact. Engineering results
come only from target-approved commands. Neither result grants completion,
merge, deployment, publication, or release.

<a id="appendix-responsive-accessibility-and-engineering-evidence"></a>
## Appendix E: Responsive, Accessibility, and Engineering Evidence

The target repository owns acceptance thresholds and commands. The Capability
Pack supplies questions and evidence categories, not a universal project gate.

### Responsive evidence

Verify the viewports and states required by target Authority. Check content
priority, reflow, navigation behavior, typography, asset crops, overflow,
touch targets, stacking, and breakpoint transitions. A desktop screenshot alone
does not prove responsive behavior.

### Accessibility evidence

Preserve semantic structure, labels, keyboard operation, visible focus,
contrast, reduced motion, zoom/reflow, meaningful alternatives for visual
assets, and state announcements where applicable. Record the target checks that
were actually run; do not infer compliance from visual similarity.

### Engineering evidence

Use only existing or explicitly authorized target commands for lint, typecheck,
unit/integration tests, build, browser tests, or component tests. CLI presence in
the environment does not mean the project has integrated it. If commands are not
run, report `TARGET_ENGINEERING_RESULT=NOT_RUN` and the reason.

Do not trade maintainability, component APIs, state correctness, accessibility,
or responsive behavior for a smaller pixel diff. Visual and engineering results
remain separate evidence inputs to target Authority.

<a id="appendix-design-intake-template"></a>
## Appendix F: Design Intake Template

### Target context

- Target Authority reference:
- Stack / component library / design system:
- Existing browser and test approach:
- Authorized WriteSet:

### Reference

- Mode: `IMAGE_REFERENCE | FIGMA_REFERENCE | HYBRID_REFERENCE`
- Identity:
- Revision:
- Conflict or prerequisite status:

### Scope

- Route:
- States:
- Viewports:
- Regions:

### Visual system

- Composition and layout relationships:
- Typography and font assets:
- Token/component mapping:
- Effects and backgrounds:
- Responsive intent:
- Accessibility constraints:

### Assets and uncertainty

- Asset manifest: [Asset Manifest template](#appendix-asset-manifest-template)
- Critical unresolved items:
- Known uncertainties:
- Selected visual profile: `HF0 | HF1 | HF2`
- Profile qualification evidence:

<a id="appendix-asset-manifest-template"></a>
## Appendix G: Asset Manifest Template

| Region | Role | Source identity | Authorized target path | Intrinsic size | Crop / position | Responsive variants | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  | `RESOLVED | ASSET_UNRESOLVED` |

### Rules

- Reuse target assets and components before introducing new assets.
- Preserve source identity/revision when an asset comes from Figma or a
  designated Reference.
- `ASSET_UNRESOLVED` remains a failure or named limitation; do not use a
  placeholder, arbitrary icon, emoji, generic gradient, or screenshot-as-page.
- Store assets only in paths authorized by the target repository.

<a id="appendix-visual-task-evidence-template"></a>
## Appendix H: Visual Task Evidence Template

This record belongs to the target project's authorized task evidence location.
It is not a capability adoption, source lock, project binding, or completion
decision.

### Application identity

- Application commit:
- Application tree:
- Application worktree clean: `true | false`
- Dirty preview identity, when explicitly allowed by target Authority:

### Reference identity

- Mode: `IMAGE_REFERENCE | FIGMA_REFERENCE | HYBRID_REFERENCE`
- Identity:
- Revision:
- Authentication / availability prerequisites:

### Render identity

- Route:
- State / fixture:
- Viewports:
- Browser and version:
- Device scale:
- Locale:
- Timezone:
- Color scheme:
- Rendering mode:

### Relevant inputs

- Assets and source identities:
- Fonts and loaded weights/axes:
- Animation / volatile data stabilization:

### Visual evidence

- Reference paths and summary:
- Actual paths and summary:
- Diff paths and summary:
- Mismatch register (priority, region, difference, cause, action, status):
- Known limitations:

### Target engineering evidence

- Target-approved commands actually run:
- Evidence/receipt references:
- Not-run reason:

### Bounded results

```text
VISUAL_CAPABILITY_RESULT=PASS|FAIL|PASS_WITH_KNOWN_LIMITATION
TARGET_ENGINEERING_RESULT=PASS|FAIL|NOT_RUN
```

Even two PASS values do not authorize completion, merge, baseline update,
deployment, publication, or release.
