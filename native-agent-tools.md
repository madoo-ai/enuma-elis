# How the native agent tools work

Scope: the `me-when-agents` checkout (manica-dei, a product fork of opencode) at commit `d0a43841a`.
"Native" here means the first-party tools the agent ships with, as opposed to MCP servers, plugins, or user tools in `.opencode/tool/`.

## 0. Short version

There are **two tool stacks** in the tree:

| Stack | Location | Status |
| --- | --- | --- |
| opencode V1 tools | `packages/opencode/src/tool` | The live stack. Used by the server/TUI/CLI session loop. |
| Core V2 tools | `packages/core/src/tool` | The in-progress rewrite. Effect-native, already powers the V2 session runner and `opencode debug agent`. |

Both stacks share the same shape: a named tool = description + typed input schema + typed output + an Effect executor. The registry turns those into model-facing JSON Schema tool definitions, and the session loop dispatches each model tool call back into the executor.

The differences are in the plumbing:

- **V1** executes tools through the Vercel AI SDK (`streamText({ tools })`) or, optionally, the native LLM runtime. Permissions are requested from inside each tool via `ctx.ask(...)`. Output is truncated after the fact.
- **V2** has an opaque canonical `Tool.make` value, a scoped `ToolRegistry`, and one settlement boundary that validates output and bounds it before the result goes back to the model.

The fork's own additions sit on the V1 stack: the `goal` tool and its gate, the `browser` tool over `agent-browser`, and the process-kill guard.

---

## 1. The live stack

### 1.1 Anatomy of a tool

`packages/opencode/src/tool/tool.ts` defines the contract:

```ts
export interface Def<Parameters, M> {
  id: string
  description: string
  parameters: Schema.Decoder<unknown>
  jsonSchema?: JSONSchema7
  execute(args, ctx): Effect.Effect<ExecuteResult<M>>
  formatValidationError?(error): string
}
```

A tool is created with `Tool.define(id, init)`:

- `init` is an `Effect` that yields either a `DefWithoutID` or a factory. Registry creation runs `Tool.init(...)` once per instance, so services (FS, permission, LSP, config) are captured at init, not per call.
- `wrap()` (`tool.ts:99-149`) replaces `execute` with a wrapper that:
  1. decodes arguments with the Effect Schema decoder;
  2. maps decode failures to `InvalidArgumentsError`, whose message tells the model to rewrite the input;
  3. runs the tool body inside a `Tool.execute` tracing span with `tool.name`, `session.id`, `message.id`, `tool.call_id`;
  4. applies generic output truncation unless the tool already set `metadata.truncated`.

The tool body receives a `Tool.Context` (`tool.ts:36-46`):

```ts
{
  sessionID, messageID, agent, abort, callID,
  extra: { model, bypassAgentCheck, promptOps },
  messages,
  metadata(input): Effect<void>,   // live progress/title updates
  ask(input): Effect<void>          // permission request
}
```

### 1.2 Registration and selection

`packages/opencode/src/tool/registry.ts` builds the tool set once per project instance:

- **Built-ins** are constructed in a fixed order (`registry.ts:238-264`): `invalid`, `question`, `goal`, `shell`, `read`, `glob`, `grep`, `edit`, `write`, `task`, `webfetch`, `todowrite`, `websearch`, `skill`, `apply_patch`, `browser`, then optional `execute` (code mode), `lsp`, `plan_exit`.
- **Conditional inclusion**:
  - `question` and `goal` only when the client is `app`, `cli`, or `desktop`, or `OPENCODE_ENABLE_QUESTION_TOOL` is set.
  - `execute` only when `OPENCODE_EXPERIMENTAL_CODE_MODE` is on.
  - `lsp` only with `OPENCODE_EXPERIMENTAL_LSP_TOOL`.
  - `plan_exit` only with `OPENCODE_EXPERIMENTAL_PLAN_MODE` and the CLI client.
