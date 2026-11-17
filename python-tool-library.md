# Python tool library: kind inventory and per-kind design

Status: review draft.
Scope: the native tools in the manica-dei/opencode fork (`packages/opencode/src/tool`, V1 live) and the canonical V2 set (`packages/core/src/tool`), plus MCP and custom tools. This is the Python package the model imports inside code mode.

## 0. Common spine

Every kind uses the same transport and the same host authority.

```text
program.py
  │  from agent import fs, mutate, shell
  │
  ▼
agent.fs.read("src/main.go")
  │  {"id":"3","tool":"read","input":{"path":"src/main.go"}}
  ▼
fd 3  ──────────────────────────────────────────────►  bridge
                                                         │
                                                         ▼
                                          execute tool (host)
                                            ├─ goal gate
                                            ├─ permission("read")
                                            ├─ read.execute(...)
                                            ├─ child call ID = parent/3
                                            └─ truncate

  ◄──────────────────────────────────────────────────────┘
     {"id":"3","ok":true,"output":{"kind":"file",...}}
```

Rules the whole library obeys:

- The package mirrors the tool tree, not the wire protocol.
- One namespace per capability. The import list is the capability declaration.
- Results are dataclasses or `TypedDict`; failures are `AgentError`.
- The host applies the goal gate, permission, plugin hooks, and truncation per child call.
- The SDK uses canonical names (`path`, `content`). The bridge maps V1 names (`filePath`) where the live tool still uses them.
- `execute` is absent (no recursion). `invalid` is absent (internal repair). `question`, `goal`, and `plan_exit` are absent (human-owned).
- The container still permits `open()`, `subprocess`, and sockets. The library is the audited path, not a wall.

## 1. Inventory

| Kind                | Tools                             | V1 live                 | V2 canonical          |
| ------------------- | --------------------------------- | ----------------------- | --------------------- |
| Filesystem read     | `read`, `glob`, `grep`            | yes                     | yes                   |
| Filesystem write    | `edit`, `write`, `apply_patch`    | yes                     | yes                   |
| Process             | `bash` (id `bash`)                | yes                     | yes                   |
| Network             | `webfetch`, `websearch`           | yes                     | yes                   |
| Session state       | `todowrite`, `skill`              | yes                     | yes                   |
| Agent orchestration | `task`, `goal`                    | yes                     | not ported            |
| Human interaction   | `question`, `plan_exit`           | yes                     | `question` only       |
| Browser             | `browser` (action enum)           | yes                     | `browser_*` (7 tools) |
| MCP                 | dynamic tools + 3 resource tools  | yes                     | not ported            |
| LSP                 | `lsp`                             | experimental            | not ported            |
| Meta                | `execute`, `invalid`              | experimental / internal | not ported            |
| Custom              | `.opencode/tool(s)`, plugin tools | yes                     | not ported            |

## 2. Filesystem read

Tools: `read`, `glob`, `grep`.

```text
agent.fs
├── read(path, offset=None, limit=None) -> Text | Image | Directory
├── glob(pattern, path=None, limit=None) -> list[FileEntry]
├── grep(pattern, path=None, include=None, limit=None) -> list[Match]
└── list(path, offset=None, limit=None) -> Directory

read  ──► permission("read")  ──► read tool  ──► Text | Image | Directory
glob  ──► permission("glob")  ──► glob tool  ──► list[FileEntry]
grep  ──► permission("grep")  ──► grep tool  ──► list[Match]
```

```python
from agent import fs

page = fs.read("packages/core/src/tool/bash.ts", limit=80)
hits = fs.grep("TODO", path="packages/core/src/tool", include="*.ts")
files = fs.glob("**/*.go", path=".")

for hit in hits:
    print(hit.path, hit.line, hit.text)
```

Design notes:

- Paths are workspace-relative. Absolute paths inside the workspace are accepted; outside paths require `external_directory`.
- `list` is a convenience over `read` on a directory; there is no separate `list` tool in the fork.
- Return structured data, not the model-facing text. `grep` returns `path`, `line`, `text`; `glob` returns entries; `read` returns a tagged result.
- Paginate with `offset`/`limit`. Do not return a 10,000-row list.
- No `find -exec`, no shell expansion. This module is pure query.
- V1 `grep`/`glob` only expose text and counts. The bridge adapter parses or the leaf is ported to V2 so the typed result is authoritative. Do not fake the types.

