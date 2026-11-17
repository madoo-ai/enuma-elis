# enuma-elis

Python code mode for the [manica-dei/opencode](../me-when-agents) fork.

The model writes one Python program; the program imports `agent` and calls native
tools through a typed module tree. The host runs the program in `bwrap`, mediates
every tool call through the fork's permission and goal-gate path, and returns one
result.

Status: **Phase 1 in progress** — the v1 Python modules, the fork catalog with
V1 adapters, top-level `toolset` and `python.modules` gating, snapshot diffing,
and audit summary are implemented. Tool-manifest generation and the experiment
run are next.

What works now:

- `agent.Client` — handshake, call multiplexing, timeouts, audit emitter, socket
  and stdio transports.
- `agent.fs` — typed `read`, `glob`, `grep`.
- `agent.mutate` — typed `edit`, `write`, `patch`.
- `agent.shell` — typed `run` with `workdir`, timeout, and `check`.
- `agent.web` — typed `fetch` and `search`.
- `agent.state` — `skills.load` and `todos.write`.
- `tests/fake_host.py` — a Python host over a socketpair; no fork needed.
- `tests/test_stdio.py` — the real stdio path the fork adapter uses.
- Fork adapter at `me-when-agents/packages/opencode/src/tool/python/` — `python`
  tool, bwrap command builder, stdio bridge, full v1 catalog, `toolset` and
  `python.modules` gating, snapshot diff, audit summary, and tests.

Not yet: the runtime volume build, the generated tool manifest, the experiment
arms, and the MCP/plugin surface.

## Layout

| Path | Purpose |
| --- | --- |
| `agent/` | Python SDK package (`Client`, bridge, `fs`, `mutate`, `shell`, `web`, `state`) |
| `spec/` | Wire protocol, tool-manifest schema, sandbox policy |
| `runtime/` | Runtime build notes and `sitecustomize.py` audit hook |
| `tests/` | Zero-dependency smoke tests |
| `scripts/` | Local checks |
| `me-when-agents/` | The fork checkout used for adapter testing (gitignored) |

## Design docs

- [`python-code-mode-plan.md`](python-code-mode-plan.md) — build plan, repo split, adapter, experiment.
- [`python-tool-library.md`](python-tool-library.md) — per-kind library design.
- [`native-agent-tools.md`](native-agent-tools.md) — how the fork's tools work.
- [`tool-call-stats.md`](tool-call-stats.md) — transcript statistics that motivated this.
- [`go-code-mode.md`](go-code-mode.md) — the earlier Go variant, kept for reference.

## Quick check

```bash
./scripts/check.sh
```

No dependencies beyond Python 3.11+.

## Notes

- The test fixture is `me-when-agents/`, a full copy of the fork. It is ignored by
  git and must stay out of commits.
- This repository was initialized at its current path. The directory name is not
  part of the repository; rename it to `enuma-elis` when convenient.
- The fork adapter will live in
  `me-when-agents/packages/opencode/src/tool/python/` once the plan reaches
  Phase 0.
