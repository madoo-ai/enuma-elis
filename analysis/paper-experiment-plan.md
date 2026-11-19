# Paper experiment plan

Status: design frozen at the level of conditions, models, and target venue.
No confirmatory runs have been made against it yet.

Decisions already made:

- Target: a full empirical paper, not a workshop experience report.
- Models: `prometheus` (DeepSeek V4.1 Flash) and `hephaestus` (GLM 5.3 Flash),
  both through the LiteLLM aliases used by the harness.
- Scale: the full five-condition matrix with both models.
- The legacy SDK will be built so the prompt and SDK effects are separated.

Goal: a defensible empirical paper about Python code mode as a tool interface,
not just a system description. The paper needs repeated trials, ablations,
pre-registered outcomes, a task suite that is not the same to-do app used during
development, and at least two models.

## 1. Claims the paper can make

Candidate contributions:

1. A design for a typed Python tool interface over native agent tools, with
   capability-shaped modules, result types, and a sandbox.
2. A measurement harness that records programs, child calls, failures, audit
   events, artifacts, and claims under identical conditions.
3. An empirical comparison against native tool calling, with ablations for the
   prompt and the SDK ergonomics.
4. A failure and recovery taxonomy, including the ways models work around or
   misunderstand a typed surface.

The paper should not claim that "Python code mode is better" in general. It can
claim effects on the task suite, model, and sandbox profile it tests.

## 2. Research questions and hypotheses

| ID | Question | Hypothesis | Primary measure |
| --- | --- | --- | --- |
| RQ1 | Does code mode improve verified success on compositional tasks? | H1: full code mode beats native tools on tasks with loops, batching, or multi-step verification. | Verified success (0/1), partial credit |
| RQ2 | Does code mode add overhead on simple tasks? | H2: on single-step tasks, full code mode is no better and may cost more time or tokens. | Wall time, tokens, tool calls |
| RQ3 | How much comes from the prompt versus the SDK? | H3: an explicit method list reduces discovery probes and shape errors; H4: ergonomic results reduce recovery calls, independent of the prompt. | Probe programs, failed programs, recovery calls |
| RQ4 | Do sandbox restrictions change behavior or success? | H5: verified success holds on tasks that fit the profile; time and adaptation calls rise under read-only or offline profiles. | Success, time, denied calls, workarounds |
| RQ5 | Do browser helpers improve browser work? | H6: element handles, typed lists, `audit`, and `Screenshot.save` reduce browser failures and time against raw refs and string parsing. | Browser-task success, failed actions, stale-ref recoveries |
| RQ6 | Does code mode change honesty about verification? | H7: grounded errors and print output reduce unsupported claims; code mode is not worse than native tools. | Automated claim-artifact mismatches |
| RQ7 | Does the benefit grow with repetitive work? | H8: the code-mode advantage increases with the number of similar calls per task. | Interaction between condition and call-count |
| RQ8 | Do the effects reproduce across models? | H9: the condition ranking is stable across DeepSeek V4.1 Flash and GLM 5.3 Flash; a large condition-by-model interaction falsifies a generic claim. | Condition-by-model interaction |

Secondary questions:

- Does code mode change the number of programs, programs per task, or child
  calls per successful artifact?
- Which error kinds disappear, and which new ones appear?
- Does the model use concurrency and detached tasks when they are available?
- Does the scratch browser replace raw CDP or CLI workarounds?

## 3. Design

### 3.1 Conditions

Main comparison, 2 x 2 factorial plus a native baseline:

| Condition | Tool surface | Prompt | SDK |
| --- | --- | --- | --- |
| N | native tools | standard agent prompt | none |
| L-G | Python | generic ("use the SDK") | legacy |
| L-E | Python | explicit method list, units, examples | legacy |
| C-G | Python | generic | current |
| C-E | Python | explicit method list, units, examples | current |

`legacy` means the pre-ergonomics SDK: no dict access, no field suggestions, no
program-line traces, no print passthrough, no element handles, no typed browser
lists. It is the `agent/` package from fork commit `42873ed8a` and root commit
`6547099`, the last build before the prompt and result-ergonomics work.
`current` is the release under test.

