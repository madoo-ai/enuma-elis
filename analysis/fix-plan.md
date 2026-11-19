# Fix plan from the harness analysis

Source analysis: [`analysis/harness-2026-11-19/report.pdf`](harness-2026-11-19/report.pdf)

Goal: remove the model-facing friction we actually observed: bad import guesses,
misused result shapes, stale browser actions, and prompt gaps around newer
capabilities.

## Phase 1 — prompt and SDK ergonomics

### 1. Dynamic Python imports in the tool prompt

**Status:** done

**Files:**

- `me-when-agents/packages/opencode/src/tool/python/catalog.ts`

**Work:**

- Add an `Imports:` block to `describeCatalog`.
- Build it from enabled modules, not a static full list.
- Canonical form:

  ```python
  from agent import fs, mutate, shell, web, state, agents, browser
  import agent
  ```

- Include `import agent` when jobs/task helpers are relevant.
- Only include module names whose specs are visible.
- Keep `browser` conditional on the native browser tool.
- Keep `agents` conditional on the native task tool.

**Tests:**

- Full catalog contains the canonical import line.
- `modules: ["fs"]` produces `from agent import fs`, not unrelated imports.
- Browser-only catalog contains `from agent import browser`.
- Agents-only catalog contains `from agent import agents`.

### 2. Typed-result cheat sheet in the tool prompt

**Status:** done

**Files:**

- `me-when-agents/packages/opencode/src/tool/python/catalog.ts`

**Work:**

- Add a compact `Result shapes:` block.
- Make it conditional on enabled modules.
- Cover the shapes the model misused:

  ```python
  fs.read(...) -> Text(path, text, lines) | Image(path, mime, bytes) | Directory(path, entries)
  fs.glob(...) -> GlobResult(entries=(FileEntry(path, type), ...), truncated)
  shell.run(...) -> ShellResult(exit, stdout, stderr, timed_out)
  browser.page().screenshot(...) -> Screenshot(path, mime, bytes)
  web.fetch(...) -> FetchResult(url, text, title, mime, bytes)
  ```

- Explicitly say: iterate `GlobResult.entries`, not `GlobResult`.
- Mention `Text.total_lines` and `ShellResult.exit_code` aliases only if we add
  them.

**Tests:**

- Catalog prompt contains `Result shapes:`.
- Catalog prompt mentions `GlobResult.entries`.
- Catalog prompt mentions `ShellResult.exit`.
- Browser-enabled prompt mentions `Screenshot(path, mime, bytes)`.

### 3. Python SDK result ergonomics

**Status:** done

**Files:**

- `agent/_types.py`
- `tests/test_tools.py`

**Work:**

- `GlobResult.paths -> tuple[str, ...]`
- `GlobResult.__iter__` iterates `.entries`
- `GlobResult.__len__`
- `Text.total_lines -> int | None` alias for `.lines`
- `ShellResult.exit_code -> int` alias for `.exit`
- Keep dataclasses frozen.
- Do not silently turn them into dicts.

**Tests:**

- `GlobResult.paths`
- iteration over `GlobResult`
- `len(GlobResult)`
- `Text.total_lines`
- `ShellResult.exit_code`

### 4. Conditional examples for jobs and detached tasks

**Status:** done

**Files:**

- `me-when-agents/packages/opencode/src/tool/python/catalog.ts`

**Work:**

- Keep the normal simple example.
- Add a compact concurrency example when more than one callable tool is enabled:

  ```python
  jobs = [agent.jobs.start(fs.read, path) for path in paths]
  values = [job.result() for job in jobs]
  ```

- Add a detached-task example only when `agents.tasks.start` is enabled:

  ```python
  task = agents.tasks.start("build", "...", "short-description")
  ```

- Do not include detached-task guidance when the background flag is off.
- Keep the examples shorter than the explanatory rules.

**Tests:**

- Multi-tool catalog includes `agent.jobs.start`.
- Background-enabled catalog includes `agents.tasks.start`.
- Background-disabled catalog omits detached-task example.

### 5. Remove or repair the native browser `read` action

**Status:** done

**Decision:** remove the invalid `read` action rather than silently aliasing it.

**Files:**

- `me-when-agents/packages/opencode/src/tool/browser.ts`
- `me-when-agents/packages/opencode/src/tool/browser.txt`
- `me-when-agents/packages/opencode/test/tool/browser.test.ts`

**Work:**

- Remove `read` from `SPECS`, `ACTIONS`, parameter descriptions, and tests.
- Remove `read [url]` from `browser.txt`.
- Keep `get text [selector]` as the page-text path.
- Keep `Page.text()` mapped to `get("text", "body")`.

**Tests:**

- `ACTIONS` does not contain `read`.
- Browser tool rejects `action: "read"` through schema validation.
- Existing browser tests still pass.

## Phase 2 — harness repeatability

### 6. Add the scenario runner to the repo

**Status:** done

**Files:**

- `harness/scenarios.sh`
- `harness/README.md`

**Work:**

- Promote `/tmp/opencode/run-scenario.sh`.
- Support scenario name, modules, sandbox, port, and prompt.
- Support `OPENCODE_STATE_DIR` for persistent DB debugging.
- Keep per-run directories with transcript, session, logs, and workspace.
- Stop the container and print analysis.

### 7. Record binary provenance in run metrics

**Status:** done

**Files:**

- `harness/arms.sh`
- `harness/analyze_run.py`

**Work:**

- Record fork commit, version, binary SHA256, base image, agent, modules,
  sandbox, and relevant flags into `metrics.json`.

## Phase 3 — deferred

These are real but not needed for this batch:

- Bake the Python runtime into the base image.
- Expand the tool manifest with input/output schemas.
- V2 browser mapping.
- MCP/plugin Python surface.
- LSP.
- Splitting the browser action enum into multiple tools.
- Cancellation for already-running in-program jobs.

## Checks

After each phase:

```bash
./scripts/check.sh
cd me-when-agents/packages/opencode && bun run typecheck
cd me-when-agents/packages/opencode && bun test test/tool/python-catalog.test.ts test/tool/python-manifest.test.ts test/tool/browser.test.ts
```

If Python SDK types changed, also run the full Python suite.

If tool descriptions changed, rebuild the fork before the next harness run:

```bash
./harness/build.sh
```
