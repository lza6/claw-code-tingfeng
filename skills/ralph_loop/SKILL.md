---
name: ralph_loop
description: Self-referential loop until task completion with architect verification - RALPH style persistence loop
---

[RALPH LOOP - ITERATION {{ITERATION}}/{{MAX}}]

Your previous attempt did not output the completion promise. Continue working on the task.

<Purpose>
Ralph is a persistence loop that keeps working on a task until it is fully complete and architect-verified. It wraps parallel execution with session persistence, automatic retry on failure, and mandatory verification before completion.
</Purpose>

<Use_When>
- Task requires guaranteed completion with verification (not just "do your best")
- User says "ralph", "don't stop", "must complete", "finish this", or "keep going until done"
- Work may span multiple iterations and needs persistence across retries
- Task benefits from parallel execution with architect sign-off at the end
</Use_When>

<Do_Not_Use_When>
- User wants a full autonomous pipeline from idea to code -- use `autopilot` instead
- User wants to explore or plan before committing -- use `plan` skill instead
- User wants a quick one-shot fix -- delegate directly to an executor agent
- User wants manual control over completion -- use `ultrawork` directly
</Do_Not_Use_When>

<Why_This_Exists>
Complex tasks often fail silently: partial implementations get declared "done", tests get skipped, edge cases get forgotten. Ralph prevents this by looping until work is genuinely complete, requiring fresh verification evidence before allowing completion, and using tiered architect review to confirm quality.
</Why_This_Exists>

<Execution_Policy>
- Fire independent agent calls simultaneously -- never wait sequentially for independent work
- Use `run_in_background: true` for long operations (installs, builds, test suites)
- Always pass the `model` parameter explicitly when delegating to agents
- Deliver the full implementation: no scope reduction, no partial completion, no deleting tests to make them pass
- Default to concise, evidence-dense progress and completion reporting unless the user or risk level requires more detail
- Treat newer user task updates as local overrides for the active workflow branch while preserving earlier non-conflicting constraints
- If correctness depends on additional inspection, retrieval, execution, or verification, keep using the relevant tools until the execution loop is grounded
- Continue through clear, low-risk, reversible next steps automatically; ask only when the next step is materially branching, destructive, or preference-dependent
</Execution_Policy>

<Steps>
0. **Pre-context intake (required before planning/execution loop starts)**:
   - Assemble or load a context snapshot at `.clawd/context/{task-slug}-{timestamp}.md`.
   - Minimum snapshot fields:
     - task statement
     - desired outcome
     - known facts/evidence
     - constraints
     - unknowns/open questions
     - likely codebase touchpoints
   - If an existing relevant snapshot is available, reuse it and record the path in Ralph state.
   - If request ambiguity is high, gather brownfield facts first. Use `deepsearch` for repository lookups. Then run `$deep-interview --quick <task>` to close critical gaps.
   - Do not begin Ralph execution work until snapshot grounding exists.
1. **Review progress**: Check TODO list and any prior iteration state
2. **Continue from where you left off**: Pick up incomplete tasks
3. **Delegate in parallel**: Route tasks to specialist agents at appropriate tiers
   - Simple lookups: LOW tier -- "What does this function return?"
   - Standard work: STANDARD tier -- "Add error handling to this module"
   - Complex analysis: THOROUGH tier -- "Debug this race condition"
4. **Run long operations in background**: Builds, installs, test suites use `run_in_background: true`
5. **Visual task gate (when screenshot/reference images are present)**:
   - Run `$visual-verdict` **before every next edit**.
   - Require structured JSON output: `score`, `verdict`, `category_match`, `differences[]`, `suggestions[]`, `reasoning`.
   - Persist verdict to `.clawd/state/ralph-progress.json` including numeric + qualitative feedback.
   - Default pass threshold: `score >= 90`.
6. **Verify completion with fresh evidence**:
   a. Identify what command proves the task is complete
   b. Run verification (test, build, lint)
   c. Read the output -- confirm it actually passed
   d. Check: zero pending/in_progress TODO items
7. **Architect verification** (tiered):
   - <5 files, <100 lines with full tests: STANDARD tier minimum (architect role)
   - Standard changes: STANDARD tier (architect role)
   - >20 files or security/architectural changes: THOROUGH tier (architect role)
   - Ralph floor: always at least STANDARD, even for small changes
7.5 **Mandatory Deslop Pass**:
   - After Step 7 passes, run `ai-slop-cleaner` on **all files changed during the Ralph session**.
   - Scope the cleaner to **changed files only**; do not widen the pass beyond Ralph-owned edits.
   - If the prompt contains `--no-deslop`, skip Step 7.5 entirely.
7.6 **Regression Re-verification**:
   - After the deslop pass, re-run all tests/build/lint and read the output to confirm they still pass.
   - If post-deslop regression fails, roll back cleaner changes or fix and retry. Then rerun Step 7.5 and Step 7.6 until the regression is green.