- **Custom tools** come from `{tool,tools}/*.{js,ts}` in config directories (`registry.ts:190-204`) and from plugin `tool` maps (`registry.ts:206-211`). They are adapted into the same `Def` shape. A file's default export is named after the file; other exports become `<file>_<export>`.
- **Per-request filtering** (`registry.ts:306-355`):
  - `websearch` only for the opencode provider or when Exa/Parallel flags are on.
  - `apply_patch` replaces `edit`/`write` for model IDs containing `gpt-`, excluding `oss` and `gpt-4`. This is a string heuristic, not a capability check.
  - `execute` is dropped when no permitted MCP tools exist, because its catalog description would be empty.
  - A plugin `tool.definition` hook may rewrite each definition's description, parameters, or JSON Schema.
  - The `task` description is extended with the list of subagents the current agent may call.
- **Permission visibility** is applied later, in `packages/opencode/src/session/llm/request.ts:208-214`: tools whose permission is denied with pattern `*` are removed from the model's tool list, as are tools the user disabled for the message.

### 1.3 From definition to model call

`packages/opencode/src/session/tools.ts` converts each `Def` into an AI SDK tool:

```ts
tools[item.id] = tool({
  description: item.description,
  inputSchema: jsonSchema(ProviderTransform.schema(model, ToolJsonSchema.fromTool(item))),
  execute(args, options) { ... }
})
```

Details worth knowing:

- Schemas go through `ToolJsonSchema.fromTool` (`packages/opencode/src/tool/json-schema.ts`), which normalizes Effect Schema output to draft 2020-12, inlines `$ref`s, drops nullable wrappers on optional properties, and fixes integer bounds.
- `ProviderTransform.schema` then applies provider quirks: OpenAI/Azure sanitization, Moonshot `$ref` handling, Gemini enum conversion, and so on.
- The AI SDK executes the tool. The `execute` closure builds `Tool.Context`, applies cross-cutting gates, and returns the result.
- Before execution: the **goal gate** (`session/tools.ts:79-91`) can refuse the call when `OPENCODE_GOAL_REQUIRED` is on and the root session's goal is not authorized.
- Around execution: plugin hooks `tool.execute.before` and `tool.execute.after` see `{ tool, sessionID, callID, args }` and the result.
- If the abort signal is already set after the tool returns, the processor is told to complete the call early (`session/tools.ts:162-165`).

Results become message parts. Attachments (images, PDFs) get fresh part IDs, and the processor normalizes images that exceed provider limits, noting any that were omitted (`session/processor.ts:383-413`).

There is one native-runtime variant: when `OPENCODE_EXPERIMENTAL_NATIVE_LLM` selects `@opencode-ai/llm` instead of `streamText`, `session/llm/native-runtime.ts` reuses the same `tools` map and bridges it into native executable tools. Tool execution stays opencode-owned; only request lowering and transport change.

### 1.4 The turn loop

The AI SDK path uses `streamText` with `tools` and `activeTools`. Events flow through `session/llm/ai-sdk.ts` to the session processor:

- `tool-input-start` / `tool-input-delta` / `tool-input-end` create and update a pending tool part.
- `tool-call` marks the part `running` and performs **doom-loop detection**: if the last three parts are the same tool with byte-identical input, it asks the `doom_loop` permission (`processor.ts:356-379`, threshold 3).
- `tool-result` completes the part; `tool-error` fails it.
- Tool-call repair is enabled (`session/llm.ts:296-318`): a tool name with different casing is lowercased, and an unparseable call is rewritten to the internal `invalid` tool, which is deliberately excluded from `activeTools` so the model cannot call it directly.
- The agent loop continues while the finish reason is `tool-calls`, up to the agent's step limit. On the last allowed step, tools are not advertised and a `MAX_STEPS_PROMPT` assistant message is appended.

### 1.5 Permissions

Each tool decides what to ask for; there is no central authorization choke point in V1.

