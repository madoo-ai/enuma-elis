# Python code mode: build plan

Status: accepted design, build plan.
Progress: Phase 0 and the Phase 1 tool set, catalog, model/provider filtering, manifest index, gating, snapshot diff, and audit summary are implemented. The runtime volume, manifest schemas, and experiment arms remain.
Scope: a separate Python runtime/SDK repository and the adapter inside the manica-dei/opencode fork.

## 0. Decisions

- **New tool `python`**, separate from the existing `execute` (which stays the MCP/JS path). One tool, one catalog, one permission.
- **Runtime:** relocatable CPython plus the `agent` SDK, delivered from a shared read-only volume at `/opt/manus/python`, with a `current` symlink.
- **Sandbox:** `bwrap` with a read-only root, read-write `/workspace` and `/tmp`, an environment whitelist, and two reserved file descriptors.
- **Protocol:** newline-delimited JSON on fd 3; final envelope on fd 4; logs on stderr.
- **Typed from day one:** no output schema means no SDK method. No `CallText` fallback.
- **v1 tools:** `fs.read/glob/grep`, `mutate.edit/write/patch`, `shell.run`, `web.fetch/search`, `state.skills.load`, `state.todos.write`.
- **Deferred:** `task` (phase 2), `browser`/`lsp` (phase 3), MCP and plugin tools (not now).
- **Goal gate:** `python` is not in the scoping allow-list. It is refused until the root goal is authorized.
- **Experiment arm B is the default:** workspace rw, `/tmp` rw, `shell` module toggle, audit hook, snapshot diff.

## 1. Architecture at a glance

```text
model
  │  python({ code })
  ▼
fork adapter  packages/opencode/src/tool/python/
  ├─ python.ts      Tool.define("python"), permission, goal gate
  ├─ catalog.ts     RuntimeTool[] from the native registry
  ├─ sandbox.ts     bwrap, env whitelist, run dir, fds, process group
  ├─ bridge.ts      fd 3 calls, fd 4 result, audit events
  └─ result.ts      truncation, metadata, snapshot diff
       │
       ▼
bwrap
  ├─ /            ro
  ├─ /workspace    rw
  ├─ /tmp          private tmpfs
  └─ python3 /run/agent/zz_main.py
       ├─ sitecustomize.py   audit hook
       └─ agent.Client       fd 3
       │
       ▼
host dispatcher
  ├─ goal gate
  ├─ permission ask
  ├─ tool.execute(...)
  ├─ truncate
  └─ snapshot before/after
```

The fork never parses Python. It writes a source file, launches `bwrap`, and speaks a framed protocol. The separate repo owns the runtime and the SDK.

## 2. Repo split

### 2.1 Separate repo: `manica-dei-python`

```text
agent/                      Python SDK, installed in the runtime
  __init__.py               Client, AgentError, log
  _bridge.py                emitter, reader thread, pending calls
  _errors.py
  _types.py
  fs.py
  mutate.py
  shell.py
  web.py
  state.py
  generated/                generated from the tool manifest
    __init__.py
    fs.py
    mutate.py
    ...
spec/
  protocol.md               wire protocol, fd 3 / fd 4
  tool-manifest.schema.json
  sandbox.md                mount and env policy
runtime/
  Dockerfile                relocatable CPython + SDK
  sitecustomize.py          audit hook
  manifest.template.json
tests/
  fake_host.py              host side in Python, no fork needed
  test_bridge.py
  test_generated.py
  test_audit.py
  test_sandbox.py
scripts/
  build-runtime.sh
  release.sh
pyproject.toml
```

The repo has no TypeScript and does not import the fork. It builds a runtime tarball and publishes a manifest.

### 2.2 Fork adapter

```text
packages/opencode/src/tool/python/
  python.ts                 the tool definition
  catalog.ts                native RuntimeTool[] builder
  sandbox.ts                bwrap launcher, env, run dir
  bridge.ts                 protocol, dispatch, audit
  protocol.ts               message types and validation
  result.ts                 metadata and truncation
packages/opencode/test/tool/python.test.ts
```

Registration goes in `packages/opencode/src/tool/registry.ts`, behind `OPENCODE_PYTHON_CODE_MODE`. No changes to `packages/core/src/tool`; the adapter consumes the existing registry.

