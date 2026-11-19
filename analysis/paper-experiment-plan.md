# Paper experiment plan

Status: design draft around Terminal-Bench. No confirmatory runs have been made
against it.

Decisions:

- Target: a full empirical paper with a focused terminal-work claim.
- Benchmark: Terminal-Bench 2.0 only. No custom tasks.
- Comparison: native tools versus the best current Python code mode.
- Models: `prometheus` (DeepSeek V4.1 Flash) and `hephaestus` (GLM 5.3 Flash).
- Scale: 16 tasks, 3 repetitions, 2 conditions, 2 models.
- No browser, scratch-browser, sandbox-profile, or prompt/SDK ablations.
- No human ratings.

Goal: measure whether one Python program over a typed terminal surface beats
direct native tool calls on real containerized tasks, and on which tasks it does
not. The paper reports a bundle-level comparison. It does not decompose the
Python condition into prompt, SDK, or runtime effects.

## 1. Claims the paper can make

1. A design for a typed Python tool interface over native agent tools, scoped to
   terminal work: filesystem, edits, shell, and result types.
2. A reproducible Harbor adapter and measurement harness for running both
   conditions on the same Terminal-Bench tasks.
3. A two-model comparison on 16 published Terminal-Bench tasks, with task-level
   effects, efficiency, recovery, and a failure taxonomy.
4. Design implications for when a code surface helps in terminal work and when
   native calls are enough.

The paper cannot claim browser or scratch-browser effects, generality beyond
the two models and 16 tasks, or which part of the Python bundle caused an
effect.

## 2. Research questions and hypotheses

| ID | Question | Hypothesis | Primary measure |
| --- | --- | --- | --- |
| RQ1 | Does Python code mode improve verified success on Terminal-Bench tasks? | H1: Python beats native on tasks with repeated edits, loops, or multi-step verification. | Official task success |
| RQ2 | Does Python add overhead? | H2: on short tasks, Python is no better and may cost more time or tokens. | Wall time, tokens |
| RQ3 | Where does the effect come from at task level? | H3: the advantage grows with the number of shell or edit operations the task needs. | Condition-by-operation-count interaction |
| RQ4 | How do failure and recovery differ? | H4: Python has fewer interface and format failures, but new failure modes appear. | Failure taxonomy, recovery rate |
| RQ5 | Do results replicate across models? | H5: the condition ranking is stable across DeepSeek V4.1 Flash and GLM 5.3 Flash. | Condition-by-model interaction |
| RQ6 | Does either surface make unsupported claims? | H6: automated claim-artifact mismatches are no worse in Python. | Claim mismatch rate |
| RQ7 | Does either surface violate the container boundary? | H7: neither does; the audit is a safety check, not a performance metric. | Raw exec/net/open, forbidden shortcuts |

## 3. Benchmark

### 3.1 Version

Use **Terminal-Bench 2.0**: 89 tasks, each with an instruction, a Docker image,
a reference solution, and official tests. Pin the dataset version and the Harbor
revision in the paper and run manifest.

Every task is run in its own container with the task's declared CPU, memory,
and network settings. The official verifier decides success. We do not add our
own task tests.

### 3.2 Task subset

Select 16 tasks, two per category, all terminal-only with zero GPUs and expert
time at most 75 minutes. This keeps the matrix affordable while covering the
main work types.

| Category | Tasks | Difficulty | Expert minutes |
| --- | --- | --- | ---: |
| software-engineering | `fix-git`, `polyglot-c-py` | easy, medium | 5, 20 |
| debugging | `overfull-hbox`, `custom-memory-heap-crash` | easy, medium | 60, 30 |
| system-administration | `configure-git-webserver`, `nginx-request-logging` | hard, medium | 15, 20 |
| security | `crack-7z-hash`, `break-filter-js-from-html` | medium, medium | 5, 20 |
| data-processing | `financial-document-processor`, `multi-source-data-merger` | medium, medium | 30, 30 |
| data-science | `mteb-leaderboard`, `hf-model-inference` | medium, medium | 5, 20 |
| scientific-computing | `raman-fitting`, `dna-insert` | medium, medium | 5, 30 |
| file-operations | `extract-elf`, `large-scale-text-editing` | medium, medium | 30, 40 |

