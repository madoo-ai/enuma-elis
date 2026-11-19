# Scratch browser: design note

Status: proposal. No code. Needs a decision before work starts.

## Problem

`browser.page()` drives the Chromium the human is watching. To keep that safe,
the tool cannot change the viewport, intercept requests, set cookies, mock
geolocation, go offline, or close anything. Models still want exactly those
things:

- `harness/runs/arms/U-20261119T020727`: the model wrote raw CDP scripts in
  node to test 360, 768, and 1280 px widths.
- `harness/runs/2026-11-18-todo-prometheus`: the model started its own
  `agent-browser` session to test `localStorage`, reloads, and disabled states,
  then ran `close --all`.

Raw scripts and CLI sessions work around the safety model instead of using it.
Better to give the agent a browser it is allowed to own.

## Proposal

`browser.scratch()` returns a `Page` backed by a headless Chromium that the host
starts for the agent.

| | `browser.page()` | `browser.scratch()` |
| --- | --- | --- |
| Owner | the human | the program's session |
| Display | the human's screen | none (headless) |
| Profile | the human's | a new temp profile |
| Viewport, offline, geolocation | refused | allowed (`page.emulate(...)`) |
| Request mocking and blocking | refused | allowed (`page.route(...)`) |
| Cookies and storage | refused | allowed (`page.cookies`, `page.storage`) |
| Close | refused | allowed, and automatic at session end |
| Parallel use | one page, serial | several pages under `agent.jobs` |

Same `Page` class, same helpers (`find_one`, `audit`, `extract`, ...). The
helpers are the point: they work on either browser.

## Ownership boundary

The rule is "the agent may do anything to a browser it started, and nothing to
one it did not." Three places enforce it:

1. **Host action table.** The scratch tool has its own table. The shared tool's
   table does not grow. A test asserts the shared table still names none of the
   new actions.
2. **Endpoint.** The host picks the CDP port for each browser. The program never
   sees a port or a URL. `scratch` takes no endpoint argument.
3. **Lifecycle.** The host tracks scratch browsers by session id and kills them
   when the session ends or the program is cancelled.

## Limits

- At most 3 scratch browsers per session, 5 pages each. Over the limit is an
  `unavailable` error that names the limit.
- Memory cap through the container's cgroup, not through Chromium flags.
- No network isolation by default. Scratch pages can reach whatever the Python
  sandbox can reach. If the arm has `OPENCODE_PYTHON_NETWORK=false`, scratch
  pages must obey it too (run Chromium in the same network namespace).
- The profile is deleted on close. Nothing persists unless the program saves it
  to the workspace.

## Open questions

1. Where does Chromium run when the Python sandbox is `bwrap`? The host starts
   it outside the sandbox and talks to it over a socket; the program gets a
   handle, not a port.
2. Should `scratch()` be a separate permission (`browser_scratch`) so an
   operator can allow the shared page and deny the scratch one, or the reverse?
   Recommended: yes.
3. Is it worth keeping `file://` and `localhost` reachable? Local app testing is
   the main use, so yes, same as today.
4. Screenshots: return bytes through the bridge, as for the shared page.

## Order of work if approved

1. Host: a `scratch` tool with its own action table and a session-scoped
   Chromium manager. Tests mirror `browser.test.ts`, including the "excluded
   surface" tests.
2. SDK: `browser.scratch()`, plus `emulate`, `route`, `cookies`, `storage`,
   `close`, on a `ScratchPage(Page)` subclass so the shared `Page` never gains
   them.
3. Prompt: a short second section, only when the scratch tool is enabled.
4. Harness scenario: viewport sweep and offline test, replacing the raw CDP
   script from the U run.