### 2.3 The contract

The two repos meet at three artifacts:

| Artifact | Producer | Consumer | Purpose |
| --- | --- | --- | --- |
| `tool-manifest.json` | fork | Python repo | tool names, modules, input/output schemas, permissions |
| `protocol.md` | Python repo | fork | message shapes, fd rules, error kinds, version |
| runtime `manifest.json` | Python repo | fork | runtime version, protocol version, Python version, tool-manifest hash |

The fork exports the tool manifest from its `RuntimeTool[]`. The Python repo generates `agent/generated/*.py` from it and checks drift in CI. The runtime manifest ties the SDK to the binary.

## 3. Protocol

### 3.1 Transport

- fd 3: request/response/audit stream, newline-delimited JSON, UTF-8.
- fd 4: final envelope, written once by the harness, then closed.
- stderr: program logs. stdout: redirected to stderr by the harness.
- Maximum line: 1 MiB. Larger values are an error.
- Reserved fds are documented in `agent/__init__` and the tool description.

### 3.2 Handshake

```json
{"type":"hello","protocol":1,"sdk":"0.1.0","python":"3.13.5"}
{"type":"hello","protocol":1,"tools":["fs.read","fs.grep","mutate.edit"],"limits":{"calls":200,"concurrency":8}}
```

The host checks `protocol` and the tool-manifest hash. A mismatch kills the process and returns a clear error; it does not fall back to another Python.

### 3.3 Calls

```json
{"type":"call","id":"c1","tool":"fs.grep","input":{"pattern":"TODO"}}
{"type":"result","id":"c1","ok":true,"output":{"matches":[]}}
{"type":"result","id":"c1","ok":false,"error":{"kind":"permission_denied","message":"grep denied"}}
```

Error kinds: `invalid_input`, `permission_denied`, `unavailable`, `not_found`, `tool_failed`, `canceled`, `timeout`.

### 3.4 Audit

```json
{"type":"audit","kind":"raw_open","path":"/home/ubuntu/workspace/api/x.go","mode":"w"}
{"type":"audit","kind":"raw_exec","argv":["go","test","./..."]}
{"type":"audit","kind":"raw_net","address":"127.0.0.1:5432"}
```

Audit messages are fire-and-forget. The host records them in the result metadata. They do not become tool calls.

### 3.5 Final envelope

fd 4 receives exactly one JSON object:

```json
{"ok":true,"value":{"edited":3}}
```

or

```json
{"ok":false,"error":{"kind":"tool_failed","message":"..."}}
```

The host waits for exit, reads fd 4, and maps a missing envelope to `tool_failed` with the stderr tail.

### 3.6 Cancellation and limits

- Host abort closes fd 3, sends SIGTERM to the process group, waits 2 s, sends SIGKILL.
- SDK `Client` cancels pending futures when fd 3 closes.
- Defaults: 64 KiB source, 5 min wall clock, 200 child calls, 8 in flight, 1 MiB result.
- `task` phase 2 raises the wall clock and task-call budget separately.

## 4. Python SDK

### 4.1 Layout

```text
agent/
├── __init__.py       Client, AgentError, log, Ptr
├── _bridge.py        emitter, reader thread, call multiplexer
├── _errors.py
├── _types.py         shared result types
├── fs.py             read, glob, grep, list
├── mutate.py         edit, write, patch
├── shell.py          run
├── web.py            fetch, search
├── state.py          skills.load, todos.write
└── generated/        typed stubs from tool-manifest.json
```

`agent.generated` is the only place with generated code. The hand-written modules re-export the generated types and add ergonomics (e.g., `fs.list` is a helper over `read`).

### 4.2 Program convention

The model writes one file. The harness supplies `zz_main.py`.

```python
# program.py
from agent import fs, mutate

def Run(ctx, a):
    hits = fs.grep("TODO", include="*.go")
    for hit in hits:
        mutate.edit(hit.path, hit.text, hit.text.replace("TODO:", "TODO(#4242):"))
    return {"matches": len(hits)}
```

