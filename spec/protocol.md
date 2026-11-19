# enuma-elis bridge protocol

Version: 1.

The host launches the program; the SDK talks to the host over two reserved file
descriptors.

| fd | Direction | Content |
| --- | --- | --- |
| 3 | both | newline-delimited JSON: handshake, calls, results, audit |
| 4 | SDK → host | exactly one final envelope, written after the program returns |
| stderr | SDK → host | program logs; the host captures the tail |
| stdout | SDK → stderr | redirected by the harness, so `print` cannot corrupt the protocol |

Limits: one JSON object per line, UTF-8, maximum 1 MiB per line.

## Handshake

SDK first:

```json
{"type":"hello","protocol":1,"sdk":"0.1.0","python":"3.13.5"}
```

Host replies:

```json
{"type":"hello","protocol":1,"tools":["fs.read","fs.grep","mutate.edit"],
 "limits":{"calls":200,"concurrency":8}}
```

The host checks the protocol version and the tool-manifest hash before it
accepts a call. A mismatch is fatal: the host kills the process and returns a
clear error. It does not fall back to another Python.

## Call

SDK:

```json
{"type":"call","id":"c1","tool":"fs.grep","input":{"pattern":"TODO"}}
```

Host success:

```json
{"type":"result","id":"c1","ok":true,"output":{"matches":[]}}
```

Host failure:

```json
{"type":"result","id":"c1","ok":false,
 "error":{"kind":"permission_denied","message":"grep denied","data":null}}
```

Error kinds: `invalid_input`, `permission_denied`, `unavailable`, `not_found`,
`tool_failed`, `canceled`, `timeout`. The host maps native tool failures onto
these by message (for example "File not found" becomes `not_found`).

## Audit

The audit hook sends fire-and-forget events. They are metadata, not calls.

```json
{"type":"audit","kind":"raw_open","path":"/home/ubuntu/workspace/api/x.go","mode":"w"}
{"type":"audit","kind":"raw_exec","argv":["go","test","./..."]}
{"type":"audit","kind":"raw_net","address":"127.0.0.1:5432"}
```

## Final envelope

fd 4 receives exactly one object:

```json
{"ok":true,"value":{"edited":3}}
```

```json
{"ok":false,"error":{"kind":"exception","message":"KeyError: 'x'","trace":"  program.py:4 in Run: row['x']"}}
```

An exception that is not an `AgentError` has kind `exception`; the message is
`Type: text`. `trace` is optional and lists the program's own frames, one per
line. The host waits for stderr to drain after the envelope, then shows the
model the failure, the trace, and the program's print output. A successful run
shows its print output after the result.

A missing envelope is reported as "exited without a result" with the print output.

## Cancellation

The host closes fd 3, sends SIGTERM to the process group, waits two seconds,
then sends SIGKILL. Pending calls are canceled. The SDK must treat a closed fd 3
as cancellation and stop issuing new calls.

## Concurrency

The SDK may send multiple calls before receiving results. The host dispatches up
to eight at a time and returns results in any order, keyed by `id`. The SDK
multiplexes by `id`. Calls above the limit queue in the host.

The SDK exposes this as `agent.jobs`: `jobs.start(fn, ...)` starts one tool call
and returns a handle; `job.result()` blocks for that result. `jobs.wait_all()`
waits for every handle the program started. This is in-program concurrency, not
detached work that survives the program.

## Defaults

| Limit | Value |
| --- | --- |
| source | 64 KiB |
| wall clock | 5 minutes |
| child calls | 200 |
| in flight | 8 |
| final result | 1 MiB |

`task` raises the wall clock and the child-call budget; it has its own limits.

## Transport fallback

The production transport is fd 3 (duplex) plus fd 4 (final envelope). When the
host cannot pass extra file descriptors, it uses stdio:

- fd 0: host → SDK, same message stream.
- fd 1: SDK → host, same message stream plus `{"type":"final",...}`.
- fd 2: logs.
- The harness creates `Client` before redirecting `sys.stdout`, then runs the
  program with `redirect_stdout(sys.stderr)`.
- After writing the final line, the harness calls `os._exit(0)`. The reader
  thread is blocked on stdin and must not survive interpreter finalization.

The Phase 0 fork adapter uses this fallback because its process helper exposes
only stdin/stdout/stderr. The message shapes are identical.
