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
- A `python-experiment` agent with `toolset: [python]` and all v1 Python
  modules. `goal` and `question` are left out so a test cannot block on an
  authorization prompt.

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
