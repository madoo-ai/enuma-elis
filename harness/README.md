# Sandbox harness

Runs the Python SDK inside the same image manus-dei uses, under the same
`bwrap` shape the fork adapter uses.

```bash
./harness/run.sh
```

Requirements: Docker, and `manus-dei/base:latest` (or set
`MANUS_BASE_IMAGE`). The script installs `bubblewrap` inside the throwaway
container; the production base image should carry it.

## What it checks

- The SDK handshake, call stream, and final envelope over stdio.
- `fs.read`, `fs.glob`, `mutate.edit`, `mutate.write` against a real workspace.
- A raw `open("raw.txt", "w")` inside the sandbox succeeds and is audited.
- A raw `open("/etc/enuma-harness", "w")` fails because `/` is read-only.
- The audit hook reports both raw opens.
- The run directory is readable at `/tmp/agent` after the private `/tmp`
  tmpfs is mounted.

Expected output ends with `HARNESS OK`.

## Two findings from the first run

1. **Default Docker seccomp blocks bwrap.** The first run died with
   `No permissions to create a new namespace`. `--security-opt
   seccomp=unconfined` fixes it; `--cap-add SYS_ADMIN` alone does not (the
   default profile still blocks `pivot_root`). A real session needs the
   unconfined profile, a custom profile that allows the namespace syscalls, or
   a different sandbox (Landlock, read-only rootfs). deusd's `HostConfig`
   currently sets no security options.
2. **`/run/agent` cannot be created on a read-only root.** bwrap failed with
   `Can't mkdir /run/agent: Read-only file system`. The adapter now binds the
   run directory at `/tmp/agent` after `--tmpfs /tmp`. The source stays outside
   `/tmp`; only the destination is inside the private tmpfs.

The harness uses the distro `python3` as the runtime. Production uses the
relocatable volume at `/opt/manus/python/current`.

## Serve harness

```bash
./harness/build.sh   # build the fork inside manus-dei/base
./harness/serve.sh
# or: PORT=4097 ./harness/serve.sh
```

Do not use a host-built binary. The base has glibc 2.43 and no ICU; a host build
needs glibc 2.44 and ICU 78, and fails with
`libicui18n.so.78: cannot open shared object file`. `build.sh` builds inside the
base, using the original checkout for `node_modules` and overlaying the changed
core config file. It writes a stamp under `dist/` so `serve.sh` can tell whether
the binary matches the current image.

`serve.sh` runs the binary inside `manus-dei/base:latest` with `python` code
mode enabled. The server binds `0.0.0.0:4096` inside the container and is
published on `http://127.0.0.1:${PORT}`.

What it sets up:

- The local `agent` package as `/opt/manus/python/current`.
- `bubblewrap`, the runtime, and a writable workspace.
- `OPENCODE_PYTHON_CODE_MODE=true`.
- `OPENCODE_GOAL_REQUIRED=false` for a test session; override it to match the
  fleet.
- `OPENCODE_ENABLE_QUESTION_TOOL=false` by default. This removes `question` and
  `goal` from every agent, including the native `build` arm, so a harness run
  cannot block on an authorization prompt.
- A `python-experiment` agent with `toolset: [python]` and all v1 Python
  modules, including `agents.tasks.run` and `browser`.
- `OPENCODE_STATE_DIR=<host-dir>` optionally bind-mounts the agent's OpenCode
  state directory, so the SQLite DB survives the container for debugging.

Pass `OPENCODE_API_KEY` and `LITELLM_BASE_URL` from the host if you want real
model calls; otherwise the server starts and health works, but a prompt cannot
reach a provider. Set `OPENCODE_SERVER_PASSWORD` before exposing the port
beyond localhost; the server warns when it is unset.

`KEEP_WORKSPACE=1` keeps the temp workspace after the server exits, so you can
inspect the artifacts.

Health check:

```bash
curl -s http://127.0.0.1:4096/global/health
# {"healthy":true,"version":"0.4.18"}
```

## First real run

The full dump and analysis are in
[`runs/2026-11-18-todo-prometheus/`](runs/2026-11-18-todo-prometheus/analysis.md).

Prompt: build a small to-do app, one HTML file, add/complete/delete, persisted
in localStorage.

Model `litellm/prometheus`, agent `python-experiment`, toolset `[python]`.

Result:

- `index.html`, 5,355 bytes.
- 64 child tool calls: `shell.run` 57, `fs.read` 4, `fs.glob` 2,
  `mutate.write` 1.
- The model started `python3 -m http.server`, drove the page with
  `agent-browser`, added two items, checked localStorage, reloaded, completed
  one item, deleted both, and checked the empty state.
- Raw audit counters were `{rawOpen: 0, rawExec: 0, rawNet: 0}`: all file work
  went through typed tools, not `open()`.
- One program-level `SyntaxError` (`return` outside `Run`) was fixed by the
  model on the next call.

Two environment notes from this run:

- The deploy env's `OPENCODE_API_KEY` is an `oc_` Zen key; LiteLLM rejects it.
  A temporary key scoped to `prometheus` was minted with the management key
  from `ref/litellm.md`; the harness injects it only for the test.
- `manus-dei/base:latest` currently loads `opencode/deepseek-v4.1-flash`, not
  the `litellm` provider from `templates/base/opencode.json`. The serve
  harness injects the LiteLLM provider through `OPENCODE_CONFIG_CONTENT`.

## Task run

The Phase 2 `task` check is in
[`runs/2026-11-18-task-prometheus/`](runs/2026-11-18-task-prometheus/analysis.md).
One Python program called `agents.tasks.run("explore", ...)`; the child returned
the file listing, and the adapter wrote the child transcript to
`.manus/tasks/<session>.jsonl`. Task time was 8.3 s; one of two task calls used.

## Unbounded run

`OPENCODE_PYTHON_SANDBOX=none` runs the Python runtime directly in the server
container. It is not a sandbox: the program can read `/etc`, use the network,
spawn processes, and see the server environment. Use a throwaway container and
do not point it at a real workspace.

```bash
OPENCODE_PYTHON_SANDBOX=none ./harness/serve.sh
# or a full arm:
./harness/arms.sh U
```

In this mode the host and Python share `/tmp`, so `page.screenshot("/tmp/a.png")`
returns a path the program can open directly. If the program returns the
`Screenshot`, the host reads the path and attaches the image; the Python
program does not carry base64 bytes in this mode.

## Browser run

The browser is a real session browser, not a headless test fixture. `Xvnc` and
Chromium start on the first call; the human would see the same page. The first
call can take a second or two while the display becomes ready.

```bash
PYTHON_MODULES=fs,mutate,browser ./harness/serve.sh
```

Prompt it with a local or public page, for example:

> Open `https://example.com`, take a snapshot, read the title, take a screenshot,
> then go back. Return what you observed.

The Python program uses `browser.page()`. It never receives a CDP port or a
browser handle, so it cannot attach to a different Chromium. A returned
`Screenshot` becomes a `file` attachment at the Python tool boundary; the host
strips the base64 from the text output and the session turns the attachment into
a media part for models that accept images.

The first recorded run is
[`runs/2026-11-18-browser-prometheus/`](runs/2026-11-18-browser-prometheus/analysis.md).
One Python call made six `browser.call` child calls, returned the title, an
attribute, visibility, and a 4,472-byte screenshot, with
`{rawOpen: 0, rawExec: 0, rawNet: 0}`.