`ctx.ask()` (`packages/opencode/src/permission/index.ts:67-107`) takes `{ permission, patterns, always, metadata }` plus the call site's merged ruleset:

- Rules are matched with wildcards; the **last** matching rule wins; no match means `ask`.
- `deny` fails immediately with `DeniedError`.
- `ask` publishes a permission event and waits on a Deferred until the user replies.
- `always` adds allow rules for the listed patterns; `once` does not persist.

Per-tool actions:

| Tool | Permission | Notes |
| --- | --- | --- |
| `shell` | `bash` | Parsed command prefixes, plus `external_directory` |
| `read` | `read` | |
| `glob` / `grep` | `glob` / `grep` | |
| `edit`, `write`, `apply_patch` | `edit` | Shared action |
| `webfetch` / `websearch` | `webfetch` / `websearch` | URL or query is the pattern |
| `task` | `task` | Pattern is the subagent type |
| `skill` | `skill` | Pattern is the skill name |
| `todowrite` | `todowrite` | |
| `browser` | `browser` | Pattern is the action |
| `lsp` | `lsp` | |
| MCP resource tools | `read` | `list_mcp_resources`, `read_mcp_resource`, etc. map to `read` |

`external-directory.ts` handles one cross-cutting case: any target outside the instance worktree asks for `external_directory` with the parent directory's glob.

`Permission.disabled` (`permission/index.ts:204-219`) is the visibility counterpart: a matching `deny *` rule removes the tool from the catalog. Execution still relies on the tool's own `ask`.

### 1.6 Output bounds

`packages/opencode/src/tool/truncate.ts`:

- Defaults: **2000 lines / 50 KiB**, configurable via `tool_output.max_lines` and `tool_output.max_bytes`.
- Over-limit output is written in full to the truncation directory as `tool_<id>`; the model gets a preview plus a hint.
- The hint tells the agent to delegate to the explore agent when the calling agent has the `task` tool, otherwise to grep or read with offsets.
- Files are cleaned up hourly after 7 days.
- Shell is special: it streams output to the UI via `ctx.metadata`, spills to a file as soon as it passes the byte limit, keeps a bounded tail in memory, and returns the file path.

### 1.7 Inventory

| Tool id | What it does | Notable behavior |
| --- | --- | --- |
| `shell` | Runs one command string | tree-sitter parses bash/PowerShell; arity-based approval; kills on timeout/abort |
| `read` | Reads files, directories, images, PDFs | 2000 lines / 50 KiB; line truncation at 2000 chars; LSP warm-up |
| `edit` | Exact string replacement | fuzzy fallbacks (block anchor, whitespace, indentation); formatter; LSP diagnostics appended |
| `write` | Full-file write | uses the `edit` permission |
| `apply_patch` | Patch application | only for GPT models |
| `glob` / `grep` | File and content search | ripgrep-backed, permission-gated |
| `task` | Spawns a subagent | depth limit, permission derivation, background mode |
| `goal` | Sets the durable goal + verification | fork addition; root session only |
| `question` | Asks the user structured questions | gated by client type |
| `plan_exit` | Switches from plan to build | experimental, CLI only |
| `todowrite` | Maintains the session todo list | |
| `skill` | Loads a skill | |
| `webfetch` | Fetches a URL | markdown/text/html; 120 s max |
| `websearch` | Web search | Exa or Parallel |
| `browser` | Curated browser actions | attaches to the session Chromium |
| `lsp` | LSP queries | experimental |
| `execute` | Code Mode over MCP tools | experimental |
| `invalid` | Internal repair sink | never advertised to the model |

---

## 2. Tool-by-tool notes

### 2.1 `shell`

`packages/opencode/src/tool/shell.ts` is the most defended tool.

