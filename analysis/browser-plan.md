# Browser extension plan

Goal: let a program combine browser steps without hand-parsing strings or
chasing expired refs. `browser.page()` stays the one session browser the human
shares: no launch, connect, close, or tab close.

Why: today `Page` is a 1:1 wrapper that returns strings. Dumps in
`harness/runs/` show models regex-parsing text, hedging on result types, and
losing refs between steps.

Real output shapes (captured from `agent-browser --json`, 0.27):

- `snapshot`: `- heading "Hi" [level=1, ref=e1]`, `- textbox "Email" [ref=e3]: a@b.c`,
  nested by two-space indent.
- `console`: `{"messages":[{"type":"log|error|warning","text":...,"args":[...]}]}`
- `errors`: `{"errors":[{"text","line","column","url"}]}`
- `network requests`: `{"requests":[{"url","method","status","resourceType","mimeType",...}]}`;
  `status` is absent while a request is pending or failed.
- `tab list`: `{"tabs":[{"tabId","url","title","active","type","label"}]}`
- `get box`: `{"x","y","width","height"}`; `eval`: `{"result": <json>}`.
- `dialog <accept|dismiss|status> [text]`, `frame <selector|main>` exist.

## Work items

Status values: `todo`, `done`.

### B1. Structured snapshot

**Status:** done

- `Node(role, name, ref, value, level, flags, depth)` parsed from the tree.
- `page.nodes(**snapshot_args)`, `page.find_all(role=, name=, contains=)`,
  `page.find_one(...)` (raises `not_found` with the closest names listed).
- Tolerate unknown lines; never raise on a line that does not parse.

### B2. Element handles with stale-ref recovery

**Status:** done

- `Element` with `click`, `dblclick`, `hover`, `focus`, `check`, `uncheck`,
  `fill`, `type`, `select`, `text`, `value`, `scroll_into_view`.
- On a tool failure the handle re-snapshots, finds the same role and name (and
  nth match), and retries once. It never retries blindly.

### B3. Typed lists

**Status:** done

- `console()` -> `list[ConsoleMessage]`, `errors()` -> `list[PageError]`,
  `network()` -> `list[Request]`, `tab_list()` -> `list[Tab]`, `diff()` ->
  `Diff(changed, additions, removals, text)`.
- All use the dict-style result mixin. A non-JSON reply degrades to one item
  holding the raw text.

### B4. Generic polling

**Status:** done

- `page.until(predicate, timeout=30, interval=0.25, message=None)`.
- `wait_text` uses it; add `wait_gone(text)` and `wait_count(selector, n)`.

### B5. Extraction

**Status:** done

- `links()`, `headings()`, `forms()`, `table(selector)`,
  `extract({"name": "css selector"})` through fixed JS run by `evaluate`.

### B6. Audit

**Status:** done

- `page.audit()` -> `PageReport(url, title, console_errors, console_warnings,
  page_errors, failed_requests, ok)`. One call for a smoke check.

### B7. Screenshots in the workspace

**Status:** done

- `Screenshot.save(path)` writes the decoded bytes; falls back to copying the
  host path when no bytes crossed the bridge.
- `page.screenshot(save="out.png")`.
- `page.goto_file("index.html")` builds an absolute `file://` URL.

### B8. Action history

**Status:** done

- `page.history` lists the actions as Python source lines;
  `page.to_script()` returns a replayable program.
- Element actions record `find_one(role, name)` so the script survives new refs.

### B9. Host actions: frame and find input

**Status:** done

- Added `frame` to the fork's `browser` tool and the `Page` API.
- Added `input` to `find`, so `find label Email fill <text>` can carry its text.
- **Dropped `dialog`.** A probe showed `agent-browser` auto-dismisses alerts
  (`dialog status` always reports none, `dialog accept` says "No dialog is
  showing"). Turning that off would let an alert freeze the human's page, so
  there is nothing safe to expose. A test asserts `dialog` is not an action.
- The `find` locator list already accepted `nth`, `first`, `last`, `testid`.

### B10. Prompt and docs

**Status:** done

- Update `BROWSER_GUIDE`, result shapes, and the Python tool tests.
- Document the combinations that now work (see "Combinations" below).

### B11. Live check

**Status:** done

- `tests/live_browser_host.py` maps `browser.call` to the real `agent-browser`
  CLI in a private session. `tests/test_browser_live.py` uses it and is skipped
  unless `AGENT_BROWSER_LIVE=1` and the binary exist. Run it with:
  `AGENT_BROWSER_LIVE=1 python3 -m unittest discover -s tests -p test_browser_live.py`
- One harness scenario with a multi-step flow on the rebuilt binary.

### B12. Scratch browser design note (no code)

**Status:** done

- `analysis/browser-scratch-design.md`: an agent-owned headless Chromium behind
  `browser.scratch()`. Covers ownership boundary, allowed commands, lifecycle,
  and what stays out of the shared page.

## Combinations this unlocks

- find -> act -> re-find without ref bookkeeping (B1, B2).
- navigate -> audit -> save screenshot to the workspace -> hand to a reviewer
  subagent (B6, B7, `agents.tasks.run`).
- explore once -> `to_script()` -> `mutate.write` a regression test (B8).
- extract page data -> `fs`/`mutate` write -> `shell` run a check (B5).
- `web.fetch` raw HTML versus rendered `page.text()` (existing modules).

## Out of scope

- Any launch, connect, close, cookies, storage, route, clipboard, or viewport
  change on the shared browser.
- A `dialog` action (see B9).
- `network har`: the file lands on the host, not in the program's workspace.
- The scratch browser itself (design note only).

## Validation

- Unit tests: 100 pass (9 live tests skipped by default).
- Live tests against a real Chromium through `agent-browser`: 9 pass. They cover
  node parsing, stale-ref recovery after a reload, `find ... fill` with input,
  typed console, error, network and tab lists, audit, extraction, polling, and
  screenshot save plus `to_script`.
- Scenario `browser_helpers` on the rebuilt binary, shared browser, model-driven.
  The model wrote a to-do page, added two items through element handles, read
  the list with `extract`, audited the page, and saved `shot.png` (9031 bytes)
  into the workspace. Its third program did all of it.

What the scenario found, and the fix:

| Observed | Fix |
| --- | --- |
| `page.wait_load()` with no state raised `TypeError` | `state` defaults to `"load"` |
| `write_result["path"]` raised `KeyError` | `WriteResult.path` and `EditResult.path` alias `file` |
| The audit JSON had no `ok`, so the model recomputed it | `ok` is included in JSON for `PageReport` and `Request` |
| In unbounded mode no screenshot bytes cross the bridge | `Screenshot.save` copies the host path as a fallback (worked: 9031 bytes) |

Known limit: in `bwrap` mode the host path is not readable, so `save` relies on
the bytes the bridge forwards. That path is covered by a unit test but was not
run live, because `bubblewrap` could not be installed in the harness container.
