#!/usr/bin/env bash
# Runs inside manus-dei/base as the `ubuntu` user.
set -euo pipefail

sudo -n apt-get update -qq
sudo -n DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends bubblewrap >/dev/null

sudo -n mkdir -p /opt/manus/python/current/bin /opt/manus/python/current/lib
sudo -n ln -sf /usr/bin/python3 /opt/manus/python/current/bin/python3
sudo -n rm -rf /opt/manus/python/current/lib/agent
sudo -n cp -r /opt/enuma/agent /opt/manus/python/current/lib/agent
sudo -n cp /opt/enuma/runtime/sitecustomize.py /opt/manus/python/current/lib/sitecustomize.py
sudo -n chmod -R a+rX /opt/manus/python

sudo -n mkdir -p /home/ubuntu/workspace
sudo -n chown -R ubuntu:ubuntu /home/ubuntu/workspace

export OPENCODE_PYTHON_CODE_MODE=true
export OPENCODE_GOAL_REQUIRED=false
export OPENCODE_CONFIG_CONTENT='{
  "model": "litellm/prometheus",
  "provider": {
    "litellm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "LiteLLM",
      "options": {
        "baseURL": "{env:LITELLM_BASE_URL}",
        "apiKey": "{env:OPENCODE_API_KEY}"
      },
      "models": {
        "prometheus": {
          "name": "Prometheus",
          "limit": { "context": 1000000, "output": 384000 }
        }
      }
    }
  },
  "agent": {
    "python-experiment": {
      "mode": "primary",
      "model": "litellm/prometheus",
      "description": "Python code mode experiment",
      "toolset": ["python"],
      "python": { "modules": ["fs", "mutate", "shell", "web", "state"] }
    }
  }
}'

exec sudo -n -u ubuntu -H env \
  OPENCODE_PYTHON_CODE_MODE="$OPENCODE_PYTHON_CODE_MODE" \
  OPENCODE_GOAL_REQUIRED="$OPENCODE_GOAL_REQUIRED" \
  OPENCODE_CONFIG_CONTENT="$OPENCODE_CONFIG_CONTENT" \
  OPENCODE_API_KEY="${OPENCODE_API_KEY:-}" \
  LITELLM_BASE_URL="${LITELLM_BASE_URL:-}" \
  /bin/bash -c 'cd /home/ubuntu/workspace && exec /opt/opencode serve --hostname 0.0.0.0 --port 4096'