8. **On approval**: Clean exit and clean up all state files
9. **On rejection**: Fix the issues raised, then re-verify at the same tier
</Steps>

<Tool_Usage>
- Before first MCP tool use, call `ToolSearch("mcp")` to discover deferred MCP tools
- Use architect verification when changes are security-sensitive, architectural, or involve complex multi-system integration
- Skip architect consultation for simple feature additions, well-tested changes, or time-critical verification
- Use state persistence tools for ralph mode state between iterations
- Persist context snapshot path in Ralph mode state so later phases and agents share the same grounding context
</Tool_Usage>

## State Management

Use the state MCP server tools or file-based state for Ralph lifecycle state:

- **On start**: Write state with `mode: "ralph", active: true, iteration: 1, max_iterations: 10`
- **On each iteration**: Update iteration count and current phase
- **On completion**: Mark as complete and cleanup
- **On cancellation**: Clear all state files

## Scenario Examples

**Good:** The user says `continue` after the workflow already has a clear next step. Continue the current branch of work instead of restarting or re-asking the same question.

**Good:** The user changes only the output shape or downstream delivery step. Preserve earlier non-conflicting workflow constraints and apply the update locally.

**Bad:** The user says `continue`, and the workflow restarts discovery or stops before the missing verification/evidence is gathered.

<Examples>
<Good>
Correct parallel delegation:
```
delegate(role="executor", tier="LOW", task="Add type export for UserConfig")
delegate(role="executor", tier="STANDARD", task="Implement the caching layer for API responses")
delegate(role="executor", tier="THOROUGH", task="Refactor auth module to support OAuth2 flow")
```
Why good: Three independent tasks fired simultaneously at appropriate tiers.
</Good>

<Good>
Correct verification before completion:
```
1. Run: pytest           → Output: "42 passed, 0 failed"
2. Run: ruff check      → Output: 0 errors
3. Run: mypy           → Output: No errors
4. Delegate to architect at STANDARD tier  → Verdict: "APPROVED"
```
Why good: Fresh evidence at each step, architect verification, then clean exit.
</Good>

<Bad>
Claiming completion without verification:
"All the changes look good, the implementation should work correctly. Task complete."
Why bad: Uses "should" and "look good" -- no fresh test/build output, no architect verification.
</Bad>

<Bad>
Sequential execution of independent tasks:
```
delegate(executor, LOW, "Add type export") → wait →
delegate(executor, STANDARD, "Implement caching") → wait →
delegate(executor, THOROUGH, "Refactor auth")
```
Why bad: These are independent tasks that should run in parallel, not sequentially.
</Bad>
</Examples>

<Escalation_And_Stop_Conditions>
- Stop and report when a fundamental blocker requires user input (missing credentials, unclear requirements, external service down)
- Stop when the user says "stop", "cancel", or "abort"
- Continue working when iteration continues
- If architect rejects verification, fix the issues and re-verify (do not stop)
- If the same issue recurs across 3+ iterations, report it as a potential fundamental problem
</Escalation_And_Stop_Conditions>

<Final_Checklist>
- [ ] All requirements from the original task are met (no scope reduction)
- [ ] Zero pending or in_progress TODO items
- [ ] Fresh test run output shows all tests pass
- [ ] Fresh build/lint output shows success
- [ ] Architect verification passed (STANDARD tier minimum)
- [ ] ai-slop-cleaner pass completed on changed files (or --no-deslop specified)
- [ ] Post-deslop regression tests pass
</Final_Checklist>

<Advanced>
## PRD Mode (Optional)

When the user provides the `--prd` flag, initialize a Product Requirements Document before starting the ralph loop.

### Detecting PRD Mode
Check if the prompt contains `--prd` or `--PRD`.

### Detecting `--no-deslop`
Check if the prompt contains `--no-deslop`. If present, skip the deslop pass.

### Visual Reference Flags (Optional)
Ralph execution supports visual reference flags for screenshot tasks:
- Image inputs: `-i <image-path>`
- Image directory input: `--images-dir <directory>`

### PRD Workflow
1. Parse the task (everything after `--prd` flag)
2. Create canonical PRD artifacts:
   - PRD: `.clawd/plans/prd-{slug}.md`
   - Progress ledger: `.clawd/state/ralph-progress.json`
3. Break down into user stories with acceptance criteria
4. Initialize progress ledger
5. Proceed to normal ralph loop using user stories as the task list

## Background Execution Rules

**Run in background** (`run_in_background: true`):
- Package installation (pip install, cargo build)
- Build processes (make, project build commands)
- Test suites
- Docker operations (docker build, docker pull)

**Run blocking** (foreground):
- Quick status checks (git status, ls, pwd)
- File reads and edits
- Simple commands
</Advanced>

Original task:
{{PROMPT}}