# Scratch browser implementation plan

Decision (approved by the user): implement an agent-owned browser.
`browser.scratch()` returns a page the program may resize, block, seed, and close.
`browser.page()` is unchanged and stays locked down.

## Design decisions

1. **One scratch browser per program.** Two callers cannot drive each other's
   pages, so there is no cross-call ownership confusion. The session name is
   passed to the tool as `session`; the SDK generates it once per program and
   reuses it. A second `browser.scratch()` returns a handle to a new tab in the
   same browser.
2. **Launch through agent-browser's `--session`.** No CDP port, no endpoint, no
   executable path ever crosses the bridge. The host starts the daemon lazily on
   the first command and stops it on `close`.
3. **Agent-owned by construction.** The session name carries an `enuma-scratch-`
   prefix plus a random id the host adds. `close` accepts only that prefix, and
   only the exact session it was given. The human's browser is never named.
4. **Private profile per session.** `--profile` points at a fresh temp directory
   under the host's state dir; nothing is persisted. Close deletes it.
5. **Own action table.** The scratch table adds `viewport`, `device`, `geo`,
   `offline`, `media`, `route`, `unroute`, `cookies`, `storage`, `tabclose`,
   `headers`, `useragent`. The shared table does not grow. A test asserts the
   shared table names none of these.
6. **Permission** `browser_scratch`, separate from `browser`. An operator can
   allow one and deny the other.
7. **Python-only module allow-list flag** `OPENCODE_PYTHON_SCRATCH=1`, because a
   scratch browser can read cookies and intercept requests. Off by default; the
   harness scenario turns it on explicitly.
8. **No HAR, trace, record, stream, clipboard, auth vault, extensions, or
   init-script files.** They either write to host paths the program cannot see
   or read host state. `screenshot` and `download` take workspace paths and are
   copied through the bridge, same as the shared page.
9. **Same `Page` class.** `ScratchPage` adds the scratch-only methods; the
   shared `Page` never gains them.

## Work items

Status: `todo` until done.

### S1. Split the browser action table so it is reusable

**Status:** done

- `src/tool/browser-actions.ts`: the shared `SPECS`, `ACTIONS`, `Parameters`,
  `buildArgs`, `renderResult`, `commandFor` move here unchanged.
- `src/tool/browser.ts` keeps the shared tool and re-exports the pieces its
  tests import, so existing tests keep passing without edits.

### S2. Scratch action table and command builder

**Status:** done

- `src/tool/scratch-actions.ts`: `SCRATCH_ACTIONS`, parameters, `buildScratchArgs`.
- Adds `session` to every command line as `--session <name>` and a private
  `--profile` directory.
- `close` uses `agent-browser close` on that session only.

### S3. Host tool with lifecycle

**Status:** done

- `src/tool/scratch.ts`: `ScratchTool`, id `browser_scratch`.
- Resolves a random session name on the first call and keeps it in the run dir;
  the program passes the name the SDK generated, so repeated calls share it.
- Rejects any session name that does not match `^enuma-scratch-[a-f0-9]{8}$`.
- Deletes the profile directory after a `close` action.

### S4. Register behind a flag

**Status:** done

- `tool/registry.ts`: add `browser_scratch` to the builtin list only when
  `OPENCODE_PYTHON_SCRATCH=1` or the new runtime flag is set. Simplest: an env
  check next to the python-mode gate, no new RuntimeFlags plumbing.
- Python catalog: a new spec `browser.scratch` that maps to the tool.

### S5. SDK: `ScratchPage`

**Status:** done

- `agent/browser.py`: `Page.__init__(session=None)`. When set, `_raw` sends
  `browser_scratch.call` and includes `session`.
- `browser.scratch()` creates the session id once per program and returns a
  `ScratchPage`.
- New methods: `viewport(w, h)`, `device(name)`, `geo(lat, lng)`, `offline(on)`,
  `media(scheme, reduced_motion)`, `route(url, abort/body)`, `unroute(url)`,
  `cookies()`, `set_cookie(...)`, `clear_cookies()`, `storage(kind)`,
  `set_storage(kind, key, value)`, `clear_storage(kind)`, `headers(json)`,
  `user_agent(ua)`, `tab_close(target)`, `close()`.
- `close()` marks the handle closed; later calls raise `unavailable`.

