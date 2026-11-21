# Code-mode optimization: deeper analysis of the post-fix dump

Source: `manus-dei/.dumps/e9ccef73-dump-20261121T021623Z`.
This follows `dev-dump-2-post-fix.md`; it does not replace that report.

I reread the raw transcripts, assistant timing and token records, all 572
Python program records, and the SDK/browser action implementations. I also ran
focused reproductions against local `agent-browser 0.27.0` and Chromium with
static and delayed test pages.

## Executive summary

The first report focused on the 33 failed programs. The deeper pass shows that
**successful programs hide two larger problems**:

1. Every executed `page.wait_load()` call stalled for about 25 seconds and then
   reported success. There were 25 such calls, costing **628.9 seconds**.
2. Six programs passed a bare JavaScript function to `page.evaluate()`. The
   browser returned `{}` without executing the function, but the Python program
   completed. Some DOM and API probes therefore did not run.

The next priorities are structural role waits and print truncation:

- `wait_for(role="dialog")` cannot match the SDK's filtered snapshot. One dump
  timeout is proven false: the next program showed that the dialog was open.
- Print output was truncated in 93/572 programs, but `metadata.truncated` was
  false for all 572. This caused visible file re-read chains.

Outside code mode, the goal harness sent generated `webui/dist` diffs to QA.
Those diffs were 92.5% and 99.0% of the two large QA prompts. Four resulting
requests carried 2.59M uncached input tokens, 72.1% of the run's total.

## Corrected time budget

The earlier session durations were session lifetimes, not active model time.
In particular, dev's 59.6-minute session included idle time while QA ran.
Summing assistant message durations gives:

| Session | Active | Python tools | Model/other active |
| --- | ---: | ---: | ---: |
| dev | 13.1m | 2.7m | 10.4m |
| QA 1 | 15.9m | 5.4m | 10.5m |
| QA 2 | 11.5m | 3.7m | 7.8m |
| QA 3 | 18.7m | 10.0m | 8.7m |
| QA 4 | 12.1m | 3.3m | 8.8m |

The complete goal span was **71.9 minutes**. Assistant-active time was 71.2
minutes: 25.3 minutes in tools and 45.9 minutes in model/other activity.

The 33 failed programs consumed 394.7 seconds, 26.2% of Python tool time.
That figure still excludes the successful 25-second `wait_load()` stalls.

## E1 — `wait_load()` is a deterministic 25-second stall

### Dump evidence

There were 25 `browser.call` children in the 25.100–25.300-second band. Every
one aligns with `page.wait_load()` in the program source:

| Session | Calls | Time |
| --- | ---: | ---: |
| QA 1 | 7 | 176.1s |
| QA 2 | 2 | 50.3s |
| QA 3 | 13 | 327.0s |
| QA 4 | 3 | 75.5s |
| **total** | **25** | **628.9s** |

They occurred in 21 programs. Three other programs contained `wait_load()` but
failed before reaching it. QA 3 program 74 called it for four pages and spent
105.5 seconds in one program.

This is **41.7% of all Python tool time** and **14.6% of the complete goal
span**. The child calls had status `completed`, so failure counts do not reveal
the cost.

### Reproduction

On a trivial static page after `open` returned:

| Command | Result |
| --- | --- |
| `agent-browser wait --load load` | `Done`, 25.155s |
| `agent-browser wait --load domcontentloaded` | `Done`, 25.155s |
| `agent-browser wait --load networkidle` | `Done`, 1.356s |
| `agent-browser eval 'document.readyState'` | `"complete"`, immediately |

The 25.155-second reproduction matches the dump's 25.15-second child calls.

### Fix

Do not use `wait --load` for `load` or `domcontentloaded`. Poll
`document.readyState` with a bounded timeout:

- `domcontentloaded`: `readyState != "loading"`;
- `load`: `readyState == "complete"`.

Keep `networkidle` as a separate semantic; do not make it the default. Add a
live regression that requires `wait_load()` after `goto()` and `reload()` to
return promptly when the document is already loaded.

## E2 — bare-function `evaluate()` silently does nothing

Six programs used Playwright-style function arguments:

```python
page.evaluate("() => document.querySelectorAll('[role=menu]').length")
page.evaluate("""async () => {
  const res = await fetch('/api/todos', ...)
  return res.status
}""")
```

Local results:

