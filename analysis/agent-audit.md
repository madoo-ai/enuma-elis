# Agent SDK audit

Date: 2026-11-20. Trigger: the `jobs.wait_all` timeout bug report. This pass
looked for state, ordering, timeout, parser, and replay bugs across `agent/`.

## Findings fixed

| Area | Bug | Fix | Regression test |
| --- | --- | --- | --- |
| `jobs.wait_all` | A later success could clear an earlier timeout; `Job.result` also wrapped its wait timeout as a tool failure | `done` only clears on timeout; `TimeoutError` is re-raised | Forced job order, real timeout, error-only job |
| `shell.run(check=True)` | A timed-out command with exit 0 was treated as success | `check` raises `AgentError("timeout")`; `ShellResult.ok` requires exit 0 and no timeout | Timed-out result is not ok and raises |
| `parse_glob`, `parse_grep`, `parse_patch` | `entries=None`, `matches=None`, or `files=None` raised `TypeError` | Normalize with the existing `_list` helper | Absent/null list fields |
| `parse_console`, `parse_page_errors` | Invalid JSON beginning with `{` was silently dropped | Fall back to the raw message | `{not json` is returned |
| `parse_diff` | Raw text such as `No changes` was marked changed | Recognize unchanged text | Empty and unchanged variants |
| `Screenshot.save` | Saving onto the same host path called `shutil.copyfile` on the same file | Treat the same path as a no-op | Save onto the source path |
| `Page.extract` | `@` inside a quoted CSS value was split as an attribute marker | Only split when the suffix is an identifier | Node harness with `input[value="a@b"]` |
| `Page.to_script` | Polling waits and many actions were not recorded, so replay raced | Record waits and remaining mutating actions | `wait_text` appears in replay |
| `ScratchPage.to_script` | Replay used the shared page, omitted scratch actions, and closed before reading title/url | Use `browser.scratch()`, record scratch actions, compute the result before closing | Execute the generated scratch replay |

## Validation

- Python suite: 130 tests pass; 16 live tests skipped by default.
- Live shared-browser suite: 9 tests pass.
- Live scratch-browser suite: 7 tests pass.
- Fork typecheck and 440 tool tests were unchanged by this SDK-only patch.

## Remaining limitations

- Stale-ref recovery matches by role, name, and match index. If the DOM inserts
  an earlier matching element, a retry can act on the wrong element. This is a
  design limit, not silently fixed here.
- `Page.to_script` records actions and waits, not every read-only helper call.
  It is a replay of actions, not a serialization of the original result.
- `run_program` supports synchronous `Run`; an `async def Run` is not supported.
- The active `Client` is process-global. Nested clients would overwrite it;
  programs get one client per process.
