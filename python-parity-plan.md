# Native tool parity: the remaining tools

Status: browser V1 is implemented. The Python catalog maps 13 V1 native tools;
LSP is deliberately deferred.

## What parity means

"Parity" here means **every native tool that can run without a model or human
turn has a Python SDK method**. It does not mean the SDK exposes the human
tools, the internal repair tool, or code-mode recursion.

| Class | Examples | In Python |
| --- | --- | --- |
| Programmatic native | read, glob, grep, edit, write, apply_patch, bash, webfetch, websearch, skill, todowrite, task | yes |
| Stateful native | browser | yes |
| Deferred | lsp | no — the user treats lint/build verification as sufficient |
| Human-owned | question, goal, plan_exit | no — the model owns them |
| Internal | invalid | no |
| Meta | execute | no recursion |
| External | MCP, plugin/custom | out of scope for native parity |

The V1 and V2 stacks are not identical. The catalog currently maps V1. V2 has
seven `browser_*` tools, no `task`, no `lsp`, and no `plan_exit`. A V2-backed
catalog therefore has a different target.

## The gap

```
V1 programmatic target: 14
  done:     13  (fs, mutate, shell, web, state, agents, browser)
  deferred: 1   (lsp)

V2 programmatic target: 18
  done:     11  (bash, read, glob, grep, edit, write, apply_patch,
                 webfetch, websearch, skill, todowrite)
  missing:  7   (browser_navigate, browser_read, browser_click,
                 browser_type, browser_screenshot, browser_back,
                 browser_forward)
  not ported by the fork: task, lsp, plan_exit
```

## 1. Browser

This is the largest practical gap. The unblocked arm B run drove
`agent-browser` through `subprocess`; the blocked arm could not test the page at
all.

### Python surface

```python
from agent import browser

page = browser.page()
page.goto("http://127.0.0.1:3000")
page.snapshot(urls=True, compact=True, depth=3, selector=None)
page.text()                                # readable page text
page.get("text", "#status")                # text, html, value, title, url, count, box, styles
page.get("attr", "#link", name="href")
page.is_("visible", "#save")               # visible, enabled, checked
page.find("role", "button", "click", name="Save", exact=True)
page.click("@e3")                          # also dblclick, hover, focus
page.fill("#new-todo", "Buy milk")         # clear + type; type appends
page.type("@e4", " more")                  # real keystrokes
page.press("Enter")
page.keyboard("typed text"); page.keyboard_insert("pasted")
page.select("#size", "large")
page.check("#done")
page.scroll("down", 500)
page.scroll_into_view("#footer")
page.drag("#card", "#column")
page.wait("#result"); page.wait_ms(250)
page.wait_text("Saved"); page.wait_url("**/done"); page.wait_load("networkidle")
page.wait_function("window.ready"); page.wait_state("#spinner", "hidden")
page.wait_download("/tmp/report.pdf")
page.screenshot(path="shot.png", full=False)   # Screenshot
page.pdf("page.pdf")
page.back(); page.forward(); page.reload()
page.push_state("/settings")
page.tabs(); page.tab_new(); page.tab_select("0")
page.console(clear=True); page.errors(); page.network(); page.vitals(); page.diff()
page.evaluate("document.title")
page.highlight("#save"); page.inspect()
page.mouse_move(100, 200); page.mouse_down(); page.mouse_up(); page.mouse_wheel(120)
```

Rules:

- `Page` is a stateless façade over the **one browser the process owns**.
  `page()` takes no endpoint, session, or instance argument. Every method is
  one bridge call; the host resolves `Browser.Service.ensure` and `endpoint`
  each time, so a Page survives a browser restart but cannot select another
  browser.
- There is no `close`, `connect`, `cookies`, `storage`, `auth`, `clipboard`,
  `set`, or `network route`. There is no tab close: the human's tab is not ours
  to remove. `get cdp-url` is refused for the same reason: it would hand out a
  second route into the shared browser.
- Take a snapshot before acting; `@ref`s expire on navigation.
- Screenshot is a `Screenshot` value: `path`, `mime`, and `data` (base64) when
  the host can read the file. The V1 tool returns a saved path; the Python
  adapter reads the bytes on the host. The V2 tool returns an attachment.
