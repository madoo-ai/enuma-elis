# Tool-call statistics: the longest agent session

## Dataset

- Dump: `/home/x1nx3r/prototypes/manus-dei/.dumps/pos2-dump-20261027T134801Z/pos2-agent-state/opencode.db` (1.7 GB SQLite).
- Longest session by parts: `ses_e899f63cfffeo7LHc8FNVSj4wA` ("New session", agent `build`, model `glm-5.3-flash`).
- 1,602 model steps, 1,613 tool calls, 33.6 hours wall clock, $24.83.
- Tokens: 2,295,033 input, 425,517 output, 131,139 reasoning, 806,831,424 cache read.
- Method: parsed `part.data` JSON where `type = "tool"`; counted operators lexically in `bash` commands; grouped consecutive same-tool calls by time. Token attribution joins `step-finish` parts by message.

This is one long session, not a corpus. Treat the percentages as a strong signal, not a universal law.

## Headline

| Metric | Value |
| --- | --- |
| Tool calls | 1,613 |
| `bash` calls | 1,289 (79.9%) |
| Steps with exactly one tool call | 1,568 of 1,584 tool-bearing steps (99.0%) |
| Steps with more than one tool call | 16 (1.0%) |
| Averaged tools per step | 1.006 |
| Compound bash commands | 1,277 of 1,289 (99.1%) |
| Bash calls starting with `cd` | 1,049 (81.4%) |
| Cache-read tokens spent on bash steps | 678,952,256 (84.2% of the session) |
| Bash calls in runs of 10+ | 1,045 (81.1%) |

The agent is not a parallel tool caller. It is a serial shell user.

## Tool mix

Root session:

| Tool | Calls | Share |
| --- | --- | --- |
| `bash` | 1,289 | 79.9% |
| `browser` | 164 | 10.2% |
| `write` | 66 | 4.1% |
| `edit` | 38 | 2.4% |
| `read` | 35 | 2.2% |
| `todowrite` | 10 | 0.6% |
| `task` | 7 | 0.4% |
| `question` | 2 | 0.1% |
| `invalid` | 1 | 0.1% |
| `goal` | 1 | 0.1% |

Root session plus all child sessions (4,173 calls):

| Tool | Calls | Share |
| --- | --- | --- |
| `bash` | 2,815 | 67.5% |
| `browser` | 590 | 14.1% |
| `read` | 282 | 6.8% |
| `edit` | 223 | 5.3% |
| `write` | 159 | 3.8% |
| `grep` | 42 | 1.0% |
| `todowrite` | 22 | 0.5% |
| `glob` | 12 | 0.3% |
| `task` | 7 | 0.2% |
| `invalid` | 7 | 0.2% |
| `skill` | 6 | 0.1% |
| `goal` | 5 | 0.1% |
| `question` | 3 | 0.1% |

The root session used **zero** native `grep` and `glob` calls. All search went through `bash`.

## Bash composition

| Pattern | Calls | Share of bash |
| --- | --- | --- |
| Any operator (`&&`, pipe, `;`, redirect) | 1,277 | 99.1% |
| `&&` | 1,090 | 84.6% |
| Pipe | 1,054 | 81.8% |
| `;` | 780 | 60.5% |
| Redirect (`>`) | 699 | 54.2% |
| Multiline | 454 | 35.2% |
| Subshell `$()` | 139 | 10.8% |
| Plain single command | 12 | 0.9% |

`&&` count per call:

| `&&` count | Calls |
| --- | --- |
| 0 | 199 |
| 1 | 603 |
| 2 | 293 |
| 3 | 102 |
| 4 | 50 |
| 5+ | 42 |

Pipe count per call:

| Pipes | Calls |
| --- | --- |
| 0 | 235 |
| 1 | 354 |
| 2 | 241 |
| 3 | 168 |
| 4 | 127 |
| 5+ | 164 |

A rough lexical segment count (split on `&&`, `|`, `;`) gives about **9,000 segments across 1,289 calls**, or ~7 commands per call. Semicolons inside quoted strings inflate this, so read it as an order of magnitude.

Average command length: 695 characters. Longest: 14,270.

## The `cd` habit

- 1,049 of 1,289 bash calls start with `cd` (81.4%).
- Every one of those 1,049 uses `&&` after the `cd`.
- 783 go to `/home/ubuntu/workspace/api`; 165 to `/home/ubuntu/workspace`; 89 to `/home/ubuntu/workspace/web`.

The shell prompt tells the model to use the `workdir` parameter instead of `cd`, with a good/bad example. The model ignores it in four out of five calls, and repeats the same `cd /home/ubuntu/workspace/api &&` 783 times.

Top first token after `cd ... &&`:

| Command | Calls |
| --- | --- |
| `python3` | 340 |
| `grep` | 228 |
| `sed` | 147 |
| `go` | 104 |
| `cat` | 39 |
| `export` | 26 |
| `gofmt` | 16 |
| `timeout` | 15 |

## What the shell is used for

Keyword counts across bash calls:

| Keyword | Calls |
| --- | --- |
| `head` | 789 |
| `grep` | 742 |
| `python` | 419 |
| `sed` | 323 |
| `tail` | 318 |
| `cat` | 91 |
| `awk` | 82 |
| `find` | 19 |
| `xargs` | 15 |
| `jq` | 2 |

