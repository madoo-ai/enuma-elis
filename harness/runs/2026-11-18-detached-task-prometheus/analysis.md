# Detached task, 2026-11-18

Model `litellm/prometheus` (`openai/deepseek-v4.1-flash`), agent
`python-experiment`, modules `fs,agents`. Normal bwrap sandbox. The fork's
background-subagent flag was enabled.

## Prompt

> Use only the python tool. In one Python program, use
> `agents.tasks.start("build", "Read README.md and report its first line in
> your final answer.", "read-readme")` to launch a detached subagent, then
> return the job object. Do not wait for it. After the background task
> finishes, report the child result.

## Result

The first program returned immediately:

```json
{
  "job": {
    "session_id": "ses_e10f9e155ffeAVczExMmBBiZ4X",
    "job_id": "ses_e10f9e155ffeAVczExMmBBiZ4X",
    "description": "read-readme",
    "status": "running",
    "background": true,
    "model": "litellm/prometheus"
  }
}
```

The child later completed, the host injected its result into the parent
session, and the parent reported the child's answer: `# enuma-elis harness`.

- Python calls: 2 (one task start, one independent verification).
- Child calls: `agents.tasks.start`, `fs.glob`, `fs.read`.
- Duration: 14.3 s.
- Audit: `{rawOpen: 0, rawExec: 0, rawNet: 0}`.
- `filesChanged`: none.

## What this shows

- `agents.tasks.start(...)` is detached: the Python program returns a job
  handle and does not wait.
- The native `task` tool's background path owns the child session.
- The host injects the child result into the parent session after completion,
  so the model receives it without polling.
- The start shares the existing two-task-per-program budget with foreground
  `agents.tasks.run`.