| Script | Result |
| --- | --- |
| `() => 42` | `{}` |
| `(() => 42)()` | `42` |
| `async () => 42` | `{}` |
| `(async () => 42)()` | `42` |

Affected dump programs included two dev probes, three QA 1 probes, and one QA 4
probe. Some returned nested empty objects such as `{"state": {}}`. Others were
side-effect probes: setting an input value or POSTing a todo. Those functions
did not execute, yet the Python program succeeded.

### Fix

Make `Page.evaluate()` accept both expressions and zero-argument function
expressions. Detect a complete function/arrow-function argument and invoke it
as `(<function>)()` before sending it to `agent-browser`. There is no useful
JSON value to preserve by returning a function object.

Test synchronous values, asynchronous values, DOM side effects, and ordinary
expressions. Also document that both forms are accepted.

This is a correctness fix, not only a latency fix.

## E3 — `wait_for()` cannot observe structural roles

`Page.find_all()` calls `nodes(full=False)` by default. The interactive
snapshot omits structural roles. More importantly, `_matching()` discards every
node without a ref.

For this live page:

```html
<dialog open aria-label="Settings">...</dialog>
```

The full snapshot contained `- dialog "Settings"`, without a ref. The
interactive snapshot contained no dialog. Consequently:

- default `wait_for(role="dialog")` cannot see the dialog;
- `full=True` still cannot return it, because `_matching()` requires a ref.

QA 1 program 42 clicked `Tambah tugas`, waited 30 seconds for a dialog, and made
76 child calls before failing. The next program printed `Judul`, `Prioritas`,
`Batal`, and the other open-dialog content. This was a false timeout.

QA 4 program 48 used the same impossible wait, although its next snapshot did
not show an open dialog; that case also involved a click/navigation problem.

### Fix

Separate **presence** from **actionability**:

- `find_one()` should continue returning actionable elements with refs.
- `wait_for()` should search the full snapshot and allow non-ref nodes.
- Return an `Element` when the matched node has a ref; return a `Node` for a
  structural presence match. Existing callers that immediately click an
  interactive result keep working.

A separate `wait_present()` is also reasonable, but `wait_for(role="dialog")`
should still delegate to it; otherwise the natural failing call remains.

Add live tests for dialog, menu, heading, and an actionable menuitem.

## E4 — native URL waits have an already-matching race

The SDK delegates `wait_url()` to `agent-browser wait --url`.

Locally, after clicking a link and confirming the current URL:

```text
http://127.0.0.1:18765/b.html
agent-browser wait --url '**/b.html'  -> timeout after 30s
```

The same happened after `history.pushState()` when the current URL already
matched. The native wait listens for a future navigation instead of first
checking the current URL.

The two dump `wait_url()` failures had different immediate causes:

- QA 2 expected `**/todos`, but the next program showed `/dashboard`.
- QA 3 expected `**/login`, but the next program showed
  `/login?next=%2Ftodos`, which that glob does not match.

Thus the dump does not prove an already-matching false timeout, but it does
show unhelpful 30-second errors and a need for clearer glob behavior.

### Fix

Implement `wait_url(pattern, timeout=30)` as an immediate check followed by
bounded polling of `page.url()`:

- return immediately if the current URL already matches;
- support the timeout keyword models already try to use;
- include the current URL in the timeout error;
- document that matching includes the query string, or deliberately match a
  documented URL/path form.

Add tests for an already-matching URL, full navigation, SPA `pushState`, query
strings, and timeout.

## E5 — nine polling programs caused 671 child calls; all failed

Programs with at least 40 child calls:

| Programs | Child calls | Time | Failed |
| ---: | ---: | ---: | ---: |
| 9 | 671 | 257.4s | 9 |

That is 31.9% of all child calls and 46.9% of browser child calls, from 1.6% of
programs. Each lasted 21–32 seconds. They used `wait_text`, `wait_for`, or a
custom `until()` loop.

`until()` polls every 0.25 seconds; a browser round trip has a median duration
of 155ms. A failed 30-second predicate therefore produces about 75 calls.

Native text waiting now works in the local version:

| Condition | Native `wait --text` result |
| --- | --- |
| text already present | 0.155s |
| text inserted after 1.2s | 1.282s |

The SDK's polling `wait_text()` came from an older native-wait failure. It
should be retested against the live browser suite before replacing it.

### Fix

1. Revalidate native `waittext` on static, delayed, and SPA pages; use it when
   reliable, retaining polling for nondefault timeout behavior if needed.