- Parameters: `command`, optional `timeout` (ms), optional `workdir`. The prompt tells the model to use `workdir` instead of `cd`.
- The command is parsed with **web-tree-sitter** using the bash or PowerShell grammar (`shell.ts:252-268`), then walked to collect:
  - absolute path arguments that point outside the worktree → `external_directory` ask;
  - command names and argument prefixes → `bash` ask patterns, reduced by `BashArity` so `git status` can be approved once.
- `ProcessGuard.broadKill` refuses `pkill -f`, `killall -r`, and `pgrep -f | kill` before the shell starts (`core/tool/process-guard.ts`). The reason: the tool's own `bash -c` command line matches those patterns, so QA once killed its own shell.
- Execution uses `ChildProcessSpawner` with a detached process group on POSIX; timeout and abort both kill with a 3-second force-kill window.
- Output: live preview through `ctx.metadata`; bounded tail in memory; full stream appended to a truncation file once it exceeds the byte limit; exit code and truncation path in metadata.

### 2.2 `read`

`packages/opencode/src/tool/read.ts`:

- `filePath`, optional `offset` (1-indexed) and `limit` (default 2000).
- Files: max 2000 lines, 50 KiB, each line clipped at 2000 characters with a suffix.
- Directories: paged entry listing.
- Images: JPEG/PNG/GIF/WebP, returned as attachments after optional resizing.
- PDFs: detected and attached.
- LSP: `touchFile` warms diagnostics for the file in the background.
- Not-found errors include suggestions from the parent directory listing.

### 2.3 `edit`, `write`, `apply_patch`

`edit` (`packages/opencode/src/tool/edit.ts`):

- Exact replacement with line-ending and BOM preservation, per-file lock, formatter invocation, and a unified diff in the permission metadata.
- If exact matching fails, it falls back through several replacers: line-trimmed, block-anchor with Levenshtein similarity, whitespace-normalized, and indentation-flexible matching. A matched span much larger than `oldString` is refused with a "re-read the file" message (line 711).
- After writing, it publishes edit/watcher events and appends LSP diagnostics to the output when the language server reports errors.
- The description says the tool errors if the file was not read first. I found **no read-ledger check** in `edit.ts`; the prompt is stricter than the code at this commit.

`write` creates or overwrites a file and asks for `edit`. `apply_patch` is the OpenAI-style patch tool and is only advertised for GPT models.

### 2.4 `task`

`packages/opencode/src/tool/task.ts`:

- Spawns a child session with a chosen subagent type.
- Enforces `subagent_depth` (default 1) by walking parent links.
- Reads the **root** session's goal and injects a warning into the child prompt when the goal is set but unauthorized.
- Asks for `task` permission with the subagent name, unless the prompt came from an explicit agent mention (`bypassAgentCheck`).
- Derives the child's permission set from the parent and the subagent's own rules, then adds denies for `todowrite` and recursive `task` unless the subagent already allows them.
- Supports `background: true` behind `OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS`; the tool returns immediately and the parent is notified on completion.

### 2.5 `goal` (fork)

`packages/opencode/src/tool/goal.ts` writes the durable goal, the size estimate, the contract, and optionally asks the human for authorization to run unattended.

- Refuses in subagents: "Goals belong to the root session."
- A `huge` goal returns a refusal that tells the model to propose a split instead of starting.
- The contract's `verification` must be one runnable command line. `goal-verification.ts` rejects prose markers ("plus", "and then", sentence boundaries, "screenshots", "make sure") with a message that names the fix.
- The verification becomes the gate: 300 s timeout, 3 retries.
- `commit: true` turns the goal into a question to the human; a yes authorizes it.

### 2.6 `browser` (fork)

`packages/opencode/src/tool/browser.ts` is a named surface over the `agent-browser` CLI, not a CDP client. It always attaches to the Chromium the session already runs, so the agent and the human watch the same page.

