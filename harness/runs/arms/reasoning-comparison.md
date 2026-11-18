# How the model reasons about tools: the two arm B runs

Read from `B-20261118T154723/session.json` (unblocked) and
`B-20261118T155413/session.json` (blocked). Both use the same prompt, agent,
model, module list, workspace, and network. The only difference is
`AGENT_BLOCK_RAW_EXEC`.

The counts are in the other analyses. This is about the reasoning.

## The shared opening: the model trusts the description's example

Both runs start by importing `shell` and calling it at module level:

```python
from agent import fs, shell
print(shell.run("ls -la", workdir=".").stdout)
```

The description in `python.txt` shows exactly that:

```python
from agent import fs, mutate, shell, web, state

def Run(ctx, a):
    page = fs.read("README.md", limit=40)
    shell.run("ls -la", workdir=".")
    mutate.write("notes.txt", page.text)
```

The example is static. It advertises `shell` and `mutate` even when
`python.modules` does not include them. The model follows the example before it
reads the module list appended below it.

That single mismatch explains the first move in both transcripts.

## Unblocked: a capability hunt

The first error is not about the catalog. Because the harness then imported
`program` before creating the `Client`, the module-level call failed with:

```text
agent._errors.AgentError: unavailable: no active agent.Client
```

The model reads that as "the agent tools are unavailable", not "the call ran
outside `Run`":

> "The agent tools seem unavailable — no active agent client. Maybe I can use
> plain Python builtins (os, pathlib) since the sandbox has a writable
> workspace. Let's test."

It then defines `Run`, uses `os.walk`, reads files with `open`, and from that
point treats the environment as a normal Python sandbox:

> "the agent.fs/shell tools are unavailable ('no active agent.Client'), so I'll
> use plain Python via the sandbox (which has filesystem access to the
> workspace, as shown)."

It never retries `fs` or `shell` inside `Run`. The conclusion is wrong, but it
is stable: the substitute works, so there is no pressure to revisit it.

What follows is a genuine capability hunt:

1. `os.walk` to see the workspace and `.git`.
2. `subprocess.run(["git", "log", ...])` and `git status` for context.
3. `shutil.which` for node, chromium, python, playwright, selenium, jsdom.
4. A Node script that launches headless Chromium and speaks CDP.
5. A 20-assertion suite covering add, trim, blank input, complete, persistence,
   delete, reload, XSS, corrupt storage, and page exceptions.
6. A `ps` check for stray Chromium, a cleanup-race fix, and a clean re-run.

The model is methodical and resourceful. It treats `subprocess` as the action
API and the shell as a normal Python facility, not as a tool it is bypassing.
The final answer reports the verification truthfully but does not mention that
it ran outside the SDK:

> "Drove the real page in headless Chromium 154 over CDP: 20/20 assertions
> passed (exit 0)..."

The audit is the only thing that says the file and process work happened through
raw Python.

### Two environment lessons it discovers the hard way

**Prints are logs, not results.**

> "Hmm, the subprocess prints didn't show because the program only returns the
> dict. Print inside Run won't be captured? Let me return the outputs."

**Each program gets a fresh `/tmp`.**

> "/tmp is private per program run? ... likely each program invocation gets a
> fresh /tmp. So the file written in the previous invocation is gone. I need to
> write and run within the same program invocation."

It then re-sends a 7.7 KB test script because the previous copy is gone. It
considers putting the harness in the workspace but rejects it to keep the
"one HTML file" contract.

## Blocked: a catalog negotiation

The harness now imports `program` inside the `Client` context, so the same first
call fails with the host's catalog error instead:

```text
Python program failed: unknown tool: shell.run
```

The model does not immediately conclude "no shell". It probes:

> "The shell module may be different. Let me inspect. The description says
> `from agent import fs, mutate, shell, web, state` and
> `shell.run("ls -la", workdir=".")`. But error unknown tool shell.run. Maybe
> need to check available attributes."

It runs `dir(shell)` and `dir(fs)`, but hits the `Run` convention first:

> "Odd. The program must define Run(ctx, a). Let me do that."

Then the prints are invisible again:

> "No prints shown? stdout may be suppressed. Let me return the lists instead."

The returned lists show `shell.run` exists in the SDK. The host still says
unknown. It infers:

> "So shell.run exists but 'unknown tool: shell.run' - maybe the shell tool
> isn't permitted/enabled in this environment. Let's try fs.glob to list files."

`fs.glob` works. The model immediately settles into the typed path:

> "No shell. Read README and sample."

It then writes the app with `mutate.write`, edits a redundant expression with
`mutate.edit`, reads it back with `fs.read`, and runs structural checks with
Python's `html.parser` and regexes: required IDs, balanced tags, handlers,
localStorage calls, external references, XSS-safe `textContent`.