2. Add adaptive backoff to custom `until()` polling.
3. Include current URL and a short page/text excerpt in wait failures where
   possible, so recovery does not require another diagnostic program.

Backoff alone is not the main wall-time fix: all nine high-poll programs failed,
so reducing their call count would not remove their 20–30-second timeouts.
Correct predicates, structural waits, and actionable errors matter more.

## E6 — print truncation is hidden and causes re-read chains

`renderLogs()` keeps only the last 60 lines and 6000 characters. Returned values
are rendered separately and do not use that cap. The prompt does not explain
the difference.

Evidence:

- 93/572 outputs contain `(earlier output omitted)`: 16.3%.
- None of the 572 program records has `metadata.truncated=true`.
- 59 involved `fs.read`, 28 shell output, and the rest browser/grep/other.
- All 93 were in QA; dev had none in this dump.

QA 2 programs 33–36 read the same form component four times in a row:

1. full read: truncated;
2. `limit=95`: still truncated by the 60-line print cap;
3. `offset=1, limit=32` plus another file: truncated;
4. `offset=1, limit=20`: finally fully visible.

Across QA, 25 omitted-output programs with direct literal read paths re-read a
path within the next four programs. Not every re-read was caused by truncation,
but the chain above directly was.

### Fix

- Add explicit Python metadata such as `printTruncated`, `omittedLines`, and
  `omittedChars`; the existing outer `truncated` flag does not describe print
  truncation.
- Include omitted counts in the visible marker.
- Raise the success-output budget and preserve head plus tail for successful
  reads. Keep tail-biased output for failures if desired.
- Document the print cap and the fact that returning a string/structured value
  avoids the print-specific cap.
- Then encourage multi-file reads with concise returned excerpts. Raising the
  cap without guidance would only move token cost elsewhere.

A/B measurement should count both output tokens and avoided model round trips.

## E7 — single-call programs limit batching value

The median program made one child call:

| Child calls per program | Programs |
| --- | ---: |
| 0 | 5 |
| 1 | 296 |
| 2–4 | 186 |
| 5 or more | 85 |

Of the 296 single-child programs, 195 were one `shell.run`, 70 one `fs.read`,
and 31 one browser call. QA had 19 adjacent pairs of single-file reads. Some
were retries caused by print truncation; others were independent files that
could have been read together.

This is not an argument to batch every shell command: tests and edits often
have dependencies. It does show that file exploration can use fewer model round
trips once output truncation stops punishing batched reads.

Program startup is not the main problem. Median program time minus child-call
time was 138ms. A persistent Python process would add state risk for little
gain compared with the browser fixes.

## E8 — error quality can remove diagnostic round trips

Two cheap improvements:

- `find_one()` builds its `page has:` error from the first 400 characters. A
  giant generic root often consumes most of that budget. Exclude or shorten the
  root, prioritize nodes with the requested role, and report the total count.
- Wait errors should include the last observed URL or a short text excerpt.
  Both dump `wait_url()` failures needed another program just to print the URL.

Also document that `name=` is exact and `contains=` is the substring form. One
failure searched for `name="Super Admin"` when the accessible name was
`SA Super Admin Super Admin`.

## E9 — the ripgrep error was a missing path, not a pattern problem

Dev program 15 searched:

```text
web/node_modules/@x1nx3r/altics-react-icons
```

The next shell probes reported `node_modules-missing` and no package `dist`
directory. `fs.grep` turned this into `tool_failed: ripgrep execution failed`
after 2ms.

`grep.ts` stats the requested path but continues when stat fails. It can choose
the parent as cwd, and a missing cwd then becomes a generic ripgrep execution
error.

Return a path-specific `not_found` error before invoking ripgrep. This also
prevents accidentally searching a parent when the requested path is absent.

## E10 — small API and output fixes remain worthwhile

These were visible in the dump and are cheap after the higher-priority fixes:

- `Element.get()` and dict-style access for `role`, `name`, `value`, and `ref`;
  the general prompt rule that results read like dicts makes this expectation
  reasonable.
- `Element.press(key)`.
- `Page.wait_for_load()` and `Page.wait_for_url()` aliases.
- Typed `Link` results for `page.links()`. Include `text` and `href`, plus a
  `name` alias: the failing program tried both `link.href` and `link.name`.
- Document separate stdlib imports: `import time`, not
  `from agent import browser, time`.