### S6. Prompt

**Status:** done

- `SCRATCH_GUIDE` in `describeCatalog`, only when the scratch tool is enabled.
- States clearly what scratch may do that the shared page may not, and that the
  profile is temporary.

### S7. Tests

**Status:** done

- Fork: `test/tool/scratch.test.ts` mirrors the shared browser tests: every
  action builds a command, the session and profile flags are right, `close`
  cannot name another session, and the shared table gains nothing.
- SDK: extend the live harness so it runs the same page helper tests against a
  scratch page, plus scratch-only checks (viewport, offline, route, cookies,
  storage, tab close, close).
- Offline unit tests for the new methods against a scripted host.

### S8. Live verification

**Status:** done

- Run the scratch live suite against a real Chromium.
- One harness scenario that reproduces the U run's viewport sweep (360, 768,
  1280) with `page.viewport` instead of a hand-written CDP script.

### S9. Docs

**Status:** done

- Update `analysis/browser-scratch-design.md` to record what was built and what
  was left out, and why.
- Note the new flag in `harness/README.md`.

## What was built, and what changed along the way

- `src/tool/browser-actions.ts` holds the shared table; `browser.ts` re-exports
  it, so the shared surface and its tests are unchanged.
- `src/tool/scratch-actions.ts` adds `viewport`, `device`, `geo`, `offline`,
  `media`, `headers`, `route`, `unroute`, `cookies`, `storage`, `tabclose`,
  `close`. `src/tool/scratch.ts` runs them with `--session` and a private
  `--profile` directory, and deletes the profile on `close`.
- Registered as `browser_scratch` only when `OPENCODE_PYTHON_SCRATCH=1`.
- SDK: `browser.scratch()` returns a `ScratchPage(Page)`; the shared `Page` has
  none of the new methods. One browser per program; `tab_new` for more pages.
- `close()` disables the handle; later calls raise `unavailable`.

Deviations from the first design:

1. **One scratch browser per program**, not three per session. Simpler
   ownership, no cross-program interference.
2. **Response mocking was dropped.** `agent-browser network route --body` did
   not intercept requests in 0.27; the real request still went out (verified
   against a local HTTP server). Only `--abort` is exposed, and the host rejects
   a `body` with a clear error rather than silently not mocking.
3. **No HAR, trace, profiler, video, streaming, clipboard, auth vault, or
   credentials**, as planned.
4. **Offline is exposed but network isolation is not.** `offline()` only changes
   what the page believes; it does not sandbox the browser's network access.

Bugs the harness scenario caught, now fixed:

| Symptom | Cause | Fix |
| --- | --- | --- |
| `unavailable: tool not enabled: browser_scratch.call` | SDK and catalog used different names for the same tool | SDK now calls `browser.scratch`, matching the catalog spec |
| `tab_select` failed with "No tab with label `select`" | the shared table built `tab select <id>`, which the CLI reads as a label | the command is now `tab <id>` |
| `fs.write` guessed again | no hint on the module | `fs.write/edit/patch` now raise with "use mutate.write(...)" |
| Bridge test flaked on short-lived programs | drain listeners attached after the streams had already closed | handle already-ended streams and cap the drain wait at 250 ms |

## Validation

- Fork tool tests: 440 pass, including `scratch.test.ts` (command mapping,
  session/profile flags, refusal of foreign session names, and a test that the
  shared table gained nothing).
- SDK unit tests: 116 pass (16 live tests skipped by default).
- Live scratch tests against a real Chromium: 7 pass. They cover the shared page
  helpers on a scratch page, viewport changes, request blocking, offline,
  cookies and storage over local HTTP, tab close, and close.
- Live shared-browser tests: 9 pass, unchanged.
- Harness scenario `scratch_viewport` on the rebuilt binary with
  `OPENCODE_PYTHON_SCRATCH=1`: the model wrote a page and measured it at 360,
  768, and 1280 px through `sb.viewport`, getting 328 px, 480 px, and 480 px
  cards with no horizontal overflow, then closed the browser and caught
  `unavailable`. No CDP or WebSocket scripts, which is what the U run needed
  before.

Not covered: the `bwrap` sandbox path (bubblewrap still cannot be installed in
the harness container), and cookies/storage behind `bwrap`.
