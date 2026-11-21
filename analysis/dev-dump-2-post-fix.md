# Post-fix code-mode dump

> Follow-up: `dev-dump-2-optimization.md` corrects the session time budget,
> supersedes the broad "application timing" interpretation of the browser
> failures, and documents the 25-second `wait_load()` stalls and silent
> bare-function `evaluate()` no-ops.

Source: `manus-dei/.dumps/e9ccef73-dump-20261121T021623Z`.
Build: `0.4.28-alcides`. Task: Go/React todo list in the boilerplate.

Important scope note: unlike the first dump, QA also used Python code mode.
This is therefore a post-fix behavior sample, not a dev-only comparison.

## Outcome

The goal loop took four QA rounds:

| Round | QA verdict | Finding |
| --- | --- | --- |
| 1 | contradicted | stray `web/tests/todos-page.png` outside the allowed paths |
| 2 | contradicted | stray `.manus/postgres` cluster plus untracked todo source |
| 3 | contradicted | real privacy bug: the TanStack Query cache leaked the previous user's todos after sign-out |
| 4 | clean | no findings |

The dev fixed the round-3 bug, rebuilt the embedded UI, and added a Vitest
regression test that fails against the old `signOut()` code. The judge's final
verdict was `done`.

## Python usage

| Session | Round | Calls | Failed | Child calls | Python tool time |
| --- | ---: | ---: | ---: | ---: | ---: |
| build/dev | — | 88 | 6 | 244 | 161s |
| QA | 1 | 126 | 7 | 412 | 326s |
| QA | 2 | 108 | 6 | 421 | 222s |
| QA | 3 | 147 | 11 | 736 | 600s |
| QA | 4 | 103 | 3 | 288 | 200s |
| **total** | | **572** | **33** | **2101** | **25.2m** |

First-attempt success: 539/572 = 94.2%.

Token totals across all sessions:

- input: 3,598,762
- output: 115,004
- reasoning: 173,902
- cache read: 73,382,894

The heaviest sessions were QA round 1 (1.93M input tokens, 7.31M cache read)
and QA round 4 (870k input tokens, 43.2M cache read).

## Post-fix validation

The earlier fixes are visible:

- **Failure telemetry (D2):** failed Python programs now retain child-call and
  audit metadata. The failed round-4 example had three child calls and an audit
  summary.
- **Program-only traces (D3):** failures point at the program line, for example
  `program.py:8 in Run`. There were no `concurrent/futures/_base.py` or
  `ast.py` traces.
- **No shell runaway (D1 not stressed):** no `setsid` background programs were
  used. `nohup` calls returned in 0.1–14.2s depending on intentional sleeps; no
  call hung until the SDK timeout.
- **Raw opens:** 1–2 per session, all from `page.screenshot(save=...)`.
- **No discovery probes:** zero `a.tools`, `dir()`, or `inspect` usage.
- **Scratch browser:** unused; all browser work used the shared page.

## Failure taxonomy

| Kind | Count | Notes |
| --- | ---: | --- |
| browser wait / not found | 17 | dialogs, menus, dynamic content; mostly application timing |
| SDK missing API | 4 | see below |
| other JS/model error | 4 | bad JavaScript selectors or assumptions |
| wrong file path | 2 | guessed repository layout before reading it |
| bad import | 1 | `from agent import browser, time` |
| read offset out of range | 1 | model guessed a line beyond EOF |
| Python syntax error | 1 | extra parenthesis in JS/Python |
| server not up | 1 | `ERR_CONNECTION_REFUSED` before the server was ready |
| ripgrep failure | 1 | `fs.grep` against `web/node_modules/...` |
| result shape | 1 | returned the `page.url` method instead of calling it |
| **total** | **33** | |

Most failures were application/UI timing, not code-mode failures.

## New SDK gaps

These are concrete and cheap:

1. `Element.get(...)` is missing. A model wrote:
   ```python
   [b.get("name") for b in page.find_all(role="button")]
   ```
2. `Element.press("Enter")` is missing.
3. `Page.wait_for_load()` is missing; only `wait_load()` exists.
4. `Page.wait_url(pattern, timeout=...)` rejects `timeout`.
5. `Page.links()` returns plain dicts, but a model wrote `link.href`. Typed
   `Link` objects would remove that guess.
6. Stdlib imports still need to be separate; `from agent import browser, time`
   failed.

## Polling cost

Several browser programs made 70+ child calls while waiting for dialogs or
menus. `wait_for` polls on a fixed interval, and each poll takes a snapshot.
Examples:

- QA round 2: 78 child calls in 21.1s, failed on a hidden user menu.
- QA round 2: 77 child calls in 30.6s, failed on a dialog wait.
- QA round 3: 81 child calls in 31.5s, failed on a dialog wait.
- QA round 4: 76 child calls in 30.6s, failed on a dialog wait.

The browser guide should also make portal behavior explicit: dropdown menus and
dialogs may not appear in the normal snapshot until opened.

## Isolated issue

One `fs.grep` call against `web/node_modules/@x1nx3r/altics-react-icons`
failed with “ripgrep execution failed”. The pattern looked valid and grep worked
elsewhere. If it recurs, expose a better error message or a `no_ignore` option
for searching dependency directories.

## Recommended next fixes

SDK:

- add `Element.get`;
- add `Element.press`;
- add `Page.wait_for_load` and `Page.wait_for_url`;
- support `Page.wait_url(pattern, timeout=30)`;
- return typed `Link` results from `Page.links()`;
- make `until()` polling back off after the first few seconds.

Prompt/docs:

- mention that menus and dialogs are portals and may need an explicit open
  before `find_one`;
- state that stdlib imports remain separate from `from agent import ...`.
