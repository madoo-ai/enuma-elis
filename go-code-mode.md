# Go Code Mode: native tools as a typed Go API

Status: design proposal. Not implemented.
Scope: extend the `execute` tool so one program can call native agent tools, not just MCP tools. Go is the first typed runtime.

## 1. The idea in one paragraph

Today `execute` sees only MCP tools. Native tools still cost one model turn each. This design gives the model a generated Go SDK (`agent`) whose methods are the native tools, runs the program in a sandbox with no ambient filesystem or network, and bridges every call back to the existing tool registry. One model turn can then do `glob → grep → read → edit → bash`, in a loop or in parallel, and return a single result. The model gets compiler errors instead of schema-decoding errors. The host keeps permissions, plugin hooks, truncation, events, and the audit trail.

## 2. Shape

```text
model
  └─ execute({ language: "go", code })
       ├─ build program (go build, warm cache)
       ├─ run sandboxed binary
       │    └─ agent.Client ──unix socket──► host dispatcher
       │                                      ├─ permission ask
       │                                      ├─ tool.execute(...)
       │                                      └─ result / error
       └─ one tool result: value + logs + child call list
```

Two rules keep the design small:

1. **One tool tree, two runtimes.** The JS interpreter and the Go runtime see the same tools. The language is an implementation detail of the program, not of the catalog.
2. **The program has no ambient authority.** It cannot read the workspace, open a socket, or spawn a process. It can only call tools, and every tool call goes through the dispatcher.

## 3. The Go SDK

The model writes one file in `package main` and defines `Run`. The harness supplies `main`, the client, timeouts, and result reporting.

```go
// user program
package main

import (
    "context"

    "agent"
)

func Run(ctx context.Context, a *agent.Client) (any, error) {
    // ...
}
```

Generated harness:

```go
// zz_agent_main.go — generated, never shown to the model
package main

import (
    "context"
    "fmt"
    "os"
    "os/signal"
    "time"

    "agent"
)

func main() {
    ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
    defer stop()
    ctx, cancel := context.WithTimeout(ctx, 5*time.Minute)
    defer cancel()

    defer func() {
        if r := recover(); r != nil {
            agent.Finish(nil, fmt.Errorf("panic: %v", r))
        }
    }()

    client, err := agent.New(ctx)
    if err != nil {
        agent.Finish(nil, err)
        return
    }
    defer client.Close()

    value, err := Run(ctx, client)
    agent.Finish(value, err)
}
```

`agent.Finish` writes a result envelope to `AGENT_RESULT_PATH` and exits. Logs go to stderr. The host reads the result file, so user `fmt.Println` calls can never corrupt the envelope.

### 3.1 Tool types

Types are generated from the canonical tool schemas. Optional JSON fields become pointers; enums become named string types; unions become tagged structs with a `Kind` field. The names below are the contract for this document.

```go
func Ptr[T any](v T) *T { return &v }
```

```go
type ReadInput struct {
    Path   string `json:"path"`
    Offset *int   `json:"offset,omitempty"` // 1-based
    Limit  *int   `json:"limit,omitempty"`
}

type ReadOutput struct {
    Kind      string     `json:"kind"` // "file" | "directory" | "image"
    Path      string     `json:"path"`
    Text      string     `json:"text,omitempty"`
    Mime      string     `json:"mime,omitempty"`
    Entries   []DirEntry `json:"entries,omitempty"`
    Total     int        `json:"total,omitempty"`
    Truncated bool       `json:"truncated,omitempty"`
}

type DirEntry struct {
    Name string `json:"name"`
    Type string `json:"type"` // "file" | "directory" | "symlink"
}
```

```go
type GlobInput struct {
    Pattern string  `json:"pattern"`
    Path    *string `json:"path,omitempty"`
    Limit   *int    `json:"limit,omitempty"`
}

type GlobOutput struct {
    Entries   []FileEntry `json:"entries"`
    Truncated bool        `json:"truncated,omitempty"`
}

type FileEntry struct {
    Path string `json:"path"`
    Type string `json:"type,omitempty"`
}
```