- `eval` is V1-only. Under V2 it raises `unavailable`.

### Host mapping

V1: one `browser.call` runtime tool over the native `browser` tool. This is
implemented in `catalog.ts` and `python.ts`.

```
Python Page.goto(url)
  -> {"action":"navigate","url":url}
  -> native browser tool (action enum, permission "browser")
  -> Browser.Service.ensure -> Browser.Service.endpoint
  -> agent-browser --cdp <port> --json open <url>
```

The native tool is the ownership boundary. It is created once with
`Browser.Service`; `ensure` is idempotent; `endpoint` is read from that service.
The Python program cannot pass a port or URL for a different browser, and the
catalog has no `browser.connect` or `browser.close`.

V2: seven native tools. The same `Page` methods map to:

| Page method | V2 tool |
| --- | --- |
| `goto` | `browser_navigate` |
| `text` / `read` | `browser_read` |
| `click` | `browser_click` |
| `fill` / `type` | `browser_type` |
| `screenshot` | `browser_screenshot` |
| `back` / `forward` | `browser_back` / `browser_forward` |

The current catalog has only the V1 `browser.call` spec. If the registry has no
`browser` tool, the spec is omitted; it does not synthesize a V2 mapping. The
future V2 adapter has to choose the seven tools by presence:

```ts
const browser =
  tools.has("browser") ? v1Browser(tools.get("browser")!) :
  tools.has("browser_navigate") ? v2Browser(tools) :
  undefined
```

The permission stays `browser` in both. V1 asks with the action as the pattern;
V2 asks with its own action. The host adapter must preserve the action in the
metadata so the human sees what the page will do. Do not add the V2 mapping
until the live stack moves.

### Output

`browser.call` returns a small object per action:

```json
{"action": "snapshot", "text": "..."}
```

For `screenshot` it also returns `path` and `mime`; `python.ts` reads the file
when it can and adds `data` as base64. Python parses that into:

```python
@dataclass(frozen=True)
class Screenshot:
    path: str
    mime: str = "image/png"
    data: str = ""        # base64

    @property
    def bytes(self) -> bytes: ...
```

Text actions (`snapshot`, `read`, `console`, `errors`, `network`, `vitals`,
`diff`) return `str`. `get` decodes the tool's JSON and returns the useful
field: text, html, value, title, url, count, box, or the styles object. `is_`
returns `bool`. `screenshot` returns `Screenshot`. There is no `BrowserResult`
wrapper; the Page methods are the typed surface.

### Tests

- Fake host: every Page method produces the exact V1 payload and parses the
  canned result. Done in `tests/test_browser.py`.
- Native mapping: `browser.test.ts` covers the safe CLI commands, the new
  snapshot/wait/mouse/scroll/find forms, and the refused command surface.
- Catalog: `python-catalog.test.ts` covers the field mapping, text output, and
  screenshot path; `python-manifest.test.ts` covers the 13th tool.
- Harness: done. The
  [browser run](../harness/runs/2026-11-18-browser-prometheus/analysis.md) uses a
  `data:` page, snapshot, `get` title and attribute, `is_` visibility, and a
  screenshot. One Python call, six `browser.call` child calls, no raw file,
  process, or socket calls. The base image already has Chromium and
  `agent-browser`; no `OPENCODE_EAGER_BROWSER` was needed.

## 2. LSP

The V1 `lsp` tool is an operation enum. The Python surface maps one-to-one.

```python
from agent import lsp

lsp.definition("src/main.ts", 12, 8)        # list[Location]
lsp.references("src/main.ts", 12, 8)
lsp.hover("src/main.ts", 12, 8)
lsp.document_symbol("src/main.ts")
lsp.workspace_symbol("SessionRunner")
lsp.implementation("src/main.ts", 12, 8)
lsp.prepare_call_hierarchy("src/main.ts", 12, 8)
lsp.incoming_calls("src/main.ts", 12, 8)
lsp.outgoing_calls("src/main.ts", 12, 8)
```

- Lines and characters are 1-based, as the tool already is.
- `document_symbol` and `workspace_symbol` pass `line = 1`, `character = 1`;
  the tool does not use them for those operations.
