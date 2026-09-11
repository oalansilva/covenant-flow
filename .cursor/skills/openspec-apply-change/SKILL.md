---
name: openspec-apply-change
description: Implement tasks from an OpenSpec change. Use when the user wants to start implementing, continue implementation, or work through tasks.
license: MIT
compatibility: Requires openspec CLI.
metadata:
  author: openspec
  version: "1.0"
  generatedBy: "1.5.0"
---

Implement tasks from an OpenSpec change.

**Parent vs child (this repo):** this skill runs **inside** the Em desenvolvimento child, spawned by the parent after `process_event iniciar_apply`. One child per Em desenvolvimento column — the sole Apply child of that column. The parent does not implement. This child MUST NOT call `process_event`, MUST NOT `git commit`/`push`, MUST NOT spawn reviewers. Loop internally until every task is done or a visible P0 blocks the column. Do **not** return control to the parent between tasks. Return task status to the parent only when all tasks are done or a visible P0 is present.

**Store selection:** If the user names a store (a store is a standalone OpenSpec repo registered on this machine) or the work lives in one, run `openspec store list --json` to discover registered store ids, then pass `--store <id>` on the commands that read or write specs and changes (`new change`, `status`, `instructions`, `list`, `show`, `validate`, `archive`, `doctor`, `context`). Other commands do not take the flag. Hints printed by commands already carry the flag; keep it on follow-ups. Without a store, commands act on the nearest local `openspec/` root.

**Input**: Optionally specify a change name. If omitted, check if it can be inferred from conversation context. If vague or ambiguous you MUST prompt for available changes.

**Steps**

1. **Select the change**

   If a name is provided, use it. Otherwise:
   - Infer from conversation context if the user mentioned a change
   - Auto-select if only one active change exists
   - If ambiguous, run `openspec list --json` to get available changes and use the **AskUserQuestion tool** to let the user select

   Always announce: "Using change: <name>" and how to override (e.g., `/opsx-apply <other>`).

2. **Check status to understand the schema**
   ```bash
   openspec status --change "<name>" --json
   ```
   Parse the JSON to understand:
   - `schemaName`: The workflow being used (e.g., "spec-driven")
   - `planningHome`, `changeRoot`, and `actionContext`: planning scope and edit constraints
   - Which artifact contains the tasks (typically "tasks" for spec-driven, check status for others)

3. **Get apply instructions**

   ```bash
   openspec instructions apply --change "<name>" --json
   ```

   This returns:
   - `contextFiles`: artifact ID -> array of concrete file paths (varies by schema - could be proposal/specs/design/tasks or spec/tests/implementation/docs)
   - Progress (total, complete, remaining)
   - Task list with status
   - Dynamic instruction based on current state

   **Handle states:**
   - If `state: "blocked"` (missing artifacts): that is a visible P0 — return it to the parent; do not archive; do not `process_event`
   - If `state: "all_done"`: report all tasks complete to the parent; do not archive; do not `process_event`
   - Otherwise: proceed to implementation. Do not yield to the parent between tasks.

4. **Load sliced apply context (per task)**

   Do **not** read every `contextFiles` path as a single dump. Do **not** read `.impeccable/critique/`.
   For each pending task, load only:
   - that task (checkbox + text in `tasks.md`);
   - the spec file(s) of the capability the task implements;
   - the short apply sections of `design.md`: `## Apply contract`, UI impact, and prototype URL/digest when UI-affected.
   Use `contextFiles` from the CLI only as a path index — open the matching capability spec and the short `design.md` sections, not the whole OpenSpec package or the Impeccable snapshot.

5. **Show current progress**

   Display:
   - Schema being used
   - Progress: "N/M tasks complete"
   - Remaining tasks overview
   - Dynamic instruction from CLI

5b. **UI spec gate (`UI impact: affected`)**

   Before editing any product UI under `frontend/src`:
   - Read `design.md` **and** the approved prototype at `frontend/public/prototypes/<change-or-card-slug>/` (prefer `index.html`). That prototype is the **layout spec**. API contracts drive data/integration only; they MUST NOT replace layout, components, states, density, or a11y.
   - If the prototype path is missing, stop. Do not invent a parallel layout.
   - Record in the card handoff/PR: prototype path, elements followed (layout, controls, states), and any explicit deviation with justification. Absence of this record **blocks apply**.
   - Before moving to Code Review, compare the delivered route vs the approved prototype (layout, components, states, a11y, responsiveness) and record the result. Unjustified drift is a review blocker.

