# Harness Core / Adoption Validation Scope Design

**Status:** APPROVED IN CHAT — awaiting written-spec confirmation

**Date:** 2026-08-31

**Parent design:** `2026-08-30-registered-validator-trust-boundary-design.md`

## Purpose

Close the two P1 findings from the fixed-candidate review without rebinding Pay,
weakening fail-closed behavior, or modifying the Java Pack or Validator:

1. one stale project adoption must not make the Harness core candidate Gate
   unusable;
2. the real-Pay sentinel must prove exact post-verification lock identity drift,
   not merely accept the same public text from an unrelated Pack failure.

This is a fault-domain split, not an allowlist. Every failure remains visible and
blocking in its owning scope.

## Existing defect

`validate` currently loads all external Pack registrations, creates a verification
session, and traverses every `integrations/**` control plane for every invocation.
Consequently an unrelated Pay lock drift makes the entire repository structural
Gate red and can trigger a heavyweight Pack candidate Gate during ordinary Harness
core validation.

Lock verification also catches every `KeyError` or `ValueError` from Pack
verification and wraps it with the same public text used by an exact lock identity
mismatch. The current Pay sentinel checks only that text, so a Validator, toolchain,
source, or TOCTOU failure can incorrectly satisfy the expected-drift test.

## Public validation scopes

Add this CLI option:

```text
harness validate --scope {all,core,adoption}
```

`all` remains the default. Existing invocations without `--scope` preserve their
current report bytes, ordering, exit status, and fail-closed behavior.

### `core`

`core` validates only Harness-owned, project-independent structure:

- repository schemas, canonical registrations, governance and references through
  `validate_repository`;
- learning candidates, experiences and eval structure;
- engineering Registry structure and relationships;
- with `--check-generated`, the design Registry, learning Registry, engineering
  Registry, design active catalog, unified active catalog, and engineering active
  catalog.

`core` must not:

- load external Capability Pack registrations;
- create `CapabilityVerificationSession`;
- enumerate `integrations/**`;
- build project or integration capability locks;
- check project or integration projections;
- build the generated Capability Pack Registry;
- execute any external Pack candidate Gate or toolchain directory digest.

A core report retains `structural-validation-report/v1`. `integrationCount` is `0`
because no adoption roots were enumerated. No new report field is added, preserving
the default `all` report contract; the selected scope is part of the command and
its receipt.

`--project` is an adoption input. `validate --scope core --project ...` is rejected
as a CLI usage error rather than silently ignoring the project.

### `adoption`

`adoption` validates project- and integration-owned consumption boundaries:

- explicitly supplied project control planes and design handoff documents;
- every registered integration control plane, deterministic capability lock, and
  scenario schema;
- with `--check-generated`, supplied project locks and CHATGPT/CODEX projection
  freshness plus the generated Capability Pack Registry;
- external Pack identity, candidate Gate, toolchain, session reuse and fail-closed
  verification required by those adoption checks.

It does not repeat the six local core generated-artifact checks. Adoption failure
returns structural `FAIL` and a nonzero CLI exit even when `core` is green.

### `all`

`all` executes the current core and adoption checks in the current deterministic
order, with one adoption verification session. It preserves existing behavior and
remains red when Pay adoption is stale. It is the compatibility and release-wide
aggregate, not the routine precondition for unrelated project work.

The acceptance sequence distinguishes the boundaries explicitly:

```text
harness validate --scope core --check-generated --format json
harness validate --scope adoption --check-generated --format json
harness validate --scope all --check-generated --format json
```

Harness core candidate acceptance requires `core` green. Adoption status is never
converted to green or omitted; it is reported by `adoption` and `all`.

## Internal error classification

Add a private `ValueError` subtype in `project.py` for genuine external lock
registration drift after the relevant facts are available. Its `str(error)` remains
exactly:

```text
external capability pack lock registration drift: <capability-id>
```

The typed drift covers real registration-drift branches such as internal/external
identity collision, missing verified entry after successful collection, exact
lock-vs-registration source identity mismatch, and locator-bound witness mismatch.

