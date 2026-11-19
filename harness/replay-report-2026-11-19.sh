#!/usr/bin/env bash
# Replay the run matrix from analysis/harness-2026-11-19/report.pdf.
#
# Six arms and twelve capability scenarios, with the same prompts, modules and
# sandboxes as the first sweep. Every run writes its transcript, workspace,
# metrics and provenance under harness/runs/ as usual.
#
# Usage:
#   OPENCODE_API_KEY=... ./harness/replay-report-2026-11-19.sh [arms|scenarios|all]
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${OPENCODE_API_KEY:?set OPENCODE_API_KEY to a LiteLLM key}"
LITELLM_BASE_URL="${LITELLM_BASE_URL:-https://dashboard.agent.tcl-it.tech/v1}"
export OPENCODE_API_KEY LITELLM_BASE_URL
export OPENCODE_ENABLE_QUESTION_TOOL=false
export OPENCODE_PYTHON_SCRATCH=0
export OPENCODE_PYTHON_SANDBOX="${OPENCODE_PYTHON_SANDBOX:-bwrap}"

WHAT="${1:-all}"
OUT="$ROOT/harness/runs/replay-$(date +%Y%m%dT%H%M%S)"
mkdir -p "$OUT"
LOG="$OUT/matrix.log"
FAILED=()

log() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG"; }

arm() {
  log "arm $1"
  if "$ROOT/harness/arms.sh" "$1" >>"$LOG" 2>&1; then
    log "arm $1 done"
  else
    log "arm $1 FAILED"
    FAILED+=("arm $1")
  fi
}

scenario() {
  local name="$1" modules="$2" sandbox="$3" port="$4" background="$5" prompt="$6"
  log "scenario $name ($modules, $sandbox)"
  if OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS="$background" \
    "$ROOT/harness/scenarios.sh" "$name" "$modules" "$sandbox" "$port" "$prompt" >>"$LOG" 2>&1; then
    log "scenario $name done"
  else
    log "scenario $name FAILED"
    FAILED+=("scenario $name")
  fi
}

if [ "$WHAT" = all ] || [ "$WHAT" = arms ]; then
  for item in 0 A B C D U; do arm "$item"; done
fi

if [ "$WHAT" = all ] || [ "$WHAT" = scenarios ]; then
  B='Use only the python tool. Use browser.page() to open https://example.com, take a snapshot, read the title, take a screenshot to /tmp/browser-check.png, and return the title, snapshot, screenshot path, and screenshot MIME type. Do not use raw open, subprocess, or sockets.'
  T='Use only the python tool. Use browser.page() to open https://example.com, then call page.text() and page.get("title"), and return the first 200 characters of text plus the title.'
  J='Use only the python tool. In one Python program, use agent.jobs.start to run fs.read("README.md") and fs.glob("*") concurrently, collect each with job.result(), and return the read line count and file paths. Do not call the tools directly.'
  D='Use only the python tool. In one Python program, use agents.tasks.start("build", "Read README.md and report its first line in your final answer.", "read-readme") to launch a detached subagent, then return the job object. Do not wait for it. After the background task finishes, report the child result.'
  D2='Use only the python tool. In one Python program, import with `from agent import agents`, then use agents.tasks.start("build", "Read README.md and report its first line in your final answer.", "read-readme") to launch a detached subagent, and return the job object. Do not wait for it. After the background task finishes, report the child result.'
  C='Use only the python tool. In one Python program, from agent import agents and fs. Use agents.tasks.start("build", "Read README.md and report its first line in your final answer.", "read-readme") to launch a detached subagent. Also use agent.jobs.start to run fs.read("README.md") and fs.glob("*") concurrently. Return the detached job plus both job results. Do not wait for the detached task.'
  A='Use only the python tool. In one Python program, use shell.run to copy /opt/enuma/harness/runs/2026-11-18-vision-prometheus/screenshot.png to vision.png, then use fs.read("vision.png") and web.fetch("https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png"). Return both objects. Do not decode or print base64.'

  scenario browser_bwrap       browser            bwrap 4300 false "$B"
  scenario browser_none        browser            none  4301 false "$B"
  scenario browser_text_bwrap  browser            bwrap 4302 false "$T"
  scenario jobs_bwrap          fs                 bwrap 4303 false "$J"
  scenario jobs_none           fs                 none  4304 false "$J"
  scenario detached_bwrap      agents             bwrap 4305 true  "$D"
  scenario detached_none       agents             none  4306 true  "$D"
  scenario detached_none2      agents             none  4307 true  "$D2"
  scenario combo_bwrap         fs,agents          bwrap 4308 true  "$C"
  scenario combo_none          fs,agents          none  4309 true  "$C"
  scenario attachments_bwrap   fs,shell,web       bwrap 4310 false "$A"
  scenario attachments_none    fs,shell,web       none  4311 false "$A"
fi

log "matrix done: ${#FAILED[@]} failed"
for item in "${FAILED[@]:-}"; do [ -n "$item" ] && log "  failed: $item"; done
printf '%s\n' "$OUT"
[ ${#FAILED[@]} -eq 0 ]