```go
type GrepInput struct {
    Pattern string  `json:"pattern"`
    Path    *string `json:"path,omitempty"`
    Include *string `json:"include,omitempty"`
    Limit   *int    `json:"limit,omitempty"`
}

type GrepOutput struct {
    Matches   []GrepMatch `json:"matches"`
    Truncated bool        `json:"truncated,omitempty"`
}

type GrepMatch struct {
    Path string `json:"path"`
    Line int    `json:"line"`
    Text string `json:"text"`
}
```

```go
type EditInput struct {
    Path       string `json:"path"`
    OldString  string `json:"oldString"`
    NewString  string `json:"newString"`
    ReplaceAll bool   `json:"replaceAll,omitempty"`
}

type EditOutput struct {
    File         string `json:"file"`
    Replacements int    `json:"replacements"`
    Additions    int    `json:"additions"`
    Deletions    int    `json:"deletions"`
    Patch        string `json:"patch,omitempty"`
}
```

```go
type BashInput struct {
    Command string  `json:"command"`
    Workdir *string `json:"workdir,omitempty"`
    Timeout *int    `json:"timeout,omitempty"` // milliseconds
}

type BashOutput struct {
    Exit       int    `json:"exit"`
    Output     string `json:"output"`
    Truncated  bool   `json:"truncated,omitempty"`
    Timeout    bool   `json:"timeout,omitempty"`
    OutputPath string `json:"outputPath,omitempty"`
}
```

Methods are thin wrappers over one bridge call:

```go
// Read reads a text file, an image, or a page of a directory.
func (c *Client) Read(ctx context.Context, in ReadInput) (ReadOutput, error) {
    var out ReadOutput
    if err := c.call(ctx, "read", in, &out); err != nil {
        return out, err
    }
    return out, nil
}

func (c *Client) Glob(ctx context.Context, in GlobInput) (GlobOutput, error) { /* same */ }
func (c *Client) Grep(ctx context.Context, in GrepInput) (GrepOutput, error) { /* same */ }
func (c *Client) Edit(ctx context.Context, in EditInput) (EditOutput, error) { /* same */ }
func (c *Client) Bash(ctx context.Context, in BashInput) (BashOutput, error) { /* same */ }

// Log writes a line to the program log. It never enters the result envelope.
func (c *Client) Log(format string, args ...any)
```

The types above are the canonical output shapes. V1 tools mostly return `{ output: string, metadata }`, so the bridge returns that as `CallText` and the generator emits a typed wrapper only where an output schema exists. The first milestone adds output adapters for `read`, `glob`, `grep`, `edit`, and `bash`, or ports those leaves to the V2 `Tool.make` contract where the output is already typed. Do not fabricate a struct for a tool that only returns text.

MCP tools live under a generated namespace so names cannot collide:

```go
issues, err := a.MCP.GitHub.ListIssues(ctx, agent.GitHubListIssuesInput{
    Owner: "opencode-ai",
    Repo:  "opencode",
    State: agent.Ptr("open"),
})
```

### 3.2 Errors

Tool failures are values, not panics. The program can handle a denied permission or a missing file and continue.

```go
type Error struct {
    Kind    string          `json:"kind"` // invalid_input | permission_denied | not_found | tool_failed | canceled
    Message string          `json:"message"`
    Data    json.RawMessage `json:"data,omitempty"`
}

func (e *Error) Error() string { return e.Kind + ": " + e.Message }

func Kind(err error) string {
    var target *Error
    if errors.As(err, &target) {
        return target.Kind
    }
    return ""
}
```

```go
if agent.Kind(err) == "permission_denied" {
    return nil, fmt.Errorf("skipped %s: %w", path, err)
}
```

### 3.3 Fan-out

Goroutines are the reason Go is a good fit. The host limits concurrency to 8; the SDK multiplexes responses by call ID.

