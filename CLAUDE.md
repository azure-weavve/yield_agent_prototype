# Claude + Codex Workflow

## Next task — user decision (2026-09-20, supersedes the 2026-09-17 note)

`pooling-mh-score` is complete and merged (main `7f3715b`, 2026-09-21).
Read [docs/next_step_claude.md](docs/next_step_claude.md) before selecting or starting the next task. It holds the adopted P0-P4 order.
The next task is **P1-3: secure 3-5 past yield-excursion cases**, using [docs/P1-3-원천추출-요청서.md](docs/P1-3-원천추출-요청서.md). Then P1-4: load them into a separate DB and run the commonality tools directly, without the LLM.
Follow-up questions and data recommendations ([docs/NEXT_TASK.md](docs/NEXT_TASK.md)) remain agreed work, but now come **after** P1-4: the real cases decide which follow-ups are worth building. Multi-agent (F) remains a user goal and must not be re-litigated; only its position moved, to after the P3 structural decisions (`where` port, group-injection contract).

## Gate verdict semantics - frozen (2026-09-20)

Do not add to or refine finalize gate verdict semantics - verdict names, lower bounds,
verdict-sentence wording, rejection reasons - unless evidence from a real historical case
requires it.

Rationale: from 2026-08-20 to 09-16 the six files with the largest change volume were all
gate semantics and their tests (`graph/nodes.py`, `graph/evidence.py`, `llm/client.py` and
their tests). They were validated only against dummy data and the mock LLM, so further
refinement has no information source and a green suite cannot show it is right.

Exempt: bug fixes; work already in flight (`pooling-mh-score`); and any change demanded by
evidence from a real case. Lifting the freeze is a user decision.
See [docs/next_step_claude.md](docs/next_step_claude.md) (P0-2).

## Roles

- Claude main: requirements, design, planning, task split, coordination.
- Claude Sonnet 5: implement/test/fix `owner: claude` work.
- Claude Opus 5 (`high effort`): independently review Claude-owned work.
- Codex GPT-5.6 Terra: implement/test/fix `owner: codex` work.
- Codex GPT-5.6 Sol (`high effort`): independently review Codex-owned work.
- Codex GPT-6 Astra (`low effort`): final integrated review of all task changes.
- Explicit user instructions override this file.

This file does not switch models automatically. Use the runtime's model/subagent controls. If a required model or effort is unavailable, report it; do not silently substitute.

## Claude Main

Inspect the repository and relevant code before designing. Split work into independently implementable Claude/Codex scopes.

Rules:
- Do not split tightly coupled logic or the same file without a good reason.
- Mark every implementation step in `plan.md` as `owner: claude` or `owner: codex`.
- Avoid duplicate implementation across Claude and Codex.
- Record shared interfaces, dependencies, ordering, and handoff contracts.
- Astra reviews the full task diff, not only Codex changes.

## Plan

Write `docs/tasks/<task>/plan.md` with:
- goal and requirements
- in/out of scope
- base branch/commit
- relevant pre-existing uncommitted changes
- current structure and relevant files
- design decisions and rationale
- interface/data-structure changes and compatibility constraints
- ordered implementation steps with owner
- Claude/Codex dependencies and handoff conditions
- failure/edge-case behavior
- tests and verifiable acceptance criteria
- open questions and assumptions

Separate implementation freedom from design decisions that require re-review. Separate verified code facts from assumptions.

## Claude Implementation — Sonnet 5

For `owner: claude` steps:
1. Validate `plan.md` against the code.
2. Implement only Claude-owned scope.
3. Run relevant tests.
4. Do not pre-implement Codex-owned scope.
5. Record results and validation in a handoff-ready form.

If requirements, public interfaces, or major data structures must change, return the decision to Claude main instead of expanding scope silently.

## Claude Review — Opus 5 (high effort)

After Sonnet implementation, use a separate Opus 5 context at `high effort` to review Claude-owned changes only.

Check:
- requirements / `plan.md`
- functional bugs and regressions
- interface/data-flow consistency
- error handling and data integrity
- missing/invalid tests
- Claude/Codex contract violations

The reviewer must not edit product code. Findings go back to Sonnet for fixes, then Opus re-reviews until no blocking Claude-scope findings remain.

## Design Revisions

If Claude, Opus, Codex, or Astra finds a design flaw or requirement conflict, inspect the code evidence and update `plan.md` when needed. Record rationale/impact and explicitly note any relaxed acceptance criteria.

## Handoff to Codex

If implementation was requested, hand off only when:
- `plan.md` exists;
- any Claude-owned implementation is complete;
- any Claude-owned implementation passed Opus 5 (`high effort`) review and required fixes;
- Codex scope and acceptance criteria are explicit.

Do not hand off design-only work or work blocked by unresolved decisions.

From repo root:

```powershell
python workflow.py run --task "docs/tasks/<task>" --dry-run
python workflow.py run --task "docs/tasks/<task>"
```

The first command verifies the handoff target; the second dispatches it. `workflow.py` uses the `thread_id` in `workflow-config.json`; use explicit config or `--thread` for another conversation.

Codex must follow AGENTS.md for handed-off work:
1. Terra implements/tests `owner: codex` scope.
2. Sol (`high effort`) reviews Codex-owned changes.
3. Terra fixes Sol findings; Sol re-reviews.
4. Astra (`low effort`) performs one final integrated review of all Claude + Codex changes.
5. Codex-scope Astra finding: Terra fix -> Sol re-review -> Astra final re-review.
6. Claude-scope Astra finding: Codex must not edit it; record evidence and return for Claude rework.

A successful `run` means accepted for processing, not complete. Do not resend while queued. Do not concurrently modify the same repo code/plan during the Codex run.

Status:

```powershell
python workflow.py status --task "docs/tasks/<task>"
python workflow.py wait --task "docs/tasks/<task>" --timeout 3600
```

A wait timeout does not cancel the job. Check status instead of resending.

Final states:
- `complete`: report implementation, validation, and remaining limits.
- `queued` / `running`: not complete.
- `dispatch_unknown`: inspect the target conversation; do not auto-resend.
- `needs_design_revision`: inspect evidence. For Claude code, Sonnet fixes -> Opus (`high effort`) re-reviews -> hand off again. Update `plan.md` if design changed.
- `blocked`: inspect logs/reason. Do not bypass auth, permissions, or model requirements with silent substitutions.

Do not repeat a stalled design loop without new information. Re-running dispatches a new request and does not cancel the old one. See `docs/codex-handoff.md` for prerequisites and result files.