```python
# zz_main.py — generated, not shown to the model
import json, os, sys
import agent
from program import Run

def main():
    os.makedirs(os.environ.get("HOME", "/tmp/home"), exist_ok=True)
    try:
        with agent.Client() as client:
            value = Run(None, client)
        envelope = {"ok": True, "value": agent.to_json(value)}
    except BaseException as error:
        envelope = {"ok": False, "error": agent.to_error(error)}
    # fd 4 in the socket transport; fd 1 in the stdio fallback.
    os.write(4, (json.dumps(envelope) + "\n").encode())
    # The bridge reader thread is blocked on the other fd. Exit hard so it
    # cannot survive interpreter finalization.
    os._exit(0)

main()
```

`agent.Client` owns fd 3. `agent.to_json` rejects non-JSON values with a clear error.

### 4.3 Typed construction

- Optional JSON fields become `Optional[T]`.
- Enums become `Literal[...]` or a `str` subclass.
- Unions become tagged dataclasses with a `kind` field.
- Generated modules carry docstrings from the tool descriptions.
- `pyright` runs in the Python repo CI; the fork CI checks manifest drift.

### 4.4 Fan-out

The SDK supports threads:

```python
from concurrent.futures import ThreadPoolExecutor
from agent import fs

with ThreadPoolExecutor(max_workers=8) as pool:
    pages = list(pool.map(lambda p: fs.read(p, limit=80), paths))
```

The bridge multiplexes by call ID. The host caps concurrency at 8.

## 5. Sandbox

### 5.1 bwrap

```bash
bwrap \
  --die-with-parent \
  --new-session \
  --ro-bind / / \
  --dev /dev \
  --proc /proc \
  --tmpfs /tmp \
  --bind /home/ubuntu/workspace /home/ubuntu/workspace \
  --ro-bind "$RUN_DIR" /run/agent \
  --chdir /home/ubuntu/workspace \
  --clearenv \
  --setenv PATH "$PATH" \
  --setenv HOME /tmp/home \
  --setenv TMPDIR /tmp \
  --setenv LANG C.UTF-8 \
  --setenv LC_ALL C.UTF-8 \
  --setenv PYTHONUNBUFFERED 1 \
  --setenv PYTHONDONTWRITEBYTECODE 1 \
  --setenv PYTHONPATH /opt/manus/python/current/lib \
  --setenv AGENT_BRIDGE_FD 3 \
  --setenv AGENT_RESULT_FD 4 \
  --preserve-fds 2 \
  -- /opt/manus/python/current/bin/python3 /run/agent/zz_main.py
```

Notes:

- `/` is ro, so `/etc`, `/usr`, `~/.config`, and `~/.local` cannot be written. `sudo` cannot remount; bwrap drops the capability.
- `/home/ubuntu/workspace` is rw. This is the experiment.
- `/tmp` is a private tmpfs; the container's shared `/tmp` is not exposed. Create `/tmp/home` and `/tmp/gocache` inside the tmpfs.
- The run dir is ro and holds `program.py`, `zz_main.py`, and nothing secret.
- `--preserve-fds 2` keeps fds 3 and 4.
- Add `bubblewrap` to the base or profile. If it is missing, `python` returns `Unavailable`; never fall back to unsandboxed execution.

### 5.2 Environment whitelist

| Variable | Value | Why |
| --- | --- | --- |
| `PATH` | host PATH | toolchains (`go`, `npm`) must run |
| `HOME` | `/tmp/home` | writable home; the real home is ro |
| `TMPDIR` | `/tmp` | private scratch |
| `LANG`, `LC_ALL` | `C.UTF-8` | deterministic |
| `PYTHON*` | runtime values | SDK import, no bytecode |
| `AGENT_*` | fd numbers | protocol |
| `GOPATH`, `GOTOOLCHAIN` | host values | Go toolchain |
| `GOCACHE`, `GOMODCACHE` | `/tmp/gocache`, `/tmp/gomodcache` (or host values with rw cache binds) | writable caches under `HOME=/tmp/home` |
| `CARGO_HOME`, `RUSTUP_HOME`, `NVM_DIR` | host values | other profiles |

Never pass: `OPENCODE_API_KEY`, `LITELLM_BASE_URL`, `GH_TOKEN`, `GITHUB_TOKEN`, `MANUS_GIT_TOKEN`, `GIT_ASKPASS`, `SSH_AUTH_SOCK`, `AWS_*`, `GOOGLE_*`, `AZURE_*`.