## 3. Filesystem write

Tools: `edit`, `write`, `apply_patch`.

```text
agent.mutate
├── edit(path, old, new, replace_all=False) -> EditResult
├── write(path, content) -> WriteResult
└── patch(text) -> PatchResult

edit   ──► permission("edit")  ──► edit tool   ──► EditResult
write  ──► permission("edit")  ──► write tool  ──► WriteResult
patch  ──► permission("edit")  ──► apply_patch ──► PatchResult
```

```python
from agent import mutate

result = mutate.edit(
    "packages/core/src/tool/bash.ts",
    "TODO:",
    "TODO(#4242):",
)
print(result.replacements, result.additions, result.deletions)
print(result.patch)
```

Design notes:

- The result carries the diff, the replacement count, and LSP diagnostics when available. That is the audit record.
- `replace_all=False` is the default; a multi-match edit fails, as the tool does.
- `patch` takes patch text, not a file path. It is only available when the host advertises `apply_patch` (V1: GPT models); otherwise the call fails with `Unavailable`.
- No `rm`, `mv`, `cp`, `mkdir` in this module. Those are `shell` calls with `bash` permission; adding them would hide a broad capability under a narrow name.
- The library does not open the repository itself. The container permits it, but `open()` bypasses the diff and the audit.
- V1 `edit` has fuzzy fallbacks; V2 is exact. The Python wrapper exposes one `edit`; the host decides which implementation runs. Do not surface the fuzzy strategy in the API.

## 4. Process execution

Tool: `bash` (tool id and permission are both `bash`).

```text
agent.shell
├── run(command, workdir=None, timeout=None, check=False) -> Result
└── Result: exit, stdout, stderr, output, truncated, output_path

run ──► permission("bash") ──► bash tool ──► Result
```

```python
from agent import shell

result = shell.run("go test ./...", workdir=".", timeout=120_000)
if result.exit != 0:
    print(result.output)
```

Design notes:

- `workdir` is explicit. The library never prefixes `cd`; the model's `cd &&` habit is redirected here.
- `check=True` raises `AgentError` on a nonzero exit. The default is to return the result, because most inspection commands exit nonzero for boring reasons.
- The host kills the process group on timeout or abort, with a 3-second force-kill window.
- `stdout` and `stderr` are separate. `output` is the combined, truncation-aware view the tool returns.
- No background jobs in v1. A program can poll with `time.sleep`; a real background handle is a later feature.
- This is the hole. A hardened profile denies `shell` in Python mode, exactly as the goal gate treats `bash` as a deliberate exception.

## 5. Network

Tools: `webfetch`, `websearch`.

```text
agent.web
├── fetch(url, format="markdown", timeout=None) -> FetchResult
└── search(query, num_results=None, livecrawl=None) -> SearchResult

fetch   ──► permission("webfetch")   ──► webfetch tool  ──► text + attachments
search  ──► permission("websearch")  ──► websearch tool ──► text
```

```python
from agent import web

page = web.fetch("https://example.com", format="markdown")
hits = web.search("go testing best practices", num_results=5)
```

Design notes:

- `fetch` accepts `http` and `https` only. No headers, no cookies, no credentials from the program.
- `search` picks the provider the host is configured for (Exa/Parallel). The program does not choose.
- Results are text plus optional attachments; large pages are truncated by the host.
- The program can still open a socket, because the container permits it. The library is the audited path.
- Rate limits and provider errors become `AgentError` with a retryable flag.

## 6. Session state

Tools: `skill`, `todowrite`.

```text
agent.state
├── skills.load(name) -> Skill
└── todos.write(items) -> None

skills.load  ──► permission("skill")     ──► skill tool  ──► Skill
todos.write  ──► permission("todowrite") ──► todowrite   ──► None
```

```python
from agent import state

skill = state.skills.load("ste-writing")
print(skill.content, skill.directory)
```

Design notes:

- `skills.load` is read-only for the program: it injects instructions and file references.
- `todos.write` replaces the session list. A program that writes a todo list is doing state management, not tool orchestration; keep it rare.
- There is no `todos.read` native tool. A program that needs its own plan should use a local list.