Why these:

- no GPU tasks;
- no task with an expert estimate above 75 minutes;
- both easy and hard tasks, so the suite does not floor immediately;
- eight categories, so a single domain cannot drive the result;
- all tasks are terminal work, where both conditions have the same capability.

Tasks are selected from the frozen Terminal-Bench 2.0 list by metadata, not by
peeking at model outcomes. Record the selection rule and the task hashes.

### 3.3 Pilot

Run one repetition on eight tasks, one per category:

```text
fix-git, overfull-hbox, configure-git-webserver, crack-7z-hash,
financial-document-processor, mteb-leaderboard, raman-fitting, extract-elf
```

Pilot matrix:

```text
2 models x 8 tasks x 2 conditions x 1 repetition = 32 runs
```

Pilot gate:

- If both conditions solve fewer than roughly 15% of tasks, the suite is at a
  floor. Replace the subset with easier Terminal-Bench tasks and rerun the
  pilot. Do not proceed to the main matrix.
- If both conditions solve more than roughly 85%, the suite is at a ceiling.
  Replace the easiest tasks with harder ones and rerun the pilot.
- Otherwise keep the suite frozen.

### 3.4 Main matrix

```text
2 models x 16 tasks x 2 conditions x 3 repetitions = 192 runs
```

Total with pilot: **224 runs**.

If the pilot shows high variance, the pre-registered extension is four
repetitions: 256 main runs, 288 total. No other extension is planned.

## 4. Conditions

| Condition | Surface | Tools | Prompt |
| --- | --- | --- | --- |
| N | native | bash, read, write, edit, glob, grep | standard agent prompt |
| P | Python code mode | `fs`, `mutate`, `shell`; `agent.jobs` for concurrency | current prompt with explicit methods, units, examples |

Both conditions get the same task instruction and the same terminal capability
set. Browser, scratch browser, subagents, and `web.fetch`/`web.search` are
disabled in both conditions because Terminal-Bench tasks are terminal work and
native tools have no equivalent browser ownership model. Network access needed
by a task happens through `shell` in both conditions.

"Best current code mode" here means the current SDK and prompt for the terminal
profile, not every module in the repository. This keeps the comparison about the
call surface.

Python runs with `OPENCODE_PYTHON_SANDBOX=none`: the Terminal-Bench task
container is the isolation boundary, and nested bwrap is not reliable in task
images. The audit hook still records raw exec, raw open, and raw net. Native
bash runs under the same container.

## 5. Harness integration

Use Harbor, the official Terminal-Bench harness, with a custom installed agent.

### 5.1 Adapter

Implement `paper/harbor_agent.py` with two `BaseInstalledAgent` subclasses or
one parameterized class:

- `install`: upload the built OpenCode binary and the `agent/` SDK into the task
  container, under `/opt/enuma` and the SDK path used by the runtime.
- `configure`: write the LiteLLM provider config, define both agents
  (`build` and `python-experiment`), set permissions, and set the environment
  for the selected condition.
- `run`: start `opencode serve` inside the task container, run the task
  instruction through `opencode run --attach`, then export the session to
  `/logs/agent/session.json`.
- `populate_context_post_run`: copy the OpenCode session, transcript, Python
  programs, audit events, and token usage into the Harbor agent context.

The binary is mounted or uploaded, not baked into every task image. Its
compatibility was checked on `fix-git`, `raman-fitting`, and
`nginx-request-logging`: the current binary runs in those images.

### 5.2 Same harness, two agents

The only difference between N and P is the OpenCode agent name:

```text
N: --agent build
P: --agent python-experiment
```