`HOME=/tmp/home` means Go's default cache is cold. Set `GOCACHE=/tmp/gocache` and `GOMODCACHE=/tmp/gomodcache` for the experiment, or bind `~/.cache` and `~/go` rw if you want warm builds. Choose one and document it in the profile.

### 5.3 Secrets

The provider key lives in the agent's process environment. `--clearenv` plus the whitelist is what keeps it out of the Python child. Do not pass the agent's full environment with a denylist; a future secret would leak.

## 6. sitecustomize audit hook

`runtime/sitecustomize.py` is installed as `lib/sitecustomize.py`, so it loads automatically. It installs an audit hook and uses the same fd 3 emitter as the SDK.

```python
import os, sys
from agent import _bridge

def hook(event, args):
    if event == "open":
        path, mode, flags = args
        if mode and any(c in mode for c in "wax+"):
            _bridge.emit({"type": "audit", "kind": "raw_open", "path": str(path), "mode": mode})
    elif event == "subprocess.Popen":
        _bridge.emit({"type": "audit", "kind": "raw_exec", "argv": repr(args)})
    elif event == "os.system":
        _bridge.emit({"type": "audit", "kind": "raw_exec", "argv": repr(args)})
    elif event == "socket.connect":
        _bridge.emit({"type": "audit", "kind": "raw_net", "address": repr(args)})

sys.addaudithook(hook)
```

Rules:

- The hook never blocks and never raises. It is measurement, not enforcement.
- `ctypes` can bypass it. The snapshot diff is the backstop.
- The hook filters `open` to write modes; read events would be too noisy.
- The emitter uses a lock shared with the call stream.

## 7. Fork adapter

### 7.1 The tool

```ts
export const PythonTool = Tool.define(
  "python",
  Effect.gen(function* () {
    return {
      description: DESCRIPTION,
      parameters: Schema.Struct({
        code: Schema.String,
        timeout: Schema.optional(PositiveInt),
      }),
      execute: (params, ctx) => runPython(params, ctx),
    }
  }),
)
```

- Permission: new action `python` (or `code`), pattern `python`, always `python`.
- Goal gate: `python` is absent from `GoalRequired.ALLOWED`; the outer call is refused during scoping.
- Child calls also pass through the gate, as defense in depth.
- `description` includes the module tree and one example, not the full API.

### 7.2 Catalog

`catalog.ts` builds `RuntimeTool[]` from the native registry:

```ts
type RuntimeTool = {
  name: string          // "fs.grep"
  tool: string          // "grep"
  module: string        // "fs"
  permission: string    // "grep"
  input: JsonSchema
  output: JsonSchema
  execute: (input: unknown, ctx: Tool.Context) => Promise<unknown>
}
```

- Native only in v1. No MCP, no plugin/custom tools.
- The module list comes from `agent.python.modules` (default: all v1 modules). The `python` description is generated from it, so the model sees only the modules it can call.
- Filter by the agent permission set, exactly as `registry.tools` does: a `deny *` removes the module method; `bash` denied omits `agent.shell`.
- Filter by model: `apply_patch` vs `edit`/`write`, websearch provider.
- V2 tools use their typed output. V1-only tools get an output normalizer in the adapter; if there is no normalizer, the tool is not exposed. No text parsing in Python.
- `python` itself and `execute` are never in the catalog. No recursion.

### 7.3 Dispatch

```ts
async function dispatch(req: Call, parent: Tool.Context): Promise<Result> {
  const item = catalog.get(req.tool)
  if (!item) return fail(req.id, "unavailable", `unknown tool: ${req.tool}`)

  const child: Tool.Context = {
    ...parent,
    callID: `${parent.callID}/${req.id}`,
    metadata: (value) => publishChild(parent, req.id, value),
  }

  try {
    const refusal = await goalGate(item.tool, req.input)
    if (refusal) return fail(req.id, "permission_denied", refusal)
    const result = await run.promise(item.execute(req.input, child))
    return { id: req.id, ok: true, output: toTyped(item, result) }
  } catch (error) {
    return { id: req.id, ok: false, error: toAgentError(error) }
  }
}
```