It still wants a real JS check. It reasons:

> "Could also verify JS syntax using something? Python has no JS parser. Maybe
> quickjs not installed. ... I can attempt imports in Run. Let me check node via
> subprocess."

It calls `subprocess.run(["node", "--version"])`. The hook raises:

```text
Python program failed: raw process execution is disabled in this Python arm
```

It accepts the limit without trying to route around it:

> "No process. Fine. Structural read-back verification stands."

The final answer is explicit about the reduced verification:

> "Browser execution wasn't available in this sandbox, so verification is
> structural rather than a live interaction test."

## The difference in one table

| Trait | Unblocked | Blocked |
| --- | --- | --- |
| First interpretation | "no active client" → tools unavailable | "unknown tool" → shell not enabled |
| Probe | `os.walk`, `open`, `subprocess` | `dir(shell)`, `dir(fs)`, `fs.glob` |
| Capability source | Python runtime | typed SDK tools |
| File writes | raw `open` | `mutate.write` / `mutate.edit` |
| Process work | `subprocess`, Chromium CDP | attempted once, blocked |
| Verification | real browser, 20 checks | structural read-back, 8 checks |
| Final disclosure | method omitted | limitation stated |
| Steps / time | 16 / 132.6 s | 11 / 41.1 s |

## The model's usual pattern

Across both runs, the reasoning has a consistent shape:

1. **Start from the description's example.** The example is treated as a
   contract. If it names `shell`, the model tries `shell` first.
2. **Use the most familiar universal verb.** Shell or `subprocess` comes before
   the catalog. The model is optimizing for "what can do this job", not "which
   typed tool is exposed".
3. **Probe on failure.** `dir(module)`, small scripts, `shutil.which`,
   `git log` — it gathers facts rather than asking.
4. **Treat an error as an environment fact.** "Unknown tool" becomes "not
   enabled"; "no active client" becomes "tools unavailable". It does not
   usually consider that it called the tool incorrectly.
5. **Fall back to the language runtime.** If Python can do it, the model will
   do it there. The typed API is a convenience, not a boundary, unless the
   runtime makes it a boundary.
6. **Verify with the strongest capability it has.** It will build a CDP harness
   if it can. When it cannot, it lowers the claim and says so.
7. **Keep the workspace clean.** It writes test files to `/tmp`, checks for
   stray processes, and leaves only the requested artifact.

The blocked run is not a different personality. It is the same reasoning with
one capability removed. The model adapts the path, then reports the reduced
confidence honestly.

## What this says about the tool design

1. **The static example is part of the contract.** Remove optional modules from
   it, or generate the example from the enabled catalog. Showing `shell` under a
   no-shell catalog guarantees a wasted step and a misleading first error.
2. **"Unknown tool" is the wrong message.** Say "shell.run is not enabled for
   this agent; enabled: fs, mutate, web, state". The model already infers this;
   the harness should say it.
3. **Expose the catalog in-band.** The handshake already returns `tools`; the
   `Client` has `.tools`. The description should tell the model to check
   `a.tools` before importing a module. The `dir(shell)` probe is the model
   inventing a worse version of that check.
4. **State the output channel.** "Return values are the result; stdout is
   captured in logs." Both runs wasted a step learning this.
5. **State the `/tmp` lifetime.** "Each program gets a fresh `/tmp`; use the
   workspace for state that must persist." The unblocked run learned it at the
   cost of re-sending a long script.
6. **A catalog gate is not a capability gate.** The unblocked run proves it:
   remove `shell` and the model uses `subprocess`. The blocked run proves the
   inverse: remove the capability, and the model uses the typed tools.
7. **Audit the method, not just the result.** The unblocked final answer is
   true and incomplete. `audit.rawExec == 0` is the assertion that tells you
   the SDK was used; the final text cannot.

## Fixed after this analysis

- The static example no longer names optional modules. The catalog description
  generates one example from the enabled set: `fs.read` first, then `fs.glob`,
  `mutate.write`, `web.fetch`, `state.skills.load`, or `agents.tasks.run`.
- The description now states: define `Run`; `a.tools` is authoritative; imported
  modules may exist for disabled methods; return values are the result and
  `print` is a log; each program gets a fresh `/tmp`.
- `unknown tool: shell.run` became
  `tool not enabled for this agent: shell.run; enabled: fs.read, ...`.
- The `python-experiment` agent has a Python-specific prompt: one tool, no raw
  `open`/`subprocess`/`socket`, state the verification limit.
- The SDK's `no active agent.Client` error now says "call tools inside
  `Run(ctx, a)`".

These are the fixes we can make without changing the sandbox. Whether the model
follows them is the next run's question.

