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

Read [`docs/02-DESIGN-INPUT-CONTRACT.md`](../../docs/02-DESIGN-INPUT-CONTRACT.md)
when analyzing input or resolving a Reference conflict. If Figma is unavailable
or unauthenticated, report the prerequisite. Do not log in, borrow a personal
session, or fabricate design context. Tool availability is not integration.

## 4. Perform Design Intake and asset resolution

For HF2, and for the changed regions in HF1:

1. identify route, states, viewports, regions, layout relationships,
   typography, effects, responsive intent, and component reuse;
2. use [`templates/DESIGN_SPEC.md`](../../templates/DESIGN_SPEC.md) when a
   durable intake artifact is appropriate;
3. inventory critical assets with
   [`templates/ASSET_MANIFEST.md`](../../templates/ASSET_MANIFEST.md);
4. resolve assets before pretending the page is visually faithful.

Read [`docs/03-ASSET-FIDELITY-STANDARD.md`](../../docs/03-ASSET-FIDELITY-STANDARD.md)
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

Read [`docs/04-VISUAL-IMPLEMENTATION-STANDARD.md`](../../docs/04-VISUAL-IMPLEMENTATION-STANDARD.md)
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

Read [`docs/05-VISUAL-VERIFICATION-AND-GATES.md`](../../docs/05-VISUAL-VERIFICATION-AND-GATES.md)
for capture/baseline rules and
[`docs/06-RESPONSIVE-AND-ENGINEERING-GATE.md`](../../docs/06-RESPONSIVE-AND-ENGINEERING-GATE.md)
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

Use [`templates/VISUAL_TASK_EVIDENCE.md`](../../templates/VISUAL_TASK_EVIDENCE.md)
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
