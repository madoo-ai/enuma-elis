# Run analysis: prometheus builds a to-do app

Artifacts in this directory:

- `session.json` — exported session (messages, parts, tool calls, final answer).
- `transcript.jsonl` — the CLI event stream (`--format json`).
- `workspace/` — the session workspace at the end of the run.
- `metrics.json` — the numbers below in machine-readable form.

## Headline

The test worked end-to-end. The model used one `python` tool, wrote a
self-contained to-do app, drove it in a real Chromium, and verified the
behaviour. It never used a raw `open()` for the file: the only write went
through `mutate.write`.

| Metric | Value |
| --- | --- |
| Model | `litellm/prometheus` |
| Agent | `python-experiment` |
| Toolset | `python` only |
| Wall clock | 1.1 minutes |
| Steps | 13 |
| `python` tool calls | 12 |
| Child tool calls | 64 |
| Program-level errors | 1 (fixed) |
| Raw `open` / exec / net | 0 / 0 / 0 |
| Artifact | `workspace/index.html`, 5,355 bytes, 203 lines |

## Tokens

| Bucket | Count |
| --- | --- |
| Input | 6,907 |
| Output | 4,094 |
| Reasoning | 1,819 |
| Cache read | 84,224 |
| Cache write | 0 |
| Cost | 0 (not reported by the provider) |

## Tool use

| Child tool | Calls |
| --- | --- |
| `shell.run` | 57 |
| `fs.read` | 4 |
| `fs.glob` | 2 |
| `mutate.write` | 1 |

Child tool time: 8.9 s total, 889 ms max. The wall clock is dominated by model
turns, not tool execution.

The 64 child calls were packed into 12 programs. The model did not pay a model
round trip per shell call; it wrote a program that ran a loop of browser
actions and returned one summary.

## Browser actions

The model used the base image's `agent-browser` CLI through `shell.run`:

| Action family | Uses |
| --- | --- |
| `get` | 16 |
| `eval` | 8 |
| `click` | 6 |
| `fill` | 5 |
| `reload` | 3 |
| `is` | 3 |
| `open` | 1 |
| `check` | 1 |
| `press` | 1 |
| `close` | 1 |

It started `python3 -m http.server 8765`, drove `index.html`, cleared storage,
added two items, checked localStorage, reloaded, completed one item, deleted
both, checked the empty state, closed the browser, and killed the server.

## Errors

One program failed with:

```text
SyntaxError: 'return' outside function
```

The model had written a bare `return` instead of wrapping it in `def Run`.
It corrected the shape on the next call. All 12 outer `python` calls completed;
the failure was a program result, not a tool failure.

## The artifact

`workspace/index.html` is a single file with no dependencies:

- Add form, Enter or button; blank/whitespace ignored; button disabled when empty.
- Complete checkbox, strike-through, delete button.
- `localStorage` persistence under `todos`, guarded `JSON.parse`.
- `crypto.randomUUID` with a timestamp fallback.
- `textContent` rendering, so todo text cannot inject HTML.
- `aria-label` on the checkbox and delete button.
- Light/dark via `prefers-color-scheme`.
- Empty state toggled with `hidden`.

The model reported 5,354 bytes; the file is 5,355. The difference is the
trailing newline. Minor, and the model separately confirmed the SHA-256.

## What the run says about the design

1. **The typed path was used.** The workspace was writable and the shell was
   available, yet the model wrote through `mutate.write` and read through
   `fs.read`/`fs.glob`. The raw audit counters are zero. This is the strongest
   evidence so far that the typed API is attractive, not just imposed.
2. **Shell is still the escape hatch.** 57 of 64 child calls were
   `shell.run`, almost all for `agent-browser`. The model needed a capability
   the Python SDK did not expose. The next browser module should cover the
   common actions so those calls become typed.
3. **Batching works.** 64 child calls in 12 programs, 1.1 minutes, 8.9 s of
   tool time. The model spent most of its time thinking and writing code, not
   waiting for individual tool results.
4. **One tool is enough for the model to work.** The toolset was `python` only;
   the model never asked for a missing read/edit/shell tool. It imported the
   modules from the description.
5. **Snapshot diffing was blind.** `filesChanged` is empty because the
   workspace is not a git repository; `Snapshot.track()` had nothing to
   capture. The experiment should use a git fixture to measure file diffs
   independently of `mutate.write`.

## Environment notes

- The deploy env's `OPENCODE_API_KEY` is an `oc_` Zen key; LiteLLM rejected it.
  A one-hour key scoped to `prometheus` was minted with the management key from
  `ref/litellm.md` for this run.
- The LAN LiteLLM URL in `ref/litellm.md` is unreachable from this host; the
  public proxy `https://dashboard.agent.tcl-it.tech/v1` was used.
- `manus-dei/base:latest` currently loads `opencode/deepseek-v4.1-flash`; the
  harness injects the `litellm` provider through `OPENCODE_CONFIG_CONTENT`.
- The fork binary was built inside the base image. A host build needs glibc
  2.44 and ICU 78; the base has glibc 2.43 and no ICU.
- The session ran with `OPENCODE_GOAL_REQUIRED=false` and `toolset: [python]`
  for the test. Production should keep the goal gate.

## Follow-ups

- Add `agent.browser` to the SDK, then measure whether `shell.run` drops.
- Run the same prompt in a git workspace to populate `filesChanged`.
- Add a repeatable fake-provider harness so the test does not depend on a
  minted key or the public gateway.
- Record the final answer as a harness assertion, not just a transcript.