```go
func readAll(ctx context.Context, a *agent.Client, paths []string) ([]agent.ReadOutput, error) {
    out := make([]agent.ReadOutput, len(paths))
    errs := make([]error, len(paths))

    var wg sync.WaitGroup
    for i, path := range paths {
        wg.Add(1)
        go func(i int, path string) {
            defer wg.Done()
            out[i], errs[i] = a.Read(ctx, agent.ReadInput{Path: path, Limit: agent.Ptr(80)})
        }(i, path)
    }
    wg.Wait()

    return out, errors.Join(errs...)
}
```

## 4. A complete program

The task: find `TODO` comments in the core tool package, read the first one, change it to a tracked reference, and report the diff.

```go
package main

import (
    "context"
    "fmt"
    "sort"

    "agent"
)

type Summary struct {
    TodoFiles []string `json:"todoFiles"`
    Edited    string   `json:"edited"`
    Preview   string   `json:"preview"`
    Diffstat  string   `json:"diffstat"`
}

func Run(ctx context.Context, a *agent.Client) (any, error) {
    hits, err := a.Grep(ctx, agent.GrepInput{
        Pattern: "TODO",
        Path:    agent.Ptr("packages/core/src/tool"),
        Include: agent.Ptr("*.ts"),
        Limit:   agent.Ptr(200),
    })
    if err != nil {
        return nil, err
    }
    if len(hits.Matches) == 0 {
        return Summary{}, nil
    }

    files := map[string]struct{}{}
    for _, match := range hits.Matches {
        files[match.Path] = struct{}{}
    }
    paths := make([]string, 0, len(files))
    for path := range files {
        paths = append(paths, path)
    }
    sort.Strings(paths)

    target := paths[0]
    preview, err := a.Read(ctx, agent.ReadInput{
        Path:   target,
        Offset: agent.Ptr(max(1, hits.Matches[0].Line-2)),
        Limit:  agent.Ptr(6),
    })
    if err != nil {
        return nil, err
    }

    edit, err := a.Edit(ctx, agent.EditInput{
        Path:      target,
        OldString: "TODO:",
        NewString: "TODO(#4242):",
    })
    if err != nil {
        return nil, err
    }

    diff, err := a.Bash(ctx, agent.BashInput{Command: "git diff --stat"})
    if err != nil {
        return nil, err
    }

    return Summary{
        TodoFiles: paths,
        Edited:    fmt.Sprintf("%s (%d replacements)", target, edit.Replacements),
        Preview:   preview.Text,
        Diffstat:  diff.Output,
    }, nil
}
```

That is four native tools and one model turn. The direct-call version needs four extra model turns at minimum.

## 5. The bridge

Unix socket, newline-delimited JSON, one connection per execution. A random token in `AGENT_BRIDGE_TOKEN` authenticates the process; the socket is `0600`. The host checks peer credentials on Linux.

Request:

```json
{"id":"3","tool":"read","input":{"path":"packages/core/src/tool/bash.ts","limit":40}}
```

Success:

```json
{"id":"3","ok":true,"output":{"kind":"file","path":"packages/core/src/tool/bash.ts","text":"...","truncated":false}}
```

Failure:

```json
{"id":"3","ok":false,"error":{"kind":"permission_denied","message":"read denied by rule edit=deny","data":{}}}
```

Host dispatch, in TypeScript:

```ts
async function dispatch(req: BridgeRequest, parent: Tool.Context): Promise<BridgeResponse> {
  const tool = registry.get(req.tool)
  if (!tool) return fail(req.id, "invalid_input", `unknown tool: ${req.tool}`)

  const child: Tool.Context = {
    ...parent,
    callID: `${parent.callID}/${req.id}`,
    // Child progress is published, not returned to the program.
    metadata: (value) => publishChild(parent, req.id, value),
  }

  try {
    const result = await run.promise(tool.execute(req.input, child))
    return { id: req.id, ok: true, output: toStructured(result) }
  } catch (error) {
    return { id: req.id, ok: false, error: toBridgeError(error) }
  }
}
```

Properties that fall out of this shape:

- **Permissions are unchanged.** `child.ask` is the real permission service, so a Go program gets the same prompt, deny, and "always" behavior as a direct call.
- **Audit is unchanged.** The child call ID is `<parent>/<n>`, so the trail is a tree.
- **Cancellation is unchanged.** Killing the `execute` tool closes the socket; the Go context cancels; the host aborts the in-flight tool.
- **Plugin hooks are unchanged.** `tool.execute.before` / `after` see the same `{ tool, sessionID, callID, args }`.
- **Truncation is unchanged.** The host truncates the tool output before it reaches the program, using the same limits.

`toStructured` uses the tool's declared output schema when it has one. When it does not, the response carries `{ output: string, metadata }` and the Go SDK exposes `CallText` for that tool. The bridge never guesses a struct by parsing model-facing prose.

## 6. Type generation

Source of truth: the canonical tool spec.

| Source | Go |
| --- | --- |
| `string` | `string` |
| `number` | `float64` |
| `integer` | `int` |
| `boolean` | `bool` |
| optional property | `*T` + `omitempty` |
| enum | named string type + consts |
| array | `[]T` |
| object | struct |
| `additionalProperties: true` | `map[string]any` |
| `oneOf` / `anyOf` | tagged struct with `Kind`, or `json.RawMessage` when ambiguous |
| `$ref` | named type |
| `description` | Go doc comment |

Generated wrapper:

```go
// Grep searches file contents with a ripgrep pattern.
// Results are relative to the active workspace.
func (c *Client) Grep(ctx context.Context, in GrepInput) (GrepOutput, error) {
    var out GrepOutput
    if err := c.call(ctx, "grep", in, &out); err != nil {
        return out, err
    }
    return out, nil
}
```

Generation runs in CI and on registry changes. Two qualities matter:

- **Native tools are hand-reviewed.** The generator handles the shape, but `read`, `edit`, and `bash` get hand-written union types and doc comments. These are the tools the model calls most.
- **MCP tools are generated wholesale.** Ambiguous schemas become `json.RawMessage`; the model can decode with `encoding/json` or ask for a better schema.

A tool without an output schema gets `CallText`, not a fabricated struct. That keeps the API honest while V1 tools are migrated:

```go
func (c *Client) CallText(ctx context.Context, tool string, in any) (string, error)
```

## 7. Execution and sandbox

The program is compiled, not interpreted.

```text
1. write main.go + zz_agent_main.go + go.mod into a temp dir
2. gofmt -w .
3. go vet ./...
4. go build -trimpath -ldflags="-s -w" -o program .
5. run ./program with no ambient authority
6. read result.json
```

Build settings:

```text
CGO_ENABLED=0
GOFLAGS=-mod=mod
GOPROXY=off
GOCACHE=<shared warm cache>
```

`go.mod` uses a local replace (`replace agent => ./agent`), so the program has no external module graph to fetch. Only the standard library and the generated SDK are available.

Compiler output is the model's error message:

```text
./main.go:14:18: undefined: agent.Reed
```

That is better feedback than a runtime schema error, and it arrives before any tool runs.

### 7.1 Phase 1: native subprocess

The binary runs with:

- no network namespace;
- no writable workspace (the program does not get direct file access);
- a private `/tmp`, a read-only root, and a private run directory for the binary and result envelope;
- `no_new_privs`, rlimits for CPU, memory, file descriptors, and processes;
- the bridge socket as the only file descriptor it can use for authority.

`bwrap` is a good launcher inside the container:

```bash
bwrap --unshare-all --die-with-parent \
  --ro-bind /usr /usr --ro-bind /lib /lib --ro-bind /lib64 /lib64 \
  --proc /proc --dev /dev --tmpfs /tmp \
  --bind "$RUN_DIR" "$RUN_DIR" \
  --unshare-net \
  -- "$RUN_DIR/program"
```

This is not a hard security boundary against a kernel bug, but it removes ambient file and network access and keeps the permission model honest. The repo already runs `bash` with host authority, so this is strictly less authority than the current shell.

### 7.2 Phase 2: WASI

The bridge protocol is runtime-agnostic. Compile the same program to `wasip1` and run it in Wasmtime with only host functions:

```bash
GOOS=wasip1 GOARCH=wasm go build -trimpath -o program.wasm .
wasmtime run --invoke _start program.wasm
```

The SDK uses a host import for `agent_call`, and the host exposes no preopened directories and no sockets. This gives a real capability boundary: if the bridge does not expose it, the program cannot reach it.

Phase 1 is the development path; Phase 2 is the production target for untrusted programs.

### 7.3 Why Go

- **Real types.** The compiler catches orchestration mistakes before any tool runs.
- **Speed.** Native execution and goroutines make fan-out cheap.
- **Static binary.** No runtime dependencies, small sandbox surface.
- **Good errors.** Compiler diagnostics point at a line and a symbol.
- **A large training corpus.** Models write Go well enough for orchestration, and the generated SDK narrows the surface.

The cost is compile latency: a warm build of a small program is typically a few hundred milliseconds, a cold build with the standard library can take seconds. Against a model round trip of several seconds, that is still a win. Cache by source hash so retries are free.

Yaegi is the fallback if compile latency becomes the bottleneck. It is an interpreter, not the real compiler, and its standard-library and generic support are uneven. Do not start there.

## 8. Permissions, limits, and what stays out

The `execute` tool itself asks for a new action, `code`, with the language as the resource:

```ts
ctx.ask({
  permission: "code",
  patterns: ["go"],
  always: ["go"],
  metadata: { language: "go", bytes: source.length },
})
```

Then every child call asks for its own tool permission. There is no privilege escalation: the program can call only what the registry exposes and the ruleset allows.

Defaults:

| Limit | Value |
| --- | --- |
| source size | 64 KiB |
| wall time | 5 minutes |
| tool calls | 200 |
| concurrent calls | 8 |
| result size | 1 MiB |
| child output | existing truncation limits |

Not exposed to Go programs:

- `question` — needs a human in the loop and a model turn.
- `task` — starts another agent loop; recursive and slow.
- `goal` — writes the durable contract and asks for authorization.
- `plan_exit` — changes UI state.
- `execute` — no recursion.

`bash` is exposed but gated by the `bash` permission. It is the known hole: a program that runs `bash` can write anywhere the shell can. A hardened profile should deny `bash` in Go mode, exactly as the goal gate treats it as a deliberate exception.

## 9. Repository changes

| Area | Change |
| --- | --- |
| `packages/codemode-go/` | New package: `agent` client, `agent/native`, `agent/mcp/<server>`, `cmd/agentrun`, Go tests |
| `packages/codemode-go/bridge.ts` | Socket server, request validation, dispatcher adapter |
| `packages/codemode-go/catalog.ts` | Project `RuntimeTool[]` into the read-only `tools/` tree |
| `packages/codemode-go/sandbox.ts` | Build cache, `go build`, `bwrap`/Wasmtime launcher |
| `packages/codemode-go/generate.ts` | Canonical tool spec → `tools_gen.go` and family packages |
| `packages/opencode/src/tool/code-mode.ts` | Build the tool tree from native + MCP; select runtime; keep the existing JS path |
| `packages/opencode/src/tool/registry.ts` | Register `execute` with `language`; gate behind `OPENCODE_EXPERIMENTAL_GO_CODE_MODE` |
| `packages/core/src/tool/registry.ts` | No change: `materialize()` already yields definitions and `settle()` already owns execution |
| `packages/opencode/src/tool/truncate.ts` | No change: child outputs are truncated before the bridge returns |

`language` is optional and defaults to `"js"`, so existing `execute({ code })` calls keep working. A session-level flag can make `"go"` the default for new sessions once the typed path is stable.

The bridge should use the same tool tree the JS runtime uses. That means refactoring `code-mode.ts`'s `toolTree` into a shared catalog builder:

```ts
type RuntimeTool = {
  name: string
  description: string
  input: JsonSchema
  output?: JsonSchema
  execute: (input: unknown, ctx: Tool.Context) => Promise<unknown>
}
```

Both runtimes consume `RuntimeTool[]`. The JS interpreter wraps them as `tools.*`; the Go bridge exposes them as socket methods and generated types.