The unbounded run is
[`runs/2026-11-18-unbounded-prometheus/`](runs/2026-11-18-unbounded-prometheus/analysis.md).
It read `/etc/hostname`, ran `id`, returned a `Screenshot`, and produced a
`file` attachment. That run predates the model capability config, so it could
not see the image. The corrected vision run is
[`runs/2026-11-18-vision-prometheus/`](runs/2026-11-18-vision-prometheus/analysis.md):
the model read `VISION-OK-739` and `#123456` from a canvas screenshot.

Native `read` and `webfetch` attachments are covered by
[`runs/2026-11-18-native-attachments-prometheus/`](runs/2026-11-18-native-attachments-prometheus/analysis.md).
An image read from the workspace and the same image fetched over local HTTP both
arrived as model attachments; the model read `VISION-OK-739` from both.

Detached subagent jobs are covered by
[`runs/2026-11-18-detached-task-prometheus/`](runs/2026-11-18-detached-task-prometheus/analysis.md).
`agents.tasks.start(...)` returned a job handle immediately, the child finished,
and the host injected its result into the parent session.

The harness model config must declare `attachment: true` and
`modalities.input: ["text", "image"]`; otherwise opencode hides media from the
model even when the provider supports vision.

## Experiment arms

```bash
./harness/arms.sh B
./harness/arms.sh 0 A B C D
```

Each arm starts a fresh server, runs the same prompt, exports the session,
copies the workspace (without `.git`), and writes `metrics.json`. The workspace
is a git fixture now, so `filesChanged` is populated by the snapshot service.
Set `OPENCODE_STATE_DIR=<host-dir>` to preserve the agent's SQLite database.

Single capability scenarios use the same runner shape:

```bash
OPENCODE_STATE_DIR=/tmp/opencode/browser-state \
  ./harness/scenarios.sh browser_bwrap browser bwrap 4300 \
  'Use browser.page() to open https://example.com and return the title.'
```

Every run records `provenance.json` with the fork commit, binary version and
SHA256, base image, agent, module list, sandbox, workspace mode, network mode,
raw-exec policy, and relevant feature flags. `analyze_run.py` copies it into
`metrics.json`.

| Arm | Catalog | Python modules | Workspace | Net | Raw exec | Sandbox |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | normal, no python | — | rw | on | — | — |
| A | python only | fs, mutate, shell, web, state, agents | rw | on | allowed | bwrap |
| B | python only | fs, mutate, web, state | rw | on | blocked | bwrap |
| C | python only | fs, mutate, web, state | ro | on | blocked | bwrap |
| D | python only | fs, mutate, state | ro | off | blocked | bwrap |
| U | python only | fs, mutate, shell, web, state, agents, browser | rw | on | allowed | none |

`OPENCODE_PYTHON_BLOCK_RAW_EXEC=1` makes the `sitecustomize` audit hook raise
`PermissionError` on `subprocess`, `os.system`, and the `os.exec` family after
recording the attempt. Raw `open()` writes are still allowed in the read-write
arms; blocking them is the next decision.

The two arm B runs are the clearest data point:

- [Unblocked](runs/arms/B-20261118T154723/analysis.md): 0 typed child calls,
  6 raw opens, 17 raw execs, claimed Chromium tests.
- [Blocked](runs/arms/B-20261118T155413/analysis.md): 9 typed child calls, 0 raw
  opens, 0 raw execs, 41 s, honest structural verification.
- [Reasoning comparison](runs/arms/reasoning-comparison.md): why the model
  chose each path, in its own words.

## Prompt contract

The `python` tool description is now generated from the enabled catalog:

- one example chosen from the enabled modules (`fs.read` first, then `fs.glob`,
  `mutate.write`, `web.fetch`, `state.skills.load`, `agents.tasks.run`);
- rules for `Run(ctx, a)`, `a.tools`, return values vs `print`, and the fresh
  `/tmp`;
- an error that names the enabled tools instead of saying "unknown tool".

The `python-experiment` agent also has a prompt: one tool, no raw
`open`/`subprocess`/`socket`, and state the verification limit. The earlier arm
B runs predate these changes.
