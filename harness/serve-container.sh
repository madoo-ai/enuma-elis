#!/usr/bin/env bash
# Runs inside manus-dei/base as the `ubuntu` user.
set -euo pipefail

sudo -n timeout 90 apt-get update -qq || echo "apt-get update failed; using cached lists" >&2
command -v bwrap >/dev/null || sudo -n DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends bubblewrap >/dev/null \
  || echo "bubblewrap is not installed; only OPENCODE_PYTHON_SANDBOX=none will work" >&2

sudo -n mkdir -p /opt/manus/python/current/bin /opt/manus/python/current/lib
sudo -n ln -sf /usr/bin/python3 /opt/manus/python/current/bin/python3
sudo -n rm -rf /opt/manus/python/current/lib/agent
sudo -n cp -r /opt/enuma/agent /opt/manus/python/current/lib/agent
sudo -n cp /opt/enuma/runtime/sitecustomize.py /opt/manus/python/current/lib/sitecustomize.py
sudo -n chmod -R a+rX /opt/manus/python

sudo -n mkdir -p /home/ubuntu/workspace
sudo -n chown -R ubuntu:ubuntu /home/ubuntu/workspace

export OPENCODE_PYTHON_CODE_MODE="${OPENCODE_PYTHON_CODE_MODE:-true}"
export OPENCODE_GOAL_REQUIRED="${MANUS_GOAL_REQUIRED:-false}"
export MODULES="${PYTHON_MODULES:-fs,mutate,shell,web,state,agents,browser}"
export OPENCODE_CONFIG_CONTENT="$(python3 - <<'PY'
import json
import os

modules = [item for item in os.environ["MODULES"].split(",") if item]
prompt = """You are an autonomous engineer in a sandboxed workspace. You have exactly one tool: python.

Every program must define Run(ctx, a). Call the SDK inside Run, never at module scope. a.tools lists the enabled methods; imported modules may exist for disabled methods, and `unavailable` means not enabled.

Use the SDK modules for file, process, and network work. Do not use raw open(), subprocess, os.system, or sockets to replace a typed tool. For independent calls, agent.jobs.start(fn, ...) runs them concurrently; await each job.result() before Run returns. Each program gets a fresh /tmp; use the workspace for persistent state.

Verify before you claim. If a capability is unavailable, say what you could not check. Leave only the requested artifact; put test files in /tmp.

The browser is the session's one shared Chromium. Use browser.page(), take a snapshot before acting, and use @refs. It has no launch, connect, close, or tab-close call; the human can see and drive the same page."""
config = {
    "model": "litellm/prometheus",
    "provider": {
        "litellm": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "LiteLLM",
            "options": {
                "baseURL": "{env:LITELLM_BASE_URL}",
                "apiKey": "{env:OPENCODE_API_KEY}",
            },
            "models": {
                "prometheus": {
                    "name": "Prometheus",
                    "attachment": True,
                    "reasoning": True,
                    "tool_call": True,
                    "modalities": {"input": ["text", "image"], "output": ["text"]},
                    "limit": {"context": 1_000_000, "output": 384_000},
                }
            },
        }
    },
    "agent": {
        "python-experiment": {
            "mode": "primary",
            "model": "litellm/prometheus",
            "description": "Python code mode experiment",
            "prompt": prompt,
            "toolset": ["python"],
            "python": {"modules": modules},
        }
    },
}
print(json.dumps(config))
PY
)"

exec sudo -n -u ubuntu -H env \
  OPENCODE_PYTHON_CODE_MODE="$OPENCODE_PYTHON_CODE_MODE" \
  OPENCODE_GOAL_REQUIRED="$OPENCODE_GOAL_REQUIRED" \
  OPENCODE_ENABLE_QUESTION_TOOL="${OPENCODE_ENABLE_QUESTION_TOOL:-false}" \
  OPENCODE_CONFIG_CONTENT="$OPENCODE_CONFIG_CONTENT" \
  OPENCODE_API_KEY="${OPENCODE_API_KEY:-}" \
  LITELLM_BASE_URL="${LITELLM_BASE_URL:-}" \
  OPENCODE_PYTHON_NETWORK="${OPENCODE_PYTHON_NETWORK:-true}" \
  OPENCODE_PYTHON_WORKSPACE="${OPENCODE_PYTHON_WORKSPACE:-rw}" \
  OPENCODE_PYTHON_BLOCK_RAW_EXEC="${OPENCODE_PYTHON_BLOCK_RAW_EXEC:-0}" \
  OPENCODE_PYTHON_SANDBOX="${OPENCODE_PYTHON_SANDBOX:-bwrap}" \
  OPENCODE_PYTHON_SCRATCH="${OPENCODE_PYTHON_SCRATCH:-0}" \
  OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS="${OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS:-false}" \
  /bin/bash -c 'cd /home/ubuntu/workspace && exec /opt/opencode serve --hostname 0.0.0.0 --port 4096'