Build and test:

| Command | Calls |
| --- | --- |
| `go test` | 213 |
| `go build` | 171 |
| `go run` | 7 |
| `npm run build` | 7 |
| `curl` | 100 |
| `psql` | 87 |
| `localhost` | 37 |
| `127.0.0.1` | 143 |

This is a compile-test-inspect loop: `go build`/`go test` (384 calls), then `curl`/`psql` (187), then `grep`/`head`/`tail` to read the result.

## Mutation happens through Python, not `edit`

| Mutation path | Calls |
| --- | --- |
| `python3 - <<'EOF'` heredocs | 373 |
| ... that call `open(` | 372 |
| ... that use `open(..., "w")` | 354 |
| `cat ... >` | 72 |
| `sed -i` | 24 |
| `rm` | 30 |
| `cp` / `mv` / `mkdir` | 3 / 2 / 4 |
| Native `edit` tool | 38 |
| Native `write` tool | 66 |

The dominant mutation path is a Python heredoc that reads a file, does a string replace, and writes it back. Example from the session:

```bash
cd /home/ubuntu/workspace/api && python3 - <<'EOF'
p='internal/app/port/pos_sales.go'
s=open(p).read()
s=s.replace('	Issue(ctx context.Context, prefix string, at time0) (string, error)\n}', ...)
s=s.replace('import (\n\t"context"\n','import (\n\t"context"\n\t"time"\n')
open(p,'w').write(s)
EOF
head -12 internal/app/port/pos_sales.go
```

This is a code edit with no diff, no line numbers, no patch, and no `edit` permission check. The model is using the filesystem as its API because the shell is the interface it trusts.

## Serial runs

Consecutive same-tool calls, ordered by time:

| Tool | Calls | Runs | Avg run | Max run |
| --- | --- | --- | --- | --- |
| `bash` | 1,289 | 106 | 12.16 | 153 |
| `browser` | 164 | 37 | 4.43 | 19 |
| `write` | 66 | 46 | 1.43 | 8 |
| `edit` | 38 | 32 | 1.19 | 3 |
| `read` | 35 | 12 | 2.92 | 11 |

Bash run lengths:

| Run length | Runs | Calls |
| --- | --- | --- |
| 1 | 27 | 27 |
| 2 | 9 | 18 |
| 3 | 12 | 36 |
| 4 | 5 | 20 |
| 5 | 7 | 35 |
| 6 | 7 | 42 |
| 7 | 6 | 42 |
| 8 | 3 | 24 |
| 10+ | 30 | 1,045 |

Thirty runs of 10+ bash calls contain 81% of all bash calls. The longest is 153 consecutive model turns of shell.

## Cost of the serial shell

| Bucket | Steps | Cache-read tokens | Share |
| --- | --- | --- | --- |
| Bash steps | 1,288 | 678,952,256 | 84.2% |
| Browser steps | 164 | 80,954,816 | 10.0% |
| Write steps | 65 | 13,938,368 | 1.7% |
| Edit steps | 38 | 9,752,832 | 1.2% |
| Other (read, todo, task, no-tool, etc.) | 47 | 23,233,152 | 2.9% |

Average cache read per step: 503,640 tokens. Max: 910,656.

The 30 long bash runs alone account for **582,047,360 cache-read tokens** — 72.1% of the session total and 85.7% of all bash-step cache reads.

A rough upper bound: if each of those 30 runs became one Go program, the session would replace 1,045 model turns with 30. At ~527K cache-read tokens per bash step, that removes roughly 535M cache-read tokens and ~1,015 round trips. Real programs will need follow-up turns, so the achievable number is lower, but the order of magnitude is clear.

## What this means for Go Code Mode

1. **Collapse runs, not just calls.** The agent already serializes. The win is turning a 12-call run into one program, not squeezing parallelism out of a single step.
2. **Do not require `cd`.** The typed API should take `Workdir` once per call, or the program context should set it. The model's `cd` habit costs a prefix on 81% of calls.
3. **Make `Edit` the obvious path.** 354 Python write-mode heredocs versus 38 native edits. The typed `Edit` must return a patch, replacements, and diagnostics; otherwise the model will keep writing Python.
4. **Return structured search.** 742 bash `grep` calls, zero native `grep` calls in the root. A typed `Grep` with `Path`, `Line`, `Text` removes the parsing and the pipe.
5. **Make the compile-test loop native.** 384 `go build`/`go test` calls and 187 `curl`/`psql` calls are the shape of a program: run, parse failures, return only the failures. This is the strongest first use case.
6. **The first target is the 10+ runs.** Thirty episodes contain 81% of the bash calls. Pick one, rewrite it as a Go program, and compare turns, cache read, and wall clock.

## Caveats

- One session in one dump. The session is a POS application build with Go, Python, Postgres, and a browser; other workloads will differ.
- Operator and segment counts are lexical. Semicolons, pipes, and `&&` inside quoted strings inflate them slightly. The `cd` prefix, tool names, and run grouping are exact.
- A "run" is a serial episode, not necessarily one logical task. Some 10+ runs contain several independent checks.
- Cache-read attribution joins `step-finish` to the message that contains the tool part. This dataset has one step per message, so the join is clean.
- The 535M savings figure is an upper bound that assumes a program handles the whole run without a follow-up turn.