Each condition runs on both models:

| Factor | Levels |
| --- | --- |
| Tool surface | native, Python |
| Prompt | generic, explicit |
| SDK | legacy, current |
| Model | prometheus (DeepSeek V4.1 Flash), hephaestus (GLM 5.3 Flash) |

This isolates:

- prompt main effect: L-G vs L-E, and C-G vs C-E;
- SDK main effect: L-G vs C-G, and L-E vs C-E;
- prompt-by-SDK interaction: whether the prompt only helps with the ergonomic
  SDK;
- bundle effect: C-E vs N;
- model replication: whether the condition contrasts have the same sign and
  comparable size on both models.

The legacy SDK build is part of the experiment, not a contingency. A bundle-only
comparison (N vs C-E) cannot support the prompt/SDK claims.

### 3.2 Sandbox and browser conditions

Keep one primary profile for the main matrix:

- `bwrap`, writable workspace, network on, raw exec blocked, raw net measured.
- One shared browser owned by the session, scratch browser enabled but only
  used by browser tasks.

Run a constraint study on a subset:

| Profile | Workspace | Network | Purpose |
| --- | --- | --- | --- |
| RW | writable | on | main |
| RO | read-only | on | adaptation to write refusal |
| OFF | writable | off | adaptation to network refusal |

Browser study, separate from the main matrix:

- shared page with element handles and helpers;
- shared page with raw refs and strings (legacy SDK);
- scratch browser for viewport, offline, request blocking, cookies, and storage.

### 3.3 Tasks

Twelve tasks, each with a public prompt and a hidden verifier. Do not use the
development to-do app. Build and freeze the suite before the confirmatory runs.

| ID | Category | Task | Why it is here | Verifier |
| --- | --- | --- | --- | --- |
| T1 | simple | Read a named file and report one value | Overhead check | Exact value |
| T2 | refactor | Rename an API across 8 files and update tests | Multi-file, exact edits | Hidden pytest |
| T3 | loop | Extract fields from 30 generated records into JSON | Repetitive calls | Schema + values |
| T4 | parallel | Fetch 6 local URLs and merge results | Concurrency | Order-independent JSON |
| T5 | browser | Fill, submit, reload, and verify a local app | Browser helpers | Browser assertions + storage |
| T6 | responsive | Measure layout at 360/768/1280 and report overflow | Scratch browser | Numeric tolerances |
| T7 | recovery | Handle a missing file and a denied write, then report both | Error honesty | Claim matches verifier and artifacts |
| T8 | sandbox | Produce a report under read-only/offline constraints | Adaptation | Artifact + claim checks |
| T9 | long-horizon | Build a small app, test it, and leave one artifact | End-to-end | Hidden tests + extra-file check |
| T10 | delegation | Have a child review a file and report one defect | Subagents | Child transcript + final claim |
| T11 | injection | Read a page/file with an instruction injection and ignore it | Safety | No forbidden action + report |
| T12 | ambiguity | A task with a missing required detail; do not invent it | Calibration | Clarification or explicit assumption |

Each task gets:

- a fixture with a fixed seed and content hash;
- an acceptance rubric with binary and partial-credit criteria;
- a hidden verifier run in a clean container;
- a list of forbidden shortcuts, for example network access on T8 or modifying
  verifier files;
- a time and token cap;
- one prompt version, hashed.

### 3.4 Repetitions and power

Pilot: 2 models x 2 tasks x 2 conditions x 3 repetitions = 24 runs, to
estimate variance, model behavior, and cost.

Main run: 2 models x 12 tasks x 5 conditions x 8 repetitions = 960 runs.

That is 192 observations per condition in total, and 96 per condition per
model. Task is a random effect; model is a fixed factor with two levels, so it
supports the planned condition-by-model interaction test without pretending two
models estimate a population variance. Do not reduce the main matrix below 8 repetitions per cell; if budget
forces a cut, remove a task before removing a repetition.

Additional runs:

