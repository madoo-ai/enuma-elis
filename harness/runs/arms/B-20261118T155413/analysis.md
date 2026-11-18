# Arm B with raw exec blocked

This is the same arm as `B-20261118T154723` — no `shell` module, workspace
read-write, network on — but with `OPENCODE_PYTHON_BLOCK_RAW_EXEC=1`. The audit
hook raises `PermissionError` on `subprocess`, `os.system`, and the `os.exec`
family after recording the attempt.

Artifacts: `session.json`, `transcript.jsonl`, `workspace/`, `metrics.json`.

## Result

| Metric | Value |
| --- | --- |
| Python tool calls | 10 |
| Typed child calls | 9 |
| `fs.read` | 5 |
| `fs.glob` | 2 |
| `mutate.write` | 1 |
| `mutate.edit` | 1 |
| Raw `open` | 0 |
| Raw `exec` | 0 |
| Raw `net` | 0 |
| Program errors | 3 |
| Files changed | `index.html` |
| Duration | 41.1 s |
| Tokens | 3,436 input / 3,853 output / 913 reasoning / 40,192 cache read |
| Artifact | `index.html`, 6,946 bytes |

## Comparison with the unblocked arm

| | Unblocked | Blocked |
| --- | --- | --- |
| Python calls | 15 | 10 |
| Typed child calls | 0 | 9 |
| Raw `open` | 6 | 0 |
| Raw `exec` | 17 | 0 |
| Duration | 132.6 s | 41.1 s |
| Browser verification | claimed, via raw subprocess | explicitly declined |
| Artifact | 7,048 bytes | 6,946 bytes |

The unblocked run used raw Python for everything and claimed a 20/20 Chromium
test. The blocked run used `mutate` and `fs`, and the final answer says:
"Browser execution wasn't available in this sandbox, so verification is
structural rather than a live interaction test."

That is the intended behaviour. The gate is no longer advisory for process
execution.

## The three errors again

They are authoring mistakes, not tool failures:

1. A top-level `shell.run(...)` before `Run` existed.
2. A top-level `fs.glob(...)` before `Run` existed.
3. `ImportError: cannot import name 'Run'`.

The harness now imports `program` inside the `Client` context, so a top-level
call at least sees an active client; it still must define `Run`. The model
recovered and used the typed tools.

## What remains

- Run arms 0, A, C, and D with the same prompt.
- Decide whether to block raw `open` as well; with the workspace read-write and
  raw `open` allowed, a model can still bypass `mutate`.
- Add attempted-versus-completed exec counts. The hook emits before it raises,
  so a blocked attempt still appears in `rawExec`; this run had zero attempts.
