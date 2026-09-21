# Work Handed Off from Claude

## Roles

- Claude main: design, planning, Claude/Codex split.
- Claude Sonnet 5: implement/fix `owner: claude` scope.
- Claude Opus 5 (`high effort`): review Claude-owned implementation.
- Codex GPT-5.6 Terra: implement/test/fix `owner: codex` scope.
- Codex GPT-5.6 Sol (`high effort`): review Codex-owned implementation.
- Codex GPT-6 Astra (`low effort`): final integrated review of all task changes.
- Explicit user instructions override this file.

This file does not switch models automatically. Apply rules by task source/role. If a required model or effort is unavailable, report `blocked`; do not silently substitute.

## App-Handoff Tasks

The main Codex manages requests sent by `workflow.py`.

Before work:
- run the request's claim command and validate the run ID;
- retry only transient state-lock conflicts;
- do not start if the run ID is inactive or already claimed.

Model flow:
1. `gpt-5.6-terra`: implement/test/fix Codex-owned scope.
2. Separate `gpt-5.6-sol` context at `high effort`: review Codex-owned scope.
3. Terra fixes Sol findings; Sol re-reviews.
4. After Codex scope passes, separate `gpt-6-astra` context at `low effort`: final review of the full task diff, including Claude-owned changes already reviewed by Opus.

Rules:
- Required subagents/models are explicitly allowed.
- Child agents do not delegate further.
- Main Codex manages scope, handoff, acceptance criteria, and review loops.
- Review agents do not edit product code.
- Model/effort names describe intended runtime use, not independently verified logs.

## Scope

Use `docs/tasks/<task>/plan.md` ownership markers:
- `owner: claude`: already implemented/reviewed by Claude; do not duplicate.
- `owner: codex`: Codex implementation scope.
- missing/conflicting owner: stop with `needs_design_revision`.

Claude-owned changes are still included in Astra's final integrated review.

If Astra finds a Claude-scope defect, do not edit it. Record location, trigger, impact, and evidence in `review.md`, then finish as `needs_design_revision`.

If Astra finds a Codex-scope defect:
`Terra fix -> Sol(high) re-review -> Astra(low) integrated re-review`.

## State / Execution

Write/update `handoff.md` and `review.md`, then use the request's finish command. Do not mark `complete` before required docs and validation are done.

Use:
- `needs_design_revision` for design changes or Claude-scope rework;
- `blocked` when required execution/validation cannot run.

Never overwrite another run's state if IDs differ. Do not edit state files directly; use `workflow.py` claim/finish commands. Do not recursively invoke Claude or `workflow.py run`. Editing workflow/instruction files does not require a separate feature plan.

## Common Rules

- `docs/tasks/<task>/plan.md` is authoritative.
- Inspect repo instructions and existing changes first.
- Preserve user changes and completed Claude changes.
- Verify plan claims against real code.
- Make local implementation choices freely if requirements remain unchanged.
- If requirements, public interfaces, or major data structures must change, record evidence/options and return to Claude design review.
- Never claim unrun validation passed.
- Sol performs deep Codex-scope review; Astra performs final cross-scope integration review.

## Codex Implementation — GPT-5.6 Terra

1. Validate `plan.md` against the code.
2. Implement only `owner: codex` scope.
3. Run relevant tests.
4. Write/update `docs/tasks/<task>/handoff.md`.

`handoff.md` must include:
- Codex changes
- separation from Claude-owned task changes
- acceptance-criteria status and evidence
- validation commands/results
- skipped validation and reasons
- deviations from plan and reasons
- remaining issues
- review baseline commit and diff scope
- relevant uncommitted/pre-existing user changes

For valid Sol/Astra Codex-scope findings, Terra fixes them, reruns relevant validation, and updates `handoff.md`. If rejecting a finding, record code/test evidence.

## Codex Review — GPT-5.6 Sol (high effort)

Use a separate context at `high effort`. Do not edit product code.

Default scope: `owner: codex` changes. Compare `plan.md`, actual diff, call sites, data flow, and `handoff.md` claims.

Priorities:
- missing Codex requirements
- functional bugs/regressions
- data integrity/error handling
- interface-contract violations
- important test gaps

Findings go to Terra. Sol re-reviews every fix. Do not proceed to Astra while blocking Sol findings remain.

Record this section in `docs/tasks/<task>/review.md`:
`Codex scoped review — Sol (high effort)`.

## Final Integrated Review — GPT-6 Astra (low effort)

After Sol passes the final Codex revision, use a separate Astra context at `low effort`.

Scope: the entire task diff:
- Claude Sonnet changes reviewed by Opus
- Codex Terra changes reviewed by Sol
- interfaces/calls/data flow across both scopes
- all `plan.md` acceptance criteria

Do not edit product code. Prefer integration-level checks over redoing deep local reviews from scratch.

Priorities:
- Claude/Codex integration defects
- missing end-to-end requirements
- interface/data-structure mismatch
- final regressions
- acceptance-criteria mismatch
- obvious defects missed by scoped reviews

Record this section in `review.md`:
`Integrated final review — Astra (low effort)`.

Final `review.md` must include:
- reviewed code version and full diff scope
- Sol scoped-review result
- Astra integrated-review result
- each defect's severity, file/location, trigger, impact, evidence
- confirmed vs suspected findings
- acceptance-criteria verification
- unverified items and reasons
- final status: pass / changes required / validation incomplete

## Completion

Complete only when:
- plan acceptance criteria are met;
- Claude-owned scope, if any, completed Sonnet implementation + Opus (`high effort`) review;
- Codex-owned scope, if any, completed Terra implementation + Sol (`high effort`) review;
- required validation passed;
- blocking findings are resolved;
- Astra (`low effort`) reviewed the final full revision;
- any unrun required validation is marked incomplete.

# Agent Workflow (Codex-Only Tasks)

You are the primary architect and coordinator.

## Primary Model Responsibilities

Use the primary agent for:
- requirements analysis
- architecture
- design decisions
- implementation planning
- reviewing implementation
- debugging strategy
- deciding the next task

## Implementation Delegation

For substantial code implementation/modification:
1. Do not implement directly unless trivial.
2. Delegate to the coding subagent.
3. Provide the plan, relevant files, constraints, and acceptance criteria.
4. Let it implement and test.
5. Review the result.
6. Re-delegate fixes as needed.
7. Continue after implementation succeeds.

Delegate for:
- new modules
- functions/classes
- multi-file changes
- refactors
- tests
- implementation bug fixes

Do not delegate for:
- architecture discussion
- planning
- requirement clarification
- trivial one-line changes
- documentation-only changes
