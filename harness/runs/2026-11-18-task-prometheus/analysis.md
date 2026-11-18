# Task-tool run: `agents.tasks.run`

This is the Phase 2 `task` check. The model was told to call
`agents.tasks.run('explore', ...)` from one Python program and return the child
session id, the child output, and the transcript path.

Artifacts:

- `session.json` — parent session.
- `transcript.jsonl` — CLI event stream.
- `workspace/.manus/tasks/ses_e122e4a33ffejD4OtM4QKUu3LK.jsonl` — the child
  transcript written by the adapter.
- `metrics.json` — the numbers below.

## Result

The call worked end-to-end:

| Field | Value |
| --- | --- |
| Parent session | `ses_e122e5d3cffeWmrASgPcw2tNce` |
| Child session | `ses_e122e4a33ffejD4OtM4QKUu3LK` |
| Child agent | `explore` |
| Child model | `litellm/prometheus` |
| Task duration | 8.3 s |
| Child transcript | `.manus/tasks/ses_e122e4a33ffejD4OtM4QKUu3LK.jsonl` (7.3K) |
| Child output | 2 files, no modifications |

The child output:

```text
Files in `/home/ubuntu/workspace`: **2**

- `/home/ubuntu/workspace/README.md` (49 bytes; contains "# enuma-elis harness" and "The sandbox read this file.")
- `/home/ubuntu/workspace/sample.txt` (24 bytes; contains "TODO: replace this line")

Checked the directory with a full listing (including hidden entries): no
subdirectories or additional files. Nothing was modified.
```

## Tokens

| Side | Input | Output | Reasoning | Cache read |
| --- | --- | --- | --- | --- |
| Parent | 543 | 344 | 420 | 3,840 |
| Child | 6,578 | 228 | 81 | 12,800 |

Cost is reported as 0 by the provider. `metrics.json` is the parent summary;
the child token counts above are summed from the child transcript.

## What it proves

- `agents.tasks.run` is reachable from the Python SDK and maps to the native
  `task` tool.
- The child runs as a real subagent (`explore`) with its own session and model.
- The adapter exports the child transcript to `.manus/tasks/<session>.jsonl`;
  the returned `TaskResult` carries `session_id`, `output`,
  `transcript_path`, `background: false`, and `model`.
- The task budget (2 per program) and the 900 s program timeout were not hit;
  one call used 8.3 s.

## Observation

The model returned a `repr(TaskResult)` rather than the dataclass fields, then
extracted the values in its final answer. The SDK can serialize dataclasses
through `agent.to_json`, so this is a model choice, not a serialization gap. It
also explicitly avoided calling the task again to prevent a duplicate child.

The child transcript is a JSONL of `{info, parts}` messages. It contains the
subagent context, the delegated prompt, the child's tool calls, and the final
child answer.