- Constraint subset: 2 models x 3 conditions (N, C-E, C-G) x 3 tasks (T2, T4,
  T8) x 2 extra sandbox profiles (RO, OFF) x 5 repetitions = 180 runs.
- Scratch-browser subset: 2 models x 1 condition (C-E scratch) x 2 tasks (T5,
  T6) x 8 repetitions = 32 runs. The current shared-page and legacy shared-page
  cells already exist in the main matrix.
- Total: 1,172 runs before the pilot.

For binary success, fit a hierarchical model rather than a per-cell proportion.
Simulate power from the pilot using the observed task variance. Target 80% power
for a 15 percentage-point difference, or state the minimum detectable effect.

If the full matrix must be cut, remove tasks before repetitions. Task diversity
matters more than a ninth repetition of the same task.

### 3.5 Randomization and blocking

- Randomize condition order within each task and repetition.
- Block by day or model endpoint if provider drift is suspected.
- Use a fresh container, workspace, browser profile, and state directory per run.
- Pin each LiteLLM alias, record the provider-reported model and response ID,
  and block runs by model. Do not mix aliases within one repetition block.
- Disable the question and goal tools in every condition.
- Disable scratch browsing except for T6.
- Record prompt caching; include cache-read tokens as a covariate, not as
  evidence of efficiency.

## 4. Outcomes

### 4.1 Primary

- **Verified success:** 0/1 from the hidden verifier. This is the primary
  outcome. Partial credit is secondary.
- **Partial credit:** 0-100 from the rubric, fixed before runs.

### 4.2 Effort and reliability

- wall-clock seconds;
- input, output, reasoning, and cache-read tokens;
- cost, if the provider reports it;
- Python programs per task;
- child tool calls per successful artifact;
- failed programs and failed child calls;
- recovery: a failed program followed by a successful one in the same run;
- time to first correct artifact;
- output truncations.

### 4.3 Interface behavior

- discovery probes: `a.tools`, `dir`, `inspect`, SDK source reads;
- import errors, shape errors, attribute errors, timeouts;
- use of result keys, `.get`, aliases, and field suggestions;
- stale-ref recoveries and element-handle retries;
- concurrency use and overlap;
- detached-task launch and delivery latency;
- browser actions by kind: snapshot, locate, act, wait, read, screenshot;
- raw CDP, WebSocket, or `agent-browser` CLI workarounds.

### 4.4 Safety and honesty

- audited raw exec, raw open, raw net, with screenshot writes separated;
- permission denials and prompt-injection compliance;
- forbidden shortcut use;
- claim-artifact consistency: every claim that names a file, test result,
  screenshot, or browser action is checked against an artifact or verifier
  record; a mismatch is counted automatically.

### 4.5 Artifact hygiene

- diff size and files changed;
- extra or forbidden files;
- output format and file count;
- verifier pass rate per artifact.

## 5. Data collection

### 5.1 Run manifest

One JSON object per run:

```json
{
  "run_id": "T5-C-E-r03",
  "batch": "confirmatory-1",
  "condition": "C-E",
  "task_id": "T5",
  "repetition": 3,
  "order": 11,
  "model_alias": "prometheus",
  "model_reported": "DeepSeek V4.1 Flash",
  "model_family": "deepseek",
  "model_tier": "flash",
  "model_snapshot": "provider-reported",
  "temperature": 0.0,
  "max_tokens": 8192,
  "prompt_hash": "sha256:...",
  "prompt_variant": "explicit",
  "sdk_version": "0.1.0",
  "fork_sha": "...",
  "root_sha": "...",
  "image_digest": "sha256:...",
  "sandbox": "bwrap",
  "workspace": "rw",
  "network": true,
  "modules": ["fs", "mutate", "shell", "web", "state", "browser"],
  "scratch": false,
  "question_tool": false,
  "started_at": "2026-...",
  "duration_seconds": 0,
  "status": "completed",
  "exclusion_reason": null
}
```

### 5.2 Event log

One JSONL row per normalized event:

- `message` with role and token usage;
- `tool_call` with tool, input hash, result hash, status, duration;
- `python_program` with code hash, AST features, prints, trace, outcome;
- `child_call` with tool, status, duration;
- `audit` with kind and target;
- `claim` with text and its automated artifact check;
- `verifier` with test id and result.

Keep raw `transcript.jsonl` and `session.json`, but never analyze only the raw
shape. The normalized log is what the statistics use.

### 5.3 Program features

For each Python program, record:

- parses, has `Run`, AST depth, lines, characters;
- imports and canonical-import compliance;
- SDK calls and child calls;
- result shape and use of dict access;
- discovery probes;
- try/except and error branches;
- concurrency, detached tasks, browser actions;
- failure kind and trace frame;
- whether it was a probe, build, verification, or recovery program.

### 5.4 Artifacts and verifier output

- file paths, sizes, SHA256, and ownership;
- diff against the fixture;
- hidden verifier stdout/stderr and exit code;
- forbidden files or shortcuts;
- browser storage and console state for browser tasks;
- screenshot hashes and dimensions.

## 6. Controls and threats

### 6.1 Controlled

- model alias, provider, reported model, temperature, max tokens, and system
  prompt;
- task prompt bytes and hash;
- fixture content hash and seed;
- container image digest, runtime version, bwrap version;
- tool permissions, timeouts, and module list;
- question/goal disabled;
- no human intervention;
- randomized order;
- one fresh environment per run.

### 6.2 Threats and mitigations

| Threat | Mitigation |
| --- | --- |
| Model stochasticity | Repetitions, randomization, hierarchical models |
| Prompt leakage between tasks | Separate containers; no shared state; randomize order |
| Evaluator gaming | Hidden tests; behavior checks; no condition-specific verifier |
| Provider drift | Pin snapshot; record response IDs; block by day |
| Prompt caching | Record cache tokens; include as covariate; do not count as tool efficiency |
| Timeouts and rate limits | Pre-registered exclusion rules; retry only infrastructure failures |
| Browser state | Fresh profile; local fixture server; no human browser |
| Task depth choice | Acceptance criteria and artifact limits; measure extra work separately |
| Development-task overfitting | Build a new suite; do not tune on confirmatory tasks |
| Export truncation | Export inside the container and copy; verify JSON parses before analysis |
| Missing bwrap/package drift | Pin image, install from recorded debs, preflight every batch |
| Raw-open accounting | Report screenshot saves separately from other raw opens |

## 7. Observed quirks to encode

These come from the development corpus and the replay. Each should become a
measurement, a control, or a hypothesis test, not an anecdote.

| Quirk | Evidence | Treatment |
| --- | --- | --- |
| Surface discovery | 31 probe programs before the explicit prompt; 0 after | Measure probe rate; H3 |
| Shape errors | Old `GlobResult` iteration, `Text.total_lines`, `Screenshot` subscripting | Error taxonomy; H4 |
| Inverse state guess | `page.is_("disabled")` failed in U | Fixed; test as an interface case |
| Node versus element | `find_all(...)[0].check()` failed in U | Fixed; test as an interface case |
| Import guess | `from agent import agent` failed in one probe | Fixed; test import paths |
| Tab selection | `tab select` was not a command | Fixed; regression test |
| Text wait timeout | `wait_text("Example Domain")` timed out twice | Measure wait failures; fixed helper |
| Raw CDP workaround | Old U wrote node scripts over WebSocket | Count raw CDP/CLI workarounds; H6 |
| Screenshot writes | Six raw opens, all `Screenshot.save` | Separate counter |
| Detached delivery | `detached_none2` took 55 s waiting for notification | Measure delivery latency, not as a stall |
| Empty final text | `combo_none` had no final text | Treat missing final as missing data, not failure |
| Browser depth | U made 68 browser actions and 276 s | Rubric must bound depth; measure overwork |
| Export truncation | Two arm exports cut mid-base64 | Export inside container; validate before analysis |
| Missing bwrap | Image lost bubblewrap; apt lists empty | Pin install path; preflight |
| Goal authorship | Native arm stalled once on goal authorization | Disable question/goal in every condition |
| Script without `Run` | Several scripts ran as top-level code | Loader behavior is part of the SDK; record it |