## 10. Two tool families and the filesystem surface

The model's view should have two layers, and they should not be the same thing.

### 10.1 The catalog is filesystem-shaped

Every tool gets a read-only entry:

```text
tools/
  native/
    read/
      README.md
      read.go
      schema.json
    grep/
    edit/
    bash/
  mcp/
    github/
      list_issues/
        README.md
        list_issues.go
        schema.json
  skills/
    todo-audit/
      main.go
      SKILL.md
```

- `README.md` is the description plus the Go signature.
- `<tool>.go` is the generated typed wrapper.
- `schema.json` is the raw input/output schema for tools that need it.
- Each directory has an `index.go` that re-exports the wrappers.

The agent discovers with `ls`, `cat`, `grep`, and `go doc`. It does not load every schema into the prompt. The tree is generated from the same `RuntimeTool[]`, so it is a projection, not a second source of truth. A denied tool is not written into the tree, so `ls` is also the permission view.

### 10.2 The runtime is importable packages

The program imports the family it needs:

```go
import (
    "context"

    "agent"
    "agent/mcp/github"
    "agent/native"
)

func Run(ctx context.Context, a *agent.Client) (any, error) {
    nat := native.New(a)
    gh := github.New(a)

    files, err := nat.Glob(ctx, native.GlobInput{Pattern: "**/*.go"})
    if err != nil {
        return nil, err
    }

    issues, err := gh.ListIssues(ctx, github.ListIssuesInput{
        Owner: "opencode-ai",
        Repo:  "opencode",
        State: agent.Ptr("open"),
    })
    if err != nil {
        return nil, err
    }

    return map[string]any{"files": files, "issues": issues}, nil
}
```

The flat `a.Read` / `a.Grep` methods remain for short programs. The family packages are the discoverable, importable view, and they keep native and MCP names apart.

This is the two-family split:

- **`agent/native`** — the agent's own hands. Hand-reviewed types, stable names, full output schemas.
- **`agent/mcp/<server>`** — external services. Generated types; ambiguous schemas fall back to `json.RawMessage`.

They share the dispatcher, permissions, and result envelope. They do not share a namespace, a release cadence, or a type-quality bar.

Origin is one axis. Authority is the other. A hardened build can split `agent/native/read` from `agent/native/write`; then the program's import list is its capability declaration, and a profile that denies writes simply omits the write package. A program that tries to import it fails at build time, before any tool runs.

### 10.3 Typed mutation and fan-out

Two properties make this more than a bag of wrappers:

1. **Typed mutation.** `Edit` returns `Replacements`, `Additions`, `Deletions`, and `Patch`. A program can loop over a plan, apply edits, inspect the returned diff, and retry the failed one without a model turn between edits.
2. **Typed fan-out.** Goroutines over `Read`/`Grep` return typed results. `errors.Join` separates "one file failed" from "the whole program failed". The host caps concurrency at 8, so a program cannot stampede the machine.

Example: audit every TODO, rewrite the ones that match a rule, and report the rest.

```go
func Run(ctx context.Context, a *agent.Client) (any, error) {
    nat := native.New(a)

    hits, err := nat.Grep(ctx, native.GrepInput{
        Pattern: "TODO",
        Include: agent.Ptr("*.go"),
    })
    if err != nil {
        return nil, err
    }

    type changed struct {
        File  string `json:"file"`
        Patch string `json:"patch"`
    }
    type skipped struct {
        File string `json:"file"`
        Line int    `json:"line"`
        Text string `json:"text"`
    }

    var edited []changed
    var left []skipped

    for _, hit := range hits.Matches {
        if !strings.Contains(hit.Text, "TODO(#") {
            left = append(left, skipped{File: hit.Path, Line: hit.Line, Text: hit.Text})
            continue
        }
        edit, err := nat.Edit(ctx, native.EditInput{
            Path:      hit.Path,
            OldString: hit.Text,
            NewString: strings.Replace(hit.Text, "TODO(#", "TODO(issue-", 1),
        })
        if err != nil {
            return nil, err
        }
        edited = append(edited, changed{File: hit.Path, Patch: edit.Patch})
    }

    return map[string]any{"edited": edited, "skipped": left}, nil
}
```