Failures while obtaining the verified Pack are not retyped as registration drift.
Validator nonzero exit, toolchain mismatch, unavailable source, registration
failure, session poisoning and TOCTOU failure retain their original cause beneath
the compatibility wrapper. Public callers still receive a `ValueError` with the
existing message, so this change does not weaken or broaden the public API.

## Exact real-Pay sentinel

The sentinel keeps the real Pay shadow and source read-only and uses one explicit
`CapabilityVerificationSession`:

1. obtain the registered Java Pack successfully in that session;
2. assert exactly one verified Pack, candidate Gate and isolated checkout;
3. execute the real integration scenario with the same session;
4. accept only the private typed registration-drift error with the exact existing
   public text;
5. assert the validation counters do not grow and the Pay source Git state is
   unchanged.

A deterministic negative test forces Pack verification failure and proves that it
remains fail-closed but is not the typed registration-drift error. Thus an unrelated
Validator/toolchain/source failure makes the sentinel fail rather than false-PASS.

## Compatibility and security invariants

- `validate` without `--scope` remains identical to `--scope all`.
- `all` and `adoption` remain fail-closed for Pay drift and Pack failures.
- `core` does not claim any project adoption is valid, current, or authorized.
- No skip, xfail, integration allowlist, ignored path, or last-error suppression is
  introduced.
- Immutable source commit/tree/content, Validator identity, toolchain identity,
  `capability-lock/v2`, exact lock fingerprint and locator exclusion are unchanged.
- Runtime scratch, session scope, invalidation and TOCTOU behavior are unchanged.
- Closed scenarios still exclude Java and all business execution remains `DENY`.
- No Pay shadow, real Pay, Java Pack, Validator, App, Authority, Skill, projection
  business semantics, merge, push, release, deploy, or execution permission changes.

## Exact WriteSet

Expected production/documentation files:

- `src/evolution_harness/assurance.py`
- `src/evolution_harness/cli.py`
- `src/evolution_harness/project.py`
- `README.md`

Expected tests:

- `tests/test_assurance_cli.py`
- `tests/test_lock_enforcement.py`
- `tests/test_pay_nexus_java_capability_adoption_pilot.py`

The parent spec, implementation plan and SDD evidence ledger may be amended for
traceability. No generated artifact, Registry, lock, projection, integration shadow,
Pack or Validator file belongs to this WriteSet.

## Test and acceptance contract

TDD must first establish RED for:

- `core` not invoking Pack registration/session/integration/candidate Gate paths;
- unavailable or mutated Pack leaving `core` green while `adoption` and `all` fail;
- default `all` report bytes remaining equal to the pre-change report;
- `core --project` being rejected;
- core/adoption generated checks detecting drift only in their owning artifacts;
- Pack verification failure not being the typed registration-drift error;
- real Pay sentinel requiring successful Pack verification and the typed exact
  post-verification mismatch.

GREEN and regression require:

- focused assurance CLI and lock tests;
- mutation, session and TOCTOU regression;
- Pack-E2E lane with the exact real-Pay sentinel;
- `validate --scope core --check-generated` exit `0` on the fixed candidate;
- `validate --scope adoption --check-generated` and default `all` retaining the
  exact Pay adoption drift failure and nonzero exit;
- a full unfiltered pytest terminal result;
- fixed Candidate/Parent/Tree, clean status, hashed receipts, and a new independent
  `deep_reviewer / xhigh` verdict with P0/P1 equal to zero.

The earlier 90.9147% fixed-baseline performance result remains evidence with its
disclosed historical provenance limitation. This amendment must not claim a new
candidate-bound baseline unless a new complete baseline is actually captured.

## Rejected alternatives

### Rebind or regenerate Pay shadow

Rejected because it changes Pay adoption truth and requires separate Pay Authority.

### Make `core` silently ignore an integration allowlist

Rejected because hidden exclusions make a red adoption appear green. The scope is
explicit, machine-selected and separately receipted.

### Change default validation to `core`

Rejected because existing automation expects aggregate fail-closed behavior. Default
remains `all`; projects opt into the narrower routine core Gate explicitly.

### Accept only the public drift string in the sentinel

Rejected because different failures currently share that compatibility message. The
sentinel must require successful Pack verification plus the typed exact mismatch.