- Results are the tool's `metadata.result` array, not the formatted output.
  Keep them as `list[dict]` until the LSP result shapes are modelled; they are
  provider-specific.
- The tool asks `lsp` permission with pattern `*`.
- Experimental: the catalog includes the module only when `lsp` exists in the
  registry. No LSP server means the native tool returns "No LSP server
  available"; the SDK surfaces that as `AgentError`.
- There is no `lsp.diagnostics` native tool. Diagnostics arrive through
  `read`/`edit`; do not invent a parity claim.

## 3. Human, goal, and plan tools

These stay outside the SDK. Making them callable from a program would let a
program block on the UI or authorize its own goal.

- `question`: the model asks. A program can return a value:

  ```python
  from agent import NeedsHuman

  def Run(ctx, a):
      return NeedsHuman(question="Which database?", options=["postgres", "sqlite"])
  ```

  The host serializes it as `{"kind":"needs_human", ...}`. The model sees the
  result and calls `question` on the next turn. The top-level toolset must
  include `question` for that to work.
- `goal`: the root session owns it. `python` is refused until the goal is
  authorized. A program can return `NeedsGoal`; the model calls `goal`.
- `plan_exit`: UI state; the model owns it.

The Python prompt should state this: "You cannot ask the human from a program;
return `NeedsHuman` and let the model ask."

## 4. V2-only and V2-missing tools

- Browser: the seven V2 tools are the mapping target. The V1-only actions
  (`eval`, `tabs`, `network`, `vitals`, `pdf`, `upload`, `download`, `pushstate`)
  are absent under V2; the `Page` methods raise `unavailable`.
- `task`: V2 has no task tool. The current `agents.tasks.run` is V1-shaped. A
  V2 catalog omits it until the fork ports task; the Python method should not
  pretend otherwise.
- `lsp`: V2 has no LSP tool. Same rule.
- `plan_exit`: V2 has no plan tool.

The catalog builder already filters by tool presence. The rule is: **no native
tool, no Python method**. Never synthesize a method that the host cannot run.

## 5. Out of native scope

- MCP tools and resources: the JS `execute` path already handles them. If
  Python needs them, generate `agent.mcp.<server>.<tool>` from the MCP catalog;
  that is a separate contract with generated schemas and resource tools.
- Plugin/custom tools: `agent.custom.<name>` with a trust label; defer.
- `execute`: no recursion.
- `invalid`: internal.

## 6. Implementation order

1. **Browser V1** — done.
2. **Browser V2 mapping** — seven tools; add when the live stack moves.
3. **`NeedsHuman` / `NeedsGoal`** — a type and prompt, not a tool call.
4. **V2 task ports** — fork work, not SDK work.
5. **MCP/plugin** — separate project.

LSP is deferred by decision, not by a technical blocker. Do not add it without a
new request.

## 7. Parity test

Add a test that compares the native tool ids with the catalog:

```text
V1 native ids: bash, read, glob, grep, edit, write, apply_patch, task,
               webfetch, websearch, skill, todowrite, browser, lsp,
               question, goal, plan_exit, execute, invalid
Python specs:  ...
Explicit out-of-scope: question, goal, plan_exit, execute, invalid
```

The test fails when a new native tool appears without a spec or an explicit
exclusion. That is how parity stops drifting silently.

## 8. Resolved and open questions

- Screenshot: path-first (V1 parity) or bytes-first (V2 convenience)? Resolved:
  return the path and, when the host can read it, base64 bytes. Python exposes
  both on `Screenshot`.
- V2 browser mapping remains open until the live stack moves to the seven
  `browser_*` tools.
- V1-only browser actions under V2: expose as `unavailable`, or emulate some
  (for example `tabs` via CDP)? Start with `unavailable`.
- LSP result types: `list[dict]` is honest. Full dataclasses should follow the
  language-specific result shapes only if the model needs them.
- Does `NeedsHuman` belong in the result envelope, or should the host detect a
  `NeedsHuman` value and return a protocol-level `needs_human` event? Start with
  the value in the result; it is simpler and visible to the model.
- V2 task/lsp: who ports them, and when? Until then, a V2 catalog is not at
  parity with V1.
