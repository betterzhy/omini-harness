# Java Engineering Standard Skill evaluation summary

- Date: 2026-08-26
- Candidate standard: 0.4.0
- Stable scenarios: 8
- Objective assertions: 31
- Historical `java-spec-governance` snapshot: 20/31 passed
- New `java-engineering-standard`: 31/31 passed

## Method

Two isolated read-only evaluations applied the historical and new Skill to the same prompts in `evals.json`. Each assertion was graded against the produced adoption, selected Profile/rule scope, quality result, Authority preservation, and refused actions. A static skill-creator review viewer was generated in a repository-external temporary workspace to inspect the old/new outputs and grading data.

## Material differences

The new Skill adds independent `ADOPTION`, `APPLICABILITY`, `JAVA_PROFILE_RESULT`, `JAVA_QUALITY_RESULT`, and `AUTHORIZATION` dimensions. It keeps ordinary non-adopted Java questions outside Pack governance, makes unsupported Generated Source evidence fail closed, blocks version drift without a Baseline, prohibits automatic Ratchet Baseline expansion, and does not convert Maven or Java quality results into project completion.

The historical Skill already preserved selected-Profile loading, project Authority precedence, version-drift caution, Maven-versus-quality separation, and no implicit push/publish/deploy. Its recurring failures were the overloaded single result, non-adopted requests routed into governance NO-GO, and no explicit Ratchet NEW-finding invariant.

## Limitations

Some prompts intentionally omit concrete project Authority paths, candidate identities, or evidence bodies. The new Skill therefore reported missing/not-evaluated dimensions instead of inventing those facts. This evaluation checks reasoning and boundary behavior; it does not prove installation, downstream adoption, runtime availability, or project CI execution.

Temporary transcripts, grading workspace, benchmark/viewer HTML, and reviewer artifacts were not committed. Only the stable Eval definition and this aggregate summary are part of the Capability Pack.
