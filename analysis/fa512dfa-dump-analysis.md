# Post-fix rerun analysis

Source: `manus-dei/.dumps/fa512dfa-dump-20261121T051411Z`.
Template: `rust-react-boilerplate`.
Build: the rerun used the updated fork adapter, but the runtime Python SDK was not refreshed.

The goal finished in two QA rounds. The final judge verdict was `done`.

## Headline comparison

The earlier code-mode dump was `e9ccef73-dump-20261121T021623Z`.
The two runs used different templates, so the comparison is directional, not a controlled benchmark.

| Metric | Earlier run | This rerun | Change |
| --- | ---: | ---: | ---: |
| Python programs | 572 | 226 | 60.5% fewer |
| Failed programs | 33 | 19 | 42.4% fewer |
| Child tool calls | 2,101 | 1,011 | 51.9% fewer |
| Python tool time | 1,509.3s | 1,261.0s | 16.4% less |
| Active time | 71.2m | 36.5m | 48.7% less |
| Goal span | 71.9m | 37.3m | 48.1% less |
| Uncached input tokens | 3,598,762 | 479,002 | 86.7% less |
| Cache-read tokens | 73,382,894 | 32,598,140 | 55.6% less |
| Print-truncated programs | 93 | 7 | 92.5% fewer |
| 25-second `wait_load` stalls | 629s | 0s | removed |
| QA rounds | 4 | 2 | 50% fewer |
| Output characters | 798,936 | 476,895 | 40.3% less |

First-attempt success was 207/226 = **91.6%**.

Two of the nineteen failures were intentional goal-gate refusals before the
goal was authorized. Counting only code-mode failures, the rate is
17/226 = **92.5%**.

## Time budget

| Session | Active | Python tools | Model/other active |
| --- | ---: | ---: | ---: |
| dev | 19.3m | 12.8m | 6.5m |
| QA 1 | 10.1m | 5.0m | 5.1m |
| QA 2 | 7.1m | 3.3m | 3.8m |
| **total** | **36.5m** | **21.1m** | **15.4m** |

The complete goal span was 37.3 minutes.

Token totals:

- uncached input: 479,002
- cache read: 32,598,140
- output + reasoning: 157,479

## Tool mix

| Child tool | Calls | Share |
| --- | ---: | ---: |
| `browser.call` | 581 | 57.5% |
| `shell.run` | 162 | 16.0% |
| `fs.read` | 147 | 14.5% |
| `mutate.edit` | 64 | 6.3% |
| `fs.glob` | 28 | 2.8% |
| `mutate.write` | 17 | 1.7% |
| `fs.grep` | 9 | 0.9% |
| `state.todos.write` | 3 | 0.3% |

## Failure taxonomy

Counting tool-state errors and metadata errors together, the run had
**19 failures**.

| Kind | Count | Notes |
| --- | ---: | --- |
| goal-gate refusals | 2 | expected harness refusals before the goal was authorized |
| browser waits and polling | 7 | three role waits, one text wait, one native URL wait, two custom `until` waits |
| old SDK API mismatches | 5 | two `wait_url(timeout=...)`, two `Element.press`, one `from agent import time` |
| model or app errors | 5 | bad selector, null click, bad unpack, bad read offset, shell timeout |

The two goal-gate refusals are not code-mode failures. They are recorded with
`state.status = "error"` and a `state.error` string, not `metadata.error`;
future analysis must count both fields.

## What improved

### Program and call volume

The rerun used 226 programs and 1,011 child calls. One program replaced about
4.5 native tool calls on average.

Single-child programs dropped from 296/572 in the earlier run to 82/226 here.
Programs with two or more child calls rose from 48% to 64%.

### Output handling

The fork output fix is active:

- 138 outputs begin with `[print output]`
- 0 outputs begin with `null`
- 7 outputs report `printTruncated: true`
- omitted telemetry reports 984 lines and 31,417 characters

The earlier run had 93 hidden truncations and no print-truncation metadata.

### Repeated reads

Literal `fs.read` calls dropped from 158 to 77, and unique paths dropped from
59 to 50. Re-reads dropped from 99 to 27.

Adjacent single-file read programs dropped from 19 to 1. The batched-read
prompt guidance had the intended effect: most multi-file reads now happen
inside one program.

### Browser polling

Six programs made 40 or more child calls. Together they used 389 browser calls
and 158.1 seconds, and all six failed.

The earlier run had nine such programs, 671 calls, and 257.4 seconds. This is
still the largest remaining latency source, but it is smaller than before.

## What was not validated

The runtime Python SDK was not refreshed. The dump still shows the old SDK:

1. `Page.wait_url(timeout=...)` failed twice with
   `TypeError: Page.wait_url() got an unexpected keyword argument 'timeout'`.
2. `Element.press(...)` failed twice with
   `AttributeError: 'Element' object has no attribute 'press'`.
3. `from agent import browser, shell, time` failed once with
   `ImportError: cannot import name 'time' from 'agent'`.
4. Three bare-function `evaluate()` calls still returned `{}`.
5. The top-level-program note still appears in 224 of 226 outputs.

The default `wait_load()` fix was not exercised. Every `wait_load` call in
this dump used `networkidle`; none used the default `load` state. Therefore
the absence of 25-second stalls does not prove that the `readyState` fix is
active.

The structural `wait_for()` fix also cannot be evaluated from this dump. The
role-wait failures may be app-level: the next program showed menu items, but
no dialog opened.

## New issue: in-program jobs are being misused

Three programs used `agent.jobs.start(...)` and then returned without calling
`job.result()`:

- QA 2 program 12 started `make lint && make test`.
- QA 2 program 19 started `make lint && make test`.
- QA 2 program 33 started Playwright.

The model later lost the handles and reran the work synchronously in programs
37 and 39. Those two reruns cost another 15 seconds.

`agent.jobs` is in-program concurrency. Jobs do not survive the program.
The catalog already says not to return unfinished jobs, but the model still
treated them as detached work.

Recommended prompt fix:

> Jobs do not survive the program. Call `job.result()` before the program ends.

A more informative `Job.__repr__` would also help:

> `Job(pending; call result() before the program ends)`

## QA prompt size

Issue #10 did not appear in this run.

| QA round | Prompt characters | Generated-artifact characters | Share |
| --- | ---: | ---: | ---: |
| 1 | 443,948 | 0 | 0% |
| 2 | 267,190 | 0 | 0% |

The largest prompt line was 508 characters. The earlier generated-bundle
problem did not occur because this template's diff contained no build output.
Issue #10 remains open but was not exercised.

## Conclusion

The fork-side output and batching fixes worked:

- no `null` output prefixes
- visible print truncation telemetry
- far fewer repeated reads
- far fewer single-call read programs
- much lower token and time totals

The root SDK fixes were not active. The next real validation needs a refreshed
runtime SDK and a run that actually exercises:

- default `wait_load()`
- `wait_url(timeout=...)`
- `Element.press`
- structural `wait_for`
- bare-function `evaluate`
- typed `Link` results

The strongest next fixes are:

1. refresh `/opt/manus/python/current/lib/agent` from the updated root SDK;
2. clarify that `agent.jobs` dies with the program;
3. keep issue #10 open until a template with generated build output is tested.
