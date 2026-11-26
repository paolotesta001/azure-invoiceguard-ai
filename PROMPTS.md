# PROMPTS.md — Prompts for your coding agent

Tip: if your tool reads a specific instructions file, copy `AGENTS.md` there too
(e.g. `.github/copilot-instructions.md` for GitHub Copilot, `CLAUDE.md` for Claude Code).

## A. Verify the current version (do this first)
```
Read AGENTS.md, SPEC.md and PROGRESS.md. We are on task V1B-10.
Run: pip install -e ".[dev]", make format, make lint, make typecheck, make test.
Fix every ruff/mypy finding without changing behaviour (tests must stay green).
Show the outputs, update PROGRESS.md (tick verified items, close OI-1 if done)
and propose a commit message.
```

## B. Live Azure check (optional)
```
Read docs/sdk-notes.md. Help me verify OI-4 and OI-5: install the azure extra, run
make record against my Document Intelligence endpoint and one INVOICEGUARD_MODE=azure run.
If a call signature or field name differs from the docs, fix it only inside the adapter or
FIELD_MAP, add a test, and update docs/sdk-notes.md (to verify → verified).
```

## C. Start a new version
```
<VERSION> is approved. Read AGENTS.md, SPEC.md and PROGRESS.md.
Show the planned file list and key interfaces for <NEXT VERSION>, list risks and every SDK
call you are unsure about. Then STOP and wait for my approval.
```

## D. Continue working (every new session)
```
Read AGENTS.md, SPEC.md and PROGRESS.md.
Tell me the current status and the next task, then implement it.
After the task: run make check, show the results, update PROGRESS.md and propose a commit message.
```

## E. Do a specific task
```
Implement task <TASK-ID> from PROGRESS.md, following SPEC.md and AGENTS.md.
Run make check, update PROGRESS.md and propose a commit message.
```

## F. Close a version
```
We are closing <VERSION>. For each acceptance criterion in SPEC.md §12 state PASS/FAIL with
evidence (test name or command + output). List what I must configure manually in Azure,
update CHANGELOG.md and PROGRESS.md, and STOP until I confirm.
```

## G. Fix a bug
```
Bug: <expected vs. actual, paste error/test output>.
Find the root cause, explain it in 2–3 lines, fix it, add a regression test, run make check,
and log it in PROGRESS.md → Open issues (status: fixed).
```

## H. Change the spec
```
I want to change the spec: <change>. Update SPEC.md (bump the version), update PROGRESS.md
tasks if needed, log it in Decisions, and tell me which completed tasks are affected.
Do not change code yet.
```

## I. Status check
```
Read PROGRESS.md and give me: % done per version, what's next, open issues,
and anything in the code that doesn't match SPEC.md.
```