The action list is the whole vocabulary, and it deliberately omits `close`, `connect`, `cookies`, `storage`, `auth`, `clipboard`, `set`, and `network route`. Those cannot be named, so they cannot be called. Every action asks for `browser` permission first, then ensures the browser is up and spawns `agent-browser`, parsing its JSON envelope and returning the useful `data` as text.

### 2.7 `webfetch` / `websearch`

- `webfetch` only accepts `http(s)`, asks for `webfetch`, sends a browser-like User-Agent and content negotiation headers, retries with an honest UA if Cloudflare blocks it, and converts HTML to markdown by default. Timeout capped at 120 s.
- `websearch` picks Exa or Parallel, asks for `websearch` with the query as pattern, and injects the current year into its description at access time.

### 2.8 `skill`, `todowrite`, `question`, `plan_exit`

- `skill` loads a skill by name, lists its files, and returns the content plus the skill's base directory.
- `todowrite` maintains the session todo list and asks for `todowrite`.
- `question` asks structured questions and returns the selected labels. It is only registered for interactive clients.
- `plan_exit` asks the human whether to switch to the build agent; a yes creates a synthetic user message and switches the agent.

### 2.9 Code Mode and MCP

Two different adapters share the `execute` tool name:

- With code mode **off**, MCP tools are added directly as AI SDK dynamic tools (`session/tools.ts:426-528`). Each call asks for a permission named after the MCP tool key, with pattern `*`.
- With `OPENCODE_EXPERIMENTAL_CODE_MODE` **on**, direct MCP tools are not added (`session/tools.ts:424`). Instead, `packages/opencode/src/tool/code-mode.ts` exposes one `execute({ code })` tool. The code runs in the `@opencode-ai/codemode` confined interpreter, and `tools.<server>.<tool>(...)` maps to MCP calls.
  - The interpreter gets no filesystem, process, network, or module authority except the supplied tools.
  - Tool calls inside the program are permission-checked and plugin-hooked exactly like direct calls.
  - Progress metadata lists child calls with `running`/`completed`/`error`.
  - Attachments returned by MCP are collected and attached to the outer result.
  - Cancellation races the interpreter against the tool's abort signal.
  - The `execute` description embeds the generated catalog instructions, so the model sees which MCP tools exist and their signatures.

MCP resources get three extra tools when any connected server advertises the capability: `list_mcp_resources`, `list_mcp_resource_templates`, and `read_mcp_resource`. Binary blobs are attached only for PDF/PNG/JPEG/GIF/WebP and only up to 10 MiB.

### 2.10 Chaining, pipes, and what the parser does not see

The tool *asks* for chaining. `shell/prompt.ts:75` tells the model to use one Bash call with `&&` when commands depend on each other, to issue independent commands as parallel tool calls, and to prefer `workdir` over `cd`. So a model that writes `grep ... | sed ... >> out` is following the prompt, not drifting from it.

What the permission scanner does with a chain:

- `commands(root)` collects **every** `command` node in the tree, so each segment of `a | b && c` is scanned separately.
- Each segment contributes a pattern (`source(node)`) and a saved-approval prefix from `BashArity` (`shell.ts:409-410`). `git add *`, `npm run *`, and plain `echo *` are the granularity, not the full command line.
- All patterns go into one `ctx.ask`. Approving "always" writes one broad allow rule per segment.

That is a reasonable design for usability, but it leaves several gaps:

1. **Redirections are invisible to the external-directory check.** `parts()` explicitly skips `redirection` nodes (`shell.ts:100`), so `pathArgs` never sees the target of `>`, `>>`, or `2>`. The directory scan also runs only for a fixed list of file commands (`rm`, `cp`, `mv`, `mkdir`, `touch`, `chmod`, `chown`, `cat`, plus PowerShell aliases). `echo x > /outside/file` therefore produces no `external_directory` prompt. The first ask includes the whole redirected statement, but the saved prefix is `echo *`, which covers later redirects.
2. **Mutating commands bypass the `edit` permission.** `sed -i`, `tee`, `dd`, `truncate`, `git checkout -- .`, `perl -pi`, and `python -c "open(...)"` all run under `bash`. A policy that denies `edit` but allows `bash` does not prevent writes. `edit` is a tool-level action, not a filesystem boundary.
3. **Wrappers hide the real command.** `bash -c "..."`, `sh -c`, `eval`, `xargs`, and `find -exec` present the parser with the outer command and a string. The inner command is not segmented or path-scanned, and `dynamic()` disables path resolution once `$`, backticks, or `$(` appear.
4. **Pipelines mask failure.** The tool starts the configured shell (`$SHELL` if acceptable, otherwise `/bin/sh`) and never sets `pipefail`; I found no `pipefail` in the tree. In `grep foo file | sed ...`, the reported exit code is `sed`'s, so a failed `grep` looks like success. The model sees one exit code and one merged output stream, with no per-segment attribution.
5. **`bash` is the goal gate's deliberate hole.** ADR-0010 allows shell before the goal is authorized. The gate's path checks apply to `edit`, `write`, and `apply_patch`; an agent that implements through `bash` writes anywhere the shell can, including implementation files, and the gate never sees a path.
6. **The process guard is lexical, not structural.** `ProcessGuard.broadKill` flattens the entire command string and checks it, so `foo && pkill -f bar` is caught even though the parser segments it. That is the exception: most of the chain semantics are not modeled.

V2 makes the trade-off explicit rather than fixing it. `core/tool/bash.ts:143-146` emits warnings for absolute path arguments outside the worktree and its description says the scan is "advisory only"; the external-directory assert applies to `workdir`, not to arguments. Its whitespace tokenizer *does* see `> /outside/file` (the path is a separate token), but it only warns. V1's tree-sitter parser is more precise about arguments and misses redirections; V2's naive tokenizer sees redirections and does not ask. Neither is a boundary.

Practical consequence: if you want the `edit` permission or the goal gate to mean something for an agent that prefers shell composition, `bash` has to be treated as equivalent to `read` + `edit` + network, and governed at that level. The current model governs it as one action named `bash`.

---

## 3. The V2 stack

`packages/core/src/tool` is the canonical replacement. Its own `AGENTS.md` states the invariant: one local tool representation, one registry, one settlement boundary.

### 3.1 `Tool.make`

`packages/core/src/tool/tool.ts:71-132`:

```ts
const tool = Tool.make({
  description,
  input,          // Effect Schema
  output,         // Effect Schema
  structured?,    // optional structured-output schema
  toStructuredOutput?,
  execute(input, context): Effect<Output, ToolFailure>,
  toModelOutput?({ input, output }): Content[]
})
```

The returned value is a frozen opaque object. The runtime — codecs, executor, definition derivation, permission action — lives in a module-private `WeakMap`, so callers cannot reach into it.

- `definition(name)` lazily builds a `ToolDefinition` with JSON Schema for input and structured output.
- `settle(call, context)` decodes input, runs `execute`, encodes output, validates it against the output schema, derives the structured projection, and builds model content: text parts, or file parts as `data:` URLs.
- `withPermission(tool, action)` decorates a tool for catalog filtering. The registry uses it only for definition visibility; it is not public authorization.

### 3.2 Registration

Two scopes:

- `ApplicationTools.Service` (`application-tools.ts`) is process-global, shared by all Locations. It backs the public `opencode.tools.register(...)`.
- `Tools.Service` (`tools.ts`) is the narrow registration view exposed to Location-scoped producers.

`ToolRegistry.register({ name: tool })` (`registry.ts:85-105`) pushes onto a per-name stack with a token and identity. The latest active registration wins; closing one registration removes only its own entry and reveals the previous one. Location registrations overlay application registrations.

### 3.3 Materialize and settle

`materialize(permissions)` (`registry.ts:106-122`) snapshots the effective registrations into a `Map` and returns:

- `definitions`: the model-facing tool list;
- `settle(input)`: the only execution entry point.

`settle` looks up the tool by name, checks the registration identity against the snapshot, and returns `Stale tool call: <name>` if the tool changed after materialization. This matters for long provider turns: a call that arrives after a plugin reload cannot silently hit a different executor.

Execution flow (`registry.ts:50-82`):

1. Resolve the captured registration.
2. `Tool.settle(...)` decodes, executes, encodes, validates.
3. `ToolFailure` becomes a model-facing error result.
4. `ToolOutputStore.bound(...)` applies generic output bounds and may write a managed file.
5. The result becomes a `ToolResultValue`, with `output` and `outputPaths` when relevant.

`ToolOutputStore` (`packages/core/src/tool-output-store.ts`) uses the same 2000 lines / 50 KiB defaults, writes to a global `tool-output` directory, and keeps files for 7 days with a single global cleanup.

### 3.4 The V2 loop

`packages/core/src/session/runner/llm.ts:203-282`:

- `tools.materialize(agent.permissions)` runs once per provider turn. On the last allowed step, no tools are materialized, `toolChoice` is `"none"`, and `MAX_STEPS_PROMPT` is appended.
- Tool definitions go into the `LLM.request`.
- For each `tool-call` event that is not provider-executed, the runner starts `settle` in a `FiberSet` and publishes a `tool-result` event. The call runs under `uninterruptibleMask` with `restore` around `settle`, so the tool keeps the caller's interruptibility while publishing the result cannot be interrupted.
- After the stream ends, it awaits every settlement fiber before continuing. Interruption, provider failure, and user declines each have explicit failure paths that mark unsettled calls.
- The loop continues when any local tool call was settled.

This is the same conceptual loop as V1, but the dispatch is owned by the runner rather than the AI SDK.

### 3.5 V2 permissions

Tools call `PermissionV2.assert` directly (`packages/core/src/permission.ts:147-212`):

```ts
permission.assert({
  action: name,
  resources: [resource],
  save: ["*"],
  sessionID,
  agent,
  source: { type: "tool", messageID, callID }
})
```

- Agent rules come from the session's agent; saved rules come from the permission store.
- Any `deny` short-circuits with `BlockedError`.
- `allow` returns immediately.
- `ask` publishes an event and waits. A decline dies with `DeclinedError`, which the runner treats as "user declined" and stops the loop rather than sending the tool an error result.

The registry itself has no permission dependency. Catalog filtering and execution authorization are deliberately separate.

### 3.6 Porting status

Already ported to V2 (`builtins.ts`): `apply_patch`, `bash`, `browser_*`, `edit`, `glob`, `grep`, `question`, `read`, `skill`, `todowrite`, `webfetch`, `websearch`, `write`.

Still V1-only or explicitly deferred, per the TODO in `builtins.ts` and the gaps in `tool/AGENTS.md`:

- `task`, LSP, `repo_clone`, `repo_overview`, `plan_exit`, and Code Mode/Rune.
- Plugin boot is not yet routing through `Tools.Service`.
- MCP and session-scoped registrations have no canonical design yet.
- The public session result still exposes `outputPaths`; full storage encapsulation is pending.
- V2 `bash` has fewer defenses than V1: no tree-sitter parser, no arity reduction, token-based external-directory advisories only. Its TODO list is explicit about the parity debt.
- V2 `edit` is exact-only; the V1 fuzzy/indentation fallbacks and formatter/LSP hooks are TODO.

One visible divergence: V1 ships one `browser` tool with an action enum; V2 ships seven separate `browser_*` tools over a CDP session. They are two different designs for the same boundary, recorded in ADR-0005 and ADR-0003 respectively.

---

## 4. What the fork adds