The program decides; the model sees the summary. Every edit still asks for `edit` permission unless the ruleset already allows it.

### 10.4 What the filesystem surface must not become

- **Not the invocation layer.** `cat tools/native/edit/edit.go` shows the API; it does not edit. Execution stays in the typed call. That preserves schema validation and the single dispatch point.
- **Not a writable control plane.** No `echo > tools/...` to run a tool. That loses argument structure, validation, and the audit choke point.
- **Not the only discovery path.** `runtime.instructions()` and `$codemode.search` remain for JS and for models that do not browse. The tree is an additional view.
- **Not a security boundary by itself.** A denied tool is hidden from the tree, but the dispatcher enforces the rule. The tree is a map, not a wall.

The practical rule: the tree tells the agent what exists; the Go package tells it how to call it; the dispatcher decides whether it may.

## 11. Rollout

**Phase 1 — read-only native tools.**
`read`, `glob`, `grep`, `webfetch`, `websearch`, `skill`. No writes. This proves the latency and typing story with low risk.

**Phase 2 — writes.**
`edit`, `write`, `apply_patch`, `bash`. These are permission-gated already. Measure retries and duplicate writes; add idempotency keys before enabling `bash` in unattended sessions.

**Phase 3 — MCP.**
Generate namespaces from the MCP catalog. This replaces the current MCP-only `execute` and gives one interface for both tool families.

**Phase 4 — saved programs.**
Store working Go programs as skills (`skills/<name>/main.go` + `SKILL.md`). The model reads them with `read`, edits them, and runs them through `execute`. This is the article's state-persistence idea, with types.

**Metrics to collect**

- model turns per task;
- provider requests per task;
- wall clock split between build, run, and tool time;
- tokens in/out;
- tool calls per program;
- build failures and retries;
- duplicate write attempts.

A paired eval on one fan-out task and one sequential task would settle the latency claim. The repo has `evals/` and `perf/`.

## 12. Trade-offs

- **Compile latency vs round-trip latency.** Go wins when a task has three or more dependent calls; it loses on one or two. The `execute` description should say so.
- **Typed SDK vs tool churn.** Every tool schema change is a generator run. Keep native types hand-reviewed and MCP types generated.
- **Sandbox strictness vs capability.** The stricter the sandbox, the more tools must go through the bridge. That is the point, but it means `read` must return file contents as data, not as a path the program opens itself.
- **Model familiarity.** Models write more Python and JavaScript than Go. The generated SDK, a short example in the tool description, and compiler feedback close most of the gap. The file tree from the earlier design is a natural place to put `go doc`-style docs: `tools/read/README.md`, `tools/read/read.go`.
- **Two runtimes.** Keeping JS for quick MCP orchestration and Go for typed native work adds maintenance. The shared `RuntimeTool[]` catalog is what keeps them honest.

## 13. Minimal example for the tool description

The model needs to know when and how to use this. The `execute` description should include:

```go
// One model turn, many tool calls.
package main

import (
    "context"

    "agent"
)

func Run(ctx context.Context, a *agent.Client) (any, error) {
    files, err := a.Glob(ctx, agent.GlobInput{Pattern: "**/*.go"})
    if err != nil {
        return nil, err
    }
    for _, file := range files.Entries {
        hits, err := a.Grep(ctx, agent.GrepInput{
            Pattern: "TODO",
            Path:    agent.Ptr(file.Path),
        })
        if err != nil {
            return nil, err
        }
        if len(hits.Matches) > 0 {
            a.Log("%s: %d TODOs", file.Path, len(hits.Matches))
        }
    }
    return files, nil
}
```

Three rules in the description:

1. Use Go mode for three or more dependent calls, fan-out, loops, or filtering large results.
2. Call tools only through `a`; the program has no filesystem or network.
3. Return a small summary; put large data in a file or in a tool result the model actually needs.