- Remove or reduce repeated output noise: 442 outputs begin with `null`, and
  391 repeat `note: no Run(ctx, a) was defined...`. The shim already supports
  top-level programs; the prompt should present that form as valid rather than
  warning on every use.

## Non-code-mode cost: generated diffs sent to QA

This belongs to the goal harness, but it dominates token cost and should not be
lost among SDK work.

| QA prompt | Total chars | `webui/dist` chars | Generated share |
| --- | ---: | ---: | ---: |
| Round 1 | 2,310,905 | 2,137,926 | 92.5% |
| Round 4 | 987,353 | 977,818 | 99.0% |

Round 1 also included `.manus/postgres` file sections.

Four requests in those rounds each had over 100k uncached input tokens. Their
combined input was **2,594,677 tokens**, **72.1%** of the run's 3,598,762
uncached input tokens. Round 4 started with a 390k-token context and ended at
466k; it accumulated 43.2M cached-read tokens.

Exclude generated bundles, source maps, rendered HTML, database files, and
binary content from the QA diff. Send a file-level summary and the source diff;
QA can inspect a generated artifact explicitly if needed.

## Recommended implementation order

### Batch A — browser correctness and deterministic stalls

1. Replace `wait_load()` for `load`/`domcontentloaded` with `readyState` checks.
2. Auto-invoke bare zero-argument functions in `evaluate()`.
3. Make `wait_for()` support structural presence.
4. Reimplement `wait_url(pattern, timeout=...)` with current-URL checks and
   actionable timeout errors.
5. Revalidate native `waittext`; add polling backoff and better diagnostics.

Expected impact on this dump: the `wait_load()` change alone removes 628.9
seconds of direct stall time. The other changes remove some 30-second failures
and, more importantly, prevent silent no-op verification.

### Batch B — output and recovery

1. Add print-truncation telemetry and visible omitted counts.
2. Change success-output truncation and document print versus return behavior.
3. Improve find/wait diagnostics and missing-path grep errors.
4. Add the small Element/Page/Link API fixes.

Measure output tokens and program count together; do not optimize only one.

### Batch C — goal-harness prompt size

Exclude generated and database artifacts from QA diffs before another large
manus-dei run. This is independent of the Terminal-Bench two-condition design.

## Implementation status

Implemented on 2026-11-21:

- `wait_load()` now polls `document.readyState` for `load` and
  `domcontentloaded`; `networkidle` keeps the native wait.
- `wait_url()` checks the current URL, accepts a timeout, and reports the last
  URL on failure. `wait_for_url()` is an alias.
- `wait_for()` searches the full snapshot and returns `Element` or structural
  `Node`; dialog waits now work.
- `evaluate()` invokes bare zero-argument functions.
- `wait_text()` uses one native wait for the default timeout, with polling and
  context-rich errors for custom timeouts.
- `until()` backs off from its initial interval to at most 500ms.
- `Element` supports dict-style access and `press()`.
- `Page.links()` returns typed `Link(text, href, name)`.
- `find_one()` and wait errors show shorter, role-prioritised node summaries.
- The loader no longer prints the top-level-program note.
- Print rendering keeps the head and tail on success, keeps the tail on
  failure, and records `printTruncated`, `printOmittedLines`, and
  `printOmittedChars`.
- The catalog documents the print policy, structural waits, URL queries,
  function evaluation, exact names, and separate stdlib imports.
- `fs.grep` reports a missing path as `File not found` instead of invoking
  ripgrep with the parent directory.

Validation:

- 153 Python SDK tests pass, with 18 live-browser tests skipped by default.
- 11 live Chromium tests pass, including the prompt `wait_load`, current-URL
  wait, structural dialog, and function `evaluate` cases.
- 443 fork tool tests pass.
- Fork typecheck is clean and the `opencode-linux-x64` binary rebuilds and
  passes its version smoke test.

## Metrics for the next dump

The next analysis should report these directly rather than infer them:

- `wait_load` calls, total duration, and p95 duration;
- bare-function evaluates and non-executing probe count;
- structural-role wait successes and false timeouts;
- print-truncated programs and omitted line/char counts;
- same-file re-read chains after truncation;
- browser calls per wait and time per recovered failure;
- active model time versus tool time, not session lifetime;
- QA prompt size split into source, generated, and binary content.

The 94.2% first-attempt program success rate is not sufficient health evidence:
all 25 `wait_load()` stalls and all six bare-function evaluates were in
successful-looking programs.