## 7. Agent orchestration

Tools: `task`, `goal`.

```text
agent.agents
├── tasks.run(type, prompt, background=False) -> TaskResult   [opt-in]
└── goals.*                                                   [absent in v1]

tasks.run ──► permission("task", type) ──► child session ──► TaskResult
```

```python
from agent import agents

result = agents.tasks.run(
    "explore",
    "Find every place the tool registry filters by model.",
)
print(result.output)
```

Design notes:

- `task` starts another agent loop. It multiplies model turns, so it is opt-in and hidden from the default tool tree.
- `goal` writes the durable contract and can ask a human to authorize it. It is the root session's job, not a program's. Do not expose it.
- `task` depth is bounded by `subagent_depth` (default 1). A program cannot recursively fan out agents.
- The child inherits the parent's permission set with `todowrite` and recursive `task` denied unless the subagent allows them.
- If `task` is exposed, the program should treat it as a slow external call, not a subroutine.

## 8. Human interaction

Tools: `question`, `plan_exit`, `goal(commit=True)`.

```text
agent.human   [absent]

program returns {"needs_human": "Which database?"}
        │
        ▼
model sees the result on the next turn and calls the question tool
```

Design notes:

- A Python program cannot render a question. The question tool needs the model to phrase the prompt and the UI to collect the answer.
- Do not block the bridge on a human. Return a `NeedsHuman` value and let the model ask.
- `plan_exit` changes agent/UI state; `goal` asks for authorization. Both belong to the model loop.
- This is a hard rule: **code mode does not own the human**.

## 9. Browser

Tools: V1 `browser` (one action enum), V2 `browser_navigate`, `browser_read`, `browser_click`, `browser_type`, `browser_screenshot`, `browser_back`, `browser_forward`.

```text
agent.browser
├── page() -> Page
├── Page.goto(url) -> Snapshot
├── Page.text() -> str
├── Page.click(selector) -> Snapshot
├── Page.type(selector, text) -> Snapshot
├── Page.screenshot(full_page=False) -> bytes
├── Page.back() -> Snapshot
└── Page.forward() -> Snapshot

Page.goto ──► permission("browser", "navigate") ──► browser tool ──► shared Chromium
```

```python
from pathlib import Path

from agent import browser

page = browser.page()
page.goto("http://localhost:3000")
page.click("text=Sign in")
print(page.text())
Path("login.png").write_bytes(page.screenshot())
```

Design notes:

- One page per session, shared with the human. The program attaches to the Chromium the session already runs.
- Actions are serialized. Element references expire after a navigation; re-read before clicking.
- No `close`, no `connect`, no cookies, no storage, no clipboard. Those are absent from the action table, so they cannot be named.
- Screenshots return bytes and are attached to the program result.
- V1 exposes one enum; V2 exposes seven tools. The Python `Page` hides the difference and maps to whichever the host has.

## 10. MCP

Tools: every tool from every connected MCP server, plus `list_mcp_resources`, `list_mcp_resource_templates`, `read_mcp_resource`.

```text
agent.mcp.<server>
├── <tool>(...) -> dict
└── resources
    ├── list() -> list[Resource]
    ├── templates() -> list[ResourceTemplate]
    └── read(uri) -> ResourceContent

call ──► permission(<server>_<tool>) ──► MCP client ──► server
```

```python
from agent.mcp import github

issues = github.list_issues(owner="opencode-ai", repo="opencode", state="open")
for issue in issues:
    print(issue["number"], issue["title"])
```

Design notes:

- Types are generated from each tool's JSON Schema. Ambiguous schemas become `dict` or `json.RawMessage`; the model can decode them.
- Namespaces are per server. A server named `github` cannot collide with `agent.fs`.
- Every call asks for its own permission (the tool key), with pattern `*`.
- Resources are files in spirit: `list`, `templates`, `read(uri)`. Binary blobs are attached only for supported MIME types and size limits.
- Timeouts are per tool. A slow MCP call can be cancelled; the Go/Python process is not blocked forever.
- Do not expose a raw JSON-RPC escape hatch. The SDK's generated methods are the whole surface.

## 11. LSP

Tool: `lsp` (experimental).