6. **Implement tasks (loop until done or visible P0)**

   This loop runs in the Apply **child**. One child per Em desenvolvimento column (not one spawn per task). Per-task sliced reads stay **inside** this child. «Pause / ask parent» between tasks is **not** the happy path.

   For each pending task:
   - Show which task is being worked on
   - Load that task + matching capability spec + `## Apply contract` (still do not ingest the whole change or `.impeccable/critique/`)
   - Make the code changes required
   - Keep changes minimal and focused
   - Mark task complete in the tasks file: `- [ ]` → `- [x]`
   - Continue to the next task inside this child. Do not return to the parent between tasks.

   **Pause if (visible P0 — this stops the column):**
   - A visible P0 blocks the column (design hole, missing prototype when `UI impact: affected`, unrecoverable error)
   - User interrupts

   **Not a pause (resolve inside this child):**
   - Task is unclear → re-read that task + matching spec + `## Apply contract`; if still blocked, that unclarity **is** a visible P0, not an ask-parent between tasks
   - Implementation reveals a design issue that does not block the remaining tasks → record it and keep looping; if it blocks the column, it is a visible P0

7. **On completion or pause, show status**

   Display:
   - Tasks completed this session
   - Overall progress: "N/M tasks complete"
   - If all done: return to parent for git + `pedir_review`. Do not archive. Do not `process_event`.
   - If paused: only because a visible P0 stopped the column — return that P0. This is not a between-task yield.

**Output During Implementation**

```
## Implementing: <change-name> (schema: <schema-name>)

Working on task 3/7: <task description>
[...implementation happening...]
✓ Task complete

Working on task 4/7: <task description>
[...implementation happening...]
✓ Task complete
```

**Output On Completion**

```
## Implementation Complete

**Change:** <change-name>
**Schema:** <schema-name>
**Progress:** 7/7 tasks complete ✓

### Completed This Session
- [x] Task 1
- [x] Task 2
...

All tasks complete. Return to parent for git + pedir_review. Do not archive. Do not process_event. Do not spawn reviewers.
```

**Output On Pause (P0 visível — pára a coluna; Pause ≠ devolver ao pai entre tasks)**

```
## Implementation Paused — P0 visível

**Change:** <change-name>
**Schema:** <schema-name>
**Progress:** 4/7 tasks complete

### P0 visível
<description of the P0 that stops the column>

Devolve ao pai só porque um P0 visível pára a coluna. Não é yield entre tasks. Não spawnes reviewers. Não `process_event` / commit / push.
```

**Guardrails**
- This skill is the Apply child: no `process_event`, no commit/push, no reviewer spawns
- Keep going through tasks until all are done or a visible P0 stops the column
- Per task: current task + matching capability spec + short `design.md` apply sections — not every `contextFiles` path, not `.impeccable/critique/`
- If a task is unclear, resolve it inside this child (spec + apply contract). Do not return to the parent between tasks. An unclarity that blocks the column is a visible P0, not an ask-parent.
- If implementation reveals a design hole that blocks the column, return that visible P0; otherwise keep looping
- Keep code changes minimal and scoped to each task
- Update task checkbox immediately after completing each task
- Visible P0 / unrecoverable blocker / user interrupt stops the column; «Pause / ask parent» between tasks is not the happy path
- Treat CLI `contextFiles` as a path index, not a dump to ingest in one pass
- For `UI impact: affected`, still read the prototype files from disk as the layout spec (#530)

**Fluid Workflow Integration**

This skill supports the "actions on a change" model:

- **Can be invoked anytime**: Before all artifacts are done (if tasks exist), after partial implementation, interleaved with other actions
- **Allows artifact updates**: If implementation reveals a design hole that does not block the column, record it and keep looping; a blocking hole is a visible P0 returned to the parent, not a between-task ask
