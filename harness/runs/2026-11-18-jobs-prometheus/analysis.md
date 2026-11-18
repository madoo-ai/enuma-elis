# Background call handles, 2026-11-18

Model `litellm/prometheus` (`openai/deepseek-v4.1-flash`), agent
`python-experiment`, modules `fs,web`. Normal bwrap sandbox.

## Prompt

> Use only the python tool. In one program, use `agent.jobs.start` to run
> `fs.read("README.md")` and `fs.glob("*")` concurrently, collect each with
> `job.result()`, and return the read line count and file list.

## Result

The model used the SDK handle:

```python
j_read = agent.jobs.start(fs.read, "README.md")
j_glob = agent.jobs.start(fs.glob, "*")
read_res = j_read.result()
glob_res = glob_job.result()
```

Final result:

```json
{
  "read_lines": 2,
  "files": [
    "/home/ubuntu/workspace/README.md",
    "/home/ubuntu/workspace/sample.txt"
  ]
}
```

- One successful Python call; two child calls: `fs.read`, `fs.glob`.
- Duration: 20.7 s, including one failed attempt when the model iterated
  `GlobResult` directly and then inspected its shape.
- Audit: `{rawOpen: 0, rawExec: 0, rawNet: 0}`.
- `filesChanged`: none.

## What this shows

- `agent.jobs.start(fn, ...)` works for any SDK tool function.
- The program can start independent calls and collect them later with
  `job.result()`.
- The model can discover the typed result shapes and use them correctly.
- This is in-program concurrency. The program still owns the jobs; there is no
  detached job store and no notification after `Run` returns.