```text
agent.lsp
├── diagnostics(path) -> list[Diagnostic]
├── definition(path, line, col) -> list[Location]
├── references(path, line, col) -> list[Location]
└── hover(path, line, col) -> str | None

diagnostics ──► permission("lsp") ──► lsp tool ──► language server
```

```python
from agent import lsp

for diag in lsp.diagnostics("packages/core/src/tool/bash.ts"):
    print(diag.line, diag.message)
```

Design notes:

- Read-only queries. No rename, no code actions, no workspace edits.
- Line and column are 1-based in the Python API; the bridge converts to the LSP convention.
- Experimental in V1, unported in V2. Mark the module `agent.lsp` optional and absent when the flag is off.

## 12. Meta, internal, and custom

Tools: `execute`, `invalid`, plugin tools, `.opencode/tool(s)` modules.

```text
agent.execute        [absent: no recursion]
agent.invalid        [absent: internal repair sink]
agent.custom.<name>  [opt-in: third-party code]

custom.<name> ──► permission(<name>) ──► plugin/custom tool ──► result
```

Design notes:

- A Python program cannot call `execute`; that is recursion, and it defeats the turn budget.
- `invalid` exists to rewrite a malformed model tool call. A program cannot reach it.
- Custom and plugin tools are third-party. They get a separate `agent.custom` namespace, opt-in per session, and a lower trust label. Do not mix them into `agent.fs`.
- A custom tool can have a Zod schema, a JSON Schema, or no schema. The bridge normalizes to the same `RuntimeTool` shape; the Python stub is generated from the normalized schema.

## 13. Permission matrix

| Method                | Permission  | Kind          | Notes                          |
| --------------------- | ----------- | ------------- | ------------------------------ |
| `fs.read`             | `read`      | read          | images and PDFs as attachments |
| `fs.glob`             | `glob`      | read          |                                |
| `fs.grep`             | `grep`      | read          |                                |
| `mutate.edit`         | `edit`      | write         | returns patch + diagnostics    |
| `mutate.write`        | `edit`      | write         |                                |
| `mutate.patch`        | `edit`      | write         |                                |
| `shell.run`           | `bash`      | exec          | the hole                       |
| `web.fetch`           | `webfetch`  | network       | http(s) only                   |
| `web.search`          | `websearch` | network       |                                |
| `state.skills.load`   | `skill`     | read          |                                |
| `state.todos.write`   | `todowrite` | state         |                                |
| `agents.tasks.run`    | `task`      | orchestration | opt-in                         |
| `browser.page.*`      | `browser`   | stateful      | shared page                    |
| `mcp.<server>.<tool>` | tool key    | external      | generated                      |
| `lsp.*`               | `lsp`       | query         | experimental                   |
| `custom.<name>`       | tool key    | third-party   | opt-in                         |

## 14. What the model sees

A short module summary in the `execute` description, plus the tree on disk:

```text
agent/
├── fs.py
├── mutate.py
├── shell.py
├── web.py
├── state.py
├── browser.py
├── lsp.py
├── mcp/
└── custom/
```

The description should say three things:

1. Import the narrow module you need; the import is the capability.
2. Paths are workspace-relative; use `workdir`, never `cd`.
3. Return a small summary; large data belongs in the workspace, not the result.

## 15. Open questions for review

1. Does `mutate` belong in the first release, or start read-only (`fs`, `web`, `state.skills`) and add writes after measuring duplicate-write behavior?
   -> well just make it alongside the others on first release, we can adjust it later, so rather than measuring duplicate-write behavior we can observe overall model behavior when it is constrained from doing bash
2. Is `agents.tasks.run` worth exposing at all? It multiplies model turns and is hard to bound from inside a program.
   -> why it's hard? i mean tasks run are stopping kind. we can even abstract it to save token and to widen model observability by putting the task subagent transcript to a temporary folder, and give result be final subagent output
3. V1 tools return text; V2 returns typed output. Do we port the leaves first, or ship `CallText` for the V1-only ones?
   -> I want typed output from the start
4. Does `shell` stay in Python mode by default, or only when the profile explicitly allows `bash`?
   -> stay python mode first with an env toggleable regular bash tool permission
5. Do custom/plugin tools ship in `agent.custom` in v1, or wait for a trust label?
   -> let's not touch plugin/mcp tools for now.
