# enuma-elis

Python code mode for the [manica-dei/opencode](../me-when-agents) fork.

The model writes one Python program; the program imports `agent` and calls native
tools through a typed module tree. The host runs the program in `bwrap`, mediates
every tool call through the fork's permission and goal-gate path, and returns one
result.

Status: **Phase 1** — every V1 programmatic native tool now has a Python
surface, including the shared browser. The fork catalog with V1 adapters,
top-level `toolset` and `python.modules` gating, snapshot diffing, audit
summary, and tool-manifest generation are implemented. LSP is deliberately
deferred; the experiment run is next.

What works now:

- `agent.Client` — handshake, call multiplexing, timeouts, audit emitter, socket
  and stdio transports.
- `agent.fs` — typed `read`, `glob`, `grep`; an image or PDF read returns its
  native attachment as an `Image` with `.bytes`.
- `agent.mutate` — typed `edit`, `write`, `patch`.
- `agent.shell` — typed `run` with `workdir`, timeout, and `check`.
- `agent.web` — typed `fetch` and `search`; an image fetch returns its native
  attachment as a `FetchResult` with `.bytes`.
- `agent.state` — `skills.load` and `todos.write`.
- `agent.agents` — `tasks.run` with the child session, final output, transcript
  path, a two-call budget, and a longer program timeout. `tasks.start` launches
  a detached subagent and returns a job handle; the host notifies the session
  when it finishes.
- `agent.browser` — a `Page` façade over the session's single Chromium:
  navigation, snapshots, semantic locators, actions, waits, tabs, screenshots,
  PDF, console/errors, network, vitals, evaluate, and low-level mouse input.
  It has no browser endpoint and no launch, connect, or close method; the host
  resolves the one browser it owns for every call. Returned `Screenshot`,
  `Image`, and image `FetchResult` values become model attachments, not base64
  blobs in the text output.
- `agent.jobs` — generic background call handles for every SDK tool: start a
  call, keep the program running, and await only the results it needs.
- `tests/fake_host.py` — a Python host over a socketpair; no fork needed.
- `tests/test_stdio.py` — the real stdio path the fork adapter uses.
- Fork adapter at `me-when-agents/packages/opencode/src/tool/python/` — `python`
  tool, bwrap command builder, stdio bridge, full v1 catalog, `toolset` and
  `python.modules` gating, model/provider filtering, a generated catalog
  description, `tool-manifest` export, snapshot diff, audit summary, and tests.

Not yet: the runtime volume build, the experiment arms, full input/output
schemas in the manifest, and the MCP/plugin surface. The browser harness run is
recorded in
[`harness/runs/2026-11-18-browser-prometheus/`](harness/runs/2026-11-18-browser-prometheus/analysis.md),
and native read/fetch attachments are confirmed in
[`harness/runs/2026-11-18-native-attachments-prometheus/`](harness/runs/2026-11-18-native-attachments-prometheus/analysis.md).
LSP is not planned for this phase.

## Layout

| Path | Purpose |
| --- | --- |
| `agent/` | Python SDK package (`Client`, bridge, `fs`, `mutate`, `shell`, `web`, `state`, `agents`, `browser`) |
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

## Sandbox harness

```bash
./harness/run.sh
```

Runs the SDK and the bwrap sandbox inside `manus-dei/base:latest`. It exercises
the stdio protocol, typed tools, raw-write audit, and the read-only root. See
[`harness/README.md`](harness/README.md) for the two production findings:
Docker's default seccomp blocks bwrap user namespaces, and the run directory
must be bound under the private `/tmp` tmpfs.

For the unbounded experiment, `OPENCODE_PYTHON_SANDBOX=none ./harness/serve.sh`
runs the Python runtime directly in the container. It has no bwrap, shares
`/tmp`, can spawn processes, and can read the server filesystem. Use a throwaway
container.

The serve harness builds the fork inside the base image (a host build needs a
newer glibc and ICU) and publishes the server port:

```bash
./harness/build.sh
./harness/serve.sh          # http://127.0.0.1:4096/global/health
PORT=4097 ./harness/serve.sh
```

## Notes

- The test fixture is `me-when-agents/`, a full copy of the fork. It is ignored by
  git and must stay out of commits.
- This repository was initialized at its current path. The directory name is not
  part of the repository; rename it to `enuma-elis` when convenient.
- The fork adapter will live in
  `me-when-agents/packages/opencode/src/tool/python/` once the plan reaches
  Phase 0.