- `ctx.ask` is the real permission service. With `permission: "allow"` it is a no-op; the goal gate is the boundary.
- Plugin hooks `tool.execute.before`/`after` run per child call with the derived call ID.
- Output is truncated with the existing `Truncate.Service` before it reaches Python.
- Child call IDs form a tree in the trail.
- Concurrency: a semaphore of 8 around `dispatch`; responses are written in any order, keyed by `id`.

### 7.4 Result metadata

```json
{
  "protocol": 1,
  "runtime": "2026.11.1",
  "python": "3.13.5",
  "durationMs": 8421,
  "toolCalls": [
    {"tool": "fs.grep", "status": "completed", "durationMs": 12},
    {"tool": "mutate.edit", "status": "completed", "durationMs": 31}
  ],
  "audit": {"rawOpen": 3, "rawExec": 1, "rawNet": 0},
  "filesChanged": ["api/internal/x.go"]
}
```

`filesChanged` comes from `Snapshot.Service`: capture before the child starts, capture after it exits, diff. This catches writes that the audit hook misses.

### 7.5 Launcher details

- Run dir: `/home/ubuntu/.local/state/manus/python/<callID>/` on the host. Write `program.py` and `zz_main.py`; mount it ro at `/run/agent`. Keep it outside `/tmp`, because the child gets a private tmpfs there and the bind source would be shadowed.
- Fds: create two pipes for fd 3 and fd 4. Node/Bun `spawn` with `stdio: ["ignore", "pipe", "pipe", "pipe", "pipe"]`. bwrap `--preserve-fds 2`.
- If the runtime cannot pass extra fds, fallback: bridge on stdin/stdout with length-prefixed frames, and `sitecustomize` redirects `sys.stdout` to stderr. Document the fallback, prefer fds.
- Process group: spawn detached or with a process group; kill the group on abort/timeout.
- Missing runtime or `bwrap`: return `Unavailable` with the exact path checked.

## 8. Typed tool manifest

`tool-manifest.json` is the contract between the fork and the Python repo.

```json
{
  "protocol": 1,
  "fork": "v0.4.26-alcides",
  "tools": [
    {
      "name": "fs.read",
      "tool": "read",
      "module": "fs",
      "permission": "read",
      "input": { "$ref": "schemas/read.input.json" },
      "output": { "$ref": "schemas/read.output.json" }
    }
  ]
}
```

Flow:

1. Fork builds `RuntimeTool[]` and exports the manifest (`opencode debug python-manifest` or a test fixture).
2. Python repo generates `agent/generated/*.py` and `.pyi`.
3. Runtime manifest records the manifest hash.
4. Fork handshake checks the hash; mismatch is a clear error.

The manifest is generated, not hand-written. A CI check fails if the committed Python stubs drift from the fork's manifest.

## 9. Runtime delivery

### 9.1 Volume layout

```text
/opt/manus/python/
  releases/
    2026.11.1/
      bin/python3
      lib/python3.13/...
      lib/agent/...          # the agent package; PYTHONPATH points at lib/
      lib/sitecustomize.py   # must be top-level importable
      manifest.json
  current -> releases/2026.11.1
```

Stable image symlink:

```dockerfile
RUN mkdir -p /opt/manus/python \
 && ln -sf /opt/manus/python/current/bin/python3 /usr/local/bin/python3
```

The volume is mounted read-only in sessions. The updater mounts it read-write in a helper, writes a new release, verifies the hash, and swaps `current` atomically. Sessions see the new release on the next spawn; running processes keep their files.

### 9.2 Manifest

```json
{
  "version": "2026.11.1",
  "protocol": 1,
  "python": "3.13.5",
  "toolManifestHash": "sha256:...",
  "sha256": "..."
}
```

### 9.3 Release lanes

| Lane | Changes | Delivery |
| --- | --- | --- |
| `agent-only` | fork binary | hot-swap binary |
| `runtime-only` | Python, SDK, pure-Python deps | volume release + `current` swap |
| `environment-change` | base image, system packages | rebuild image, re-summon |

`runtime-only` is the lane this design adds. The fork adapter checks the runtime manifest at startup of each `python` call.

### 9.4 Base image

