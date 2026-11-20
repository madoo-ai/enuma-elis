# Dev dump fixes

Source: `manus-dei/.dumps/ca632267-dump-20261120T083306Z`, the first real
code-mode run. The build/dev agent used Python; QA and the judge stayed native.

## Findings

| ID | Finding | Evidence | Status | Fix |
| --- | --- | --- | --- | --- |
| D1 | A detached descendant can keep the shell tool's stdio open, so `shell.run` ignores its requested timeout and the Python bridge times out later | Program 35: `setsid ... & disown`, `timeout=8000`, but the Python call failed after 120s | fixed | `CrossSpawnSpawner` resolves exit on process exit and no longer waits on a process that already exited |
| D2 | Failed Python programs lose child-call and audit telemetry | Programs 49 and 97 had successful edits before failing, but metadata had no `toolCalls` and no audit | fixed | `ProgramError` now carries the bridge's `toolCalls` and audit; the Python tool includes them in failure metadata |
| D3 | Tool-error and syntax-error traces include Python internals | Program 49/97 showed `concurrent/futures/_base.py`; program 107 showed `ast.py` instead of the failing line | fixed | The loader records the program path; traces are program-only. Syntax errors point at the program line |
| D4 | Program failures are tool results with `metadata.error=true`, not tool-state errors | Programs 35, 49, 97, and 107 have state `completed` | accepted behavior | Keep the rich failure text; analyzers should use `metadata.error` |
| D5 | One failed edit aborts the rest of a batched program | Programs 49 and 97 stopped at a failed `mutate.edit` | short-term fix | The Python prompt now says to wrap independent edits in `try/except AgentError`; a batch helper remains future work |
| D6 | Long-running setup work has no first-class background API | Programs 24 and 35 improvised with `nohup`/`setsid`; the second hung | D1 fixed; D6 future | A typed `shell.background(command)` returning pid/log path would replace the workaround. Not in the Terminal-Bench scope |
| D7 | QA used native browser calls and hit schema mistakes | QA round 2 had six browser errors, including wrong `find` field names | out of scope for this dump | Python browser helpers would help, but QA was intentionally native |

## What is implemented

### D1 — shell timeout

`packages/core/src/cross-spawn-spawner.ts`:

- resolve the child-process signal on `exit`, not only stdio `close`;
- do not wait on a process that already reported `exitCode`/`signalCode`;
- short-circuit kill and release paths for an already-finished process.

A detached `setsid` descendant can still hold stdio, but the shell tool now
returns when the shell exits and does not block on the descendant.

The regression test is guarded so a checkout whose `node_modules` points at a
different fork does not test the wrong implementation.

### D5 — batched edits

The Python catalog's `mutate.edit` note now says that a failed edit stops the
program and that independent edits should be wrapped in `try/except AgentError`
with per-edit status.

### D2 — failure telemetry

`packages/opencode/src/tool/python/bridge.ts`:

- `ProgramError.details` now carries `toolCalls` and `audit`;
- timeout, cancel, missing-envelope, and final-error paths include them.

`packages/opencode/src/tool/python/python.ts` includes them in failure
metadata alongside `filesChanged`.

### D3 — traces

`agent/_program.py` records `PROGRAM_PATH`.

`agent/to_error`:

- for `SyntaxError`, points at the program file and line;
- otherwise, keeps only frames from the recorded program path;
- if there is no recorded path, it keeps the previous best-effort behavior.

### Validation

- Python SDK: 143 tests pass.
- Fork: 22 shell tests and three Python bridge tests pass; the detached-child
  regression was additionally validated against the local core source.
- Fork typecheck is clean, and the fork binary is rebuilt.

## Follow-ups

- Consider `mutate.edits` if batched edits keep failing in real work.
- Consider `shell.background` if long-running setup keeps appearing.
- Keep the dev/QA split in mind when reading failure counts: the Python
  failures here are author-side only.