Both use the same binary, provider, model alias, task instruction, time limit,
and container. The native condition's toolset is restricted to the terminal
tools. The Python condition's module list is restricted to `fs`, `mutate`,
`shell`.

### 5.3 Task working directory

Use the task's declared working directory, not `/home/ubuntu/workspace`.
Discover it from the image or from Harbor's task metadata. If a task expects a
specific path such as `/app`, run the agent there and keep the harness out of the
task's output paths.

### 5.4 Verification

Harbor runs the official task tests after the agent exits. The harness stores:

- reward and pass/fail per task;
- verifier stdout/stderr and CTRF JSON where present;
- the final container diff and file hashes;
- agent session, transcript, token usage, and audit events.

## 6. Outcomes

### 6.1 Primary

- **Official task success:** 0/1 from the Terminal-Bench verifier.
- **Partial credit:** only if the task's verifier provides it; otherwise not
  synthesized.

### 6.2 Effort and reliability

- wall-clock seconds within the task's agent timeout;
- input, output, reasoning, and cache-read tokens;
- cost, when reported;
- Python programs per task;
- child calls per task;
- failed programs and failed child calls;
- recovery: a failed program followed by a successful one in the same run;
- output truncations;
- task timeouts.

### 6.3 Interface behavior

- discovery probes: `a.tools`, `dir`, `inspect`, SDK source reads;
- import, shape, attribute, command, and timeout errors;
- result access patterns: attributes, keys, `.get`, aliases;
- shell command construction and quoting;
- concurrency use;
- raw CDP, WebSocket, or `agent-browser` CLI workarounds, if any.

### 6.4 Safety and honesty

- audited raw exec, raw open, and raw net;
- forbidden shortcut use;
- claim-artifact consistency: every claim that names a file, test result, or
  command is checked against an artifact or verifier record; a mismatch is
  counted automatically.

### 6.5 Artifact hygiene

- diff size and files changed;
- extra files;
- file count and output format;
- verifier pass rate per artifact.

No human ratings, rater agreement, or subjective quality score.

## 7. Data collection

### 7.1 Run manifest

```json
{
  "run_id": "fix-git-P-prometheus-r01",
  "batch": "confirmatory-1",
  "benchmark": "terminal-bench@2.0",
  "dataset_revision": "...",
  "task_id": "fix-git",
  "task_hash": "sha256:...",
  "category": "software-engineering",
  "difficulty": "easy",
  "expert_time_estimate_min": 5,
  "condition": "P",
  "repetition": 1,
  "order": 1,
  "model_alias": "prometheus",
  "model_reported": "DeepSeek V4.1 Flash",
  "temperature": 0.0,
  "max_tokens": 8192,
  "prompt_hash": "sha256:...",
  "sdk_version": "0.1.0",
  "fork_sha": "...",
  "root_sha": "...",
  "harbor_revision": "...",
  "task_image": "alexgshaw/fix-git:20251031",
  "task_image_digest": "sha256:...",
  "sandbox": "task-container",
  "python_sandbox": "none",
  "modules": ["fs", "mutate", "shell"],
  "scratch": false,
  "question_tool": false,
  "started_at": "2026-...",
  "duration_seconds": 0,
  "status": "completed",
  "exclusion_reason": null
}
```

### 7.2 Event log

One JSONL row per normalized event:

- `message` with role and token usage;
- `tool_call` with tool, input hash, result hash, status, duration;
- `python_program` with code hash, AST features, prints, trace, outcome;
- `child_call` with tool, status, duration;
- `audit` with kind and target;
- `claim` with text and its automated artifact check;
- `verifier` with task id, reward, and test summary.

Keep the raw OpenCode session and transcript, but analyze the normalized log.

### 7.3 Program features

For each Python program:

- parses, has `Run`, AST depth, lines, characters;
- imports and canonical-import compliance;
- SDK calls and child calls;
- result shape and dict access;
- discovery probes;
- try/except and error branches;
- concurrency;
- failure kind and trace frame;
- whether it was a probe, build, verification, or recovery program.