- Add `bubblewrap` to the apt list.
- Create `/opt/manus/python` mount point and the `/usr/local/bin/python3` symlink.
- Keep the distro Python as the fallback behind the symlink.
- Set `OPENCODE_PYTHON_CODE_MODE=true` in the base or profile.
- If the volume is missing, the symlink is broken; the shell falls back to `/usr/bin/python3`, but `python` returns `Unavailable` because the SDK is absent. Do not silently run without the SDK.

## 10. Experiment

### 10.1 Catalog gating: disabling the other tools

Adding `python` does not remove `bash`, `read`, `edit`, or `grep`. The model will keep using the familiar tools unless the top-level catalog is gated too. But **do not gate by denying the execution permission**: the Python modules use the same actions (`read`, `edit`, `bash`), so a deny hides both the top-level tool and the Python module.

Split **visibility** from **authority**:

- add a per-agent `toolset` allow-list for the top-level catalog;
- add a per-agent `python.modules` allow-list for the SDK module tree;
- leave the execution permissions unchanged (`read`, `edit`, `bash` stay `allow`).

```json
{
  "agent": {
    "python-experiment": {
      "description": "Python code-mode experiment",
      "mode": "primary",
      "model": "litellm/hephaestus",
      "toolset": ["python", "goal", "question"],
      "python": {
        "modules": ["fs", "mutate", "web", "state"]
      },
      "permission": {
        "python": "allow",
        "question": "allow",
        "goal": "allow"
      }
    }
  }
}
```

- `toolset` is the entire top-level catalog. Anything not listed is not advertised. `Permission.disabled` still runs, so a denied tool stays hidden.
- `python.modules` is the SDK tree. `shell` absent means no `agent.shell`; the top-level `bash` is absent because it is not in `toolset`.
- The execution permission for `mutate.edit` remains `edit: allow`; the top-level `edit` tool is absent because it is not in `toolset`. The module works; the tool does not.
- The `python` description is generated from `python.modules`, so the model does not see modules it cannot call.
- The handshake sends the available module methods. A call to an absent module returns `unavailable`; the SDK raises rather than silently running.
- MCP and custom tools are excluded twice: the experiment template configures no MCP servers and no plugins, and `python` is native-only.

Implementation points:

- Add `toolset?: string[]` to `Agent.Info` and to the agent config schema. Do not reuse the deprecated `tools` boolean map.
- Apply it in `ToolRegistry.tools` (or `SessionTools.resolve`), next to the existing model/provider filters. The final gate in `session/llm/request.ts:resolveTools` should also intersect with it.
- Add `python?: { modules?: string[] }` to `Agent.Info`; `catalog.ts` builds `RuntimeTool[]` from that list.
- For a temporary experiment, an env flag `OPENCODE_EXPERIMENT_TOOLSET=python-only` can hard-code the allow-list before the config field lands. Remove it once the config field exists.
- Verify with a unit test that the advertised top-level names are exactly `["python", "goal", "question"]`, and that the `python` description lists exactly the allowed modules.

The control arm needs the normal catalog. Do not run it with the `python-experiment` agent; use `build` with `python` either absent or present alongside the normal tools.

### 10.2 Arms

| Arm | Top-level catalog | `python.modules` | `/workspace` | net | Measures |
| --- | --- | --- | --- | --- | --- |
| 0 | normal, no `python` | — | rw | on | control: today's behavior |
| A | `python`, `goal`, `question` | fs, mutate, shell, web, state | rw | on | baseline code mode |
| B | `python`, `goal`, `question` | fs, mutate, web, state | rw | on | substitution, no shell module |
| C | `python`, `goal`, `question` | fs, mutate, web, state | ro | on | forced `mutate` |
| D | `python`, `goal`, `question` | fs, mutate, state | ro | off | strict typed tools |

Run 0 and B first. 0 gives the baseline; B gives the treatment. A isolates the shell module; C tests whether `mutate` is sufficient when `open()` cannot write; D is the hardened profile.

### 10.3 Metrics

- tool calls by module and method;
- raw `open` writes, `subprocess`/`os.system`, `socket.connect` (audit hook);
- files changed (snapshot diff);
- model turns, provider requests, cache-read tokens;
- duplicate write attempts and failed edits;
- wall clock split: launch, Python, child calls, tool execution;
- result size and truncation;
- top-level tool calls that should be absent (a gating failure).