1. **Goal gate** (`OPENCODE_GOAL_REQUIRED`).
   `session/goal-required.ts` is a pure function over tool name, args, worktree, and goal state. Before the root goal is authorized, only an allow-list runs: reads, searches, questions, research, skills, `bash`, `browser`, `task`, and plan tools. Edits are limited to `docs/adr/`, `.opencode/scratchpads/`, and `.opencode/plans/`. Unknown tools are refused, so a newly added tool cannot slip through by omission. The allow-list names `bash` and `browser` as deliberate holes.

2. **Goal tool** (ADR-0006/0010/0011).
   Durable goal, contract, verification gate, root-only ownership, prose-verification refusal.

3. **Browser tool** (ADR-0005).
   One Chromium shared with the human, curated action list, no way to close or repoint it.

4. **Process guard** (ADR-0006 live-fire finding).
   Refuses broad pattern kills that would match the tool's own shell.

5. **Truncation hint aware of subagents**.
   When the calling agent can use `task`, the hint tells it to delegate the full output to the explore agent instead of reading it into its own context.

---

## 5. Gotchas and observations

- **Tool id and permission action can differ.** The tool is `shell`; its permission is `bash` (`tool/shell/id.ts` keeps the old name for compatibility).
- **`edit`, `write`, and `apply_patch` share one permission.** Approving one approves all three.
- **`external_directory` is a separate action.** A tool can be allowed for the worktree but still prompt for an outside path; the prompt grants the parent directory glob.
- **`deny *` hides a tool; it does not just block calls.** Visibility filtering removes it from the model's catalog, but execution still asks.
- **Doom-loop detection keys on exact JSON equality** of the last three tool inputs, so formatted-but-equivalent arguments can evade it.
- **The `invalid` tool is a repair sink**, not a model tool. `activeTools` excludes it.
- **Descriptions are partly generated at request time**: `websearch` injects the current year, `task` appends the allowed subagent list, `execute` appends the MCP catalog.
- **Code mode replaces direct MCP tools**; when the flag is on, the model cannot call MCP tools directly, only through `execute`.
- **The V2 registry is Location-scoped, the application tool store is process-global.** A tool registered by an app is visible to every Location; a Location tool shadows it.
- **V2 reports `Stale tool call` instead of executing a changed tool.** That is intentional, but it means a mid-turn plugin reload can turn a call into an error.
- **Both stacks truncate output, but at different points.** V1 truncates inside the tool wrapper; V2 truncates in the registry's settlement boundary. Tools that already manage their own output (shell) bypass the wrapper.
- **The V1 `edit` prompt promises a read-before-edit error that the code does not implement** at this commit. The prompt and the implementation disagree.
- **A shell chain is one tool call but many capabilities.** Permissions are evaluated per segment, saved rules are command prefixes, redirections are not path-scanned, and mutating subcommands run under `bash`, not `edit`. See §2.10.

---

## 6. Reading map

| Question | File |
| --- | --- |
| V1 tool contract and wrapper | `packages/opencode/src/tool/tool.ts` |
| V1 registration, filtering, plugin/custom tools | `packages/opencode/src/tool/registry.ts` |
| V1 tool → AI SDK adapter | `packages/opencode/src/session/tools.ts` |
| V1 permission semantics | `packages/opencode/src/permission/index.ts` |
| V1 output truncation | `packages/opencode/src/tool/truncate.ts` |
| V1 turn events and tool parts | `packages/opencode/src/session/processor.ts` |
| Goal gate | `packages/opencode/src/session/goal-required.ts` |
| V2 tool value | `packages/core/src/tool/tool.ts` |
| V2 registry and settlement | `packages/core/src/tool/registry.ts` |
| V2 runner loop | `packages/core/src/session/runner/llm.ts` |
| V2 permission | `packages/core/src/permission.ts` |
| V2 output store | `packages/core/src/tool-output-store.ts` |
| Code Mode | `packages/opencode/src/tool/code-mode.ts`, `packages/codemode/README.md` |
| Architecture rules | `packages/core/src/tool/AGENTS.md` |