## 8. Analysis plan

### 8.1 Primary model

Fit a Bayesian hierarchical logistic regression:

```text
success ~ condition * task_complexity * model
          + (1 | task) + (1 | task:condition)
```

with weakly informative priors. Report posterior means, 95% credible intervals,
and marginal success probabilities per condition. Use PSIS-LOO for model checks.

If the factorial is unavailable, use `condition` as a four-level factor and
report planned contrasts, not all pairwise comparisons.

### 8.2 Secondary models

- counts: negative binomial or Poisson with overdispersion, offset by task;
- duration: log-normal or Gamma;
- tokens and cost: log-normal, with cache-read tokens as a covariate;
- claim mismatches: binary logistic model;
- error kinds: multinomial or per-kind logistic models.

Use Holm correction within each family of secondary outcomes. Report effect
sizes, not only p-values.

### 8.3 Equivalence for simple tasks

For H2, do not test "no difference" with a non-significant p-value. Use a
region of practical equivalence (ROPE) or TOST with a pre-declared margin, for
example 10% of native time or tokens.

### 8.4 Failure taxonomy

A rule-based classifier labels every failed program with a codebook derived
from the observed quirks. Ambiguous cases are inspected by one author against a
fixed decision table, with the rule and the manual decision recorded. Report
counts and rates per condition. Separate:

- interface errors (import, shape, attribute, command);
- capability errors (missing tool, permission, timeout);
- model errors (wrong plan, invented file, unsupported claim);
- infrastructure errors (container, export, provider).

### 8.5 Qualitative analysis

- One worked trace per condition and task family, chosen by a fixed rule.
- A table of workarounds: raw CDP, CLI, shell, direct file writes.
- A table of recovery strategies: retry, probe, switch tool, narrow scope.
- Quote only redacted, non-identifying text.

## 9. Execution plan

| Phase | Work | Output |
| --- | --- | --- |
| 0 | Freeze claims, task suite, rubric, exclusions; write pre-registration | `paper/prereg.md`, task hashes |
| 1 | Build condition flags and legacy SDK snapshot; add manifest fields; build verifiers | Reproducible condition matrix |
| 2 | Pilot 2 tasks x 2 conditions x 3 reps; estimate variance and cost | Power simulation, revised repetition count |
| 3 | Run confirmatory matrix; validate every export and verifier | Raw corpus, run manifests |
| 4 | Normalize events and programs; run automated checks | Analysis tables |
| 5 | Automated claim and artifact audit | Mismatch table |
| 6 | Fit models, sensitivity checks, write paper | Draft, artifact, replication script |

Target run: 1,172 runs, as specified in Section 3.4. The main matrix is 960
runs; the constraint and scratch subsets add 212.

Abort or revise the design only if the pilot shows that the verifiers cannot
separate conditions, that one model cannot complete the suite, or that the
provider cannot sustain the run budget. Do not silently reduce repetitions
after seeing the main results.

## 10. Artifacts and reproducibility

- Public repository with the harness, SDK, task suite, verifiers, and scripts.
- Frozen task prompts and fixtures by hash.
- Run manifests, normalized event logs, and aggregate tables.
- A `reproduce.sh` that runs the pilot, the matrix, and the analysis.
- A data dictionary for every field in the run manifest and event log.
- A statement of what is excluded and why.
- No API keys, credentials, or human browser state in the artifact.

## 11. Open decisions

Resolved:

1. Venue: full empirical paper.
2. Models: prometheus (DeepSeek V4.1 Flash) and hephaestus (GLM 5.3 Flash).
3. Scale: full five-condition matrix on both models.
4. Legacy SDK: build it for the 2 x 2 prompt-by-SDK design.

Still open:

1. Task suite: keep all twelve, or replace one browser-heavy task if the paper's
   scope is narrowed.
2. Confirmatory venue and deadline, which sets the final analysis freeze.
3. Model snapshot lock: confirm that both LiteLLM aliases resolve to stable
   upstream versions for the duration of the run.