### 10.4 What the numbers mean

- High `raw_open` writes in B means the model prefers the old habit.
- Low `raw_open` and high `mutate.edit` in B means the typed API is attractive.
- In C, `mutate` failures and retries reveal whether the API is sufficient.
- Bash usage should drop relative to the transcript baseline (80% of calls) if the library is working.
- Any top-level `bash`/`read`/`edit` call in A-D means the catalog gate leaked.

## 11. Phases

**Phase 0 — contract and skeleton.**
Protocol spec, fake host, `agent.Client`, `fs.read` typed, bwrap launcher, `python` tool hello/exit. No writes.

**Phase 1 — v1 tool set.**
`fs` (read/glob/grep), `mutate` (edit/write/patch), `shell`, `web`, `state`. Tool manifest generation, V1 output adapters, audit hook, snapshot diff. Add the top-level `toolset` allow-list and `python.modules` gating; run experiment 0 and B.

**Phase 2 — experiment and `task`.**
Run 0/A/B/C. Add `task` with `TaskResult` transcript export, task-call budget, and longer timeout. Tune concurrency and truncation.

**Phase 3 — browser and LSP.**
`agent.browser.Page`, `agent.lsp`, V1/V2 mapping.

**Phase 4 — runtime volume release.**
Build the runtime tarball, populate the shared volume, add the base image symlink and `bubblewrap`, ship the `runtime-only` lane.

**Phase 5 — deferred.**
MCP and plugin/custom tools. Not in v1.

## 12. Testing

**Python repo**

- `pytest` with `fake_host.py`: handshake, calls, errors, cancellation, concurrency.
- Generated types: compile, `pyright`, schema drift.
- Audit hook: `open`, `subprocess`, `socket` events.
- Sandbox smoke: bwrap ro root, rw workspace, ro `/etc`, env whitelist.
- Runtime build: Python version, `agent` import, `manifest.json`.

**Fork adapter**

- Fake child process: protocol conformance, malformed messages, missing final envelope.
- Permission and goal gate: denied module absent; child call refusal.
- Truncation and metadata: child output, final result, snapshot diff.
- Cancellation: SIGTERM/SIGKILL, process group, fd cleanup.
- `catalog`: V1 normalizers, V2 typed, model/provider filters.

**Integration**

- Base image with `bubblewrap` and the runtime volume.
- One real session: `fs` + `mutate` + `shell` program.
- Experiment A/B/C on a fixed task; compare turns, cache read, raw writes.

## 13. Risks

| Risk | Mitigation |
| --- | --- |
| bwrap unavailable or user namespaces blocked | Install `bubblewrap`; smoke test in the base image; return `Unavailable` rather than unsandboxed |
| Bun/Node extra fd support | Test fd 3/4; fallback to framed stdin/stdout with `sitecustomize` redirect |
| V1 tools return text | Adapters or V2 port; no SDK method without an output schema |
| Runtime/binary protocol drift | Manifest hash + handshake; fail closed |
| Secrets in the child env | `--clearenv` + whitelist; never a denylist |
| Goal gate is advisory with rw workspace | Refuse `python` during scoping; ro workspace for the scoping arm |
| Top-level toolset leaks (`bash` still callable) | `toolset` allow-list + a test that asserts the advertised names; log the catalog per turn |
| Denying an execution permission hides the Python module | Gate visibility with `toolset`/`python.modules`, not with `deny` rules |
| Audit hook bypass via `ctypes` | Snapshot diff as the backstop; mount flags for enforcement |
| Task cost and timeout | Task-call budget, per-task timeout, child step cap, transcript export |
| Toolchain caches cold under `HOME=/tmp/home` | Set `GOCACHE`/`GOMODCACHE` or bind caches rw; document the choice |

## 14. Open items

- Confirm bwrap user-namespace behavior in the target Docker runtime.
- Confirm extra-fd support in the fork's Bun runtime.
- Pick the cache policy for the experiment: cold `/tmp` caches or warm `~/.cache`/`~/go` binds.
- Decide whether `state.todos.write` is useful enough for v1; it may be noise.
- Decide whether the `python` permission action is `python` or reuses `code`.