## 8. Controls and threats

Controlled:

- benchmark revision, task hashes, and task image digests;
- model aliases, provider, reported model, temperature, max tokens;
- task instruction and system prompt;
- OpenCode binary SHA256 and SDK version;
- Harbor revision;
- terminal toolset and Python module list;
- task time limit;
- question and goal tools disabled;
- scratch browser disabled;
- randomized condition order within task and repetition;
- one fresh container per run.

Threats:

| Threat | Mitigation |
| --- | --- |
| Benchmark contamination | Use a published benchmark and report the date; do not claim unseen tasks |
| Terminal-Bench floor or ceiling | Pilot gate; replace tasks if success is too low or high |
| Bundle confound | State that prompt, SDK, and helpers move together |
| Model drift | Pin aliases; record provider-reported model and response IDs |
| Task image drift | Pin image digests; preflight every batch |
| Harbor/agent integration bugs | Validate install and export on 3 task images; fail the batch on any missing session |
| Python sandbox mismatch | Use the task container as the boundary; report `python_sandbox=none` |
| Raw-open accounting | Add no screenshot helper to this scope; report raw opens separately if any |
| Tool-surface imbalance | Restrict both conditions to the same terminal capability set |
| Timeout truncation | Record timeouts; do not silently treat them as task failures unless the benchmark does |

## 9. Analysis plan

### 9.1 Primary model

```text
success ~ condition * model * task_complexity + (1 | task)
```

Model is a fixed factor with two levels. Report posterior means, 95% credible
intervals, pooled and per-model marginal success, and the condition-by-model
interaction.

### 9.2 Secondary models

- counts: negative binomial, offset by task;
- duration: log-normal or Gamma;
- tokens and cost: log-normal, with cache-read tokens as a covariate;
- claim mismatches: binary logistic;
- error kinds: per-kind logistic models.

Use Holm correction within each family.

### 9.3 Failure taxonomy

A rule-based classifier labels failed programs and failed runs using a codebook
derived from the development corpus. Ambiguous cases fall into `other` and are
listed with raw messages. Separate interface, capability, model, and
infrastructure errors.

### 9.4 No human ratings

All outcomes are automated: official task reward, verifier output, audit
counters, artifact checks, and claim-artifact matching.

## 10. Execution plan

| Phase | Work | Output |
| --- | --- | --- |
| 0 | Freeze task list and selection rule; write pre-registration | Task hashes, `paper/prereg.md` |
| 1 | Build Harbor adapter; validate install/export on three task images | Working N and P agents |
| 2 | Run 32-run pilot; apply floor/ceiling gate | Pilot corpus, power estimate |
| 3 | Run 192-run main matrix; validate every session and verifier | Raw corpus |
| 4 | Normalize events and programs; run automated checks | Analysis tables |
| 5 | Automated claim and artifact audit | Mismatch table |
| 6 | Fit models, sensitivity checks, write paper | Draft and artifact |

Run count:

| Block | Calculation | Runs |
| --- | --- | ---: |
| Pilot | 2 models x 8 tasks x 2 conditions x 1 rep | 32 |
| Main | 2 models x 16 tasks x 2 conditions x 3 reps | 192 |
| **Total** | | **224** |

Pre-registered extension: four repetitions gives 256 main runs, 288 total.

## 11. Scope boundaries

Not evaluated in this paper:

- browser and scratch-browser behavior;
- subagent delegation;
- web search and fetch;
- non-terminal tasks;
- general-purpose assistants;
- models other than the two flash models.

These are future work, not claims.

## 12. Open decisions

1. Task subset: confirm the 16-task list and replacement pool after the pilot.
2. Confirmatory venue and deadline, which sets the analysis freeze.
3. Model snapshot lock: confirm both LiteLLM aliases resolve to stable upstream
   versions for the run.
4. Harbor revision and dataset revision to pin.
